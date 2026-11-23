# Copyright 2016-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


from collections import Counter
import random
from unittest.mock import Mock

import pytest

from maasserver.enum import INTERFACE_TYPE, IPADDRESS_TYPE
from maasserver.models import bmc as bmc_module
from maasserver.models.bmc import BMC, BMCRoutableRackControllerRelationship
from maasserver.models.staticipaddress import StaticIPAddress
from maasserver.secrets import SecretManager
from maasserver.testing.factory import factory
from maasserver.utils.orm import post_commit_hooks, reload_object
from maastesting.crochet import wait_for

wait_for_reactor = wait_for()
UNDEFINED = object()


@pytest.mark.usefixtures("maasdb", "maas_region_test")
class TestBMC:
    def get_machine_ip_address(self, machine):
        return machine.current_config.interface_set.all()[
            0
        ].ip_addresses.all()[0]

    def make_machine_and_bmc_with_shared_ip(self):
        machine = factory.make_Node(interface=False)
        machine.current_config.interface_set.clear()
        vlan = factory.make_VLAN()
        subnet = factory.make_Subnet(vlan=vlan)
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, vlan=vlan, node=machine
        )
        machine_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            subnet=subnet,
            interface=interface,
        )
        assert 1 == machine.current_config.interface_set.count()

        bmc = factory.make_BMC(
            power_type="virsh",
            power_parameters={
                "power_address": "protocol://%s:8080/path/to/thing#tag"
                % (factory.ip_to_url_format(machine_ip.ip))
            },
        )
        # Make sure they're sharing an IP.
        machine = reload_object(machine)
        machine_ip_addr = self.get_machine_ip_address(machine)
        assert machine_ip_addr.id == bmc.ip_address.id
        return machine, bmc, machine_ip

    def make_machine_and_bmc_differing_ips(self):
        machine = factory.make_Node(interface=False)
        machine.current_config.interface_set.clear()
        vlan = factory.make_VLAN()
        subnet = factory.make_Subnet(vlan=vlan)
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, vlan=vlan, node=machine
        )
        machine_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            subnet=subnet,
            interface=interface,
        )
        assert 1 == machine.current_config.interface_set.count()

        ip_address = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY, subnet=subnet
        )
        bmc_ip = ip_address.ip
        with post_commit_hooks:
            ip_address.delete()
        bmc = factory.make_BMC(
            power_type="virsh",
            power_parameters={
                "power_address": "protocol://%s:8080/path/to/thing#tag"
                % (factory.ip_to_url_format(bmc_ip))
            },
        )
        # Make sure they're not sharing an IP.
        machine = reload_object(machine)
        machine_ip_addr = self.get_machine_ip_address(machine)
        assert machine_ip_addr.id != bmc.ip_address.id
        return machine, bmc, machine_ip

    def test_make_machine_and_bmc_discovered_ip(self):
        # Regression test for LP:1816651
        subnet = factory.make_Subnet()
        discovered_ip = factory.make_StaticIPAddress(
            subnet=subnet, alloc_type=IPADDRESS_TYPE.DISCOVERED
        )
        sticky_ip = factory.make_StaticIPAddress(
            ip=discovered_ip.ip,
            subnet=subnet,
            alloc_type=IPADDRESS_TYPE.STICKY,
        )
        bmc = factory.make_BMC(
            power_type="virsh",
            power_parameters={
                "power_address": "protocol://%s:8080/path/to/thing#tag"
                % (factory.ip_to_url_format(discovered_ip.ip))
            },
        )
        assert Counter([discovered_ip, sticky_ip]) == Counter(
            StaticIPAddress.objects.filter(ip=discovered_ip.ip)
        )
        assert sticky_ip == bmc.ip_address

    def test_bmc_save_extracts_ip_address(self):
        subnet = factory.make_Subnet()
        sticky_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY, subnet=subnet
        )
        power_parameters = {
            "power_address": "protocol://%s:8080/path/to/thing#tag"
            % (factory.ip_to_url_format(sticky_ip.ip))
        }
        bmc = factory.make_BMC(
            power_type="virsh", power_parameters=power_parameters
        )
        assert sticky_ip.ip == bmc.ip_address.ip
        assert subnet == bmc.ip_address.subnet

    def test_bmc_save_accepts_naked_ipv6_address(self):
        subnet = factory.make_Subnet(cidr=factory.make_ipv6_network())
        sticky_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY, subnet=subnet
        )
        power_parameters = {"power_address": "%s" % sticky_ip.ip}
        bmc = factory.make_BMC(
            power_type="ipmi", power_parameters=power_parameters
        )
        assert sticky_ip.ip == bmc.ip_address.ip
        assert subnet == bmc.ip_address.subnet

    def test_bmc_save_accepts_bracketed_ipv6_address(self):
        subnet = factory.make_Subnet(cidr=factory.make_ipv6_network())
        sticky_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY, subnet=subnet
        )
        power_parameters = {"power_address": "[%s]" % sticky_ip.ip}
        bmc = factory.make_BMC(
            power_type="ipmi", power_parameters=power_parameters
        )
        assert sticky_ip.ip == bmc.ip_address.ip
        assert subnet == bmc.ip_address.subnet

    def test_bmc_changing_power_parameters_changes_ip(self):
        ip = factory.make_ipv4_address()
        power_parameters = {
            "power_address": "protocol://%s:8080/path#tag"
            % factory.ip_to_url_format(ip)
        }
        bmc = factory.make_BMC(
            power_type="virsh", power_parameters=power_parameters
        )
        assert ip == bmc.ip_address.ip
        assert bmc.ip_address.subnet is None

        subnet = factory.make_Subnet()
        sticky_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY, subnet=subnet
        )
        bmc.set_power_parameters(
            {
                "power_address": "protocol://%s:8080/path/to/thing#tag"
                % (factory.ip_to_url_format(sticky_ip.ip))
            }
        )
        bmc.save()
        assert sticky_ip.ip == bmc.ip_address.ip
        assert subnet == bmc.ip_address.subnet

    def test_bmc_changing_power_parameters_ipmi_errors_if_invalid(self):
        ip = factory.make_ipv4_address()
        power_parameters = {
            "power_address": "protocol://%s" % factory.ip_to_url_format(ip)
        }
        with pytest.raises(
            ValueError, match="does not support netmasks or subnet prefixes!"
        ):
            factory.make_BMC(
                power_type="ipmi", power_parameters=power_parameters
            )

    def test_deleting_machine_ip_when_shared_with_bmc(self):
        machine, bmc, machine_ip = self.make_machine_and_bmc_with_shared_ip()

        # Now delete the machine.
        old_ip = machine_ip.ip
        with post_commit_hooks:
            machine.delete()

        # Check BMC still has old IP.
        bmc = reload_object(bmc)
        assert bmc.ip_address is not None
        assert old_ip == bmc.ip_address.ip

        # Make sure DB ID's of StaticIPAddress instances differ.
        assert machine_ip.id != bmc.ip_address.id

    def test_removing_bmc_ip_when_shared_with_bmc(self):
        machine, bmc, machine_ip = self.make_machine_and_bmc_with_shared_ip()

        # Clear the BMC IP.
        old_ip = bmc.ip_address.ip
        bmc.power_type = "manual"
        bmc.save()
        assert bmc.ip_address is None

        # Check Machine still has same IP address.
        machine = reload_object(machine)
        machine_ip_addr = self.get_machine_ip_address(machine)
        assert old_ip == machine_ip_addr.ip
        assert machine_ip.id == machine_ip_addr.id

    def test_changing_machine_ip_when_shared_with_bmc_keeps_both(self):
        machine, bmc, machine_ip = self.make_machine_and_bmc_with_shared_ip()

        # Now change the Machine's IP to a new address on same subnet.
        old_ip = machine_ip.ip
        new_ip_address = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY, subnet=machine_ip.subnet
        )
        new_ip = new_ip_address.ip
        # Remove IP so we can set machine_ip to its address.
        with post_commit_hooks:
            new_ip_address.delete()
        assert new_ip != old_ip
        machine_ip.ip = new_ip

        with post_commit_hooks:
            machine_ip.save()

        # Check Machine has new IP address but kept same instance: machine_ip.
        machine = reload_object(machine)
        machine_ip_addr = self.get_machine_ip_address(machine)
        assert new_ip == machine_ip_addr.ip
        assert machine_ip.id == machine_ip_addr.id

        # Check BMC still has old IP.
        bmc = reload_object(bmc)
        assert old_ip == bmc.ip_address.ip

        # Make sure DB ID's of StaticIPAddress instances differ.
        assert machine_ip_addr.id != bmc.ip_address.id

    def test_changing_bmc_ip_when_shared_with_machine_keeps_both(self):
        machine, bmc, machine_ip = self.make_machine_and_bmc_with_shared_ip()

        # Now change the BMC's IP to a new address on same subnet.
        old_ip = machine_ip.ip
        new_ip_address = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY, subnet=machine_ip.subnet
        )
        new_ip = new_ip_address.ip

        with post_commit_hooks:
            # Remove IP so we can set machine_ip to its address.
            new_ip_address.delete()
        assert new_ip != old_ip

        with post_commit_hooks:
            bmc.set_power_parameters(
                {
                    "power_address": "protocol://%s:8080/path/to/thing#tag"
                    % (factory.ip_to_url_format(new_ip))
                }
            )
            bmc.save()

        # Check Machine has old IP address and kept same instance: machine_ip.
        machine = reload_object(machine)
        machine_ip_addr = self.get_machine_ip_address(machine)
        assert old_ip == machine_ip_addr.ip
        assert machine_ip.id == machine_ip_addr.id

        # Check BMC has new IP.
        bmc = reload_object(bmc)
        assert new_ip == bmc.ip_address.ip

        # Make sure DB ID's of StaticIPAddress instances differ.
        assert machine_ip_addr.id != bmc.ip_address.id

    def test_bmc_existing_ip_links_to_it(self):
        ip = factory.make_StaticIPAddress(ip="10.10.10.10")
        bmc = factory.make_BMC(
            power_type="virsh",
            power_parameters={
                "power_address": f"virsh://{ip.ip}/path/to/thing#tag"
            },
        )
        assert bmc.ip_address.id == ip.id

    def test_merging_bmc_into_machine_ip(self):
        machine, bmc, machine_ip = self.make_machine_and_bmc_differing_ips()

        # Now change the BMC's address to match machine's.
        bmc.set_power_parameters(
            {
                "power_address": "protocol://%s:8080/path/to/thing#tag"
                % (factory.ip_to_url_format(machine_ip.ip))
            }
        )
        with post_commit_hooks:
            bmc.save()

        # Make sure BMC and Machine are using same StaticIPAddress instance.
        machine = reload_object(machine)
        machine_ip_addr = self.get_machine_ip_address(machine)
        assert machine_ip_addr.id == bmc.ip_address.id

    def test_delete_bmc_deletes_orphaned_ip_address(self):
        bmc = factory.make_BMC(
            power_type="virsh",
            power_parameters={
                "power_address": "protocol://%s:8080/path/to/thing#tag"
                % (factory.make_ipv4_address())
            },
        )
        ip = bmc.ip_address
        with post_commit_hooks:
            bmc.delete()
        assert 0 == StaticIPAddress.objects.filter(id=ip.id).count()

    def test_delete_deletes_bmc_secrets(self):
        bmc = factory.make_BMC()
        secret_manager = SecretManager()
        secret_manager.set_composite_secret(
            "power-parameters", {"foo": "bar"}, obj=bmc
        )

        with post_commit_hooks:
            bmc.delete()
        assert (
            secret_manager.get_simple_secret(
                "power-parameters", obj=bmc, default=None
            )
            is None
        )

    def test_delete_bmc_spares_non_orphaned_ip_address(self):
        machine, bmc, machine_ip = self.make_machine_and_bmc_with_shared_ip()
        bmc.delete()
        assert 1 == StaticIPAddress.objects.filter(id=machine_ip.id).count()

    def test_scope_power_parameters(self):
        bmc_parameters = dict(
            power_address=factory.make_string(),
            power_pass=factory.make_string(),
        )
        node_parameters = dict(
            power_vm_name=factory.make_string(),
            power_uuid=factory.make_string(),
        )
        parameters = {**bmc_parameters, **node_parameters}
        result = BMC.scope_power_parameters("vmware", parameters)
        assert result[0]
        assert bmc_parameters == result[1]
        assert node_parameters == result[2]

    def test_scope_power_parameters_unknown_parameter(self):
        bmc_parameters = dict(power_address=factory.make_string())
        node_parameters = dict(server_name=factory.make_string())
        # This random parameter should be stored on the node instance.
        node_parameters[factory.make_string()] = factory.make_string()
        parameters = {**bmc_parameters, **node_parameters}
        result = BMC.scope_power_parameters("hmc", parameters)
        assert result[0]
        assert bmc_parameters == result[1]
        assert node_parameters == result[2]

    def test_bmc_extract_ip_address_whole_value(self):
        power_parameters = {"power_address": "192.168.1.1"}
        assert "192.168.1.1" == BMC.extract_ip_address("hmc", power_parameters)

    def test_bmc_extract_ip_address_empty_power_type_gives_none(self):
        power_parameters = {"power_address": "192.168.1.1"}
        assert BMC.extract_ip_address("", power_parameters) is None
        assert BMC.extract_ip_address(None, power_parameters) is None

    def test_bmc_extract_ip_address_blank_gives_none(self):
        assert BMC.extract_ip_address("hmc", None) is None
        assert BMC.extract_ip_address("hmc", {}) is None

        power_parameters = {"power_address": ""}
        assert BMC.extract_ip_address("hmc", power_parameters) is None

        power_parameters = {"power_address": None}
        assert BMC.extract_ip_address("hmc", power_parameters) is None

    def test_bmc_extract_ip_address_from_url_blank_gives_none(self):
        assert BMC.extract_ip_address("virsh", None) is None
        assert BMC.extract_ip_address("virsh", {}) is None

        power_parameters = {"power_address": ""}
        assert BMC.extract_ip_address("virsh", power_parameters) is None

        power_parameters = {"power_address": None}
        assert BMC.extract_ip_address("virsh", power_parameters) is None

    def test_bmc_extract_ip_address_from_url_empty_host(self):
        power_parameters = {"power_address": "http://:8080/foo/#baz"}
        assert "" == BMC.extract_ip_address("virsh", power_parameters)

    def test_bmc_extract_ip_address_with_fqdn_returns_none(self):
        assert (
            BMC.extract_ip_address(
                "webhook", {"power_address": factory.make_url()}
            )
            is None
        )

    def test_get_usable_rack_controllers_returns_empty_when_none(self):
        bmc = factory.make_BMC()
        assert bmc.get_usable_rack_controllers() == []

    def test_get_usable_rack_controllers_returns_routable_racks(self):
        bmc = factory.make_BMC()
        routable_racks = [factory.make_RackController() for _ in range(3)]
        not_routable_racks = [factory.make_RackController() for _ in range(3)]
        for rack in routable_racks:
            BMCRoutableRackControllerRelationship(
                bmc=bmc, rack_controller=rack, routable=True
            ).save()
        for rack in not_routable_racks:
            BMCRoutableRackControllerRelationship(
                bmc=bmc, rack_controller=rack, routable=False
            ).save()
        assert Counter(routable_racks) == Counter(
            bmc.get_usable_rack_controllers(with_connection=False)
        )

    def test_get_usable_rack_controllers_returns_routable_racks_conn(
        self, mocker
    ):
        bmc = factory.make_BMC()
        routable_racks = [factory.make_RackController() for _ in range(3)]
        not_routable_racks = [factory.make_RackController() for _ in range(3)]
        for rack in routable_racks:
            BMCRoutableRackControllerRelationship(
                bmc=bmc, rack_controller=rack, routable=True
            ).save()
        for rack in not_routable_racks:
            BMCRoutableRackControllerRelationship(
                bmc=bmc, rack_controller=rack, routable=False
            ).save()
        connected_rack = random.choice(routable_racks)
        client = Mock()
        client.ident = connected_rack.system_id
        mocker.patch.object(bmc_module, "getAllClients", return_value=[client])
        assert [connected_rack] == bmc.get_usable_rack_controllers(
            with_connection=True
        )

    def test_get_usable_rack_controllers_updates_subnet_on_sip(self):
        network = factory.make_ipv4_network()
        subnet = factory.make_Subnet(cidr=str(network.cidr))
        ip = factory.pick_ip_in_Subnet(subnet)
        sip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY, ip=ip, subnet=subnet
        )
        sip.subnet = None
        with post_commit_hooks:
            sip.save()
        bmc = factory.make_BMC(
            power_type="virsh",
            power_parameters={
                "power_address": "qemu+ssh://user@%s/system" % ip
            },
            ip_address=sip,
        )
        bmc.get_usable_rack_controllers()
        assert subnet == reload_object(sip).subnet

    def test_get_usable_rack_controllers_updates_handles_unknown_subnet(self):
        network = factory.make_ipv4_network()
        ip = factory.pick_ip_in_network(network)
        with post_commit_hooks:
            sip = StaticIPAddress.objects.create(
                alloc_type=IPADDRESS_TYPE.STICKY, ip=ip
            )
        bmc = factory.make_BMC(
            power_type="virsh",
            power_parameters={
                "power_address": "qemu+ssh://user@%s/system" % ip
            },
            ip_address=sip,
        )
        bmc.get_usable_rack_controllers()
        assert reload_object(sip).subnet is None

    def test_get_usable_rack_controllers_returns_rack_controllers(self):
        rack_controller = factory.make_RackController()
        machine = factory.make_Node(bmc_connected_to=rack_controller)
        assert [rack_controller] == machine.bmc.get_usable_rack_controllers(
            with_connection=False
        )

    def test_get_client_identifiers_returns_rack_controller_system_ids(
        self, mocker
    ):
        rack_controllers = [factory.make_RackController() for _ in range(3)]
        bmc = factory.make_BMC()
        mocker.patch.object(
            bmc, "get_usable_rack_controllers", return_value=rack_controllers
        )
        expected_system_ids = [rack.system_id for rack in rack_controllers]
        assert expected_system_ids == bmc.get_client_identifiers()

    def test_is_accessible_calls_get_usable_rack_controllers(self, mocker):
        bmc = factory.make_BMC()
        mock_get_usable_rack_controllers = mocker.patch.object(
            bmc, "get_usable_rack_controllers"
        )
        bmc.is_accessible()
        mock_get_usable_rack_controllers.assert_called_once_with(
            with_connection=True
        )

    def test_is_accessible_returns_true(self, mocker):
        bmc = factory.make_BMC()
        mock_get_usable_rack_controllers = mocker.patch.object(
            bmc, "get_usable_rack_controllers"
        )
        mock_get_usable_rack_controllers.return_value = [
            factory.make_RackController()
        ]
        assert bmc.is_accessible()

    def test_is_accessible_returns_false(self, mocker):
        bmc = factory.make_BMC()
        mock_get_usable_rack_controllers = mocker.patch.object(
            bmc, "get_usable_rack_controllers"
        )
        mock_get_usable_rack_controllers.return_value = []
        assert not bmc.is_accessible()

    def test_update_routable_racks_updates_rack_relationship(self):
        node = factory.make_Node(power_type="virsh")

        # Create old relationships that should be removed.
        old_relationship_ids = [
            BMCRoutableRackControllerRelationship.objects.create(
                bmc=node.bmc,
                rack_controller=factory.make_RackController(),
                routable=True,
            ).id
            for _ in range(3)
        ]

        routable_racks = [factory.make_RackController() for _ in range(3)]
        non_routable_racks = [factory.make_RackController() for _ in range(3)]

        node.bmc.update_routable_racks(
            [rack.system_id for rack in routable_racks],
            [rack.system_id for rack in non_routable_racks],
        )

        assert not BMCRoutableRackControllerRelationship.objects.filter(
            id__in=old_relationship_ids
        ).exists()
        assert BMCRoutableRackControllerRelationship.objects.filter(
            rack_controller__in=routable_racks, routable=True
        ).count() == len(routable_racks)
        assert BMCRoutableRackControllerRelationship.objects.filter(
            rack_controller__in=non_routable_racks, routable=False
        ).count() == len(non_routable_racks)

    def test_get_power_params(self):
        bmc = factory.make_BMC()
        secret_manager = SecretManager()
        secret_manager.set_composite_secret(
            "power-parameters", {"foo": "bar"}, obj=bmc
        )

        assert {"foo": "bar"} == bmc.get_power_parameters()
