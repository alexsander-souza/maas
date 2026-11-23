# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


import random
from unittest.mock import sentinel

from django.core.handlers.wsgi import WSGIHandler
import pytest
from twisted.internet import reactor
from twisted.internet.endpoints import TCP4ServerEndpoint
from twisted.web.error import UnsupportedMethod
from twisted.web.resource import NoResource, Resource
from twisted.web.server import Site
from twisted.web.test.requesthelper import DummyChannel, DummyRequest

from maasserver import eventloop, webapp
from maasserver.testing.listener import FakePostgresListenerService
from maasserver.webapp import OverlaySite
from maasserver.websockets.protocol import WebSocketFactory
from maastesting.factory import factory
from provisioningserver.utils.twisted import reducedWebLogFormatter


class TestCleanPathRequest:
    def test_requestReceived_converts_extra_slashes_to_single(self, mocker):
        mock_super_requestReceived = mocker.patch.object(
            webapp.Request, "requestReceived"
        )
        request = webapp.CleanPathRequest(DummyChannel(), sentinel.queued)
        path_pieces = [
            factory.make_name("path").encode("utf-8") for _ in range(3)
        ]
        double_path = (b"/" * random.randint(2, 8)).join(path_pieces)
        single_path = b"/".join(path_pieces)
        request.requestReceived(
            sentinel.command, double_path, sentinel.version
        )
        mock_super_requestReceived.assert_called_once_with(
            sentinel.command, single_path, sentinel.version
        )

    def test_requestReceived_converts_extra_slashes_ignores_args(self, mocker):
        mock_super_requestReceived = mocker.patch.object(
            webapp.Request, "requestReceived"
        )
        request = webapp.CleanPathRequest(DummyChannel(), sentinel.queued)
        path_pieces = [
            factory.make_name("path").encode("utf-8") for _ in range(3)
        ]
        args = b"?op=extra//data"
        double_path = (b"/" * random.randint(2, 8)).join(path_pieces) + args
        single_path = b"/".join(path_pieces) + args
        request.requestReceived(
            sentinel.command, double_path, sentinel.version
        )
        mock_super_requestReceived.assert_called_once_with(
            sentinel.command, single_path, sentinel.version
        )


class TestOverlaySite:
    def test_init__(self):
        root = Resource()
        site = OverlaySite(root)
        assert isinstance(site, Site)

    def test_getResourceFor_returns_no_resource_wo_underlay(self):
        root = Resource()
        site = OverlaySite(root)
        request = DummyRequest([b"MAAS"])
        resource = site.getResourceFor(request)
        assert isinstance(resource, NoResource)

    def test_getResourceFor_wraps_render_wo_underlay(self, mocker):
        root = Resource()
        maas = Resource()
        mock_render = mocker.patch.object(maas, "render")
        root.putChild(b"MAAS", maas)
        site = OverlaySite(root)
        request = DummyRequest([b"MAAS"])
        resource = site.getResourceFor(request)
        assert resource is maas
        assert resource.render is not mock_render
        resource.render(request)
        mock_render.assert_called_once_with(request)

    def test_getResourceFor_wraps_render_wo_underlay_raises_no_method(self):
        root = Resource()
        maas = Resource()
        root.putChild(b"MAAS", maas)
        site = OverlaySite(root)
        request = DummyRequest([b"MAAS"])
        resource = site.getResourceFor(request)
        assert resource is maas
        with pytest.raises(UnsupportedMethod):
            resource.render(request)

    def test_getResourceFor_returns_resource_from_underlay(self):
        underlay_root = Resource()
        underlay_maas = Resource()
        underlay_root.putChild(b"MAAS", underlay_maas)
        overlay_root = Resource()
        site = OverlaySite(overlay_root)
        site.underlay = Site(underlay_root)
        request = DummyRequest([b"MAAS"])
        resource = site.getResourceFor(request)
        assert resource is underlay_maas

    def test_getResourceFor_calls_render_on_underlay_when_no_method(
        self, mocker
    ):
        underlay_root = Resource()
        underlay_maas = Resource()
        mock_underlay_maas_render = mocker.patch.object(
            underlay_maas, "render"
        )
        underlay_root.putChild(b"MAAS", underlay_maas)
        overlay_root = Resource()
        overlay_maas = Resource()
        overlay_root.putChild(b"MAAS", overlay_maas)
        site = OverlaySite(overlay_root)
        site.underlay = Site(underlay_root)
        request = DummyRequest([b"MAAS"])
        resource = site.getResourceFor(request)
        resource.render(request)
        mock_underlay_maas_render.assert_called_once_with(request)

    def test_getResourceFor_doesnt_wrapper_render_if_already_wrapped(
        self, mocker
    ):
        underlay_root = Resource()
        overlay_root = Resource()
        overlay_maas = Resource()
        mock_render = mocker.patch.object(overlay_maas, "render")
        mock_render.__overlay_wrapped__ = True
        overlay_root.putChild(b"MAAS", overlay_maas)
        site = OverlaySite(overlay_root)
        site.underlay = Site(underlay_root)
        request = DummyRequest([b"MAAS"])
        resource = site.getResourceFor(request)
        assert mock_render is resource.render

    def test_getResourceFor_does_wrapper_render_not_wrapped(self):
        underlay_root = Resource()
        overlay_root = Resource()
        overlay_maas = Resource()
        original_render = overlay_maas.render
        overlay_root.putChild(b"MAAS", overlay_maas)
        site = OverlaySite(overlay_root)
        site.underlay = Site(underlay_root)
        request = DummyRequest([b"MAAS"])
        resource = site.getResourceFor(request)
        assert original_render is not resource.render


class TestResourceOverlay:
    def make_resourceoverlay(self):
        return webapp.ResourceOverlay(Resource())

    def test_init__(self):
        resource = self.make_resourceoverlay()
        assert isinstance(resource, Resource)

    def test_getChild(self):
        resource = self.make_resourceoverlay()
        assert isinstance(resource, webapp.ResourceOverlay)
        assert isinstance(resource.basis, Resource)


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestWebApplicationService:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        # Patch the getServiceNamed so the WebSocketFactory does not
        # error trying to register for events from the RPC service. In this
        # test the RPC service is not started.
        mocker.patch.object(eventloop.services, "getServiceNamed")

    def make_webapp(self, mocker):
        listener = FakePostgresListenerService()
        service = webapp.WebApplicationService(
            listener, sentinel.status_worker
        )
        mock_makeEndpoint = mocker.patch.object(service, "_makeEndpoint")
        mock_makeEndpoint.return_value = TCP4ServerEndpoint(
            reactor, 0, interface="localhost"
        )
        return service

    def test_init_creates_site(self, mocker):
        service = self.make_webapp(mocker)
        assert isinstance(service.site, Site)
        assert service.site.requestFactory is webapp.CleanPathRequest
        assert service.site._logFormatter is reducedWebLogFormatter
        assert service.site.timeOut is None
        assert isinstance(service.websocket, WebSocketFactory)

    def test_start_and_stop_the_service(self, mocker):
        service = self.make_webapp(mocker)
        # Both privileged and and normal start must be called, as twisted
        # multi-service will do the same.
        service.privilegedStartService()
        assert service.starting
        service.startService()
        assert service.running
        service.stopService()
        assert not service.running
        assert not service.starting

    def test_successful_start_installs_wsgi_resource(self, mocker, request):
        service = self.make_webapp(mocker)
        request.addfinalizer(service.stopService)

        # Both privileged and and normal start must be called, as twisted
        # multi-service will do the same.
        service.privilegedStartService()
        service.startService()

        # Overlay
        site = service.site
        assert isinstance(site, OverlaySite)
        resource = service.site.resource
        assert isinstance(resource, Resource)
        overlay_resource = resource.getChildWithDefault(b"MAAS", request=None)
        assert isinstance(overlay_resource, Resource)

        # Underlay
        site = service.site.underlay
        assert isinstance(site, Site)
        underlay_resource = site.resource
        assert isinstance(underlay_resource, Resource)
        underlay_maas_resource = underlay_resource.getChildWithDefault(
            b"MAAS", request=None
        )
        assert isinstance(underlay_maas_resource, webapp.ResourceOverlay)
        assert underlay_maas_resource.basis._reactor is reactor
        assert underlay_maas_resource.basis._threadpool is service.threadpool
        assert isinstance(
            underlay_maas_resource.basis._application, WSGIHandler
        )
