# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maasserver.ntp`."""

from netaddr import IPSet
import pytest

from maasserver.models.config import Config
from maasserver.ntp import get_peers_for, get_servers_for
from maasserver.testing.factory import factory
from maasserver.utils.orm import post_commit_hooks


def populate_node_with_addresses(node, subnets):
    iface = factory.make_Interface(node=node)
    for subnet in subnets:
        factory.make_StaticIPAddress(interface=iface, subnet=subnet)


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestGetServersFor_ExternalOnly:
    """Tests `get_servers_for` when `ntp_external_only` is set."""

    @pytest.fixture(autouse=True)
    def _set_external_only(self, maasdb):
        Config.objects.set_config("ntp_external_only", True)

    @pytest.mark.parametrize(
        "make_node",
        [
            factory.make_RegionController,
            factory.make_RegionRackController,
            factory.make_RackController,
            factory.make_Machine,
            factory.make_Device,
        ],
        ids=["region", "region+rack", "rack", "machine", "device"],
    )
    def test_yields_nothing_when_no_ntp_servers_defined(self, make_node):
        Config.objects.set_config("ntp_servers", "")
        servers = get_servers_for(node=make_node())
        assert servers == set()

    @pytest.mark.parametrize(
        "make_node",
        [
            factory.make_RegionController,
            factory.make_RegionRackController,
            factory.make_RackController,
            factory.make_Machine,
            factory.make_Device,
        ],
        ids=["region", "region+rack", "rack", "machine", "device"],
    )
    def test_yields_all_ntp_servers_when_defined(self, make_node):
        ntp_servers = factory.make_hostname(), factory.make_hostname()
        Config.objects.set_config("ntp_servers", " ".join(ntp_servers))
        servers = get_servers_for(node=make_node())
        assert servers == set(ntp_servers)


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestGetServersFor_Common:
    """Common basis for tests of `get_servers_for`.

    This ensures that `ntp_external_only` is NOT set.
    """

    @pytest.fixture(autouse=True)
    def _set_external_only(self, maasdb):
        Config.objects.set_config("ntp_external_only", False)


class TestGetServersFor_Region_RegionRack_None(TestGetServersFor_Common):
    """Tests `get_servers_for` for `RegionController` nodes.

    Also test for `None`, i.e. where there is no node.
    """

    @pytest.mark.parametrize(
        "make_node",
        [
            factory.make_RegionController,
            factory.make_RegionRackController,
            lambda: None,
        ],
        ids=["region", "region+rack", "none"],
    )
    def test_yields_nothing_when_no_ntp_servers_defined(self, make_node):
        Config.objects.set_config("ntp_servers", "")
        servers = get_servers_for(node=make_node())
        assert servers == set()

    @pytest.mark.parametrize(
        "make_node",
        [
            factory.make_RegionController,
            factory.make_RegionRackController,
            lambda: None,
        ],
        ids=["region", "region+rack", "none"],
    )
    def test_yields_all_ntp_servers_when_defined(self, make_node):
        ntp_servers = factory.make_hostname(), factory.make_hostname()
        Config.objects.set_config("ntp_servers", " ".join(ntp_servers))
        servers = get_servers_for(node=make_node())
        assert servers == set(ntp_servers)


class TestGetServersFor_Rack(TestGetServersFor_Common):
    """Tests `get_servers_for` for `RackController` nodes."""

    def test_yields_region_addresses(self):
        rack = factory.make_RackController()
        address = factory.make_StaticIPAddress(
            interface=factory.make_Interface(node=rack)
        )

        region1 = factory.make_RegionController()
        region1_address = factory.make_StaticIPAddress(
            interface=factory.make_Interface(node=region1),
            subnet=address.subnet,
        )

        region2 = factory.make_RegionController()
        region2_address = factory.make_StaticIPAddress(
            interface=factory.make_Interface(node=region2),
            subnet=address.subnet,
        )

        servers = get_servers_for(rack)
        assert servers == {region1_address.ip, region2_address.ip}


class TestGetServersFor_Machine(TestGetServersFor_Common):
    """Tests `get_servers_for` for `Machine` nodes."""

    def test_yields_rack_addresses_before_first_boot(self):
        machine = factory.make_Machine()
        machine.boot_cluster_ip = None
        machine.save()
        address = factory.make_StaticIPAddress(
            interface=factory.make_Interface(node=machine)
        )

        rack1 = factory.make_RackController()
        rack1_address = factory.make_StaticIPAddress(
            interface=factory.make_Interface(node=rack1), subnet=address.subnet
        )

        rack2 = factory.make_RackController()
        rack2_address = factory.make_StaticIPAddress(
            interface=factory.make_Interface(node=rack2), subnet=address.subnet
        )

        servers = get_servers_for(machine)
        assert servers == {rack1_address.ip, rack2_address.ip}

    def test_yields_boot_rack_addresses_when_machine_has_booted(self):
        machine = factory.make_Machine()
        address = factory.make_StaticIPAddress(
            interface=factory.make_Interface(node=machine)
        )

        rack_primary = factory.make_RackController()
        rack_primary_address = factory.make_StaticIPAddress(
            interface=factory.make_Interface(node=rack_primary),
            subnet=address.subnet,
        )

        rack_secondary = factory.make_RackController()
        rack_secondary_address = factory.make_StaticIPAddress(
            interface=factory.make_Interface(node=rack_secondary),
            subnet=address.subnet,
        )

        rack_other = factory.make_RackController()
        factory.make_StaticIPAddress(  # noqa
            interface=factory.make_Interface(node=rack_other),
            subnet=address.subnet,
        )

        vlan = address.subnet.vlan
        vlan.primary_rack = rack_primary
        vlan.secondary_rack = rack_secondary
        vlan.dhcp_on = True

        with post_commit_hooks:
            vlan.save()

        servers = get_servers_for(machine)
        assert servers == {
            rack_primary_address.ip,
            rack_secondary_address.ip,
        }


class TestGetServersFor_Device(TestGetServersFor_Common):
    """Tests `get_servers_for` for `Device` nodes."""

    def test_yields_rack_addresses(self):
        device = factory.make_Device()
        address = factory.make_StaticIPAddress(
            interface=factory.make_Interface(node=device)
        )

        rack1 = factory.make_RackController()
        rack1_address = factory.make_StaticIPAddress(
            interface=factory.make_Interface(node=rack1), subnet=address.subnet
        )

        rack2 = factory.make_RackController()
        rack2_address = factory.make_StaticIPAddress(
            interface=factory.make_Interface(node=rack2), subnet=address.subnet
        )

        servers = get_servers_for(device)
        assert servers == {rack1_address.ip, rack2_address.ip}


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestGetServersFor_Selection:
    """Tests the address selection mechanism for `get_servers_for`.

    For racks, machines, and devices, a selection process takes place to
    determine which of several candidate addresses per server to choose. This
    result is semi-stable, i.e. it will always prefer "closer" addresses.
    """

    @pytest.fixture(autouse=True)
    def _set_external_only(self, maasdb):
        Config.objects.set_config("ntp_external_only", False)

    @pytest.mark.parametrize(
        "make_node,make_server",
        [
            (factory.make_RackController, factory.make_RegionController),
            (factory.make_Machine, factory.make_RackController),
            (factory.make_Device, factory.make_RackController),
        ],
        ids=["rack", "machine", "device"],
    )
    def test_prefers_closest_addresses(self, make_node, make_server):
        subnet4 = factory.make_Subnet(version=4)
        subnet6 = factory.make_Subnet(version=6)
        # Separate subnets but sharing the VLAN, hence routable.
        subnet4v = factory.make_Subnet(version=4, vlan=subnet4.vlan)
        subnet6v = factory.make_Subnet(version=6, vlan=subnet6.vlan)

        # Create a node with an address in the first two subnets...
        node = make_node()
        populate_node_with_addresses(node, {subnet4, subnet6})
        # ... and a server with an address in every subnet.
        server = make_server()
        populate_node_with_addresses(
            server, {subnet4, subnet6, subnet4v, subnet6v}
        )

        # The NTP server addresses chosen will be those that are "closest" to
        # the node, and same-subnet wins in this over same-VLAN. No additional
        # preference is made between IPv4 or IPv6, hence we allow for either.
        preferred_subnets = subnet4, subnet6
        preferred_networks = IPSet(
            subnet.get_ipnetwork() for subnet in preferred_subnets
        )

        servers = get_servers_for(node)
        assert len(servers) != 0
        for server in servers:
            assert server in preferred_networks


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestGetPeersFor_Region_RegionRack:
    """Tests `get_peers_for` for region and region+rack controllers."""

    @pytest.fixture(autouse=True)
    def _set_external_only(self, maasdb):
        Config.objects.set_config("ntp_external_only", False)

    @pytest.mark.parametrize(
        "make_node",
        [factory.make_RegionController, factory.make_RegionRackController],
        ids=["region", "region+rack"],
    )
    def test_yields_peer_addresses(self, make_node):
        node1 = make_node()
        node1_address = factory.make_StaticIPAddress(
            interface=factory.make_Interface(node=node1)
        )
        node2 = make_node()
        node2_address = factory.make_StaticIPAddress(
            interface=factory.make_Interface(node=node2),
            subnet=node1_address.subnet,
        )

        assert get_peers_for(node1) == {node2_address.ip}
        assert get_peers_for(node2) == {node1_address.ip}

    @pytest.mark.parametrize(
        "make_node",
        [factory.make_RegionController, factory.make_RegionRackController],
        ids=["region", "region+rack"],
    )
    def test_prefers_closest_addresses(self, make_node):
        subnet4 = factory.make_Subnet(version=4)
        subnet6 = factory.make_Subnet(version=6)
        # Separate subnets but sharing the VLAN, hence routable.
        subnet4v1 = factory.make_Subnet(version=4, vlan=subnet4.vlan)
        subnet6v1 = factory.make_Subnet(version=6, vlan=subnet6.vlan)
        subnet4v2 = factory.make_Subnet(version=4, vlan=subnet4.vlan)
        subnet6v2 = factory.make_Subnet(version=6, vlan=subnet6.vlan)

        # Create a node with an address in the first two subnets and the first
        # two same-VLAN subnets.
        node1 = make_node()
        populate_node_with_addresses(
            node1, {subnet4, subnet6, subnet4v1, subnet6v1}
        )
        # Create a node with an address in the first two subnets and the
        # second two same-VLAN subnets.
        node2 = make_node()
        populate_node_with_addresses(
            node2, {subnet4, subnet6, subnet4v2, subnet6v2}
        )

        # The NTP server addresses chosen will be those that are "closest" to
        # the node, and same-subnet wins in this over same-VLAN. No additional
        # preference is made between IPv4 or IPv6, hence we allow for either.
        preferred_subnets = subnet4, subnet6
        preferred_networks = IPSet(
            subnet.get_ipnetwork() for subnet in preferred_subnets
        )

        for node in (node1, node2):
            peers = get_peers_for(node)
            assert len(peers) != 0
            for peer in peers:
                assert peer in preferred_networks


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestGetPeersFor_Other:
    """Tests `get_peers_for` for other node types."""

    @pytest.fixture(autouse=True)
    def _set_external_only(self, maasdb):
        Config.objects.set_config("ntp_external_only", False)

    @pytest.mark.parametrize(
        "make_node",
        [
            factory.make_RackController,
            factory.make_Machine,
            factory.make_Device,
        ],
        ids=["rack", "machine", "device"],
    )
    def test_yields_nothing(self, make_node):
        node1 = make_node()
        node1_address = factory.make_StaticIPAddress(
            interface=factory.make_Interface(node=node1)
        )
        node2 = make_node()
        factory.make_StaticIPAddress(  # noqa
            interface=factory.make_Interface(node=node2),
            subnet=node1_address.subnet,
        )

        assert get_peers_for(node1) == set()
        assert get_peers_for(node2) == set()


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestGetPeersFor_None:
    """Tests `get_peers_for` for `None`, i.e. where there is no node."""

    @pytest.fixture(autouse=True)
    def _set_external_only(self, maasdb):
        Config.objects.set_config("ntp_external_only", False)

    def test_yields_nothing(self):
        assert get_peers_for(None) == set()
