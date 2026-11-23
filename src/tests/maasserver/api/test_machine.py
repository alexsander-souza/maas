# Copyright 2015-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
from base64 import b64encode
import http.client
import logging
from random import choice
from unittest.mock import ANY, Mock

from django.conf import settings
from django.core.serializers import json
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from netaddr import IPAddress, IPNetwork
import pytest
from twisted.internet import defer
import yaml

from maascommon.osystem import CustomOS, OperatingSystemRegistry
from maasserver import forms, server_address
from maasserver.api import machines as machines_module
from maasserver.enum import (
    BOOT_RESOURCE_TYPE,
    BRIDGE_TYPE,
    FILESYSTEM_TYPE,
    INTERFACE_LINK_TYPE,
    INTERFACE_TYPE,
    IPADDRESS_TYPE,
    NODE_STATUS,
    NODE_STATUS_CHOICES,
    NODE_STATUS_CHOICES_DICT,
    NODE_TYPE,
    NODE_TYPE_CHOICES,
)
from maasserver.exceptions import StaticIPAddressExhaustion
from maasserver.models import (
    Config,
    Domain,
    Filesystem,
    Machine,
    Node,
    NodeKey,
    NodeUserData,
    ScriptSet,
    StaticIPAddress,
)
from maasserver.models import node as node_module
from maasserver.models import staticipaddress as staticipaddress_module
from maasserver.models.node import RELEASABLE_STATUSES
from maasserver.models.signals.testing import SignalsDisabled
from maasserver.storage_layouts import (
    MIN_BOOT_PARTITION_SIZE,
    StorageLayoutError,
)
from maasserver.testing.api import explain_unexpected_response
from maasserver.testing.architecture import make_arch
from maasserver.testing.factory import factory
from maasserver.testing.orm import reload_objects
from maasserver.testing.testclient import MAASSensibleOAuthClient
from maasserver.utils.converters import json_load_bytes
from maasserver.utils.orm import post_commit, post_commit_hooks, reload_object
from maastemporalworker.workflow import power as power_module
from metadataserver.builtin_scripts import load_builtin_scripts
from metadataserver.enum import SCRIPT_TYPE
from metadataserver.nodeinituser import get_node_init_user
from provisioningserver.enum import POWER_STATE
from provisioningserver.refresh.node_info_scripts import (
    COMMISSIONING_OUTPUT_NAME,
    NODE_INFO_SCRIPTS,
)
from provisioningserver.utils.enum import map_enum
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin
from tests.metadataserver.builtin_scripts import test_hooks


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestMachineAnonAPI:
    def test_machine_init_user_cannot_access(self):
        token = NodeKey.objects.get_token_for_node(factory.make_Node())
        client = MAASSensibleOAuthClient(get_node_init_user(), token)
        response = client.get(reverse("machines_handler"))
        assert response.status_code == http.client.FORBIDDEN


@pytest.mark.parametrize(
    "api_identity",
    [
        pytest.param("user=user,client=oauth", id="user=user,client=oauth"),
        pytest.param("user=admin,client=oauth", id="user=admin,client=oauth"),
    ],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestMachinesAPILoggedIn:
    """A logged-in user can access the API."""

    @pytest.fixture(autouse=True)
    def _setup(
        self,
        api_identity,
        maas_user,
        api_client,
        admin,
        admin_api_client,
        mocker,
    ):
        if api_identity == "user=user,client=oauth":
            self.user, self.client = maas_user, api_client
        else:
            self.user, self.client = admin, admin_api_client
        mocker.patch.object(node_module, "wait_for_power_command", create=True)
        mocker.patch.object(Node, "_start")

    def test_machines_GET_logged_in(self):
        machine = factory.make_Node()
        response = self.client.get(reverse("machines_handler"))
        parsed_result = json_load_bytes(response.content)

        assert http.client.OK == response.status_code
        assert [machine.system_id] == [
            parsed_machine.get("system_id") for parsed_machine in parsed_result
        ]


@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestMachineAPI:
    """Tests for /api/2.0/machines/<machine>/."""

    # XXX: GavinPanella 2016-05-24 bug=1585138: op=acquire does not work for
    # clients authenticated via username and password.
    clientfactories = {"oauth": MAASSensibleOAuthClient}

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client, mocker):
        self.user = maas_user
        self.client = api_client
        self.region = factory.make_RegionController()
        mocker.patch.object(
            node_module.Node, "_pc_power_control_node", create=True
        )
        mocker.patch.object(node_module.Node, "_temporal_deploy")
        mocker.patch.object(staticipaddress_module, "post_commit_do")

    @staticmethod
    def _make_usable_architecture(mocker, **kwargs):
        architecture = make_arch(**kwargs)
        mocker.patch.object(
            forms, "list_all_usable_architectures", return_value=[architecture]
        )
        return architecture

    @staticmethod
    def _make_usable_osystem(
        mocker, request, osystem_name=None, releases=None
    ):
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

    @staticmethod
    def get_machine_uri(machine):
        """Get the API URI for `machine`."""
        return reverse("machine_handler", args=[machine.system_id])

    def test_handler_path(self):
        assert "/MAAS/api/2.0/machines/machine-name/" == reverse(
            "machine_handler", args=["machine-name"]
        )

    def test_GET_returns_machine(self):
        # The api allows for fetching a single Machine (using system_id).
        machine = factory.make_Node()
        response = self.client.get(self.get_machine_uri(machine))

        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        domain_name = Domain.objects.get_default_domain().name
        assert f"{machine.hostname}.{domain_name}" == parsed_result["fqdn"]
        assert machine.system_id == parsed_result["system_id"]

    def test_GET_returns_boot_interface_object(self):
        # The api allows for fetching a single Machine (using system_id).
        machine = factory.make_Node(interface=True)
        boot_interface = machine.get_boot_interface()
        response = self.client.get(self.get_machine_uri(machine))

        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        assert boot_interface.id == parsed_result["boot_interface"]["id"]
        assert (
            str(boot_interface.mac_address)
            == parsed_result["boot_interface"]["mac_address"]
        )

    def test_GET_returns_associated_tag(self):
        machine = factory.make_Node()
        tag = factory.make_Tag()
        machine.tags.add(tag)
        response = self.client.get(self.get_machine_uri(machine))

        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        assert [tag.name] == parsed_result["tag_names"]

    def test_GET_returns_bios_boot_method(self):
        machine = factory.make_Node(bios_boot_method="pxe")
        tag = factory.make_Tag()
        machine.tags.add(tag)
        response = self.client.get(self.get_machine_uri(machine))

        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        assert "pxe" == parsed_result["bios_boot_method"]

    def test_GET_returns_associated_ip_addresses(self):
        machine = factory.make_Node()
        nic = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=machine)
        subnet = factory.make_Subnet()
        ip = factory.pick_ip_in_network(subnet.get_ipnetwork())
        lease = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.DISCOVERED,
            ip=ip,
            interface=nic,
            subnet=subnet,
        )
        response = self.client.get(self.get_machine_uri(machine))

        assert http.client.OK == response.status_code, response.content
        parsed_result = json_load_bytes(response.content)
        assert [lease.ip] == parsed_result["ip_addresses"]

    def test_GET_returns_interface_set(self):
        machine = factory.make_Node()
        response = self.client.get(self.get_machine_uri(machine))
        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        assert "interface_set" in parsed_result

    def test_GET_returns_zone(self):
        machine = factory.make_Node()
        response = self.client.get(self.get_machine_uri(machine))
        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        assert [machine.zone.name, machine.zone.description] == [
            parsed_result["zone"]["name"],
            parsed_result["zone"]["description"],
        ]

    def test_GET_returns_pool(self):
        pool = factory.make_ResourcePool()
        machine = factory.make_Node(pool=pool)
        response = self.client.get(self.get_machine_uri(machine))
        assert http.client.OK == response.status_code
        result = json_load_bytes(response.content)
        assert result["pool"] == {
            "id": pool.id,
            "name": pool.name,
            "description": pool.description,
            "resource_uri": reverse("resourcepool_handler", args=[pool.id]),
        }

    def test_GET_returns_boot_interface(self):
        machine = factory.make_Node(interface=True)
        machine.boot_interface = machine.current_config.interface_set.first()
        machine.save()
        response = self.client.get(self.get_machine_uri(machine))
        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        assert (
            machine.boot_interface.mac_address
            == parsed_result["boot_interface"]["mac_address"]
        )

    def test_GET_returns_hardware_sync_values(self):
        machine = factory.make_Node(enable_hw_sync=True)
        machine.last_sync = timezone.now()
        machine.save()
        response = self.client.get(self.get_machine_uri(machine))
        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        encoder = json.DjangoJSONEncoder()
        assert encoder.default(machine.last_sync) == parsed_result["last_sync"]
        assert machine.sync_interval == parsed_result["sync_interval"]
        assert encoder.default(machine.next_sync) == parsed_result["next_sync"]

    def test_GET_refuses_to_access_nonexistent_machine(self):
        # When fetching a Machine, the api returns a 'Not Found' (404) error
        # if no machine is found.
        url = reverse("machine_handler", args=["invalid-uuid"])

        response = self.client.get(url)

        assert http.client.NOT_FOUND == response.status_code
        assert (
            "No Machine matches the given query."
            == response.content.decode(settings.DEFAULT_CHARSET)
        )

    def test_GET_returns_404_if_machine_name_contains_invld_characters(self):
        # When the requested name contains characters that are invalid for
        # a hostname, the result of the request is a 404 response.
        url = reverse("machine_handler", args=["invalid-uuid-#..."])

        response = self.client.get(url)

        assert http.client.NOT_FOUND == response.status_code
        assert (
            "No Machine matches the given query."
            == response.content.decode(settings.DEFAULT_CHARSET)
        )

    def test_GET_returns_owner_name_when_allocated_to_self(self):
        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=self.user
        )
        response = self.client.get(self.get_machine_uri(machine))
        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        assert machine.owner.username == parsed_result["owner"]

    def test_GET_permission_denied_when_allocated_to_other_user(self):
        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=factory.make_User()
        )
        response = self.client.get(self.get_machine_uri(machine))
        assert http.client.FORBIDDEN == response.status_code

    def test_GET_returns_empty_owner_when_not_allocated(self):
        machine = factory.make_Node(status=NODE_STATUS.READY)
        response = self.client.get(self.get_machine_uri(machine))
        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        assert parsed_result["owner"] is None

    def test_GET_returns_physical_block_devices(self):
        machine = factory.make_Node(with_boot_disk=False)
        devices = [
            factory.make_PhysicalBlockDevice(node=machine) for _ in range(3)
        ]
        response = self.client.get(self.get_machine_uri(machine))
        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        parsed_devices = [
            device["name"]
            for device in parsed_result["physicalblockdevice_set"]
        ]
        assert sorted(device.name for device in devices) == sorted(
            parsed_devices
        )

    def test_GET_rejects_other_node_types(self):
        node = factory.make_Node_with_Interface_on_Subnet(
            owner=self.user,
            node_type=factory.pick_choice(
                NODE_TYPE_CHOICES, but_not=[NODE_TYPE.MACHINE]
            ),
        )
        response = self.client.get(self.get_machine_uri(node))
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_GET_returns_min_hwe_kernel_and_hwe_kernel(self):
        machine = factory.make_Node()
        response = self.client.get(self.get_machine_uri(machine))

        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        assert parsed_result["min_hwe_kernel"] is None
        assert parsed_result["hwe_kernel"] is None

    def test_GET_returns_min_hwe_kernel(self):
        machine = factory.make_Node(min_hwe_kernel="hwe-v")
        response = self.client.get(self.get_machine_uri(machine))

        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        assert "hwe-v" == parsed_result["min_hwe_kernel"]

    def test_GET_returns_ephemeral_deployment(self):
        machine = factory.make_Node(
            status=NODE_STATUS.READY, ephemeral_deploy=True
        )
        response = self.client.get(self.get_machine_uri(machine))

        assert response.status_code == http.client.OK
        parsed_result = json_load_bytes(response.content)
        assert parsed_result["ephemeral_deploy"] is True

    def test_GET_returns_error_description(self):
        machine = factory.make_Node(
            status=NODE_STATUS.BROKEN,
            ephemeral_deploy=True,
            error_description="my error",
        )
        response = self.client.get(self.get_machine_uri(machine))

        assert response.status_code == http.client.OK
        parsed_result = json_load_bytes(response.content)
        assert parsed_result["error_description"] == "my error"

    def test_GET_returns_status_message_with_most_recent_event(self):
        """Makes sure the most recent event from this machine is shown in the
        status_message attribute."""
        type_description = "Type description"
        event_type = factory.make_EventType(
            level=logging.INFO, description=type_description
        )
        # The first event won't be returned.
        event = factory.make_Event(
            type=event_type, description="Uninteresting event"
        )
        machine = event.node
        # The second (and last) event will be returned.
        message = "Interesting event"
        factory.make_Event(type=event_type, description=message, node=machine)
        response = self.client.get(self.get_machine_uri(machine))
        parsed_result = json_load_bytes(response.content)
        assert (
            f"{type_description} - {message}"
            == parsed_result["status_message"]
        )

    def test_GET_returns_status_name(self):
        """GET should display the machine status as a user-friendly string."""
        for status in NODE_STATUS_CHOICES_DICT:
            machine = factory.make_Node(status=status)
            response = self.client.get(self.get_machine_uri(machine))
            parsed_result = json_load_bytes(response.content)
            assert (
                NODE_STATUS_CHOICES_DICT[status]
                == parsed_result["status_name"]
            )

    def test_GET_returns_parent(self):
        parent = factory.make_Node()
        machine = factory.make_Node(parent=parent)
        response = self.client.get(self.get_machine_uri(machine))

        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        assert parent.system_id == parsed_result["parent"]["system_id"]
        assert (
            reverse("machine_handler", args=[parent.system_id])
            == parsed_result["parent"]["resource_uri"]
        )

    def test_GET_returns_enable_kernel_crash_dump(self, mocker):
        machine = factory.make_Node(
            status=NODE_STATUS.READY,
            enable_kernel_crash_dump=True,
            architecture=self._make_usable_architecture(
                mocker, arch_name="amd64"
            ),
        )
        response = self.client.get(self.get_machine_uri(machine))

        assert response.status_code == http.client.OK
        parsed_result = json_load_bytes(response.content)
        assert parsed_result["enable_kernel_crash_dump"] is True

    def test_POST_deploy_sets_osystem_and_distro_series(self, mocker, request):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            power_type="manual",
            status=NODE_STATUS.READY,
            architecture=self._make_usable_architecture(mocker),
        )
        osystem, releases = self._make_usable_osystem(mocker, request)
        distro_series = releases[0]
        response = self.client.post(
            self.get_machine_uri(machine),
            {"op": "deploy", "distro_series": distro_series},
        )
        assert (http.client.OK, machine.system_id) == (
            response.status_code,
            json_load_bytes(response.content)["system_id"],
        )
        assert osystem == reload_object(machine).osystem
        assert distro_series == reload_object(machine).distro_series

    def test_POST_deploy_validates_distro_series(self, mocker):
        machine = factory.make_Node_with_Interface_on_Subnet(
            owner=self.user,
            interface=True,
            power_type="manual",
            status=NODE_STATUS.READY,
            architecture=self._make_usable_architecture(mocker),
        )
        invalid_distro_series = factory.make_string()
        response = self.client.post(
            self.get_machine_uri(machine),
            {"op": "deploy", "distro_series": invalid_distro_series},
        )
        assert (
            http.client.BAD_REQUEST,
            {
                "distro_series": [
                    "'%s' is not a valid distro_series.  "
                    "It should be one of: '', 'ubuntu/noble'."
                    % invalid_distro_series
                ]
            },
        ) == (response.status_code, json_load_bytes(response.content))

    def test_POST_deploy_sets_license_key(self, mocker, request):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            power_type="manual",
            status=NODE_STATUS.READY,
            architecture=self._make_usable_architecture(mocker),
        )
        osystem, releases = self._make_usable_osystem(mocker, request)
        distro_series = releases[0]
        license_key = factory.make_string()
        mocker.patch.object(forms, "validate_license_key").return_value = True
        response = self.client.post(
            self.get_machine_uri(machine),
            {
                "op": "deploy",
                "osystem": osystem,
                "distro_series": distro_series,
                "license_key": license_key,
            },
        )
        assert (http.client.OK, machine.system_id) == (
            response.status_code,
            json_load_bytes(response.content)["system_id"],
        )
        assert license_key == reload_object(machine).license_key

    def test_POST_deploy_validates_license_key(self, mocker, request):
        machine = factory.make_Node_with_Interface_on_Subnet(
            owner=self.user,
            interface=True,
            power_type="manual",
            status=NODE_STATUS.READY,
            architecture=self._make_usable_architecture(mocker),
        )
        osystem, releases = self._make_usable_osystem(mocker, request)
        distro_series = releases[0]
        license_key = factory.make_string()
        mocker.patch.object(forms, "validate_license_key").return_value = False
        response = self.client.post(
            self.get_machine_uri(machine),
            {
                "op": "deploy",
                "osystem": osystem,
                "distro_series": distro_series,
                "license_key": license_key,
            },
        )
        assert (
            http.client.BAD_REQUEST,
            {"license_key": ["Invalid license key."]},
        ) == (response.status_code, json_load_bytes(response.content))

    def test_POST_deploy_sets_default_distro_series(self, mocker, request):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            power_type="manual",
            status=NODE_STATUS.READY,
            architecture=self._make_usable_architecture(mocker),
        )
        osystem = Config.objects.get_config("default_osystem")
        distro_series = Config.objects.get_config("default_distro_series")
        self._make_usable_osystem(
            mocker, request, osystem_name=osystem, releases=[distro_series]
        )
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "deploy"}
        )
        response_info = json_load_bytes(response.content)
        assert response.status_code == http.client.OK
        assert response_info["osystem"] == osystem
        assert response_info["distro_series"] == distro_series

    def test_POST_deploy_works_if_series_already_set(self, mocker, request):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        osystem = Config.objects.get_config("default_osystem")
        distro_series = Config.objects.get_config("default_distro_series")
        self._make_usable_osystem(
            mocker, request, osystem_name=osystem, releases=[distro_series]
        )
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            distro_series=distro_series,
            osystem=osystem,
            architecture=self._make_usable_architecture(mocker),
        )
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "deploy"}
        )
        response_info = json_load_bytes(response.content)
        assert response.status_code == http.client.OK
        assert response_info["osystem"] == osystem
        assert response_info["distro_series"] == distro_series

    def test_POST_deploy_fails_when_install_kvm_is_true(
        self, admin, admin_api_client, mocker, request
    ):
        osystem = Config.objects.get_config("default_osystem")
        distro_series = Config.objects.get_config("default_distro_series")
        self._make_usable_osystem(
            mocker, request, osystem_name=osystem, releases=[distro_series]
        )
        machine = factory.make_Node(
            owner=admin,
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            distro_series=distro_series,
            osystem=osystem,
            architecture=self._make_usable_architecture(mocker),
        )
        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {"op": "deploy", "install_kvm": True},
        )
        assert response.status_code == http.client.BAD_REQUEST
        assert response.content == (
            b"Support for install_kvm allocation parameter has been removed."
        )

    def test_POST_deploy_fails_when_install_rackd_is_true(
        self, admin, admin_api_client, mocker, request
    ):
        osystem = Config.objects.get_config("default_osystem")
        distro_series = Config.objects.get_config("default_distro_series")
        self._make_usable_osystem(
            mocker, request, osystem_name=osystem, releases=[distro_series]
        )
        machine = factory.make_Node(
            owner=admin,
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            distro_series=distro_series,
            osystem=osystem,
            architecture=self._make_usable_architecture(mocker),
        )
        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {"op": "deploy", "install_rackd": True},
        )
        assert response.status_code == http.client.BAD_REQUEST
        assert response.content == (
            b"Support for install_rackd allocation parameter has been removed."
        )

    def test_POST_deploy_sets_ephemeral_deployment_automatically_if_diskless(
        self, mocker, request
    ):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        osystem = Config.objects.get_config("default_osystem")
        distro_series = Config.objects.get_config("default_distro_series")
        self._make_usable_osystem(
            mocker, request, osystem_name=osystem, releases=[distro_series]
        )
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            distro_series=distro_series,
            osystem=osystem,
            architecture=self._make_usable_architecture(mocker),
            with_boot_disk=False,
        )
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "deploy"}
        )
        response_info = json_load_bytes(response.content)
        assert response.status_code == http.client.OK
        assert response_info["ephemeral_deploy"] is True

    def test_POST_deploy_sets_ephemeral_deploy(self, mocker):
        mocker.patch.object(node_module.Node, "_start")
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            power_type="manual",
            status=NODE_STATUS.READY,
            architecture=self._make_usable_architecture(mocker),
        )
        assert not machine.ephemeral_deploy
        response = self.client.post(
            self.get_machine_uri(machine),
            {"op": "deploy", "ephemeral_deploy": "true"},
        )
        assert response.status_code == http.client.OK
        assert reload_object(machine).ephemeral_deploy

    def test_POST_deploy_fails_when_preseed_not_rendered(
        self, mocker, request
    ):
        mock_get_curtin_merged_config = mocker.patch.object(
            machines_module, "get_curtin_merged_config"
        )
        mock_get_curtin_merged_config.side_effect = Exception("error")
        osystem = Config.objects.get_config("default_osystem")
        distro_series = Config.objects.get_config("default_distro_series")
        self._make_usable_osystem(
            mocker, request, osystem_name=osystem, releases=[distro_series]
        )
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            distro_series=distro_series,
            osystem=osystem,
            architecture=self._make_usable_architecture(mocker),
        )
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "deploy"}
        )
        assert response.status_code == http.client.BAD_REQUEST
        assert response.content == b"Failed to render preseed: error"

    def test_POST_deploy_validates_hwe_kernel_with_default_distro_series(
        self, mocker, request
    ):
        architecture = self._make_usable_architecture(
            mocker, subarch_name="generic"
        )
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            power_type="manual",
            status=NODE_STATUS.READY,
            architecture=architecture,
        )
        osystem = Config.objects.get_config("default_osystem")
        distro_series = Config.objects.get_config("default_distro_series")
        self._make_usable_osystem(
            mocker, request, osystem_name=osystem, releases=[distro_series]
        )
        bad_hwe_kernel = "hwe-" + chr(ord(distro_series[0]) - 1)
        response = self.client.post(
            self.get_machine_uri(machine),
            {"op": "deploy", "hwe_kernel": bad_hwe_kernel},
        )
        assert (
            http.client.BAD_REQUEST,
            {
                "hwe_kernel": [
                    "%s is not available for %s/%s on %s."
                    % (bad_hwe_kernel, osystem, distro_series, architecture)
                ]
            },
        ) == (response.status_code, json_load_bytes(response.content))

    def test_POST_deploy_not_allowed_statuses(self, mocker, request):
        _, releases = self._make_usable_osystem(mocker, request)
        distro_series = releases[0]
        deploy_request = {"op": "deploy", "distro_series": distro_series}
        not_allowed_statuses = [
            status
            for status in NODE_STATUS_CHOICES_DICT.keys()
            if status not in [NODE_STATUS.READY, NODE_STATUS.ALLOCATED]
        ]
        for not_allowed_status in not_allowed_statuses:
            machine = factory.make_Node(
                owner=self.user,
                interface=True,
                power_type="manual",
                architecture=self._make_usable_architecture(mocker),
                status=not_allowed_status,
            )
            response = self.client.post(
                self.get_machine_uri(machine), deploy_request
            )
            assert http.client.CONFLICT == response.status_code
            error_message = response.content.decode("utf-8")
            assert (
                "Can't deploy a machine that is in the "
                f"'{NODE_STATUS_CHOICES_DICT[not_allowed_status]}' state"
            ) == error_message

    def test_POST_deploy_stores_user_data_base64_encoded(
        self, mocker, request
    ):
        rack_controller = factory.make_RackController()
        mocker.patch.object(
            node_module.RackControllerManager, "filter_by_url_accessible"
        ).return_value = [rack_controller]
        mocker.patch.object(node_module.Node, "_power_control_node")
        mocker.patch.object(node_module.Node, "_start_deployment")
        mocker.patch.object(node_module.Node, "_claim_auto_ips")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        mocker.patch.object(
            server_address, "get_maas_facing_server_addresses"
        ).return_value = [IPAddress("127.0.0.1"), IPAddress("::1")]
        client = Mock()
        client.ident = rack_controller.system_id
        mocker.patch.object(power_module, "getAllClients").return_value = [
            client
        ]
        machine = factory.make_Node_with_Interface_on_Subnet(
            owner=self.user,
            interface=True,
            power_type="virsh",
            architecture=self._make_usable_architecture(mocker),
            status=NODE_STATUS.ALLOCATED,
            bmc_connected_to=rack_controller,
        )

        # assign an IP to both the machine and the rack on the same subnet
        machine_interface = machine.get_boot_interface()
        [auto_ip] = machine_interface.ip_addresses.filter(
            alloc_type=IPADDRESS_TYPE.AUTO
        )
        ip = factory.pick_ip_in_Subnet(auto_ip.subnet)

        with post_commit_hooks:
            auto_ip.ip = ip
            auto_ip.save()
            rack_if = rack_controller.current_config.interface_set.first()

            rack_if.link_subnet(
                INTERFACE_LINK_TYPE.STATIC,
                auto_ip.subnet,
                factory.pick_ip_in_Subnet(auto_ip.subnet),
            )

        _, releases = self._make_usable_osystem(mocker, request)
        distro_series = releases[0]
        user_data = b64encode(
            b"\xff\x00\xff\xfe\xff\xff\xfe"
            + factory.make_string().encode("ascii")
        )
        response = self.client.post(
            self.get_machine_uri(machine),
            {
                "op": "deploy",
                "user_data": user_data.decode("ascii"),
                "distro_series": distro_series,
            },
        )
        assert http.client.OK == response.status_code
        assert user_data == NodeUserData.objects.get_user_data_for_user_env(
            machine
        )

    def test_POST_deploy_stores_user_data_plain_text(self, mocker, request):
        rack_controller = factory.make_RackController()
        mocker.patch.object(
            node_module.RackControllerManager, "filter_by_url_accessible"
        ).return_value = [rack_controller]
        mocker.patch.object(node_module.Node, "_power_control_node")
        mocker.patch.object(node_module.Node, "_start_deployment")
        mocker.patch.object(node_module.Node, "_claim_auto_ips")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        mocker.patch.object(
            server_address, "get_maas_facing_server_addresses"
        ).return_value = [IPAddress("127.0.0.1"), IPAddress("::1")]

        client = Mock()
        client.ident = rack_controller.system_id

        mocker.patch.object(power_module, "getAllClients").return_value = [
            client
        ]
        machine = factory.make_Node_with_Interface_on_Subnet(
            owner=self.user,
            interface=True,
            power_type="virsh",
            architecture=self._make_usable_architecture(mocker),
            status=NODE_STATUS.ALLOCATED,
            bmc_connected_to=rack_controller,
        )

        # assign an IP to both the machine and the rack on the same subnet
        machine_interface = machine.get_boot_interface()
        [auto_ip] = machine_interface.ip_addresses.filter(
            alloc_type=IPADDRESS_TYPE.AUTO
        )
        ip = factory.pick_ip_in_Subnet(auto_ip.subnet)

        with post_commit_hooks:
            auto_ip.ip = ip
            auto_ip.save()
            rack_if = rack_controller.current_config.interface_set.first()
            rack_if.link_subnet(
                INTERFACE_LINK_TYPE.STATIC,
                auto_ip.subnet,
                factory.pick_ip_in_Subnet(auto_ip.subnet),
            )

        _, releases = self._make_usable_osystem(mocker, request)
        distro_series = releases[0]
        user_data = factory.make_name("user_data")
        response = self.client.post(
            self.get_machine_uri(machine),
            {
                "op": "deploy",
                "user_data": user_data,
                "distro_series": distro_series,
            },
        )
        assert http.client.OK == response.status_code
        assert (
            user_data.encode()
            == NodeUserData.objects.get_user_data_for_user_env(machine)
        )

    def test_POST_deploy_passes_comment(self, mocker, request):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        rack_controller = factory.make_RackController()
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            power_type="virsh",
            status=NODE_STATUS.READY,
            architecture=self._make_usable_architecture(mocker),
            bmc_connected_to=rack_controller,
        )
        _, releases = self._make_usable_osystem(mocker, request)
        distro_series = releases[0]
        comment = factory.make_name("comment")
        machine_start = mocker.patch.object(node_module.Machine, "start")
        machine_start.return_value = False
        self.client.post(
            self.get_machine_uri(machine),
            {
                "op": "deploy",
                "distro_series": distro_series,
                "comment": comment,
            },
        )
        machine_start.assert_called_once_with(
            self.user,
            user_data=ANY,
            comment=comment,
        )

    def test_POST_deploy_handles_missing_comment(self, mocker, request):
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            power_type="manual",
            status=NODE_STATUS.READY,
            architecture=self._make_usable_architecture(mocker),
        )
        _, releases = self._make_usable_osystem(mocker, request)
        distro_series = releases[0]
        machine_start = mocker.patch.object(node_module.Machine, "start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        machine_start.return_value = False
        self.client.post(
            self.get_machine_uri(machine),
            {"op": "deploy", "distro_series": distro_series},
        )
        machine_start.assert_called_once_with(
            self.user,
            user_data=ANY,
            comment=None,
        )

    def test_POST_deploy_doesnt_reset_power_options_bug_1569102(
        self, admin, admin_api_client, mocker, request
    ):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        rack_controller = factory.make_RackController()
        machine = factory.make_Node(
            owner=admin,
            interface=True,
            power_type="virsh",
            status=NODE_STATUS.READY,
            architecture=self._make_usable_architecture(mocker),
            bmc_connected_to=rack_controller,
        )
        _, releases = self._make_usable_osystem(mocker, request)
        distro_series = releases[0]
        machine_start = mocker.patch.object(node_module.Machine, "start")
        machine_start.return_value = False
        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {"op": "deploy", "distro_series": distro_series},
        )
        assert http.client.OK == response.status_code, response.content
        response_content = json_load_bytes(response.content)
        assert "virsh" == response_content["power_type"]

    def test_POST_deploy_allocates_ready_machines(self, mocker, request):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        machine = factory.make_Node(
            status=NODE_STATUS.READY,
            interface=True,
            power_type="manual",
            architecture=self._make_usable_architecture(mocker),
        )
        _, releases = self._make_usable_osystem(mocker, request)
        distro_series = releases[0]
        deploy_request = {"op": "deploy", "distro_series": distro_series}
        response = self.client.post(
            self.get_machine_uri(machine), deploy_request
        )
        assert http.client.OK == response.status_code

    def test_POST_deploy_rejects_node_owned_by_another_user(
        self, mocker, request
    ):
        mocker.patch.object(node_module.Node, "_start")
        user2 = factory.make_User()
        machine = factory.make_Node(
            status=NODE_STATUS.READY,
            owner=user2,
            interface=True,
            power_type="manual",
            architecture=self._make_usable_architecture(mocker),
        )
        _, releases = self._make_usable_osystem(mocker, request)
        distro_series = releases[0]
        deploy_request = {"op": "deploy", "distro_series": distro_series}
        response = self.client.post(
            self.get_machine_uri(machine), deploy_request
        )
        assert http.client.FORBIDDEN == response.status_code

    def test_POST_deploy_passes_agent_name(self, mocker, request):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        machine = factory.make_Node(
            status=NODE_STATUS.READY,
            interface=True,
            power_type="manual",
            architecture=self._make_usable_architecture(mocker),
        )
        _, releases = self._make_usable_osystem(mocker, request)
        distro_series = releases[0]
        deploy_request = {
            "op": "deploy",
            "distro_series": distro_series,
            "agent_name": factory.make_name(),
            "comment": factory.make_name(),
        }
        response = self.client.post(
            self.get_machine_uri(machine), deploy_request
        )
        assert http.client.OK == response.status_code
        machine = reload_object(machine)
        assert deploy_request["agent_name"] == machine.agent_name

    def test_POST_deploy_passes_comment_on_acquire(self, mocker, request):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        machine_method = mocker.patch.object(node_module.Machine, "acquire")
        machine = factory.make_Node(
            status=NODE_STATUS.READY,
            owner=self.user,
            interface=True,
            power_type="manual",
            architecture=self._make_usable_architecture(mocker),
        )
        _, releases = self._make_usable_osystem(mocker, request)
        distro_series = releases[0]
        deploy_request = {
            "op": "deploy",
            "distro_series": distro_series,
            "agent_name": factory.make_name(),
            "comment": factory.make_name(),
        }
        self.client.post(self.get_machine_uri(machine), deploy_request)
        machine_method.assert_called_once_with(
            ANY,
            agent_name=ANY,
            bridge_all=False,
            bridge_type=BRIDGE_TYPE.STANDARD,
            bridge_fd=0,
            bridge_stp=False,
            comment=deploy_request["comment"],
        )

    def test_POST_deploy_passes_bridge_settings(self, mocker, request):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        machine_method = mocker.patch.object(node_module.Machine, "acquire")
        machine = factory.make_Node(
            status=NODE_STATUS.READY,
            owner=self.user,
            interface=True,
            power_type="manual",
            architecture=self._make_usable_architecture(mocker),
        )
        _, releases = self._make_usable_osystem(mocker, request)
        distro_series = releases[0]
        deploy_request = {
            "op": "deploy",
            "distro_series": distro_series,
            "bridge_all": True,
            "bridge_type": BRIDGE_TYPE.OVS,
            "bridge_stp": True,
            "bridge_fd": 7,
        }
        self.client.post(self.get_machine_uri(machine), deploy_request)
        machine_method.assert_called_once_with(
            ANY,
            agent_name=ANY,
            bridge_all=True,
            bridge_type=BRIDGE_TYPE.OVS,
            bridge_fd=7,
            bridge_stp=True,
            comment=None,
        )

    def test_POST_deploy_stores_vcenter_registration_by_default(
        self, admin, admin_api_client, mocker, request
    ):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        machine = factory.make_Node(
            owner=admin,
            interface=True,
            power_type="manual",
            status=NODE_STATUS.READY,
            architecture=self._make_usable_architecture(mocker),
        )
        _, releases = self._make_usable_osystem(
            mocker, request, osystem_name="esxi", releases=["6.7"]
        )
        distro_series = releases[0]
        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {"op": "deploy", "distro_series": distro_series},
        )
        assert (http.client.OK, machine.system_id) == (
            response.status_code,
            json_load_bytes(response.content)["system_id"],
        )
        assert machine.nodemetadata_set.filter(
            key="vcenter_registration"
        ).exists()

    def test_POST_deploy_stores_vcenter_registration_when_defined(
        self, admin, admin_api_client, mocker, request
    ):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        machine = factory.make_Node(
            owner=admin,
            interface=True,
            power_type="manual",
            status=NODE_STATUS.READY,
            architecture=self._make_usable_architecture(mocker),
        )
        _, releases = self._make_usable_osystem(
            mocker, request, osystem_name="esxi", releases=["6.7"]
        )
        distro_series = releases[0]
        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {
                "op": "deploy",
                "distro_series": distro_series,
                "vcenter_registration": True,
            },
        )
        assert (http.client.OK, machine.system_id) == (
            response.status_code,
            json_load_bytes(response.content)["system_id"],
        )
        assert machine.nodemetadata_set.filter(
            key="vcenter_registration"
        ).exists()

    def test_POST_deploy_removes_vcenter_registration_when_false(
        self, admin, admin_api_client, mocker, request
    ):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        machine = factory.make_Node(
            owner=admin,
            interface=True,
            power_type="manual",
            status=NODE_STATUS.READY,
            architecture=self._make_usable_architecture(mocker),
        )
        machine.nodemetadata_set.create(
            key="vcenter_registration", value="True"
        )
        _, releases = self._make_usable_osystem(
            mocker, request, osystem_name="esxi", releases=["6.7"]
        )
        distro_series = releases[0]
        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {
                "op": "deploy",
                "distro_series": distro_series,
                "vcenter_registration": False,
            },
        )
        assert (http.client.OK, machine.system_id) == (
            response.status_code,
            json_load_bytes(response.content)["system_id"],
        )
        assert not machine.nodemetadata_set.filter(
            key="vcenter_registration"
        ).exists()

    def test_POST_deploy_sets_vcenter_registration_only_when_esxi(
        self, admin, admin_api_client, mocker, request
    ):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        machine = factory.make_Node(
            owner=admin,
            interface=True,
            power_type="manual",
            status=NODE_STATUS.READY,
            architecture=self._make_usable_architecture(mocker),
        )
        _, releases = self._make_usable_osystem(mocker, request)
        distro_series = releases[0]
        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {
                "op": "deploy",
                "distro_series": distro_series,
                "vcenter_registration": True,
            },
        )
        assert (http.client.OK, machine.system_id) == (
            response.status_code,
            json_load_bytes(response.content)["system_id"],
        )
        assert not machine.nodemetadata_set.filter(
            key="vcenter_registration"
        ).exists()

    def test_POST_deploy_distro_series(self, mocker):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        # The api allows the updating of a Machine.
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            power_type="manual",
            status=NODE_STATUS.READY,
            architecture=self._make_usable_architecture(mocker),
        )
        response = self.client.post(
            self.get_machine_uri(machine),
            {"op": "deploy", "distro_series": "ubuntu/noble"},
        )
        assert http.client.OK == response.status_code
        assert (
            machine.system_id == json_load_bytes(response.content)["system_id"]
        )

    def test_POST_deploy_enable_hw_sync_defaults_to_False(self, mocker):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            power_type="manual",
            status=NODE_STATUS.READY,
            architecture=self._make_usable_architecture(mocker),
        )
        response = self.client.post(
            self.get_machine_uri(machine),
            {"op": "deploy", "distro_series": "ubuntu/noble"},
        )
        assert http.client.OK == response.status_code
        machine.refresh_from_db()
        assert not machine.enable_hw_sync

    def test_POST_deploy_set_enable_hardware_sync(self, mocker, request):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            power_type="manual",
            status=NODE_STATUS.READY,
            architecture=self._make_usable_architecture(mocker),
        )
        osystem, releases = self._make_usable_osystem(
            mocker, request, osystem_name="ubuntu", releases=["noble"]
        )
        response = self.client.post(
            self.get_machine_uri(machine),
            {
                "op": "deploy",
                "distro_series": f"{osystem}/{releases[0]}",
                "enable_hw_sync": True,
            },
        )
        assert http.client.OK == response.status_code
        machine.refresh_from_db()
        assert machine.enable_hw_sync

    def test_POST_multiple_deploy_override_options_ephemeral_deploy(
        self, mocker, request
    ):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        osystem = Config.objects.get_config("default_osystem")
        distro_series = Config.objects.get_config("default_distro_series")
        self._make_usable_osystem(
            mocker, request, osystem_name=osystem, releases=[distro_series]
        )
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            distro_series=distro_series,
            osystem=osystem,
            architecture=self._make_usable_architecture(mocker),
        )

        response = self.client.post(
            self.get_machine_uri(machine),
            {"op": "deploy", "ephemeral_deploy": True},
        )
        assert http.client.OK == response.status_code
        response_info = json_load_bytes(response.content)
        assert response_info["ephemeral_deploy"]

        response = self.client.post(
            self.get_machine_uri(machine), {"op": "deploy"}
        )
        assert http.client.OK == response.status_code
        response_info = json_load_bytes(response.content)
        assert not response_info["ephemeral_deploy"]

    def test_POST_multiple_deploy_override_options_hw_sync(
        self, mocker, request
    ):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        osystem = Config.objects.get_config("default_osystem")
        distro_series = Config.objects.get_config("default_distro_series")
        self._make_usable_osystem(
            mocker, request, osystem_name=osystem, releases=[distro_series]
        )
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            distro_series=distro_series,
            osystem=osystem,
            architecture=self._make_usable_architecture(mocker),
        )

        response = self.client.post(
            self.get_machine_uri(machine),
            {"op": "deploy", "enable_hw_sync": True},
        )
        assert http.client.OK == response.status_code
        response_info = json_load_bytes(response.content)
        assert response_info["enable_hw_sync"]

        response = self.client.post(
            self.get_machine_uri(machine), {"op": "deploy"}
        )
        assert http.client.OK == response.status_code
        response_info = json_load_bytes(response.content)
        assert not response_info["enable_hw_sync"]

    def test_POST_multiple_deploy_override_options_distro_series(
        self, mocker, request
    ):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        osystem = Config.objects.get_config("default_osystem")
        _, releases = self._make_usable_osystem(mocker, request)
        default_distro_series = Config.objects.get_config(
            "default_distro_series"
        )
        distro_series = (
            releases[0]
            if releases[0] != default_distro_series
            else releases[1]
        )

        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            distro_series=distro_series,
            osystem=osystem,
            architecture=self._make_usable_architecture(mocker),
        )

        response = self.client.post(
            self.get_machine_uri(machine),
            {"op": "deploy", "distro_series": distro_series},
        )
        assert http.client.OK == response.status_code
        response_info = json_load_bytes(response.content)
        assert response_info["distro_series"] == distro_series

        response = self.client.post(
            self.get_machine_uri(machine), {"op": "deploy"}
        )
        assert http.client.OK == response.status_code
        response_info = json_load_bytes(response.content)
        assert response_info["distro_series"] == default_distro_series

    def test_POST_deploy_default_enable_kernel_crash_dumps(
        self, mocker, request
    ):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        Config.objects.set_config(name="enable_kernel_crash_dump", value=True)
        osystem = Config.objects.get_config("default_osystem")
        distro_series = Config.objects.get_config("default_distro_series")
        self._make_usable_osystem(
            mocker, request, osystem_name=osystem, releases=[distro_series]
        )
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            distro_series=distro_series,
            osystem=osystem,
            architecture=self._make_usable_architecture(
                mocker, arch_name="amd64"
            ),
            with_boot_disk=False,
            enable_kernel_crash_dump=False,
            cpu_count=4,
            memory=6 * 1024,
        )
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "deploy"}
        )
        response_info = json_load_bytes(response.content)
        assert response.status_code == http.client.OK
        assert response_info["enable_kernel_crash_dump"] is True
        machine.refresh_from_db()
        assert machine.enable_kernel_crash_dump

    def test_POST_deploy_sets_enable_kernel_crash_dumps(self, mocker, request):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        osystem = Config.objects.get_config("default_osystem")
        distro_series = Config.objects.get_config("default_distro_series")
        self._make_usable_osystem(
            mocker, request, osystem_name=osystem, releases=[distro_series]
        )
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            distro_series=distro_series,
            osystem=osystem,
            architecture=self._make_usable_architecture(
                mocker, arch_name="amd64"
            ),
            with_boot_disk=False,
            enable_kernel_crash_dump=False,
            cpu_count=4,
            memory=6 * 1024,
        )
        response = self.client.post(
            self.get_machine_uri(machine),
            {"op": "deploy", "enable_kernel_crash_dump": True},
        )
        response_info = json_load_bytes(response.content)
        assert response.status_code == http.client.OK
        assert response_info["enable_kernel_crash_dump"] is True
        machine.refresh_from_db()
        assert machine.enable_kernel_crash_dump

    def test_POST_deploy_sets_enable_kernel_crash_dumps_overrides_default(
        self, mocker, request
    ):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        Config.objects.set_config("enable_kernel_crash_dump", True)
        osystem = Config.objects.get_config("default_osystem")
        distro_series = Config.objects.get_config("default_distro_series")
        self._make_usable_osystem(
            mocker, request, osystem_name=osystem, releases=[distro_series]
        )
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            distro_series=distro_series,
            osystem=osystem,
            architecture=self._make_usable_architecture(
                mocker, arch_name="amd64"
            ),
            with_boot_disk=False,
            enable_kernel_crash_dump=False,
            cpu_count=4,
            memory=6 * 1024,
        )
        response = self.client.post(
            self.get_machine_uri(machine),
            {"op": "deploy", "enable_kernel_crash_dump": False},
        )
        response_info = json_load_bytes(response.content)
        assert response.status_code == http.client.OK
        assert response_info["enable_kernel_crash_dump"] is False
        machine.refresh_from_db()
        assert not machine.enable_kernel_crash_dump

    def test_POST_deploy_sets_enable_kernel_crash_dumps_requirements_not_satisfied(
        self, mocker, request
    ):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        osystem = Config.objects.get_config("default_osystem")
        distro_series = Config.objects.get_config("default_distro_series")
        self._make_usable_osystem(
            mocker, request, osystem_name=osystem, releases=[distro_series]
        )
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            distro_series=distro_series,
            osystem=osystem,
            architecture=self._make_usable_architecture(
                mocker, arch_name="amd64"
            ),
            with_boot_disk=False,
            enable_kernel_crash_dump=False,
            cpu_count=3,  # not enough cpu
            memory=6 * 1024,
        )
        response = self.client.post(
            self.get_machine_uri(machine),
            {"op": "deploy", "enable_kernel_crash_dump": True},
        )
        response_info = json_load_bytes(response.content)
        assert response.status_code == http.client.OK
        assert response_info["enable_kernel_crash_dump"] is False
        machine.refresh_from_db()
        assert not machine.enable_kernel_crash_dump

    def test_POST_deploy_sets_enable_kernel_crash_dumps_arch_invalid(
        self, mocker, request
    ):
        mocker.patch.object(node_module.Node, "_start")
        mocker.patch.object(machines_module, "get_curtin_merged_config")
        osystem = Config.objects.get_config("default_osystem")
        distro_series = Config.objects.get_config("default_distro_series")
        self._make_usable_osystem(
            mocker, request, osystem_name=osystem, releases=[distro_series]
        )
        machine = factory.make_Node(
            owner=self.user,
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            distro_series=distro_series,
            osystem=osystem,
            architecture=self._make_usable_architecture(
                mocker, arch_name="armhf"
            ),
            with_boot_disk=False,
            enable_kernel_crash_dump=False,
            cpu_count=4,
            memory=6 * 1024,
        )
        response = self.client.post(
            self.get_machine_uri(machine),
            {"op": "deploy", "enable_kernel_crash_dump": True},
        )
        response_info = json_load_bytes(response.content)
        assert response.status_code == http.client.OK
        assert response_info["enable_kernel_crash_dump"] is False
        machine.refresh_from_db()
        assert not machine.enable_kernel_crash_dump

    def test_POST_release_releases_owned_machine(self, mocker):
        mocker.patch.object(node_module.Machine, "_stop")
        owned_statuses = [NODE_STATUS.RESERVED, NODE_STATUS.ALLOCATED]
        owned_machines = [
            factory.make_Node(
                owner=self.user,
                status=status,
                power_type="virsh",
                power_state=POWER_STATE.ON,
            )
            for status in owned_statuses
        ]
        responses = [
            self.client.post(self.get_machine_uri(machine), {"op": "release"})
            for machine in owned_machines
        ]
        assert [http.client.OK] * len(owned_machines) == [
            response.status_code for response in responses
        ]
        assert [NODE_STATUS.RELEASING] * len(owned_machines) == [
            machine.status for machine in reload_objects(Node, owned_machines)
        ]

    def test_POST_release_fails_with_locked(self):
        machine = factory.make_Node(
            owner=self.user,
            status=NODE_STATUS.ALLOCATED,
            locked=True,
            power_type="virsh",
            power_state=POWER_STATE.ON,
        )
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "release"}
        )
        assert http.client.FORBIDDEN == response.status_code

    def test_POST_release_starts_disk_erasing(self, mocker):
        mocker.patch.object(
            node_module.Node, "_start", return_value=defer.succeed(None)
        )
        mocker.patch.object(
            node_module.Machine,
            "_start_disk_erasing_async",
            return_value=defer.succeed(None),
        )
        mocker.patch.object(
            node_module, "asynchronous", lambda function: function
        )
        mocker.patch.object(
            node_module.Node,
            "_power_control_node",
            return_value=defer.succeed(None),
        )
        machine = factory.make_Node(
            owner=self.user,
            status=NODE_STATUS.DEPLOYED,
            power_type="virsh",
            power_state=POWER_STATE.OFF,
        )
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "release", "erase": "true"}
        )
        assert http.client.OK == response.status_code
        assert NODE_STATUS.DISK_ERASING == reload_object(machine).status

    def test_POST_release_releases_failed_machine(self, mocker):
        mocker.patch.object(node_module.Machine, "_stop")
        owned_machine = factory.make_Node(
            owner=self.user,
            status=NODE_STATUS.FAILED_DEPLOYMENT,
            power_type="ipmi",
            power_state=POWER_STATE.ON,
        )
        response = self.client.post(
            self.get_machine_uri(owned_machine), {"op": "release"}
        )
        assert http.client.OK == response.status_code, response.content
        owned_machine = Machine.objects.get(id=owned_machine.id)
        assert owned_machine.status == NODE_STATUS.RELEASING
        assert owned_machine.owner == self.user

    def test_POST_release_does_nothing_for_ready_machine(self):
        machine = factory.make_Node_with_Interface_on_Subnet(
            status=NODE_STATUS.READY
        )
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "release"}
        )
        assert http.client.OK == response.status_code
        assert NODE_STATUS.READY == reload_object(machine).status

    def test_POST_release_rejects_other_node_types(self):
        node = factory.make_Node_with_Interface_on_Subnet(
            owner=self.user,
            node_type=factory.pick_choice(
                NODE_TYPE_CHOICES, but_not=[NODE_TYPE.MACHINE]
            ),
        )
        response = self.client.post(
            self.get_machine_uri(node), {"op": "release"}
        )
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_POST_release_on_ready_is_noop(self):
        machine = factory.make_Node(status=NODE_STATUS.READY)
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "release"}
        )
        assert http.client.OK == response.status_code

    def test_POST_release_fails_for_other_machine_states(self):
        releasable_statuses = {
            NODE_STATUS.RELEASING,
            NODE_STATUS.READY,
        } | RELEASABLE_STATUSES
        unreleasable_statuses = [
            status
            for status in map_enum(NODE_STATUS).values()
            if status not in releasable_statuses
        ]
        machines = [
            factory.make_Node(status=status, owner=self.user)
            for status in unreleasable_statuses
        ]
        responses = [
            self.client.post(self.get_machine_uri(machine), {"op": "release"})
            for machine in machines
        ]
        assert [http.client.CONFLICT] * len(unreleasable_statuses) == [
            response.status_code for response in responses
        ]
        assert sorted(unreleasable_statuses) == sorted(
            machine.status for machine in reload_objects(Node, machines)
        )

    def test_POST_release_in_wrong_state_reports_current_state(self):
        machine = factory.make_Node(
            status=NODE_STATUS.RETIRED, owner=self.user
        )
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "release"}
        )
        assert (
            http.client.CONFLICT,
            "Machine cannot be released in its current state ('Retired').",
        ) == (
            response.status_code,
            response.content.decode(settings.DEFAULT_CHARSET),
        )

    def test_POST_release_rejects_request_from_unauthorized_user(self):
        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=factory.make_User()
        )
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "release"}
        )
        assert http.client.FORBIDDEN == response.status_code
        assert NODE_STATUS.ALLOCATED == reload_object(machine).status

    def test_POST_release_allows_admin_to_release_anyones_machine(
        self, admin, admin_api_client, mocker
    ):
        mocker.patch.object(node_module.Machine, "_stop")
        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED,
            owner=factory.make_User(),
            power_type="ipmi",
            power_state=POWER_STATE.ON,
        )
        response = admin_api_client.post(
            self.get_machine_uri(machine), {"op": "release"}
        )
        assert http.client.OK == response.status_code, response.content
        assert NODE_STATUS.RELEASING == reload_object(machine).status

    def test_POST_release_combines_with_allocate(self, mocker):
        mocker.patch.object(node_module.Machine, "_stop")
        machine = factory.make_Node(
            status=NODE_STATUS.READY,
            power_type="ipmi",
            power_state=POWER_STATE.ON,
            with_boot_disk=True,
        )
        response = self.client.post(
            reverse("machines_handler"), {"op": "allocate"}
        )
        assert NODE_STATUS.ALLOCATED == reload_object(machine).status
        machine_uri = json_load_bytes(response.content)["resource_uri"]
        response = self.client.post(machine_uri, {"op": "release"})
        assert http.client.OK == response.status_code, response.content
        assert NODE_STATUS.RELEASING == reload_object(machine).status

    def test_POST_allocate_passes_comment(self, mocker):
        factory.make_Node(
            status=NODE_STATUS.READY,
            power_type="ipmi",
            power_state=POWER_STATE.ON,
            with_boot_disk=True,
        )
        machine_method = mocker.patch.object(node_module.Machine, "acquire")
        comment = factory.make_name("comment")
        self.client.post(
            reverse("machines_handler"), {"op": "allocate", "comment": comment}
        )
        machine_method.assert_called_once_with(
            ANY,
            agent_name=ANY,
            bridge_all=False,
            bridge_type=BRIDGE_TYPE.STANDARD,
            bridge_fd=False,
            bridge_stp=False,
            comment=comment,
        )

    def test_POST_allocate_handles_missing_comment(self, mocker):
        factory.make_Node(
            status=NODE_STATUS.READY,
            power_type="ipmi",
            power_state=POWER_STATE.ON,
            with_boot_disk=True,
        )
        machine_method = mocker.patch.object(node_module.Machine, "acquire")
        self.client.post(reverse("machines_handler"), {"op": "allocate"})
        machine_method.assert_called_once_with(
            ANY,
            agent_name=ANY,
            bridge_all=False,
            bridge_type=BRIDGE_TYPE.STANDARD,
            bridge_fd=0,
            bridge_stp=False,
            comment=None,
        )

    def test_POST_release_frees_hwe_kernel(self, mocker):
        mocker.patch.object(node_module.Machine, "_stop")
        machine = factory.make_Node(
            owner=self.user,
            status=NODE_STATUS.ALLOCATED,
            power_type="ipmi",
            power_state=POWER_STATE.ON,
            hwe_kernel="hwe-v",
        )
        assert "hwe-v" == reload_object(machine).hwe_kernel
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "release"}
        )
        assert http.client.OK == response.status_code, response.content
        assert NODE_STATUS.RELEASING == reload_object(machine).status
        assert reload_object(machine).hwe_kernel is None

    def test_POST_release_passes_comment(
        self, admin, admin_api_client, mocker
    ):
        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED,
            owner=factory.make_User(),
            power_type="ipmi",
            power_state=POWER_STATE.OFF,
        )
        comment = factory.make_name("comment")
        machine_release = mocker.patch.object(
            node_module.Machine, "start_releasing"
        )
        admin_api_client.post(
            self.get_machine_uri(machine),
            {"op": "release", "comment": comment},
        )
        machine_release.assert_called_once_with(
            user=admin,
            comment=comment,
            scripts=[],
            script_input={},
            force=False,
        )

    def test_POST_release_passes_erase_options(
        self, admin, admin_api_client, mocker
    ):
        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED,
            owner=factory.make_User(),
            power_type="ipmi",
            power_state=POWER_STATE.OFF,
        )
        secure_erase = factory.pick_bool()
        quick_erase = factory.pick_bool()
        machine_release = mocker.patch.object(
            node_module.Machine, "start_releasing"
        )
        admin_api_client.post(
            self.get_machine_uri(machine),
            {
                "op": "release",
                "erase": True,
                "secure_erase": secure_erase,
                "quick_erase": quick_erase,
            },
        )
        machine_release.assert_called_once_with(
            user=admin,
            comment="",
            scripts=["wipe-disks"],
            script_input={
                "wipe-disks": {
                    "secure_erase": secure_erase,
                    "quick_erase": quick_erase,
                }
            },
            force=False,
        )

    def test_POST_release_passes_force_option(
        self, admin, admin_api_client, mocker
    ):
        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED,
            owner=factory.make_User(),
            power_type="ipmi",
            power_state=POWER_STATE.OFF,
        )
        force = factory.pick_bool()
        machine_release = mocker.patch.object(
            node_module.Machine, "start_releasing"
        )
        admin_api_client.post(
            self.get_machine_uri(machine), {"op": "release", "force": force}
        )
        machine_release.assert_called_once_with(
            user=admin,
            comment="",
            scripts=[],
            script_input={},
            force=force,
        )

    def test_POST_release_handles_missing_comment(
        self, admin, admin_api_client, mocker
    ):
        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED,
            owner=factory.make_User(),
            power_type="ipmi",
            power_state=POWER_STATE.OFF,
        )
        machine_release = mocker.patch.object(
            node_module.Machine, "start_releasing"
        )
        admin_api_client.post(self.get_machine_uri(machine), {"op": "release"})
        machine_release.assert_called_once_with(
            user=admin,
            comment="",
            scripts=[],
            script_input={},
            force=False,
        )

    def test_POST_commission_commissions_machine(
        self, admin, admin_api_client, mocker
    ):
        mocker.patch.object(
            node_module.Node,
            "_start_commissioning_async",
            return_value=defer.succeed(None),
        )
        mocker.patch.object(
            node_module.Node, "_start"
        ).return_value = defer.succeed(None)
        machine = factory.make_Node(
            status=NODE_STATUS.READY,
            owner=admin,
            power_state=POWER_STATE.OFF,
            interface=True,
        )
        response = admin_api_client.post(
            self.get_machine_uri(machine), {"op": "commission"}
        )
        assert http.client.OK == response.status_code
        assert NODE_STATUS.COMMISSIONING == reload_object(machine).status

    def test_POST_commission_commissions_machine_with_options(
        self, admin, admin_api_client, mocker
    ):
        load_builtin_scripts()
        factory.make_Script(
            script_type=SCRIPT_TYPE.COMMISSIONING, tags=["bmc-config"]
        )
        mocker.patch.object(
            node_module.Node, "_start", return_value=defer.succeed(None)
        )
        mocker.patch.object(
            node_module.Node,
            "_start_commissioning_async",
            return_value=defer.succeed(None),
        )
        machine = factory.make_Node(
            status=NODE_STATUS.READY,
            owner=admin,
            power_state=POWER_STATE.OFF,
            interface=True,
        )

        commissioning_scripts = [
            factory.make_Script(script_type=SCRIPT_TYPE.COMMISSIONING)
            for _ in range(10)
        ]
        commissioning_script_selected_by_tag = choice(commissioning_scripts)
        commissioning_script_selected_by_name = choice(commissioning_scripts)
        expected_commissioning_scripts = list(NODE_INFO_SCRIPTS)
        expected_commissioning_scripts.append(
            commissioning_script_selected_by_tag.name
        )
        expected_commissioning_scripts.append(
            commissioning_script_selected_by_name.name
        )

        testing_scripts = [
            factory.make_Script(script_type=SCRIPT_TYPE.TESTING)
            for _ in range(10)
        ]
        testing_script_selected_by_tag = choice(testing_scripts)
        testing_script_selected_by_name = choice(testing_scripts)
        expected_testing_scripts = [
            testing_script_selected_by_tag.name,
            testing_script_selected_by_name.name,
        ]

        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {
                "op": "commission",
                "enable_ssh": "true",
                "skip_bmc_config": 1,
                "skip_networking": 1,
                "commissioning_scripts": ",".join(
                    [
                        choice(
                            [
                                tag
                                for tag in commissioning_script_selected_by_tag.tags
                                if "tag" in tag
                            ]
                        ),
                        commissioning_script_selected_by_name.name,
                    ]
                ),
                "testing_scripts": ",".join(
                    [
                        choice(
                            [
                                tag
                                for tag in testing_script_selected_by_tag.tags
                                if "tag" in tag
                            ]
                        ),
                        testing_script_selected_by_name.name,
                    ]
                ),
            },
        )
        assert http.client.OK == response.status_code
        machine = reload_object(machine)
        commissioning_script_set = machine.current_commissioning_script_set
        testing_script_set = machine.current_testing_script_set
        assert machine.enable_ssh
        assert machine.skip_networking
        assert set(expected_commissioning_scripts) == {
            script_result.name for script_result in commissioning_script_set
        }
        assert set(expected_testing_scripts) == {
            script_result.name for script_result in testing_script_set
        }

    def test_POST_lock_deployed(self):
        machine = factory.make_Node(
            status=NODE_STATUS.DEPLOYED, owner=self.user
        )
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "lock"}
        )
        assert http.client.OK == response.status_code
        machine = reload_object(machine)
        assert machine.locked

    def test_POST_lock_with_comment(self, mocker):
        machine = factory.make_Node(
            status=NODE_STATUS.DEPLOYED, owner=self.user
        )
        node_lock = mocker.patch.object(node_module.Node, "lock")
        comment = factory.make_name("comment")
        self.client.post(
            self.get_machine_uri(machine), {"op": "lock", "comment": comment}
        )
        node_lock.assert_called_once_with(self.user, comment=comment)

    def test_POST_lock_not_deployed(self):
        machine = factory.make_Node(status=NODE_STATUS.READY, owner=self.user)
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "lock"}
        )
        assert http.client.CONFLICT == response.status_code
        machine = reload_object(machine)
        assert not machine.locked

    def test_POST_lock_locked(self):
        machine = factory.make_Node(
            status=NODE_STATUS.DEPLOYED, locked=True, owner=self.user
        )
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "lock"}
        )
        assert http.client.CONFLICT == response.status_code

    def test_POST_unlock(self):
        machine = factory.make_Node(locked=True, owner=self.user)
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "unlock"}
        )
        assert http.client.OK == response.status_code
        machine = reload_object(machine)
        assert not machine.locked

    def test_POST_unlock_with_comment(self, mocker):
        machine = factory.make_Node(locked=True, owner=self.user)
        node_unlock = mocker.patch.object(node_module.Node, "unlock")
        comment = factory.make_name("comment")
        self.client.post(
            self.get_machine_uri(machine), {"op": "unlock", "comment": comment}
        )
        node_unlock.assert_called_once_with(self.user, comment=comment)

    def test_POST_unlock_unlocked(self):
        machine = factory.make_Node(owner=self.user)
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "unlock"}
        )
        assert http.client.CONFLICT == response.status_code

    def test_PUT_updates_machine_superuser(
        self, admin, admin_api_client, mocker
    ):
        # The api allows the updating of a Machine.
        machine = factory.make_Node(
            hostname="diane",
            owner=self.user,
            architecture=self._make_usable_architecture(mocker),
            power_type="manual",
        )
        new_description = factory.make_name("description")
        response = admin_api_client.put(
            self.get_machine_uri(machine),
            {"hostname": "francis", "description": new_description},
        )
        parsed_result = json_load_bytes(response.content)

        assert http.client.OK == response.status_code
        domain_name = Domain.objects.get_default_domain().name
        assert "francis.%s" % domain_name == parsed_result["fqdn"]
        assert new_description == parsed_result["description"]
        assert new_description == reload_object(machine).description
        assert 0 == Machine.objects.filter(hostname="diane").count()
        assert 1 == Machine.objects.filter(hostname="francis").count()

    def test_PUT_not_updates_machine_non_superuser(self, mocker):
        machine = factory.make_Node(
            hostname="diane",
            owner=self.user,
            architecture=self._make_usable_architecture(mocker),
            power_type="manual",
        )
        response = self.client.put(
            self.get_machine_uri(machine), {"hostname": "francis"}
        )

        assert http.client.FORBIDDEN == response.status_code

    def test_PUT_denied_if_locked(self, admin, admin_api_client, mocker):
        machine = factory.make_Node(
            hostname="foo",
            owner=self.user,
            status=NODE_STATUS.DEPLOYED,
            locked=True,
            architecture=self._make_usable_architecture(mocker),
            power_type="manual",
        )
        response = admin_api_client.put(
            self.get_machine_uri(machine), {"hostname": "bar"}
        )
        assert http.client.FORBIDDEN == response.status_code

    def test_PUT_omitted_hostname(self, admin, admin_api_client, mocker):
        hostname = factory.make_name("hostname")
        arch = self._make_usable_architecture(mocker)
        machine = factory.make_Node(
            hostname=hostname,
            owner=self.user,
            architecture=arch,
            power_type="manual",
        )
        response = admin_api_client.put(
            self.get_machine_uri(machine), {"architecture": arch}
        )
        assert http.client.OK == response.status_code, response.content
        assert Machine.objects.filter(hostname=hostname).exists()

    def test_PUT_rejects_other_node_types(self, admin, admin_api_client):
        node = factory.make_Node_with_Interface_on_Subnet(
            owner=self.user,
            node_type=factory.pick_choice(
                NODE_TYPE_CHOICES, but_not=[NODE_TYPE.MACHINE]
            ),
        )
        response = admin_api_client.put(self.get_machine_uri(node))
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_PUT_ignores_unknown_fields(self, admin, admin_api_client, mocker):
        machine = factory.make_Node(
            owner=self.user,
            architecture=self._make_usable_architecture(mocker),
            power_type="manual",
        )
        field = factory.make_string()
        response = admin_api_client.put(
            self.get_machine_uri(machine), {field: factory.make_string()}
        )

        assert http.client.OK == response.status_code

    def test_PUT_admin_can_change_power_type(
        self, admin, admin_api_client, mocker
    ):
        original_power_type = "ipmi"
        new_power_type = "redfish"
        machine = factory.make_Node(
            owner=self.user,
            power_type=original_power_type,
            architecture=self._make_usable_architecture(mocker),
            interface=True,
        )
        response = admin_api_client.put(
            self.get_machine_uri(machine),
            {
                "power_type": new_power_type,
                "power_parameters_skip_check": "true",
            },
        )

        assert http.client.OK == response.status_code
        assert new_power_type == reload_object(machine).power_type

    def test_PUT_non_admin_cannot_change_power_type(self):
        original_power_type = "ipmi"
        new_power_type = "redfish"
        machine = factory.make_Node(
            owner=self.user, power_type=original_power_type
        )
        response = self.client.put(
            self.get_machine_uri(machine), {"power_type": new_power_type}
        )

        assert http.client.FORBIDDEN == response.status_code
        assert original_power_type == reload_object(machine).power_type

    def test_resource_uri_points_back_at_machine(
        self, admin, admin_api_client, mocker
    ):
        # When a Machine is returned by the API, the field 'resource_uri'
        # provides the URI for this Machine.
        machine = factory.make_Node(
            hostname="diane",
            owner=self.user,
            architecture=self._make_usable_architecture(mocker),
            power_type="manual",
        )
        response = admin_api_client.put(
            self.get_machine_uri(machine), {"hostname": "francis"}
        )
        parsed_result = json_load_bytes(response.content)

        assert http.client.OK == response.status_code
        assert (
            reverse("machine_handler", args=[parsed_result["system_id"]])
            == parsed_result["resource_uri"]
        )

    def test_get_token_with_token(self, admin, admin_api_client):
        machine = factory.make_Node()
        token = NodeKey.objects.get_token_for_node(machine)
        response = admin_api_client.get(
            self.get_machine_uri(machine), {"op": "get_token"}
        )
        assert json_load_bytes(response.content) == {
            "token_key": token.key,
            "token_secret": token.secret,
            "consumer_key": token.consumer.key,
        }

    def test_get_token_no_token(self, admin, admin_api_client):
        machine = factory.make_Node()
        response = admin_api_client.get(
            self.get_machine_uri(machine), {"op": "get_token"}
        )
        assert json_load_bytes(response.content) is None

    def test_get_token_no_admin(self):
        machine = factory.make_Node()
        NodeKey.objects.get_token_for_node(machine)
        response = self.client.get(
            self.get_machine_uri(machine), {"op": "get_token"}
        )
        assert http.client.FORBIDDEN == response.status_code

    def test_PUT_rejects_invalid_data(self, admin, admin_api_client, mocker):
        # If the data provided to update a machine is invalid, a 'Bad request'
        # response is returned.
        machine = factory.make_Node(
            hostname="diane",
            owner=self.user,
            architecture=self._make_usable_architecture(mocker),
            power_type="manual",
        )
        response = admin_api_client.put(
            self.get_machine_uri(machine), {"hostname": "."}
        )
        parsed_result = json_load_bytes(response.content)

        assert http.client.BAD_REQUEST == response.status_code
        assert {
            "hostname": [
                "DNS name contains an empty label.",
                "Nonexistant domain.",
            ]
        } == parsed_result

    def test_PUT_refuses_to_update_nonexistent_machine(
        self, admin, admin_api_client
    ):
        # When updating a Machine, the api returns a 'Not Found' (404) error
        # if no machine is found.
        url = reverse("machine_handler", args=["invalid-uuid"])
        response = admin_api_client.put(url)

        assert http.client.NOT_FOUND == response.status_code

    def test_PUT_updates_power_parameters_field(
        self, admin, admin_api_client, mocker
    ):
        # The api allows the updating of a Machine's power_parameters field.
        machine = factory.make_Node(
            owner=self.user,
            power_type="virsh",
            architecture=self._make_usable_architecture(mocker),
        )
        # Create a power_parameter valid for the selected power_type.
        new_power_id = factory.make_name("power_id")
        new_power_pass = factory.make_name("power_pass")
        new_power_address = factory.make_ipv4_address()
        response = admin_api_client.put(
            self.get_machine_uri(machine),
            {
                "power_parameters_power_id": new_power_id,
                "power_parameters_power_pass": new_power_pass,
                "power_parameters_power_address": new_power_address,
            },
        )

        assert http.client.OK == response.status_code
        assert {
            "power_id": new_power_id,
            "power_pass": new_power_pass,
            "power_address": new_power_address,
        } == reload_object(machine).get_power_parameters()

    def test_PUT_updates_cpu_memory(self, admin, admin_api_client, mocker):
        machine = factory.make_Node(
            owner=self.user,
            architecture=self._make_usable_architecture(mocker),
            power_type="manual",
        )
        response = admin_api_client.put(
            self.get_machine_uri(machine), {"cpu_count": 1, "memory": 1024}
        )
        assert http.client.OK == response.status_code
        machine = reload_object(machine)
        assert 1 == machine.cpu_count
        assert 1024 == machine.memory

    def test_PUT_updates_power_parameters_rejects_unknown_param(
        self, admin, admin_api_client, mocker
    ):
        power_parameters = {factory.make_string(): factory.make_string()}
        machine = factory.make_Node(
            owner=self.user,
            power_type="manual",
            power_parameters=power_parameters,
            architecture=self._make_usable_architecture(mocker),
        )
        response = admin_api_client.put(
            self.get_machine_uri(machine),
            {"power_parameters_unknown_param": factory.make_string()},
        )

        assert (
            http.client.BAD_REQUEST,
            {"power_parameters": ["Unknown parameter(s): unknown_param."]},
        ) == (response.status_code, json_load_bytes(response.content))
        assert (
            power_parameters == reload_object(machine).get_power_parameters()
        )

    def test_PUT_updates_power_type_default_resets_params(
        self, admin, admin_api_client, mocker
    ):
        # If one sets power_type to empty, power_parameter gets
        # reset by default (if skip_check is not set).
        power_parameters = {factory.make_string(): factory.make_string()}
        machine = factory.make_Node(
            owner=self.user,
            power_type="manual",
            power_parameters=power_parameters,
            architecture=self._make_usable_architecture(mocker),
        )
        response = admin_api_client.put(
            self.get_machine_uri(machine), {"power_type": ""}
        )

        machine = reload_object(machine)
        assert (
            http.client.OK,
            machine.power_type,
            machine.get_power_parameters(),
        ) == (response.status_code, "", {})

    def test_PUT_updates_power_type_empty_rejects_params(
        self, admin, admin_api_client, mocker
    ):
        # If one sets power_type to empty, one cannot set power_parameters.
        power_parameters = {factory.make_string(): factory.make_string()}
        machine = factory.make_Node(
            owner=self.user,
            power_type="manual",
            power_parameters=power_parameters,
            architecture=self._make_usable_architecture(mocker),
        )
        new_param = factory.make_string()
        response = admin_api_client.put(
            self.get_machine_uri(machine),
            {"power_type": "", "power_parameters_address": new_param},
        )

        machine = reload_object(machine)
        assert (
            http.client.BAD_REQUEST,
            {"power_parameters": ["Unknown parameter(s): address."]},
        ) == (response.status_code, json_load_bytes(response.content))
        assert power_parameters == machine.get_power_parameters()

    def test_PUT_updates_power_type_empty_skip_check_to_force_params(
        self, admin, admin_api_client, mocker
    ):
        # If one sets power_type to empty, it is possible to pass
        # power_parameter_skip_check='true' to force power_parameters.
        # XXX bigjools 2014-01-21 Why is this necessary?
        power_parameters = {factory.make_string(): factory.make_string()}
        machine = factory.make_Node(
            owner=self.user,
            power_type="manual",
            power_parameters=power_parameters,
            architecture=self._make_usable_architecture(mocker),
        )
        new_param = factory.make_string()
        response = admin_api_client.put(
            self.get_machine_uri(machine),
            {
                "power_type": "",
                "power_parameters_param": new_param,
                "power_parameters_skip_check": "true",
            },
        )

        machine = reload_object(machine)
        assert (
            http.client.OK,
            machine.power_type,
            machine.get_power_parameters(),
        ) == (response.status_code, "", {"param": new_param})

    def test_PUT_updates_power_parameters_skip_ckeck(
        self, admin, admin_api_client, mocker
    ):
        # With power_parameters_skip_check, arbitrary data
        # can be put in a Machine's power_parameter field.
        machine = factory.make_Node(
            owner=self.user,
            architecture=self._make_usable_architecture(mocker),
            power_parameters={},
        )
        new_param = factory.make_string()
        new_value = factory.make_string()
        response = admin_api_client.put(
            self.get_machine_uri(machine),
            {
                "power_parameters_%s" % new_param: new_value,
                "power_parameters_skip_check": "true",
            },
        )

        assert http.client.OK == response.status_code
        assert {new_param: new_value} == reload_object(
            machine
        ).get_power_parameters()

    def test_PUT_updates_power_parameters_empty_string(
        self, admin, admin_api_client, mocker
    ):
        power_parameters = {
            "power_address": factory.make_ip_address(),
            "power_id": factory.make_name("power_id"),
            "power_pass": factory.make_name("power_pass"),
        }
        machine = factory.make_Node(
            owner=self.user,
            power_type="virsh",
            power_parameters=power_parameters,
            architecture=self._make_usable_architecture(mocker),
        )
        response = admin_api_client.put(
            self.get_machine_uri(machine), {"power_parameters_power_pass": ""}
        )

        assert http.client.OK == response.status_code
        assert (
            "" == reload_object(machine).get_power_parameters()["power_pass"]
        )

    def test_PUT_sets_zone(self, admin, admin_api_client, mocker):
        new_zone = factory.make_Zone()
        machine = factory.make_Node(
            architecture=self._make_usable_architecture(mocker),
            power_type="manual",
        )

        response = admin_api_client.put(
            self.get_machine_uri(machine), {"zone": new_zone.name}
        )

        assert http.client.OK == response.status_code
        machine = reload_object(machine)
        assert new_zone == machine.zone

    def test_PUT_does_not_set_zone_if_not_present(
        self, admin, admin_api_client, mocker
    ):
        new_name = factory.make_name()
        machine = factory.make_Node(
            architecture=self._make_usable_architecture(mocker),
            power_type="manual",
        )
        old_zone = machine.zone

        response = admin_api_client.put(
            self.get_machine_uri(machine), {"hostname": new_name}
        )

        assert http.client.OK == response.status_code
        machine = reload_object(machine)
        assert (old_zone, new_name) == (machine.zone, machine.hostname)

    def test_PUT_clears_zone(self):
        pytest.skip(
            "XXX: JeroenVermeulen 2013-12-11 bug=1259872: Clearing the "
            "zone field does not work..."
        )

        machine = factory.make_Node(zone=factory.make_Zone())
        response = self.client.put(self.get_machine_uri(machine), {"zone": ""})

        assert http.client.OK == response.status_code
        machine = reload_object(machine)
        assert machine.zone is None

    def test_PUT_without_zone_leaves_zone_unchanged(
        self, admin, admin_api_client, mocker
    ):
        zone = factory.make_Zone()
        machine = factory.make_Node(
            zone=zone,
            architecture=self._make_usable_architecture(mocker),
            power_type="manual",
        )

        response = admin_api_client.put(self.get_machine_uri(machine), {})

        assert http.client.OK == response.status_code
        machine = reload_object(machine)
        assert zone == machine.zone

    def test_PUT_requires_admin(self, mocker):
        machine = factory.make_Node(
            owner=self.user,
            architecture=self._make_usable_architecture(mocker),
        )
        # PUT the machine with no arguments - should get FORBIDDEN
        response = self.client.put(self.get_machine_uri(machine), {})
        assert http.client.FORBIDDEN == response.status_code

    def test_PUT_zone_change_requires_admin(self, mocker):
        new_zone = factory.make_Zone()
        machine = factory.make_Node(
            owner=self.user,
            architecture=self._make_usable_architecture(mocker),
        )
        old_zone = machine.zone

        response = self.client.put(
            self.get_machine_uri(machine), {"zone": new_zone.name}
        )

        assert http.client.FORBIDDEN == response.status_code
        # Confirm the machine's physical zone has not been updated.
        machine = reload_object(machine)
        assert old_zone == machine.zone

    def test_PUT_updates_swap_size(self, admin, admin_api_client, mocker):
        machine = factory.make_Node(
            owner=self.user,
            architecture=self._make_usable_architecture(mocker),
            power_type="manual",
        )
        response = admin_api_client.put(
            reverse("machine_handler", args=[machine.system_id]),
            {"swap_size": 5 * 1000**3},
        )  # Making sure we overflow 32 bits
        parsed_result = json_load_bytes(response.content)
        machine = reload_object(machine)
        assert http.client.OK == response.status_code
        assert machine.swap_size == parsed_result["swap_size"]

    def test_PUT_updates_swap_size_suffixes(
        self, admin, admin_api_client, mocker
    ):
        machine = factory.make_Node(
            owner=self.user,
            architecture=self._make_usable_architecture(mocker),
            power_type="manual",
        )

        response = admin_api_client.put(
            reverse("machine_handler", args=[machine.system_id]),
            {"swap_size": "5K"},
        )
        parsed_result = json_load_bytes(response.content)
        assert http.client.OK == response.status_code
        assert 5000 == parsed_result["swap_size"]

        response = admin_api_client.put(
            reverse("machine_handler", args=[machine.system_id]),
            {"swap_size": "5M"},
        )
        parsed_result = json_load_bytes(response.content)
        assert http.client.OK == response.status_code
        assert 5000000 == parsed_result["swap_size"]

        response = admin_api_client.put(
            reverse("machine_handler", args=[machine.system_id]),
            {"swap_size": "5G"},
        )
        parsed_result = json_load_bytes(response.content)
        assert http.client.OK == response.status_code
        assert 5000000000 == parsed_result["swap_size"]

        response = admin_api_client.put(
            reverse("machine_handler", args=[machine.system_id]),
            {"swap_size": "5T"},
        )
        parsed_result = json_load_bytes(response.content)
        assert http.client.OK == response.status_code
        assert 5000000000000 == parsed_result["swap_size"]

    def test_PUT_updates_swap_size_invalid_suffix(
        self, admin, admin_api_client, mocker
    ):
        machine = factory.make_Node(
            owner=self.user,
            architecture=self._make_usable_architecture(mocker),
        )
        response = admin_api_client.put(
            reverse("machine_handler", args=[machine.system_id]),
            {"swap_size": "5E"},
        )  # We won't support exabytes yet
        parsed_result = json_load_bytes(response.content)
        assert http.client.BAD_REQUEST == response.status_code
        assert "Invalid size for swap: 5E" == parsed_result["swap_size"][0]

    def test_DELETE_deletes_machine(self, admin, admin_api_client):
        # The api allows to delete a Machine.
        machine = factory.make_Node(owner=self.user)
        system_id = machine.system_id
        response = admin_api_client.delete(self.get_machine_uri(machine))

        assert 204 == response.status_code
        assert not Machine.objects.filter(system_id=system_id).exists()

    def test_DELETE_rejects_other_node_types(self):
        node = factory.make_Node_with_Interface_on_Subnet(
            owner=self.user,
            node_type=factory.pick_choice(
                NODE_TYPE_CHOICES, but_not=[NODE_TYPE.MACHINE]
            ),
        )
        response = self.client.delete(self.get_machine_uri(node))
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_DELETE_deletes_machine_fails_if_not_admin(self):
        # Only superusers can delete machines.
        machine = factory.make_Node(owner=self.user)
        response = self.client.delete(self.get_machine_uri(machine))

        assert http.client.FORBIDDEN == response.status_code

    def test_DELETE_forbidden_without_edit_permission(self):
        # A user without the edit permission cannot delete a Machine.
        machine = factory.make_Node()
        response = self.client.delete(self.get_machine_uri(machine))

        assert http.client.FORBIDDEN == response.status_code

    def test_DELETE_deletes_machine_fails_if_locked(self):
        # Only superusers can delete machines.
        machine = factory.make_Node(
            owner=self.user, status=NODE_STATUS.DEPLOYED, locked=True
        )
        response = self.client.delete(self.get_machine_uri(machine))
        assert http.client.FORBIDDEN == response.status_code

    def test_DELETE_refuses_to_delete_invisible_machine(self):
        # The request to delete a single machine is denied if the machine isn't
        # visible by the user.
        other_machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=factory.make_User()
        )

        response = self.client.delete(self.get_machine_uri(other_machine))

        assert http.client.FORBIDDEN == response.status_code

    def test_DELETE_refuses_to_delete_nonexistent_machine(self):
        # When deleting a Machine, the api returns a 'Not Found' (404) error
        # if no machine is found.
        url = reverse("machine_handler", args=["invalid-uuid"])
        response = self.client.delete(url)

        assert http.client.NOT_FOUND == response.status_code

    def test_DELETE_delete_with_force(self, admin, admin_api_client):
        vlan = factory.make_VLAN()
        subnet = factory.make_Subnet(vlan=vlan)
        machine = factory.make_Machine_with_Interface_on_Subnet(
            vlan=vlan, subnet=subnet
        )
        response = admin_api_client.delete(
            self.get_machine_uri(machine),
            QUERY_STRING=urlencode({"force": "true"}, doseq=True),
        )
        assert http.client.NO_CONTENT == response.status_code, (
            explain_unexpected_response(http.client.NO_CONTENT, response)
        )


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures(
    "maasdb", "maas_region_test", "factory", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.real_post_commit_hooks
class TestMachineAPITransactional:
    @pytest.fixture(autouse=True)
    def _setup(
        self, transactional_maasdb, api_identity, maas_user, api_client, mocker
    ):
        self.user = maas_user
        self.client = api_client
        mocker.patch.object(staticipaddress_module, "post_commit_do")
        load_builtin_scripts()

    def test_POST_start_returns_error_when_static_ips_exhausted(
        self, mocker, request
    ):
        mocker.patch.object(node_module, "power_driver_check")
        network = IPNetwork("10.0.0.0/30")
        rack_controller = factory.make_RackController()
        subnet = factory.make_Subnet(cidr=str(network.cidr))
        subnet.vlan.dhcp_on = True
        subnet.vlan.primary_rack = rack_controller

        client = Mock()
        client.ident = rack_controller.system_id
        mocker.patch.object(
            power_module, "getAllClients", return_value=[client]
        )

        with post_commit_hooks:
            subnet.vlan.save()

        architecture = TestMachineAPI._make_usable_architecture(mocker)
        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED,
            architecture=architecture,
            power_type="virsh",
            owner=self.user,
            power_state=POWER_STATE.OFF,
            bmc_connected_to=rack_controller,
        )
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=machine, vlan=subnet.vlan
        )
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO,
            ip="",
            subnet=subnet,
            interface=interface,
        )

        with transaction.atomic():
            StaticIPAddress.objects.allocate_new(requested_address="10.0.0.1")
            StaticIPAddress.objects.allocate_new(requested_address="10.0.0.2")
            StaticIPAddress.objects.allocate_new(requested_address="10.0.0.3")

        osystem, releases = TestMachineAPI._make_usable_osystem(
            mocker, request
        )
        distro_series = releases[0]
        machine.osystem = osystem
        machine.distro_series = distro_series
        machine.save()

        with pytest.raises(StaticIPAddressExhaustion):
            with post_commit_hooks:
                self.client.post(
                    TestMachineAPI.get_machine_uri(machine),
                    {"op": "power_on", "distro_series": distro_series},
                )


@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestSetStorageLayout:
    @pytest.fixture(autouse=True)
    def _setup_api_client(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def get_machine_uri(self, machine):
        """Get the API URI for `machine`."""
        return reverse("machine_handler", args=[machine.system_id])

    def test_403_when_not_admin(self, factory):
        machine = factory.make_Node(status=NODE_STATUS.READY)
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "set_storage_layout"}
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_409_when_machine_not_ready(
        self, admin, admin_api_client, factory
    ):
        machine = factory.make_Node(owner=admin, status=NODE_STATUS.ALLOCATED)
        response = admin_api_client.post(
            self.get_machine_uri(machine), {"op": "set_storage_layout"}
        )
        assert http.client.CONFLICT == response.status_code, response.content

    def test_400_when_storage_layout_missing(
        self, admin, admin_api_client, factory
    ):
        machine = factory.make_Node(owner=admin, status=NODE_STATUS.READY)
        response = admin_api_client.post(
            self.get_machine_uri(machine), {"op": "set_storage_layout"}
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        assert {
            "storage_layout": ["This field is required."]
        } == json_load_bytes(response.content)

    def test_400_when_invalid_optional_param(
        self, admin, admin_api_client, factory
    ):
        machine = factory.make_Node(owner=admin, status=NODE_STATUS.READY)
        factory.make_PhysicalBlockDevice(node=machine)
        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {
                "op": "set_storage_layout",
                "storage_layout": "flat",
                "boot_size": MIN_BOOT_PARTITION_SIZE - 1,
            },
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        assert {
            "boot_size": [
                "Size is too small. Minimum size is %s."
                % MIN_BOOT_PARTITION_SIZE
            ]
        } == json_load_bytes(response.content)

    def test_400_when_no_boot_disk(self, admin, admin_api_client, factory):
        machine = factory.make_Node(
            owner=admin, status=NODE_STATUS.READY, with_boot_disk=False
        )
        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {"op": "set_storage_layout", "storage_layout": "flat"},
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        assert (
            "Machine is missing a boot disk; no storage layout can be "
            "applied." == response.content.decode(settings.DEFAULT_CHARSET)
        )

    def test_400_when_layout_error(
        self, admin, admin_api_client, factory, mocker
    ):
        machine = factory.make_Node(owner=admin, status=NODE_STATUS.READY)
        mock_set_storage_layout = mocker.patch.object(
            Machine, "set_storage_layout"
        )
        error_msg = factory.make_name("error")
        mock_set_storage_layout.side_effect = StorageLayoutError(error_msg)

        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {"op": "set_storage_layout", "storage_layout": "flat"},
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        assert (
            "Failed to configure storage layout 'flat': %s" % error_msg
            == response.content.decode(settings.DEFAULT_CHARSET)
        )

    def test_400_when_layout_not_supported(
        self, admin, admin_api_client, factory
    ):
        machine = factory.make_Node(owner=admin, status=NODE_STATUS.READY)
        factory.make_PhysicalBlockDevice(node=machine)
        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {"op": "set_storage_layout", "storage_layout": "bcache"},
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        assert (
            "Failed to configure storage layout 'bcache': Node doesn't "
            "have an available cache device to setup bcache."
            == response.content.decode(settings.DEFAULT_CHARSET)
        )

    def test_calls_set_storage_layout_on_machine(
        self, admin, admin_api_client, factory, mocker
    ):
        machine = factory.make_Node(owner=admin, status=NODE_STATUS.READY)
        mock_set_storage_layout = mocker.patch.object(
            Machine, "set_storage_layout"
        )
        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {"op": "set_storage_layout", "storage_layout": "flat"},
        )
        assert http.client.OK == response.status_code, response.content
        mock_set_storage_layout.assert_called_once_with(
            "flat", params=ANY, allow_fallback=False
        )


@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestMountSpecial:
    """Tests for op=mount_special."""

    @pytest.fixture(autouse=True)
    def _setup_api_client(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def get_machine_uri(self, machine):
        """Get the API URI for `machine`."""
        return reverse("machine_handler", args=[machine.system_id])

    def test_fstype_and_mount_point_is_required_but_options_is_not(self):
        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=self.user
        )
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "mount_special"}
        )
        assert http.client.BAD_REQUEST == response.status_code
        assert {
            "fstype": ["This field is required."],
            "mount_point": ["This field is required."],
        } == json_load_bytes(response.content)

    def test_fstype_must_be_a_non_storage_type(self):
        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=self.user
        )
        for fstype in Filesystem.TYPES_REQUIRING_STORAGE:
            response = self.client.post(
                self.get_machine_uri(machine),
                {
                    "op": "mount_special",
                    "fstype": fstype,
                    "mount_point": factory.make_absolute_path(),
                },
            )
            assert http.client.BAD_REQUEST == response.status_code
            error = json_load_bytes(response.content)
            assert error.get("fstype") == [
                f"Select a valid choice. {fstype} is not one of the available choices."
            ]

    def test_mount_point_must_be_absolute(self):
        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=self.user
        )
        response = self.client.post(
            self.get_machine_uri(machine),
            {
                "op": "mount_special",
                "fstype": FILESYSTEM_TYPE.RAMFS,
                "mount_point": factory.make_name("path"),
            },
        )
        assert http.client.BAD_REQUEST == response.status_code
        assert json_load_bytes(response.content).get("mount_point") == [
            # XXX: Wow, what a lame error from AbsolutePathField!
            "Enter a valid value.",
        ]


@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.parametrize("fstype", ["ramfs", "tmpfs"], ids=["ramfs", "tmpfs"])
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestMountSpecialScenarios:
    """Scenario tests for op=mount_special."""

    @pytest.fixture(autouse=True)
    def _setup_api_client(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def get_machine_uri(self, machine):
        """Get the API URI for `machine`."""
        return reverse("machine_handler", args=[machine.system_id])

    def test_machine_representation_includes_non_storage_filesystem(
        self, fstype, factory, admin, admin_api_client
    ):
        machine = factory.make_Node(status=NODE_STATUS.READY, owner=admin)
        filesystem = factory.make_Filesystem(
            node_config=machine.current_config,
            fstype=fstype,
        )
        response = admin_api_client.get(self.get_machine_uri(machine))
        assert http.client.OK == response.status_code, response.content
        machine_response = json_load_bytes(response.content)
        assert machine_response.get("special_filesystems") == [
            {
                "fstype": filesystem.fstype,
                "label": filesystem.label,
                "mount_options": filesystem.mount_options,
                "mount_point": filesystem.mount_point,
                "uuid": filesystem.uuid,
            }
        ]

    def test_only_acquired_special_filesystems(
        self, fstype, factory, admin, admin_api_client
    ):
        machine = factory.make_Node(status=NODE_STATUS.DEPLOYED, owner=admin)
        factory.make_Filesystem(
            node_config=machine.current_config,
            fstype=fstype,
            label="not-acquired",
        )
        filesystem = factory.make_Filesystem(
            node_config=machine.current_config,
            fstype=fstype,
            label="acquired",
            acquired=True,
        )
        response = admin_api_client.get(self.get_machine_uri(machine))
        assert http.client.OK == response.status_code, response.content
        machine_response = json_load_bytes(response.content)
        assert machine_response.get("special_filesystems") == [
            {
                "fstype": filesystem.fstype,
                "label": filesystem.label,
                "mount_options": filesystem.mount_options,
                "mount_point": filesystem.mount_point,
                "uuid": filesystem.uuid,
            }
        ]

    def test_only_not_acquired_special_filesystems(
        self, fstype, factory, admin, admin_api_client
    ):
        machine = factory.make_Node(status=NODE_STATUS.READY, owner=admin)
        filesystem = factory.make_Filesystem(
            node_config=machine.current_config,
            fstype=fstype,
            label="not-acquired",
        )
        factory.make_Filesystem(
            node_config=machine.current_config,
            fstype=fstype,
            label="acquired",
            acquired=True,
        )
        response = admin_api_client.get(self.get_machine_uri(machine))
        assert http.client.OK == response.status_code, response.content
        machine_response = json_load_bytes(response.content)
        assert machine_response.get("special_filesystems") == [
            {
                "fstype": filesystem.fstype,
                "label": filesystem.label,
                "mount_options": filesystem.mount_options,
                "mount_point": filesystem.mount_point,
                "uuid": filesystem.uuid,
            }
        ]

    def _can_mount_filesystem(self, machine, fstype, api_client, factory):
        mount_point = factory.make_absolute_path()
        mount_options = factory.make_name("options")
        response = api_client.post(
            self.get_machine_uri(machine),
            {
                "op": "mount_special",
                "fstype": fstype,
                "mount_point": mount_point,
                "mount_options": mount_options,
            },
        )
        assert http.client.OK == response.status_code, response.content
        special_fss = machine.current_config.special_filesystems
        assert len(special_fss) == 1
        special_fs = special_fss[0]
        assert special_fs.fstype == fstype
        assert special_fs.mount_point == mount_point
        assert special_fs.mount_options == mount_options
        assert special_fs.node_config == machine.current_config

    def test_user_mounts_non_storage_filesystem_on_allocated_machine(
        self, fstype, factory
    ):
        self._can_mount_filesystem(
            factory.make_Node(status=NODE_STATUS.ALLOCATED, owner=self.user),
            fstype,
            self.client,
            factory,
        )

    def test_conflict_to_mount_on_non_ready_allocated_machine(
        self, fstype, factory
    ):
        statuses = {name for name, _ in NODE_STATUS_CHOICES}
        statuses -= {NODE_STATUS.READY, NODE_STATUS.ALLOCATED}
        for status in statuses:
            machine = factory.make_Node(status=status)
            response = self.client.post(
                self.get_machine_uri(machine),
                {
                    "op": "mount_special",
                    "fstype": fstype,
                    "mount_point": factory.make_absolute_path(),
                    "mount_options": factory.make_name("options"),
                },
            )
            assert response.status_code == http.client.CONFLICT, (
                "using status %d" % status
            )

    def test_admin_mounts_non_storage_filesystem_on_allocated_machine(
        self, fstype, factory, admin, admin_api_client
    ):
        self._can_mount_filesystem(
            factory.make_Node(status=NODE_STATUS.ALLOCATED, owner=self.user),
            fstype,
            admin_api_client,
            factory,
        )

    def test_admin_mounts_non_storage_filesystem_on_ready_machine(
        self, fstype, factory, admin, admin_api_client
    ):
        self._can_mount_filesystem(
            factory.make_Node(status=NODE_STATUS.READY, owner=admin),
            fstype,
            admin_api_client,
            factory,
        )

    def test_admin_cannot_mount_on_non_ready_or_allocated_machine(
        self, fstype, factory, admin, admin_api_client
    ):
        statuses = {name for name, _ in NODE_STATUS_CHOICES}
        statuses -= {NODE_STATUS.READY, NODE_STATUS.ALLOCATED}
        for status in statuses:
            machine = factory.make_Node(status=status)
            response = admin_api_client.post(
                self.get_machine_uri(machine),
                {
                    "op": "mount_special",
                    "fstype": fstype,
                    "mount_point": factory.make_absolute_path(),
                    "mount_options": factory.make_name("options"),
                },
            )
            assert response.status_code == http.client.CONFLICT, (
                "using status %d" % status
            )


@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestUnmountSpecial:
    """Tests for op=unmount_special."""

    @pytest.fixture(autouse=True)
    def _setup_api_client(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def get_machine_uri(self, machine):
        """Get the API URI for `machine`."""
        return reverse("machine_handler", args=[machine.system_id])

    def test_mount_point_is_required(self, factory):
        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=self.user
        )
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "unmount_special"}
        )
        assert http.client.BAD_REQUEST == response.status_code
        assert {"mount_point": ["This field is required."]} == json_load_bytes(
            response.content
        )

    def test_mount_point_must_be_absolute(self, factory):
        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=self.user
        )
        response = self.client.post(
            self.get_machine_uri(machine),
            {
                "op": "unmount_special",
                "mount_point": factory.make_name("path"),
            },
        )
        assert http.client.BAD_REQUEST == response.status_code
        assert json_load_bytes(response.content).get("mount_point") == [
            "Enter a valid value."
        ]


@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
@pytest.mark.parametrize("fstype", ["ramfs", "tmpfs"], ids=["ramfs", "tmpfs"])
class TestUnmountSpecialScenarios:
    """Scenario tests for op=unmount_special."""

    @pytest.fixture(autouse=True)
    def _setup_api_client(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def get_machine_uri(self, machine):
        """Get the API URI for `machine`."""
        return reverse("machine_handler", args=[machine.system_id])

    def unmount_filesystem(self, machine, fstype, client, factory):
        filesystem = factory.make_Filesystem(
            node_config=machine.current_config,
            fstype=fstype,
            mount_point=factory.make_absolute_path(),
        )
        response = client.post(
            self.get_machine_uri(machine),
            {"op": "unmount_special", "mount_point": filesystem.mount_point},
        )
        assert http.client.OK == response.status_code, response.content
        assert not machine.current_config.special_filesystems.exists()

    def test_user_unmounts_non_storage_filesystem_on_allocated_machine(
        self, fstype, factory
    ):
        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=self.user
        )
        self.unmount_filesystem(machine, fstype, self.client, factory)

    def test_conflict_to_unmount_on_non_ready_allocated_machine(
        self, fstype, factory
    ):
        statuses = {name for name, _ in NODE_STATUS_CHOICES}
        statuses -= {NODE_STATUS.READY, NODE_STATUS.ALLOCATED}
        for status in statuses:
            machine = factory.make_Node(status=status)
            filesystem = factory.make_Filesystem(
                node_config=machine.current_config,
                fstype=fstype,
                mount_point=factory.make_absolute_path(),
            )
            response = self.client.post(
                self.get_machine_uri(machine),
                {
                    "op": "unmount_special",
                    "mount_point": filesystem.mount_point,
                },
            )
            assert response.status_code == http.client.CONFLICT, (
                "using status %d" % status
            )

    def test_admin_unmounts_non_storage_filesystem_on_allocated_machine(
        self, fstype, admin, admin_api_client, factory
    ):
        machine = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=self.user
        )
        self.unmount_filesystem(machine, fstype, admin_api_client, factory)

    def test_admin_unmounts_non_storage_filesystem_on_ready_machine(
        self, fstype, admin, admin_api_client, factory
    ):
        machine = factory.make_Node(status=NODE_STATUS.READY)
        self.unmount_filesystem(machine, fstype, admin_api_client, factory)

    def test_admin_cannot_unmount_on_non_ready_or_allocated_machine(
        self, fstype, admin, admin_api_client, factory
    ):
        statuses = {name for name, _ in NODE_STATUS_CHOICES}
        statuses -= {NODE_STATUS.READY, NODE_STATUS.ALLOCATED}
        for status in statuses:
            machine = factory.make_Node(status=status)
            filesystem = factory.make_Filesystem(
                node_config=machine.current_config,
                fstype=fstype,
                mount_point=factory.make_absolute_path(),
            )
            response = admin_api_client.post(
                self.get_machine_uri(machine),
                {
                    "op": "unmount_special",
                    "mount_point": filesystem.mount_point,
                },
            )
            assert response.status_code == http.client.CONFLICT, (
                "using status %d" % status
            )


@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestDefaultGateways:
    @pytest.fixture(autouse=True)
    def _setup_api_client(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def get_machine_uri(self, machine):
        """Get the API URI for `machine`."""
        return reverse("machine_handler", args=[machine.system_id])

    def test_403_when_not_admin(self, factory):
        machine = factory.make_Node(
            owner=self.user, status=NODE_STATUS.ALLOCATED
        )
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "clear_default_gateways"}
        )
        assert http.client.FORBIDDEN == response.status_code

    def test_clears_default_gateways(self, admin, admin_api_client, factory):
        machine = factory.make_Node(owner=admin, status=NODE_STATUS.ALLOCATED)
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=machine
        )
        network_v4 = factory.make_ipv4_network()
        subnet_v4 = factory.make_Subnet(
            cidr=str(network_v4.cidr), vlan=interface.vlan
        )
        link_v4 = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO,
            ip="",
            subnet=subnet_v4,
            interface=interface,
        )
        machine.gateway_link_ipv4 = link_v4
        network_v6 = factory.make_ipv6_network()
        subnet_v6 = factory.make_Subnet(
            cidr=str(network_v6.cidr), vlan=interface.vlan
        )
        link_v6 = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO,
            ip="",
            subnet=subnet_v6,
            interface=interface,
        )
        machine.gateway_link_ipv6 = link_v6
        machine.save()
        response = admin_api_client.post(
            self.get_machine_uri(machine), {"op": "clear_default_gateways"}
        )
        assert http.client.OK == response.status_code, response.content
        machine = reload_object(machine)
        assert machine.gateway_link_ipv4 is None
        assert machine.gateway_link_ipv6 is None

    def test_returns_null_gateway_if_no_explicit_gateway_exists(
        self, admin, admin_api_client, factory
    ):
        machine = factory.make_Node(owner=admin, status=NODE_STATUS.ALLOCATED)
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=machine
        )
        network_v4 = factory.make_ipv4_network()
        subnet_v4 = factory.make_Subnet(
            cidr=str(network_v4.cidr), vlan=interface.vlan, gateway_ip=None
        )
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO,
            ip="",
            subnet=subnet_v4,
            interface=interface,
        )
        network_v6 = factory.make_ipv6_network()
        subnet_v6 = factory.make_Subnet(
            cidr=str(network_v6.cidr), vlan=interface.vlan, gateway_ip=None
        )
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO,
            ip="",
            subnet=subnet_v6,
            interface=interface,
        )
        response = admin_api_client.get(self.get_machine_uri(machine))
        assert http.client.OK == response.status_code, response.content
        response = json_load_bytes(response.content)
        assert {
            "ipv4": {"link_id": None, "gateway_ip": None},
            "ipv6": {"link_id": None, "gateway_ip": None},
        } == response["default_gateways"]

    def test_returns_effective_gateway_if_no_explicit_gateway_set(
        self, admin, admin_api_client, factory
    ):
        machine = factory.make_Node(owner=admin, status=NODE_STATUS.ALLOCATED)
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=machine
        )
        network_v4 = factory.make_ipv4_network()
        subnet_v4 = factory.make_Subnet(
            cidr=str(network_v4.cidr), vlan=interface.vlan
        )
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO,
            ip="",
            subnet=subnet_v4,
            interface=interface,
        )
        network_v6 = factory.make_ipv6_network()
        subnet_v6 = factory.make_Subnet(
            cidr=str(network_v6.cidr), vlan=interface.vlan
        )
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO,
            ip="",
            subnet=subnet_v6,
            interface=interface,
        )
        response = admin_api_client.get(self.get_machine_uri(machine))
        assert http.client.OK == response.status_code, response.content
        response = json_load_bytes(response.content)
        assert {
            "ipv4": {
                "link_id": None,
                "gateway_ip": str(subnet_v4.gateway_ip),
            },
            "ipv6": {
                "link_id": None,
                "gateway_ip": str(subnet_v6.gateway_ip),
            },
        } == response["default_gateways"]

    def test_returns_links_if_set(self, admin, admin_api_client, factory):
        machine = factory.make_Node(owner=admin, status=NODE_STATUS.ALLOCATED)
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=machine
        )
        network_v4 = factory.make_ipv4_network()
        subnet_v4 = factory.make_Subnet(
            cidr=str(network_v4.cidr), vlan=interface.vlan
        )
        link_v4 = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO,
            ip="",
            subnet=subnet_v4,
            interface=interface,
        )
        machine.gateway_link_ipv4 = link_v4
        network_v6 = factory.make_ipv6_network()
        subnet_v6 = factory.make_Subnet(
            cidr=str(network_v6.cidr), vlan=interface.vlan
        )
        link_v6 = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO,
            ip="",
            subnet=subnet_v6,
            interface=interface,
        )
        machine.gateway_link_ipv6 = link_v6
        machine.save()
        response = admin_api_client.get(self.get_machine_uri(machine))
        assert http.client.OK == response.status_code, response.content
        response = json_load_bytes(response.content)
        assert {
            "ipv4": {
                "link_id": link_v4.id,
                "gateway_ip": str(subnet_v4.gateway_ip),
            },
            "ipv6": {
                "link_id": link_v6.id,
                "gateway_ip": str(subnet_v6.gateway_ip),
            },
        } == response["default_gateways"]


@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestGetCurtinConfig:
    @pytest.fixture(autouse=True)
    def _setup_api_client(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def get_machine_uri(self, machine):
        """Get the API URI for `machine`."""
        return reverse("machine_handler", args=[machine.system_id])

    def test_500_when_machine_not_in_deployment_state(self, factory):
        machine = factory.make_Node(
            owner=self.user,
            status=factory.pick_enum(
                NODE_STATUS,
                but_not=[
                    NODE_STATUS.DEPLOYING,
                    NODE_STATUS.DEPLOYED,
                    NODE_STATUS.FAILED_DEPLOYMENT,
                ],
            ),
        )
        response = self.client.get(
            self.get_machine_uri(machine), {"op": "get_curtin_config"}
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )

    def test_returns_curtin_config_in_yaml(self, factory, mocker):
        machine = factory.make_Node(
            owner=self.user, status=NODE_STATUS.DEPLOYING
        )
        fake_config = {"config": factory.make_name("config")}
        mock_get_curtin_merged_config = mocker.patch.object(
            machines_module, "get_curtin_merged_config"
        )
        mock_get_curtin_merged_config.return_value = fake_config
        response = self.client.get(
            self.get_machine_uri(machine), {"op": "get_curtin_config"}
        )
        assert http.client.OK == response.status_code, response.content
        assert yaml.safe_dump(
            fake_config, default_flow_style=False
        ) == response.content.decode(settings.DEFAULT_CHARSET)
        mock_get_curtin_merged_config.assert_called_once_with(ANY, machine)


@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestRestoreNetworkingConfiguration:
    """Tests for
    /api/2.0/machines/<machine>/?op=restore_networking_configuration"""

    @pytest.fixture(autouse=True)
    def _setup_api_client(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def get_machine_uri(self, machine):
        """Get the API URI for `machine`."""
        return reverse("machine_handler", args=[machine.system_id])

    def test_restore_networking_configuration(
        self, admin, admin_api_client, factory, mocker
    ):
        machine = factory.make_Machine(
            owner=admin,
            status=choice([NODE_STATUS.READY, NODE_STATUS.FAILED_TESTING]),
        )
        mock_restore_network_interfaces = mocker.patch.object(
            node_module.Machine, "restore_network_interfaces"
        )
        mock_set_initial_networking_config = mocker.patch.object(
            node_module.Machine, "set_initial_networking_configuration"
        )
        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {"op": "restore_networking_configuration"},
        )
        assert http.client.OK == response.status_code, response.content
        assert (
            machine.system_id == json_load_bytes(response.content)["system_id"]
        )
        mock_set_initial_networking_config.assert_called_once()
        mock_restore_network_interfaces.assert_called_once()

    def test_restore_networking_configuration_no_gateway_link_ipv4_conflict(
        self, admin, admin_api_client, factory
    ):
        # See also LP#2015411
        machine = factory.make_Machine_with_Interface_on_Subnet(
            owner=admin, status=NODE_STATUS.READY
        )

        lxd_script = factory.make_Script(
            name=COMMISSIONING_OUTPUT_NAME,
            script_type=SCRIPT_TYPE.COMMISSIONING,
        )
        commissioning_script_set = (
            ScriptSet.objects.create_commissioning_script_set(
                machine, scripts=[lxd_script.name]
            )
        )
        machine.current_commissioning_script_set = commissioning_script_set
        output = test_hooks.make_lxd_output_json()
        factory.make_ScriptResult(
            script_set=commissioning_script_set,
            script=lxd_script,
            exit_status=0,
            output=output,
            stdout=output,
        )
        # Create NUMA nodes.
        test_hooks.create_numa_nodes(machine)

        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=machine
        )
        network = factory.make_ipv4_network()
        subnet = factory.make_Subnet(cidr=str(network.cidr))

        link_v4 = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip=factory.pick_ip_in_network(network),
            subnet=subnet,
            interface=interface,
        )
        machine.gateway_link_ipv4 = link_v4
        machine.save()

        machine.restore_network_interfaces()
        machine.set_initial_networking_configuration()
        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {"op": "restore_networking_configuration"},
        )

        assert http.client.OK == response.status_code, response.content
        assert (
            machine.system_id == json_load_bytes(response.content)["system_id"]
        )

    def test_restore_networking_configuration_requires_admin(self, factory):
        machine = factory.make_Machine()
        response = self.client.post(
            self.get_machine_uri(machine),
            {"op": "restore_networking_configuration"},
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_restore_networking_configuration_checks_machine_status(
        self, admin, admin_api_client, factory, mocker
    ):
        machine = factory.make_Machine(
            owner=admin,
            status=factory.pick_choice(
                NODE_STATUS_CHOICES,
                but_not=[NODE_STATUS.READY, NODE_STATUS.FAILED_TESTING],
            ),
        )
        mock_set_initial_networking_config = mocker.patch.object(
            node_module.Machine, "set_initial_networking_configuration"
        )
        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {"op": "restore_networking_configuration"},
        )
        assert http.client.CONFLICT == response.status_code, response.content
        mock_set_initial_networking_config.assert_not_called()


@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestRestoreStorageConfiguration:
    """Tests for
    /api/2.0/machines/<machine>/?op=restore_storage_configuration"""

    @pytest.fixture(autouse=True)
    def _setup_api_client(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def get_machine_uri(self, machine):
        """Get the API URI for `machine`."""
        return reverse("machine_handler", args=[machine.system_id])

    def test_restore_storage_configuration(
        self, admin, admin_api_client, factory, mocker
    ):
        machine = factory.make_Machine(
            owner=admin,
            status=choice([NODE_STATUS.READY, NODE_STATUS.FAILED_TESTING]),
        )
        mock_set_default_storage_layout = mocker.patch.object(
            node_module.Machine, "set_default_storage_layout"
        )
        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {"op": "restore_storage_configuration"},
        )
        assert http.client.OK == response.status_code, response.content
        assert (
            machine.system_id == json_load_bytes(response.content)["system_id"]
        )
        mock_set_default_storage_layout.assert_called_once()

    def test_restore_storage_configuration_requires_admin(self, factory):
        machine = factory.make_Machine()
        response = self.client.post(
            self.get_machine_uri(machine),
            {"op": "restore_storage_configuration"},
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_restore_storage_configuration_checks_machine_status(
        self, admin, admin_api_client, factory, mocker
    ):
        machine = factory.make_Machine(
            owner=admin,
            status=factory.pick_choice(
                NODE_STATUS_CHOICES,
                but_not=[NODE_STATUS.READY, NODE_STATUS.FAILED_TESTING],
            ),
        )
        mock_set_default_storage_layout = mocker.patch.object(
            node_module.Machine, "set_default_storage_layout"
        )
        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {"op": "restore_storage_configuration"},
        )
        assert http.client.CONFLICT == response.status_code, response.content
        mock_set_default_storage_layout.assert_not_called()


@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestRestoreDefaultConfiguration:
    """Tests for
    /api/2.0/machines/<machine>/?op=restore_default_configuration"""

    @pytest.fixture(autouse=True)
    def _setup_api_client(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def get_machine_uri(self, machine):
        """Get the API URI for `machine`."""
        return reverse("machine_handler", args=[machine.system_id])

    def test_restore_default_configuration(
        self, admin, admin_api_client, factory, mocker
    ):
        machine = factory.make_Machine(
            owner=admin,
            status=choice([NODE_STATUS.READY, NODE_STATUS.FAILED_TESTING]),
        )
        mock_set_default_storage_layout = mocker.patch.object(
            node_module.Machine, "set_default_storage_layout"
        )
        mock_restore_network_interfaces = mocker.patch.object(
            node_module.Machine, "restore_network_interfaces"
        )
        mock_set_initial_networking_config = mocker.patch.object(
            node_module.Machine, "set_initial_networking_configuration"
        )
        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {"op": "restore_default_configuration"},
        )
        assert http.client.OK == response.status_code, response.content
        assert (
            machine.system_id == json_load_bytes(response.content)["system_id"]
        )
        mock_set_default_storage_layout.assert_called_once()
        mock_restore_network_interfaces.assert_called_once()
        mock_set_initial_networking_config.assert_called_once()

    def test_restore_default_configuration_requires_admin(self, factory):
        machine = factory.make_Machine()
        response = self.client.post(
            self.get_machine_uri(machine),
            {"op": "restore_default_configuration"},
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_restore_default_configuration_checks_machine_status(
        self, admin, admin_api_client, factory, mocker
    ):
        machine = factory.make_Machine(
            owner=admin,
            status=factory.pick_choice(
                NODE_STATUS_CHOICES,
                but_not=[NODE_STATUS.READY, NODE_STATUS.FAILED_TESTING],
            ),
        )
        mock_restore_default_configuration = mocker.patch.object(
            node_module.Machine, "restore_default_configuration", create=True
        )
        response = admin_api_client.post(
            self.get_machine_uri(machine),
            {"op": "restore_default_configuration"},
        )
        assert http.client.CONFLICT == response.status_code, response.content
        mock_restore_default_configuration.assert_not_called()


@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestMarkBroken:
    @pytest.fixture(autouse=True)
    def _setup_api_client(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    @pytest.fixture(autouse=True)
    def _patch_stop_workflow(self, mocker):
        mocker.patch.object(node_module, "stop_workflow")

    def get_node_uri(self, machine):
        """Get the API URI for `machine`."""
        return reverse("machine_handler", args=[machine.system_id])

    def test_mark_broken_changes_status(self, factory):
        node = factory.make_Node(
            status=NODE_STATUS.COMMISSIONING, owner=self.user
        )
        response = self.client.post(
            self.get_node_uri(node), {"op": "mark_broken"}
        )
        assert http.client.OK == response.status_code, response.content
        assert NODE_STATUS.BROKEN == reload_object(node).status

    def test_mark_broken_updates_error_description(self, factory):
        # 'error_description' parameter was renamed 'comment' for consistency
        # make sure this comment updates the node's error_description
        node = factory.make_Node(
            status=NODE_STATUS.COMMISSIONING, owner=self.user
        )
        comment = factory.make_name("comment")
        response = self.client.post(
            self.get_node_uri(node), {"op": "mark_broken", "comment": comment}
        )
        assert http.client.OK == response.status_code, response.content
        node = reload_object(node)
        assert (NODE_STATUS.BROKEN, comment) == (
            node.status,
            node.error_description,
        )

    def test_mark_broken_updates_error_description_compatibility(
        self, factory
    ):
        # test old 'error_description' parameter is honored for compatibility
        node = factory.make_Node(
            status=NODE_STATUS.COMMISSIONING, owner=self.user
        )
        error_description = factory.make_name("error_description")
        response = self.client.post(
            self.get_node_uri(node),
            {"op": "mark_broken", "error_description": error_description},
        )
        assert http.client.OK == response.status_code, response.content
        node = reload_object(node)
        assert (NODE_STATUS.BROKEN, error_description) == (
            node.status,
            node.error_description,
        )

    def test_mark_broken_passes_comment(self, factory, mocker):
        node = factory.make_Node(
            status=NODE_STATUS.COMMISSIONING, owner=self.user
        )
        node_mark_broken = mocker.patch.object(
            node_module.Machine, "mark_broken"
        )
        comment = factory.make_name("comment")
        self.client.post(
            self.get_node_uri(node), {"op": "mark_broken", "comment": comment}
        )
        node_mark_broken.assert_called_once_with(self.user, comment)

    def test_mark_broken_handles_missing_comment(self, factory, mocker):
        node = factory.make_Node(
            status=NODE_STATUS.COMMISSIONING, owner=self.user
        )
        node_mark_broken = mocker.patch.object(
            node_module.Machine, "mark_broken"
        )
        self.client.post(self.get_node_uri(node), {"op": "mark_broken"})
        node_mark_broken.assert_called_once_with(self.user, None)

    def test_mark_broken_requires_ownership(self, factory):
        node = factory.make_Node(status=NODE_STATUS.COMMISSIONING)
        response = self.client.post(
            self.get_node_uri(node), {"op": "mark_broken"}
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_mark_broken_allowed_from_any_other_state(self, factory, mocker):
        mocker.patch.object(node_module.Machine, "_stop")
        for status, _ in NODE_STATUS_CHOICES:
            if status == NODE_STATUS.BROKEN:
                continue

            node = factory.make_Node(status=status, owner=self.user)
            response = self.client.post(
                self.get_node_uri(node), {"op": "mark_broken"}
            )
            assert http.client.OK == response.status_code, response.content
            node = reload_object(node)
            assert NODE_STATUS.BROKEN == node.status


@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestMarkFixed:
    @pytest.fixture(autouse=True)
    def _setup_api_client(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def get_node_uri(self, machine):
        """Get the API URI for `machine`."""
        return reverse("machine_handler", args=[machine.system_id])

    def test_mark_fixed_changes_status(self, admin, admin_api_client, factory):
        node = factory.make_Node(status=NODE_STATUS.BROKEN)
        response = admin_api_client.post(
            self.get_node_uri(node), {"op": "mark_fixed"}
        )
        assert http.client.OK == response.status_code, response.content
        assert NODE_STATUS.READY == reload_object(node).status

    def test_mark_fixed_requires_admin(self):
        node = factory.make_Node(status=NODE_STATUS.BROKEN)
        response = self.client.post(
            self.get_node_uri(node), {"op": "mark_fixed"}
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_mark_fixed_passes_comment(
        self, admin, admin_api_client, factory, mocker
    ):
        node = factory.make_Node(status=NODE_STATUS.BROKEN)
        node_mark_fixed = mocker.patch.object(
            node_module.Machine, "mark_fixed"
        )
        comment = factory.make_name("comment")
        admin_api_client.post(
            self.get_node_uri(node), {"op": "mark_fixed", "comment": comment}
        )
        node_mark_fixed.assert_called_once_with(admin, comment)

    def test_mark_fixed_handles_missing_comment(
        self, admin, admin_api_client, factory, mocker
    ):
        node = factory.make_Node(status=NODE_STATUS.BROKEN)
        node_mark_fixed = mocker.patch.object(
            node_module.Machine, "mark_fixed"
        )
        admin_api_client.post(self.get_node_uri(node), {"op": "mark_fixed"})
        node_mark_fixed.assert_called_once_with(admin, None)


@pytest.mark.usefixtures(
    "maasdb", "maas_region_test", "factory", "transactional_maasdb"
)
@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.allow_transactions
class TestRescueMode:
    """Tests for /api/2.0/machines/<machine>/?op=rescue_mode"""

    @pytest.fixture(autouse=True)
    def _setup_api_client(
        self, transactional_maasdb, api_identity, maas_user, api_client
    ):
        self.user = maas_user
        self.client = api_client

    def get_machine_uri(self, machine):
        """Get the API URI for `machine`."""
        return reverse("machine_handler", args=[machine.system_id])

    def test_rescue_mode_requires_admin(self, factory):
        status = choice((NODE_STATUS.BROKEN, NODE_STATUS.DEPLOYED))
        machine = factory.make_Node(owner=self.user, status=status)
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "rescue_mode"}
        )
        assert http.client.FORBIDDEN == response.status_code

    def test_rescue_mode_changes_state(
        self, admin, admin_api_client, factory, mocker
    ):
        status = choice((NODE_STATUS.BROKEN, NODE_STATUS.DEPLOYED))
        machine = factory.make_Node(status=status)
        mock_power_cycle = mocker.patch.object(
            node_module.Machine, "_power_cycle"
        )
        mock_power_cycle.side_effect = lambda: post_commit()

        with SignalsDisabled("power"):
            response = admin_api_client.post(
                self.get_machine_uri(machine), {"op": "rescue_mode"}
            )
        assert http.client.OK == response.status_code
        assert (
            NODE_STATUS.ENTERING_RESCUE_MODE == reload_object(machine).status
        )


@pytest.mark.usefixtures(
    "maasdb", "maas_region_test", "factory", "transactional_maasdb"
)
@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.allow_transactions
class TestExitRescueMode:
    """Tests for /api/2.0/machines/<machine>/?op=exit_rescue_mode"""

    @pytest.fixture(autouse=True)
    def _setup_api_client(
        self, transactional_maasdb, api_identity, maas_user, api_client
    ):
        self.user = maas_user
        self.client = api_client

    def get_machine_uri(self, machine):
        """Get the API URI for `machine`."""
        return reverse("machine_handler", args=[machine.system_id])

    def test_exit_rescue_mode_requires_admin(self, factory):
        machine = factory.make_Node(status=NODE_STATUS.RESCUE_MODE)
        response = self.client.post(
            self.get_machine_uri(machine), {"op": "exit_rescue_mode"}
        )
        assert http.client.FORBIDDEN == response.status_code

    def test_exit_rescue_mode_changes_state(
        self, admin, admin_api_client, factory, mocker
    ):
        previous_status = choice((NODE_STATUS.BROKEN, NODE_STATUS.DEPLOYED))
        machine = factory.make_Node(
            owner=admin,
            status=NODE_STATUS.RESCUE_MODE,
            previous_status=previous_status,
        )
        mock_power_cycle = mocker.patch.object(
            node_module.Machine, "_power_cycle"
        )
        mock_power_cycle.side_effect = lambda: post_commit()
        mock_stop = mocker.patch.object(node_module.Machine, "_stop")
        mock_stop.side_effect = lambda user: post_commit()

        with SignalsDisabled("power"):
            response = admin_api_client.post(
                self.get_machine_uri(machine), {"op": "exit_rescue_mode"}
            )
        assert http.client.OK == response.status_code
        assert NODE_STATUS.EXITING_RESCUE_MODE == reload_object(machine).status


@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestMachineHandlerOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup_api_client(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_commission_succees_if_edit_access(self, mocker):
        mocker.patch.object(
            node_module.Node, "_start", return_value=defer.succeed(None)
        )

        mocker.patch.object(
            node_module.Node,
            "_start_commissioning_async",
            return_value=defer.succeed(None),
        )
        pool = factory.make_ResourcePool()
        self.openfga_client.can_edit_machines_in_pool.return_value = True

        machine = factory.make_Node(
            status=NODE_STATUS.READY,
            owner=factory.make_User(),
            power_state=POWER_STATE.OFF,
            interface=True,
            pool=pool,
        )

        machine_uri = reverse("machine_handler", args=[machine.system_id])
        response = self.client.post(machine_uri, {"op": "commission"})

        assert http.client.OK == response.status_code
        assert NODE_STATUS.COMMISSIONING == reload_object(machine).status

    def test_commission_403(self, mocker):
        mocker.patch.object(
            node_module.Node, "_start", return_value=defer.succeed(None)
        )

        pool = factory.make_ResourcePool()
        self.openfga_client.can_edit_machines_in_pool.return_value = False

        machine = factory.make_Node(
            status=NODE_STATUS.READY,
            owner=factory.make_User(),
            power_state=POWER_STATE.OFF,
            interface=True,
            pool=pool,
        )

        machine_uri = reverse("machine_handler", args=[machine.system_id])
        response = self.client.post(machine_uri, {"op": "commission"})

        assert http.client.FORBIDDEN == response.status_code
        assert NODE_STATUS.READY == reload_object(machine).status
