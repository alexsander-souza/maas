# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for
:py:module:`~provisioningserver.rackdservices.node_power_monitor_service`."""

from unittest.mock import ANY, Mock, sentinel

from fixtures import FakeLogger
import pytest
from twisted.internet.defer import fail, succeed
from twisted.internet.error import ConnectionDone
from twisted.internet.task import Clock

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.deferred import extract_result
from maastesting.factory import factory
from maastesting.twisted import TwistedLoggerFixture
from provisioningserver.rackdservices import node_power_monitor_service as npms
from provisioningserver.rpc import (
    clusterservice,
    exceptions,
    getRegionClient,
    region,
)
from provisioningserver.rpc.testing import MockClusterToRegionRPCFixture

TIMEOUT = get_testing_timeout()


@pytest.fixture
def rpc_fixture(request):
    fixture = MockClusterToRegionRPCFixture()
    fixture.setUp()
    request.addfinalizer(fixture.cleanUp)
    return fixture


@pytest.mark.rack_reactor_guard
class TestNodePowerMonitorService:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        mocker.patch.object(
            clusterservice, "get_all_interfaces_definition", return_value={}
        )

    def test_init_sets_up_timer_correctly(self):
        service = npms.NodePowerMonitorService()
        assert service.call == (service.try_query_nodes, tuple(), {})
        assert service.step == 15
        assert service.clock is None

    def make_monitor_service(self):
        service = npms.NodePowerMonitorService(Clock())
        return service

    @wait_for(timeout=TIMEOUT)
    def test_query_nodes_calls_the_region(self, rpc_fixture):
        service = self.make_monitor_service()

        proto_region, io = rpc_fixture.makeEventLoop(
            region.ListNodePowerParameters
        )
        proto_region.ListNodePowerParameters.return_value = succeed(
            {"nodes": []}
        )

        client = getRegionClient()
        d = service.query_nodes(client)
        io.flush()

        assert extract_result(d) is None
        proto_region.ListNodePowerParameters.assert_called_once_with(
            ANY, uuid=client.localIdent
        )

    @wait_for(timeout=TIMEOUT)
    def test_query_nodes_calls_query_all_nodes(self, rpc_fixture, mocker):
        service = self.make_monitor_service()
        service.max_nodes_at_once = sentinel.max_nodes_at_once

        example_power_parameters = {
            "system_id": factory.make_UUID(),
            "hostname": factory.make_hostname(),
            "power_state": factory.make_name("power_state"),
            "power_type": factory.make_name("power_type"),
            "context": {},
        }

        proto_region, io = rpc_fixture.makeEventLoop(
            region.ListNodePowerParameters
        )
        proto_region.ListNodePowerParameters.side_effect = [
            succeed({"nodes": [example_power_parameters]}),
            succeed({"nodes": []}),
        ]

        query_all_nodes = mocker.patch.object(npms, "query_all_nodes")

        d = service.query_nodes(getRegionClient())
        io.flush()

        assert extract_result(d) is None
        query_all_nodes.assert_called_once_with(
            [example_power_parameters],
            max_concurrency=sentinel.max_nodes_at_once,
            clock=service.clock,
        )

    @wait_for(timeout=TIMEOUT)
    def test_query_nodes_copes_with_NoSuchCluster(self, rpc_fixture):
        service = self.make_monitor_service()

        proto_region, io = rpc_fixture.makeEventLoop(
            region.ListNodePowerParameters
        )
        client = getRegionClient()
        proto_region.ListNodePowerParameters.return_value = fail(
            exceptions.NoSuchCluster.from_uuid(client.localIdent)
        )

        d = service.query_nodes(client)
        d.addErrback(service.query_nodes_failed, client.localIdent)
        with FakeLogger("maas") as maaslog:
            io.flush()

        assert extract_result(d) is None
        assert "Rack controller '' is not recognised." in maaslog.output

    @wait_for(timeout=TIMEOUT)
    def test_query_nodes_copes_with_losing_connection_to_region(self):
        service = self.make_monitor_service()

        client = Mock(
            return_value=fail(ConnectionDone("Connection was closed cleanly."))
        )

        with FakeLogger("maas") as maaslog:
            d = service.query_nodes(client)
            d.addErrback(service.query_nodes_failed, sentinel.ident)

        assert extract_result(d) is None
        assert "Lost connection to region controller." in maaslog.output

    @wait_for(timeout=TIMEOUT)
    def test_try_query_nodes_logs_other_errors(self, mocker):
        service = self.make_monitor_service()
        mocker.patch.object(
            npms, "getRegionClient"
        ).return_value = sentinel.client
        sentinel.client.localIdent = factory.make_UUID()

        query_nodes = mocker.patch.object(service, "query_nodes")
        query_nodes.return_value = fail(
            ZeroDivisionError("Such a shame I can't divide by zero")
        )

        with FakeLogger("maas") as maaslog, TwistedLoggerFixture():
            d = service.try_query_nodes()

        assert extract_result(d) is None
        assert (
            "Failed to query nodes' power status: Such a shame I can't divide by zero"
            in maaslog.output
        )
