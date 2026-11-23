# Copyright 2016-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from datetime import timedelta
from hashlib import sha256
from hmac import HMAC
from json import dumps
import random
from random import randint
import re

from django.db.utils import IntegrityError
from django.utils import timezone
import pytest
from twisted.internet.defer import inlineCallbacks, succeed
from twisted.protocols.amp import UnknownRemoteError
from twisted.python.failure import Failure

from maasserver import eventloop
from maasserver.enum import INTERFACE_TYPE, NODE_STATUS
from maasserver.models import Config, Event, EventType, Node
from maasserver.models import node as node_module
from maasserver.models.interface import PhysicalInterface
from maasserver.models.signals.testing import SignalsDisabled
from maasserver.rpc import events as events_module
from maasserver.rpc import regionservice
from maasserver.rpc.nodes import get_controller_type, get_time_configuration
from maasserver.rpc.regionservice import Region
from maasserver.rpc.services import update_services
from maasserver.security import get_shared_secret
from maasserver.testing.architecture import make_usable_architecture
from maasserver.testing.eventloop import RegionEventLoopFixture
from maasserver.testing.factory import factory
from maasserver.utils.orm import (
    make_serialization_failure,
    reload_object,
    transactional,
)
from maasserver.utils.threads import deferToDatabase
from maastesting.crochet import wait_for
from maastesting.twisted import TwistedLoggerFixture
from provisioningserver.enum import POWER_STATE
from provisioningserver.rpc.exceptions import NoSuchCluster, NoSuchNode
from provisioningserver.rpc.region import (
    Authenticate,
    CommissionNode,
    CreateNode,
    GetBootConfig,
    GetControllerType,
    GetProxyConfiguration,
    GetSyslogConfiguration,
    GetTimeConfiguration,
    Identify,
    ListNodePowerParameters,
    MarkNodeFailed,
    RegisterEventType,
    ReportForeignDHCPServer,
    ReportNeighbours,
    RequestNodeInfoByMACAddress,
    RequestRackRefresh,
    SendEvent,
    SendEventMACAddress,
    UpdateNodePowerState,
    UpdateServices,
)
from provisioningserver.rpc.testing import call_responder

wait_for_reactor = wait_for()

pytestmark = pytest.mark.recreate_db


@transactional
def transactional_reload_object(obj):
    return reload_object(obj)


class TestRegionProtocol:
    def test_unauthenticated_allowed_commands(self):
        protocol = Region()
        assert [Authenticate.commandName] == protocol.unauthenticated_commands

    def test_default_auth_status(self):
        protocol = Region()
        assert not protocol.auth_status.is_authenticated


class TestRegionProtocol_Identify:
    def test_identify_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(Identify.commandName)
        assert responder is not None

    @wait_for_reactor
    def test_identify_reports_event_loop_name(self):
        d = call_responder(Region(), Identify, {})

        def check(response):
            assert {"ident": eventloop.loop.name} == response

        return d.addCallback(check)


@pytest.mark.usefixtures("maasdb")
class TestRegionProtocol_Authenticate:
    def test_authenticate_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(Authenticate.commandName)
        assert responder is not None

    @wait_for_reactor
    @inlineCallbacks
    def test_authenticate_calculates_digest_with_salt(self):
        message = factory.make_bytes()
        secret = yield get_shared_secret()

        args = {"message": message}
        response = yield call_responder(Region(), Authenticate, args)
        digest = response["digest"]
        salt = response["salt"]

        expected_digest = HMAC(
            secret, message + b"rack-to-region" + salt, sha256
        ).digest()
        assert expected_digest == digest
        assert len(salt) == 16


@pytest.mark.usefixtures("maasdb")
class TestRegionProtocol_GetBootConfig:
    def test_get_boot_config_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(GetBootConfig.commandName)
        assert responder is not None

    @wait_for_reactor
    @inlineCallbacks
    def test_get_boot_config_returns_expected_result(self, mocker):
        rack_controller = yield deferToDatabase(
            transactional(factory.make_RackController)
        )
        yield deferToDatabase(factory.make_RegionController)

        class _MockTestCase:
            def __init__(self, mocker):
                self.patch = lambda obj, attr: mocker.patch.object(obj, attr)
                self.patch_autospec = (
                    lambda obj, attr, **kw: mocker.patch.object(
                        obj, attr, autospec=True, **kw
                    )
                )

        yield deferToDatabase(
            lambda: make_usable_architecture(_MockTestCase(mocker))
        )
        local_ip = factory.make_ip_address()
        remote_ip = factory.make_ip_address()

        response = yield call_responder(
            Region(),
            GetBootConfig,
            {
                "system_id": rack_controller.system_id,
                "local_ip": local_ip,
                "remote_ip": remote_ip,
            },
        )

        assert response.keys() >= {
            "arch",
            "subarch",
            "osystem",
            "release",
            "kernel_osystem",
            "kernel_release",
            "kernel",
            "initrd",
            "boot_dtb",
            "purpose",
            "hostname",
            "domain",
            "preseed_url",
            "fs_host",
            "log_host",
            "extra_opts",
            "ephemeral_opts",
        }


@pytest.mark.usefixtures("maasdb")
class TestRegionProtocol_MarkNodeFailed:
    def test_mark_failed_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(MarkNodeFailed.commandName)
        assert responder is not None

    @transactional
    def create_deploying_node(self):
        node = factory.make_Node(status=NODE_STATUS.DEPLOYING)
        return node.system_id

    @transactional
    def get_node_status(self, system_id):
        node = Node.objects.get(system_id=system_id)
        return node.status

    @transactional
    def get_node_error_description(self, system_id):
        node = Node.objects.get(system_id=system_id)
        return node.error_description

    @wait_for_reactor
    @inlineCallbacks
    def test_mark_node_failed_changes_status_and_updates_error_msg(
        self, mocker
    ):
        with SignalsDisabled("power"):
            mocker.patch.object(node_module, "stop_workflow")
            system_id = yield deferToDatabase(self.create_deploying_node)

            error_description = factory.make_name("error-description")
            response = yield call_responder(
                Region(),
                MarkNodeFailed,
                {
                    "system_id": system_id,
                    "error_description": error_description,
                },
            )

            assert {} == response
            new_status = yield deferToDatabase(self.get_node_status, system_id)
            new_error_description = yield deferToDatabase(
                self.get_node_error_description, system_id
            )
            assert (NODE_STATUS.FAILED_DEPLOYMENT, error_description) == (
                new_status,
                new_error_description,
            )

    @wait_for_reactor
    def test_mark_node_failed_errors_if_node_cannot_be_found(self):
        system_id = factory.make_name("unknown-system-id")
        error_description = factory.make_name("error-description")

        d = call_responder(
            Region(),
            MarkNodeFailed,
            {"system_id": system_id, "error_description": error_description},
        )

        def check(error):
            assert isinstance(error, Failure)
            assert isinstance(error.value, NoSuchNode)
            # The error message contains a reference to system_id.
            assert system_id in str(error.value)

        return d.addErrback(check)


@pytest.mark.usefixtures("maasdb")
@pytest.mark.usefixtures("mock_start_workflows")
class TestRegionProtocol_ListNodePowerParameters:
    @transactional
    def create_node(self, **kwargs):
        node = factory.make_Node(**kwargs)
        return node

    @transactional
    def create_rack_controller(self, **kwargs):
        rack = factory.make_RackController(**kwargs)
        return rack

    @transactional
    def get_node_power_parameters(self, node):
        return node.get_effective_power_parameters()

    def test_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(
            ListNodePowerParameters.commandName
        )
        assert responder is not None

    @wait_for_reactor
    @inlineCallbacks
    def test_returns_correct_arguments(self):
        rack = yield deferToDatabase(self.create_rack_controller)

        nodes = []
        for _ in range(3):
            node = yield deferToDatabase(
                self.create_node,
                power_type="virsh",
                power_state_updated=None,
                bmc_connected_to=rack,
            )
            power_params = yield deferToDatabase(
                self.get_node_power_parameters, node
            )
            nodes.append(
                {
                    "system_id": node.system_id,
                    "hostname": node.hostname,
                    "power_state": node.power_state,
                    "power_type": node.get_effective_power_type(),
                    "context": power_params,
                }
            )

        # Create a node with an invalid power type.
        # This will not be reported by the call to ListNodePowerParameters.
        yield deferToDatabase(
            self.create_node, power_type="invalid", power_state_updated=None
        )

        response = yield call_responder(
            Region(), ListNodePowerParameters, {"uuid": rack.system_id}
        )

        assert sorted(nodes, key=lambda n: n["system_id"]) == sorted(
            response["nodes"], key=lambda n: n["system_id"]
        )

    @wait_for_reactor
    @inlineCallbacks
    def test_raises_exception_if_nodegroup_doesnt_exist(self):
        uuid = factory.make_UUID()

        d = call_responder(Region(), ListNodePowerParameters, {"uuid": uuid})

        with pytest.raises(
            NoSuchCluster,
            match=re.escape(
                rf"The rack controller with UUID {uuid} could not be found."
            ),
        ):
            yield d


@pytest.mark.usefixtures("maasdb")
class TestRegionProtocol_UpdateNodePowerState:
    @transactional
    def create_node(self, power_state):
        node = factory.make_Node(power_state=power_state)
        return node

    @transactional
    def get_node_power_state(self, system_id):
        node = Node.objects.get(system_id=system_id)
        return node.power_state

    def test_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(UpdateNodePowerState.commandName)
        assert responder is not None

    @wait_for_reactor
    @inlineCallbacks
    def test_changes_power_state(self):
        power_state = factory.pick_enum(POWER_STATE)
        node = yield deferToDatabase(self.create_node, power_state)

        new_state = factory.pick_enum(POWER_STATE, but_not=[power_state])
        yield call_responder(
            Region(),
            UpdateNodePowerState,
            {"system_id": node.system_id, "power_state": new_state},
        )

        db_state = yield deferToDatabase(
            self.get_node_power_state, node.system_id
        )
        assert new_state == db_state

    @wait_for_reactor
    def test_errors_if_node_cannot_be_found(self):
        system_id = factory.make_name("unknown-system-id")
        power_state = factory.pick_enum(POWER_STATE)

        d = call_responder(
            Region(),
            UpdateNodePowerState,
            {"system_id": system_id, "power_state": power_state},
        )

        def check(error):
            assert isinstance(error, Failure)
            assert isinstance(error.value, NoSuchNode)
            assert system_id in str(error.value)

        return d.addErrback(check)


@pytest.mark.usefixtures("maasdb")
class TestRegionProtocol_RegisterEventType:
    def test_register_event_type_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(RegisterEventType.commandName)
        assert responder is not None

    @transactional
    def get_event_type(self, name):
        return EventType.objects.get(name=name)

    @wait_for_reactor
    @inlineCallbacks
    def test_register_event_type_creates_object(self):
        name = factory.make_name("name")
        description = factory.make_name("description")
        level = random.randint(0, 100)
        response = yield call_responder(
            Region(),
            RegisterEventType,
            {"name": name, "description": description, "level": level},
        )

        assert {} == response
        event_type = yield deferToDatabase(self.get_event_type, name)
        assert event_type.name == name
        assert event_type.description == description
        assert event_type.level == level

    @wait_for_reactor
    @inlineCallbacks
    def test_register_event_type_does_not_error_for_existing_event_types(self):
        # This is a regression test for bug 1373357.
        name = factory.make_name("name")
        old_description = factory.make_name("old-description")
        level = random.randint(0, 100)
        response = yield call_responder(
            Region(),
            RegisterEventType,
            {"name": name, "description": old_description, "level": level},
        )
        assert {} == response

        new_description = factory.make_name("new-description")
        response = yield call_responder(
            Region(),
            RegisterEventType,
            {"name": name, "description": new_description, "level": level},
        )
        # If we get this far, no error has been raised, even though we
        # sent a duplicate request for registration.
        assert {} == response


@pytest.mark.usefixtures("maasdb")
class TestRegionProtocol_SendEvent:
    @pytest.fixture(autouse=True)
    def _setup(self, maasdb):
        _fixture = RegionEventLoopFixture("database-tasks")
        _fixture.setUp()
        try:
            yield
        finally:
            _fixture.cleanUp()

    def test_send_event_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(SendEvent.commandName)
        assert responder is not None

    @transactional
    def get_event(self, system_id, type_name):
        all_events_qs = Event.objects.all().select_related("node", "type")
        event = all_events_qs.get(
            node__system_id=system_id, type__name=type_name
        )
        return event

    @transactional
    def create_event_type(self, name, description, level):
        EventType.objects.create(
            name=name, description=description, level=level
        )

    @transactional
    def create_node(self):
        return factory.make_Node().system_id

    @wait_for_reactor
    @inlineCallbacks
    def test_send_event_stores_event(self):
        name = factory.make_name("type_name")
        description = factory.make_name("description")
        level = random.randint(0, 100)
        yield deferToDatabase(self.create_event_type, name, description, level)
        system_id = yield deferToDatabase(self.create_node)

        event_description = factory.make_name("description")

        yield eventloop.start()
        try:
            response = yield call_responder(
                Region(),
                SendEvent,
                {
                    "system_id": system_id,
                    "type_name": name,
                    "description": event_description,
                },
            )
        finally:
            yield eventloop.reset()

        assert {} == response
        event = yield deferToDatabase(self.get_event, system_id, name)
        assert event.node.system_id == system_id
        assert event.description == event_description
        assert event.type.name == name

    @wait_for_reactor
    @inlineCallbacks
    def test_send_event_stores_event_with_timestamp_received(self, mocker):
        # Use a random time in the recent past and coerce the responder to use
        # it as the time-stamp for the event. We'll check this later on.
        timestamp = timezone.now() - timedelta(seconds=randint(99, 99999))
        mocker.patch.object(
            regionservice, "timezone"
        ).now.return_value = timestamp

        event_type = factory.make_name("type_name")
        yield deferToDatabase(self.create_event_type, event_type, "", 0)
        system_id = yield deferToDatabase(self.create_node)

        yield eventloop.start()
        try:
            yield call_responder(
                Region(),
                SendEvent,
                {
                    "system_id": system_id,
                    "type_name": event_type,
                    "description": factory.make_name("description"),
                },
            )
        finally:
            yield eventloop.reset()

        event = yield deferToDatabase(self.get_event, system_id, event_type)
        assert event.created == timestamp

    @wait_for_reactor
    @inlineCallbacks
    def test_send_event_does_not_fail_if_unknown_type(self):
        name = factory.make_name("type_name")
        system_id = factory.make_name("system_id")
        description = factory.make_name("description")

        with TwistedLoggerFixture() as logger:
            yield eventloop.start()
            try:
                yield call_responder(
                    Region(),
                    SendEvent,
                    {
                        "system_id": system_id,
                        "type_name": name,
                        "description": description,
                    },
                )
            finally:
                yield eventloop.reset()

        # The log records the issue.
        assert (
            re.search(
                (
                    r"(?ms)Unhandled failure in database task\..*"
                    r"Traceback \(most recent call last\):.*"
                    "provisioningserver.rpc.exceptions.NoSuchEventType:"
                ),
                logger.output,
            )
            is not None
        )

    @wait_for_reactor
    @inlineCallbacks
    def test_send_event_logs_if_unknown_node(self, mocker):
        log = mocker.patch.object(events_module, "log")
        name = factory.make_name("type_name")
        description = factory.make_name("description")
        level = random.randint(0, 100)
        yield deferToDatabase(self.create_event_type, name, description, level)

        system_id = factory.make_name("system_id")
        event_description = factory.make_name("event-description")

        yield eventloop.start()
        try:
            yield call_responder(
                Region(),
                SendEvent,
                {
                    "system_id": system_id,
                    "type_name": name,
                    "description": event_description,
                },
            )
        finally:
            yield eventloop.reset()

        log.debug.assert_called_once_with(
            "Event '{type}: {description}' sent for "
            "non-existent node '{node_id}'.",
            type=name,
            description=event_description,
            node_id=system_id,
        )


@pytest.mark.usefixtures("maasdb")
class TestRegionProtocol_SendEventMACAddress:
    @pytest.fixture(autouse=True)
    def _setup(self, maasdb):
        _fixture = RegionEventLoopFixture("database-tasks")
        _fixture.setUp()
        try:
            yield
        finally:
            _fixture.cleanUp()

    def test_send_event_mac_address_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(SendEventMACAddress.commandName)
        assert responder is not None

    @transactional
    def get_event(self, mac_address, type_name):
        all_events_qs = Event.objects.all().select_related("node", "type")
        node = PhysicalInterface.objects.get(
            mac_address=mac_address
        ).node_config.node
        event = all_events_qs.get(node=node, type__name=type_name)
        return event

    @transactional
    def create_event_type(self, name, description, level):
        EventType.objects.create(
            name=name, description=description, level=level
        )

    @transactional
    def make_interface(self):
        interface = factory.make_Interface(INTERFACE_TYPE.PHYSICAL)
        interface.node_config.node  # noqa: B018
        return interface

    @wait_for_reactor
    @inlineCallbacks
    def test_send_event_mac_address_stores_event(self):
        name = factory.make_name("type_name")
        description = factory.make_name("description")
        level = random.randint(0, 100)
        yield deferToDatabase(self.create_event_type, name, description, level)
        interface = yield deferToDatabase(self.make_interface)
        mac_address = interface.mac_address
        event_description = factory.make_name("description")

        yield eventloop.start()
        try:
            response = yield call_responder(
                Region(),
                SendEventMACAddress,
                {
                    "mac_address": mac_address,
                    "type_name": name,
                    "description": event_description,
                },
            )
        finally:
            yield eventloop.reset()

        assert {} == response
        event = yield deferToDatabase(self.get_event, mac_address, name)
        assert event.node.system_id == interface.node_config.node.system_id
        assert event.description == event_description
        assert event.type.name == name

    @wait_for_reactor
    @inlineCallbacks
    def test_send_event_mac_address_stores_event_with_timestamp_received(
        self, mocker
    ):
        timestamp = timezone.now() - timedelta(seconds=randint(99, 99999))
        mocker.patch.object(
            regionservice, "timezone"
        ).now.return_value = timestamp

        event_type = factory.make_name("type_name")
        yield deferToDatabase(self.create_event_type, event_type, "", 0)
        interface = yield deferToDatabase(self.make_interface)
        mac_address = interface.mac_address

        yield eventloop.start()
        try:
            yield call_responder(
                Region(),
                SendEventMACAddress,
                {
                    "mac_address": mac_address,
                    "type_name": event_type,
                    "description": factory.make_name("description"),
                },
            )
        finally:
            yield eventloop.reset()

        event = yield deferToDatabase(self.get_event, mac_address, event_type)
        assert event.created == timestamp

    @wait_for_reactor
    @inlineCallbacks
    def test_send_event_mac_address_does_not_fail_if_unknown_type(self):
        name = factory.make_name("type_name")
        mac_address = factory.make_mac_address()
        description = factory.make_name("description")

        with TwistedLoggerFixture() as logger:
            yield eventloop.start()
            try:
                yield call_responder(
                    Region(),
                    SendEventMACAddress,
                    {
                        "mac_address": mac_address,
                        "type_name": name,
                        "description": description,
                    },
                )
            finally:
                yield eventloop.reset()

        # The log records the issue.
        assert (
            re.search(
                (
                    r"(?ms)Unhandled failure in database task\..*"
                    r"Traceback \(most recent call last\):.*"
                    "provisioningserver.rpc.exceptions.NoSuchEventType:"
                ),
                logger.output,
            )
            is not None
        )

    @wait_for_reactor
    @inlineCallbacks
    def test_send_event_mac_address_logs_if_unknown_node(self, mocker):
        log = mocker.patch.object(events_module, "log")
        name = factory.make_name("type_name")
        description = factory.make_name("description")
        level = random.randint(0, 100)
        yield deferToDatabase(self.create_event_type, name, description, level)
        mac_address = factory.make_mac_address()
        event_description = factory.make_name("event-description")

        yield eventloop.start()
        try:
            yield call_responder(
                Region(),
                SendEventMACAddress,
                {
                    "mac_address": mac_address,
                    "type_name": name,
                    "description": event_description,
                },
            )
        finally:
            yield eventloop.reset()

        log.debug.assert_called_once_with(
            "Event '{type}: {description}' sent for non-existent node "
            "with MAC address '{mac}'.",
            type=name,
            description=event_description,
            mac=mac_address,
        )


@pytest.mark.usefixtures("maasdb")
class TestRegionProtocol_UpdateServices:
    @pytest.fixture(autouse=True)
    def _setup(self, maasdb):
        _fixture = RegionEventLoopFixture("database-tasks")
        _fixture.setUp()
        yield
        _fixture.cleanUp()

    def test_update_services_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(UpdateServices.commandName)
        assert responder is not None

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_update_services_in_database_thread(self, mocker):
        system_id = factory.make_name("system_id")
        services = [
            {
                "name": factory.make_name("service"),
                "status": factory.make_name("status"),
                "status_info": factory.make_name("status_info"),
            }
        ]

        mock_deferToDatabase = mocker.patch.object(
            regionservice, "deferToDatabase"
        )
        mock_deferToDatabase.return_value = succeed({})

        yield eventloop.start()
        try:
            yield call_responder(
                Region(),
                UpdateServices,
                {"system_id": system_id, "services": services},
            )
        finally:
            yield eventloop.reset()

        mock_deferToDatabase.assert_called_with(
            update_services, system_id, services
        )


@pytest.mark.usefixtures("maasdb")
class TestRegionProtocol_ReportForeignDHCPServer:
    def test_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(
            ReportForeignDHCPServer.commandName
        )
        assert responder is not None

    @transactional
    def create_rack_interface(self):
        rack_controller = factory.make_RackController(interface=False)
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=rack_controller
        )
        return rack_controller, interface

    @transactional
    def get_vlan_for_interface(self, interface):
        return reload_object(interface.vlan)

    @wait_for_reactor
    @inlineCallbacks
    def test_sets_external_dhcp_value(self):
        dhcp_ip = factory.make_ipv4_address()
        rack, interface = yield deferToDatabase(self.create_rack_interface)

        response = yield call_responder(
            Region(),
            ReportForeignDHCPServer,
            {
                "system_id": rack.system_id,
                "interface_name": interface.name,
                "dhcp_ip": dhcp_ip,
            },
        )

        assert {} == response
        vlan = yield deferToDatabase(self.get_vlan_for_interface, interface)
        assert dhcp_ip == vlan.external_dhcp


@pytest.mark.usefixtures("maasdb")
class TestRegionProtocol_CreateNode:
    def test_create_node_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(CreateNode.commandName)
        assert responder is not None

    @transactional
    def create_node(self):
        return factory.make_Node()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_create_node_function(self, mocker):
        create_node_function = mocker.patch.object(
            regionservice, "create_node"
        )
        create_node_function.return_value = yield deferToDatabase(
            self.create_node
        )

        params = {
            "architecture": factory.make_name("arch"),
            "power_type": factory.make_name("power_type"),
            "power_parameters": dumps({}),
            "mac_addresses": [factory.make_mac_address()],
            "domain": factory.make_name("domain"),
            "hostname": None,
        }

        response = yield call_responder(Region(), CreateNode, params)
        assert response is not None

        create_node_function.assert_called_once_with(
            params["architecture"],
            params["power_type"],
            params["power_parameters"],
            params["mac_addresses"],
            domain=params["domain"],
            hostname=params["hostname"],
        )
        assert (
            create_node_function.return_value.system_id
            == response["system_id"]
        )


@pytest.mark.usefixtures("maasdb")
class TestRegionProtocol_CommissionNode:
    def test_commission_node_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(CommissionNode.commandName)
        assert responder is not None

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_commission_node_function(self, mocker):
        commission_node_function = mocker.patch.object(
            regionservice, "commission_node"
        )

        params = {
            "system_id": factory.make_name("system_id"),
            "user": factory.make_name("user"),
        }

        response = yield call_responder(Region(), CommissionNode, params)
        assert response is not None

        commission_node_function.assert_called_once_with(
            params["system_id"], params["user"]
        )


@pytest.mark.usefixtures("maasdb")
class TestRegionProtocol_ReportNeighbours:
    def test_report_neighbours_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(ReportNeighbours.commandName)
        assert responder is not None

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_report_neighbours_function(self, mocker):
        report_neighbours = mocker.patch.object(
            regionservice.rackcontrollers, "report_neighbours"
        )

        params = {
            "system_id": factory.make_name("system_id"),
            "neighbours": [{"ip": "127.0.0.1"}, {"ip": "127.0.0.2"}],
        }

        response = yield call_responder(Region(), ReportNeighbours, params)
        assert response is not None

        report_neighbours.assert_called_once_with(
            params["system_id"], params["neighbours"]
        )

    @wait_for_reactor
    @inlineCallbacks
    def test_retryable_db_failure_is_suppressed(self, mocker):
        report_neighbours = mocker.patch.object(
            regionservice.rackcontrollers, "report_neighbours"
        )
        report_neighbours.side_effect = make_serialization_failure()

        params = {
            "system_id": factory.make_name("system_id"),
            "neighbours": [{"ip": "127.0.0.1"}],
        }

        response = yield call_responder(Region(), ReportNeighbours, params)
        assert {} == response

    @wait_for_reactor
    @inlineCallbacks
    def test_non_retryable_db_failure_propagates(self, mocker):
        report_neighbours = mocker.patch.object(
            regionservice.rackcontrollers, "report_neighbours"
        )
        report_neighbours.side_effect = IntegrityError("constraint violation")

        params = {
            "system_id": factory.make_name("system_id"),
            "neighbours": [{"ip": "127.0.0.1"}],
        }

        with pytest.raises(UnknownRemoteError):
            yield call_responder(Region(), ReportNeighbours, params)


@pytest.mark.usefixtures("maasdb")
class TestRegionProtocol_RequestNodeInforByMACAddress:
    def test_request_node_info_by_mac_address_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(
            RequestNodeInfoByMACAddress.commandName
        )
        assert responder is not None

    @transactional
    def make_interface(self, node):
        return factory.make_Interface(INTERFACE_TYPE.PHYSICAL, node=node)

    @transactional
    def create_node(self):
        return factory.make_Node()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_request_node_info_by_mac_address_function(self, mocker):
        purpose = factory.make_name("purpose")
        node = yield deferToDatabase(self.create_node)
        node_info_function = mocker.patch.object(
            regionservice, "request_node_info_by_mac_address"
        )
        node_info_function.return_value = (node, purpose)
        interface = yield deferToDatabase(self.make_interface, node)

        params = {"mac_address": interface.mac_address}

        response = yield call_responder(
            Region(), RequestNodeInfoByMACAddress, params
        )
        assert response is not None
        node_info_function.assert_called_once_with(params["mac_address"])
        response_purpose = response.pop("purpose")
        assert purpose == response_purpose
        # Remove the boot_type from the response as node no longer has that
        # attribute.
        copy_response = dict(response)
        del copy_response["boot_type"]
        for key, value in copy_response.items():
            assert getattr(node, key) == value
        assert "fastpath" == response["boot_type"]

    @wait_for_reactor
    @inlineCallbacks
    def test_request_node_info_by_mac_address_raises_if_unknown_mac(self):
        params = {"mac_address": factory.make_mac_address()}
        d = call_responder(Region(), RequestNodeInfoByMACAddress, params)

        with pytest.raises(
            NoSuchNode,
            match=re.escape(
                f"Node with mac_address={params['mac_address']} could not be found."
            ),
        ):
            yield d


@pytest.mark.usefixtures("maasdb")
class TestRegionProtocol_RequestRefresh:
    def test_request_refresh_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(RequestRackRefresh.commandName)
        assert responder is not None

    @wait_for_reactor
    @inlineCallbacks
    def test_prepares_for_refresh(self):
        def get_events(rack):
            return [
                event.type.name
                for event in Event.objects.filter(
                    node_system_id=rack.system_id
                )
            ]

        rack = yield deferToDatabase(factory.make_RackController)
        response = yield call_responder(
            Region(),
            RequestRackRefresh,
            {"system_id": rack.system_id},
        )
        assert sorted(["consumer_key", "token_key", "token_secret"]) == sorted(
            response.keys()
        )

        event_names = yield deferToDatabase(get_events, rack)
        assert "REQUEST_CONTROLLER_REFRESH" in event_names


@pytest.mark.usefixtures("maasdb")
class TestRegionProtocol_GetControllerType:
    def test_get_controller_type_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(GetControllerType.commandName)
        assert responder is not None

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_get_controller_type(self, mocker):
        example_response = {
            "is_region": factory.pick_bool(),
            "is_rack": factory.pick_bool(),
        }
        mock_defer = mocker.patch.object(regionservice, "deferToDatabase")
        mock_defer.return_value = succeed(example_response)
        system_id = factory.make_name("id")
        response = yield call_responder(
            Region(), GetControllerType, {"system_id": system_id}
        )
        assert example_response == response
        mock_defer.assert_called_once_with(get_controller_type, system_id)

    @wait_for_reactor
    @inlineCallbacks
    def test_raises_NoSuchNode_when_node_does_not_exist(self):
        arguments = {"system_id": factory.make_name("id")}
        d = call_responder(Region(), GetControllerType, arguments)
        with pytest.raises(
            NoSuchNode,
            match=re.escape(
                f"Node with system_id={arguments['system_id']} could not be found."
            ),
        ):
            yield d


@pytest.mark.usefixtures("maasdb")
class TestRegionProtocol_GetTimeConfiguration:
    def test_get_time_configuration_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(GetTimeConfiguration.commandName)
        assert responder is not None

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_get_time_configuration(self, mocker):
        example_response = {
            "servers": [
                factory.make_ipv4_address(),
                factory.make_ipv6_address(),
                factory.make_hostname(),
            ],
            "peers": [
                factory.make_ipv4_address(),
                factory.make_ipv6_address(),
            ],
        }
        mock_defer = mocker.patch.object(regionservice, "deferToDatabase")
        mock_defer.return_value = succeed(example_response)
        system_id = factory.make_name("id")
        response = yield call_responder(
            Region(), GetTimeConfiguration, {"system_id": system_id}
        )
        assert example_response == response
        mock_defer.assert_called_once_with(get_time_configuration, system_id)

    @wait_for_reactor
    @inlineCallbacks
    def test_raises_NoSuchNode_when_node_does_not_exist(self):
        arguments = {"system_id": factory.make_name("id")}
        d = call_responder(Region(), GetTimeConfiguration, arguments)
        with pytest.raises(
            NoSuchNode,
            match=re.escape(
                f"Node with system_id={arguments['system_id']} could not be found."
            ),
        ):
            yield d


@pytest.mark.usefixtures("maasdb")
class TestRegionProtocol_GetProxyConfiguration:
    def test_get_proxy_configuration_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(GetProxyConfiguration.commandName)
        assert responder is not None

    @wait_for_reactor
    @inlineCallbacks
    def test_returns_proxy_configuration(self):
        def _db_work():
            cidrs = [
                factory.make_Subnet(allow_proxy=True).cidr for _ in range(3)
            ]
            for _ in range(3):
                factory.make_Subnet(allow_proxy=False)
            enabled = factory.pick_bool()
            Config.objects.set_config("enable_http_proxy", enabled)
            port = random.randint(1000, 8000)
            Config.objects.set_config("maas_proxy_port", port)
            prefer_v4_proxy = factory.pick_bool()
            Config.objects.set_config("prefer_v4_proxy", prefer_v4_proxy)
            return cidrs, enabled, port, prefer_v4_proxy

        cidrs, enabled, port, prefer_v4_proxy = yield deferToDatabase(_db_work)

        system_id = factory.make_name("id")
        response = yield call_responder(
            Region(), GetProxyConfiguration, {"system_id": system_id}
        )
        assert response == {
            "enabled": enabled,
            "port": port,
            "allowed_cidrs": cidrs,
            "prefer_v4_proxy": prefer_v4_proxy,
        }


@pytest.mark.usefixtures("maasdb")
class TestRegionProtocol_GetSyslogConfiguration:
    def test_get_proxy_configuration_is_registered(self):
        protocol = Region()
        responder = protocol.locateResponder(
            GetSyslogConfiguration.commandName
        )
        assert responder is not None

    @wait_for_reactor
    @inlineCallbacks
    def test_returns_syslog_configuration(self):
        def _db_work():
            port = random.randint(1000, 8000)
            Config.objects.set_config("maas_syslog_port", port)
            return port

        port = yield deferToDatabase(_db_work)

        system_id = factory.make_name("id")
        response = yield call_responder(
            Region(), GetSyslogConfiguration, {"system_id": system_id}
        )
        assert {"port": port, "promtail_port": None} == response

    @wait_for_reactor
    @inlineCallbacks
    def test_returns_syslog_promtail_configuration(self):
        def _db_work():
            port = random.randint(1000, 8000)
            Config.objects.set_config("maas_syslog_port", port)
            Config.objects.set_config("promtail_enabled", True)
            Config.objects.set_config("promtail_port", port + 1)
            return port

        port = yield deferToDatabase(_db_work)

        system_id = factory.make_name("id")
        response = yield call_responder(
            Region(), GetSyslogConfiguration, {"system_id": system_id}
        )
        assert {"port": port, "promtail_port": port + 1} == response
