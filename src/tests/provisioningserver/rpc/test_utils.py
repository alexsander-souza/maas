# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test `provisioningserver.rpc.utils`."""

import json
from random import choice

import pytest
from twisted.internet import defer
from twisted.internet.defer import inlineCallbacks

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.factory import factory
from provisioningserver.rpc import clusterservice, region
from provisioningserver.rpc.exceptions import (
    CommissionNodeFailed,
    NodeAlreadyExists,
)
from provisioningserver.rpc.testing import MockLiveClusterToRegionRPCFixture
import provisioningserver.rpc.utils
from provisioningserver.rpc.utils import commission_node, create_node

TIMEOUT = get_testing_timeout()


def _cleanup_rpc_fixture(fixture, shutdown):
    @inlineCallbacks
    def cleanup():
        try:
            yield shutdown()
        finally:
            yield fixture.cleanUp()

    return cleanup()


@inlineCallbacks
def prepare_region_rpc(request, rpc_method):
    fixture = MockLiveClusterToRegionRPCFixture()
    shutdown = [lambda: defer.succeed(None)]
    request.addfinalizer(
        lambda: wait_for(timeout=TIMEOUT)(_cleanup_rpc_fixture)(
            fixture, shutdown[0]
        )
    )
    yield fixture.setUp()
    protocol, connecting = fixture.makeEventLoop(rpc_method)
    shutdown[0] = yield connecting
    return protocol


@pytest.mark.rack_reactor_guard
class TestCreateNode:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        mocker.patch.object(
            clusterservice, "get_all_interfaces_definition"
        ).return_value = {}

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_calls_create_node_rpc(self, request):
        protocol = yield prepare_region_rpc(request, region.CreateNode)
        protocol.CreateNode.return_value = defer.succeed(
            {"system_id": factory.make_name("system-id")}
        )

        uuid = "node-" + factory.make_UUID()
        macs = sorted(factory.make_mac_address() for _ in range(3))
        arch = factory.make_name("architecture")
        hostname = factory.make_hostname()
        domain = factory.make_name("domain")

        power_type = factory.make_name("power_type")
        power_parameters = {
            "power_address": factory.make_ipv4_address(),
            "power_user": factory.make_name("power_user"),
            "power_pass": factory.make_name("power_pass"),
            "power_control": None,
            "system_id": uuid,
        }

        yield create_node(
            macs,
            arch,
            power_type,
            power_parameters,
            domain=domain,
            hostname=hostname,
        )
        protocol.CreateNode.assert_called_once_with(
            protocol,
            architecture=arch,
            power_type=power_type,
            power_parameters=json.dumps(power_parameters),
            mac_addresses=macs,
            domain=domain,
            hostname=hostname,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_returns_system_id_of_new_node(self, request):
        protocol = yield prepare_region_rpc(request, region.CreateNode)
        system_id = factory.make_name("system-id")
        protocol.CreateNode.return_value = defer.succeed(
            {"system_id": system_id}
        )

        uuid = "node-" + factory.make_UUID()
        macs = sorted(factory.make_mac_address() for _ in range(3))
        arch = factory.make_name("architecture")
        power_type = factory.make_name("power_type")
        power_parameters = {
            "power_address": factory.make_ipv4_address(),
            "power_user": factory.make_name("power_user"),
            "power_pass": factory.make_name("power_pass"),
            "power_control": None,
            "system_id": uuid,
        }
        new_system_id = yield create_node(
            macs, arch, power_type, power_parameters
        )
        assert system_id == new_system_id

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_passes_on_no_duplicate_macs(self, request):
        protocol = yield prepare_region_rpc(request, region.CreateNode)
        system_id = factory.make_name("system-id")
        protocol.CreateNode.return_value = defer.succeed(
            {"system_id": system_id}
        )

        uuid = "node-" + factory.make_UUID()
        arch = factory.make_name("architecture")
        power_type = factory.make_name("power_type")
        power_parameters = {
            "power_address": factory.make_ipv4_address(),
            "power_user": factory.make_name("power_user"),
            "power_pass": factory.make_name("power_pass"),
            "power_control": None,
            "system_id": uuid,
        }

        # Create a list of MACs with one random duplicate.
        macs = sorted(factory.make_mac_address() for _ in range(3))
        macs_with_duplicate = macs + [choice(macs)]

        yield create_node(
            macs_with_duplicate, arch, power_type, power_parameters
        )
        protocol.CreateNode.assert_called_once_with(
            protocol,
            architecture=arch,
            power_type=power_type,
            power_parameters=json.dumps(power_parameters),
            mac_addresses=macs,
            domain=None,
            hostname=None,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_logs_error_on_duplicate_macs(self, request, mocker):
        protocol = yield prepare_region_rpc(request, region.CreateNode)
        system_id = factory.make_name("system-id")
        maaslog = mocker.patch.object(provisioningserver.rpc.utils, "maaslog")

        uuid = "node-" + factory.make_UUID()
        macs = sorted(factory.make_mac_address() for _ in range(3))
        arch = factory.make_name("architecture")
        power_type = factory.make_name("power_type")
        power_parameters = {
            "power_address": factory.make_ipv4_address(),
            "power_user": factory.make_name("power_user"),
            "power_pass": factory.make_name("power_pass"),
            "power_control": None,
            "system_id": uuid,
        }

        protocol.CreateNode.side_effect = [
            defer.succeed({"system_id": system_id}),
            defer.fail(NodeAlreadyExists("Node already exists.")),
        ]

        yield create_node(macs, arch, power_type, power_parameters)
        yield create_node(macs, arch, power_type, power_parameters)
        maaslog.error.assert_called_once_with(
            "A node with one of the mac addresses in %s already exists.",
            macs,
        )


@pytest.mark.rack_reactor_guard
class TestCommissionNode:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        mocker.patch.object(
            clusterservice, "get_all_interfaces_definition"
        ).return_value = {}

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_calls_commission_node_rpc(self, request):
        protocol = yield prepare_region_rpc(request, region.CommissionNode)
        protocol.CommissionNode.return_value = defer.succeed({})
        system_id = factory.make_name("system_id")
        user = factory.make_name("user")

        yield commission_node(system_id, user)
        protocol.CommissionNode.assert_called_once_with(
            protocol, system_id=system_id, user=user
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_logs_error_when_not_able_to_commission(self, request, mocker):
        protocol = yield prepare_region_rpc(request, region.CommissionNode)
        maaslog = mocker.patch.object(provisioningserver.rpc.utils, "maaslog")
        system_id = factory.make_name("system_id")
        user = factory.make_name("user")
        error = CommissionNodeFailed("error")

        protocol.CommissionNode.return_value = defer.fail(error)

        yield commission_node(system_id, user)
        maaslog.error.assert_called_once_with(
            "Could not commission with system_id %s because %s.",
            system_id,
            error.args[0],
        )
