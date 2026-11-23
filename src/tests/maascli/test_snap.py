# Copyright 2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import io
import os
import sys
from unittest.mock import MagicMock

import netifaces
import pytest

from maascli import snap
from maascli.command import CommandError
from maascli.parser import ArgumentParser
import maasserver.vault
from maasserver.vault import VaultError
from maastesting.factory import factory


class TestHelpers:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        snap_common = tmp_path / "common"
        snap_common.mkdir(exist_ok=True)
        snap_data = tmp_path / "data"
        snap_data.mkdir(exist_ok=True)
        self.environ = {
            "SNAP_COMMON": str(snap_common),
            "SNAP_DATA": str(snap_data),
        }
        monkeypatch.setattr(os, "environ", self.environ)

    def test_get_default_gateway_ip_no_defaults(self, mocker):
        mocker.patch.object(netifaces, "gateways").return_value = {}
        assert snap.get_default_gateway_ip() is None

    def test_get_default_gateway_ip_returns_ipv4(self, mocker):
        gw_address = factory.make_ipv4_address()
        ipv4_address = factory.make_ipv4_address()
        iface_name = factory.make_name("eth")
        mocker.patch.object(netifaces, "gateways").return_value = {
            "default": {netifaces.AF_INET: (gw_address, iface_name)}
        }
        mocker.patch.object(netifaces, "ifaddresses").return_value = {
            netifaces.AF_INET: [{"addr": ipv4_address}]
        }
        assert ipv4_address == snap.get_default_gateway_ip()

    def test_get_default_gateway_ip_returns_ipv6(self, mocker):
        gw_address = factory.make_ipv6_address()
        ipv6_address = factory.make_ipv6_address()
        iface_name = factory.make_name("eth")
        mocker.patch.object(netifaces, "gateways").return_value = {
            "default": {netifaces.AF_INET6: (gw_address, iface_name)}
        }
        mocker.patch.object(netifaces, "ifaddresses").return_value = {
            netifaces.AF_INET6: [{"addr": ipv6_address}]
        }
        assert ipv6_address == snap.get_default_gateway_ip()

    def test_get_default_gateway_ip_returns_ipv4_over_ipv6(self, mocker):
        gw4_address = factory.make_ipv4_address()
        gw6_address = factory.make_ipv6_address()
        ipv4_address = factory.make_ipv4_address()
        ipv6_address = factory.make_ipv6_address()
        iface = factory.make_name("eth")
        mocker.patch.object(netifaces, "gateways").return_value = {
            "default": {
                netifaces.AF_INET: (gw4_address, iface),
                netifaces.AF_INET6: (gw6_address, iface),
            }
        }
        mocker.patch.object(netifaces, "ifaddresses").return_value = {
            netifaces.AF_INET: [{"addr": ipv4_address}],
            netifaces.AF_INET6: [{"addr": ipv6_address}],
        }
        assert ipv4_address == snap.get_default_gateway_ip()

    def test_get_default_gateway_ip_returns_first_ip(self, mocker):
        gw_address = factory.make_ipv4_address()
        ipv4_address1 = factory.make_ipv4_address()
        ipv4_address2 = factory.make_ipv4_address()
        iface = factory.make_name("eth")
        mocker.patch.object(netifaces, "gateways").return_value = {
            "default": {netifaces.AF_INET: (gw_address, iface)}
        }
        mocker.patch.object(netifaces, "ifaddresses").return_value = {
            netifaces.AF_INET: [
                {"addr": ipv4_address1},
                {"addr": ipv4_address2},
            ]
        }
        assert ipv4_address1 == snap.get_default_gateway_ip()

    def test_get_default_url_uses_gateway_ip(self, mocker):
        ipv4_address = factory.make_ipv4_address()
        mocker.patch.object(
            snap, "get_default_gateway_ip"
        ).return_value = ipv4_address
        assert "http://%s:5240/MAAS" % ipv4_address == snap.get_default_url()

    def test_get_default_url_fallsback_to_localhost(self, mocker):
        mocker.patch.object(snap, "get_default_gateway_ip").return_value = None
        assert "http://localhost:5240/MAAS" == snap.get_default_url()

    def test_get_mode_filepath(self):
        assert (
            os.path.join(self.environ["SNAP_COMMON"], "snap_mode")
            == snap.get_mode_filepath()
        )

    def test_get_current_mode_returns_none_when_missing(self):
        assert "none" == snap.get_current_mode()

    def test_get_current_mode_returns_file_contents(self):
        snap.set_current_mode("all")
        assert "all" == snap.get_current_mode()

    def test_set_current_mode_creates_file(self):
        snap.set_current_mode("all")
        assert os.path.exists(snap.get_mode_filepath())

    def test_set_current_mode_overwrites(self):
        snap.set_current_mode("all")
        snap.set_current_mode("none")
        assert "none" == snap.get_current_mode()


class TestConfigHelpers:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        maas_data = tmp_path / "maas_data"
        maas_data.mkdir(exist_ok=True)
        self.secret_file = maas_data / "secret"
        monkeypatch.setenv("MAAS_DATA", str(maas_data))

    def test_print_config_value(self, mocker):
        mock_print = mocker.patch.object(snap, "print_msg")
        key = factory.make_name("key")
        value = factory.make_name("value")
        config = {key: value}
        snap.print_config_value(config, key)
        mock_print.assert_called_once_with(f"{key}={value}")

    def test_print_config_value_hidden(self, mocker):
        mock_print = mocker.patch.object(snap, "print_msg")
        key = factory.make_name("key")
        value = factory.make_name("value")
        config = {key: value}
        snap.print_config_value(config, key, hidden=True)
        mock_print.assert_called_once_with(f"{key}=(hidden)")

    def test_get_rpc_secret_returns_secret(self):
        secret = factory.make_string()
        self.secret_file.write_text(secret)
        assert snap.get_rpc_secret() == secret

    def test_get_rpc_secret_returns_None_when_no_file(self):
        assert snap.get_rpc_secret() is None

    def test_get_rpc_secret_returns_None_when_empty_file(self):
        self.secret_file.write_text("")
        assert snap.get_rpc_secret() is None

    def test_set_rpc_secret_sets_secret(self):
        secret = factory.make_string()
        snap.set_rpc_secret(secret)
        assert secret == snap.get_rpc_secret()

    def test_set_rpc_secret_clears_secret(self):
        secret = factory.make_string()
        snap.set_rpc_secret(secret)
        snap.set_rpc_secret(None)
        assert snap.get_rpc_secret() is None
        assert not self.secret_file.exists()


class TestCmdInit:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, mocker):
        self.parser = ArgumentParser()
        self.cmd = snap.cmd_init(self.parser)
        mocker.patch.object(os, "getuid").return_value = 0
        snap_common_path = tmp_path / "snap_common"
        snap_common_path.mkdir(exist_ok=True)
        self.snap_common = str(snap_common_path)
        mocker.patch.object(
            os,
            "environ",
            {
                "SNAP": "/snap/maas",
                "SNAP_COMMON": self.snap_common,
                "SNAP_DATA": "/snap/maas/data",
            },
        )
        self.mock_read_input = mocker.patch.object(snap, "read_input")

    def test_init_snap_db_options_prompt(self, mocker):
        self.mock_maas_configuration = mocker.patch.object(
            snap, "MAASConfiguration"
        )
        mocker.patch.object(snap, "set_rpc_secret")
        mocker.patch.object(snap.cmd_init, "_finalize_init")

        self.mock_read_input.side_effect = [
            "postgres://maas:pwd@localhost/db",
            "http://localhost:5240/MAAS",
        ]
        options = self.parser.parse_args(["region+rack"])
        self.cmd(options)
        self.mock_maas_configuration().update.assert_called_once_with(
            {
                "maas_url": "http://localhost:5240/MAAS",
                "database_host": "localhost",
                "database_name": "db",
                "database_user": "maas",
                "database_pass": "pwd",
                "database_sslmode": "prefer",
                "database_sslcert": "",
                "database_sslkey": "",
                "database_sslrootcert": "",
            }
        )

    def test_init_snap_clears_certificates_dir(self, mocker):
        self.mock_maas_configuration = mocker.patch.object(
            snap, "MAASConfiguration"
        )
        mocker.patch.object(snap, "set_rpc_secret")
        mocker.patch.object(snap.cmd_init, "_finalize_init")

        self.mock_read_input.side_effect = [
            "postgres://maas:pwd@localhost/db",
            "http://localhost:5240/MAAS",
        ]
        self.mock_clear_certificates_dir = mocker.patch.object(
            snap, "clear_certificates_dir"
        )
        options = self.parser.parse_args(["region+rack"])
        self.cmd(options)
        self.mock_clear_certificates_dir.assert_called_once()

    def test_init_db_parse_error(self, mocker):
        mocker.patch.object(snap, "print_msg")
        self.mock_maas_configuration = mocker.patch.object(
            snap, "MAASConfiguration"
        )
        mocker.patch.object(snap, "set_rpc_secret")
        mocker.patch.object(snap.cmd_init, "_finalize_init")

        self.mock_read_input.side_effect = [
            "localhost",
            "db",
            "maas",
            "pwd",
            "http://localhost:5240/MAAS",
        ]
        options = self.parser.parse_args(
            ["region+rack", "--database-uri", "invalid"]
        )
        with pytest.raises(CommandError) as exc_info:
            self.cmd(options)
        assert (
            str(exc_info.value)
            == "Database URI needs to be either 'maas-test-db:///' or start "
            "with 'postgres://'"
        )
        self.mock_maas_configuration().update.assert_not_called()

    def test_get_database_settings_no_prompt_dsn(self):
        options = self.parser.parse_args(
            [
                "region+rack",
                "--database-uri",
                "postgres://dbuser:pwd@dbhost/dbname",
            ]
        )
        settings = snap.get_database_settings(options)
        assert settings == {
            "database_host": "dbhost",
            "database_name": "dbname",
            "database_user": "dbuser",
            "database_pass": "pwd",
            "database_sslmode": "prefer",
            "database_sslcert": "",
            "database_sslkey": "",
            "database_sslrootcert": "",
        }

    def test_get_database_settings_prompt_dsn(self):
        self.mock_read_input.side_effect = [
            "postgres://dbuser:pwd@dbhost/dbname"
        ]
        options = self.parser.parse_args(["region+rack"])
        settings = snap.get_database_settings(options)
        assert settings == {
            "database_host": "dbhost",
            "database_name": "dbname",
            "database_user": "dbuser",
            "database_pass": "pwd",
            "database_sslmode": "prefer",
            "database_sslcert": "",
            "database_sslkey": "",
            "database_sslrootcert": "",
        }

    def test_get_database_settings_maas_test_db_prompt_default(self):
        options = self.parser.parse_args(["region+rack"])
        os.mkdir(os.path.join(self.snap_common, "test-db-socket"))
        self.mock_read_input.side_effect = [""]
        settings = snap.get_database_settings(options)
        assert settings == {
            "database_host": f"{self.snap_common}/test-db-socket",
            "database_name": "maasdb",
            "database_user": "maas",
            "database_pass": None,
            "database_sslmode": "prefer",
            "database_sslcert": "",
            "database_sslkey": "",
            "database_sslrootcert": "",
        }

    def test_get_database_settings_maas_test_db_prompt_no_default(self):
        options = self.parser.parse_args(["region+rack"])
        self.mock_read_input.side_effect = ["", "postgres:///?user=foo"]
        settings = snap.get_database_settings(options)
        assert settings == {
            "database_host": "localhost",
            "database_name": "foo",
            "database_user": "foo",
            "database_pass": None,
            "database_sslmode": "prefer",
            "database_sslcert": "",
            "database_sslkey": "",
            "database_sslrootcert": "",
        }

    def test_get_database_settings_maas_test_db(self):
        options = self.parser.parse_args(
            ["region+rack", "--database-uri", "maas-test-db:///"]
        )
        settings = snap.get_database_settings(options)
        assert settings == {
            "database_host": f"{self.snap_common}/test-db-socket",
            "database_name": "maasdb",
            "database_user": "maas",
            "database_pass": None,
            "database_sslmode": "prefer",
            "database_sslcert": "",
            "database_sslkey": "",
            "database_sslrootcert": "",
        }

    def test_get_database_settings_minimal_postgres(self):
        options = self.parser.parse_args(
            ["region+rack", "--database-uri", "postgres:///?user=myuser"]
        )
        settings = snap.get_database_settings(options)
        assert settings == {
            "database_host": "localhost",
            "database_name": "myuser",
            "database_user": "myuser",
            "database_pass": None,
            "database_sslmode": "prefer",
            "database_sslcert": "",
            "database_sslkey": "",
            "database_sslrootcert": "",
        }

    def test_get_database_settings_full_postgres(self):
        options = self.parser.parse_args(
            [
                "region+rack",
                "--database-uri",
                "postgres://myuser:pwd@myhost:1234/mydb",
            ]
        )
        settings = snap.get_database_settings(options)
        assert settings == {
            "database_host": "myhost",
            "database_name": "mydb",
            "database_user": "myuser",
            "database_pass": "pwd",
            "database_sslmode": "prefer",
            "database_sslcert": "",
            "database_sslkey": "",
            "database_sslrootcert": "",
            "database_port": 1234,
        }

    def test_get_database_settings_invalid_parameters(self):
        options = self.parser.parse_args(
            [
                "region+rack",
                "--database-uri",
                "postgres://myuser:pwd@myhost:1234/mydb?foo=bar",
            ]
        )
        with pytest.raises(snap.DatabaseSettingsError) as exc_info:
            snap.get_database_settings(options)
        assert str(exc_info.value) == (
            "Error parsing database URI: "
            'invalid dsn: invalid URI query parameter: "foo"'
        )

    def test_get_database_settings_unsupported_parameters(self):
        options = self.parser.parse_args(
            [
                "region+rack",
                "--database-uri",
                "postgres://myuser:pwd@myhost/?passfile=foo&options=bar",
            ]
        )
        with pytest.raises(snap.DatabaseSettingsError) as exc_info:
            snap.get_database_settings(options)
        assert str(exc_info.value) == (
            "Error parsing database URI: "
            "Unsupported parameters: options, passfile"
        )

    def test_get_database_settings_missing_user(self):
        options = self.parser.parse_args(
            ["region+rack", "--database-uri", "postgres://myhost/"]
        )
        with pytest.raises(snap.DatabaseSettingsError) as exc_info:
            snap.get_database_settings(options)
        assert (
            str(exc_info.value) == "No user found in URI: postgres://myhost/"
        )

    def test_get_database_settings_invalid_maas_test_db(self):
        options = self.parser.parse_args(
            ["region+rack", "--database-uri", "maas-test-db:///foo"]
        )
        with pytest.raises(snap.DatabaseSettingsError) as exc_info:
            snap.get_database_settings(options)
        assert (
            str(exc_info.value)
            == "Database URI needs to be either 'maas-test-db:///' or start with "
            "'postgres://'"
        )

    def test_get_database_settings_incomplete_postgres_uri(self):
        # The URI needs to start with at least postgres:// before we
        # even try to parse it.
        options = self.parser.parse_args(
            ["region+rack", "--database-uri", "postgres:/"]
        )
        with pytest.raises(snap.DatabaseSettingsError) as exc_info:
            snap.get_database_settings(options)
        assert (
            str(exc_info.value)
            == "Database URI needs to be either 'maas-test-db:///' or start with "
            "'postgres://'"
        )

    def test_get_vault_settings_returns_empty_dict_with_no_vault_uri(self):
        options = self.parser.parse_args(
            ["region+rack", "--database-uri", "maas-test-db:///"]
        )
        assert snap.get_vault_settings(options) == {}

    def test_get_vault_settings_requires_args_when_vault_uri_provided(self):
        options = self.parser.parse_args(
            [
                "region+rack",
                "--database-uri",
                "maas-test-db:///",
                "--vault-uri",
                "http://vault:8200",
            ]
        )
        with pytest.raises(CommandError):
            snap.get_vault_settings(options)

    def test_get_vault_settings_returns_default_mount_when_not_specified(
        self, mocker
    ):
        url = "http://vault:8200"
        approle_id = factory.make_name("uuid")
        wrapped_token = factory.make_name("uuid")
        secret_id = factory.make_name("uuid")
        secrets_path = "path"
        options = self.parser.parse_args(
            [
                "region+rack",
                "--database-uri",
                "maas-test-db:///",
                "--vault-uri",
                url,
                "--vault-approle-id",
                approle_id,
                "--vault-wrapped-token",
                wrapped_token,
                "--vault-secrets-path",
                secrets_path,
            ]
        )

        prepare_mock = mocker.patch.object(
            maasserver.vault, "prepare_wrapped_approle"
        )
        prepare_mock.return_value = secret_id

        assert snap.get_vault_settings(options) == {
            "vault_url": url,
            "vault_approle_id": approle_id,
            "vault_secret_id": secret_id,
            "vault_secrets_mount": "secret",
            "vault_secrets_path": secrets_path,
        }
        prepare_mock.assert_called_once_with(
            url=url,
            role_id=approle_id,
            wrapped_token=wrapped_token,
            secrets_path=secrets_path,
            secrets_mount="secret",
        )

    def test_get_vault_settings_returns_mount_when_specified(self, mocker):
        url = "http://vault:8200"
        approle_id = factory.make_name("uuid")
        wrapped_token = factory.make_name("uuid")
        secret_id = factory.make_name("uuid")
        secrets_path = "path"
        secrets_mount = "test_mount"
        options = self.parser.parse_args(
            [
                "region+rack",
                "--database-uri",
                "maas-test-db:///",
                "--vault-uri",
                url,
                "--vault-approle-id",
                approle_id,
                "--vault-wrapped-token",
                wrapped_token,
                "--vault-secrets-path",
                secrets_path,
                "--vault-secrets-mount",
                secrets_mount,
            ]
        )

        prepare_mock = mocker.patch.object(
            maasserver.vault, "prepare_wrapped_approle"
        )
        prepare_mock.return_value = secret_id

        assert snap.get_vault_settings(options) == {
            "vault_url": url,
            "vault_approle_id": approle_id,
            "vault_secret_id": secret_id,
            "vault_secrets_mount": secrets_mount,
            "vault_secrets_path": secrets_path,
        }
        prepare_mock.assert_called_once_with(
            url=url,
            role_id=approle_id,
            wrapped_token=wrapped_token,
            secrets_path=secrets_path,
            secrets_mount=secrets_mount,
        )

    def test_get_vault_settings_raises_command_error_for_vault_issues(
        self, mocker
    ):
        url = "http://vault:8200"
        approle_id = factory.make_name("uuid")
        wrapped_token = factory.make_name("uuid")
        secrets_path = "path"
        options = self.parser.parse_args(
            [
                "region+rack",
                "--database-uri",
                "maas-test-db:///",
                "--vault-uri",
                url,
                "--vault-approle-id",
                approle_id,
                "--vault-wrapped-token",
                wrapped_token,
                "--vault-secrets-path",
                secrets_path,
            ]
        )

        prepare_mock = mocker.patch.object(
            maasserver.vault, "prepare_wrapped_approle"
        )
        prepare_mock.side_effect = [VaultError()]

        with pytest.raises(CommandError):
            snap.get_vault_settings(options)

    def test_get_vault_settings_reraises_unknown_error(self, mocker):
        url = "http://vault:8200"
        approle_id = factory.make_name("uuid")
        wrapped_token = factory.make_name("uuid")
        secrets_path = "path"
        options = self.parser.parse_args(
            [
                "region+rack",
                "--database-uri",
                "maas-test-db:///",
                "--vault-uri",
                url,
                "--vault-approle-id",
                approle_id,
                "--vault-wrapped-token",
                wrapped_token,
                "--vault-secrets-path",
                secrets_path,
            ]
        )

        prepare_mock = mocker.patch.object(
            maasserver.vault, "prepare_wrapped_approle"
        )
        exc = factory.make_exception()
        prepare_mock.side_effect = [exc]
        with pytest.raises(type(exc)):
            snap.get_vault_settings(options)

    def test_clear_certificates_dir(self, tmp_path, monkeypatch):
        maas_data = tmp_path / "maas_data"
        maas_data.mkdir(exist_ok=True)
        self.certificates_dir = maas_data / "certificates"
        self.certificates_dir.mkdir(exist_ok=True)
        monkeypatch.setenv("MAAS_ROOT", str(maas_data))

        fake_cert = self.certificates_dir / "test.pem"
        fake_cert.write_text("test")

        assert fake_cert.exists()
        snap.clear_certificates_dir()
        assert not fake_cert.exists()


class TestCmdStatus:
    def test_requires_root(self, mocker):
        parser = ArgumentParser()
        cmd = snap.cmd_status(parser)
        mocker.patch.object(os, "getuid").return_value = 1000
        with pytest.raises(SystemExit) as exc_info:
            cmd(parser.parse_args([]))
        assert (
            str(exc_info.value) == "The 'status' command must be run by root."
        )


class TestCmdConfig:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, mocker, monkeypatch):
        self.parser = ArgumentParser()
        self.cmd = snap.cmd_config(self.parser)
        mocker.patch.object(os, "getuid").return_value = 0
        snap_common = tmp_path / "common"
        snap_common.mkdir(exist_ok=True)
        snap_data = tmp_path / "data"
        snap_data.mkdir(exist_ok=True)
        monkeypatch.setenv("SNAP_COMMON", str(snap_common))
        monkeypatch.setenv("SNAP_DATA", str(snap_data))

    def test_show(self, mocker):
        # Regression test for LP:1892868
        stdout = io.StringIO()
        mocker.patch.object(sys, "stdout", stdout)
        options = self.parser.parse_args([])
        assert self.cmd(options) is None
        assert stdout.getvalue() == "Mode: none\n"

    def test_enable_debugging(self, mocker):
        mock_maas_configuration = mocker.patch.object(
            snap, "MAASConfiguration"
        )
        mock_restart_pebble = mocker.patch.object(snap, "restart_pebble")
        options = self.parser.parse_args(["--enable-debug"])
        stdout = io.StringIO()
        mocker.patch.object(sys, "stdout", stdout)

        self.cmd(options)
        mock_maas_configuration().update.assert_called_once_with(
            {"debug": True}
        )
        # After config is changed, services are restarted
        assert stdout.getvalue() == "Stopping services\n"
        mock_restart_pebble.assert_called_once_with()

    def test_reenable_debugging(self, mocker):
        mock_maas_configuration = mocker.patch.object(
            snap, "MAASConfiguration"
        )
        config_manager = mock_maas_configuration()
        mock_restart_pebble = mocker.patch.object(snap, "restart_pebble")
        options = self.parser.parse_args(["--enable-debug"])
        stdout = io.StringIO()
        mocker.patch.object(sys, "stdout", stdout)

        # Simulate the value already being enabled
        current_config = config_manager.get()
        current_config.get.side_effect = {"debug": True}.__getitem__

        self.cmd(options)
        config_manager.update.assert_not_called()
        assert stdout.getvalue() == ""
        mock_restart_pebble.assert_not_called()


class TestGetDatabaseSettingsSslmode:
    """Tests for sslmode handling in get_database_settings()."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.parser = ArgumentParser()
        snap.cmd_init(self.parser)
        monkeypatch.setattr(
            os, "environ", {"SNAP_COMMON": str(tmp_path / "common")}
        )

    def _parse(self, uri):
        options = self.parser.parse_args(
            ["region+rack", "--database-uri", uri]
        )
        return snap.get_database_settings(options)

    def test_missing_sslmode_defaults_to_prefer(self):
        settings = self._parse("postgres://myuser@myhost/")
        assert "prefer" == settings["database_sslmode"]

    def test_sslmode_is_included_in_returned_dict(self):
        # Regression: sslmode was previously treated as an unsupported parameter.
        settings = self._parse("postgres://myuser@myhost/?sslmode=require")
        assert "require" == settings["database_sslmode"]

    def test_all_valid_sslmodes_accepted(self):
        valid_modes = [
            "disable",
            "allow",
            "prefer",
            "require",
            "verify-ca",
            "verify-full",
        ]
        for mode in valid_modes:
            settings = self._parse(f"postgres://myuser@myhost/?sslmode={mode}")
            assert mode == settings["database_sslmode"], (
                f"Expected sslmode={mode!r} to be accepted"
            )

    def test_invalid_sslmode_raises_error(self):
        with pytest.raises(snap.DatabaseSettingsError) as exc_info:
            self._parse("postgres://myuser@myhost/?sslmode=bogus")
        assert "Invalid sslmode: bogus" == str(exc_info.value)


class TestPrintConfig:
    """print_config() emits SSL settings for region modes."""

    def _run_print_config(self, config_data, mocker):
        mocker.patch.object(
            snap, "get_current_mode"
        ).return_value = "region+rack"
        mock_config = mocker.patch.object(
            snap, "MAASConfiguration"
        ).return_value
        mock_config.get.return_value = config_data
        out = io.StringIO()
        mocker.patch.object(
            snap, "print_msg", lambda msg: out.write(msg + "\n")
        )
        snap.print_config()
        return out.getvalue()

    def test_database_sslmode_printed_in_region_mode(self, mocker):
        output = self._run_print_config(
            {
                "maas_url": "http://localhost:5240/MAAS",
                "database_host": "localhost",
                "database_port": 5432,
                "database_name": "maasdb",
                "database_sslmode": "verify-full",
                "database_user": "maas",
                "database_pass": "secret",
            },
            mocker,
        )
        assert "database_sslmode=verify-full" in output

    def test_cert_paths_printed_in_region_mode(self, mocker):
        output = self._run_print_config(
            {
                "maas_url": "http://localhost:5240/MAAS",
                "database_host": "localhost",
                "database_port": 5432,
                "database_name": "maasdb",
                "database_sslmode": "verify-full",
                "database_sslcert": "/etc/maas/db.crt",
                "database_sslkey": "/etc/maas/db.key",
                "database_sslrootcert": "/etc/maas/ca.crt",
                "database_user": "maas",
                "database_pass": "secret",
            },
            mocker,
        )
        assert "database_sslcert=/etc/maas/db.crt" in output
        assert "database_sslkey=/etc/maas/db.key" in output
        assert "database_sslrootcert=/etc/maas/ca.crt" in output


class TestGetDatabaseSettingsCerts:
    """Tests for sslcert/sslkey/sslrootcert handling in get_database_settings()."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.parser = ArgumentParser()
        snap.cmd_init(self.parser)
        monkeypatch.setattr(
            os, "environ", {"SNAP_COMMON": str(tmp_path / "common")}
        )

    def _parse(self, uri):
        options = self.parser.parse_args(
            ["region+rack", "--database-uri", uri]
        )
        return snap.get_database_settings(options)

    def test_cert_params_absent_default_to_empty_string(self):
        settings = self._parse("postgres://myuser@myhost/")
        assert "" == settings["database_sslcert"]
        assert "" == settings["database_sslkey"]
        assert "" == settings["database_sslrootcert"]

    def test_cert_params_extracted_from_uri(self):
        settings = self._parse(
            "postgres://myuser@myhost/"
            "?sslmode=verify-full"
            "&sslcert=/etc/maas/db.crt"
            "&sslkey=/etc/maas/db.key"
            "&sslrootcert=/etc/maas/ca.crt"
        )
        assert "/etc/maas/db.crt" == settings["database_sslcert"]
        assert "/etc/maas/db.key" == settings["database_sslkey"]
        assert "/etc/maas/ca.crt" == settings["database_sslrootcert"]

    def test_rootcert_only_without_client_cert(self):
        """sslrootcert alone is valid (server-verification without mTLS)."""
        settings = self._parse(
            "postgres://myuser@myhost/"
            "?sslmode=verify-ca&sslrootcert=/etc/maas/ca.crt"
        )
        assert "" == settings["database_sslcert"]
        assert "" == settings["database_sslkey"]
        assert "/etc/maas/ca.crt" == settings["database_sslrootcert"]


class TestDBNeedInit:
    def test_has_tables(self):
        connection = MagicMock()
        connection.introspection.table_names.return_value = [
            "table1",
            "table2",
        ]
        assert not snap.db_need_init(connection)

    def test_no_tables(self):
        connection = MagicMock()
        connection.introspection.table_names.return_value = []
        assert snap.db_need_init(connection)

    def test_fail(self):
        connection = MagicMock()
        connection.introspection.table_names.side_effect = Exception(
            "connection failed"
        )
        assert snap.db_need_init(connection)
