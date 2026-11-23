# Copyright 2017-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maasserver.websockets.handlers.notification`."""

from operator import itemgetter
import random
from unittest.mock import sentinel

import pytest

from maasserver.models.notification import (
    NotificationDismissal,
    NotificationNotDismissable,
)
from maasserver.testing.factory import factory
from maasserver.websockets.base import dehydrate_datetime, Handler
from maasserver.websockets.handlers.notification import NotificationHandler


def dismissed_by_user(notification, user):
    return NotificationDismissal.objects.filter(
        notification=notification, user=user
    ).exists()


def assertNotificationEqual(response, reference_notification):
    assert response["id"] == reference_notification.id
    if reference_notification.ident is None:
        assert response["ident"] is None
    else:
        assert response["ident"] == reference_notification.ident
    if reference_notification.user_id is None:
        assert response["user"] is None
    else:
        assert response["user"] == reference_notification.user_id
    assert response["users"] is reference_notification.users
    assert response["admins"] is reference_notification.admins
    assert response["updated"] == dehydrate_datetime(
        reference_notification.updated
    )
    assert response["created"] == dehydrate_datetime(
        reference_notification.created
    )
    assert response["message"] == reference_notification.render()
    assert response["category"] == reference_notification.category
    assert response["dismissable"] == reference_notification.dismissable


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNotificationHandler:
    """Tests for `NotificationHandler`."""

    def test_get(self):
        user = factory.make_User()
        handler = NotificationHandler(user, {}, None)
        notification = factory.make_Notification(user=user)
        data = handler.get({"id": notification.id})
        assertNotificationEqual(data, notification)

    def test_list(self):
        user = factory.make_User()
        user2 = factory.make_User()
        handler = NotificationHandler(user, {}, None)
        notifications = [
            factory.make_Notification(user=user),  # Will match.
            factory.make_Notification(user=user2),
            factory.make_Notification(users=True),  # Will match.
            factory.make_Notification(users=False),
            factory.make_Notification(admins=True),
            factory.make_Notification(admins=False),
        ]
        this_user_notification = notifications[0]
        all_users_notification = notifications[2]
        response = sorted(handler.list({}), key=itemgetter("id"))

        assert len(response) == 2
        (n1, n2) = response
        assertNotificationEqual(n1, this_user_notification)
        assertNotificationEqual(n2, all_users_notification)

    def test_list_for_admin(self):
        admin = factory.make_admin()
        admin2 = factory.make_admin()
        handler = NotificationHandler(admin, {}, None)
        notifications = [
            factory.make_Notification(user=admin),  # Will match.
            factory.make_Notification(user=admin2),
            factory.make_Notification(users=True),
            factory.make_Notification(users=False),
            factory.make_Notification(admins=True),  # Will match.
            factory.make_Notification(admins=False),
        ]
        this_admin_notification = notifications[0]
        all_admins_notification = notifications[4]
        response = sorted(handler.list({}), key=itemgetter("id"))
        assert len(response) == 2
        (n1, n2) = response
        assertNotificationEqual(n1, this_admin_notification)
        assertNotificationEqual(n2, all_admins_notification)

    def test_dismiss(self):
        user = factory.make_User()
        handler = NotificationHandler(user, {}, None)
        notification = factory.make_Notification(user=user)
        assert not dismissed_by_user(notification, user)
        handler.dismiss({"id": str(notification.id)})
        assert dismissed_by_user(notification, user)

    def test_not_dismissable(self):
        user = factory.make_User()
        handler = NotificationHandler(user, {}, None)
        notification = factory.make_Notification(user=user, dismissable=False)
        with pytest.raises(NotificationNotDismissable):
            handler.dismiss({"id": str(notification.id)})

    def test_dismiss_multiple(self):
        user = factory.make_User()
        handler = NotificationHandler(user, {}, None)
        notifications = [
            factory.make_Notification(user=user),
            factory.make_Notification(users=True),
        ]
        for notification in notifications:
            assert not dismissed_by_user(notification, user)
        handler.dismiss({"id": [str(ntfn.id) for ntfn in notifications]})
        for notification in notifications:
            assert dismissed_by_user(notification, user)


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNotificationHandlerListening:
    """Tests for `NotificationHandler` listening to database messages."""

    def test_on_listen_for_notification_up_calls(self, mocker):
        super_on_listen = mocker.patch.object(Handler, "on_listen")
        super_on_listen.return_value = sentinel.on_listen

        user = factory.make_User()
        handler = NotificationHandler(user, {}, None)

        assert (
            handler.on_listen("notification", sentinel.action, sentinel.pk)
            is sentinel.on_listen
        )
        super_on_listen.assert_called_once_with(
            "notification", sentinel.action, sentinel.pk
        )

    def test_on_listen_for_dismissal_up_calls_with_delete(self, mocker):
        super_on_listen = mocker.patch.object(Handler, "on_listen")
        super_on_listen.return_value = sentinel.on_listen

        user = factory.make_User()
        handler = NotificationHandler(user, {}, None)
        notification = factory.make_Notification(user=user)

        # A dismissal notification from the database.
        dismissal = "%d:%d" % (notification.id, user.id)

        assert (
            handler.on_listen(
                "notificationdismissal", sentinel.action, dismissal
            )
            is sentinel.on_listen
        )
        super_on_listen.assert_called_once_with(
            "notification", "delete", notification.id
        )

    def test_on_listen_for_dismissal_for_other_user_does_nothing(self, mocker):
        super_on_listen = mocker.patch.object(Handler, "on_listen")
        super_on_listen.return_value = sentinel.on_listen

        user = factory.make_User()
        handler = NotificationHandler(user, {}, None)
        notification = factory.make_Notification(user=user)

        # A dismissal notification from the database FOR ANOTHER USER.
        dismissal = "%d:%d" % (notification.id, random.randrange(1, 99999))

        assert (
            handler.on_listen(
                "notificationdismissal", sentinel.action, dismissal
            )
            is None
        )
        super_on_listen.assert_not_called()

    def test_on_listen_for_edited_notification_does_nothing(self, mocker):
        super_on_listen = mocker.patch.object(Handler, "on_listen")
        super_on_listen.return_value = sentinel.on_listen

        user = factory.make_User()
        handler = NotificationHandler(user, {}, None)
        notification = factory.make_Notification(user=user)
        notification.dismiss(user)

        assert (
            handler.on_listen("notification", "update", notification.id)
            is None
        )
        super_on_listen.assert_not_called()


@pytest.mark.usefixtures("factory", "mock_openfga")
class TestNotificationHandlerListeningScenarios:
    """Tests for `NotificationHandler` listening to database messages."""

    @pytest.mark.parametrize(
        "make_user",
        [
            factory.make_User,
            factory.make_admin,
        ],
    )
    @pytest.mark.parametrize(
        "to_user,to_users,to_admins",
        [
            (False, False, False),
            (False, False, True),
            (False, True, False),
            (False, True, True),
            (True, False, False),
            (True, False, True),
            (True, True, False),
            (True, True, True),
            ("Other", False, False),
            ("Other", False, True),
            ("Other", True, False),
            ("Other", True, True),
        ],
    )
    def test_on_listen(self, make_user, to_user, to_users, to_admins):
        user = make_user()

        if to_user is False:
            to_user = None
        elif to_user is True:
            to_user = user
        else:
            to_user = factory.make_User()

        notification = factory.make_Notification(
            user=to_user, users=to_users, admins=to_admins
        )

        handler = NotificationHandler(user, {}, None)
        response = handler.on_listen("notification", "create", notification.id)
        if notification.is_relevant_to(user):
            handler_name, action, data = response
            assert handler_name == "notification"
            assert action == "create"
            assertNotificationEqual(data, notification)
        else:
            assert response is None
