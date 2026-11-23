# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


from unittest.mock import call, Mock

import pytest
from twisted.internet.defer import inlineCallbacks, maybeDeferred, succeed
from twisted.internet.task import Clock

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.factory import factory
from provisioningserver import services
from provisioningserver.rackdservices.networks_monitoring_service import (
    RackNetworksMonitoringService,
)
from provisioningserver.rpc import clusterservice, region
from provisioningserver.rpc.testing import MockLiveClusterToRegionRPCFixture
from provisioningserver.utils import services as services_module

TIMEOUT = get_testing_timeout()


@inlineCallbacks
def _cleanup_rpc_fixture(fixture, shutdown):
    try:
        yield shutdown()
    finally:
        yield fixture.cleanUp()


@inlineCallbacks
def _create_fake_rpc_service(metadata_creds, request, *commands):
    fixture = MockLiveClusterToRegionRPCFixture()
    shutdown = [lambda: succeed(None)]
    request.addfinalizer(
        lambda: wait_for(timeout=TIMEOUT)(_cleanup_rpc_fixture)(
            fixture, shutdown[0]
        )
    )
    yield fixture.setUp()
    protocol, connecting = fixture.makeEventLoop(*commands)
    shutdown[0] = yield connecting
    if region.RequestRackRefresh in commands:
        protocol.RequestRackRefresh.return_value = metadata_creds
    return protocol


@pytest.mark.rack_reactor_guard
class TestRackNetworksMonitoringService:
    @pytest.fixture(autouse=True)
    def _set_up(self, mocker):
        mocker.patch.object(
            clusterservice, "get_all_interfaces_definition", return_value={}
        )
        self.mock_refresh = mocker.patch.object(services_module, "refresh")
        self.metadata_creds = {
            "consumer_key": factory.make_string(),
            "token_key": factory.make_string(),
            "token_secret": factory.make_string(),
        }

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_get_refresh_details_not_running(self, request):
        yield _create_fake_rpc_service(
            self.metadata_creds, request, region.RequestRackRefresh
        )
        rpc_service = services.getServiceNamed("rpc")
        service = RackNetworksMonitoringService(
            rpc_service,
            Clock(),
            enable_monitoring=False,
            enable_beaconing=False,
        )
        service.running = 0
        details = yield service.getRefreshDetails()
        assert (None, None, None) == details

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_get_refresh_details_running(self, request):
        yield _create_fake_rpc_service(
            self.metadata_creds, request, region.RequestRackRefresh
        )
        rpc_service = services.getServiceNamed("rpc")
        service = RackNetworksMonitoringService(
            rpc_service,
            Clock(),
            enable_monitoring=False,
            enable_beaconing=False,
        )
        service.running = 1
        self.metadata_creds.update(
            {
                "consumer_key": "my-key",
                "token_key": "my-token",
                "token_secret": "my-secret",
            }
        )
        details = yield service.getRefreshDetails()
        assert ("http://localhost/MAAS", "", self.metadata_creds) == details

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_reports_interfaces_to_region(self, request):
        def refresh(
            system_id,
            consumer_key,
            token_key,
            token_secret,
            maas_url=None,
            post_process_hook=None,
        ):
            assert "" == system_id
            assert self.metadata_creds["consumer_key"] == consumer_key
            assert self.metadata_creds["token_key"] == token_key
            assert self.metadata_creds["token_secret"] == token_secret
            assert "http://localhost/MAAS" == maas_url

        yield _create_fake_rpc_service(
            self.metadata_creds, request, region.RequestRackRefresh
        )

        interfaces = {
            "eth0": {
                "type": "physical",
                "mac_address": factory.make_mac_address(),
                "parents": [],
                "links": [],
                "enabled": True,
            }
        }

        rpc_service = services.getServiceNamed("rpc")
        clock = Clock()
        service = RackNetworksMonitoringService(
            rpc_service,
            clock,
            enable_monitoring=False,
            enable_beaconing=False,
        )
        service.getInterfaces = lambda: succeed(interfaces)
        # Put something in the cache. This tells recordInterfaces that refresh
        # has already run but the interfaces have changed thus they need to be
        # updated.
        service._recorded = {}

        service.startService()
        clock.advance(0)
        yield service.stopService()

        assert self.mock_refresh.call_count == 1

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_reports_interfaces_with_hints_if_beaconing_enabled(
        self, request, mocker
    ):
        yield _create_fake_rpc_service(
            self.metadata_creds, request, region.RequestRackRefresh
        )
        # Don't actually wait for beaconing to complete.
        pause_mock = mocker.patch.object(services_module, "pause")
        queue_mcast_mock = mocker.patch.object(
            services_module.BeaconingSocketProtocol, "queueMulticastBeaconing"
        )

        interfaces = {
            "eth0": {
                "type": "physical",
                "mac_address": factory.make_mac_address(),
                "parents": [],
                "links": [],
                "enabled": True,
            }
        }

        rpc_service = services.getServiceNamed("rpc")
        service = RackNetworksMonitoringService(
            rpc_service,
            Clock(),
            enable_monitoring=False,
            enable_beaconing=True,
        )
        service.getInterfaces = lambda: succeed(interfaces)

        service.startService()
        # By stopping the TimerService first, we assure that the loop
        # happens at least once before the service stops completely.
        yield maybeDeferred(service._timer_service.stopService)
        yield service.stopService()

        # The service should have sent out beacons, waited three seconds,
        # solicited for more beacons, then waited another three seconds before
        # deciding that beaconing is complete.
        pause_mock.assert_has_calls([call(3.0), call(3.0)])
        queue_mcast_mock.assert_has_calls(
            [
                # Called when the service starts.
                call(solicitation=True),
                # Called three seconds later.
                call(solicitation=True),
                # Not called again when the service shuts down.
            ],
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_reports_neighbours_to_region(self, request):
        protocol = yield _create_fake_rpc_service(
            self.metadata_creds, request, region.ReportNeighbours
        )
        rpc_service = services.getServiceNamed("rpc")
        service = RackNetworksMonitoringService(
            rpc_service,
            Clock(),
            enable_monitoring=False,
            enable_beaconing=False,
        )
        neighbours = [{"ip": factory.make_ip_address()}]
        yield service.reportNeighbours(neighbours)
        protocol.ReportNeighbours.assert_called_once_with(
            protocol,
            system_id=rpc_service.getClient().localIdent,
            neighbours=neighbours,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_reports_mdns_to_region(self, request):
        protocol = yield _create_fake_rpc_service(
            self.metadata_creds, request, region.ReportMDNSEntries
        )
        rpc_service = services.getServiceNamed("rpc")
        service = RackNetworksMonitoringService(
            rpc_service,
            Clock(),
            enable_monitoring=False,
            enable_beaconing=False,
        )
        mdns = [
            {
                "interface": "eth0",
                "hostname": "boggle.example.com",
                "address": factory.make_ip_address(),
            }
        ]
        yield service.reportMDNSEntries(mdns)
        protocol.ReportMDNSEntries.assert_called_once_with(
            protocol,
            system_id=rpc_service.getClient().localIdent,
            mdns=mdns,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_asks_region_for_monitoring_state(self, request):
        protocol = yield _create_fake_rpc_service(
            self.metadata_creds, request, region.GetDiscoveryState
        )
        rpc_service = services.getServiceNamed("rpc")
        reactor = Clock()
        service = RackNetworksMonitoringService(
            rpc_service,
            reactor,
            enable_monitoring=False,
            enable_beaconing=False,
        )
        protocol.GetDiscoveryState.return_value = {"interfaces": {}}
        # Put something in the cache. This tells recordInterfaces that refresh
        # has already run but the interfaces have changed thus they need to be
        # updated.
        service._recorded = {}
        yield service.startService()
        yield maybeDeferred(service.getDiscoveryState)
        yield service.stopService()
        protocol.GetDiscoveryState.assert_called_once_with(
            protocol, system_id=rpc_service.getClient().localIdent
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_requests_beaconing_when_timer_fires(self, request):
        yield _create_fake_rpc_service(
            self.metadata_creds, request, region.GetDiscoveryState
        )
        rpc_service = services.getServiceNamed("rpc")
        reactor = Clock()
        service = RackNetworksMonitoringService(
            rpc_service,
            reactor,
            enable_monitoring=False,
            enable_beaconing=True,
        )
        service.beaconing_protocol = Mock()
        service.beaconing_protocol.queueMulticastBeaconing = Mock()
        service.getInterfaces = lambda: succeed({})
        service._recorded = {}
        service.startService()
        yield service.stopService()
        service.beaconing_protocol.queueMulticastBeaconing.assert_has_calls(
            [call(solicitation=True)]
        )
