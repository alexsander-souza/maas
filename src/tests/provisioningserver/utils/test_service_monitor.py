# Copyright 2015-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `provisioningserver.service_monitor`."""

import json
from json import JSONDecodeError
import logging
import os
import random
from unittest.mock import MagicMock, Mock, sentinel

from fixtures import FakeLogger
import pytest
from twisted.internet import reactor
from twisted.internet.defer import DeferredLock, fail, inlineCallbacks, succeed
from twisted.internet.interfaces import IConsumer
from twisted.internet.task import deferLater
from twisted.web._newclient import Response
from twisted.web.client import Agent
from twisted.web.http_headers import Headers
from zope.interface import implementer

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.factory import factory
from provisioningserver.utils import service_monitor as service_monitor_module
from provisioningserver.utils.service_monitor import (
    Service,
    SERVICE_STATE,
    ServiceActionError,
    ServiceMonitor,
    ServiceNotOnError,
    ServiceParsingError,
    ServiceState,
    ServiceUnknownError,
    ToggleableService,
)

TIMEOUT = get_testing_timeout()

EMPTY_SET = frozenset()


def pick_observed_state(*, but_not=EMPTY_SET):
    return factory.pick_enum(
        SERVICE_STATE,
        but_not={SERVICE_STATE.ANY, SERVICE_STATE.OBSERVE, *but_not},
    )


def pick_expected_state(*, but_not=EMPTY_SET):
    return factory.pick_enum(
        SERVICE_STATE, but_not={SERVICE_STATE.UNKNOWN, *but_not}
    )


def make_fake_service(expected_state=None, status_info=None):
    fake_name = factory.make_name("name")
    fake_service_name = factory.make_name("service")
    fake_snap_service_name = factory.make_name("snap-service")
    if expected_state is None:
        if factory.pick_bool():
            expected_state = SERVICE_STATE.ON
        else:
            expected_state = SERVICE_STATE.OFF

    class FakeService(Service):
        name = fake_name
        service_name = fake_service_name
        snap_service_name = fake_snap_service_name

        def getExpectedState(self):
            return succeed((expected_state, status_info))

    return FakeService()


@pytest.mark.parametrize(
    ("state_observed", "state_expected"),
    [
        pytest.param(
            observed,
            expected,
            id=f"observed={observed.name},expected={expected.name}",
        )
        for observed in SERVICE_STATE
        if observed not in {SERVICE_STATE.ANY, SERVICE_STATE.OBSERVE}
        for expected in SERVICE_STATE
        if expected not in {SERVICE_STATE.UNKNOWN, SERVICE_STATE.OBSERVE}
    ],
)
@pytest.mark.rack_reactor_guard
class TestServiceState:
    """Tests for `ServiceState`."""

    expected_status_strings = {
        # (state-observed, state-expected): status-string
        (SERVICE_STATE.ON, SERVICE_STATE.ON): "running",
        (SERVICE_STATE.ON, SERVICE_STATE.OFF): "running",
        (SERVICE_STATE.ON, SERVICE_STATE.DEAD): "running",
        (SERVICE_STATE.ON, SERVICE_STATE.ANY): "running",
        (SERVICE_STATE.OFF, SERVICE_STATE.ON): "dead",
        (SERVICE_STATE.OFF, SERVICE_STATE.OFF): "off",
        (SERVICE_STATE.OFF, SERVICE_STATE.DEAD): "off",
        (SERVICE_STATE.OFF, SERVICE_STATE.ANY): "off",
        (SERVICE_STATE.DEAD, SERVICE_STATE.ON): "dead",
        (SERVICE_STATE.DEAD, SERVICE_STATE.OFF): "off",
        (SERVICE_STATE.DEAD, SERVICE_STATE.DEAD): "off",
        (SERVICE_STATE.DEAD, SERVICE_STATE.ANY): "off",
        (SERVICE_STATE.UNKNOWN, SERVICE_STATE.ON): "unknown",
        (SERVICE_STATE.UNKNOWN, SERVICE_STATE.OFF): "unknown",
        (SERVICE_STATE.UNKNOWN, SERVICE_STATE.DEAD): "unknown",
        (SERVICE_STATE.UNKNOWN, SERVICE_STATE.ANY): "unknown",
    }

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_returns_service_status_string(
        self, state_observed, state_expected
    ):
        service = make_fake_service(state_expected)
        state = ServiceState(state_observed, None)
        status_string, _ = yield state.getStatusInfo(service)

        assert (
            status_string
            == self.expected_status_strings[state_observed, state_expected]
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_returns_service_info_message(
        self, state_observed, state_expected
    ):
        example_message = factory.make_string(60, spaces=True)
        example_process_state = factory.make_name("process-state")
        service = make_fake_service(state_expected, example_message)
        state = ServiceState(state_observed, example_process_state)
        status_string, status_message = yield state.getStatusInfo(service)

        if state_expected == SERVICE_STATE.ON:
            if state_observed == SERVICE_STATE.OFF:
                assert (
                    status_message
                    == service.service_name + " is currently stopped."
                )
            elif state_observed == SERVICE_STATE.DEAD:
                assert status_message == (
                    service.service_name
                    + " failed to start, process result: ("
                    + example_process_state
                    + ")"
                )
            else:
                assert status_message == example_message
        else:
            assert status_message == example_message


@pytest.mark.rack_reactor_guard
class TestServiceMonitor:
    """Tests for `ServiceMonitor`."""

    @pytest.fixture(autouse=True)
    def _use_mocker(self, mocker):
        self.mocker = mocker

    def make_service_monitor(self, fake_services=None, pebble_agent=None):
        if fake_services is None:
            fake_services = [make_fake_service() for _ in range(3)]
        return ServiceMonitor(*fake_services, pebble_agent=pebble_agent)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_getServiceLock_returns_lock_for_service(self):
        service_monitor = self.make_service_monitor()
        name = factory.make_name("service")
        lock = yield service_monitor._getServiceLock(name)
        assert isinstance(lock, DeferredLock)

    @wait_for(timeout=TIMEOUT)
    def test_getServiceByName_returns_service(self):
        fake_service = make_fake_service()
        service_monitor = self.make_service_monitor([fake_service])
        assert fake_service == service_monitor.getServiceByName(
            fake_service.name
        )

    @wait_for(timeout=TIMEOUT)
    def test_getServiceByName_raises_ServiceUnknownError(self):
        service_monitor = self.make_service_monitor()
        with pytest.raises(ServiceUnknownError):
            service_monitor.getServiceByName(factory.make_name("service"))

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_updateServiceState_updates_stored_service_state(self):
        service_monitor = self.make_service_monitor()
        name = factory.make_name("service")
        active_state = pick_observed_state()
        process_state = random.choice(["running", "dead"])
        observed_state = yield service_monitor._updateServiceState(
            name, active_state, process_state
        )
        state = service_monitor._serviceStates[name]
        assert (active_state, process_state) == (
            state.active_state,
            state.process_state,
        )
        assert state == observed_state

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_updateServiceState_does_not_hold_service_lock(self):
        service_monitor = self.make_service_monitor()
        service_lock = self.mocker.patch.object(
            service_monitor, "_getServiceLock"
        )
        name = factory.make_name("service")
        active_state = pick_observed_state()
        process_state = random.choice(["running", "dead"])
        yield service_monitor._updateServiceState(
            name, active_state, process_state
        )
        service_lock.acquire.assert_not_called()
        service_lock.release.assert_not_called()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_getServiceState_with_now_True(self):
        fake_service = make_fake_service()
        service_monitor = self.make_service_monitor([fake_service])
        active_state = pick_observed_state()
        process_state = random.choice(["running", "dead"])
        mock_loadServiceState = self.mocker.patch.object(
            service_monitor, "_loadServiceState"
        )
        mock_loadServiceState.return_value = succeed(
            (active_state, process_state)
        )
        observed_state = yield service_monitor.getServiceState(
            fake_service.name, now=True
        )
        state = service_monitor._serviceStates[fake_service.name]
        assert (active_state, process_state) == (
            state.active_state,
            state.process_state,
        )
        assert state == observed_state
        mock_loadServiceState.assert_called_once_with(fake_service)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_getServiceState_with_now_False(self):
        fake_service = make_fake_service()
        service_monitor = self.make_service_monitor([fake_service])
        mock_loadServiceState = self.mocker.patch.object(
            service_monitor, "_loadServiceState"
        )
        observed_state = yield service_monitor.getServiceState(
            fake_service.name, now=False
        )
        state = service_monitor._serviceStates[fake_service.name]
        assert (SERVICE_STATE.UNKNOWN, None) == (
            state.active_state,
            state.process_state,
        )
        assert state == observed_state
        mock_loadServiceState.assert_not_called()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_ensureServices_returns_dict_for_states(self):
        fake_services = [make_fake_service() for _ in range(3)]
        expected_states = {}
        for service in fake_services:
            active_state = pick_observed_state()
            process_state = random.choice(["running", "dead"])
            expected_states[service.name] = ServiceState(
                active_state, process_state
            )
        service_monitor = self.make_service_monitor(fake_services)
        self.mocker.patch.object(
            service_monitor, "ensureService"
        ).side_effect = lambda name: succeed(expected_states[name])
        observed = yield service_monitor.ensureServices()
        assert expected_states == observed

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_ensureServices_handles_errors(self):
        services = make_fake_service(), make_fake_service()
        service_monitor = self.make_service_monitor(services)
        service_states = {
            service.name: ServiceState(
                pick_observed_state(), random.choice(["running", "dead"])
            )
            for service in services
        }
        service_monitor._serviceStates.update(service_states)
        self.mocker.patch.object(service_monitor, "ensureService")

        def raise_exception(service_name):
            raise factory.make_exception(service_name + " broke")

        def raise_exception_later(service_name):
            return deferLater(reactor, 0, raise_exception, service_name)

        service_monitor.ensureService.side_effect = raise_exception_later
        with FakeLogger("maas.service_monitor") as logger:
            observed = yield service_monitor.ensureServices()
        assert observed == service_states
        for service in services:
            assert (
                f"While monitoring service '{service.name}' an error was encountered: {service.name} broke"
                in logger.output
            )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_ensureServices_calls__ensureService(self):
        fake_service = make_fake_service()
        service_monitor = self.make_service_monitor([fake_service])
        active_state = pick_observed_state()
        process_state = random.choice(["running", "dead"])
        service_state = ServiceState(active_state, process_state)
        mock_ensureService = self.mocker.patch.object(
            service_monitor, "_ensureService"
        )
        mock_ensureService.return_value = succeed(service_state)
        observed = yield service_monitor.ensureService(fake_service.name)
        assert service_state == observed
        mock_ensureService.assert_called_once_with(fake_service)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_restartService_raises_ServiceNotOnError(self):
        fake_service = make_fake_service(SERVICE_STATE.OFF)
        service_monitor = self.make_service_monitor([fake_service])
        with pytest.raises(
            ServiceNotOnError,
            match=rf"Service '{fake_service.service_name}' is not expected to be on, unable to restart\.",
        ):
            yield service_monitor.restartService(fake_service.name)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_restartService_performs_restart(self):
        fake_service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor([fake_service])
        mock_performServiceAction = self.mocker.patch.object(
            service_monitor, "_performServiceAction"
        )
        mock_performServiceAction.return_value = succeed(None)
        service_state = ServiceState(SERVICE_STATE.ON, "running")
        mock_getServiceState = self.mocker.patch.object(
            service_monitor, "getServiceState"
        )
        mock_getServiceState.return_value = succeed(service_state)
        observed = yield service_monitor.restartService(fake_service.name)
        assert service_state == observed
        mock_getServiceState.assert_called_once_with(
            fake_service.name, now=True
        )
        mock_performServiceAction.assert_called_once_with(
            fake_service, "restart"
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_restartService_raises_ServiceActionError_if_not_on(self):
        fake_service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor([fake_service])
        mock_performServiceAction = self.mocker.patch.object(
            service_monitor, "_performServiceAction"
        )
        mock_performServiceAction.return_value = succeed(None)
        active_state = pick_observed_state(but_not={SERVICE_STATE.ON})
        service_state = ServiceState(active_state, "dead")
        mock_getServiceState = self.mocker.patch.object(
            service_monitor, "getServiceState"
        )
        mock_getServiceState.return_value = succeed(service_state)
        with pytest.raises(
            ServiceActionError,
            match=rf"Service '{fake_service.service_name}' failed to restart",
        ):
            yield service_monitor.restartService(fake_service.name)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_reloadService_raises_ServiceNotOnError(self):
        fake_service = make_fake_service(SERVICE_STATE.OFF)
        service_monitor = self.make_service_monitor([fake_service])
        with pytest.raises(
            ServiceNotOnError,
            match=rf"Service '{fake_service.service_name}' is not expected to be on, unable to reload\.",
        ):
            yield service_monitor.reloadService(fake_service.name)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_reloadService_returns_when_if_on(self):
        fake_service = make_fake_service(SERVICE_STATE.OFF)
        service_monitor = self.make_service_monitor([fake_service])
        yield service_monitor.restartService(fake_service.name, if_on=True)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_reloadService_calls_ensureService_then_reloads(self):
        fake_service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor([fake_service])
        mock_performServiceAction = self.mocker.patch.object(
            service_monitor, "_performServiceAction"
        )
        mock_performServiceAction.return_value = succeed(None)
        mock_ensureService = self.mocker.patch.object(
            service_monitor, "ensureService"
        )
        mock_ensureService.return_value = succeed(
            ServiceState(SERVICE_STATE.ON, "running")
        )
        yield service_monitor.reloadService(fake_service.name)
        mock_ensureService.assert_called_once_with(fake_service.name)
        mock_performServiceAction.assert_called_once_with(
            fake_service, "reload"
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_reloadService_raises_error_if_fails_to_start(self):
        fake_service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor([fake_service])
        mock_ensureService = self.mocker.patch.object(
            service_monitor, "ensureService"
        )
        mock_ensureService.return_value = succeed(
            ServiceState(SERVICE_STATE.OFF, "dead")
        )
        with pytest.raises(
            ServiceActionError,
            match=rf"Service '{fake_service.service_name}' is not running and could not be started to perform the reload",
        ):
            yield service_monitor.reloadService(fake_service.name)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_reloadService_returns_when_if_on_equals_false(self):
        fake_service = make_fake_service(SERVICE_STATE.OFF)
        service_monitor = self.make_service_monitor([fake_service])
        yield service_monitor.reloadService(fake_service.name, if_on=True)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_reloadService_always_calls_ensureService_then_reloads(self):
        fake_service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor([fake_service])
        mock_performServiceAction = self.mocker.patch.object(
            service_monitor, "_performServiceAction"
        )
        mock_performServiceAction.return_value = succeed(None)
        mock_ensureService = self.mocker.patch.object(
            service_monitor, "ensureService"
        )
        mock_ensureService.return_value = succeed(
            ServiceState(SERVICE_STATE.ON, "running")
        )
        yield service_monitor.reloadService(fake_service.name, if_on=True)
        mock_ensureService.assert_called_once_with(fake_service.name)
        mock_performServiceAction.assert_called_once_with(
            fake_service, "reload"
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_reloadService_always_raises_error_if_fails_to_start(self):
        fake_service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor([fake_service])
        mock_ensureService = self.mocker.patch.object(
            service_monitor, "ensureService"
        )
        mock_ensureService.return_value = succeed(
            ServiceState(SERVICE_STATE.OFF, "dead")
        )
        with pytest.raises(
            ServiceActionError,
            match=rf"Service '{fake_service.service_name}' is not running and could not be started to perform the reload",
        ):
            yield service_monitor.reloadService(fake_service.name, if_on=True)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_killService_performs_kill_then_ensureService(self):
        fake_service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor([fake_service])
        mock_performServiceAction = self.mocker.patch.object(
            service_monitor, "_performServiceAction"
        )
        mock_performServiceAction.return_value = succeed(None)
        mock_ensureService = self.mocker.patch.object(
            service_monitor, "ensureService"
        )
        mock_ensureService.return_value = succeed(
            ServiceState(SERVICE_STATE.ON, "running")
        )
        yield service_monitor.killService(fake_service.name)
        mock_ensureService.assert_called_once_with(fake_service.name)
        mock_performServiceAction.assert_called_once_with(fake_service, "kill")

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_killService_doesnt_fail_on_ServiceActionError(self):
        fake_service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor([fake_service])
        mock_performServiceAction = self.mocker.patch.object(
            service_monitor, "_performServiceAction"
        )
        mock_performServiceAction.return_value = fail(ServiceActionError())
        mock_ensureService = self.mocker.patch.object(
            service_monitor, "ensureService"
        )
        mock_ensureService.return_value = succeed(
            ServiceState(SERVICE_STATE.ON, "running")
        )
        yield service_monitor.killService(fake_service.name)
        mock_ensureService.assert_called_once_with(fake_service.name)
        mock_performServiceAction.assert_called_once_with(fake_service, "kill")

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_execPebbleServiceAction_calls_pebble_api(self):
        service_monitor = self.make_service_monitor()
        service_name = factory.make_name("service")
        action = "start"
        mock_pebble_request = self.mocker.patch.object(
            service_monitor, "_pebble_request"
        )
        mock_pebble_request.return_value = succeed({})
        result = yield service_monitor._execPebbleServiceAction(
            service_name, action
        )
        mock_pebble_request.assert_called_once_with(
            "POST",
            "/v1/services",
            payload={"action": action, "services": [service_name]},
        )
        assert result == (0, None, None)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_execPebbleServiceAction_turns_kill_to_stop(self):
        service_monitor = self.make_service_monitor()
        service_name = factory.make_name("service")
        mock_pebble_request = self.mocker.patch.object(
            service_monitor, "_pebble_request"
        )
        mock_pebble_request.return_value = succeed({})
        yield service_monitor._execPebbleServiceAction(service_name, "kill")
        mock_pebble_request.assert_called_once_with(
            "POST",
            "/v1/services",
            payload={"action": "stop", "services": [service_name]},
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_execPebbleServiceAction_raises_on_unsupported_action(self):
        service_monitor = self.make_service_monitor()
        service_name = factory.make_name("service")
        action = factory.make_name("action")
        with pytest.raises(
            ValueError, match=f"^Unknown pebble action '{action}'$"
        ):
            yield service_monitor._execPebbleServiceAction(
                service_name, action
            )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_execPebbleServiceAction_service_performs_valid_get_request(self):
        service_monitor = self.make_service_monitor()
        service_name = factory.make_name("service")
        mock_pebble_request = self.mocker.patch.object(
            service_monitor, "_pebble_request"
        )
        mock_pebble_request.return_value = succeed(
            {"result": [{"name": service_name, "current": "active"}]}
        )
        result = yield service_monitor._execPebbleServiceAction(
            service_name, "services"
        )
        mock_pebble_request.assert_called_once_with(
            "GET", f"/v1/services?names={service_name}", payload={}
        )
        assert result == (0, f"{service_name} active", None)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_execPebbleServiceAction_reload_sends_sighup(self):
        service_monitor = self.make_service_monitor()
        service_name = factory.make_name("service")
        mock_pebble_request = self.mocker.patch.object(
            service_monitor, "_pebble_request"
        )
        mock_pebble_request.return_value = succeed({})
        yield service_monitor._execPebbleServiceAction(service_name, "reload")
        mock_pebble_request.assert_called_once_with(
            "POST",
            "/v1/signals",
            payload={"signal": "SIGHUP", "services": [service_name]},
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_execPebbleServiceAction_signal_sends_signal(self):
        service_monitor = self.make_service_monitor()
        service_name = factory.make_name("service")
        mock_pebble_request = self.mocker.patch.object(
            service_monitor, "_pebble_request"
        )
        mock_pebble_request.return_value = succeed({})
        signal = "SIGWHATEVER"
        yield service_monitor._execPebbleServiceAction(
            service_name, "signal", extra_opts=[signal]
        )
        mock_pebble_request.assert_called_once_with(
            "POST",
            "/v1/signals",
            payload={"signal": signal, "services": [service_name]},
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_execPebbleServiceAction_signal_raises_on_multiple_signals(self):
        service_monitor = self.make_service_monitor()
        service_name = factory.make_name("service")
        mock_pebble_request = self.mocker.patch.object(
            service_monitor, "_pebble_request"
        )
        mock_pebble_request.return_value = succeed({})
        with pytest.raises(
            ValueError, match="^Multiple signal names provided$"
        ):
            yield service_monitor._execPebbleServiceAction(
                service_name,
                "signal",
                extra_opts=["SIGWHATEVER", "SIGANYTHING"],
            )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_execPebbleServiceAction_signal_raises_when_no_extra_opts_provided(
        self,
    ):
        service_monitor = self.make_service_monitor()
        service_name = factory.make_name("service")
        mock_pebble_request = self.mocker.patch.object(
            service_monitor, "_pebble_request"
        )
        mock_pebble_request.return_value = succeed({})
        with pytest.raises(
            ValueError,
            match=r"^Provide signal name in 'SIG\.\*' format in extra_opts$",
        ):
            yield service_monitor._execPebbleServiceAction(
                service_name, "signal"
            )
        mock_pebble_request.assert_not_called()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_execPebbleServiceAction_signal_raises_when_no_signals_found_in_extra_opts(
        self,
    ):
        service_monitor = self.make_service_monitor()
        service_name = factory.make_name("service")
        mock_pebble_request = self.mocker.patch.object(
            service_monitor, "_pebble_request"
        )
        mock_pebble_request.return_value = succeed({})
        with pytest.raises(
            ValueError,
            match=r"^Provide signal name in 'SIG\.\*' format in extra_opts$",
        ):
            yield service_monitor._execPebbleServiceAction(
                service_name, "signal", extra_opts=["AAAA", "BBBB"]
            )
        mock_pebble_request.assert_not_called()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_execPebbleServiceAction_waits_for_change_to_be_ready(self):
        service_monitor = self.make_service_monitor()
        service_name = factory.make_name("service")
        mock_pebble_request = self.mocker.patch.object(
            service_monitor, "_pebble_request"
        )

        def pebble_request_side_effect(method, endpoint, payload=None):
            if method == "GET" and endpoint == "/v1/changes/42":
                return succeed({"result": {"status": "Done", "ready": True}})
            if method == "POST" and endpoint == "/v1/services":
                return succeed({"type": "async", "change": 42})
            raise AssertionError(f"Unexpected request: {method} {endpoint}")

        mock_pebble_request.side_effect = pebble_request_side_effect
        yield service_monitor._execPebbleServiceAction(service_name, "start")
        assert len(mock_pebble_request.mock_calls) == 2

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_execPebbleServiceAction_raises_errors_predictably(self):
        service_monitor = self.make_service_monitor()
        service_name = factory.make_name("service")
        mock_pebble_request = self.mocker.patch.object(
            service_monitor, "_pebble_request"
        )
        error = "TEST"
        mock_pebble_request.side_effect = [fail(ValueError(error))]
        result = yield service_monitor._execPebbleServiceAction(
            service_name, "start"
        )
        assert (1, None, error) == result

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_execPebbleServiceAction_wait_on_change_raises_when_no_change_id_present(
        self,
    ):
        service_monitor = self.make_service_monitor()
        service_name = factory.make_name("service")
        action = "start"
        mock_pebble_request = self.mocker.patch.object(
            service_monitor, "_pebble_request"
        )
        mock_pebble_request.return_value = succeed({"type": "async"})
        code, output, error = yield service_monitor._execPebbleServiceAction(
            service_name, action
        )
        assert code == 1
        assert output is None
        assert error == "Expected to have change id in async request response"

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_execPebbleServiceAction_extract_service_status_raises_when_no_results(
        self,
    ):
        service_monitor = self.make_service_monitor()
        service_name = factory.make_name("service")
        action = "services"
        mock_pebble_request = self.mocker.patch.object(
            service_monitor, "_pebble_request"
        )
        mock_pebble_request.return_value = succeed({"result": []})
        code, output, error = yield service_monitor._execPebbleServiceAction(
            service_name, action
        )
        assert code == 1
        assert output is None
        assert (
            error
            == "Expected at least one result in services request response"
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_pebble_request_generates_valid_post_requests(self):
        mock_agent = MagicMock(Agent)
        service_monitor = self.make_service_monitor(pebble_agent=mock_agent)
        mock_response = MagicMock(Response)
        mock_response.code = 200
        mock_agent.request.return_value = succeed(mock_response)
        mock_read_body = self.mocker.patch.object(
            service_monitor_module, "readBody"
        )
        mock_read_body.return_value = succeed(b"{}")
        method = "POST"
        endpoint = "/endpoint"
        body = {"key": "value"}
        yield service_monitor._pebble_request(method, endpoint, body)
        mock_agent.request.assert_called()
        call_args = mock_agent.mock_calls[0].args
        assert call_args[0] == b"POST"
        assert call_args[1] == b"unix://localhost/endpoint"
        assert call_args[2] == Headers({"Content-Type": ["application/json"]})
        consumed = []

        @implementer(IConsumer)
        class Consumer:
            def registerProducer(self, producer, streaming):
                pass

            def unregisterProducer(self):
                pass

            def write(self, data):
                consumed.append(data)

        yield call_args[3].startProducing(Consumer())
        assert body == json.loads(b"".join(consumed).decode("utf-8"))

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_pebble_request_generates_valid_get_requests(self):
        mock_agent = MagicMock(Agent)
        service_monitor = self.make_service_monitor(pebble_agent=mock_agent)
        mock_response = MagicMock(Response)
        mock_response.code = 200
        mock_agent.request.return_value = succeed(mock_response)
        mock_read_body = self.mocker.patch.object(
            service_monitor_module, "readBody"
        )
        mock_read_body.return_value = succeed(b"{}")
        yield service_monitor._pebble_request("GET", "/")
        mock_agent.request.assert_called()
        call_args = mock_agent.mock_calls[0].args
        assert call_args[0] == b"GET"
        assert call_args[1] == b"unix://localhost/"
        assert call_args[2] is None
        assert call_args[3] is None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_pebble_request_raises_for_endpoint_not_starting_with_slash(self):
        mock_agent = MagicMock(Agent)
        service_monitor = self.make_service_monitor(pebble_agent=mock_agent)
        with pytest.raises(
            ValueError, match="Pebble endpoint does not start with '/'"
        ):
            yield service_monitor._pebble_request("GET", "endpoint")
        mock_agent.request.assert_not_called()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_pebble_request_raises_on_non_2xx_code(self):
        mock_agent = MagicMock(Agent)
        mock_response = MagicMock(Response)
        mock_response.code = 400
        mock_agent.request.return_value = succeed(mock_response)
        service_monitor = self.make_service_monitor(pebble_agent=mock_agent)
        with pytest.raises(
            ValueError, match="Unexpected pebble response code"
        ):
            yield service_monitor._pebble_request("GET", "/400")

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_pebble_request_deserializes_json(self):
        mock_agent = MagicMock(Agent)
        mock_response = MagicMock(Response)
        mock_response.code = 200
        mock_agent.request.return_value = succeed(mock_response)
        mock_read_body = self.mocker.patch.object(
            service_monitor_module, "readBody"
        )
        mock_read_body.return_value = succeed(b'{"what": "ever"}')
        service_monitor = self.make_service_monitor(pebble_agent=mock_agent)
        result = yield service_monitor._pebble_request("GET", "/json")
        assert result == {"what": "ever"}

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_pebble_request_raises_on_non_json_deserialisable_responses(self):
        mock_agent = MagicMock(Agent)
        mock_response = MagicMock(Response)
        mock_response.code = 200
        mock_agent.request.return_value = succeed(mock_response)
        mock_read_body = self.mocker.patch.object(
            service_monitor_module, "readBody"
        )
        mock_read_body.return_value = succeed(b"OK!")
        service_monitor = self.make_service_monitor(pebble_agent=mock_agent)
        with pytest.raises(
            JSONDecodeError,
            match=r"^Expecting value: line 1 column 1 \(char 0\)$",
        ):
            yield service_monitor._pebble_request("GET", "/")

    def test_service_monitor_creates_agent_if_not_provided(self):
        service_monitor = self.make_service_monitor()
        assert service_monitor._agent is not None

    def test_pebble_create_agent_uses_pebble_env_var(self):
        env = {"PEBBLE": "/var/run/pebble"}
        self.mocker.patch.object(os, "environ", env)
        service_monitor = self.make_service_monitor()
        agent = service_monitor._pebble_create_agent()
        assert isinstance(
            agent._endpointFactory,
            service_monitor_module.UnixClientEndpointFactory,
        )
        assert (
            os.path.join(env["PEBBLE"], ".pebble.socket")
            == agent._endpointFactory._socket_path
        )

    def test_pebble_create_agent_prioritises_pebble_socket_over_pebble(self):
        env = {
            "PEBBLE": "/var/run/pebble",
            "PEBBLE_SOCKET": "/any/other/path/to/pebble/.socket",
        }
        self.mocker.patch.object(os, "environ", env)
        service_monitor = self.make_service_monitor()
        agent = service_monitor._pebble_create_agent()
        assert isinstance(
            agent._endpointFactory,
            service_monitor_module.UnixClientEndpointFactory,
        )
        assert env["PEBBLE_SOCKET"] == agent._endpointFactory._socket_path

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_pebble_wait_on_change_monitors_changes(self):
        service_monitor = self.make_service_monitor()
        mock_pebble_request = self.mocker.patch.object(
            service_monitor, "_pebble_request"
        )
        change_id = 42
        request_count = 0

        def pebble_request_side_effect(method, endpoint, payload=None):
            nonlocal request_count
            request_count += 1
            if request_count == 1:
                return succeed({"result": {"status": "Doing", "ready": False}})
            return succeed({"result": {"status": "Done", "ready": True}})

        mock_pebble_request.side_effect = pebble_request_side_effect
        yield service_monitor._pebble_wait_on_change(change_id, backoff=0.001)
        assert request_count == 2

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_pebble_wait_on_change_handles_error_status(self):
        service_monitor = self.make_service_monitor()
        mock_pebble_request = self.mocker.patch.object(
            service_monitor, "_pebble_request"
        )
        change_id = 42
        error = "Test"
        mock_pebble_request.return_value = succeed(
            {"result": {"status": "Error", "ready": True, "err": error}}
        )
        with pytest.raises(
            ValueError,
            match=f"Pebble change {change_id} failed with an error: {error}",
        ):
            yield service_monitor._pebble_wait_on_change(change_id, backoff=0)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_pebble_wait_on_change_handles_hold_status(self):
        service_monitor = self.make_service_monitor()
        mock_pebble_request = self.mocker.patch.object(
            service_monitor, "_pebble_request"
        )
        change_id = 42
        mock_pebble_request.return_value = succeed(
            {"result": {"status": "Hold", "ready": True}}
        )
        with pytest.raises(
            ValueError, match=f"Pebble change {change_id} is on hold"
        ):
            yield service_monitor._pebble_wait_on_change(change_id, backoff=0)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_pebble_wait_on_change_handles_undone_status(self):
        service_monitor = self.make_service_monitor()
        mock_pebble_request = self.mocker.patch.object(
            service_monitor, "_pebble_request"
        )
        change_id = 42
        mock_pebble_request.return_value = succeed(
            {"result": {"status": "Undone", "ready": True}}
        )
        with pytest.raises(
            ValueError, match=f"Pebble change {change_id} is undone"
        ):
            yield service_monitor._pebble_wait_on_change(change_id, backoff=0)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_pebble_wait_on_change_handles_unknown_error_status(self):
        service_monitor = self.make_service_monitor()
        mock_pebble_request = self.mocker.patch.object(
            service_monitor, "_pebble_request"
        )
        change_id = 42
        error = "Test"
        status = "ImNotPebble"
        mock_pebble_request.return_value = succeed(
            {"result": {"status": status, "ready": True, "err": error}}
        )
        with pytest.raises(
            ValueError,
            match=(
                f"Pebble change {change_id} finished with unknown error "
                f"status `{status}`: {error}"
            ),
        ):
            yield service_monitor._pebble_wait_on_change(change_id, backoff=0)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_performServiceAction_holds_lock_perform_pebble_action(self):
        service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor()
        service_locks = service_monitor._serviceLocks
        service_lock = service_locks[service.name]
        service_lock = service_locks[service.name] = Mock(wraps=service_lock)
        mock_execPebbleServiceAction = self.mocker.patch.object(
            service_monitor, "_execPebbleServiceAction"
        )
        mock_execPebbleServiceAction.return_value = (0, "", "")
        action = "start"
        yield service_monitor._performServiceAction(service, action)
        service_lock.run.assert_called_once_with(
            service_monitor._execPebbleServiceAction,
            service.snap_service_name,
            action,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_performServiceAction_raises_ServiceActionError_if_fails(self):
        service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor()
        mock_execPebbleServiceAction = self.mocker.patch.object(
            service_monitor, "_execPebbleServiceAction"
        )
        mock_execPebbleServiceAction.return_value = (1, "", "")
        action = factory.make_name("action")
        with pytest.raises(
            ServiceActionError,
            match=f"^Service '{service.name}' failed to {action}: $",
        ):
            yield service_monitor._performServiceAction(service, action)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_performServiceAction_logs_error_if_action_fails(self):
        service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor()
        mock_execPebbleServiceAction = self.mocker.patch.object(
            service_monitor, "_execPebbleServiceAction"
        )
        error_output = factory.make_name("error")
        mock_execPebbleServiceAction.return_value = (1, "", error_output)
        action = factory.make_name("action")
        with pytest.raises(
            ServiceActionError,
            match=f"^Service '{service.name}' failed to {action}: {error_output}$",
        ):
            with FakeLogger("maas.service_monitor") as maaslog:
                yield service_monitor._performServiceAction(service, action)
        assert (
            f"Service '{service.name}' failed to {action}: {error_output}\n"
            == maaslog.output
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_loadServiceState_status_calls_pebble_socket(self):
        service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor([service])
        mock_execPebbleServiceAction = self.mocker.patch.object(
            service_monitor, "_execPebbleServiceAction"
        )
        mock_execPebbleServiceAction.side_effect = factory.make_exception()
        try:
            yield service_monitor._loadServiceState(service)
        except Exception:
            pass
        mock_execPebbleServiceAction.assert_called_once_with(
            service.snap_service_name, "services"
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_loadServiceState_service_name_doesnt_match(self):
        service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor()
        mock_execPebbleServiceAction = self.mocker.patch.object(
            service_monitor, "_execPebbleServiceAction"
        )
        mock_execPebbleServiceAction.return_value = (
            0,
            "any_service active",
            "",
        )
        with pytest.raises(
            ServiceParsingError,
            match=f"Pebble returned status for 'any_service' instead of '{service.snap_service_name}'",
        ):
            yield service_monitor._loadServiceState(service)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_loadServiceState_unknown_status(self):
        service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor()
        mock_execPebbleServiceAction = self.mocker.patch.object(
            service_monitor, "_execPebbleServiceAction"
        )
        mock_execPebbleServiceAction.return_value = (
            0,
            f"{service.snap_service_name} unknown_status_for_maas",
            "",
        )
        with pytest.raises(
            ServiceParsingError,
            match="Pebble returned status as 'unknown_status_for_maas'",
        ):
            yield service_monitor._loadServiceState(service)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_loadServiceState_active_returns_on(self):
        service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor([service])
        mock_execPebbleServiceAction = self.mocker.patch.object(
            service_monitor, "_execPebbleServiceAction"
        )
        mock_execPebbleServiceAction.return_value = (
            0,
            f"{service.snap_service_name} active",
            "",
        )
        active_state, process_state = yield service_monitor._loadServiceState(
            service
        )
        assert active_state == SERVICE_STATE.ON
        assert process_state == "running"

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_loadServiceState_inactive_returns_off(self):
        service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor([service])
        mock_execPebbleServiceAction = self.mocker.patch.object(
            service_monitor, "_execPebbleServiceAction"
        )
        mock_execPebbleServiceAction.return_value = (
            0,
            f"{service.snap_service_name} inactive",
            "",
        )
        active_state, process_state = yield service_monitor._loadServiceState(
            service
        )
        assert active_state == SERVICE_STATE.OFF
        assert process_state == "dead"

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_loadServiceState_backoff_returns_dead(self):
        service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor([service])
        mock_execPebbleServiceAction = self.mocker.patch.object(
            service_monitor, "_execPebbleServiceAction"
        )
        mock_execPebbleServiceAction.return_value = (
            0,
            f"{service.snap_service_name} backoff",
            "",
        )
        active_state, process_state = yield service_monitor._loadServiceState(
            service
        )
        assert active_state == SERVICE_STATE.DEAD
        assert process_state == "Result: exit-code"

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_loadServiceState_error_returns_dead(self):
        service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor([service])
        mock_execPebbleServiceAction = self.mocker.patch.object(
            service_monitor, "_execPebbleServiceAction"
        )
        mock_execPebbleServiceAction.return_value = (
            0,
            f"{service.snap_service_name} error",
            "",
        )
        active_state, process_state = yield service_monitor._loadServiceState(
            service
        )
        assert active_state == SERVICE_STATE.DEAD
        assert process_state == "Result: exit-code"

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_ensureService_logs_warning_in_mismatch_process_state(self):
        service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor([service])
        invalid_process_state = factory.make_name("invalid_state")
        mock_getServiceState = self.mocker.patch.object(
            service_monitor, "getServiceState"
        )
        mock_getServiceState.return_value = succeed(
            ServiceState(SERVICE_STATE.ON, invalid_process_state)
        )
        with FakeLogger(
            "maas.service_monitor", level=logging.WARNING
        ) as maaslog:
            yield service_monitor._ensureService(service)
        assert (
            f"Service '{service.service_name}' is on but not in the expected state of 'running', "
            in maaslog.output
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_ensureService_logs_debug_in_expected_states(self):
        state = SERVICE_STATE.ON
        service = make_fake_service(state)
        service_monitor = self.make_service_monitor([service])
        expected_process_state = service_monitor.PROCESS_STATE[state]
        mock_getServiceState = self.mocker.patch.object(
            service_monitor, "getServiceState"
        )
        mock_getServiceState.return_value = succeed(
            ServiceState(SERVICE_STATE.ON, expected_process_state)
        )
        log = self.mocker.patch.object(service_monitor_module, "log")
        yield service_monitor._ensureService(service)
        log.debug.assert_called_once_with(
            "Service '{name}' is {state} and '{process}'.",
            name=service.service_name,
            state=SERVICE_STATE.ON,
            process=expected_process_state,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_ensureService_allows_dead_for_off_service(self):
        service = make_fake_service(SERVICE_STATE.OFF)
        service_monitor = self.make_service_monitor([service])
        mock_getServiceState = self.mocker.patch.object(
            service_monitor, "getServiceState"
        )
        mock_getServiceState.return_value = succeed(
            ServiceState(SERVICE_STATE.DEAD, "Result: exit-code")
        )
        log = self.mocker.patch.object(service_monitor_module, "log")
        yield service_monitor._ensureService(service)
        log.debug.assert_called_once_with(
            "Service '{name}' is {state} and '{process}'.",
            name=service.service_name,
            state=SERVICE_STATE.DEAD,
            process="Result: exit-code",
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_ensureService_logs_mismatch_for_dead_process_state(self):
        service = make_fake_service(SERVICE_STATE.OFF)
        service_monitor = self.make_service_monitor([service])
        invalid_process_state = factory.make_name("invalid")
        mock_getServiceState = self.mocker.patch.object(
            service_monitor, "getServiceState"
        )
        mock_getServiceState.return_value = succeed(
            ServiceState(SERVICE_STATE.DEAD, invalid_process_state)
        )
        with FakeLogger(
            "maas.service_monitor", level=logging.WARNING
        ) as maaslog:
            yield service_monitor._ensureService(service)
        assert (
            f"Service '{service.service_name}' is dead but not in the expected state of 'Result: exit-code', "
            in maaslog.output
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_ensureService_performs_start_for_off_service(self):
        service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor([service])
        mock_getServiceState = self.mocker.patch.object(
            service_monitor, "getServiceState"
        )
        mock_getServiceState.side_effect = [
            succeed(ServiceState(SERVICE_STATE.OFF, "waiting")),
            succeed(ServiceState(SERVICE_STATE.ON, "running")),
        ]
        mock_performServiceAction = self.mocker.patch.object(
            service_monitor, "_performServiceAction"
        )
        mock_performServiceAction.return_value = succeed(None)
        with FakeLogger("maas.service_monitor", level=logging.INFO) as maaslog:
            yield service_monitor._ensureService(service)
        assert (
            f"Service '{service.service_name}' is not on, it will be started.\n"
            f"Service '{service.service_name}' has been started and is 'running'.\n"
        ) == maaslog.output

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_ensureService_performs_stop_for_on_service(self):
        service = make_fake_service(SERVICE_STATE.OFF)
        service_monitor = self.make_service_monitor([service])
        mock_getServiceState = self.mocker.patch.object(
            service_monitor, "getServiceState"
        )
        mock_getServiceState.side_effect = [
            succeed(ServiceState(SERVICE_STATE.ON, "running")),
            succeed(ServiceState(SERVICE_STATE.OFF, "waiting")),
        ]
        mock_performServiceAction = self.mocker.patch.object(
            service_monitor, "_performServiceAction"
        )
        mock_performServiceAction.return_value = succeed(None)
        with FakeLogger("maas.service_monitor", level=logging.INFO) as maaslog:
            yield service_monitor._ensureService(service)
        assert (
            f"Service '{service.service_name}' is not off, it will be stopped.\n"
            f"Service '{service.service_name}' has been stopped and is 'waiting'.\n"
        ) == maaslog.output

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_ensureService_performs_raises_ServiceActionError(self):
        service = make_fake_service(SERVICE_STATE.ON)
        service_monitor = self.make_service_monitor([service])
        mock_getServiceState = self.mocker.patch.object(
            service_monitor, "getServiceState"
        )
        mock_getServiceState.side_effect = [
            succeed(ServiceState(SERVICE_STATE.OFF, "waiting")),
            succeed(ServiceState(SERVICE_STATE.OFF, "waiting")),
        ]
        mock_performServiceAction = self.mocker.patch.object(
            service_monitor, "_performServiceAction"
        )
        mock_performServiceAction.return_value = succeed(None)
        with pytest.raises(
            ServiceActionError,
            match=rf"^Service '{service.service_name}' failed to start\.",
        ):
            with FakeLogger(
                "maas.service_monitor", level=logging.INFO
            ) as maaslog:
                yield service_monitor._ensureService(service)
        assert (
            f"Service '{service.service_name}' is not on, it will be started."
            in maaslog.output
        )
        assert (
            f"Service '{service.service_name}' failed to start. Its current state is 'off' and 'waiting'."
            in maaslog.output
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_ensureService_does_nothing_when_any_state_expected(self):
        service = make_fake_service(SERVICE_STATE.ANY)
        service_monitor = self.make_service_monitor([service])
        self.mocker.patch.object(
            service_monitor, "getServiceState", autospec=True
        )
        self.mocker.patch.object(
            service_monitor, "_performServiceAction", autospec=True
        )
        assert (yield service_monitor._ensureService(service)) == ServiceState(
            SERVICE_STATE.UNKNOWN
        )
        service_monitor.getServiceState.assert_not_called()
        service_monitor._performServiceAction.assert_not_called()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_ensureService_only_gets_state_when_observe_state_expected(self):
        service = make_fake_service(SERVICE_STATE.OBSERVE)
        service_monitor = self.make_service_monitor([service])
        getState = self.mocker.patch.object(
            service_monitor, "getServiceState", autospec=True
        )
        getState.return_value = succeed(ServiceState(SERVICE_STATE.ON))
        self.mocker.patch.object(
            service_monitor, "_performServiceAction", autospec=True
        )
        assert (yield service_monitor._ensureService(service)) == ServiceState(
            SERVICE_STATE.ON
        )
        service_monitor.getServiceState.assert_called()
        service_monitor._performServiceAction.assert_not_called()


class TestToggleableService:
    def make_toggleable_service(self):
        class FakeToggleableService(ToggleableService):
            name = factory.make_name("name")
            service_name = factory.make_name("service")
            snap_service_name = factory.make_name("service")

        return FakeToggleableService()

    def test_expected_state_starts_off(self):
        service = self.make_toggleable_service()
        assert service.expected_state == SERVICE_STATE.OFF

    def test_getExpectedState_returns_from_expected_state_and_reason(self):
        service = self.make_toggleable_service()
        service.expected_state = sentinel.state
        service.expected_state_reason = sentinel.reason
        assert service.getExpectedState() == (sentinel.state, sentinel.reason)

    def test_is_on_returns_True_when_expected_state_on(self):
        service = self.make_toggleable_service()
        service.expected_state = SERVICE_STATE.ON
        assert service.is_on(), (
            "Did not return true when expected_state was on."
        )

    def test_is_on_returns_False_when_expected_state_off(self):
        service = self.make_toggleable_service()
        service.expected_state = SERVICE_STATE.OFF
        assert not service.is_on(), (
            "Did not return false when expected_state was off."
        )

    def test_on_sets_expected_state_to_on(self):
        service = self.make_toggleable_service()
        service.expected_state = SERVICE_STATE.OFF
        service.on(sentinel.reason)
        assert service.expected_state == SERVICE_STATE.ON
        assert service.expected_state_reason == sentinel.reason

    def test_off_sets_expected_state_to_off(self):
        service = self.make_toggleable_service()
        service.expected_state = SERVICE_STATE.ON
        service.off(sentinel.reason)
        assert service.expected_state == SERVICE_STATE.OFF
        assert service.expected_state_reason == sentinel.reason
