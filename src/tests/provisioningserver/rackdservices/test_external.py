# Copyright 2018-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `provisioningserver.rackdservices.external`."""

from socket import AF_INET, AF_INET6
from unittest.mock import Mock

import attr
import pytest
from twisted.internet import defer, reactor
from twisted.internet.defer import inlineCallbacks

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.factory import factory
from maastesting.fixtures import MAASRootFixture
from maastesting.twisted import always_succeed_with, TwistedLoggerFixture
from provisioningserver import services
from provisioningserver.rackdservices import external
from provisioningserver.rpc import clusterservice, common, exceptions, region
from provisioningserver.rpc.testing import MockLiveClusterToRegionRPCFixture
from provisioningserver.service_monitor import service_monitor
from provisioningserver.testing.config import ClusterConfigurationFixture
from provisioningserver.utils.service_monitor import SERVICE_STATE
from provisioningserver.utils.testing import MAASIDFixture, MAASUUIDFixture

TIMEOUT = get_testing_timeout()


@inlineCallbacks
def _cleanup_rpc_fixture(fixture, shutdown):
    try:
        yield shutdown()
    finally:
        yield fixture.cleanUp()


@pytest.fixture(autouse=True)
def _patch_cluster_interfaces(mocker):
    mocker.patch.object(
        clusterservice, "get_all_interfaces_definition", return_value={}
    )


@pytest.fixture
def maas_root(request):
    fixture = MAASRootFixture()
    fixture.setUp()
    request.addfinalizer(fixture.cleanUp)
    return fixture


@pytest.fixture
def cluster_configuration(request):
    fixture = ClusterConfigurationFixture(
        debug=False,
        maas_url=["http://127.0.0.1:5240/MAAS"],
    )
    fixture.setUp()
    request.addfinalizer(fixture.cleanUp)
    return fixture


@pytest.fixture
def rack_controller_identity(request):
    maas_uuid = factory.make_UUID()
    system_id = factory.make_name("system-id")
    uuid_fixture = MAASUUIDFixture(maas_uuid)
    id_fixture = MAASIDFixture(system_id)
    uuid_fixture.setUp()
    id_fixture.setUp()
    request.addfinalizer(id_fixture.cleanUp)
    request.addfinalizer(uuid_fixture.cleanUp)
    return maas_uuid, system_id


def stop_service(request, service):
    request.addfinalizer(
        lambda: wait_for(timeout=TIMEOUT)(service.stopService)()
    )


@inlineCallbacks
def prepareRegion(
    request,
    *,
    is_region=False,
    is_rack=True,
    servers=None,
    peers=None,
    proxy_enabled=True,
    proxy_port=8000,
    proxy_allowed_cidrs=None,
    proxy_prefer_v4_proxy=False,
    syslog_port=5247,
):
    """Set up a mock region controller and register its async teardown."""
    fixture = MockLiveClusterToRegionRPCFixture()
    shutdown = [lambda: defer.succeed(None)]
    request.addfinalizer(
        lambda: wait_for(timeout=TIMEOUT)(_cleanup_rpc_fixture)(
            fixture, shutdown[0]
        )
    )
    yield fixture.setUp()
    protocol, connecting = fixture.makeEventLoop(
        region.GetControllerType,
        region.GetTimeConfiguration,
        region.GetProxyConfiguration,
        region.GetSyslogConfiguration,
    )
    shutdown[0] = yield connecting
    protocol.RegisterRackController.side_effect = always_succeed_with(
        {"system_id": factory.make_name("maas-id")}
    )
    protocol.GetControllerType.side_effect = always_succeed_with(
        {"is_region": is_region, "is_rack": is_rack}
    )
    protocol.GetTimeConfiguration.side_effect = always_succeed_with(
        {
            "servers": [] if servers is None else servers,
            "peers": [] if peers is None else peers,
        }
    )
    if proxy_allowed_cidrs is None:
        proxy_allowed_cidrs = []
    protocol.GetProxyConfiguration.side_effect = always_succeed_with(
        {
            "enabled": proxy_enabled,
            "port": proxy_port,
            "allowed_cidrs": proxy_allowed_cidrs,
            "prefer_v4_proxy": proxy_prefer_v4_proxy,
        }
    )
    protocol.GetSyslogConfiguration.side_effect = always_succeed_with(
        {"port": syslog_port, "promtail_port": 5555}
    )
    return services.getServiceNamed("rpc"), protocol


def make_startable_RackExternalService(mocker, *args, **kwargs):
    service = external.RackExternalService(*args, **kwargs)
    service._orig_tryUpdate = service._tryUpdate
    mocker.patch.object(
        service, "_tryUpdate"
    ).return_value = always_succeed_with(None)
    service.call = (service._tryUpdate, tuple(), {})
    return service


@attr.s
class StubClusterClientService:
    """A stub `ClusterClientService` service that's never connected."""

    def getClientNow(self):
        raise exceptions.NoConnectionsAvailable()


def _fake_dual_stack_source_address(v4="10.0.0.9", v6="fd00::9"):
    """Return a `get_source_address_for_url` stub keyed by address family."""

    def fake_source_address(maas_url, family=None):
        return {AF_INET: v4, AF_INET6: v6}[family]

    return fake_source_address


@pytest.mark.rack_reactor_guard
class TestRackExternalService:
    """Tests for `RackExternalService`."""

    def test_service_uses__tryUpdate_as_periodic_function(
        self, mocker, request
    ):
        service = external.RackExternalService(
            StubClusterClientService(), reactor
        )
        assert (service._tryUpdate, (), {}) == service.call

    def test_service_iterates_on_low_interval(self, mocker, request):
        service = external.RackExternalService(
            StubClusterClientService(), reactor
        )
        assert service.INTERVAL_LOW == service.step

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_getConfiguration_updates_interval_to_high(self, mocker, request):
        rpc_service, protocol = yield prepareRegion(request)
        service = make_startable_RackExternalService(
            mocker, rpc_service, reactor, []
        )

        yield service.startService()
        stop_service(request, service)

        yield service._orig_tryUpdate()

        assert service.INTERVAL_HIGH == service.step
        assert service.INTERVAL_HIGH == service._loop.interval

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_is_silent_and_does_nothing_when_region_is_not_available(
        self, mocker, request, maas_root
    ):
        # Patch the logger in the clusterservice so no log messages are printed
        # because the tests run in debug mode.
        mocker.patch.object(common.log, "debug")

        ntp = external.RackNTP()
        service = make_startable_RackExternalService(
            mocker, StubClusterClientService(), reactor, [("NTP", ntp)]
        )
        mocker.patch.object(ntp, "_tryUpdate", autospec=True)

        yield service.startService()
        stop_service(request, service)

        with TwistedLoggerFixture() as logger:
            yield service._tryUpdate()

        assert "" == logger.output
        ntp._tryUpdate.assert_not_called()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_is_silent_and_does_nothing_when_rack_is_not_recognised(
        self, mocker, request, maas_root
    ):
        # Patch the logger in the clusterservice so no log messages are printed
        # because the tests run in debug mode.
        mocker.patch.object(common.log, "debug")

        rpc_service, protocol = yield prepareRegion(request)
        protocol.GetControllerType.side_effect = exceptions.NoSuchNode
        ntp = external.RackNTP()
        service = make_startable_RackExternalService(
            mocker, StubClusterClientService(), reactor, [("NTP", ntp)]
        )
        mocker.patch.object(ntp, "_tryUpdate", autospec=True)

        yield service.startService()
        stop_service(request, service)

        with TwistedLoggerFixture() as logger:
            yield service._tryUpdate()

        assert "" == logger.output
        ntp._tryUpdate.assert_not_called()


@pytest.mark.rack_reactor_guard
class TestRackNTP:
    """Tests for `RackNTP` in `RackExternalService`."""

    def make_RackNTP_ExternalService(self, rpc_service, reactor, mocker):
        ntp = external.RackNTP()
        service = make_startable_RackExternalService(
            mocker, rpc_service, reactor, [("NTP", ntp)]
        )
        return service, ntp

    def make_servers_and_peers(self):
        return (
            frozenset(
                {
                    factory.make_ipv4_address(),
                    factory.make_ipv6_address(),
                    factory.make_hostname(),
                }
            ),
            frozenset(
                {factory.make_ipv4_address(), factory.make_ipv6_address()}
            ),
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_getConfiguration_returns_configuration_object(
        self, mocker, request
    ):
        is_region, is_rack = factory.pick_bool(), factory.pick_bool()
        servers, peers = self.make_servers_and_peers()
        rpc_service, protocol = yield prepareRegion(
            request,
            is_region=is_region,
            is_rack=is_rack,
            servers=servers,
            peers=peers,
        )
        service, ntp = self.make_RackNTP_ExternalService(
            rpc_service, reactor, mocker
        )
        config = yield service._getConfiguration()
        observed = ntp._getConfiguration(
            config.controller_type, config.time_configuration
        )

        assert isinstance(observed, external._NTPConfiguration)
        assert observed.references == servers
        assert observed.peers == peers
        assert observed.is_region == is_region
        assert observed.is_rack == is_rack

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_tryUpdate_updates_ntp_server(self, mocker, request, maas_root):
        servers, peers = self.make_servers_and_peers()
        rpc_service, _ = yield prepareRegion(
            request, servers=servers, peers=peers
        )
        service, ntp = self.make_RackNTP_ExternalService(
            rpc_service, reactor, mocker
        )
        configure_rack = mocker.patch.object(
            external, "configure_rack", autospec=True
        )
        restartService = mocker.patch.object(
            service_monitor, "restartService", autospec=True
        )

        config = yield service._getConfiguration()
        yield ntp._tryUpdate(config)
        configure_rack.assert_called_once_with(servers, peers)
        restartService.assert_called_once_with("ntp_rack")
        # If the configuration has not changed then a second call to
        # `_tryUpdate` does not result in another call to `configure`.
        yield ntp._tryUpdate(config)
        configure_rack.assert_called_once_with(servers, peers)
        restartService.assert_called_once_with("ntp_rack")

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_is_silent_does_nothing_but_saves_config_when_is_region(
        self, mocker, request, maas_root
    ):
        # Patch the logger in the clusterservice so no log messages are printed
        # because the tests run in debug mode.
        mocker.patch.object(common.log, "debug")

        rpc_service, _ = yield prepareRegion(request, is_region=True)
        service, ntp = self.make_RackNTP_ExternalService(
            rpc_service, reactor, mocker
        )
        mocker.patch.object(
            external, "configure_rack", autospec=True
        )  # No-op configuration.

        # There is no most recently applied configuration.
        assert ntp._configuration is None

        yield service.startService()
        stop_service(request, service)

        with TwistedLoggerFixture() as logger:
            yield service._orig_tryUpdate()

        # The most recently applied configuration is set, though it was not
        # actually "applied" because this host was configured as a region+rack
        # controller, and the rack should not attempt to manage the NTP server
        # on a region+rack.
        assert isinstance(ntp._configuration, external._NTPConfiguration)
        # The configuration was not applied.
        external.configure_rack.assert_not_called()
        # Nothing was logged; there's no need for lots of chatter.
        assert "" == logger.output

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_sets_ntp_rack_service_to_any_when_is_region(
        self, mocker, request, maas_root
    ):
        # Patch the logger in the clusterservice so no log messages are printed
        # because the tests run in debug mode.
        mocker.patch.object(common.log, "debug")

        rpc_service, _ = yield prepareRegion(request, is_region=True)
        service, ntp = self.make_RackNTP_ExternalService(
            rpc_service, reactor, mocker
        )
        mocker.patch.object(
            ntp, "_configure", autospec=True
        )  # No-op configuration.

        # There is no most recently applied configuration.
        assert ntp._configuration is None

        with TwistedLoggerFixture() as logger:
            yield service.startService()
            stop_service(request, service)
            yield service._orig_tryUpdate()

        # Ensure that the service was set to any.
        service = service_monitor.getServiceByName("ntp_rack")
        assert (
            SERVICE_STATE.ANY,
            "managed by the region",
        ) == service.getExpectedState()
        # The most recently applied configuration is set, though it was not
        # actually "applied" because this host was configured as a region+rack
        # controller, and the rack should not attempt to manage the DNS server
        # on a region+rack.
        assert isinstance(ntp._configuration, external._NTPConfiguration)
        # The configuration was not applied.
        ntp._configure.assert_not_called()
        # Nothing was logged; there's no need for lots of chatter.
        assert "" == logger.output


@pytest.mark.rack_reactor_guard
class TestRackNetworkTimeProtocolService_Errors:
    """Tests for error handing in `RackExternalService`."""

    @pytest.mark.parametrize(
        "method",
        [
            pytest.param("_getConfiguration", id="_getConfiguration"),
            pytest.param("_configurationApplied", id="_configurationApplied"),
            pytest.param(
                "_maybeApplyConfiguration", id="_maybeApplyConfiguration"
            ),
            pytest.param("_applyConfiguration", id="_applyConfiguration"),
        ],
    )
    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_tryUpdate_logs_errors_from_broken_method(
        self, method, mocker, request, maas_root
    ):
        # Patch the logger in the clusterservice so no log messages are printed
        # because the tests run in debug mode.
        mocker.patch.object(common.log, "debug")

        rpc_service, _ = yield prepareRegion(request)
        mocker.patch.object(
            external, "configure_rack", autospec=True
        )  # No-op configuration.

        ntp = external.RackNTP()
        service = make_startable_RackExternalService(
            mocker, rpc_service, reactor, [("NTP", ntp)]
        )
        broken_method = mocker.patch.object(ntp, method, autospec=True)
        broken_method.side_effect = factory.make_exception()

        # Ensure that we never actually execute against systemd.
        mocker.patch.object(service_monitor, "restartService", autospec=True)

        yield service.startService()
        stop_service(request, service)

        with TwistedLoggerFixture() as logger:
            yield service._orig_tryUpdate()
        assert "Failed to update NTP configuration" in logger.output


@pytest.mark.rack_reactor_guard
class TestRackProxy:
    """Tests for `RackProxy` for `RackExternalService`."""

    def make_cidrs(self):
        return frozenset(
            {
                str(factory.make_ipv4_network()),
                str(factory.make_ipv6_network()),
            }
        )

    def extract_regions(self, rpc_service):
        return frozenset(
            {
                client.address[0]
                for _, client in rpc_service.connections.items()
            }
        )

    def make_RackProxy_ExternalService(self, rpc_service, reactor, mocker):
        proxy = external.RackProxy()
        service = make_startable_RackExternalService(
            mocker, rpc_service, reactor, [("proxy", proxy)]
        )
        return service, proxy

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_getConfiguration_returns_configuration_object(
        self, mocker, request
    ):
        is_region, is_rack = factory.pick_bool(), factory.pick_bool()
        allowed_cidrs = self.make_cidrs()
        proxy_enabled = factory.pick_bool()
        proxy_prefer_v4_proxy = factory.pick_bool()
        proxy_port = factory.pick_port()
        rpc_service, protocol = yield prepareRegion(
            request,
            is_region=is_region,
            is_rack=is_rack,
            proxy_enabled=proxy_enabled,
            proxy_allowed_cidrs=allowed_cidrs,
            proxy_port=proxy_port,
            proxy_prefer_v4_proxy=proxy_prefer_v4_proxy,
        )
        region_ips = self.extract_regions(rpc_service)
        service, proxy = self.make_RackProxy_ExternalService(
            rpc_service, reactor, mocker
        )
        yield service.startService()
        stop_service(request, service)

        config = yield service._getConfiguration()
        observed = proxy._getConfiguration(
            config.controller_type,
            config.proxy_configuration,
            config.connections,
        )

        assert isinstance(observed, external._ProxyConfiguration)
        assert observed.enabled == proxy_enabled
        assert observed.port == proxy_port
        assert observed.allowed_cidrs == allowed_cidrs
        assert observed.prefer_v4_proxy == proxy_prefer_v4_proxy
        assert observed.upstream_proxies == region_ips
        assert observed.is_region == is_region
        assert observed.is_rack == is_rack

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_tryUpdate_updates_proxy_server(self, mocker, request, maas_root):
        allowed_cidrs = self.make_cidrs()
        proxy_prefer_v4_proxy = factory.pick_bool()
        proxy_port = factory.pick_port()
        rpc_service, _ = yield prepareRegion(
            request,
            proxy_allowed_cidrs=allowed_cidrs,
            proxy_port=proxy_port,
            proxy_prefer_v4_proxy=proxy_prefer_v4_proxy,
        )
        region_ips = self.extract_regions(rpc_service)
        service, _ = self.make_RackProxy_ExternalService(
            rpc_service, reactor, mocker
        )

        write_config = mocker.patch.object(
            external.proxy_config, "write_config", autospec=True
        )
        service_monitor = mocker.patch.object(
            external, "service_monitor", autospec=True
        )

        yield service.startService()
        stop_service(request, service)

        yield service._orig_tryUpdate()

        expected_peers = sorted(
            f"http://{ip}:{proxy_port}" for ip in region_ips
        )
        write_config.assert_called_once_with(
            allowed_cidrs,
            peer_proxies=expected_peers,
            prefer_v4_proxy=proxy_prefer_v4_proxy,
            maas_proxy_port=proxy_port,
            http_proxy_bind=[],
        )
        service_monitor.restartService.assert_called_once_with("proxy_rack")
        # If the configuration has not changed then a second call to
        # `_tryUpdate` does not result in another call to `_configure`.
        yield service._orig_tryUpdate()
        write_config.assert_called_once_with(
            allowed_cidrs,
            peer_proxies=expected_peers,
            prefer_v4_proxy=proxy_prefer_v4_proxy,
            maas_proxy_port=proxy_port,
            http_proxy_bind=[],
        )
        service_monitor.restartService.assert_called_once_with("proxy_rack")

    def _make_proxy_configuration(self, **overrides):
        defaults = dict(
            enabled=True,
            port=8000,
            allowed_cidrs=frozenset(),
            prefer_v4_proxy=False,
            upstream_proxies=frozenset(),
            is_region=False,
            is_rack=True,
        )
        defaults.update(overrides)
        return external._ProxyConfiguration(**defaults)

    def test_configure_hardening_off_unset_stays_wildcard(
        self, mocker, request
    ):
        from provisioningserver.config import ClusterConfiguration

        mocker.patch.object(
            external, "is_hardening_enabled"
        ).return_value = False
        mock_open = mocker.patch.object(ClusterConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.http_proxy_bind = []
        mock_cfg.maas_url = ["http://10.0.0.9:5240/MAAS"]
        mock_open.return_value.__exit__.return_value = False
        write_config = mocker.patch.object(
            external.proxy_config, "write_config", autospec=True
        )

        external.RackProxy()._configure(self._make_proxy_configuration())

        assert [] == write_config.call_args.kwargs["http_proxy_bind"]

    def test_configure_hardening_on_unset_derives_both_families(
        self, mocker, request
    ):
        from provisioningserver.config import ClusterConfiguration
        import provisioningserver.utils.network as network_module

        fake_source_address = _fake_dual_stack_source_address()

        mocker.patch.object(
            external, "is_hardening_enabled"
        ).return_value = True
        mocker.patch.object(
            network_module, "get_source_address_for_url"
        ).side_effect = fake_source_address
        mock_open = mocker.patch.object(ClusterConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.http_proxy_bind = []
        mock_cfg.maas_url = ["http://10.0.0.9:5240/MAAS"]
        mock_open.return_value.__exit__.return_value = False
        write_config = mocker.patch.object(
            external.proxy_config, "write_config", autospec=True
        )

        external.RackProxy()._configure(self._make_proxy_configuration())

        assert ["10.0.0.9", "fd00::9"] == write_config.call_args.kwargs[
            "http_proxy_bind"
        ]

    def test_configure_explicit_v4_backfills_v6_under_hardening(
        self, mocker, request
    ):
        from provisioningserver.config import ClusterConfiguration
        import provisioningserver.utils.network as network_module

        fake_source_address = _fake_dual_stack_source_address()

        mocker.patch.object(
            external, "is_hardening_enabled"
        ).return_value = True
        mocker.patch.object(
            network_module, "get_source_address_for_url"
        ).side_effect = fake_source_address
        mock_open = mocker.patch.object(ClusterConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.http_proxy_bind = ["10.0.0.5"]
        mock_cfg.maas_url = ["http://10.0.0.9:5240/MAAS"]
        mock_open.return_value.__exit__.return_value = False
        write_config = mocker.patch.object(
            external.proxy_config, "write_config", autospec=True
        )

        external.RackProxy()._configure(self._make_proxy_configuration())

        assert ["10.0.0.5", "fd00::9"] == write_config.call_args.kwargs[
            "http_proxy_bind"
        ]

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_sets_proxy_rack_service_to_any_when_is_region(
        self, mocker, request, maas_root
    ):
        # Patch the logger in the clusterservice so no log messages are printed
        # because the tests run in debug mode.
        mocker.patch.object(common.log, "debug")

        rpc_service, _ = yield prepareRegion(request, is_region=True)
        service, proxy = self.make_RackProxy_ExternalService(
            rpc_service, reactor, mocker
        )
        mocker.patch.object(
            proxy, "_configure", autospec=True
        )  # No-op configuration.

        # There is no most recently applied configuration.
        assert proxy._configuration is None

        with TwistedLoggerFixture() as logger:
            yield service.startService()
            stop_service(request, service)
            yield service._orig_tryUpdate()

        # Ensure that the service was set to any.
        service = service_monitor.getServiceByName("proxy_rack")
        assert (
            SERVICE_STATE.ANY,
            "managed by the region",
        ) == service.getExpectedState()
        # The most recently applied configuration is set, though it was not
        # actually "applied" because this host was configured as a region+rack
        # controller, and the rack should not attempt to manage the DNS server
        # on a region+rack.
        assert isinstance(proxy._configuration, external._ProxyConfiguration)
        # The configuration was not applied.
        proxy._configure.assert_not_called()
        # Nothing was logged; there's no need for lots of chatter.
        assert "" == logger.output


@pytest.mark.rack_reactor_guard
class TestRackSyslog:
    """Tests for `RackSyslog` for `RackExternalService`."""

    def extract_regions(self, rpc_service):
        return frozenset(
            {
                (eventloop, client.address[0])
                for eventloop, client in rpc_service.connections.items()
            }
        )

    def make_RackSyslog_ExternalService(self, rpc_service, reactor, mocker):
        syslog = external.RackSyslog()
        service = make_startable_RackExternalService(
            mocker, rpc_service, reactor, [("syslog", syslog)]
        )
        return service, syslog

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_getConfiguration_returns_configuration_object(
        self, mocker, request
    ):
        port = factory.pick_port()
        is_region, is_rack = factory.pick_bool(), factory.pick_bool()
        rpc_service, protocol = yield prepareRegion(
            request, is_region=is_region, is_rack=is_rack, syslog_port=port
        )
        forwarders = self.extract_regions(rpc_service)
        service, syslog = self.make_RackSyslog_ExternalService(
            rpc_service, reactor, mocker
        )
        yield service.startService()
        stop_service(request, service)

        config = yield service._getConfiguration()
        observed = syslog._getConfiguration(
            config.controller_type,
            config.syslog_configuration,
            config.connections,
        )

        assert isinstance(observed, external._SyslogConfiguration)
        assert observed.port == port
        assert observed.forwarders == forwarders
        assert observed.promtail_port == 5555
        assert observed.is_region == is_region
        assert observed.is_rack == is_rack

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_tryUpdate_updates_syslog_server(self, mocker, request, maas_root):
        port = factory.pick_port()
        rpc_service, _ = yield prepareRegion(request, syslog_port=port)
        forwarders = self.extract_regions(rpc_service)
        service, _ = self.make_RackSyslog_ExternalService(
            rpc_service, reactor, mocker
        )

        write_config = mocker.patch.object(
            external.syslog_config, "write_config", autospec=True
        )
        service_monitor = mocker.patch.object(
            external, "service_monitor", autospec=True
        )

        yield service.startService()
        stop_service(request, service)

        yield service._orig_tryUpdate()

        expected_forwards = [
            {"name": name, "ip": ip} for name, ip in forwarders
        ]
        write_config.assert_called_once_with(
            False,
            forwarders=expected_forwards,
            port=port,
            promtail_port=5555,
            bind=[],
        )
        service_monitor.restartService.assert_called_once_with("syslog_rack")
        # If the configuration has not changed then a second call to
        # `_tryUpdate` does not result in another call to `_configure`.
        yield service._orig_tryUpdate()
        write_config.assert_called_once_with(
            False,
            forwarders=expected_forwards,
            port=port,
            promtail_port=5555,
            bind=[],
        )
        service_monitor.restartService.assert_called_once_with("syslog_rack")

    def _make_syslog_configuration(self, **overrides):
        defaults = dict(
            port=5247,
            forwarders=frozenset(),
            is_region=False,
            is_rack=True,
            promtail_port=None,
        )
        defaults.update(overrides)
        return external._SyslogConfiguration(**defaults)

    def test_configure_hardening_off_unset_stays_wildcard(
        self, mocker, request
    ):
        from provisioningserver.config import ClusterConfiguration

        mocker.patch.object(
            external, "is_hardening_enabled"
        ).return_value = False
        mock_open = mocker.patch.object(ClusterConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.syslog_bind = []
        mock_cfg.maas_url = ["http://10.0.0.9:5240/MAAS"]
        mock_open.return_value.__exit__.return_value = False
        write_config = mocker.patch.object(
            external.syslog_config, "write_config", autospec=True
        )

        external.RackSyslog()._configure(self._make_syslog_configuration())

        assert [] == write_config.call_args.kwargs["bind"]

    def test_configure_hardening_on_unset_derives_from_maas_url(
        self, mocker, request
    ):
        from provisioningserver.config import ClusterConfiguration
        import provisioningserver.utils.network as network_module

        mocker.patch.object(
            external, "is_hardening_enabled"
        ).return_value = True
        mocker.patch.object(
            network_module, "get_source_address_for_url"
        ).return_value = "10.0.0.9"
        mock_open = mocker.patch.object(ClusterConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.syslog_bind = []
        mock_cfg.maas_url = ["http://10.0.0.9:5240/MAAS"]
        mock_open.return_value.__exit__.return_value = False
        write_config = mocker.patch.object(
            external.syslog_config, "write_config", autospec=True
        )

        external.RackSyslog()._configure(self._make_syslog_configuration())

        assert ["10.0.0.9"] == write_config.call_args.kwargs["bind"]

    def test_configure_explicit_bind_wins_over_derivation(
        self, mocker, request
    ):
        from provisioningserver.config import ClusterConfiguration

        mocker.patch.object(
            external, "is_hardening_enabled"
        ).return_value = True
        mock_open = mocker.patch.object(ClusterConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.syslog_bind = ["10.0.0.5"]
        mock_cfg.maas_url = ["http://10.0.0.9:5240/MAAS"]
        mock_open.return_value.__exit__.return_value = False
        write_config = mocker.patch.object(
            external.syslog_config, "write_config", autospec=True
        )

        external.RackSyslog()._configure(self._make_syslog_configuration())

        assert ["10.0.0.5"] == write_config.call_args.kwargs["bind"]

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_sets_syslog_rack_service_to_any_when_is_region(
        self, mocker, request, maas_root
    ):
        # Patch the logger in the clusterservice so no log messages are printed
        # because the tests run in debug mode.
        mocker.patch.object(common.log, "debug")

        rpc_service, _ = yield prepareRegion(request, is_region=True)
        service, syslog = self.make_RackSyslog_ExternalService(
            rpc_service, reactor, mocker
        )
        mocker.patch.object(
            syslog, "_configure", autospec=True
        )  # No-op configuration.

        # There is no most recently applied configuration.
        assert syslog._configuration is None

        with TwistedLoggerFixture() as logger:
            yield service.startService()
            stop_service(request, service)
            yield service._orig_tryUpdate()

        # Ensure that the service was set to any.
        service = service_monitor.getServiceByName("syslog_rack")
        assert (
            SERVICE_STATE.ANY,
            "managed by the region",
        ) == service.getExpectedState()
        # The most recently applied configuration is set, though it was not
        # actually "applied" because this host was configured as a region+rack
        # controller, and the rack should not attempt to manage the DNS server
        # on a region+rack.
        assert isinstance(syslog._configuration, external._SyslogConfiguration)
        # The configuration was not applied.
        syslog._configure.assert_not_called()
        # Nothing was logged; there's no need for lots of chatter.
        assert "" == logger.output


@pytest.mark.rack_reactor_guard
class TestRackControllerExternalService:
    def test_getConfiguration_returns_configuration_object(
        self, rack_controller_identity, cluster_configuration
    ):
        maas_uuid, system_id = rack_controller_identity
        rack_controller = external.RackControllerExternalService()
        observed = rack_controller._getConfiguration()
        assert observed.maas_uuid == maas_uuid
        assert observed.system_id == system_id
        assert observed.controller == "https://127.0.0.1:5242"
        assert observed.observability.logging.level == "info"
        assert observed.observability.metrics.enabled
        assert observed.temporal.host == "127.0.0.1"

    def test_getConfiguration_forwards_temporal_server(
        self, request, rack_controller_identity
    ):
        fixture = ClusterConfigurationFixture(
            debug=False,
            maas_url=["http://127.0.0.1:5240/MAAS"],
            temporal_server="some.other.server",
        )
        fixture.setUp()
        request.addfinalizer(fixture.cleanUp)
        rack_controller = external.RackControllerExternalService()
        observed = rack_controller._getConfiguration()
        assert observed.temporal.host == "some.other.server"

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_maybeApplyConfiguration_only_restarts_when_new_config(
        self, mocker, rack_controller_identity
    ):
        restart_service = mocker.patch.object(
            service_monitor, "restartService", autospec=True
        )
        rack_controller = external.RackControllerExternalService()
        rack_controller._configure = Mock()
        assert rack_controller._configuration is None
        config = rack_controller._getConfiguration()
        yield rack_controller._maybeApplyConfiguration(config)
        rack_controller._configure.assert_called_once_with(config)
        restart_service.assert_called_once_with("rack-controller")
        assert rack_controller._configuration is not None
        rack_controller._configure.reset_mock()
        restart_service.reset_mock()
        yield rack_controller._maybeApplyConfiguration(config)
        rack_controller._configure.assert_not_called()
        restart_service.assert_not_called()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_tryUpdate_uses_maybeApplyConfiguration(
        self, mocker, rack_controller_identity
    ):
        mocker.patch.object(service_monitor, "restartService", autospec=True)
        rack_controller = external.RackControllerExternalService()
        config = rack_controller._getConfiguration()
        rack_controller._maybeApplyConfiguration = Mock()
        yield rack_controller._tryUpdate(Mock())
        rack_controller._maybeApplyConfiguration.assert_called_once_with(config)
