# Copyright 2017-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import http.client

from django.urls import reverse
import pytest

from maasserver.enum import NODE_DEVICE_BUS_CHOICES
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object
from metadataserver.enum import HARDWARE_TYPE_CHOICES


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNodeDevicesAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_hander_path(self):
        node = factory.make_Node()
        assert reverse("node_devices_handler", args=[node.system_id]) == (
            f"/MAAS/api/2.0/nodes/{node.system_id}/devices/"
        )

    def test_GET(self):
        node = factory.make_Node()
        node_devices = [
            factory.make_NodeDevice(node=node),
            factory.make_NodeDevice(node=node),
        ]
        response = self.client.get(
            f"/MAAS/api/2.0/nodes/{node.system_id}/devices/",
        )
        assert response.status_code == http.client.OK
        assert sorted(
            node_device.id for node_device in node_devices
        ) == sorted(node_device["id"] for node_device in response.json())


@pytest.mark.parametrize(
    "key,choices",
    [
        pytest.param("bus", NODE_DEVICE_BUS_CHOICES, id="filter=bus"),
        pytest.param(
            "hardware_type", HARDWARE_TYPE_CHOICES, id="filter=hardware_type"
        ),
        pytest.param(
            "vendor_id",
            lambda: factory.make_hex_string(4),
            id="filter=vendor_id",
        ),
        pytest.param(
            "product_id",
            lambda: factory.make_hex_string(4),
            id="filter=product_id",
        ),
        pytest.param(
            "vendor_name", factory.make_name, id="filter=vendor_name"
        ),
        pytest.param(
            "product_name", factory.make_name, id="filter=product_name"
        ),
        pytest.param(
            "commissioning_driver",
            factory.make_name,
            id="filter=commissioning_driver",
        ),
    ],
)
@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNodeDevicesAPIFilter:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client
        self.node = factory.make_Node()
        self.uri = reverse("node_devices_handler", args=[self.node.system_id])

    def test_GET_filter(self, key, choices):
        if callable(choices):
            choice1 = choices()
        else:
            choice1 = factory.pick_choice(choices)
        node_device = factory.make_NodeDevice(node=self.node, **{key: choice1})
        # create a device with different criteria
        if callable(choices):
            choice2 = choices()
        else:
            choice2 = factory.pick_choice(choices, but_not=[choice1])
        factory.make_NodeDevice(node=self.node, **{key: choice2})

        response = self.client.get(self.uri, {key: choice1})
        assert response.status_code == http.client.OK
        assert [node_device.id] == [
            node_device["id"] for node_device in response.json()
        ]


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNodeDeviceAPI:
    """Tests for /api/2.0/nodes/<system_id>/device/<id>."""

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def get_node_device_uri(self, node_device, force_id=False):
        """Return the script's URI on the API."""
        if force_id or factory.pick_bool():
            id = node_device.id
        elif node_device.is_pcie:
            id = node_device.pci_address
        elif node_device.is_usb:
            id = f"{node_device.bus_number}:{node_device.device_number}"
        return reverse(
            "node_device_handler",
            args=[node_device.node_config.node.system_id, id],
        )

    def test_hander_path(self):
        node_device = factory.make_NodeDevice()
        assert (
            "/MAAS/api/2.0/nodes/"
            f"{node_device.node_config.node.system_id}/devices/{node_device.id}/"
        ) == self.get_node_device_uri(node_device, True)

    def test_GET(self):
        node_device = factory.make_NodeDevice()

        response = self.client.get(self.get_node_device_uri(node_device))
        assert response.status_code == http.client.OK
        parsed_result = response.json()

        assert {
            "id": node_device.id,
            "bus": node_device.bus,
            "bus_name": node_device.get_bus_display(),
            "hardware_type": node_device.hardware_type,
            "hardware_type_name": node_device.get_hardware_type_display(),
            "system_id": node_device.node_config.node.system_id,
            "numa_node": node_device.numa_node.index,
            "physical_blockdevice": None,
            "physical_interface": None,
            "vendor_id": node_device.vendor_id,
            "product_id": node_device.product_id,
            "vendor_name": node_device.vendor_name,
            "product_name": node_device.product_name,
            "commissioning_driver": node_device.commissioning_driver,
            "bus_number": node_device.bus_number,
            "device_number": node_device.device_number,
            "pci_address": node_device.pci_address,
            "resource_uri": self.get_node_device_uri(node_device, True),
        } == parsed_result

    def test_DELETE(self):
        self.user.is_superuser = True
        self.user.save()
        node_device = factory.make_NodeDevice()

        response = self.client.delete(self.get_node_device_uri(node_device))
        assert response.status_code == http.client.NO_CONTENT
        assert reload_object(node_device) is None

    def test_DELETE_admin_only(self):
        node_device = factory.make_NodeDevice()

        response = self.client.delete(self.get_node_device_uri(node_device))
        assert response.status_code == http.client.FORBIDDEN
        assert reload_object(node_device) is not None
