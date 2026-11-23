# Copyright 2015-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from collections.abc import Iterable
import datetime
import random
import re
import threading
from unittest.mock import call

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections, IntegrityError, transaction
from django.http import Http404
from django.utils import timezone
from fixtures import FakeLogger
from netaddr import EUI, IPAddress, IPNetwork
import pytest

from maascommon.workflows.dhcp import (
    CONFIGURE_DHCP_WORKFLOW_NAME,
    ConfigureDHCPParam,
)
from maasserver.enum import (
    BRIDGE_TYPE,
    BRIDGE_TYPE_CHOICES,
    INTERFACE_LINK_TYPE,
    INTERFACE_TYPE,
    IPADDRESS_TYPE,
    IPRANGE_TYPE,
    NODE_STATUS,
)
from maasserver.exceptions import (
    StaticIPAddressExhaustion,
    StaticIPAddressOutOfRange,
    StaticIPAddressReservedIPConflict,
    StaticIPAddressUnavailable,
)
from maasserver.models import interface as interface_module
from maasserver.models import (
    MDNS,
    Neighbour,
    Space,
    StaticIPAddress,
    Subnet,
    VLAN,
)
from maasserver.models import staticipaddress as staticipaddress_module
from maasserver.models.config import NetworkDiscoveryConfig
from maasserver.models.interface import (
    BondInterface,
    BridgeInterface,
    Interface,
    InterfaceRelationship,
    PhysicalInterface,
    UnknownInterface,
    VLANInterface,
)
from maasserver.models.vlan import DEFAULT_MTU
from maasserver.permissions import NodePermission
from maasserver.testing.factory import factory
from maasserver.testing.orm import reload_objects
from maasserver.utils.orm import (
    get_one,
    post_commit_hooks,
    reload_object,
    transactional,
)
from maastesting.djangotestcase import CountQueries
from provisioningserver.utils.network import (
    annotate_with_default_monitored_interfaces,
)


@pytest.fixture
def transactional_maasdb(maasdb):
    """Provide the database as `MAASTransactionServerTestCase` did.

    The `maasdb` fixture leaves autocommit disabled, under which
    `transaction.atomic()` only creates savepoints (subtransactions). The
    tests using this fixture need top-level transactions and real commits,
    so autocommit is restored here.
    """
    transaction.rollback()
    transaction.set_autocommit(True)
    yield


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestInterfaceManager:
    def test_get_queryset_returns_all_interface_types(self):
        physical = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        bond = factory.make_Interface(INTERFACE_TYPE.BOND, parents=[physical])
        vlan = factory.make_Interface(INTERFACE_TYPE.VLAN, parents=[bond])
        assert sorted([physical, bond, vlan], key=str) == sorted(
            Interface.objects.all(), key=str
        )

    def test_get_interface_or_404_returns_interface(self):
        node = factory.make_Node()
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        user = factory.make_User()
        assert interface == (
            Interface.objects.get_interface_or_404(
                node.system_id, interface.id, user, NodePermission.view
            )
        )

    def test_get_interface_or_404_returns_interface_for_admin(self):
        node = factory.make_Node()
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        user = factory.make_admin()
        assert interface == (
            Interface.objects.get_interface_or_404(
                node.system_id, interface.id, user, NodePermission.admin
            )
        )

    def test_get_interface_or_404_raises_Http404_when_invalid_id(self):
        node = factory.make_Node()
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        user = factory.make_User()
        with pytest.raises(Http404):
            Interface.objects.get_interface_or_404(
                node.system_id,
                random.randint(1000 * 1000, 1000 * 1000 * 100),
                user,
                NodePermission.view,
            )

    def test_get_interface_or_404_raises_PermissionDenied_when_user(self):
        node = factory.make_Node()
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        user = factory.make_User()
        with pytest.raises(PermissionDenied):
            Interface.objects.get_interface_or_404(
                node.system_id,
                interface.id,
                user,
                NodePermission.admin,
            )

    def test_get_interface_or_404_uses_device_perm(self):
        user = factory.make_User()
        device = factory.make_Device(owner=user)
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=device
        )
        assert interface == (
            Interface.objects.get_interface_or_404(
                device.system_id,
                interface.id,
                user,
                NodePermission.admin,
                NodePermission.edit,
            )
        )

    def test_get_or_create_without_parents(self):
        node_config = factory.make_NodeConfig()
        mac_address = factory.make_mac_address()
        name = factory.make_name("eth")
        interface, created = PhysicalInterface.objects.get_or_create(
            node_config=node_config, mac_address=mac_address, name=name
        )
        assert created
        assert interface is not None
        retrieved_interface, created = PhysicalInterface.objects.get_or_create(
            node_config=node_config, mac_address=mac_address
        )
        assert not created
        assert interface == retrieved_interface

    def test_get_or_create_with_parents(self):
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            node_config=parent1.node_config,
        )
        interface, created = BondInterface.objects.get_or_create(
            node_config=parent1.node_config,
            mac_address=parent1.mac_address,
            name="bond0",
            parents=[parent1, parent2],
        )
        assert created
        assert interface is not None
        retrieved_interface, created = BondInterface.objects.get_or_create(
            node_config=parent1.node_config, parents=[parent1, parent2]
        )
        assert not created
        assert interface == retrieved_interface

    def test_get_interface_dict_for_node(self):
        node1 = factory.make_Node()
        node1_eth0 = factory.make_Interface(node=node1, name="eth0")
        node1_eth1 = factory.make_Interface(node=node1, name="eth1")
        node2 = factory.make_Node()
        node2_eth0 = factory.make_Interface(node=node2, name="eth0")
        node2_eth1 = factory.make_Interface(node=node2, name="eth1")
        assert {
            "eth0": node1_eth0,
            "eth1": node1_eth1,
        } == Interface.objects.get_interface_dict_for_node(node1)
        assert {
            "eth0": node2_eth0,
            "eth1": node2_eth1,
        } == Interface.objects.get_interface_dict_for_node(node2)

    def test_get_interface_dict_for_node__by_names(self):
        node1 = factory.make_Node()
        node1_eth0 = factory.make_Interface(node=node1, name="eth0")
        node1_eth1 = factory.make_Interface(node=node1, name="eth1")
        node2 = factory.make_Node()
        node2_eth0 = factory.make_Interface(node=node2, name="eth0")
        node2_eth1 = factory.make_Interface(node=node2, name="eth1")
        assert (
            Interface.objects.get_interface_dict_for_node(
                node1, names=("eth0",)
            )
        ) == {"eth0": node1_eth0}
        assert (
            Interface.objects.get_interface_dict_for_node(
                node1, names=("eth0", "eth1")
            )
        ) == {"eth0": node1_eth0, "eth1": node1_eth1}
        assert (
            Interface.objects.get_interface_dict_for_node(
                node2, names=("eth0", "eth1")
            )
        ) == {"eth0": node2_eth0, "eth1": node2_eth1}

    def test_get_all_interfaces_definition_for_node(self):
        node1 = factory.make_Node()
        eth0 = factory.make_Interface(node=node1, name="eth0")
        eth0_vlan = factory.make_Interface(
            iftype=INTERFACE_TYPE.VLAN, parents=[eth0], node=node1
        )
        eth1 = factory.make_Interface(node=node1, name="eth1", enabled=False)
        eth2 = factory.make_Interface(node=node1, name="eth2")
        eth4 = factory.make_Interface(node=node1, name="eth4")
        bond0 = factory.make_Interface(
            iftype=INTERFACE_TYPE.BOND,
            parents=[eth2],
            name="bond0",
            node=node1,
        )
        br0 = factory.make_Interface(
            iftype=INTERFACE_TYPE.BRIDGE,
            parents=[eth4],
            name="br0",
            node=node1,
        )
        br1 = factory.make_Interface(
            iftype=INTERFACE_TYPE.BRIDGE, parents=[], name="br1", node=node1
        )
        # Make sure we only got one Node's interfaces by creating a few
        # dummy interfaces.
        node2 = factory.make_Node()
        factory.make_Interface(node=node2, name="eth0")
        factory.make_Interface(node=node2, name="eth1")
        expected_result = {
            "eth0": {
                "type": "physical",
                "mac_address": str(eth0.mac_address),
                "enabled": True,
                "parents": [],
                "source": "maas-database",
                "obj": eth0,
                "monitored": True,
            },
            eth0_vlan.name: {
                "type": "vlan",
                "mac_address": str(eth0_vlan.mac_address),
                "enabled": True,
                "parents": ["eth0"],
                "source": "maas-database",
                "obj": eth0_vlan,
                "monitored": False,
            },
            "eth1": {
                "type": "physical",
                "mac_address": str(eth1.mac_address),
                "enabled": False,
                "parents": [],
                "source": "maas-database",
                "obj": eth1,
                "monitored": False,
            },
            "eth2": {
                "type": "physical",
                "mac_address": str(eth2.mac_address),
                "enabled": True,
                "parents": [],
                "source": "maas-database",
                "obj": eth2,
                "monitored": False,
            },
            "eth4": {
                "type": "physical",
                "mac_address": str(eth4.mac_address),
                "enabled": True,
                "parents": [],
                "source": "maas-database",
                "obj": eth4,
                # Physical bridge members are monitored.
                "monitored": True,
            },
            "bond0": {
                "type": "bond",
                "mac_address": str(bond0.mac_address),
                "enabled": True,
                "parents": ["eth2"],
                "source": "maas-database",
                "obj": bond0,
                # Bonds are monitored.
                "monitored": True,
            },
            "br0": {
                "type": "bridge",
                "mac_address": str(br0.mac_address),
                "enabled": True,
                "parents": ["eth4"],
                "source": "maas-database",
                "obj": br0,
                "monitored": False,
            },
            "br1": {
                "type": "bridge",
                "mac_address": str(br1.mac_address),
                "enabled": True,
                "parents": [],
                "source": "maas-database",
                "obj": br1,
                # Zero-parent bridges are monitored.
                "monitored": True,
            },
        }
        interfaces = Interface.objects.get_all_interfaces_definition_for_node(
            node1
        )
        # Need to ensure this call is compatible with the returned structure.
        annotate_with_default_monitored_interfaces(interfaces)
        assert interfaces == expected_result

    def test_get_interface_dict_for_node__prefetches_on_request(self):
        node1 = factory.make_Node()
        factory.make_Interface(node=node1, name="eth0")
        counter = CountQueries()
        with counter:
            interfaces = Interface.objects.get_interface_dict_for_node(
                node1, fetch_fabric_vlan=True
            )
            # Need this line in order to cause the extra [potential] queries.
            assert interfaces["eth0"].vlan.fabric is not None
        assert counter.count == 1

    def test_get_interface_dict_for_node__skips_prefetch_if_not_requested(
        self,
    ):
        node1 = factory.make_Node()
        factory.make_Interface(node=node1, name="eth0")
        counter = CountQueries()
        with counter:
            interfaces = Interface.objects.get_interface_dict_for_node(
                node1, fetch_fabric_vlan=False
            )
            assert interfaces["eth0"].vlan.fabric is not None
        assert counter.count == 3

    def test_filter_by_ip(self):
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        iface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        ip = factory.make_StaticIPAddress(
            ip="10.0.0.1", interface=iface, subnet=subnet
        )
        fetched_iface = get_one(Interface.objects.filter_by_ip(ip))
        assert iface == fetched_iface
        fetched_iface = get_one(Interface.objects.filter_by_ip("10.0.0.1"))
        assert iface == fetched_iface

    def test_resolve_missing_mac_address(self):
        iface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            node=factory.make_Node(bmc=factory.make_BMC(power_type="virsh")),
        )
        iface.mac_address = None
        with post_commit_hooks:
            iface.save()
        assert iface.node_config.node.status == NODE_STATUS.BROKEN
        iface.mac_address = factory.make_mac_address()
        PhysicalInterface.objects.resolve_missing_mac_address(iface)
        assert iface.node_config.node.status == NODE_STATUS.READY

    def test_resolve_missing_mac_address_raises_error_on_no_new_mac_address(
        self,
    ):
        iface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            node=factory.make_Node(bmc=factory.make_BMC(power_type="virsh")),
        )
        iface.mac_address = None
        with post_commit_hooks:
            iface.save()
        assert iface.node_config.node.status == NODE_STATUS.BROKEN
        with pytest.raises(ValidationError):
            PhysicalInterface.objects.resolve_missing_mac_address(iface)


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestInterfaceQueriesMixin:
    def test_filter_by_specifiers_default_matches_cidr_or_name(self):
        subnet1 = factory.make_Subnet(cidr="10.0.0.0/24")
        subnet2 = factory.make_Subnet(cidr="2001:db8::/64")
        node1 = factory.make_Node_with_Interface_on_Subnet(subnet=subnet1)
        node2 = factory.make_Node_with_Interface_on_Subnet(subnet=subnet2)
        iface1 = node1.get_boot_interface()
        iface2 = node2.get_boot_interface()
        iface3 = factory.make_Interface(
            iftype=INTERFACE_TYPE.BOND, parents=[iface2], name="bond0"
        )
        ip1 = factory.make_StaticIPAddress(
            ip="10.0.0.1", interface=iface1, subnet=subnet1
        )
        ip3 = factory.make_StaticIPAddress(
            ip="2001:db8::1", interface=iface3, subnet=subnet2
        )
        # First try with the '/prefixlen' string appended.
        assert sorted(
            Interface.objects.filter_by_specifiers("%s/24" % ip1.ip), key=str
        ) == sorted([iface1], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers("%s/64" % ip3.ip), key=str
        ) == sorted([iface3], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers(
                ["%s/24" % ip1.ip, "%s/64" % ip3.ip]
            ),
            key=str,
        ) == sorted([iface1, iface3], key=str)
        # Next, try plain old IP addresses.
        assert sorted(
            Interface.objects.filter_by_specifiers("%s" % ip1.ip), key=str
        ) == sorted([iface1], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers("%s" % ip3.ip), key=str
        ) == sorted([iface3], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers(
                ["%s" % ip1.ip, "%s" % ip3.ip]
            ),
            key=str,
        ) == sorted([iface1, iface3], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers(iface1.name), key=str
        ) == sorted([iface1], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers(iface2.name), key=str
        ) == sorted([iface2], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers(iface3.name), key=str
        ) == sorted([iface3], key=str)

    def test_filter_by_specifiers_matches_fabric_class(self):
        fabric1 = factory.make_Fabric(class_type="10g")
        fabric2 = factory.make_Fabric(class_type="1g")
        vlan1 = factory.make_VLAN(vid=1, fabric=fabric1)
        vlan2 = factory.make_VLAN(vid=2, fabric=fabric2)
        iface1 = factory.make_Interface(vlan=vlan1)
        iface2 = factory.make_Interface(vlan=vlan2)
        assert sorted(
            Interface.objects.filter_by_specifiers("fabric_class:10g"), key=str
        ) == sorted([iface1], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers("fabric_class:1g"), key=str
        ) == sorted([iface2], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers(
                ["fabric_class:1g", "fabric_class:10g"]
            ),
            key=str,
        ) == sorted([iface1, iface2], key=str)

    def test_filter_by_specifiers_matches_fabric(self):
        fabric1 = factory.make_Fabric(name="fabric1")
        fabric2 = factory.make_Fabric(name="fabric2")
        vlan1 = factory.make_VLAN(vid=1, fabric=fabric1)
        vlan2 = factory.make_VLAN(vid=2, fabric=fabric2)
        iface1 = factory.make_Interface(vlan=vlan1)
        iface2 = factory.make_Interface(vlan=vlan2)
        assert sorted(
            Interface.objects.filter_by_specifiers("fabric:fabric1"), key=str
        ) == sorted([iface1], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers("fabric:fabric2"), key=str
        ) == sorted([iface2], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers(
                ["fabric:fabric1", "fabric:fabric2"]
            ),
            key=str,
        ) == sorted([iface1, iface2], key=str)

    def test_filter_by_specifiers_matches_interface_id(self):
        iface1 = factory.make_Interface()
        iface2 = factory.make_Interface()
        assert sorted(
            Interface.objects.filter_by_specifiers("id:%s" % iface1.id),
            key=str,
        ) == sorted([iface1], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers("id:%s" % iface2.id),
            key=str,
        ) == sorted([iface2], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers(
                ["id:%s" % iface1.id, "id:%s" % iface2.id]
            ),
            key=str,
        ) == sorted([iface1, iface2], key=str)

    def test_filter_by_specifiers_matches_vid(self):
        fabric1 = factory.make_Fabric()
        parent1 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, vlan=fabric1.get_default_vlan()
        )
        vlan1 = factory.make_VLAN(fabric=fabric1)
        iface1 = factory.make_Interface(
            INTERFACE_TYPE.VLAN, vlan=vlan1, parents=[parent1]
        )
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, vlan=fabric1.get_default_vlan()
        )
        vlan2 = factory.make_VLAN(fabric=fabric1)
        iface2 = factory.make_Interface(
            INTERFACE_TYPE.VLAN, vlan=vlan2, parents=[parent2]
        )
        assert sorted(
            Interface.objects.filter_by_specifiers("vid:%s" % vlan1.vid),
            key=str,
        ) == sorted([iface1], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers("vid:%s" % vlan2.vid),
            key=str,
        ) == sorted([iface2], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers(
                ["vid:%s" % vlan1.vid, "vid:%s" % vlan2.vid]
            ),
            key=str,
        ) == sorted([iface1, iface2], key=str)

    def test_filter_by_specifiers_matches_vlan(self):
        fabric1 = factory.make_Fabric()
        parent1 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, vlan=fabric1.get_default_vlan()
        )
        vlan1 = factory.make_VLAN(fabric=fabric1)
        iface1 = factory.make_Interface(
            INTERFACE_TYPE.VLAN, vlan=vlan1, parents=[parent1]
        )
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, vlan=fabric1.get_default_vlan()
        )
        vlan2 = factory.make_VLAN(fabric=fabric1)
        iface2 = factory.make_Interface(
            INTERFACE_TYPE.VLAN, vlan=vlan2, parents=[parent2]
        )
        assert sorted(
            Interface.objects.filter_by_specifiers("vlan:%s" % vlan1.vid),
            key=str,
        ) == sorted([iface1], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers("vlan:%s" % vlan2.vid),
            key=str,
        ) == sorted([iface2], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers(
                ["vlan:%s" % vlan1.vid, "vlan:%s" % vlan2.vid]
            ),
            key=str,
        ) == sorted([iface1, iface2], key=str)

    def test_filter_by_specifiers_matches_subnet_specifier(self):
        subnet1 = factory.make_Subnet()
        subnet2 = factory.make_Subnet()
        node1 = factory.make_Node_with_Interface_on_Subnet(
            subnet=subnet1, with_dhcp_rack_primary=False
        )
        node2 = factory.make_Node_with_Interface_on_Subnet(
            subnet=subnet2, with_dhcp_rack_primary=False
        )
        iface1 = node1.get_boot_interface()
        iface2 = node2.get_boot_interface()
        assert sorted(
            Interface.objects.filter_by_specifiers(
                "subnet:cidr:%s" % subnet1.cidr
            ),
            key=str,
        ) == sorted([iface1], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers(
                "subnet:cidr:%s" % subnet2.cidr
            ),
            key=str,
        ) == sorted([iface2], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers(
                [
                    "subnet:cidr:%s" % subnet1.cidr,
                    "subnet:cidr:%s" % subnet2.cidr,
                ]
            ),
            key=str,
        ) == sorted([iface1, iface2], key=str)

    def test_filter_by_specifiers_matches_subnet_cidr_alias(self):
        subnet1 = factory.make_Subnet()
        subnet2 = factory.make_Subnet()
        node1 = factory.make_Node_with_Interface_on_Subnet(
            subnet=subnet1, with_dhcp_rack_primary=False
        )
        node2 = factory.make_Node_with_Interface_on_Subnet(
            subnet=subnet2, with_dhcp_rack_primary=False
        )
        iface1 = node1.get_boot_interface()
        iface2 = node2.get_boot_interface()
        assert sorted(
            Interface.objects.filter_by_specifiers(
                "subnet_cidr:%s" % subnet1.cidr
            ),
            key=str,
        ) == sorted([iface1], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers(
                "subnet_cidr:%s" % subnet2.cidr
            ),
            key=str,
        ) == sorted([iface2], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers(
                [
                    "subnet_cidr:%s" % subnet1.cidr,
                    "subnet_cidr:%s" % subnet2.cidr,
                ]
            ),
            key=str,
        ) == sorted([iface1, iface2], key=str)

    def test_filter_by_specifiers_matches_space_by_subnet(self):
        space1 = factory.make_Space()
        space2 = factory.make_Space()
        vlan1 = factory.make_VLAN(space=space1)
        vlan2 = factory.make_VLAN(space=space2)
        subnet1 = factory.make_Subnet(vlan=vlan1, space=None)
        subnet2 = factory.make_Subnet(vlan=vlan2, space=None)
        node1 = factory.make_Node_with_Interface_on_Subnet(
            subnet=subnet1, with_dhcp_rack_primary=False
        )
        node2 = factory.make_Node_with_Interface_on_Subnet(
            subnet=subnet2, with_dhcp_rack_primary=False
        )
        iface1 = node1.get_boot_interface()
        iface2 = node2.get_boot_interface()
        assert sorted(
            Interface.objects.filter_by_specifiers("space:%s" % space1.name),
            key=str,
        ) == sorted([iface1], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers("space:%s" % space2.name),
            key=str,
        ) == sorted([iface2], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers(
                ["space:%s" % space1.name, "space:%s" % space2.name]
            ),
            key=str,
        ) == sorted([iface1, iface2], key=str)

    def test_filter_by_specifiers_matches_space_by_vlan(self):
        space1 = factory.make_Space()
        space2 = factory.make_Space()
        vlan1 = factory.make_VLAN(space=space1)
        vlan2 = factory.make_VLAN(space=space2)
        subnet1 = factory.make_Subnet(vlan=vlan1, space=None)
        subnet2 = factory.make_Subnet(vlan=vlan2, space=None)
        node1 = factory.make_Node_with_Interface_on_Subnet(
            subnet=subnet1, with_dhcp_rack_primary=False
        )
        node2 = factory.make_Node_with_Interface_on_Subnet(
            subnet=subnet2, with_dhcp_rack_primary=False
        )
        iface1 = node1.get_boot_interface()
        iface2 = node2.get_boot_interface()
        assert sorted(
            Interface.objects.filter_by_specifiers("space:%s" % space1.name),
            key=str,
        ) == sorted([iface1], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers("space:%s" % space2.name),
            key=str,
        ) == sorted([iface2], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers(
                ["space:%s" % space1.name, "space:%s" % space2.name]
            ),
            key=str,
        ) == sorted([iface1, iface2], key=str)

    def test_filter_by_specifiers_matches_undefined_space(self):
        space1 = factory.make_Space()
        vlan1 = factory.make_VLAN(space=space1)
        vlan2 = factory.make_VLAN(space=None)
        subnet1 = factory.make_Subnet(vlan=vlan1, space=None)
        subnet2 = factory.make_Subnet(vlan=vlan2, space=None)
        node1 = factory.make_Node_with_Interface_on_Subnet(
            subnet=subnet1, with_dhcp_rack_primary=False
        )
        node2 = factory.make_Node_with_Interface_on_Subnet(
            subnet=subnet2, with_dhcp_rack_primary=False
        )
        iface1 = node1.get_boot_interface()
        iface2 = node2.get_boot_interface()
        assert sorted(
            Interface.objects.filter_by_specifiers("space:%s" % space1.name),
            key=str,
        ) == sorted([iface1], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers(
                "space:%s" % Space.UNDEFINED
            ),
            key=str,
        ) == sorted([iface2], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers(
                ["space:%s" % space1.name, "space:%s" % Space.UNDEFINED]
            ),
            key=str,
        ) == sorted([iface1, iface2], key=str)

    def test_filter_by_specifiers_matches_type(self):
        physical = factory.make_Interface()
        bond = factory.make_Interface(
            iftype=INTERFACE_TYPE.BOND, parents=[physical]
        )
        vlan = factory.make_Interface(
            iftype=INTERFACE_TYPE.VLAN, parents=[physical]
        )
        unknown = factory.make_Interface(iftype=INTERFACE_TYPE.UNKNOWN)
        assert sorted(
            Interface.objects.filter_by_specifiers("type:physical"), key=str
        ) == sorted([physical], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers("type:vlan"), key=str
        ) == sorted([vlan], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers("type:bond"), key=str
        ) == sorted([bond], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers("type:unknown"), key=str
        ) == sorted([unknown], key=str)

    def test_filter_by_specifiers_matches_ip(self):
        subnet1 = factory.make_Subnet(cidr="10.0.0.0/24")
        subnet2 = factory.make_Subnet(cidr="10.0.1.0/24")
        iface1 = factory.make_Interface()
        iface2 = factory.make_Interface()
        factory.make_StaticIPAddress(
            ip="10.0.0.1",
            alloc_type=IPADDRESS_TYPE.AUTO,
            subnet=subnet1,
            interface=iface1,
        )
        factory.make_StaticIPAddress(
            ip="10.0.1.1",
            alloc_type=IPADDRESS_TYPE.AUTO,
            subnet=subnet2,
            interface=iface2,
        )
        assert sorted(
            Interface.objects.filter_by_specifiers("ip:10.0.0.1"), key=str
        ) == sorted([iface1], key=str)
        assert sorted(
            Interface.objects.filter_by_specifiers("ip:10.0.1.1"), key=str
        ) == sorted([iface2], key=str)

    def test_filter_by_specifiers_matches_unconfigured_mode(self):
        subnet1 = factory.make_Subnet(cidr="10.0.0.0/24")
        subnet2 = factory.make_Subnet(cidr="10.0.1.0/24")
        subnet3 = factory.make_Subnet(cidr="10.0.2.0/24")
        iface1 = factory.make_Interface()
        iface2 = factory.make_Interface()
        iface3 = factory.make_Interface()
        factory.make_StaticIPAddress(
            ip="",
            alloc_type=IPADDRESS_TYPE.STICKY,
            subnet=subnet1,
            interface=iface1,
        )
        factory.make_StaticIPAddress(
            ip=None,
            alloc_type=IPADDRESS_TYPE.AUTO,
            subnet=subnet2,
            interface=iface2,
        )
        factory.make_StaticIPAddress(
            ip="10.0.2.1",
            alloc_type=IPADDRESS_TYPE.AUTO,
            subnet=subnet3,
            interface=iface3,
        )
        assert sorted([iface1, iface2], key=str) == sorted(
            Interface.objects.filter_by_specifiers("mode:unconfigured"),
            key=str,
        )

    def test_get_matching_node_map(self):
        space1 = factory.make_Space()
        space2 = factory.make_Space()
        vlan1 = factory.make_VLAN(space=space1)
        vlan2 = factory.make_VLAN(space=space2)
        subnet1 = factory.make_Subnet(vlan=vlan1, space=None)
        subnet2 = factory.make_Subnet(vlan=vlan2, space=None)
        node1 = factory.make_Node_with_Interface_on_Subnet(
            subnet=subnet1, with_dhcp_rack_primary=False
        )
        node2 = factory.make_Node_with_Interface_on_Subnet(
            subnet=subnet2, with_dhcp_rack_primary=False
        )
        iface1 = node1.get_boot_interface()
        iface2 = node2.get_boot_interface()
        nodes1, map1 = Interface.objects.get_matching_node_map(
            "space:%s" % space1.name
        )
        assert sorted(nodes1, key=str) == sorted([node1.id], key=str)
        assert map1 == {node1.id: [iface1.id]}
        nodes2, map2 = Interface.objects.get_matching_node_map(
            "space:%s" % space2.name
        )
        assert nodes2 == {node2.id}
        assert map2 == {node2.id: [iface2.id]}
        nodes3, map3 = Interface.objects.get_matching_node_map(
            ["space:%s" % space1.name, "space:%s" % space2.name]
        )
        assert nodes3 == {node1.id, node2.id}
        assert map3 == {node1.id: [iface1.id], node2.id: [iface2.id]}

    def test_get_matching_node_map_with_multiple_interfaces(self):
        space1 = factory.make_Space()
        space2 = factory.make_Space()
        vlan1 = factory.make_VLAN(space=space1)
        vlan2 = factory.make_VLAN(space=space2)
        subnet1 = factory.make_Subnet(vlan=vlan1, space=space1)
        subnet2 = factory.make_Subnet(vlan=vlan2, space=space2)
        node1 = factory.make_Node_with_Interface_on_Subnet(
            subnet=subnet1, with_dhcp_rack_primary=False
        )
        node2 = factory.make_Node_with_Interface_on_Subnet(
            subnet=subnet2, with_dhcp_rack_primary=False
        )
        iface1 = node1.get_boot_interface()
        iface2 = node2.get_boot_interface()
        iface3 = factory.make_Interface(node=node1, subnet=subnet1)
        factory.make_StaticIPAddress(interface=iface3, subnet=subnet1)
        nodes1, map1 = Interface.objects.get_matching_node_map(
            "space:%s" % space1.name
        )
        assert nodes1 == {node1.id}
        map1[node1.id].sort()
        assert map1 == {node1.id: sorted([iface1.id, iface3.id])}
        nodes2, map2 = Interface.objects.get_matching_node_map(
            "space:%s" % space2.name
        )
        assert nodes2 == {node2.id}
        assert map2 == {node2.id: [iface2.id]}
        nodes3, map3 = Interface.objects.get_matching_node_map(
            ["space:%s" % space1.name, "space:%s" % space2.name]
        )
        assert nodes3 == {node1.id, node2.id}
        map3[node1.id].sort()
        assert map3 == {
            node1.id: sorted([iface1.id, iface3.id]),
            node2.id: [iface2.id],
        }

    def test_get_matching_node_map_by_multiple_tags(self):
        tags = [factory.make_name("tag")]
        tags_specifier = "tag:%s" % "&&".join(tags)
        node = factory.make_Node()
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=node, tags=tags
        )
        # Other interface with subset of tags.
        factory.make_Interface(INTERFACE_TYPE.PHYSICAL, tags=tags[1:])
        nodes, map_ = Interface.objects.get_matching_node_map(tags_specifier)
        assert nodes == {node.id}
        assert map_ == {node.id: [interface.id]}

    def test_get_matching_node_map_by_tag(self):
        tags = [factory.make_name("tag")]
        node = factory.make_Node()
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=node, tags=tags
        )
        nodes, map_ = Interface.objects.get_matching_node_map(
            "tag:%s" % random.choice(tags)
        )
        assert nodes == {node.id}
        assert map_ == {node.id: [interface.id]}


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestAllInterfacesParentsFirst:
    def test_all_interfaces_parents_first(self):
        node1 = factory.make_Node()
        eth0 = factory.make_Interface(node=node1, name="eth0")
        eth0_vlan = factory.make_Interface(
            iftype=INTERFACE_TYPE.VLAN, parents=[eth0], node=node1
        )
        eth1 = factory.make_Interface(node=node1, name="eth1", enabled=False)
        eth2 = factory.make_Interface(node=node1, name="eth2")
        eth3 = factory.make_Interface(node=node1, name="eth3")
        eth4 = factory.make_Interface(node=node1, name="eth4")
        eth5 = factory.make_Interface(node=node1, name="eth5")
        bond0 = factory.make_Interface(
            iftype=INTERFACE_TYPE.BOND,
            parents=[eth2, eth3],
            name="bond0",
            node=node1,
        )
        br0 = factory.make_Interface(
            iftype=INTERFACE_TYPE.BRIDGE,
            parents=[eth4, eth5],
            name="br0",
            node=node1,
        )
        br1 = factory.make_Interface(
            iftype=INTERFACE_TYPE.BRIDGE, parents=[], name="br1", node=node1
        )
        br2 = factory.make_Interface(
            iftype=INTERFACE_TYPE.BRIDGE,
            parents=[bond0],
            name="br2",
            node=node1,
        )
        # Make sure we only got one Node's interfaces by creating a few
        # dummy interfaces.
        node2 = factory.make_Node()
        n2_eth0 = factory.make_Interface(node=node2, name="eth0")
        n2_eth1 = factory.make_Interface(node=node2, name="eth1")
        ifaces = Interface.objects.all_interfaces_parents_first(node1)
        assert isinstance(ifaces, Iterable)
        iface_list = list(ifaces)
        # Expect alphabetical interface order, interleaved with a parents-first
        # search for each child interface. That is, child interfaces will
        # always be listed after /all/ of their parents.
        assert iface_list == (
            [
                br1,
                eth0,
                eth0_vlan,
                eth1,
                eth2,
                eth3,
                bond0,
                br2,
                eth4,
                eth5,
                br0,
            ]
        )
        # Might as well test that the other host looks okay, too.
        n2_ifaces = list(Interface.objects.all_interfaces_parents_first(node2))
        assert n2_ifaces == [n2_eth0, n2_eth1]

    def test_all_interfaces_parents_ignores_orphan_interfaces(self):
        # Previous versions of MAAS had a bug which resulted in an "orphan"
        # interface (an interface missing a pointer to its node). Because
        # we don't want this method to cause excessive querying, we expect
        # those to NOT show up.
        node = factory.make_Node()
        eth0 = factory.make_Interface(node=node, name="eth0")
        eth0_vlan = factory.make_Interface(
            iftype=INTERFACE_TYPE.VLAN, parents=[eth0], node=node
        )
        # Use the QuerySet update() to avoid calling the post-save handler,
        # which would otherwise automatically work around this.
        Interface.objects.filter(id=eth0_vlan.id).update(node_config=None)
        iface_list = list(Interface.objects.all_interfaces_parents_first(node))
        assert iface_list == [eth0]


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestInterface:
    def test_rejects_invalid_name(self):
        with pytest.raises(ValidationError):
            factory.make_Interface(
                INTERFACE_TYPE.PHYSICAL, name="invalid*name"
            )

    def test_rejects_name_too_long(self):
        with pytest.raises(ValidationError):
            factory.make_Interface(
                INTERFACE_TYPE.PHYSICAL,
                name=factory.make_hex_string(size=16),
            )

    def test_rejects_invalid_mac_address(self):
        with pytest.raises(ValidationError) as exception:
            factory.make_Interface(
                INTERFACE_TYPE.PHYSICAL, mac_address="invalid"
            )
        assert exception.value.message_dict == {
            "mac_address": ["'invalid' is not a valid MAC address."]
        }

    def test_allows_blank_mac_address(self):
        factory.make_Interface(INTERFACE_TYPE.UNKNOWN, mac_address="")

    def test_allows_none_mac_address(self):
        factory.make_Interface(INTERFACE_TYPE.UNKNOWN, mac_address=None)

    def test_get_type_returns_None(self):
        assert Interface.get_type() is None

    def test_creates_interface(self):
        name = factory.make_name("name")
        node_config = factory.make_NodeConfig()
        mac = factory.make_mac_address()
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            name=name,
            node_config=node_config,
            mac_address=mac,
        )
        assert interface.name == name
        assert interface.node_config == node_config
        assert interface.mac_address == mac
        assert interface.type == INTERFACE_TYPE.PHYSICAL

    def test_allows_null_vlan(self):
        name = factory.make_name("name")
        node_config = factory.make_NodeConfig()
        mac = factory.make_mac_address()
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            name=name,
            node_config=node_config,
            mac_address=mac,
            link_connected=False,
        )
        assert interface.name == name
        assert interface.node_config == node_config
        assert interface.mac_address == mac
        assert interface.type == INTERFACE_TYPE.PHYSICAL
        assert interface.vlan is None

    def test_string_representation_contains_essential_data(self):
        name = factory.make_name("name")
        node = factory.make_Node()
        mac = factory.make_mac_address()
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, name=name, node=node, mac_address=mac
        )
        assert mac in str(interface)
        assert name in str(interface)

    def test_deletes_related_children(self):
        node = factory.make_Node()
        nic1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        nic2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        bond = factory.make_Interface(
            INTERFACE_TYPE.BOND, parents=[nic1, nic2]
        )
        vlan = factory.make_Interface(INTERFACE_TYPE.VLAN, parents=[bond])
        nic1.delete()
        # Should not be deleted yet.
        assert reload_object(bond) is not None, "Bond was deleted."
        assert reload_object(vlan) is not None, "VLAN was deleted."
        nic2.delete()
        # Should now all be deleted.
        assert reload_object(bond) is None, "Bond was not deleted."
        assert reload_object(vlan) is None, "VLAN was not deleted."

    def test_is_configured_returns_False_when_disabled(self):
        nic1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, enabled=False)
        assert not nic1.is_configured()

    def test_is_configured_returns_False_when_no_links(self):
        nic1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, enabled=False)
        nic1.ip_addresses.clear()
        assert not nic1.is_configured()

    def test_is_configured_returns_False_when_only_link_up(self):
        nic1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        nic1.ensure_link_up()
        assert not nic1.is_configured()

    def test_is_configured_returns_True_when_other_link(self):
        nic1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        nic1.ensure_link_up()
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO, interface=nic1
        )
        assert nic1.is_configured()

    def test_get_links_returns_links_for_each_type(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        expected_links = []
        dhcp_subnet = factory.make_Subnet()
        dhcp_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.DHCP,
            ip="",
            subnet=dhcp_subnet,
            interface=interface,
        )
        expected_links.append(
            {
                "id": dhcp_ip.id,
                "mode": INTERFACE_LINK_TYPE.DHCP,
                "subnet": dhcp_subnet,
            }
        )
        static_subnet = factory.make_Subnet()
        static_ip = factory.pick_ip_in_network(static_subnet.get_ipnetwork())
        sip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip=static_ip,
            subnet=static_subnet,
            interface=interface,
        )
        expected_links.append(
            {
                "id": sip.id,
                "mode": INTERFACE_LINK_TYPE.STATIC,
                "ip_address": static_ip,
                "subnet": static_subnet,
            }
        )

        temp_ip = factory.pick_ip_in_network(
            static_subnet.get_ipnetwork(), but_not=[static_ip]
        )
        temp_sip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO,
            ip=temp_ip,
            subnet=static_subnet,
            interface=interface,
            temp_expires_on=timezone.now(),
        )
        expected_links.append(
            {
                "id": temp_sip.id,
                "mode": INTERFACE_LINK_TYPE.AUTO,
                "subnet": static_subnet,
            }
        )
        link_subnet = factory.make_Subnet()
        link_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip="",
            subnet=link_subnet,
            interface=interface,
        )
        expected_links.append(
            {
                "id": link_ip.id,
                "mode": INTERFACE_LINK_TYPE.LINK_UP,
                "subnet": link_subnet,
            }
        )
        assert sorted(interface.get_links(), key=str) == sorted(
            expected_links, key=str
        )

    def test_get_discovered_returns_None_when_empty(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        assert interface.get_discovered() is None

    def test_get_discovered_returns_discovered_address_for_ipv4_and_ipv6(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        network_v4 = factory.make_ipv4_network()
        subnet_v4 = factory.make_Subnet(cidr=str(network_v4.cidr))
        ip_v4 = factory.pick_ip_in_network(network_v4)
        network_v6 = factory.make_ipv6_network()
        subnet_v6 = factory.make_Subnet(cidr=str(network_v6.cidr))
        ip_v6 = factory.pick_ip_in_network(network_v6)
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.DISCOVERED,
            ip=ip_v6,
            subnet=subnet_v6,
            interface=interface,
        )
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.DISCOVERED,
            ip=ip_v4,
            subnet=subnet_v4,
            interface=interface,
        )
        d_v4, d_v6 = interface.get_discovered()
        assert d_v4["ip_address"] == ip_v4
        assert d_v4["subnet"] == subnet_v4
        assert d_v6["ip_address"] == ip_v6
        assert d_v6["subnet"] == subnet_v6

    def test_delete_deletes_related_ip_addresses(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        discovered_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.DISCOVERED, interface=interface
        )
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY, interface=interface
        )
        interface.delete()
        assert reload_object(discovered_ip) is None
        assert reload_object(static_ip) is None

    def test_remove_gateway_link_on_node_ipv4(self):
        node = factory.make_Node()
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        network = factory.make_ipv4_network()
        subnet = factory.make_Subnet(cidr=str(network.cidr))
        ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip=factory.pick_ip_in_network(network),
            subnet=subnet,
            interface=interface,
        )
        node.gateway_link_ipv4 = ip
        node.save()
        reload_object(interface).ip_addresses.remove(ip)
        node = reload_object(node)
        assert node.gateway_link_ipv4 is None

    def test_remove_gateway_link_on_node_ipv6(self):
        node = factory.make_Node()
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        network = factory.make_ipv6_network()
        subnet = factory.make_Subnet(cidr=str(network.cidr))
        ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip=factory.pick_ip_in_network(network),
            subnet=subnet,
            interface=interface,
        )
        node.gateway_link_ipv6 = ip
        node.save()
        reload_object(interface).ip_addresses.remove(ip)
        node = reload_object(node)
        assert node.gateway_link_ipv6 is None

    def test_get_ancestors_includes_grandparents(self):
        node = factory.make_Node()
        eth0 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        eth0_100 = factory.make_Interface(
            INTERFACE_TYPE.VLAN, node=node, parents=[eth0]
        )
        br0 = factory.make_Interface(
            INTERFACE_TYPE.BRIDGE, node=node, parents=[eth0_100]
        )
        assert {eth0, eth0_100} == br0.get_ancestors()

    def test_get_successors_includes_grandchildren(self):
        node = factory.make_Node()
        eth0 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        eth0_100 = factory.make_Interface(
            INTERFACE_TYPE.VLAN, node=node, parents=[eth0]
        )
        br0 = factory.make_Interface(
            INTERFACE_TYPE.BRIDGE, node=node, parents=[eth0_100]
        )
        assert {eth0_100, br0} == eth0.get_successors()

    def test_get_all_related_interafces_includes_all_related(self):
        node = factory.make_Node()
        eth0 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        eth0_100 = factory.make_Interface(
            INTERFACE_TYPE.VLAN, node=node, parents=[eth0]
        )
        eth0_101 = factory.make_Interface(
            INTERFACE_TYPE.VLAN, node=node, parents=[eth0]
        )
        br0 = factory.make_Interface(
            INTERFACE_TYPE.BRIDGE, node=node, parents=[eth0_100]
        )
        assert {
            eth0,
            eth0_100,
            eth0_101,
            br0,
        } == eth0_100.get_all_related_interfaces()

    def test_add_tag_adds_new_tag(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, tags=[])
        tag = factory.make_name("tag")
        interface.add_tag(tag)
        assert [tag] == interface.tags

    def test_add_tag_doesnt_duplicate(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, tags=[])
        tag = factory.make_name("tag")
        interface.add_tag(tag)
        interface.add_tag(tag)
        assert [tag] == interface.tags

    def test_remove_tag_deletes_tag(self):
        tag = factory.make_name("tag")
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, tags=[tag])
        interface.remove_tag(tag)
        assert [] == interface.tags

    def test_remove_tag_doesnt_error_on_missing_tag(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, tags=[])
        tag = factory.make_name("tag")
        # Test is this doesn't raise an exception
        interface.remove_tag(tag)

    def test_save_link_speed_may_exceed_interface_speed(self):
        # LP:1877158 - Interfaces which use aggregate physical links do
        # not report the full max interface speed.
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface.interface_speed = 100
        interface.link_speed = 1000
        interface.save()
        assert 100 == interface.interface_speed
        assert 1000 == interface.link_speed

    def test_save_link_speed_may_exceed_unknown_interface_speed(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface.interface_speed = 0
        interface.link_speed = 1000
        interface.save()
        interface = reload_object(interface)
        assert 0 == interface.interface_speed
        assert 1000 == interface.link_speed

    def test_save_if_link_disconnected_set_link_speed_to_zero(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface.link_connected = False
        interface.save()
        assert 0 == interface.link_speed

    def test_save_does_not_call_cofigure_dhcp_on_create(self, mocker):
        mock_start_workflow = mocker.patch.object(
            interface_module, "start_workflow"
        )
        interface = Interface(
            type=INTERFACE_TYPE.PHYSICAL,
            name=f"{factory.make_name()}0",
            mac_address=factory.make_mac_address(),
            node_config=factory.make_NodeConfig(),
        )
        interface.save()
        mock_start_workflow.assert_not_called()

    def test_save_calls_configure_dhcp_if_name_changed(self, mocker):
        mock_start_workflow = mocker.patch.object(
            interface_module, "start_workflow"
        )
        vlan = factory.make_VLAN()
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, vlan=vlan)
        interface.name = factory.make_name()

        with post_commit_hooks:
            interface.save()

        mock_start_workflow.assert_called_once_with(
            workflow_name=CONFIGURE_DHCP_WORKFLOW_NAME,
            param=ConfigureDHCPParam(vlan_ids=[vlan.id]),
            task_queue="region",
        )

    def test_save_calls_configure_dhcp_if_mac_address_changed(self, mocker):
        mock_start_workflow = mocker.patch.object(
            interface_module, "start_workflow"
        )
        vlan = factory.make_VLAN()
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, vlan=vlan)
        interface.mac_address = factory.make_mac_address()

        with post_commit_hooks:
            interface.save()

        mock_start_workflow.assert_called_once_with(
            workflow_name=CONFIGURE_DHCP_WORKFLOW_NAME,
            param=ConfigureDHCPParam(vlan_ids=[vlan.id]),
            task_queue="region",
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
@pytest.mark.parametrize(
    "iftype",
    [INTERFACE_TYPE.BOND, INTERFACE_TYPE.BRIDGE],
    ids=["bond", "bridge"],
)
class TestUpdateInterfaceParentsOnSave:
    def test_updates_parents_vlan(self, iftype):
        node_config = factory.make_NodeConfig()
        parent1 = factory.make_Interface(
            iftype=INTERFACE_TYPE.PHYSICAL, node_config=node_config
        )
        parent2 = factory.make_Interface(
            iftype=INTERFACE_TYPE.PHYSICAL, node_config=node_config
        )
        child = factory.make_Interface(iftype, parents=[parent1, parent2])
        assert child.vlan == reload_object(parent1).vlan
        assert child.vlan == reload_object(parent2).vlan

    def test_update_interface_clears_parent_links(self, iftype):
        node_config = factory.make_NodeConfig()
        parent1 = factory.make_Interface(
            iftype=INTERFACE_TYPE.PHYSICAL, node_config=node_config
        )
        parent2 = factory.make_Interface(
            iftype=INTERFACE_TYPE.PHYSICAL, node_config=node_config
        )
        static_ip = factory.make_StaticIPAddress(interface=parent1)
        factory.make_Interface(iftype, parents=[parent1, parent2])
        assert reload_object(static_ip) is None

    def test_log_message(self, iftype):
        node_config = factory.make_NodeConfig()
        parent1 = factory.make_Interface(
            iftype=INTERFACE_TYPE.PHYSICAL,
            node_config=node_config,
            name="parent1",
        )
        parent2 = factory.make_Interface(
            iftype=INTERFACE_TYPE.PHYSICAL,
            node_config=node_config,
            name="parent2",
        )
        with FakeLogger("maas.interface") as maaslog:
            child = factory.make_Interface(
                iftype, parents=[parent1, parent2], name="child"
            )
        hostname = node_config.node.hostname
        assert (
            f"parent2 (physical) on {hostname}: VLAN updated to match child ({iftype}) on {hostname} (vlan={child.vlan_id}).\n"
            == maaslog.output
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestInterfaceUpdateNeighbour:
    """Tests for `Interface.update_neighbour`."""

    def make_neighbour_json(self, ip=None, mac=None, time=None, **kwargs):
        """Returns a dictionary in the same JSON format that the region
        expects to receive from the rack.
        """
        if ip is None:
            ip = factory.make_ip_address(ipv6=False)
        if mac is None:
            mac = factory.make_mac_address()
        if time is None:
            time = random.randint(0, 200000000)
        if "vid" not in kwargs:
            has_vid = random.choice([True, False])
            if has_vid:
                vid = random.randint(1, 4094)
            else:
                vid = None
        return {"ip": ip, "mac": mac, "time": time, "vid": vid}

    def test_adds_new_neighbour(self):
        iface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        iface.update_neighbour(**self.make_neighbour_json())
        assert 1 == Neighbour.objects.count()

    def test_updates_existing_neighbour(self):
        iface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        json = self.make_neighbour_json()
        iface.update_neighbour(**json)
        neighbour = get_one(Neighbour.objects.all())
        # Pretend this was updated one day ago.
        yesterday = timezone.now() - datetime.timedelta(days=1)
        neighbour.save(_updated=yesterday, update_fields=["updated"])
        neighbour = reload_object(neighbour)
        assert int(yesterday.timestamp()) == int(neighbour.updated.timestamp())
        json["time"] += 1
        iface.update_neighbour(**json)
        neighbour = reload_object(neighbour)
        assert 1 == Neighbour.objects.count()
        assert json["time"] == neighbour.time
        # This is the second time we saw this neighbour.
        neighbour = reload_object(neighbour)
        assert 2 == neighbour.count
        # Make sure the "last seen" time is correct.
        assert yesterday != neighbour.updated

    def test_replaces_obsolete_neighbour(self):
        iface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        json = self.make_neighbour_json()
        iface.update_neighbour(**json)
        # Have a different MAC address claim ownership of the IP.
        json["time"] += 1
        json["mac"] = factory.make_mac_address()
        iface.update_neighbour(**json)
        assert 1 == Neighbour.objects.count()
        assert json["mac"] == list(Neighbour.objects.all())[0].mac_address
        # This is the first time we saw this neighbour, because the original
        # binding was deleted.
        assert 1 == list(Neighbour.objects.all())[0].count

    def test_logs_new_binding(self):
        iface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        with FakeLogger("maas.interface") as maaslog:
            iface.update_neighbour(**self.make_neighbour_json())
        assert ": New MAC, IP binding observed" in maaslog.output

    def test_logs_moved_binding(self):
        iface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        iface.neighbour_discovery_state = True
        json = self.make_neighbour_json()
        iface.update_neighbour(**json)
        # Have a different MAC address claim ownership of the IP.
        json["time"] += 1
        json["mac"] = factory.make_mac_address()
        with FakeLogger("maas.neighbour") as maaslog:
            iface.update_neighbour(**json)
        assert re.search(": IP address .* moved from .* to", maaslog.output)


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestInterfaceUpdateMDNSEntry:
    """Tests for `Interface.update_mdns_entry`."""

    def make_mdns_entry_json(self, ip=None, hostname=None):
        """Returns a dictionary in the same JSON format that the region
        expects to receive from the rack.
        """
        if ip is None:
            ip = factory.make_ip_address(ipv6=False)
        if hostname is None:
            hostname = factory.make_hostname()
        return {"address": ip, "hostname": hostname}

    def test_ignores_updates_if_mdns_discovery_state_is_false(self):
        iface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        iface.update_mdns_entry(self.make_mdns_entry_json())
        assert 0 == MDNS.objects.count()

    def test_adds_new_entry_if_mdns_discovery_state_is_true(self):
        iface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        iface.mdns_discovery_state = True
        iface.update_mdns_entry(self.make_mdns_entry_json())
        assert 1 == MDNS.objects.count()

    def test_updates_existing_entry(self):
        iface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        iface.mdns_discovery_state = True
        json = self.make_mdns_entry_json()
        iface.update_mdns_entry(json)
        yesterday = timezone.now() - datetime.timedelta(days=1)
        mdns_entry = get_one(MDNS.objects.all())
        mdns_entry.save(_updated=yesterday, update_fields=["updated"])
        mdns_entry = reload_object(mdns_entry)
        assert int(yesterday.timestamp()) == int(
            mdns_entry.updated.timestamp()
        )
        # First time we saw the entry.
        assert 1 == mdns_entry.count
        assert 1 == MDNS.objects.count()
        iface.update_mdns_entry(json)
        mdns_entry = reload_object(mdns_entry)
        assert json["address"] == mdns_entry.ip
        assert json["hostname"] == mdns_entry.hostname
        # This is the second time we saw this entry.
        assert 2 == mdns_entry.count
        assert yesterday != mdns_entry.updated

    def test_replaces_obsolete_entry(self):
        iface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        iface.mdns_discovery_state = True
        json = self.make_mdns_entry_json()
        iface.update_mdns_entry(json)
        # Have a different IP address claim ownership of the hostname.
        json["address"] = factory.make_ip_address(ipv6=False)
        iface.update_mdns_entry(json)
        assert 1 == MDNS.objects.count()
        assert json["address"] == MDNS.objects.first().ip
        # This is the first time we saw this neighbour, because the original
        # binding was deleted.
        assert 1 == MDNS.objects.count()

    def test_logs_new_entry(self):
        iface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        iface.mdns_discovery_state = True
        json = self.make_mdns_entry_json()
        with FakeLogger("maas.interface") as maaslog:
            iface.update_mdns_entry(json)
        assert ": New mDNS entry resolved" in maaslog.output

    def test_logs_moved_entry(self):
        iface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        iface.mdns_discovery_state = True
        json = self.make_mdns_entry_json()
        iface.update_mdns_entry(json)
        # Have a different IP address claim ownership of the hostma,e.
        json["address"] = factory.make_ip_address(ipv6=False)
        with FakeLogger("maas.mDNS") as maaslog:
            iface.update_mdns_entry(json)
        assert re.search(": Hostname .* moved from .* to", maaslog.output)

    def test_logs_updated_entry(self):
        iface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        iface.mdns_discovery_state = True
        json = self.make_mdns_entry_json()
        iface.update_mdns_entry(json)
        # Assign a different hostname to the IP.
        json["hostname"] = factory.make_hostname()
        with FakeLogger("maas.mDNS") as maaslog:
            iface.update_mdns_entry(json)
        assert re.search(
            ": Hostname for .* updated from .* to", maaslog.output
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestPhysicalInterface:
    def test_manager_returns_physical_interfaces(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        vlan = factory.make_VLAN()
        factory.make_Interface(
            INTERFACE_TYPE.VLAN, vlan=vlan, parents=[parent]
        )
        assert sorted([parent], key=str) == sorted(
            PhysicalInterface.objects.all(), key=str
        )

    def test_serialize(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        assert (
            {
                "id": interface.id,
                "name": interface.name,
                "mac_address": str(interface.mac_address),
                "vendor": interface.vendor,
                "product": interface.product,
            }
        ) == interface.serialize()

    def test_get_node_returns_its_node(self):
        node = factory.make_Node()
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        assert node == interface.get_node()

    def test_default_node_numanode(self):
        node = factory.make_Node()
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        assert interface.numa_node == node.default_numanode

    def test_no_default_node_numanode_device(self):
        node = factory.make_Device()
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        assert interface.numa_node is None

    def test_requires_node(self):
        interface = PhysicalInterface(
            name=factory.make_name("eth"),
            mac_address=factory.make_mac_address(),
        )
        with pytest.raises(ValidationError) as error:
            interface.save()
        assert {
            "node_config": ["This field cannot be blank."]
        } == error.value.message_dict

    def test_requires_mac_address(self):
        interface = PhysicalInterface(
            name=factory.make_name("eth"),
            node_config=factory.make_Node(
                bmc=factory.make_BMC()
            ).current_config,
        )
        with pytest.raises(ValidationError) as error:
            interface.save()
        assert {
            "mac_address": ["This field cannot be blank."]
        } == error.value.message_dict

    def test_mac_address_must_be_unique_for_nodeconfig(self):
        node_config = factory.make_NodeConfig()
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node_config=node_config
        )
        bad_interface = PhysicalInterface(
            node_config=node_config,
            mac_address=interface.mac_address,
            name=factory.make_name("eth"),
        )
        with pytest.raises(ValidationError) as error:
            bad_interface.save()
        assert (
            {
                "mac_address": [
                    "This MAC address is already in use by %s."
                    % (interface.get_log_string())
                ]
            }
        ) == error.value.message_dict

    def test_mac_address_is_normalised_on_save(self):
        node_config = factory.make_NodeConfig()
        interface = PhysicalInterface(
            node_config=node_config,
            mac_address="AA:BB:CC:DD:EE:FF",
            name=factory.make_name("eth"),
        )
        interface.save()
        assert interface.mac_address == "aa:bb:cc:dd:ee:ff"

    def test_mac_address_uniqueness_ignores_case(self):
        node_config = factory.make_NodeConfig()
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            node_config=node_config,
            mac_address="aa:bb:cc:dd:ee:ff",
        )
        bad_interface = PhysicalInterface(
            node_config=node_config,
            mac_address="AA:BB:CC:DD:EE:FF",
            name=factory.make_name("eth"),
        )
        with pytest.raises(ValidationError) as error:
            bad_interface.save()
        assert (
            {
                "mac_address": [
                    "This MAC address is already in use by %s."
                    % (interface.get_log_string())
                ]
            }
        ) == error.value.message_dict

    def test_mac_address_can_be_duplicated_for_other_nodeconfig(self):
        node = factory.make_Node()
        if1 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node_config=node.current_config
        )
        node_config2 = factory.make_NodeConfig(node=node, name="deployment")
        if2 = PhysicalInterface.objects.create(
            node_config=node_config2,
            mac_address=if1.mac_address,
            name=factory.make_name("eth"),
        )
        # no error is raised on interface save
        assert if1.mac_address == if2.mac_address

    def test_create_raises_error_on_not_unique(self):
        node = factory.make_Node()
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        with pytest.raises(ValidationError):
            factory.make_Interface(
                INTERFACE_TYPE.PHYSICAL,
                name=interface.name,
                node=node,
            )

    def test_update_raises_error_on_not_unique(self):
        node = factory.make_Node()
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        interface_to_update = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=node
        )
        interface_to_update.name = interface.name
        with pytest.raises(ValidationError):
            interface_to_update.save()

    def test_update_does_not_raise_error_on_unique(self):
        node = factory.make_Node()
        name = factory.make_name("eth")
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        interface.name = name

        with post_commit_hooks:
            interface.save()
        interface = reload_object(interface)
        assert interface.name == name

    def test_cannot_have_parents(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        with pytest.raises(ValidationError) as error:
            factory.make_Interface(
                INTERFACE_TYPE.PHYSICAL,
                node_config=parent.node_config,
                parents=[parent],
            )
        assert {
            "parents": ["A physical interface cannot have parents."]
        } == error.value.message_dict

    def test_can_be_disabled(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface.enabled = False
        # Test is that this does not fail.
        interface.save()
        assert not reload_object(interface).enabled


@pytest.mark.allow_transactions
class TestPhysicalInterfaceTransactional:
    @pytest.fixture(autouse=True)
    def _setup(self, transactional_maasdb, mock_openfga, mock_start_workflows):
        pass

    def test_duplicate_physical_macs_not_allowed(self):
        mac = factory.make_mac_address()
        node = factory.make_Node(power_type="manual")
        vlan = factory.make_VLAN(dhcp_on=True)

        def _create_physical():
            factory.make_Interface(
                INTERFACE_TYPE.PHYSICAL, node=node, vlan=vlan, mac_address=mac
            )

        def create_physical():
            try:
                with transaction.atomic():
                    _create_physical()
            finally:
                connections.close_all()

        t = threading.Thread(target=create_physical)

        with transaction.atomic():
            # Perform an actual query so that Django actually
            # starts the transaction.
            VLAN.objects.count()

            # Create same physical in another transaction.
            t.start()
            t.join()

            # Should fail as this is a duplicate physical MAC address.
            with pytest.raises(IntegrityError):
                _create_physical()


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestInterfaceMTU:
    def test_get_effective_mtu_returns_default_mtu(self):
        nic1 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, link_connected=False
        )
        assert DEFAULT_MTU == nic1.get_effective_mtu()

    def test_get_effective_mtu_returns_interface_mtu(self):
        nic1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        nic_mtu = random.randint(552, 9100)
        nic1.params = {"mtu": nic_mtu}
        nic1.save()
        assert nic_mtu == nic1.get_effective_mtu()

    def test_get_effective_mtu_returns_vlan_mtu(self):
        nic1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        vlan_mtu = random.randint(552, 9100)
        nic1.vlan.mtu = vlan_mtu

        with post_commit_hooks:
            nic1.vlan.save()

        assert vlan_mtu == nic1.get_effective_mtu()

    def test_get_effective_mtu_considers_jumbo_vlan_children(self):
        fabric = factory.make_Fabric()
        vlan = factory.make_VLAN(fabric=fabric)
        eth0 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, vlan=fabric.get_default_vlan()
        )
        eth0_vlan = factory.make_Interface(
            iftype=INTERFACE_TYPE.VLAN, vlan=vlan, parents=[eth0]
        )
        vlan_mtu = random.randint(DEFAULT_MTU + 1, 9100)
        eth0_vlan.vlan.mtu = vlan_mtu
        eth0_vlan.vlan.save()
        assert vlan_mtu == eth0.get_effective_mtu()

    def test_get_effective_mtu_returns_highest_vlan_mtu(self):
        fabric = factory.make_Fabric()
        vlan1 = factory.make_VLAN(fabric=fabric)
        vlan2 = factory.make_VLAN(fabric=fabric)
        eth0 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, vlan=fabric.get_default_vlan()
        )
        eth0_vlan1 = factory.make_Interface(
            iftype=INTERFACE_TYPE.VLAN, vlan=vlan1, parents=[eth0]
        )
        eth0_vlan2 = factory.make_Interface(
            iftype=INTERFACE_TYPE.VLAN, vlan=vlan2, parents=[eth0]
        )
        eth0_vlan1.vlan.mtu = random.randint(1000, 1999)
        eth0_vlan1.vlan.save()
        eth0_vlan2.vlan.mtu = random.randint(2000, 2999)
        eth0_vlan2.vlan.save()
        assert eth0_vlan2.vlan.mtu == eth0.get_effective_mtu()

    def test_creates_acquired_bridge_copies_mtu(self):
        mtu = random.randint(600, 9100)
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        parent.params = {"mtu": mtu}
        parent.save()
        bridge = parent.create_acquired_bridge()
        assert bridge.name == parent.get_default_bridge_name()
        assert bridge.mac_address == parent.mac_address
        assert bridge.node_config == parent.node_config
        assert bridge.vlan == parent.vlan
        assert bridge.enabled
        assert bridge.acquired
        assert bridge.params == (
            {
                "bridge_type": BRIDGE_TYPE.STANDARD,
                "bridge_stp": False,
                "bridge_fd": 15,
                "mtu": mtu,
            }
        )
        assert [parent.id] == [p.id for p in bridge.parents.all()]


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestVLANInterface:
    def test_vlan_has_supplied_name(self):
        name = factory.make_name("eth", size=2)
        node_config = factory.make_NodeConfig()
        parent = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, name=name, node_config=node_config
        )
        vlan = factory.make_VLAN()
        vlan_ifname = factory.make_name()
        interface = VLANInterface(
            node_config=node_config,
            mac_address=factory.make_mac_address(),
            type=INTERFACE_TYPE.VLAN,
            name=vlan_ifname,
            vlan=vlan,
            enabled=True,
        )
        interface.save()
        InterfaceRelationship(child=interface, parent=parent).save()
        assert vlan_ifname == interface.name

    def test_manager_returns_vlan_interfaces(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        vlan = factory.make_VLAN()
        interface = factory.make_Interface(
            INTERFACE_TYPE.VLAN, vlan=vlan, parents=[parent]
        )
        assert sorted([interface], key=str) == sorted(
            VLANInterface.objects.all(), key=str
        )

    def test_get_node_returns_parent_node(self):
        node = factory.make_Node()
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        vlan = factory.make_VLAN()
        interface = factory.make_Interface(
            INTERFACE_TYPE.VLAN, vlan=vlan, parents=[parent]
        )
        assert node == interface.get_node()

    def test_removed_if_underlying_interface_gets_removed(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface = factory.make_Interface(
            INTERFACE_TYPE.VLAN, parents=[parent]
        )
        parent.delete()
        assert reload_object(interface) is None

    def test_can_only_have_one_parent(self):
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        with pytest.raises(ValidationError) as error:
            factory.make_Interface(
                INTERFACE_TYPE.VLAN, parents=[parent1, parent2]
            )
        assert {
            "parents": ["VLAN interface must have exactly one parent."]
        } == error.value.message_dict

    def test_must_have_one_parent(self):
        node = factory.make_Device()
        vlan = factory.make_VLAN(vid=1)
        with pytest.raises(ValidationError) as error:
            factory.make_Interface(INTERFACE_TYPE.VLAN, node=node, vlan=vlan)
        assert {
            "parents": ["VLAN interface must have exactly one parent."]
        } == error.value.message_dict

    def test_parent_cannot_be_VLAN(self):
        physical = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        vlan = factory.make_Interface(INTERFACE_TYPE.VLAN, parents=[physical])
        with pytest.raises(ValidationError) as error:
            factory.make_Interface(INTERFACE_TYPE.VLAN, parents=[vlan])
        assert (
            {
                "parents": [
                    "VLAN interface can only be created on a physical "
                    "or bond interface."
                ]
            }
        ) == error.value.message_dict

    def test_node_config_set_to_parent_node_config(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface = factory.make_Interface(
            INTERFACE_TYPE.VLAN, parents=[parent]
        )
        assert parent.node_config == interface.node_config

    def test_mac_address_set_to_parent_mac_address(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface = factory.make_Interface(
            INTERFACE_TYPE.VLAN, parents=[parent]
        )
        assert parent.mac_address == interface.mac_address

    def test_updating_parent_mac_address_updates_vlan_mac_address(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface = factory.make_Interface(
            INTERFACE_TYPE.VLAN, parents=[parent]
        )
        parent.mac_address = factory.make_mac_address()

        with post_commit_hooks:
            parent.save()

        interface = reload_object(interface)
        assert parent.mac_address == interface.mac_address

    def test_disable_parent_disables_vlan_interface(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface = factory.make_Interface(
            INTERFACE_TYPE.VLAN, parents=[parent]
        )
        parent.enabled = False
        parent.save()
        assert not interface.is_enabled()
        assert not reload_object(interface).enabled

    def test_enable_parent_enables_vlan_interface(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface = factory.make_Interface(
            INTERFACE_TYPE.VLAN, parents=[parent]
        )
        parent.enabled = False
        parent.save()
        parent.enabled = True
        parent.save()
        assert interface.is_enabled()
        assert reload_object(interface).enabled

    def test_disable_bond_parents_disables_vlan_interface(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        bond = factory.make_Interface(
            INTERFACE_TYPE.BOND,
            mac_address=parent1.mac_address,
            parents=[parent1, parent2],
        )
        interface = factory.make_Interface(INTERFACE_TYPE.VLAN, parents=[bond])
        parent1.enabled = False
        parent1.save()
        parent2.enabled = False
        parent2.save()
        assert not interface.is_enabled()
        assert not reload_object(interface).enabled

    def test_vlan_has_bootable_vlan_for_vlan(self):
        name = factory.make_name("eth", size=2)
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, name=name)
        vlan = factory.make_VLAN(dhcp_on=True)
        interface = factory.make_Interface(
            INTERFACE_TYPE.VLAN, vlan=vlan, parents=[parent]
        )
        assert interface.has_bootable_vlan()

    def test_vlan_has_bootable_vlan_for_relay_vlan(self):
        name = factory.make_name("eth", size=2)
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, name=name)
        vlan = factory.make_VLAN(
            dhcp_on=False, relay_vlan=factory.make_VLAN(dhcp_on=True)
        )
        interface = factory.make_Interface(
            INTERFACE_TYPE.VLAN, vlan=vlan, parents=[parent]
        )
        assert interface.has_bootable_vlan()

    def test_vlan_has_bootable_vlan_with_no_dhcp(self):
        name = factory.make_name("eth", size=2)
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, name=name)
        vlan = factory.make_VLAN()
        interface = factory.make_Interface(
            INTERFACE_TYPE.VLAN, vlan=vlan, parents=[parent]
        )
        assert not interface.has_bootable_vlan()


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestBondInterface:
    def test_manager_returns_bond_interfaces(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        interface = factory.make_Interface(
            INTERFACE_TYPE.BOND, parents=[parent1, parent2]
        )
        assert sorted([interface], key=str) == sorted(
            BondInterface.objects.all(), key=str
        )

    def test_get_node_returns_parent_node(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        interface = factory.make_Interface(
            INTERFACE_TYPE.BOND, parents=[parent1, parent2]
        )
        assert sorted([interface], key=str) == sorted(
            BondInterface.objects.all(), key=str
        )
        assert node == interface.get_node()

    def test_removed_if_underlying_interfaces_gets_removed(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        interface = factory.make_Interface(
            INTERFACE_TYPE.BOND, parents=[parent1, parent2]
        )
        parent1.delete()
        parent2.delete()
        assert reload_object(interface) is None

    def test_requires_mac_address(self):
        interface = BondInterface(
            name=factory.make_name("bond"),
            node_config=factory.make_NodeConfig(),
        )
        with pytest.raises(ValidationError) as error:
            interface.save()
        assert {
            "mac_address": ["This field cannot be blank."]
        } == error.value.message_dict

    def test_parent_interfaces_must_belong_to_same_node(self):
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        with pytest.raises(ValidationError) as error:
            factory.make_Interface(
                INTERFACE_TYPE.BOND, parents=[parent1, parent2]
            )
        assert {
            "parents": ["Parent interfaces do not belong to the same node."]
        } == error.value.message_dict

    def test_parent_interfaces_must_be_physical(self):
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        vlan1 = factory.make_Interface(INTERFACE_TYPE.VLAN, parents=[parent1])
        with pytest.raises(ValidationError) as error:
            factory.make_Interface(
                INTERFACE_TYPE.BOND, parents=[parent1, vlan1]
            )
        assert {
            "parents": ["Only physical interfaces can be bonded."]
        } == error.value.message_dict

    def test_can_use_parents_mac_address(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        # Test is that no error is raised.
        factory.make_Interface(
            INTERFACE_TYPE.BOND,
            mac_address=parent1.mac_address,
            parents=[parent1, parent2],
        )

    def test_can_use_unique_mac_address(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        # Test is that no error is raised.
        factory.make_Interface(
            INTERFACE_TYPE.BOND,
            mac_address=factory.make_mac_address(),
            parents=[parent1, parent2],
        )

    def test_warns_for_non_unique_mac_address(self):
        with FakeLogger("maas") as logger:
            node = factory.make_Node()
            other_nic = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
            parent1 = factory.make_Interface(
                INTERFACE_TYPE.PHYSICAL, node=node
            )
            parent2 = factory.make_Interface(
                INTERFACE_TYPE.PHYSICAL, node=node
            )
            iface = factory.make_Interface(
                INTERFACE_TYPE.BOND,
                mac_address=other_nic.mac_address,
                parents=[parent1, parent2],
            )
            assert (
                f"While adding {iface.get_log_string()}: found a MAC address already in use by {other_nic.get_log_string()}."
                in logger.output
            )

    def test_node_config_is_set_to_parents_node_config(self):
        node_config = factory.make_NodeConfig()
        parent1 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node_config=node_config
        )
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node_config=node_config
        )
        interface = factory.make_Interface(
            INTERFACE_TYPE.BOND,
            mac_address=factory.make_mac_address(),
            parents=[parent1, parent2],
        )
        assert interface.node_config == parent1.node_config

    def test_disable_one_parent_doesnt_disable_the_bond(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        interface = factory.make_Interface(
            INTERFACE_TYPE.BOND,
            mac_address=factory.make_mac_address(),
            parents=[parent1, parent2],
        )
        parent1.enabled = False
        parent1.save()
        assert interface.is_enabled()
        assert reload_object(interface).enabled

    def test_disable_all_parents_disables_the_bond(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        interface = factory.make_Interface(
            INTERFACE_TYPE.BOND,
            mac_address=factory.make_mac_address(),
            parents=[parent1, parent2],
        )
        parent1.enabled = False
        parent1.save()
        parent2.enabled = False
        parent2.save()
        assert not interface.is_enabled()
        assert not reload_object(interface).enabled

    def test_create_bond_with_no_link_parents(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent1.clear_all_links()
        parent2.clear_all_links()
        parent1.remove_link_dhcp()
        parent2.remove_link_dhcp()
        parent1.remove_link_up()
        parent2.remove_link_up()
        parent1.vlan = None
        parent2.vlan = None
        parent1.link_connected = False
        parent2.link_connected = False
        parent1.save()
        parent2.save()
        interface = factory.make_Interface(
            INTERFACE_TYPE.BOND,
            mac_address=factory.make_mac_address(),
            parents=[parent1, parent2],
        )
        assert interface.link_connected


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestBridgeInterface:
    def test_manager_returns_bridge_interfaces(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        interface = factory.make_Interface(
            INTERFACE_TYPE.BRIDGE, parents=[parent1, parent2]
        )
        assert sorted([interface], key=str) == sorted(
            BridgeInterface.objects.all(), key=str
        )

    def test_get_node_returns_parent_node(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        interface = factory.make_Interface(
            INTERFACE_TYPE.BRIDGE, parents=[parent1, parent2]
        )
        assert sorted([interface], key=str) == sorted(
            BridgeInterface.objects.all(), key=str
        )
        assert node == interface.get_node()

    def test_removed_if_underlying_interfaces_gets_removed(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        interface = factory.make_Interface(
            INTERFACE_TYPE.BRIDGE, parents=[parent1, parent2]
        )
        parent1.delete()
        parent2.delete()
        assert reload_object(interface) is None

    def test_requires_mac_address(self):
        interface = BridgeInterface(
            name=factory.make_name("bridge"),
            node_config=factory.make_NodeConfig(),
        )
        with pytest.raises(ValidationError) as error:
            interface.save()
        assert {
            "mac_address": ["This field cannot be blank."]
        } == error.value.message_dict

    def test_allows_acquired_to_be_true(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        bridge = factory.make_Interface(
            INTERFACE_TYPE.BRIDGE, parents=[parent]
        )
        bridge.acquired = True
        bridge.save()

    def test_parent_interfaces_must_belong_to_same_node(self):
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        with pytest.raises(ValidationError) as error:
            factory.make_Interface(
                INTERFACE_TYPE.BRIDGE, parents=[parent1, parent2]
            )
        assert {
            "parents": ["Parent interfaces do not belong to the same node."]
        } == error.value.message_dict

    def test_can_use_parents_mac_address(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        # Test is that no error is raised.
        factory.make_Interface(
            INTERFACE_TYPE.BRIDGE,
            mac_address=parent1.mac_address,
            parents=[parent1, parent2],
        )

    def test_can_use_unique_mac_address(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        # Test is that no error is raised.
        factory.make_Interface(
            INTERFACE_TYPE.BRIDGE,
            mac_address=factory.make_mac_address(),
            parents=[parent1, parent2],
        )

    def test_warns_for_non_unique_mac_address(self):
        with FakeLogger("maas") as logger:
            node = factory.make_Node()
            other_nic = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
            parent1 = factory.make_Interface(
                INTERFACE_TYPE.PHYSICAL, node=node
            )
            parent2 = factory.make_Interface(
                INTERFACE_TYPE.PHYSICAL, node=node
            )
            # Test is that no error is raised.
            iface = factory.make_Interface(
                INTERFACE_TYPE.BRIDGE,
                mac_address=other_nic.mac_address,
                parents=[parent1, parent2],
            )
            assert (
                f"While adding {iface.get_log_string()}: found a MAC address already in use by {other_nic.get_log_string()}."
                in logger.output
            )

    def test_node_config_is_set_to_parents_node_config(self):
        node_config = factory.make_NodeConfig()
        parent1 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node_config=node_config
        )
        parent2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node_config=node_config
        )
        interface = factory.make_Interface(
            INTERFACE_TYPE.BRIDGE,
            mac_address=factory.make_mac_address(),
            parents=[parent1, parent2],
        )
        assert interface.node_config == parent1.node_config

    def test_disable_one_parent_doesnt_disable_the_bridge(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        interface = factory.make_Interface(
            INTERFACE_TYPE.BRIDGE,
            mac_address=factory.make_mac_address(),
            parents=[parent1, parent2],
        )
        parent1.enabled = False
        parent1.save()
        assert interface.is_enabled()
        assert reload_object(interface).enabled

    def test_disable_all_parents_disables_the_bridge(self):
        node = factory.make_Node()
        parent1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        parent2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)
        interface = factory.make_Interface(
            INTERFACE_TYPE.BRIDGE,
            mac_address=factory.make_mac_address(),
            parents=[parent1, parent2],
        )
        parent1.enabled = False
        parent1.save()
        parent2.enabled = False
        parent2.save()
        assert not interface.is_enabled()
        assert not reload_object(interface).enabled


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestUnknownInterface:
    def test_manager_returns_unknown_interfaces(self):
        unknown = factory.make_Interface(INTERFACE_TYPE.UNKNOWN)
        assert sorted([unknown], key=str) == sorted(
            UnknownInterface.objects.all(), key=str
        )

    def test_get_node_returns_None(self):
        interface = factory.make_Interface(INTERFACE_TYPE.UNKNOWN)
        assert interface.get_node() is None

    def test_doesnt_allow_node_config(self):
        interface = UnknownInterface(
            name="eth0",
            node_config=factory.make_NodeConfig(),
            mac_address=factory.make_mac_address(),
        )
        with pytest.raises(ValidationError) as error:
            interface.save()
        assert {
            "node_config": ["This field must be blank."]
        } == error.value.message_dict

    def test_warns_for_non_unique_unknown_mac(self):
        with FakeLogger("maas") as logger:
            interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
            unknown = UnknownInterface(
                name="eth0", mac_address=interface.mac_address
            )
            unknown.save()
            assert (
                f"While adding {unknown.get_log_string()}: found a MAC address already in use by {interface.get_log_string()}."
                in logger.output
            )


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestUpdateIpAddresses:
    def test_finds_ipv6_subnet(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        network = factory.make_ipv6_network()
        subnet = factory.make_Subnet(cidr=network.cidr)
        cidr = "%s/128" % str(IPAddress(network.first + 1))

        with post_commit_hooks:
            interface.update_ip_addresses([cidr])

        assert not Subnet.objects.filter(cidr=cidr).exists()
        assert interface.ip_addresses.first().subnet == subnet

    def test_eui64_address_returns_correct_value(self):
        mac_address = factory.make_mac_address()
        network = factory.make_ipv6_network(slash=64)
        iface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, mac_address=mac_address
        )
        assert iface._eui64_address(network.cidr) == EUI(mac_address).ipv6(
            network.first
        )

    def test_does_not_add_eui_64_address(self):
        # See also LP#1639090.
        mac_address = factory.make_mac_address()
        iface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, mac_address=mac_address
        )
        network = factory.make_ipv6_network(slash=64)
        cidr = "%s/64" % str(iface._eui64_address(network.cidr))

        with post_commit_hooks:
            iface.update_ip_addresses([cidr])
        assert 0 == iface.ip_addresses.count()
        assert 1 == Subnet.objects.filter(cidr=network.cidr).count()

    def test_does_not_add_addresses_from_duplicate_subnet(self):
        # See also LP#1803188.
        mac_address = factory.make_mac_address()
        vlan = factory.make_VLAN()
        factory.make_Subnet(cidr="10.0.0.0/8", vlan=vlan)
        factory.make_Subnet(cidr="2001::/64", vlan=vlan)
        node = factory.make_Node()
        iface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL,
            mac_address=mac_address,
            vlan=vlan,
            node=node,
        )

        with post_commit_hooks:
            iface.update_ip_addresses(
                ["10.0.0.1/8", "10.0.0.2/8", "2001::1/64", "2001::2/64"]
            )
        assert 2 == iface.ip_addresses.count()

    def test_finds_ipv6_subnet_regardless_of_order(self):
        iface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        network = factory.make_ipv6_network()
        subnet = factory.make_Subnet(cidr=network.cidr)
        cidr_net = str(network.cidr)
        cidr_128 = "%s/128" % str(IPAddress(network.first + 1))

        with post_commit_hooks:
            iface.update_ip_addresses([cidr_128, cidr_net])

        assert not Subnet.objects.filter(cidr=cidr_128).exists()
        assert not iface.ip_addresses.exclude(subnet=subnet).exists()

    def test_creates_missing_slash_64_ipv6_subnet(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        network = factory.make_ipv6_network()
        cidr = "%s/128" % str(IPAddress(network.first + 1))

        with post_commit_hooks:
            interface.update_ip_addresses([cidr])

        subnets = Subnet.objects.filter(cidr="%s/64" % str(network.ip))
        assert 1 == len(subnets)
        assert not Subnet.objects.filter(cidr=cidr).exists()
        assert interface.ip_addresses.first().subnet == subnets[0]

    def test_creates_missing_subnet(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        assert 0 == interface.ip_addresses.count()
        network = factory.make_ip4_or_6_network()
        cidr = str(network)
        address = str(network.ip)

        with post_commit_hooks:
            interface.update_ip_addresses([cidr])

        subnets = Subnet.objects.filter(
            cidr=str(network.cidr), vlan=interface.vlan
        )
        assert 1 == len(subnets)
        assert 1 == interface.ip_addresses.count()

        ip = interface.ip_addresses.first()
        assert ip.alloc_type == IPADDRESS_TYPE.DISCOVERED
        assert ip.subnet == subnets[0]
        assert ip.ip == address

    def test_creates_discovered_ip_addresses(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        vlan = VLAN.objects.get_default_vlan()
        num_connections = 3
        cidr_list = [
            str(factory.make_ip4_or_6_network())
            for _ in range(num_connections)
        ]
        subnet_list = [
            factory.make_Subnet(cidr=cidr, vlan=vlan) for cidr in cidr_list
        ]

        with post_commit_hooks:
            interface.update_ip_addresses(cidr_list)

        assert num_connections == interface.ip_addresses.count()
        for cidr, subnet in zip(cidr_list, subnet_list, strict=True):
            ip = interface.ip_addresses.get(ip=cidr.split("/")[0])
            assert ip.alloc_type == IPADDRESS_TYPE.DISCOVERED
            assert ip.subnet == subnet
            assert ip.ip == str(IPNetwork(cidr).ip)

    def test_links_interface_to_vlan_on_existing_subnet_with_logging(
        self, mocker
    ):
        fabric1 = factory.make_Fabric()
        fabric2 = factory.make_Fabric()
        fabric3 = factory.make_Fabric()
        vlan1 = factory.make_VLAN(fabric=fabric1)
        vlan2 = factory.make_VLAN(fabric=fabric2)
        vlan3 = factory.make_VLAN(fabric=fabric3)
        subnet1 = factory.make_Subnet(vlan=vlan1)
        subnet2 = factory.make_Subnet(vlan=vlan2)
        subnet3 = factory.make_Subnet(vlan=vlan3)
        interface1 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface2 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface3 = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        maaslog = mocker.patch.object(
            interface_module, "maaslog", autospec=True
        )

        with post_commit_hooks:
            interface1.update_ip_addresses([subnet1.cidr])
            interface2.update_ip_addresses([subnet2.cidr])
            interface3.update_ip_addresses([subnet3.cidr])
        assert vlan1 == interface1.vlan
        assert vlan2 == interface2.vlan
        assert vlan3 == interface3.vlan
        maaslog.info.assert_has_calls(
            [
                call(
                    "%s: Observed connected to %s via %s."
                    % (
                        interface1.get_log_string(),
                        interface1.vlan.fabric.get_name(),
                        subnet1.cidr,
                    )
                ),
                call(
                    "%s: Observed connected to %s via %s."
                    % (
                        interface2.get_log_string(),
                        interface2.vlan.fabric.get_name(),
                        subnet2.cidr,
                    )
                ),
                call(
                    "%s: Observed connected to %s via %s."
                    % (
                        interface3.get_log_string(),
                        interface3.vlan.fabric.get_name(),
                        subnet3.cidr,
                    )
                ),
            ]
        )

    def test_deletes_old_discovered_ip_addresses_on_interface(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        # Create existing DISCOVERED IP address on the interface. These should
        # all be deleted.
        existing_discovered = [
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.DISCOVERED, interface=interface
            )
            for i in range(3)
        ]

        with post_commit_hooks:
            interface.update_ip_addresses([])

        assert 0 == len(
            reload_objects(StaticIPAddress, existing_discovered)
        ), "Discovered IP address should have been deleted."

    def test_deletes_old_discovered_ip_addresses(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        vlan = VLAN.objects.get_default_vlan()
        num_connections = 3
        cidr_list = [
            str(factory.make_ip4_or_6_network())
            for _ in range(num_connections)
        ]
        subnet_list = [
            factory.make_Subnet(cidr=cidr, vlan=vlan) for cidr in cidr_list
        ]

        # Create existing DISCOVERED IP address with the same IP as those
        # that are going to be connected to the interface. These objects
        # should be deleted.
        existing_discovered = [
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.DISCOVERED,
                ip=str(IPNetwork(cidr_list[i]).ip),
                subnet=subnet_list[i],
            )
            for i in range(num_connections)
        ]

        with post_commit_hooks:
            interface.update_ip_addresses(cidr_list)

        assert 0 == len(
            reload_objects(StaticIPAddress, existing_discovered)
        ), "Discovered IP address should have been deleted."
        assert num_connections == interface.ip_addresses.count()
        for cidr, subnet in zip(cidr_list, subnet_list, strict=True):
            ip = interface.ip_addresses.get(ip=cidr.split("/")[0])
            assert ip.alloc_type == IPADDRESS_TYPE.DISCOVERED
            assert ip.subnet == subnet
            assert ip.ip == str(IPNetwork(cidr).ip)

    def test_deletes_old_discovered_ip_addresses_with_unknown_nics(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        vlan = VLAN.objects.get_default_vlan()
        num_connections = 3
        cidr_list = [
            str(factory.make_ip4_or_6_network())
            for _ in range(num_connections)
        ]
        subnet_list = [
            factory.make_Subnet(cidr=cidr, vlan=vlan) for cidr in cidr_list
        ]

        # Create existing DISCOVERED IP address with the same IP as those
        # that are going to be connected to the interface. Each IP address
        # is linked to an UnknownInterface. The interfaces and the static IP
        # address should be deleted.
        existing_nics = [
            UnknownInterface.objects.create(
                name="eth0",
                mac_address=factory.make_mac_address(),
                vlan=subnet_list[i].vlan,
            )
            for i in range(num_connections)
        ]
        existing_discovered = [
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.DISCOVERED,
                ip=str(IPNetwork(cidr_list[i]).ip),
                subnet=subnet_list[i],
                interface=existing_nics[i],
            )
            for i in range(num_connections)
        ]

        with post_commit_hooks:
            interface.update_ip_addresses(cidr_list)

        assert 0 == len(
            reload_objects(StaticIPAddress, existing_discovered)
        ), "Discovered IP address should have been deleted."
        assert 0 == len(reload_objects(UnknownInterface, existing_nics)), (
            "Unknown interfaces should have been deleted."
        )
        assert num_connections == interface.ip_addresses.count()
        for cidr, subnet in zip(cidr_list, subnet_list, strict=True):
            ip = interface.ip_addresses.get(ip=cidr.split("/")[0])
            assert ip.alloc_type == IPADDRESS_TYPE.DISCOVERED
            assert ip.subnet == subnet
            assert ip.ip == str(IPNetwork(cidr).ip)

    def test_deletes_old_sticky_ip_addresses_not_linked(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        vlan = VLAN.objects.get_default_vlan()
        num_connections = 3
        cidr_list = [
            str(factory.make_ip4_or_6_network())
            for _ in range(num_connections)
        ]
        subnet_list = [
            factory.make_Subnet(cidr=cidr, vlan=vlan) for cidr in cidr_list
        ]

        # Create existing DISCOVERED IP address with the same IP as those
        # that are going to be connected to the interface. These objects
        # should be deleted.
        existing_discovered = [
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.STICKY,
                ip=str(IPNetwork(cidr_list[i]).ip),
                subnet=subnet_list[i],
            )
            for i in range(num_connections)
        ]

        with post_commit_hooks:
            interface.update_ip_addresses(cidr_list)

        assert 0 == len(
            reload_objects(StaticIPAddress, existing_discovered)
        ), "Sticky IP address should have been deleted."
        assert num_connections == interface.ip_addresses.count()
        for cidr, subnet in zip(cidr_list, subnet_list, strict=True):
            ip = interface.ip_addresses.get(ip=cidr.split("/")[0])
            assert ip.alloc_type == IPADDRESS_TYPE.DISCOVERED
            assert ip.subnet == subnet
            assert ip.ip == str(IPNetwork(cidr).ip)

    def test_deletes_old_ip_address_on_managed_subnet_with_log(self, mocker):
        network = factory.make_ip4_or_6_network()
        cidr = str(network)
        address = str(network.ip)
        vlan = VLAN.objects.get_default_vlan()
        vlan.dhcp_on = True

        with post_commit_hooks:
            vlan.save()

        subnet = factory.make_Subnet(cidr=cidr, vlan=vlan)
        other_interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip=address,
            subnet=subnet,
            interface=other_interface,
        )
        maaslog = mocker.patch.object(
            interface_module, "maaslog", autospec=True
        )

        # Update that ip address on another interface. Which will log the
        # error message and delete the IP address.
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)

        with post_commit_hooks:
            interface.update_ip_addresses([cidr])
        maaslog.warning.assert_called_with(
            f"{ip.get_log_name_for_alloc_type()} IP address "
            f"({address}) on {other_interface.node_config.node.fqdn} "
            "was deleted because it was handed out by the MAAS DHCP server "
            "from the dynamic range.",
        )

    def test_deletes_multiple_staticipaddress_with_same_ip(self):
        network = factory.make_ip4_or_6_network()
        cidr = str(network)
        address = str(network.ip)
        vlan = VLAN.objects.get_default_vlan()
        vlan.dhcp_on = True

        with post_commit_hooks:
            vlan.save()

        subnet = factory.make_Subnet(cidr=cidr, vlan=vlan)
        ip1 = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip=address,
            subnet=subnet,
        )
        ip2 = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.DISCOVERED,
            ip=address,
            subnet=subnet,
        )
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)

        with post_commit_hooks:
            interface.update_ip_addresses([cidr])

        assert reload_object(ip1) is None
        assert reload_object(ip2) is None

    def test_deletes_old_ip_address_on_unmanaged_subnet_with_log(self, mocker):
        network = factory.make_ip4_or_6_network()
        cidr = str(network)
        address = str(network.ip)
        vlan = VLAN.objects.get_default_vlan()
        subnet = factory.make_Subnet(cidr=cidr, vlan=vlan)
        other_interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip=address,
            subnet=subnet,
            interface=other_interface,
        )
        maaslog = mocker.patch.object(
            interface_module, "maaslog", autospec=True
        )

        # Update that ip address on another interface. Which will log the
        # error message and delete the IP address.
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)

        with post_commit_hooks:
            interface.update_ip_addresses([cidr])
        maaslog.warning.assert_called_with(
            f"{ip.get_log_name_for_alloc_type()} IP address "
            f"({address}) on {other_interface.node_config.node.fqdn} "
            "was deleted because it was handed out by an external DHCP "
            "server.",
        )


@pytest.mark.allow_transactions
class TestLinkSubnet:
    """Tests for `Interface.link_subnet`."""

    @pytest.fixture(autouse=True)
    def _setup(self, transactional_maasdb, mock_openfga, mock_start_workflows):
        pass

    def test_AUTO_creates_link_to_AUTO_with_subnet(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        auto_subnet = factory.make_Subnet(vlan=interface.vlan)
        interface.link_subnet(INTERFACE_LINK_TYPE.AUTO, auto_subnet)
        interface = reload_object(interface)
        auto_ip = interface.ip_addresses.get(alloc_type=IPADDRESS_TYPE.AUTO)
        assert auto_subnet == auto_ip.subnet

    def test_DHCP_creates_link_to_DHCP_with_subnet(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        dhcp_subnet = factory.make_Subnet(vlan=interface.vlan)
        interface.link_subnet(INTERFACE_LINK_TYPE.DHCP, dhcp_subnet)
        interface = reload_object(interface)
        dhcp_ip = interface.ip_addresses.get(alloc_type=IPADDRESS_TYPE.DHCP)
        assert dhcp_subnet == dhcp_ip.subnet

    def test_DHCP_creates_link_to_DHCP_without_subnet(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface.link_subnet(INTERFACE_LINK_TYPE.DHCP, None)
        interface = reload_object(interface)
        assert (
            get_one(
                interface.ip_addresses.filter(alloc_type=IPADDRESS_TYPE.DHCP)
            )
        ) is not None

    def test_STATIC_not_allowed_if_ip_address_not_in_subnet(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        network = factory.make_ipv4_network()
        subnet = factory.make_Subnet(
            vlan=interface.vlan, cidr=str(network.cidr)
        )
        ip_not_in_subnet = factory.make_ipv6_address()
        with pytest.raises(StaticIPAddressOutOfRange) as error:
            interface.link_subnet(
                INTERFACE_LINK_TYPE.STATIC,
                subnet,
                ip_address=ip_not_in_subnet,
            )
        assert "IP address is not in the given subnet '%s'." % subnet == str(
            error.value
        )

    def test_STATIC_not_allowed_if_reserved_ip_does_not_match_the_same_reserved_ip(
        self,
    ):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, vlan=interface.vlan
        )
        network = factory.make_ipv4_network()
        subnet = factory.make_Subnet(
            cidr=str(network.cidr), vlan=interface.vlan
        )
        reserved_ip = factory.make_ReservedIP(
            ip=factory.pick_ip_in_Subnet(subnet=subnet),
            subnet=subnet,
            mac_address=interface.mac_address,
        )
        reserved_ip2 = factory.make_ReservedIP(
            ip=factory.pick_ip_in_Subnet(
                subnet=subnet, but_not=[reserved_ip.ip]
            ),
            subnet=subnet,
            mac_address=interface2.mac_address,
        )
        with pytest.raises(StaticIPAddressReservedIPConflict) as error:
            interface.link_subnet(
                INTERFACE_LINK_TYPE.STATIC,
                subnet,
                ip_address=reserved_ip2.ip,
            )
        assert (
            "The MAC address %s or the static IP %s are associated with a reserved IP and cannot be used."
            % (interface.mac_address, reserved_ip2.ip)
        ) == str(error.value)

    def test_STATIC_not_allowed_if_reserved_ip_does_not_match_the_mac(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface2 = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, vlan=interface.vlan
        )
        network = factory.make_ipv4_network()
        subnet = factory.make_Subnet(
            cidr=str(network.cidr), vlan=interface.vlan
        )
        reserved_ip = factory.make_ReservedIP(
            ip=factory.pick_ip_in_Subnet(subnet=subnet),
            subnet=subnet,
            mac_address=interface.mac_address,
        )
        with pytest.raises(StaticIPAddressReservedIPConflict) as error:
            interface2.link_subnet(
                INTERFACE_LINK_TYPE.STATIC,
                subnet,
                ip_address=reserved_ip.ip,
            )
        assert (
            "The static IP %s is already reserved for the MAC address %s."
            % (reserved_ip.ip, interface.mac_address)
        ) == str(error.value)

    def test_STATIC_not_allowed_if_reserved_ip_does_not_match(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        network = factory.make_ipv4_network()
        subnet = factory.make_Subnet(
            cidr=str(network.cidr), vlan=interface.vlan
        )
        reserved_ip = factory.make_ReservedIP(
            ip=factory.pick_ip_in_Subnet(subnet=subnet),
            subnet=subnet,
            mac_address=interface.mac_address,
        )
        static_ip = factory.pick_ip_in_Subnet(
            subnet=subnet, but_not=[reserved_ip.ip]
        )
        with pytest.raises(StaticIPAddressReservedIPConflict) as error:
            interface.link_subnet(
                INTERFACE_LINK_TYPE.STATIC,
                subnet,
                ip_address=static_ip,
            )
        assert (
            "The static IP %s does not match the reserved IP %s for the MAC address %s."
            % (static_ip, reserved_ip.ip, interface.mac_address)
        ) == str(error.value)

    def test_STATIC_allowed_if_reserved_ip_matches(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        network = factory.make_ipv4_network()
        subnet = factory.make_Subnet(
            cidr=str(network.cidr), vlan=interface.vlan
        )
        reserved_ip = factory.make_ReservedIP(
            ip=factory.pick_ip_in_Subnet(subnet=subnet),
            subnet=subnet,
            mac_address=interface.mac_address,
        )
        with post_commit_hooks:
            interface.link_subnet(
                INTERFACE_LINK_TYPE.STATIC, subnet, ip_address=reserved_ip.ip
            )
        interface = reload_object(interface)
        assert (
            get_one(
                interface.ip_addresses.filter(
                    alloc_type=IPADDRESS_TYPE.STICKY, ip=reserved_ip.ip
                )
            )
        ) is not None

    def test_AUTO_link_sets_vlan_if_vlan_undefined(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        network = factory.make_ipv4_network()
        subnet = factory.make_Subnet(
            vlan=interface.vlan, cidr=str(network.cidr)
        )
        interface.vlan = None
        interface.save()
        with post_commit_hooks:
            interface.link_subnet(INTERFACE_LINK_TYPE.AUTO, subnet)
        interface = reload_object(interface)
        assert subnet.vlan == interface.vlan

    def test_STATIC_not_allowed_if_ip_address_in_dynamic_range(self):
        with post_commit_hooks:
            interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)

            subnet = factory.make_ipv4_Subnet_with_IPRanges(
                vlan=interface.vlan
            )

            ip_in_dynamic = IPAddress(
                subnet.get_dynamic_ranges().first().start_ip
            )
            with pytest.raises(StaticIPAddressOutOfRange) as error:
                interface.link_subnet(
                    INTERFACE_LINK_TYPE.STATIC,
                    subnet,
                    ip_address=ip_in_dynamic,
                )
            expected_range = subnet.get_dynamic_range_for_ip(ip_in_dynamic)
        assert (
            "IP address is inside a dynamic range %s-%s."
            % (expected_range.start_ip, expected_range.end_ip)
        ) == str(error.value)

    def test_STATIC_sets_ip_in_no_subnet(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        ip = factory.make_ip_address()
        with post_commit_hooks:
            interface.link_subnet(
                INTERFACE_LINK_TYPE.STATIC, None, ip_address=ip
            )
        interface = reload_object(interface)
        assert (
            get_one(
                interface.ip_addresses.filter(
                    alloc_type=IPADDRESS_TYPE.STICKY, ip=ip, subnet=None
                )
            )
        ) is not None

    def test_STATIC_sets_ip_in_subnet(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        ip = factory.pick_ip_in_network(subnet.get_ipnetwork())

        with post_commit_hooks:
            interface.link_subnet(
                INTERFACE_LINK_TYPE.STATIC, subnet, ip_address=ip
            )
        interface = reload_object(interface)
        assert (
            get_one(
                interface.ip_addresses.filter(
                    alloc_type=IPADDRESS_TYPE.STICKY, ip=ip, subnet=subnet
                )
            )
        ) is not None

    @transactional
    def test_STATIC_picks_ip_in_subnet(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        with post_commit_hooks:
            interface.link_subnet(INTERFACE_LINK_TYPE.STATIC, subnet)
        interface = reload_object(interface)
        ip_address = get_one(
            interface.ip_addresses.filter(
                alloc_type=IPADDRESS_TYPE.STICKY, subnet=subnet
            )
        )
        assert ip_address is not None
        assert IPAddress(ip_address.ip) in subnet.get_ipnetwork()

    def test_LINK_UP_creates_link_STICKY_with_subnet(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        with post_commit_hooks:
            link_subnet = factory.make_Subnet(vlan=interface.vlan)
            interface.link_subnet(INTERFACE_LINK_TYPE.LINK_UP, link_subnet)
        interface = reload_object(interface)
        link_ip = interface.ip_addresses.get(alloc_type=IPADDRESS_TYPE.STICKY)
        assert link_ip.ip is None
        assert link_subnet == link_ip.subnet

    def test_LINK_UP_creates_link_STICKY_without_subnet(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        with post_commit_hooks:
            interface.link_subnet(INTERFACE_LINK_TYPE.LINK_UP, None)
        interface = reload_object(interface)
        link_ip = get_one(
            interface.ip_addresses.filter(alloc_type=IPADDRESS_TYPE.STICKY)
        )
        assert link_ip is not None
        assert link_ip.ip is None


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestForceAutoOrDHCPLink:
    """Tests for `Interface.force_auto_or_dhcp_link`."""

    def test_does_nothing_when_disconnected(self):
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, link_connected=False
        )
        assert interface.force_auto_or_dhcp_link() is None

    def test_sets_to_AUTO_on_subnet(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        static_ip = interface.force_auto_or_dhcp_link()
        assert IPADDRESS_TYPE.AUTO == static_ip.alloc_type
        assert subnet == static_ip.subnet

    def test_sets_to_DHCP(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        static_ip = interface.force_auto_or_dhcp_link()
        assert IPADDRESS_TYPE.DHCP == static_ip.alloc_type
        assert static_ip.subnet is None


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestEnsureLinkUp:
    """Tests for `Interface.ensure_link_up`."""

    def test_does_nothing_if_has_link(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        with post_commit_hooks:
            interface.link_subnet(INTERFACE_LINK_TYPE.DHCP, subnet)
            interface.ensure_link_up()
        interface = reload_object(interface)
        assert 1 == interface.ip_addresses.count(), (
            "Should only have one IP address assigned."
        )

    def test_does_nothing_if_no_vlan(self):
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, link_connected=False
        )
        interface.ensure_link_up()
        interface = reload_object(interface)
        assert 0 == interface.ip_addresses.count(), (
            "Should only have no IP address assigned."
        )

    def test_removes_other_link_ups_if_other_link_exists(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        link_ups = [
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.STICKY, ip="", interface=interface
            )
            for _ in range(3)
        ]
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO, interface=interface
        )
        with post_commit_hooks:
            interface.ensure_link_up()
        assert sorted([], key=str) == sorted(
            reload_objects(StaticIPAddress, link_ups), key=str
        )

    def test_creates_link_up_to_discovered_subnet_on_same_vlan(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.DISCOVERED,
            ip="",
            subnet=subnet,
            interface=interface,
        )
        with post_commit_hooks:
            interface.ensure_link_up()
        link_ip = interface.ip_addresses.filter(
            alloc_type=IPADDRESS_TYPE.STICKY
        ).first()
        assert link_ip.ip is None
        assert subnet == link_ip.subnet

    def test_creates_link_up_to_no_subnet_when_on_different_vlan(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet()
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.DISCOVERED,
            ip="",
            subnet=subnet,
            interface=interface,
        )
        with post_commit_hooks:
            interface.ensure_link_up()
        link_ip = interface.ip_addresses.filter(
            alloc_type=IPADDRESS_TYPE.STICKY
        ).first()
        assert link_ip.ip is None
        assert link_ip.subnet is None

    def test_creates_link_up_to_no_subnet(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        with post_commit_hooks:
            interface.ensure_link_up()
        link_ip = interface.ip_addresses.filter(
            alloc_type=IPADDRESS_TYPE.STICKY
        ).first()
        assert link_ip.ip is None
        assert link_ip.subnet is None


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestUnlinkIPAddress:
    """Tests for `Interface.unlink_ip_address`."""

    def test_doesnt_call_ensure_link_up_if_clearing_config(self, mocker):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        auto_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO,
            ip="",
            subnet=subnet,
            interface=interface,
        )
        mock_ensure_link_up = mocker.patch.object(
            interface, "ensure_link_up", autospec=True
        )
        with post_commit_hooks:
            interface.unlink_ip_address(auto_ip, clearing_config=True)
        assert reload_object(auto_ip) is None
        mock_ensure_link_up.assert_not_called()


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestUnlinkSubnet:
    """Tests for `Interface.unlink_subnet`."""

    def test_AUTO_deletes_link(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        auto_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO,
            ip="",
            subnet=subnet,
            interface=interface,
        )
        with post_commit_hooks:
            interface.unlink_subnet_by_id(auto_ip.id)
        assert reload_object(auto_ip) is None

    def test_DHCP_deletes_link_with_subnet(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        dhcp_subnet = factory.make_Subnet(vlan=interface.vlan)
        with post_commit_hooks:
            interface.link_subnet(INTERFACE_LINK_TYPE.DHCP, dhcp_subnet)
        interface = reload_object(interface)
        dhcp_ip = interface.ip_addresses.get(alloc_type=IPADDRESS_TYPE.DHCP)
        with post_commit_hooks:
            interface.unlink_subnet_by_id(dhcp_ip.id)
        assert reload_object(dhcp_ip) is None

    def test_STATIC_deletes_link_in_no_subnet(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        ip = factory.make_ip_address()
        with post_commit_hooks:
            interface.link_subnet(
                INTERFACE_LINK_TYPE.STATIC, None, ip_address=ip
            )
        interface = reload_object(interface)
        static_ip = get_one(
            interface.ip_addresses.filter(
                alloc_type=IPADDRESS_TYPE.STICKY, ip=ip, subnet=None
            )
        )
        with post_commit_hooks:
            interface.unlink_subnet_by_id(static_ip.id)
        assert reload_object(static_ip) is None

    def test_STATIC_deletes_link_in_subnet(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        ip = factory.pick_ip_in_network(subnet.get_ipnetwork())
        with post_commit_hooks:
            interface.link_subnet(
                INTERFACE_LINK_TYPE.STATIC, subnet, ip_address=ip
            )
        interface = reload_object(interface)
        static_ip = get_one(
            interface.ip_addresses.filter(
                alloc_type=IPADDRESS_TYPE.STICKY, ip=ip, subnet=subnet
            )
        )
        with post_commit_hooks:
            interface.unlink_subnet_by_id(static_ip.id)
        assert reload_object(static_ip) is None

    def test_LINK_UP_deletes_link(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        link_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip="",
            subnet=subnet,
            interface=interface,
        )
        with post_commit_hooks:
            interface.unlink_subnet_by_id(link_ip.id)
        assert reload_object(link_ip) is None

    def test_always_has_LINK_UP(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        link_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip="",
            subnet=subnet,
            interface=interface,
        )
        with post_commit_hooks:
            interface.unlink_subnet_by_id(link_ip.id)
        assert reload_object(link_ip) is None
        assert (
            interface.ip_addresses.filter(
                alloc_type=IPADDRESS_TYPE.STICKY, ip=None
            ).first()
        ) is not None


@pytest.mark.allow_transactions
class TestUpdateIPAddress:
    """Tests for `Interface.update_ip_address`."""

    @pytest.fixture(autouse=True)
    def _setup(self, transactional_maasdb, mock_openfga, mock_start_workflows):
        pass

    def test_switch_dhcp_to_auto(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.DHCP,
            ip="",
            subnet=subnet,
            interface=interface,
        )
        static_id = static_ip.id
        new_subnet = factory.make_Subnet(vlan=interface.vlan)
        with post_commit_hooks:
            static_ip = interface.update_ip_address(
                static_ip, INTERFACE_LINK_TYPE.AUTO, new_subnet
            )
        assert static_id == static_ip.id
        assert IPADDRESS_TYPE.AUTO == static_ip.alloc_type
        assert new_subnet == static_ip.subnet
        assert static_ip.ip is None

    def test_switch_dhcp_to_link_up(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.DHCP,
            ip="",
            subnet=subnet,
            interface=interface,
        )
        static_id = static_ip.id
        new_subnet = factory.make_Subnet(vlan=interface.vlan)
        with post_commit_hooks:
            static_ip = interface.update_ip_address(
                static_ip, INTERFACE_LINK_TYPE.LINK_UP, new_subnet
            )
        assert static_id == static_ip.id
        assert IPADDRESS_TYPE.STICKY == static_ip.alloc_type
        assert new_subnet == static_ip.subnet
        assert static_ip.ip is None

    @transactional
    def test_switch_dhcp_to_static(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        network_v4 = factory.make_ipv4_network(slash=24)
        subnet = factory.make_Subnet(
            vlan=interface.vlan, cidr=str(network_v4.cidr)
        )
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.DHCP,
            ip="",
            subnet=subnet,
            interface=interface,
        )
        static_id = static_ip.id
        network_v6 = factory.make_ipv6_network(slash=24)
        new_subnet = factory.make_Subnet(
            vlan=interface.vlan, cidr=str(network_v6.cidr)
        )
        with post_commit_hooks:
            static_ip = interface.update_ip_address(
                static_ip, INTERFACE_LINK_TYPE.STATIC, new_subnet
            )
        assert static_id == static_ip.id
        assert IPADDRESS_TYPE.STICKY == static_ip.alloc_type
        assert new_subnet == static_ip.subnet
        assert static_ip.ip is not None

    def test_switch_auto_to_dhcp(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO,
            ip="",
            subnet=subnet,
            interface=interface,
        )
        static_id = static_ip.id
        new_subnet = factory.make_Subnet(vlan=interface.vlan)
        with post_commit_hooks:
            static_ip = interface.update_ip_address(
                static_ip, INTERFACE_LINK_TYPE.DHCP, new_subnet
            )
        assert static_id == static_ip.id
        assert IPADDRESS_TYPE.DHCP == static_ip.alloc_type
        assert new_subnet == static_ip.subnet
        assert static_ip.ip is None

    def test_switch_auto_to_link_up(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO,
            ip="",
            subnet=subnet,
            interface=interface,
        )
        static_id = static_ip.id
        new_subnet = factory.make_Subnet(vlan=interface.vlan)
        with post_commit_hooks:
            static_ip = interface.update_ip_address(
                static_ip, INTERFACE_LINK_TYPE.LINK_UP, new_subnet
            )
        assert static_id == static_ip.id
        assert IPADDRESS_TYPE.STICKY == static_ip.alloc_type
        assert new_subnet == static_ip.subnet
        assert static_ip.ip is None

    @transactional
    def test_switch_auto_to_static(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        network_v4 = factory.make_ipv4_network(slash=24)
        subnet = factory.make_Subnet(
            vlan=interface.vlan, cidr=str(network_v4.cidr)
        )
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO,
            ip="",
            subnet=subnet,
            interface=interface,
        )
        static_id = static_ip.id
        network_v6 = factory.make_ipv6_network(slash=24)
        new_subnet = factory.make_Subnet(
            vlan=interface.vlan, cidr=str(network_v6.cidr)
        )
        with post_commit_hooks:
            static_ip = interface.update_ip_address(
                static_ip, INTERFACE_LINK_TYPE.STATIC, new_subnet
            )
        assert static_id == static_ip.id
        assert IPADDRESS_TYPE.STICKY == static_ip.alloc_type
        assert new_subnet == static_ip.subnet
        assert static_ip.ip is not None

    def test_switch_link_up_to_auto(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip="",
            subnet=subnet,
            interface=interface,
        )
        static_id = static_ip.id
        new_subnet = factory.make_Subnet(vlan=interface.vlan)
        with post_commit_hooks:
            static_ip = interface.update_ip_address(
                static_ip, INTERFACE_LINK_TYPE.AUTO, new_subnet
            )
        assert static_id == static_ip.id
        assert IPADDRESS_TYPE.AUTO == static_ip.alloc_type
        assert new_subnet == static_ip.subnet
        assert static_ip.ip is None

    def test_switch_link_up_to_dhcp(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip="",
            subnet=subnet,
            interface=interface,
        )
        static_id = static_ip.id
        new_subnet = factory.make_Subnet(vlan=interface.vlan)
        with post_commit_hooks:
            static_ip = interface.update_ip_address(
                static_ip, INTERFACE_LINK_TYPE.DHCP, new_subnet
            )
        assert static_id == static_ip.id
        assert IPADDRESS_TYPE.DHCP == static_ip.alloc_type
        assert new_subnet == static_ip.subnet
        assert static_ip.ip is None

    @transactional
    def test_switch_link_up_to_static(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        network_v4 = factory.make_ipv4_network(slash=24)
        subnet = factory.make_Subnet(
            vlan=interface.vlan, cidr=str(network_v4.cidr)
        )
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip="",
            subnet=subnet,
            interface=interface,
        )
        static_id = static_ip.id
        network_v6 = factory.make_ipv6_network(slash=24)
        new_subnet = factory.make_Subnet(
            vlan=interface.vlan, cidr=str(network_v6.cidr)
        )
        with post_commit_hooks:
            static_ip = interface.update_ip_address(
                static_ip, INTERFACE_LINK_TYPE.STATIC, new_subnet
            )
        assert static_id == static_ip.id
        assert IPADDRESS_TYPE.STICKY == static_ip.alloc_type
        assert new_subnet == static_ip.subnet
        assert static_ip.ip is not None

    def test_switch_static_to_dhcp(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip=factory.pick_ip_in_Subnet(subnet),
            subnet=subnet,
            interface=interface,
        )
        static_id = static_ip.id
        new_subnet = factory.make_Subnet(vlan=interface.vlan)
        with post_commit_hooks:
            static_ip = interface.update_ip_address(
                static_ip, INTERFACE_LINK_TYPE.DHCP, new_subnet
            )
        assert static_id == static_ip.id
        assert IPADDRESS_TYPE.DHCP == static_ip.alloc_type
        assert new_subnet == static_ip.subnet
        assert static_ip.ip is None

    def test_switch_static_to_auto(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip=factory.pick_ip_in_Subnet(subnet),
            subnet=subnet,
            interface=interface,
        )
        static_id = static_ip.id
        new_subnet = factory.make_Subnet(vlan=interface.vlan)
        with post_commit_hooks:
            static_ip = interface.update_ip_address(
                static_ip, INTERFACE_LINK_TYPE.AUTO, new_subnet
            )
        assert static_id == static_ip.id
        assert IPADDRESS_TYPE.AUTO == static_ip.alloc_type
        assert new_subnet == static_ip.subnet
        assert static_ip.ip is None

    def test_switch_static_to_link_up(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip=factory.pick_ip_in_Subnet(subnet),
            subnet=subnet,
            interface=interface,
        )
        static_id = static_ip.id
        new_subnet = factory.make_Subnet(vlan=interface.vlan)
        with post_commit_hooks:
            static_ip = interface.update_ip_address(
                static_ip, INTERFACE_LINK_TYPE.LINK_UP, new_subnet
            )
        assert static_id == static_ip.id
        assert IPADDRESS_TYPE.STICKY == static_ip.alloc_type
        assert new_subnet == static_ip.subnet
        assert static_ip.ip is None

    def test_switch_static_to_same_subnet_does_nothing(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip=factory.pick_ip_in_Subnet(subnet),
            subnet=subnet,
            interface=interface,
        )
        static_id = static_ip.id
        static_ip_address = static_ip.ip
        with post_commit_hooks:
            static_ip = interface.update_ip_address(
                static_ip, INTERFACE_LINK_TYPE.STATIC, subnet
            )
        assert static_id == static_ip.id
        assert IPADDRESS_TYPE.STICKY == static_ip.alloc_type
        assert subnet == static_ip.subnet
        assert static_ip_address == static_ip.ip

    def test_switch_static_to_already_used_ip_address(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip=factory.pick_ip_in_Subnet(subnet),
            subnet=subnet,
            interface=interface,
        )
        other_interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        used_ip_address = factory.pick_ip_in_Subnet(
            subnet, but_not=[static_ip.ip]
        )
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip=used_ip_address,
            subnet=subnet,
            interface=other_interface,
        )
        with pytest.raises(
            StaticIPAddressUnavailable, match=r"IP address is already in use\."
        ):
            interface.update_ip_address(
                static_ip,
                INTERFACE_LINK_TYPE.STATIC,
                subnet,
                ip_address=used_ip_address,
            )

    def test_switch_static_to_same_subnet_with_different_ip(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        network = factory.make_ipv4_network(slash=24)
        subnet = factory.make_Subnet(
            vlan=interface.vlan, cidr=str(network.cidr)
        )
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip=factory.pick_ip_in_Subnet(subnet),
            subnet=subnet,
            interface=interface,
        )
        static_id = static_ip.id
        static_ip_address = static_ip.ip
        new_ip_address = factory.pick_ip_in_Subnet(
            subnet, but_not=[static_ip_address]
        )
        with post_commit_hooks:
            new_static_ip = interface.update_ip_address(
                static_ip,
                INTERFACE_LINK_TYPE.STATIC,
                subnet,
                ip_address=new_ip_address,
            )
        assert static_id == new_static_ip.id
        assert IPADDRESS_TYPE.STICKY == new_static_ip.alloc_type
        assert subnet == new_static_ip.subnet
        assert new_ip_address == new_static_ip.ip

    @transactional
    def test_switch_static_to_another_subnet(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        network_v4 = factory.make_ipv4_network(slash=24)
        subnet = factory.make_Subnet(
            vlan=interface.vlan, cidr=str(network_v4.cidr)
        )
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip=factory.pick_ip_in_Subnet(subnet),
            subnet=subnet,
            interface=interface,
        )
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip=factory.pick_ip_in_Subnet(subnet, but_not=[static_ip.ip]),
            subnet=subnet,
            interface=interface,
        )
        static_id = static_ip.id
        network_v6 = factory.make_ipv6_network(slash=24)
        new_subnet = factory.make_Subnet(
            vlan=interface.vlan, cidr=str(network_v6.cidr)
        )
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip=factory.pick_ip_in_Subnet(new_subnet),
            subnet=new_subnet,
            interface=interface,
        )
        with post_commit_hooks:
            new_static_ip = interface.update_ip_address(
                static_ip, INTERFACE_LINK_TYPE.STATIC, new_subnet
            )
        assert static_id == new_static_ip.id
        assert IPADDRESS_TYPE.STICKY == new_static_ip.alloc_type
        assert new_subnet == new_static_ip.subnet
        assert new_static_ip.ip is not None

    def test_switch_static_to_another_subnet_with_ip_address(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        network_v4 = factory.make_ipv4_network(slash=24)
        subnet = factory.make_Subnet(
            vlan=interface.vlan, cidr=str(network_v4.cidr)
        )
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip=factory.pick_ip_in_Subnet(subnet),
            subnet=subnet,
            interface=interface,
        )
        static_id = static_ip.id
        network_v6 = factory.make_ipv6_network(slash=24)
        new_subnet = factory.make_Subnet(
            vlan=interface.vlan, cidr=str(network_v6.cidr)
        )
        new_ip_address = factory.pick_ip_in_Subnet(new_subnet)
        with post_commit_hooks:
            new_static_ip = interface.update_ip_address(
                static_ip,
                INTERFACE_LINK_TYPE.STATIC,
                new_subnet,
                ip_address=new_ip_address,
            )
        assert static_id == new_static_ip.id
        assert IPADDRESS_TYPE.STICKY == new_static_ip.alloc_type
        assert new_subnet == new_static_ip.subnet
        assert new_ip_address == new_static_ip.ip


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestUpdateLinkById:
    """Tests for `Interface.update_link_by_id`."""

    def test_calls_update_ip_address_with_ip_address(self, mocker):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.DHCP,
            ip="",
            subnet=subnet,
            interface=interface,
        )
        mock_update_ip_address = mocker.patch.object(
            interface, "update_ip_address", autospec=True
        )
        interface.update_link_by_id(
            static_ip.id, INTERFACE_LINK_TYPE.AUTO, subnet
        )
        mock_update_ip_address.assert_called_once_with(
            static_ip, INTERFACE_LINK_TYPE.AUTO, subnet, ip_address=None
        )


@pytest.mark.allow_transactions
class TestClaimAutoIPs:
    """Tests for `Interface.claim_auto_ips`."""

    @pytest.fixture(autouse=True)
    def _setup(self, transactional_maasdb, mock_openfga, mock_start_workflows):
        pass

    def test_claims_all_auto_ip_addresses(self):
        with transaction.atomic():
            interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
            for _ in range(3):
                subnet = factory.make_ipv4_Subnet_with_IPRanges(
                    vlan=interface.vlan
                )
                factory.make_StaticIPAddress(
                    alloc_type=IPADDRESS_TYPE.AUTO,
                    ip="",
                    subnet=subnet,
                    interface=interface,
                )
        with transaction.atomic():
            with post_commit_hooks:
                observed = interface.claim_auto_ips()
        # Should now have 3 AUTO with IP addresses assigned.
        interface = reload_object(interface)
        assigned_addresses = interface.ip_addresses.filter(
            alloc_type=IPADDRESS_TYPE.AUTO
        )
        assigned_addresses = [ip for ip in assigned_addresses if ip.ip]
        assert 3 == len(assigned_addresses), (
            "Should have 3 AUTO IP addresses with an IP address assigned."
        )
        assert assigned_addresses == observed

    def test_keeps_ip_address_ids_consistent(self):
        auto_ip_ids = []
        with transaction.atomic():
            interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
            for _ in range(3):
                subnet = factory.make_ipv4_Subnet_with_IPRanges(
                    vlan=interface.vlan
                )
                auto_ip = factory.make_StaticIPAddress(
                    alloc_type=IPADDRESS_TYPE.AUTO,
                    ip="",
                    subnet=subnet,
                    interface=interface,
                )
                auto_ip_ids.append(auto_ip.id)
        with transaction.atomic():
            with post_commit_hooks:
                observed = interface.claim_auto_ips()
        # Should now have 3 AUTO with IP addresses assigned.
        interface = reload_object(interface)
        assigned_addresses = interface.ip_addresses.filter(
            alloc_type=IPADDRESS_TYPE.AUTO
        )
        assigned_addresses = [ip for ip in assigned_addresses if ip.ip]
        assert 3 == len(assigned_addresses), (
            "Should have 3 AUTO IP addresses with an IP address assigned."
        )
        assert assigned_addresses == observed
        # Make sure the IDs didn't change upon allocation.
        assert auto_ip_ids == [ip.id for ip in assigned_addresses]

    def test_claims_all_missing_assigned_auto_ip_addresses(self):
        with transaction.atomic():
            interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
            for _ in range(3):
                subnet = factory.make_Subnet(vlan=interface.vlan)
                ip = factory.pick_ip_in_network(subnet.get_ipnetwork())
                factory.make_StaticIPAddress(
                    alloc_type=IPADDRESS_TYPE.AUTO,
                    ip=ip,
                    subnet=subnet,
                    interface=interface,
                )
            subnet = factory.make_Subnet(vlan=interface.vlan)
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.AUTO,
                ip="",
                subnet=subnet,
                interface=interface,
            )
        with transaction.atomic():
            with post_commit_hooks:
                observed = interface.claim_auto_ips()
        assert 1 == len(observed), (
            "Should have 1 AUTO IP addresses with an IP address assigned."
        )
        assert subnet == observed[0].subnet
        assert (
            IPAddress(observed[0].ip) in observed[0].subnet.get_ipnetwork()
        ), "Assigned IP address should be inside the subnet network."

    def test_claims_ip_address_not_in_dynamic_ip_range(self):
        with transaction.atomic():
            subnet = factory.make_ipv4_Subnet_with_IPRanges()
            interface = factory.make_Interface(
                INTERFACE_TYPE.PHYSICAL, vlan=subnet.vlan
            )
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.AUTO,
                ip="",
                subnet=subnet,
                interface=interface,
            )
        with transaction.atomic():
            with post_commit_hooks:
                observed = interface.claim_auto_ips()
        assert 1 == len(observed), (
            "Should have 1 AUTO IP addresses with an IP address assigned."
        )
        assert subnet == observed[0].subnet
        assert subnet.get_dynamic_range_for_ip(observed[0].ip) is None
        assert subnet.is_valid_static_ip(observed[0].ip)

    def test_claims_ip_address_in_dynamic_ip_range_if_reserved(self):
        with transaction.atomic():
            subnet = factory.make_Subnet(cidr="10.0.0.0/24")
            factory.make_IPRange(
                subnet=subnet,
                start_ip="10.0.0.100",
                end_ip="10.0.0.200",
                alloc_type=IPRANGE_TYPE.RESERVED,
            )
            interface = factory.make_Interface(
                INTERFACE_TYPE.PHYSICAL, vlan=subnet.vlan
            )
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.AUTO,
                ip="",
                subnet=subnet,
                interface=interface,
            )
            reserved_ip = factory.make_ReservedIP(
                subnet=subnet,
                ip="10.0.0.100",
                mac_address=interface.mac_address,
            )
        with transaction.atomic():
            with post_commit_hooks:
                observed = interface.claim_auto_ips()
        assert 1 == len(observed), (
            "Should have 1 AUTO IP addresses with an IP address assigned."
        )
        assert subnet == observed[0].subnet
        assert reserved_ip.ip == observed[0].ip

    def test_claims_ip_address_in_static_ip_range_skips_gateway_ip(self):
        with transaction.atomic():
            interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
            network = factory.make_ipv4_network(slash=30)
            subnet = factory.make_Subnet(
                vlan=interface.vlan, cidr=str(network.cidr)
            )
            # Make it so only one IP is available.
            subnet.gateway_ip = str(IPAddress(network.first))
            subnet.save()
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.AUTO,
                ip="",
                subnet=subnet,
                interface=interface,
            )
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.STICKY,
                ip=str(IPAddress(network.first + 1)),
                subnet=subnet,
                interface=interface,
            )
        with transaction.atomic():
            with post_commit_hooks:
                observed = interface.claim_auto_ips()
        assert 1 == len(observed), (
            "Should have 1 AUTO IP addresses with an IP address assigned."
        )
        assert subnet == observed[0].subnet
        assert IPAddress(network.first + 2) == IPAddress(observed[0].ip)

    def test_claim_fails_if_subnet_missing(self, mocker):
        with transaction.atomic():
            interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
            subnet = factory.make_Subnet(vlan=interface.vlan)
            ip = factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.AUTO,
                ip="",
                subnet=subnet,
                interface=interface,
            )
            ip.subnet = None
            with post_commit_hooks:
                ip.save()
            maaslog = mocker.patch.object(
                interface_module, "maaslog", autospec=True
            )
        with transaction.atomic():
            with pytest.raises(
                StaticIPAddressUnavailable,
                match="Automatic IP address cannot be configured on .* without an associated subnet",
            ):
                interface.claim_auto_ips()
        maaslog.error.assert_called_once_with(
            f"Could not find subnet for interface {interface.get_log_string()}."
        )

    def test_excludes_ip_addresses_in_exclude_addresses(self):
        with transaction.atomic():
            interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
            subnet = factory.make_Subnet(vlan=interface.vlan)
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.AUTO,
                ip="",
                subnet=subnet,
                interface=interface,
            )
            exclude = factory.pick_ip_in_Subnet(subnet)
        with transaction.atomic():
            with post_commit_hooks:
                interface.claim_auto_ips(exclude_addresses={exclude})
            auto_ip = interface.ip_addresses.get(
                alloc_type=IPADDRESS_TYPE.AUTO
            )
        assert IPAddress(exclude) != IPAddress(auto_ip.ip)

    def test_can_acquire_multiple_address_from_the_same_subnet(self):
        with transaction.atomic():
            interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
            subnet = factory.make_ipv4_Subnet_with_IPRanges(
                vlan=interface.vlan
            )
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.AUTO,
                ip="",
                subnet=subnet,
                interface=interface,
            )
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.AUTO,
                ip="",
                subnet=subnet,
                interface=interface,
            )
        with transaction.atomic():
            with post_commit_hooks:
                interface.claim_auto_ips()
            auto_ips = interface.ip_addresses.filter(
                alloc_type=IPADDRESS_TYPE.AUTO
            ).order_by("id")
        assert IPAddress(auto_ips[0].ip) + 1 == IPAddress(auto_ips[1].ip)

    def test_claims_all_auto_ip_addresses_with_temp_expires_on(self):
        with transaction.atomic():
            interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
            for _ in range(3):
                subnet = factory.make_ipv4_Subnet_with_IPRanges(
                    vlan=interface.vlan
                )
                factory.make_StaticIPAddress(
                    alloc_type=IPADDRESS_TYPE.AUTO,
                    ip="",
                    subnet=subnet,
                    interface=interface,
                )
        with transaction.atomic():
            with post_commit_hooks:
                observed = interface.claim_auto_ips(
                    temp_expires_after=datetime.timedelta(minutes=5)
                )
        # Should now have 3 AUTO with IP addresses assigned.
        interface = reload_object(interface)
        assigned_addresses = interface.ip_addresses.filter(
            alloc_type=IPADDRESS_TYPE.AUTO
        )
        assigned_addresses = [
            ip for ip in assigned_addresses if ip.ip and ip.temp_expires_on
        ]
        assert 3 == len(assigned_addresses), (
            "Should have 3 AUTO IP addresses with an IP address assigned "
            "and temp_expires_on set."
        )
        assert sorted(assigned_addresses, key=str) == sorted(observed, key=str)

    def test_claims_with_reserved_ip(self):
        with transaction.atomic():
            interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
            subnet = factory.make_ipv4_Subnet_with_IPRanges(
                vlan=interface.vlan
            )
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.AUTO,
                ip="",
                subnet=subnet,
                interface=interface,
            )
            reserved_ip = factory.make_ReservedIP(
                subnet=subnet,
                ip=factory.pick_ip_in_Subnet(subnet=subnet),
                mac_address=interface.mac_address,
            )

        with transaction.atomic():
            with post_commit_hooks:
                observed = interface.claim_auto_ips(
                    temp_expires_after=datetime.timedelta(minutes=5)
                )
        interface = reload_object(interface)
        assigned_addresses = interface.ip_addresses.filter(
            alloc_type=IPADDRESS_TYPE.AUTO
        )
        assert 1 == len(assigned_addresses), (
            "Should have 3 AUTO IP addresses with an IP address assigned"
        )
        assert reserved_ip.ip == observed[0].ip

    def test_claims_with_reserved_ip_already_in_use(self):
        with transaction.atomic():
            interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
            subnet = factory.make_ipv4_Subnet_with_IPRanges(
                vlan=interface.vlan
            )
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.AUTO,
                ip="",
                subnet=subnet,
                interface=interface,
            )
            reserved_ip = factory.make_ReservedIP(
                subnet=subnet,
                ip=factory.pick_ip_in_Subnet(subnet=subnet),
                mac_address=interface.mac_address,
            )
        with transaction.atomic():
            with pytest.raises(StaticIPAddressUnavailable):
                interface.claim_auto_ips(
                    temp_expires_after=datetime.timedelta(minutes=5),
                    exclude_addresses=[reserved_ip.ip],
                )

    def test_claims_excludes_reserved_ips(self):
        with transaction.atomic():
            subnet = factory.make_Subnet(cidr="192.0.0.0/28")
            interface = factory.make_Interface(
                INTERFACE_TYPE.PHYSICAL, subnet=subnet
            )
            interface2 = factory.make_Interface(
                INTERFACE_TYPE.PHYSICAL, subnet=subnet
            )
            # From 192.0.0.1 to 192.0.0.14
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.AUTO,
                ip="",
                subnet=subnet,
                interface=interface,
            )
            # Reserve 192.0.0.14 for another interface
            factory.make_ReservedIP(
                subnet=subnet,
                ip="192.0.0.14",
                mac_address=interface2.mac_address,
            )
            # Disallow the usage of all the other ips in the subnet
            factory.make_IPRange(
                subnet=subnet,
                alloc_type=IPRANGE_TYPE.RESERVED,
                start_ip="192.0.0.1",
                end_ip="192.0.0.13",
            )
        # claim_auto_ip is not picking 192.0.0.14
        with transaction.atomic():
            with pytest.raises(StaticIPAddressExhaustion):
                interface.claim_auto_ips(
                    temp_expires_after=datetime.timedelta(minutes=5),
                )

    def test_claims_all_auto_ip_addresses_with_reserved_ips(self):
        with transaction.atomic():
            interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
            for _ in range(2):
                subnet = factory.make_ipv4_Subnet_with_IPRanges(
                    vlan=interface.vlan
                )
                factory.make_StaticIPAddress(
                    alloc_type=IPADDRESS_TYPE.AUTO,
                    ip="",
                    subnet=subnet,
                    interface=interface,
                )
            # reserve an ip on the last subnet
            reserved_ip = factory.make_ReservedIP(
                subnet=subnet,
                ip=factory.pick_ip_in_Subnet(subnet=subnet),
                mac_address=interface.mac_address,
            )

        with transaction.atomic():
            with post_commit_hooks:
                observed = interface.claim_auto_ips(
                    temp_expires_after=datetime.timedelta(minutes=5)
                )
        # Should now have 2 AUTO with IP addresses assigned. One of them must be the reserved ip.
        interface = reload_object(interface)
        assigned_addresses = interface.ip_addresses.filter(
            alloc_type=IPADDRESS_TYPE.AUTO
        )
        assigned_addresses = [
            ip for ip in assigned_addresses if ip.ip and ip.temp_expires_on
        ]
        assert 2 == len(assigned_addresses), (
            "Should have 3 AUTO IP addresses with an IP address assigned "
            "and temp_expires_on set."
        )
        assert sorted(assigned_addresses, key=str) == sorted(observed, key=str)
        assert any(
            assigned_address.ip == reserved_ip.ip
            for assigned_address in assigned_addresses
        )

    def test_claims_dhcp_interface_with_reserved_ip(self):
        with transaction.atomic():
            interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
            subnet = factory.make_ipv4_Subnet_with_IPRanges(
                vlan=interface.vlan
            )
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.DHCP,
                ip="",
                subnet=subnet,
                interface=interface,
            )
            factory.make_ReservedIP(
                subnet=subnet,
                ip=factory.pick_ip_in_Subnet(subnet=subnet),
                mac_address=interface.mac_address,
            )

        with transaction.atomic():
            with post_commit_hooks:
                observed = interface.claim_auto_ips(
                    temp_expires_after=datetime.timedelta(minutes=5)
                )
        assert [] == observed

    def test_claims_static_ip_interface_with_reserved_ip(self):
        with transaction.atomic():
            interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
            subnet = factory.make_ipv4_Subnet_with_IPRanges(
                vlan=interface.vlan
            )
            ip = factory.pick_ip_in_Subnet(subnet=subnet)
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.STICKY,
                ip=ip,
                subnet=subnet,
                interface=interface,
            )
            factory.make_ReservedIP(
                subnet=subnet,
                ip=ip,
                mac_address=interface.mac_address,
            )

        with transaction.atomic():
            with post_commit_hooks:
                observed = interface.claim_auto_ips(
                    temp_expires_after=datetime.timedelta(minutes=5)
                )
        assert [] == observed


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestCreateAcquiredBridge:
    """Tests for `Interface.create_acquired_bridge`."""

    def test_raises_ValueError_for_bridge(self):
        bridge = factory.make_Interface(INTERFACE_TYPE.BRIDGE)
        with pytest.raises(ValueError):
            bridge.create_acquired_bridge()

    def test_creates_acquired_bridge_with_default_options(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        bridge = parent.create_acquired_bridge()
        assert bridge.name == parent.get_default_bridge_name()
        assert bridge.mac_address == parent.mac_address
        assert bridge.node_config == parent.node_config
        assert bridge.vlan == parent.vlan
        assert bridge.enabled
        assert bridge.acquired
        assert bridge.params == (
            {
                "bridge_type": BRIDGE_TYPE.STANDARD,
                "bridge_stp": False,
                "bridge_fd": 15,
            }
        )
        assert [parent.id] == [p.id for p in bridge.parents.all()]

    def test_creates_acquired_bridge_with_passed_options(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        bridge_type = factory.pick_choice(BRIDGE_TYPE_CHOICES)
        bridge_stp = factory.pick_bool()
        bridge_fd = random.randint(0, 500)
        bridge = parent.create_acquired_bridge(
            bridge_type=bridge_type, bridge_stp=bridge_stp, bridge_fd=bridge_fd
        )
        assert bridge.name == parent.get_default_bridge_name()
        assert bridge.mac_address == parent.mac_address
        assert bridge.node_config == parent.node_config
        assert bridge.vlan == parent.vlan
        assert bridge.enabled
        assert bridge.acquired
        assert bridge.params == (
            {
                "bridge_type": bridge_type,
                "bridge_stp": bridge_stp,
                "bridge_fd": bridge_fd,
            }
        )
        assert [parent.id] == [p.id for p in bridge.parents.all()]

    def test_creates_acquired_bridge_moves_links_from_parent_to_bridge(self):
        parent = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        auto_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO, interface=parent
        )
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY, interface=parent
        )
        bridge = parent.create_acquired_bridge()
        assert bridge.name == parent.get_default_bridge_name()
        assert bridge.mac_address == parent.mac_address
        assert bridge.node_config == parent.node_config
        assert bridge.vlan == parent.vlan
        assert bridge.enabled
        assert bridge.acquired
        assert bridge.params == (
            {
                "bridge_type": BRIDGE_TYPE.STANDARD,
                "bridge_stp": False,
                "bridge_fd": 15,
            }
        )
        assert [parent.id] == [p.id for p in bridge.parents.all()]
        assert [bridge.id] == [nic.id for nic in auto_ip.interface_set.all()]
        assert [bridge.id] == [nic.id for nic in static_ip.interface_set.all()]


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestReleaseAutoIPs:
    """Tests for `Interface.release_auto_ips`."""

    def test_clears_all_auto_ips_with_ips(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        for _ in range(3):
            subnet = factory.make_Subnet(vlan=interface.vlan)
            ip = factory.pick_ip_in_network(subnet.get_ipnetwork())
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.AUTO,
                ip=ip,
                subnet=subnet,
                interface=interface,
            )

        with post_commit_hooks:
            observed = interface.release_auto_ips()

        # Should now have 3 AUTO with no IP addresses assigned.
        interface = reload_object(interface)
        releases_addresses = interface.ip_addresses.filter(
            alloc_type=IPADDRESS_TYPE.AUTO
        )
        releases_addresses = [rip for rip in releases_addresses if not rip.ip]
        assert 3 == len(releases_addresses), (
            "Should have 3 AUTO IP addresses with no IP address assigned."
        )
        assert sorted(releases_addresses, key=str) == sorted(observed, key=str)

    def test_clears_only_auto_ips_with_ips(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        for _ in range(2):
            subnet = factory.make_Subnet(vlan=interface.vlan)
            factory.make_StaticIPAddress(
                alloc_type=IPADDRESS_TYPE.AUTO,
                ip="",
                subnet=subnet,
                interface=interface,
            )
        subnet = factory.make_Subnet(vlan=interface.vlan)
        ip = factory.pick_ip_in_network(subnet.get_ipnetwork())
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO,
            ip=ip,
            subnet=subnet,
            interface=interface,
        )

        with post_commit_hooks:
            observed = interface.release_auto_ips()

        assert 1 == len(observed), (
            "Should have 1 AUTO IP addresses that was released."
        )
        assert subnet == observed[0].subnet
        assert observed[0].ip is None

    def test_releasing_auto_ips_triggers_dhcp_reload_for_subnet(self, mocker):
        mock_start_workflow = mocker.patch.object(
            staticipaddress_module, "start_workflow"
        )
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        subnet = factory.make_Subnet(vlan=interface.vlan)
        ip = factory.pick_ip_in_network(subnet.get_ipnetwork())
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO,
            ip=ip,
            subnet=subnet,
            interface=interface,
        )

        mock_start_workflow.reset_mock()

        with post_commit_hooks:
            interface.release_auto_ips()

        mock_start_workflow.assert_called_once_with(
            workflow_name=CONFIGURE_DHCP_WORKFLOW_NAME,
            param=ConfigureDHCPParam(subnet_ids=[subnet.id]),
            task_queue="region",
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestInterfaceUpdateDiscovery:
    """Tests for `Interface.update_discovery_state`.

    Note: these tests make extensive use of reload_object() to help ensure that
    the update_fields=[...] parameter to save() is correct.
    """

    def test_monitored_flag_vetoes_discovery_state(self):
        iface = factory.make_Interface()
        iface.update_discovery_state(
            NetworkDiscoveryConfig(passive=True, active=False),
            monitored=False,
        )
        iface = reload_object(iface)
        assert not iface.neighbour_discovery_state

    def test_sets_neighbour_state_true_when_monitored_flag_is_true(self):
        iface = factory.make_Interface()
        iface.update_discovery_state(
            NetworkDiscoveryConfig(passive=True, active=False),
            monitored=True,
        )
        iface = reload_object(iface)
        assert iface.neighbour_discovery_state

    def test_sets_mdns_state_based_on_passive_setting(self):
        iface = factory.make_Interface()
        iface.update_discovery_state(
            NetworkDiscoveryConfig(passive=False, active=False),
            monitored=False,
        )
        iface = reload_object(iface)
        assert not iface.mdns_discovery_state
        iface.update_discovery_state(
            NetworkDiscoveryConfig(passive=True, active=False),
            monitored=False,
        )
        iface = reload_object(iface)
        assert iface.mdns_discovery_state


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestInterfaceGetDiscoveryState:
    def test_reports_correct_parameters(self):
        iface = factory.make_Interface()
        iface.neighbour_discovery_state = random.choice([True, False])
        iface.mdns_discovery_state = random.choice([True, False])
        state = iface.get_discovery_state()
        assert iface.neighbour_discovery_state == state["neighbour"]
        assert iface.mdns_discovery_state == state["mdns"]


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestReportVID:
    def test_creates_vlan_if_necessary(self):
        fabric = factory.make_Fabric()
        vlan = fabric.get_default_vlan()
        iface = factory.make_Interface(vlan=vlan)
        vid = random.randint(1, 4094)
        ip = factory.make_ip_address()
        vlan_before = get_one(VLAN.objects.filter(fabric=fabric, vid=vid))
        assert vlan_before is None
        iface.report_vid(vid, ip=ip)
        vlan_after = get_one(VLAN.objects.filter(fabric=fabric, vid=vid))
        assert vlan_after is not None
        # Report it one more time to make sure we can handle it if we already
        # observed it. (expect nothing to happen.)
        iface.report_vid(vid, ip=ip)

    def test_logs_vlan_creation_and_sets_description(self):
        fabric = factory.make_Fabric()
        vlan = fabric.get_default_vlan()
        iface = factory.make_Interface(vlan=vlan)
        vid = random.randint(1, 4094)
        with FakeLogger("maas.interface") as maaslog:
            iface.report_vid(vid)
        assert f": Automatically created VLAN {vid}" in maaslog.output
        new_vlan = get_one(VLAN.objects.filter(fabric=fabric, vid=vid))
        assert (
            f"Automatically created VLAN (observed by {iface.get_log_string()})."
            in new_vlan.description
        )

    def test_report_vid_does_not_modify_existing_vlan(self):
        fabric1 = factory.make_Fabric()
        fabric2 = factory.make_Fabric()
        observing_vlan = fabric1.get_default_vlan()
        neighbour_vlan = factory.make_VLAN(fabric=fabric2)
        subnet1 = factory.make_Subnet(vlan=observing_vlan)
        subnet2 = factory.make_Subnet(vlan=neighbour_vlan)
        iface = factory.make_Interface(subnet=subnet1)
        iface.report_vid(
            neighbour_vlan.vid, ip=subnet2.get_next_ip_for_allocation()[0]
        )
        neighbour_vlan.refresh_from_db()
        assert observing_vlan.fabric == fabric1


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestInterfaceGetDefaultBridgeName:
    # Normally we would use scenarios for this, but this was copied and
    # pasted from Juju code in bridgepolicy_test.go.
    expected_bridge_names = {
        "eno0": "br-eno0",
        "twelvechars0": "br-twelvechars0",
        "thirteenchars": "b-thirteenchars",
        "enfourteenchar": "b-fourteenchar",
        "enfifteenchars0": "b-fifteenchars0",
        "fourteenchars1": "b-5590a4-chars1",
        "fifteenchars.12": "b-7e0acf-ars.12",
        "zeros0526193032": "b-000000-193032",
        "enx00e07cc81e1d": "b-x00e07cc81e1d",
    }

    def test_returns_expected_bridge_names_consistent_with_juju(self):
        interface = factory.make_Interface()
        for ifname, expected_bridge_name in self.expected_bridge_names.items():
            interface.name = ifname
            assert expected_bridge_name == interface.get_default_bridge_name()
