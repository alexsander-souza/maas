# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
"""Tests for the config-hardening management command."""

from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from maasserver.management.commands.base import BaseCommandWithConnection
from maasserver.management.commands.config_hardening import Command


def _cmd(**kw):
    cmd = Command(stdout=StringIO(), stderr=StringIO())
    cmd.handle(**kw)
    return cmd


class TestConfigHardeningSet:
    def test_set_config_key_writes_to_db(self):
        with patch("maasserver.models.Config") as MockConfig:
            mock_mgr = MagicMock()
            MockConfig.objects.db_manager.return_value = mock_mgr
            _cmd(command="set", key="hardening_enabled", value="on")
        mock_mgr.set_config.assert_called_once_with("hardening_enabled", "on")

    def test_set_conf_key_writes_to_regiond_conf(self):
        with patch(
            "maasserver.management.commands.config_hardening.RegionConfiguration"
        ) as MockRegionCfg:
            mock_cfg = MagicMock()
            MockRegionCfg.open_for_update.return_value.__enter__ = MagicMock(
                return_value=mock_cfg
            )
            MockRegionCfg.open_for_update.return_value.__exit__ = MagicMock(
                return_value=False
            )
            cmd = _cmd(command="set", key="database_sslmode", value="prefer")
        assert mock_cfg.database_sslmode == "prefer"
        assert "database_sslmode" in cmd.stdout.getvalue()

    def test_set_conf_key_works_without_db(self):
        with (
            patch(
                "maasserver.utils.orm.with_connection",
                side_effect=Exception("DB connection refused"),
            ),
            patch(
                "maasserver.management.commands.config_hardening.RegionConfiguration"
            ) as MockRegionCfg,
        ):
            mock_cfg = MagicMock()
            MockRegionCfg.open_for_update.return_value.__enter__ = MagicMock(
                return_value=mock_cfg
            )
            MockRegionCfg.open_for_update.return_value.__exit__ = MagicMock(
                return_value=False
            )
            cmd = Command(stdout=StringIO(), stderr=StringIO())
            cmd.execute(command="set", key="database_sslmode", value="prefer")
        assert "database_sslmode" in cmd.stdout.getvalue()

    def test_set_config_key_requires_db_connection(self):
        with patch.object(
            BaseCommandWithConnection, "execute", autospec=True
        ) as mock_execute:
            mock_execute.return_value = None
            cmd = Command(stdout=StringIO(), stderr=StringIO())
            cmd.execute(command="set", key="hardening_enabled", value="on")
        mock_execute.assert_called_once()

    def test_set_unknown_key_exits_with_error(self):
        with pytest.raises(SystemExit) as ctx:
            _cmd(command="set", key="nonexistent_key", value="val")
        assert ctx.value.code == 1

    def test_set_fips_enabled_refused(self):
        with pytest.raises(SystemExit) as ctx:
            _cmd(command="set", key="fips_enabled", value="true")
        assert ctx.value.code == 1


class TestConfigHardeningDnsBind:
    def test_set_dns_bind_writes_to_regiond_conf(self):
        with patch(
            "maasserver.management.commands.config_hardening.RegionConfiguration"
        ) as MockRegionCfg:
            mock_cfg = MagicMock()
            MockRegionCfg.open_for_update.return_value.__enter__ = MagicMock(
                return_value=mock_cfg
            )
            MockRegionCfg.open_for_update.return_value.__exit__ = MagicMock(
                return_value=False
            )
            _cmd(command="set", key="dns_bind", value="10.0.0.1")
        assert mock_cfg.dns_bind == ["10.0.0.1"]

    def test_list_includes_dns_bind(self):
        with (
            patch(
                "maasserver.management.commands.config_hardening.RegionConfiguration"
            ) as MockRegionCfg,
            patch(
                "maasserver.certificates.get_maas_certificate",
                return_value=None,
            ),
            patch("maasserver.models.Config") as MockConfig,
        ):
            mock_cfg = MagicMock()
            MockRegionCfg.open.return_value.__enter__ = MagicMock(
                return_value=mock_cfg
            )
            MockRegionCfg.open.return_value.__exit__ = MagicMock(
                return_value=False
            )
            MockConfig.objects.db_manager.return_value.get_config.return_value = None
            cmd = _cmd(command="list")
        assert "dns_bind " in cmd.stdout.getvalue()


class TestConfigHardeningGet:
    def test_get_conf_key_reads_from_regiond_conf(self):
        with patch(
            "maasserver.management.commands.config_hardening.RegionConfiguration"
        ) as MockRegionCfg:
            mock_cfg = MagicMock()
            mock_cfg.api_bind = ["10.0.0.1"]
            mock_cfg.api_tls_dhparam = ""
            mock_cfg.prometheus_bind = "127.0.0.1"
            mock_cfg.temporal_bind = "127.0.0.1"
            mock_cfg.rpc_bind = ["127.0.0.1"]
            mock_cfg.dns_bind = []
            mock_cfg.database_sslmode = "prefer"
            mock_cfg.database_sslcert = ""
            mock_cfg.database_sslkey = ""
            mock_cfg.database_sslrootcert = ""
            MockRegionCfg.open.return_value.__enter__ = MagicMock(
                return_value=mock_cfg
            )
            MockRegionCfg.open.return_value.__exit__ = MagicMock(
                return_value=False
            )
            cmd = _cmd(command="get", key="api_bind")
        assert "10.0.0.1" in cmd.stdout.getvalue()

    def test_get_conf_key_works_without_db(self):
        with (
            patch(
                "maasserver.utils.orm.with_connection",
                side_effect=Exception("DB connection refused"),
            ),
            patch(
                "maasserver.management.commands.config_hardening.RegionConfiguration"
            ) as MockRegionCfg,
        ):
            mock_cfg = MagicMock()
            mock_cfg.prometheus_bind = "127.0.0.1"
            mock_cfg.api_bind = []
            mock_cfg.api_tls_dhparam = ""
            mock_cfg.temporal_bind = ""
            mock_cfg.rpc_bind = []
            mock_cfg.dns_bind = []
            mock_cfg.database_sslmode = ""
            mock_cfg.database_sslcert = ""
            mock_cfg.database_sslkey = ""
            mock_cfg.database_sslrootcert = ""
            MockRegionCfg.open.return_value.__enter__ = MagicMock(
                return_value=mock_cfg
            )
            MockRegionCfg.open.return_value.__exit__ = MagicMock(
                return_value=False
            )
            cmd = Command(stdout=StringIO(), stderr=StringIO())
            cmd.execute(command="get", key="prometheus_bind")
        assert "127.0.0.1" in cmd.stdout.getvalue()

    def test_get_config_key_requires_db_connection(self):
        with patch.object(
            BaseCommandWithConnection, "execute", autospec=True
        ) as mock_execute:
            mock_execute.return_value = None
            cmd = Command(stdout=StringIO(), stderr=StringIO())
            cmd.execute(command="get", key="hardening_enabled")
        mock_execute.assert_called_once()


class TestConfigHardeningValidate:
    @staticmethod
    def _mock_cfg():
        return MagicMock(
            api_tls_dhparam="",
            api_bind=[],
            api_int_bind=[],
            prometheus_bind="",
            temporal_bind="",
            rpc_bind=[],
            rack_ctrl_api_bind=[],
            dns_bind=[],
            syslog_bind=[],
            http_proxy_bind=[],
            database_sslmode="",
        )

    def _run_validate(self, violations, hardening_active=True):
        with (
            patch(
                "maasserver.models.config.read_hardening_enabled_from_db",
                return_value=None,
            ),
            patch(
                "maasserver.management.commands.config_hardening.configure_hardening"
            ),
            patch(
                "maasserver.certificates.get_maas_certificate",
                return_value=None,
            ),
            patch.object(Command, "_read_fips_declared", return_value=None),
            patch(
                "maasserver.management.commands.config_hardening"
                ".is_hardening_enabled",
                return_value=hardening_active,
            ),
            patch(
                "maasserver.management.commands.config_hardening"
                ".configure_and_validate_hardening",
                return_value=violations,
            ),
            patch(
                "maasserver.management.commands.config_hardening.RegionConfiguration"
            ) as MockCfg,
        ):
            MockCfg.open.return_value.__enter__ = MagicMock(
                return_value=self._mock_cfg()
            )
            MockCfg.open.return_value.__exit__ = MagicMock(return_value=False)
            return _cmd(command="validate")

    def test_no_violations_exits_zero(self):
        cmd = self._run_validate([])
        assert "OK" in cmd.stdout.getvalue()

    def test_violations_exit_nonzero(self):
        from maasservicelayer.services.hardening import (
            _ident,
            HardeningViolation,
        )

        v = HardeningViolation(
            ident=_ident("MISSING_TLS_CERT"),
            code="MISSING_TLS_CERT",
            message="cert missing",
            resolution="fix it",
            config_key="api_tls_cert",
        )
        with pytest.raises(SystemExit) as ctx:
            self._run_validate([v])
        assert ctx.value.code == 1

    def test_hardening_inactive_skips_checks(self):
        cmd = self._run_validate([], hardening_active=False)
        assert "not active" in cmd.stdout.getvalue()

    def test_fips_host_enables_hardening_automatically(self):
        """On a FIPS host with hardening_enabled=auto, validate must run checks."""
        import maascommon.hardening as _h

        with (
            patch(
                "maasserver.models.config.read_hardening_enabled_from_db",
                return_value=None,
            ),
            patch(
                "maasserver.certificates.get_maas_certificate",
                return_value=None,
            ),
            patch.object(Command, "_read_fips_declared", return_value=None),
            patch("maascommon.hardening.is_fips_enabled", return_value=True),
            patch(
                "maasserver.management.commands.config_hardening"
                ".configure_and_validate_hardening",
                return_value=[],
            ),
            patch(
                "maasserver.management.commands.config_hardening.RegionConfiguration"
            ) as MockCfg,
        ):
            orig = (_h._hardening_active, _h._hardening_configured)
            _h._hardening_active = False
            _h._hardening_configured = False
            try:
                MockCfg.open.return_value.__enter__ = MagicMock(
                    return_value=self._mock_cfg()
                )
                MockCfg.open.return_value.__exit__ = MagicMock(
                    return_value=False
                )
                cmd = _cmd(command="validate")
                assert "not active" not in cmd.stdout.getvalue()
            finally:
                _h._hardening_active, _h._hardening_configured = orig


class TestConfigHardeningDisable:
    def test_refused_on_fips_host(self):
        with patch(
            "maasserver.management.commands.config_hardening.is_fips_enabled",
            return_value=True,
        ):
            cmd = Command(stdout=StringIO(), stderr=StringIO())
            with pytest.raises(SystemExit) as ctx:
                cmd.handle(command="disable")
        assert ctx.value.code == 1
        assert "FIPS" in cmd.stderr.getvalue()

    def test_sets_config_on_non_fips(self):
        with (
            patch(
                "maasserver.management.commands.config_hardening.is_fips_enabled",
                return_value=False,
            ),
            patch("maasserver.models.Config") as MockConfig,
        ):
            mock_mgr = MagicMock()
            MockConfig.objects.db_manager.return_value = mock_mgr
            _cmd(command="disable")
        mock_mgr.set_config.assert_called_once_with("hardening_enabled", "off")


class TestConfigHardeningEnable:
    def test_sets_hardening_enabled_in_db(self):
        with patch("maasserver.models.Config") as MockConfig:
            mock_mgr = MagicMock()
            MockConfig.objects.db_manager.return_value = mock_mgr
            cmd = _cmd(command="enable")

        mock_mgr.set_config.assert_called_once_with("hardening_enabled", "on")
        assert "Hardening enabled" in cmd.stdout.getvalue()

    def test_enable_does_not_touch_regiond_conf(self):
        # `enable` is a pure DB operation; it must never open regiond.conf
        # (it used to seed a prometheus_bind loopback default there).
        with (
            patch("maasserver.models.Config"),
            patch(
                "maasserver.management.commands.config_hardening.RegionConfiguration"
            ) as MockRegionCfg,
        ):
            _cmd(command="enable")

        MockRegionCfg.open_for_update.assert_not_called()
        MockRegionCfg.open.assert_not_called()


class TestConfigHardeningListEffectiveBinds:
    @staticmethod
    def _mock_cfg(**overrides):
        defaults = dict(
            api_tls_dhparam="",
            api_bind=[],
            api_int_bind=[],
            prometheus_bind="",
            temporal_bind="",
            rpc_bind=[],
            rack_ctrl_api_bind=[],
            dns_bind=[],
            syslog_bind=[],
            http_proxy_bind=[],
            database_sslmode="prefer",
            database_sslcert="",
            database_sslkey="",
            database_sslrootcert="",
            maas_url="http://10.0.0.9:5240/MAAS",
        )
        defaults.update(overrides)
        return MagicMock(**defaults)

    def _run_list(self, mock_cfg, hardening_active):
        with (
            patch(
                "maasserver.management.commands.config_hardening"
                ".is_hardening_enabled",
                return_value=hardening_active,
            ),
            patch(
                "maasserver.management.commands.config_hardening.RegionConfiguration"
            ) as MockRegionCfg,
            patch(
                "maasserver.certificates.get_maas_certificate",
                return_value=None,
            ),
            patch("maasserver.models.Config") as MockConfig,
        ):
            MockRegionCfg.open.return_value.__enter__ = MagicMock(
                return_value=mock_cfg
            )
            MockRegionCfg.open.return_value.__exit__ = MagicMock(
                return_value=False
            )
            MockConfig.objects.db_manager.return_value.get_config.return_value = None
            cmd = _cmd(command="list")
        return cmd.stdout.getvalue()

    @staticmethod
    def _line_for(output, key):
        for line in output.splitlines():
            if line.split()[0] == key:
                return line
        raise AssertionError(f"no '{key}' line in output:\n{output}")

    def test_hardening_gated_binds_not_effective_when_hardening_inactive(
        self,
    ):
        # rpc_bind derives from maas_url regardless of hardening (see
        # `resolve_rpc_bind_addresses`), so it is checked separately via
        # `test_rpc_bind_shows_effective_value_regardless_of_hardening`.
        import provisioningserver.utils.network as network_module

        with patch.object(
            network_module,
            "get_source_address_for_url",
            return_value="10.0.0.9",
        ):
            output = self._run_list(self._mock_cfg(), hardening_active=False)
        for key in (
            "api_bind",
            "rack_ctrl_api_bind",
            "http_proxy_bind",
            "syslog_bind",
            "temporal_bind",
        ):
            assert "effective" not in self._line_for(output, key)

    def test_temporal_bind_shows_effective_value_under_hardening(self):
        import provisioningserver.utils.network as network_module

        with patch.object(
            network_module,
            "get_source_address_for_url",
            return_value="10.0.0.9",
        ):
            output = self._run_list(self._mock_cfg(), hardening_active=True)
        assert "(effective: 10.0.0.9)" in self._line_for(
            output, "temporal_bind"
        )

    def test_api_bind_shows_effective_value_under_hardening(self):
        import socket

        import provisioningserver.utils.network as network_module

        def fake_source(url, family=None):
            return "10.0.0.9" if family == socket.AF_INET else "fd00::9"

        with patch.object(
            network_module,
            "get_source_address_for_url",
            side_effect=fake_source,
        ):
            output = self._run_list(self._mock_cfg(), hardening_active=True)
        assert "(effective: 10.0.0.9,fd00::9)" in self._line_for(
            output, "api_bind"
        )

    def test_explicit_bind_not_annotated_as_effective(self):
        import provisioningserver.utils.network as network_module

        with patch.object(
            network_module,
            "get_source_address_for_url",
            return_value="10.0.0.9",
        ):
            output = self._run_list(
                self._mock_cfg(api_bind=["10.0.0.5"]), hardening_active=True
            )
        assert "effective" not in self._line_for(output, "api_bind")

    def test_rpc_bind_shows_effective_value_regardless_of_hardening(self):
        with patch(
            "maasserver.eventloop.resolve_rpc_bind_addresses",
            return_value=["10.0.0.9"],
        ):
            output = self._run_list(self._mock_cfg(), hardening_active=False)
        assert "(effective: 10.0.0.9)" in self._line_for(output, "rpc_bind")

    def test_prometheus_bind_shows_loopback_effective_under_hardening(self):
        output = self._run_list(self._mock_cfg(), hardening_active=True)
        assert "(effective: 127.0.0.1)" in self._line_for(
            output, "prometheus_bind"
        )

    def test_prometheus_bind_no_effective_value_outside_hardening(self):
        output = self._run_list(self._mock_cfg(), hardening_active=False)
        assert "effective" not in self._line_for(output, "prometheus_bind")
