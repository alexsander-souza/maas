# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the ``maas-rack config-hardening`` command."""

from contextlib import redirect_stdout
import io
from unittest.mock import patch

import pytest

from provisioningserver import hardening_command
from provisioningserver.config import ClusterConfiguration
from provisioningserver.testing.config import ClusterConfigurationFixture


class _Base:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker, request):
        _config_fixture = ClusterConfigurationFixture()
        _config_fixture.setUp()
        request.addfinalizer(_config_fixture.cleanUp)
        # `configure_hardening()` is process-global and latches after the
        # first call; each test patches it out and drives
        # `is_hardening_enabled()` directly instead.
        mocker.patch(
            "provisioningserver.hardening_command.configure_hardening"
        )

    @staticmethod
    def _capture(fn, *args):
        out = io.StringIO()
        code = 0
        with redirect_stdout(out):
            try:
                fn(*args)
            except SystemExit as exc:
                code = exc.code if exc.code is not None else 0
        return out.getvalue(), code


class TestCmdSetGetList(_Base):
    def test_set_and_get_scalar_key(self):
        hardening_command._cmd_set("rpc_bind", "10.0.0.5")
        with ClusterConfiguration.open() as config:
            assert config.rpc_bind == "10.0.0.5"

    def test_set_and_get_tftp_bind(self):
        hardening_command._cmd_set("tftp_bind", "10.0.0.5")
        with ClusterConfiguration.open() as config:
            assert config.tftp_bind == ["10.0.0.5"]

    def test_set_and_get_tftp_bind_multiple_addresses(self):
        hardening_command._cmd_set("tftp_bind", "10.0.0.5,fd00::5")
        with ClusterConfiguration.open() as config:
            assert config.tftp_bind == ["10.0.0.5", "fd00::5"]

    def test_set_and_get_list_key(self):
        hardening_command._cmd_set("api_bind", "10.0.0.5,10.0.0.6")
        with ClusterConfiguration.open() as config:
            assert config.api_bind == ["10.0.0.5", "10.0.0.6"]

    def test_set_hardening_enabled_rejects_invalid_value(self):
        with pytest.raises(SystemExit) as exc:
            hardening_command._cmd_set("hardening_enabled", "bogus")
        assert "hardening_enabled must be one of" in str(exc.value)

    def test_set_hardening_enabled_accepts_known_values(self):
        hardening_command._cmd_set("hardening_enabled", "ON")
        with ClusterConfiguration.open() as config:
            assert config.hardening_enabled == "on"

    def test_set_and_get_dns_bind(self):
        hardening_command._cmd_set("dns_bind", "10.0.0.5")
        with ClusterConfiguration.open() as config:
            assert config.dns_bind == ["10.0.0.5"]

    def test_list_includes_dns_bind(self):
        output, _ = self._capture(hardening_command._cmd_list)
        assert "dns_bind" in output


class TestCmdValidate(_Base):
    def test_inactive_hardening_reports_and_exits_zero(self):
        hardening_command._cmd_set("hardening_enabled", "off")
        with patch.object(
            hardening_command, "is_hardening_enabled", return_value=False
        ):
            output, code = self._capture(hardening_command._cmd_validate)
        assert "not active" in output
        assert code == 0

    def test_active_hardening_with_unset_binds_reports_violations(self):
        hardening_command._cmd_set("hardening_enabled", "on")
        with patch.object(
            hardening_command, "is_hardening_enabled", return_value=True
        ):
            output, code = self._capture(hardening_command._cmd_validate)
        assert "WILDCARD_BIND_NOT_ALLOWED" in output
        assert "rpc_bind" in output
        assert code == 1

    def test_active_hardening_with_invalid_address_reports_invalid_bind(self):
        hardening_command._cmd_set("hardening_enabled", "on")
        hardening_command._cmd_set("api_bind", "not-an-ip,fd00::5")
        hardening_command._cmd_set("rpc_bind", "10.0.0.5")
        hardening_command._cmd_set("syslog_bind", "10.0.0.5")
        hardening_command._cmd_set("http_proxy_bind", "10.0.0.5,fd00::5")
        hardening_command._cmd_set("dns_bind", "10.0.0.5,fd00::5")
        with patch.object(
            hardening_command, "is_hardening_enabled", return_value=True
        ):
            output, code = self._capture(hardening_command._cmd_validate)
        assert "INVALID_BIND_ADDRESS" in output
        assert "api_bind" in output
        assert code == 1

    def test_all_binds_set_reports_ok(self):
        hardening_command._cmd_set("hardening_enabled", "on")
        for key, value in (
            ("api_bind", "10.0.0.5,fd00::5"),
            ("rpc_bind", "10.0.0.5"),
            ("tftp_bind", "10.0.0.5"),
            ("syslog_bind", "10.0.0.5"),
            ("http_proxy_bind", "10.0.0.5,fd00::5"),
            ("dns_bind", "10.0.0.5,fd00::5"),
        ):
            hardening_command._cmd_set(key, value)
        with patch.object(
            hardening_command, "is_hardening_enabled", return_value=True
        ):
            output, code = self._capture(hardening_command._cmd_validate)
        assert "OK" in output
        assert code == 0

    def test_multi_subnet_tftp_bind_reports_ok(self):
        hardening_command._cmd_set("hardening_enabled", "on")
        for key, value in (
            ("api_bind", "10.0.0.5,fd00::5"),
            ("rpc_bind", "10.0.0.5"),
            ("tftp_bind", "10.0.0.5,10.0.1.5,fd00::5"),
            ("syslog_bind", "10.0.0.5"),
            ("http_proxy_bind", "10.0.0.5,fd00::5"),
            ("dns_bind", "10.0.0.5,fd00::5"),
        ):
            hardening_command._cmd_set(key, value)
        with patch.object(
            hardening_command, "is_hardening_enabled", return_value=True
        ):
            output, code = self._capture(hardening_command._cmd_validate)
        assert "OK" in output
        assert code == 0
