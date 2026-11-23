# Copyright 2015-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `provisioningserver.drivers.power.raritan`."""

import pytest

from maastesting.factory import factory
from provisioningserver.drivers.power import PowerActionError
from provisioningserver.drivers.power import raritan as raritan_module
from provisioningserver.utils.shell import ProcessResult

COMMON_ARGS = "-c private -v2c {} .1.3.6.1.4.1.13742.6.4.1.2.1.2.1.{}"
COMMON_OUTPUT = "iso.1.3.6.1.4.1.13742.6.4.1.2.1.2.1.%s = INTEGER: 1\n"


class TestRaritanPowerDriver:
    def make_context(self):
        return {
            "power_address": factory.make_name("power_address"),
            "node_outlet": factory.make_name("node_outlet"),
            "power_on_delay": "5",
        }

    def test_missing_packages(self, mocker):
        mock = mocker.patch(
            "provisioningserver.utils.shell.has_command_available"
        )
        mock.return_value = False
        driver = raritan_module.RaritanPowerDriver()
        missing = driver.detect_missing_packages()
        assert ["snmp"] == missing

    def test_no_missing_packages(self, mocker):
        mock = mocker.patch(
            "provisioningserver.utils.shell.has_command_available"
        )
        mock.return_value = True
        driver = raritan_module.RaritanPowerDriver()
        missing = driver.detect_missing_packages()
        assert [] == missing

    def patch_run_command(self, mocker, stdout="", stderr="", returncode=0):
        mock_run_command = mocker.patch.object(
            raritan_module.shell, "run_command"
        )
        mock_run_command.return_value = ProcessResult(
            stdout=stdout, stderr=stderr, returncode=returncode
        )
        return mock_run_command

    def test_run_process_calls_command_and_returns_output(self, mocker):
        driver = raritan_module.RaritanPowerDriver()
        context = self.make_context()
        command = ["snmpget"] + COMMON_ARGS.format(
            context["power_address"], context["node_outlet"]
        ).split()
        mock_run_command = self.patch_run_command(
            mocker,
            stdout=COMMON_OUTPUT % context["node_outlet"],
            stderr="error_output",
        )
        output = driver.run_process(*command)
        mock_run_command.assert_called_once_with(*command)
        assert output == raritan_module.RaritanState.ON

    def test_run_process_crashes_on_external_process_error(self, mocker):
        driver = raritan_module.RaritanPowerDriver()
        self.patch_run_command(mocker, returncode=1)
        with pytest.raises(PowerActionError):
            driver.run_process(factory.make_name("command"))

    def test_run_process_crashes_on_no_power_state_match_found(self, mocker):
        driver = raritan_module.RaritanPowerDriver()
        self.patch_run_command(mocker, stdout="Error")
        with pytest.raises(PowerActionError):
            driver.run_process(factory.make_name("command"))

    def test_power_on_calls_run_process(self, mocker):
        driver = raritan_module.RaritanPowerDriver()
        system_id = factory.make_name("system_id")
        context = self.make_context()
        mock_power_query = mocker.patch.object(driver, "power_query")
        mock_power_query.return_value = "on"
        mocker.patch.object(driver, "power_off")
        mock_sleep = mocker.patch.object(raritan_module, "sleep")
        mock_run_process = mocker.patch.object(driver, "run_process")
        driver.power_on(system_id, context)

        mock_power_query.assert_called_once_with(system_id, context)
        mock_sleep.assert_called_once_with(float(context["power_on_delay"]))
        command = (
            ["snmpset"]
            + COMMON_ARGS.format(
                context["power_address"], context["node_outlet"]
            ).split()
            + ["i", "1"]
        )
        mock_run_process.assert_called_once_with(*command)

    def test_power_off_calls_run_process(self, mocker):
        driver = raritan_module.RaritanPowerDriver()
        system_id = factory.make_name("system_id")
        context = self.make_context()
        mock_run_process = mocker.patch.object(driver, "run_process")
        driver.power_off(system_id, context)
        command = (
            ["snmpset"]
            + COMMON_ARGS.format(
                context["power_address"], context["node_outlet"]
            ).split()
            + ["i", "0"]
        )
        mock_run_process.assert_called_once_with(*command)

    def test_power_query_returns_power_state_on(self, mocker):
        driver = raritan_module.RaritanPowerDriver()
        system_id = factory.make_name("system_id")
        context = self.make_context()
        mock_run_process = mocker.patch.object(driver, "run_process")
        mock_run_process.return_value = raritan_module.RaritanState.ON
        result = driver.power_query(system_id, context)
        command = ["snmpget"] + COMMON_ARGS.format(
            context["power_address"], context["node_outlet"]
        ).split()
        mock_run_process.assert_called_once_with(*command)
        assert result == "on"

    def test_power_query_returns_power_state_off(self, mocker):
        driver = raritan_module.RaritanPowerDriver()
        system_id = factory.make_name("system_id")
        context = self.make_context()
        mock_run_process = mocker.patch.object(driver, "run_process")
        mock_run_process.return_value = raritan_module.RaritanState.OFF
        result = driver.power_query(system_id, context)
        command = ["snmpget"] + COMMON_ARGS.format(
            context["power_address"], context["node_outlet"]
        ).split()
        mock_run_process.assert_called_once_with(*command)
        assert result == "off"

    def test_power_query_crashes_for_uknown_power_state(self, mocker):
        driver = raritan_module.RaritanPowerDriver()
        system_id = factory.make_name("system_id")
        context = self.make_context()
        mock_run_process = mocker.patch.object(driver, "run_process")
        mock_run_process.return_value = "Error"
        with pytest.raises(PowerActionError):
            driver.power_query(system_id, context)
