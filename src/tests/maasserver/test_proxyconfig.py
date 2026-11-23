# Copyright 2016-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the proxyconfig."""

import random
from socket import AF_INET, AF_INET6

from django.conf import settings
import pytest
from twisted.internet.defer import inlineCallbacks

from maasserver import proxyconfig
from maasserver.models import Config
from maasserver.testing.factory import factory
from maasserver.utils.orm import transactional
from maasserver.utils.threads import deferToDatabase
from maastesting.crochet import wait_for
from provisioningserver.proxy import config

wait_for_reactor = wait_for()


def _fake_dual_stack_source_address(v4="10.0.0.9", v6="fd00::9"):
    """Return a `get_source_address_for_url` stub keyed by address family."""

    def fake_source_address(maas_url, family=None):
        return {AF_INET: v4, AF_INET6: v6}[family]

    return fake_source_address


@pytest.mark.allow_transactions
@pytest.mark.usefixtures(
    "maasdb", "maas_region_test", "factory", "transactional_maasdb"
)
class TestProxyUpdateConfig:
    """Tests for `maasserver.proxyconfig`."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, mocker, monkeypatch):
        self.proxy_path = tmp_path / config.MAAS_PROXY_CONF_NAME
        self.service_monitor = mocker.patch.object(
            proxyconfig, "service_monitor"
        )
        self._mocker = mocker
        monkeypatch.setenv("MAAS_PROXY_CONFIG_DIR", str(tmp_path))

    def patch(self, obj, attribute, value=None):
        if value is None:
            return self._mocker.patch.object(obj, attribute)
        return self._mocker.patch.object(obj, attribute, value)

    @transactional
    def make_subnet(self, allow_proxy=True):
        return factory.make_Subnet(allow_proxy=allow_proxy)

    @wait_for_reactor
    @inlineCallbacks
    def test_only_enabled_subnets_are_present(self):
        self.patch(settings, "PROXY_CONNECT", True)
        disabled = yield deferToDatabase(self.make_subnet, allow_proxy=False)
        enabled = yield deferToDatabase(self.make_subnet)
        yield proxyconfig.proxy_update_config(reload_proxy=False)
        # enabled's cidr must be present
        needle = f"acl localnet src {enabled.cidr}"

        with self.proxy_path.open("r") as fh:
            contents = fh.read()
        assert needle in contents
        # disabled's cidr must not be present
        disabled_line = f"acl localnet src {disabled.cidr}"
        assert disabled_line not in contents

    @wait_for_reactor
    @inlineCallbacks
    def test_with_use_peer_proxy_with_http_proxy(self):
        self.patch(settings, "PROXY_CONNECT", True)
        yield deferToDatabase(
            transactional(Config.objects.set_config), "enable_http_proxy", True
        )
        yield deferToDatabase(
            transactional(Config.objects.set_config), "use_peer_proxy", True
        )
        yield deferToDatabase(
            transactional(Config.objects.set_config),
            "http_proxy",
            "http://example.com:8000/",
        )
        yield deferToDatabase(self.make_subnet, allow_proxy=False)
        yield deferToDatabase(self.make_subnet)
        yield proxyconfig.proxy_update_config(reload_proxy=False)
        cache_peer_line = (
            "cache_peer example.com parent 8000 0 no-query default"
        )
        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
        assert "never_direct allow all" in lines
        assert cache_peer_line in lines

    @wait_for_reactor
    @inlineCallbacks
    def test_with_use_peer_proxy_without_http_proxy(self):
        self.patch(settings, "PROXY_CONNECT", True)
        yield deferToDatabase(
            transactional(Config.objects.set_config), "enable_http_proxy", True
        )
        yield deferToDatabase(
            transactional(Config.objects.set_config), "use_peer_proxy", True
        )
        yield deferToDatabase(
            transactional(Config.objects.set_config), "http_proxy", ""
        )
        yield deferToDatabase(self.make_subnet, allow_proxy=False)
        yield deferToDatabase(self.make_subnet)
        yield proxyconfig.proxy_update_config(reload_proxy=False)
        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
        assert "never_direct allow all" not in lines
        assert "cache_peer" not in lines

    @wait_for_reactor
    @inlineCallbacks
    def test_without_use_peer_proxy(self):
        self.patch(settings, "PROXY_CONNECT", True)
        yield deferToDatabase(
            transactional(Config.objects.set_config), "enable_http_proxy", True
        )
        yield deferToDatabase(
            transactional(Config.objects.set_config), "use_peer_proxy", False
        )
        yield deferToDatabase(
            transactional(Config.objects.set_config),
            "http_proxy",
            "http://example.com:8000/",
        )
        yield deferToDatabase(self.make_subnet, allow_proxy=False)
        yield deferToDatabase(self.make_subnet)
        yield proxyconfig.proxy_update_config(reload_proxy=False)
        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
        assert "never_direct allow all" not in lines
        assert "cache_peer" not in lines

    @wait_for_reactor
    @inlineCallbacks
    def test_with_prefer_v4_proxy_False(self):
        self.patch(settings, "PROXY_CONNECT", True)
        yield deferToDatabase(
            transactional(Config.objects.set_config), "prefer_v4_proxy", False
        )
        yield proxyconfig.proxy_update_config(reload_proxy=False)
        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
        assert "dns_v4_first on" not in lines

    @wait_for_reactor
    @inlineCallbacks
    def test_with_prefer_v4_proxy_True(self):
        self.patch(settings, "PROXY_CONNECT", True)
        yield deferToDatabase(
            transactional(Config.objects.set_config), "prefer_v4_proxy", True
        )
        yield proxyconfig.proxy_update_config(reload_proxy=False)
        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
        assert "dns_v4_first on" in lines

    @wait_for_reactor
    @inlineCallbacks
    def test_with_new_maas_proxy_port_changes_port(self):
        self.patch(settings, "PROXY_CONNECT", True)
        port = random.randint(1, 65535)
        yield deferToDatabase(
            transactional(Config.objects.set_config), "maas_proxy_port", port
        )
        yield proxyconfig.proxy_update_config(reload_proxy=False)
        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
        assert f"http_port {port}" in lines

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_restartService(self):
        self.patch(settings, "PROXY_CONNECT", True)
        yield deferToDatabase(self.make_subnet)
        yield proxyconfig.proxy_update_config()
        self.service_monitor.restartService.assert_called_once_with(
            "proxy", if_on=True
        )

    @wait_for_reactor
    @inlineCallbacks
    def test_doesnt_call_restartService_when_PROXY_CONNECT_False(self):
        self.patch(settings, "PROXY_CONNECT", False)
        yield deferToDatabase(self.make_subnet)
        yield proxyconfig.proxy_update_config()
        self.service_monitor.restartService.assert_not_called()

    @wait_for_reactor
    @inlineCallbacks
    def test_doesnt_call_restartService_when_reload_proxy_False(self):
        self.patch(settings, "PROXY_CONNECT", True)
        yield deferToDatabase(self.make_subnet)
        yield proxyconfig.proxy_update_config(reload_proxy=False)
        self.service_monitor.restartService.assert_not_called()

    @wait_for_reactor
    @inlineCallbacks
    def test_http_proxy_bind_hardening_off_stays_wildcard(self):
        self.patch(settings, "PROXY_CONNECT", True)
        import maascommon.hardening as hardening_module

        self.patch(
            hardening_module, "is_hardening_enabled"
        ).return_value = False
        yield deferToDatabase(self.make_subnet)
        yield proxyconfig.proxy_update_config(reload_proxy=False)
        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
        assert "http_port 3128 transparent" in lines

    @wait_for_reactor
    @inlineCallbacks
    def test_http_proxy_bind_derives_both_families_under_hardening(self):
        self.patch(settings, "PROXY_CONNECT", True)
        import maascommon.hardening as hardening_module
        from maasserver.config import RegionConfiguration
        import provisioningserver.utils.network as network_module

        fake_source_address = _fake_dual_stack_source_address()

        self.patch(
            hardening_module, "is_hardening_enabled"
        ).return_value = True
        self.patch(
            network_module, "get_source_address_for_url"
        ).side_effect = fake_source_address
        mock_open = self.patch(RegionConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.http_proxy_bind = []
        mock_cfg.maas_url = "http://10.0.0.9:5240/MAAS"
        mock_open.return_value.__exit__.return_value = False

        yield deferToDatabase(self.make_subnet)
        yield proxyconfig.proxy_update_config(reload_proxy=False)

        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
        assert "http_port 10.0.0.9:3128 transparent" in lines
        assert "http_port [fd00::9]:3128 transparent" in lines

    @wait_for_reactor
    @inlineCallbacks
    def test_http_proxy_bind_explicit_value_used(self):
        self.patch(settings, "PROXY_CONNECT", True)
        import maascommon.hardening as hardening_module
        from maasserver.config import RegionConfiguration

        self.patch(
            hardening_module, "is_hardening_enabled"
        ).return_value = False
        mock_open = self.patch(RegionConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.http_proxy_bind = ["10.0.0.5"]
        mock_cfg.maas_url = ""
        mock_open.return_value.__exit__.return_value = False

        yield deferToDatabase(self.make_subnet)
        yield proxyconfig.proxy_update_config(reload_proxy=False)

        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
        assert "http_port 10.0.0.5:3128 transparent" in lines

    @wait_for_reactor
    @inlineCallbacks
    def test_http_proxy_bind_explicit_v4_backfills_v6_under_hardening(self):
        self.patch(settings, "PROXY_CONNECT", True)
        import maascommon.hardening as hardening_module
        from maasserver.config import RegionConfiguration
        import provisioningserver.utils.network as network_module

        fake_source_address = _fake_dual_stack_source_address()

        self.patch(
            hardening_module, "is_hardening_enabled"
        ).return_value = True
        self.patch(
            network_module, "get_source_address_for_url"
        ).side_effect = fake_source_address
        mock_open = self.patch(RegionConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.http_proxy_bind = ["10.0.0.5"]
        mock_cfg.maas_url = "http://10.0.0.9:5240/MAAS"
        mock_open.return_value.__exit__.return_value = False

        yield deferToDatabase(self.make_subnet)
        yield proxyconfig.proxy_update_config(reload_proxy=False)

        with self.proxy_path.open() as proxy_file:
            lines = [line.strip() for line in proxy_file.readlines()]
        assert "http_port 10.0.0.5:3128 transparent" in lines
        assert "http_port [fd00::9]:3128 transparent" in lines
