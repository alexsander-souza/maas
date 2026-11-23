# Copyright 2017-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test smartctl functions."""

import io
import random
from subprocess import CalledProcessError, DEVNULL, STDOUT, TimeoutExpired
from unittest.mock import call

import pytest

from maasserver.testing.factory import factory
from metadataserver.builtin_scripts.testing_scripts import smartctl


class TestRunSmartCTL:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        self.output = factory.make_name("output")
        self.mock_check_output = mocker.patch.object(smartctl, "check_output")
        self.mock_check_output.return_value = self.output.encode()
        self.mock_print = mocker.patch.object(smartctl, "print")
        self.blockdevice = factory.make_name("blockdevice")
        self.args = [factory.make_name("arg") for _ in range(3)]

    def test_default(self):
        assert self.output == smartctl.run_smartctl(
            self.blockdevice, self.args
        )
        self.mock_check_output.assert_called_once_with(
            ["sudo", "-n", "smartctl"] + self.args + [self.blockdevice],
            timeout=smartctl.TIMEOUT,
        )
        self.mock_print.assert_not_called()

    def test_device(self):
        device = factory.make_name("device")
        assert self.output == smartctl.run_smartctl(
            self.blockdevice, self.args, device=device
        )
        self.mock_check_output.assert_called_once_with(
            ["sudo", "-n", "smartctl", "-d", device]
            + self.args
            + [self.blockdevice],
            timeout=smartctl.TIMEOUT,
        )
        self.mock_print.assert_not_called()

    def test_output(self):
        assert self.output == smartctl.run_smartctl(
            self.blockdevice, self.args, output=True
        )
        self.mock_check_output.assert_called_once_with(
            ["sudo", "-n", "smartctl"] + self.args + [self.blockdevice],
            timeout=smartctl.TIMEOUT,
        )
        self.mock_print.assert_called_once()

    def test_output_invalid_utf8_replaced(self):
        # invalid UTF-8 input
        self.mock_check_output.return_value = b"foo\x99bar"
        assert "foo\ufffdbar" == smartctl.run_smartctl(
            self.blockdevice, self.args, output=True
        )


class TestRunStorCLI:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        self.output = factory.make_name("output")
        self.mock_check_output = mocker.patch.object(smartctl, "check_output")
        self.mock_check_output.return_value = self.output.encode()
        self.mock_print = mocker.patch.object(smartctl, "print")
        self.args = [factory.make_name("arg") for _ in range(3)]

    def test_default(self):
        assert self.output == smartctl.run_storcli(self.args)
        self.mock_check_output.assert_called_once_with(
            ["sudo", "-n", "storcli64"] + self.args,
            timeout=smartctl.TIMEOUT,
        )
        self.mock_print.assert_not_called()

    def test_using_alt_path(self, mocker):
        mocker.patch.object(smartctl.os.path, "exists").return_value = True
        assert self.output == smartctl.run_storcli(self.args)
        self.mock_check_output.assert_called_once_with(
            ["sudo", "-n", "/opt/MegaRAID/storcli/storcli64"] + self.args,
            timeout=smartctl.TIMEOUT,
        )
        self.mock_print.assert_not_called()

    def test_output(self):
        assert self.output == smartctl.run_storcli(self.args, True)
        self.mock_check_output.assert_called_once_with(
            ["sudo", "-n", "storcli64"] + self.args,
            timeout=smartctl.TIMEOUT,
        )
        self.mock_print.assert_called_once()


class TestMakeDeviceName:
    def test_blockdevice(self):
        blockdevice = factory.make_name("blockdevice")
        assert blockdevice == smartctl.make_device_name(blockdevice)

    def test_device(self):
        blockdevice = factory.make_name("blockdevice")
        device = factory.make_name("device")
        assert f"{blockdevice} {device}" == smartctl.make_device_name(
            blockdevice, device
        )


class TestExitSkipped:
    def test_default(self, mocker):
        result_path = factory.make_name("result_path")
        mocker.patch.object(
            smartctl.os, "environ", {"RESULT_PATH": result_path}
        )
        mock_open = mocker.patch.object(smartctl, "open")
        mock_open.return_value = io.StringIO()
        mock_yaml_safe_dump = mocker.patch.object(smartctl.yaml, "safe_dump")

        with pytest.raises(SystemExit):
            smartctl.exit_skipped()
        mock_open.assert_called_once_with(result_path, "w")
        mock_yaml_safe_dump.assert_called_once_with(
            {"status": "skipped"}, mock_open.return_value
        )


class TestFindMatchingMegaRAIDController:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        mocker.patch.object(smartctl, "print")

    def test_no_controllers(self, mocker):
        mock_run_storcli = mocker.patch.object(smartctl, "run_storcli")
        mock_run_storcli.return_value = ""
        mock_exit_skipped = mocker.patch.object(smartctl, "exit_skipped")

        smartctl.find_matching_megaraid_controller(
            factory.make_name("blockdevice")
        )

        mock_exit_skipped.assert_called_once()

    def test_found(self, mocker):
        scsi_id = factory.make_name()
        mock_run_storcli = mocker.patch.object(smartctl, "run_storcli")
        mock_run_storcli.side_effect = (
            "Number of Controllers = 2",
            "Virtual Drives = 1",
            "SCSI NAA Id = %s" % factory.make_name("scsi_id"),
            "Virtual Drives = 1",
            f"SCSI NAA Id = {scsi_id}",
        )
        mocker.patch.object(smartctl.glob, "glob").return_value = [
            factory.make_name("path")
        ]
        mocker.patch.object(smartctl.os.path, "realpath").side_effect = (
            scsi_id,
            scsi_id,
        )
        assert 1 == smartctl.find_matching_megaraid_controller(
            factory.make_name("blockdevice")
        )

    def test_no_matching_scsi_id(self, mocker):
        mock_run_storcli = mocker.patch.object(smartctl, "run_storcli")
        mock_run_storcli.side_effect = (
            "Number of Controllers = 1",
            "Virtual Drives = 1",
            "SCSI NAA Id = %s" % factory.make_name("scsi_id"),
        )
        mock_exit_skipped = mocker.patch.object(smartctl, "exit_skipped")
        smartctl.find_matching_megaraid_controller(
            factory.make_name("blockdevice")
        )
        mock_exit_skipped.assert_called_once()


class TestDetectMegaRAIDConfig:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        mocker.patch.object(smartctl, "print")

    def test_no_storcli(self, mocker):
        mock_exit_skipped = mocker.patch.object(smartctl, "exit_skipped")
        smartctl.detect_megaraid_config(factory.make_name("blockdevice"))
        mock_exit_skipped.assert_called_once()

    def test_returns_scsi_bus_nums(self, mocker):
        controller = random.randint(0, 3)
        scsi_bus_nums = [random.randint(0, 127) for _ in range(3)]
        mocker.patch.object(smartctl.os.path, "exists").return_value = True
        mocker.patch.object(
            smartctl, "find_matching_megaraid_controller"
        ).return_value = controller
        mock_run_storcli = mocker.patch.object(smartctl, "run_storcli")
        mock_run_storcli.return_value = "".join(
            [
                "%d:%d %d\n"
                % (
                    random.randint(0, 255),
                    random.randint(0, 255),
                    scsi_bus_num,
                )
                for scsi_bus_num in scsi_bus_nums
            ]
        )

        assert sorted(scsi_bus_nums) == sorted(
            smartctl.detect_megaraid_config(factory.make_name("blockdevice"))
        )
        mock_run_storcli.assert_called_once_with(
            [f"/c{controller}", "/eall", "/sall", "show"]
        )


class TestCheckSMARTSupport:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        mocker.patch.object(smartctl, "print")

    def test_raises_timeoutexpired(self, mocker):
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        mock_run_smartctl.side_effect = TimeoutExpired("smartctl", 60)
        with pytest.raises(TimeoutExpired):
            smartctl.check_SMART_support(factory.make_name("blockdevice"))

    def test_raises_calledprocesserrror(self, mocker):
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        mock_run_smartctl.side_effect = CalledProcessError(1, "smartctl")
        with pytest.raises(CalledProcessError):
            smartctl.check_SMART_support(factory.make_name("blockdevice"))

    def test_available(self, mocker):
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        mock_run_smartctl.return_value = (
            "Product: %s\n"
            "SMART support is: Available\n" % factory.make_name("product")
        )
        assert (None, []) == smartctl.check_SMART_support(
            factory.make_name("blockdevice")
        )

    def test_available2(self, mocker):
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        mock_run_smartctl.return_value = (
            "SMART overall-health self-assessment test result: "
        )
        assert (None, []) == smartctl.check_SMART_support(
            factory.make_name("blockdevice")
        )

    def test_available_megaraid(self, mocker):
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        mock_run_smartctl.return_value = (
            "Product: MegaRAID\nSMART support is: Unavailable\n"
        )
        scsi_ids = [random.randint(0, 127) for _ in range(3)]
        mocker.patch.object(
            smartctl, "detect_megaraid_config"
        ).return_value = scsi_ids
        assert ("megaraid", scsi_ids) == smartctl.check_SMART_support(
            factory.make_name("blockdevice")
        )

    def test_unavailable(self, mocker):
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        mock_run_smartctl.return_value = (
            "Product: %s\n"
            "SMART support is: Unavailable\n" % factory.make_name("product")
        )
        mock_exit_skipped = mocker.patch.object(smartctl, "exit_skipped")
        smartctl.check_SMART_support(factory.make_name("blockdevice"))
        mock_exit_skipped.assert_called_once()


class TestRunSmartCTLSelfTest:
    def test_default(self, mocker):
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        blockdevice = factory.make_name("blockdevice")
        test = factory.make_name("test")
        device = factory.make_name("device")
        smartctl.run_smartctl_selftest(blockdevice, test, device)
        mock_run_smartctl.assert_called_once_with(
            blockdevice, ["-t", test], device, output=True, stderr=DEVNULL
        )

    def test_raises_timeoutexpired(self, mocker):
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        mock_run_smartctl.side_effect = TimeoutExpired("smartctl", 60)
        mock_print = mocker.patch.object(smartctl, "print")
        blockdevice = factory.make_name("blockdevice")
        test = factory.make_name("test")
        with pytest.raises(TimeoutExpired):
            smartctl.run_smartctl_selftest(blockdevice, test)
        mock_print.assert_called_once()

    def test_raises_calledprocesserror(self, mocker):
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        mock_run_smartctl.side_effect = CalledProcessError(1, "smartctl")
        mock_print = mocker.patch.object(smartctl, "print")
        blockdevice = factory.make_name("blockdevice")
        test = factory.make_name("test")
        with pytest.raises(CalledProcessError):
            smartctl.run_smartctl_selftest(blockdevice, test)
        mock_print.assert_called_once()


class TestWaitSmartCTLSelfTest:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        mocker.patch.object(smartctl, "print")

    def test_waits(self, mocker):
        blockdevice = factory.make_name("blockdevice")
        test = factory.make_name("test")
        device = factory.make_name("device")
        mock_sleep = mocker.patch.object(smartctl, "sleep")
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        mock_run_smartctl.side_effect = (
            "Self-test execution status: (42) Self-test routine in progress",
            "",
            "",
        )

        smartctl.wait_smartctl_selftest(blockdevice, test, device)

        mock_run_smartctl.assert_has_calls(
            [
                call(blockdevice, ["-c"], device),
                call(blockdevice, ["-c"], device),
                call(blockdevice, ["--all"], device),
            ]
        )
        mock_sleep.assert_called_once_with(30)

    def test_waits_alt(self, mocker):
        blockdevice = factory.make_name("blockdevice")
        test = factory.make_name("test")
        device = factory.make_name("device")
        mock_sleep = mocker.patch.object(smartctl, "sleep")
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        mock_run_smartctl.side_effect = (
            f"Background {test} Self test in progress",
            f"Background {test} Self test in progress",
            "",
        )

        smartctl.wait_smartctl_selftest(blockdevice, test, device)

        mock_run_smartctl.assert_has_calls(
            [
                call(blockdevice, ["-c"], device),
                call(blockdevice, ["--all"], device),
                call(blockdevice, ["--all"], device),
            ]
        )
        mock_sleep.assert_called_once_with(30)

    def test_raises_timeoutexpired(self, mocker):
        blockdevice = factory.make_name("blockdevice")
        test = factory.make_name("test")
        device = factory.make_name("device")
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        mock_run_smartctl.side_effect = TimeoutExpired("smartctl", 60)
        mock_sleep = mocker.patch.object(smartctl, "sleep")
        with pytest.raises(TimeoutExpired):
            smartctl.wait_smartctl_selftest(blockdevice, test, device)
        mock_sleep.assert_not_called()

    def test_raises_calledprocesserror(self, mocker):
        blockdevice = factory.make_name("blockdevice")
        test = factory.make_name("test")
        device = factory.make_name("device")
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        mock_run_smartctl.side_effect = CalledProcessError(1, "smartctl")
        mock_sleep = mocker.patch.object(smartctl, "sleep")
        with pytest.raises(CalledProcessError):
            smartctl.wait_smartctl_selftest(blockdevice, test, device)
        mock_sleep.assert_not_called()


class TestCheckSmartCTL:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        mocker.patch.object(smartctl, "print")

    def test_default(self, mocker):
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        blockdevice = factory.make_name("blockdevice")
        device = factory.make_name("device")
        smartctl.check_smartctl(blockdevice, device)
        mock_run_smartctl.assert_called_once_with(
            blockdevice, ["--xall"], device, output=True, stderr=STDOUT
        )

    def test_raises_timeoutexpired(self, mocker):
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        mock_run_smartctl.side_effect = TimeoutExpired("smartctl", 60)
        blockdevice = factory.make_name("blockdevice")
        with pytest.raises(TimeoutExpired):
            smartctl.check_smartctl(blockdevice)

    def test_ignores_returncode_four(self, mocker):
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        mock_run_smartctl.side_effect = CalledProcessError(
            4, "smartctl", factory.make_name("output").encode()
        )
        blockdevice = factory.make_name("blockdevice")
        device = factory.make_name("device")
        smartctl.check_smartctl(blockdevice, device)
        mock_run_smartctl.assert_called_once_with(
            blockdevice, ["--xall"], device, output=True, stderr=STDOUT
        )

    def test_ignores_returncode_sixty_four(self, mocker):
        # Bit 6 is set when the error log contains past errors, which does
        # not indicate the drive is currently failing.
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        mock_run_smartctl.side_effect = CalledProcessError(
            64, "smartctl", factory.make_name("output").encode()
        )
        blockdevice = factory.make_name("blockdevice")
        device = factory.make_name("device")
        smartctl.check_smartctl(blockdevice, device)
        mock_run_smartctl.assert_called_once_with(
            blockdevice, ["--xall"], device, output=True, stderr=STDOUT
        )

    def test_ignores_returncode_sixty_eight(self, mocker):
        # Bits 2 and 6 set together (4 | 64) are both ignored.
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        mock_run_smartctl.side_effect = CalledProcessError(
            68, "smartctl", factory.make_name("output").encode()
        )
        blockdevice = factory.make_name("blockdevice")
        device = factory.make_name("device")
        smartctl.check_smartctl(blockdevice, device)
        mock_run_smartctl.assert_called_once_with(
            blockdevice, ["--xall"], device, output=True, stderr=STDOUT
        )

    def test_raises_when_other_bits_set_with_ignored_bits(self, mocker):
        # Bit 6 ignored, but bit 0 (1) still indicates a real failure.
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        mock_run_smartctl.side_effect = CalledProcessError(
            65, "smartctl", factory.make_name("output").encode()
        )
        blockdevice = factory.make_name("blockdevice")
        with pytest.raises(CalledProcessError):
            smartctl.check_smartctl(blockdevice)

    def test_raises_calledprocesserror(self, mocker):
        mock_run_smartctl = mocker.patch.object(smartctl, "run_smartctl")
        mock_run_smartctl.side_effect = CalledProcessError(42, "smartctl")
        blockdevice = factory.make_name("blockdevice")
        with pytest.raises(CalledProcessError):
            smartctl.check_smartctl(blockdevice)


class TestExecuteSmartCTL:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        mocker.patch.object(smartctl, "print")
        self.blockdevice = factory.make_name("blockdevice")
        self.test = factory.make_name("test")
        self.mock_check_smart_support = mocker.patch.object(
            smartctl, "check_SMART_support"
        )
        self.mock_run_smartctl_selftest = mocker.patch.object(
            smartctl, "run_smartctl_selftest"
        )
        self.mock_wait_smartctl_selftest = mocker.patch.object(
            smartctl, "wait_smartctl_selftest"
        )
        self.mock_check_smartctl = mocker.patch.object(
            smartctl, "check_smartctl"
        )

    def test_returns_false_with_check_smart_support_error(self):
        self.mock_check_smart_support.side_effect = random.choice(
            [
                TimeoutExpired("smartctl", 60),
                CalledProcessError(42, "smartctl"),
            ]
        )
        assert not smartctl.execute_smartctl(self.blockdevice, self.test)
        self.mock_run_smartctl_selftest.assert_not_called()
        self.mock_wait_smartctl_selftest.assert_not_called()
        self.mock_check_smartctl.assert_not_called()

    def test_returns_false_when_unable_to_check_device_support(self):
        device = factory.make_name("device")
        self.mock_check_smart_support.side_effect = (
            (device, [42]),
            random.choice(
                [
                    TimeoutExpired("smartctl", 60),
                    CalledProcessError(42, "smartctl"),
                ]
            ),
        )
        device = f"{device},42"
        assert not smartctl.execute_smartctl(self.blockdevice, self.test)
        self.mock_check_smart_support.assert_has_calls(
            [call(self.blockdevice), call(self.blockdevice, device)]
        )
        self.mock_run_smartctl_selftest.assert_not_called()
        self.mock_wait_smartctl_selftest.assert_called_once_with(
            self.blockdevice, self.test, device
        )
        self.mock_check_smartctl.assert_called_once_with(
            self.blockdevice, device
        )

    def test_returns_false_when_unable_to_start_device_test(self):
        device = factory.make_name("device")
        self.mock_check_smart_support.return_value = (device, [42])
        self.mock_run_smartctl_selftest.side_effect = (
            random.choice(
                [
                    TimeoutExpired("smartctl", 60),
                    CalledProcessError(42, "smartctl"),
                ]
            ),
        )
        device = f"{device},42"
        assert not smartctl.execute_smartctl(self.blockdevice, self.test)
        self.mock_check_smart_support.assert_has_calls(
            [call(self.blockdevice), call(self.blockdevice, device)]
        )
        self.mock_run_smartctl_selftest.assert_called_once_with(
            self.blockdevice, self.test, device
        )

        self.mock_wait_smartctl_selftest.assert_called_once_with(
            self.blockdevice, self.test, device
        )
        self.mock_check_smartctl.assert_called_once_with(
            self.blockdevice, device
        )

    def test_returns_false_when_unable_to_wait_start_device_test(self):
        device = factory.make_name("device")
        self.mock_check_smart_support.return_value = (device, [42])
        self.mock_wait_smartctl_selftest.side_effect = (
            random.choice(
                [
                    TimeoutExpired("smartctl", 60),
                    CalledProcessError(42, "smartctl"),
                ]
            ),
        )
        device = f"{device},42"
        assert not smartctl.execute_smartctl(self.blockdevice, self.test)
        self.mock_check_smart_support.assert_has_calls(
            [call(self.blockdevice), call(self.blockdevice, device)]
        )
        self.mock_run_smartctl_selftest.assert_called_once_with(
            self.blockdevice, self.test, device
        )

        self.mock_wait_smartctl_selftest.assert_called_once_with(
            self.blockdevice, self.test, device
        )
        self.mock_check_smartctl.assert_called_once_with(
            self.blockdevice, device
        )

    def test_returns_false_when_unable_to_check_device(self):
        device = factory.make_name("device")
        self.mock_check_smart_support.return_value = (device, [42])
        self.mock_check_smartctl.side_effect = (
            random.choice(
                [
                    TimeoutExpired("smartctl", 60),
                    CalledProcessError(42, "smartctl"),
                ]
            ),
        )
        device = f"{device},42"
        assert not smartctl.execute_smartctl(self.blockdevice, self.test)
        self.mock_check_smart_support.assert_has_calls(
            [call(self.blockdevice), call(self.blockdevice, device)]
        )
        self.mock_run_smartctl_selftest.assert_called_once_with(
            self.blockdevice, self.test, device
        )

        self.mock_wait_smartctl_selftest.assert_called_once_with(
            self.blockdevice, self.test, device
        )
        self.mock_check_smartctl.assert_called_once_with(
            self.blockdevice, device
        )

    def test_returns_true_with_device(self):
        device = factory.make_name("device")
        self.mock_check_smart_support.return_value = (device, [42])
        device = f"{device},42"
        assert smartctl.execute_smartctl(self.blockdevice, self.test)
        self.mock_check_smart_support.assert_has_calls(
            [call(self.blockdevice), call(self.blockdevice, device)]
        )
        self.mock_check_smart_support.assert_has_calls(
            [call(self.blockdevice), call(self.blockdevice, device)]
        )
        self.mock_run_smartctl_selftest.assert_called_once_with(
            self.blockdevice, self.test, device
        )

        self.mock_wait_smartctl_selftest.assert_called_once_with(
            self.blockdevice, self.test, device
        )
        self.mock_check_smartctl.assert_called_once_with(
            self.blockdevice, device
        )

    def test_tests_all_scsi_bus_nums(self):
        device = factory.make_name("device")
        self.mock_check_smart_support.return_value = (device, [1, 2, 3])
        assert smartctl.execute_smartctl(self.blockdevice, self.test)
        self.mock_check_smart_support.assert_has_calls(
            [
                call(self.blockdevice),
                call(self.blockdevice, f"{device},1"),
                call(self.blockdevice, f"{device},2"),
                call(self.blockdevice, f"{device},3"),
            ]
        )
        self.mock_run_smartctl_selftest.assert_has_calls(
            [
                call(self.blockdevice, self.test, f"{device},1"),
                call(self.blockdevice, self.test, f"{device},2"),
                call(self.blockdevice, self.test, f"{device},3"),
            ]
        )
        self.mock_wait_smartctl_selftest.assert_has_calls(
            [
                call(self.blockdevice, self.test, f"{device},1"),
                call(self.blockdevice, self.test, f"{device},2"),
                call(self.blockdevice, self.test, f"{device},3"),
            ]
        )
        self.mock_check_smartctl.assert_has_calls(
            [
                call(self.blockdevice, f"{device},1"),
                call(self.blockdevice, f"{device},2"),
                call(self.blockdevice, f"{device},3"),
            ]
        )

    def test_doesnt_run_testing_when_validating_device(self):
        device = factory.make_name("device")
        self.mock_check_smart_support.return_value = (device, [42])
        device = f"{device},42"
        assert smartctl.execute_smartctl(self.blockdevice, "validate")
        self.mock_check_smart_support.assert_has_calls(
            [call(self.blockdevice), call(self.blockdevice, device)]
        )
        self.mock_run_smartctl_selftest.assert_not_called()
        self.mock_wait_smartctl_selftest.assert_not_called()
        self.mock_check_smartctl.assert_called_once_with(
            self.blockdevice, device
        )

    def test_returns_false_when_starting_test_fails(self):
        self.mock_check_smart_support.return_value = (None, [])
        self.mock_run_smartctl_selftest.side_effect = random.choice(
            [
                TimeoutExpired("smartctl", 60),
                CalledProcessError(42, "smartctl"),
            ]
        )
        assert not smartctl.execute_smartctl(self.blockdevice, self.test)
        self.mock_run_smartctl_selftest.assert_called_once_with(
            self.blockdevice, self.test
        )
        self.mock_wait_smartctl_selftest.assert_not_called()
        self.mock_check_smartctl.assert_called_once_with(self.blockdevice)

    def test_returns_false_when_waiting_test_fails(self):
        self.mock_check_smart_support.return_value = (None, [])
        self.mock_wait_smartctl_selftest.side_effect = random.choice(
            [
                TimeoutExpired("smartctl", 60),
                CalledProcessError(42, "smartctl"),
            ]
        )
        assert not smartctl.execute_smartctl(self.blockdevice, self.test)
        self.mock_run_smartctl_selftest.assert_called_once_with(
            self.blockdevice, self.test
        )
        self.mock_wait_smartctl_selftest.assert_called_once_with(
            self.blockdevice, self.test
        )
        self.mock_check_smartctl.assert_called_once_with(self.blockdevice)

    def test_returns_false_when_check_fails(self):
        self.mock_check_smart_support.return_value = (None, [])
        self.mock_check_smartctl.side_effect = random.choice(
            [
                TimeoutExpired("smartctl", 60),
                CalledProcessError(42, "smartctl"),
            ]
        )
        assert not smartctl.execute_smartctl(self.blockdevice, self.test)
        self.mock_run_smartctl_selftest.assert_called_once_with(
            self.blockdevice, self.test
        )
        self.mock_wait_smartctl_selftest.assert_called_once_with(
            self.blockdevice, self.test
        )
        self.mock_check_smartctl.assert_called_once_with(self.blockdevice)

    def test_returns_true(self):
        self.mock_check_smart_support.return_value = (None, [])
        assert smartctl.execute_smartctl(self.blockdevice, self.test)
        self.mock_run_smartctl_selftest.assert_called_once_with(
            self.blockdevice, self.test
        )
        self.mock_wait_smartctl_selftest.assert_called_once_with(
            self.blockdevice, self.test
        )
        self.mock_check_smartctl.assert_called_once_with(self.blockdevice)

    def test_doesnt_run_testing_when_validating(self):
        self.mock_check_smart_support.return_value = (None, [])
        assert smartctl.execute_smartctl(self.blockdevice, "validate")
        self.mock_run_smartctl_selftest.assert_not_called()
        self.mock_wait_smartctl_selftest.assert_not_called()
        self.mock_check_smartctl.assert_called_once_with(self.blockdevice)
