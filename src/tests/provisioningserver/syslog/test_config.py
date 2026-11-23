# Copyright 2018-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `provisioningserver.syslog.config`."""

import os

import pytest

from maastesting.factory import factory
from provisioningserver.syslog import config


class TestGetConfigDir:
    """Tests for `get_syslog_config_path`."""

    def test_returns_default(self):
        assert config.get_syslog_config_path() == "/var/lib/maas/rsyslog.conf"

    def test_env_overrides_default(self, mocker):
        env_val = factory.make_name("env")
        mocker.patch.dict(os.environ, {"MAAS_SYSLOG_CONFIG_DIR": env_val})
        assert config.get_syslog_config_path() == os.sep.join(
            [env_val, config.MAAS_SYSLOG_CONF_NAME]
        )


class TestWriteConfig:
    """Tests for `write_config`."""

    @pytest.fixture(autouse=True)
    def _setup(self, mocker, tmp_path):
        self.tmpdir = str(tmp_path)
        self.syslog_path = tmp_path / config.MAAS_SYSLOG_CONF_NAME
        mocker.patch.dict(
            os.environ, {"MAAS_SYSLOG_CONFIG_DIR": str(tmp_path)}
        )

    def assertLinesContain(self, match, lines):
        for line in lines:
            if match in line:
                return
        pytest.fail(f"{match} was not present in: {lines}")

    def test_snap_root_user_group_no_drop(self):
        config.write_config(False)
        needles = ["$FileOwner root", "$FileGroup root"]
        contents = self.syslog_path.read_text()
        for needle in needles:
            assert needle in contents

    def test_udp_and_tcp(self):
        config.write_config(False)
        needles = [
            'input(type="imtcp" port="5247")',
            'input(type="imudp" port="5247")',
        ]
        contents = self.syslog_path.read_text()
        for needle in needles:
            assert needle in contents

    def test_udp_and_tcp_both_use_different_port(self):
        port = factory.pick_port()
        config.write_config(False, port=port)
        needles = [
            f'input(type="imtcp" port="{port}")',
            f'input(type="imudp" port="{port}")',
        ]
        contents = self.syslog_path.read_text()
        for needle in needles:
            assert needle in contents

    def test_bind_addresses_rendered_for_tcp_and_udp(self):
        config.write_config(False, bind=["10.0.0.5", "10.0.0.6"])
        needles = [
            'input(type="imtcp" port="5247" address="10.0.0.5")',
            'input(type="imtcp" port="5247" address="10.0.0.6")',
            'input(type="imudp" port="5247" address="10.0.0.5")',
            'input(type="imudp" port="5247" address="10.0.0.6")',
        ]
        contents = self.syslog_path.read_text()
        for needle in needles:
            assert needle in contents
        assert 'input(type="imtcp" port="5247")\n' not in contents
        assert 'input(type="imudp" port="5247")\n' not in contents

    def test_no_bind_listens_on_all_interfaces(self):
        config.write_config(False)
        contents = self.syslog_path.read_text()
        assert 'input(type="imtcp" port="5247")' in contents
        assert 'input(type="imudp" port="5247")' in contents
        assert "address=" not in contents

    def test_adds_tcp_stop(self):
        cidr = factory.make_ipv4_network()
        config.write_config([cidr])
        needle = ':inputname, isequal, "imtcp" stop'
        contents = self.syslog_path.read_text()
        assert needle in contents

    def test_write_local(self):
        config.write_config(True)
        needles = [
            'set $!remote!SYSLOG_IDENTIFIER = "maas-enlist";',
            'set $!remote!SYSLOG_IDENTIFIER = "maas-machine";',
        ]
        contents = self.syslog_path.read_text()
        for needle in needles:
            assert needle in contents

    def test_no_write_local(self):
        config.write_config(False)
        expected_misses = [
            'set $!remote!SYSLOG_IDENTIFIER = "maas-enlist";',
            'set $!remote!SYSLOG_IDENTIFIER = "maas-machine";',
        ]
        contents = self.syslog_path.read_text()
        for miss in expected_misses:
            assert miss not in contents
        # maas.log is still local when no write local.
        assert 'if $syslogtag contains "maas" then' in contents

    def test_forwarders(self):
        forwarders = [
            {
                "ip": factory.make_ip_address(),
                "name": factory.make_name("name"),
            }
            for _ in range(3)
        ]
        config.write_config(False, forwarders)
        with self.syslog_path.open() as syslog_file:
            lines = [line.strip() for line in syslog_file.readlines()]
            for host in forwarders:
                self.assertLinesContain('target="%s"' % host["ip"], lines)
                self.assertLinesContain(
                    'queue.filename="%s"' % host["name"], lines
                )

    def test_forwarders_diff_port(self):
        port = factory.pick_port()
        forwarders = [
            {
                "ip": factory.make_ip_address(),
                "name": factory.make_name("name"),
            }
            for _ in range(3)
        ]
        config.write_config(False, forwarders, port=port)
        with self.syslog_path.open() as syslog_file:
            lines = [line.strip() for line in syslog_file.readlines()]
            for host in forwarders:
                self.assertLinesContain('target="%s"' % host["ip"], lines)
                self.assertLinesContain('port="%d"' % port, lines)

    def test_write_local_and_forwarders(self):
        forwarders = [
            {
                "ip": factory.make_ip_address(),
                "name": factory.make_name("name"),
            }
            for _ in range(3)
        ]
        config.write_config(True, forwarders)
        with self.syslog_path.open() as syslog_file:
            lines = [line.strip() for line in syslog_file.readlines()]
            assert 'set $!remote!SYSLOG_IDENTIFIER = "maas-enlist";' in lines
            assert 'set $!remote!SYSLOG_IDENTIFIER = "maas-machine";' in lines
            for host in forwarders:
                self.assertLinesContain('target="%s"' % host["ip"], lines)
                self.assertLinesContain(
                    'queue.filename="%s"' % host["name"], lines
                )
