# Copyright 2017-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maasserver.websockets.handlers.script`"""

import random

import pytest

from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object
from maasserver.websockets.base import (
    dehydrate_datetime,
    HandlerDoesNotExistError,
    HandlerPermissionError,
)
from maasserver.websockets.handlers.script import ScriptHandler
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestScriptHandler:
    def dehydrate_script(self, script):
        return {
            "id": script.id,
            "name": script.name,
            "title": script.title,
            "description": script.description,
            "tags": script.tags,
            "script_type": script.script_type,
            "hardware_type": script.hardware_type,
            "parallel": script.parallel,
            "results": script.results,
            "parameters": script.parameters,
            "packages": script.packages,
            "timeout": "0%s" % str(script.timeout),
            "destructive": script.destructive,
            "default": script.default,
            "script": script.script_id,
            "for_hardware": script.for_hardware,
            "may_reboot": script.may_reboot,
            "recommission": script.recommission,
            "apply_configured_networking": script.apply_configured_networking,
            "created": dehydrate_datetime(script.created),
            "updated": dehydrate_datetime(script.updated),
        }

    def test_list(self):
        user = factory.make_User()
        handler = ScriptHandler(user, {}, None)
        parameters = {"interface": {"type": "interface"}}
        expected_scripts = sorted(
            (
                self.dehydrate_script(
                    factory.make_Script(parameters=parameters)
                )
                for _ in range(3)
            ),
            key=lambda i: i["id"],
        )
        sorted_results = sorted(handler.list({}), key=lambda i: i["id"])
        for expected, real in zip(
            expected_scripts, sorted_results, strict=True
        ):
            assert expected == real

    def test_delete(self):
        script = factory.make_Script()
        admin = factory.make_admin()
        handler = ScriptHandler(admin, {}, None)

        handler.delete({"id": script.id})

        assert reload_object(script) is None

    def test_delete_admin_only(self):
        script = factory.make_Script()
        user = factory.make_User()
        handler = ScriptHandler(user, {}, None)

        pytest.raises(
            HandlerPermissionError, handler.delete, {"id": script.id}
        )

        assert reload_object(script) is not None

    def test_delete_cannot_delete_default(self):
        script = factory.make_Script(default=True)
        admin = factory.make_admin()
        handler = ScriptHandler(admin, {}, None)

        pytest.raises(
            HandlerPermissionError, handler.delete, {"id": script.id}
        )

        assert reload_object(script) is not None

    def test_get_script(self):
        script = factory.make_Script()
        user = factory.make_User()
        handler = ScriptHandler(user, {}, None)

        assert script.script.data == handler.get_script({"id": script.id})

    def test_get_script_not_found(self):
        user = factory.make_User()
        handler = ScriptHandler(user, {}, None)

        pytest.raises(
            HandlerDoesNotExistError,
            handler.get_script,
            {"id": random.randint(1000, 10000)},
        )

    def test_get_script_revision(self):
        script = factory.make_Script()
        old_vtf = script.script
        script.script = script.script.update(factory.make_string())
        script.save()
        user = factory.make_User()
        handler = ScriptHandler(user, {}, None)

        assert old_vtf.data == handler.get_script(
            {"id": script.id, "revision": old_vtf.id}
        )

    def test_get_script_revision_not_found(self):
        script = factory.make_Script()
        user = factory.make_User()
        handler = ScriptHandler(user, {}, None)

        pytest.raises(
            HandlerDoesNotExistError,
            handler.get_script,
            {"id": script.id, "revision": random.randint(1000, 10000)},
        )


@pytest.mark.usefixtures("maasdb", "factory")
class TestScriptHandlerOpenFGAIntegration(PytestOpenFGAMockMixin):
    def test_delete_requires_can_edit_global_entities(self):
        self.openfga_client.can_edit_global_entities.return_value = True
        user = factory.make_User()
        script = factory.make_Script()
        handler = ScriptHandler(user, {}, None)
        handler.delete({"id": script.id})
        self.openfga_client.can_edit_global_entities.assert_called_once_with(
            user
        )
        assert reload_object(script) is None

    def test_delete_denied_without_can_edit_global_entities(self):
        self.openfga_client.can_edit_global_entities.return_value = False
        user = factory.make_User()
        script = factory.make_Script()
        handler = ScriptHandler(user, {}, None)
        pytest.raises(
            HandlerPermissionError, handler.delete, {"id": script.id}
        )
        assert reload_object(script) is not None
