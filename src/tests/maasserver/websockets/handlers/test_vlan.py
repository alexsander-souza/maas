# Copyright 2015-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


import random
from unittest.mock import MagicMock

import pytest

from maasserver import openfga
from maasserver.enum import INTERFACE_TYPE
from maasserver.models.vlan import VLAN
from maasserver.testing.factory import factory
from maasserver.utils.orm import post_commit_hooks, reload_object
from maasserver.websockets.base import (
    dehydrate_datetime,
    HandlerPermissionError,
    HandlerValidationError,
)
from maasserver.websockets.handlers.vlan import VLANHandler


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestVLANHandler:
    def dehydrate_vlan(self, vlan, for_list=False):
        data = {
            "id": vlan.id,
            "name": vlan.name,
            "description": vlan.description,
            "vid": vlan.vid,
            "mtu": vlan.mtu,
            "fabric": vlan.fabric_id,
            "space": vlan.space_id,
            "updated": dehydrate_datetime(vlan.updated),
            "created": dehydrate_datetime(vlan.created),
            "dhcp_on": vlan.dhcp_on,
            "external_dhcp": vlan.external_dhcp,
            "primary_rack": vlan.primary_rack,
            "secondary_rack": vlan.secondary_rack,
            "relay_vlan": vlan.relay_vlan_id,
        }
        data["rack_sids"] = sorted(
            list(
                {
                    interface.node.system_id
                    for interface in vlan.interface_set.all()
                    if interface.node_config_id is not None
                    and interface.node_config.node.is_rack_controller
                }
            )
        )
        data["subnet_ids"] = list(
            vlan.subnet_set.values_list("id", flat=True).order_by("id")
        )
        if not for_list:
            data["node_ids"] = sorted(
                list(
                    {
                        interface.node_config.node_id
                        for interface in vlan.interface_set.all()
                        if interface.node_config_id is not None
                    }
                )
            )
            data["space_ids"] = sorted(
                {subnet.space.id for subnet in vlan.subnet_set.all()}
            )
        return data

    def test_get(self):
        user = factory.make_User()
        handler = VLANHandler(user, {}, None)
        vlan = factory.make_VLAN(space=factory.make_Space())
        for _ in range(3):
            factory.make_Subnet(vlan=vlan)
        for _ in range(3):
            node = factory.make_Node(interface=True)
            interface = node.get_boot_interface()
            interface.vlan = vlan
            interface.save()
        assert self.dehydrate_vlan(vlan) == handler.get({"id": vlan.id})

    def test_list(self):
        user = factory.make_User()
        handler = VLANHandler(user, {}, None)
        factory.make_VLAN()
        expected_vlans = [
            self.dehydrate_vlan(vlan, for_list=True)
            for vlan in VLAN.objects.all()
        ]
        assert sorted(expected_vlans, key=repr) == sorted(
            handler.list({}), key=repr
        )

    def test_create(self):
        admin = factory.make_admin()
        handler = VLANHandler(admin, {}, None)
        fabric = factory.make_Fabric()
        vid = random.randint(1, 4094)
        name = factory.make_name("vlan")
        new_vlan = handler.create(
            {"fabric": fabric.id, "vid": vid, "name": name}
        )
        assert new_vlan.get("fabric") == fabric.id
        assert new_vlan.get("name") == name
        assert new_vlan.get("vid") == vid


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestVLANHandlerUpdate:
    def test_update_as_user(self):
        user = factory.make_User()
        handler = VLANHandler(user, {}, None)
        vlan = factory.make_VLAN()
        old_name = vlan.name
        pytest.raises(
            HandlerPermissionError,
            handler.update,
            {"id": vlan.id, "name": "new-name"},
        )
        vlan = reload_object(vlan)
        assert old_name == vlan.name

    def test_update_as_admin(self):
        user = factory.make_admin()
        handler = VLANHandler(user, {}, None)
        vlan = factory.make_VLAN()
        handler.update({"id": vlan.id, "name": "new-name"})
        vlan = reload_object(vlan)
        assert "new-name" == vlan.name

    def test_update_clear_name(self):
        user = factory.make_admin()
        handler = VLANHandler(user, {}, None)
        vlan = factory.make_VLAN(name="my-name")
        handler.update({"id": vlan.id, "name": ""})
        vlan = reload_object(vlan)
        assert vlan.name is None


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestVLANHandlerDelete:
    def test_delete_as_admin_success(self):
        user = factory.make_admin()
        handler = VLANHandler(user, {}, None)
        vlan = factory.make_VLAN()
        handler.delete({"id": vlan.id})
        vlan = reload_object(vlan)
        assert vlan is None

    def test_delete_as_non_admin_asserts(self):
        user = factory.make_User()
        handler = VLANHandler(user, {}, None)
        vlan = factory.make_VLAN()
        pytest.raises(HandlerPermissionError, handler.delete, {"id": vlan.id})


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestVLANHandlerConfigureDHCP:
    def test_configure_dhcp_with_one_parameter(self):
        user = factory.make_admin()
        handler = VLANHandler(user, {}, None)
        vlan = factory.make_VLAN()
        rack = factory.make_RackController()
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=rack, vlan=vlan)
        factory.make_ipv4_Subnet_with_IPRanges(vlan=vlan)

        with post_commit_hooks:
            handler.configure_dhcp(
                {"id": vlan.id, "controllers": [rack.system_id]}
            )

        vlan = reload_object(vlan)
        assert vlan.dhcp_on
        assert rack == vlan.primary_rack

    def test_configure_dhcp_with_two_parameters(self):
        user = factory.make_admin()
        handler = VLANHandler(user, {}, None)
        vlan = factory.make_VLAN()
        rack = factory.make_RackController()
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=rack, vlan=vlan)
        rack2 = factory.make_RackController()
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=rack2, vlan=vlan)
        factory.make_ipv4_Subnet_with_IPRanges(vlan=vlan)

        with post_commit_hooks:
            handler.configure_dhcp(
                {
                    "id": vlan.id,
                    "controllers": [rack.system_id, rack2.system_id],
                }
            )

        vlan = reload_object(vlan)
        assert vlan.dhcp_on
        assert rack == vlan.primary_rack
        assert rack2 == vlan.secondary_rack

    def test_configure_dhcp_with_duplicate_raises(self):
        user = factory.make_admin()
        handler = VLANHandler(user, {}, None)
        vlan = factory.make_VLAN()
        rack = factory.make_RackController()
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=rack, vlan=vlan)
        factory.make_ipv4_Subnet_with_IPRanges(vlan=vlan)

        with post_commit_hooks:
            pytest.raises(
                HandlerValidationError,
                handler.configure_dhcp,
                {
                    "id": vlan.id,
                    "controllers": [rack.system_id, rack.system_id],
                },
            )

    def test_configure_dhcp_with_no_parameters_disables_dhcp(self):
        user = factory.make_admin()
        handler = VLANHandler(user, {}, None)
        rack = factory.make_RackController()
        vlan = factory.make_VLAN()
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=rack, vlan=vlan)
        vlan.dhcp_on = True
        vlan.primary_rack = rack

        with post_commit_hooks:
            vlan.save()

        factory.make_ipv4_Subnet_with_IPRanges(vlan=vlan)

        with post_commit_hooks:
            handler.configure_dhcp({"id": vlan.id, "controllers": []})

        vlan = reload_object(vlan)
        assert not vlan.dhcp_on
        assert vlan.primary_rack is None
        assert vlan.secondary_rack is None

    def test_configure_dhcp_with_relay_vlan(self):
        user = factory.make_admin()
        handler = VLANHandler(user, {}, None)
        vlan = factory.make_VLAN()
        relay_vlan = factory.make_VLAN()

        with post_commit_hooks:
            handler.configure_dhcp(
                {"id": vlan.id, "controllers": [], "relay_vlan": relay_vlan.id}
            )

        vlan = reload_object(vlan)
        assert not vlan.dhcp_on
        assert relay_vlan == vlan.relay_vlan

    def test_non_superuser_asserts(self):
        user = factory.make_User()
        handler = VLANHandler(user, {}, None)
        rack = factory.make_RackController()
        vlan = factory.make_VLAN()
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=rack, vlan=vlan)
        vlan.dhcp_on = True
        vlan.primary_rack = rack

        with post_commit_hooks:
            vlan.save()

        factory.make_ipv4_Subnet_with_IPRanges(vlan=vlan)
        pytest.raises(
            HandlerPermissionError,
            handler.configure_dhcp,
            {"id": vlan.id, "controllers": []},
        )

    def test_configure_dhcp_optionally_creates_iprange(self):
        user = factory.make_admin()
        handler = VLANHandler(user, {}, None)
        vlan = factory.make_VLAN()
        rack = factory.make_RackController()
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=rack, vlan=vlan)
        subnet = factory.make_Subnet(
            vlan=vlan, cidr="10.0.0.0/24", gateway_ip=""
        )
        assert 0 == subnet.get_dynamic_ranges().count()

        with post_commit_hooks:
            handler.configure_dhcp(
                {
                    "id": vlan.id,
                    "controllers": [rack.system_id],
                    "extra": {
                        "subnet": subnet.id,
                        "start": "10.0.0.2",
                        "end": "10.0.0.99",
                    },
                }
            )

        vlan = reload_object(vlan)
        subnet = reload_object(subnet)
        assert vlan.dhcp_on
        assert rack == vlan.primary_rack
        assert 1 == subnet.get_dynamic_ranges().count()
        dynamic_range = subnet.get_dynamic_ranges().first()
        assert "10.0.0.2" == dynamic_range.start_ip
        assert "10.0.0.99" == dynamic_range.end_ip
        assert "dynamic" == dynamic_range.type
        assert user.id == dynamic_range.user_id
        assert "Web UI" in dynamic_range.comment

    def test_configure_dhcp_optionally_defines_gateway(self):
        user = factory.make_admin()
        handler = VLANHandler(user, {}, None)
        vlan = factory.make_VLAN()
        rack = factory.make_RackController()
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=rack, vlan=vlan)
        subnet = factory.make_Subnet(
            vlan=vlan, cidr="10.0.0.0/24", gateway_ip=""
        )
        factory.make_ipv4_Subnet_with_IPRanges(vlan=vlan)
        assert 0 == subnet.get_dynamic_ranges().count()

        with post_commit_hooks:
            handler.configure_dhcp(
                {
                    "id": vlan.id,
                    "controllers": [rack.system_id],
                    "extra": {"subnet": subnet.id, "gateway": "10.0.0.1"},
                }
            )

        vlan = reload_object(vlan)
        subnet = reload_object(subnet)
        assert vlan.dhcp_on
        assert rack == vlan.primary_rack
        assert 0 == subnet.get_dynamic_ranges().count()
        assert "10.0.0.1" == subnet.gateway_ip

    def test_configure_dhcp_optionally_defines_gateway_and_range(self):
        user = factory.make_admin()
        handler = VLANHandler(user, {}, None)
        vlan = factory.make_VLAN()
        rack = factory.make_RackController()
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=rack, vlan=vlan)
        subnet = factory.make_Subnet(
            vlan=vlan, cidr="10.0.0.0/24", gateway_ip=""
        )
        assert 0 == subnet.get_dynamic_ranges().count()

        with post_commit_hooks:
            handler.configure_dhcp(
                {
                    "id": vlan.id,
                    "controllers": [rack.system_id],
                    "extra": {
                        "subnet": subnet.id,
                        "gateway": "10.0.0.1",
                        "start": "10.0.0.2",
                        "end": "10.0.0.99",
                    },
                }
            )

        subnet = reload_object(subnet)
        vlan = reload_object(vlan)
        subnet = reload_object(subnet)
        assert vlan.dhcp_on
        assert rack == vlan.primary_rack
        assert 1 == subnet.get_dynamic_ranges().count()
        dynamic_range = subnet.get_dynamic_ranges().first()
        assert "10.0.0.1" == subnet.gateway_ip
        assert "10.0.0.2" == dynamic_range.start_ip
        assert "10.0.0.99" == dynamic_range.end_ip
        assert "dynamic" == dynamic_range.type
        assert user.id == dynamic_range.user_id
        assert "Web UI" in dynamic_range.comment

    def test_configure_dhcp_ignores_empty_gateway(self):
        user = factory.make_admin()
        handler = VLANHandler(user, {}, None)
        vlan = factory.make_VLAN()
        rack = factory.make_RackController()
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=rack, vlan=vlan)
        subnet = factory.make_Subnet(
            vlan=vlan, cidr="10.0.0.0/24", gateway_ip=""
        )
        assert 0 == subnet.get_dynamic_ranges().count()

        with post_commit_hooks:
            handler.configure_dhcp(
                {
                    "id": vlan.id,
                    "controllers": [rack.system_id],
                    "extra": {
                        "subnet": subnet.id,
                        "gateway": "",
                        "start": "10.0.0.2",
                        "end": "10.0.0.99",
                    },
                }
            )

        subnet = reload_object(subnet)
        vlan = reload_object(vlan)
        subnet = reload_object(subnet)
        assert vlan.dhcp_on
        assert rack == vlan.primary_rack
        assert 1 == subnet.get_dynamic_ranges().count()
        dynamic_range = subnet.get_dynamic_ranges().first()
        assert subnet.gateway_ip is None
        assert "10.0.0.2" == dynamic_range.start_ip
        assert "10.0.0.99" == dynamic_range.end_ip
        assert "dynamic" == dynamic_range.type
        assert user.id == dynamic_range.user_id
        assert "Web UI" in dynamic_range.comment

    def test_configure_dhcp_gateway_outside_subnet_raises(self):
        user = factory.make_admin()
        handler = VLANHandler(user, {}, None)
        vlan = factory.make_VLAN()
        rack = factory.make_RackController()
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=rack, vlan=vlan)
        subnet = factory.make_Subnet(
            vlan=vlan, cidr="10.0.0.0/24", gateway_ip=""
        )
        assert 0 == subnet.get_dynamic_ranges().count()

        with post_commit_hooks:
            pytest.raises(
                ValueError,
                handler.configure_dhcp,
                {
                    "id": vlan.id,
                    "controllers": [rack.system_id],
                    "extra": {
                        "subnet": subnet.id,
                        "gateway": "1.0.0.1",
                        "start": "10.0.0.2",
                        "end": "10.0.0.99",
                    },
                },
            )

    def test_configure_dhcp_gateway_fe80_allowed(self):
        user = factory.make_admin()
        handler = VLANHandler(user, {}, None)
        vlan = factory.make_VLAN()
        rack = factory.make_RackController()
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=rack, vlan=vlan)
        subnet = factory.make_Subnet(
            vlan=vlan, cidr="2001:db8::/64", gateway_ip=""
        )
        assert 0 == subnet.get_dynamic_ranges().count()

        with post_commit_hooks:
            handler.configure_dhcp(
                {
                    "id": vlan.id,
                    "controllers": [rack.system_id],
                    "extra": {
                        "subnet": subnet.id,
                        "gateway": "fe80::1",
                        "start": "2001:db8:0:0:1::",
                        "end": "2001:db8:0:0:1:ffff:ffff:ffff",
                    },
                }
            )

        subnet = reload_object(subnet)
        assert subnet.gateway_ip == "fe80::1"

    def test_configure_dhcp_gateway_inside_range_raises(self):
        user = factory.make_admin()
        handler = VLANHandler(user, {}, None)
        vlan = factory.make_VLAN()
        rack = factory.make_RackController()
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=rack, vlan=vlan)
        subnet = factory.make_Subnet(
            vlan=vlan, cidr="10.0.0.0/24", gateway_ip=""
        )
        assert 0 == subnet.get_dynamic_ranges().count()

        with post_commit_hooks:
            pytest.raises(
                ValueError,
                handler.configure_dhcp,
                {
                    "id": vlan.id,
                    "controllers": [rack.system_id],
                    "extra": {
                        "subnet": subnet.id,
                        "gateway": "10.0.0.1",
                        "start": "10.0.0.1",
                        "end": "10.0.0.99",
                    },
                },
            )

    def test_configure_dhcp_gateway_raises_if_dynamic_range_required(self):
        user = factory.make_admin()
        handler = VLANHandler(user, {}, None)
        vlan = factory.make_VLAN()
        rack = factory.make_RackController()
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=rack, vlan=vlan)
        subnet = factory.make_Subnet(
            vlan=vlan, cidr="10.0.0.0/24", gateway_ip=""
        )
        assert 0 == subnet.get_dynamic_ranges().count()

        with post_commit_hooks:
            pytest.raises(
                ValueError,
                handler.configure_dhcp,
                {
                    "id": vlan.id,
                    "controllers": [rack.system_id],
                    "extra": {
                        "subnet": subnet.id,
                        "gateway": "10.0.0.1",
                        "start": "",
                        "end": "",
                    },
                },
            )

    def test_configure_dhcp_ignores_undefined_subnet(self):
        user = factory.make_admin()
        handler = VLANHandler(user, {}, None)
        vlan = factory.make_VLAN()
        rack = factory.make_RackController()
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=rack, vlan=vlan)
        factory.make_ipv4_Subnet_with_IPRanges(vlan=vlan)

        with post_commit_hooks:
            handler.configure_dhcp(
                {
                    "id": vlan.id,
                    "controllers": [rack.system_id],
                    "extra": {
                        "subnet": None,
                        "gateway": "",
                        "start": "",
                        "end": "",
                    },
                }
            )

        vlan = reload_object(vlan)
        assert vlan.dhcp_on
        assert rack == vlan.primary_rack


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestVLANHandlerViewPermission:
    def deny_global_view(self):
        client = openfga.get_openfga_client()
        client.can_view_global_entities = MagicMock(return_value=False)

    def test_list_requires_view_permission(self):
        self.deny_global_view()
        handler = VLANHandler(factory.make_User(), {}, None)
        factory.make_VLAN()
        pytest.raises(HandlerPermissionError, handler.list, {})

    def test_get_requires_view_permission(self):
        self.deny_global_view()
        vlan = factory.make_VLAN()
        handler = VLANHandler(factory.make_User(), {}, None)
        pytest.raises(HandlerPermissionError, handler.get, {"id": vlan.id})
