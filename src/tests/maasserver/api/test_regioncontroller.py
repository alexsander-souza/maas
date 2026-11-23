# Copyright 2016-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import http.client

from django.urls import reverse
from django.utils.http import urlencode
import pytest

from maasserver.enum import NODE_TYPE
from maasserver.testing.api import explain_unexpected_response
from maasserver.testing.factory import factory
from maasserver.utils.converters import json_load_bytes
from maasserver.utils.orm import reload_object
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestRegionControllerAPI:
    """Tests for /api/2.0/regioncontrollers/<region>/."""

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_handler_path(self):
        assert "/MAAS/api/2.0/regioncontrollers/region-name/" == reverse(
            "regioncontroller_handler", args=["region-name"]
        )

    @staticmethod
    def get_region_uri(region):
        """Get the API URI for `region`."""
        return reverse("regioncontroller_handler", args=[region.system_id])

    def test_PUT_updates_region_controller(self):
        self.user.is_superuser = True
        self.user.save()
        region = factory.make_RegionController(
            power_parameters={
                "power_address": (
                    f"qemu+ssh://user@{factory.make_ipv4_address()}/system"
                ),
                "power_id": factory.make_name("power_id"),
            }
        )
        zone = factory.make_zone()
        new_description = factory.make_name("description")
        response = self.client.put(
            self.get_region_uri(region),
            {"description": new_description, "zone": zone.name},
        )
        assert http.client.OK == response.status_code
        region = reload_object(region)
        assert zone.name == region.zone.name
        assert new_description == region.description

    def test_PUT_requires_admin(self):
        region = factory.make_RegionController()
        response = self.client.put(self.get_region_uri(region), {})
        assert http.client.FORBIDDEN == response.status_code

    def test_DELETE_delete_with_force(self):
        self.user.is_superuser = True
        self.user.save()
        vlan = factory.make_VLAN()
        subnet = factory.make_Subnet(vlan=vlan)
        region = factory.make_Node_with_Interface_on_Subnet(
            node_type=NODE_TYPE.REGION_CONTROLLER, subnet=subnet, vlan=vlan
        )
        response = self.client.delete(
            self.get_region_uri(region),
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
class TestRegionControllersAPI:
    """Tests for /api/2.0/regioncontrollers/."""

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    @staticmethod
    def get_region_uri():
        """Get the API URI for `region`."""
        return reverse("regioncontrollers_handler")

    def test_handler_path(self):
        assert "/MAAS/api/2.0/regioncontrollers/" == reverse(
            "regioncontrollers_handler"
        )

    def test_read_returns_limited_fields(self):
        self.user.is_superuser = True
        self.user.save()
        factory.make_RegionController()
        response = self.client.get(reverse("regioncontrollers_handler"))
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
        region = factory.make_RegionController(
            power_parameters={
                "power_address": (
                    f"qemu+ssh://user@{factory.make_ipv4_address()}/system"
                ),
                "power_id": factory.make_name("power_id"),
            }
        )
        response = self.client.put(
            reverse("regioncontroller_handler", args=[region.system_id]), {}
        )
        assert http.client.OK == response.status_code
        self.openfga_client.can_edit_controllers.assert_called_once_with(
            self.user
        )

    def test_delete_requires_can_edit_controllers(self):
        self.openfga_client.can_edit_controllers.return_value = True
        region = factory.make_RegionController()
        response = self.client.delete(
            reverse("regioncontroller_handler", args=[region.system_id])
        )
        assert http.client.NO_CONTENT == response.status_code
        self.openfga_client.can_edit_controllers.assert_called_once_with(
            self.user
        )
