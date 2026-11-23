# Copyright 2015-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import http.client
import random

from django.conf import settings
from django.urls import reverse
import pytest

from maascommon.osystem import CustomOS, OperatingSystemRegistry
from maasserver.enum import BOOT_RESOURCE_TYPE
from maasserver.models import PackageRepository
from maasserver.models.config import Config
from maasserver.testing.factory import factory
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin

# Names forbidden for use via the Web API.
FORBIDDEN_NAMES = {
    "active_discovery_last_scan",
    "commissioning_osystem",
    "maas_url",
    "omapi_key",
    "rpc_shared_secret",
    "tls_port",
    "uuid",
    "vault_enabled",
}


def _make_test_osystem(factory_fixture, request, releases=3):
    osystem = factory_fixture.make_name("os")
    release_names = [
        factory_fixture.make_name("release") for _ in range(releases)
    ]
    OperatingSystemRegistry.register_item(osystem, CustomOS())
    request.addfinalizer(
        lambda: OperatingSystemRegistry.unregister_item(osystem)
    )
    for release in release_names:
        factory_fixture.make_BootResource(
            rtype=BOOT_RESOURCE_TYPE.UPLOADED,
            name=f"{osystem}/{release}",
            architecture="i386/generic",
        )
    return osystem, release_names


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestMAASHandlerAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request):
        user_kind, client_kind = api_identity.split(",")
        self.user = request.getfixturevalue(
            {"user=user": "maas_user"}[user_kind]
        )
        self.client = request.getfixturevalue(
            {"client=oauth": "api_client"}[client_kind]
        )
        self.request = request

    def test_get_config_default_distro_series(self):
        default_distro_series = factory.make_name("distro_series")
        Config.objects.set_config(
            "default_distro_series", default_distro_series
        )
        response = self.client.get(
            reverse("maas_handler"),
            {"op": "get_config", "name": "default_distro_series"},
        )
        assert http.client.OK == response.status_code, response.content
        expected = '"%s"' % default_distro_series
        assert expected.encode(settings.DEFAULT_CHARSET) == response.content

    def test_set_config_default_distro_series(self):
        osystem, releases = _make_test_osystem(factory, self.request)
        factory.make_default_ubuntu_release_bootable()
        Config.objects.set_config("default_osystem", osystem)
        selected_release = releases[0]
        self.user.is_superuser = True
        self.user.save()
        response = self.client.post(
            reverse("maas_handler"),
            {
                "op": "set_config",
                "name": "default_distro_series",
                "value": selected_release,
            },
        )
        assert http.client.OK == response.status_code, response.content
        assert selected_release == Config.objects.get_config(
            "default_distro_series"
        )

    def test_set_config_only_default_osystem_are_valid_for_distro_series(self):
        default_osystem, _ = _make_test_osystem(factory, self.request)
        _, other_releases = _make_test_osystem(factory, self.request)
        factory.make_default_ubuntu_release_bootable()
        Config.objects.set_config("default_osystem", default_osystem)
        self.user.is_superuser = True
        self.user.save()
        response = self.client.post(
            reverse("maas_handler"),
            {
                "op": "set_config",
                "name": "default_distro_series",
                "value": other_releases[0],
            },
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )

    def test_get_config_forbidden_config_items(self):
        for name in sorted(FORBIDDEN_NAMES):
            response = self.client.get(
                reverse("maas_handler"), {"op": "get_config", "name": name}
            )
            assert response.status_code == http.client.BAD_REQUEST
            assert response["Content-Type"] == "application/json"
            assert (
                f"{name} is not a valid config setting (valid settings are: "
                in response.json().get(name, [""])[0]
            )

    def test_set_config_forbidden_config_items(self):
        self.user.is_superuser = True
        self.user.save()
        for name in sorted(FORBIDDEN_NAMES):
            response = self.client.post(
                reverse("maas_handler"),
                {
                    "op": "set_config",
                    "name": name,
                    "value": factory.make_name("nonsense"),
                },
            )
            assert response.status_code == http.client.BAD_REQUEST
            assert response["Content-Type"] == "application/json"
            assert (
                f"{name} is not a valid config setting (valid settings are: "
                in response.json().get(name, [""])[0]
            )

    def test_get_config_ntp_server_alias_for_ntp_servers(self):
        ntp_servers = factory.make_hostname() + " " + factory.make_hostname()
        Config.objects.set_config("ntp_servers", ntp_servers)
        response = self.client.get(
            reverse("maas_handler"),
            {"op": "get_config", "name": "ntp_server"},
        )
        assert response.status_code == http.client.OK
        assert response["Content-Type"] == "application/json"
        assert response.json() == ntp_servers

    def test_set_config_ntp_server_alias_for_ntp_servers(self):
        ntp_servers = factory.make_hostname() + " " + factory.make_hostname()
        self.user.is_superuser = True
        self.user.save()
        response = self.client.post(
            reverse("maas_handler"),
            {
                "op": "set_config",
                "name": "ntp_server",
                "value": ntp_servers,
            },
        )
        assert response.status_code == http.client.OK
        assert ntp_servers == Config.objects.get_config("ntp_servers")

    def test_get_main_archive_overrides_to_package_repository(self):
        PackageRepository.objects.all().delete()
        main_url = factory.make_url(scheme="http")
        factory.make_PackageRepository(
            url=main_url, default=True, arches=["i386", "amd64"]
        )
        response = self.client.get(
            reverse("maas_handler"),
            {"op": "get_config", "name": "main_archive"},
        )
        assert response.status_code == http.client.OK
        assert response["Content-Type"] == "application/json"
        assert response.json() == main_url

    def test_get_ports_archive_overrides_to_package_repository(self):
        PackageRepository.objects.all().delete()
        ports_url = factory.make_url(scheme="http")
        factory.make_PackageRepository(
            url=ports_url, default=True, arches=["arm64", "armhf", "powerpc"]
        )
        response = self.client.get(
            reverse("maas_handler"),
            {"op": "get_config", "name": "ports_archive"},
        )
        assert response.status_code == http.client.OK
        assert response["Content-Type"] == "application/json"
        assert response.json() == ports_url

    def test_set_main_archive_overrides_to_package_repository(self):
        main_archive = factory.make_url(scheme="http")
        self.user.is_superuser = True
        self.user.save()
        response = self.client.post(
            reverse("maas_handler"),
            {
                "op": "set_config",
                "name": "main_archive",
                "value": main_archive,
            },
        )
        assert response.status_code == http.client.OK
        assert main_archive == PackageRepository.get_main_archive().url

    def test_set_ports_archive_overrides_to_package_repository(self):
        ports_archive = factory.make_url(scheme="http")
        self.user.is_superuser = True
        self.user.save()
        response = self.client.post(
            reverse("maas_handler"),
            {
                "op": "set_config",
                "name": "ports_archive",
                "value": ports_archive,
            },
        )
        assert response.status_code == http.client.OK
        assert ports_archive == PackageRepository.get_ports_archive().url

    def test_set_config_use_peer_proxy(self):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.post(
            reverse("maas_handler"),
            {"op": "set_config", "name": "use_peer_proxy", "value": True},
        )
        assert http.client.OK == response.status_code
        assert Config.objects.get_config("use_peer_proxy")

    def test_set_config_prefer_v4_proxy(self):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.post(
            reverse("maas_handler"),
            {"op": "set_config", "name": "prefer_v4_proxy", "value": True},
        )
        assert http.client.OK == response.status_code
        assert Config.objects.get_config("prefer_v4_proxy")

    def test_set_config_boot_images_no_proxy(self):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.post(
            reverse("maas_handler"),
            {
                "op": "set_config",
                "name": "boot_images_no_proxy",
                "value": True,
            },
        )
        assert http.client.OK == response.status_code
        assert Config.objects.get_config("boot_images_no_proxy")

    def test_get_config_maas_internal_domain(self):
        internal_domain = factory.make_name("internal")
        Config.objects.set_config("maas_internal_domain", internal_domain)
        response = self.client.get(
            reverse("maas_handler"),
            {"op": "get_config", "name": "maas_internal_domain"},
        )
        assert http.client.OK == response.status_code, response.content
        assert ('"%s"' % internal_domain).encode(
            settings.DEFAULT_CHARSET
        ) == response.content

    def test_set_config_maas_internal_domain(self):
        internal_domain = factory.make_name("internal")
        self.user.is_superuser = True
        self.user.save()
        response = self.client.post(
            reverse("maas_handler"),
            {
                "op": "set_config",
                "name": "maas_internal_domain",
                "value": internal_domain,
            },
        )
        assert http.client.OK == response.status_code, response.content
        assert internal_domain == Config.objects.get_config(
            "maas_internal_domain"
        )

    def test_get_config_maas_ipmi_user(self):
        ipmi_user = factory.make_name("internal")
        Config.objects.set_config("maas_auto_ipmi_user", ipmi_user)
        response = self.client.get(
            reverse("maas_handler"),
            {"op": "get_config", "name": "maas_auto_ipmi_user"},
        )
        assert http.client.OK == response.status_code, response.content
        assert ('"%s"' % ipmi_user).encode(
            settings.DEFAULT_CHARSET
        ) == response.content

    def test_set_config_maas_ipmi_user(self):
        ipmi_user = factory.make_name("internal")
        self.user.is_superuser = True
        self.user.save()
        response = self.client.post(
            reverse("maas_handler"),
            {
                "op": "set_config",
                "name": "maas_auto_ipmi_user",
                "value": ipmi_user,
            },
        )
        assert http.client.OK == response.status_code, response.content
        assert ipmi_user == Config.objects.get_config("maas_auto_ipmi_user")


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.parametrize(
    "port,valid",
    [
        pytest.param(random.randint(5300, 65535), True, id="valid-port"),
        pytest.param(
            random.randint(5240, 5270),
            False,
            id="invalid-port_maas-reserved-range",
        ),
        pytest.param(
            random.randint(0, 1023),
            False,
            id="invalid-port_system-services",
        ),
        pytest.param(
            random.randint(65536, 70000),
            False,
            id="invalid-port_out-of-range",
        ),
    ],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestMAASHandlerAPIForProxyPort:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request):
        user_kind, client_kind = api_identity.split(",")
        self.user = request.getfixturevalue(
            {"user=user": "maas_user"}[user_kind]
        )
        self.client = request.getfixturevalue(
            {"client=oauth": "api_client"}[client_kind]
        )

    def test_set_config_maas_proxy_port(self, port, valid):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.post(
            reverse("maas_handler"),
            {"op": "set_config", "name": "maas_proxy_port", "value": port},
        )
        if valid:
            assert http.client.OK == response.status_code, response.content
            assert port == Config.objects.get_config("maas_proxy_port")
        else:
            assert http.client.BAD_REQUEST == response.status_code, (
                response.content
            )


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestMAASAPIOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request):
        user_kind, client_kind = api_identity.split(",")
        self.user = request.getfixturevalue(
            {"user=user": "maas_user"}[user_kind]
        )
        self.client = request.getfixturevalue(
            {"client=oauth": "api_client"}[client_kind]
        )

    def test_set_config_requires_can_edit_configurations(self):
        self.openfga_client.can_edit_configurations.return_value = True
        ntp_servers = factory.make_hostname() + " " + factory.make_hostname()
        response = self.client.post(
            reverse("maas_handler"),
            {"op": "set_config", "name": "ntp_server", "value": ntp_servers},
        )
        assert http.client.OK == response.status_code, response.content
        self.openfga_client.can_edit_configurations.assert_called_once_with(
            self.user
        )
