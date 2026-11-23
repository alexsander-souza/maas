# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test event catalog."""

import random
from unittest.mock import sentinel

import pytest
from twisted.internet.defer import fail, inlineCallbacks, succeed

from maascommon.events import EventDetail
from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.factory import factory
from provisioningserver.events import (
    EVENT_DETAILS,
    EVENT_TYPES,
    NodeEventHub,
    nodeEventHub,
    send_node_event,
    send_node_event_ip_address,
    send_node_event_mac_address,
    send_rack_event,
)
from provisioningserver.rpc import clusterservice, region
from provisioningserver.rpc.exceptions import NoSuchEventType, NoSuchNode
from provisioningserver.rpc.testing import MockLiveClusterToRegionRPCFixture
from provisioningserver.utils.enum import map_enum
from provisioningserver.utils.testing import MAASIDFixture

TIMEOUT = get_testing_timeout()


class TestEvents:
    def test_every_event_has_details(self):
        all_events = map_enum(EVENT_TYPES)
        assert set(all_events.values()) == EVENT_DETAILS.keys()
        for detail in EVENT_DETAILS.values():
            assert isinstance(detail, EventDetail)


@pytest.mark.rack_reactor_guard
class TestSendEventNode:
    """Tests for `send_node_event`."""

    def test_calls_singleton_hub_logByID_directly(self, mocker):
        mocker.patch.object(nodeEventHub, "logByID").return_value = sentinel.d
        result = send_node_event(
            sentinel.event_type,
            sentinel.system_id,
            sentinel.hostname,
            sentinel.description,
        ).wait(TIMEOUT)
        assert result is sentinel.d
        nodeEventHub.logByID.assert_called_once_with(
            sentinel.event_type, sentinel.system_id, sentinel.description
        )


@pytest.mark.rack_reactor_guard
class TestSendEventNodeMACAddress:
    """Tests for `send_node_event_mac_address`."""

    def test_calls_singleton_hub_logByMAC_directly(self, mocker):
        mocker.patch.object(nodeEventHub, "logByMAC").return_value = sentinel.d
        result = send_node_event_mac_address(
            sentinel.event_type, sentinel.mac_address, sentinel.description
        ).wait(TIMEOUT)
        assert result is sentinel.d


@pytest.mark.rack_reactor_guard
class TestSendEventNodeIPAddress:
    """Tests for `send_node_event_ip_address`."""

    def test_calls_singleton_hub_logByIP_directly(self, mocker):
        mocker.patch.object(nodeEventHub, "logByIP").return_value = sentinel.d
        result = send_node_event_ip_address(
            sentinel.event_type, sentinel.ip_address, sentinel.description
        ).wait(TIMEOUT)
        assert result is sentinel.d


@pytest.mark.rack_reactor_guard
class TestSendRackEvent:
    """Tests for `send_rack_event`."""

    def test_calls_singleton_hub_logByID_directly(self, mocker, request):
        mocker.patch.object(nodeEventHub, "logByID").return_value = sentinel.d
        rack_system_id = factory.make_name("system_id")
        fixture = MAASIDFixture(rack_system_id)
        fixture.setUp()
        request.addfinalizer(fixture.cleanUp)
        result = send_rack_event(
            sentinel.event_type, sentinel.description
        ).wait(TIMEOUT)
        assert result is sentinel.d
        nodeEventHub.logByID.assert_called_once_with(
            sentinel.event_type, rack_system_id, sentinel.description
        )


def _cleanup_rpc_fixture(fixture, shutdown):
    @inlineCallbacks
    def cleanup():
        try:
            yield shutdown()
        finally:
            yield fixture.cleanUp()

    return cleanup()


@pytest.mark.rack_reactor_guard
class TestNodeEventHubLogByID:
    """Tests for `NodeEventHub.logByID`."""

    @inlineCallbacks
    def patch_rpc_methods(self, request, mocker, side_effect=None):
        mocker.patch.object(
            clusterservice, "get_all_interfaces_definition", return_value={}
        )
        fixture = MockLiveClusterToRegionRPCFixture()
        shutdown = [lambda: succeed(None)]
        request.addfinalizer(
            lambda: wait_for(timeout=TIMEOUT)(_cleanup_rpc_fixture)(
                fixture, shutdown[0]
            )
        )
        yield fixture.setUp()
        protocol, connecting = fixture.makeEventLoop(
            region.SendEvent, region.RegisterEventType
        )
        shutdown[0] = yield connecting
        protocol.SendEvent.side_effect = side_effect
        return protocol

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_event_is_sent_to_region(self, request, mocker):
        protocol = yield self.patch_rpc_methods(request, mocker)
        system_id = factory.make_name("system_id")
        description = factory.make_name("description")
        event_name = random.choice(list(map_enum(EVENT_TYPES)))

        yield NodeEventHub().logByID(event_name, system_id, description)

        protocol.SendEvent.assert_called_once_with(
            protocol,
            type_name=event_name,
            system_id=system_id,
            description=description,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_event_type_is_registered_on_first_call_only(
        self, request, mocker
    ):
        protocol = yield self.patch_rpc_methods(
            request, mocker, side_effect=[succeed({}), succeed({})]
        )

        system_id = factory.make_name("system_id")
        description = factory.make_name("description")
        event_name = random.choice(list(map_enum(EVENT_TYPES)))
        event_detail = EVENT_DETAILS[event_name]
        event_hub = NodeEventHub()

        yield event_hub.logByID(event_name, system_id, description)
        protocol.RegisterEventType.assert_called_once_with(
            protocol,
            name=event_name,
            description=event_detail.description,
            level=event_detail.level,
        )
        protocol.SendEvent.assert_called_once()

        protocol.RegisterEventType.reset_mock()
        protocol.SendEvent.reset_mock()

        yield event_hub.logByID(event_name, system_id, description)
        protocol.RegisterEventType.assert_not_called()
        protocol.SendEvent.assert_called_once()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_updates_cache_if_event_type_not_found(self, request, mocker):
        yield self.patch_rpc_methods(
            request,
            mocker,
            side_effect=[succeed({}), fail(NoSuchEventType.from_name("foo"))],
        )

        system_id = factory.make_name("system_id")
        description = factory.make_name("description")
        event_name = random.choice(list(map_enum(EVENT_TYPES)))
        event_hub = NodeEventHub()

        yield event_hub.logByID(event_name, system_id, description)
        assert {event_name} == event_hub._types_registered
        with pytest.raises(
            NoSuchEventType,
            match=r"Event type with name=foo could not be found\.",
        ):
            yield event_hub.logByID(event_name, system_id, description)


@pytest.mark.rack_reactor_guard
class TestSendEventMACAddress:
    """Tests for `NodeEventHub.logByMAC`."""

    @inlineCallbacks
    def patch_rpc_methods(self, request, mocker, side_effect=None):
        mocker.patch.object(
            clusterservice, "get_all_interfaces_definition", return_value={}
        )
        fixture = MockLiveClusterToRegionRPCFixture()
        shutdown = [lambda: succeed(None)]
        request.addfinalizer(
            lambda: wait_for(timeout=TIMEOUT)(_cleanup_rpc_fixture)(
                fixture, shutdown[0]
            )
        )
        yield fixture.setUp()
        protocol, connecting = fixture.makeEventLoop(
            region.SendEventMACAddress, region.RegisterEventType
        )
        shutdown[0] = yield connecting
        protocol.SendEventMACAddress.side_effect = side_effect
        return protocol

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_event_is_sent_to_region(self, request, mocker):
        protocol = yield self.patch_rpc_methods(request, mocker)

        mac_address = factory.make_mac_address()
        description = factory.make_name("description")
        event_name = random.choice(list(map_enum(EVENT_TYPES)))

        yield NodeEventHub().logByMAC(event_name, mac_address, description)

        protocol.SendEventMACAddress.assert_called_once_with(
            protocol,
            type_name=event_name,
            mac_address=mac_address,
            description=description,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_failure_is_suppressed_if_node_not_found(self, request, mocker):
        protocol = yield self.patch_rpc_methods(
            request, mocker, side_effect=[fail(NoSuchNode())]
        )

        mac_address = factory.make_mac_address()
        description = factory.make_name("description")
        event_name = random.choice(list(map_enum(EVENT_TYPES)))

        yield NodeEventHub().logByMAC(event_name, mac_address, description)

        protocol.SendEventMACAddress.assert_called_once_with(
            protocol,
            type_name=event_name,
            mac_address=mac_address,
            description=description,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_event_type_is_registered_on_first_call_only(
        self, request, mocker
    ):
        protocol = yield self.patch_rpc_methods(
            request, mocker, side_effect=[{}, {}]
        )

        mac_address = factory.make_mac_address()
        description = factory.make_name("description")
        event_name = random.choice(list(map_enum(EVENT_TYPES)))
        event_detail = EVENT_DETAILS[event_name]
        event_hub = NodeEventHub()

        yield event_hub.logByMAC(event_name, mac_address, description)
        protocol.RegisterEventType.assert_called_once_with(
            protocol,
            name=event_name,
            description=event_detail.description,
            level=event_detail.level,
        )
        protocol.SendEventMACAddress.assert_called_once()

        protocol.RegisterEventType.reset_mock()
        protocol.SendEventMACAddress.reset_mock()

        yield event_hub.logByMAC(event_name, mac_address, description)
        protocol.RegisterEventType.assert_not_called()
        protocol.SendEventMACAddress.assert_called_once()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_updates_cache_if_event_type_not_found(self, request, mocker):
        yield self.patch_rpc_methods(
            request,
            mocker,
            side_effect=[succeed({}), fail(NoSuchEventType.from_name("foo"))],
        )

        mac_address = factory.make_mac_address()
        description = factory.make_name("description")
        event_name = random.choice(list(map_enum(EVENT_TYPES)))
        event_hub = NodeEventHub()

        yield event_hub.logByMAC(event_name, mac_address, description)
        assert {event_name} == event_hub._types_registered
        with pytest.raises(
            NoSuchEventType,
            match=r"Event type with name=foo could not be found\.",
        ):
            yield event_hub.logByMAC(event_name, mac_address, description)


@pytest.mark.rack_reactor_guard
class TestSendEventIPAddress:
    """Tests for `NodeEventHub.logByIP`."""

    @inlineCallbacks
    def patch_rpc_methods(self, request, mocker, side_effect=None):
        mocker.patch.object(
            clusterservice, "get_all_interfaces_definition", return_value={}
        )
        fixture = MockLiveClusterToRegionRPCFixture()
        shutdown = [lambda: succeed(None)]
        request.addfinalizer(
            lambda: wait_for(timeout=TIMEOUT)(_cleanup_rpc_fixture)(
                fixture, shutdown[0]
            )
        )
        yield fixture.setUp()
        protocol, connecting = fixture.makeEventLoop(
            region.SendEventIPAddress, region.RegisterEventType
        )
        shutdown[0] = yield connecting
        protocol.SendEventIPAddress.side_effect = side_effect
        return protocol

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_event_is_sent_to_region(self, request, mocker):
        protocol = yield self.patch_rpc_methods(request, mocker)

        ip_address = factory.make_ip_address()
        description = factory.make_name("description")
        event_name = random.choice(list(map_enum(EVENT_TYPES)))

        yield NodeEventHub().logByIP(event_name, ip_address, description)

        protocol.SendEventIPAddress.assert_called_once_with(
            protocol,
            type_name=event_name,
            ip_address=ip_address,
            description=description,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_failure_is_suppressed_if_node_not_found(self, request, mocker):
        protocol = yield self.patch_rpc_methods(
            request, mocker, side_effect=[fail(NoSuchNode())]
        )

        ip_address = factory.make_ip_address()
        description = factory.make_name("description")
        event_name = random.choice(list(map_enum(EVENT_TYPES)))

        yield NodeEventHub().logByIP(event_name, ip_address, description)

        protocol.SendEventIPAddress.assert_called_once_with(
            protocol,
            type_name=event_name,
            ip_address=ip_address,
            description=description,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_event_type_is_registered_on_first_call_only(
        self, request, mocker
    ):
        protocol = yield self.patch_rpc_methods(
            request, mocker, side_effect=[{}, {}]
        )

        ip_address = factory.make_ip_address()
        description = factory.make_name("description")
        event_name = random.choice(list(map_enum(EVENT_TYPES)))
        event_detail = EVENT_DETAILS[event_name]
        event_hub = NodeEventHub()

        yield event_hub.logByIP(event_name, ip_address, description)
        protocol.RegisterEventType.assert_called_once_with(
            protocol,
            name=event_name,
            description=event_detail.description,
            level=event_detail.level,
        )
        protocol.SendEventIPAddress.assert_called_once_with(
            protocol,
            ip_address=ip_address,
            type_name=event_name,
            description=description,
        )

        protocol.RegisterEventType.reset_mock()
        protocol.SendEventIPAddress.reset_mock()

        yield event_hub.logByIP(event_name, ip_address, description)
        protocol.RegisterEventType.assert_not_called()
        protocol.SendEventIPAddress.assert_called_once()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_updates_cache_if_event_type_not_found(self, request, mocker):
        yield self.patch_rpc_methods(
            request,
            mocker,
            side_effect=[succeed({}), fail(NoSuchEventType.from_name("foo"))],
        )

        ip_address = factory.make_ip_address()
        description = factory.make_name("description")
        event_name = random.choice(list(map_enum(EVENT_TYPES)))
        event_hub = NodeEventHub()

        yield event_hub.logByIP(event_name, ip_address, description)
        assert {event_name} == event_hub._types_registered
        with pytest.raises(
            NoSuchEventType,
            match=r"Event type with name=foo could not be found\.",
        ):
            yield event_hub.logByIP(event_name, ip_address, description)
        assert set() == event_hub._types_registered
