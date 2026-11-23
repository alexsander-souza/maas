# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for VLAN forms."""

from collections import Counter
import random

import pytest

from maasserver.enum import SERVICE_STATUS
from maasserver.forms.vlan import VLANForm
from maasserver.models.fabric import Fabric
from maasserver.models.service import Service
from maasserver.models.vlan import DEFAULT_MTU
from maasserver.testing.factory import factory
from maasserver.utils.orm import post_commit_hooks, reload_object


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestVLANForm:
    def test_requires_vid(self):
        fabric = factory.make_Fabric()
        form = VLANForm(fabric=fabric, data={})
        assert not form.is_valid(), form.errors
        assert {
            "vid": [
                "This field is required.",
                "VID must be between 0 and 4094.",
            ]
        } == form.errors

    def test_vlans_already_using_relay_vlan_not_shown(self):
        fabric = Fabric.objects.get_default_fabric()
        relay_vlan = factory.make_VLAN()
        factory.make_VLAN(relay_vlan=relay_vlan)
        form = VLANForm(fabric=fabric, data={})
        assert Counter([fabric.get_default_vlan(), relay_vlan]) == Counter(
            form.fields["relay_vlan"].queryset
        )

    def test_self_vlan_not_used_in_relay_vlan_field(self):
        fabric = Fabric.objects.get_default_fabric()
        relay_vlan = fabric.get_default_vlan()
        form = VLANForm(instance=relay_vlan, data={})
        assert Counter([]) == Counter(form.fields["relay_vlan"].queryset)

    def test_no_relay_vlans_allowed_when_dhcp_on(self):
        vlan = factory.make_VLAN(dhcp_on=True)
        factory.make_VLAN()
        form = VLANForm(instance=vlan, data={})
        assert Counter([]) == Counter(form.fields["relay_vlan"].queryset)

    def test_creates_vlan(self):
        fabric = factory.make_Fabric()
        vlan_name = factory.make_name("vlan")
        vlan_description = factory.make_name("description")
        vid = random.randint(1, 1000)
        mtu = random.randint(552, 4096)
        form = VLANForm(
            fabric=fabric,
            data={
                "name": vlan_name,
                "description": vlan_description,
                "vid": vid,
                "mtu": mtu,
            },
        )
        assert form.is_valid(), form.errors
        vlan = form.save()
        assert vlan_name == vlan.name
        assert vlan_description == vlan.description
        assert vid == vlan.vid
        assert fabric == vlan.fabric
        assert mtu == vlan.mtu

    def test_creates_vlan_with_default_mtu(self):
        fabric = factory.make_Fabric()
        vlan_name = factory.make_name("vlan")
        vid = random.randint(1, 1000)
        form = VLANForm(fabric=fabric, data={"name": vlan_name, "vid": vid})
        assert form.is_valid(), form.errors
        vlan = form.save()
        assert vlan_name == vlan.name
        assert vid == vlan.vid
        assert fabric == vlan.fabric
        assert DEFAULT_MTU == vlan.mtu

    def test_doest_require_name_vid_or_mtu_on_update(self):
        vlan = factory.make_VLAN()
        form = VLANForm(instance=vlan, data={})
        assert form.is_valid(), form.errors

    def test_updates_vlan(self):
        vlan = factory.make_VLAN()
        new_name = factory.make_name("vlan")
        new_description = factory.make_name("description")
        new_vid = random.randint(1, 1000)
        new_mtu = random.randint(552, 4096)
        form = VLANForm(
            instance=vlan,
            data={
                "name": new_name,
                "description": new_description,
                "vid": new_vid,
                "mtu": new_mtu,
            },
        )
        assert form.is_valid(), form.errors
        form.save()
        assert new_name == reload_object(vlan).name
        assert new_description == reload_object(vlan).description
        assert new_vid == reload_object(vlan).vid
        assert new_mtu == reload_object(vlan).mtu

    def test_update_verfies_primary_rack_is_on_vlan(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController()
        form = VLANForm(instance=vlan, data={"primary_rack": rack.system_id})
        assert not form.is_valid(), form.errors

    def test_update_sets_primary_rack(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController(vlan=vlan)
        form = VLANForm(instance=vlan, data={"primary_rack": rack.system_id})
        assert form.is_valid(), form.errors
        form.save()
        assert rack == reload_object(vlan).primary_rack

    def test_update_unsets_primary_rack(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController(vlan=vlan)
        vlan.primary_rack = rack

        with post_commit_hooks:
            vlan.save()

        form = VLANForm(instance=vlan, data={"primary_rack": ""})
        assert form.is_valid(), form.errors
        form.save()
        assert reload_object(vlan).primary_rack is None

    def test_update_verfies_secondary_rack_is_on_vlan(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController()
        form = VLANForm(instance=vlan, data={"secondary_rack": rack.system_id})
        assert not form.is_valid(), form.errors

    def test_update_sets_secondary_rack(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController(vlan=vlan)
        form = VLANForm(instance=vlan, data={"secondary_rack": rack.system_id})
        assert form.is_valid(), form.errors
        form.save()
        assert rack == reload_object(vlan).secondary_rack

    def test_update_unsets_secondary_rack(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController(vlan=vlan)
        vlan.secondary_rack = rack

        with post_commit_hooks:
            vlan.save()

        form = VLANForm(instance=vlan, data={"secondary_rack": ""})
        assert form.is_valid(), form.errors
        form.save()
        assert reload_object(vlan).secondary_rack is None

    def test_update_blank_primary_sets_to_secondary(self):
        vlan = factory.make_VLAN()
        primary_rack = factory.make_RackController(vlan=vlan)
        secondary_rack = factory.make_RackController(vlan=vlan)
        vlan.primary_rack = primary_rack
        vlan.secondary_rack = secondary_rack

        with post_commit_hooks:
            vlan.save()

        form = VLANForm(
            instance=reload_object(vlan), data={"primary_rack": ""}
        )
        assert form.is_valid(), form.errors
        form.save()
        vlan = reload_object(vlan)
        assert secondary_rack == vlan.primary_rack
        assert vlan.secondary_rack is None

    def test_update_primary_set_to_secondary_removes_secondary(self):
        vlan = factory.make_VLAN()
        primary_rack = factory.make_RackController(vlan=vlan)
        secondary_rack = factory.make_RackController(vlan=vlan)
        vlan.primary_rack = primary_rack
        vlan.secondary_rack = secondary_rack

        with post_commit_hooks:
            vlan.save()

        form = VLANForm(
            instance=reload_object(vlan),
            data={"primary_rack": secondary_rack.system_id},
        )
        assert form.is_valid(), form.errors
        form.save()
        vlan = reload_object(vlan)
        assert secondary_rack == vlan.primary_rack
        assert vlan.secondary_rack is None

    def test_update_secondary_set_to_existing_primary_fails(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController(vlan=vlan)
        vlan.primary_rack = rack

        with post_commit_hooks:
            vlan.save()

        form = VLANForm(
            instance=reload_object(vlan),
            data={"secondary_rack": rack.system_id},
        )
        assert not form.is_valid()

    def test_update_setting_both_racks_to_same_fails(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController(vlan=vlan)
        form = VLANForm(
            instance=vlan,
            data={
                "primary_rack": rack.system_id,
                "secondary_rack": rack.system_id,
            },
        )
        assert not form.is_valid()

    def test_update_setting_secondary_fails_when_primary_dead(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController(vlan=vlan)
        vlan.primary_rack = rack

        with post_commit_hooks:
            vlan.save()

        service = Service.objects.get(node=rack, name="rackd")
        service.status = SERVICE_STATUS.DEAD
        service.save()
        second_rack = factory.make_RackController(vlan=vlan)
        form = VLANForm(
            instance=vlan, data={"secondary_rack": second_rack.system_id}
        )
        assert not form.is_valid()

    def test_update_setting_secondary_allowed_when_primary_on(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController(vlan=vlan)
        vlan.primary_rack = rack

        with post_commit_hooks:
            vlan.save()

        service = Service.objects.get(node=rack, name="rackd")
        service.status = SERVICE_STATUS.RUNNING
        service.save()
        second_rack = factory.make_RackController(vlan=vlan)
        form = VLANForm(
            instance=vlan, data={"secondary_rack": second_rack.system_id}
        )
        assert form.is_valid(), form.errors
        form.save()
        vlan = reload_object(vlan)
        assert second_rack == vlan.secondary_rack

    def test_update_turns_dhcp_on(self):
        vlan = factory.make_VLAN()
        factory.make_ipv4_Subnet_with_IPRanges(vlan=vlan)
        rack = factory.make_RackController(vlan=vlan)
        vlan.primary_rack = rack

        with post_commit_hooks:
            vlan.save()

        form = VLANForm(instance=reload_object(vlan), data={"dhcp_on": "true"})
        assert form.is_valid(), form.errors
        form.save()
        vlan = reload_object(vlan)
        assert vlan.dhcp_on

    def test_update_sets_relay_vlan(self):
        vlan = factory.make_VLAN()
        relay_vlan = factory.make_VLAN()
        form = VLANForm(instance=vlan, data={"relay_vlan": relay_vlan.id})
        assert form.is_valid(), form.errors
        with post_commit_hooks:
            form.save()
        vlan = reload_object(vlan)
        assert relay_vlan.id == vlan.relay_vlan.id

    def test_update_clears_relay_vlan_when_None(self):
        relay_vlan = factory.make_VLAN()
        vlan = factory.make_VLAN(relay_vlan=relay_vlan)
        form = VLANForm(instance=vlan, data={"relay_vlan": None})
        assert form.is_valid(), form.errors

        with post_commit_hooks:
            form.save()

        vlan = reload_object(vlan)
        assert vlan.relay_vlan is None

    def test_update_clears_relay_vlan_when_empty(self):
        relay_vlan = factory.make_VLAN()
        vlan = factory.make_VLAN(relay_vlan=relay_vlan)
        form = VLANForm(instance=vlan, data={"relay_vlan": ""})
        assert form.is_valid(), form.errors

        with post_commit_hooks:
            form.save()

        vlan = reload_object(vlan)
        assert vlan.relay_vlan is None

    def test_update_sets_space(self):
        vlan = factory.make_VLAN()
        space = factory.make_Space()
        form = VLANForm(instance=vlan, data={"space": space.id})
        assert form.is_valid(), form.errors

        with post_commit_hooks:
            form.save()

        vlan = reload_object(vlan)
        assert space.id == vlan.space.id

    def test_update_sets_space_by_specifier(self):
        vlan = factory.make_VLAN()
        space = factory.make_Space()
        form = VLANForm(instance=vlan, data={"space": "name:" + space.name})
        assert form.is_valid(), form.errors

        with post_commit_hooks:
            form.save()

        vlan = reload_object(vlan)
        assert space.id == vlan.space.id

    def test_update_clears_space_when_None(self):
        space = factory.make_Space()
        vlan = factory.make_VLAN(space=space)
        form = VLANForm(instance=vlan, data={"space": None})
        assert form.is_valid(), form.errors

        with post_commit_hooks:
            form.save()

        vlan = reload_object(vlan)
        assert vlan.space is None

    def test_update_clears_space_when_empty(self):
        space = factory.make_Space()
        vlan = factory.make_VLAN(space=space)
        form = VLANForm(instance=vlan, data={"space": ""})
        assert form.is_valid(), form.errors

        with post_commit_hooks:
            form.save()

        vlan = reload_object(vlan)
        assert vlan.space is None

    def test_update_clears_space_vlan_when_empty(self):
        space = factory.make_Space()
        vlan = factory.make_VLAN(space=space)
        form = VLANForm(instance=vlan, data={"space": ""})
        assert form.is_valid(), form.errors

        with post_commit_hooks:
            form.save()

        vlan = reload_object(vlan)
        assert vlan.space is None

    def test_update_disables_relay_vlan_when_dhcp_turned_on(self):
        relay_vlan = factory.make_VLAN()
        vlan = factory.make_VLAN(relay_vlan=relay_vlan)
        factory.make_ipv4_Subnet_with_IPRanges(vlan=vlan)
        rack = factory.make_RackController(vlan=vlan)
        vlan.primary_rack = rack

        with post_commit_hooks:
            vlan.save()

        form = VLANForm(instance=reload_object(vlan), data={"dhcp_on": "true"})
        assert form.is_valid(), form.errors

        with post_commit_hooks:
            form.save()

        vlan = reload_object(vlan)
        assert vlan.relay_vlan is None

    def test_update_validates_primary_rack_with_dhcp_on(self):
        vlan = factory.make_VLAN()
        form = VLANForm(instance=vlan, data={"dhcp_on": "true"})
        assert not form.is_valid()

    def test_update_validates_subnet_with_dhcp_on(self):
        vlan = factory.make_VLAN()
        rack = factory.make_RackController(vlan=vlan)
        vlan.primary_rack = rack

        with post_commit_hooks:
            vlan.save()

        form = VLANForm(instance=reload_object(vlan), data={"dhcp_on": "true"})
        assert not form.is_valid()

    def test_update_can_delete_primary_and_set_dhcp_on_with_secondary(self):
        vlan = factory.make_VLAN()
        factory.make_ipv4_Subnet_with_IPRanges(vlan=vlan)
        primary_rack = factory.make_RackController(vlan=vlan)
        secondary_rack = factory.make_RackController(vlan=vlan)
        vlan.primary_rack = primary_rack
        vlan.secondary_rack = secondary_rack

        with post_commit_hooks:
            vlan.save()

        form = VLANForm(
            instance=reload_object(vlan),
            data={"primary_rack": "", "dhcp_on": "true"},
        )
        assert form.is_valid(), form.errors

        with post_commit_hooks:
            form.save()

        vlan = reload_object(vlan)
        assert secondary_rack == vlan.primary_rack
        assert vlan.secondary_rack is None
        assert vlan.dhcp_on


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestVLANFormFabricModification:
    def test_cannot_move_vlan_with_overlapping_vid(self):
        fabric0 = Fabric.objects.get_default_fabric()
        fabric1 = factory.make_Fabric()
        fabric1_untagged = fabric1.get_default_vlan()
        form = VLANForm(instance=fabric1_untagged, data={"fabric": fabric0.id})
        is_valid = form.is_valid()
        assert not is_valid
        assert dict(form.errors) == {
            "__all__": [
                "A VLAN with the specified VID already "
                "exists in the destination fabric."
            ]
        }
        with pytest.raises(ValueError):
            form.save()

    def test_allows_moving_vlan_to_new_fabric_if_vid_is_unique(self):
        fabric0 = Fabric.objects.get_default_fabric()
        fabric1 = factory.make_Fabric()
        fabric1_untagged = fabric1.get_default_vlan()
        form = VLANForm(
            instance=fabric1_untagged, data={"fabric": fabric0.id, "vid": 10}
        )
        is_valid = form.is_valid()
        assert is_valid
        form.save()

    def test_deletes_empty_fabrics(self):
        fabric0 = Fabric.objects.get_default_fabric()
        fabric1 = factory.make_Fabric()
        fabric1_untagged = fabric1.get_default_vlan()
        form = VLANForm(
            instance=fabric1_untagged, data={"fabric": fabric0.id, "vid": 10}
        )
        is_valid = form.is_valid()
        assert is_valid
        form.save()
        assert reload_object(fabric1) is None

    def test_does_not_delete_non_empty_fabrics(self):
        fabric0 = Fabric.objects.get_default_fabric()
        fabric1 = factory.make_Fabric()
        factory.make_VLAN(fabric=fabric1)
        fabric1_untagged = fabric1.get_default_vlan()
        form = VLANForm(
            instance=fabric1_untagged, data={"fabric": fabric0.id, "vid": 10}
        )
        is_valid = form.is_valid()
        form.save()
        assert is_valid
        assert reload_object(fabric1) is not None
