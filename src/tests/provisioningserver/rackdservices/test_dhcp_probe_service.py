# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for periodic DHCP prober."""

from unittest.mock import Mock, sentinel

import pytest
from twisted.internet import defer
from twisted.internet.defer import inlineCallbacks
from twisted.internet.task import Clock

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.factory import factory
from maastesting.twisted import TwistedLoggerFixture
from provisioningserver.rackdservices import dhcp_probe_service
from provisioningserver.rackdservices.dhcp_probe_service import (
    DHCPProbeService,
)
from provisioningserver.rpc import clusterservice, getRegionClient, region
from provisioningserver.rpc.testing import MockLiveClusterToRegionRPCFixture

TIMEOUT = get_testing_timeout()


@inlineCallbacks
def _cleanup_rpc_fixture(fixture, shutdown):
    try:
        yield shutdown()
    finally:
        yield fixture.cleanUp()


@inlineCallbacks
def _patch_rpc_methods(request):
    fixture = MockLiveClusterToRegionRPCFixture()
    yield fixture.setUp()
    protocol, connecting = fixture.makeEventLoop(
        region.ReportForeignDHCPServer
    )
    shutdown = yield connecting
    request.addfinalizer(
        lambda: wait_for(timeout=TIMEOUT)(_cleanup_rpc_fixture)(
            fixture, shutdown
        )
    )
    return protocol


@pytest.mark.rack_reactor_guard
class TestDHCPProbeService:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        mocker.patch.object(
            clusterservice, "get_all_interfaces_definition"
        ).return_value = {}

    def test_is_called_every_interval(self, mocker):
        clock = Clock()
        service = DHCPProbeService(sentinel.service, clock)

        # Avoid actually probing
        probe_dhcp = mocker.patch.object(service, "probe_dhcp")

        # Until the service has started, periodicprobe_dhcp() won't
        # be called.
        probe_dhcp.assert_not_called()

        # The first call is issued at startup.
        service.startService()
        probe_dhcp.assert_called_once_with()

        # Wind clock forward one second less than the desired interval.
        clock.advance(service.check_interval - 1)

        # No more periodic calls made.
        assert 1 == probe_dhcp.call_count

        # Wind clock forward one second, past the interval.
        clock.advance(1)

        # Now there were two calls.
        assert 2 == probe_dhcp.call_count

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_exits_gracefully_if_cant_report_foreign_dhcp_server(
        self, mocker, request
    ):
        clock = Clock()
        interface_name = factory.make_name("eth")
        interfaces = {
            interface_name: {
                "enabled": True,
                "links": [{"address": "10.0.0.1/24"}],
            }
        }

        maaslog = mocker.patch.object(dhcp_probe_service, "maaslog")
        deferToThread = mocker.patch.object(
            dhcp_probe_service, "deferToThread"
        )
        deferToThread.side_effect = [defer.succeed(interfaces)]
        probe_interface = mocker.patch.object(
            dhcp_probe_service, "probe_interface"
        )
        probe_interface.return_value = ["192.168.0.100"]
        protocol = yield _patch_rpc_methods(request)

        del protocol._commandDispatch[
            region.ReportForeignDHCPServer.commandName
        ]

        rpc_service = Mock()
        rpc_service.getClientNow.return_value = defer.succeed(
            getRegionClient()
        )
        service = DHCPProbeService(rpc_service, clock)
        yield service.startService()
        yield service.stopService()

        maaslog.error.assert_called_once_with(
            "Unable to inform region of DHCP server: the region "
            "does not yet support the ReportForeignDHCPServer RPC "
            "method."
        )

    def test_logs_errors(self, mocker):
        clock = Clock()
        interface_name = factory.make_name("eth")
        interfaces = {
            interface_name: {
                "enabled": True,
                "links": [{"address": "10.0.0.1/24"}],
            }
        }

        maaslog = mocker.patch.object(dhcp_probe_service, "maaslog")
        mock_interfaces = mocker.patch.object(
            dhcp_probe_service, "get_all_interfaces_definition"
        )
        mock_interfaces.return_value = interfaces
        service = DHCPProbeService(sentinel.service, clock)
        error_message = factory.make_string()
        mocker.patch.object(service, "probe_dhcp").side_effect = Exception(
            error_message
        )
        with TwistedLoggerFixture() as logger:
            service.startService()
        maaslog.error.assert_called_once_with(
            "Unable to probe for DHCP servers: %s", error_message
        )
        assert "Running periodic DHCP probe." in logger.messages
        assert "Unable to probe for DHCP servers." in logger.messages

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_skips_disabled_interfaces(self, mocker):
        clock = Clock()
        interface_name = factory.make_name("eth")
        interfaces = {
            interface_name: {
                "enabled": False,
                "links": [{"address": "10.0.0.1/24"}],
            }
        }
        mock_interfaces = mocker.patch.object(
            dhcp_probe_service, "get_all_interfaces_definition"
        )
        mock_interfaces.return_value = interfaces
        service = DHCPProbeService(sentinel.service, clock)
        try_get_client = mocker.patch.object(service, "_tryGetClient")
        try_get_client.getClientNow = Mock()
        probe_interface = mocker.patch.object(
            dhcp_probe_service, "probe_interface"
        )
        yield service.startService()
        yield service.stopService()
        probe_interface.assert_not_called()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_probes_ipv4_interfaces(self, mocker):
        clock = Clock()
        interface_name = factory.make_name("eth")
        interfaces = {
            interface_name: {
                "enabled": True,
                "links": [{"address": "10.0.0.1/24"}],
            }
        }
        mock_interfaces = mocker.patch.object(
            dhcp_probe_service, "get_all_interfaces_definition"
        )
        mock_interfaces.return_value = interfaces
        service = DHCPProbeService(sentinel.service, clock)
        try_get_client = mocker.patch.object(service, "_tryGetClient")
        try_get_client.getClientNow = Mock()
        probe_interface = mocker.patch.object(
            dhcp_probe_service, "probe_interface"
        )
        yield service.startService()
        yield service.stopService()
        probe_interface.assert_called_once()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_skips_ipv6_interfaces(self, mocker):
        clock = Clock()
        interface_name = factory.make_name("eth")
        interfaces = {
            interface_name: {
                "enabled": True,
                "links": [{"address": "2001:db8::1/64"}],
            }
        }
        mock_interfaces = mocker.patch.object(
            dhcp_probe_service, "get_all_interfaces_definition"
        )
        mock_interfaces.return_value = interfaces
        service = DHCPProbeService(sentinel.service, clock)
        try_get_client = mocker.patch.object(service, "_tryGetClient")
        try_get_client.getClientNow = Mock()
        probe_interface = mocker.patch.object(
            dhcp_probe_service, "probe_interface"
        )
        yield service.startService()
        yield service.stopService()
        probe_interface.assert_not_called()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_skips_unconfigured_interfaces(self, mocker):
        clock = Clock()
        interface_name = factory.make_name("eth")
        interfaces = {interface_name: {"enabled": True, "links": []}}
        mock_interfaces = mocker.patch.object(
            dhcp_probe_service, "get_all_interfaces_definition"
        )
        mock_interfaces.return_value = interfaces
        service = DHCPProbeService(sentinel.service, clock)
        try_get_client = mocker.patch.object(service, "_tryGetClient")
        try_get_client.getClientNow = Mock()
        probe_interface = mocker.patch.object(
            dhcp_probe_service, "probe_interface"
        )
        yield service.startService()
        yield service.stopService()
        probe_interface.assert_not_called()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_reports_foreign_dhcp_servers_to_region(self, request, mocker):
        clock = Clock()
        interface_name = factory.make_name("eth")
        interfaces = {
            interface_name: {
                "enabled": True,
                "links": [{"address": "10.0.0.1/24"}],
            }
        }

        protocol = yield _patch_rpc_methods(request)

        deferToThread = mocker.patch.object(
            dhcp_probe_service, "deferToThread"
        )
        foreign_dhcp_ip = factory.make_ipv4_address()
        deferToThread.side_effect = [defer.succeed(interfaces)]
        probe_interface = mocker.patch.object(
            dhcp_probe_service, "probe_interface"
        )
        probe_interface.return_value = [foreign_dhcp_ip]
        client = getRegionClient()
        rpc_service = Mock()
        rpc_service.getClientNow.return_value = defer.succeed(client)

        service = DHCPProbeService(rpc_service, clock)
        yield service.startService()
        yield service.stopService()

        protocol.ReportForeignDHCPServer.assert_called_once_with(
            protocol,
            system_id=client.localIdent,
            interface_name=interface_name,
            dhcp_ip=foreign_dhcp_ip,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_reports_lack_of_foreign_dhcp_servers_to_region(
        self, request, mocker
    ):
        clock = Clock()
        interface_name = factory.make_name("eth")
        interfaces = {
            interface_name: {
                "enabled": True,
                "links": [{"address": "10.0.0.1/24"}],
            }
        }

        protocol = yield _patch_rpc_methods(request)

        deferToThread = mocker.patch.object(
            dhcp_probe_service, "deferToThread"
        )
        deferToThread.side_effect = [defer.succeed(interfaces)]
        probe_interface = mocker.patch.object(
            dhcp_probe_service, "probe_interface"
        )
        probe_interface.return_value = []

        client = getRegionClient()
        rpc_service = Mock()
        rpc_service.getClientNow.return_value = defer.succeed(client)
        service = DHCPProbeService(rpc_service, clock)
        yield service.startService()
        yield service.stopService()

        protocol.ReportForeignDHCPServer.assert_called_once_with(
            protocol,
            system_id=client.localIdent,
            interface_name=interface_name,
            dhcp_ip=None,
        )
