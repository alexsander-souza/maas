# Copyright 2016-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from textwrap import dedent
from unittest.mock import call

from metadataserver.builtin_scripts.commissioning_scripts import (
    capture_lldpd,
    install_lldpd,
)


class TestLLDPScripts:
    def test_install_script_installs_configures_and_restarts_systemd(
        self, mocker, tmp_path
    ):
        config_file = tmp_path / "config"
        config_file.write_text("# ...")
        check_call = mocker.patch.object(install_lldpd, "check_call")
        mocker.patch.object(install_lldpd.os.path, "isdir").return_value = True
        install_lldpd.lldpd_install(str(config_file))
        # lldpd is installed and restarted.
        assert check_call.call_args_list == [
            call(("systemctl", "restart", "lldpd"))
        ]
        # lldpd's config was updated to include an updated DAEMON_ARGS
        # setting. Note that the new comment is on a new line, and
        # does not interfere with existing config.
        config_expected = dedent(
            """\
            # ...
            # Configured by MAAS:
            DAEMON_ARGS="-c -f -s -e -r"
            """
        ).encode("ascii")
        with open(str(config_file), "rb") as fd:
            config_observed = fd.read()
        assert config_expected == config_observed

    def test_install_script_disables_intel_lldp(self, mocker, tmp_path):
        mocker.patch.object(
            install_lldpd.os.path, "exists"
        ).return_value = True
        mocker.patch.object(install_lldpd.os, "listdir").return_value = [
            "0000:1a:00.0"
        ]
        temp_file = tmp_path / "temp"
        temp_file.write_text("")
        mock_open = mocker.patch.object(install_lldpd, "open")
        mock_open.return_value = open(str(temp_file), "w", encoding="ascii")
        install_lldpd.disable_embedded_lldp_agent_in_intel_cna_cards()
        output_expected = b"lldp stop\n"
        with open(str(temp_file), "rb") as fd:
            output_observed = fd.read()
        assert output_expected == output_observed
        mock_open.assert_called_once_with(
            "/sys/kernel/debug/i40e/0000:1a:00.0/command",
            "w",
            encoding="ascii",
        )

    def test_capture_lldpd_script_waits_for_lldpd(self, mocker, tmp_path):
        reference_file = tmp_path / "reference"
        reference_file.write_text("")
        time_delay = 8.98  # seconds
        # Do the patching as late as possible, because the setup may call
        # one of the patched functions somewhere in the plumbing.  We've had
        # spurious test failures over this: bug 1283918.
        mock_mtime = mocker.patch.object(capture_lldpd, "getmtime")
        mock_mtime.return_value = 10.65
        mock_time = mocker.patch.object(capture_lldpd, "time")
        mock_time.return_value = 14.12
        mock_sleep = mocker.patch.object(capture_lldpd, "sleep")
        mocker.patch.object(capture_lldpd, "check_call")

        capture_lldpd.lldpd_capture(str(reference_file), time_delay)

        # lldpd_wait checks the mtime of the reference file,
        mock_mtime.assert_called_once_with(str(reference_file))
        # and gets the current time,
        mock_time.assert_called_once_with()
        # then sleeps until time_delay seconds has passed since the
        # mtime of the reference file.
        mock_sleep.assert_called_once_with(
            mock_mtime() + time_delay - mock_time()
        )

    def test_capture_lldpd_script_doesnt_waits_for_more_than_sixty_secs(
        self, mocker, tmp_path
    ):
        # Regression test for LP:1801152
        reference_file = tmp_path / "reference"
        reference_file.write_text("")
        mocker.patch.object(capture_lldpd, "getmtime").return_value = 1000.1
        mocker.patch.object(capture_lldpd, "time").return_value = 10.25
        mock_sleep = mocker.patch.object(capture_lldpd, "sleep")
        mocker.patch.object(capture_lldpd, "check_call")

        capture_lldpd.lldpd_capture(str(reference_file), 60)

        mock_sleep.assert_called_once_with(60)

    def test_capture_lldpd_calls_lldpdctl(self, mocker, tmp_path):
        reference_file = tmp_path / "reference"
        reference_file.write_text("")
        check_call = mocker.patch.object(capture_lldpd, "check_call")
        capture_lldpd.lldpd_capture(str(reference_file), 0.0)
        assert check_call.call_args_list == [call(("lldpctl", "-f", "xml"))]
