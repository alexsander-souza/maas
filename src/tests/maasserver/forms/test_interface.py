# Copyright 2015-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from collections import Counter
import random

from django.core.exceptions import ValidationError
import pytest

from maasserver.enum import BRIDGE_TYPE_CHOICES, INTERFACE_TYPE, IPADDRESS_TYPE
from maasserver.forms.interface import (
    AcquiredBridgeInterfaceForm,
    BOND_LACP_RATE_CHOICES,
    BOND_MODE_CHOICES,
    BOND_XMIT_HASH_POLICY_CHOICES,
    BondInterfaceForm,
    BridgeInterfaceForm,
    ControllerInterfaceForm,
    DeployedInterfaceForm,
    InterfaceForm,
    PhysicalInterfaceForm,
    VLANInterfaceForm,
)
from maasserver.testing.factory import factory
from maasserver.utils.forms import compose_invalid_choice_text
from maasserver.utils.orm import post_commit_hooks


@pytest.mark.parametrize(
    "iface_type,form",
    [
        (INTERFACE_TYPE.PHYSICAL, PhysicalInterfaceForm),
        (INTERFACE_TYPE.BOND, BondInterfaceForm),
        (INTERFACE_TYPE.VLAN, VLANInterfaceForm),
    ],
    ids=["physical", "bond", "vlan"],
)
class TestGetInterfaceForm:
    def test_get_interface_form_returns_form(self, iface_type, form):
        assert form is InterfaceForm.get_interface_form(iface_type)


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestGetInterfaceFormError:
    def test_get_interface_form_returns_form(self):
        with pytest.raises(ValidationError):
            InterfaceForm.get_interface_form(factory.make_name())


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "factory"
)
class TestControllerInterfaceForm:
    @pytest.mark.parametrize(
        "maker",
        [
            factory.make_RegionController,
            factory.make_RackController,
            factory.make_RegionRackController,
        ],
        ids=["region", "rack", "region_rack"],
    )
    def test_edits_interface(self, maker):
        node = maker()
        original_interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=node
        )
        new_vlan = factory.make_VLAN(vid=33)
        form = ControllerInterfaceForm(
            instance=original_interface, data={"vlan": new_vlan.id}
        )
        assert form.is_valid(), dict(form.errors)
        interface = form.save()
        assert interface.name == original_interface.name
        assert interface.vlan == new_vlan
        assert interface.enabled == original_interface.enabled

    @pytest.mark.parametrize(
        "maker",
        [
            factory.make_RegionController,
            factory.make_RackController,
            factory.make_RegionRackController,
        ],
        ids=["region", "rack", "region_rack"],
    )
    def test_allows_no_vlan(self, maker):
        node = maker()
        original_interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=node
        )
        form = ControllerInterfaceForm(
            instance=original_interface, data={"vlan": None}
        )
        assert form.is_valid(), dict(form.errors)
        interface = form.save()
        assert interface.name == original_interface.name
        assert interface.vlan is None
        assert interface.enabled == original_interface.enabled

    @pytest.mark.parametrize(
        "maker",
        [
            factory.make_RegionController,
            factory.make_RackController,
            factory.make_RegionRackController,
        ],
        ids=["region", "rack", "region_rack"],
    )
    def test_updates_interface_links(self, maker):
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, name="eth0", link_connected=False
        )
        new_link_connected = True
        new_link_speed = random.randint(10, 1000)
        new_interface_speed = random.randint(new_link_speed, 1000)
        form = ControllerInterfaceForm(
            instance=interface,
            data={
                "link_connected": new_link_connected,
                "link_speed": new_link_speed,
                "interface_speed": new_interface_speed,
            },
        )
        assert form.is_valid(), dict(form.errors)
        interface = form.save()
        assert interface.interface_speed == new_interface_speed
        assert interface.link_connected == new_link_connected
        assert interface.link_speed == new_link_speed

    def test_updates_interface_errors_for_not_link_connected_and_speed(self):
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, name="eth0", link_connected=False
        )
        new_mac = factory.make_mac_address()
        new_link_speed = random.randint(10, interface.interface_speed)
        form = ControllerInterfaceForm(
            instance=interface,
            data={"mac_address": new_mac, "link_speed": new_link_speed},
        )
        assert not form.is_valid(), dict(form.errors)
        assert (
            "link_speed cannot be set when link_connected is false."
            == form.errors["__all__"][0]
        )


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestDeployedInterfaceForm:
    def test_updates_interface(self):
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, name="eth0", link_connected=False
        )
        new_name = "eth1"
        new_mac = factory.make_mac_address()
        new_link_connected = True
        new_link_speed = random.randint(10, 1000)
        new_interface_speed = random.randint(new_link_speed, 1000)
        form = DeployedInterfaceForm(
            instance=interface,
            data={
                "name": new_name,
                "mac_address": new_mac,
                "link_connected": new_link_connected,
                "link_speed": new_link_speed,
                "interface_speed": new_interface_speed,
            },
        )
        assert form.is_valid(), dict(form.errors)
        interface = form.save()
        assert interface.name == new_name
        assert interface.mac_address == new_mac
        assert interface.link_connected == new_link_connected
        assert interface.link_speed == new_link_speed
        assert interface.interface_speed == new_interface_speed

    def test_updates_interface_errors_for_not_link_connected_and_speed(self):
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, name="eth0", link_connected=False
        )
        new_name = "eth1"
        new_mac = factory.make_mac_address()
        new_link_speed = random.randint(10, interface.interface_speed)
        form = DeployedInterfaceForm(
            instance=interface,
            data={
                "name": new_name,
                "mac_address": new_mac,
                "link_speed": new_link_speed,
            },
        )
        assert not form.is_valid(), dict(form.errors)
        assert (
            "link_speed cannot be set when link_connected is false."
            == form.errors["__all__"][0]
        )


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestPhysicalInterfaceForm:
    def test_updates_interface(self):
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, name="eth0", link_connected=False
        )
        node = interface.node_config.node
        new_numa_node = factory.make_NUMANode(node=node)
        new_name = "eth1"
        new_mac = factory.make_mac_address()
        new_link_connected = True
        new_link_speed = random.randint(10, 1000)
        new_interface_speed = random.randint(new_link_speed, 1000)
        form = PhysicalInterfaceForm(
            instance=interface,
            data={
                "name": new_name,
                "mac_address": new_mac,
                "link_connected": new_link_connected,
                "link_speed": new_link_speed,
                "interface_speed": new_interface_speed,
                "numa_node": new_numa_node.index,
            },
        )
        assert form.is_valid(), dict(form.errors)
        interface = form.save()
        assert interface.name == new_name
        assert interface.mac_address == new_mac
        assert interface.link_connected == new_link_connected
        assert interface.link_speed == new_link_speed
        assert interface.interface_speed == new_interface_speed
        assert interface.numa_node == new_numa_node

    def test_updates_interface_errors_for_not_link_connected_and_speed(self):
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, name="eth0", link_connected=False
        )
        new_name = "eth1"
        new_mac = factory.make_mac_address()
        new_link_speed = random.randint(10, interface.interface_speed)
        form = PhysicalInterfaceForm(
            instance=interface,
            data={
                "name": new_name,
                "mac_address": new_mac,
                "link_speed": new_link_speed,
            },
        )
        assert not form.is_valid(), dict(form.errors)
        assert (
            "link_speed cannot be set when link_connected is false."
            == form.errors["__all__"][0]
        )

    def test_creates_physical_interface(self):
        node = factory.make_Node()
        mac_address = factory.make_mac_address()
        interface_name = "eth0"
        vlan = factory.make_VLAN()
        tags = [factory.make_name("tag") for _ in range(3)]
        form = PhysicalInterfaceForm(
            node=node,
            data={
                "name": interface_name,
                "mac_address": mac_address,
                "vlan": vlan.id,
                "tags": ",".join(tags),
            },
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert interface.node_config == node.current_config
        assert interface.mac_address == mac_address
        assert interface.name == interface_name
        assert interface.type == INTERFACE_TYPE.PHYSICAL
        assert interface.tags == tags
        assert interface.numa_node == node.default_numanode

        assert Counter([]) == Counter(interface.parents.all())

    def test_creates_physical_interface_with_numa_node(self):
        node = factory.make_Node()
        numa_node = factory.make_NUMANode(node=node)
        mac_address = factory.make_mac_address()
        interface_name = "eth0"
        vlan = factory.make_VLAN()
        tags = [factory.make_name("tag") for _ in range(3)]
        form = PhysicalInterfaceForm(
            node=node,
            data={
                "name": interface_name,
                "mac_address": mac_address,
                "vlan": vlan.id,
                "tags": ",".join(tags),
                "numa_node": numa_node.index,
            },
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert interface.node_config.node == node
        assert interface.numa_node == numa_node

    def test_creates_physical_interface_generates_name(self, mocker):
        node = factory.make_Node()
        interface_name = factory.make_name("eth")
        mocker.patch.object(
            node, "get_next_ifname"
        ).return_value = interface_name
        mac_address = factory.make_mac_address()
        fabric = factory.make_Fabric()
        vlan = fabric.get_default_vlan()
        tags = [factory.make_name("tag") for _ in range(3)]
        form = PhysicalInterfaceForm(
            node=node,
            data={
                "mac_address": mac_address,
                "vlan": vlan.id,
                "tags": ",".join(tags),
            },
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert interface.node_config == node.current_config
        assert interface.mac_address == mac_address
        assert interface.name == interface_name
        assert interface.type == INTERFACE_TYPE.PHYSICAL
        assert interface.tags == tags
        assert interface.numa_node == node.default_numanode
        assert Counter([]) == Counter(interface.parents.all())

    def test_creates_physical_interface_disconnected(self):
        node = factory.make_Node()
        mac_address = factory.make_mac_address()
        interface_name = "eth0"
        tags = [factory.make_name("tag") for _ in range(3)]
        form = PhysicalInterfaceForm(
            node=node,
            data={
                "name": interface_name,
                "mac_address": mac_address,
                "tags": ",".join(tags),
            },
        )
        assert form.is_valid(), dict(form.errors)
        interface = form.save()
        assert interface.node_config == node.current_config
        assert interface.mac_address == mac_address
        assert interface.name == interface_name
        assert interface.type == INTERFACE_TYPE.PHYSICAL
        assert interface.tags == tags
        assert interface.vlan is None
        assert interface.numa_node == node.default_numanode
        assert Counter([]) == Counter(interface.parents.all())

    def test_creates_physical_interface_normalises_mac_address(self):
        node = factory.make_Node()
        form = PhysicalInterfaceForm(
            node=node,
            data={
                "name": "eth0",
                "mac_address": "AA:BB:CC:DD:EE:FF",
            },
        )
        assert form.is_valid(), dict(form.errors)
        with post_commit_hooks:
            interface = form.save()
        assert interface.mac_address == "aa:bb:cc:dd:ee:ff"

    def test_rejects_duplicate_mac_address_with_different_case(self):
        node = factory.make_Node()
        factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            node=node,
            name="eth0",
            mac_address="aa:bb:cc:dd:ee:ff",
        )
        form = PhysicalInterfaceForm(
            node=node,
            data={
                "name": "eth1",
                "mac_address": "AA:BB:CC:DD:EE:FF",
            },
        )
        assert not form.is_valid(), dict(form.errors)
        assert "mac_address" in form.errors
        assert (
            "This MAC address is already in use"
            in form.errors["mac_address"][0]
        )

    def test_create_ensures_link_up(self):
        node = factory.make_Node()
        mac_address = factory.make_mac_address()
        interface_name = "eth0"
        vlan = factory.make_VLAN()
        tags = [factory.make_name("tag") for _ in range(3)]
        form = PhysicalInterfaceForm(
            node=node,
            data={
                "name": interface_name,
                "mac_address": mac_address,
                "vlan": vlan.id,
                "tags": ",".join(tags),
            },
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()
        assert (
            interface.ip_addresses.filter(alloc_type=IPADDRESS_TYPE.STICKY)
            is not None
        )

    def test_requires_mac_address(self):
        interface_name = "eth0"
        vlan = factory.make_VLAN()
        form = PhysicalInterfaceForm(
            node=factory.make_Node(),
            data={"name": interface_name, "vlan": vlan.id},
        )
        assert not form.is_valid(), dict(form.errors)
        assert {"mac_address"} == form.errors.keys(), form.errors
        assert "This field is required." in form.errors["mac_address"][0]

    def test_rejects_interface_with_duplicate_name(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        mac_address = factory.make_mac_address()
        form = PhysicalInterfaceForm(
            node=interface.node_config.node,
            data={
                "name": interface.name,
                "mac_address": mac_address,
                "vlan": interface.vlan.id,
            },
        )
        assert not form.is_valid(), dict(form.errors)
        assert {"name"} == form.errors.keys(), form.errors
        assert (
            "already has an interface named '%s'." % interface.name
            in form.errors["name"][0]
        )

    def test_rejects_interface_with_numa_node_for_device(self):
        node = factory.make_Device()
        form = PhysicalInterfaceForm(
            node=node,
            data={"mac_address": factory.make_mac_address(), "numa_node": 2},
        )
        assert not form.is_valid()
        assert form.errors == {
            "numa_node": [
                "Only interfaces for machines are linked to a NUMA node"
            ]
        }

    def test_allows_interface_on_tagged_vlan_for_device(self):
        device = factory.make_Device()
        fabric = factory.make_Fabric()
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            node=device,
            vlan=fabric.get_default_vlan(),
        )
        vlan = factory.make_VLAN(fabric=fabric)
        mac_address = factory.make_mac_address()
        form = PhysicalInterfaceForm(
            node=device,
            data={
                "name": factory.make_name("eth"),
                "mac_address": mac_address,
                "vlan": vlan.id,
            },
        )
        assert form.is_valid(), dict(form.errors)
        with post_commit_hooks:
            interface = form.save()
        assert vlan == interface.vlan

    def test_rejects_parents(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        vlan = factory.make_VLAN()
        form = PhysicalInterfaceForm(
            node=parent.node_config.node,
            data={
                "name": factory.make_name("eth"),
                "mac_address": factory.make_mac_address(),
                "vlan": vlan.id,
                "parents": [parent.id],
            },
        )
        assert not form.is_valid(), dict(form.errors)
        assert {"parents"} == form.errors.keys(), form.errors
        assert (
            "A physical interface cannot have parents."
            in form.errors["parents"][0]
        )

    def test_edits_interface(self):
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, name="eth0"
        )
        new_name = "eth1"
        new_vlan = factory.make_VLAN(vid=33)
        form = PhysicalInterfaceForm(
            instance=interface,
            data={
                "name": new_name,
                "vlan": new_vlan.id,
                "enabled": False,
                "tags": "",
            },
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()
        assert interface.name == new_name
        assert interface.vlan == new_vlan
        assert not interface.enabled
        assert interface.tags == []
        assert Counter([]) == Counter(interface.parents.all())

    def test_edits_doesnt_overwrite_name(self):
        original_interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, name="eth0"
        )
        new_fabric = factory.make_Fabric()
        new_vlan = new_fabric.get_default_vlan()
        form = PhysicalInterfaceForm(
            instance=original_interface,
            data={"vlan": new_vlan.id, "enabled": False, "tags": ""},
        )
        assert form.is_valid(), dict(form.errors)
        interface = form.save()
        assert interface.name == original_interface.name
        assert interface.vlan == new_vlan
        assert not interface.enabled
        assert interface.tags == []
        assert Counter([]) == Counter(interface.parents.all())

    def test_edits_interface_disconnected(self):
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, name="eth0"
        )
        new_name = "eth1"
        form = PhysicalInterfaceForm(
            instance=interface,
            data={
                "name": new_name,
                "vlan": None,
                "enabled": False,
                "tags": "",
            },
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert interface.name == new_name
        assert interface.vlan is None
        assert not interface.enabled
        assert interface.tags == []
        assert Counter([]) == Counter(interface.parents.all())

    def test_create_sets_interface_parameters(self):
        node = factory.make_Node()
        mac_address = factory.make_mac_address()
        interface_name = "eth0"
        vlan = factory.make_VLAN()
        tags = [factory.make_name("tag") for _ in range(3)]
        mtu = random.randint(1000, 2000)
        accept_ra = factory.pick_bool()
        form = PhysicalInterfaceForm(
            node=node,
            data={
                "name": interface_name,
                "mac_address": mac_address,
                "vlan": vlan.id,
                "tags": ",".join(tags),
                "mtu": mtu,
                "accept_ra": accept_ra,
            },
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()
        assert {"mtu": mtu, "accept-ra": accept_ra} == interface.params

    def test_update_doesnt_change_interface_parameters(self):
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, name="eth0"
        )
        mtu = random.randint(1000, 2000)
        accept_ra = factory.pick_bool()
        interface.params = {
            "mtu": mtu,
            "accept-ra": accept_ra,
        }
        new_name = "eth1"
        new_vlan = factory.make_VLAN(vid=33)
        form = PhysicalInterfaceForm(
            instance=interface,
            data={
                "name": new_name,
                "vlan": new_vlan.id,
                "enabled": False,
                "tags": "",
            },
        )
        assert form.is_valid(), dict(form.errors)
        with post_commit_hooks:
            interface = form.save()
        assert {"mtu": mtu, "accept-ra": accept_ra} == interface.params

    def test_update_does_change_interface_parameters(self):
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, name="eth0"
        )
        mtu = random.randint(1000, 2000)
        accept_ra = factory.pick_bool()
        interface.params = {
            "mtu": mtu,
            "accept-ra": accept_ra,
        }
        new_mtu = random.randint(1000, 2000)
        new_accept_ra = not accept_ra
        form = PhysicalInterfaceForm(
            instance=interface,
            data={
                "mtu": new_mtu,
                "accept_ra": new_accept_ra,
            },
        )
        assert form.is_valid(), dict(form.errors)
        interface = form.save()
        assert {
            "mtu": new_mtu,
            "accept-ra": new_accept_ra,
        } == interface.params

    def test_update_allows_clearing_interface_parameters(self):
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, name="eth0"
        )
        mtu = random.randint(1000, 2000)
        accept_ra = factory.pick_bool()
        interface.params = {
            "mtu": mtu,
            "accept-ra": accept_ra,
        }
        form = PhysicalInterfaceForm(
            instance=interface,
            data={"mtu": "", "accept_ra": ""},
        )
        assert form.is_valid(), dict(form.errors)
        interface = form.save()
        assert {} == interface.params

    def test_update_allows_rack_controller_with_numa_node(self):
        rack_controller = factory.make_RackController()
        numa = factory.make_NUMANode(node=rack_controller)
        iface = factory.make_Interface(node=rack_controller)
        ip = factory.make_ip_address()
        form = PhysicalInterfaceForm(
            instance=iface,
            data={
                "ip_address": ip,
                "numa_node": numa.index,
            },
        )
        assert form.is_valid(), form.errors


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestVLANInterfaceForm:
    def test_creates_vlan_interface(self):
        vlan = factory.make_VLAN(vid=10)
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, vlan=vlan)
        form = VLANInterfaceForm(
            node=parent.node_config.node,
            data={"name": "myvlan", "vlan": vlan.id, "parents": [parent.id]},
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert "myvlan" == interface.name
        assert INTERFACE_TYPE.VLAN == interface.type
        assert vlan == interface.vlan
        assert Counter([parent]) == Counter(interface.parents.all())

    def test_creates_vlan_interface_generates_name(self):
        fabric = factory.make_Fabric()
        vlan = factory.make_VLAN(fabric=fabric, vid=10)
        parent = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            name="eth42",
            vlan=fabric.get_default_vlan(),
        )
        form = VLANInterfaceForm(
            node=parent.node_config.node,
            data={"vlan": vlan.id, "parents": [parent.id]},
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()
        assert "eth42.10" == interface.name

    def test_create_ensures_link_up(self):
        vlan = factory.make_VLAN(vid=10)
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, vlan=vlan)
        form = VLANInterfaceForm(
            node=parent.node_config.node,
            data={"vlan": vlan.id, "parents": [parent.id]},
        )
        assert form.is_valid(), dict(form.errors)
        with post_commit_hooks:
            interface = form.save()
        assert (
            interface.ip_addresses.filter(alloc_type=IPADDRESS_TYPE.STICKY)
            is not None
        )

    def test_create_rejects_interface_without_vlan(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        form = VLANInterfaceForm(
            node=parent.node_config.node, data={"parents": [parent.id]}
        )
        assert not form.is_valid(), dict(form.errors)
        assert {"vlan"} == form.errors.keys(), form.errors
        assert (
            "A VLAN interface must be connected to a tagged VLAN."
            in form.errors["vlan"][0]
        )

    def test_rejects_interface_with_duplicate_name(self):
        vlan = factory.make_VLAN(vid=10)
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, vlan=vlan)
        interface = factory.make_Interface(
            INTERFACE_TYPE.VLAN, vlan=vlan, parents=[parent]
        )
        form = VLANInterfaceForm(
            node=parent.node_config.node,
            data={"vlan": vlan.id, "parents": [parent.id]},
        )
        assert not form.is_valid(), dict(form.errors)
        assert {"name"} == form.errors.keys(), form.errors
        assert (
            "already has an interface named '%s'." % interface.name
            in form.errors["name"][0]
        )

    def test_rejects_interface_on_default_fabric(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        vlan = parent.vlan.fabric.get_default_vlan()
        form = VLANInterfaceForm(
            node=parent.node_config.node,
            data={"vlan": vlan.id, "parents": [parent.id]},
        )
        assert not form.is_valid(), dict(form.errors)
        assert {"vlan"} == form.errors.keys(), form.errors
        assert (
            "A VLAN interface can only belong to a tagged VLAN."
            in form.errors["vlan"][0]
        )

    def test_rejects_no_parents(self):
        vlan = factory.make_VLAN(vid=10)
        form = VLANInterfaceForm(
            node=factory.make_Node(), data={"vlan": vlan.id}
        )
        assert not form.is_valid(), dict(form.errors)
        assert {"parents"} == form.errors.keys()
        assert (
            "A VLAN interface must have exactly one parent."
            in form.errors["parents"][0]
        )

    def test_rejects_vlan_parent(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        vlan_parent = factory.make_Interface(
            INTERFACE_TYPE.VLAN, parents=[parent]
        )
        vlan = factory.make_VLAN(vid=10)
        form = VLANInterfaceForm(
            node=parent.node_config.node,
            data={"vlan": vlan.id, "parents": [vlan_parent.id]},
        )
        assert not form.is_valid(), dict(form.errors)
        assert {"parents"} == form.errors.keys()
        assert (
            "VLAN interface can't have another VLAN interface as parent."
            in form.errors["parents"][0]
        )

    def test_rejects_no_vlan(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        form = VLANInterfaceForm(
            node=parent.node_config.node,
            data={"vlan": None, "parents": [parent.id]},
        )
        assert not form.is_valid(), dict(form.errors)
        assert {"vlan"} == form.errors.keys()
        assert (
            "A VLAN interface must be connected to a tagged VLAN."
            in form.errors["vlan"][0]
        )

    def test_rejects_vlan_not_on_same_fabric(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        factory.make_VLAN(fabric=parent.vlan.fabric, vid=10)
        other_vlan = factory.make_VLAN()
        form = VLANInterfaceForm(
            node=parent.node_config.node,
            data={"vlan": other_vlan.id, "parents": [parent.id]},
        )
        assert not form.is_valid(), dict(form.errors)
        assert {"vlan"} == form.errors.keys()
        assert (
            "A VLAN interface can only belong to a tagged VLAN on "
            "the same fabric as its parent interface."
            in form.errors["vlan"][0]
        )

    def test_rejects_parent_on_bond(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        factory.make_Interface(INTERFACE_TYPE.BOND, parents=[parent])
        vlan = factory.make_VLAN(vid=10)
        form = VLANInterfaceForm(
            node=parent.node_config.node,
            data={"vlan": vlan.id, "parents": [parent.id]},
        )
        assert not form.is_valid(), dict(form.errors)
        assert {"parents"} == form.errors.keys()
        assert (
            "A VLAN interface can't have a parent that is already in a bond."
            in form.errors["parents"][0]
        )

    def test_rejects_more_than_one_parent(self):
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            node_config=parent1.node_config,
        )
        vlan = factory.make_VLAN(vid=10)
        form = VLANInterfaceForm(
            node=parent1.node_config.node,
            data={"vlan": vlan.id, "parents": [parent1.id, parent2.id]},
        )
        assert not form.is_valid(), dict(form.errors)
        assert {"parents"} == form.errors.keys()
        assert (
            "A VLAN interface must have exactly one parent."
            in form.errors["parents"][0]
        )

    def test_edits_interface(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface = factory.make_Interface(
            INTERFACE_TYPE.VLAN, parents=[parent]
        )
        new_vlan = factory.make_VLAN(vid=33, fabric=interface.vlan.fabric)
        form = VLANInterfaceForm(
            instance=interface, data={"vlan": new_vlan.id}
        )
        assert form.is_valid(), dict(form.errors)
        interface = form.save()
        assert interface.vlan == new_vlan
        assert interface.type == INTERFACE_TYPE.VLAN
        assert Counter([parent]) == Counter(interface.parents.all())


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestBondInterfaceForm:
    def test_error_with_invalid_bond_mode(self):
        vlan = factory.make_VLAN(vid=10)
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, vlan=vlan)
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=parent1.node_config.node, vlan=vlan
        )
        interface_name = factory.make_name()
        bond_mode = factory.make_name("bond_mode")
        form = BondInterfaceForm(
            node=parent1.node_config.node,
            data={
                "name": interface_name,
                "vlan": vlan.id,
                "parents": [parent1.id, parent2.id],
                "bond_mode": bond_mode,
            },
        )
        assert not form.is_valid(), dict(form.errors)
        assert {
            "bond_mode": [
                compose_invalid_choice_text("bond_mode", BOND_MODE_CHOICES)
                % {"value": bond_mode}
            ]
        } == form.errors

    def test_creates_bond_interface(self):
        vlan = factory.make_VLAN(vid=10)
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, vlan=vlan)
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node_config=parent1.node_config, vlan=vlan
        )
        interface_name = factory.make_name()
        form = BondInterfaceForm(
            node=parent1.node_config.node,
            data={
                "name": interface_name,
                "vlan": vlan.id,
                "parents": [parent1.id, parent2.id],
            },
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert interface.name == interface_name
        assert interface.type == INTERFACE_TYPE.BOND
        assert interface.vlan == parent1.vlan
        assert interface.mac_address in [
            parent1.mac_address,
            parent2.mac_address,
        ]
        assert Counter([parent1, parent2]) == Counter(interface.parents.all())

    def test_create_removes_parent_links_and_sets_link_up_on_bond(self):
        vlan = factory.make_VLAN(vid=10)
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, vlan=vlan)

        with post_commit_hooks:
            parent1.ensure_link_up()

        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node_config=parent1.node_config, vlan=vlan
        )

        with post_commit_hooks:
            parent2.ensure_link_up()

        interface_name = factory.make_name()
        form = BondInterfaceForm(
            node=parent1.node_config.node,
            data={
                "name": interface_name,
                "vlan": vlan.id,
                "parents": [parent1.id, parent2.id],
            },
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert (
            0
            == parent1.ip_addresses.exclude(
                alloc_type=IPADDRESS_TYPE.DISCOVERED
            ).count()
        )
        assert (
            0
            == parent2.ip_addresses.exclude(
                alloc_type=IPADDRESS_TYPE.DISCOVERED
            ).count()
        )
        assert (
            interface.ip_addresses.filter(alloc_type=IPADDRESS_TYPE.STICKY)
            is not None
        )

    def test_creates_bond_interface_with_parent_mac_address(self):
        vlan = factory.make_VLAN(vid=10)
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, vlan=vlan)
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node_config=parent1.node_config, vlan=vlan
        )
        interface_name = factory.make_name()
        form = BondInterfaceForm(
            node=parent1.node_config.node,
            data={
                "name": interface_name,
                "vlan": vlan.id,
                "parents": [parent1.id, parent2.id],
                "mac_address": parent1.mac_address,
            },
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert interface.name == interface_name
        assert interface.mac_address == parent1.mac_address
        assert interface.type == INTERFACE_TYPE.BOND
        assert interface.mac_address in [
            parent1.mac_address,
            parent2.mac_address,
        ]

        assert Counter([parent1, parent2]) == Counter(interface.parents.all())

    def test_creates_bond_interface_with_default_bond_params(self):
        vlan = factory.make_VLAN(vid=10)
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, vlan=vlan)
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node_config=parent1.node_config, vlan=vlan
        )
        interface_name = factory.make_name()
        form = BondInterfaceForm(
            node=parent1.node_config.node,
            data={
                "name": interface_name,
                "vlan": vlan.id,
                "parents": [parent1.id, parent2.id],
            },
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()
        assert {
            "bond_mode": "balance-rr",
            "bond_miimon": 100,
            "bond_downdelay": 0,
            "bond_updelay": 0,
            "bond_num_grat_arp": 1,
            "bond_lacp_rate": "fast",
            "bond_xmit_hash_policy": "layer2",
        } == interface.params

    def test_creates_bond_interface_with_bond_params(self):
        vlan = factory.make_VLAN(vid=10)
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, vlan=vlan)
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node_config=parent1.node_config, vlan=vlan
        )
        interface_name = factory.make_name()
        bond_mode = factory.pick_choice(BOND_MODE_CHOICES)
        bond_miimon = random.randint(0, 1000)
        bond_downdelay = random.randint(0, 1000)
        bond_updelay = random.randint(0, 1000)
        bond_num_grat_arp = random.randint(0, 255)
        bond_lacp_rate = factory.pick_choice(BOND_LACP_RATE_CHOICES)
        bond_xmit_hash_policy = factory.pick_choice(
            BOND_XMIT_HASH_POLICY_CHOICES
        )
        form = BondInterfaceForm(
            node=parent1.node_config.node,
            data={
                "name": interface_name,
                "vlan": vlan.id,
                "parents": [parent1.id, parent2.id],
                "bond_mode": bond_mode,
                "bond_miimon": bond_miimon,
                "bond_downdelay": bond_downdelay,
                "bond_updelay": bond_updelay,
                "bond_lacp_rate": bond_lacp_rate,
                "bond_xmit_hash_policy": bond_xmit_hash_policy,
                "bond_num_grat_arp": bond_num_grat_arp,
            },
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert {
            "bond_mode": bond_mode,
            "bond_miimon": bond_miimon,
            "bond_downdelay": bond_downdelay,
            "bond_updelay": bond_updelay,
            "bond_lacp_rate": bond_lacp_rate,
            "bond_xmit_hash_policy": bond_xmit_hash_policy,
            "bond_num_grat_arp": bond_num_grat_arp,
        } == interface.params

    def test_rejects_no_parents(self):
        vlan = factory.make_VLAN(vid=10)
        interface_name = factory.make_name()
        form = BondInterfaceForm(
            node=factory.make_Node(),
            data={"name": interface_name, "vlan": vlan.id},
        )
        assert not form.is_valid(), dict(form.errors)
        assert {"parents", "mac_address"} == form.errors.keys()
        assert (
            "A bond interface must have one or more parents."
            in form.errors["parents"][0]
        )

    def test_rejects_when_parents_already_have_children(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=node, name="eth0"
        )
        factory.make_Interface(INTERFACE_TYPE.VLAN, parents=[parent1])
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=node, name="eth1"
        )
        factory.make_Interface(INTERFACE_TYPE.VLAN, parents=[parent2])
        vlan = factory.make_VLAN(vid=10)
        interface_name = factory.make_name()
        form = BondInterfaceForm(
            node=node,
            data={
                "name": interface_name,
                "vlan": vlan.id,
                "parents": [parent1.id, parent2.id],
            },
        )
        assert not form.is_valid(), dict(form.errors)
        assert (
            "Interfaces already in-use: eth0, eth1."
            in form.errors["parents"][0]
        )

    def test_rejects_when_parents_not_in_same_vlan(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=node, name="eth0"
        )
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=node, name="eth1"
        )
        interface_name = factory.make_name()
        form = BondInterfaceForm(
            node=node,
            data={"name": interface_name, "parents": [parent1.id, parent2.id]},
        )
        assert not form.is_valid(), dict(form.errors)
        assert (
            "All parents must belong to the same VLAN."
            == form.errors["parents"][0]
        )

    def test_edits_interface(self):
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            node_config=parent1.node_config,
        )
        original_interface = factory.make_Interface(
            INTERFACE_TYPE.BOND, parents=[parent1, parent2]
        )
        new_vlan = factory.make_VLAN(vid=33)
        new_name = factory.make_name()
        new_parent = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            node_config=parent1.node_config,
        )
        form = BondInterfaceForm(
            instance=original_interface,
            data={
                "vlan": new_vlan.id,
                "name": new_name,
                "parents": [parent1.id, parent2.id, new_parent.id],
            },
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert interface.mac_address == original_interface.mac_address
        assert interface.name == new_name
        assert interface.vlan == new_vlan
        assert interface.type == INTERFACE_TYPE.BOND
        assert Counter([parent1, parent2, new_parent]) == Counter(
            interface.parents.all()
        )

    def test_edits_interface_allows_disconnected(self):
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            node_config=parent1.node_config,
        )
        original_interface = factory.make_Interface(
            INTERFACE_TYPE.BOND, parents=[parent1, parent2]
        )
        form = BondInterfaceForm(
            instance=original_interface, data={"vlan": None}
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert interface.mac_address == original_interface.mac_address
        assert interface.vlan is None
        assert interface.type == INTERFACE_TYPE.BOND

    def test_edits_interface_removes_parents(self):
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            node_config=parent1.node_config,
        )
        parent3 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            node_config=parent1.node_config,
        )
        original_interface = factory.make_Interface(
            INTERFACE_TYPE.BOND, parents=[parent1, parent2, parent3]
        )
        new_name = factory.make_name()
        form = BondInterfaceForm(
            instance=original_interface,
            data={"name": new_name, "parents": [parent1.id, parent2.id]},
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert interface.mac_address == original_interface.mac_address
        assert interface.name == new_name
        assert interface.type == INTERFACE_TYPE.BOND

        assert Counter([parent1, parent2]) == Counter(interface.parents.all())

    def test_edits_interface_updates_mac_address_when_parent_removed(self):
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            node_config=parent1.node_config,
        )
        parent3 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            node_config=parent1.node_config,
        )
        interface = factory.make_Interface(
            INTERFACE_TYPE.BOND,
            mac_address=parent3.mac_address,
            parents=[parent1, parent2, parent3],
        )
        new_name = factory.make_name()
        form = BondInterfaceForm(
            instance=interface,
            data={"name": new_name, "parents": [parent1.id, parent2.id]},
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert interface.name == new_name
        assert interface.type == INTERFACE_TYPE.BOND
        assert Counter([parent1, parent2]) == Counter(interface.parents.all())
        assert interface.mac_address in [
            parent1.mac_address,
            parent2.mac_address,
        ]

    def test_edit_doesnt_overwrite_params(self):
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            node_config=parent1.node_config,
        )
        interface = factory.make_Interface(
            INTERFACE_TYPE.BOND, parents=[parent1, parent2]
        )
        bond_mode = factory.pick_choice(BOND_MODE_CHOICES)
        bond_miimon = random.randint(0, 1000)
        bond_downdelay = random.randint(0, 1000)
        bond_updelay = random.randint(0, 1000)
        bond_lacp_rate = factory.pick_choice(BOND_LACP_RATE_CHOICES)
        bond_xmit_hash_policy = factory.pick_choice(
            BOND_XMIT_HASH_POLICY_CHOICES
        )
        interface.params = {
            "bond_mode": bond_mode,
            "bond_miimon": bond_miimon,
            "bond_downdelay": bond_downdelay,
            "bond_updelay": bond_updelay,
            "bond_lacp_rate": bond_lacp_rate,
            "bond_xmit_hash_policy": bond_xmit_hash_policy,
        }

        with post_commit_hooks:
            interface.save()

        new_vlan = factory.make_VLAN(vid=33)
        new_name = factory.make_name()
        form = BondInterfaceForm(
            instance=interface, data={"vlan": new_vlan.id, "name": new_name}
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()
        assert {
            "bond_mode": bond_mode,
            "bond_miimon": bond_miimon,
            "bond_downdelay": bond_downdelay,
            "bond_updelay": bond_updelay,
            "bond_lacp_rate": bond_lacp_rate,
            "bond_xmit_hash_policy": bond_xmit_hash_policy,
        } == interface.params

    def test_edit_does_overwrite_params(self):
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            node_config=parent1.node_config,
        )
        interface = factory.make_Interface(
            INTERFACE_TYPE.BOND, parents=[parent1, parent2]
        )
        bond_mode = factory.pick_choice(BOND_MODE_CHOICES)
        bond_miimon = random.randint(0, 1000)
        bond_downdelay = random.randint(0, 1000)
        bond_updelay = random.randint(0, 1000)
        bond_lacp_rate = factory.pick_choice(BOND_LACP_RATE_CHOICES)
        bond_xmit_hash_policy = factory.pick_choice(
            BOND_XMIT_HASH_POLICY_CHOICES
        )
        interface.params = {
            "bond_mode": bond_mode,
            "bond_miimon": bond_miimon,
            "bond_downdelay": bond_downdelay,
            "bond_updelay": bond_updelay,
            "bond_lacp_rate": bond_lacp_rate,
            "bond_xmit_hash_policy": bond_xmit_hash_policy,
        }

        with post_commit_hooks:
            interface.save()

        new_vlan = factory.make_VLAN(vid=33)
        new_name = factory.make_name()
        new_bond_mode = factory.pick_choice(BOND_MODE_CHOICES)
        new_bond_miimon = random.randint(0, 1000)
        new_bond_downdelay = random.randint(0, 1000)
        new_bond_updelay = random.randint(0, 1000)
        new_bond_lacp_rate = factory.pick_choice(BOND_LACP_RATE_CHOICES)
        new_bond_xmit_hash_policy = factory.pick_choice(
            BOND_XMIT_HASH_POLICY_CHOICES
        )
        form = BondInterfaceForm(
            instance=interface,
            data={
                "vlan": new_vlan.id,
                "name": new_name,
                "bond_mode": new_bond_mode,
                "bond_miimon": new_bond_miimon,
                "bond_downdelay": new_bond_downdelay,
                "bond_updelay": new_bond_updelay,
                "bond_lacp_rate": new_bond_lacp_rate,
                "bond_xmit_hash_policy": new_bond_xmit_hash_policy,
            },
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert {
            "bond_mode": new_bond_mode,
            "bond_miimon": new_bond_miimon,
            "bond_downdelay": new_bond_downdelay,
            "bond_updelay": new_bond_updelay,
            "bond_lacp_rate": new_bond_lacp_rate,
            "bond_xmit_hash_policy": new_bond_xmit_hash_policy,
        } == interface.params

    def test_edit_allows_zero_params(self):
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            node_config=parent1.node_config,
        )
        interface = factory.make_Interface(
            INTERFACE_TYPE.BOND, parents=[parent1, parent2]
        )
        bond_mode = factory.pick_choice(BOND_MODE_CHOICES)
        bond_miimon = random.randint(0, 1000)
        bond_downdelay = random.randint(0, 1000)
        bond_updelay = random.randint(0, 1000)
        bond_lacp_rate = factory.pick_choice(BOND_LACP_RATE_CHOICES)
        bond_xmit_hash_policy = factory.pick_choice(
            BOND_XMIT_HASH_POLICY_CHOICES
        )
        interface.params = {
            "bond_mode": bond_mode,
            "bond_miimon": bond_miimon,
            "bond_downdelay": bond_downdelay,
            "bond_updelay": bond_updelay,
            "bond_lacp_rate": bond_lacp_rate,
            "bond_xmit_hash_policy": bond_xmit_hash_policy,
        }

        with post_commit_hooks:
            interface.save()

        new_vlan = factory.make_VLAN(vid=33)
        new_name = factory.make_name()
        new_bond_mode = factory.pick_choice(BOND_MODE_CHOICES)
        new_bond_miimon = 0
        new_bond_downdelay = 0
        new_bond_updelay = 0
        new_bond_lacp_rate = factory.pick_choice(BOND_LACP_RATE_CHOICES)
        new_bond_xmit_hash_policy = factory.pick_choice(
            BOND_XMIT_HASH_POLICY_CHOICES
        )
        form = BondInterfaceForm(
            instance=interface,
            data={
                "vlan": new_vlan.id,
                "name": new_name,
                "bond_mode": new_bond_mode,
                "bond_miimon": new_bond_miimon,
                "bond_downdelay": new_bond_downdelay,
                "bond_updelay": new_bond_updelay,
                "bond_lacp_rate": new_bond_lacp_rate,
                "bond_xmit_hash_policy": new_bond_xmit_hash_policy,
            },
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert {
            "bond_mode": new_bond_mode,
            "bond_miimon": new_bond_miimon,
            "bond_downdelay": new_bond_downdelay,
            "bond_updelay": new_bond_updelay,
            "bond_lacp_rate": new_bond_lacp_rate,
            "bond_xmit_hash_policy": new_bond_xmit_hash_policy,
        } == interface.params


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestBridgeInterfaceForm:
    def test_creates_bridge_interface(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface_name = factory.make_name()
        form = BridgeInterfaceForm(
            node=parent.node_config.node,
            data={"name": interface_name, "parents": [parent.id]},
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()
        assert interface.name == interface_name
        assert interface.type == INTERFACE_TYPE.BRIDGE
        assert interface.mac_address == parent.mac_address
        assert Counter([parent]) == Counter(interface.parents.all())

    def test_allows_bridge_on_parent_with_vlan_bridges(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        vlan1 = factory.make_Interface(INTERFACE_TYPE.VLAN, parents=[parent])
        factory.make_Interface(INTERFACE_TYPE.BRIDGE, parents=[vlan1])
        vlan2 = factory.make_Interface(INTERFACE_TYPE.VLAN, parents=[parent])
        factory.make_Interface(INTERFACE_TYPE.BRIDGE, parents=[vlan2])
        interface_name = factory.make_name()
        form = BridgeInterfaceForm(
            node=parent.node_config.node,
            data={"name": interface_name, "parents": [parent.id]},
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()
        assert interface.name == interface_name
        assert interface.type == INTERFACE_TYPE.BRIDGE
        assert interface.mac_address == parent.mac_address
        assert Counter([parent]) == Counter(interface.parents.all())

    def test_allows_bridge_on_bond_with_vlan_bridges(self):
        node = factory.make_Node()
        eth0 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        eth1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        bond0 = factory.make_Interface(
            INTERFACE_TYPE.BOND, parents=[eth0, eth1]
        )
        vlan1 = factory.make_Interface(INTERFACE_TYPE.VLAN, parents=[bond0])
        factory.make_Interface(INTERFACE_TYPE.BRIDGE, parents=[vlan1])
        vlan2 = factory.make_Interface(INTERFACE_TYPE.VLAN, parents=[bond0])
        factory.make_Interface(INTERFACE_TYPE.BRIDGE, parents=[vlan2])
        interface_name = factory.make_name()
        form = BridgeInterfaceForm(
            node=node, data={"name": interface_name, "parents": [bond0.id]}
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert interface.name == interface_name
        assert interface.type == INTERFACE_TYPE.BRIDGE
        assert interface.mac_address == bond0.mac_address
        assert Counter([bond0]) == Counter(interface.parents.all())

    def test_create_removes_parent_links_and_sets_link_up_on_bridge(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)

        with post_commit_hooks:
            parent.ensure_link_up()

        interface_name = factory.make_name()
        form = BridgeInterfaceForm(
            node=parent.node_config.node,
            data={"name": interface_name, "parents": [parent.id]},
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert (
            0
            == parent.ip_addresses.exclude(
                alloc_type=IPADDRESS_TYPE.DISCOVERED
            ).count()
        )
        assert (
            interface.ip_addresses.filter(alloc_type=IPADDRESS_TYPE.STICKY)
            is not None
        )

    def test_creates_bridge_interface_with_parent_mac_address(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface_name = factory.make_name()
        form = BridgeInterfaceForm(
            node=parent.node_config.node,
            data={
                "name": interface_name,
                "parents": [parent.id],
                "mac_address": parent.mac_address,
            },
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert interface.name == interface_name
        assert interface.mac_address == parent.mac_address
        assert interface.type == INTERFACE_TYPE.BRIDGE
        assert Counter([parent]) == Counter(interface.parents.all())

    def test_rejects_no_parent(self):
        interface_name = factory.make_name()
        form = BridgeInterfaceForm(
            node=factory.make_Node(), data={"name": interface_name}
        )
        assert not form.is_valid(), dict(form.errors)
        assert {"parents", "mac_address"} == form.errors.keys()
        assert (
            "A bridge interface must have at least one parent."
            in form.errors["parents"][0]
        )

    def test_rejects_when_parent_already_have_children(self):
        node = factory.make_Node()
        eth0 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=node, name="eth0"
        )
        eth1 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=node, name="eth1"
        )
        invalid0 = factory.make_Interface(
            INTERFACE_TYPE.BOND, parents=[eth0, eth1]
        )
        # This should never happen, but in order to validate the case we're
        # trying to validate, we need a child that isn't a bond or bridge.
        invalid0.type = INTERFACE_TYPE.UNKNOWN

        with post_commit_hooks:
            invalid0.save()

        interface_name = factory.make_name()
        form = BridgeInterfaceForm(
            node=node, data={"name": interface_name, "parents": [eth0.id]}
        )
        assert not form.is_valid(), dict(form.errors)
        assert "Interfaces already in-use: eth0." in form.errors["parents"][0]

    def test_rejects_when_parent_is_bridge(self):
        node = factory.make_Node()
        bridge = factory.make_Interface(INTERFACE_TYPE.BRIDGE, node=node)
        interface_name = factory.make_name()
        form = BridgeInterfaceForm(
            node=node, data={"name": interface_name, "parents": [bridge.id]}
        )
        assert not form.is_valid(), dict(form.errors)
        assert (
            "A bridge interface can't have another bridge interface as "
            "parent." in form.errors["parents"][0]
        )

    def test_rejects_when_parent_is_already_in_a_bridge(self):
        node = factory.make_Node()
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        factory.make_Interface(
            INTERFACE_TYPE.BRIDGE, node=node, parents=[parent]
        )
        interface_name = factory.make_name()
        form = BridgeInterfaceForm(
            node=node, data={"name": interface_name, "parents": [parent.id]}
        )
        assert not form.is_valid(), dict(form.errors)
        assert (
            "A bridge interface can't have a parent that is already "
            "in a bond or a bridge." in form.errors["parents"][0]
        )

    def test_rejects_when_parent_is_already_in_a_bond(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        factory.make_Interface(
            INTERFACE_TYPE.BOND, node=node, parents=[parent1, parent2]
        )
        interface_name = factory.make_name()
        form = BridgeInterfaceForm(
            node=node, data={"name": interface_name, "parents": [parent1.id]}
        )
        assert not form.is_valid(), dict(form.errors)
        assert (
            "A bridge interface can't have a parent that is already "
            "in a bond or a bridge." in form.errors["parents"][0]
        )

    def test_edits_interface(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        original_interface = factory.make_Interface(
            INTERFACE_TYPE.BRIDGE, parents=[parent]
        )
        new_fabric = factory.make_Fabric()
        new_vlan = new_fabric.get_default_vlan()
        new_name = factory.make_name()
        new_parent = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            node_config=parent.node_config,
            vlan=parent.vlan,
        )
        form = BridgeInterfaceForm(
            instance=original_interface,
            data={
                "vlan": new_vlan.id,
                "name": new_name,
                "parents": [new_parent.id],
            },
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert interface.mac_address == original_interface.mac_address
        assert interface.name == new_name
        assert interface.vlan == new_vlan
        assert interface.type == INTERFACE_TYPE.BRIDGE
        assert Counter([new_parent]) == Counter(interface.parents.all())

    def test_edits_interface_allows_disconnected(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        original_interface = factory.make_Interface(
            INTERFACE_TYPE.BRIDGE, parents=[parent]
        )
        form = BridgeInterfaceForm(
            instance=original_interface, data={"vlan": None}
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert interface.mac_address == original_interface.mac_address
        assert interface.vlan is None
        assert interface.type == INTERFACE_TYPE.BRIDGE

    def test_edit_doesnt_overwrite_params(self):
        """Check that updating parameters that are not bridge specific do not
        overwrite the bridge specific parameters."""
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface = factory.make_Interface(
            INTERFACE_TYPE.BRIDGE, parents=[parent]
        )
        bridge_type = factory.pick_choice(BRIDGE_TYPE_CHOICES)
        bridge_stp = factory.pick_bool()
        bridge_fd = random.randint(0, 1000)
        interface.params = {
            "bridge_type": bridge_type,
            "bridge_stp": bridge_stp,
            "bridge_fd": bridge_fd,
        }

        with post_commit_hooks:
            interface.save()

        new_name = factory.make_name()
        form = BridgeInterfaceForm(instance=interface, data={"name": new_name})
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert {
            "bridge_type": bridge_type,
            "bridge_stp": bridge_stp,
            "bridge_fd": bridge_fd,
        } == interface.params

    def test_edit_does_overwrite_params(self):
        """Check that updating specific bridge parameters actually
        update the parameters."""
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface = factory.make_Interface(
            INTERFACE_TYPE.BRIDGE, parents=[parent]
        )
        bridge_type = factory.pick_choice(BRIDGE_TYPE_CHOICES)
        bridge_stp = factory.pick_bool()
        bridge_fd = random.randint(0, 1000)
        interface.params = {
            "bridge_type": bridge_type,
            "bridge_stp": bridge_stp,
            "bridge_fd": bridge_fd,
        }

        with post_commit_hooks:
            interface.save()

        new_bridge_type = factory.pick_choice(
            BRIDGE_TYPE_CHOICES, but_not=[bridge_type]
        )
        new_bridge_stp = factory.pick_bool()
        new_bridge_fd = random.randint(0, 1000)
        form = BridgeInterfaceForm(
            instance=interface,
            data={
                "bridge_type": new_bridge_type,
                "bridge_stp": new_bridge_stp,
                "bridge_fd": new_bridge_fd,
            },
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert {
            "bridge_type": new_bridge_type,
            "bridge_stp": new_bridge_stp,
            "bridge_fd": new_bridge_fd,
        } == interface.params

    def test_edit_allows_zero_params(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface = factory.make_Interface(
            INTERFACE_TYPE.BRIDGE, parents=[parent]
        )
        bridge_type = factory.pick_choice(BRIDGE_TYPE_CHOICES)
        bridge_stp = True
        bridge_fd = random.randint(1, 1000)
        interface.params = {
            "bridge_type": bridge_type,
            "bridge_stp": bridge_stp,
            "bridge_fd": bridge_fd,
        }

        with post_commit_hooks:
            interface.save()

        new_bridge_type = factory.pick_choice(
            BRIDGE_TYPE_CHOICES, but_not=[bridge_type]
        )
        new_bridge_stp = False
        new_bridge_fd = 0
        form = BridgeInterfaceForm(
            instance=interface,
            data={
                "bridge_type": new_bridge_type,
                "bridge_stp": new_bridge_stp,
                "bridge_fd": new_bridge_fd,
            },
        )
        assert form.is_valid(), dict(form.errors)
        interface = form.save()
        assert {
            "bridge_type": new_bridge_type,
            "bridge_stp": new_bridge_stp,
            "bridge_fd": new_bridge_fd,
        } == interface.params

    def test_creates_bridge_interface_multiple_parents(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        interface_name = factory.make_name()
        form = BridgeInterfaceForm(
            node=node,
            data={"name": interface_name, "parents": [parent1.id, parent2.id]},
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()
        assert interface.name == interface_name
        assert interface.type == INTERFACE_TYPE.BRIDGE
        assert (
            interface.mac_address == parent1.mac_address
        )  # mac from the first parent
        assert Counter([parent1, parent2]) == Counter(interface.parents.all())


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestAcquiredBridgeInterfaceForm:
    def test_creates_acquired_bridge_interface(self):
        interface_name = factory.make_name("br")
        node = factory.make_Node()
        parent_fabric = factory.make_Fabric()
        parent_vlan = parent_fabric.get_default_vlan()
        parent = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=node, vlan=parent_vlan
        )
        parent_subnet = factory.make_Subnet(vlan=parent_vlan)
        parent_sip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO,
            ip=factory.pick_ip_in_Subnet(parent_subnet),
            subnet=parent_subnet,
            interface=parent,
        )
        tags = [factory.make_name("tag") for _ in range(3)]
        form = AcquiredBridgeInterfaceForm(
            node=node,
            data={
                "name": interface_name,
                "parents": [parent.id],
                "tags": tags,
            },
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            interface = form.save()

        assert interface.name == interface_name
        assert interface.type == INTERFACE_TYPE.BRIDGE
        assert interface.acquired
        assert interface.vlan == parent_vlan
        assert interface.mac_address == parent.mac_address
        assert Counter([parent]) == Counter(interface.parents.all())
        assert Counter([parent_sip]) == Counter(interface.ip_addresses.all())
        assert Counter([]) == Counter(parent.ip_addresses.all())

    def test_rejects_no_parent(self):
        interface_name = factory.make_name()
        form = AcquiredBridgeInterfaceForm(
            node=factory.make_Node(), data={"name": interface_name}
        )
        assert not form.is_valid(), dict(form.errors)
        assert {"parents", "mac_address"} == form.errors.keys()
        assert (
            "A bridge interface must have at least one parent."
            in form.errors["parents"][0]
        )

    def test_rejects_when_parent_already_have_non_vlan_children(self):
        node = factory.make_Node()
        eth0 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=node, name="eth0"
        )
        eth1 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=node, name="eth1"
        )
        bond0 = factory.make_Interface(
            INTERFACE_TYPE.BOND, parents=[eth0, eth1]
        )
        bond0.type = INTERFACE_TYPE.UNKNOWN

        with post_commit_hooks:
            bond0.save()

        interface_name = factory.make_name()
        form = AcquiredBridgeInterfaceForm(
            node=node, data={"name": interface_name, "parents": [eth0.id]}
        )
        assert not form.is_valid(), dict(form.errors)
        assert "Interfaces already in-use: eth0." in form.errors["parents"][0]

    def test_rejects_when_parent_is_bridge(self):
        node = factory.make_Node()
        bridge = factory.make_Interface(INTERFACE_TYPE.BRIDGE, node=node)
        interface_name = factory.make_name()
        form = AcquiredBridgeInterfaceForm(
            node=node, data={"name": interface_name, "parents": [bridge.id]}
        )
        assert not form.is_valid(), dict(form.errors)
        assert (
            "A bridge interface can't have another bridge interface as "
            "parent." in form.errors["parents"][0]
        )

    def test_rejects_when_parent_is_already_in_a_bridge(self):
        node = factory.make_Node()
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        factory.make_Interface(
            INTERFACE_TYPE.BRIDGE, node=node, parents=[parent]
        )
        interface_name = factory.make_name()
        form = AcquiredBridgeInterfaceForm(
            node=node, data={"name": interface_name, "parents": [parent.id]}
        )
        assert not form.is_valid(), dict(form.errors)
        assert (
            "A bridge interface can't have a parent that is already "
            "in a bond or a bridge." in form.errors["parents"][0]
        )

    def test_rejects_when_parent_is_already_in_a_bond(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        factory.make_Interface(
            INTERFACE_TYPE.BOND, node=node, parents=[parent1, parent2]
        )
        interface_name = factory.make_name()
        form = AcquiredBridgeInterfaceForm(
            node=node, data={"name": interface_name, "parents": [parent1.id]}
        )
        assert not form.is_valid(), dict(form.errors)
        assert (
            "A bridge interface can't have a parent that is already "
            "in a bond or a bridge." in form.errors["parents"][0]
        )
