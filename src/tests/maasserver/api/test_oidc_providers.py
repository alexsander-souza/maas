import http.client

from django.urls import reverse
import pytest

from maasserver.api.oidc_providers import provider_to_dict
from maasserver.testing.factory import factory
from maasserver.utils.converters import json_load_bytes
from maasservicelayer.exceptions.catalog import (
    AlreadyExistsException,
    BadGatewayException,
    ConflictException,
    NotFoundException,
    PreconditionFailedException,
)
from maasservicelayer.models.base import ListResult
from maasservicelayer.models.external_auth import ProviderVendorType


def get_oidc_provider_uri(provider):
    """Return an OIDC provider's URI on the API."""
    return reverse("oidc_provider_handler", args=[provider.id])


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("maas_user", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestOidcProvider:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request, api_client, mocker):
        self.user = request.getfixturevalue(api_identity)
        self.client = api_client
        self.external_oauth = mocker.patch(
            "maasserver.api.oidc_providers.service_layer"
            ".services.external_oauth"
        )

    def test_handler_path(self):
        assert "/MAAS/api/2.0/oidc-providers/1/" == reverse(
            "oidc_provider_handler", args=["1"]
        )

    def test_GET_returns_provider(self):
        self.user.is_superuser = True
        self.user.save()
        provider = factory.make_OidcProvider()
        self.external_oauth.get_by_id.return_value = provider

        response = self.client.get(get_oidc_provider_uri(provider))

        assert http.client.OK == response.status_code
        self.external_oauth.get_by_id.assert_called_once_with(id=provider.id)
        assert json_load_bytes(response.content) == provider_to_dict(provider)

    def test_GET_nonexistent_provider(self):
        self.user.is_superuser = True
        self.user.save()
        self.external_oauth.get_by_id.return_value = None

        response = self.client.get(
            reverse("oidc_provider_handler", args=[999])
        )

        assert http.client.NOT_FOUND == response.status_code
        self.external_oauth.get_by_id.assert_called_once_with(id=999)

    def test_GET_requires_admin(self):
        provider = factory.make_OidcProvider()

        response = self.client.get(get_oidc_provider_uri(provider))

        assert http.client.FORBIDDEN == response.status_code

    def test_DELETE_nonexistent_provider(self):
        self.user.is_superuser = True
        self.user.save()
        self.external_oauth.delete_by_id.side_effect = NotFoundException()

        response = self.client.delete(
            reverse("oidc_provider_handler", args=[999])
        )

        assert http.client.NOT_FOUND == response.status_code
        self.external_oauth.delete_by_id.assert_called_once_with(id=999)

    def test_DELETE_raises_conflict(self):
        self.user.is_superuser = True
        self.user.save()
        self.external_oauth.delete_by_id.side_effect = (
            PreconditionFailedException()
        )

        response = self.client.delete(
            get_oidc_provider_uri(factory.make_OidcProvider())
        )

        assert http.client.CONFLICT == response.status_code
        self.external_oauth.delete_by_id.assert_called_once_with(id=1)

    def test_DELETE_returns_no_content(self):
        self.user.is_superuser = True
        self.user.save()

        response = self.client.delete(
            get_oidc_provider_uri(factory.make_OidcProvider())
        )

        assert http.client.NO_CONTENT == response.status_code
        self.external_oauth.delete_by_id.assert_called_once_with(id=1)

    def test_DELETE_requires_admin(self):
        provider = factory.make_OidcProvider()

        response = self.client.delete(get_oidc_provider_uri(provider))

        assert http.client.FORBIDDEN == response.status_code

    def test_PUT_nonexistent_provider(self):
        self.user.is_superuser = True
        self.user.save()
        self.external_oauth.update_provider.side_effect = NotFoundException()

        response = self.client.put(
            reverse("oidc_provider_handler", args=[999]), data={}
        )

        assert http.client.NOT_FOUND == response.status_code

    def test_PUT_conflict(self):
        self.user.is_superuser = True
        self.user.save()
        self.external_oauth.update_provider.side_effect = ConflictException()

        response = self.client.put(
            reverse("oidc_provider_handler", args=[999]), data={}
        )

        assert http.client.CONFLICT == response.status_code
        assert str(response.content, "utf-8") == (
            "An enabled provider already exists. Disable the existing provider "
            "before enabling this one."
        )

    def test_PUT_success(self):
        self.user.is_superuser = True
        self.user.save()
        provider = factory.make_OidcProvider()
        updated_provider = provider.copy()
        updated_provider.name = "New Name"
        self.external_oauth.get_by_id.return_value = provider
        self.external_oauth.update_provider.return_value = updated_provider

        response = self.client.put(
            get_oidc_provider_uri(provider),
            data={
                "name": "New Name",
            },
        )

        assert http.client.OK == response.status_code
        assert json_load_bytes(response.content) == provider_to_dict(
            updated_provider
        )

    def test_PUT_invalid_vendor(self):
        self.user.is_superuser = True
        self.user.save()
        provider = factory.make_OidcProvider()
        self.external_oauth.get_by_id.return_value = provider

        response = self.client.put(
            get_oidc_provider_uri(provider),
            data={
                "vendor": "INVALID",
            },
        )

        assert http.client.BAD_REQUEST == response.status_code
        assert str(response.content, "utf-8") == (
            "Invalid vendor: INVALID. Must be one of: "
            "Generic, EntraID, Auth0, Keycloak."
        )
        self.external_oauth.update_provider.assert_not_called()

    def test_PUT_updates_vendor(self):
        self.user.is_superuser = True
        self.user.save()
        provider = factory.make_OidcProvider(vendor=ProviderVendorType.GENERIC)
        updated_provider = provider.copy()
        updated_provider.vendor = ProviderVendorType.AUTH0
        self.external_oauth.get_by_id.return_value = provider
        self.external_oauth.update_provider.return_value = updated_provider

        response = self.client.put(
            get_oidc_provider_uri(provider),
            data={
                "vendor": "Auth0",
            },
        )

        assert http.client.OK == response.status_code
        builder = self.external_oauth.update_provider.call_args.kwargs[
            "builder"
        ]
        assert builder.vendor == ProviderVendorType.AUTH0
        assert json_load_bytes(response.content)["vendor"] == "Auth0"

    def test_PUT_requires_admin(self):
        provider = factory.make_OidcProvider()

        response = self.client.put(
            get_oidc_provider_uri(provider),
            data={
                "name": "New Name",
            },
        )

        assert http.client.FORBIDDEN == response.status_code


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("maas_user", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestOidcProviders:
    SAMPLE_PROVIDER_DATA = {
        "name": "Test Provider",
        "issuer_url": "https://example.com",
        "client_id": "test-client-id",
        "client_secret": "test-client-secret",
        "redirect_uri": "https://example.com/callback",
        "scopes": "openid profile email",
        "enabled": True,
        "token_type": "JWT",
        "vendor": "Generic",
    }

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request, api_client, mocker):
        self.user = request.getfixturevalue(api_identity)
        self.client = api_client
        self.external_oauth = mocker.patch(
            "maasserver.api.oidc_providers.service_layer"
            ".services.external_oauth"
        )

    def test_handler_path(self):
        assert "/MAAS/api/2.0/oidc-providers/" == reverse(
            "oidc_providers_handler"
        )

    def test_GET_empty_list(self):
        self.user.is_superuser = True
        self.user.save()
        self.external_oauth.list.return_value = ListResult(items=[], total=0)

        response = self.client.get(reverse("oidc_providers_handler"))

        assert http.client.OK == response.status_code
        assert json_load_bytes(response.content) == "No OIDC providers found."
        self.external_oauth.list.assert_called_once()

    def test_GET_returns_providers(self):
        self.user.is_superuser = True
        self.user.save()
        providers = [factory.make_OidcProvider() for _ in range(3)]
        self.external_oauth.list.return_value = ListResult(
            items=providers, total=3
        )

        response = self.client.get(reverse("oidc_providers_handler"))

        assert http.client.OK == response.status_code
        self.external_oauth.list.assert_called_once()
        assert json_load_bytes(response.content) == [
            provider_to_dict(provider) for provider in providers
        ]

    def test_GET_requires_admin(self):
        response = self.client.get(reverse("oidc_providers_handler"))

        assert http.client.FORBIDDEN == response.status_code

    def test_GET_get_active_not_found(self):
        self.user.is_superuser = True
        self.user.save()
        self.external_oauth.get_provider.return_value = None

        response = self.client.get(
            reverse("oidc_providers_handler"), {"op": "get_active"}
        )

        assert http.client.NOT_FOUND == response.status_code
        assert (
            str(response.content, "utf-8") == "No enabled OIDC provider found."
        )
        self.external_oauth.get_provider.assert_called_once()

    def test_GET_get_active_success(self):
        self.user.is_superuser = True
        self.user.save()
        provider = factory.make_OidcProvider()
        self.external_oauth.get_provider.return_value = provider

        response = self.client.get(
            reverse("oidc_providers_handler"), {"op": "get_active"}
        )

        assert http.client.OK == response.status_code
        self.external_oauth.get_provider.assert_called_once()
        assert json_load_bytes(response.content) == provider_to_dict(provider)

    def test_CREATE_invalid_url(self):
        self.user.is_superuser = True
        self.user.save()
        data = self.SAMPLE_PROVIDER_DATA.copy()
        data["issuer_url"] = "not-a-valid-url"

        response = self.client.post(
            reverse("oidc_providers_handler"),
            data=data,
        )
        assert http.client.BAD_REQUEST == response.status_code
        assert str(response.content, "utf-8") == (
            "Issuer URL must be a valid HTTP or HTTPS address."
        )

    def test_CREATE_invalid_token_type(self):
        self.user.is_superuser = True
        self.user.save()
        data = self.SAMPLE_PROVIDER_DATA.copy()
        data["token_type"] = "INVALID"

        response = self.client.post(
            reverse("oidc_providers_handler"),
            data=data,
        )
        assert http.client.BAD_REQUEST == response.status_code
        assert str(response.content, "utf-8") == (
            "Invalid token type: INVALID. Must be 'JWT' or 'Opaque'."
        )

    def test_CREATE_invalid_vendor(self):
        self.user.is_superuser = True
        self.user.save()
        data = self.SAMPLE_PROVIDER_DATA.copy()
        data["vendor"] = "INVALID"

        response = self.client.post(
            reverse("oidc_providers_handler"),
            data=data,
        )
        assert http.client.BAD_REQUEST == response.status_code
        assert str(response.content, "utf-8") == (
            "Invalid vendor: INVALID. Must be one of: "
            "Generic, EntraID, Auth0, Keycloak."
        )

    def test_CREATE_bad_gateway(self):
        self.user.is_superuser = True
        self.user.save()
        self.external_oauth.create.side_effect = BadGatewayException()

        response = self.client.post(
            reverse("oidc_providers_handler"),
            data=self.SAMPLE_PROVIDER_DATA,
        )
        assert http.client.BAD_GATEWAY == response.status_code
        assert str(response.content, "utf-8") == (
            "Failed to create OIDC provider: Bad gateway."
        )

    def test_CREATE_already_exists(self):
        self.user.is_superuser = True
        self.user.save()
        self.external_oauth.create.side_effect = AlreadyExistsException()

        response = self.client.post(
            reverse("oidc_providers_handler"),
            data=self.SAMPLE_PROVIDER_DATA,
        )
        assert http.client.CONFLICT == response.status_code
        assert str(response.content, "utf-8") == (
            "An OIDC provider with the same name already exists."
        )

    def test_CREATE_conflict_with_enabled_provider(self):
        self.user.is_superuser = True
        self.user.save()
        self.external_oauth.create.side_effect = ConflictException()

        response = self.client.post(
            reverse("oidc_providers_handler"),
            data=self.SAMPLE_PROVIDER_DATA,
        )
        assert http.client.CONFLICT == response.status_code
        assert str(response.content, "utf-8") == (
            "An enabled provider already exists. Disable the existing provider "
            "before creating a new one."
        )

    def test_CREATE_success(self):
        self.user.is_superuser = True
        self.user.save()
        provider = factory.make_OidcProvider()
        self.external_oauth.create.return_value = provider

        response = self.client.post(
            reverse("oidc_providers_handler"),
            data=self.SAMPLE_PROVIDER_DATA,
        )
        assert http.client.CREATED == response.status_code
        assert json_load_bytes(response.content) == provider_to_dict(provider)

    def test_CREATE_defaults_vendor_to_generic(self):
        self.user.is_superuser = True
        self.user.save()
        provider = factory.make_OidcProvider(vendor=ProviderVendorType.GENERIC)
        self.external_oauth.create.return_value = provider

        response = self.client.post(
            reverse("oidc_providers_handler"),
            data=self.SAMPLE_PROVIDER_DATA,
        )
        assert http.client.CREATED == response.status_code
        builder = self.external_oauth.create.call_args.kwargs["builder"]
        assert builder.vendor == ProviderVendorType.GENERIC

    def test_CREATE_with_vendor(self):
        self.user.is_superuser = True
        self.user.save()
        provider = factory.make_OidcProvider(
            vendor=ProviderVendorType.KEYCLOAK
        )
        self.external_oauth.create.return_value = provider
        data = self.SAMPLE_PROVIDER_DATA.copy()
        data["vendor"] = "Keycloak"

        response = self.client.post(
            reverse("oidc_providers_handler"),
            data=data,
        )
        assert http.client.CREATED == response.status_code
        builder = self.external_oauth.create.call_args.kwargs["builder"]
        assert builder.vendor == ProviderVendorType.KEYCLOAK
        assert json_load_bytes(response.content)["vendor"] == "Keycloak"

    def test_CREATE_requires_admin(self):
        response = self.client.post(
            reverse("oidc_providers_handler"),
            data=self.SAMPLE_PROVIDER_DATA,
        )

        assert http.client.FORBIDDEN == response.status_code
