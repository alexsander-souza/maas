# Copyright 2015-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import http.client
import json
import random

from django.conf import settings
from django.test import RequestFactory
from django.urls import reverse
import pytest
from twisted.internet.defer import succeed

from maascommon.osystem import CustomOS, OperatingSystemRegistry
from maasserver import eventloop, forms
from maasserver.api import machines as machines_module
from maasserver.api.machines import AllocationOptions, get_allocation_options
from maasserver.enum import (
    BOOT_RESOURCE_TYPE,
    BRIDGE_TYPE,
    INTERFACE_TYPE,
    IPADDRESS_TYPE,
    NODE_STATUS,
)
from maasserver.exceptions import MAASAPIBadRequest
from maasserver.models import (
    Config,
    Domain,
    Machine,
    Node,
    ScriptSet,
    StaticIPAddress,
)
from maasserver.models import node as node_module
from maasserver.models.node import RELEASABLE_STATUSES
from maasserver.testing.architecture import make_arch
from maasserver.testing.eventloop import (
    RegionEventLoopFixture,
    RunningEventLoopFixture,
)
from maasserver.testing.factory import factory
from maasserver.utils.orm import post_commit_hooks, reload_object
from maastesting.querycounter import CountQueries
from metadataserver.enum import SCRIPT_TYPE
from provisioningserver.enum import POWER_STATE
from provisioningserver.utils.enum import map_enum
from tests.maasserver.api.test_nodes import RenderedNodesMixin
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


class TestGetStorageLayoutParams:
    def test_sets_request_data_to_mutable(self):
        data = {"op": "allocate", "storage_layout": "flat"}
        request = RequestFactory().post(reverse("machines_handler"), data)
        request.data = request.POST.copy()
        request.data._mutable = False
        machines_module.get_storage_layout_params(request)
        assert request.data._mutable


@pytest.mark.parametrize(
    "api_identity",
    [
        pytest.param("user=user,client=oauth", id="user=user,client=oauth"),
        pytest.param("user=admin,client=oauth", id="user=admin,client=oauth"),
    ],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestMachineHostname:
    @pytest.fixture(autouse=True)
    def _setup(
        self, api_identity, admin, admin_api_client, maas_user, api_client
    ):
        if "user=admin" in api_identity:
            self.user, self.client = admin, admin_api_client
        else:
            self.user, self.client = maas_user, api_client

    def test_GET_returns_fqdn_with_domain_name_from_node(self):
        # If DNS management is enabled, the domain part of a hostname
        # still comes from the node.
        hostname = factory.make_name("hostname")
        domainname = factory.make_name("domain")

        with post_commit_hooks:
            domain, _ = Domain.objects.get_or_create(
                name=domainname, defaults={"authoritative": True}
            )

        factory.make_Node(hostname=hostname, domain=domain)
        fqdn = f"{hostname}.{domainname}"
        response = self.client.get(reverse("machines_handler"))

        assert response.status_code == http.client.OK.value, response.content
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert [fqdn] == [machine.get("fqdn") for machine in parsed_result]


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestMachineWorkloadAnnotations:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_GET_returns_workload_annotations(self):
        owner_data = {factory.make_name("key"): factory.make_name("value")}
        factory.make_Node(owner_data=owner_data)
        response = self.client.get(reverse("machines_handler"))
        assert response.status_code == http.client.OK.value, response.content
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert [machine.get("owner_data") for machine in parsed_result] == [
            owner_data
        ]
        assert [
            machine.get("workload_annotations") for machine in parsed_result
        ] == [owner_data]


def extract_system_ids(parsed_result):
    """List the system_ids of the machines in `parsed_result`."""
    return [machine.get("system_id") for machine in parsed_result]


def extract_system_ids_from_machines(machines):
    return [machine.system_id for machine in machines]


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestMachinesAPI:
    """Tests for /api/2.0/machines/."""

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, api_client, maas_user, mocker):
        self.user = maas_user
        self.client = api_client
        self.machines_url = reverse("machines_handler")
        mocker.patch.object(node_module, "stop_workflow")

    def get_json(self, *args, **kwargs):
        """Call the handler, and get the JSON response"""
        return self.client.get(self.machines_url, *args, **kwargs).json()

    def make_usable_architecture(self, mocker, **kwargs):
        architecture = make_arch(**kwargs)
        mocker.patch.object(
            forms, "list_all_usable_architectures", return_value=[architecture]
        )
        return architecture

    def make_usable_osystem(self, request, osystem_name=None, releases=None):
        if osystem_name is None:
            osystem_name = factory.make_name("os")
        if releases is None:
            releases = [factory.make_name("release") for _ in range(3)]
        aliases = [factory.make_name("alias") for _ in releases]
        if osystem_name not in OperatingSystemRegistry:
            OperatingSystemRegistry.register_item(osystem_name, CustomOS())
            request.addfinalizer(
                lambda: OperatingSystemRegistry.unregister_item(osystem_name)
            )
        architectures = [
            node.architecture for node in Node.objects.distinct("architecture")
        ]
        if not architectures:
            architectures.append(f"{factory.make_name('arch')}/generic")
        for architecture in architectures:
            factory.make_default_ubuntu_release_bootable(
                architecture.split("/")[0]
            )
            for release, alias in zip(releases, aliases):
                factory.make_BootResource(
                    rtype=BOOT_RESOURCE_TYPE.UPLOADED,
                    name=f"{osystem_name}/{release}",
                    alias=f"{osystem_name}/{alias}",
                    architecture=architecture,
                )
        return osystem_name, releases

    def test_handler_path(self):
        assert "/MAAS/api/2.0/machines/" == self.machines_url

    def test_GET_includes_error_description(self):
        factory.make_Node(
            status=NODE_STATUS.BROKEN,
            ephemeral_deploy=True,
            error_description="my error",
        )
        parsed_result = self.get_json()
        assert parsed_result[0]["error_description"] == "my error"

    def test_POST_creates_machine(self, mocker):
        # The API allows a non-admin logged-in user to create a Machine.
        hostname = factory.make_name("host")
        architecture = self.make_usable_architecture(mocker)
        macs = {
            factory.make_mac_address() for _ in range(random.randint(1, 2))
        }
        response = self.client.post(
            self.machines_url,
            {
                "hostname": hostname,
                "architecture": architecture,
                "mac_addresses": macs,
            },
        )
        assert http.client.OK == response.status_code
        system_id = response.json()["system_id"]
        machine = Machine.objects.get(system_id=system_id)
        assert machine.hostname == hostname
        assert machine.architecture == architecture
        assert {
            nic.mac_address
            for nic in machine.current_config.interface_set.all()
        } == macs

    def test_POST_creates_ipmi_machine_sets_workaround_flags(self, mocker):
        self.make_usable_architecture(mocker)
        hostname = factory.make_name("host")
        macs = {
            factory.make_mac_address() for _ in range(random.randint(1, 2))
        }
        power_address = factory.make_ip_address()
        workaround_flags = ["authcap"]
        response = self.client.post(
            self.machines_url,
            {
                "hostname": hostname,
                "mac_addresses": macs,
                "power_type": "ipmi",
                "power_parameters_power_address": power_address,
                "power_parameters_workaround_flags": workaround_flags,
            },
        )
        assert http.client.OK == response.status_code
        system_id = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )["system_id"]
        machine = Machine.objects.get(system_id=system_id)
        assert machine.hostname == hostname
        assert sorted(workaround_flags) == sorted(
            machine.get_power_parameters()["workaround_flags"]
        )

    def test_POST_creates_ipmi_machine_sets_mac_addresses_empty_no_arch(
        self, mocker
    ):
        self.make_usable_architecture(mocker)
        hostname = factory.make_name("host")
        macs = {
            factory.make_mac_address() for _ in range(random.randint(1, 2))
        }
        power_address = factory.make_ip_address()
        response = self.client.post(
            self.machines_url,
            {
                "hostname": hostname,
                "mac_addresses": macs,
                "power_type": "ipmi",
                "power_parameters_power_address": power_address,
            },
        )
        assert http.client.OK == response.status_code
        system_id = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )["system_id"]
        machine = Machine.objects.get(system_id=system_id)
        assert machine.hostname == hostname
        assert {
            nic.mac_address
            for nic in machine.current_config.interface_set.all()
        } == set()
        assert power_address == machine.get_power_parameters()["power_address"]

    def test_POST_when_logged_in_creates_machine_in_declared_state(
        self, mocker
    ):
        # When a user enlists a machine, it goes into the New state.
        # This will change once we start doing proper commissioning.
        response = self.client.post(
            self.machines_url,
            {
                "hostname": factory.make_name("host"),
                "architecture": self.make_usable_architecture(mocker),
                "mac_addresses": [factory.make_mac_address()],
            },
        )
        assert http.client.OK == response.status_code
        system_id = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )["system_id"]
        assert NODE_STATUS.NEW == Node.objects.get(system_id=system_id).status

    def test_POST_when_logged_in_creates_deployed_machine(
        self, admin, admin_api_client, mocker
    ):
        response = admin_api_client.post(
            self.machines_url,
            {
                "deployed": True,
                "hostname": factory.make_name("host"),
                "architecture": self.make_usable_architecture(mocker),
                "mac_addresses": [factory.make_mac_address()],
            },
        )
        assert http.client.OK == response.status_code
        system_id = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )["system_id"]
        node = Node.objects.get(system_id=system_id)
        assert NODE_STATUS.DEPLOYED == node.status
        assert admin == node.owner

    def test_POST_new_when_no_RPC_to_rack_defaults_empty_power(
        self, admin, admin_api_client, mocker
    ):
        # Test for bug 1305061, if there is no cluster RPC connection
        # then make sure that power_type is defaulted to the empty
        # string rather than being entirely absent, which results in a
        # crash.
        # The patching behind the scenes to avoid *real* RPC is
        # complex and the available power types is actually a
        # valid set, so use an invalid type to trigger the bug here.
        power_type = factory.make_name("power_type")
        response = admin_api_client.post(
            self.machines_url,
            {
                "architecture": self.make_usable_architecture(mocker),
                "mac_addresses": ["aa:bb:cc:dd:ee:ff"],
                "power_type": power_type,
            },
        )
        assert http.client.BAD_REQUEST == response.status_code
        validation_errors = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )["power_type"]
        assert (
            "Select a valid choice. %s is not one of the "
            "available choices." % power_type == validation_errors[0]
        )

    def test_POST_new_handles_empty_str_power_parameters(self, mocker):
        # Regression test for LP:1636858
        response = self.client.post(
            self.machines_url,
            {
                "architecture": self.make_usable_architecture(mocker),
                "mac_addresses": ["aa:bb:cc:dd:ee:ff"],
                "power_type": "",
                "power_parameters": "",
            },
        )
        assert http.client.OK == response.status_code
        system_id = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )["system_id"]
        machine = Machine.objects.get(system_id=system_id)
        assert "" == machine.power_type
        assert {} == machine.get_power_parameters()

    def test_POST_handles_error_when_unable_to_access_bmc(
        self, admin, admin_api_client, mocker, request
    ):
        # Regression test for LP1600328
        mocker.patch.object(Machine, "_start").return_value = None
        self.make_usable_osystem(request)
        power_address = factory.make_ip_address()
        power_id = factory.make_name("power_id")
        response = admin_api_client.post(
            self.machines_url,
            {
                "architecture": self.make_usable_architecture(mocker),
                "mac_addresses": ["aa:bb:cc:dd:ee:ff"],
                "power_type": "virsh",
                "power_parameters_power_address": power_address,
                "power_parameters_power_id": power_id,
            },
        )
        parsed_result = response.json()
        machine = Machine.objects.get(system_id=parsed_result["system_id"])
        assert "virsh" == parsed_result["power_type"]
        assert power_address == machine.get_power_parameters()["power_address"]
        assert power_id == machine.get_power_parameters()["power_id"]

    def test_POST_rejects_non_fips_driver_when_fips_enabled(
        self, admin, admin_api_client, mocker
    ):
        from maasserver.forms import fips_power

        mocker.patch.object(fips_power, "is_fips_enabled", return_value=True)
        response = admin_api_client.post(
            self.machines_url,
            {
                "architecture": self.make_usable_architecture(mocker),
                "mac_addresses": ["aa:bb:cc:dd:ee:ff"],
                "power_type": "apc",
                "power_parameters_power_address": factory.make_ip_address(),
                "power_parameters_node_outlet": "1",
            },
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        assert b"FIPS" in response.content

    def test_POST_sets_description(
        self, admin, admin_api_client, mocker, request
    ):
        # Regression test for LP1707562
        mocker.patch.object(Machine, "_start").return_value = None
        self.make_usable_osystem(request)
        power_address = factory.make_ip_address()
        power_id = factory.make_name("power_id")
        description = factory.make_name("description")
        response = admin_api_client.post(
            self.machines_url,
            {
                "architecture": self.make_usable_architecture(mocker),
                "mac_addresses": ["aa:bb:cc:dd:ee:ff"],
                "power_type": "virsh",
                "power_parameters_power_address": power_address,
                "power_parameters_power_id": power_id,
                "description": description,
            },
        )
        parsed_result = response.json()
        assert NODE_STATUS.COMMISSIONING == parsed_result["status"]
        assert description == parsed_result["description"]

    def test_POST_starts_commissioning_with_selected_test_scripts(
        self, admin, admin_api_client, mocker, request
    ):
        # Regression test for LP1707562
        mocker.patch.object(Machine, "_start").return_value = None
        self.make_usable_osystem(request)
        power_address = factory.make_ip_address()
        power_id = factory.make_name("power_id")
        test_script = factory.make_Script(script_type=SCRIPT_TYPE.TESTING)
        response = admin_api_client.post(
            self.machines_url,
            {
                "architecture": self.make_usable_architecture(mocker),
                "mac_addresses": ["aa:bb:cc:dd:ee:ff"],
                "power_type": "virsh",
                "power_parameters_power_address": power_address,
                "power_parameters_power_id": power_id,
                "testing_scripts": test_script.name,
            },
        )
        parsed_result = response.json()
        assert NODE_STATUS.COMMISSIONING == parsed_result["status"]
        script_set = ScriptSet.objects.get(
            id=parsed_result["current_testing_result_id"]
        )
        assert [test_script.name] == [
            script_result.name for script_result in script_set
        ]

    def test_POST_commission_true(
        self, admin, admin_api_client, mocker, request
    ):
        # Regression test for LP:1904398
        mocker.patch.object(Machine, "_start").return_value = None
        self.make_usable_osystem(request)
        response = admin_api_client.post(
            self.machines_url,
            {
                "architecture": self.make_usable_architecture(mocker),
                "mac_addresses": ["aa:bb:cc:dd:ee:ff"],
                "power_type": "manual",
                "commission": True,
            },
        )
        parsed_result = response.json()
        assert NODE_STATUS.COMMISSIONING == parsed_result["status"]

    def test_POST_commission_false(
        self, admin, admin_api_client, mocker, request
    ):
        # Regression test for LP:1904398
        self.make_usable_osystem(request)
        response = admin_api_client.post(
            self.machines_url,
            {
                "architecture": self.make_usable_architecture(mocker),
                "mac_addresses": ["aa:bb:cc:dd:ee:ff"],
                "power_type": "manual",
                "commission": False,
            },
        )
        parsed_result = response.json()
        assert NODE_STATUS.NEW == parsed_result["status"]

    def test_GET_lists_machines(self, api_identity):
        # The api allows for fetching the list of Machines.
        machine1 = factory.make_Node()
        machine2 = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=self.user
        )
        parsed_result = self.get_json()

        assert sorted([machine1.system_id, machine2.system_id]) == sorted(
            extract_system_ids(parsed_result)
        )

    def test_GET_includes_numa_nodes(self, api_identity):
        machine = factory.make_Node()
        factory.make_NUMANode(node=machine, memory=2048 * 1024, cores=[0, 1])
        factory.make_NUMANode(node=machine, memory=4096 * 1024, cores=[2, 3])
        [parsed_result] = self.get_json()
        assert sorted(
            parsed_result["numanode_set"], key=lambda node: node["index"]
        ) == [
            {"index": 0, "memory": 0, "cores": [], "hugepages_set": []},
            {
                "index": 1,
                "memory": 2048 * 1024,
                "cores": [0, 1],
                "hugepages_set": [],
            },
            {
                "index": 2,
                "memory": 4096 * 1024,
                "cores": [2, 3],
                "hugepages_set": [],
            },
        ]

    def test_GET_includes_numa_nodes_hugepages(self, api_identity):
        machine = factory.make_Node()
        hugepages = factory.make_NUMANodeHugepages(
            numa_node=machine.default_numanode
        )
        [parsed_result] = self.get_json()
        assert parsed_result["numanode_set"][0]["hugepages_set"] == [
            {
                "page_size": hugepages.page_size,
                "total": hugepages.total,
            },
        ]

    def test_GET_orders_by_id(self, api_identity):
        # Machines are returned in id order.
        machines = [factory.make_Node() for counter in range(3)]
        parsed_result = self.get_json()
        assert [
            machine.system_id for machine in machines
        ] == extract_system_ids(parsed_result)

    def test_GET_doesnt_list_devices(self, api_identity):
        factory.make_Device()
        parsed_result = self.get_json()
        assert [] == parsed_result

    def test_GET_machines_issues_constant_number_of_queries(
        self, api_identity
    ):
        queries_count = []
        machines_count = []

        def exec_request():
            with CountQueries(reset=True) as counter:
                result = self.get_json()
            queries_count.append(counter.count)
            machines_count.append(len(result))

        default_domain = Domain.objects.get_default_domain()
        factory.make_DNSResource(domain=default_domain)
        vlan = factory.make_VLAN(space=factory.make_Space())
        node = factory.make_Node_with_Interface_on_Subnet(vlan=vlan)
        factory.make_VirtualBlockDevice(node=node)
        exec_request()

        node = factory.make_Node_with_Interface_on_Subnet(vlan=vlan)
        factory.make_VirtualBlockDevice(node=node)
        exec_request()

        node = factory.make_Node_with_Interface_on_Subnet(vlan=vlan)
        factory.make_VirtualBlockDevice(node=node)
        exec_request()

        assert machines_count == [1, 2, 3]
        assert len(set(queries_count)) == 1

    def test_GET_without_machines_returns_empty_list(self, api_identity):
        # If there are no machines to list, the "read" op still works but
        # returns an empty list.
        assert [] == self.get_json()

    def test_GET_with_id_returns_matching_machines(self, api_identity):
        # The "read" operation takes optional "id" parameters.  Only
        # machines with matching ids will be returned.
        ids = [factory.make_Node().system_id for counter in range(3)]
        matching_id = ids[0]
        parsed_result = self.get_json({"id": [matching_id]})
        assert [matching_id] == extract_system_ids(parsed_result)

    def test_GET_with_nonexistent_id_returns_empty_list(self, api_identity):
        # Trying to list a nonexistent machine id returns a list containing
        # no machines -- even if other (non-matching) machines exist.
        existing_id = factory.make_Node().system_id
        nonexistent_id = existing_id + factory.make_string()
        response = self.get_json({"id": [nonexistent_id]})
        assert [] == response

    def test_GET_with_ids_orders_by_id(self, api_identity):
        # Even when ids are passed to "list," machines are returned in id
        # order, not necessarily in the order of the id arguments.
        ids = [factory.make_Node().system_id for counter in range(3)]
        parsed_result = self.get_json({"id": list(reversed(ids))})
        assert ids == extract_system_ids(parsed_result)

    def test_GET_with_some_matching_ids_returns_matching_machines(
        self, api_identity
    ):
        # If some machines match the requested ids and some don't, only the
        # matching ones are returned.
        existing_id = factory.make_Node().system_id
        nonexistent_id = existing_id + factory.make_string()
        parsed_result = self.get_json({"id": [existing_id, nonexistent_id]})
        assert [existing_id] == extract_system_ids(parsed_result)

    def test_GET_with_hostname_returns_matching_machines(self, api_identity):
        # The read operation takes optional "hostname" parameters. Only
        # machines with matching hostnames will be returned.
        machines = [factory.make_Node() for _ in range(3)]
        matching_hostname = machines[0].hostname
        matching_system_id = machines[0].system_id
        parsed_result = self.get_json({"hostname": [matching_hostname]})
        assert [matching_system_id] == extract_system_ids(parsed_result)

    def test_GET_with_macs_returns_matching_machines(self, api_identity):
        # The "read" operation takes optional "mac_address" parameters. Only
        # machines with matching MAC addresses will be returned.
        interfaces = [
            factory.make_Interface(INTERFACE_TYPE.PHYSICAL) for _ in range(3)
        ]
        matching_mac = interfaces[0].mac_address
        matching_system_id = interfaces[0].node_config.node.system_id
        parsed_result = self.get_json({"mac_address": [matching_mac]})
        assert [matching_system_id] == extract_system_ids(parsed_result)

    def test_GET_with_invalid_macs_returns_sensible_error(self, api_identity):
        # If specifying an invalid MAC, make sure the error that's
        # returned is not a crazy stack trace, but something nice to
        # humans.
        bad_mac1 = "00:E0:81:DD:D1:ZZ"  # ZZ is bad.
        bad_mac2 = "00:E0:81:DD:D1:XX"  # XX is bad.
        ok_mac = str(
            factory.make_Interface(INTERFACE_TYPE.PHYSICAL).mac_address
        )
        parsed_result = self.get_json(
            {"mac_address": [bad_mac1, bad_mac2, ok_mac]}
        )
        assert parsed_result == {
            "mac_address": ["'00:E0:81:DD:D1:ZZ' is not a valid MAC address."]
        }

    def test_GET_with_agent_name_filters_by_agent_name(self, api_identity):
        factory.make_Node(agent_name=factory.make_name("other_agent_name"))
        agent_name = factory.make_name("agent-name")
        machine = factory.make_Node(agent_name=agent_name)
        parsed_result = self.get_json({"agent_name": agent_name})
        assert [machine.system_id] == extract_system_ids(parsed_result)

    def test_GET_with_agent_name_filters_with_empty_string(self, api_identity):
        factory.make_Node(agent_name=factory.make_name("agent-name"))
        machine = factory.make_Node(agent_name="")
        parsed_result = self.get_json({"agent_name": ""})
        assert [machine.system_id] == extract_system_ids(parsed_result)

    def test_GET_without_agent_name_does_not_filter(self, api_identity):
        machines = [
            factory.make_Node(agent_name=factory.make_name("agent-name"))
            for _ in range(3)
        ]
        parsed_result = self.get_json()
        assert sorted(machine.system_id for machine in machines) == sorted(
            extract_system_ids(parsed_result)
        )

    def test_GET_with_zone_filters_by_zone(self, api_identity):
        factory.make_Node(zone=factory.make_Zone(name="twilight"))
        zone = factory.make_Zone()
        machine = factory.make_Node(zone=zone)
        parsed_result = self.get_json({"zone": zone.name})
        assert [machine.system_id] == extract_system_ids(parsed_result)

    def test_GET_without_zone_does_not_filter(self, api_identity):
        machines = [
            factory.make_Node(zone=factory.make_Zone()) for _ in range(3)
        ]
        parsed_result = self.get_json()
        assert [
            machine.system_id for machine in machines
        ] == extract_system_ids(parsed_result)

    def test_GET_list_allocated_returns_only_allocated_with_user(self):
        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=self.user
        )
        factory.make_Node(status=NODE_STATUS.ALLOCATED)

        parsed_result = self.get_json({"op": "list_allocated"})
        assert [machine.system_id] == extract_system_ids(parsed_result)

    def test_GET_list_allocated_filters_by_id(self):
        machines = []
        for _ in range(3):
            machines.append(
                factory.make_Node(
                    status=NODE_STATUS.ALLOCATED, owner=self.user
                )
            )

        required_machine_ids = [machines[0].system_id, machines[1].system_id]
        parsed_result = self.get_json(
            {"op": "list_allocated", "id": required_machine_ids}
        )
        assert sorted(required_machine_ids) == sorted(
            extract_system_ids(parsed_result)
        )

    def test_POST_allocate_returns_available_machine(self, api_identity):
        # The "allocate" operation returns an available machine.
        available_status = NODE_STATUS.READY
        machine = factory.make_Node(
            status=available_status, owner=None, with_boot_disk=True
        )
        response = self.client.post(self.machines_url, {"op": "allocate"})
        assert http.client.OK == response.status_code
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert machine.system_id == parsed_result["system_id"]

    def test_POST_allocate_allocates_machine(self, api_identity):
        # The "allocate" operation allocates the machine it returns.
        available_status = NODE_STATUS.READY
        machine = factory.make_Node(
            status=available_status, owner=None, with_boot_disk=True
        )
        self.client.post(self.machines_url, {"op": "allocate"})
        machine = Machine.objects.get(system_id=machine.system_id)
        assert self.user == machine.owner

    def test_POST_allocate_uses_machine_acquire_lock(
        self, api_identity, mocker
    ):
        # The "allocate" operation allocates the machine it returns.
        available_status = NODE_STATUS.READY
        factory.make_Node(
            status=available_status, owner=None, with_boot_disk=True
        )
        machine_acquire = mocker.patch.object(
            machines_module.locks, "node_acquire"
        )
        self.client.post(self.machines_url, {"op": "allocate"})
        machine_acquire.__enter__.assert_called_once_with()
        machine_acquire.__exit__.assert_called_once_with(None, None, None)

    def test_POST_allocate_sets_agent_name(self, api_identity):
        available_status = NODE_STATUS.READY
        machine = factory.make_Node(
            status=available_status,
            owner=None,
            agent_name=factory.make_name("agent-name"),
            with_boot_disk=True,
        )
        agent_name = factory.make_name("agent-name")
        self.client.post(
            self.machines_url,
            {"op": "allocate", "agent_name": agent_name},
        )
        machine = Machine.objects.get(system_id=machine.system_id)
        assert agent_name == machine.agent_name

    def test_POST_allocate_agent_name_defaults_to_empty_string(
        self, api_identity
    ):
        available_status = NODE_STATUS.READY
        agent_name = factory.make_name("agent-name")
        machine = factory.make_Node(
            status=available_status,
            owner=None,
            agent_name=agent_name,
            with_boot_disk=True,
        )
        self.client.post(self.machines_url, {"op": "allocate"})
        machine = Machine.objects.get(system_id=machine.system_id)
        assert "" == machine.agent_name

    def test_POST_allocate_fails_if_no_machine_present(self, api_identity):
        # The "allocate" operation returns a Conflict error if no machines
        # are available.
        response = self.client.post(self.machines_url, {"op": "allocate"})
        # Fails with Conflict error: resource can't satisfy request.
        assert http.client.CONFLICT == response.status_code

    def test_POST_allocate_failure_shows_no_constraints_if_none_given(
        self, api_identity
    ):
        response = self.client.post(self.machines_url, {"op": "allocate"})
        assert http.client.CONFLICT == response.status_code
        assert "No machine available." == response.content.decode(
            settings.DEFAULT_CHARSET
        )

    def test_POST_allocate_failure_shows_constraints_if_given(
        self, api_identity
    ):
        hostname = factory.make_name("host")
        response = self.client.post(
            self.machines_url, {"op": "allocate", "name": hostname}
        )
        expected_response = (
            "No available machine matches constraints: [('name', "
            "['%s'])] (resolved to \"name=%s\")" % (hostname, hostname)
        ).encode(settings.DEFAULT_CHARSET)
        assert http.client.CONFLICT == response.status_code
        assert expected_response == response.content

    def test_POST_allocate_ignores_already_allocated_machine(
        self, api_identity
    ):
        factory.make_Node(
            status=NODE_STATUS.ALLOCATED,
            owner=factory.make_User(),
            with_boot_disk=True,
        )
        response = self.client.post(self.machines_url, {"op": "allocate"})
        assert http.client.CONFLICT == response.status_code

    def test_POST_allocate_chooses_candidate_matching_constraint(
        self, api_identity
    ):
        # If "allocate" is passed a constraint, it will go for a machine
        # matching that constraint even if there's tons of other machines
        # available.
        # (Creating lots of machines here to minimize the chances of this
        # passing by accident).
        available_machines = [
            factory.make_Node(
                status=NODE_STATUS.READY, owner=None, with_boot_disk=True
            )
            for counter in range(20)
        ]
        desired_machine = random.choice(available_machines)
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "name": desired_machine.hostname},
        )
        assert http.client.OK == response.status_code
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        domain_name = desired_machine.domain.name
        assert (
            f"{desired_machine.hostname}.{domain_name}"
            == parsed_result["fqdn"]
        )

    def test_POST_allocate_would_rather_fail_than_disobey_constraint(
        self, api_identity
    ):
        # If "allocate" is passed a constraint, it won't return a machine
        # that does not meet that constraint.  Even if it means that it
        # can't meet the request.
        factory.make_Node(
            status=NODE_STATUS.READY, owner=None, with_boot_disk=True
        )
        desired_machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=factory.make_User()
        )
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "name": desired_machine.system_id},
        )
        assert http.client.CONFLICT == response.status_code

    def test_POST_allocate_fails_if_given_system_id_invalid(
        self, api_identity
    ):
        # If an unavailable or incorrect "system_id" is passed, make sure
        # that no machine is returned.
        some_available_machine = factory.make_Node(
            status=NODE_STATUS.READY, owner=None, with_boot_disk=True
        )
        incorrect_system_id = (
            some_available_machine.system_id[-1]
            + some_available_machine.system_id[:-1]
        )
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "system_id": incorrect_system_id},
        )
        expected_response = f"No machine with system ID {incorrect_system_id} available.".encode(
            "utf-8"
        )
        assert http.client.CONFLICT == response.status_code
        assert expected_response == response.content

    def test_POST_allocate_does_not_ignore_unknown_constraint(
        self, api_identity
    ):
        factory.make_Node(
            status=NODE_STATUS.READY, owner=None, with_boot_disk=True
        )
        unknown_constraint = factory.make_string()
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", unknown_constraint: factory.make_string()},
        )
        assert http.client.BAD_REQUEST == response.status_code
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert {unknown_constraint: ["No such constraint."]} == parsed_result

    def test_POST_allocate_allocates_machine_by_name(self, api_identity):
        # Positive test for name constraint.
        # If a name constraint is given, "allocate" attempts to allocate
        # a machine of that name.
        machine = factory.make_Node(
            domain=factory.make_Domain(),
            status=NODE_STATUS.READY,
            owner=None,
            with_boot_disk=True,
        )
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "name": machine.hostname},
        )
        assert http.client.OK == response.status_code
        domain_name = machine.domain.name
        assert (
            f"{machine.hostname}.{domain_name}"
            == json.loads(response.content.decode(settings.DEFAULT_CHARSET))[
                "fqdn"
            ]
        )

    def test_POST_allocate_allocates_machine_by_system_id(self, api_identity):
        # Positive test for system_id constraint.
        # If a name constraint is given, "allocate" attempts to allocate
        # a machine with that system_id.
        machine = factory.make_Node(
            domain=factory.make_Domain(),
            status=NODE_STATUS.READY,
            owner=None,
            with_boot_disk=True,
        )
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "system_id": machine.system_id},
        )
        assert http.client.OK == response.status_code
        resultant_system_id = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )["system_id"]
        assert machine.system_id == resultant_system_id

    def test_POST_allocate_treats_unknown_name_as_resource_conflict(
        self, api_identity
    ):
        # A name constraint naming an unknown machine produces a resource
        # conflict: most likely the machine existed but has changed or
        # disappeared.
        # Certainly it's not a 404, since the resource named in the URL
        # is "machines/," which does exist.
        factory.make_Node(
            status=NODE_STATUS.READY, owner=None, with_boot_disk=True
        )
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "name": factory.make_string()},
        )
        assert http.client.CONFLICT == response.status_code

    def test_POST_allocate_allocates_machine_by_arch(
        self, api_identity, mocker
    ):
        # Asking for a particular arch allocates a machine with that arch.
        arch = self.make_usable_architecture(mocker)
        machine = factory.make_Node(
            status=NODE_STATUS.READY, architecture=arch, with_boot_disk=True
        )
        response = self.client.post(
            self.machines_url, {"op": "allocate", "arch": arch}
        )
        assert http.client.OK == response.status_code
        response_json = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert machine.architecture == response_json["architecture"]

    def test_POST_allocate_treats_unknown_arch_as_bad_request(
        self, api_identity
    ):
        # Asking for an unknown arch returns an HTTP "400 Bad Request"
        factory.make_Node(status=NODE_STATUS.READY, with_boot_disk=True)
        response = self.client.post(
            self.machines_url, {"op": "allocate", "arch": "sparc"}
        )
        assert http.client.BAD_REQUEST == response.status_code

    def test_POST_allocate_allocates_machine_by_cpu(self, api_identity):
        # Asking for enough cpu allocates a machine with at least that.
        machine = factory.make_Node(
            status=NODE_STATUS.READY, cpu_count=3, with_boot_disk=True
        )
        response = self.client.post(
            self.machines_url, {"op": "allocate", "cpu_count": 2}
        )
        assert http.client.OK == response.status_code
        response_json = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert machine.system_id == response_json["system_id"]

    def test_POST_allocate_allocates_machine_by_float_cpu(self, api_identity):
        # Asking for a needlessly precise number of cpus works.
        machine = factory.make_Node(
            status=NODE_STATUS.READY, cpu_count=1, with_boot_disk=True
        )
        response = self.client.post(
            self.machines_url, {"op": "allocate", "cpu_count": "1.0"}
        )
        assert http.client.OK == response.status_code
        response_json = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert machine.system_id == response_json["system_id"]

    def test_POST_allocate_fails_with_invalid_cpu(self):
        # Asking for an invalid amount of cpu returns a bad request.
        factory.make_Node(status=NODE_STATUS.READY, with_boot_disk=True)
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "cpu_count": "plenty"},
        )
        assert http.client.BAD_REQUEST == response.status_code

    def test_POST_allocate_allocates_machine_by_mem(self):
        # Asking for enough memory acquires a machine with at least that.
        machine = factory.make_Node(
            status=NODE_STATUS.READY, memory=1024, with_boot_disk=True
        )
        response = self.client.post(
            self.machines_url, {"op": "allocate", "mem": 1024}
        )
        assert http.client.OK == response.status_code
        response_json = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert machine.system_id == response_json["system_id"]

    def test_POST_allocate_fails_with_invalid_mem(self):
        # Asking for an invalid amount of memory returns a bad request.
        factory.make_Node(status=NODE_STATUS.READY, with_boot_disk=True)
        response = self.client.post(
            self.machines_url, {"op": "allocate", "mem": "bags"}
        )
        assert http.client.BAD_REQUEST == response.status_code

    def test_POST_allocate_allocates_machine_by_tags(self, api_identity):
        machine = factory.make_Node(
            status=NODE_STATUS.READY, with_boot_disk=True
        )
        machine_tag_names = ["fast", "stable", "cute"]
        machine.tags.set(factory.make_Tag(t) for t in machine_tag_names)
        # Legacy call using comma-separated tags.
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "tags": ["fast", "stable"]},
        )
        assert response.status_code == http.client.OK
        response_json = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert sorted(machine_tag_names) == sorted(response_json["tag_names"])

    def test_POST_allocate_allocates_machine_by_negated_tags(
        self, api_identity
    ):
        tagged_machine = factory.make_Node(
            status=NODE_STATUS.READY, with_boot_disk=True
        )
        partially_tagged_machine = factory.make_Node(
            status=NODE_STATUS.READY, with_boot_disk=True
        )
        machine_tag_names = ["fast", "stable", "cute"]
        tags = [factory.make_Tag(t) for t in machine_tag_names]
        tagged_machine.tags.set(tags)
        partially_tagged_machine.tags.set(tags[:-1])
        # Legacy call using comma-separated tags.
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "not_tags": ["cute"]},
        )
        assert response.status_code == http.client.OK
        response_json = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert partially_tagged_machine.system_id == response_json["system_id"]
        assert sorted(machine_tag_names[:-1]) == sorted(
            response_json["tag_names"]
        )

    def test_POST_allocate_allocates_machine_by_zone(self, api_identity):
        factory.make_Node(status=NODE_STATUS.READY, with_boot_disk=True)
        zone = factory.make_Zone()
        machine = factory.make_Node(
            status=NODE_STATUS.READY, zone=zone, with_boot_disk=True
        )
        response = self.client.post(
            self.machines_url, {"op": "allocate", "zone": zone.name}
        )
        assert response.status_code == http.client.OK
        response_json = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert machine.system_id == response_json["system_id"]

    def test_POST_allocate_allocates_machine_by_zone_fails_if_no_machine(
        self, api_identity
    ):
        factory.make_Node(status=NODE_STATUS.READY, with_boot_disk=True)
        zone = factory.make_Zone()
        response = self.client.post(
            self.machines_url, {"op": "allocate", "zone": zone.name}
        )
        assert response.status_code == http.client.CONFLICT

    def test_POST_allocate_rejects_unknown_zone(self, api_identity):
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "zone": factory.make_name("zone")},
        )
        assert response.status_code == http.client.BAD_REQUEST

    def test_POST_allocate_allocates_machine_by_pool(self, api_identity):
        node1 = factory.make_Node(
            status=NODE_STATUS.READY, with_boot_disk=True
        )
        factory.make_Node(status=NODE_STATUS.READY, with_boot_disk=True)
        pool = factory.make_ResourcePool(nodes=[node1])
        response = self.client.post(
            self.machines_url, {"op": "allocate", "pool": pool.name}
        )
        assert response.status_code == http.client.OK
        response_json = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert node1.system_id == response_json["system_id"]

    def test_POST_allocate_allocates_machine_by_pool_fails_if_no_machine(
        self, api_identity
    ):
        factory.make_Node(status=NODE_STATUS.READY, with_boot_disk=True)
        pool = factory.make_ResourcePool()
        response = self.client.post(
            self.machines_url, {"op": "allocate", "pool": pool.name}
        )
        assert response.status_code == http.client.CONFLICT

    def test_POST_allocate_rejects_unknown_pool(self, api_identity):
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "pool": factory.make_name("pool")},
        )
        assert response.status_code == http.client.BAD_REQUEST

    def test_POST_allocate_allocates_machine_by_tags_comma_separated(
        self, api_identity
    ):
        machine = factory.make_Node(
            status=NODE_STATUS.READY, with_boot_disk=True
        )
        machine_tag_names = ["fast", "stable", "cute"]
        machine.tags.set(factory.make_Tag(t) for t in machine_tag_names)
        # Legacy call using comma-separated tags.
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "tags": "fast, stable"},
        )
        assert response.status_code == http.client.OK
        response_json = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert sorted(machine_tag_names) == sorted(response_json["tag_names"])

    def test_POST_allocate_allocates_machine_by_tags_space_separated(
        self, api_identity
    ):
        machine = factory.make_Node(
            status=NODE_STATUS.READY, with_boot_disk=True
        )
        machine_tag_names = ["fast", "stable", "cute"]
        machine.tags.set(factory.make_Tag(t) for t in machine_tag_names)
        # Legacy call using space-separated tags.
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "tags": "fast stable"},
        )
        assert response.status_code == http.client.OK
        response_json = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert sorted(machine_tag_names) == sorted(response_json["tag_names"])

    def test_POST_allocate_allocates_machine_by_tags_comma_space_delim(
        self, api_identity
    ):
        machine = factory.make_Node(
            status=NODE_STATUS.READY, with_boot_disk=True
        )
        machine_tag_names = ["fast", "stable", "cute"]
        machine.tags.set(factory.make_Tag(t) for t in machine_tag_names)
        # Legacy call using comma-and-space-separated tags.
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "tags": "fast, stable cute"},
        )
        assert response.status_code == http.client.OK
        response_json = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert sorted(machine_tag_names) == sorted(response_json["tag_names"])

    def test_POST_allocate_allocates_machine_by_tags_mixed_input(
        self, api_identity
    ):
        machine = factory.make_Node(
            status=NODE_STATUS.READY, with_boot_disk=True
        )
        machine_tag_names = ["fast", "stable", "cute"]
        machine.tags.set(factory.make_Tag(t) for t in machine_tag_names)
        # Mixed call using comma-separated tags in a list.
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "tags": ["fast, stable", "cute"]},
        )
        assert response.status_code == http.client.OK
        response_json = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert sorted(machine_tag_names) == sorted(response_json["tag_names"])

    def test_POST_allocate_allocates_machine_by_storage(self, api_identity):
        """Storage label is returned alongside machine data"""
        machine = factory.make_Node(
            status=NODE_STATUS.READY, with_boot_disk=False
        )
        factory.make_PhysicalBlockDevice(
            node=machine,
            size=11 * (1000**3),
            tags=["ssd"],
            formatted_root=True,
        )
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "storage": "needed:10(ssd)"},
        )
        assert response.status_code == http.client.OK
        response_json = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        device_id = response_json["physicalblockdevice_set"][0]["id"]
        constraints = response_json["constraints_by_type"]
        assert "storage" in constraints
        assert "needed" in constraints["storage"]
        assert device_id in constraints["storage"]["needed"]
        assert "verbose_storage" not in constraints

    def test_POST_allocate_allocates_machine_by_storage_with_verbose(
        self, api_identity
    ):
        """Storage label is returned alongside machine data"""
        machine = factory.make_Node(
            status=NODE_STATUS.READY, with_boot_disk=False
        )
        factory.make_PhysicalBlockDevice(
            node=machine,
            size=11 * (1000**3),
            tags=["ssd"],
            formatted_root=True,
        )
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "storage": "needed:10(ssd)", "verbose": "true"},
        )
        assert response.status_code == http.client.OK
        response_json = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        device_id = response_json["physicalblockdevice_set"][0]["id"]
        constraints = response_json["constraints_by_type"]
        assert "storage" in constraints
        assert "needed" in constraints["storage"]
        assert device_id in constraints["storage"]["needed"]
        assert str(machine.id) in constraints.get("verbose_storage")

    def test_POST_allocate_allocates_machine_by_interfaces(self, api_identity):
        """Interface label is returned alongside machine data"""
        fabric = factory.make_Fabric("ubuntu")
        # The ID may always be '1', which won't be interesting for testing.
        for _ in range(1, random.choice([1, 3, 5])):
            factory.make_Interface()
        machine = factory.make_Node_with_Interface_on_Subnet(
            status=NODE_STATUS.READY, fabric=fabric
        )
        iface = machine.get_boot_interface()
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "interfaces": "needed:fabric=ubuntu"},
        )
        assert response.status_code == http.client.OK
        response_json = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert response_json["status"] == NODE_STATUS.ALLOCATED
        constraints = response_json["constraints_by_type"]
        assert "interfaces" in constraints
        interfaces = constraints.get("interfaces")
        assert "needed" in interfaces
        assert iface.id in interfaces["needed"]
        assert "verbose_interfaces" not in constraints

    def test_POST_allocate_with_subnet_specifier_renders_error(
        self, api_identity
    ):
        space = factory.make_Space("foo")
        v1 = factory.make_VLAN(space=space)
        v2 = factory.make_VLAN(space=space)
        s1 = factory.make_Subnet(vlan=v1, space=None)
        s2 = factory.make_Subnet(vlan=v2, space=None)
        factory.make_Node_with_Interface_on_Subnet(subnet=s1)
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "subnets": "space:foo"},
        )
        assert response.status_code == http.client.CONFLICT
        expected_response = (
            "No available machine matches constraints: [('subnets', "
            "['space:foo'])] (resolved to \"subnets=%d,%d\")" % (s1.pk, s2.pk)
        ).encode(settings.DEFAULT_CHARSET)
        assert expected_response == response.content

    def test_POST_allocate_machine_by_interfaces_dry_run_with_verbose(
        self, api_identity
    ):
        """Interface label is returned alongside machine data"""
        fabric = factory.make_Fabric("ubuntu")
        # The ID may always be '1', which won't be interesting for testing.
        for _ in range(1, random.choice([1, 3, 5])):
            factory.make_Interface()
        machine = factory.make_Node_with_Interface_on_Subnet(
            status=NODE_STATUS.READY, fabric=fabric
        )
        iface = machine.get_boot_interface()
        response = self.client.post(
            self.machines_url,
            {
                "op": "allocate",
                "interfaces": "needed:fabric=ubuntu",
                "verbose": "true",
                "dry_run": "true",
            },
        )
        assert response.status_code == http.client.OK
        response_json = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert response_json["status"] == NODE_STATUS.READY
        # Check that we still got the verbose constraints output even if
        # it was a dry run.
        constraints = response_json["constraints_by_type"]
        assert "interfaces" in constraints
        interfaces = constraints.get("interfaces")
        assert "needed" in interfaces
        assert iface.id in interfaces["needed"]
        assert "verbose_interfaces" in constraints
        verbose_interfaces = constraints.get("verbose_interfaces")
        assert "needed" in verbose_interfaces
        assert str(machine.id) in verbose_interfaces["needed"]
        assert iface.id in verbose_interfaces["needed"][str(machine.id)]

    def test_POST_allocate_allocates_machine_by_interfaces_with_verbose(
        self, api_identity
    ):
        """Interface label is returned alongside machine data"""
        fabric = factory.make_Fabric("ubuntu")
        # The ID may always be '1', which won't be interesting for testing.
        for _ in range(1, random.choice([1, 3, 5])):
            factory.make_Interface()
        factory.make_Node()
        machine = factory.make_Node_with_Interface_on_Subnet(
            status=NODE_STATUS.READY, fabric=fabric
        )
        iface = machine.get_boot_interface()
        response = self.client.post(
            self.machines_url,
            {
                "op": "allocate",
                "interfaces": "needed:fabric=ubuntu",
                "verbose": "true",
            },
        )
        assert response.status_code == http.client.OK
        response_json = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        constraints = response_json["constraints_by_type"]
        assert "interfaces" in constraints
        interfaces = constraints.get("interfaces")
        assert "needed" in interfaces
        assert [iface.id] == interfaces["needed"]
        assert "verbose_interfaces" in constraints
        verbose_interfaces = constraints.get("verbose_interfaces")
        assert "needed" in verbose_interfaces
        assert str(machine.id) in verbose_interfaces["needed"]
        assert iface.id in verbose_interfaces["needed"][str(machine.id)]

    def test_POST_allocate_fails_without_all_tags(self):
        # Asking for particular tags does not acquire if no machine has all
        # tags.
        machine1 = factory.make_Node(
            status=NODE_STATUS.READY, with_boot_disk=True
        )
        machine1.tags.set(
            factory.make_Tag(t) for t in ("fast", "stable", "cute")
        )
        machine2 = factory.make_Node(
            status=NODE_STATUS.READY, with_boot_disk=True
        )
        machine2.tags.set([factory.make_Tag("cheap")])
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "tags": "fast, cheap"},
        )
        assert response.status_code == http.client.CONFLICT

    def test_POST_allocate_fails_with_unknown_tags(self):
        # Asking for a tag that does not exist gives a specific error.
        machine = factory.make_Node(
            status=NODE_STATUS.READY, with_boot_disk=True
        )
        machine.tags.set([factory.make_Tag("fast")])
        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "tags": "fast, hairy, boo"},
        )
        assert response.status_code == http.client.BAD_REQUEST
        response_dict = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        # The order in which "foo" and "bar" appear is not guaranteed.
        assert "No such tag(s):" in response_dict["tags"][0]
        assert "'hairy'" in response_dict["tags"][0]
        assert "'boo'" in response_dict["tags"][0]

    def test_POST_allocate_allocates_machine_by_subnet(self):
        subnets = [factory.make_Subnet() for _ in range(5)]
        machines = [
            factory.make_Node_with_Interface_on_Subnet(
                status=NODE_STATUS.READY, with_boot_disk=True, subnet=subnet
            )
            for subnet in subnets
        ]
        # We'll make it so that only the machine and subnet at this index will
        # match the request.
        pick = 2

        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "subnets": [subnets[pick].name]},
        )

        assert response.status_code == http.client.OK
        response_json = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert machines[pick].system_id == response_json["system_id"]

    def test_POST_allocate_allocates_machine_by_not_subnet(self):
        subnets = [factory.make_Subnet() for _ in range(5)]
        for subnet in subnets:
            factory.make_Node_with_Interface_on_Subnet(
                status=NODE_STATUS.READY, with_boot_disk=True, subnet=subnet
            )
        right_machine = factory.make_Node_with_Interface_on_Subnet(
            status=NODE_STATUS.READY, with_boot_disk=True
        )

        response = self.client.post(
            self.machines_url,
            {
                "op": "allocate",
                "not_subnets": [subnet.name for subnet in subnets],
            },
        )

        assert response.status_code == http.client.OK
        response_json = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert right_machine.system_id == response_json["system_id"]

    def test_POST_allocate_obeys_not_in_zone(self):
        # Zone we don't want to acquire from.
        not_in_zone = factory.make_Zone()
        machines = [
            factory.make_Node(
                status=NODE_STATUS.READY, zone=not_in_zone, with_boot_disk=True
            )
            for _ in range(5)
        ]
        # Pick a machine in the middle to avoid false negatives if acquire()
        # always tries the oldest, or the newest, machine first.
        eligible_machine = machines[2]
        eligible_machine.zone = factory.make_Zone()
        eligible_machine.save()

        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "not_in_zone": [not_in_zone.name]},
        )
        assert http.client.OK == response.status_code
        system_id = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )["system_id"]
        assert eligible_machine.system_id == system_id

    def test_POST_allocate_obeys_not_in_pool(self):
        # Pool we don't want to acquire from.
        node1 = factory.make_Node(
            status=NODE_STATUS.READY, with_boot_disk=True
        )
        node2 = factory.make_Node(
            status=NODE_STATUS.READY, with_boot_disk=True
        )
        pool1 = factory.make_ResourcePool(nodes=[node1])
        factory.make_ResourcePool(nodes=[node2])

        response = self.client.post(
            self.machines_url,
            {"op": "allocate", "not_in_pool": [pool1.name]},
        )
        assert http.client.OK == response.status_code
        system_id = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )["system_id"]
        assert node2.system_id == system_id

    def test_POST_accept_gets_machine_out_of_declared_state(
        self, admin, admin_api_client, mocker
    ):
        # This will change when we add provisioning.  Until then,
        # acceptance gets a machine straight to Ready state.
        target_state = NODE_STATUS.COMMISSIONING

        mocker.patch.object(Machine, "_start").return_value = None
        machine = factory.make_Node_with_Interface_on_Subnet(
            status=NODE_STATUS.NEW
        )
        response = admin_api_client.post(
            self.machines_url,
            {"op": "accept", "machines": [machine.system_id]},
        )
        accepted_ids = [
            accepted_machine["system_id"]
            for accepted_machine in json.loads(
                response.content.decode(settings.DEFAULT_CHARSET)
            )
        ]
        assert (http.client.OK, [machine.system_id]) == (
            response.status_code,
            accepted_ids,
        )
        assert target_state == reload_object(machine).status

    def test_POST_quietly_accepts_empty_set(self):
        response = self.client.post(self.machines_url, {"op": "accept"})
        assert (http.client.OK.value, "[]") == (
            response.status_code,
            response.content.decode(settings.DEFAULT_CHARSET),
        )

    def test_POST_accept_rejects_impossible_state_changes(
        self, admin, admin_api_client, mocker
    ):
        mocker.patch.object(Machine, "_start").return_value = None
        acceptable_states = {
            NODE_STATUS.NEW,
            NODE_STATUS.COMMISSIONING,
            NODE_STATUS.READY,
        }
        status_iter = iter(
            set(map_enum(NODE_STATUS).values()) - acceptable_states
        )
        machine = factory.make_Node(with_boot_disk=False)
        mocker.patch.object(
            machines_module.MachinesHandler.base_model.objects, "get_nodes"
        ).return_value = [machine]

        for status in status_iter:
            machine.status = status
            response = admin_api_client.post(
                self.machines_url,
                {"op": "accept", "machines": [machine.system_id]},
            )
            assert response.status_code == http.client.CONFLICT
            content = response.content.decode(settings.DEFAULT_CHARSET)
            assert content == (
                f"Cannot accept node enlistment: node {machine.system_id} is in state {machine.status_name}."
            )

    def test_POST_accept_fails_if_machine_does_not_exist(
        self, admin, admin_api_client
    ):
        # Make sure there is a machine, it just isn't the one being accepted
        factory.make_Node()
        machine_id = factory.make_string()
        response = admin_api_client.post(
            self.machines_url,
            {"op": "accept", "machines": [machine_id]},
        )
        assert (
            http.client.BAD_REQUEST,
            ("Unknown machine(s): %s." % machine_id).encode(
                settings.DEFAULT_CHARSET
            ),
        ) == (
            response.status_code,
            response.content,
        )

    def test_POST_accept_fails_for_device(self, admin, admin_api_client):
        factory.make_Device()
        machine_id = factory.make_string()
        response = admin_api_client.post(
            self.machines_url,
            {"op": "accept", "machines": [machine_id]},
        )
        assert (
            http.client.BAD_REQUEST,
            ("Unknown machine(s): %s." % machine_id).encode(
                settings.DEFAULT_CHARSET
            ),
        ) == (
            response.status_code,
            response.content,
        )

    def test_POST_accept_accepts_multiple_machines(
        self, admin, admin_api_client, mocker
    ):
        # This will change when we add provisioning.  Until then,
        # acceptance gets a machine straight to Ready state.
        target_state = NODE_STATUS.COMMISSIONING

        mocker.patch.object(Machine, "_start").return_value = None
        machines = [
            factory.make_Node_with_Interface_on_Subnet(status=NODE_STATUS.NEW)
            for counter in range(2)
        ]
        machine_ids = [machine.system_id for machine in machines]
        response = admin_api_client.post(
            self.machines_url,
            {"op": "accept", "machines": machine_ids},
        )
        assert http.client.OK == response.status_code
        assert [target_state] * len(machines) == [
            reload_object(machine).status for machine in machines
        ]

    def test_POST_accept_returns_actually_accepted_machines(
        self, admin, admin_api_client, mocker
    ):
        mocker.patch.object(Machine, "_start").return_value = None
        acceptable_machines = [
            factory.make_Node_with_Interface_on_Subnet(status=NODE_STATUS.NEW)
            for counter in range(2)
        ]
        accepted_machine = factory.make_Node(status=NODE_STATUS.READY)
        machines = acceptable_machines + [accepted_machine]
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "accept",
                "machines": [machine.system_id for machine in machines],
            },
        )
        assert http.client.OK == response.status_code
        accepted_ids = [
            machine["system_id"]
            for machine in json.loads(
                response.content.decode(settings.DEFAULT_CHARSET)
            )
        ]
        assert sorted(
            machine.system_id for machine in acceptable_machines
        ) == sorted(accepted_ids)
        assert accepted_machine.system_id not in accepted_ids

    def test_POST_quietly_releases_empty_set(self, api_client):
        response = api_client.post(self.machines_url, {"op": "release"})
        assert (http.client.OK.value, "[]") == (
            response.status_code,
            response.content.decode(settings.DEFAULT_CHARSET),
        )

    def test_POST_release_ignores_devices(self, api_client):
        device_ids = {factory.make_Device().system_id for _ in range(3)}
        response = api_client.post(
            self.machines_url,
            {"op": "release", "machines": device_ids},
        )
        assert http.client.BAD_REQUEST == response.status_code

    def test_POST_release_rejects_request_from_unauthorized_user(self):
        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=factory.make_User()
        )
        response = self.client.post(
            self.machines_url,
            {"op": "release", "machines": [machine.system_id]},
        )
        assert http.client.FORBIDDEN == response.status_code
        assert NODE_STATUS.ALLOCATED == reload_object(machine).status

    def test_POST_release_fails_if_machines_do_not_exist(self):
        # Make sure there is a machine, it just isn't among the ones to release
        factory.make_Node()
        machine_ids = {factory.make_string() for _ in range(5)}
        response = self.client.post(
            self.machines_url,
            {"op": "release", "machines": machine_ids},
        )
        # Awkward parsing, but the order may vary and it's not JSON
        s = response.content.decode(settings.DEFAULT_CHARSET)
        returned_ids = s[s.find(":") + 2 : s.rfind(".")].split(", ")
        assert http.client.BAD_REQUEST == response.status_code
        assert "Unknown machine(s): " in response.content.decode(
            settings.DEFAULT_CHARSET
        )
        assert sorted(machine_ids) == sorted(returned_ids)

    def test_POST_release_forbidden_if_user_cannot_edit_machine(self):
        # Create a bunch of machines, owned by the logged in user
        machine_ids = {
            factory.make_Node(
                status=NODE_STATUS.ALLOCATED, owner=self.user
            ).system_id
            for _ in range(3)
        }
        # And one with another owner
        another_machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=factory.make_User()
        )
        machine_ids.add(another_machine.system_id)
        response = self.client.post(
            self.machines_url,
            {"op": "release", "machines": machine_ids},
        )
        expected_response = (
            "You don't have the required permission to release the following "
            "machine(s): %s." % another_machine.system_id
        ).encode(settings.DEFAULT_CHARSET)
        assert (http.client.FORBIDDEN.value, expected_response) == (
            response.status_code,
            response.content,
        )

    def test_POST_release_forbidden_if_locked_machines(self):
        machine1 = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=self.user
        )
        machine2 = factory.make_Node(
            status=NODE_STATUS.DEPLOYED, owner=self.user, locked=True
        )
        # And one with no owner
        response = self.client.post(
            self.machines_url,
            {
                "op": "release",
                "machines": [machine1.system_id, machine2.system_id],
            },
        )
        expected_response = (
            "You don't have the required permission to release the following "
            "machine(s): {}.".format(machine2.system_id)
        ).encode(settings.DEFAULT_CHARSET)
        assert (http.client.FORBIDDEN.value, expected_response) == (
            response.status_code,
            response.content,
        )

    def test_POST_release_rejects_impossible_state_changes(self, api_client):
        acceptable_states = {NODE_STATUS.READY} | RELEASABLE_STATUSES
        unacceptable_states = (
            set(map_enum(NODE_STATUS).values()) - acceptable_states
        )
        owner = self.user
        machines = [
            factory.make_Node(status=status, owner=owner)
            for status in unacceptable_states
        ]
        response = api_client.post(
            self.machines_url,
            {
                "op": "release",
                "machines": [machine.system_id for machine in machines],
            },
        )
        # Awkward parsing again, because a string is returned, not JSON
        expected = [
            f"{machine.system_id} ('{machine.display_status()}')"
            for machine in machines
            if machine.status not in acceptable_states
        ]
        s = response.content.decode(settings.DEFAULT_CHARSET)
        returned = s[s.rfind(":") + 2 : s.rfind(".")].split(", ")
        assert http.client.CONFLICT == response.status_code
        assert "Machine(s) cannot be released in their current state:" in (
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert sorted(expected) == sorted(returned)

    def test_POST_release_returns_modified_machines(self, api_client, mocker):
        owner = self.user
        mocker.patch.object(Machine, "_stop")
        mocker.patch.object(Machine, "_set_status")
        acceptable_states = RELEASABLE_STATUSES | {NODE_STATUS.READY}
        zone = factory.make_Zone()
        machines = [
            factory.make_Node(
                status=status, owner=owner, with_boot_disk=False, zone=zone
            )
            for status in acceptable_states
        ]
        response = api_client.post(
            self.machines_url,
            {
                "op": "release",
                "machines": [machine.system_id for machine in machines],
            },
        )
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert http.client.OK == response.status_code
        # The first machine is READY, so shouldn't be touched.
        assert sorted(machine.system_id for machine in machines[1:]) == sorted(
            parsed_result
        )

    def test_POST_release_erases_disks_when_enabled(self, api_client, mocker):
        owner = self.user
        mocker.patch.object(Machine, "_start").return_value = None
        machine = factory.make_Node_with_Interface_on_Subnet(
            status=NODE_STATUS.ALLOCATED,
            power_state=POWER_STATE.OFF,
            owner=owner,
        )
        Config.objects.set_config("enable_disk_erasing_on_release", True)
        response = api_client.post(
            self.machines_url,
            {"op": "release", "machines": [machine.system_id]},
        )
        assert http.client.OK.value == response.status_code, response
        machine = reload_object(machine)
        assert NODE_STATUS.DISK_ERASING == machine.status

    def test_POST_set_zone_sets_zone_on_machines(
        self, admin, admin_api_client
    ):
        machine = factory.make_Node()
        zone = factory.make_Zone()
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "set_zone",
                "nodes": [machine.system_id],
                "zone": zone.name,
            },
        )
        assert http.client.OK == response.status_code
        machine = reload_object(machine)
        assert zone == machine.zone

    def test_POST_set_zone_does_not_affect_other_machines(
        self, admin, admin_api_client
    ):
        machine = factory.make_Node()
        original_zone = machine.zone
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "set_zone",
                "nodes": [factory.make_Node().system_id],
                "zone": factory.make_Zone().name,
            },
        )
        assert http.client.OK == response.status_code
        machine = reload_object(machine)
        assert original_zone == machine.zone

    def test_POST_set_zone_requires_admin(self, api_client):
        machine = factory.make_Node(owner=self.user)
        original_zone = machine.zone
        response = api_client.post(
            self.machines_url,
            {
                "op": "set_zone",
                "nodes": [machine.system_id],
                "zone": factory.make_Zone().name,
            },
        )
        assert http.client.BAD_REQUEST == response.status_code
        machine = reload_object(machine)
        assert original_zone == machine.zone

    def test_POST_add_chassis_requires_admin(self, api_client):
        response = api_client.post(self.machines_url, {"op": "add_chassis"})
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_POST_add_chassis_requires_chassis_type(
        self, admin, admin_api_client
    ):
        response = admin_api_client.post(
            self.machines_url, {"op": "add_chassis"}
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        assert b"No provided chassis_type!" == response.content

    def test_POST_add_chassis_invalid_chasis_type(
        self, admin, admin_api_client
    ):
        response = admin_api_client.post(
            self.machines_url,
            {"op": "add_chassis", "chassis_type": "invalid"},
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        assert response.content.startswith(
            b"Invalid chassis_type: Value must be one of: "
        )

    def test_POST_add_chassis_requires_hostname(self, admin, admin_api_client):
        response = admin_api_client.post(
            self.machines_url,
            {"op": "add_chassis", "chassis_type": "virsh"},
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        assert b"No provided hostname!" == response.content

    def test_POST_add_chassis_rejects_removed_chassis_types(
        self, admin, admin_api_client, mocker
    ):
        add_chassis = mocker.patch.object(
            node_module.RackController, "add_chassis"
        )
        for chassis_type in (
            "dli",
            "eaton",
            "mscm",
            "msftocs",
            "openbmc",
            "ucsm",
        ):
            response = admin_api_client.post(
                self.machines_url,
                {
                    "op": "add_chassis",
                    "chassis_type": chassis_type,
                    "hostname": factory.make_url(),
                    "username": factory.make_name("username"),
                    "password": factory.make_name("password"),
                },
            )
            assert http.client.BAD_REQUEST == response.status_code
            assert response.content.startswith(
                b"Invalid chassis_type: Value must be one of: "
            )
            choices = response.content.split(b" (not ", 1)[0]
            assert chassis_type.encode("utf-8") not in choices
        add_chassis.assert_not_called()

    def test_POST_add_chassis_validates_chassis_type(
        self, admin, admin_api_client
    ):
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "add_chassis",
                "chassis_type": factory.make_name("chassis_type"),
                "hostname": factory.make_url(),
            },
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )

    def test_POST_add_chassis_username_required_for_required_chassis(
        self, admin, admin_api_client, mocker
    ):
        rack = factory.make_RackController()
        mocker.patch.object(
            machines_module.RackController.objects,
            "get_accessible_by_url",
            return_value=rack,
        )
        mocker.patch.object(rack, "add_chassis")
        for chassis_type in (
            "hmcz",
            "recs_box",
            "seamicro15k",
            "vmware",
        ):
            response = admin_api_client.post(
                self.machines_url,
                {
                    "op": "add_chassis",
                    "chassis_type": chassis_type,
                    "hostname": factory.make_url(),
                },
            )
            assert http.client.BAD_REQUEST == response.status_code, (
                response.content
            )
            assert b"No provided username!" == response.content

    def test_POST_add_chassis_password_required_for_required_chassis(
        self, admin, admin_api_client, mocker
    ):
        rack = factory.make_RackController()
        mocker.patch.object(
            machines_module.RackController.objects,
            "get_accessible_by_url",
            return_value=rack,
        )
        mocker.patch.object(rack, "add_chassis")
        for chassis_type in (
            "hmcz",
            "recs_box",
            "seamicro15k",
            "vmware",
        ):
            response = admin_api_client.post(
                self.machines_url,
                {
                    "op": "add_chassis",
                    "chassis_type": chassis_type,
                    "hostname": factory.make_url(),
                    "username": factory.make_name("username"),
                },
            )
            assert http.client.BAD_REQUEST == response.status_code, (
                response.content
            )
            assert b"No provided password!" == response.content

    def test_POST_add_chassis_proxmox_requires_password_or_token(
        self, admin, admin_api_client, mocker
    ):
        rack = factory.make_RackController()
        chassis_mock = mocker.patch.object(rack, "add_chassis")
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "add_chassis",
                "rack_controller": rack.system_id,
                "chassis_type": "proxmox",
                "hostname": factory.make_url(),
                "username": factory.make_name("username"),
            },
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        assert (
            b"You must use a password or token with Proxmox."
            == response.content
        )
        chassis_mock.assert_not_called()

    def test_POST_add_chassis_proxmox_requires_password_xor_token(
        self, admin, admin_api_client, mocker
    ):
        rack = factory.make_RackController()
        chassis_mock = mocker.patch.object(rack, "add_chassis")
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "add_chassis",
                "rack_controller": rack.system_id,
                "chassis_type": "proxmox",
                "hostname": factory.make_url(),
                "username": factory.make_name("username"),
                "password": factory.make_name("password"),
                "token_name": factory.make_name("token_name"),
                "token_secret": factory.make_name("token_secret"),
            },
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        assert (
            b"You may only use a password or token with Proxmox, not both."
            == response.content
        )
        chassis_mock.assert_not_called()

    def test_POST_add_chassis_proxmox_requires_token_name_and_secret(
        self, admin, admin_api_client, mocker
    ):
        rack = factory.make_RackController()
        chassis_mock = mocker.patch.object(rack, "add_chassis")
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "add_chassis",
                "rack_controller": rack.system_id,
                "chassis_type": "proxmox",
                "hostname": factory.make_url(),
                "username": factory.make_name("username"),
                random.choice(
                    ["token_name", "token_secret"]
                ): factory.make_name("token"),
            },
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        assert (
            b"Proxmox requires both a token_name and token_secret."
            == response.content
        )
        chassis_mock.assert_not_called()

    def test_POST_add_chassis_username_disallowed_on_virsh_and_powerkvm(
        self, admin, admin_api_client, mocker
    ):
        rack = factory.make_RackController()
        mocker.patch.object(
            machines_module.RackController.objects,
            "get_accessible_by_url",
            return_value=rack,
        )
        mocker.patch.object(rack, "add_chassis")
        for chassis_type in ("powerkvm", "virsh"):
            response = admin_api_client.post(
                self.machines_url,
                {
                    "op": "add_chassis",
                    "chassis_type": chassis_type,
                    "hostname": factory.make_url(),
                    "username": factory.make_name("username"),
                },
            )
            assert http.client.BAD_REQUEST == response.status_code, (
                response.content
            )
            assert (
                "username can not be specified when using the %s chassis."
                % chassis_type
            ).encode("utf-8") == response.content

    def test_POST_add_chassis_sends_accept_all_when_true(
        self, admin, admin_api_client, mocker
    ):
        rack = factory.make_RackController()
        mocker.patch.object(
            machines_module.RackController.objects,
            "get_accessible_by_url",
            return_value=rack,
        )
        add_chassis = mocker.patch.object(rack, "add_chassis")
        hostname = factory.make_url()
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "add_chassis",
                "chassis_type": "virsh",
                "hostname": hostname,
                "accept_all": "true",
            },
        )
        assert http.client.OK == response.status_code, response.content
        add_chassis.assert_called_once_with(
            admin.username,
            "virsh",
            hostname,
            None,
            None,
            True,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            False,
        )

    def test_POST_add_chassis_sends_accept_all_false_when_not_true(
        self, admin, admin_api_client, mocker
    ):
        rack = factory.make_RackController()
        mocker.patch.object(
            machines_module.RackController.objects,
            "get_accessible_by_url",
            return_value=rack,
        )
        add_chassis = mocker.patch.object(rack, "add_chassis")
        hostname = factory.make_url()
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "add_chassis",
                "chassis_type": "virsh",
                "hostname": hostname,
                "accept_all": factory.make_name("accept_all"),
            },
        )
        assert http.client.OK == response.status_code, response.content
        add_chassis.assert_called_once_with(
            admin.username,
            "virsh",
            hostname,
            None,
            None,
            False,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            False,
        )

    def test_POST_add_chassis_sends_prefix_filter(
        self, admin, admin_api_client, mocker
    ):
        rack = factory.make_RackController()
        mocker.patch.object(
            machines_module.RackController.objects,
            "get_accessible_by_url",
            return_value=rack,
        )
        add_chassis = mocker.patch.object(rack, "add_chassis")
        hostname = factory.make_url()
        for chassis_type in ("powerkvm", "virsh", "vmware", "proxmox", "hmcz"):
            prefix_filter = factory.make_name("prefix_filter")
            password = factory.make_name("password")
            params = {
                "op": "add_chassis",
                "chassis_type": chassis_type,
                "hostname": hostname,
                "password": password,
                "prefix_filter": prefix_filter,
            }
            if chassis_type in {"vmware", "proxmox", "hmcz"}:
                username = factory.make_name("username")
                params["username"] = username
            else:
                username = None
            response = admin_api_client.post(self.machines_url, params)
            assert http.client.OK == response.status_code, response.content
            add_chassis.assert_called_with(
                admin.username,
                chassis_type,
                hostname,
                username,
                password,
                False,
                None,
                prefix_filter,
                None,
                None,
                None,
                None,
                None,
                False,
            )

    def test_POST_add_chassis_only_allows_prefix_filter_on_virtual_chassis(
        self, admin, admin_api_client
    ):
        for chassis_type in ("recs_box", "seamicro15k"):
            response = admin_api_client.post(
                self.machines_url,
                {
                    "op": "add_chassis",
                    "chassis_type": chassis_type,
                    "hostname": factory.make_url(),
                    "username": factory.make_name("username"),
                    "password": factory.make_name("password"),
                    "prefix_filter": factory.make_name("prefix_filter"),
                },
            )
            assert http.client.BAD_REQUEST == response.status_code, (
                response.content
            )
            assert (
                "prefix_filter is unavailable with the %s chassis type"
                % chassis_type
            ).encode("utf-8") == response.content

    def test_POST_add_chassis_seamicro_validates_power_control(
        self, admin, admin_api_client
    ):
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "add_chassis",
                "chassis_type": "seamicro15k",
                "hostname": factory.make_url(),
                "username": factory.make_name("username"),
                "password": factory.make_name("password"),
                "power_control": factory.make_name("power_control"),
            },
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )

    def test_POST_add_chassis_seamicro_allows_acceptable_power_controls(
        self, admin, admin_api_client, mocker
    ):
        rack = factory.make_RackController()
        mocker.patch.object(
            machines_module.RackController.objects,
            "get_accessible_by_url",
            return_value=rack,
        )
        mocker.patch.object(rack, "add_chassis")
        for power_control in ("ipmi", "restapi", "restapi2"):
            hostname = factory.make_url()
            username = factory.make_name("username")
            password = factory.make_name("password")
            response = admin_api_client.post(
                self.machines_url,
                {
                    "op": "add_chassis",
                    "chassis_type": "seamicro15k",
                    "hostname": hostname,
                    "username": username,
                    "password": password,
                    "power_control": power_control,
                },
            )
            assert http.client.OK == response.status_code, response.content
            assert (
                "Asking %s to add machines from chassis %s"
                % (rack.hostname, hostname)
            ).encode("utf-8") == response.content

    def test_POST_add_chassis_only_allow_power_control_on_seamicro15k(
        self, admin, admin_api_client
    ):
        for chassis_type in (
            "virsh",
            "vmware",
            "powerkvm",
            "proxmox",
        ):
            params = {
                "op": "add_chassis",
                "chassis_type": chassis_type,
                "hostname": factory.make_url(),
                "password": factory.make_name("password"),
                "power_control": "ipmi",
            }
            if chassis_type not in ("virsh", "powerkvm"):
                params["username"] = factory.make_name("username")
            response = admin_api_client.post(self.machines_url, params)
            assert http.client.BAD_REQUEST == response.status_code, (
                response.content
            )
            assert (
                "power_control is unavailable with the %s chassis type"
                % chassis_type
            ).encode("utf-8") == response.content

    def test_POST_add_chassis_sends_port_with_vmware_and_recs_box(
        self, admin, admin_api_client, mocker
    ):
        rack = factory.make_RackController()
        mocker.patch.object(
            machines_module.RackController.objects,
            "get_accessible_by_url",
            return_value=rack,
        )
        add_chassis = mocker.patch.object(rack, "add_chassis")
        hostname = factory.make_url()
        username = factory.make_name("username")
        password = factory.make_name("password")
        port = random.randint(1, 65535)
        for chassis_type in ("recs_box", "vmware"):
            response = admin_api_client.post(
                self.machines_url,
                {
                    "op": "add_chassis",
                    "chassis_type": chassis_type,
                    "hostname": hostname,
                    "username": username,
                    "password": password,
                    "port": port,
                },
            )
            assert http.client.OK == response.status_code, response.content
            add_chassis.assert_called_with(
                admin.username,
                chassis_type,
                hostname,
                username,
                password,
                False,
                None,
                None,
                None,
                port,
                None,
                None,
                None,
                False,
            )

    def test_POST_add_chassis_only_allows_port_with_vmware_and_recs_box(
        self, admin, admin_api_client
    ):
        for chassis_type in (
            "powerkvm",
            "seamicro15k",
            "virsh",
        ):
            params = {
                "op": "add_chassis",
                "chassis_type": chassis_type,
                "hostname": factory.make_url(),
                "password": factory.make_name("password"),
                "port": random.randint(1, 65535),
            }
            if chassis_type not in ("virsh", "powerkvm"):
                params["username"] = factory.make_name("username")
            response = admin_api_client.post(self.machines_url, params)
            assert http.client.BAD_REQUEST == response.status_code, (
                response.content
            )
            assert (
                "port is unavailable with the %s chassis type" % chassis_type
            ).encode("utf-8") == response.content

    def test_POST_add_chassis_checks_port_too_high(
        self, admin, admin_api_client
    ):
        for chassis_type in ("recs_box", "vmware"):
            params = {
                "op": "add_chassis",
                "chassis_type": chassis_type,
                "hostname": factory.make_url(),
                "username": factory.make_name("username"),
                "password": factory.make_name("password"),
                "port": 65536,
            }
            response = admin_api_client.post(self.machines_url, params)
            assert http.client.BAD_REQUEST == response.status_code, (
                response.content
            )
            assert (
                b"Invalid port: Please enter a number that is 65535 or smaller"
                == response.content
            )

    def test_POST_add_chassis_checks_port_too_low(
        self, admin, admin_api_client
    ):
        for chassis_type in ("recs_box", "vmware"):
            params = {
                "op": "add_chassis",
                "chassis_type": chassis_type,
                "hostname": factory.make_url(),
                "username": factory.make_name("username"),
                "password": factory.make_name("password"),
                "port": random.randint(-2, 0),
            }
            response = admin_api_client.post(self.machines_url, params)
            assert http.client.BAD_REQUEST == response.status_code, (
                response.content
            )
            assert (
                b"Invalid port: Please enter a number that is 1 or greater"
                == response.content
            )

    def test_POST_add_chassis_only_allows_protocol_with_vmware(
        self, admin, admin_api_client
    ):
        for chassis_type in (
            "powerkvm",
            "seamicro15k",
            "virsh",
        ):
            params = {
                "op": "add_chassis",
                "chassis_type": chassis_type,
                "hostname": factory.make_url(),
                "password": factory.make_name("password"),
                "protocol": factory.make_name("protocol"),
            }
            if chassis_type not in ("virsh", "powerkvm"):
                params["username"] = factory.make_name("username")
            response = admin_api_client.post(self.machines_url, params)
            assert http.client.BAD_REQUEST == response.status_code, (
                response.content
            )
            assert (
                "protocol is unavailable with the %s chassis type"
                % chassis_type
            ).encode("utf-8") == response.content

    def test_POST_add_chassis_sends_protcol_with_vmware(
        self, admin, admin_api_client, mocker
    ):
        rack = factory.make_RackController()
        mocker.patch.object(
            machines_module.RackController.objects,
            "get_accessible_by_url",
            return_value=rack,
        )
        add_chassis = mocker.patch.object(rack, "add_chassis")
        hostname = factory.make_url()
        username = factory.make_name("username")
        password = factory.make_name("password")
        protocol = factory.make_name("protocol")
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "add_chassis",
                "chassis_type": "vmware",
                "hostname": hostname,
                "username": username,
                "password": password,
                "protocol": protocol,
            },
        )
        assert http.client.OK == response.status_code, response.content
        add_chassis.assert_called_once_with(
            admin.username,
            "vmware",
            hostname,
            username,
            password,
            False,
            None,
            None,
            None,
            None,
            protocol,
            None,
            None,
            False,
        )

    def test_POST_add_chassis_accept_domain_by_name(
        self, admin, admin_api_client, mocker
    ):
        rack = factory.make_RackController()
        mocker.patch.object(
            machines_module.RackController.objects,
            "get_accessible_by_url",
            return_value=rack,
        )
        add_chassis = mocker.patch.object(rack, "add_chassis")
        hostname = factory.make_url()
        domain = factory.make_Domain()
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "add_chassis",
                "chassis_type": "virsh",
                "hostname": hostname,
                "domain": domain.name,
            },
        )
        assert http.client.OK == response.status_code, response.content
        add_chassis.assert_called_once_with(
            admin.username,
            "virsh",
            hostname,
            None,
            None,
            False,
            domain.name,
            None,
            None,
            None,
            None,
            None,
            None,
            False,
        )

    def test_POST_add_chassis_accept_domain_by_id(
        self, admin, admin_api_client, mocker
    ):
        rack = factory.make_RackController()
        mocker.patch.object(
            machines_module.RackController.objects,
            "get_accessible_by_url",
            return_value=rack,
        )
        add_chassis = mocker.patch.object(rack, "add_chassis")
        hostname = factory.make_url()
        domain = factory.make_Domain()
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "add_chassis",
                "chassis_type": "virsh",
                "hostname": hostname,
                "domain": domain.id,
            },
        )
        assert http.client.OK == response.status_code, response.content
        add_chassis.assert_called_once_with(
            admin.username,
            "virsh",
            hostname,
            None,
            None,
            False,
            domain.name,
            None,
            None,
            None,
            None,
            None,
            None,
            False,
        )

    def test_POST_add_chassis_validates_domain(self, admin, admin_api_client):
        domain = factory.make_name("domain")
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "add_chassis",
                "chassis_type": "virsh",
                "hostname": factory.make_url(),
                "domain": domain,
            },
        )
        assert http.client.NOT_FOUND == response.status_code, response.content
        assert ("Unable to find specified domain %s" % domain).encode(
            "utf-8"
        ) == response.content

    def test_POST_add_chassis_accepts_system_id_for_rack_controller(
        self, admin, admin_api_client, mocker
    ):
        subnet = factory.make_Subnet()
        rack = factory.make_RackController(subnet=subnet)
        add_chassis = mocker.patch.object(
            node_module.RackController, "add_chassis"
        )
        factory.make_RackController(subnet=subnet)
        accessible_by_url = mocker.patch.object(
            machines_module.RackController.objects, "get_accessible_by_url"
        )
        hostname = factory.pick_ip_in_Subnet(subnet)
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "add_chassis",
                "chassis_type": "virsh",
                "hostname": hostname,
                "rack_controller": rack.system_id,
            },
        )
        assert http.client.OK == response.status_code, response.content
        accessible_by_url.assert_not_called()
        add_chassis.assert_called_once_with(
            admin.username,
            "virsh",
            hostname,
            None,
            None,
            False,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            False,
        )

    def test_POST_add_chassis_accepts_hostname_for_rack_controller(
        self, admin, admin_api_client, mocker
    ):
        subnet = factory.make_Subnet()
        rack = factory.make_RackController(subnet=subnet)
        add_chassis = mocker.patch.object(
            node_module.RackController, "add_chassis"
        )
        factory.make_RackController(subnet=subnet)
        accessible_by_url = mocker.patch.object(
            machines_module.RackController.objects, "get_accessible_by_url"
        )
        hostname = factory.pick_ip_in_Subnet(subnet)
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "add_chassis",
                "chassis_type": "virsh",
                "hostname": hostname,
                "rack_controller": rack.hostname,
            },
        )
        assert http.client.OK == response.status_code, response.content
        accessible_by_url.assert_not_called()
        add_chassis.assert_called_once_with(
            admin.username,
            "virsh",
            hostname,
            None,
            None,
            False,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            False,
        )

    def test_POST_add_chassis_rejects_invalid_rack_controller(
        self, admin, admin_api_client, mocker
    ):
        subnet = factory.make_Subnet()
        factory.make_RackController(subnet=subnet)
        mocker.patch.object(node_module.RackController, "add_chassis")
        accessible_by_url = mocker.patch.object(
            machines_module.RackController.objects, "get_accessible_by_url"
        )
        hostname = factory.pick_ip_in_Subnet(subnet)
        bad_rack = factory.make_name("rack_controller")
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "add_chassis",
                "chassis_type": "virsh",
                "hostname": hostname,
                "rack_controller": bad_rack,
            },
        )
        assert http.client.NOT_FOUND == response.status_code, response.content
        assert ("Unable to find specified rack %s" % bad_rack).encode(
            "utf-8"
        ) == response.content
        accessible_by_url.assert_not_called()

    def test_POST_add_chassis_all_racks_when_no_racks_avalible(
        self, admin, admin_api_client, mocker
    ):
        rack1 = factory.make_RackController(hostname="rack-a")
        rack2 = factory.make_RackController(hostname="rack-b")
        add_chassis1 = mocker.patch.object(rack1, "add_chassis")
        add_chassis2 = mocker.patch.object(rack2, "add_chassis")
        mocker.patch.object(
            machines_module.RackController.objects,
            "all",
            return_value=[rack1, rack2],
        )
        mocker.patch.object(
            machines_module.RackController.objects,
            "get_accessible_by_url",
            return_value=None,
        )
        hostname = factory.make_url()
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "add_chassis",
                "chassis_type": "virsh",
                "hostname": hostname,
            },
        )
        assert http.client.OK == response.status_code, response.content
        add_chassis1.assert_called_once_with(
            admin.username,
            "virsh",
            hostname,
            None,
            None,
            False,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            False,
        )
        add_chassis2.assert_called_once_with(
            admin.username,
            "virsh",
            hostname,
            None,
            None,
            False,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            False,
        )

    def test_POST_clone_error(self, admin, admin_api_client):
        source = factory.make_Machine(with_boot_disk=False)
        factory.make_Interface(node=source, name="eth0")
        destination = factory.make_Machine(
            status=NODE_STATUS.READY, with_boot_disk=False
        )
        factory.make_Interface(node=destination, name="eth1")
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "clone",
                "source": source.system_id,
                "destinations": destination.system_id,
                "interfaces": "true",
            },
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )

    def test_POST_clone(self, admin, admin_api_client):
        source = factory.make_Machine(with_boot_disk=False)
        factory.make_Interface(node=source, name="eth0")
        destination = factory.make_Machine(
            status=NODE_STATUS.READY, with_boot_disk=False
        )
        factory.make_Interface(node=destination, name="eth0")
        response = admin_api_client.post(
            self.machines_url,
            {
                "op": "clone",
                "source": source.system_id,
                "destinations": destination.system_id,
                "interfaces": "true",
            },
        )
        assert http.client.NO_CONTENT == response.status_code, response.content


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures(
    "maasdb", "maas_region_test", "factory", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestPowerState:
    @pytest.fixture(autouse=True)
    def _setup_api_identity(
        self, transactional_maasdb, api_identity, maas_user, api_client
    ):
        self.user = maas_user
        self.client = api_client

    @pytest.fixture(autouse=True)
    def _setup_event_loop(self, request):
        region_event_loop = RegionEventLoopFixture("database-tasks", "rpc")
        region_event_loop.setUp()
        request.addfinalizer(region_event_loop.cleanUp)

        running_event_loop = RunningEventLoopFixture()
        running_event_loop.setUp()
        request.addfinalizer(running_event_loop.cleanUp)

    def get_machine_uri(self, machine):
        """Get the API URI for a machine."""
        return reverse("machine_handler", args=[machine.system_id])

    def test_returns_actual_state(self, factory, mocker):
        machine = factory.make_Node_with_Interface_on_Subnet(power_type="ipmi")
        random_state = random.choice(["on", "off", "error"])

        mocker.patch.object(
            Node,
            "_power_control_node",
            return_value=succeed({"state": random_state}),
        )

        response = self.client.get(
            self.get_machine_uri(machine), {"op": "query_power_state"}
        )
        assert response.status_code == http.client.OK
        response = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert {"state": random_state} == response
        # The machine's power state is now `random_state`.
        dbtasks = eventloop.services.getServiceNamed("database-tasks")
        dbtasks.syncTask().wait(
            timeout=5
        )  # Wait for all pending tasks to run.
        assert random_state == reload_object(machine).power_state


class TestGetAllocationOptions:
    def test_defaults(self):
        request = factory.make_fake_request(method="POST", data={})
        options = get_allocation_options(request)
        expected_options = AllocationOptions(
            agent_name="",
            bridge_all=False,
            bridge_type=BRIDGE_TYPE.STANDARD,
            bridge_fd=0,
            bridge_stp=False,
            comment=None,
            ephemeral_deploy=False,
            enable_hw_sync=False,
        )
        assert expected_options == options

    def test_install_kvm_raises_bad_request(self):
        request = factory.make_fake_request(
            method="POST", data=dict(install_kvm="true")
        )
        with pytest.raises(MAASAPIBadRequest):
            get_allocation_options(request)

    def test_non_defaults(self):
        request = factory.make_fake_request(
            method="POST",
            data=dict(
                bridge_all="true",
                bridge_type=BRIDGE_TYPE.OVS,
                bridge_stp="true",
                bridge_fd="42",
                agent_name="maas",
                comment="don't panic",
                ephemeral_deploy="true",
                enable_hw_sync="true",
            ),
        )
        options = get_allocation_options(request)
        expected_options = AllocationOptions(
            agent_name="maas",
            bridge_all=True,
            bridge_type=BRIDGE_TYPE.OVS,
            bridge_fd=42,
            bridge_stp=True,
            comment="don't panic",
            ephemeral_deploy=True,
            enable_hw_sync=True,
        )
        assert expected_options == options


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestMachinesAPIOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client
        self.machines_url = reverse("machines_handler")

    def test_read_filters_machines(self):
        p1 = factory.make_ResourcePool()
        p2 = factory.make_ResourcePool()

        n1 = factory.make_Node(pool=p1)
        n2 = factory.make_Node(pool=p2)

        self.openfga_client.list_pools_with_view_available_machines_access.return_value = [
            p1.id,
            p2.id,
        ]

        response = self.client.get(self.machines_url)

        assert response.status_code == http.client.OK
        response_data = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        machine_ids = [machine["system_id"] for machine in response_data]
        assert n1.system_id in machine_ids
        assert n2.system_id in machine_ids

        self.openfga_client.list_pools_with_view_available_machines_access.assert_called_once_with(
            self.user
        )

    def test_read_filters_machines_owned_by_other_users(self):
        p1 = factory.make_ResourcePool()
        p2 = factory.make_ResourcePool()
        p3 = factory.make_ResourcePool()

        n1 = factory.make_Node(pool=p1)
        other_user = factory.make_User()
        n2 = factory.make_Node(pool=p2, owner=other_user)
        n3 = factory.make_Node(pool=p3)

        self.openfga_client.list_pools_with_view_available_machines_access.return_value = [
            p1.id,
            p2.id,
        ]

        response = self.client.get(self.machines_url)

        assert response.status_code == http.client.OK
        response_data = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        machine_ids = [machine["system_id"] for machine in response_data]
        assert n1.system_id in machine_ids
        assert n2.system_id not in machine_ids
        assert n3.system_id not in machine_ids

        self.openfga_client.list_pools_with_view_available_machines_access.assert_called_once_with(
            self.user
        )

    def test_read_includes_machines_owned_by_other_users_if_view_all(self):
        p1 = factory.make_ResourcePool()
        p2 = factory.make_ResourcePool()
        p3 = factory.make_ResourcePool()

        n1 = factory.make_Node(pool=p1)
        other_user = factory.make_User()
        n2 = factory.make_Node(pool=p2, owner=other_user)
        n3 = factory.make_Node(pool=p3)

        self.openfga_client.list_pools_with_view_available_machines_access.return_value = [
            p1.id,
            p2.id,
        ]
        self.openfga_client.list_pools_with_view_machines_access.return_value = [
            p1.id,
            p2.id,
        ]

        response = self.client.get(self.machines_url)

        assert response.status_code == http.client.OK
        response_data = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        machine_ids = [machine["system_id"] for machine in response_data]
        assert n1.system_id in machine_ids
        assert n2.system_id in machine_ids
        assert n3.system_id not in machine_ids

        self.openfga_client.list_pools_with_view_available_machines_access.assert_called_once_with(
            self.user
        )
        self.openfga_client.list_pools_with_view_machines_access.assert_called_once_with(
            self.user
        )

    def test_allocate_checks_view_deployable_machines_access(self):
        p = factory.make_ResourcePool()

        self.openfga_client.list_pool_with_deploy_machines_access.return_value = [
            p.id
        ]

        available_status = NODE_STATUS.READY
        machine = factory.make_Node(
            status=available_status, owner=None, with_boot_disk=True, pool=p
        )
        response = self.client.post(self.machines_url, {"op": "allocate"})
        assert response.status_code == http.client.OK, response.content
        machine = Machine.objects.get(system_id=machine.system_id)
        assert machine.owner == self.user
        self.openfga_client.list_pool_with_deploy_machines_access.assert_called_once()

    def test_allocate_returns_409_if_not_deployable(self):
        p = factory.make_ResourcePool()

        self.openfga_client.list_pool_with_deploy_machines_access.return_value = []

        available_status = NODE_STATUS.READY
        factory.make_Node(
            status=available_status, owner=None, with_boot_disk=True, pool=p
        )
        response = self.client.post(self.machines_url, {"op": "allocate"})
        assert response.status_code == http.client.CONFLICT, response.content
        self.openfga_client.list_pool_with_deploy_machines_access.assert_called_once()

    def test_release_returns_403_if_owned_by_another_user(self):
        p = factory.make_ResourcePool()

        self.openfga_client.list_pool_with_deploy_machines_access.return_value = [
            p.id
        ]

        other_user = factory.make_User()
        machine = factory.make_Node(
            status=NODE_STATUS.DEPLOYED,
            owner=other_user,
            with_boot_disk=True,
            pool=p,
        )
        response = self.client.post(
            self.machines_url,
            {"op": "release", "machines": [machine.system_id]},
        )
        assert response.status_code == http.client.FORBIDDEN, response.content
        self.openfga_client.list_pool_with_deploy_machines_access.assert_called_once()

    def test_release_success_if_can_edit_machines(self, mocker):
        mocker.patch.object(Machine, "_stop")
        mocker.patch.object(Machine, "_set_status")

        p = factory.make_ResourcePool()

        self.openfga_client.list_pool_with_deploy_machines_access.return_value = [
            p.id
        ]
        self.openfga_client.list_pools_with_edit_machines_access.return_value = [
            p.id
        ]

        other_user = factory.make_User()
        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED,
            owner=other_user,
            with_boot_disk=True,
            pool_id=p.id,
        )
        response = self.client.post(
            self.machines_url,
            {"op": "release", "machines": {machine.system_id}},
        )
        assert response.status_code == http.client.OK, response.content
        self.openfga_client.list_pool_with_deploy_machines_access.assert_called_once()
        self.openfga_client.list_pools_with_edit_machines_access.assert_called_once()

    def test_release_success_if_is_owner(self, mocker):
        mocker.patch.object(Machine, "_stop")
        mocker.patch.object(Machine, "_set_status")

        p = factory.make_ResourcePool()

        self.openfga_client.list_pool_with_deploy_machines_access.return_value = [
            p.id
        ]
        self.openfga_client.list_pools_with_edit_machines_access.return_value = []

        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED,
            owner=self.user,
            with_boot_disk=True,
            pool_id=p.id,
        )
        response = self.client.post(
            self.machines_url,
            {"op": "release", "machines": [machine.system_id]},
        )
        assert response.status_code == http.client.OK, response.content
        self.openfga_client.list_pool_with_deploy_machines_access.assert_called_once()

    def test_add_chassis_requires_can_edit_machines(self):
        self.openfga_client.can_edit_machines.return_value = True
        response = self.client.post(self.machines_url, {"op": "add_chassis"})
        assert response.status_code != http.client.FORBIDDEN, response.content
        self.openfga_client.can_edit_machines.assert_called_once_with(
            self.user
        )


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestMachinesListingMatchesDetails(RenderedNodesMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client, mocker):
        self.user = maas_user
        self.client = api_client
        self.setup_rendered_nodes(mocker)

    def test_GET_lists_machines_like_details(self):
        machines = self.make_machines()

        listing = self.get_json(reverse("machines_handler"))

        assert [
            machine.system_id for machine in machines
        ] == extract_system_ids(listing)
        self.check_listed_like_details(listing, "machine_handler")

    def test_GET_renders_expected_values(self):
        machine = self.make_rich_machine()

        [listed] = self.get_json(reverse("machines_handler"))

        interfaces = {
            interface["name"]: interface
            for interface in listed["interface_set"]
        }
        assert {9000} == {
            interfaces[interface.name]["effective_mtu"]
            for interface in machine.current_config.interface_set.exclude(
                type=INTERFACE_TYPE.PHYSICAL
            )
        }
        discovered_ip = StaticIPAddress.objects.get(
            interface__node_config__node=machine,
            alloc_type=IPADDRESS_TYPE.DISCOVERED,
        )
        [dhcp_link] = [
            link
            for interface in listed["interface_set"]
            for link in interface["links"]
            if link["mode"] == "dhcp"
        ]
        assert discovered_ip.ip == dhcp_link["ip_address"]
        assert (
            self.tagged_vlan.id
            == dhcp_link["subnet"]["vlan"]["relay_vlan"]["id"]
        )
        assert {
            "gateway_ip": self.tagged_subnet.gateway_ip,
            "link_id": machine.gateway_link_ipv4_id,
        } == listed["default_gateways"]["ipv4"]
        assert (
            self.ipv6_subnet.gateway_ip
            == listed["default_gateways"]["ipv6"]["gateway_ip"]
        )
        assert (
            f"{self.info_event_type.description} - latest"
            == listed["status_message"]
        )
        used_for = {
            device["used_for"]
            for block_device in listed["blockdevice_set"]
            for device in [block_device, *block_device["partitions"]]
        }
        assert {
            "Cache device for cache0",
            "Cache device for cache1",
        } <= used_for
        assert {
            "commissioning_status_name": "Failed",
            "testing_status_name": "Running",
            "cpu_test_status_name": "Passed",
            "memory_test_status_name": "Passed",
            "storage_test_status_name": "Running",
            "network_test_status_name": "Failed",
            "other_test_status_name": "Passed",
        } == {
            key: listed[key]
            for key in (
                "commissioning_status_name",
                "testing_status_name",
                "cpu_test_status_name",
                "memory_test_status_name",
                "storage_test_status_name",
                "network_test_status_name",
                "other_test_status_name",
            )
        }
