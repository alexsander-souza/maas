# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for service monitoring in the regiond."""

import random
from unittest.mock import Mock

from netaddr import IPNetwork
import pytest
from twisted.internet.defer import inlineCallbacks
from twisted.internet.task import Clock

from maasserver.models import Config
from maasserver.regiondservices import active_discovery
from maasserver.regiondservices.active_discovery import ActiveDiscoveryService
from maasserver.testing.factory import factory
from maasserver.utils.orm import transactional
from maasserver.utils.threads import deferToDatabase
from maastesting.crochet import wait_for
from maastesting.twisted import TwistedLoggerFixture

wait_for_reactor = wait_for()


@pytest.mark.allow_transactions
@pytest.mark.usefixtures(
    "maasdb", "transactional_maasdb", "maas_region_test", "factory"
)
class TestActiveDiscoveryService:
    def test_registers_and_unregisters_listener(self, mocker):
        mock_listener = Mock()
        register = mock_listener.register = Mock()
        unregister = mock_listener.unregister = Mock()
        clock = Clock()
        run = mocker.patch.object(ActiveDiscoveryService, "run")
        service = ActiveDiscoveryService(clock, mock_listener)
        service.startService()
        assert service.call == (run, (), {})
        assert service.step == active_discovery.CHECK_INTERVAL
        assert service.clock == clock
        register.assert_called_once_with(
            "config", service.refreshDiscoveryConfig
        )
        unregister.assert_not_called()
        service.stopService()
        unregister.assert_called_once_with(
            "config", service.refreshDiscoveryConfig
        )

    def test_run_calls_refreshDiscoveryConfig(self, mocker):
        clock = Clock()
        service = ActiveDiscoveryService(clock)
        refreshDiscoveryConfig = mocker.patch.object(
            service, "refreshDiscoveryConfig"
        )
        service.startService()
        refreshDiscoveryConfig.assert_called_once_with()

    def test_run_calls_scanIfNeeded_if_discovery_enabled(self, mocker):
        clock = Clock()
        service = ActiveDiscoveryService(clock)
        mocker.patch.object(service, "refreshDiscoveryConfig")
        scanIfNeeded = mocker.patch.object(service, "scanIfNeeded")
        service.startService()
        service.discovery_enabled = True
        clock.advance(300)
        scanIfNeeded.assert_called_once_with()

    def test_run_handles_refresh_failure(self, mocker):
        clock = Clock()
        service = ActiveDiscoveryService(clock)
        refreshDiscoveryConfig = mocker.patch.object(
            service, "refreshDiscoveryConfig"
        )
        refreshDiscoveryConfig.side_effect = Exception
        with TwistedLoggerFixture() as logger:
            service.startService()
        assert (
            ": error refreshing discovery configuration.\nTraceback (most recent call last):"
            in logger.output
        )

    def test_monitorServices_handles_scan_failure(self, mocker):
        clock = Clock()
        service = ActiveDiscoveryService(clock)
        mocker.patch.object(service, "refreshDiscoveryConfig")
        scanIfNeeded = mocker.patch.object(service, "scanIfNeeded")
        scanIfNeeded.side_effect = Exception
        service.discovery_enabled = True
        with TwistedLoggerFixture() as logger:
            service.run()
        assert (
            ": periodic scan failed.\nTraceback (most recent call last):"
            in logger.output
        )

    @wait_for_reactor
    @inlineCallbacks
    def test_scanIfNeeded_logs_success(self, mocker):
        service = ActiveDiscoveryService(Clock())
        try_lock_and_scan = mocker.patch.object(service, "try_lock_and_scan")
        try_lock_and_scan.return_value = "happy"
        service.discovery_enabled = True
        service.discovery_last_scan = 0
        service.discovery_interval = 1
        service.startService()
        with TwistedLoggerFixture() as logger:
            yield service.run()
        assert "Active network discovery: happy" in logger.output


@pytest.mark.allow_transactions
@pytest.mark.usefixtures(
    "maasdb", "transactional_maasdb", "maas_region_test", "factory"
)
class TestRefreshDiscoveryConfig:
    @transactional
    def set_last_scan(self, last_scan):
        Config.objects.set_config("active_discovery_last_scan", last_scan)

    @transactional
    def set_interval(self, interval):
        Config.objects.set_config("active_discovery_interval", interval)

    @wait_for_reactor
    @inlineCallbacks
    def test_stores_correct_values_and_fires_timer(self, mocker):
        expected_last_scan = random.randint(1, 1000)
        expected_interval = random.randint(1, 1000)
        yield deferToDatabase(self.set_interval, expected_interval)
        yield deferToDatabase(self.set_last_scan, expected_last_scan)
        service = ActiveDiscoveryService(Clock())
        run = mocker.patch.object(service, "run")
        with TwistedLoggerFixture() as logger:
            yield service.refreshDiscoveryConfig()
        assert "Discovery interval set to" in logger.output
        assert service.discovery_enabled
        assert service.discovery_interval == expected_interval
        assert service.discovery_last_scan == expected_last_scan
        run.assert_called_once_with()

    @wait_for_reactor
    @inlineCallbacks
    def test_disables_discovery_if_interval_is_zero(self, mocker):
        expected_last_scan = random.randint(1, 1000)
        expected_interval = random.randint(1, 1000)
        yield deferToDatabase(self.set_interval, expected_interval)
        yield deferToDatabase(self.set_last_scan, expected_last_scan)
        service = ActiveDiscoveryService(Clock())
        mocker.patch.object(service, "run")
        yield service.refreshDiscoveryConfig()
        yield deferToDatabase(self.set_interval, 0)
        with TwistedLoggerFixture() as logger:
            yield service.refreshDiscoveryConfig()
        assert "discovery is disabled" in logger.output
        assert not service.discovery_enabled
        assert service.discovery_interval == 0
        assert service.discovery_last_scan == expected_last_scan


@pytest.mark.allow_transactions
@pytest.mark.usefixtures(
    "maasdb", "transactional_maasdb", "maas_region_test", "factory"
)
class TestGetActiveDiscoveryConfig:
    def test_returns_expected_interval(self):
        expected_interval = random.randint(1, 1000)
        Config.objects.set_config(
            "active_discovery_interval", expected_interval
        )
        service = ActiveDiscoveryService(Clock())
        enabled, interval, last_scan = service.get_active_discovery_config()
        assert interval == expected_interval
        assert enabled

    def test_returns_expected_last_scan(self):
        expected_last_scan = random.randint(1, 1000)
        Config.objects.set_config(
            "active_discovery_last_scan", expected_last_scan
        )
        service = ActiveDiscoveryService(Clock())
        enabled, interval, last_scan = service.get_active_discovery_config()
        assert last_scan == expected_last_scan

    def test_returns_disabled_if_interval_is_zero(self):
        Config.objects.set_config("active_discovery_last_scan", 0)
        Config.objects.set_config("active_discovery_interval", 0)
        service = ActiveDiscoveryService(Clock())
        enabled, interval, last_scan = service.get_active_discovery_config()
        assert not enabled

    def test_returns_disabled_if_interval_is_invalid(self):
        expected_interval = factory.make_name()
        expected_last_scan = factory.make_name()
        Config.objects.set_config(
            "active_discovery_last_scan", expected_last_scan
        )
        Config.objects.set_config(
            "active_discovery_interval", expected_interval
        )
        service = ActiveDiscoveryService(Clock())
        enabled, interval, last_scan = service.get_active_discovery_config()
        assert not enabled
        assert interval == 0
        assert last_scan == 0


@pytest.mark.allow_transactions
@pytest.mark.usefixtures(
    "maasdb", "transactional_maasdb", "maas_region_test", "factory"
)
class TestTryLockAndScan:
    """ActiveDiscoveryService.check_settings_and_scan_rack_networks tests."""

    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        self.service = ActiveDiscoveryService(Clock())
        self.get_active_discovery_config = mocker.patch.object(
            self.service, "get_active_discovery_config"
        )
        self.getCurrentTimestamp = mocker.patch.object(
            self.service, "getCurrentTimestamp"
        )
        self.get_network_discovery_config = mocker.patch.object(
            active_discovery.Config.objects, "get_network_discovery_config"
        )
        self.get_cidr_list = mocker.patch.object(
            active_discovery.Subnet.objects,
            "get_cidr_list_for_periodic_active_scan",
        )
        self.mock_discovery_config = Mock()
        self.get_network_discovery_config.return_value = (
            self.mock_discovery_config
        )

    def test_aborts_if_passive_discovery_is_disabled(self):
        self.mock_discovery_config.passive = False
        result = self.service.try_lock_and_scan()
        assert "discovery is disabled. Skipping" in result

    def test_aborts_if_periodic_discovery_is_disabled(self):
        self.mock_discovery_config.passive = True
        self.get_active_discovery_config.return_value = (False, 0, 0)
        result = self.service.try_lock_and_scan()
        assert (
            "Skipping active scan. Periodic discovery is now disabled."
            in result
        )

    def test_aborts_if_periodic_discovery_if_last_scan_too_recent(self):
        self.mock_discovery_config.passive = True
        self.get_active_discovery_config.return_value = (True, 10, 91)
        self.getCurrentTimestamp.return_value = 100
        result = self.service.try_lock_and_scan()
        assert "Another region controller is already scanning" in result

    def test_aborts_if_periodic_discovery_if_no_subnets_enabled(self):
        self.mock_discovery_config.passive = True
        self.get_active_discovery_config.return_value = (True, 10, 90)
        self.getCurrentTimestamp.return_value = 100
        self.get_cidr_list.return_value = []
        result = self.service.try_lock_and_scan()
        assert "Active scanning is not enabled on any subnet" in result

    def test_calls_scan_all_rack_networks_if_everything_is_okay(self, mocker):
        self.mock_discovery_config.passive = True
        self.get_active_discovery_config.return_value = (True, 10, 90)
        self.getCurrentTimestamp.return_value = 100
        cidrs = [IPNetwork(factory.make_ipv4_network())]
        self.get_cidr_list.return_value = cidrs
        scan_all_rack_networks = mocker.patch.object(
            active_discovery, "scan_all_rack_networks"
        )
        rpc_results = Mock()
        rpc_results.available = ["rack1"]
        scan_all_rack_networks.return_value = rpc_results
        get_result_string = mocker.patch.object(
            active_discovery, "get_scan_result_string_for_humans"
        )
        get_result_string.return_value = "sensational"
        result = self.service.try_lock_and_scan()
        assert result == "sensational"
        scan_all_rack_networks.assert_called_once_with(cidrs=cidrs)
