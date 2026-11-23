# Copyright 2016-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


import http.client

from django.urls import reverse
from django.utils.http import urlencode
import pytest

from maasserver.api import rackcontrollers
from maasserver.clusterrpc.driver_parameters import get_all_power_types
from maasserver.enum import BOOT_RESOURCE_FILE_TYPE, BOOT_RESOURCE_TYPE
from maasserver.models.signals import vlan as vlan_signals_module
from maasserver.testing.api import explain_unexpected_response
from maasserver.testing.factory import factory
from maasserver.utils.converters import json_load_bytes
from maasserver.utils.orm import reload_object
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures(
    "maasdb", "maas_region_test", "factory", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestRackControllerAPI:
    """Tests for /api/2.0/rackcontrollers/<rack>/."""

    @pytest.fixture(autouse=True)
    def _setup(
        self, transactional_maasdb, api_identity, maas_user, api_client, mocker
    ):
        self.user = maas_user
        self.client = api_client
        mocker.patch.object(vlan_signals_module, "post_commit_do")

    def test_handler_path(self):
        assert "/MAAS/api/2.0/rackcontrollers/rack-name/" == reverse(
            "rackcontroller_handler", args=["rack-name"]
        )

    @staticmethod
    def get_rack_uri(rack):
        """Get the API URI for `rack`."""
        return reverse("rackcontroller_handler", args=[rack.system_id])

    def test_PUT_updates_rack_controller(self):
        self.user.is_superuser = True
        self.user.save()
        rack = factory.make_RackController(
            owner=self.user,
            power_parameters={
                "power_address": (
                    f"qemu+ssh://user@{factory.make_ipv4_address()}/system"
                ),
                "power_id": factory.make_name("power_id"),
            },
        )
        zone = factory.make_zone()
        new_description = factory.make_name("description")
        response = self.client.put(
            self.get_rack_uri(rack),
            {"description": new_description, "zone": zone.name},
        )
        assert http.client.OK == response.status_code, (
            explain_unexpected_response(http.client.OK, response)
        )
        rack = reload_object(rack)
        assert zone.name == rack.zone.name
        assert new_description == rack.description

    def test_PUT_requires_admin(self):
        rack = factory.make_RackController(owner=self.user)
        response = self.client.put(self.get_rack_uri(rack), {})
        assert http.client.FORBIDDEN == response.status_code

    def test_POST_import_boot_images_import_to_rack_controllers(self):
        self.user.is_superuser = True
        self.user.save()
        rack = factory.make_RackController(owner=factory.make_User())
        response = self.client.post(
            self.get_rack_uri(rack), {"op": "import_boot_images"}
        )
        assert http.client.ACCEPTED == response.status_code, (
            explain_unexpected_response(http.client.ACCEPTED, response)
        )

    def test_POST_import_boot_images_denied_if_not_admin(self):
        rack = factory.make_RackController(owner=factory.make_User())
        response = self.client.post(
            self.get_rack_uri(rack), {"op": "import_boot_images"}
        )
        assert http.client.FORBIDDEN == response.status_code, (
            explain_unexpected_response(http.client.FORBIDDEN, response)
        )

    def test_GET_list_boot_images(self):
        factory.make_RegionController()
        rack = factory.make_RackController(owner=factory.make_User())
        resource = factory.make_usable_boot_resource(
            architecture="amd64/hwe-16.04",
            extra={"subarches": "hwe-p,hwe-t,hwe-16.04,hwe-16.10"},
        )
        self.user.is_superuser = True
        self.user.save()
        response = self.client.get(
            self.get_rack_uri(rack), {"op": "list_boot_images"}
        )
        assert http.client.OK == response.status_code, (
            explain_unexpected_response(http.client.OK, response)
        )
        ret = json_load_bytes(response.content)
        assert {"connected", "images", "status"} == ret.keys()
        image = ret["images"][0]
        assert image["name"] == resource.name
        assert sorted(image["subarches"]) == sorted(
            ["hwe-p", "hwe-t", "hwe-16.04", "hwe-16.10"]
        )

    def test_GET_list_boot_images_keeps_legacy_bootloader_names(self):
        factory.make_RegionController()
        rack = factory.make_RackController(owner=factory.make_User())

        bootloaders = [
            ("grub-efi-signed/uefi", "amd64/generic", "uefi"),
            ("grub-efi/uefi", "arm64/generic", "uefi"),
            (
                "grub-ieee1275/open-firmware",
                "ppc64el/generic",
                "open-firmware",
            ),
            ("pxelinux/pxe", "i386/generic", "pxe"),
        ]

        for name, arch, btype in bootloaders:
            factory.make_usable_boot_resource(
                rtype=BOOT_RESOURCE_TYPE.SYNCED,
                name=name,
                bootloader_type=btype,
                architecture=arch,
                image_filetype=BOOT_RESOURCE_FILE_TYPE.ARCHIVE_TAR_XZ,
            )
        self.user.is_superuser = True
        self.user.save()
        response = self.client.get(
            self.get_rack_uri(rack), {"op": "list_boot_images"}
        )
        assert http.client.OK == response.status_code, (
            explain_unexpected_response(http.client.OK, response)
        )
        ret = json_load_bytes(response.content)
        assert sorted([img["name"] for img in ret["images"]]) == sorted(
            [f"bootloader/{btype}" for (_, _, btype) in bootloaders]
        )

    def test_GET_list_boot_images_denied_if_not_admin(self):
        rack = factory.make_RackController(owner=factory.make_User())
        response = self.client.get(
            self.get_rack_uri(rack), {"op": "list_boot_images"}
        )
        assert http.client.FORBIDDEN == response.status_code, (
            explain_unexpected_response(http.client.FORBIDDEN, response)
        )

    def test_DELETE_cannot_delete_if_primary_rack(self):
        self.user.is_superuser = True
        self.user.save()
        vlan = factory.make_VLAN()
        rack = factory.make_RackController(vlan=vlan)
        vlan.dhcp_on = True
        vlan.primary_rack = rack
        vlan.save()
        response = self.client.delete(self.get_rack_uri(rack))
        assert http.client.BAD_REQUEST == response.status_code, (
            explain_unexpected_response(http.client.BAD_REQUEST, response)
        )

    def test_DELETE_delete_with_force(self):
        self.user.is_superuser = True
        self.user.save()
        vlan = factory.make_VLAN()
        factory.make_Subnet(vlan=vlan)
        rack = factory.make_RackController(vlan=vlan)
        vlan.dhcp_on = True
        vlan.primary_rack = rack
        vlan.save()
        response = self.client.delete(
            self.get_rack_uri(rack),
            QUERY_STRING=urlencode({"force": "true"}, doseq=True),
        )
        assert http.client.NO_CONTENT == response.status_code, (
            explain_unexpected_response(http.client.NO_CONTENT, response)
        )


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestRackControllersAPI:
    """Tests for /api/2.0/rackcontrollers/."""

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client, mocker):
        self.user = maas_user
        self.client = api_client
        mocker.patch.object(vlan_signals_module, "post_commit_do")

    @staticmethod
    def get_rack_uri():
        """Get the API URI for `rack`."""
        return reverse("rackcontrollers_handler")

    def test_handler_path(self):
        assert "/MAAS/api/2.0/rackcontrollers/" == reverse(
            "rackcontrollers_handler"
        )

    def test_read_returns_limited_fields(self):
        self.user.is_superuser = True
        self.user.save()
        factory.make_RackController(owner=self.user)
        response = self.client.get(reverse("rackcontrollers_handler"))
        parsed_result = json_load_bytes(response.content)

        assert {
            "system_id",
            "hostname",
            "description",
            "hardware_uuid",
            "domain",
            "fqdn",
            "architecture",
            "cpu_count",
            "cpu_speed",
            "memory",
            "swap_size",
            "osystem",
            "power_state",
            "power_type",
            "resource_uri",
            "distro_series",
            "interface_set",
            "ip_addresses",
            "zone",
            "status_action",
            "node_type",
            "node_type_name",
            "service_set",
            "current_commissioning_result_id",
            "current_testing_result_id",
            "current_installation_result_id",
            "version",
            "commissioning_status",
            "commissioning_status_name",
            "testing_status",
            "testing_status_name",
            "cpu_test_status",
            "cpu_test_status_name",
            "memory_test_status",
            "memory_test_status_name",
            "network_test_status",
            "network_test_status_name",
            "storage_test_status",
            "storage_test_status_name",
            "other_test_status",
            "other_test_status_name",
            "hardware_info",
            "tag_names",
            "interface_test_status",
            "interface_test_status_name",
        } == parsed_result[0].keys()

    def test_POST_import_boot_images_import_to_rack_controllers(self):
        self.user.is_superuser = True
        self.user.save()
        factory.make_RackController(owner=factory.make_User())
        response = self.client.post(
            self.get_rack_uri(), {"op": "import_boot_images"}
        )
        assert http.client.ACCEPTED == response.status_code, (
            explain_unexpected_response(http.client.ACCEPTED, response)
        )

    def test_POST_import_boot_images_denied_if_not_admin(self):
        factory.make_RackController(owner=factory.make_User())
        response = self.client.post(
            self.get_rack_uri(), {"op": "import_boot_images"}
        )
        assert http.client.FORBIDDEN == response.status_code, (
            explain_unexpected_response(http.client.FORBIDDEN, response)
        )

    def test_GET_describe_power_types(self, mocker):
        get_all_power_types = mocker.patch.object(
            rackcontrollers, "get_all_power_types"
        )
        self.user.is_superuser = True
        self.user.save()
        response = self.client.get(
            self.get_rack_uri(), {"op": "describe_power_types"}
        )
        assert http.client.OK == response.status_code, (
            explain_unexpected_response(http.client.OK, response)
        )
        get_all_power_types.assert_called_once_with()

    def test_GET_describe_power_types_denied_if_not_admin(self, mocker):
        get_all_power_types = mocker.patch.object(
            rackcontrollers, "get_all_power_types"
        )
        response = self.client.get(
            self.get_rack_uri(), {"op": "describe_power_types"}
        )
        assert http.client.FORBIDDEN == response.status_code, (
            explain_unexpected_response(http.client.FORBIDDEN, response)
        )
        get_all_power_types.assert_not_called()


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestRegionControllerAPIOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_update_requires_can_edit_controllers(self):
        self.openfga_client.can_edit_controllers.return_value = True
        rack = factory.make_RackController(
            power_parameters={
                "power_address": (
                    f"qemu+ssh://user@{factory.make_ipv4_address()}/system"
                ),
                "power_id": factory.make_name("power_id"),
            }
        )
        response = self.client.put(
            reverse("rackcontroller_handler", args=[rack.system_id]), {}
        )
        assert http.client.OK == response.status_code
        self.openfga_client.can_edit_controllers.assert_called_once_with(
            self.user
        )

    def test_list_boot_images_requires_can_edit_controllers(self):
        self.openfga_client.can_edit_controllers.return_value = True
        rack = factory.make_RackController()
        response = self.client.post(
            reverse("rackcontroller_handler", args=[rack.system_id]),
            {"op": "import_boot_images"},
        )
        assert http.client.ACCEPTED == response.status_code
        self.openfga_client.can_edit_controllers.assert_called_once_with(
            self.user
        )

    def test_list_boot_images_requires_can_view_controllers(self):
        self.openfga_client.can_view_controllers.return_value = True
        rack = factory.make_RackController()
        response = self.client.get(
            reverse("rackcontroller_handler", args=[rack.system_id]),
            {"op": "list_boot_images"},
        )
        assert http.client.OK == response.status_code
        self.openfga_client.can_view_controllers.assert_called_once_with(
            self.user
        )

    def test_delete_requires_can_edit_controllers(self):
        self.openfga_client.can_edit_controllers.return_value = True
        rack = factory.make_RackController()
        response = self.client.delete(
            reverse("rackcontroller_handler", args=[rack.system_id])
        )
        assert http.client.NO_CONTENT == response.status_code
        self.openfga_client.can_edit_controllers.assert_called_once_with(
            self.user
        )


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestGetAllPowerTypesFIPSFields:
    """Tests that get_all_power_types() annotates each entry with FIPS fields."""

    def test_all_power_types_have_fips_fields(self):
        power_types = get_all_power_types()
        for pt in power_types:
            assert "fips_supported" in pt, (
                f"{pt['name']} missing fips_supported"
            )
            assert "fips_unsupported_reason" in pt, (
                f"{pt['name']} missing fips_unsupported_reason"
            )
            assert isinstance(pt["fips_supported"], bool)
            assert isinstance(pt["fips_unsupported_reason"], (str, type(None)))

    def test_ipmi_is_fips_supported(self):
        power_types = get_all_power_types()
        ipmi = next(pt for pt in power_types if pt["name"] == "ipmi")
        assert ipmi["fips_supported"]
        assert ipmi["fips_unsupported_reason"] is None

    def test_apc_is_not_fips_supported(self):
        power_types = get_all_power_types()
        apc = next(pt for pt in power_types if pt["name"] == "apc")
        assert not apc["fips_supported"]
        assert apc["fips_unsupported_reason"] is not None
