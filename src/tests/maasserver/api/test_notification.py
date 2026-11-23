# Copyright 2017-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for Notification API."""

import http.client
import json
import random

from django.contrib.auth.models import AnonymousUser
from django.urls import reverse
import pytest

from maasserver.models.notification import Notification, NotificationDismissal
from maasserver.testing.factory import factory
from maasserver.testing.testclient import MAASSensibleOAuthClient
from maasserver.utils.orm import reload_object
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


def get_notifications_uri():
    """Return a Notification's URI on the API."""
    return reverse("notifications_handler", args=[])


def get_notification_uri(notification):
    """Return a Notification URI on the API."""
    return reverse("notification_handler", args=[notification.id])


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestURIs:
    def test_notifications_handler_path(self):
        assert "/MAAS/api/2.0/notifications/" == get_notifications_uri()

    def test_notification_handler_path(self):
        notification = factory.make_Notification()
        assert (
            "/MAAS/api/2.0/notifications/%d/" % notification.id
            == get_notification_uri(notification)
        )


def check_notification_matches(notification, parsed_notification):
    """Check the expected JSON rendering of `notification`."""
    assert parsed_notification.get("id") == notification.id
    assert parsed_notification.get("ident") == notification.ident
    if notification.user_id is None:
        assert parsed_notification.get("user", object()) is None
    else:
        assert (
            parsed_notification.get("user").get("username")
            == notification.user.username
        )
        assert parsed_notification.get("users") == notification.users
        assert parsed_notification.get("admins") == notification.admins
        assert parsed_notification.get("message") == notification.message
        assert parsed_notification.get("context") == notification.context
        assert parsed_notification.get("category") == notification.category
        assert (
            parsed_notification.get("dismissable") == notification.dismissable
        )
        assert parsed_notification.get("resource_uri") == get_notification_uri(
            notification
        )


@pytest.mark.parametrize(
    "api_identity",
    [
        pytest.param("maas_user", id="user=user,client=oauth"),
        pytest.param("admin", id="user=admin,client=oauth"),
    ],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNotificationsAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request):
        self.user = request.getfixturevalue(api_identity)
        client_fixture = (
            "api_client" if api_identity == "maas_user" else "admin_api_client"
        )
        self.client = request.getfixturevalue(client_fixture)

    def test_read(self):
        notifications = [
            factory.make_Notification(
                user=self.user, users=False, admins=False
            ),
            factory.make_Notification(user=None, users=True, admins=False),
            factory.make_Notification(user=None, users=False, admins=True),
        ]
        response = self.client.get(get_notifications_uri())
        assert response.status_code == http.client.OK
        parsed_notifications = response.json()
        for notification, parsed_notification in zip(
            notifications, parsed_notifications, strict=False
        ):
            if notification.is_relevant_to(self.user):
                check_notification_matches(notification, parsed_notification)

    def test_create_with_minimal_fields(self):
        message = factory.make_name("message")
        response = self.client.post(
            get_notifications_uri(), {"message": message}
        )
        if self.user.is_superuser:
            assert response.status_code == http.client.OK
            response = response.json()
            assert isinstance(response.get("id"), int)
            notification = Notification.objects.get(id=response["id"])
            check_notification_matches(notification, response)
        else:
            assert response.status_code == http.client.FORBIDDEN

    def test_create_with_all_fields(self):
        context = {factory.make_name("key"): factory.make_name("value")}
        data = {
            "ident": factory.make_name("ident"),
            "user": str(self.user.id),
            "users": random.choice(["true", "false"]),
            "admins": random.choice(["true", "false"]),
            "message": factory.make_name("message"),
            "context": json.dumps(context),
            "category": random.choice(("info", "success", "warning", "error")),
            "dismissable": random.choice(["true", "false"]),
        }
        response = self.client.post(get_notifications_uri(), data)
        if self.user.is_superuser:
            assert response.status_code == http.client.OK
            notification = response.json()
            assert isinstance(notification.get("id"), int)
            assert notification.get("ident") == data["ident"]
            assert (
                notification.get("user").get("username") == self.user.username
            )
            assert notification.get("users") == (data["users"] == "true")
            assert notification.get("admins") == (data["admins"] == "true")
            assert notification.get("message") == data["message"]
            assert notification.get("context") == context
            assert notification.get("category") == data["category"]
            assert notification.get("dismissable") == (
                data["dismissable"] == "true"
            )
        else:
            assert response.status_code == http.client.FORBIDDEN

    def test_create_with_username_user_field(self):
        recipient = factory.make_User()
        response = self.client.post(
            get_notifications_uri(),
            {
                "message": factory.make_name("message"),
                "user": recipient.username,
            },
        )
        if self.user.is_superuser:
            assert response.status_code == http.client.OK
            notification = response.json()
            assert (
                notification.get("user").get("username") == recipient.username
            )
        else:
            assert response.status_code == http.client.FORBIDDEN

    def test_create_rejects_unknown_username_user_field(self):
        response = self.client.post(
            get_notifications_uri(),
            {
                "message": factory.make_name("message"),
                "user": "no-such-user",
            },
        )
        if self.user.is_superuser:
            assert response.status_code == http.client.BAD_REQUEST
            assert response.json().get("user") == [
                "Enter a valid user id or username."
            ]
        else:
            assert response.status_code == http.client.FORBIDDEN


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("anonymous", id="user=anonymous,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNotificationsAPI_Anonymous:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity):
        assert api_identity == "anonymous"
        self.client = MAASSensibleOAuthClient(user=AnonymousUser())

    def test_read(self):
        response = self.client.get(get_notifications_uri())
        assert response.status_code == http.client.UNAUTHORIZED

    def test_create(self):
        response = self.client.post(
            get_notifications_uri(), {"message": factory.make_name()}
        )
        assert response.status_code == http.client.UNAUTHORIZED


@pytest.mark.parametrize(
    "api_identity",
    [
        pytest.param("maas_user", id="user=user,client=oauth"),
        pytest.param("admin", id="user=admin,client=oauth"),
    ],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNotificationAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request):
        self.user = request.getfixturevalue(api_identity)
        client_fixture = (
            "api_client" if api_identity == "maas_user" else "admin_api_client"
        )
        self.client = request.getfixturevalue(client_fixture)

    def test_read_notification_for_self(self):
        notification = factory.make_Notification(user=self.user)
        response = self.client.get(get_notification_uri(notification))
        assert response.status_code == http.client.OK
        check_notification_matches(notification, response.json())

    def test_read_notification_for_other(self):
        other = factory.make_User()
        notification = factory.make_Notification(user=other)
        response = self.client.get(get_notification_uri(notification))
        if self.user.is_superuser:
            assert response.status_code == http.client.OK
            check_notification_matches(notification, response.json())
        else:
            assert response.status_code == http.client.FORBIDDEN

    def test_read_notification_for_users(self):
        notification = factory.make_Notification(users=True)
        response = self.client.get(get_notification_uri(notification))
        assert response.status_code == http.client.OK
        check_notification_matches(notification, response.json())

    def test_read_notification_for_admins(self):
        notification = factory.make_Notification(admins=True)
        response = self.client.get(get_notification_uri(notification))
        if self.user.is_superuser:
            assert response.status_code == http.client.OK
            check_notification_matches(notification, response.json())
        else:
            assert response.status_code == http.client.FORBIDDEN

    def test_update_is_for_admins_only(self):
        notification = factory.make_Notification()
        message_new = factory.make_name("message")
        response = self.client.put(
            get_notification_uri(notification), {"message": message_new}
        )
        if self.user.is_superuser:
            assert response.status_code == http.client.OK
            notification = reload_object(notification)
            assert message_new == notification.message
            check_notification_matches(notification, response.json())
        else:
            assert response.status_code == http.client.FORBIDDEN

    def test_update_with_username_user_field(self):
        notification = factory.make_Notification()
        recipient = factory.make_User()
        response = self.client.put(
            get_notification_uri(notification),
            {
                "message": factory.make_name("message"),
                "user": recipient.username,
            },
        )
        if self.user.is_superuser:
            assert response.status_code == http.client.OK
            assert (
                response.json().get("user").get("username")
                == recipient.username
            )
        else:
            assert response.status_code == http.client.FORBIDDEN

    def test_update_rejects_unknown_username_user_field(self):
        notification = factory.make_Notification()
        response = self.client.put(
            get_notification_uri(notification),
            {
                "message": factory.make_name("message"),
                "user": "no-such-user",
            },
        )
        if self.user.is_superuser:
            assert response.status_code == http.client.BAD_REQUEST
            assert response.json().get("user") == [
                "Enter a valid user id or username."
            ]
        else:
            assert response.status_code == http.client.FORBIDDEN

    def test_delete_is_for_admins_only(self):
        notification = factory.make_Notification()
        response = self.client.delete(get_notification_uri(notification))
        if self.user.is_superuser:
            assert response.status_code == http.client.NO_CONTENT
            assert reload_object(notification) is None
        else:
            assert response.status_code == http.client.FORBIDDEN

    def test_dismiss_notification_for_self(self):
        notification = factory.make_Notification(user=self.user)
        response = self.client.post(
            get_notification_uri(notification), {"op": "dismiss"}
        )
        assert response.status_code == http.client.OK
        has_been_dismissed = NotificationDismissal.objects.filter(
            notification=notification, user=self.user
        ).exists()
        assert has_been_dismissed

    def test_dismiss_notification_for_other(self):
        other = factory.make_User()
        notification = factory.make_Notification(user=other)
        response = self.client.post(
            get_notification_uri(notification), {"op": "dismiss"}
        )
        assert response.status_code == http.client.FORBIDDEN

    def test_dismiss_notification_for_users(self):
        notification = factory.make_Notification(users=True)
        response = self.client.post(
            get_notification_uri(notification), {"op": "dismiss"}
        )
        if notification.is_relevant_to(self.user):
            assert response.status_code == http.client.OK
            has_been_dismissed = NotificationDismissal.objects.filter(
                notification=notification, user=self.user
            ).exists()
            assert has_been_dismissed
        else:
            assert response.status_code == http.client.FORBIDDEN

    def test_dismiss_notification_for_admins(self):
        notification = factory.make_Notification(admins=True)
        response = self.client.post(
            get_notification_uri(notification), {"op": "dismiss"}
        )
        if notification.is_relevant_to(self.user):
            assert response.status_code == http.client.OK
            has_been_dismissed = NotificationDismissal.objects.filter(
                notification=notification, user=self.user
            ).exists()
            assert has_been_dismissed
        else:
            assert response.status_code == http.client.FORBIDDEN


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("anonymous", id="user=anonymous,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNotificationAPI_Anonymous:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity):
        assert api_identity == "anonymous"
        self.client = MAASSensibleOAuthClient(user=AnonymousUser())

    def test_read_notification_for_other(self):
        other = factory.make_User()
        notification = factory.make_Notification(user=other)
        response = self.client.get(get_notification_uri(notification))
        assert response.status_code == http.client.UNAUTHORIZED

    def test_read_notification_for_users(self):
        notification = factory.make_Notification(users=True)
        response = self.client.get(get_notification_uri(notification))
        assert response.status_code == http.client.UNAUTHORIZED

    def test_read_notification_for_admins(self):
        notification = factory.make_Notification(admins=True)
        response = self.client.get(get_notification_uri(notification))
        assert response.status_code == http.client.UNAUTHORIZED

    def test_update_is_for_admins_only(self):
        notification = factory.make_Notification()
        message_new = factory.make_name("message")
        response = self.client.put(
            get_notification_uri(notification), {"message": message_new}
        )
        assert response.status_code == http.client.UNAUTHORIZED

    def test_delete_is_for_admins_only(self):
        notification = factory.make_Notification()
        response = self.client.delete(get_notification_uri(notification))
        assert response.status_code == http.client.UNAUTHORIZED


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNotificationsOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request):
        self.user = request.getfixturevalue(
            {"user": "maas_user"}[api_identity]
        )
        self.client = request.getfixturevalue(
            {"user": "api_client"}[api_identity]
        )

    def test_create_requires_can_edit_notifications(self):
        self.openfga_client.can_edit_notifications.return_value = True
        response = self.client.post(
            get_notifications_uri(), {"message": factory.make_name()}
        )
        assert http.client.OK == response.status_code
        self.openfga_client.can_edit_notifications.assert_called_once_with(
            self.user
        )


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNotificationOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request):
        self.user = request.getfixturevalue(
            {"user": "maas_user"}[api_identity]
        )
        self.client = request.getfixturevalue(
            {"user": "api_client"}[api_identity]
        )

    def test_view_all_if_can_view_notifications(self):
        self.openfga_client.can_view_notifications.return_value = True
        other = factory.make_User()
        notification = factory.make_Notification(user=other)
        response = self.client.get(get_notification_uri(notification))
        assert http.client.OK == response.status_code
        self.openfga_client.can_view_notifications.assert_called()

    def test_update_requires_can_edit_notifications(self):
        self.openfga_client.can_edit_notifications.return_value = True
        notification = factory.make_Notification()
        message_new = factory.make_name("message")
        response = self.client.put(
            get_notification_uri(notification), {"message": message_new}
        )
        assert http.client.OK == response.status_code
        self.openfga_client.can_edit_notifications.assert_called_once_with(
            self.user
        )

    def test_delete_requires_can_edit_notifications(self):
        self.openfga_client.can_edit_notifications.return_value = True
        notification = factory.make_Notification()
        response = self.client.delete(get_notification_uri(notification))
        assert http.client.NO_CONTENT == response.status_code
        self.openfga_client.can_edit_notifications.assert_called_once_with(
            self.user
        )
