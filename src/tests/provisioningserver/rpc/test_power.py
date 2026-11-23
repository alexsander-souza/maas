# Copyright 2014-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for :py:module:`~provisioningserver.rpc.power`."""

import logging
import random
import re
from unittest.mock import ANY, call, sentinel

from fixtures import FakeLogger
import pytest
from twisted.internet import reactor
from twisted.internet.defer import (
    fail,
    inlineCallbacks,
    maybeDeferred,
    succeed,
)
from twisted.internet.task import Clock
from twisted.python.failure import Failure

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.deferred import extract_result
from maastesting.factory import factory
from maastesting.twisted import always_fail_with, TwistedLoggerFixture
from provisioningserver.drivers import power as power_driver_module
from provisioningserver.drivers.power import DEFAULT_WAITING_POLICY, PowerError
from provisioningserver.drivers.power.registry import PowerDriverRegistry
from provisioningserver.events import EVENT_TYPES
from provisioningserver.rpc import clusterservice, exceptions, power, region
from provisioningserver.rpc.testing import MockLiveClusterToRegionRPCFixture
from provisioningserver.testing.events import EventTypesAllRegistered

TIMEOUT = get_testing_timeout()


@inlineCallbacks
def _cleanup_rpc_fixture(fixture, shutdown):
    try:
        yield shutdown()
    finally:
        yield fixture.cleanUp()


def suppress_reporting(mocker):
    mock = mocker.patch.object(power, "report_power_state")
    mock.side_effect = lambda deferred, *_args: deferred


@pytest.mark.rack_reactor_guard
class TestPowerHelpers:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker, request):
        mocker.patch.object(
            clusterservice, "get_all_interfaces_definition"
        ).return_value = {}
        self.request = request

    @inlineCallbacks
    def patch_rpc_methods(self, request):
        fixture = MockLiveClusterToRegionRPCFixture()
        shutdown = [lambda: succeed(None)]
        request.addfinalizer(
            lambda: wait_for(timeout=TIMEOUT)(_cleanup_rpc_fixture)(
                fixture, shutdown[0]
            )
        )
        yield fixture.setUp()
        protocol, connecting = fixture.makeEventLoop(
            region.MarkNodeFailed,
            region.UpdateNodePowerState,
            region.SendEvent,
        )
        shutdown[0] = yield connecting
        return protocol

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_state_update_calls_UpdateNodePowerState(self, request):
        system_id = factory.make_name("system_id")
        state = random.choice(["on", "off"])
        protocol = yield self.patch_rpc_methods(request)
        yield power.power_state_update(system_id, state)
        protocol.UpdateNodePowerState.assert_called_once_with(
            ANY, system_id=system_id, power_state=state
        )


@pytest.mark.parametrize(
    "power_type,power_driver,func,waits,calls",
    [
        (
            driver.name,
            driver,
            "perform_power_driver_query",
            []
            if driver.name in PowerDriverRegistry
            else DEFAULT_WAITING_POLICY,
            1
            if driver.name in PowerDriverRegistry
            else len(DEFAULT_WAITING_POLICY),
        )
        for _, driver in PowerDriverRegistry
        if driver.queryable
    ],
    ids=[driver.name for _, driver in PowerDriverRegistry if driver.queryable],
)
@pytest.mark.rack_reactor_guard
class TestPowerQueryExceptions:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        mocker.patch.object(
            power_driver_module, "deferToThread", maybeDeferred
        )

    @wait_for(timeout=TIMEOUT)
    def test_report_power_state_reports_all_exceptions(
        self, power_type, power_driver, func, waits, calls, mocker
    ):
        with (
            TwistedLoggerFixture() as logger_twisted,
            FakeLogger("maas") as logger_maaslog,
        ):
            exception_type = factory.make_exception_type()
            exception_message = factory.make_string()
            exception = exception_type(exception_message)
            query = mocker.patch.object(power, func, autospec=True)
            query.side_effect = always_fail_with(exception)
            power_state_update = mocker.patch.object(
                power, "power_state_update", autospec=True
            )
            power_state_update.return_value = succeed(None)
            send_node_event = mocker.patch.object(
                power, "send_node_event", autospec=True
            )
            send_node_event.return_value = succeed(None)
            mocker.patch.object(
                power_driver, "detect_missing_packages"
            ).return_value = []

            system_id = factory.make_name("system_id")
            hostname = factory.make_name("hostname")
            context = sentinel.context
            clock = Clock()
            deferred = power.get_power_state(
                system_id, hostname, power_type, context, clock
            )
            deferred = power.report_power_state(deferred, system_id, hostname)

            for wait in waits:
                assert not deferred.called
                clock.advance(wait)
            assert deferred.called
            with pytest.raises(exception_type):
                extract_result(deferred)

            expected_call = call(system_id, hostname, power_type, context)
            query.assert_has_calls([expected_call] * calls)
            expected_message = (
                f"{hostname}: Power state could not be queried: "
                f"{exception_message}"
            )
            power_state_update.assert_called_once_with(system_id, "error")
            send_node_event.assert_called_once_with(
                EVENT_TYPES.NODE_POWER_QUERY_FAILED,
                system_id,
                hostname,
                exception_message,
            )
            assert logger_twisted.output == ""
            assert logger_maaslog.output == expected_message + "\n"


@pytest.mark.rack_reactor_guard
class TestPowerQuery:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker, request):
        self.mocker = mocker
        self.request = request
        fixture = EventTypesAllRegistered()
        fixture.setUp()
        request.addfinalizer(fixture.cleanUp)
        mocker.patch.object(
            power_driver_module, "deferToThread", maybeDeferred
        )
        for _, power_driver in PowerDriverRegistry:
            mocker.patch.object(
                power_driver, "detect_missing_packages"
            ).return_value = []
        mocker.patch.object(
            clusterservice, "get_all_interfaces_definition"
        ).return_value = {}

    @inlineCallbacks
    def patch_rpc_methods(self, request, return_value=None, side_effect=None):
        fixture = MockLiveClusterToRegionRPCFixture()
        shutdown = [lambda: succeed(None)]
        request.addfinalizer(
            lambda: wait_for(timeout=TIMEOUT)(_cleanup_rpc_fixture)(
                fixture, shutdown[0]
            )
        )
        yield fixture.setUp()
        protocol, connecting = fixture.makeEventLoop(
            region.SendEvent, region.UpdateNodePowerState
        )
        shutdown[0] = yield connecting
        protocol.UpdateNodePowerState.return_value = succeed(
            return_value or {}
        )
        protocol.UpdateNodePowerState.side_effect = side_effect
        return protocol

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_query_failure_emits_event(self, request):
        system_id = factory.make_name("system_id")
        hostname = factory.make_name("hostname")
        message = factory.make_name("message")
        protocol = yield self.patch_rpc_methods(request)

        yield power.power_query_failure(
            system_id, hostname, Failure(Exception(message))
        )

        protocol.SendEvent.assert_called_once_with(
            protocol,
            type_name=EVENT_TYPES.NODE_POWER_QUERY_FAILED,
            system_id=system_id,
            description=message,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_get_power_state_queries_node(self):
        system_id = factory.make_name("system_id")
        hostname = factory.make_name("hostname")
        power_driver = random.choice(
            [driver for _, driver in PowerDriverRegistry if driver.queryable]
        )
        power_state = random.choice(["on", "off"])
        context = {
            factory.make_name("context-key"): factory.make_name("context-val")
        }
        mock_perform_power_driver_query = self.mocker.patch.object(
            power, "perform_power_driver_query"
        )
        mock_perform_power_driver_query.return_value = power_state

        result = yield power.get_power_state(
            system_id, hostname, power_driver.name, context
        )

        assert result == power_state
        power_driver.detect_missing_packages.assert_called_once_with()
        power.perform_power_driver_query.assert_called_once_with(
            system_id, hostname, power_driver.name, context
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_get_power_state_fails_for_missing_packages(self):
        system_id = factory.make_name("system_id")
        hostname = factory.make_name("hostname")
        power_driver = random.choice(
            [driver for _, driver in PowerDriverRegistry if driver.queryable]
        )
        context = {
            factory.make_name("context-key"): factory.make_name("context-val")
        }
        power_driver.detect_missing_packages.return_value = ["gone"]

        with pytest.raises(exceptions.PowerActionFail):
            yield power.get_power_state(
                system_id, hostname, power_driver.name, context
            )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_report_power_state_changes_power_state_if_failure(self, request):
        system_id = factory.make_name("system_id")
        hostname = factory.make_name("hostname")
        err_msg = factory.make_name("error")
        protocol = yield self.patch_rpc_methods(request)

        with pytest.raises(exceptions.PowerActionFail) as exc:
            yield power.report_power_state(
                fail(exceptions.PowerActionFail(err_msg)),
                system_id,
                hostname,
            )

        assert str(exc.value) == err_msg
        protocol.UpdateNodePowerState.assert_called_once_with(
            protocol, system_id=system_id, power_state="error"
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_report_power_state_changes_power_state_if_success(self, request):
        system_id = factory.make_name("system_id")
        hostname = factory.make_name("hostname")
        power_state = random.choice(["on", "off"])
        protocol = yield self.patch_rpc_methods(request)

        result = yield power.report_power_state(
            succeed(power_state), system_id, hostname
        )

        assert result == power_state
        protocol.UpdateNodePowerState.assert_called_once_with(
            protocol, system_id=system_id, power_state=power_state
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_report_power_state_changes_power_state_if_unknown(self, request):
        system_id = factory.make_name("system_id")
        hostname = factory.make_name("hostname")
        protocol = yield self.patch_rpc_methods(request)

        result = yield power.report_power_state(
            succeed("unknown"), system_id, hostname
        )

        assert result == "unknown"
        protocol.UpdateNodePowerState.assert_called_once_with(
            protocol, system_id=system_id, power_state="unknown"
        )


@pytest.mark.rack_reactor_guard
class TestPowerQueryAsync:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker, request):
        self.mocker = mocker
        self.request = request
        fixture = EventTypesAllRegistered()
        fixture.setUp()
        request.addfinalizer(fixture.cleanUp)
        mocker.patch.object(
            power_driver_module, "deferToThread", maybeDeferred
        )
        for _, power_driver in PowerDriverRegistry:
            mocker.patch.object(
                power_driver, "detect_missing_packages"
            ).return_value = []
        mocker.patch.object(
            clusterservice, "get_all_interfaces_definition"
        ).return_value = {}

    def make_node(self, power_type=None):
        system_id = factory.make_name("system_id")
        hostname = factory.make_name("hostname")
        if power_type is None:
            power_type = random.choice(
                [
                    driver.name
                    for _, driver in PowerDriverRegistry
                    if driver.queryable
                ]
            )
        state = random.choice(["on", "off", "unknown", "error"])
        context = {
            factory.make_name("context-key"): (
                factory.make_name("context-val")
            )
        }
        return {
            "context": context,
            "hostname": hostname,
            "power_state": state,
            "power_type": power_type,
            "system_id": system_id,
        }

    def make_nodes(self, count=3):
        nodes = [self.make_node() for _ in range(count)]
        # Sanity check that these nodes are something that can emerge
        # from a call to ListNodePowerParameters.
        region.ListNodePowerParameters.makeResponse({"nodes": nodes}, None)
        return nodes

    def pick_alternate_state(self, state):
        return random.choice(
            [
                value
                for value in ["on", "off", "unknown", "error"]
                if value != state
            ]
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_query_all_nodes_gets_and_reports_power_state(self):
        nodes = self.make_nodes()
        power_states = [node["power_state"] for node in nodes]
        queries = list(map(succeed, power_states))
        get_power_state = self.mocker.patch.object(power, "get_power_state")
        get_power_state.side_effect = queries
        report_power_state = self.mocker.patch.object(
            power, "report_power_state"
        )
        report_power_state.side_effect = lambda d, sid, hn: d

        yield power.query_all_nodes(nodes)
        get_power_state.assert_has_calls(
            [
                call(
                    node["system_id"],
                    node["hostname"],
                    node["power_type"],
                    node["context"],
                    clock=reactor,
                )
                for node in nodes
            ]
        )
        report_power_state.assert_has_calls(
            [
                call(query, node["system_id"], node["hostname"])
                for query, node in zip(queries, nodes, strict=True)
            ]
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_query_all_nodes_skips_nodes_in_action_registry(self):
        nodes = self.make_nodes()
        first_system_id = nodes[0]["system_id"]
        power.power_action_registry[first_system_id] = sentinel.action
        self.request.addfinalizer(
            lambda: power.power_action_registry.pop(first_system_id)
        )
        power_states = [node["power_state"] for node in nodes[1:]]
        get_power_state = self.mocker.patch.object(power, "get_power_state")
        get_power_state.side_effect = map(succeed, power_states)
        suppress_reporting(self.mocker)

        yield power.query_all_nodes(nodes)
        get_power_state.assert_has_calls(
            [
                call(
                    node["system_id"],
                    node["hostname"],
                    node["power_type"],
                    node["context"],
                    clock=reactor,
                )
                for node in nodes[1:]
            ]
        )
        assert (
            call(
                nodes[0]["system_id"],
                nodes[0]["hostname"],
                nodes[0]["power_type"],
                nodes[0]["context"],
                clock=reactor,
            )
            not in get_power_state.mock_calls
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_query_all_nodes_only_queries_queryable_power_types(self):
        nodes = self.make_nodes()
        nodes.append(self.make_node(power_type="manual"))
        power_states = [node["power_state"] for node in nodes]
        get_power_state = self.mocker.patch.object(power, "get_power_state")
        get_power_state.side_effect = map(succeed, power_states)
        suppress_reporting(self.mocker)

        yield power.query_all_nodes(nodes)
        get_power_state.assert_has_calls(
            [
                call(
                    node["system_id"],
                    node["hostname"],
                    node["power_type"],
                    node["context"],
                    clock=reactor,
                )
                for node in nodes
                if node["power_type"] in PowerDriverRegistry
            ]
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_query_all_nodes_swallows_PowerActionFail(self):
        node1, node2 = self.make_nodes(2)
        new_state_2 = self.pick_alternate_state(node2["power_state"])
        get_power_state = self.mocker.patch.object(power, "get_power_state")
        error_msg = factory.make_name("error")
        get_power_state.side_effect = [
            fail(exceptions.PowerActionFail(error_msg)),
            succeed(new_state_2),
        ]
        suppress_reporting(self.mocker)

        with FakeLogger("maas.power", level=logging.DEBUG) as maaslog:
            yield power.query_all_nodes([node1, node2])

        assert re.search(
            rf"hostname-.*: Could not query power state: {error_msg}",
            maaslog.output,
        )
        assert re.search(
            rf"hostname-.*: Power state has changed from .* to {new_state_2}",
            maaslog.output,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_query_all_nodes_swallows_PowerError(self):
        node1, node2 = self.make_nodes(2)
        new_state_2 = self.pick_alternate_state(node2["power_state"])
        get_power_state = self.mocker.patch.object(power, "get_power_state")
        error_msg = factory.make_name("error")
        get_power_state.side_effect = [
            fail(PowerError(error_msg)),
            succeed(new_state_2),
        ]
        suppress_reporting(self.mocker)

        with FakeLogger("maas.power", level=logging.DEBUG) as maaslog:
            yield power.query_all_nodes([node1, node2])

        assert re.search(
            rf"{node1['hostname']}: Could not query power state: {error_msg}",
            maaslog.output,
        )
        assert re.search(
            rf"{node2['hostname']}: Power state has changed from {node2['power_state']} to {new_state_2}",
            maaslog.output,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_query_all_nodes_swallows_NoSuchNode(self):
        node1, node2 = self.make_nodes(2)
        new_state_2 = self.pick_alternate_state(node2["power_state"])
        get_power_state = self.mocker.patch.object(power, "get_power_state")
        get_power_state.side_effect = [
            fail(exceptions.NoSuchNode()),
            succeed(new_state_2),
        ]
        suppress_reporting(self.mocker)

        with FakeLogger("maas.power", level=logging.DEBUG) as maaslog:
            yield power.query_all_nodes([node1, node2])

        assert re.search(
            rf"{node2['hostname']}: Power state has changed from {node2['power_state']} to {new_state_2}",
            maaslog.output,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_query_all_nodes_swallows_Exception(self):
        node1, node2 = self.make_nodes(2)
        error_message = factory.make_name("error")
        error_type = factory.make_exception_type()
        new_state_2 = self.pick_alternate_state(node2["power_state"])
        get_power_state = self.mocker.patch.object(power, "get_power_state")
        get_power_state.side_effect = [
            fail(error_type(error_message)),
            succeed(new_state_2),
        ]
        suppress_reporting(self.mocker)
        maaslog = FakeLogger("maas.power", level=logging.DEBUG)
        twistlog = TwistedLoggerFixture()

        with maaslog, twistlog:
            yield power.query_all_nodes([node1, node2])

        assert re.search(
            rf"{node1['hostname']}: Failed to refresh power state: {error_message}",
            maaslog.output,
        )
        assert re.search(
            rf"{node2['hostname']}: Power state has changed from {node2['power_state']} to {new_state_2}",
            maaslog.output,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_query_all_nodes_returns_deferredlist_of_number_of_nodes(self):
        node1, node2 = self.make_nodes(2)
        get_power_state = self.mocker.patch.object(power, "get_power_state")
        get_power_state.side_effect = [
            succeed(node1["power_state"]),
            succeed(node2["power_state"]),
        ]
        suppress_reporting(self.mocker)

        results = yield power.query_all_nodes([node1, node2])
        assert [
            (True, node1["power_state"]),
            (True, node2["power_state"]),
        ] == results
