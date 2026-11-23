# Copyright 2014-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `provisioningserver.drivers.power`."""

import random
from unittest.mock import call, sentinel

from jsonschema import validate
import pytest
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks, succeed

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.factory import factory
from provisioningserver.drivers import make_setting_field, power
from provisioningserver.drivers.power import (
    get_error_message,
    JSON_POWER_DRIVER_SCHEMA,
    PowerActionError,
    PowerAuthError,
    PowerConnError,
    PowerDriver,
    PowerDriverBase,
    PowerError,
    PowerFatalError,
    PowerSettingError,
    PowerToolError,
)
from provisioningserver.utils.twisted import asynchronous

TIMEOUT = get_testing_timeout()


class FakePowerDriverBase(PowerDriverBase):
    name = ""
    chassis = False
    can_probe = False
    can_set_boot_order = False
    description = ""
    settings = []
    ip_extractor = None
    queryable = True

    def __init__(self, name, description, settings, chassis=False):
        self.name = name
        self.description = description
        self.settings = settings
        self.chassis = chassis
        super().__init__()

    def on(self, system_id, context):
        raise NotImplementedError

    def off(self, system_id, context):
        raise NotImplementedError

    def cycle(self, system_id, context):
        raise NotImplementedError

    def query(self, system_id, context):
        raise NotImplementedError

    def reset(self, system_id, context):
        raise NotImplementedError

    def detect_missing_packages(self):
        return []


def make_power_driver_base(
    name=None, description=None, settings=None, chassis=False
):
    if name is None:
        name = factory.make_name("diskless")
    if description is None:
        description = factory.make_name("description")
    if settings is None:
        settings = []
    return FakePowerDriverBase(name, description, settings, chassis)


class TestFakePowerDriverBase:
    def test_attributes(self):
        fake_name = factory.make_name("name")
        fake_description = factory.make_name("description")
        fake_setting = factory.make_name("setting")
        fake_settings = [
            make_setting_field(fake_setting, fake_setting.title())
        ]
        fake_driver = FakePowerDriverBase(
            fake_name, fake_description, fake_settings
        )
        assert fake_driver.name == fake_name
        assert fake_driver.description == fake_description
        assert fake_driver.settings == fake_settings

    def test_make_power_driver_base(self):
        fake_name = factory.make_name("name")
        fake_description = factory.make_name("description")
        fake_setting = factory.make_name("setting")
        fake_settings = [
            make_setting_field(fake_setting, fake_setting.title())
        ]
        fake_driver = make_power_driver_base(
            name=fake_name,
            description=fake_description,
            settings=fake_settings,
        )
        assert fake_driver.name == fake_name
        assert fake_driver.description == fake_description
        assert fake_driver.settings == fake_settings

    def test_make_power_driver_base_makes_name_and_description(self):
        fake_driver = make_power_driver_base()
        assert fake_driver.name != ""
        assert fake_driver.description != ""

    def test_on_raises_not_implemented(self):
        fake_driver = make_power_driver_base()
        with pytest.raises(NotImplementedError):
            fake_driver.on(sentinel.system_id, sentinel.context)

    def test_off_raises_not_implemented(self):
        fake_driver = make_power_driver_base()
        with pytest.raises(NotImplementedError):
            fake_driver.off(sentinel.system_id, sentinel.context)

    def test_cycle_raises_not_implemented(self):
        fake_driver = make_power_driver_base()
        with pytest.raises(NotImplementedError):
            fake_driver.cycle(sentinel.system_id, sentinel.context)

    def test_query_raises_not_implemented(self):
        fake_driver = make_power_driver_base()
        with pytest.raises(NotImplementedError):
            fake_driver.query(sentinel.system_id, sentinel.context)

    def test_set_boot_order_raises_not_implemented(self):
        fake_driver = make_power_driver_base()
        with pytest.raises(NotImplementedError):
            fake_driver.set_boot_order(
                sentinel.system_id, sentinel.context, sentinel.order
            )


class TestPowerDriverBase:
    def test_get_schema(self):
        fake_name = factory.make_name("name")
        fake_description = factory.make_name("description")
        fake_setting = factory.make_name("setting")
        fake_chassis = factory.pick_bool()
        fake_settings = [
            make_setting_field(fake_setting, fake_setting.title())
        ]
        fake_driver = make_power_driver_base(
            name=fake_name,
            description=fake_description,
            chassis=fake_chassis,
            settings=fake_settings,
        )
        assert fake_driver.get_schema() == {
            "driver_type": "power",
            "name": fake_name,
            "description": fake_description,
            "chassis": fake_chassis,
            "can_probe": False,
            "fields": fake_settings,
            "queryable": fake_driver.queryable,
            "missing_packages": fake_driver.detect_missing_packages(),
        }

    def test_get_schema_returns_valid_schema(self):
        fake_driver = make_power_driver_base()
        # doesn't raise ValidationError
        validate(fake_driver.get_schema(), JSON_POWER_DRIVER_SCHEMA)


@pytest.mark.parametrize(
    "exception,message",
    [
        pytest.param(
            PowerAuthError("auth"),
            "Could not authenticate to node's BMC: auth",
            id="auth",
        ),
        pytest.param(
            PowerConnError("conn"),
            "Could not contact node's BMC: conn",
            id="conn",
        ),
        pytest.param(
            PowerSettingError("setting"),
            "Missing or invalid power setting: setting",
            id="setting",
        ),
        pytest.param(
            PowerToolError("tool"),
            "Missing power tool: tool",
            id="tool",
        ),
        pytest.param(
            PowerActionError("action"),
            "Failed to complete power action: action",
            id="action",
        ),
        pytest.param(
            PowerError("unknown error"),
            "Failed talking to node's BMC: unknown error",
            id="unknown",
        ),
    ],
)
@pytest.mark.rack_reactor_guard
class TestGetErrorMessage:
    def test_return_msg(self, exception, message):
        assert message == get_error_message(exception)


class FakePowerDriver(PowerDriver):
    name = ""
    chassis = False
    can_probe = False
    can_set_boot_order = False
    description = ""
    settings = []
    ip_extractor = None
    queryable = True

    def __init__(
        self, name, description, settings, wait_time=None, clock=reactor
    ):
        self.name = name
        self.description = description
        self.settings = settings
        if wait_time is not None:
            self.wait_time = wait_time
        super().__init__(clock)

    def detect_missing_packages(self):
        return []

    def power_on(self, system_id, context):
        raise NotImplementedError

    def power_off(self, system_id, context):
        raise NotImplementedError

    def power_query(self, system_id, context):
        raise NotImplementedError

    def power_reset(self, system_id, context):
        raise NotImplementedError


def make_power_driver(
    name=None, description=None, settings=None, wait_time=None, clock=reactor
):
    if name is None:
        name = factory.make_name("diskless")
    if description is None:
        description = factory.make_name("description")
    if settings is None:
        settings = []
    return FakePowerDriver(
        name, description, settings, wait_time=wait_time, clock=clock
    )


class AsyncFakePowerDriver(FakePowerDriver):
    def __init__(
        self,
        name,
        description,
        settings,
        wait_time=None,
        clock=reactor,
        query_result=None,
    ):
        super().__init__(
            name, description, settings, wait_time=None, clock=reactor
        )
        self.power_query_result = query_result
        self.power_on_called = 0
        self.power_off_called = 0
        self.power_reset_called = 0

    @asynchronous
    def power_on(self, system_id, context):
        self.power_on_called += 1
        return succeed(None)

    @asynchronous
    def power_off(self, system_id, context):
        self.power_off_called += 1
        return succeed(None)

    @asynchronous
    def power_query(self, system_id, context):
        return succeed(self.power_query_result)

    @asynchronous
    def power_reset(self, system_id, context):
        self.power_reset_called += 1
        return succeed(None)


def make_async_power_driver(
    name=None,
    description=None,
    settings=None,
    wait_time=None,
    clock=reactor,
    query_result=None,
):
    if name is None:
        name = factory.make_name("diskless")
    if description is None:
        description = factory.make_name("description")
    if settings is None:
        settings = []
    return AsyncFakePowerDriver(
        name,
        description,
        settings,
        wait_time=wait_time,
        clock=clock,
        query_result=query_result,
    )


@pytest.mark.parametrize(
    "action,action_func,bad_state",
    [
        pytest.param("on", "power_on", "off", id="on"),
        pytest.param("off", "power_off", "on", id="off"),
    ],
)
@pytest.mark.rack_reactor_guard
class TestPowerDriverPowerAction:
    @pytest.fixture(autouse=True)
    def _setup_mocker(self, mocker):
        self.mocker = mocker

    def make_error_message(self):
        error = factory.make_name("msg")
        self.mocker.patch.object(
            power, "get_error_message"
        ).return_value = error
        return error

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_success(self, action, action_func, bad_state):
        system_id = factory.make_name("system_id")
        context = {"context": factory.make_name("context")}
        driver = make_power_driver(wait_time=[0])
        self.mocker.patch.object(driver, action_func)
        self.mocker.patch.object(driver, "power_query").return_value = action
        method = getattr(driver, action)
        result = yield method(system_id, context)
        assert result is None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_success_async(self, action, action_func, bad_state):
        system_id = factory.make_name("system_id")
        context = {"context": factory.make_name("context")}
        mock_defer_to_thread = self.mocker.patch.object(power, "deferToThread")
        driver = make_async_power_driver(wait_time=[0], query_result=action)
        method = getattr(driver, action)
        result = yield method(system_id, context)
        assert result is None
        call_count = getattr(driver, "%s_called" % action_func)
        assert call_count == 1
        mock_defer_to_thread.assert_not_called()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_handles_fatal_error_on_first_call(
        self, action, action_func, bad_state
    ):
        system_id = factory.make_name("system_id")
        context = {"context": factory.make_name("context")}
        driver = make_power_driver(wait_time=[0, 0])
        mock_action = self.mocker.patch.object(driver, action_func)
        mock_action.side_effect = [PowerFatalError(), None]
        mock_query = self.mocker.patch.object(driver, "power_query")
        mock_query.return_value = action
        method = getattr(driver, action)
        with pytest.raises(PowerFatalError, match="^$"):
            yield method(system_id, context)
        mock_query.assert_not_called()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_handles_non_fatal_error_on_first_call(
        self, action, action_func, bad_state
    ):
        system_id = factory.make_name("system_id")
        context = {"context": factory.make_name("context")}
        driver = make_power_driver(wait_time=[0, 0])
        mock_action = self.mocker.patch.object(driver, action_func)
        mock_action.side_effect = [PowerError(), None]
        mock_query = self.mocker.patch.object(driver, "power_query")
        mock_query.return_value = action
        method = getattr(driver, action)
        result = yield method(system_id, context)
        mock_query.assert_called_once_with(system_id, context)
        assert result is None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_handles_non_fatal_error_and_holds_error(
        self, action, action_func, bad_state
    ):
        system_id = factory.make_name("system_id")
        context = {"context": factory.make_name("context")}
        driver = make_power_driver(wait_time=[0])
        error_msg = factory.make_name("error")
        self.mocker.patch.object(driver, action_func)
        mock_query = self.mocker.patch.object(driver, "power_query")
        mock_query.side_effect = PowerError(error_msg)
        method = getattr(driver, action)
        with pytest.raises(PowerError, match=f"^{error_msg}$"):
            yield method(system_id, context)
        mock_query.assert_called_once_with(system_id, context)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_handles_non_fatal_error(self, action, action_func, bad_state):
        system_id = factory.make_name("system_id")
        context = {"context": factory.make_name("context")}
        driver = make_power_driver(wait_time=[0])
        mock_action = self.mocker.patch.object(driver, action_func)
        mock_action.side_effect = PowerError("foo")
        method = getattr(driver, action)
        with pytest.raises(PowerError, match="foo"):
            yield method(system_id, context)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_handles_fails_to_complete_power_action_in_time(
        self, action, action_func, bad_state
    ):
        system_id = factory.make_name("system_id")
        context = {"context": factory.make_name("context")}
        driver = make_power_driver(wait_time=[0])
        self.mocker.patch.object(driver, action_func)
        mock_query = self.mocker.patch.object(driver, "power_query")
        mock_query.return_value = bad_state
        method = getattr(driver, action)
        with pytest.raises(
            PowerError,
            match=f"Failed to power {system_id}. BMC never transitioned from {bad_state} to {action}",
        ):
            yield method(system_id, context)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_doesnt_power_query_if_unqueryable(
        self, action, action_func, bad_state
    ):
        system_id = factory.make_name("system_id")
        context = {"context": factory.make_name("context")}
        driver = make_power_driver(wait_time=[0])
        driver.queryable = False
        self.mocker.patch.object(driver, action_func)
        mock_query = self.mocker.patch.object(driver, "power_query")
        method = getattr(driver, action)
        yield method(system_id, context)
        mock_query.assert_not_called()


@pytest.mark.rack_reactor_guard
class TestPowerDriverCycle:
    @pytest.fixture(autouse=True)
    def _setup_mocker(self, mocker):
        self.mocker = mocker

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_cycles_power_when_node_is_powered_on(self):
        system_id = factory.make_name("system_id")
        context = {"context": factory.make_name("context")}
        driver = make_power_driver()
        mock_perform_power = self.mocker.patch.object(driver, "perform_power")
        self.mocker.patch.object(driver, "power_query").return_value = "on"
        yield driver.cycle(system_id, context)
        mock_perform_power.assert_has_calls(
            [
                call(driver.power_off, "off", system_id, context),
                call(driver.power_on, "on", system_id, context),
            ]
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_cycles_power_when_node_is_powered_off(self):
        system_id = factory.make_name("system_id")
        context = {"context": factory.make_name("context")}
        driver = make_power_driver()
        mock_perform_power = self.mocker.patch.object(driver, "perform_power")
        self.mocker.patch.object(driver, "power_query").return_value = "off"
        yield driver.cycle(system_id, context)
        mock_perform_power.assert_called_once_with(
            driver.power_on, "on", system_id, context
        )


@pytest.mark.rack_reactor_guard
class TestPowerDriverQuery:
    @pytest.fixture(autouse=True)
    def _setup_mocker(self, mocker):
        self.mocker = mocker
        mocker.patch.object(power, "pause")

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_returns_state(self):
        system_id = factory.make_name("system_id")
        context = {"context": factory.make_name("context")}
        driver = make_power_driver()
        state = factory.make_name("state")
        self.mocker.patch.object(driver, "power_query").return_value = state
        output = yield driver.query(system_id, context)
        assert output == state

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_retries_on_failure_then_returns_state(self):
        driver = make_power_driver()
        self.mocker.patch.object(driver, "power_query").side_effect = [
            PowerError("one"),
            PowerError("two"),
            sentinel.state,
        ]
        output = yield driver.query(sentinel.system_id, sentinel.context)
        assert output == sentinel.state

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_raises_last_exception_after_all_retries_fail(self):
        wait_time = [random.randrange(1, 10) for _ in range(3)]
        driver = make_power_driver(wait_time=wait_time)
        exception_types = list(
            factory.make_exception_type((PowerError,)) for _ in wait_time
        )
        self.mocker.patch.object(
            driver, "power_query"
        ).side_effect = exception_types
        with pytest.raises(exception_types[-1], match="^$"):
            yield driver.query(sentinel.system_id, sentinel.context)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_pauses_between_retries(self):
        wait_time = [random.randrange(1, 10) for _ in range(3)]
        driver = make_power_driver(wait_time=wait_time)
        self.mocker.patch.object(
            driver, "power_query"
        ).side_effect = PowerError
        with pytest.raises(PowerError, match="^$"):
            yield driver.query(sentinel.system_id, sentinel.context)
        power.pause.assert_has_calls(
            [call(wait, reactor) for wait in wait_time]
        )
