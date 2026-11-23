# Copyright 2017-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the behaviour of user signals."""

from django.db import connection
import pytest

from maasserver.sqlalchemy import service_layer
from maasserver.testing.factory import factory
from maasserver.testing.testcase import MAASServerTestCase
from maasserver.worker_user import get_worker_user
from maasservicelayer.db.filters import QuerySpec
from maasservicelayer.db.repositories.usergroups import UserGroupsClauseFactory
from metadataserver.nodeinituser import get_node_init_user


class TestUserUsername(MAASServerTestCase):
    """Test that event's `username` is set when the user is
    going to be deleted."""

    def test_deleting_user_updates_event_username(self):
        user = factory.make_admin()
        username = user.username
        events = [factory.make_Event(user=user) for _ in range(3)]
        user.delete()
        for event in events:
            self.assertEqual(event.username, username)


@pytest.mark.parametrize(
    "user_factory", [factory.make_User, factory.make_admin]
)
@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "factory"
)
class TestPostSaveUserSignal:
    def test_save_creates_openfga_tuple(self, user_factory):
        user = user_factory()

        group = service_layer.services.usergroups.get_one(
            QuerySpec(
                where=UserGroupsClauseFactory.with_name(
                    "Administrators" if user.is_superuser else "Users"
                )
            )
        )

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT object_type, object_id, relation FROM openfga.tuple WHERE _user = 'user:%s'",
                [user.id],
            )
            openfga_tuple = cursor.fetchone()

        assert "group" == openfga_tuple[0]
        assert str(group.id) == openfga_tuple[1]
        assert "member" == openfga_tuple[2]

    def test_save_ignores_deleted_default_groups(self, user_factory):
        service_layer.services.usergroups.delete_one(
            QuerySpec(
                where=UserGroupsClauseFactory.with_name("Administrators")
            )
        )
        service_layer.services.usergroups.delete_one(
            QuerySpec(where=UserGroupsClauseFactory.with_name("Users"))
        )

        user = user_factory()

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT object_type, object_id, relation FROM openfga.tuple WHERE _user = 'user:%s'",
                [user.id],
            )
            openfga_tuple = cursor.fetchone()

        assert openfga_tuple is None


@pytest.mark.parametrize("user_factory", [get_worker_user, get_node_init_user])
@pytest.mark.usefixtures(
    "maasdb", "mock_openfga", "mock_start_workflows", "factory"
)
class TestPostSaveUserSystemUsersIgnoredSignal:
    def test_save_user_is_ignored(self, user_factory):
        user = user_factory()

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT object_type, object_id, relation FROM openfga.tuple WHERE _user = 'user:%s'",
                [user.id],
            )
            openfga_tuple = cursor.fetchone()

        assert openfga_tuple is None


class TestPostDeleteUserSignal(MAASServerTestCase):
    def test_delete_removes_openfga_tuple(self):
        user = factory.make_User()
        user_id = user.id

        user.delete()

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT object_type, object_id, relation FROM openfga.tuple WHERE _user = 'user:%s'",
                [user_id],
            )
            openfga_tuple = cursor.fetchone()

        self.assertIsNone(openfga_tuple)
