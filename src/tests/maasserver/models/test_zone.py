# Copyright 2013-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test Zone objects."""

import pytest

from maasserver.enum import NODE_TYPE
from maasserver.models.defaultresource import DefaultResource
from maasserver.models.zone import Zone
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestZoneManager:
    """Tests for `Zone` manager."""

    DEFAULT_ZONE_NAME = "default"

    def test_get_default_zone_returns_default_zone(self):
        assert (
            self.DEFAULT_ZONE_NAME
            == DefaultResource.objects.get_default_zone().name
        )

    def test_get_default_zone_ignores_other_zones(self):
        factory.make_Zone()
        assert (
            self.DEFAULT_ZONE_NAME
            == DefaultResource.objects.get_default_zone().name
        )

    def test_get_renamed_default_zone(self):
        default_zone = Zone.objects.get(name=self.DEFAULT_ZONE_NAME)
        default_zone.name = "myzone"
        default_zone.save()

        assert DefaultResource.objects.get_default_zone().name == "myzone"


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestZone:
    """Tests for :class:`Zone`."""

    def test_init(self):
        node1 = factory.make_Node()
        node2 = factory.make_Node()
        name = factory.make_name("name")
        description = factory.make_name("description")

        zone = Zone(name=name, description=description)
        zone.save()
        zone.node_set.add(node1)
        zone.node_set.add(node2)

        assert (
            set(zone.node_set.all()),
            zone.name,
            zone.description,
            node1.zone,
            node2.zone,
        ) == ({node1, node2}, name, description, zone, zone)

    def test_delete_deletes_zone(self):
        zone = factory.make_Zone()
        zone.delete()
        assert reload_object(zone) is None

    def test_delete_severs_link_to_nodes(self):
        zone = factory.make_Zone()
        node = factory.make_Node(zone=zone)
        zone.delete()
        assert reload_object(zone) is None
        node = reload_object(node)
        assert node is not None
        assert DefaultResource.objects.get_default_zone() == node.zone

    def test_nodes_only_set(self):
        """zone.node_only_set has only type node."""
        zone = factory.make_Zone()
        node1 = factory.make_Node(zone=zone, node_type=NODE_TYPE.MACHINE)
        node2 = factory.make_Node(zone=zone, node_type=NODE_TYPE.MACHINE)
        node3 = factory.make_Node(zone=zone, node_type=NODE_TYPE.MACHINE)
        device1 = factory.make_Node(zone=zone, node_type=NODE_TYPE.DEVICE)
        device2 = factory.make_Node(zone=zone, node_type=NODE_TYPE.DEVICE)
        rack_controller = factory.make_Node(
            zone=zone, node_type=NODE_TYPE.RACK_CONTROLLER
        )
        assert zone.node_only_set.count() == 3
        assert node1 in zone.node_only_set
        assert node2 in zone.node_only_set
        assert node3 in zone.node_only_set
        assert device1 not in zone.node_only_set
        assert device2 not in zone.node_only_set
        assert rack_controller not in zone.node_only_set

    def test_devices_only_set(self):
        """zone.devices_only_set has only type device."""
        zone = factory.make_Zone()
        node1 = factory.make_Node(zone=zone, node_type=NODE_TYPE.MACHINE)
        node2 = factory.make_Node(zone=zone, node_type=NODE_TYPE.MACHINE)
        node3 = factory.make_Node(zone=zone, node_type=NODE_TYPE.MACHINE)
        device1 = factory.make_Node(zone=zone, node_type=NODE_TYPE.DEVICE)
        device2 = factory.make_Node(zone=zone, node_type=NODE_TYPE.DEVICE)
        rack_controller = factory.make_Node(
            zone=zone, node_type=NODE_TYPE.RACK_CONTROLLER
        )
        assert zone.device_only_set.count() == 2
        assert node1 not in zone.device_only_set
        assert node2 not in zone.device_only_set
        assert node3 not in zone.device_only_set
        assert device1 in zone.device_only_set
        assert device2 in zone.device_only_set
        assert rack_controller not in zone.node_only_set

    def test_rack_controllers_only_set(self):
        """zone.rack_controllers_only_set has only type rack_controller."""
        zone = factory.make_Zone()
        node1 = factory.make_Node(zone=zone, node_type=NODE_TYPE.MACHINE)
        node2 = factory.make_Node(zone=zone, node_type=NODE_TYPE.MACHINE)
        node3 = factory.make_Node(zone=zone, node_type=NODE_TYPE.MACHINE)
        device1 = factory.make_Node(zone=zone, node_type=NODE_TYPE.DEVICE)
        device2 = factory.make_Node(zone=zone, node_type=NODE_TYPE.DEVICE)
        rack_controller = factory.make_Node(
            zone=zone, node_type=NODE_TYPE.RACK_CONTROLLER
        )
        assert zone.device_only_set.count() == 2
        assert node1 not in zone.rack_controller_only_set
        assert node2 not in zone.rack_controller_only_set
        assert node3 not in zone.rack_controller_only_set
        assert device1 not in zone.rack_controller_only_set
        assert device2 not in zone.rack_controller_only_set
        assert rack_controller in zone.rack_controller_only_set
