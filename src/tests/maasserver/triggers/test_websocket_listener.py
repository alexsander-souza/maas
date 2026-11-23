# Copyright 2015-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from contextlib import contextmanager
import logging
import random

from django.db import connection
from netaddr import IPAddress
import pytest
from twisted.internet.defer import DeferredList, DeferredQueue, inlineCallbacks

from maasserver.enum import IPADDRESS_TYPE, IPRANGE_TYPE, NODE_TYPE
from maasserver.listener import PostgresListenerService
from maasserver.models import ControllerInfo, Node, OwnerData
from maasserver.models.blockdevice import MIN_BLOCK_DEVICE_SIZE
from maasserver.models.partition import MIN_PARTITION_SIZE
from maasserver.storage_layouts import MIN_BOOT_PARTITION_SIZE
from maasserver.testing.factory import factory
from maasserver.triggers.testing import TransactionalHelpersMixin
from maasserver.utils.threads import deferToDatabase
from maastesting.crochet import wait_for
from metadataserver.builtin_scripts import load_builtin_scripts
from metadataserver.enum import SCRIPT_STATUS
from provisioningserver.utils.snap import SnapVersionsInfo
from provisioningserver.utils.twisted import (
    asynchronous,
    DeferredValue,
    deferWithTimeout,
    FOREVER,
    synchronous,
)

wait_for_reactor = wait_for()


@synchronous
@contextmanager
def listenFor(channel):
    """Context manager to start and stop a listener service.

    The context object returned is a callable that returns a captured value.
    If you want to capture more than one value, call the callable more than
    once.

    Note that database changes MUST be committed for the listener to receive
    notifications. If you find that the returned callable times-out, consider
    if you've committed all changes to the database!

    A convenient way to deal with this is `MAASTransactionServerTestCase`
    which will mean you're running auto-commit by default.
    """
    listener = PostgresListenerService()
    values = DeferredQueue()

    def capture(*args):
        values.put(args)

    @asynchronous(timeout=10)
    def start():
        listener.register(channel, capture)
        return listener.startService()

    @asynchronous(timeout=10)
    def stop():
        return listener.stopService()

    @asynchronous(timeout=FOREVER)
    def get(timeout=2):
        return deferWithTimeout(timeout, values.get)

    start()
    try:
        yield get
    finally:
        stop()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.parametrize(
    "params, listener_channel",
    [
        pytest.param(
            {
                "node_type": NODE_TYPE.MACHINE,
                # This is needed to avoid updating the node after creating it
                "with_boot_disk": False,
            },
            "machine",
            id="machine",
        ),
        pytest.param({"node_type": NODE_TYPE.DEVICE}, "device", id="device"),
        pytest.param(
            {"node_type": NODE_TYPE.RACK_CONTROLLER}, "controller", id="rack"
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_AND_RACK_CONTROLLER},
            "controller",
            id="region_and_rack",
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_CONTROLLER},
            "controller",
            id="region",
        ),
    ],
)
class TestNodeListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers code."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create_notification(
        self, params, listener_channel
    ):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            node = yield deferToDatabase(self.create_node, params)
            yield dv.get(timeout=2)
            assert (("create", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_update_notification(
        self, params, listener_channel
    ):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        node = yield deferToDatabase(self.create_node, params)
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_node,
                node.system_id,
                {"hostname": factory.make_name("hostname")},
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_description_update(
        self, params, listener_channel
    ):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        node = yield deferToDatabase(self.create_node, params)
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_node,
                node.system_id,
                {"description": factory.make_name("hostname")},
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_delete_notification(
        self, params, listener_channel
    ):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        node = yield deferToDatabase(self.create_node, params)
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_node, node.system_id)
            yield dv.get(timeout=2)
            assert (("delete", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_domain_name_change(
        self, params, listener_channel
    ):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        domain = yield deferToDatabase(self.create_domain, {})
        params = params.copy()
        params["domain"] = domain
        yield deferToDatabase(self.create_node, params)
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_domain,
                domain.id,
                {"name": factory.make_name("name")},
            )
            yield dv.get(timeout=2)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_all_handler_on_domain_name_change(
        self, params, listener_channel
    ):
        listener = self.make_listener_without_delay()
        dvs = DeferredValue()
        domain = yield deferToDatabase(self.create_domain, {})
        params = params.copy()
        params["domain"] = domain
        dvs = []
        nodes = set()
        for _ in range(3):
            node = yield deferToDatabase(self.create_node, params)
            nodes.add(node)
            dvs.append(DeferredValue())
        save_dvs = dvs[:]
        listener.register(listener_channel, lambda *args: dvs.pop().set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_domain,
                domain.id,
                {"name": factory.make_name("name")},
            )
            results = yield DeferredList(dv.get(timeout=2) for dv in save_dvs)
            assert sorted(
                {("update", node.system_id) for node in nodes}
            ) == sorted({res for (suc, res) in results})
        finally:
            yield listener.stopService()

    def test_expected_number_of_fields_watched(self, params, listener_channel):
        triggers = [
            "node_region_controller_update_notify",
            "node_machine_update_notify",
            "node_device_update_notify",
            "node_rack_controller_update_notify",
            "node_region_and_rack_controller_update_notify",
        ]
        table_name = "maasserver_node"

        for trigger_name in triggers:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT pg_get_triggerdef(t.oid)
                    FROM pg_trigger t
                    JOIN pg_class c ON c.oid = t.tgrelid
                    WHERE t.tgname = %s
                      AND c.relname = %s
                    """,
                    [trigger_name, table_name],
                )
                row = cursor.fetchone()

            assert (row) is not None

            trigger_def = row[0]

            count = trigger_def.count("IS DISTINCT FROM")

            assert (26) == (count), (
                "Any field listed here will be monitored for changes causing "
                "the UI on all clients to refresh this node object. This is "
                "costly! Only fields which are visible in the UI, and not listed "
                f"in other handlers should be listed here. Please check the trigger {trigger_name}."
            )


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.parametrize(
    "params, listener_channel",
    [
        pytest.param(
            {"node_type": NODE_TYPE.RACK_CONTROLLER}, "controller", id="rack"
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_AND_RACK_CONTROLLER},
            "controller",
            id="region_and_rack",
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_CONTROLLER},
            "controller",
            id="region",
        ),
    ],
)
class TestControllerListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers code."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    def set_version(self, controller, version):
        ControllerInfo.objects.set_version(controller, version)

    def set_versions_info(self, controller, versions_info):
        ControllerInfo.objects.set_versions_info(controller, versions_info)

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_controllerinfo_insert(
        self, params, listener_channel
    ):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        controller = yield deferToDatabase(self.create_node, params)
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.set_version, controller, "2.10.0")
            yield dv.get(timeout=2)
            assert (("update", controller.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_controllerinfo_version_update(
        self, params, listener_channel
    ):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        controller = yield deferToDatabase(self.create_node, params)
        yield deferToDatabase(self.set_version, controller, "2.10.0")
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.set_version, controller, "2.10.1")
            yield dv.get(timeout=2)
            assert (("update", controller.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_controllerinfo_versionsinfo_update(
        self, params, listener_channel
    ):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        controller = yield deferToDatabase(self.create_node, params)
        # first set the version
        yield deferToDatabase(self.set_version, controller, "3.0.0")
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            # update other fields but keep the same version
            yield deferToDatabase(
                self.set_versions_info,
                controller,
                SnapVersionsInfo(
                    current={"version": "3.0.0", "revision": "1234"}
                ),
            )
            yield dv.get(timeout=2)
            assert (("update", controller.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_controllerinfo_delete(
        self, params, listener_channel
    ):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        controller = yield deferToDatabase(self.create_node, params)
        yield deferToDatabase(self.set_version, controller, "2.10.0")
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(controller.controllerinfo.delete)
            yield dv.get(timeout=2)
            assert (("update", controller.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestDeviceWithParentListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers code."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("machine", lambda *args: dv.set(args))
        parent = yield deferToDatabase(self.create_node)
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.create_node,
                {"node_type": NODE_TYPE.DEVICE, "parent": parent},
            )
            yield dv.get(timeout=2)
            assert (("update", parent.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_update_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("machine", lambda *args: dv.set(args))
        device, parent = yield deferToDatabase(self.create_device_with_parent)
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_node,
                device.system_id,
                {"hostname": factory.make_name("hostname")},
            )
            yield dv.get(timeout=2)
            assert (("update", parent.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_delete_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("machine", lambda *args: dv.set(args))
        device, parent = yield deferToDatabase(self.create_device_with_parent)
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_node, device.system_id)
            yield dv.get(timeout=2)
            assert (("update", parent.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestTagListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the tag
    triggers code."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("tag", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            tag = yield deferToDatabase(self.create_tag)
            yield dv.get(timeout=2)
            assert (("create", str(tag.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_update_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("tag", lambda *args: dv.set(args))
        tag = yield deferToDatabase(self.create_tag)

        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_tag, tag.id, {"name": factory.make_name("tag")}
            )
            yield dv.get(timeout=2)
            assert (("update", str(tag.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_delete_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("tag", lambda *args: dv.set(args))
        tag = yield deferToDatabase(self.create_tag)
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_tag, tag.id)
            yield dv.get(timeout=2)
            assert (("delete", str(tag.id))) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.parametrize(
    "params, listener_channel",
    [
        pytest.param(
            {"node_type": NODE_TYPE.MACHINE}, "machine", id="machine"
        ),
        pytest.param({"node_type": NODE_TYPE.DEVICE}, "device", id="device"),
        pytest.param(
            {"node_type": NODE_TYPE.RACK_CONTROLLER}, "controller", id="rack"
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_AND_RACK_CONTROLLER},
            "controller",
            id="region_and_rack",
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_CONTROLLER},
            "controller",
            id="region",
        ),
    ],
)
class TestNodeTagListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_node_tags table."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_create(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        tag = yield deferToDatabase(self.create_tag)

        listener = self.make_listener_without_delay()
        node_dv = DeferredValue()
        listener.register(listener_channel, lambda *args: node_dv.set(args))
        tag_dv = DeferredValue()
        listener.register("tag", lambda *args: tag_dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.add_node_to_tag, node, tag)
            yield node_dv.get(timeout=2)
            assert (("update", node.system_id)) == (node_dv.value)
            yield tag_dv.get(timeout=2)
            assert (("update", str(tag.id))) == (tag_dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_delete(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        tag = yield deferToDatabase(self.create_tag)
        yield deferToDatabase(self.add_node_to_tag, node, tag)

        listener = self.make_listener_without_delay()
        node_dv = DeferredValue()
        tag_dv = DeferredValue()
        listener.register("tag", lambda *args: tag_dv.set(args))
        listener.register(listener_channel, lambda *args: node_dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.remove_node_from_tag, node, tag)
            yield node_dv.get(timeout=2)
            assert (("update", node.system_id)) == (node_dv.value)
            yield tag_dv.get(timeout=2)
            assert (("update", str(tag.id))) == (tag_dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_node_handler_with_update_on_tag_rename(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        tag = yield deferToDatabase(self.create_tag)
        yield deferToDatabase(self.add_node_to_tag, node, tag)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            tag = yield deferToDatabase(
                self.update_tag, tag.id, {"name": factory.make_name("tag")}
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.parametrize(
    "params, listener_channel",
    [
        pytest.param(
            {"node_type": NODE_TYPE.MACHINE}, "machine", id="machine"
        ),
        pytest.param({"node_type": NODE_TYPE.DEVICE}, "device", id="device"),
        pytest.param(
            {"node_type": NODE_TYPE.RACK_CONTROLLER}, "controller", id="rack"
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_AND_RACK_CONTROLLER},
            "controller",
            id="region_and_rack",
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_CONTROLLER},
            "controller",
            id="region",
        ),
    ],
)
class TestOwnerDataTriggers(TransactionalHelpersMixin):
    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_create(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                OwnerData.objects.set_owner_data, node, {"foo": "baz"}
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_update(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield deferToDatabase(
            OwnerData.objects.set_owner_data, node, {"foo": "bar"}
        )
        yield listener.startService()
        try:
            yield deferToDatabase(
                OwnerData.objects.set_owner_data, node, {"foo": "baz"}
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_replace(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield deferToDatabase(
            OwnerData.objects.set_owner_data, node, {"foo": "bar"}
        )
        yield listener.startService()
        try:
            yield deferToDatabase(
                OwnerData.objects.set_owner_data, node, {"new": "value"}
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.parametrize(
    "params, listener_channel",
    [
        pytest.param(
            {"node_type": NODE_TYPE.MACHINE}, "machine", id="machine"
        ),
        pytest.param({"node_type": NODE_TYPE.DEVICE}, "device", id="device"),
        pytest.param(
            {"node_type": NODE_TYPE.RACK_CONTROLLER}, "controller", id="rack"
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_AND_RACK_CONTROLLER},
            "controller",
            id="region_and_rack",
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_CONTROLLER},
            "controller",
            id="region",
        ),
    ],
)
class TestNodeMetadataTriggers(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_node_tags table."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_create(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.set_node_metadata, node, "foo", "bar")
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_update(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield deferToDatabase(self.set_node_metadata, node, "foo", "bar")
        yield listener.startService()
        try:
            yield deferToDatabase(self.set_node_metadata, node, "foo", "baz")
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_delete(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield deferToDatabase(self.set_node_metadata, node, "foo", "bar")
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_node_metadata, node, "foo")
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestDeviceWithParentTagListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_node_tags table."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_create(self):
        device, parent = yield deferToDatabase(self.create_device_with_parent)
        tag = yield deferToDatabase(self.create_tag)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("machine", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.add_node_to_tag, device, tag)
            yield dv.get(timeout=2)
            assert (("update", parent.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_delete(self):
        device, parent = yield deferToDatabase(self.create_device_with_parent)
        tag = yield deferToDatabase(self.create_tag)
        yield deferToDatabase(self.add_node_to_tag, device, tag)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("machine", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.remove_node_from_tag, device, tag)
            yield dv.get(timeout=2)
            assert (("update", parent.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_node_handler_with_update_on_tag_rename(self):
        device, parent = yield deferToDatabase(self.create_device_with_parent)
        tag = yield deferToDatabase(self.create_tag)
        yield deferToDatabase(self.add_node_to_tag, device, tag)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("machine", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            tag = yield deferToDatabase(
                self.update_tag, tag.id, {"name": factory.make_name("tag")}
            )
            yield dv.get(timeout=2)
            assert (("update", parent.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestEventListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the event
    triggers code."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("event", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            event = yield deferToDatabase(self.create_event)
            yield dv.get(timeout=2)
            assert (("create", str(event.id))) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.parametrize(
    "params, listener_channel",
    [
        pytest.param(
            {"node_type": NODE_TYPE.MACHINE}, "machine", id="machine"
        ),
        pytest.param(
            {"node_type": NODE_TYPE.RACK_CONTROLLER}, "controller", id="rack"
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_AND_RACK_CONTROLLER},
            "controller",
            id="region_and_rack",
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_CONTROLLER},
            "controller",
            id="region",
        ),
    ],
)
class TestNodeEventListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_event table that notifies its node."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_create(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        event_type = yield deferToDatabase(
            self.create_event_type, {"level": logging.INFO}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.create_event, {"node": node, "type": event_type}
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.parametrize(
    "params, listener_channel",
    [
        pytest.param(
            {"node_type": NODE_TYPE.MACHINE, "interface": True},
            "machine",
            id="machine",
        ),
        pytest.param(
            {"node_type": NODE_TYPE.DEVICE, "interface": True},
            "device",
            id="device",
        ),
        pytest.param(
            {
                "node_type": NODE_TYPE.RACK_CONTROLLER,
                "interface": True,
            },
            "controller",
            id="rack",
        ),
        pytest.param(
            {
                "node_type": NODE_TYPE.REGION_AND_RACK_CONTROLLER,
                "interface": True,
            },
            "controller",
            id="region_and_rack",
        ),
        pytest.param(
            {
                "node_type": NODE_TYPE.REGION_CONTROLLER,
                "interface": True,
            },
            "controller",
            id="region",
        ),
    ],
)
class TestNodeStaticIPAddressListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_interfacestaticipaddresslink table that notifies its node."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_create(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        interface = yield deferToDatabase(
            self.get_node_boot_interface, node.system_id
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.create_staticipaddress, {"interface": interface}
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_delete(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        interface = yield deferToDatabase(
            self.get_node_boot_interface, node.system_id
        )
        sip = yield deferToDatabase(
            self.create_staticipaddress, {"interface": interface}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_staticipaddress, sip.id)
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestDeviceWithParentStaticIPAddressListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_interfacestaticipaddresslink table that notifies its node."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_create(self):
        device, parent = yield deferToDatabase(
            self.create_device_with_parent, {"interface": True}
        )
        interface = yield deferToDatabase(
            self.get_node_boot_interface, device.system_id
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("machine", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.create_staticipaddress, {"interface": interface}
            )
            yield dv.get(timeout=2)
            assert (("update", parent.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_delete(self):
        device, parent = yield deferToDatabase(
            self.create_device_with_parent, {"interface": True}
        )
        interface = yield deferToDatabase(
            self.get_node_boot_interface, device.system_id
        )
        sip = yield deferToDatabase(
            self.create_staticipaddress, {"interface": interface}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("machine", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_staticipaddress, sip.id)
            yield dv.get(timeout=2)
            assert (("update", parent.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.parametrize(
    "params, listener_channel",
    [
        pytest.param(
            {"node_type": NODE_TYPE.MACHINE}, "machine", id="machine"
        ),
        pytest.param({"node_type": NODE_TYPE.DEVICE}, "device", id="device"),
        pytest.param(
            {"node_type": NODE_TYPE.RACK_CONTROLLER}, "controller", id="rack"
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_AND_RACK_CONTROLLER},
            "controller",
            id="region_and_rack",
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_CONTROLLER},
            "controller",
            id="region",
        ),
    ],
)
class TestScriptSetListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_scriptset table that notifies its node."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_create(
        self, params, listener_channel
    ):
        yield deferToDatabase(load_builtin_scripts)
        node = yield deferToDatabase(self.create_node, params)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.create_scriptset, node)
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_delete(
        self, params, listener_channel
    ):
        yield deferToDatabase(load_builtin_scripts)
        node = yield deferToDatabase(self.create_node, params)
        result = yield deferToDatabase(self.create_scriptset, node)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_scriptset, result)
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestDeviceWithParentScriptSetListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_scriptset table that notifies its node."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_create(self):
        yield deferToDatabase(load_builtin_scripts)
        device, parent = yield deferToDatabase(self.create_device_with_parent)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("machine", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.create_scriptset, device)
            yield dv.get(timeout=2)
            assert (("update", parent.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_delete(self):
        yield deferToDatabase(load_builtin_scripts)
        device, parent = yield deferToDatabase(self.create_device_with_parent)
        result = yield deferToDatabase(self.create_scriptset, device)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("machine", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_scriptset, result)
            yield dv.get(timeout=2)
            assert (("update", parent.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.parametrize(
    "params, listener_channel",
    [
        pytest.param(
            {"node_type": NODE_TYPE.MACHINE}, "machine", id="machine"
        ),
        pytest.param({"node_type": NODE_TYPE.DEVICE}, "device", id="device"),
        pytest.param(
            {"node_type": NODE_TYPE.RACK_CONTROLLER}, "controller", id="rack"
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_AND_RACK_CONTROLLER},
            "controller",
            id="region_and_rack",
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_CONTROLLER},
            "controller",
            id="region",
        ),
    ],
)
class TestNDScriptResultListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_scriptresult table that notifies its node."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_create(
        self, params, listener_channel
    ):
        yield deferToDatabase(load_builtin_scripts)
        node = yield deferToDatabase(self.create_node, params)
        script_set = yield deferToDatabase(self.create_scriptset, node)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.create_scriptresult, script_set)
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_update(
        self, params, listener_channel
    ):
        yield deferToDatabase(load_builtin_scripts)
        node = yield deferToDatabase(self.create_node, params)
        script_set = yield deferToDatabase(self.create_scriptset, node)
        script_result = yield deferToDatabase(
            self.create_scriptresult,
            script_set,
            {"status": SCRIPT_STATUS.PENDING},
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(script_result.store_result, 0)
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_delete(
        self, params, listener_channel
    ):
        yield deferToDatabase(load_builtin_scripts)
        node = yield deferToDatabase(self.create_node, params)
        script_set = yield deferToDatabase(self.create_scriptset, node)
        script_result = yield deferToDatabase(
            self.create_scriptresult, script_set
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_scriptresult, script_result)
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestScriptResultListener(TransactionalHelpersMixin):
    """End-to-end test of both the listers code and the triggers on
    the maasserver_scriptresult table that notifies the node-results
    websocket."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_create(self):
        yield deferToDatabase(load_builtin_scripts)
        node = yield deferToDatabase(self.create_node)
        script_set = yield deferToDatabase(self.create_scriptset, node)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("scriptresult", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            script_result = yield deferToDatabase(
                self.create_scriptresult, script_set
            )
            yield dv.get(timeout=2)
            assert (("create", str(script_result.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_update(self):
        yield deferToDatabase(load_builtin_scripts)
        node = yield deferToDatabase(self.create_node)
        script_set = yield deferToDatabase(self.create_scriptset, node)
        script_result = yield deferToDatabase(
            self.create_scriptresult,
            script_set,
            {"status": SCRIPT_STATUS.PENDING},
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("scriptresult", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(script_result.store_result, 0)
            yield dv.get(timeout=2)
            assert (("update", str(script_result.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_delete(self):
        yield deferToDatabase(load_builtin_scripts)
        node = yield deferToDatabase(self.create_node)
        script_set = yield deferToDatabase(self.create_scriptset, node)
        script_result = yield deferToDatabase(
            self.create_scriptresult, script_set
        )
        script_result_id = script_result.id

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("scriptresult", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_scriptresult, script_result)
            yield dv.get(timeout=2)
            assert (("delete", str(script_result_id))) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.parametrize(
    "params, listener_channel",
    [
        pytest.param(
            {"node_type": NODE_TYPE.MACHINE}, "machine", id="machine"
        ),
        pytest.param({"node_type": NODE_TYPE.DEVICE}, "device", id="device"),
        pytest.param(
            {"node_type": NODE_TYPE.RACK_CONTROLLER}, "controller", id="rack"
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_AND_RACK_CONTROLLER},
            "controller",
            id="region_and_rack",
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_CONTROLLER},
            "controller",
            id="region",
        ),
    ],
)
class TestNodeInterfaceListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_interface table that notifies its node."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_create(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.create_interface, {"node": node})
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_delete(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        interface = yield deferToDatabase(
            self.create_interface, {"node": node}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_interface, interface.id)
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @pytest.mark.skip(
        reason="XXX: LaMontJones 2016-06-14 bug=1592474: Fails spuriously."
    )
    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_update(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        interface = yield deferToDatabase(
            self.create_interface, {"node": node}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_interface,
                interface.id,
                {"mac_address": factory.make_mac_address()},
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_old_node_on_update(
        self, params, listener_channel
    ):
        node1 = yield deferToDatabase(self.create_node, params)
        node2 = yield deferToDatabase(self.create_node, params)
        interface = yield deferToDatabase(
            self.create_interface, {"node": node1}
        )
        dvs = [DeferredValue(), DeferredValue()]

        def set_defer_value(*args):
            for dv in dvs:
                if not dv.isSet:
                    dv.set(args)
                    break

        listener = self.make_listener_without_delay()
        listener.register(listener_channel, set_defer_value)
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_interface,
                interface.id,
                {"node_config": node2.current_config},
            )
            yield dvs[0].get(timeout=2)
            yield dvs[1].get(timeout=2)
            assert sorted(
                [
                    ("update", node1.system_id),
                    ("update", node2.system_id),
                ]
            ) == sorted([dvs[0].value, dvs[1].value])
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestDeviceWithParentInterfaceListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_interface table that notifies its node."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_create(self):
        device, parent = yield deferToDatabase(self.create_device_with_parent)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("machine", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.create_interface, {"node": device})
            yield dv.get(timeout=2)
            assert (("update", parent.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_delete(self):
        device, parent = yield deferToDatabase(self.create_device_with_parent)
        interface = yield deferToDatabase(
            self.create_interface, {"node": device}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("machine", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_interface, interface.id)
            yield dv.get(timeout=2)
            assert (("update", parent.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_update(self):
        device, parent = yield deferToDatabase(self.create_device_with_parent)
        interface = yield deferToDatabase(
            self.create_interface, {"node": device}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("machine", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_interface,
                interface.id,
                {"mac_address": factory.make_mac_address()},
            )
            yield dv.get(timeout=2)
            assert (("update", parent.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_old_node_on_update(self):
        device1, parent1 = yield deferToDatabase(
            self.create_device_with_parent
        )
        device2, parent2 = yield deferToDatabase(
            self.create_device_with_parent
        )
        interface = yield deferToDatabase(
            self.create_interface, {"node": device1}
        )
        dvs = [DeferredValue(), DeferredValue()]

        def set_defer_value(*args):
            for dv in dvs:
                if not dv.isSet:
                    dv.set(args)
                    break

        listener = self.make_listener_without_delay()
        listener.register("machine", set_defer_value)
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_interface,
                interface.id,
                {"node_config": device2.current_config},
            )
            yield dvs[0].get(timeout=2)
            yield dvs[1].get(timeout=2)
            assert sorted(
                [
                    ("update", parent1.system_id),
                    ("update", parent2.system_id),
                ]
            ) == sorted([dvs[0].value, dvs[1].value])
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestFabricListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the cluster
    triggers code."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create_notification_with_blank_name(self):
        listener = self.make_listener_without_delay()
        dvs = [DeferredValue(), DeferredValue()]
        save_dvs = dvs[:]
        listener.register("fabric", lambda *args: dvs.pop().set(args))
        yield listener.startService()
        try:
            fabric = yield deferToDatabase(self.create_fabric)
            results = yield DeferredList(dv.get(timeout=2) for dv in save_dvs)
            assert sorted(
                [("create", str(fabric.id)), ("update", str(fabric.id))]
            ) == sorted([res for (suc, res) in results])
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create_notification_with_name(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("fabric", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            fabric = yield deferToDatabase(
                self.create_fabric, {"name": factory.make_name("name")}
            )
            yield dv.get(timeout=2)
            assert (("create", str(fabric.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_update_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("fabric", lambda *args: dv.set(args))
        fabric = yield deferToDatabase(self.create_fabric)

        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_fabric,
                fabric.id,
                {"name": factory.make_name("name")},
            )
            yield dv.get(timeout=2)
            assert (("update", str(fabric.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_delete_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("fabric", lambda *args: dv.set(args))
        fabric = yield deferToDatabase(self.create_fabric)
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_fabric, fabric.id)
            yield dv.get(timeout=2)
            assert (("delete", str(fabric.id))) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestVLANListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the cluster
    triggers code."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create_notification(self):
        fabric = yield deferToDatabase(self.create_fabric)
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("vlan", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            vlan = yield deferToDatabase(self.create_vlan, {"fabric": fabric})
            yield dv.get(timeout=2)
            assert (("create", str(vlan.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_update_notification(self):
        fabric = yield deferToDatabase(self.create_fabric)
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("vlan", lambda *args: dv.set(args))
        vlan = yield deferToDatabase(self.create_vlan, {"fabric": fabric})

        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_vlan, vlan.id, {"name": factory.make_name("name")}
            )
            yield dv.get(timeout=2)
            assert (("update", str(vlan.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_delete_notification(self):
        fabric = yield deferToDatabase(self.create_fabric)
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("vlan", lambda *args: dv.set(args))
        vlan = yield deferToDatabase(self.create_vlan, {"fabric": fabric})
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_vlan, vlan.id)
            yield dv.get(timeout=2)
            assert (("delete", str(vlan.id))) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestIPRangeListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the cluster
    triggers code."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("iprange", lambda *args: dv.set(args))
        network = factory.make_ipv4_network()
        subnet = yield deferToDatabase(
            self.create_subnet, {"cidr": str(network)}
        )
        params = {
            "subnet": subnet,
            "start_ip": IPAddress(network.first + 2),
            "end_ip": IPAddress(network.last - 1),
        }
        yield listener.startService()
        try:
            iprange = yield deferToDatabase(self.create_iprange, params)
            yield dv.get(timeout=2)
            assert (("create", str(iprange.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_update_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("iprange", lambda *args: dv.set(args))
        iprange = yield deferToDatabase(self.create_iprange)
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_iprange,
                iprange.id,
                {"comment": factory.make_name("name")},
            )
            yield dv.get(timeout=2)
            assert (("update", str(iprange.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_delete_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("iprange", lambda *args: dv.set(args))
        iprange = yield deferToDatabase(self.create_iprange)
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_iprange, iprange.id)
            yield dv.get(timeout=2)
            assert (("delete", str(iprange.id))) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestStaticRouteListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the cluster
    triggers code."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("staticroute", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            staticroute = yield deferToDatabase(self.create_staticroute)
            yield dv.get(timeout=2)
            assert (("create", str(staticroute.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_update_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("staticroute", lambda *args: dv.set(args))
        staticroute = yield deferToDatabase(
            self.create_staticroute, {"metric": 9}
        )
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_staticroute,
                staticroute.id,
                {"metric": random.randint(10, 500)},
            )
            yield dv.get(timeout=2)
            assert (("update", str(staticroute.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_delete_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("staticroute", lambda *args: dv.set(args))
        staticroute = yield deferToDatabase(self.create_staticroute)
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_staticroute, staticroute.id)
            yield dv.get(timeout=2)
            assert (("delete", str(staticroute.id))) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestDomainListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the cluster
    triggers code."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("domain", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            domain = yield deferToDatabase(self.create_domain)
            yield dv.get(timeout=2)
            assert (("create", str(domain.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_update_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("domain", lambda *args: dv.set(args))
        domain = yield deferToDatabase(self.create_domain)

        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_domain,
                domain.id,
                {"name": factory.make_name("name")},
            )
            yield dv.get(timeout=2)
            assert (("update", str(domain.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_delete_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("domain", lambda *args: dv.set(args))
        domain = yield deferToDatabase(self.create_domain)
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_domain, domain.id)
            yield dv.get(timeout=2)
            assert (("delete", str(domain.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_ip_address_update(self):
        domain = yield deferToDatabase(self.create_domain)
        params = {"node_type": NODE_TYPE.MACHINE, "domain": domain}
        node = yield deferToDatabase(self.create_node, params)
        interface = yield deferToDatabase(
            self.create_interface, {"node": node}
        )
        subnet = yield deferToDatabase(self.create_subnet)
        ipaddress = yield deferToDatabase(
            self.create_staticipaddress,
            {
                "alloc_type": IPADDRESS_TYPE.AUTO,
                "interface": interface,
                "subnet": subnet,
                "ip": "",
            },
        )

        selected_ip = factory.pick_ip_in_network(subnet.get_ipnetwork())
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("domain", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_staticipaddress,
                ipaddress.id,
                {"alloc_type": IPADDRESS_TYPE.STICKY, "ip": selected_ip},
            )
            yield dv.get(timeout=2)
            assert (("update", str(domain.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_node_ip_address_addition(self):
        domain = yield deferToDatabase(self.create_domain)
        params = {"node_type": NODE_TYPE.MACHINE, "domain": domain}
        node = yield deferToDatabase(self.create_node, params)
        interface = yield deferToDatabase(
            self.create_interface, {"node": node}
        )
        subnet = yield deferToDatabase(self.create_subnet)

        selected_ip = factory.pick_ip_in_network(subnet.get_ipnetwork())
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("domain", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.create_staticipaddress,
                {
                    "alloc_type": IPADDRESS_TYPE.STICKY,
                    "interface": interface,
                    "subnet": subnet,
                    "ip": selected_ip,
                },
            )
            yield dv.get(timeout=2)
            assert (("update", str(domain.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_node_ip_address_removal(self):
        domain = yield deferToDatabase(self.create_domain)
        params = {"node_type": NODE_TYPE.MACHINE, "domain": domain}
        node = yield deferToDatabase(self.create_node, params)
        interface = yield deferToDatabase(
            self.create_interface, {"node": node}
        )
        subnet = yield deferToDatabase(self.create_subnet)
        selected_ip = factory.pick_ip_in_network(subnet.get_ipnetwork())
        ipaddress = yield deferToDatabase(
            self.create_staticipaddress,
            {
                "alloc_type": IPADDRESS_TYPE.STICKY,
                "interface": interface,
                "subnet": subnet,
                "ip": selected_ip,
            },
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("domain", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_staticipaddress, ipaddress.id)
            yield dv.get(timeout=2)
            assert (("update", str(domain.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_dnsresource_create_notification(self):
        domain = yield deferToDatabase(self.create_domain)
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("domain", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.create_dnsresource, {"domain": domain})
            yield dv.get(timeout=2)
            assert (("update", str(domain.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_dnsresource_address_addition(self):
        domain = yield deferToDatabase(self.create_domain)
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        dnsrr = yield deferToDatabase(
            self.create_dnsresource,
            {"domain": domain, "no_ip_addresses": True},
        )
        subnet = yield deferToDatabase(self.create_subnet)
        listener.register("domain", lambda *args: dv.set(args))

        yield listener.startService()
        selected_ip = factory.pick_ip_in_network(subnet.get_ipnetwork())
        try:
            yield deferToDatabase(
                self.create_staticipaddress,
                {
                    "alloc_type": IPADDRESS_TYPE.STICKY,
                    "dnsresource": dnsrr,
                    "subnet": subnet,
                    "ip": selected_ip,
                },
            )
            yield dv.get(timeout=2)
            assert (("update", str(domain.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_dnsresource_address_removal(self):
        domain = yield deferToDatabase(self.create_domain)
        dnsrr = yield deferToDatabase(
            self.create_dnsresource, {"domain": domain}
        )
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("domain", lambda *args: dv.set(args))
        staticip = yield deferToDatabase(self.get_first_staticipaddress, dnsrr)
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_staticipaddress, staticip.id)
            yield dv.get(timeout=2)
            assert (("update", str(domain.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_dnsresource_update_notification(self):
        domain = yield deferToDatabase(self.create_domain)
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        dnsrr = yield deferToDatabase(
            self.create_dnsresource, {"domain": domain}
        )
        listener.register("domain", lambda *args: dv.set(args))

        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_dnsresource,
                dnsrr.id,
                {"name": factory.make_name("name")},
            )
            yield dv.get(timeout=2)
            assert (("update", str(domain.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_dnsresource_delete_notification(self):
        domain = yield deferToDatabase(self.create_domain)
        dnsrr = yield deferToDatabase(
            self.create_dnsresource, {"domain": domain}
        )
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("domain", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_dnsresource, dnsrr.id)
            yield dv.get(timeout=2)
            assert (("update", str(domain.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_dnsdata_create_notification(self):
        domain = yield deferToDatabase(self.create_domain)
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("domain", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.create_dnsdata, {"domain": domain})
            yield dv.get(timeout=2)
            assert (("update", str(domain.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_dnsdata_update_notification(self):
        domain = yield deferToDatabase(self.create_domain)
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        dnsdata = yield deferToDatabase(
            self.create_dnsdata, {"domain": domain}
        )
        listener.register("domain", lambda *args: dv.set(args))

        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_dnsdata,
                dnsdata.id,
                {"ttl": random.randint(100, 199)},
            )
            yield dv.get(timeout=2)
            assert (("update", str(domain.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_dnsdata_delete_notification(self):
        domain = yield deferToDatabase(self.create_domain)
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("domain", lambda *args: dv.set(args))
        dnsdata = yield deferToDatabase(
            self.create_dnsdata, {"domain": domain}
        )
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_dnsdata, dnsdata.id)
            yield dv.get(timeout=2)
            assert (("update", str(domain.id))) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestSubnetListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the cluster
    triggers code."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("subnet", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            subnet = yield deferToDatabase(self.create_subnet)
            yield dv.get(timeout=2)
            assert (("create", str(subnet.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_update_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("subnet", lambda *args: dv.set(args))
        subnet = yield deferToDatabase(self.create_subnet)

        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_subnet,
                subnet.id,
                {"name": factory.make_name("name")},
            )
            yield dv.get(timeout=2)
            assert (("update", str(subnet.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_update_notification_for_vlan(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("subnet", lambda *args: dv.set(args))
        subnet = yield deferToDatabase(self.create_subnet)

        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_vlan,
                subnet.vlan.id,
                {"name": factory.make_name("name")},
            )
            yield dv.get(timeout=2)
            assert (("update", str(subnet.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_delete_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("subnet", lambda *args: dv.set(args))
        subnet = yield deferToDatabase(self.create_subnet)
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_subnet, subnet.id)
            yield dv.get(timeout=2)
            assert (("delete", str(subnet.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_ip_address_insert(self):
        node = yield deferToDatabase(
            self.create_node,
            {"node_type": NODE_TYPE.MACHINE, "interface": True},
        )
        interface = yield deferToDatabase(
            self.get_node_boot_interface, node.system_id
        )
        subnet = yield deferToDatabase(self.create_subnet)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("subnet", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.create_staticipaddress,
                {
                    "alloc_type": IPADDRESS_TYPE.AUTO,
                    "interface": interface,
                    "subnet": subnet,
                    "ip": "",
                },
            )
            yield dv.get(timeout=2)
            assert (("update", str(subnet.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_ip_address_update(self):
        node = yield deferToDatabase(
            self.create_node,
            {"node_type": NODE_TYPE.MACHINE, "interface": True},
        )
        interface = yield deferToDatabase(
            self.get_node_boot_interface, node.system_id
        )
        subnet = yield deferToDatabase(self.create_subnet)
        selected_ip = factory.pick_ip_in_network(subnet.get_ipnetwork())
        ipaddress = yield deferToDatabase(
            self.create_staticipaddress,
            {
                "alloc_type": IPADDRESS_TYPE.AUTO,
                "interface": interface,
                "subnet": subnet,
                "ip": "",
            },
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("subnet", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_staticipaddress, ipaddress.id, {"ip": selected_ip}
            )
            yield dv.get(timeout=2)
            assert (("update", str(subnet.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_ip_address_delete(self):
        node = yield deferToDatabase(
            self.create_node,
            {"node_type": NODE_TYPE.MACHINE, "interface": True},
        )
        interface = yield deferToDatabase(
            self.get_node_boot_interface, node.system_id
        )
        subnet = yield deferToDatabase(self.create_subnet)
        ipaddress = yield deferToDatabase(
            self.create_staticipaddress,
            {
                "alloc_type": IPADDRESS_TYPE.AUTO,
                "interface": interface,
                "subnet": subnet,
                "ip": "",
            },
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("subnet", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_staticipaddress, ipaddress.id)
            yield dv.get(timeout=2)
            assert (("update", str(subnet.id))) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestSpaceListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the cluster
    triggers code."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create_notification_with_blank_name(self):
        listener = self.make_listener_without_delay()
        dvs = [DeferredValue(), DeferredValue()]
        save_dvs = dvs[:]
        listener.register("space", lambda *args: dvs.pop().set(args))
        yield listener.startService()
        try:
            space = yield deferToDatabase(self.create_space)
            results = yield DeferredList(dv.get(timeout=2) for dv in save_dvs)
            assert sorted(
                [("create", str(space.id)), ("update", str(space.id))]
            ) == sorted([res for (suc, res) in results])
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create_notification_with_name(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("space", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            space = yield deferToDatabase(
                self.create_space, {"name": factory.make_name("name")}
            )
            yield dv.get(timeout=2)
            assert (("create", str(space.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_update_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("space", lambda *args: dv.set(args))
        space = yield deferToDatabase(self.create_space)

        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_space,
                space.id,
                {"name": factory.make_name("name")},
            )
            yield dv.get(timeout=2)
            assert (("update", str(space.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_delete_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("space", lambda *args: dv.set(args))
        space = yield deferToDatabase(self.create_space)
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_space, space.id)
            yield dv.get(timeout=2)
            assert (("delete", str(space.id))) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.parametrize(
    "params, listener_channel",
    [
        pytest.param(
            {"node_type": NODE_TYPE.MACHINE, "interface": True},
            "machine",
            id="machine",
        ),
        pytest.param(
            {"node_type": NODE_TYPE.DEVICE, "interface": True},
            "device",
            id="device",
        ),
        pytest.param(
            {
                "node_type": NODE_TYPE.RACK_CONTROLLER,
                "interface": True,
            },
            "controller",
            id="rack",
        ),
        pytest.param(
            {
                "node_type": NODE_TYPE.REGION_AND_RACK_CONTROLLER,
                "interface": True,
            },
            "controller",
            id="region_and_rack",
        ),
        pytest.param(
            {
                "node_type": NODE_TYPE.REGION_CONTROLLER,
                "interface": True,
            },
            "controller",
            id="region",
        ),
    ],
)
class TestNodeNetworkListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_fabric, maasserver_space, maasserver_subnet, and
    maasserver_vlan tables that notifies affected nodes."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_iface_with_update_on_fabric_update(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        interface = yield deferToDatabase(
            self.get_node_boot_interface, node.system_id
        )
        yield deferToDatabase(
            self.create_staticipaddress, {"interface": interface}
        )
        fabric = yield deferToDatabase(self.get_interface_fabric, interface.id)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_fabric,
                fabric.id,
                {"name": factory.make_name("name")},
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_iface_with_update_on_vlan_update(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        interface = yield deferToDatabase(
            self.get_node_boot_interface, node.system_id
        )
        yield deferToDatabase(
            self.create_staticipaddress, {"interface": interface}
        )
        vlan = yield deferToDatabase(self.get_interface_vlan, interface.id)
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_vlan, vlan.id, {"name": factory.make_name("name")}
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_subnet_update(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        interface = yield deferToDatabase(
            self.get_node_boot_interface, node.system_id
        )
        ipaddress = yield deferToDatabase(
            self.create_staticipaddress, {"interface": interface}
        )
        subnet = yield deferToDatabase(self.get_ipaddress_subnet, ipaddress.id)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_subnet,
                subnet.id,
                {"name": factory.make_name("name")},
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_space_update(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        interface = yield deferToDatabase(
            self.get_node_boot_interface, node.system_id
        )
        ipaddress = yield deferToDatabase(
            self.create_staticipaddress, {"interface": interface}
        )
        space = yield deferToDatabase(self.get_ipaddress_space, ipaddress.id)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_space,
                space.id,
                {"name": factory.make_name("name")},
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_ip_address_update(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        interface = yield deferToDatabase(
            self.get_node_boot_interface, node.system_id
        )
        subnet = yield deferToDatabase(self.create_subnet)
        selected_ip = factory.pick_ip_in_network(subnet.get_ipnetwork())
        ipaddress = yield deferToDatabase(
            self.create_staticipaddress,
            {
                "alloc_type": IPADDRESS_TYPE.AUTO,
                "interface": interface,
                "subnet": subnet,
                "ip": "",
            },
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_staticipaddress, ipaddress.id, {"ip": selected_ip}
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestDeviceWithParentNetworkListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_fabric, maasserver_space, maasserver_subnet, and
    maasserver_vlan tables that notifies affected nodes."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_iface_with_update_on_fabric_update(self):
        device, parent = yield deferToDatabase(
            self.create_device_with_parent, {"interface": True}
        )
        interface = yield deferToDatabase(
            self.get_node_boot_interface, device.system_id
        )
        yield deferToDatabase(
            self.create_staticipaddress, {"interface": interface}
        )
        fabric = yield deferToDatabase(self.get_interface_fabric, interface.id)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("machine", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_fabric,
                fabric.id,
                {"name": factory.make_name("name")},
            )
            yield dv.get(timeout=2)
            assert (("update", parent.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_iface_with_update_on_vlan_update(self):
        device, parent = yield deferToDatabase(
            self.create_device_with_parent, {"interface": True}
        )
        interface = yield deferToDatabase(
            self.get_node_boot_interface, device.system_id
        )
        yield deferToDatabase(
            self.create_staticipaddress, {"interface": interface}
        )
        vlan = yield deferToDatabase(self.get_interface_vlan, interface.id)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("machine", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_vlan, vlan.id, {"name": factory.make_name("name")}
            )
            yield dv.get(timeout=2)
            assert (("update", parent.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_subnet_update(self):
        device, parent = yield deferToDatabase(
            self.create_device_with_parent, {"interface": True}
        )
        interface = yield deferToDatabase(
            self.get_node_boot_interface, device.system_id
        )
        ipaddress = yield deferToDatabase(
            self.create_staticipaddress, {"interface": interface}
        )
        subnet = yield deferToDatabase(self.get_ipaddress_subnet, ipaddress.id)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("machine", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_subnet,
                subnet.id,
                {"name": factory.make_name("name")},
            )
            yield dv.get(timeout=2)
            assert (("update", parent.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_space_update(self):
        device, parent = yield deferToDatabase(
            self.create_device_with_parent, {"interface": True}
        )
        interface = yield deferToDatabase(
            self.get_node_boot_interface, device.system_id
        )
        ipaddress = yield deferToDatabase(
            self.create_staticipaddress, {"interface": interface}
        )
        space = yield deferToDatabase(self.get_ipaddress_space, ipaddress.id)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("machine", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_space,
                space.id,
                {"name": factory.make_name("name")},
            )
            yield dv.get(timeout=2)
            assert (("update", parent.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_ip_address_update(self):
        device, parent = yield deferToDatabase(
            self.create_device_with_parent, {"interface": True}
        )
        interface = yield deferToDatabase(
            self.get_node_boot_interface, device.system_id
        )
        subnet = yield deferToDatabase(self.create_subnet)
        selected_ip = factory.pick_ip_in_network(subnet.get_ipnetwork())
        ipaddress = yield deferToDatabase(
            self.create_staticipaddress,
            {
                "alloc_type": IPADDRESS_TYPE.AUTO,
                "interface": interface,
                "subnet": subnet,
                "ip": "",
            },
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("machine", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_staticipaddress, ipaddress.id, {"ip": selected_ip}
            )
            yield dv.get(timeout=2)
            assert (("update", parent.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestStaticIPAddressSubnetListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_staticipaddress tables that notifies affected subnets."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_update_on_subnet(self):
        subnet = yield deferToDatabase(self.create_subnet)
        selected_ip = factory.pick_ip_in_network(subnet.get_ipnetwork())
        ipaddress = yield deferToDatabase(
            self.create_staticipaddress,
            {"alloc_type": IPADDRESS_TYPE.AUTO, "subnet": subnet, "ip": ""},
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("subnet", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_staticipaddress, ipaddress.id, {"ip": selected_ip}
            )
            yield dv.get(timeout=2)
            assert (("update", str(subnet.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_update_on_old_and_new_subnet(self):
        old_subnet = yield deferToDatabase(self.create_subnet)
        new_subnet = yield deferToDatabase(self.create_subnet)
        selected_ip = factory.pick_ip_in_network(new_subnet.get_ipnetwork())
        ipaddress = yield deferToDatabase(
            self.create_staticipaddress,
            {
                "alloc_type": IPADDRESS_TYPE.AUTO,
                "subnet": old_subnet,
                "ip": "",
            },
        )
        dvs = [DeferredValue(), DeferredValue()]

        def set_defer_value(*args):
            for dv in dvs:
                if not dv.isSet:
                    dv.set(args)
                    break

        listener = self.make_listener_without_delay()
        listener.register("subnet", set_defer_value)
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_staticipaddress,
                ipaddress.id,
                {"ip": selected_ip, "subnet": new_subnet},
            )
            yield dvs[0].get(timeout=2)
            yield dvs[1].get(timeout=2)
            assert sorted(
                [
                    ("update", str(old_subnet.id)),
                    ("update", str(new_subnet.id)),
                ]
            ) == sorted([dvs[0].value, dvs[1].value])
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.parametrize(
    "params, listener_channel",
    [
        pytest.param(
            {"node_type": NODE_TYPE.MACHINE}, "machine", id="machine"
        ),
    ],
)
class TestMachineBlockDeviceListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_blockdevice, maasserver_physicalblockdevice, and
    maasserver_virtualblockdevice tables that notifies its machine."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_create(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.create_blockdevice, {"node": node})
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_delete(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        blockdevice = yield deferToDatabase(
            self.create_blockdevice, {"node": node}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_blockdevice, blockdevice.id)
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_update(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        blockdevice = yield deferToDatabase(
            self.create_blockdevice, {"node": node}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_blockdevice,
                blockdevice.id,
                {"size": random.randint(MIN_BLOCK_DEVICE_SIZE, 1000**3)},
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_physicalblockdevice_update(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        blockdevice = yield deferToDatabase(
            self.create_physicalblockdevice, {"node": node}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_physicalblockdevice,
                blockdevice.id,
                {"model": factory.make_name("model")},
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_virtualblockdevice_update(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        blockdevice = yield deferToDatabase(
            self.create_virtualblockdevice,
            {"node": node, "size": MIN_BOOT_PARTITION_SIZE},
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_virtualblockdevice,
                blockdevice.id,
                {"uuid": factory.make_UUID()},
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.parametrize(
    "params, listener_channel",
    [
        pytest.param(
            {"node_type": NODE_TYPE.MACHINE}, "machine", id="machine"
        ),
    ],
)
class TestMachinePartitionTableListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_partitiontable tables that notifies its machine."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_create(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.create_partitiontable, {"node": node})
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_delete(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        partitiontable = yield deferToDatabase(
            self.create_partitiontable, {"node": node}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.delete_partitiontable, partitiontable.id
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_update(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        partitiontable = yield deferToDatabase(
            self.create_partitiontable, {"node": node}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            # No changes to apply, but trigger a save nonetheless.
            yield deferToDatabase(
                self.update_partitiontable,
                partitiontable.id,
                {},
                force_update=True,
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.parametrize(
    "params, listener_channel",
    [
        pytest.param(
            {"node_type": NODE_TYPE.MACHINE}, "machine", id="machine"
        ),
    ],
)
class TestMachinePartitionListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_partition tables that notifies its machine."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_create(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.create_partition, {"node": node})
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_delete(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        partition = yield deferToDatabase(
            self.create_partition, {"node": node}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_partition, partition.id)
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @pytest.mark.skip(
        reason="XXX: GavinPanella 2016-03-11 bug=1556188: Fails spuriously."
    )
    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_update(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        partition = yield deferToDatabase(
            self.create_partition, {"node": node}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            # Only downsize the partition otherwise the test may fail due
            # to the random number being generated is greater than the mock
            # available disk space
            yield deferToDatabase(
                self.update_partition,
                partition.id,
                {"size": random.randint(MIN_PARTITION_SIZE, 1000**3)},
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.parametrize(
    "params, channel",
    [
        pytest.param(
            {"node_type": NODE_TYPE.MACHINE}, "machine", id="machine"
        ),
    ],
)
class TestMachineFilesystemListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_filesystem tables that notifies its machine."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    def setUp(self):
        super().setUp()

    def test_calls_handler_with_update_on_create_fs_on_partition(
        self, params, channel
    ):
        node = factory.make_Node(**params)
        partition = factory.make_Partition(node=node)
        with listenFor(channel) as get:
            factory.make_Filesystem(partition=partition)
            assert (("update", node.system_id)) == (get())

    def test_calls_handler_with_update_on_create_fs_on_block_device(
        self, params, channel
    ):
        node = factory.make_Node(**params)
        block_device = factory.make_BlockDevice(node=node)
        with listenFor(channel) as get:
            factory.make_Filesystem(block_device=block_device)
            assert (("update", node.system_id)) == (get())

    def test_calls_handler_with_update_on_create_special_fs(
        self, params, channel
    ):
        node = factory.make_Node(**params)
        with listenFor(channel) as get:
            factory.make_Filesystem(node_config=node.current_config)
            assert (("update", node.system_id)) == (get())

    def test_calls_handler_with_update_on_delete_fs_on_partition(
        self, params, channel
    ):
        node = factory.make_Node(**params)
        partition = factory.make_Partition(node=node)
        filesystem = factory.make_Filesystem(partition=partition)
        with listenFor(channel) as get:
            filesystem.delete()
            assert (("update", node.system_id)) == (get())

    def test_calls_handler_with_update_on_delete_fs_on_block_device(
        self, params, channel
    ):
        node = factory.make_Node(**params)
        block_device = factory.make_BlockDevice(node=node)
        filesystem = factory.make_Filesystem(block_device=block_device)
        with listenFor(channel) as get:
            filesystem.delete()
            assert (("update", node.system_id)) == (get())

    def test_calls_handler_with_update_on_delete_special_fs(
        self, params, channel
    ):
        node = factory.make_Node(**params)
        filesystem = factory.make_Filesystem(node_config=node.current_config)
        with listenFor(channel) as get:
            filesystem.delete()
            assert (("update", node.system_id)) == (get())

    def test_calls_handler_with_update_on_update_fs_on_partition(
        self, params, channel
    ):
        node = factory.make_Node(**params)
        partition = factory.make_Partition(node=node)
        filesystem = factory.make_Filesystem(partition=partition)
        with listenFor(channel) as get:
            filesystem.save(force_update=True)  # A no-op update is enough.
            assert (("update", node.system_id)) == (get())

    def test_calls_handler_with_update_on_update_fs_on_block_device(
        self, params, channel
    ):
        node = factory.make_Node(**params)
        block_device = factory.make_BlockDevice(node=node)
        filesystem = factory.make_Filesystem(block_device=block_device)
        with listenFor(channel) as get:
            filesystem.save(force_update=True)  # A no-op update is enough.
            assert (("update", node.system_id)) == (get())

    def test_calls_handler_with_update_on_update_special_fs(
        self, params, channel
    ):
        node = factory.make_Node(**params)
        filesystem = factory.make_Filesystem(node_config=node.current_config)
        with listenFor(channel) as get:
            filesystem.save(force_update=True)  # A no-op update is enough.
            assert (("update", node.system_id)) == (get())


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.parametrize(
    "params, listener_channel",
    [
        pytest.param(
            {
                "node_type": NODE_TYPE.MACHINE,
                "with_boot_disk": True,
            },
            "machine",
            id="machine",
        ),
    ],
)
class TestMachineFilesystemgroupListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_filesystemgroup tables that notifies its machine."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_create(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        yield deferToDatabase(
            self.create_partitiontable, {"node": node, "bootable": True}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.create_filesystemgroup, {"node": node})
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_delete(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        yield deferToDatabase(
            self.create_partitiontable, {"node": node, "bootable": True}
        )
        filesystemgroup = yield deferToDatabase(
            self.create_filesystemgroup, {"node": node, "group_type": "raid-5"}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.delete_filesystemgroup, filesystemgroup.id
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_update(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        yield deferToDatabase(
            self.create_partitiontable, {"node": node, "bootable": True}
        )
        filesystemgroup = yield deferToDatabase(
            self.create_filesystemgroup, {"node": node, "group_type": "bcache"}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_filesystemgroup,
                filesystemgroup.id,
                {"name": factory.make_name("fsgroup")},
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.parametrize(
    "params, listener_channel",
    [
        pytest.param(
            {"node_type": NODE_TYPE.MACHINE}, "machine", id="machine"
        ),
    ],
)
class TestMachineCachesetListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_cacheset tables that notifies its machine."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_create(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        partition = yield deferToDatabase(
            self.create_partition, {"node": node}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.create_cacheset, {"node": node, "partition": partition}
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_delete(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        partition = yield deferToDatabase(
            self.create_partition, {"node": node}
        )
        cacheset = yield deferToDatabase(
            self.create_cacheset, {"node": node, "partition": partition}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_cacheset, cacheset.id)
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_with_update_on_update(
        self, params, listener_channel
    ):
        node = yield deferToDatabase(self.create_node, params)
        partition = yield deferToDatabase(
            self.create_partition, {"node": node}
        )
        cacheset = yield deferToDatabase(
            self.create_cacheset, {"node": node, "partition": partition}
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        yield listener.startService()
        try:
            # No changes to apply, but trigger a save nonetheless.
            yield deferToDatabase(
                self.update_cacheset, cacheset.id, {}, force_update=True
            )
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestTokenListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the piston3_token
    table."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create(self):
        user = yield deferToDatabase(self.create_user)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("token", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            obj = yield deferToDatabase(self.create_token, {"user": user})
            yield dv.get(timeout=2)
            assert (("create", str(obj.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_update(self):
        user = yield deferToDatabase(self.create_user)
        token = yield deferToDatabase(self.create_token, {"user": user})
        new_name = factory.make_name("name")

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("token", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            # Force the update because the key contents could be the same.
            yield deferToDatabase(self.update_token, token.id, name=new_name)
            yield dv.get(timeout=2)
            assert (("update", str(token.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_delete(self):
        user = yield deferToDatabase(self.create_user)
        token = yield deferToDatabase(self.create_token, {"user": user})

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("token", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_token, token.id)
            yield dv.get(timeout=2)
            assert (("delete", str(token.id))) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestPackageRepositoryListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the cluster
    triggers code."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("packagerepository", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            repository = yield deferToDatabase(self.create_package_repository)
            yield dv.get(timeout=2)
            assert (("create", str(repository.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_update_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("packagerepository", lambda *args: dv.set(args))
        repository = yield deferToDatabase(self.create_package_repository)

        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_package_repository,
                repository.id,
                {"name": factory.make_name("name")},
            )
            yield dv.get(timeout=2)
            assert (("update", str(repository.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_delete_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("packagerepository", lambda *args: dv.set(args))
        repository = yield deferToDatabase(self.create_package_repository)
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.delete_package_repository, repository.id
            )
            yield dv.get(timeout=2)
            assert (("delete", str(repository.id))) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestIPRangeSubnetListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the triggers on
    maasserver_iprange tables that notifies affected subnets."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create_notification(self):
        subnet = yield deferToDatabase(
            self.create_subnet,
            {
                "cidr": "192.168.0.0/24",
                "gateway_ip": "192.168.0.1",
                "dns_servers": [],
            },
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("subnet", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            iprange = yield deferToDatabase(
                self.create_iprange,
                {
                    "alloc_type": IPRANGE_TYPE.DYNAMIC,
                    "subnet": subnet,
                    "start_ip": "192.168.0.100",
                    "end_ip": "192.168.0.110",
                },
            )
            yield dv.get(timeout=2)
            assert (("update", str(iprange.subnet.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_update_notification(self):
        iprange = yield deferToDatabase(self.create_iprange)
        new_end_ip = factory.pick_ip_in_IPRange(
            iprange, but_not=[iprange.start_ip, iprange.end_ip]
        )

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("subnet", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_iprange, iprange.id, {"end_ip": new_end_ip}
            )
            yield dv.get(timeout=2)
            assert (("update", str(iprange.subnet.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_update_on_old_and_new_subnet_notification(self):
        old_subnet = yield deferToDatabase(
            self.create_subnet,
            {
                "cidr": "192.168.0.0/24",
                "gateway_ip": "192.168.0.1",
                "dns_servers": [],
            },
        )
        new_subnet = yield deferToDatabase(
            self.create_subnet,
            {
                "cidr": "192.168.1.0/24",
                "gateway_ip": "192.168.1.1",
                "dns_servers": [],
            },
        )
        iprange = yield deferToDatabase(
            self.create_iprange,
            {
                "alloc_type": IPRANGE_TYPE.DYNAMIC,
                "subnet": old_subnet,
                "start_ip": "192.168.0.100",
                "end_ip": "192.168.0.110",
            },
        )
        dvs = [DeferredValue(), DeferredValue()]

        def set_defer_value(*args):
            for dv in dvs:
                if not dv.isSet:
                    dv.set(args)
                    break

        listener = self.make_listener_without_delay()
        listener.register("subnet", set_defer_value)
        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_iprange,
                iprange.id,
                {
                    "type": IPRANGE_TYPE.DYNAMIC,
                    "subnet": new_subnet,
                    "start_ip": "192.168.1.10",
                    "end_ip": "192.168.1.150",
                },
            )
            yield dvs[0].get(timeout=2)
            yield dvs[1].get(timeout=2)
            assert sorted(
                [
                    ("update", str(old_subnet.id)),
                    ("update", str(new_subnet.id)),
                ]
            ) == sorted([dvs[0].value, dvs[1].value])
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_delete_notification(self):
        iprange = yield deferToDatabase(self.create_iprange)

        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("subnet", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_iprange, iprange.id)
            yield dv.get(timeout=2)
            assert (("update", str(iprange.subnet.id))) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.parametrize(
    "params, listener_channel",
    [
        pytest.param(
            {
                "node_type": NODE_TYPE.MACHINE,
                # This is needed to avoid updating the node after creating it
                "with_boot_disk": False,
            },
            "machine",
            id="machine",
        ),
        pytest.param(
            {"node_type": NODE_TYPE.RACK_CONTROLLER}, "controller", id="rack"
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_AND_RACK_CONTROLLER},
            "controller",
            id="region_and_rack",
        ),
        pytest.param(
            {"node_type": NODE_TYPE.REGION_CONTROLLER},
            "controller",
            id="region",
        ),
    ],
)
class TestBMCListener(TransactionalHelpersMixin):
    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_bmc_update(self, params, listener_channel):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register(listener_channel, lambda *args: dv.set(args))
        params.update(
            {
                "power_type": "lxd",
                "power_parameters": {"power_address": "1.2.3.4"},
            }
        )
        node = yield deferToDatabase(self.create_node, params)

        def update_node(system_id):
            node = Node.objects.get(system_id=system_id)
            node.bmc.set_power_parameters({"power_address": "5.6.7.8"})
            node.bmc.save()

        yield listener.startService()
        try:
            yield deferToDatabase(update_node, node.system_id)
            yield dv.get(timeout=2)
            assert (("update", node.system_id)) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
@pytest.mark.parametrize(
    "from_type, from_listener, to_type, to_listener",
    [
        pytest.param(
            NODE_TYPE.MACHINE,
            "machine",
            NODE_TYPE.RACK_CONTROLLER,
            "controller",
            id="machine_to_rack",
        ),
        pytest.param(
            NODE_TYPE.MACHINE,
            "machine",
            NODE_TYPE.REGION_CONTROLLER,
            "controller",
            id="machine_to_region",
        ),
        pytest.param(
            NODE_TYPE.MACHINE,
            "machine",
            NODE_TYPE.REGION_AND_RACK_CONTROLLER,
            "controller",
            id="machine_to_rack_and_region",
        ),
        pytest.param(
            NODE_TYPE.MACHINE,
            "machine",
            NODE_TYPE.DEVICE,
            "device",
            id="machine_to_device",
        ),
        pytest.param(
            NODE_TYPE.RACK_CONTROLLER,
            "controller",
            NODE_TYPE.MACHINE,
            "machine",
            id="rack_to_machine",
        ),
        pytest.param(
            NODE_TYPE.RACK_CONTROLLER,
            "controller",
            NODE_TYPE.DEVICE,
            "device",
            id="rack_to_device",
        ),
        pytest.param(
            NODE_TYPE.REGION_CONTROLLER,
            "controller",
            NODE_TYPE.MACHINE,
            "machine",
            id="region_to_machine",
        ),
        pytest.param(
            NODE_TYPE.REGION_CONTROLLER,
            "controller",
            NODE_TYPE.DEVICE,
            "device",
            id="region_to_device",
        ),
        pytest.param(
            NODE_TYPE.REGION_AND_RACK_CONTROLLER,
            "controller",
            NODE_TYPE.MACHINE,
            "machine",
            id="region_and_rack_to_machine",
        ),
        pytest.param(
            NODE_TYPE.REGION_AND_RACK_CONTROLLER,
            "controller",
            NODE_TYPE.DEVICE,
            "device",
            id="region_and_rack_to_device",
        ),
        pytest.param(
            NODE_TYPE.DEVICE,
            "device",
            NODE_TYPE.RACK_CONTROLLER,
            "controller",
            id="device_to_rack",
        ),
        pytest.param(
            NODE_TYPE.DEVICE,
            "device",
            NODE_TYPE.REGION_CONTROLLER,
            "controller",
            id="device_to_region",
        ),
        pytest.param(
            NODE_TYPE.DEVICE,
            "device",
            NODE_TYPE.REGION_AND_RACK_CONTROLLER,
            "controller",
            id="device_to_rack_and_region",
        ),
        pytest.param(
            NODE_TYPE.DEVICE,
            "device",
            NODE_TYPE.MACHINE,
            "machine",
            id="device_to_machine",
        ),
    ],
)
class TestNodeTypeChange(TransactionalHelpersMixin):
    """End-to-end test of node type change triggers code."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_transition_notifies(
        self, from_type, from_listener, to_type, to_listener
    ):
        listener1 = self.make_listener_without_delay()
        listener2 = self.make_listener_without_delay()
        node = yield deferToDatabase(
            self.create_node, {"node_type": from_type}
        )
        q_from, q_to = DeferredQueue(), DeferredQueue()
        listener1.register(from_listener, lambda *args: q_from.put(args))
        listener2.register(to_listener, lambda *args: q_to.put(args))
        yield listener1.startService()
        yield listener2.startService()
        try:
            node.node_type = to_type
            if to_type != NODE_TYPE.MACHINE:
                node.pool = None
            yield deferToDatabase(node.save)
            assert (("delete", node.system_id)) == (
                yield deferWithTimeout(2, q_from.get)
            )
            if NODE_TYPE.MACHINE in (from_type, to_type):
                # Changing to and from a node will cause a pool to either
                # be added or removed. This causes an additional update
                # trigger.
                notifications = {}
                for _ in range(2):
                    f, system_id = yield deferWithTimeout(2, q_to.get)
                    notifications[f] = system_id
                assert (
                    {"update": node.system_id, "create": node.system_id}
                ) == (notifications)
            else:
                assert (("create", node.system_id)) == (
                    yield deferWithTimeout(2, q_to.get)
                )
        finally:
            yield listener1.stopService()
            yield listener2.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestNotificationListener(TransactionalHelpersMixin):
    """Tests for notifications relating to the `Notification` model."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("notification", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            notification = yield deferToDatabase(factory.make_Notification)
            yield dv.get(timeout=2)
            assert (("create", str(notification.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_update_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("notification", lambda *args: dv.set(args))
        notification = yield deferToDatabase(factory.make_Notification)

        def update_notification(notification):
            notification.users = not notification.users
            notification.admins = not notification.admins
            notification.save()

        yield listener.startService()
        try:
            yield deferToDatabase(update_notification, notification)
            yield dv.get(timeout=2)
            assert (("update", str(notification.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_delete_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("notification", lambda *args: dv.set(args))
        notification = yield deferToDatabase(factory.make_Notification)
        notification_id = notification.id  # Capture before delete.
        yield listener.startService()
        try:
            yield deferToDatabase(notification.delete)
            yield dv.get(timeout=2)
            assert (("delete", str(notification_id))) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestNotificationDismissalListener(TransactionalHelpersMixin):
    """Tests relating to the `NotificationDismissal` model.

    At present `NotificationDismissal` rows are only ever created.
    """

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("notificationdismissal", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            user = yield deferToDatabase(factory.make_User)
            notification = yield deferToDatabase(factory.make_Notification)
            yield deferToDatabase(notification.dismiss, user)
            yield dv.get(timeout=2)
            assert (("create", "%d:%d" % (notification.id, user.id))) == (
                dv.value
            )
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestScriptListener(TransactionalHelpersMixin):
    """End-to-end test of both the listeners code and the cluster
    triggers code."""

    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create_notification(self):
        yield deferToDatabase(load_builtin_scripts)
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("script", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            script = yield deferToDatabase(self.create_script)
            yield dv.get(timeout=2)
            assert (("create", str(script.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_update_notification(self):
        yield deferToDatabase(load_builtin_scripts)
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("script", lambda *args: dv.set(args))
        script = yield deferToDatabase(self.create_script)

        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_script,
                script.id,
                {"name": factory.make_name("name")},
            )
            yield dv.get(timeout=2)
            assert (("update", str(script.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_delete_notification(self):
        yield deferToDatabase(load_builtin_scripts)
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("script", lambda *args: dv.set(args))
        script = yield deferToDatabase(self.create_script)
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_script, script.id)
            yield dv.get(timeout=2)
            assert (("delete", str(script.id))) == (dv.value)
        finally:
            yield listener.stopService()


@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestNodeDeviceListener(TransactionalHelpersMixin):
    @pytest.fixture(autouse=True)
    def _mocker_patch(self, mocker):
        self.patch = mocker.patch.object

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_create_notification(self):
        node = yield deferToDatabase(self.create_node)
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("nodedevice", lambda *args: dv.set(args))
        yield listener.startService()
        try:
            node_device = yield deferToDatabase(
                self.create_node_device, {"node": node}
            )
            yield dv.get(timeout=2)
            assert (("create", str(node_device.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_update_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("nodedevice", lambda *args: dv.set(args))
        node_device = yield deferToDatabase(self.create_node_device)

        yield listener.startService()
        try:
            yield deferToDatabase(
                self.update_node_device,
                node_device.id,
                {
                    "commissioning_driver": factory.make_name(
                        "commissioning_driver"
                    )
                },
            )
            yield dv.get(timeout=2)
            assert (("update", str(node_device.id))) == (dv.value)
        finally:
            yield listener.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_calls_handler_on_delete_notification(self):
        listener = self.make_listener_without_delay()
        dv = DeferredValue()
        listener.register("nodedevice", lambda *args: dv.set(args))
        node_device = yield deferToDatabase(self.create_node_device)
        yield listener.startService()
        try:
            yield deferToDatabase(self.delete_node_device, node_device.id)
            yield dv.get(timeout=2)
            assert (("delete", str(node_device.id))) == (dv.value)
        finally:
            yield listener.stopService()
