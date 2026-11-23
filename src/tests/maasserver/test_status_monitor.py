# Copyright 2016-2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the status monitor module."""

from datetime import timedelta
import random
from unittest.mock import call

import pytest
from twisted.internet.defer import maybeDeferred
from twisted.internet.task import Clock

from maasserver import status_monitor
from maasserver.enum import NODE_STATUS
from maasserver.models import Config, Node
from maasserver.models import node as node_module
from maasserver.models.signals.testing import SignalsDisabled
from maasserver.models.timestampedmodel import now
from maasserver.node_status import (
    get_node_timeout,
    NODE_FAILURE_MONITORED_STATUS_TRANSITIONS,
)
from maasserver.status_monitor import (
    mark_nodes_failed_after_expiring,
    mark_nodes_failed_after_missing_script_timeout,
    StatusMonitorService,
)
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object
from maastesting.querycounter import CountQueries
from metadataserver.builtin_scripts import load_builtin_scripts
from metadataserver.enum import SCRIPT_STATUS, SCRIPT_TYPE


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestMarkNodesFailedAfterExpiring:
    def test_marks_all_possible_failed_status_as_failed(self, mocker):
        maaslog = mocker.patch.object(status_monitor.maaslog, "info")
        mocker.patch.object(node_module, "stop_workflow")
        current_time = now()
        expired_time = current_time - timedelta(minutes=1)
        nodes = [
            factory.make_Node(status=status, status_expires=expired_time)
            for status in NODE_FAILURE_MONITORED_STATUS_TRANSITIONS.keys()
        ]
        with SignalsDisabled("power"):
            mark_nodes_failed_after_expiring(current_time, 20)
        failed_statuses = [reload_object(node).status for node in nodes]
        assert sorted(
            NODE_FAILURE_MONITORED_STATUS_TRANSITIONS.values()
        ) == sorted(failed_statuses)
        # MAAS logs in the status_monitor that the timeout was detected. It
        # then logs the transisition in the node signal handler.
        assert (
            len(NODE_FAILURE_MONITORED_STATUS_TRANSITIONS)
            == len(maaslog.call_args_list) / 2
        )

    def test_skips_those_that_have_not_expired(self, mocker):
        maaslog = mocker.patch.object(status_monitor.maaslog, "info")
        current_time = now()
        expired_time = current_time + timedelta(minutes=1)
        nodes = [
            factory.make_Node(status=status, status_expires=expired_time)
            for status in NODE_FAILURE_MONITORED_STATUS_TRANSITIONS.keys()
        ]
        with SignalsDisabled("power"):
            mark_nodes_failed_after_expiring(current_time, 20)
        failed_statuses = [reload_object(node).status for node in nodes]
        assert sorted(
            NODE_FAILURE_MONITORED_STATUS_TRANSITIONS.keys()
        ) == sorted(failed_statuses)
        maaslog.assert_not_called()


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestMarkNodesFailedAfterMissingScriptTimeout:
    @pytest.fixture(autouse=True)
    def _setup(self, maasdb, mocker):
        self.mock_stop = mocker.patch.object(Node, "stop")
        self.maaslog = mocker.patch.object(status_monitor.maaslog, "info")

    @pytest.mark.parametrize(
        "status,failed_status",
        [
            (
                NODE_STATUS.COMMISSIONING,
                NODE_STATUS.FAILED_COMMISSIONING,
            ),
            (NODE_STATUS.TESTING, NODE_STATUS.FAILED_TESTING),
        ],
        ids=["commissioning", "testing"],
    )
    def test_mark_nodes_handled_last_ping_None(
        self, mocker, status, failed_status
    ):
        node, script_set = self.make_node(status)
        script_set.last_ping = None
        script_set.save()
        for _ in range(3):
            factory.make_ScriptResult(
                script_set=script_set, status=SCRIPT_STATUS.PENDING
            )

        # No exception should be raised.
        with SignalsDisabled("power"):
            mark_nodes_failed_after_missing_script_timeout(now(), 20)
        node = reload_object(node)
        assert status == node.status
        self.maaslog.assert_not_called()

    @pytest.mark.parametrize(
        "status,failed_status",
        [
            (
                NODE_STATUS.COMMISSIONING,
                NODE_STATUS.FAILED_COMMISSIONING,
            ),
            (NODE_STATUS.TESTING, NODE_STATUS.FAILED_TESTING),
        ],
        ids=["commissioning", "testing"],
    )
    def test_mark_nodes_failed_after_missing_timeout_heartbeat(
        self, mocker, status, failed_status
    ):
        node, script_set = self.make_node(status)
        current_time = now()
        node_timeout = Config.objects.get_config("node_timeout")
        script_set.last_ping = current_time - timedelta(
            minutes=(node_timeout + 1)
        )
        script_set.save()
        script_results = [
            factory.make_ScriptResult(
                script_set=script_set, status=SCRIPT_STATUS.PENDING
            )
            for _ in range(3)
        ]

        with SignalsDisabled("power"):
            mark_nodes_failed_after_missing_script_timeout(
                current_time, node_timeout
            )
        node = reload_object(node)

        assert failed_status == node.status
        assert (
            "Node has not been heard from for the last %s minutes"
            % node_timeout
            == node.error_description
        )
        assert (
            call(
                "%s: Has not been heard from for the last %s minutes"
                % (node.hostname, node_timeout)
            )
            in self.maaslog.call_args_list
        )
        if node.enable_ssh:
            self.mock_stop.assert_not_called()
        else:
            self.mock_stop.assert_called_once()
            assert (
                call(f"{node.hostname}: Stopped because SSH is disabled")
                in self.maaslog.call_args_list
            )
        for script_result in script_results:
            assert (
                SCRIPT_STATUS.TIMEDOUT == reload_object(script_result).status
            )

    @pytest.mark.parametrize(
        "status,failed_status",
        [
            (
                NODE_STATUS.COMMISSIONING,
                NODE_STATUS.FAILED_COMMISSIONING,
            ),
            (NODE_STATUS.TESTING, NODE_STATUS.FAILED_TESTING),
        ],
        ids=["commissioning", "testing"],
    )
    def test_sets_status_expires_when_flatlined_with_may_reboot_script(
        self, status, failed_status
    ):
        node, script_set = self.make_node(status)
        current_time = now()
        if status == NODE_STATUS.COMMISSIONING:
            script_type = SCRIPT_TYPE.COMMISSIONING
        else:
            script_type = SCRIPT_TYPE.TESTING
        script = factory.make_Script(script_type=script_type, may_reboot=True)
        factory.make_ScriptResult(
            script=script, script_set=script_set, status=SCRIPT_STATUS.RUNNING
        )
        script_set.last_ping = current_time - timedelta(11)
        script_set.save()

        with SignalsDisabled("power"):
            mark_nodes_failed_after_missing_script_timeout(current_time, 20)
        node = reload_object(node)

        assert (
            current_time
            - (current_time - script_set.last_ping)
            + timedelta(minutes=get_node_timeout(status, 20))
            == node.status_expires
        )

    @pytest.mark.parametrize(
        "status,failed_status",
        [
            (
                NODE_STATUS.COMMISSIONING,
                NODE_STATUS.FAILED_COMMISSIONING,
            ),
            (NODE_STATUS.TESTING, NODE_STATUS.FAILED_TESTING),
        ],
        ids=["commissioning", "testing"],
    )
    def test_mark_nodes_failed_after_script_overrun(
        self, status, failed_status
    ):
        node, script_set = self.make_node(status)
        current_time = now()
        script_set.last_ping = current_time
        script_set.save()
        passed_script_result = factory.make_ScriptResult(
            script_set=script_set, status=SCRIPT_STATUS.PASSED
        )
        failed_script_result = factory.make_ScriptResult(
            script_set=script_set, status=SCRIPT_STATUS.FAILED
        )
        pending_script_result = factory.make_ScriptResult(
            script_set=script_set, status=SCRIPT_STATUS.PENDING
        )
        script = factory.make_Script(timeout=timedelta(seconds=60))
        running_script_result = factory.make_ScriptResult(
            script_set=script_set,
            status=SCRIPT_STATUS.RUNNING,
            script=script,
            started=current_time - timedelta(minutes=10),
        )

        with SignalsDisabled("power"):
            mark_nodes_failed_after_missing_script_timeout(current_time, 20)
        node = reload_object(node)

        assert failed_status == node.status
        assert (
            "%s has run past it's timeout(%s)"
            % (
                running_script_result.name,
                str(running_script_result.script.timeout),
            )
            == node.error_description
        )
        assert (
            call(
                "%s: %s has run past it's timeout(%s)"
                % (
                    node.hostname,
                    running_script_result.name,
                    str(running_script_result.script.timeout),
                )
            )
            in self.maaslog.call_args_list
        )
        if node.enable_ssh:
            self.mock_stop.assert_not_called()
        else:
            self.mock_stop.assert_called_once()
            assert (
                call(f"{node.hostname}: Stopped because SSH is disabled")
                in self.maaslog.call_args_list
            )
        assert (
            SCRIPT_STATUS.PASSED == reload_object(passed_script_result).status
        )
        assert (
            SCRIPT_STATUS.FAILED == reload_object(failed_script_result).status
        )
        assert (
            SCRIPT_STATUS.ABORTED
            == reload_object(pending_script_result).status
        )
        assert (
            SCRIPT_STATUS.TIMEDOUT
            == reload_object(running_script_result).status
        )

    @pytest.mark.parametrize(
        "status,failed_status",
        [
            (
                NODE_STATUS.COMMISSIONING,
                NODE_STATUS.FAILED_COMMISSIONING,
            ),
            (NODE_STATUS.TESTING, NODE_STATUS.FAILED_TESTING),
        ],
        ids=["commissioning", "testing"],
    )
    def test_uses_param_runtime(self, status, failed_status):
        node, script_set = self.make_node(status)
        current_time = now()
        script_set.last_ping = current_time
        script_set.save()
        passed_script_result = factory.make_ScriptResult(
            script_set=script_set, status=SCRIPT_STATUS.PASSED
        )
        failed_script_result = factory.make_ScriptResult(
            script_set=script_set, status=SCRIPT_STATUS.FAILED
        )
        pending_script_result = factory.make_ScriptResult(
            script_set=script_set, status=SCRIPT_STATUS.PENDING
        )
        script = factory.make_Script(timeout=timedelta(minutes=2))
        running_script_result = factory.make_ScriptResult(
            script_set=script_set,
            status=SCRIPT_STATUS.RUNNING,
            script=script,
            started=current_time - timedelta(minutes=50),
            parameters={"runtime": {"type": "runtime", "value": 60 * 60}},
        )

        with SignalsDisabled("power"):
            mark_nodes_failed_after_missing_script_timeout(current_time, 20)
        node = reload_object(node)

        assert status == node.status
        self.mock_stop.assert_not_called()
        assert (
            SCRIPT_STATUS.PASSED == reload_object(passed_script_result).status
        )
        assert (
            SCRIPT_STATUS.FAILED == reload_object(failed_script_result).status
        )
        assert (
            SCRIPT_STATUS.PENDING
            == reload_object(pending_script_result).status
        )
        assert (
            SCRIPT_STATUS.RUNNING
            == reload_object(running_script_result).status
        )

    @pytest.mark.parametrize(
        "status,failed_status",
        [
            (
                NODE_STATUS.COMMISSIONING,
                NODE_STATUS.FAILED_COMMISSIONING,
            ),
            (NODE_STATUS.TESTING, NODE_STATUS.FAILED_TESTING),
        ],
        ids=["commissioning", "testing"],
    )
    def test_mark_nodes_failed_after_missing_timeout_prefetches(
        self, mocker, status, failed_status
    ):
        mocker.patch.object(Node, "mark_failed")
        current_time = now()
        node, script_set = self.make_node(status)
        script_set.last_ping = current_time
        script_set.save()
        script = factory.make_Script(timeout=timedelta(seconds=60))
        factory.make_ScriptResult(
            script_set=script_set,
            status=SCRIPT_STATUS.RUNNING,
            script=script,
            started=current_time - timedelta(minutes=3),
        )

        counter_one = CountQueries()
        with counter_one, SignalsDisabled("power"):
            mark_nodes_failed_after_missing_script_timeout(current_time, 20)

        nodes = []
        for _ in range(6):
            node, script_set = self.make_node(status)
            script_set.last_ping = current_time
            script_set.save()
            script = factory.make_Script(timeout=timedelta(seconds=60))
            factory.make_ScriptResult(
                script_set=script_set,
                status=SCRIPT_STATUS.RUNNING,
                script=script,
                started=current_time - timedelta(minutes=3),
            )
            nodes.append(node)

        counter_many = CountQueries()
        with counter_many, SignalsDisabled("power"):
            mark_nodes_failed_after_missing_script_timeout(current_time, 20)

        # Lookup takes 7 queries no matter the amount of Nodes
        # 1. Get all Nodes in commissioning or testing
        # 2. Get all commissioning ScriptSets
        # 3. Get all testing ScriptSets
        # 4. Get all commissioning ScriptResults
        # 5. Get all testing ScriptResults
        # 6. Get all commissioning Scripts
        # 7. Get all testing Scripts
        assert 7 == counter_one.count
        assert 7 == counter_many.count

    def make_node(self, status):
        user = factory.make_admin()
        node = factory.make_Node(
            status=status,
            with_empty_script_sets=True,
            owner=user,
            enable_ssh=factory.pick_bool(),
        )
        if status == NODE_STATUS.COMMISSIONING:
            script_set = node.current_commissioning_script_set
        elif status == NODE_STATUS.TESTING:
            script_set = node.current_testing_script_set
        return node, script_set


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestStatusMonitorService:
    @pytest.fixture(autouse=True)
    def _load_scripts(self, maasdb):
        load_builtin_scripts()

    def test_init_with_default_interval(self, mocker):
        # The service itself calls `check_status` in a thread, via a couple of
        # decorators. This indirection makes it clearer to mock
        # `cleanup_old_nonces` here and track calls to it.
        mock_check_status = mocker.patch.object(status_monitor, "check_status")
        # Making `deferToDatabase` use the current thread helps testing.
        mocker.patch.object(status_monitor, "deferToDatabase", maybeDeferred)

        service = StatusMonitorService()
        # Use a deterministic clock instead of the reactor for testing.
        service.clock = Clock()

        # The interval is stored as `step` by TimerService,
        # StatusMonitorService's parent class.
        interval = 60  # seconds.
        assert service.step == interval

        # `check_status` is not called before the service is started.
        mock_check_status.assert_not_called()
        # `check_status` is called the moment the service is started.
        service.startService()
        mock_check_status.assert_called_once_with()
        mock_check_status.reset_mock()
        # Advancing the clock by `interval - 1` means that
        # `mark_nodes_failed_after_expiring` has still only been called once.
        service.clock.advance(interval - 1)
        mock_check_status.assert_not_called()
        # Advancing the clock one more second causes another call to
        # `check_status`.
        service.clock.advance(1)
        mock_check_status.assert_called_once_with()

    def test_failures_do_not_stop_the_timer_job(self, mocker):
        mock_check_status = mocker.patch.object(status_monitor, "check_status")
        mock_check_status.side_effect = Exception("BOOM")
        mocker.patch.object(status_monitor, "deferToDatabase", maybeDeferred)

        service = StatusMonitorService()
        # Use a deterministic clock instead of the reactor for testing.
        service.clock = Clock()

        # The interval is stored as `step` by TimerService,
        # StatusMonitorService's parent class.
        interval = 60  # seconds.
        assert service.step == interval

        service.startService()
        mock_check_status.assert_called_once_with()
        mock_check_status.reset_mock()

        # Call the function
        service.clock.advance(interval)
        mock_check_status.assert_called_once_with()
        mock_check_status.reset_mock()

        # The function should be called again even if the previous call has
        # crashed
        service.clock.advance(interval)
        mock_check_status.assert_called_once_with()

    def test_interval_can_be_set(self):
        interval = random.randint(1, 1000)
        service = StatusMonitorService(interval)
        assert interval == service.step
