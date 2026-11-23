# Copyright 2014-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for :py:module:`provisioningserver.dns.actions`."""

import ipaddress
import os
from os.path import join
import random
from random import randint
import re
from subprocess import CalledProcessError
from textwrap import dedent
from unittest.mock import call, Mock, sentinel

from fixtures import FakeLogger
from netaddr import IPNetwork
import pytest

from maastesting.factory import factory
from provisioningserver.dns import actions
from provisioningserver.dns.config import (
    MAAS_NAMED_CONF_NAME,
    MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME,
)
from provisioningserver.dns.zoneconfig import (
    DNSForwardZoneConfig,
    DNSReverseZoneConfig,
)
from provisioningserver.utils.shell import ExternalProcessError
from tests.provisioningserver.dns.test_zoneconfig import HostnameIPMapping


class TestReconfigure:
    """Tests for :py:func:`actions.bind_reconfigure`."""

    def test_executes_rndc_command(self, mocker):
        mocker.patch.object(actions, "execute_rndc_command", autospec=True)
        actions.bind_reconfigure()
        actions.execute_rndc_command.assert_called_once_with(("reconfig",))

    def test_logs_subprocess_error(self, mocker):
        erc = mocker.patch.object(
            actions, "execute_rndc_command", autospec=True
        )
        erc.side_effect = factory.make_CalledProcessError()
        with FakeLogger("maas") as logger:
            with pytest.raises(CalledProcessError):
                actions.bind_reconfigure()
        assert re.search(
            r"^Reloading BIND configuration failed: Command [^\s]+ returned non-zero exit status",
            logger.output,
        )

    def test_upgrades_subprocess_error(self, mocker):
        erc = mocker.patch.object(
            actions, "execute_rndc_command", autospec=True
        )
        erc.side_effect = factory.make_CalledProcessError()
        with pytest.raises(ExternalProcessError):
            actions.bind_reconfigure()


class TestReload:
    """Tests for :py:func:`actions.bind_reload`."""

    def test_executes_rndc_command(self, mocker):
        mocker.patch.object(actions, "execute_rndc_command", autospec=True)
        actions.bind_reload()
        actions.execute_rndc_command.assert_called_once_with(
            ("reload",), timeout=2
        )

    def test_logs_subprocess_error(self, mocker):
        erc = mocker.patch.object(
            actions, "execute_rndc_command", autospec=True
        )
        erc.side_effect = factory.make_CalledProcessError()
        with FakeLogger("maas") as logger:
            assert not actions.bind_reload()
        assert re.search(
            r"^Reloading BIND failed \(is it running\?\): Command [^\s]+ returned non-zero exit status",
            logger.output,
        )

    def test_false_on_subprocess_error(self, mocker):
        erc = mocker.patch.object(
            actions, "execute_rndc_command", autospec=True
        )
        erc.side_effect = factory.make_CalledProcessError()
        assert not actions.bind_reload()


class TestReloadWithRetries:
    """Tests for :py:func:`actions.bind_reload_with_retries`."""

    def test_calls_bind_reload_count_times(self, mocker):
        mocker.patch.object(actions, "sleep", autospec=True)  # Disable.
        bind_reload = mocker.patch.object(
            actions, "bind_reload", autospec=True
        )
        bind_reload.return_value = False
        attempts = randint(3, 13)
        assert not actions.bind_reload_with_retries(max_attempts=attempts)
        expected_calls = [call(timeout=2)] * attempts
        actions.bind_reload.assert_has_calls(expected_calls)

    def test_returns_on_success(self, mocker):
        mocker.patch.object(actions, "sleep", autospec=True)  # Disable.
        bind_reload = mocker.patch.object(actions, "bind_reload")
        bind_reload_return_values = [False, False, True]
        bind_reload.side_effect = lambda *args, **kwargs: (
            bind_reload_return_values.pop(0)
        )

        assert actions.bind_reload_with_retries(max_attempts=5)
        expected_calls = [call(timeout=2), call(timeout=2), call(timeout=2)]
        actions.bind_reload.assert_has_calls(expected_calls)

    def test_sleeps_interval_seconds_between_attempts(self, mocker):
        mocker.patch.object(actions, "sleep", autospec=True)  # Disable.
        bind_reload = mocker.patch.object(
            actions, "bind_reload", autospec=True
        )
        bind_reload.return_value = False
        attempts = randint(3, 13)
        actions.bind_reload_with_retries(
            max_attempts=attempts, interval=sentinel.interval
        )
        expected_sleep_calls = [call(sentinel.interval)] * (attempts - 1)
        actions.sleep.assert_has_calls(expected_sleep_calls)


class TestReloadZone:
    """Tests for :py:func:`actions.bind_reload_zones`."""

    def test_executes_rndc_command(self, mocker):
        mocker.patch.object(actions, "execute_rndc_command", autospec=True)
        assert actions.bind_reload_zones(sentinel.zone)
        actions.execute_rndc_command.assert_called_once_with(
            ("reload", sentinel.zone)
        )

    def test_logs_subprocess_error(self, mocker):
        erc = mocker.patch.object(
            actions, "execute_rndc_command", autospec=True
        )
        erc.side_effect = factory.make_CalledProcessError()
        with FakeLogger("maas") as logger:
            assert not actions.bind_reload_zones(sentinel.zone)
        assert re.search(
            r"^Reloading BIND zone sentinel.zone failed \(is it running\?\): Command [^\s]+ returned non-zero exit status",
            logger.output,
        )

    def test_false_on_subprocess_error(self, mocker):
        erc = mocker.patch.object(
            actions, "execute_rndc_command", autospec=True
        )
        erc.side_effect = factory.make_CalledProcessError()
        assert not actions.bind_reload_zones(sentinel.zone)


class TestConfiguration:
    """Tests for the `bind_write_*` functions."""

    @pytest.fixture(autouse=True)
    def _setup(self, mocker, tmp_path, monkeypatch):
        # Ensure that files are written to a temporary directory.
        self.dns_conf_dir = tmp_path
        monkeypatch.setenv("MAAS_DNS_CONFIG_DIR", str(tmp_path))
        monkeypatch.setenv("MAAS_BIND_CONFIG_DIR", str(tmp_path))
        # Patch out calls to 'execute_rndc_command'.
        mocker.patch.object(actions, "execute_rndc_command", autospec=True)

    def test_bind_write_configuration_writes_file(self):
        domain = factory.make_string()
        zones = [
            DNSReverseZoneConfig(
                domain,
                serial=random.randint(1, 100),
                network=factory.make_ipv4_network(),
            ),
            DNSReverseZoneConfig(
                domain,
                serial=random.randint(1, 100),
                network=factory.make_ipv6_network(),
            ),
        ]
        actions.bind_write_configuration(
            zones=zones, trusted_networks=[], allow_only_trusted_transfers=True
        )
        assert os.path.exists(
            os.path.join(self.dns_conf_dir, MAAS_NAMED_CONF_NAME)
        )

    def test_bind_write_configuration_writes_file_with_acl(self):
        trusted_networks = [
            factory.make_ipv4_network(),
            factory.make_ipv6_network(),
        ]
        actions.bind_write_configuration(
            zones=[],
            trusted_networks=trusted_networks,
            allow_only_trusted_transfers=True,
        )
        expected_file = os.path.join(self.dns_conf_dir, MAAS_NAMED_CONF_NAME)
        assert os.path.exists(expected_file)
        expected_content = dedent(
            """\
        acl "trusted" {
            %s;
            %s;
            localnets;
            localhost;
        };
        """
        )
        expected_content %= tuple(trusted_networks)
        with open(expected_file, "r") as fh:
            contents = fh.read()
        assert expected_content in contents

    def test_bind_write_zones_writes_file(self, monkeypatch, tmp_path):
        zone_file_dir = tmp_path / "zone_files"
        zone_file_dir.mkdir()
        monkeypatch.setenv("MAAS_ZONE_FILE_CONFIG_DIR", str(zone_file_dir))
        domain = factory.make_string()
        network = IPNetwork("192.168.0.3/24")
        dns_ip_list = [factory.pick_ip_in_network(network)]
        ip = factory.pick_ip_in_network(network)
        ttl = random.randint(10, 1000)
        forward_zone = DNSForwardZoneConfig(
            domain,
            serial=random.randint(1, 100),
            mapping={
                factory.make_string(): HostnameIPMapping(
                    None, ttl, {ipaddress.ip_address(ip)}
                )
            },
            dns_ip_list=dns_ip_list,
        )
        reverse_zone = DNSReverseZoneConfig(
            domain, serial=random.randint(1, 100), network=network
        )
        actions.bind_write_zones(zones=[forward_zone, reverse_zone])

        forward_file_name = "zone.%s" % domain
        reverse_file_name = "zone.0.168.192.in-addr.arpa"
        assert os.path.exists(join(zone_file_dir, forward_file_name))
        assert os.path.exists(join(zone_file_dir, reverse_file_name))

    def test_bind_write_zones_does_not_freeze_zones(self):
        zone = Mock(write_config=Mock())
        actions.bind_write_zones([zone])
        zone.write_config.assert_called_once_with()
        actions.execute_rndc_command.assert_not_called()

    def test_bind_write_options_sets_up_config(self):
        # bind_write_configuration_and_zones writes the config file, writes
        # the zone files, and reloads the dns service.
        upstream_dns = [
            factory.make_ipv4_address(),
            factory.make_ipv4_address(),
        ]
        dnssec_validation = random.choice(["auto", "yes", "no"])
        expected_dnssec_validation = dnssec_validation
        actions.bind_write_options(
            upstream_dns=upstream_dns, dnssec_validation=dnssec_validation
        )
        expected_options_file = join(
            self.dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        assert os.path.exists(expected_options_file)
        expected_options_content = dedent(
            """\
        forwarders {
            %s;
            %s;
        };

        dnssec-validation %s;
        empty-zones-enable no;
        allow-query { any; };
        allow-recursion { trusted; };
        allow-query-cache { trusted; };
        """
        )
        expected_options_content %= tuple(upstream_dns) + (
            expected_dnssec_validation,
        )
        with open(expected_options_file, "r") as fh:
            contents = fh.read()
        assert expected_options_content in contents
