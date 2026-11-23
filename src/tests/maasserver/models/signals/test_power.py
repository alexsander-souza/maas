"""Tests for node power status query when state changes."""

from unittest.mock import ANY, Mock

import pytest
from twisted.internet import defer
from twisted.internet.task import Clock

from maasserver.exceptions import PowerProblem
from maasserver.models.node import Node
from maasserver.models.signals import power
from maasserver.node_status import get_failed_status, NODE_STATUS
from maasserver.testing.factory import factory
from maasserver.utils.orm import post_commit_hooks, transactional
from maasserver.utils.threads import deferToDatabase
from maastesting.crochet import wait_for
from provisioningserver.enum import POWER_STATE
from provisioningserver.rpc.exceptions import UnknownPowerType

wait_for_reactor = wait_for()


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestStatusQueryEvent:
    @pytest.mark.real_post_commit_hooks
    def test_changing_status_of_node_emits_event(self, mocker):
        update_power_state = mocker.patch.object(
            power, "update_power_state_of_node_soon", autospec=True
        )
        old_status = NODE_STATUS.COMMISSIONING
        node = factory.make_Node(status=old_status, power_type="virsh")
        node.update_status(get_failed_status(old_status))

        with post_commit_hooks:
            node.save()
            # update_power_state_of_node_soon is registered as a post-commit
            # task, so it's not called immediately.
            update_power_state.assert_not_called()

        # One post-commit hooks have been fired, then it's called.
        post_commit_hooks.fire()
        update_power_state.assert_called_once_with(node.system_id)

    @pytest.mark.real_post_commit_hooks
    def test_commissioning_to_new_emits_query_event(self, mocker):
        update_power_state = mocker.patch.object(
            power, "update_power_state_of_node_soon", autospec=True
        )
        node = factory.make_Node(
            status=NODE_STATUS.COMMISSIONING, power_type="virsh"
        )
        node.update_status(NODE_STATUS.NEW)

        with post_commit_hooks:
            node.save()
            update_power_state.assert_not_called()

        post_commit_hooks.fire()
        update_power_state.assert_called_once_with(node.system_id)

    def test_changing_not_tracked_status_of_node_doesnt_emit_event(
        self, mocker
    ):
        update_power_state = mocker.patch.object(
            power, "update_power_state_of_node_soon", autospec=True
        )
        old_status = NODE_STATUS.ALLOCATED
        node = factory.make_Node(status=old_status, power_type="virsh")
        node.update_status(NODE_STATUS.DEPLOYING)
        node.save()
        update_power_state.assert_not_called()


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestUpdatePowerStateOfNodeSoon:
    def test_calls_update_power_state_of_node_after_wait_time(self, mocker):
        update_power_state = mocker.patch.object(
            power, "update_power_state_of_node", autospec=True
        )
        node = factory.make_Node(power_type="virsh")
        clock = Clock()
        power.update_power_state_of_node_soon(node.system_id, clock=clock)
        update_power_state.assert_not_called()
        clock.advance(power.WAIT_TO_QUERY.total_seconds())
        update_power_state.assert_called_once_with(node.system_id)


@pytest.mark.allow_transactions
@pytest.mark.usefixtures("transactional_maasdb", "maas_region_test", "factory")
class TestUpdatePowerStateOfNode:
    @wait_for_reactor
    @defer.inlineCallbacks
    def test_retrieves_power_state(self, mocker):
        node = yield deferToDatabase(transactional(factory.make_Node))
        mock_power_query = mocker.patch.object(Node, "power_query")
        mock_power_query.return_value = POWER_STATE.ON
        power_state = yield power.update_power_state_of_node(node.system_id)
        assert power_state == POWER_STATE.ON

    def test_traps_failure_for_Node_DoesNotExist(self):
        assert (
            power.update_power_state_of_node(factory.make_name("system_id"))
            is None
        )

    @wait_for_reactor
    @defer.inlineCallbacks
    def test_traps_failure_for_UnknownPowerType(self, mocker):
        node = yield deferToDatabase(transactional(factory.make_Node))
        mock_power_query = mocker.patch.object(Node, "power_query")
        mock_power_query.side_effect = UnknownPowerType()
        power_state = yield power.update_power_state_of_node(node.system_id)
        assert power_state is None

    @wait_for_reactor
    @defer.inlineCallbacks
    def test_traps_failure_for_PowerProblem(self, mocker):
        node = yield deferToDatabase(transactional(factory.make_Node))
        mock_power_query = mocker.patch.object(Node, "power_query")
        mock_power_query.side_effect = PowerProblem()
        power_state = yield power.update_power_state_of_node(node.system_id)
        assert power_state is None

    @wait_for_reactor
    @defer.inlineCallbacks
    def test_logs_other_errors(self, mocker):
        node = yield deferToDatabase(transactional(factory.make_Node))
        mock_power_query = mocker.patch.object(Node, "power_query")
        mock_power_query.side_effect = factory.make_exception("Error")
        mock_log_err = mocker.patch.object(power.log, "err")
        yield power.update_power_state_of_node(node.system_id)
        mock_log_err.assert_called_once_with(
            ANY,
            "Failed to update power state of machine after state transition.",
        )


@pytest.mark.allow_transactions
@pytest.mark.usefixtures("transactional_maasdb", "maas_region_test", "factory")
class TestUpdatePowerStateOfDeployedNode:
    @pytest.fixture(autouse=True)
    def _mock_power_methods(self, mocker):
        self.mock_power_query = mocker.patch.object(Node, "power_query")
        self.power_info = mocker.patch.object(Node, "get_effective_power_info")

    def prepare(self, power_state, can_set_boot_order, status=None):
        node = factory.make_Node(
            status=NODE_STATUS.DEPLOYED if status is None else status
        )
        self.mock_power_query.return_value = power_state
        self.power_info.return_value = Mock(
            can_set_boot_order=can_set_boot_order
        )
        return node

    def assert_recheck_scheduled(
        self, clock, system_id, attempts_left, consecutive_on
    ):
        [recheck] = clock.calls
        assert (
            recheck.getTime()
            == power.DEPLOYED_RECHECK_INTERVAL.total_seconds()
        )
        assert recheck.func == power.update_power_state_of_node
        assert recheck.args == (
            system_id,
            attempts_left,
            consecutive_on,
            clock,
        )

    @wait_for_reactor
    @defer.inlineCallbacks
    def test_reschedules_when_deployed_node_is_not_on(self):
        node = yield deferToDatabase(
            transactional(self.prepare), POWER_STATE.OFF, True
        )
        clock = Clock()
        yield power.update_power_state_of_node(node.system_id, clock=clock)
        self.assert_recheck_scheduled(
            clock,
            node.system_id,
            power.DEPLOYED_RECHECK_MAX_ATTEMPTS - 1,
            0,
        )

    @wait_for_reactor
    @defer.inlineCallbacks
    def test_reschedules_once_more_after_a_single_on_reading(self):
        node = yield deferToDatabase(
            transactional(self.prepare), POWER_STATE.ON, True
        )
        clock = Clock()
        yield power.update_power_state_of_node(node.system_id, clock=clock)
        self.assert_recheck_scheduled(
            clock,
            node.system_id,
            power.DEPLOYED_RECHECK_MAX_ATTEMPTS - 1,
            1,
        )

    @wait_for_reactor
    @defer.inlineCallbacks
    def test_settles_after_required_consecutive_on_readings(self):
        node = yield deferToDatabase(
            transactional(self.prepare), POWER_STATE.ON, True
        )
        clock = Clock()
        power_state = yield power.update_power_state_of_node(
            node.system_id,
            consecutive_on_seen=power.REQUIRED_CONSECUTIVE_ON_READINGS - 1,
            clock=clock,
        )
        assert power_state == POWER_STATE.ON
        assert clock.calls == []

    @wait_for_reactor
    @defer.inlineCallbacks
    def test_does_not_reschedule_for_power_type_without_boot_order(self):
        node = yield deferToDatabase(
            transactional(self.prepare), POWER_STATE.OFF, False
        )
        clock = Clock()
        yield power.update_power_state_of_node(node.system_id, clock=clock)
        assert clock.calls == []

    @wait_for_reactor
    @defer.inlineCallbacks
    def test_does_not_reschedule_when_attempts_are_exhausted(self):
        node = yield deferToDatabase(
            transactional(self.prepare), POWER_STATE.OFF, True
        )
        clock = Clock()
        yield power.update_power_state_of_node(
            node.system_id, recheck_attempts_left=0, clock=clock
        )
        assert clock.calls == []

    @wait_for_reactor
    @defer.inlineCallbacks
    def test_does_not_reschedule_when_node_is_no_longer_deployed(self):
        node = yield deferToDatabase(
            transactional(self.prepare),
            POWER_STATE.OFF,
            True,
            NODE_STATUS.READY,
        )
        clock = Clock()
        yield power.update_power_state_of_node(node.system_id, clock=clock)
        assert clock.calls == []
        self.power_info.assert_not_called()
