# Copyright 2013-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from collections import namedtuple
import http.client
from unittest.mock import call, MagicMock, Mock, sentinel

from django.core.exceptions import PermissionDenied
from django.urls import reverse
from piston3.authentication import NoAuthentication
import pytest

from maasserver import openfga
from maasserver.api.doc import get_api_description
from maasserver.api.support import (
    AdminRestrictedResource,
    check_permission,
    deprecated,
    Emitter,
    OperationsHandlerMixin,
    OperationsResource,
    RestrictedResource,
)
from maasserver.models.config import Config, ConfigManager
from maasserver.testing.factory import factory


class TestEmitterOnlyJSON:
    def test_emitters(self):
        assert Emitter.EMITTERS.keys() == {"json"}


class StubHandler:
    """A stub handler class that breaks when called."""

    def __call__(self, request):
        raise AssertionError("Do not call the stub handler.")


class TestOperationsResource:
    def test_type_error_is_not_hidden(self, admin_api_client, factory, mocker):
        # This tests that bug #1228205 is fixed (i.e. that a
        # TypeError is properly reported and not swallowed by
        # piston).

        # Create a valid configuration item.
        name = "maas_name"
        value = factory.make_string()
        Config.objects.set_config(name, value)

        # Patch ConfigManager.get_config so that it will raise a
        # TypeError exception.
        def mock_get_config(config):
            if config == name:
                raise TypeError()

        mocker.patch.object(
            ConfigManager, "get_config", side_effect=mock_get_config
        )
        response = admin_api_client.get(
            reverse("maas_handler"), {"op": "get_config", "name": name}
        )
        assert http.client.INTERNAL_SERVER_ERROR == response.status_code, (
            response.content
        )

    def test_api_hash_is_set_in_headers(self, admin_api_client, factory):
        Config.objects.set_config("maas_name", factory.make_name("name"))
        response = admin_api_client.get(
            reverse("maas_handler"), {"op": "get_config", "name": "maas_name"}
        )
        assert response["X-MAAS-API-Hash"] == get_api_description()["hash"]

    def test_call_op_in_path(self, admin_api_client, factory):
        Config.objects.set_config("maas_name", factory.make_name("name"))
        response = admin_api_client.get(
            reverse("maas_handler-op-get_config"), {"name": "maas_name"}
        )
        assert http.client.OK == response.status_code

    def test_authenticated_is_False_when_no_authentication_provided(self):
        resource = OperationsResource(StubHandler)
        assert not resource.is_authentication_attempted

    def test_authenticated_is_False_when_authentication_is_empty(self):
        resource = OperationsResource(StubHandler, authentication=[])
        assert not resource.is_authentication_attempted

    def test_authenticated_is_False_when_authentication_is_NoAuthn(self):
        resource = OperationsResource(
            StubHandler, authentication=NoAuthentication()
        )
        assert not resource.is_authentication_attempted

    def test_authenticated_is_True_when_authentication_is_provided(self):
        resource = OperationsResource(
            StubHandler, authentication=sentinel.authentication
        )
        assert resource.is_authentication_attempted


@pytest.mark.parametrize(
    "_resource_type",
    [RestrictedResource, AdminRestrictedResource],
    ids=["user", "admin"],
)
class TestRestrictedResources:
    """Tests for `RestrictedResource` and `AdminRestrictedResource`."""

    def test_authentication_must_not_be_None(self, _resource_type):
        with pytest.raises(AssertionError) as error:
            _resource_type(StubHandler, authentication=None)
        assert "Authentication must be attempted." == str(error.value)

    def test_authentication_must_be_non_empty(self, _resource_type):
        with pytest.raises(AssertionError) as error:
            _resource_type(StubHandler, authentication=[])
        assert "Authentication must be attempted." == str(error.value)

    def test_authentication_must_be_meaningful(self, _resource_type):
        with pytest.raises(AssertionError) as error:
            _resource_type(StubHandler, authentication=NoAuthentication())
        assert "Authentication must be attempted." == str(error.value)

    def test_authentication_is_okay(self, _resource_type):
        resource = _resource_type(
            StubHandler, authentication=sentinel.authentication
        )
        assert resource.is_authentication_attempted


@pytest.fixture
def openfga_client(mocker):
    client = MagicMock()
    mocker.patch.object(openfga, "_get_client", return_value=client)
    openfga.get_openfga_client.cache_clear()
    yield client
    openfga.get_openfga_client.cache_clear()


@pytest.mark.usefixtures("maasdb")
class TestAdminMethodDecorator:
    def test_permission_denied(self, openfga_client):
        openfga_client.can_edit_global_entities.return_value = False

        FakeRequest = namedtuple("FakeRequest", ["user"])
        user = factory.make_User()
        request = FakeRequest(user=user)
        mock = Mock()

        @check_permission("can_edit_global_entities")
        def api_method(self, request):
            return mock()

        with pytest.raises(PermissionDenied):
            api_method("self", request)
        assert [] == mock.mock_calls
        openfga_client.can_edit_global_entities.assert_called_once_with(user)

    def test_permission_success(self, openfga_client):
        openfga_client.can_edit_global_entities.return_value = True

        FakeRequest = namedtuple("FakeRequest", ["user"])
        user = factory.make_User()
        request = FakeRequest(user=user)
        return_value = factory.make_name("return")
        mock = Mock(return_value=return_value)

        @check_permission("can_edit_global_entities")
        def api_method(self, request):
            return mock()

        response = api_method("self", request)
        assert (return_value, [call()]) == (response, mock.mock_calls)
        openfga_client.can_edit_global_entities.assert_called_once_with(user)


class TestDeprecatedMethodDecorator:
    def test_function_marked_as_deprecated(self):
        def api_replacement_method(self, request):
            pass

        @deprecated(use=api_replacement_method)
        def api_method(self, request):
            pass

        assert api_method.deprecated is api_replacement_method

    def test_class_marked_as_deprecated(self):
        class api_replacement_endpoint:
            api_doc_section_name = "Replacement"

        @deprecated(use=api_replacement_endpoint)
        class api_endpoint:
            api_doc_section_name = "Deprecated"

        assert api_endpoint.deprecated is api_replacement_endpoint

    def test_deprecated_class_inheritance_only_affects_own_methods(self):
        class BaseHandler:
            api_doc_section_name = "Base"

            def inherited_method(self):
                pass

        class ReplacementHandler:
            api_doc_section_name = "Replacement"

            def own_method(self):
                pass

        @deprecated(use=ReplacementHandler)
        class DeprecatedHandler(BaseHandler):
            api_doc_section_name = "Deprecated"

            def own_method(self):
                pass

        assert hasattr(DeprecatedHandler.own_method, "deprecated")
        assert not hasattr(DeprecatedHandler.inherited_method, "deprecated")


class TestOperationsHandlerMixin:
    """Tests for :py:class:`maasserver.api.support.OperationsHandlerMixin`."""

    def make_handler(self, **namespace):
        return type("TestHandler", (OperationsHandlerMixin,), namespace)

    def test_decorate_decorates_exports(self):
        handler = self.make_handler(
            exports={"foo": sentinel.foo, "bar": sentinel.bar}
        )
        handler.decorate(lambda thing: str(thing).upper())
        assert {
            "foo": "SENTINEL.FOO",
            "bar": "SENTINEL.BAR",
        } == handler.exports

    def test_decorate_decorates_anonymous_exports(self):
        handler = self.make_handler(exports={"foo": sentinel.foo})
        handler.anonymous = self.make_handler(exports={"bar": sentinel.bar})
        handler.decorate(lambda thing: str(thing).upper())
        assert {"foo": "SENTINEL.FOO"} == handler.exports
        assert {"bar": "SENTINEL.BAR"} == handler.anonymous.exports
