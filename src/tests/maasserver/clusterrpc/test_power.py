# Copyright 2014-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import random
from unittest.mock import Mock

import pytest
from twisted.internet import reactor
from twisted.internet.defer import fail, inlineCallbacks, succeed
from twisted.internet.task import deferLater

from maasserver.clusterrpc import power as power_module
from maasserver.clusterrpc.power import (
    pick_best_power_state,
    power_driver_check,
    power_query,
    power_query_all,
)
from maasserver.testing.factory import factory
from maasserver.utils.orm import transactional
from maasserver.utils.threads import deferToDatabase
from maastesting.crochet import wait_for
from provisioningserver.enum import POWER_STATE
from provisioningserver.rpc.cluster import PowerDriverCheck, PowerQuery

wait_for_reactor = wait_for()


@transactional
def make_node_with_power_info():
    node = factory.make_Node()
    power_info = node.get_effective_power_info()
    return node, power_info


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestPowerQuery:
    """Tests for `power_query`."""

    def test_power_querys_single_node(self):
        node = factory.make_Node()
        client = Mock()

        wait_for_reactor(power_query)(
            client,
            node.system_id,
            node.hostname,
            node.get_effective_power_info(),
        )

        power_info = node.get_effective_power_info()
        client.assert_called_once_with(
            PowerQuery,
            system_id=node.system_id,
            hostname=node.hostname,
            power_type=power_info.power_type,
            context=power_info.power_parameters,
        )


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestPowerDriverCheck:
    """Tests for `power_driver_check`."""

    def test_handled(self):
        node = factory.make_Node()
        power_info = node.get_effective_power_info()
        client = Mock()

        wait_for_reactor(power_driver_check)(client, power_info.power_type)

        client.assert_called_once_with(
            PowerDriverCheck, power_type=power_info.power_type
        )


@pytest.mark.allow_transactions
@pytest.mark.usefixtures("maas_region_test", "factory", "transactional_maasdb")
class TestPowerQueryAll:
    """Tests for `power_query_all`."""

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_PowerQuery_on_all_clients(self, mocker):
        node, power_info = yield deferToDatabase(make_node_with_power_info)

        successful_rack_ids = [
            factory.make_name("system_id") for _ in range(3)
        ]
        error_rack_ids = [factory.make_name("system_id") for _ in range(3)]
        failed_rack_ids = [factory.make_name("system_id") for _ in range(3)]
        clients = []
        power_states = []
        for rack_id in successful_rack_ids:
            power_state = random.choice([POWER_STATE.ON, POWER_STATE.OFF])
            power_states.append(power_state)
            client = Mock()
            client.ident = rack_id
            client.return_value = succeed({"state": power_state})
            clients.append(client)
        for rack_id in error_rack_ids:
            client = Mock()
            client.ident = rack_id
            client.return_value = succeed({"state": POWER_STATE.ERROR})
            clients.append(client)
        for rack_id in failed_rack_ids:
            client = Mock()
            client.ident = rack_id
            client.return_value = fail(factory.make_exception())
            clients.append(client)

        mocker.patch.object(
            power_module, "getAllClients", return_value=clients
        )
        power_state, success_racks, failed_racks = yield power_query_all(
            node.system_id, node.hostname, power_info
        )

        assert power_state == pick_best_power_state(power_states)
        assert sorted(successful_rack_ids) == sorted(success_racks)
        assert sorted(error_rack_ids + failed_rack_ids) == sorted(failed_racks)

    @wait_for_reactor
    @inlineCallbacks
    def test_handles_timeout(self, mocker):
        node, power_info = yield deferToDatabase(make_node_with_power_info)

        def defer_way_later(*args, **kwargs):
            # Create a defer that will finish in 1 minute.
            return deferLater(reactor, 60 * 60, lambda: None)

        rack_id = factory.make_name("system_id")
        client = Mock()
        client.ident = rack_id
        client.side_effect = defer_way_later

        mocker.patch.object(
            power_module, "getAllClients", return_value=[client]
        )
        power_state, success_racks, failed_racks = yield power_query_all(
            node.system_id, node.hostname, power_info, timeout=0.5
        )

        assert power_state == POWER_STATE.UNKNOWN
        assert success_racks == set()
        assert failed_racks == {rack_id}
