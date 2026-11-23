# Copyright 2012-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import json
import random
from unittest.mock import ANY, Mock, sentinel

from django.db import transaction
from netaddr import IPNetwork
import pytest

from maascommon.events import AUDIT
from maasserver import locks
from maasserver.clusterrpc.utils import get_error_message_for_exception
from maasserver.enum import (
    INTERFACE_TYPE,
    IPADDRESS_TYPE,
    NODE_ACTION_TYPE,
    NODE_STATUS,
    NODE_STATUS_CHOICES,
    NODE_STATUS_CHOICES_DICT,
    NODE_TYPE,
    NODE_TYPE_CHOICES_DICT,
)
from maasserver.exceptions import NodeActionError
from maasserver.models import (
    Config,
    Event,
    Notification,
    ScriptSet,
    signals,
    StaticIPAddress,
)
from maasserver.models import node as node_module
from maasserver.models.signals.testing import SignalsDisabled
import maasserver.node_action as node_action_module
from maasserver.node_action import (
    Abort,
    Acquire,
    ACTION_CLASSES,
    AddTag,
    Clone,
    Commission,
    compile_node_actions,
    Delete,
    Deploy,
    ExitRescueMode,
    Lock,
    MarkBroken,
    MarkFixed,
    NodeAction,
    OverrideFailedTesting,
    PowerOff,
    PowerOn,
    Release,
    RemoveTag,
    RescueMode,
    RPC_EXCEPTIONS,
    SetPool,
    SetZone,
    Test,
    Unlock,
)
from maasserver.node_status import (
    MONITORED_STATUSES,
    NODE_TESTING_RESET_READY_TRANSITIONS,
    NON_MONITORED_STATUSES,
)
from maasserver.openfga import get_openfga_client
from maasserver.permissions import NodePermission
from maasserver.testing.architecture import make_usable_architecture
from maasserver.testing.factory import factory
from maasserver.testing.fixtures import IntroCompletedFixture
from maasserver.testing.osystems import make_usable_osystem
from maasserver.utils.orm import post_commit, post_commit_hooks, reload_object
from maastemporalworker.workflow import power as power_module
from metadataserver.builtin_scripts import load_builtin_scripts
from metadataserver.enum import (
    RESULT_TYPE,
    SCRIPT_STATUS,
    SCRIPT_STATUS_FAILED,
    SCRIPT_TYPE,
)
from provisioningserver.enum import POWER_STATE
from provisioningserver.utils.shell import ExternalProcessError

ALL_STATUSES = list(NODE_STATUS_CHOICES_DICT)


@pytest.fixture
def transactional_maasdb(maasdb):
    """Provide the database as `MAASTransactionServerTestCase` did.

    The `maasdb` fixture leaves autocommit disabled, under which
    `transaction.atomic()` only creates savepoints (subtransactions). The
    tests using this fixture need top-level transactions and real commits,
    so autocommit is restored here.

    The service-layer initialisation done by `maasdb` may leave an
    implicit transaction open on the shared connection (it cannot be
    queried while autocommit is disabled); clear it before flipping
    autocommit back on.
    """
    transaction.rollback()
    transaction.set_autocommit(True)
    yield


@pytest.fixture(autouse=True)
def _maas_server_testcase_compat(request, mocker):
    # Replicate the parts of MAASServerTestCase.setUp()/setUpFixtures() that
    # the maasdb/mock_openfga/mock_start_workflows fixtures don't cover.
    # Only applies to the converted (maasdb-marked) classes.
    marker = request.node.get_closest_marker("usefixtures")
    if marker is None or "maasdb" not in marker.args:
        yield
        return
    request.getfixturevalue("maasdb")
    # MAASServerTestCase cleared this cache after every test (via
    # OpenFGAMock); the mock_openfga fixture doesn't, so clear it here.
    get_openfga_client.cache_clear()
    # The status transition event is disconnected in tests, as done by
    # MAASRegionTestCaseBase.setUpFixtures().
    mocker.patch(
        "maasserver.models.signals.events.STATE_TRANSITION_EVENT_CONNECT",
        False,
    )
    with IntroCompletedFixture():
        yield
    get_openfga_client.cache_clear()


class _TestCaseAdapter:
    """Adapt a plain pytest class for helpers given a `TestCase` object.

    Only the `patch` and `addCleanup` methods expected by legacy test
    helpers (e.g. `make_usable_architecture`) are provided; test bodies
    should use the `mocker` fixture directly.
    """

    _mocker = None
    _request = None

    @pytest.fixture(autouse=True)
    def _testcase_adapter(self, mocker, request):
        self._mocker = mocker
        self._request = request

    def patch(self, obj, attribute=None, value=sentinel.unset):
        """Patch `obj.attribute` with `value` (a mock if unspecified)."""
        if value is sentinel.unset:
            return self._mocker.patch.object(obj, attribute)
        else:
            return self._mocker.patch.object(obj, attribute, value)

    def addCleanup(self, func, *args, **kwargs):
        """Call `func(*args, **kwargs)` once the test has finished."""
        self._request.addfinalizer(lambda: func(*args, **kwargs))


class FakeNodeAction(NodeAction):
    name = "fake"
    display = "Action label"
    actionable_statuses = ALL_STATUSES
    permission = NodePermission.view
    for_type = [NODE_TYPE.MACHINE]
    action_type = NODE_ACTION_TYPE.MISC

    fake_description = factory.make_name("desc")

    def get_node_action_audit_description(self):
        return self.fake_description

    def _execute(self):
        pass


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestNodeAction:
    def test_compile_node_actions_returns_available_actions(self):
        class MyAction(FakeNodeAction):
            name = factory.make_string()

        actions = compile_node_actions(
            factory.make_Node(), factory.make_admin(), classes=[MyAction]
        )
        assert list(actions.keys()) == [MyAction.name]

    def test_compile_node_actions_checks_node_status(self):
        class MyAction(FakeNodeAction):
            actionable_statuses = (NODE_STATUS.READY,)

        node = factory.make_Node(status=NODE_STATUS.NEW)
        actions = compile_node_actions(
            node, factory.make_admin(), classes=[MyAction]
        )
        assert actions == {}

    def test_compile_node_actions_checks_permission(self):
        class MyAction(FakeNodeAction):
            permission = NodePermission.edit

        node = factory.make_Node(
            status=NODE_STATUS.COMMISSIONING, owner=factory.make_User()
        )
        actions = compile_node_actions(
            node, factory.make_User(), classes=[MyAction]
        )
        assert actions == {}

    def test_compile_node_actions_maps_names(self):
        class Action1(FakeNodeAction):
            name = factory.make_string()

        class Action2(FakeNodeAction):
            name = factory.make_string()

        actions = compile_node_actions(
            factory.make_Node(),
            factory.make_admin(),
            classes=[Action1, Action2],
        )
        for name, action in actions.items():
            assert name == action.name

    def test_compile_node_actions_maintains_order(self):
        names = [factory.make_string() for counter in range(4)]
        classes = [
            type("Action%d" % counter, (FakeNodeAction,), {"name": name})
            for counter, name in enumerate(names)
        ]
        actions = compile_node_actions(
            factory.make_Node(), factory.make_admin(), classes=classes
        )
        assert list(actions.keys()) == names
        assert [action.name for action in list(actions.values())] == names

    def test_is_permitted_allows_if_user_has_permission(self):
        class MyAction(FakeNodeAction):
            permission = NodePermission.edit

        node = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=factory.make_User()
        )
        assert MyAction(node, node.owner).is_permitted()

    def test_is_permitted_disallows_if_user_lacks_permission(self):
        class MyAction(FakeNodeAction):
            permission = NodePermission.edit

        node = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=factory.make_User()
        )
        assert not MyAction(node, factory.make_User()).is_permitted()

    def test_is_permitted_uses_node_permission(self):
        class MyAction(FakeNodeAction):
            permission = NodePermission.view
            node_permission = NodePermission.edit

        node = factory.make_Node(
            status=NODE_STATUS.ALLOCATED, owner=factory.make_User()
        )
        assert not MyAction(node, factory.make_User()).is_permitted()

    def test_is_permitted_doest_use_node_permission_if_device(self):
        class MyAction(FakeNodeAction):
            permission = NodePermission.view
            node_permission = NodePermission.edit

        node = factory.make_Node(
            status=NODE_STATUS.ALLOCATED,
            owner=factory.make_User(),
            node_type=NODE_TYPE.DEVICE,
        )
        assert MyAction(node, factory.make_User()).is_permitted()

    def test_node_only_is_not_actionable_if_node_isnt_node_type(self):
        status = NODE_STATUS.NEW
        owner = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = owner
        node = factory.make_Node(
            owner=owner, status=status, node_type=NODE_TYPE.DEVICE
        )
        action = FakeNodeAction(node, owner, request)
        action.node_only = True
        assert not action.is_actionable()

    def test_node_only_is_actionable_if_node_type_is_node(self):
        status = NODE_STATUS.NEW
        owner = factory.make_User()
        node = factory.make_Node(
            owner=owner, status=status, node_type=NODE_TYPE.MACHINE
        )
        action = FakeNodeAction(node, owner)
        action.node_only = True
        assert action.is_actionable()

    def test_is_actionable_checks_node_status_in_actionable_status(self):
        class MyAction(FakeNodeAction):
            actionable_statuses = [NODE_STATUS.ALLOCATED]

        node = factory.make_Node(status=NODE_STATUS.BROKEN)
        assert not MyAction(node, factory.make_User()).is_actionable()

    def test_is_actionable_checks_permission(self):
        class MyAction(FakeNodeAction):
            machine_permission = NodePermission.admin

        node = factory.make_Node()
        assert not MyAction(node, factory.make_User()).is_actionable()

    def test_is_actionable_false_if_locked(self):
        class MyAction(FakeNodeAction):
            pass

        node = factory.make_Node(status=NODE_STATUS.DEPLOYED, locked=True)
        assert not MyAction(node, factory.make_User()).is_actionable()

    def test_is_actionable_true_if_allowed_when_locked(self):
        class MyAction(FakeNodeAction):
            allowed_when_locked = True

        node = factory.make_Node(status=NODE_STATUS.DEPLOYED, locked=True)
        assert MyAction(node, factory.make_User()).is_actionable()

    def test_is_actionable_no_requires_networking_by_default(self):
        node = factory.make_Node(status=NODE_STATUS.NEW)
        assert FakeNodeAction(node, factory.make_User()).is_actionable()

    def test_is_actionable_requires_networking(self):
        class MyAction(FakeNodeAction):
            requires_networking = True

        node = factory.make_Node(status=NODE_STATUS.NEW)
        assert not MyAction(node, factory.make_User()).is_actionable()

    def test_delete_action_last_for_node(self):
        node = factory.make_Node()
        actions = compile_node_actions(
            node, factory.make_admin(), classes=ACTION_CLASSES
        )
        assert list(actions)[-1] == "delete"

    def test_delete_action_last_for_controller(self):
        controller = factory.make_RackController()
        actions = compile_node_actions(
            controller, factory.make_admin(), classes=ACTION_CLASSES
        )
        assert list(actions)[-1] == "delete"


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestDeleteAction:
    def test_users_cannot_delete_controller(self):
        controller = factory.make_RackController()
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        action = Delete(controller, user, request)
        assert not action.is_permitted()

    def test_admins_can_delete_controller(self):
        controller = factory.make_RackController()
        admin = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = admin
        action = Delete(controller, admin, request)
        assert action.is_permitted()

    def test_deletes_node(self):
        node = factory.make_Node()
        admin = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = admin
        action = Delete(node, admin, request)
        action.execute()
        assert reload_object(node) is None
        audit_event = Event.objects.get(type__level=AUDIT)
        assert audit_event.description == "Deleted the '%s' '%s'." % (
            NODE_TYPE_CHOICES_DICT[node.node_type].lower(),
            node.hostname,
        )

    def test_deletes_when_primary_rack_on_vlan(self):
        # Regression test for LP:1793478.
        rack = factory.make_RackController()
        nic = factory.make_Interface(node=rack)
        vlan = nic.vlan
        vlan.primary_rack = rack
        vlan.dhcp_on = True

        with post_commit_hooks:
            vlan.save()

        admin = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = admin

        with post_commit_hooks:
            action = Delete(rack, admin, request)
            action.execute()

        assert reload_object(rack) is None


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
@pytest.mark.parametrize(
    "status",
    [
        NODE_STATUS.NEW,
        NODE_STATUS.FAILED_COMMISSIONING,
        NODE_STATUS.READY,
    ],
    ids=["NEW", "FAILED_COMMISSIONING", "READY"],
)
class TestCommissionAction:
    @pytest.fixture(autouse=True)
    def _setup(self, maasdb):
        load_builtin_scripts()

    def test_is_actionable_doesnt_require_interface_if_ipmi(self, status):
        node = factory.make_Node(status=status, power_type="ipmi")
        assert Commission(node, factory.make_admin()).is_actionable()

    def test_Commission_starts_commissioning_if_already_on(
        self, status, mocker
    ):
        node = factory.make_Node(
            interface=True,
            status=status,
            power_type="manual",
            power_state=POWER_STATE.ON,
        )
        node_start = mocker.patch.object(node, "_start")
        node_start.side_effect = lambda *args, **kwargs: post_commit()
        admin = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = admin
        action = Commission(node, admin, request)
        with post_commit_hooks:
            action.execute()
        assert node.status == NODE_STATUS.COMMISSIONING
        node_start.assert_called_once_with(
            user=admin,
            user_data_for_ephemeral_env=ANY,
            user_data_for_user_env=None,
            old_status=ANY,
            allow_power_cycle=True,
            config=ANY,
        )

    def test_Commission_starts_commissioning(self, status, mocker):
        node = factory.make_Node(
            interface=True,
            status=status,
            power_type="manual",
            power_state=POWER_STATE.OFF,
        )
        testing_scripts = [
            factory.make_Script(script_type=SCRIPT_TYPE.TESTING)
            for _ in range(3)
        ]
        script_input = {
            "smartctl-validate": {"storage": "sda"},
            "badblocks": {"storage": "sdb"},
        }
        node_start = mocker.patch.object(node, "_start")
        node_start.side_effect = lambda *args, **kwargs: post_commit()
        admin = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = admin
        action = Commission(node, admin, request)
        with post_commit_hooks:
            action.execute(
                testing_scripts=testing_scripts, script_input=script_input
            )
        script_sets = ScriptSet.objects.all().order_by("id")
        node = reload_object(node)
        assert len(script_sets) == 2
        assert node.current_commissioning_script_set_id == script_sets[0].id
        assert node.current_testing_script_set_id == script_sets[1].id
        assert node.status == NODE_STATUS.COMMISSIONING
        node_start.assert_called_once_with(
            user=admin,
            user_data_for_ephemeral_env=ANY,
            user_data_for_user_env=None,
            old_status=ANY,
            allow_power_cycle=True,
            config=ANY,
        )

    def test_Commission_logs_audit_event(self, status, mocker):
        node = factory.make_Node(
            interface=True,
            status=status,
            power_type="manual",
            power_state=POWER_STATE.OFF,
        )
        node_start = mocker.patch.object(node, "_start")
        node_start.side_effect = lambda *args, **kwargs: post_commit()
        admin = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = admin
        action = Commission(node, admin, request)
        with post_commit_hooks:
            action.execute()
        audit_event = Event.objects.get(type__level=AUDIT)
        assert (
            audit_event.description
            == "Started commissioning on '%s'." % node.hostname
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestTest:
    def test_starts_testing(self, mocker):
        node = factory.make_Node(status=NODE_STATUS.DEPLOYED)
        script = factory.make_Script(script_type=SCRIPT_TYPE.TESTING)
        enable_ssh = factory.pick_bool()
        mocker.patch.object(node, "_start").return_value = None
        admin = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = admin
        action = Test(node, admin, request)
        with post_commit_hooks:
            action.execute(
                enable_ssh=enable_ssh, testing_scripts=[script.name]
            )
        node = reload_object(node)
        assert node.status == NODE_STATUS.TESTING
        assert node.enable_ssh == enable_ssh
        assert (
            node.current_testing_script_set.scriptresult_set.first().name
            == script.name
        )
        audit_event = Event.objects.get(type__level=AUDIT)
        assert (
            audit_event.description
            == "Started testing on '%s'." % node.hostname
        )


@pytest.mark.allow_transactions
@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
class TestAbortAction:
    def test_Abort_aborts_disk_erasing(self, mocker):
        with SignalsDisabled("power"):
            with transaction.atomic():
                owner = factory.make_User()
                node = factory.make_Node(
                    status=NODE_STATUS.DISK_ERASING, owner=owner
                )
                request = factory.make_fake_request("/")
                request.user = owner

        node_stop = mocker.patch.object(node, "_stop", autospec=True)
        # Return a post-commit hook from Node.stop().
        node_stop.side_effect = lambda user: post_commit()

        with post_commit_hooks:
            with transaction.atomic():
                Abort(node, owner, request).execute()
                audit_event = Event.objects.get(type__level=AUDIT)
                assert audit_event.description == "Aborted '%s' on '%s'." % (
                    NODE_STATUS_CHOICES_DICT[node.status].lower(),
                    node.hostname,
                )

        with transaction.atomic():
            node = reload_object(node)
            assert node.status == NODE_STATUS.FAILED_DISK_ERASING

        node_stop.assert_called_once_with(owner)

    def test_Abort_aborts_commissioning(self, mocker):
        """Makes sure a COMMISSIONING node is returned to NEW status after an
        abort.
        """
        with transaction.atomic():
            node = factory.make_Node(
                interface=True,
                status=NODE_STATUS.COMMISSIONING,
                power_type="virsh",
            )
            admin = factory.make_admin()
            request = factory.make_fake_request("/")
            request.user = admin

        node_stop = mocker.patch.object(node, "_stop", autospec=True)
        # Return a post-commit hook from Node.stop().
        node_stop.side_effect = lambda user: post_commit()

        with post_commit_hooks:
            with transaction.atomic():
                Abort(node, admin, request).execute()
                audit_event = Event.objects.get(type__level=AUDIT)
                assert audit_event.description == "Aborted '%s' on '%s'." % (
                    NODE_STATUS_CHOICES_DICT[node.status].lower(),
                    node.hostname,
                )

        with transaction.atomic():
            node = reload_object(node)
            assert node.status == NODE_STATUS.NEW

        node_stop.assert_called_once_with(admin)

    def test_Abort_aborts_deployment(self, mocker):
        """Makes sure a DEPLOYING node is returned to ALLOCATED status after an
        abort.
        """
        with transaction.atomic():
            node = factory.make_Node(
                interface=True,
                status=NODE_STATUS.DEPLOYING,
                power_type="virsh",
            )
            admin = factory.make_admin()
            request = factory.make_fake_request("/")
            request.user = admin

        node_stop = mocker.patch.object(node, "_stop", autospec=True)
        temporal_stop = mocker.patch.object(node_module, "stop_workflow")
        # Return a post-commit hook from Node.stop().
        node_stop.side_effect = lambda user: post_commit()

        with post_commit_hooks:
            with transaction.atomic():
                Abort(node, admin, request).execute()
                audit_event = Event.objects.get(type__level=AUDIT)
                assert audit_event.description == "Aborted '%s' on '%s'." % (
                    NODE_STATUS_CHOICES_DICT[node.status].lower(),
                    node.hostname,
                )

        with transaction.atomic():
            node = reload_object(node)
            assert node.status == NODE_STATUS.ALLOCATED

        node_stop.assert_called_once_with(admin)
        temporal_stop.assert_called_once_with(f"deploy:{node.system_id}")

    def test_Abort_aborts_testing(self, mocker):
        """Makes sure a TESTING node is returned to previous status after an
        abort.
        """
        status = random.choice(list(NODE_TESTING_RESET_READY_TRANSITIONS))
        with transaction.atomic():
            node = factory.make_Node(
                interface=True,
                previous_status=status,
                status=NODE_STATUS.TESTING,
                power_type="virsh",
            )
            admin = factory.make_admin()
            request = factory.make_fake_request("/")
            request.user = admin

        node_stop = mocker.patch.object(node, "_stop", autospec=True)
        # Return a post-commit hook from Node.stop().
        node_stop.side_effect = lambda user: post_commit()

        with post_commit_hooks:
            with transaction.atomic():
                Abort(node, admin, request).execute()
                audit_event = Event.objects.get(type__level=AUDIT)
                assert audit_event.description == "Aborted '%s' on '%s'." % (
                    NODE_STATUS_CHOICES_DICT[node.status].lower(),
                    node.hostname,
                )

        # Allow abortion of auto testing into ready state.
        if status == NODE_STATUS.COMMISSIONING:
            status = NODE_STATUS.READY

        with transaction.atomic():
            node = reload_object(node)
            assert node.status == status

        node_stop.assert_called_once_with(admin)


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestAcquireNodeAction:
    def test_Acquire_acquires_node(self):
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.READY,
            power_type="manual",
            with_boot_disk=True,
        )
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        Acquire(node, user, request).execute()
        assert node.status == NODE_STATUS.ALLOCATED
        assert node.owner == user
        audit_event = Event.objects.get(type__level=AUDIT)
        assert audit_event.description == "Acquired '%s'." % node.hostname

    def test_Acquire_uses_node_acquire_lock(self, mocker):
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.READY,
            power_type="manual",
            with_boot_disk=True,
        )
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node_acquire = mocker.patch.object(locks, "node_acquire")
        Acquire(node, user, request).execute()
        node_acquire.__enter__.assert_called_once_with()
        node_acquire.__exit__.assert_called_once_with(None, None, None)


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestDeployAction(_TestCaseAdapter):
    @pytest.fixture(autouse=True)
    def _setup(self, maasdb):
        factory.make_RegionController()

    def test_Deploy_is_actionable_if_user_doesnt_have_ssh_keys(self):
        owner = factory.make_User()
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            owner=owner,
        )
        assert Deploy(node, owner).is_actionable()

    def test_Deploy_is_actionable_if_user_has_ssh_keys(self):
        owner = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = owner
        factory.make_SSHKey(owner)
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            owner=owner,
        )
        assert Deploy(node, owner, request).is_actionable()

    def test_Deploy_starts_node(self, mocker):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            owner=user,
        )
        mocker.patch.object(node_action_module, "get_curtin_config")
        mock_node_start = mocker.patch.object(node, "start")
        osystem, releases = make_usable_osystem(self)
        os_name = osystem
        release_name = releases[0]
        Config.objects.set_config("default_osystem", os_name)
        Config.objects.set_config("default_distro_series", release_name)
        Deploy(node, user, request).execute()
        mock_node_start.assert_called_once_with(
            user,
            user_data=None,
            enable_hw_sync=False,
        )
        audit_event = Event.objects.get(type__level=AUDIT)
        assert (
            audit_event.description
            == "Started deploying '%s'." % node.hostname
        )

    def test_Deploy_passes_user_data(self, mocker):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            owner=user,
        )
        mocker.patch.object(node_action_module, "get_curtin_config")
        mock_node_start = mocker.patch.object(node, "start")
        osystem, releases = make_usable_osystem(self)
        os_name = osystem
        release_name = releases[0]
        Config.objects.set_config("default_osystem", os_name)
        Config.objects.set_config("default_distro_series", release_name)
        extra = {"user_data": "foo: bar"}
        expected = b"foo: bar"
        Deploy(node, user, request).execute(**extra)
        mock_node_start.assert_called_once_with(
            user,
            user_data=expected,
            enable_hw_sync=False,
        )

    def test_Deploy_raises_NodeActionError_for_no_curtin_config(self, mocker):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            owner=user,
        )
        mock_get_curtin_config = mocker.patch.object(
            node_action_module, "get_curtin_config"
        )
        mock_get_curtin_config.side_effect = NodeActionError("error")
        osystem, releases = make_usable_osystem(self)
        os_name = osystem
        release_name = releases[0]
        Config.objects.set_config("default_osystem", os_name)
        Config.objects.set_config("default_distro_series", release_name)
        with pytest.raises(NodeActionError) as error:
            Deploy(node, user, request).execute()
        assert str(error.value) == "Failed to retrieve curtin config: error"

    def test_Deploy_raises_NodeActionError_for_invalid_os(self, mocker):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            owner=user,
        )
        mocker.patch.object(node, "start")
        os_name = factory.make_name("os")
        release_name = factory.make_name("release")
        extra = {"osystem": os_name, "distro_series": release_name}
        with pytest.raises(NodeActionError) as error:
            Deploy(node, user, request).execute(**extra)
        assert (
            str(error.value)
            == f"{os_name} is not a supported operating system."
        )

    def test_Deploy_sets_osystem_and_series_and_ephemeral_deploy(self, mocker):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            owner=user,
        )
        mocker.patch.object(node_action_module, "get_curtin_config")
        mocker.patch.object(node, "start")

        osystem, releases = make_usable_osystem(
            self, osystem_name="ubuntu", releases=["noble"]
        )
        os_name = osystem
        release_name = releases[0]
        extra = {
            "osystem": os_name,
            "distro_series": release_name,
            "ephemeral_deploy": True,
        }
        Deploy(node, user, request).execute(**extra)
        assert node.osystem == os_name
        assert node.distro_series == release_name
        assert node.ephemeral_deploy is True

    def test_Deploy_diskless_without_ephemeral_raises_an_exception(
        self, mocker
    ):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            owner=user,
            with_boot_disk=False,
        )
        mocker.patch.object(node_action_module, "get_curtin_config")
        mocker.patch.object(node, "start")
        osystem, releases = make_usable_osystem(
            self, osystem_name="ubuntu", releases=["focal"]
        )
        os_name = osystem
        release_name = releases[0]
        extra = {"osystem": os_name, "distro_series": release_name}
        with pytest.raises(NodeActionError) as exception:
            Deploy(node, user, request).execute(**extra)
        assert (
            str(exception.value)
            == "Can’t deploy to disk in a diskless machine. Deploy to memory must be used instead."
        )

    def test_Deploy_sets_osystem_and_series_and_ephemeral_deploy_to_default(
        self,
        mocker,
    ):
        # Regression test for LP:1822173
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            owner=user,
        )
        mocker.patch.object(node_action_module, "get_curtin_config")
        mocker.patch.object(node, "start")
        osystem, releases = make_usable_osystem(
            self, osystem_name="ubuntu", releases=["noble"]
        )
        os_name = osystem
        release_name = releases[0]
        Config.objects.set_config("default_osystem", os_name)
        Config.objects.set_config("default_distro_series", release_name)
        Deploy(node, user, request).execute()
        assert node.osystem == os_name
        assert node.distro_series == release_name
        assert node.ephemeral_deploy is False

    def test_Deploy_sets_osystem_and_series_strips_license_key_token(
        self, mocker
    ):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            owner=user,
        )
        mocker.patch.object(node_action_module, "get_curtin_config")
        mocker.patch.object(node, "start")
        osystem, releases = make_usable_osystem(self)
        os_name = osystem
        release_name = releases[0]
        extra = {"osystem": os_name, "distro_series": release_name + "*"}
        Deploy(node, user, request).execute(**extra)
        assert node.osystem == os_name
        assert node.distro_series == release_name

    def test_Deploy_allocates_node_if_node_not_already_allocated(self, mocker):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(status=NODE_STATUS.READY, with_boot_disk=True)
        mocker.patch.object(node_action_module, "get_curtin_config")
        mocker.patch.object(node, "start")
        osystem, releases = make_usable_osystem(self)
        os_name = osystem
        release_name = releases[0]
        Config.objects.set_config("default_osystem", os_name)
        Config.objects.set_config("default_distro_series", release_name)
        action = Deploy(node, user, request)
        action.execute()

        assert node.owner == user
        assert node.status == NODE_STATUS.ALLOCATED

    def test_Deploy_raises_an_error_when_enable_hw_sync_is_True_for_non_linux(
        self,
        mocker,
    ):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(status=NODE_STATUS.READY, with_boot_disk=True)
        mocker.patch.object(node_action_module, "get_curtin_config")
        mocker.patch.object(node, "start")
        osystem, releases = make_usable_osystem(self, osystem_name="windows")
        os_name = osystem
        release_name = releases[0]
        Config.objects.set_config("default_osystem", os_name)
        Config.objects.set_config("default_distro_series", release_name)
        extra = {"enable_hw_sync": True}
        action = Deploy(node, user, request)
        with pytest.raises(NodeActionError):
            action.execute(**extra)

    def test_Deploy_enable_kernel_crash_dump_default(self, mocker):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        Config.objects.set_config(name="enable_kernel_crash_dump", value=True)
        request.user = user
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            owner=user,
            cpu_count=4,
            memory=6 * 1024,
            architecture=make_usable_architecture(self, arch_name="amd64"),
        )
        mocker.patch.object(node_action_module, "get_curtin_config")
        mocker.patch.object(node, "start")

        osystem, releases = make_usable_osystem(
            self, osystem_name="ubuntu", releases=["jammy"]
        )
        os_name = osystem
        extra = {
            "osystem": os_name,
            "ephemeral_deploy": True,
        }
        Deploy(node, user, request).execute(**extra)
        assert node.osystem == os_name
        assert node.enable_kernel_crash_dump is True

    def test_Deploy_set_enable_kernel_crash_dump(self, mocker):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            owner=user,
            cpu_count=4,
            memory=6 * 1024,
            architecture=make_usable_architecture(self, arch_name="amd64"),
        )
        mocker.patch.object(node_action_module, "get_curtin_config")
        mocker.patch.object(node, "start")

        osystem, releases = make_usable_osystem(
            self, osystem_name="ubuntu", releases=["jammy"]
        )
        os_name = osystem
        extra = {"osystem": os_name, "enable_kernel_crash_dump": True}
        Deploy(node, user, request).execute(**extra)
        assert node.osystem == os_name
        assert node.enable_kernel_crash_dump is True

    def test_Deploy_set_enable_kernel_crash_dump_overrides_default(
        self, mocker
    ):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        Config.objects.set_config(name="enable_kernel_crash_dump", value=True)
        request.user = user
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            owner=user,
            cpu_count=4,
            memory=6 * 1024,
            architecture=make_usable_architecture(self, arch_name="amd64"),
        )
        mocker.patch.object(node_action_module, "get_curtin_config")
        mocker.patch.object(node, "start")

        osystem, releases = make_usable_osystem(
            self, osystem_name="ubuntu", releases=["jammy"]
        )
        os_name = osystem
        extra = {"osystem": os_name, "enable_kernel_crash_dump": False}
        Deploy(node, user, request).execute(**extra)
        assert node.osystem == os_name
        assert node.enable_kernel_crash_dump is False

    def test_Deploy_set_enable_kernel_crash_dump_requirements_not_satisfied(
        self,
        mocker,
    ):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            owner=user,
            cpu_count=3,  # not enough cpu
            memory=6 * 1024,
            architecture=make_usable_architecture(self, arch_name="amd64"),
        )
        mocker.patch.object(node_action_module, "get_curtin_config")
        mocker.patch.object(node, "start")

        osystem, releases = make_usable_osystem(
            self, osystem_name="ubuntu", releases=["jammy"]
        )
        os_name = osystem
        extra = {"osystem": os_name, "enable_kernel_crash_dump": True}
        Deploy(node, user, request).execute(**extra)
        assert node.osystem == os_name
        assert node.enable_kernel_crash_dump is False
        assert Notification.objects.filter(
            ident=f"kernel_crash_{node.system_id}"
        ).exists()

    def test_Deploy_set_enable_kernel_crash_dump_arch_invalid(
        self,
        mocker,
    ):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            owner=user,
            cpu_count=4,
            memory=6 * 1024,
            architecture="armhf/generic",
        )
        mocker.patch.object(node_action_module, "get_curtin_config")
        mocker.patch.object(node, "start")

        osystem, releases = make_usable_osystem(
            self, osystem_name="ubuntu", releases=["jammy"]
        )
        os_name = osystem
        extra = {"osystem": os_name, "enable_kernel_crash_dump": True}
        Deploy(node, user, request).execute(**extra)
        assert node.osystem == os_name
        assert node.enable_kernel_crash_dump is False
        assert Notification.objects.filter(
            ident=f"kernel_crash_{node.system_id}"
        ).exists()


@pytest.mark.allow_transactions
@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
class TestDeployActionTransactional(_TestCaseAdapter):
    """The following TestDeployAction tests require
    MAASTransactionServerTestCase, and thus, have been separated
    from the TestDeployAction above.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, transactional_maasdb, mocker):
        factory.make_RegionController()
        mocker.patch.object(node_module.Node, "_temporal_deploy")

    def test_Deploy_returns_error_when_no_more_static_IPs(self, mocker):
        load_builtin_scripts()
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        network = IPNetwork("10.0.0.0/30")
        subnet = factory.make_Subnet(cidr=str(network.cidr))
        rack_controller = factory.make_RackController()
        subnet.vlan.dhcp_on = True
        subnet.vlan.primary_rack = rack_controller

        with post_commit_hooks:
            subnet.vlan.save()

        node = factory.make_Node(
            status=NODE_STATUS.ALLOCATED,
            power_type="virsh",
            owner=user,
            power_state=POWER_STATE.OFF,
            bmc_connected_to=rack_controller,
        )
        interface = factory.make_Interface(
            INTERFACE_TYPE.PHYSICAL, node=node, vlan=subnet.vlan
        )
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.AUTO,
            ip="",
            subnet=subnet,
            interface=interface,
        )
        client = Mock()
        client.ident = rack_controller.system_id
        mocker.patch.object(
            power_module, "getAllClients", return_value=[client]
        )

        make_usable_osystem(self)

        # Pre-claim the only addresses.
        with transaction.atomic():
            with post_commit_hooks:
                StaticIPAddress.objects.allocate_new(
                    subnet, requested_address="10.0.0.1"
                )
                StaticIPAddress.objects.allocate_new(
                    subnet, requested_address="10.0.0.2"
                )
                StaticIPAddress.objects.allocate_new(
                    subnet, requested_address="10.0.0.3"
                )

        with pytest.raises(NodeActionError) as e:
            Deploy(node, user, request).execute()
        assert str(e.value) == (
            f"{node.hostname}: Failed to start, static IP addresses are exhausted."
        )
        assert node.status == NODE_STATUS.ALLOCATED


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestSetZoneAction:
    def test_SetZone_sets_zone(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        zone1 = factory.make_Zone()
        zone2 = factory.make_Zone()
        node = factory.make_Node(status=NODE_STATUS.NEW, zone=zone1)
        action = SetZone(node, user, request)
        action.execute(zone_id=zone2.id)
        assert node.zone.id == zone2.id
        audit_event = Event.objects.get(type__level=AUDIT)
        assert (
            audit_event.description
            == f"Set the zone to '{node.zone.name}' on '{node.hostname}'."
        )

    def test_is_icionable_true_for_owned_device(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        device = factory.make_Device(owner=user)
        action = SetZone(device, user, request)
        assert action.is_actionable()

    def test_is_icionable_false_not_owner(self):
        device = factory.make_Device(owner=factory.make_User())
        action = SetZone(device, factory.make_User())
        assert not action.is_actionable()


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestSetPoolAction:
    def test_SetPool_sets_pool(self):
        user = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = user
        pool1 = factory.make_ResourcePool()
        pool2 = factory.make_ResourcePool()
        node = factory.make_Node(status=NODE_STATUS.NEW, pool=pool1)
        action = SetPool(node, user, request)
        action.execute(pool_id=pool2.id)
        assert reload_object(node).pool.id == pool2.id
        audit_event = Event.objects.get(type__level=AUDIT)
        assert (
            audit_event.description
            == "Set the resource pool to '%s' on '%s'."
            % (node.pool.name, node.hostname)
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestAddTagAction:
    def test_AddTag_adds_tag(self):
        user = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = user
        tags = [factory.make_Tag(definition="") for _ in range(3)]
        node = factory.make_Node(status=NODE_STATUS.NEW)
        action = AddTag(node, user, request)
        action.execute(tags=[tag.id for tag in tags])
        assert sorted(tag.id for tag in tags) == sorted(
            reload_object(node).tags.values_list("id", flat=True)
        )

    def test_requires_admin_permission(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node()
        assert not AddTag(node, user, request).is_permitted()


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestRemoveTagAction:
    def test_RemoveTag_removes_tag(self):
        user = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = user
        tags = [factory.make_Tag(definition="") for _ in range(3)]
        node = factory.make_Node(status=NODE_STATUS.NEW)
        node.tags.set(tags)
        action = RemoveTag(node, user, request)
        action.execute(tags=[tag.id for tag in tags])
        assert not reload_object(node).tags.exists()

    def test_requires_admin_permission(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node()
        assert not RemoveTag(node, user, request).is_permitted()


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestPowerOnAction:
    def test_PowerOn_starts_node(self, mocker):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.ALLOCATED,
            power_type="manual",
            owner=user,
        )
        node_start = mocker.patch.object(node, "start")
        PowerOn(node, user, request).execute()
        node_start.assert_called_once_with(user)
        audit_event = Event.objects.get(type__level=AUDIT)
        assert audit_event.description == "Powered on '%s'." % node.hostname

    def test_PowerOn_requires_edit_permission(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(owner=factory.make_User())
        assert not user.has_perm(NodePermission.edit, node)
        assert not PowerOn(node, user, request).is_permitted()

    def test_PowerOn_is_actionable_if_node_doesnt_have_an_owner(self):
        owner = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = owner
        node = factory.make_Node(
            interface=True, status=NODE_STATUS.DEPLOYED, power_type="manual"
        )
        assert PowerOn(node, owner, request).is_actionable()

    def test_PowerOn_is_actionable_if_node_does_have_an_owner(self):
        owner = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = owner
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.DEPLOYED,
            power_type="manual",
            owner=owner,
        )
        assert PowerOn(node, owner, request).is_actionable()


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestPowerOffAction:
    def test_stops_deployed_node(self, mocker):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        params = dict(
            power_address=factory.make_ipv4_address(),
            power_user=factory.make_string(),
            power_pass=factory.make_string(),
        )
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.DEPLOYED,
            power_type="ipmi",
            owner=user,
            power_parameters=params,
        )
        node_stop = mocker.patch.object(node, "stop", autospec=True)

        PowerOff(node, user, request).execute()

        node_stop.assert_called_once_with(user, stop_mode=None)
        audit_event = Event.objects.get(type__level=AUDIT)
        assert audit_event.description == f"Powered off '{node.hostname}'."

    def test_can_stop_with_soft_stop_mode(self, mocker):
        admin = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = admin
        params = dict(
            power_address=factory.make_ipv4_address(),
            power_user=factory.make_string(),
            power_pass=factory.make_string(),
        )
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.READY,
            power_type="ipmi",
            power_parameters=params,
        )
        node_stop = mocker.patch.object(node, "stop", autospec=True)

        PowerOff(node, admin, request).execute(stop_mode="soft")

        node_stop.assert_called_once_with(admin, stop_mode="soft")

    def test_stops_Ready_node(self, mocker):
        admin = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = admin
        params = dict(
            power_address=factory.make_ipv4_address(),
            power_user=factory.make_string(),
            power_pass=factory.make_string(),
        )
        node = factory.make_Node(
            interface=True,
            status=NODE_STATUS.READY,
            power_type="ipmi",
            power_parameters=params,
        )
        node_stop = mocker.patch.object(node, "stop", autospec=True)

        PowerOff(node, admin, request).execute()

        node_stop.assert_called_once_with(admin, stop_mode=None)

    def test_actionable_for_non_monitored_states(self):
        all_statuses = NON_MONITORED_STATUSES
        results = {}
        for status in all_statuses:
            node = factory.make_Node(
                status=status,
                power_type="ipmi",
                power_parameters={"power_address": factory.make_ip_address()},
                power_state=POWER_STATE.ON,
            )
            actions = compile_node_actions(
                node, factory.make_admin(), classes=[PowerOff]
            )
            results[status] = list(actions.keys())
        expected_results = {status: [PowerOff.name] for status in all_statuses}
        assert expected_results == results, (
            "Nodes with certain statuses could not be powered off."
        )

    def test_non_actionable_for_monitored_states(self):
        all_statuses = MONITORED_STATUSES
        results = {}
        for status in all_statuses:
            node = factory.make_Node(
                status=status,
                power_type="ipmi",
                power_parameters={"power_address": factory.make_ip_address()},
                power_state=POWER_STATE.ON,
            )
            actions = compile_node_actions(
                node, factory.make_admin(), classes=[PowerOff]
            )
            results[status] = list(actions.keys())
        expected_results = {status: [] for status in all_statuses}
        assert expected_results == results, (
            "Nodes with certain statuses could be powered off."
        )

    def test_non_actionable_if_node_already_off(self):
        all_statuses = NON_MONITORED_STATUSES
        results = {}
        for status in all_statuses:
            node = factory.make_Node(
                status=status,
                power_type="ipmi",
                power_parameters={"power_address": factory.make_ip_address()},
                power_state=POWER_STATE.OFF,
            )
            actions = compile_node_actions(
                node, factory.make_admin(), classes=[PowerOff]
            )
            results[status] = list(actions.keys())
        expected_results = {status: [] for status in all_statuses}
        assert expected_results == results, (
            "Nodes already powered off can be powered off."
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestLockAction:
    def test_changes_locked_status_deployed(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(status=NODE_STATUS.DEPLOYED, owner=user)
        action = Lock(node, user, request)
        assert action.is_permitted()
        action.execute()
        assert reload_object(node).locked
        audit_event = Event.objects.get(type__level=AUDIT)
        assert audit_event.description == "Locked '%s'." % node.hostname

    def test_changes_locked_status_deploying(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(status=NODE_STATUS.DEPLOYING, owner=user)
        action = Lock(node, user, request)
        assert action.is_permitted()
        action.execute()
        assert reload_object(node).locked
        audit_event = Event.objects.get(type__level=AUDIT)
        assert audit_event.description == "Locked '%s'." % node.hostname

    def test_not_actionable_if_wrong_status(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(status=NODE_STATUS.READY, owner=user)
        action = Lock(node, user, request)
        assert not action.is_actionable()

    def test_not_actionable_if_locked(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(
            status=NODE_STATUS.DEPLOYED, owner=user, locked=True
        )
        action = Lock(node, user, request)
        assert not action.is_actionable()

    def test_not_actionable_if_not_machine(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        controller = factory.make_RackController()
        action = Lock(controller, user, request)
        assert not action.is_actionable()


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestUnlockAction:
    def test_changes_locked_status(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(locked=True, owner=user)
        action = Unlock(node, user, request)
        assert action.is_permitted()
        action.execute()
        assert not reload_object(node).locked
        audit_event = Event.objects.get(type__level=AUDIT)
        assert audit_event.description == "Unlocked '%s'." % node.hostname

    def test_not_actionable_if_not_locked(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(owner=user)
        action = Unlock(node, user, request)
        assert not action.is_actionable()

    def test_not_actionable_if_not_machine(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        controller = factory.make_RackController()
        action = Unlock(controller, user, request)
        assert not action.is_actionable()


ACTIONABLE_STATUSES = [
    NODE_STATUS.DEPLOYING,
    NODE_STATUS.FAILED_DEPLOYMENT,
    NODE_STATUS.FAILED_DISK_ERASING,
]


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
@pytest.mark.parametrize(
    "actionable_status",
    ACTIONABLE_STATUSES,
    ids=[NODE_STATUS_CHOICES_DICT[status] for status in ACTIONABLE_STATUSES],
)
class TestReleaseAction:
    def test_Release_stops_and_releases_node(self, actionable_status, mocker):
        mocker.patch.object(node_module, "stop_workflow")
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        params = dict(
            power_address=factory.make_ipv4_address(),
            power_user=factory.make_string(),
            power_pass=factory.make_string(),
        )
        node = factory.make_Node(
            interface=True,
            status=actionable_status,
            power_type="ipmi",
            power_state=POWER_STATE.ON,
            owner=user,
            power_parameters=params,
        )
        node_stop = mocker.patch.object(node, "_stop", autospec=True)

        with post_commit_hooks:
            Release(node, user, request).execute()

        assert node.status == NODE_STATUS.RELEASING
        node_stop.assert_called_once_with(user)
        audit_event = Event.objects.get(type__level=AUDIT)
        assert (
            audit_event.description
            == "Started releasing '%s'." % node.hostname
        )

    def test_Release_enters_disk_erasing(self, actionable_status, mocker):
        mocker.patch.object(node_module, "stop_workflow")
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        params = dict(
            power_address=factory.make_ipv4_address(),
            power_user=factory.make_string(),
            power_pass=factory.make_string(),
        )
        node = factory.make_Node(
            interface=True,
            status=actionable_status,
            power_type="ipmi",
            power_state=POWER_STATE.OFF,
            owner=user,
            power_parameters=params,
        )
        old_status = node.status
        node_start = mocker.patch.object(node, "_start", autospec=True)
        node_start.return_value = None

        with post_commit_hooks:
            Release(node, user, request).execute(erase=True)

        assert node.status == NODE_STATUS.DISK_ERASING
        node_start.assert_called_once_with(
            user=user,
            user_data_for_ephemeral_env=ANY,
            user_data_for_user_env=None,
            old_status=old_status,
            allow_power_cycle=True,
            config=ANY,
        )

    def test_Release_passes_secure_erase_and_quick_erase(
        self, actionable_status, mocker
    ):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        params = dict(
            power_address=factory.make_ipv4_address(),
            power_user=factory.make_string(),
            power_pass=factory.make_string(),
        )
        node = factory.make_Node(
            interface=True,
            status=actionable_status,
            power_type="ipmi",
            power_state=POWER_STATE.OFF,
            owner=user,
            power_parameters=params,
        )
        node_start_releasing = mocker.patch.object(
            node, "start_releasing", autospec=True
        )

        with post_commit_hooks:
            Release(node, user, request).execute(
                erase=True, secure_erase=True, quick_erase=True
            )

        node_start_releasing.assert_called_once_with(
            user=user,
            scripts=["wipe-disks"],
            script_input={
                "wipe-disks": {"secure_erase": True, "quick_erase": True}
            },
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestMarkBrokenAction:
    def test_changes_status(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(owner=user, status=NODE_STATUS.COMMISSIONING)
        action = MarkBroken(node, user, request)
        assert action.is_permitted()
        action.execute()
        assert reload_object(node).status == NODE_STATUS.BROKEN
        audit_event = Event.objects.get(type__level=AUDIT)
        assert audit_event.description == "Marked '%s' broken." % node.hostname

    def test_updates_error_description(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(owner=user, status=NODE_STATUS.COMMISSIONING)
        action = MarkBroken(node, user, request)
        assert action.is_permitted()
        action.execute()
        assert reload_object(node).error_description == ""

    def test_user_provided_description(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(owner=user, status=NODE_STATUS.COMMISSIONING)
        action = MarkBroken(node, user, request)
        assert action.is_permitted()
        action.execute(message="Provided broken message")
        assert (
            reload_object(node).error_description == "Provided broken message"
        )

    def test_requires_edit_permission(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(owner=factory.make_User())
        assert not MarkBroken(node, user, request).is_permitted()


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestMarkFixedAction:
    def make_commissioning_data(self, node, result=0, count=3):
        script_set = factory.make_ScriptSet(
            node=node, result_type=RESULT_TYPE.COMMISSIONING
        )
        node.current_commissioning_script_set = script_set
        node.save()
        if result == 0:
            status = SCRIPT_STATUS.PASSED
        elif result == 1:
            status = SCRIPT_STATUS.FAILED
        elif result == -1:
            status = SCRIPT_STATUS.SKIPPED
        return [
            factory.make_ScriptResult(
                script_set=script_set, exit_status=result, status=status
            )
            for _ in range(count)
        ]

    def test_changes_status(self):
        node = factory.make_Node(
            status=NODE_STATUS.BROKEN, power_state=POWER_STATE.ON
        )
        self.make_commissioning_data(node)
        self.make_commissioning_data(node, result=-1)
        user = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = user
        action = MarkFixed(node, user, request)
        assert action.is_permitted()
        action.execute()
        assert reload_object(node).status == NODE_STATUS.READY
        audit_event = Event.objects.get(type__level=AUDIT)
        assert audit_event.description == "Marked '%s' fixed." % node.hostname

    def test_raise_NodeActionError_if_on(self):
        node = factory.make_Node(
            status=NODE_STATUS.BROKEN, power_state=POWER_STATE.ON
        )
        user = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = user
        action = MarkFixed(node, user, request)
        assert action.is_permitted()
        with pytest.raises(NodeActionError):
            action.execute()

    def test_raise_NodeActionError_if_no_commissioning_results(self):
        node = factory.make_Node(
            status=NODE_STATUS.BROKEN, power_state=POWER_STATE.OFF
        )
        user = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = user
        action = MarkFixed(node, user, request)
        assert action.is_permitted()
        with pytest.raises(NodeActionError):
            action.execute()

    def test_raise_NodeActionError_if_one_commissioning_result_fails(self):
        node = factory.make_Node(
            status=NODE_STATUS.BROKEN, power_state=POWER_STATE.OFF
        )
        self.make_commissioning_data(node)
        self.make_commissioning_data(node, result=1, count=1)
        user = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = user
        action = MarkFixed(node, user, request)
        assert action.is_permitted()
        with pytest.raises(NodeActionError):
            action.execute()

    def test_raise_NodeActionError_if_multi_commissioning_result_fails(self):
        node = factory.make_Node(
            status=NODE_STATUS.BROKEN, power_state=POWER_STATE.OFF
        )
        self.make_commissioning_data(node)
        self.make_commissioning_data(node, result=1)
        user = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = user
        action = MarkFixed(node, user, request)
        assert action.is_permitted()
        with pytest.raises(NodeActionError):
            action.execute()

    def test_requires_admin_permission(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node()
        assert not MarkFixed(node, user, request).is_permitted()

    def test_not_enabled_if_not_broken(self):
        status = factory.pick_choice(
            NODE_STATUS_CHOICES, but_not=[NODE_STATUS.BROKEN]
        )
        node = factory.make_Node(status=status)
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        actions = compile_node_actions(
            node, factory.make_admin(), classes=[MarkFixed], request=request
        )
        assert actions == {}


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestOverrideFailedTesting:
    def create_script_results(self, nodes, count=5):
        script_results = []
        for node in nodes:
            script = factory.make_Script()
            for _ in range(count):
                script_set = factory.make_ScriptSet(
                    result_type=script.script_type, node=node
                )
                factory.make_ScriptResult(script=script, script_set=script_set)

            script_set = factory.make_ScriptSet(
                result_type=script.script_type, node=node
            )
            script_result = factory.make_ScriptResult(
                script=script,
                script_set=script_set,
                status=random.choice(
                    list(SCRIPT_STATUS_FAILED.union({SCRIPT_STATUS.PASSED}))
                ),
            )
            if script.script_type == SCRIPT_TYPE.TESTING and (
                script_result.status in SCRIPT_STATUS_FAILED
            ):
                script_results.append(script_result)
        return script_results

    def test_ignore_tests_sets_status_to_ready(self):
        owner = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = owner
        description = factory.make_name("error-description")
        node = factory.make_Node(
            status=NODE_STATUS.FAILED_TESTING,
            owner=owner,
            error_description=description,
            osystem="",
        )
        failed_scripts = self.create_script_results(nodes=[node])
        action = OverrideFailedTesting(node, owner, request)
        assert action.is_permitted()
        action.execute(suppress_failed_script_results=True)
        node = reload_object(node)
        assert node.status == NODE_STATUS.READY
        assert node.osystem == ""
        assert node.error_description == ""
        audit_event = Event.objects.get(type__level=AUDIT)
        assert (
            audit_event.description
            == "Overrode failed testing on '%s'." % node.hostname
        )
        for script_result in failed_scripts:
            script_result = reload_object(script_result)
            assert script_result.suppressed

    def test_ignore_tests_sets_status_to_deployed(self):
        owner = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = owner
        osystem = factory.make_name("osystem")
        description = factory.make_name("error-description")
        node = factory.make_Node(
            status=NODE_STATUS.FAILED_TESTING,
            owner=owner,
            error_description=description,
            osystem=osystem,
        )
        action = OverrideFailedTesting(node, owner, request)
        assert action.is_permitted()
        action.execute()
        node = reload_object(node)
        assert node.status == NODE_STATUS.DEPLOYED
        assert node.osystem == osystem
        assert node.error_description == ""

    def test_requires_admin(self):
        owner = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = owner
        node = factory.make_Node(
            status=NODE_STATUS.FAILED_TESTING, owner=owner
        )
        action = OverrideFailedTesting(node, owner, request)
        assert not action.is_permitted()


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestRescueModeAction:
    def test_requires_admin_permission(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node()
        assert not RescueMode(node, user, request).is_permitted()

    def test_rescue_mode_action_for_ready(self, mocker):
        user = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(owner=user, status=NODE_STATUS.READY)
        node_start_rescue_mode = mocker.patch.object(
            node, "start_rescue_mode", autospec=True
        )
        action = RescueMode(node, user, request)
        assert action.is_permitted()
        action.execute()
        node_start_rescue_mode.assert_called_once_with(user)
        audit_event = Event.objects.get(type__level=AUDIT)
        assert (
            audit_event.description
            == "Started rescue mode on '%s'." % node.hostname
        )

    def test_rescue_mode_action_for_broken(self, mocker):
        user = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(owner=user, status=NODE_STATUS.BROKEN)
        node_start_rescue_mode = mocker.patch.object(
            node, "start_rescue_mode", autospec=True
        )
        action = RescueMode(node, user, request)
        assert action.is_permitted()
        action.execute()
        node_start_rescue_mode.assert_called_once_with(user)

    def test_rescue_mode_action_for_deployed(self, mocker):
        user = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(owner=user, status=NODE_STATUS.DEPLOYED)
        node_start_rescue_mode = mocker.patch.object(
            node, "start_rescue_mode", autospec=True
        )
        action = RescueMode(node, user, request)
        assert action.is_permitted()
        action.execute()
        node_start_rescue_mode.assert_called_once_with(user)


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestExitRescueModeAction:
    def test_requires_admin_permission(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node()
        assert not ExitRescueMode(node, user, request).is_permitted()

    def test_exit_rescue_mode_action_for_ready(self, mocker):
        user = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(owner=user, status=NODE_STATUS.READY)
        node_stop_rescue_mode = mocker.patch.object(
            node, "stop_rescue_mode", autospec=True
        )
        action = ExitRescueMode(node, user, request)
        assert action.is_permitted()
        action.execute()
        node_stop_rescue_mode.assert_called_once_with(user)
        audit_event = Event.objects.get(type__level=AUDIT)
        assert (
            audit_event.description
            == "Exited rescue mode on '%s'." % node.hostname
        )

    def test_exit_rescue_mode_action_for_broken(self, mocker):
        user = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(owner=user, status=NODE_STATUS.BROKEN)
        node_stop_rescue_mode = mocker.patch.object(
            node, "stop_rescue_mode", autospec=True
        )
        action = ExitRescueMode(node, user, request)
        assert action.is_permitted()
        action.execute()
        node_stop_rescue_mode.assert_called_once_with(user)

    def test_exit_rescue_mode_action_for_deployed(self, mocker):
        user = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node(owner=user, status=NODE_STATUS.DEPLOYED)
        node_stop_rescue_mode = mocker.patch.object(
            node, "stop_rescue_mode", autospec=True
        )
        action = ExitRescueMode(node, user, request)
        assert action.is_permitted()
        action.execute()
        node_stop_rescue_mode.assert_called_once_with(user)


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestCloneAction:
    def test_admin_permission_required(self):
        user = factory.make_User()
        request = factory.make_fake_request("/")
        request.user = user
        node = factory.make_Node()
        assert not Clone(node, user, request).is_permitted()

    def test_requires_destinations(self):
        user = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = user
        source = factory.make_Machine()
        action = Clone(source, user, request)
        with pytest.raises(NodeActionError) as exception:
            action.execute(storage=True, interfaces=True)
        (error,) = exception.value.args
        assert json.loads(error)["destinations"] == [
            {"code": "required", "message": "This field is required."}
        ]

    def test_requires_storage_or_interfaces(self):
        user = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = user
        source = factory.make_Machine()
        destination1 = factory.make_Machine(
            status=NODE_STATUS.READY,
            with_boot_disk=False,
        )
        action = Clone(source, user, request)
        with pytest.raises(NodeActionError) as exception:
            action.execute(destinations=[destination1.system_id])
        (error,) = exception.value.args
        assert json.loads(error)["__all__"] == [
            {
                "code": "required",
                "message": "Either storage or interfaces must be true.",
            }
        ]

    def test_clone_action_log(self):
        user = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = user
        source = factory.make_Machine(with_boot_disk=False)
        factory.make_PhysicalBlockDevice(
            node=source, size=8 * 1024**3, name="sda"
        )
        factory.make_Interface(node=source, name="eth0")
        destination1 = factory.make_Machine(
            status=NODE_STATUS.READY,
            with_boot_disk=False,
        )
        factory.make_PhysicalBlockDevice(
            node=destination1, size=8 * 1024**3, name="sda"
        )
        factory.make_Interface(node=destination1, name="eth0")
        destination2 = factory.make_Machine(
            status=NODE_STATUS.FAILED_TESTING,
            with_boot_disk=False,
        )
        factory.make_PhysicalBlockDevice(
            node=destination2, size=8 * 1024**3, name="sda"
        )
        factory.make_Interface(node=destination2, name="eth0")

        action = Clone(source, user, request)

        with post_commit_hooks:
            action.execute(
                destinations=[destination1.system_id, destination2.system_id],
                storage=True,
                interfaces=True,
            )
        audit_event = Event.objects.get(type__level=AUDIT)
        assert audit_event.description == f"Cloning from '{source.hostname}'."

    def test_clone_errors_include_system_id(self):
        user = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = user
        source = factory.make_Machine(
            status=NODE_STATUS.READY, with_boot_disk=False
        )
        factory.make_PhysicalBlockDevice(
            node=source, size=8 * 1024**3, name="sda"
        )
        destination = factory.make_Machine(
            status=NODE_STATUS.READY, with_boot_disk=False
        )
        factory.make_PhysicalBlockDevice(
            node=destination, size=4 * 1024**3, name="sda"
        )
        action = Clone(source, user, request)
        with pytest.raises(NodeActionError) as exception:
            action.execute(
                destinations=[destination.system_id],
                storage=True,
            )
        (error,) = exception.value.args
        assert json.loads(error)["destinations"] == [
            {
                "code": "storage",
                "message": f"{destination} is invalid: destination boot disk(sda) is smaller than source boot disk(sda)",
                "system_id": destination.system_id,
            }
        ]


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
@pytest.mark.parametrize(
    "exception_class",
    RPC_EXCEPTIONS + (ExternalProcessError,),
    ids=[c.__name__ for c in RPC_EXCEPTIONS + (ExternalProcessError,)],
)
class TestActionsErrorHandling:
    """Tests for error handling in actions.

    This covers RPC exceptions and `ExternalProcessError`s.
    """

    def make_exception(self, exception_class):
        if exception_class is ExternalProcessError:
            exception = exception_class(
                1, ["cmd"], factory.make_name("exception")
            )
        else:
            exception = exception_class(factory.make_name("exception"))
        return exception

    def patch_rpc_methods(self, mocker, node, exception):
        mocker.patch.object(node, "_start", side_effect=exception)
        mocker.patch.object(node, "_stop", side_effect=exception)

    def make_action(
        self,
        action_class,
        node_status,
        power_state=None,
        node_type=NODE_TYPE.MACHINE,
    ):
        node = factory.make_Node(
            interface=True,
            status=node_status,
            power_type="manual",
            power_state=power_state,
            node_type=node_type,
        )
        admin = factory.make_admin()
        request = factory.make_fake_request("/")
        request.user = admin
        return action_class(node.as_self(), admin, request)

    def test_Commission_handles_rpc_errors(self, exception_class, mocker):
        signals.power.signals.disable()
        try:
            action = self.make_action(
                Commission, NODE_STATUS.READY, POWER_STATE.OFF
            )
            exception = self.make_exception(exception_class)
            self.patch_rpc_methods(mocker, action.node, exception)
            with pytest.raises(NodeActionError) as error:
                action.execute()
            assert str(error.value) == get_error_message_for_exception(
                action.node._start.side_effect
            )
        finally:
            signals.power.signals.enable()

    def test_Abort_handles_rpc_errors(self, exception_class, mocker):
        action = self.make_action(Abort, NODE_STATUS.DISK_ERASING)
        exception = self.make_exception(exception_class)
        self.patch_rpc_methods(mocker, action.node, exception)
        with pytest.raises(NodeActionError) as error:
            action.execute()
        assert str(error.value) == get_error_message_for_exception(
            action.node._stop.side_effect
        )

    def test_PowerOn_handles_rpc_errors(self, exception_class, mocker):
        action = self.make_action(PowerOn, NODE_STATUS.READY)
        exception = self.make_exception(exception_class)
        self.patch_rpc_methods(mocker, action.node, exception)
        with pytest.raises(NodeActionError) as error:
            action.execute()
        assert str(error.value) == get_error_message_for_exception(
            action.node._start.side_effect
        )

    def test_PowerOff_handles_rpc_errors(self, exception_class, mocker):
        action = self.make_action(PowerOff, NODE_STATUS.DEPLOYED)
        exception = self.make_exception(exception_class)
        self.patch_rpc_methods(mocker, action.node, exception)
        with pytest.raises(NodeActionError) as error:
            action.execute()
        assert str(error.value) == get_error_message_for_exception(
            action.node._stop.side_effect
        )

    def test_Release_handles_rpc_errors(self, exception_class, mocker):
        action = self.make_action(
            Release, NODE_STATUS.ALLOCATED, power_state=POWER_STATE.ON
        )
        exception = self.make_exception(exception_class)
        self.patch_rpc_methods(mocker, action.node, exception)
        with pytest.raises(NodeActionError) as error:
            action.execute()
        assert str(error.value) == get_error_message_for_exception(
            action.node._stop.side_effect
        )

    def test_RescueMode_handles_rpc_errors_for_entering_rescue_mode(
        self, exception_class, mocker
    ):
        action = self.make_action(
            RescueMode,
            random.choice(
                [
                    NODE_STATUS.READY,
                    NODE_STATUS.BROKEN,
                    NODE_STATUS.DEPLOYED,
                    NODE_STATUS.FAILED_ENTERING_RESCUE_MODE,
                ]
            ),
        )
        mocker.patch.object(
            action.node,
            "start_rescue_mode",
            side_effect=self.make_exception(exception_class),
        )
        with pytest.raises(NodeActionError) as exception:
            action.execute()
        assert str(exception.value) == get_error_message_for_exception(
            action.node.start_rescue_mode.side_effect
        )

    def test_ExitRescueMode_handles_rpc_errors_for_exiting_rescue_mode(
        self, exception_class, mocker
    ):
        action = self.make_action(
            ExitRescueMode,
            random.choice(
                [
                    NODE_STATUS.RESCUE_MODE,
                    NODE_STATUS.ENTERING_RESCUE_MODE,
                    NODE_STATUS.FAILED_ENTERING_RESCUE_MODE,
                    NODE_STATUS.FAILED_EXITING_RESCUE_MODE,
                ]
            ),
        )
        mocker.patch.object(
            action.node,
            "stop_rescue_mode",
            side_effect=self.make_exception(exception_class),
        )
        with pytest.raises(NodeActionError) as exception:
            action.execute()
        assert str(exception.value) == get_error_message_for_exception(
            action.node.stop_rescue_mode.side_effect
        )
