# Copyright 2014-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the `LicenseKey` API."""

import http.client
import random

from django.urls import reverse
import pytest

from maascommon.osystem import OperatingSystemRegistry, WindowsOS
from maascommon.osystem.windows import REQUIRE_LICENSE_KEY
from maasserver import forms
from maasserver.enum import BOOT_RESOURCE_TYPE
from maasserver.models.licensekey import LicenseKey
from maasserver.testing.factory import factory
from maasserver.utils.converters import json_load_bytes
from maasserver.utils.orm import get_one, reload_object
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


def make_os(request):
    osystem = factory.make_name("osystem")
    release = random.choice(REQUIRE_LICENSE_KEY)
    distro_series = f"{osystem}/{release}"
    drv = WindowsOS()
    drv.title = osystem
    OperatingSystemRegistry.register_item(osystem, drv)
    factory.make_BootResource(
        name=distro_series,
        rtype=BOOT_RESOURCE_TYPE.UPLOADED,
        extra={"title": drv.get_release_title(release)},
    )
    request.addfinalizer(
        lambda: OperatingSystemRegistry.unregister_item(osystem)
    )
    return osystem, release


def get_license_key_url(osystem, distro_series):
    """Return the URL for the license key of the given osystem and
    distro_series."""
    return reverse("license_key_handler", args=[osystem, distro_series])


def make_license_key_with_os(request, license_key=None):
    osystem, release = make_os(request)
    return factory.make_LicenseKey(
        osystem=osystem, distro_series=release, license_key=license_key
    )


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("maas_user", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestLicenseKey:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request):
        self.user = request.getfixturevalue(api_identity)
        self.client = request.getfixturevalue("api_client")

    def test_handler_path(self):
        osystem = factory.make_name("osystem")
        distro_series = factory.make_name("series")
        assert (
            f"/MAAS/api/2.0/license-key/{osystem}/{distro_series}"
            == get_license_key_url(osystem, distro_series)
        )

    def test_POST_is_prohibited(self, admin_api_client):
        license_key = factory.make_LicenseKey()
        response = admin_api_client.post(
            get_license_key_url(
                license_key.osystem, license_key.distro_series
            ),
            {"osystem": "New osystem"},
        )
        assert http.client.METHOD_NOT_ALLOWED == response.status_code

    def test_GET_returns_license_key(self, admin_api_client):
        license_key = factory.make_LicenseKey()
        response = admin_api_client.get(
            get_license_key_url(license_key.osystem, license_key.distro_series)
        )
        assert http.client.OK == response.status_code

        parsed_result = json_load_bytes(response.content)
        assert (
            license_key.osystem,
            license_key.distro_series,
            license_key.license_key,
        ) == (
            parsed_result["osystem"],
            parsed_result["distro_series"],
            parsed_result["license_key"],
        )

    def test_GET_returns_404_for_unknown_os_and_series(self, admin_api_client):
        assert (
            http.client.NOT_FOUND
            == admin_api_client.get(
                get_license_key_url("noneos", "noneseries")
            ).status_code
        )

    def test_GET_requires_admin(self):
        license_key = factory.make_LicenseKey()
        response = self.client.get(
            get_license_key_url(license_key.osystem, license_key.distro_series)
        )
        assert http.client.FORBIDDEN == response.status_code

    def test_PUT_updates_license_key(self, admin_api_client, mocker, request):
        license_key = make_license_key_with_os(request)
        mocker.patch.object(forms, "validate_license_key", return_value=True)
        new_key = factory.make_name("key")
        response = admin_api_client.put(
            get_license_key_url(
                license_key.osystem, license_key.distro_series
            ),
            {"license_key": new_key},
        )
        assert http.client.OK == response.status_code
        license_key = reload_object(license_key)
        assert new_key == license_key.license_key

    def test_PUT_requires_admin(self, request):
        key = factory.make_name("key")
        license_key = make_license_key_with_os(request, license_key=key)
        response = self.client.put(
            get_license_key_url(
                license_key.osystem, license_key.distro_series
            ),
            {"license_key": factory.make_name("key")},
        )
        assert http.client.FORBIDDEN == response.status_code
        assert key == reload_object(license_key).license_key

    def test_PUT_returns_404_for_unknown_os_and_series(self, admin_api_client):
        assert (
            http.client.NOT_FOUND
            == admin_api_client.put(
                get_license_key_url("noneos", "noneseries")
            ).status_code
        )

    def test_DELETE_deletes_license_key(self, admin_api_client):
        license_key = factory.make_LicenseKey()
        response = admin_api_client.delete(
            get_license_key_url(license_key.osystem, license_key.distro_series)
        )
        assert http.client.NO_CONTENT == response.status_code
        assert reload_object(license_key) is None

    def test_DELETE_requires_admin(self):
        license_key = factory.make_LicenseKey()
        response = self.client.delete(
            get_license_key_url(license_key.osystem, license_key.distro_series)
        )
        assert http.client.FORBIDDEN == response.status_code
        assert reload_object(license_key) is not None

    def test_DELETE_is_idempotent(self, admin_api_client):
        osystem = factory.make_name("no-os")
        series = factory.make_name("no-series")
        response1 = admin_api_client.delete(
            get_license_key_url(osystem, series)
        )
        response2 = admin_api_client.delete(
            get_license_key_url(osystem, series)
        )
        assert response1.status_code == response2.status_code


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("maas_user", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestLicenseKeysAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request):
        self.user = request.getfixturevalue(api_identity)
        self.client = request.getfixturevalue("api_client")

    def test_handler_path(self):
        assert "/MAAS/api/2.0/license-keys/" == reverse("license_keys_handler")

    def test_GET_returns_license_keys(self, admin_api_client):
        orig_license_key = factory.make_LicenseKey()
        response = admin_api_client.get(reverse("license_keys_handler"))
        assert http.client.OK == response.status_code, response.content

        parsed_result = json_load_bytes(response.content)
        assert 1 == len(parsed_result)
        [returned_network] = parsed_result
        fields = {"osystem", "distro_series", "license_key"}
        assert fields.union({"resource_uri"}) == returned_network.keys()
        expected_values = {
            field: getattr(orig_license_key, field)
            for field in fields
            if field != "resource_uri"
        }
        expected_values["resource_uri"] = reverse(
            "license_key_handler",
            args=[orig_license_key.osystem, orig_license_key.distro_series],
        )
        assert expected_values == returned_network

    def test_GET_requires_admin(self):
        factory.make_LicenseKey()
        response = self.client.get(reverse("license_keys_handler"))
        assert http.client.FORBIDDEN == response.status_code

    def test_GET_returns_empty_if_no_networks(self, admin_api_client):
        response = admin_api_client.get(reverse("license_keys_handler"))
        assert http.client.OK == response.status_code, response.content
        assert [] == json_load_bytes(response.content)

    def test_POST_creates_license_key(self, admin_api_client, mocker, request):
        osystem, release = make_os(request)
        mocker.patch.object(forms, "validate_license_key", return_value=True)
        params = {
            "osystem": osystem,
            "distro_series": release,
            "license_key": factory.make_name("key"),
        }
        response = admin_api_client.post(
            reverse("license_keys_handler"), params
        )
        assert http.client.OK == response.status_code
        license_key = LicenseKey.objects.get(
            osystem=osystem, distro_series=release
        )
        assert osystem == license_key.osystem
        assert release == license_key.distro_series
        assert params["license_key"] == license_key.license_key

    def test_POST_supports_combined_distro_series(
        self, admin_api_client, mocker, request
    ):
        # API allows specifying only distro_series containing both
        # os and series in the "os/series" form.
        osystem, release = make_os(request)
        mocker.patch.object(forms, "validate_license_key", return_value=True)
        params = {
            "distro_series": f"{osystem}/{release}",
            "license_key": factory.make_name("key"),
        }
        response = admin_api_client.post(
            reverse("license_keys_handler"), params
        )
        assert http.client.OK == response.status_code
        license_key = LicenseKey.objects.get(
            osystem=osystem, distro_series=release
        )
        assert osystem == license_key.osystem
        assert release == license_key.distro_series
        assert params["license_key"] == license_key.license_key

    def test_POST_requires_osystem(self, admin_api_client, mocker, request):
        # If osystem is not specified and distro_series is not in the
        # osystem/release form, API call fails.
        _, release = make_os(request)
        mocker.patch.object(forms, "validate_license_key", return_value=True)
        params = {
            "distro_series": release,
            "license_key": factory.make_name("key"),
        }
        response = admin_api_client.post(
            reverse("license_keys_handler"), params
        )
        assert http.client.BAD_REQUEST == response.status_code

    def test_POST_requires_admin(self):
        osystem = factory.make_name("no-os")
        series = factory.make_name("no-series")
        response = self.client.post(
            reverse("license_keys_handler"),
            {"osystem": osystem, "distro_series": series},
        )
        assert http.client.FORBIDDEN == response.status_code
        assert (
            get_one(
                LicenseKey.objects.filter(
                    osystem=osystem, distro_series=series
                )
            )
            is None
        )


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("maas_user", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestLicenseKeysAPIOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request):
        self.user = request.getfixturevalue(api_identity)
        self.client = request.getfixturevalue("api_client")

    def test_read_requires_can_view_license_keys(self):
        self.openfga_client.can_view_license_keys.return_value = True
        factory.make_LicenseKey()
        response = self.client.get(reverse("license_keys_handler"))
        assert http.client.OK == response.status_code
        self.openfga_client.can_view_license_keys.assert_called_once_with(
            self.user
        )

    def test_create_requires_can_edit_global_entities(self, mocker, request):
        self.openfga_client.can_edit_license_keys.return_value = True
        osystem, release = make_os(request)
        mocker.patch.object(forms, "validate_license_key", return_value=True)
        params = {
            "osystem": osystem,
            "distro_series": release,
            "license_key": factory.make_name("key"),
        }
        response = self.client.post(reverse("license_keys_handler"), params)
        assert http.client.OK == response.status_code
        self.openfga_client.can_edit_license_keys.assert_called_once_with(
            self.user
        )


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("maas_user", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestLicenseKeyAPIOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request):
        self.user = request.getfixturevalue(api_identity)
        self.client = request.getfixturevalue("api_client")

    def test_read_requires_can_view_license_keys(self):
        self.openfga_client.can_view_license_keys.return_value = True
        license_key = factory.make_LicenseKey()
        response = self.client.get(
            get_license_key_url(license_key.osystem, license_key.distro_series)
        )
        assert http.client.OK == response.status_code
        self.openfga_client.can_view_license_keys.assert_called_once_with(
            self.user
        )

    def test_update_requires_can_edit_license_keys(self, mocker, request):
        self.openfga_client.can_edit_license_keys.return_value = True
        license_key = make_license_key_with_os(request)
        mocker.patch.object(forms, "validate_license_key", return_value=True)
        new_key = factory.make_name("key")
        response = self.client.put(
            get_license_key_url(
                license_key.osystem, license_key.distro_series
            ),
            {"license_key": new_key},
        )
        assert http.client.OK == response.status_code
        self.openfga_client.can_edit_license_keys.assert_called_once_with(
            self.user
        )

    def test_delete_requires_can_edit_license_keys(self):
        self.openfga_client.can_edit_license_keys.return_value = True
        license_key = factory.make_LicenseKey()
        response = self.client.delete(
            get_license_key_url(license_key.osystem, license_key.distro_series)
        )
        assert http.client.NO_CONTENT == response.status_code
        self.openfga_client.can_edit_license_keys.assert_called_once_with(
            self.user
        )
