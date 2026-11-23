# Copyright 2020-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for register command code."""

from argparse import ArgumentParser, Namespace
from collections import defaultdict
import json

import pytest
from twisted.internet import reactor
from twisted.internet.defer import ensureDeferred, inlineCallbacks

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from provisioningserver import power_driver_command
from provisioningserver.drivers.power import PowerDriver
from provisioningserver.drivers.power.hmcz import HMCZPowerDriver
from provisioningserver.logger import DEFAULT_LOG_VERBOSITY, LoggingMode


class FakeDriver(PowerDriver):
    # These are required by the base class, but unused in this test.
    chassis = False
    can_probe = False
    can_set_boot_order = False
    description = None
    detect_missing_packages = None
    ip_extractor = None
    name = None
    settings = []
    _state = "off"

    calls = defaultdict(list)

    def __init__(self, clock=reactor):
        super().__init__(clock)
        self.calls = defaultdict(list)

    def power_on(self, *args, **kwargs):
        self._state = "on"
        self.calls["power_on"].append(True)

    def power_off(self, *args, **kwargs):
        self._state = "off"
        self.calls["power_off"].append(True)

    def power_query(self, *args, **kwargs):
        self.calls["power_query"].append(True)
        return self._state

    def power_cycle(self, *args, **kwargs):
        self._state = "on"
        self.calls["power_cycle"].append(True)

    def power_reset(self, *args, **kwargs):
        self._state = "on"
        self.calls["power_reset"].append(True)


class FakeHMCZDriver(FakeDriver):
    can_set_boot_order = True
    settings = HMCZPowerDriver.settings

    async def set_boot_order(self, system_id, context, order):
        self.calls["set_boot_order"].append(
            {
                "system_id": system_id,
                "context": context,
                "order": order,
            }
        )


@pytest.mark.rack_reactor_guard
class TestPowerDriverCommand:
    @wait_for(timeout=get_testing_timeout())
    @inlineCallbacks
    def test_run_set_boot_order_hmcz_parses_json_order(self):
        order = [
            {"mac_address": "00:11:22:33:44:55"},
            {"id": 1, "name": "sda"},
        ]
        args = power_driver_command._parse_args(
            [
                "set-boot-order",
                "hmcz",
                "--power-address",
                "hmc.example",
                "--power-user",
                "maas",
                "--power-pass",
                "secret",
                "--power-partition-name",
                "partition-1",
                "--power-verify-ssl",
                "y",
                "--order",
                json.dumps(order),
            ]
        )

        driver = FakeHMCZDriver()
        status = yield ensureDeferred(
            power_driver_command._run(reactor, args, {"hmcz": driver})
        )

        assert status == "off"
        assert len(driver.calls["set_boot_order"]) == 1
        set_boot_order_call = driver.calls["set_boot_order"][0]
        assert set_boot_order_call["system_id"] is None
        assert set_boot_order_call["order"] == order
        assert set_boot_order_call["context"] == {
            "power_address": "hmc.example",
            "power_user": "maas",
            "power_pass": "secret",
            "power_partition_name": "partition-1",
            "power_verify_ssl": "y",
        }

    def test_run_configures_logging(self, mocker):
        configure = mocker.patch.object(
            power_driver_command, "configure_standard_logging"
        )
        mocker.patch.object(power_driver_command, "react")
        mocker.patch.object(power_driver_command, "_parse_args")

        power_driver_command.run(["status", "virsh"])

        configure.assert_called_once_with(
            DEFAULT_LOG_VERBOSITY, LoggingMode.COMMAND
        )

    def test_create_subparser(self):
        parser = ArgumentParser()
        driver_settings = [
            {
                "name": "password",
                "label": "Password",
                "required": True,
                "choices": [],
            },
            {
                "name": "version",
                "label": "Driver Version",
                "required": True,
                "field_type": "choice",
                "choices": [("1", "one"), ("2", "two")],
            },
            {
                "name": "multi_flag",
                "label": "Multiple flags",
                "required": True,
                "field_type": "multiple_choice",
                "choices": [("1", "one"), ("2", "two")],
            },
        ]

        power_driver_command._create_subparser(driver_settings, parser)

        args = parser.parse_args(
            ["--password", "pass", "--version", "1", "--multi-flag", "1"]
        )

        assert args.password == "pass"
        assert args.version == "1"
        assert args.multi_flag == ["1"]

    def test_parse_args_virsh(self):
        args = power_driver_command._parse_args(
            [
                "on",
                "virsh",
                "--power-address",
                "qemu+ssh://ubuntu@$KVM_HOST/system",
                "--power-id",
                "power_id",
            ]
        )

        assert args.command == "on"
        assert args.driver == "virsh"
        assert args.power_address == "qemu+ssh://ubuntu@$KVM_HOST/system"
        assert args.power_id == "power_id"

    def test_parse_args_ipmi(self):
        """Test parsing args with ipmi, as it includes settings with defined choices"""

        args = power_driver_command._parse_args(
            [
                "on",
                "ipmi",
                "--power-address",
                "power_address",
                "--power-driver",
                "LAN_2_0",
                "--workaround-flags",
                "opensesspriv",
                "--workaround-flags",
                "authcap",
                "--power-off-mode",
                "hard",
            ]
        )

        assert args.command == "on"
        assert args.driver == "ipmi"
        assert args.power_address == "power_address"
        assert args.power_driver == "LAN_2_0"
        assert args.workaround_flags == ["opensesspriv", "authcap"]

    def test_parse_args_dpu(self):
        """
        Ensure the `--is-dpu` flag is set correctly when given.
        """

        args = power_driver_command._parse_args(
            [
                "reset",
                "--is-dpu",
                "redfish",
                "--power-address",
                "addr",
                "--power-user",
                "maas",
                "--power-pass",
                "maas",
            ]
        )

        assert args.command == "reset"
        assert args.is_dpu is True
        assert args.driver == "redfish"
        assert args.power_address == "addr"
        assert args.power_user == "maas"
        assert args.power_pass == "maas"

    @wait_for(timeout=get_testing_timeout())
    @inlineCallbacks
    def test_dpu_calls_reset_on_power_reset(self):
        args = Namespace()
        args.command = "reset"
        args.driver = "fake"
        args.is_dpu = True

        driver = FakeDriver()
        registry = {"fake": driver}

        status = yield ensureDeferred(
            power_driver_command._run(reactor, args, registry)
        )

        assert status == "on"
        assert len(driver.calls["power_reset"]) == 1

    @wait_for(timeout=get_testing_timeout())
    @inlineCallbacks
    def test_dpu_calls_reset_on_power_on(self):
        args = Namespace()
        args.command = "on"
        args.driver = "fake"
        args.is_dpu = True

        driver = FakeDriver()
        registry = {"fake": driver}

        status = yield ensureDeferred(
            power_driver_command._run(reactor, args, registry)
        )

        assert status == "on"
        assert len(driver.calls["power_on"]) == 0
        assert len(driver.calls["power_reset"]) == 1

    @wait_for(timeout=get_testing_timeout())
    @inlineCallbacks
    def test_dpu_calls_reset_on_power_cycle(self):
        args = Namespace()
        args.command = "cycle"
        args.driver = "fake"
        args.is_dpu = True

        driver = FakeDriver()
        registry = {"fake": driver}

        status = yield ensureDeferred(
            power_driver_command._run(reactor, args, registry)
        )

        assert status == "on"
        assert len(driver.calls["power_cycle"]) == 0
        assert len(driver.calls["power_reset"]) == 1

    @wait_for(timeout=get_testing_timeout())
    @inlineCallbacks
    def test_dpu_invalid_command_raises_error(self):
        args = Namespace()
        args.command = "off"
        args.driver = "fake"
        args.is_dpu = True

        driver = FakeDriver()
        registry = {"fake": driver}

        with pytest.raises(
            power_driver_command.InvalidDPUCommandError,
            match=f"Invalid power command to send to DPU: {args.command}",
        ):
            _ = yield ensureDeferred(
                power_driver_command._run(reactor, args, registry)
            )

    @wait_for(timeout=get_testing_timeout())
    @inlineCallbacks
    def test_run(self):
        args = Namespace()
        args.command = "on"
        args.driver = "fake"
        args.is_dpu = False

        driver = FakeDriver()
        registry = {"fake": driver}

        status = yield ensureDeferred(
            power_driver_command._run(reactor, args, registry)
        )
        assert status == "on"
