# Copyright 2015-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import random

from django.core.exceptions import ValidationError
from django.db.models import ProtectedError
import pytest

from maasserver.enum import INTERFACE_TYPE
from maasserver.models.interface import PhysicalInterface, VLANInterface
from maasserver.models.notification import Notification
from maasserver.models.vlan import VLAN
from maasserver.testing.factory import factory
from maasserver.utils.orm import post_commit_hooks, reload_object


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestVLANManager:
    def test_default_specifier_matches_vid(self):
        # Note: this is for backward compatibility with the previous iteration
        # of constraints, which used vlan:<number> to mean VID, not represent
        # a database ID.
        with post_commit_hooks:
            factory.make_VLAN()
            vlan = factory.make_VLAN()
            factory.make_VLAN()
        vid = vlan.vid
        assert list(VLAN.objects.filter_by_specifiers("%s" % vid)) == [vlan]

    def test_default_specifier_matches_name(self):
        with post_commit_hooks:
            factory.make_VLAN()
            vlan = factory.make_VLAN(name="infinite-improbability")
            factory.make_VLAN()
        assert list(
            VLAN.objects.filter_by_specifiers("infinite-improbability")
        ) == [vlan]

    def test_name_specifier_matches_name(self):
        with post_commit_hooks:
            factory.make_VLAN()
            vlan = factory.make_VLAN(name="infinite-improbability")
            factory.make_VLAN()
        assert list(
            VLAN.objects.filter_by_specifiers("name:infinite-improbability")
        ) == [vlan]

    def test_vid_specifier_matches_vid(self):
        with post_commit_hooks:
            factory.make_VLAN()
            vlan = factory.make_VLAN()
            vid = vlan.vid
            factory.make_VLAN()
        assert list(VLAN.objects.filter_by_specifiers("vid:%d" % vid)) == [
            vlan
        ]

    def test_space_specifier_matches_space_by_name(self):
        with post_commit_hooks:
            factory.make_VLAN()
            space = factory.make_Space()
            vlan = factory.make_VLAN(space=space)
            factory.make_VLAN()
        assert list(
            VLAN.objects.filter_by_specifiers("space:%s" % space.name)
        ) == [vlan]

    def test_space_specifier_matches_space_by_id(self):
        with post_commit_hooks:
            factory.make_VLAN()
            space = factory.make_Space()
            vlan = factory.make_VLAN(space=space)
            factory.make_VLAN()
        assert list(
            VLAN.objects.filter_by_specifiers("space:%s" % space.id)
        ) == [vlan]

    def test_class_specifier_matches_attached_subnet(self):
        with post_commit_hooks:
            factory.make_VLAN()
            vlan = factory.make_VLAN()
            subnet = factory.make_Subnet(vlan=vlan)
            factory.make_VLAN()
        assert list(
            VLAN.objects.filter_by_specifiers("subnet:%s" % subnet.id)
        ) == [vlan]

    def test_class_specifier_matches_attached_fabric(self):
        with post_commit_hooks:
            factory.make_Fabric()
            fabric = factory.make_Fabric(name="rack42")
            factory.make_VLAN()
            vlan = factory.make_VLAN(fabric=fabric)
            factory.make_VLAN()
        assert list(
            VLAN.objects.filter_by_specifiers(
                "fabric:%s,vid:%d" % (fabric.name, vlan.vid)
            )
        ) == [vlan]


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestVLAN:
    def test_delete_relay_vlan_doesnt_delete_vlan(self):
        with post_commit_hooks:
            relay_vlan = factory.make_VLAN()
            vlan = factory.make_VLAN(relay_vlan=relay_vlan)
            relay_vlan.delete()
        vlan = reload_object(vlan)
        assert vlan is not None
        assert vlan.relay_vlan is None

    def test_delete_primary_rack_fails(self):
        rack = factory.make_RackController()
        with post_commit_hooks:
            vlan = factory.make_VLAN(primary_rack=rack)
        with pytest.raises(ProtectedError):
            rack.delete()
        vlan = reload_object(vlan)
        assert vlan is not None
        assert vlan.primary_rack == rack

    def test_get_name_for_default_vlan_is_untagged(self):
        fabric = factory.make_Fabric()
        assert fabric.get_default_vlan().get_name() == "untagged"

    def test_get_name_for_set_name(self):
        name = factory.make_name("name")
        vlan = factory.make_VLAN(name=name)
        assert vlan.get_name() == name

    def test_get_name_for_unnamed_vlan(self):
        vlan = factory.make_VLAN()
        assert vlan.get_name() is None

    def test_creates_vlan(self):
        name = factory.make_name("name")
        vid = random.randint(3, 55)
        fabric = factory.make_Fabric()
        vlan = VLAN(vid=vid, name=name, fabric=fabric)

        with post_commit_hooks:
            vlan.save()

        assert vlan.vid == vid
        assert vlan.name == name

    def test_is_fabric_default_detects_default_vlan(self):
        fabric = factory.make_Fabric()
        factory.make_VLAN(fabric=fabric)
        vlan = fabric.vlan_set.all().order_by("id").first()
        assert vlan.is_fabric_default()

    def test_is_fabric_default_detects_non_default_vlan(self):
        vlan = factory.make_VLAN()
        assert not vlan.is_fabric_default()

    def test_cant_delete_default_vlan(self):
        name = factory.make_name("name")
        fabric = factory.make_Fabric(name=name)
        with pytest.raises(
            ValidationError,
            match="This VLAN is the default VLAN in the fabric",
        ):
            fabric.get_default_vlan().delete()

    def test_manager_get_default_vlan_returns_dflt_vlan_of_dflt_fabric(self):
        factory.make_Fabric()
        vlan = VLAN.objects.get_default_vlan()
        assert vlan.is_fabric_default()
        assert vlan.fabric.is_default()

    def test_vlan_interfaces_are_deleted_when_related_vlan_is_deleted(self):
        node = factory.make_Node()
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        vlan = factory.make_VLAN()
        interface = factory.make_Interface(
            INTERFACE_TYPE.VLAN, vlan=vlan, parents=[parent]
        )
        vlan.delete()
        assert not list(VLANInterface.objects.filter(id=interface.id))

    def test_interfaces_are_reconnected_when_vlan_is_deleted(self):
        node = factory.make_Node()
        vlan = factory.make_VLAN()
        fabric = vlan.fabric
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=node, vlan=vlan
        )
        vlan.delete()
        reconnected_interfaces = PhysicalInterface.objects.filter(
            id=interface.id
        )
        assert list(reconnected_interfaces) == [interface]
        reconnected_interface = reconnected_interfaces[0]
        assert reconnected_interface.vlan == fabric.get_default_vlan()

    def test_raises_integrity_error_if_reconnecting_fails(self, mocker):
        # Here we test a corner case: we test that the DB refuses to
        # leave an interface without a VLAN in case the reconnection
        # fails when a VLAN is deleted.
        vlan = factory.make_VLAN()
        # Break 'manage_connected_interfaces'.
        mocker.patch.object(vlan, "manage_connected_interfaces")
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL, vlan=vlan)
        with pytest.raises(ProtectedError, match="Interface.vlan"):
            vlan.delete()

    def test_subnets_are_reconnected_when_vlan_is_deleted(self):
        with post_commit_hooks:
            fabric = factory.make_Fabric()
            vlan = factory.make_VLAN(fabric=fabric)
            subnet = factory.make_Subnet(vlan=vlan)
            vlan.delete()
        assert reload_object(subnet).vlan == fabric.get_default_vlan()

    def tests_creates_notification_when_no_dhcp(self):
        Notification.objects.filter(ident="dhcp_disabled_all_vlans").delete()
        factory.make_VLAN(dhcp_on=False)
        assert Notification.objects.filter(
            ident="dhcp_disabled_all_vlans"
        ).exists()

    def tests_deletes_notification_once_there_is_dhcp(self):
        Notification.objects.filter(ident="dhcp_disabled_all_vlans").delete()
        with post_commit_hooks:
            # Force the notification to exist
            vlan = factory.make_VLAN(dhcp_on=False)
            # Now clear it.
            vlan.dhcp_on = True
            vlan.save()
        assert not Notification.objects.filter(
            ident="dhcp_disabled_all_vlans"
        ).exists()

    def test_connected_rack_controllers(self):
        with post_commit_hooks:
            vlan = factory.make_VLAN()
            racks = [factory.make_RackController(vlan=vlan) for _ in range(3)]
        assert set(vlan.connected_rack_controllers()) == set(racks)


@pytest.mark.parametrize(
    "vid,valid",
    [
        (0, True),
        (12, True),
        (250, True),
        (3000, True),
        (4095, False),
        (4094, True),
        (-23, False),
        (4096, False),
        (10000, False),
    ],
    ids=["0", "12", "250", "3000", "4095", "4094", "-23", "4096", "10000"],
)
@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestVLANVidValidation:
    def test_validates_vid(self, vid, valid):
        fabric = factory.make_Fabric()
        # Update the VID of the default VLAN so that it doesn't clash with
        # the VIDs we're testing here.
        default_vlan = fabric.get_default_vlan()
        default_vlan.vid = 999

        with post_commit_hooks:
            default_vlan.save()

            name = factory.make_name("name")
            vlan = VLAN(vid=vid, name=name, fabric=fabric)
            if valid:
                # No exception.
                assert vlan.save() is None

            else:
                with pytest.raises(ValidationError):
                    vlan.save()


@pytest.mark.parametrize(
    "mtu,valid",
    [(551, False), (552, True), (65535, True), (65536, False)],
    ids=["551", "552", "65535", "65536"],
)
@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestVLANMTUValidation:
    def test_validates_mtu(self, mtu, valid):
        vlan = factory.make_VLAN()
        vlan.mtu = mtu

        with post_commit_hooks:
            if valid:
                # No exception.
                assert vlan.save() is None
            else:
                with pytest.raises(ValidationError):
                    vlan.save()
