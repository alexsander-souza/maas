# Copyright 2016-2026 Canonical Ltd. This software is licnesed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


import random
from unittest.mock import Mock, patch, sentinel
from urllib.parse import urlparse

from fixtures import FakeLogger
import pytest

from maasserver import locks, worker_user
from maasserver.enum import INTERFACE_TYPE, IPADDRESS_TYPE, NODE_TYPE
from maasserver.models import RackController, RegionController
from maasserver.rpc import rackcontrollers
from maasserver.rpc.rackcontrollers import (
    register,
    report_neighbours,
    update_foreign_dhcp,
    update_state,
)
from maasserver.testing.factory import factory
from maasserver.utils.orm import post_commit_hooks, reload_object
from maasservicelayer.models import rackcontrollers as rackcontroller_models
from maasservicelayer.services.rackcontrollers import RackControllersService
from metadataserver.builtin_scripts import load_builtin_scripts
from provisioningserver.rpc.exceptions import NoSuchScope


class _PytestTestCaseAdapter:
    @pytest.fixture(autouse=True)
    def _pytest_adapter(self, mocker, request):
        self._mocker = mocker
        self._request = request

    def patch(self, obj, attribute=None, value=None):
        if attribute is None:
            return self._mocker.patch(obj)
        if value is None:
            return self._mocker.patch.object(obj, attribute)
        return self._mocker.patch.object(obj, attribute, value)

    def useFixture(self, fixture):
        fixture.setUp()
        self._request.addfinalizer(fixture.cleanUp)
        return fixture


@pytest.mark.usefixtures(
    "maasdb",
    "maas_region_test",
    "factory",
    "mock_openfga",
    "mock_start_workflows",
)
class TestRegisterRackController(_PytestTestCaseAdapter):
    @pytest.fixture(autouse=True)
    def _setup(self, maasdb, maas_region_test, factory, mocker):
        self.this_region = factory.make_RegionController()
        mocker.patch.object(
            RegionController.objects,
            "get_running_controller",
            return_value=self.this_region,
        )

    def test_sets_owner_to_worker_when_none(self):
        node = factory.make_Node()
        with post_commit_hooks:
            rack_registered = register(system_id=node.system_id)
        assert worker_user.get_worker_user() == rack_registered.owner

    def test_leaves_owner_when_owned(self):
        user = factory.make_User()
        node = factory.make_Machine(owner=user)
        with post_commit_hooks:
            rack_registered = register(system_id=node.system_id)
        assert user == rack_registered.owner

    def test_finds_existing_node_by_system_id(self):
        node = factory.make_Node()
        with post_commit_hooks:
            rack_registered = register(system_id=node.system_id)
        assert node.system_id == rack_registered.system_id

    def test_finds_existing_node_by_hostname(self):
        node = factory.make_Node()
        with post_commit_hooks:
            rack_registered = register(hostname=node.hostname)
        assert node.system_id == rack_registered.system_id

    def test_finds_existing_node_by_mac(self):
        node = factory.make_Node()
        nic = factory.make_Interface(node=node)
        interfaces = {
            nic.name: {
                "type": "physical",
                "mac_address": nic.mac_address,
                "parents": [],
                "links": [],
                "enabled": True,
            }
        }
        with post_commit_hooks:
            rack_registered = register(interfaces=interfaces)
        assert node.system_id == rack_registered.system_id

    def test_find_existing_keeps_type(self):
        node_type = random.choice(
            (NODE_TYPE.RACK_CONTROLLER, NODE_TYPE.REGION_AND_RACK_CONTROLLER)
        )
        node = factory.make_Node(node_type=node_type)
        with post_commit_hooks:
            register(system_id=node.system_id)
        assert node_type == node.node_type

    def test_logs_finding_existing_node(self):
        logger = self.useFixture(FakeLogger("maas"))
        node = factory.make_Node(node_type=NODE_TYPE.RACK_CONTROLLER)
        with post_commit_hooks:
            register(system_id=node.system_id)
        assert (
            "Existing rack controller '%s' running version 2.2 or below has "
            "connected to region '%s'."
            % (node.hostname, self.this_region.hostname)
        ) == logger.output.strip()

    def test_logs_finding_existing_node_with_version(self):
        logger = self.useFixture(FakeLogger("maas"))
        node = factory.make_Node(node_type=NODE_TYPE.RACK_CONTROLLER)
        with post_commit_hooks:
            register(system_id=node.system_id, version="2.10.0")
        assert (
            "Existing rack controller '%s' running version 2.10.0 has "
            "connected to region '%s'."
            % (node.hostname, self.this_region.hostname)
        ) == logger.output.strip()

    def test_converts_region_controller(self):
        node = factory.make_Node(node_type=NODE_TYPE.REGION_CONTROLLER)
        with post_commit_hooks:
            rack_registered = register(system_id=node.system_id)
        assert (
            rack_registered.node_type == NODE_TYPE.REGION_AND_RACK_CONTROLLER
        )

    def test_logs_converting_region_controller(self):
        logger = self.useFixture(FakeLogger("maas"))
        node = factory.make_Node(node_type=NODE_TYPE.REGION_CONTROLLER)
        with post_commit_hooks:
            register(system_id=node.system_id)
        assert (
            "Region controller '%s' running version 2.2 or below converted "
            "into a region and rack controller.\n" % node.hostname
        ) == logger.output

    def test_logs_converting_region_controller_with_version(self):
        logger = self.useFixture(FakeLogger("maas"))
        node = factory.make_Node(node_type=NODE_TYPE.REGION_CONTROLLER)

        with post_commit_hooks:
            register(system_id=node.system_id, version="2.10.0")
        assert (
            "Region controller '%s' running version 2.10.0 converted "
            "into a region and rack controller.\n" % node.hostname
        ) == logger.output

    def test_converts_existing_node(self):
        node = factory.make_Machine()
        rack_registered = register(system_id=node.system_id)
        assert rack_registered.node_type == NODE_TYPE.RACK_CONTROLLER
        reload_object(node)
        assert not node.should_be_dynamically_deleted()

    def test_logs_converting_existing_node(self):
        logger = self.useFixture(FakeLogger("maas"))
        node = factory.make_Node(node_type=NODE_TYPE.MACHINE)
        with post_commit_hooks:
            register(system_id=node.system_id)
        assert (
            "Region controller '%s' converted '%s' running version 2.2 or "
            "below into a rack controller.\n"
            % (self.this_region.hostname, node.hostname)
        ) == logger.output

    def test_logs_converting_existing_node_with_version(self):
        logger = self.useFixture(FakeLogger("maas"))
        node = factory.make_Node(node_type=NODE_TYPE.MACHINE)
        with post_commit_hooks:
            register(system_id=node.system_id, version="1.10.2")
        assert (
            "Region controller '%s' converted '%s' running version 1.10.2 "
            "into a rack controller.\n"
            % (self.this_region.hostname, node.hostname)
        ) == logger.output

    def test_creates_new_rackcontroller(self):
        existing_machine = factory.make_Machine()
        rack_mac = factory.make_mac_address()
        interfaces = {
            factory.make_name("eth0"): {
                "type": "physical",
                "mac_address": rack_mac,
                "parents": [],
                "links": [],
                "enabled": True,
            }
        }

        with post_commit_hooks:
            rack_controller = register(interfaces=interfaces)
        assert existing_machine.system_id != rack_controller.system_id
        assert rack_controller.should_be_dynamically_deleted()

    @patch("maasserver.rpc.rackcontrollers.service_layer")
    def test_creates_new_rackcontroller_and_links_rack_controller(
        self, mock_service_layer
    ):
        mock_service_layer.ensure_connection.return_value = None
        rack_controller_uuid = factory.make_UUID()
        mock_rack_controllers_service = Mock(RackControllersService)
        mock_rack_controller = Mock(rackcontroller_models.RackController)
        mock_rack_controller.id = 12
        mock_rack_controller.node_id = None
        mock_rack_controllers_service.get_one = Mock(
            return_value=mock_rack_controller
        )
        mock_rack_controllers_service.update_by_id = Mock()
        mock_service_layer.services.rack_controllers = (
            mock_rack_controllers_service
        )

        rack_mac = factory.make_mac_address()
        interfaces = {
            factory.make_name("eth0"): {
                "type": "physical",
                "mac_address": rack_mac,
                "parents": [],
                "links": [],
                "enabled": True,
            }
        }

        with post_commit_hooks:
            register(
                interfaces=interfaces,
                rack_controller_uuid=rack_controller_uuid,
            )

        mock_rack_controllers_service.update_by_id.assert_called_once()

    @patch("maasserver.rpc.rackcontrollers.service_layer")
    def test_logs_creating_new_rackcontroller_and_linking_rack_controller(
        self, mock_service_layer
    ):
        logger = self.useFixture(FakeLogger("maas"))

        mock_service_layer.ensure_connection.return_value = None
        rack_controller_uuid = factory.make_UUID()
        mock_rack_controllers_service = Mock(RackControllersService)
        mock_rack_controller = Mock(rackcontroller_models.RackController)
        mock_rack_controller.id = 12
        mock_rack_controller.node_id = None
        mock_rack_controllers_service.get_one = Mock(
            return_value=mock_rack_controller
        )
        mock_rack_controllers_service.update_by_id = Mock()
        mock_service_layer.services.rack_controllers = (
            mock_rack_controllers_service
        )
        hostname = factory.make_name("hostname")

        with post_commit_hooks:
            rack_registered = register(
                hostname=hostname, rack_controller_uuid=rack_controller_uuid
            )

        assert (
            f"Linked rack controller '{rack_controller_uuid}' to node "
            f"'{hostname}' (id: {rack_registered.id})"
        ) in logger.output

    @patch("maasserver.rpc.rackcontrollers.service_layer")
    def test_registers_without_matching_rack_controller_uuid(
        self, mock_service_layer
    ):
        mock_service_layer.ensure_connection.return_value = None
        rack_controller_uuid = factory.make_UUID()
        mock_rack_controllers_service = Mock(RackControllersService)
        mock_rack_controller = Mock(rackcontroller_models.RackController)
        mock_rack_controller.id = 12
        mock_rack_controllers_service.get_one = Mock(return_value=None)
        mock_service_layer.services.rack_controllers = (
            mock_rack_controllers_service
        )
        hostname = factory.make_name("hostname")

        with post_commit_hooks:
            register(
                hostname=hostname, rack_controller_uuid=rack_controller_uuid
            )

        mock_rack_controllers_service.update_by_id.assert_not_called()

    @patch("maasserver.rpc.rackcontrollers.service_layer")
    def test_logs_registering_without_matching_rack_controller_uuid(
        self, mock_service_layer
    ):
        logger = self.useFixture(FakeLogger("maas"))

        mock_service_layer.ensure_connection.return_value = None
        rack_controller_uuid = factory.make_UUID()
        mock_rack_controllers_service = Mock(RackControllersService)
        mock_rack_controller = Mock(rackcontroller_models.RackController)
        mock_rack_controller.id = 12
        mock_rack_controllers_service.get_one = Mock(return_value=None)
        mock_service_layer.services.rack_controllers = (
            mock_rack_controllers_service
        )
        hostname = factory.make_name("hostname")

        with post_commit_hooks:
            register(
                hostname=hostname, rack_controller_uuid=rack_controller_uuid
            )

        assert (
            f"Rack controller with UUID '{rack_controller_uuid}' not found "
            "during registration"
        ) in logger.output

    def test_always_has_current_commissioning_script_set(self):
        load_builtin_scripts()
        hostname = factory.make_name("hostname")
        with post_commit_hooks:
            register(hostname=hostname)
        rack = RackController.objects.get(hostname=hostname)
        assert rack.current_commissioning_script_set is not None

    def test_logs_creating_new_rackcontroller(self):
        logger = self.useFixture(FakeLogger("maas"))
        hostname = factory.make_name("hostname")
        with post_commit_hooks:
            register(hostname=hostname)
        assert (
            "New rack controller '%s' running version 2.2 or below was "
            "created by region '%s' upon first connection."
            % (hostname, self.this_region.hostname)
        ) == logger.output.strip()

    def test_logs_creating_new_rackcontroller_with_version(self):
        logger = self.useFixture(FakeLogger("maas"))
        hostname = factory.make_name("hostname")
        with post_commit_hooks:
            register(hostname=hostname, version="2.10.0")
        assert (
            "New rack controller '%s' running version 2.10.0 was "
            "created by region '%s' upon first connection."
            % (hostname, self.this_region.hostname)
        ) == logger.output.strip()

    def test_sets_version_of_controller(self):
        version = "1.10.2"
        node = factory.make_Node(node_type=NODE_TYPE.MACHINE)
        with post_commit_hooks:
            register(system_id=node.system_id, version=version)
        assert version == node.as_rack_controller().version

    def test_registers_with_startup_lock_held(self):
        lock_status = []

        def record_lock_status(*args):
            lock_status.append(locks.startup.is_locked())
            return None  # Simulate that no rack found.

        find = self.patch(rackcontrollers, "find")
        find.side_effect = record_lock_status

        with post_commit_hooks:
            register()

        assert [True] == lock_status

    def test_sets_url(self):
        load_builtin_scripts()
        rack_controller = factory.make_RackController()
        interfaces = {
            factory.make_name("eth0"): {
                "type": "physical",
                "mac_address": factory.make_mac_address(),
                "parents": [],
                "links": [],
                "enabled": True,
            }
        }
        url = "http://%s/MAAS" % factory.make_name("host")
        with post_commit_hooks:
            rack_registered = register(
                rack_controller.system_id,
                interfaces=interfaces,
                url=urlparse(url),
                is_loopback=False,
            )
        assert url == rack_registered.url
        with post_commit_hooks:
            rack_registered = register(
                rack_controller.system_id,
                interfaces=interfaces,
                url=urlparse("http://localhost/MAAS/"),
                is_loopback=True,
            )
        assert "" == rack_registered.url

    def test_creates_rackcontroller_domain(self):
        # Create a domain if a newly registered rackcontroller uses a FQDN
        # as the hostname, but the domain does not already existing in MAAS,
        hostname = "newcontroller.example.com"
        interfaces = {
            factory.make_name("eth0"): {
                "type": "physical",
                "mac_address": factory.make_mac_address(),
                "parents": [],
                "links": [],
                "enabled": True,
            }
        }
        url = "http://%s/MAAS" % factory.make_name("host")
        with post_commit_hooks:
            rack_registered = register(
                "rack-id-foo",
                interfaces=interfaces,
                url=urlparse(url),
                is_loopback=False,
                hostname=hostname,
            )
        assert "newcontroller" == rack_registered.hostname
        assert "example.com" == rack_registered.domain.name
        assert not rack_registered.domain.authoritative

    def test_reuses_rackcontroller_domain(self):
        # If a domain name already exists for a FQDN hostname, it is
        # not modified.
        factory.make_Domain("example.com", authoritative=True)
        hostname = "newcontroller.example.com"
        interfaces = {
            factory.make_name("eth0"): {
                "type": "physical",
                "mac_address": factory.make_mac_address(),
                "parents": [],
                "links": [],
                "enabled": True,
            }
        }
        url = "http://%s/MAAS" % factory.make_name("host")

        with post_commit_hooks:
            rack_registered = register(
                "rack-id-foo",
                interfaces=interfaces,
                url=urlparse(url),
                is_loopback=False,
                hostname=hostname,
            )
        assert "newcontroller" == rack_registered.hostname
        assert "example.com" == rack_registered.domain.name
        assert rack_registered.domain.authoritative


@pytest.mark.usefixtures(
    "maasdb",
    "maas_region_test",
    "factory",
    "mock_openfga",
    "mock_start_workflows",
)
class TestUpdateForeignDHCP(_PytestTestCaseAdapter):
    def test_doesnt_fail_if_interface_missing(self):
        rack_controller = factory.make_RackController()
        # No error should be raised.
        update_foreign_dhcp(
            rack_controller.system_id, factory.make_name("eth"), None
        )

    def test_clears_external_dhcp_on_vlan(self):
        rack_controller = factory.make_RackController(interface=False)
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=rack_controller
        )
        interface.vlan.external_dhcp = factory.make_ip_address()
        interface.vlan.save()
        update_foreign_dhcp(rack_controller.system_id, interface.name, None)
        assert reload_object(interface.vlan).external_dhcp is None

    def test_sets_external_dhcp_when_not_managed_vlan(self):
        rack_controller = factory.make_RackController(interface=False)
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=rack_controller
        )
        dhcp_ip = factory.make_ip_address()
        update_foreign_dhcp(rack_controller.system_id, interface.name, dhcp_ip)
        assert dhcp_ip == reload_object(interface.vlan).external_dhcp

    def test_logs_warning_for_external_dhcp_on_interface_no_vlan(self):
        rack_controller = factory.make_RackController(interface=False)
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=rack_controller
        )
        dhcp_ip = factory.make_ip_address()
        interface.vlan = None
        interface.save()
        logger = self.useFixture(FakeLogger())
        update_foreign_dhcp(rack_controller.system_id, interface.name, dhcp_ip)
        assert (
            "DHCP server on an interface with no VLAN defined" in logger.output
        )

    def test_clears_external_dhcp_when_managed_vlan(self):
        rack_controller = factory.make_RackController(interface=False)
        fabric = factory.make_Fabric()
        vlan = fabric.get_default_vlan()
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=rack_controller, vlan=vlan
        )
        subnet = factory.make_Subnet()
        dhcp_ip = factory.pick_ip_in_Subnet(subnet)
        vlan.dhcp_on = True
        vlan.primary_rack = rack_controller
        vlan.external_dhcp = dhcp_ip

        with post_commit_hooks:
            vlan.save()

        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.STICKY,
            ip=dhcp_ip,
            subnet=subnet,
            interface=interface,
        )

        with post_commit_hooks:
            update_foreign_dhcp(
                rack_controller.system_id, interface.name, dhcp_ip
            )
        assert reload_object(interface.vlan).external_dhcp is None


@pytest.mark.usefixtures(
    "maasdb",
    "maas_region_test",
    "factory",
    "mock_openfga",
    "mock_start_workflows",
)
class TestReportNeighbours(_PytestTestCaseAdapter):
    def test_calls_report_neighbours_on_rack_controller(self):
        rack_controller = factory.make_RackController()
        patched_report_neighbours = self.patch(
            RackController, "report_neighbours"
        )
        report_neighbours(rack_controller.system_id, sentinel.neighbours)
        patched_report_neighbours.assert_called_once_with(sentinel.neighbours)


@pytest.mark.usefixtures(
    "maasdb",
    "maas_region_test",
    "factory",
    "mock_openfga",
    "mock_start_workflows",
)
class TestUpdateState(_PytestTestCaseAdapter):
    def test_scope_versions_snap(self):
        rack = factory.make_RackController()
        versions = {
            "snap": {
                "current": {
                    "revision": "1234",
                    "version": "3.0.0~alpha1-111-g.deadbeef",
                },
                "channel": "3.0/stable",
                "update": {
                    "revision": "5678",
                    "version": "3.0.0~alpha2-222-g.cafecafe",
                },
                "cohort": "abc123",
            },
        }
        update_state(rack.system_id, "versions", versions)
        controller_info = rack.controllerinfo
        assert controller_info.version == "3.0.0~alpha1-111-g.deadbeef"
        assert controller_info.update_version == "3.0.0~alpha2-222-g.cafecafe"
        assert controller_info.update_origin == "3.0/stable"
        assert controller_info.snap_revision == "1234"
        assert controller_info.snap_update_revision == "5678"
        assert controller_info.snap_cohort == "abc123"

    def test_scope_versions_other(self):
        rack = factory.make_RackController()
        update_state(rack.system_id, "versions", {"something": "else"})
        # no ControllerInfo is created as the state is not updated
        assert not hasattr(rack, "controllerinfo")

    def test_scope_unhandled(self):
        rack = factory.make_RackController()
        with pytest.raises(NoSuchScope):
            update_state(rack.system_id, "other", {})
