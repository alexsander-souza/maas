# Copyright 2018-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


import os
from pathlib import Path
import random
from unittest.mock import ANY, Mock

import attr
import pytest
from tftp.errors import AccessViolation, FileNotFound
from twisted.application.service import Service
from twisted.internet import defer, reactor
from twisted.internet.defer import fail, inlineCallbacks, succeed
from twisted.web.http_headers import Headers
from twisted.web.server import NOT_DONE_YET, Request
from twisted.web.test.test_web import DummyChannel, DummyRequest

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.factory import factory
from maastesting.fixtures import MAASRootFixture
from maastesting.twisted import always_succeed_with, TwistedLoggerFixture
from provisioningserver import services
from provisioningserver.boot import BytesReader
from provisioningserver.events import EVENT_TYPES
from provisioningserver.rackdservices import http
from provisioningserver.rpc import clusterservice, common, exceptions
from provisioningserver.rpc.testing import MockLiveClusterToRegionRPCFixture

TIMEOUT = get_testing_timeout()


@wait_for(timeout=TIMEOUT)
@inlineCallbacks
def _cleanup_rpc_fixture(fixture, shutdown):
    try:
        yield shutdown()
    finally:
        yield fixture.cleanUp()


@inlineCallbacks
def prepareRegion(request):
    """Set up a mock region controller."""
    fixture = MockLiveClusterToRegionRPCFixture()
    shutdown = [lambda: defer.succeed(None)]
    request.addfinalizer(lambda: _cleanup_rpc_fixture(fixture, shutdown[0]))
    yield fixture.setUp()
    protocol, connecting = fixture.makeEventLoop()
    protocol.RegisterRackController.side_effect = always_succeed_with(
        {"system_id": factory.make_name("maas-id")}
    )
    shutdown[0] = yield connecting
    return services.getServiceNamed("rpc"), protocol


@attr.s
class StubClusterClientService:
    """A stub `ClusterClientService` service that's never connected."""

    def getClientNow(self):
        raise exceptions.NoConnectionsAvailable()


@pytest.mark.rack_reactor_guard
class TestRackHTTPService:
    """Tests for `RackHTTPService`."""

    @pytest.fixture(autouse=True)
    def _set_up(self, tmp_path, mocker):
        self.tmp_path = tmp_path
        self.mocker = mocker
        mocker.patch.object(
            clusterservice, "get_all_interfaces_definition", return_value={}
        )

    def make_dir(self):
        path = self.tmp_path / factory.make_name("directory")
        path.mkdir()
        return str(path)

    def test_service_uses__tryUpdate_as_periodic_function(self):
        service = http.RackHTTPService(
            self.make_dir(), StubClusterClientService(), reactor
        )
        assert service.call == (service._tryUpdate, (), {})

    def test_service_iterates_on_low_interval(self):
        service = http.RackHTTPService(
            self.make_dir(), StubClusterClientService(), reactor
        )
        assert service.step == service.INTERVAL_LOW

    def extract_regions(self, rpc_service):
        return frozenset(
            {
                client.address[0]
                for _, client in rpc_service.connections.items()
            }
        )

    def make_startable_RackHTTPService(self, *args, **kwargs):
        service = http.RackHTTPService(*args, **kwargs)
        service._orig_tryUpdate = service._tryUpdate
        self.mocker.patch.object(
            service, "_tryUpdate", return_value=always_succeed_with(None)
        )
        service.call = (service._tryUpdate, tuple(), {})
        return service

    def test_configure(self):
        self.mocker.patch.dict(os.environ, {"SNAP": "/snap/maas/123"})
        tempdir = self.make_dir()
        nginx_conf = Path(tempdir) / "rackd.nginx.conf"
        service = self.make_startable_RackHTTPService(tempdir, None, reactor)
        self.mocker.patch.object(
            http, "compose_http_config_path", return_value=str(nginx_conf)
        )
        service._configure(["region1.maas", "region2.maas"])
        assert "root /snap/maas/123/usr/share/maas;" in nginx_conf.read_text()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_getConfiguration_returns_configuration_object(self, request):
        rpc_service, _ = yield prepareRegion(request)
        region_ips = self.extract_regions(rpc_service)
        service = self.make_startable_RackHTTPService(
            self.make_dir(), rpc_service, reactor
        )
        yield service.startService()
        try:
            observed = yield service._getConfiguration()
        finally:
            yield service.stopService()
        assert isinstance(observed, http._Configuration)
        assert observed.upstream_http == region_ips

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_tryUpdate_writes_nginx_config_reloads_nginx(self, request):
        with MAASRootFixture():
            rpc_service, _ = yield prepareRegion(request)
            region_ips = self.extract_regions(rpc_service)
            service = self.make_startable_RackHTTPService(
                self.make_dir() + "/", rpc_service, reactor
            )
            mock_reloadService = self.mocker.patch.object(
                http.service_monitor,
                "reloadService",
                return_value=always_succeed_with(None),
            )
            yield service.startService()
            try:
                yield service._orig_tryUpdate()
                target_path = http.compose_http_config_path("rackd.nginx.conf")
                with open(target_path, "r") as fh:
                    contents = fh.read()
                for region_ip in region_ips:
                    assert f"server {region_ip}:5240;" in contents
                assert "proxy_pass http://maas-regions/MAAS/;" in contents
                mock_reloadService.assert_called_once_with("http")
                yield service._orig_tryUpdate()
                mock_reloadService.assert_called_once_with("http")
            finally:
                yield service.stopService()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_getConfiguration_updates_interval_to_high(self, request):
        rpc_service, _ = yield prepareRegion(request)
        service = http.RackHTTPService(self.make_dir(), rpc_service, reactor)
        yield service.startService()
        try:
            yield service._getConfiguration()
        finally:
            yield service.stopService()
        assert service.step == service.INTERVAL_HIGH
        assert service._loop.interval == service.INTERVAL_HIGH

    def test_genRegionIps_groups_by_region(self):
        mock_rpc = Mock()
        mock_rpc.connections = {}
        for _ in range(3):
            region_name = factory.make_name("region")
            for _ in range(3):
                pid = random.randint(0, 10000)
                eventloop = f"{region_name}:pid={pid}"
                ip = factory.make_ip_address()
                mock_conn = Mock()
                mock_conn.address = (ip, random.randint(5240, 5250))
                mock_rpc.connections[eventloop] = mock_conn

        service = http.RackHTTPService(self.make_dir(), mock_rpc, reactor)
        region_ips = list(service._genRegionIps())
        assert len(region_ips) == 3

    def test_genRegionIps_always_returns_same_result(self):
        mock_rpc = Mock()
        mock_rpc.connections = {}
        for _ in range(3):
            region_name = factory.make_name("region")
            for _ in range(3):
                pid = random.randint(0, 10000)
                eventloop = f"{region_name}:pid={pid}"
                ip = factory.make_ip_address()
                mock_conn = Mock()
                mock_conn.address = (ip, random.randint(5240, 5250))
                mock_rpc.connections[eventloop] = mock_conn

        service = http.RackHTTPService(self.make_dir(), mock_rpc, reactor)
        region_ips = frozenset(service._genRegionIps())
        for _ in range(3):
            assert region_ips == frozenset(service._genRegionIps())

    def test_genRegionIps_formats_ipv6(self):
        mock_rpc = Mock()
        mock_rpc.connections = {}
        ip_addresses = set()
        for _ in range(3):
            region_name = factory.make_name("region")
            pid = random.randint(0, 10000)
            eventloop = f"{region_name}:pid={pid}"
            ip = factory.make_ipv6_address()
            ip_addresses.add("[%s]" % ip)
            mock_conn = Mock()
            mock_conn.address = (ip, random.randint(5240, 5250))
            mock_rpc.connections[eventloop] = mock_conn

        service = http.RackHTTPService(self.make_dir(), mock_rpc, reactor)
        region_ips = set(service._genRegionIps())
        assert ip_addresses == region_ips


@pytest.mark.rack_reactor_guard
class TestRackHTTPService_Errors:
    """Tests for error handing in `RackHTTPService`."""

    @pytest.fixture(autouse=True)
    def _set_up(self, tmp_path, mocker):
        self.tmp_path = tmp_path
        self.mocker = mocker
        mocker.patch.object(
            clusterservice, "get_all_interfaces_definition", return_value={}
        )

    def make_dir(self):
        path = self.tmp_path / factory.make_name("directory")
        path.mkdir()
        return str(path)

    def make_startable_RackHTTPService(self, *args, **kwargs):
        service = http.RackHTTPService(*args, **kwargs)
        service._orig_tryUpdate = service._tryUpdate
        self.mocker.patch.object(
            service, "_tryUpdate", return_value=always_succeed_with(None)
        )
        service.call = (service._tryUpdate, tuple(), {})
        return service

    @pytest.mark.parametrize(
        "method",
        [
            "_getConfiguration",
            "_configurationApplied",
            "_maybeApplyConfiguration",
            "_applyConfiguration",
        ],
        ids=[
            "_getConfiguration",
            "_configurationApplied",
            "_maybeApplyConfiguration",
            "_applyConfiguration",
        ],
    )
    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_tryUpdate_logs_errors_from_broken_method(self, method, request):
        self.mocker.patch.object(common.log, "debug")
        self.mocker.patch.object(
            http.service_monitor,
            "reloadService",
            return_value=always_succeed_with(None),
        )
        rpc_service, _ = yield prepareRegion(request)
        service = self.make_startable_RackHTTPService(
            self.make_dir(), rpc_service, reactor
        )
        self.mocker.patch.object(service, "_configure", autospec=True)
        broken_method = self.mocker.patch.object(
            service, method, autospec=True
        )
        broken_method.side_effect = factory.make_exception()

        with MAASRootFixture(), TwistedLoggerFixture() as logger:
            yield service.startService()
            try:
                yield service._orig_tryUpdate()
            finally:
                yield service.stopService()

        assert "Failed to update HTTP configuration." in logger.messages


class TestHTTPLogResource:
    def test_render_GET_logs_node_event_with_original_path_ip(self, mocker):
        path = factory.make_name("path")
        ip = factory.make_ip_address()
        request = Request(DummyChannel(), False)
        request.requestHeaders = Headers(
            {"X-Original-URI": [path], "X-Original-Remote-IP": [ip]}
        )

        log_info = mocker.patch.object(http.log, "info")
        mock_deferLater = mocker.patch.object(http, "deferLater")
        mock_deferLater.side_effect = always_succeed_with(None)

        resource = http.HTTPLogResource()
        resource.render_GET(request)

        log_info.assert_called_once_with(
            "{path} requested by {remote_host}", path=path, remote_host=ip
        )
        mock_deferLater.assert_called_once_with(
            ANY,
            0,
            http.send_node_event_ip_address,
            event_type=EVENT_TYPES.NODE_HTTP_REQUEST,
            ip_address=ip,
            description=path,
        )

    def test_render_GET_logs_node_event_status_message(self, mocker):
        path = factory.make_name("squashfs")
        ip = factory.make_ip_address()
        request = Request(DummyChannel(), False)
        request.requestHeaders = Headers(
            {"X-Original-URI": [path], "X-Original-Remote-IP": [ip]}
        )

        mock_deferLater = mocker.patch.object(http, "deferLater")
        mock_deferLater.side_effect = always_succeed_with(None)
        mock_send_node_event_ip_address = mocker.patch.object(
            http, "send_node_event_ip_address"
        )

        resource = http.HTTPLogResource()
        resource.render_GET(request)

        mock_deferLater.assert_called_once_with(
            ANY,
            0,
            http.send_node_event_ip_address,
            event_type=EVENT_TYPES.NODE_HTTP_REQUEST,
            ip_address=ip,
            description=path,
        )
        mock_send_node_event_ip_address.assert_called_once_with(
            event_type=EVENT_TYPES.LOADING_EPHEMERAL, ip_address=ip
        )


@pytest.mark.rack_reactor_guard
class TestHTTPBootResource:
    @pytest.fixture(autouse=True)
    def _set_up(self, request, mocker):
        self.mocker = mocker
        self.tftp = Service()
        self.tftp.setName("tftp")
        self.tftp.backend = Mock()
        self.tftp.backend.get_reader = Mock()
        self.tftp.setServiceParent(services)
        request.addfinalizer(self._tear_down)

    def _tear_down(self):
        if self.tftp:
            self.tftp.disownServiceParent()
            self.tftp = None

    def render_GET(self, resource, request):
        result = resource.render_GET(request)
        if isinstance(result, bytes):
            request.write(result)
            request.finish()
            return succeed(None)
        elif result is NOT_DONE_YET:
            if request.finished:
                return succeed(None)
            else:
                return request.notifyFinish()
        else:
            raise ValueError(f"Unexpected return value: {result!r}")

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_render_GET_503_when_no_tftp_service(self):
        # Remove the fake 'tftp' service.
        self.tftp.disownServiceParent()
        self.tftp = None

        path = factory.make_name("path")
        ip = factory.make_ip_address()
        request = DummyRequest([path.encode("utf-8")])
        request.requestHeaders = Headers(
            {
                "X-Server-Addr": ["192.168.1.1"],
                "X-Server-Port": ["5248"],
                "X-Forwarded-For": [ip],
                "X-Forwarded-Port": ["%s" % factory.pick_port()],
            }
        )

        self.mocker.patch.object(http.log, "info")
        mock_deferLater = self.mocker.patch.object(http, "deferLater")
        mock_deferLater.side_effect = always_succeed_with(None)

        resource = http.HTTPBootResource()
        yield self.render_GET(resource, request)

        assert request.responseCode == 503
        assert b"HTTP boot service not ready." == b"".join(request.written)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_render_GET_400_when_no_local_addr(self):
        path = factory.make_name("path")
        ip = factory.make_ip_address()
        request = DummyRequest([path.encode("utf-8")])
        request.requestHeaders = Headers(
            {
                "X-Forwarded-For": [ip],
                "X-Forwarded-Port": ["%s" % factory.pick_port()],
            }
        )

        self.mocker.patch.object(http.log, "info")
        mock_deferLater = self.mocker.patch.object(http, "deferLater")
        mock_deferLater.side_effect = always_succeed_with(None)

        resource = http.HTTPBootResource()
        yield self.render_GET(resource, request)

        assert request.responseCode == 400
        assert (
            b"Missing X-Server-Addr and X-Forwarded-For HTTP headers."
            == b"".join(request.written)
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_render_GET_400_when_no_remote_addr(self):
        path = factory.make_name("path")
        request = DummyRequest([path.encode("utf-8")])
        request.requestHeaders = Headers(
            {"X-Server-Addr": ["192.168.1.1"], "X-Server-Port": ["5248"]}
        )

        self.mocker.patch.object(http.log, "info")
        mock_deferLater = self.mocker.patch.object(http, "deferLater")
        mock_deferLater.side_effect = always_succeed_with(None)

        resource = http.HTTPBootResource()
        yield self.render_GET(resource, request)

        assert request.responseCode == 400
        assert (
            b"Missing X-Server-Addr and X-Forwarded-For HTTP headers."
            == b"".join(request.written)
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_render_GET_403_access_violation(self):
        path = factory.make_name("path")
        ip = factory.make_ip_address()
        request = DummyRequest([path.encode("utf-8")])
        request.requestHeaders = Headers(
            {
                "X-Server-Addr": ["192.168.1.1"],
                "X-Server-Port": ["5248"],
                "X-Forwarded-For": [ip],
                "X-Forwarded-Port": ["%s" % factory.pick_port()],
            }
        )

        self.mocker.patch.object(http.log, "info")
        mock_deferLater = self.mocker.patch.object(http, "deferLater")
        mock_deferLater.side_effect = always_succeed_with(None)

        self.tftp.backend.get_reader.return_value = fail(AccessViolation())

        resource = http.HTTPBootResource()
        yield self.render_GET(resource, request)

        assert request.responseCode == 403
        assert b"" == b"".join(request.written)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_render_GET_404_file_not_found(self):
        path = factory.make_name("path")
        ip = factory.make_ip_address()
        request = DummyRequest([path.encode("utf-8")])
        request.requestHeaders = Headers(
            {
                "X-Server-Addr": ["192.168.1.1"],
                "X-Server-Port": ["5248"],
                "X-Forwarded-For": [ip],
                "X-Forwarded-Port": ["%s" % factory.pick_port()],
            }
        )

        self.mocker.patch.object(http.log, "info")
        mock_deferLater = self.mocker.patch.object(http, "deferLater")
        mock_deferLater.side_effect = always_succeed_with(None)

        self.tftp.backend.get_reader.return_value = fail(FileNotFound(path))

        resource = http.HTTPBootResource()
        yield self.render_GET(resource, request)

        assert request.responseCode == 404
        assert b"" == b"".join(request.written)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_render_GET_500_server_error(self):
        path = factory.make_name("path")
        ip = factory.make_ip_address()
        request = DummyRequest([path.encode("utf-8")])
        request.requestHeaders = Headers(
            {
                "X-Server-Addr": ["192.168.1.1"],
                "X-Server-Port": ["5248"],
                "X-Forwarded-For": [ip],
                "X-Forwarded-Port": ["%s" % factory.pick_port()],
            }
        )

        self.mocker.patch.object(http.log, "info")
        mock_deferLater = self.mocker.patch.object(http, "deferLater")
        mock_deferLater.side_effect = always_succeed_with(None)

        exc = factory.make_exception("internal error")
        self.tftp.backend.get_reader.return_value = fail(exc)

        resource = http.HTTPBootResource()
        yield self.render_GET(resource, request)

        assert request.responseCode == 500
        assert str(exc).encode("utf-8") == b"".join(request.written)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_render_GET_produces_from_reader(self):
        path = factory.make_name("path")
        ip = factory.make_ip_address()
        request = DummyRequest([path.encode("utf-8")])
        request.requestHeaders = Headers(
            {
                "X-Server-Addr": ["192.168.1.1"],
                "X-Server-Port": ["5248"],
                "X-Forwarded-For": [ip],
                "X-Forwarded-Port": ["%s" % factory.pick_port()],
            }
        )

        self.mocker.patch.object(http.log, "info")
        mock_deferLater = self.mocker.patch.object(http, "deferLater")
        mock_deferLater.side_effect = always_succeed_with(None)

        content = factory.make_string(size=100).encode("utf-8")
        reader = BytesReader(content)
        self.tftp.backend.get_reader.return_value = succeed(reader)

        resource = http.HTTPBootResource()
        yield self.render_GET(resource, request)

        assert [b"100"] == request.responseHeaders.getRawHeaders(
            b"Content-Length"
        )
        assert content == b"".join(request.written)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_render_GET_logs_node_event_with_original_path_ip(self):
        path = factory.make_name("path")
        ip = factory.make_ip_address()
        request = DummyRequest([path.encode("utf-8")])
        request.requestHeaders = Headers(
            {
                "X-Server-Addr": ["192.168.1.1"],
                "X-Server-Port": ["5248"],
                "X-Forwarded-For": [ip],
                "X-Forwarded-Port": ["%s" % factory.pick_port()],
            }
        )

        log_info = self.mocker.patch.object(http.log, "info")
        mock_deferLater = self.mocker.patch.object(http, "deferLater")
        mock_deferLater.side_effect = always_succeed_with(None)

        self.tftp.backend.get_reader.return_value = fail(AccessViolation())

        resource = http.HTTPBootResource()
        yield self.render_GET(resource, request)

        log_info.assert_called_once_with(
            "{path} requested by {remoteHost}", path=path, remoteHost=ip
        )
        mock_deferLater.assert_called_once_with(
            ANY,
            0,
            http.send_node_event_ip_address,
            event_type=EVENT_TYPES.NODE_HTTP_REQUEST,
            ip_address=ip,
            description=path,
        )
