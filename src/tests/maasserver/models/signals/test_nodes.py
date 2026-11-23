# Copyright 2015-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


import random

import pytest

from maasserver.enum import (
    IPADDRESS_TYPE,
    NODE_STATUS,
    NODE_STATUS_CHOICES,
    NODE_TYPE,
    NODE_TYPE_CHOICES,
)
from maasserver.models import (
    DNSPublication,
    Node,
    RackController,
    StaticIPAddress,
)
from maasserver.models.nodekey import NodeKey
from maasserver.models.service import RACK_SERVICES, REGION_SERVICES, Service
from maasserver.models.signals import power
from maasserver.node_status import NODE_TRANSITIONS
from maasserver.testing.factory import factory
from maasserver.utils.orm import post_commit_hooks, reload_object
from provisioningserver.enum import POWER_STATE, POWER_STATE_CHOICES


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNodeDeletion:
    def test_deleting_node_updates_event_node_hostname(self):
        """Test that event's `node_hostname` is set when the node is going to be
        deleted."""
        node = factory.make_Node()
        node_hostname = node.hostname
        events = [factory.make_Event(node=node) for _ in range(3)]
        node.delete()
        for event in events:
            assert event.node_hostname == node_hostname

    def test_deleting_node_sets_node_to_null(self):
        node = factory.make_Node()
        events = [factory.make_Event(node=node) for _ in range(3)]
        node.delete()
        for event in events:
            event = reload_object(event)
            assert event.node is None

    def test_deleting_node_creates_dnspublication(self):
        domain = factory.make_Domain("example.com", authoritative=True)
        node = factory.make_Node(domain=domain)
        node.delete()
        dnspublication = DNSPublication.objects.get_most_recent()
        assert f"removed node {node.hostname}" in dnspublication.source

    def test_deleting_node_does_not_create_dnspublication_if_domain_is_not_authoritative(
        self,
    ):
        domain = factory.make_Domain("example.com", authoritative=False)
        node = factory.make_Node(domain=domain)
        node.delete()
        dnspublication = DNSPublication.objects.get_most_recent()
        assert f"removed node {node.hostname}" not in dnspublication.source


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNodeUpdateEmitsDNSPublication:
    def test_updating_node_hostname_emits_dnspublication(self):
        domain = factory.make_Domain("example.com", authoritative=True)
        node = factory.make_Node(domain=domain, hostname="old-hostname")
        node.hostname = "new-hostname"
        with post_commit_hooks:
            node.save()
        dnspublication = DNSPublication.objects.get_most_recent()
        assert (
            "node old-hostname changed hostname to new-hostname"
            in dnspublication.source
        )

    def test_updating_node_domain_emits_dnspublication(self):
        old_domain = factory.make_Domain("old-example.com", authoritative=True)
        new_domain = factory.make_Domain("new-example.com", authoritative=True)
        node = factory.make_Node(domain=old_domain)
        node.domain = new_domain
        with post_commit_hooks:
            node.save()
        dnspublication = DNSPublication.objects.get_most_recent()
        assert (
            f"node {node.hostname} changed zone to new-example.com"
            in dnspublication.source
        )

    def test_updating_node_does_not_emit_dnspublication_if_domain_is_not_authoritative(
        self,
    ):
        old_domain = factory.make_Domain(
            "old-example.com", authoritative=False
        )
        new_domain = factory.make_Domain(
            "new-example.com", authoritative=False
        )
        node = factory.make_Node(domain=old_domain)
        node.domain = new_domain
        with post_commit_hooks:
            node.save()
        dnspublication = DNSPublication.objects.get_most_recent()
        assert (
            f"node {node.hostname} changed zone to new-example.com"
            not in dnspublication.source
        )


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNodePreviousStatus:
    """Test that `previous_status` is set when the status is changed."""

    @pytest.fixture(autouse=True)
    def _disable_power_signals(self, request):
        power.signals.disable()
        request.addfinalizer(power.signals.enable)

    def test_changing_status_updates_previous_status(self):
        node = factory.make_Node()
        old_status = node.status
        new_status = random.choice(NODE_TRANSITIONS[node.status])
        node.update_status(new_status)
        node.save()
        assert node.status == new_status
        assert node.previous_status == old_status

    def test_chaning_status_doesnt_store_blacklisted_statuses(self):
        black_listed_statuses = [
            NODE_STATUS.RESCUE_MODE,
            NODE_STATUS.ENTERING_RESCUE_MODE,
            NODE_STATUS.FAILED_ENTERING_RESCUE_MODE,
            NODE_STATUS.EXITING_RESCUE_MODE,
            NODE_STATUS.FAILED_EXITING_RESCUE_MODE,
            NODE_STATUS.TESTING,
        ]
        status = random.choice(black_listed_statuses)
        previous_status = factory.pick_choice(
            NODE_STATUS_CHOICES, but_not=black_listed_statuses
        )
        node = factory.make_Node(
            previous_status=previous_status, status=status
        )
        node.update_status(random.choice(NODE_TRANSITIONS[node.status]))
        node.save()
        assert previous_status == node.previous_status


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNodeClearsOwnerNEWOrREADYStatus:
    """Test that `owner` is cleared when the status is set to
    NEW or READY state.
    """

    @pytest.fixture(autouse=True)
    def _disable_power_signals(self, request):
        power.signals.disable()
        request.addfinalizer(power.signals.enable)

    def test_changing_to_new_status_clears_owner(self):
        node = factory.make_Node(
            owner=factory.make_User(), status=NODE_STATUS.COMMISSIONING
        )
        node.update_status(NODE_STATUS.NEW)
        node.save()
        assert node.owner is None

    def test_changing_to_ready_status_clears_owner(self):
        node = factory.make_Node(owner=factory.make_User())
        node.update_status(NODE_STATUS.READY)
        node.save()
        assert node.owner is None


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNodeKeyPolicy:
    """Test that `NodeKey`s are cleared when nodes change ownership."""

    def test_changing_owner_clears_node_key(self):
        node = factory.make_Node(status=NODE_STATUS.READY)
        # Ensure the node has an owner.
        node.owner = factory.make_User()
        node.save()
        # Ensure there's a token.
        token = NodeKey.objects.get_token_for_node(node)
        assert token is not None
        # Change the owner.
        node.owner = factory.make_User()
        node.save()
        # The token has been deleted.
        token = reload_object(token)
        assert token is None

    def test_clearing_owner_clears_node_key(self):
        node = factory.make_Node(status=NODE_STATUS.READY)
        # Ensure that the node has an owner.
        node.owner = factory.make_User()
        node.save()
        # Ensure there's a token.
        token = NodeKey.objects.get_token_for_node(node)
        assert token is not None
        # Remove the owner.
        node.owner = None
        node.save()
        # The token has been deleted.
        token = reload_object(token)
        assert token is None

    def test_setting_owner_clears_node_key(self):
        node = factory.make_Node(status=NODE_STATUS.READY)
        # Ensure the node has no owner.
        node.owner = None
        node.save()
        # Ensure there's a token.
        token = NodeKey.objects.get_token_for_node(node)
        assert token is not None
        # Set the owner.
        node.owner = factory.make_User()
        node.save()
        # The token has been deleted.
        token = reload_object(token)
        assert token is None


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNodeCreateServices:
    """Test that services are created when a node is created
    or node_type changes.
    """

    def test_doesnt_create_services_for_machine(self):
        machine = factory.make_Node()
        services = Service.objects.filter(node=machine)
        assert {service.name for service in services} == set()

    def test_doesnt_create_services_for_device(self):
        device = factory.make_Device()
        services = Service.objects.filter(node=device)
        assert {service.name for service in services} == set()

    def test_creates_services_for_rack_controller(self):
        rack_controller = factory.make_RackController()
        services = Service.objects.filter(node=rack_controller)
        assert {service.name for service in services} == RACK_SERVICES

    def test_creates_services_for_region_controller(self):
        region_controller = factory.make_RegionController()
        services = Service.objects.filter(node=region_controller)
        assert {service.name for service in services} == REGION_SERVICES

    def test_creates_services_when_region_converts_to_region_rack(self):
        controller = factory.make_RegionController()
        controller.node_type = NODE_TYPE.REGION_AND_RACK_CONTROLLER
        controller.save()
        services = Service.objects.filter(node=controller)
        assert {service.name for service in services} == (
            REGION_SERVICES | RACK_SERVICES
        )

    def test_creates_services_when_rack_controller_becomes_just_region(self):
        controller = factory.make_RackController()
        controller.node_type = NODE_TYPE.REGION_CONTROLLER
        controller.save()
        services = Service.objects.filter(node=controller)
        assert {service.name for service in services} == REGION_SERVICES


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNodeDefaultNUMANode:
    def test_create_node_creates_default_numanode(self):
        node = Node()
        node.save()
        [numanode] = node.numanode_set.all()
        assert numanode.node is node
        assert numanode.index == 0

    def test_create_node_creates_default_numanode_controller(self):
        node = RackController()
        node.save()
        [numanode] = node.numanode_set.all()
        assert numanode.node is node
        assert numanode.index == 0

    def test_update_doesnt_create_numanode(self):
        node = factory.make_Node()
        [numanode] = node.numanode_set.all()
        node.hostname = factory.make_string()
        with post_commit_hooks:
            node.save()
        [new_numanode] = node.numanode_set.all()
        assert new_numanode.id == numanode.id

    def test_not_for_devices(self):
        device = factory.make_Device()
        assert device.numanode_set.count() == 0


@pytest.mark.parametrize(
    "status",
    [
        status
        for status, status_label in NODE_STATUS_CHOICES
        if status
        not in [
            NODE_STATUS.COMMISSIONING,
            NODE_STATUS.DEPLOYED,
            NODE_STATUS.DEPLOYING,
            NODE_STATUS.DISK_ERASING,
            NODE_STATUS.RESCUE_MODE,
            NODE_STATUS.ENTERING_RESCUE_MODE,
            NODE_STATUS.TESTING,
        ]
    ],
)
@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "factory"
)
class TestNodeReleasesAutoIPs:
    reserved_statuses = [
        NODE_STATUS.COMMISSIONING,
        NODE_STATUS.DEPLOYED,
        NODE_STATUS.DEPLOYING,
        NODE_STATUS.DISK_ERASING,
        NODE_STATUS.RESCUE_MODE,
        NODE_STATUS.ENTERING_RESCUE_MODE,
        NODE_STATUS.TESTING,
    ]

    def test_releases_interface_config_when_turned_off(self, status):
        machine = factory.make_Machine_with_Interface_on_Subnet(
            status=random.choice(self.reserved_statuses),
            power_state=POWER_STATE.ON,
        )

        with post_commit_hooks:
            for interface in machine.current_config.interface_set.all():
                interface.claim_auto_ips()

        # Hack to get around node transition model
        Node.objects.filter(id=machine.id).update(status=status)
        machine = reload_object(machine)
        machine.power_state = POWER_STATE.OFF

        with post_commit_hooks:
            machine.save()

        for ip in StaticIPAddress.objects.filter(
            interface__node_config__node=machine,
            alloc_type=IPADDRESS_TYPE.AUTO,
        ):
            assert ip.ip is None

    def test_does_nothing_if_not_off(self, status):
        machine = factory.make_Machine_with_Interface_on_Subnet(
            status=random.choice(self.reserved_statuses),
            power_state=POWER_STATE.ON,
        )

        with post_commit_hooks:
            for interface in machine.current_config.interface_set.all():
                interface.claim_auto_ips()

        # Hack to get around node transition model
        Node.objects.filter(id=machine.id).update(status=status)
        machine = reload_object(machine)
        machine.power_state = factory.pick_choice(
            POWER_STATE_CHOICES, but_not=[POWER_STATE.OFF]
        )
        machine.save()

        for ip in StaticIPAddress.objects.filter(
            interface__node_config__node=machine,
            alloc_type=IPADDRESS_TYPE.AUTO,
        ):
            assert ip.ip is not None

    def test_does_nothing_if_reserved_status(self, status):
        machine = factory.make_Machine_with_Interface_on_Subnet(
            status=status, power_state=POWER_STATE.ON
        )

        with post_commit_hooks:
            for interface in machine.current_config.interface_set.all():
                interface.claim_auto_ips()

        # Hack to get around node transition model
        Node.objects.filter(id=machine.id).update(
            status=random.choice(self.reserved_statuses)
        )
        machine = reload_object(machine)
        machine.power_state = POWER_STATE.OFF
        machine.save()

        for ip in StaticIPAddress.objects.filter(
            interface__node_config__node=machine,
            alloc_type=IPADDRESS_TYPE.AUTO,
        ):
            assert ip.ip is not None

    def test_does_nothing_if_not_machine(self, status):
        node = factory.make_Node_with_Interface_on_Subnet(
            node_type=factory.pick_choice(
                NODE_TYPE_CHOICES, but_not=[NODE_TYPE.MACHINE]
            ),
            status=random.choice(self.reserved_statuses),
            power_state=POWER_STATE.ON,
        )

        with post_commit_hooks:
            for interface in node.current_config.interface_set.all():
                interface.claim_auto_ips()

        # Hack to get around node transition model
        Node.objects.filter(id=node.id).update(status=status)
        node = reload_object(node)
        node.power_state = POWER_STATE.OFF
        node.save()

        for ip in StaticIPAddress.objects.filter(
            interface__node_config__node=node, alloc_type=IPADDRESS_TYPE.AUTO
        ):
            assert ip.ip is not None
