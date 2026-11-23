# Copyright 2018-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `provisioningserver.proxy.config`."""

import os
import random

import pytest

from maastesting.factory import factory
from provisioningserver.proxy import config


class TestGetConfigDir:
    """Tests for `get_proxy_config_path`."""

    def test_returns_default(self):
        assert (
            "/var/lib/maas/maas-proxy.conf" == config.get_proxy_config_path()
        )

    def test_env_overrides_default(self, mocker):
        env_dir = factory.make_name("env")
        mocker.patch.dict(os.environ, {"MAAS_PROXY_CONFIG_DIR": env_dir})
        assert (
            os.sep.join([env_dir, config.MAAS_PROXY_CONF_NAME])
            == config.get_proxy_config_path()
        )


class TestWriteConfig:
    """Tests for `write_config`."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, mocker):
        self.proxy_path = tmp_path / config.MAAS_PROXY_CONF_NAME
        mocker.patch.dict(os.environ, {"MAAS_PROXY_CONFIG_DIR": str(tmp_path)})

    def test_adds_cidr(self):
        cidr = factory.make_ipv4_network()
        config.write_config([cidr])
        with self.proxy_path.open() as fh:
            contents = fh.read()
        assert f"acl localnet src {cidr}" in contents

    def test_peer_proxies(self):
        cidr = factory.make_ipv4_network()
        peer_proxies = ["http://example.com:8000/", "http://other.com:8001/"]
        config.write_config([cidr], peer_proxies=peer_proxies)
        cache_peer1_line = (
            "cache_peer example.com parent 8000 0 no-query default"
        )
        cache_peer2_line = (
            "cache_peer other.com parent 8001 0 no-query default"
        )
        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
            assert "never_direct allow all" in lines
            assert cache_peer1_line in lines
            assert cache_peer2_line in lines

    def test_peer_proxies_with_auth(self):
        cidr = factory.make_ipv4_network()
        peer_proxies = [
            "http://example:example@example.com:8000/",
            "http://other:other@other.com:8001",
        ]
        config.write_config([cidr], peer_proxies=peer_proxies)
        cache_peer1_line = "cache_peer example.com parent 8000 0 no-query default login=example:example"
        cache_peer2_line = "cache_peer other.com parent 8001 0 no-query default login=other:other"
        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
            assert cache_peer1_line in lines
            assert cache_peer2_line in lines

    def test_without_use_peer_proxy(self):
        cidr = factory.make_ipv4_network()
        config.write_config([cidr])
        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
            assert "never_direct allow all" not in lines
            assert "cache_peer" not in lines

    def test_with_prefer_v4_proxy_False(self):
        cidr = factory.make_ipv4_network()
        config.write_config([cidr], prefer_v4_proxy=False)
        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
            assert "dns_v4_first on" not in lines

    def test_with_prefer_v4_proxy_True(self):
        cidr = factory.make_ipv4_network()
        config.write_config([cidr], prefer_v4_proxy=True)
        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
            assert "dns_v4_first on" in lines

    def test_port_changes_port(self):
        cidr = factory.make_ipv4_network()
        port = random.randint(1, 65535)
        config.write_config([cidr], maas_proxy_port=port)
        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
            assert "http_port %s" % port in lines

    def test_http_proxy_bind_single_address(self):
        cidr = factory.make_ipv4_network()
        config.write_config([cidr], http_proxy_bind=["10.0.0.5"])
        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
            assert "http_port 10.0.0.5:3128 transparent" in lines
            assert "http_port 10.0.0.5:8000" in lines

    def test_http_proxy_bind_multiple_addresses(self):
        cidr = factory.make_ipv4_network()
        config.write_config([cidr], http_proxy_bind=["10.0.0.5", "10.0.0.6"])
        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
            assert "http_port 10.0.0.5:3128 transparent" in lines
            assert "http_port 10.0.0.6:3128 transparent" in lines
            assert "http_port 10.0.0.5:8000" in lines
            assert "http_port 10.0.0.6:8000" in lines

    def test_http_proxy_bind_ipv6_only_uses_bracketed_address(self):
        cidr = factory.make_ipv4_network()
        config.write_config([cidr], http_proxy_bind=["fd00::5"])
        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
            assert "http_port [fd00::5]:3128 transparent" in lines
            assert "http_port [fd00::5]:8000" in lines

    def test_http_proxy_bind_v4_and_v6_combined(self):
        cidr = factory.make_ipv4_network()
        config.write_config(
            [cidr],
            http_proxy_bind=["10.0.0.5", "fd00::5"],
        )
        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
            assert "http_port 10.0.0.5:3128 transparent" in lines
            assert "http_port [fd00::5]:3128 transparent" in lines
            assert "http_port 10.0.0.5:8000" in lines
            assert "http_port [fd00::5]:8000" in lines

    def test_no_http_proxy_bind_listens_on_all_interfaces(self):
        cidr = factory.make_ipv4_network()
        config.write_config([cidr])
        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
            assert "http_port 3128 transparent" in lines
            assert "http_port 8000" in lines

    def test_user_in_snap(self):
        config.write_config(allowed_cidrs=[])
        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
            assert "cache_effective_user snap_daemon" in lines
            assert "cache_effective_group snap_daemon" in lines
