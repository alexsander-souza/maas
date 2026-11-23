# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `provisioningserver.drivers.power.manual`."""

from provisioningserver.drivers.power import manual as manual_module


class TestManualPowerDriver:
    def test_no_missing_packages(self):
        driver = manual_module.ManualPowerDriver()
        missing = driver.detect_missing_packages()
        assert [] == missing

    def test_power_on(self, mocker):
        driver = manual_module.ManualPowerDriver()
        mock_log_info = mocker.patch.object(manual_module.maaslog, "info")
        driver.power_on("fake_id", {})
        mock_log_info.assert_called_once_with(
            "You need to power on fake_id manually."
        )

    def test_power_off(self, mocker):
        driver = manual_module.ManualPowerDriver()
        mock_log_info = mocker.patch.object(manual_module.maaslog, "info")
        driver.power_off("fake_id", {})
        mock_log_info.assert_called_once_with(
            "You need to power off fake_id manually."
        )

    def test_power_query(self, mocker):
        driver = manual_module.ManualPowerDriver()
        mock_log_info = mocker.patch.object(manual_module.maaslog, "info")
        power_state = driver.power_query("fake_id", {})
        assert power_state == "unknown"
        mock_log_info.assert_called_once_with(
            "You need to check power state of fake_id manually."
        )
