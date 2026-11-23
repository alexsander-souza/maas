# Copyright 2017-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `provisioningserver.drivers.power.virsh`."""

import os
from pathlib import Path
import re

import pexpect
import pytest
from twisted.internet.defer import inlineCallbacks

from maascommon.fips import FIPS_SSH_CONFIG
from maastesting import dev_root, get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.factory import factory
from provisioningserver.drivers.power import virsh
from provisioningserver.drivers.power.virsh import VirshPowerDriver
from provisioningserver.utils.shell import get_env_with_locale

TIMEOUT = get_testing_timeout()


@pytest.fixture(autouse=True)
def _pytest_test_helpers(request, mocker):
    if request.instance is not None:
        request.instance.mocker = mocker
        request.instance.request = request


class TestWriteKnownHosts:
    """Tests for `_write_known_hosts`."""

    def test_writes_one_line_per_trusted_key(self):
        path = virsh._write_known_hosts(
            "10.0.0.2",
            [
                {"key_type": "ecdsa-sha2-nistp256", "public_key": "AAAA"},
                {"key_type": "rsa-sha2-256", "public_key": "BBBB"},
            ],
        )
        self.request.addfinalizer(lambda: os.unlink(path))

        with open(path) as known_hosts_file:
            content = known_hosts_file.read()
        assert content == (
            "10.0.0.2 ecdsa-sha2-nistp256 AAAA\n10.0.0.2 rsa-sha2-256 BBBB\n"
        )


class TestVerifiedSshWrapperAlgorithms:
    """The `verified-ssh` wrapper's algorithm allow-lists must stay in
    lockstep with `maascommon.fips.FIPS_SSH_CONFIG`; shell can't import
    Python, so this is the drift guard."""

    def _read_wrapper(self):
        path = os.path.join(
            dev_root, "package-files/usr/lib/maas/verified-ssh"
        )
        with open(path) as wrapper_file:
            return wrapper_file.read()

    def _option_values(self, script, option):
        match = re.search(rf"-o {option}=(\S+?) \\", script)
        assert match is not None, f"{option} not found in verified-ssh wrapper"
        return tuple(match.group(1).rstrip(",").split(","))

    def test_ciphers_match_fips_ssh_config(self):
        script = self._read_wrapper()
        assert (
            self._option_values(script, "Ciphers") == FIPS_SSH_CONFIG.ciphers
        )

    def test_kex_algorithms_match_fips_ssh_config(self):
        script = self._read_wrapper()
        assert (
            self._option_values(script, "KexAlgorithms") == FIPS_SSH_CONFIG.kex
        )

    def test_macs_match_fips_ssh_config(self):
        script = self._read_wrapper()
        assert self._option_values(script, "MACs") == FIPS_SSH_CONFIG.macs

    def test_host_key_algorithms_match_fips_ssh_config(self):
        script = self._read_wrapper()
        assert (
            self._option_values(script, "HostKeyAlgorithms")
            == FIPS_SSH_CONFIG.key_types
        )

    def test_isolates_verification_from_global_known_hosts(self):
        script = self._read_wrapper()
        assert "-o GlobalKnownHostsFile=/dev/null \\" in script


class TestVirshSSH:
    """Tests for `VirshSSH`."""

    def configure_virshssh_pexpect(self, inputs=None, dom_prefix=None):
        """Configures the VirshSSH class to use 'cat' process
        for testing instead of the actual virsh."""
        conn = virsh.VirshSSH(timeout=0.1, dom_prefix=dom_prefix)
        self.request.addfinalizer(conn.close)
        self.mocker.patch.object(conn, "_execute")
        conn._spawn("cat")
        if inputs is not None:
            for line in inputs:
                conn.sendline(line)
        return conn

    def configure_virshssh(self, results, dom_prefix=None):
        virshssh = virsh.VirshSSH(dom_prefix=dom_prefix)
        mock_run = self.mocker.patch.object(virshssh, "run")
        if isinstance(results, str):
            mock_run.return_value = results
        else:
            # either a single exception or a list of results/errors
            mock_run.side_effect = results

        return virshssh

    def test_login_prompt(self):
        virsh_outputs = ["virsh # "]
        conn = self.configure_virshssh_pexpect(virsh_outputs)
        assert conn.login(poweraddr=factory.make_name("poweraddr"))

    def test_login_with_sshkey(self):
        virsh_outputs = [
            "The authenticity of host '127.0.0.1' can't be established.",
            "ECDSA key fingerprint is "
            "00:11:22:33:44:55:66:77:88:99:aa:bb:cc:dd:ee:ff.",
            "Are you sure you want to continue connecting (yes/no)? ",
        ]
        conn = self.configure_virshssh_pexpect(virsh_outputs)
        mock_sendline = self.mocker.patch.object(conn, "sendline")
        conn.login(poweraddr=factory.make_name("poweraddr"))
        mock_sendline.assert_called_once_with("yes")

    def test_login_with_password(self):
        virsh_outputs = [
            "ubuntu@%s's password: " % factory.make_ipv4_address()
        ]
        conn = self.configure_virshssh_pexpect(virsh_outputs)
        fake_password = factory.make_name("password")
        mock_sendline = self.mocker.patch.object(conn, "sendline")
        conn.login(
            poweraddr=factory.make_name("poweraddr"), password=fake_password
        )
        mock_sendline.assert_called_once_with(fake_password)

    def test_login_missing_password(self):
        virsh_outputs = [
            "ubuntu@%s's password: " % factory.make_ipv4_address()
        ]
        conn = self.configure_virshssh_pexpect(virsh_outputs)
        mock_close = self.mocker.patch.object(conn, "close")
        assert not conn.login(poweraddr=factory.make_name("poweraddr"))
        mock_close.assert_called_once_with()

    def test_pkttyagent_permission_denied(self):
        # Sometimes pkttyagent can't be executed in the snap. The connection
        # itself still works, though.
        # See https://bugs.launchpad.net/maas/+bug/2053033
        virsh_outputs = [
            "libvirt:  error : cannot execute binary /usr/bin/pkttyagent: Permission denied",
            "Welcome to virsh, the virtualization interactive terminal.",
            "",
            "Type:  'help' for help with commands",
            "       'quit' to quit",
            "",
            "virsh # ",
        ]
        conn = self.configure_virshssh_pexpect(virsh_outputs)
        assert conn.login(poweraddr=factory.make_name("poweraddr"))

    def test_login_invalid(self):
        virsh_outputs = ["Permission denied, please try again."]
        conn = self.configure_virshssh_pexpect(virsh_outputs)
        mock_close = self.mocker.patch.object(conn, "close")
        assert not conn.login(poweraddr=factory.make_name("poweraddr"))
        mock_close.assert_called_once_with()

    def test_unknown(self):
        virsh_outputs = [factory.make_string()]
        conn = self.configure_virshssh_pexpect(virsh_outputs)
        mock_close = self.mocker.patch.object(conn, "close")
        assert not conn.login(poweraddr=factory.make_name("poweraddr"))
        mock_close.assert_called_once_with()

    def test_login_errors_with_poweraddr_extra_parameters(self):
        conn = virsh.VirshSSH(timeout=0.1)
        self.request.addfinalizer(conn.close)
        poweraddr = "qemu+ssh://ubuntu@10.0.0.2/system?no_verify=1"
        conn._spawn("cat")
        with pytest.raises(virsh.VirshError):
            conn.login(poweraddr)

    def test_login_with_poweraddr_adds_extra_parameters(self):
        conn = virsh.VirshSSH(timeout=0.1)
        self.request.addfinalizer(conn.close)
        mock_execute = self.mocker.patch.object(conn, "_execute")
        mock_close = self.mocker.patch.object(conn, "close")
        poweraddr = "qemu+ssh://ubuntu@10.0.0.2/system"
        conn._spawn("cat")
        assert not conn.login(poweraddr=poweraddr)
        new_poweraddr = poweraddr + "?command=/usr/lib/maas/unverified-ssh"
        mock_execute.assert_called_once_with(new_poweraddr)
        mock_close.assert_called_once_with()

    def test_login_with_poweraddr_no_extra_parameters(self):
        conn = virsh.VirshSSH(timeout=0.1)
        self.request.addfinalizer(conn.close)
        mock_execute = self.mocker.patch.object(conn, "_execute")
        mock_close = self.mocker.patch.object(conn, "close")
        poweraddr = "qemu+ssh://ubuntu@10.0.0.2/system"
        conn._spawn("cat")
        assert not conn.login(poweraddr=poweraddr)
        mock_execute.assert_called_once_with(
            poweraddr + "?command=/usr/lib/maas/unverified-ssh"
        )
        mock_close.assert_called_once_with()

    def test_login_fips_connects_via_verified_ssh_and_cleans_up(
        self, tmp_path
    ):
        self.mocker.patch.object(virsh, "is_fips_enabled").return_value = True
        trusted_keys = [
            {"key_type": "ecdsa-sha2-nistp256", "public_key": "AAAA"}
        ]
        self.mocker.patch.object(
            virsh, "get_trusted_ssh_host_keys"
        ).return_value = trusted_keys
        known_hosts_file = str(tmp_path / "known_hosts")
        Path(known_hosts_file).touch()
        mock_write_known_hosts = self.mocker.patch.object(
            virsh, "_write_known_hosts", return_value=known_hosts_file
        )
        mock_log = self.mocker.patch.object(virsh, "_log_fips_virsh_ssh_event")
        conn = self.configure_virshssh_pexpect(["virsh # "])
        poweraddr = "qemu+ssh://ubuntu@10.0.0.2/system"

        assert conn.login(poweraddr=poweraddr)

        new_poweraddr = poweraddr + "?command=/usr/lib/maas/verified-ssh"
        conn._execute.assert_called_once_with(new_poweraddr)
        mock_write_known_hosts.assert_called_once_with(
            "10.0.0.2", trusted_keys
        )
        assert conn.env["MAAS_KNOWN_HOSTS"] == known_hosts_file
        assert not os.path.exists(known_hosts_file)
        mock_log.assert_called_once_with(
            "10.0.0.2", "ecdsa-sha2-nistp256", "success"
        )

    def test_login_fips_uses_bracket_notation_for_custom_port(self, tmp_path):
        self.mocker.patch.object(virsh, "is_fips_enabled").return_value = True
        trusted_keys = [
            {"key_type": "ecdsa-sha2-nistp256", "public_key": "AAAA"}
        ]
        self.mocker.patch.object(
            virsh, "get_trusted_ssh_host_keys"
        ).return_value = trusted_keys
        known_hosts_file = str(tmp_path / "known_hosts")
        Path(known_hosts_file).touch()
        mock_write_known_hosts = self.mocker.patch.object(
            virsh, "_write_known_hosts"
        )
        self.mocker.patch.object(virsh, "_log_fips_virsh_ssh_event")
        conn = self.configure_virshssh_pexpect(["virsh # "])
        poweraddr = "qemu+ssh://ubuntu@10.0.0.2:2222/system"

        assert conn.login(poweraddr=poweraddr)

        mock_write_known_hosts.assert_called_once_with(
            "[10.0.0.2]:2222", trusted_keys
        )

    def test_login_fips_omits_bracket_notation_for_default_port(
        self, tmp_path
    ):
        self.mocker.patch.object(virsh, "is_fips_enabled").return_value = True
        trusted_keys = [
            {"key_type": "ecdsa-sha2-nistp256", "public_key": "AAAA"}
        ]
        self.mocker.patch.object(
            virsh, "get_trusted_ssh_host_keys"
        ).return_value = trusted_keys
        known_hosts_file = str(tmp_path / "known_hosts")
        Path(known_hosts_file).touch()
        mock_write_known_hosts = self.mocker.patch.object(
            virsh, "_write_known_hosts"
        )
        self.mocker.patch.object(virsh, "_log_fips_virsh_ssh_event")
        conn = self.configure_virshssh_pexpect(["virsh # "])
        poweraddr = "qemu+ssh://ubuntu@10.0.0.2:22/system"

        assert conn.login(poweraddr=poweraddr)

        mock_write_known_hosts.assert_called_once_with(
            "10.0.0.2", trusted_keys
        )

    def test_login_fips_fails_closed_without_trusted_key(self):
        self.mocker.patch.object(virsh, "is_fips_enabled").return_value = True
        self.mocker.patch.object(
            virsh, "get_trusted_ssh_host_keys"
        ).return_value = []
        conn = virsh.VirshSSH(timeout=0.1)
        self.request.addfinalizer(conn.close)
        mock_execute = self.mocker.patch.object(conn, "_execute")
        poweraddr = "qemu+ssh://ubuntu@10.0.0.2/system"
        conn._spawn("cat")

        with pytest.raises(virsh.VirshError):
            conn.login(poweraddr)
        mock_execute.assert_not_called()

    def test_login_fips_rejects_sshkey_prompt(self, tmp_path):
        self.mocker.patch.object(virsh, "is_fips_enabled").return_value = True
        trusted_keys = [
            {"key_type": "ecdsa-sha2-nistp256", "public_key": "AAAA"}
        ]
        self.mocker.patch.object(
            virsh, "get_trusted_ssh_host_keys"
        ).return_value = trusted_keys
        known_hosts_file = str(tmp_path / "known_hosts")
        Path(known_hosts_file).touch()
        self.mocker.patch.object(
            virsh, "_write_known_hosts"
        ).return_value = known_hosts_file
        mock_log = self.mocker.patch.object(virsh, "_log_fips_virsh_ssh_event")
        virsh_outputs = [
            "The authenticity of host '10.0.0.2' can't be established."
        ]
        conn = self.configure_virshssh_pexpect(virsh_outputs)
        poweraddr = "qemu+ssh://ubuntu@10.0.0.2/system"

        assert not conn.login(poweraddr=poweraddr)

        assert not os.path.exists(known_hosts_file)
        mock_log.assert_called_once_with(
            "10.0.0.2", "ecdsa-sha2-nistp256", "failed"
        )

    def test_login_non_fips_does_not_call_trusted_store(self):
        self.mocker.patch.object(virsh, "is_fips_enabled").return_value = False
        mock_get_keys = self.mocker.patch.object(
            virsh, "get_trusted_ssh_host_keys"
        )
        mock_log = self.mocker.patch.object(virsh, "_log_fips_virsh_ssh_event")
        conn = self.configure_virshssh_pexpect(["virsh # "])
        poweraddr = "qemu+ssh://ubuntu@10.0.0.2/system"

        assert conn.login(poweraddr=poweraddr)

        new_poweraddr = poweraddr + "?command=/usr/lib/maas/unverified-ssh"
        conn._execute.assert_called_once_with(new_poweraddr)
        mock_get_keys.assert_not_called()
        mock_log.assert_not_called()

    def test_logout(self):
        conn = self.configure_virshssh_pexpect()
        mock_sendline = self.mocker.patch.object(conn, "sendline")
        mock_close = self.mocker.patch.object(conn, "close")
        conn.logout()
        mock_sendline.assert_called_once_with("quit")
        mock_close.assert_called_once_with()

    def test_prompt(self):
        virsh_outputs = ["virsh # "]
        conn = self.configure_virshssh_pexpect(virsh_outputs)
        assert conn.prompt()

    def test_invalid_prompt(self):
        virsh_outputs = [factory.make_string()]
        conn = self.configure_virshssh_pexpect(virsh_outputs)
        assert not conn.prompt()

    def test_run(self):
        cmd = ["list", "--all", "--name"]
        expected = " ".join(cmd)
        names = [factory.make_name("machine") for _ in range(3)]
        conn = self.configure_virshssh_pexpect()
        conn.before = ("\n".join([expected] + names)).encode("utf-8")
        mock_sendline = self.mocker.patch.object(conn, "sendline")
        mock_prompt = self.mocker.patch.object(conn, "prompt")
        output = conn.run(cmd)
        mock_sendline.assert_called_once_with(expected)
        mock_prompt.assert_called_once_with()
        assert "\n".join(names) == output

    def test_run_error(self):
        cmd = ["list", "--all", "--name"]
        message = "something failed"
        conn = self.configure_virshssh_pexpect()
        conn.before = "\n".join([" ".join(cmd), f"error: {message}"]).encode(
            "utf-8"
        )
        self.mocker.patch.object(conn, "sendline")
        self.mocker.patch.object(conn, "prompt")
        mock_log = self.mocker.patch.object(virsh.maaslog, "error")
        with pytest.raises(virsh.VirshError) as exc_info:
            conn.run(cmd)
        error = exc_info.value
        expected_message = "Virsh command ['list', '--all', '--name'] failed: something failed"
        assert str(error) == expected_message
        mock_log.assert_called_once_with(expected_message)

    def test_get_machine_state(self):
        state = factory.make_name("state")
        conn = self.configure_virshssh(state)
        expected = conn.get_machine_state("")
        assert state == expected

    def test_get_machine_state_error(self):
        conn = self.configure_virshssh(virsh.VirshError("some error"))
        expected = conn.get_machine_state("")
        assert expected is None

    def test_poweron(self):
        conn = self.configure_virshssh("")
        expected = conn.poweron(factory.make_name("machine"))
        assert expected

    def test_poweron_error(self):
        conn = self.configure_virshssh(virsh.VirshError("some error"))
        expected = conn.poweron(factory.make_name("machine"))
        assert not expected

    def test_poweroff(self):
        conn = self.configure_virshssh("")
        expected = conn.poweroff(factory.make_name("machine"))
        assert expected

    def test_poweroff_error(self):
        conn = self.configure_virshssh(virsh.VirshError("some error"))
        expected = conn.poweroff(factory.make_name("machine"))
        assert not expected

    def test_resets_locale(self):
        """
        VirshSSH resets the locale to ensure we only ever get English strings.
        """
        c_utf8_environment = get_env_with_locale()
        mock_spawn = self.mocker.patch.object(pexpect.spawn, "__init__")
        self.configure_virshssh("")
        mock_spawn.assert_called_once_with(
            None, timeout=30, maxread=2000, env=c_utf8_environment
        )


@pytest.mark.rack_reactor_guard
class TestVirshPowerDriver:
    """Tests for the Virsh power driver."""

    @pytest.fixture(autouse=True)
    def _pytest_test_helpers(self, mocker):
        self.mocker = mocker

    def test_missing_packages(self, mocker):
        mock = mocker.patch.object(virsh.shell, "has_command_available")
        mock.return_value = False
        driver = virsh.VirshPowerDriver()
        assert ["libvirt-clients"] == driver.detect_missing_packages()

    def test_no_missing_packages(self, mocker):
        mock = mocker.patch.object(virsh.shell, "has_command_available")
        mock.return_value = True
        driver = virsh.VirshPowerDriver()
        assert [] == driver.detect_missing_packages()

    def test_chassis_for_bmc_deduplication(self):
        driver = virsh.VirshPowerDriver()
        assert driver.chassis
        assert driver.can_probe

    def make_context(self):
        return {
            "system_id": factory.make_name("system_id"),
            "power_address": factory.make_name("power_address"),
            "power_id": factory.make_name("power_id"),
            "power_pass": factory.make_name("power_pass"),
        }

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_on_calls_power_control_virsh(self):
        context = self.make_context()
        driver = VirshPowerDriver()
        power_control_virsh = self.mocker.patch.object(
            driver, "power_control_virsh"
        )
        yield driver.power_on(context["system_id"], context)
        power_control_virsh.assert_called_once_with(
            power_change="on", **context
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_off_calls_power_control_virsh(self):
        context = self.make_context()
        driver = VirshPowerDriver()
        power_control_virsh = self.mocker.patch.object(
            driver, "power_control_virsh"
        )
        yield driver.power_off(context["system_id"], context)
        power_control_virsh.assert_called_once_with(
            power_change="off", **context
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_query_calls_power_state_virsh(self):
        context = self.make_context()
        driver = VirshPowerDriver()
        power_state_virsh = self.mocker.patch.object(
            driver, "power_state_virsh"
        )
        power_state_virsh.return_value = "off"
        expected_result = yield driver.power_query(
            context["system_id"], context
        )
        power_state_virsh.assert_called_once_with(**context)
        assert expected_result == "off"

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_control_login_failure(self):
        driver = VirshPowerDriver()
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = False
        with pytest.raises(
            virsh.VirshError, match=r"^Failed to login to virsh console\.$"
        ):
            yield driver.power_control_virsh(
                factory.make_name("power_address"),
                factory.make_name("power_id"),
                factory.make_name("power_change"),
                power_pass=factory.make_string(),
            )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_control_on(self):
        driver = VirshPowerDriver()
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = True
        mock_state = self.mocker.patch.object(
            virsh.VirshSSH, "get_machine_state"
        )
        mock_state.return_value = virsh.VirshVMState.OFF
        mock_poweron = self.mocker.patch.object(virsh.VirshSSH, "poweron")

        power_address = factory.make_name("power_address")
        power_id = factory.make_name("power_id")
        yield driver.power_control_virsh(power_address, power_id, "on")

        mock_login.assert_called_once_with(power_address, None)
        mock_state.assert_called_once_with(power_id)
        mock_poweron.assert_called_once_with(power_id)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_control_off(self):
        driver = VirshPowerDriver()
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = True
        mock_state = self.mocker.patch.object(
            virsh.VirshSSH, "get_machine_state"
        )
        mock_state.return_value = virsh.VirshVMState.ON
        mock_poweroff = self.mocker.patch.object(virsh.VirshSSH, "poweroff")

        power_address = factory.make_name("power_address")
        power_id = factory.make_name("power_id")
        yield driver.power_control_virsh(power_address, power_id, "off")

        mock_login.assert_called_once_with(power_address, None)
        mock_state.assert_called_once_with(power_id)
        mock_poweroff.assert_called_once_with(power_id)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_control_bad_domain(self):
        driver = VirshPowerDriver()
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = True
        mock_state = self.mocker.patch.object(
            virsh.VirshSSH, "get_machine_state"
        )
        mock_state.return_value = None

        power_address = factory.make_name("power_address")
        power_id = factory.make_name("power_id")
        with pytest.raises(
            virsh.VirshError,
            match=rf"^{power_id}: Failed to get power state$",
        ):
            yield driver.power_control_virsh(power_address, power_id, "on")

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_control_power_failure(self):
        driver = VirshPowerDriver()
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = True
        mock_state = self.mocker.patch.object(
            virsh.VirshSSH, "get_machine_state"
        )
        mock_state.return_value = virsh.VirshVMState.ON
        mock_poweroff = self.mocker.patch.object(virsh.VirshSSH, "poweroff")
        mock_poweroff.return_value = False

        power_address = factory.make_name("power_address")
        power_id = factory.make_name("power_id")
        with pytest.raises(
            virsh.VirshError, match=rf"^{power_id}: Failed to power off VM$"
        ):
            yield driver.power_control_virsh(power_address, power_id, "off")

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_state_login_failure(self):
        driver = VirshPowerDriver()
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = False
        with pytest.raises(
            virsh.VirshError, match=r"^Failed to login to virsh console\.$"
        ):
            yield driver.power_state_virsh(
                factory.make_name("power_address"),
                factory.make_name("power_id"),
                power_pass=factory.make_string(),
            )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_state_get_on(self):
        driver = VirshPowerDriver()
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = True
        mock_state = self.mocker.patch.object(
            virsh.VirshSSH, "get_machine_state"
        )
        mock_state.return_value = virsh.VirshVMState.ON

        power_address = factory.make_name("power_address")
        power_id = factory.make_name("power_id")
        state = yield driver.power_state_virsh(power_address, power_id)
        assert "on" == state

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_state_get_off(self):
        driver = VirshPowerDriver()
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = True
        mock_state = self.mocker.patch.object(
            virsh.VirshSSH, "get_machine_state"
        )
        mock_state.return_value = virsh.VirshVMState.OFF

        power_address = factory.make_name("power_address")
        power_id = factory.make_name("power_id")
        state = yield driver.power_state_virsh(power_address, power_id)
        assert "off" == state

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_state_bad_domain(self):
        driver = VirshPowerDriver()
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = True
        mock_state = self.mocker.patch.object(
            virsh.VirshSSH, "get_machine_state"
        )
        mock_state.return_value = None

        power_address = factory.make_name("power_address")
        power_id = factory.make_name("power_id")
        with pytest.raises(
            virsh.VirshError, match=rf"^Failed to get domain: {power_id}$"
        ):
            yield driver.power_state_virsh(power_address, power_id)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_state_error_on_unknown_state(self):
        driver = VirshPowerDriver()
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = True
        mock_state = self.mocker.patch.object(
            virsh.VirshSSH, "get_machine_state"
        )
        mock_state.return_value = "unknown"

        power_address = factory.make_name("power_address")
        power_id = factory.make_name("power_id")
        with pytest.raises(
            virsh.VirshError, match=r"^Unknown state: unknown$"
        ):
            yield driver.power_state_virsh(power_address, power_id)
