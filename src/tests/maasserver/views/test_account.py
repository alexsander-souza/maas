# Copyright 2012-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from http import HTTPStatus
import http.client
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import SESSION_KEY
from django.urls import reverse
import pytest

from maascommon.events import AUDIT
from maascommon.logging.security import (
    AUTHN_LOGIN_SUCCESSFUL,
    AUTHN_LOGIN_UNSUCCESSFUL,
    SECURITY,
)
from maasserver.models.event import Event
from maasserver.models.user import create_auth_token, get_auth_tokens
from maasserver.testing.testclient import MAASSensibleClient
from maasserver.utils.converters import json_load_bytes


@pytest.fixture
def client():
    return MAASSensibleClient()


@pytest.mark.usefixtures("maasdb", "maas_region_test")
class TestLogin:
    def test_login_GET_returns_not_authenticated(self, client):
        client.handler.enforce_csrf_checks = True
        response = client.get(reverse("login"))
        assert response.status_code == http.client.OK
        assert json_load_bytes(response.content) == {
            "authenticated": False,
            "no_users": True,
        }

    def test_login_GET_returns_not_authenticated_with_users(
        self, client, factory
    ):
        factory.make_User()
        client.handler.enforce_csrf_checks = True
        response = client.get(reverse("login"))
        assert response.status_code == http.client.OK
        assert json_load_bytes(response.content) == {
            "authenticated": False,
            "no_users": False,
        }

    def test_login_GET_returns_authenticated(self, client, factory):
        password = factory.make_string()
        user = factory.make_User(password=password)
        client.handler.enforce_csrf_checks = True
        client.login(username=user.username, password=password)
        response = client.get(reverse("login"))
        assert response.status_code == http.client.OK
        assert json_load_bytes(response.content) == {
            "authenticated": True,
            "no_users": False,
        }

    def test_login_returns_204_when_already_authenticated(
        self, client, factory
    ):
        password = factory.make_string()
        user = factory.make_User(password=password)
        client.handler.enforce_csrf_checks = True
        client.login(username=user.username, password=password)
        response = client.post(reverse("login"))
        assert response.status_code == http.client.NO_CONTENT

    def test_login_returns_204_on_authentication(self, client, factory):
        password = factory.make_string()
        user = factory.make_User(password=password)
        client.handler.enforce_csrf_checks = True
        response = client.post(
            reverse("login"), {"username": user.username, "password": password}
        )
        assert response.status_code == http.client.NO_CONTENT
        assert response.cookies.keys() == {"csrftoken", "sessionid"}

    def test_login_returns_400_on_bad_authentication(self, client, factory):
        password = factory.make_string()
        factory.make_User(password=password)
        client.handler.enforce_csrf_checks = True
        response = client.post(
            reverse("login"),
            {
                "username": factory.make_name("username"),
                "password": factory.make_name("password"),
            },
        )
        assert response.status_code == http.client.BAD_REQUEST

    def test_login_creates_audit_event(self, client, factory):
        password = factory.make_string()
        user = factory.make_User(password=password)
        client.post(
            reverse("login"), {"username": user.username, "password": password}
        )
        event = Event.objects.get(type__level=AUDIT)
        assert event is not None
        assert event.description == "Logged in user."

    def test_login_creates_log(self, client, factory):
        password = factory.make_string()
        user = factory.make_User(password=password)
        with patch("maasserver.views.account.logger") as mock_logger:
            client.post(
                reverse("login"),
                {"username": user.username, "password": password},
            )
        mock_logger.info.assert_called_once_with(
            AUTHN_LOGIN_SUCCESSFUL,
            type=SECURITY,
            user_id=user.username,
            role="User",
        )

    def test_failed_login_creates_log(self, client, factory):
        password = factory.make_string()
        user = factory.make_User(password=password)
        with patch("maasserver.views.account.logger") as mock_logger:
            client.post(
                reverse("login"),
                {"username": user.username, "password": "wrong"},
            )
        mock_logger.info.assert_called_once_with(
            AUTHN_LOGIN_UNSUCCESSFUL,
            type=SECURITY,
            user_id=user.username,
        )


@pytest.mark.usefixtures("maasdb", "maas_region_test")
class TestLogout:
    def test_logout_returns_204(self, client, factory):
        password = factory.make_string()
        user = factory.make_User(password=password)
        client.handler.enforce_csrf_checks = True
        client.login(username=user.username, password=password)
        client.handler.enforce_csrf_checks = False
        response = client.post(reverse("logout"))
        assert response.status_code == http.client.NO_CONTENT
        assert SESSION_KEY not in client.session

    def test_logout_GET_returns_405(self, client, factory):
        password = factory.make_string()
        user = factory.make_User(password=password)
        client.handler.enforce_csrf_checks = True
        client.login(username=user.username, password=password)
        client.handler.enforce_csrf_checks = False
        response = client.get(reverse("logout"))
        assert response.status_code == http.client.METHOD_NOT_ALLOWED

    def test_logout_creates_audit_event(self, client, factory):
        password = factory.make_string()
        user = factory.make_User(password=password)
        client.handler.enforce_csrf_checks = True
        client.login(username=user.username, password=password)
        client.handler.enforce_csrf_checks = False
        client.post(reverse("logout"))
        event = Event.objects.get(type__level=AUDIT)
        assert event is not None
        assert event.description == "Logged out user."


def token_to_dict(token):
    return {
        "token_key": token.key,
        "token_secret": token.secret,
        "consumer_key": token.consumer.key,
        "name": token.consumer.name,
    }


@pytest.mark.usefixtures("maasdb", "maas_region_test")
class TestAuthenticate:
    """Tests for the `authenticate` view."""

    def test_returns_existing_credentials(self, client, factory):
        username = factory.make_name("username")
        password = factory.make_name("password")
        user = factory.make_User(username, password)
        [token] = get_auth_tokens(user)
        response = client.post(
            reverse("authenticate"),
            data={"username": username, "password": password},
        )
        assert response.status_code == http.client.OK
        assert token_to_dict(token) == json_load_bytes(response.content)

    def test_returns_first_of_existing_credentials(self, client, factory):
        username = factory.make_name("username")
        password = factory.make_name("password")
        user = factory.make_User(username, password)
        [token] = get_auth_tokens(user)
        for i in range(1, 6):
            create_auth_token(user, "Token #%d" % i)
        response = client.post(
            reverse("authenticate"),
            data={"username": username, "password": password},
        )
        assert response.status_code == http.client.OK
        assert token_to_dict(token) == json_load_bytes(response.content)

    def test_returns_existing_named_credentials(self, client, factory):
        username = factory.make_name("username")
        password = factory.make_name("password")
        consumer = factory.make_name("consumer")
        user = factory.make_User(username, password)
        token = create_auth_token(user, consumer)
        response = client.post(
            reverse("authenticate"),
            data={
                "username": username,
                "password": password,
                "consumer": consumer,
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert token_to_dict(token) == json_load_bytes(response.content)

    def test_returns_first_of_existing_named_credentials(
        self, client, factory
    ):
        username = factory.make_name("username")
        password = factory.make_name("password")
        consumer = factory.make_name("consumer")
        user = factory.make_User(username, password)
        tokens = [create_auth_token(user, consumer) for _ in range(1, 6)]
        response = client.post(
            reverse("authenticate"),
            data={
                "username": username,
                "password": password,
                "consumer": consumer,
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert token_to_dict(tokens[0]) == json_load_bytes(response.content)

    def test_returns_new_credentials(self, client, factory):
        username = factory.make_name("username")
        password = factory.make_name("password")
        user = factory.make_User(username, password)
        get_auth_tokens(user).delete()  # Delete all tokens.
        response = client.post(
            reverse("authenticate"),
            data={"username": username, "password": password},
        )
        assert response.status_code == HTTPStatus.OK
        [token] = get_auth_tokens(user)
        assert token_to_dict(token) == json_load_bytes(response.content)

    def test_returns_new_named_credentials(self, client, factory):
        username = factory.make_name("username")
        password = factory.make_name("password")
        consumer = factory.make_name("consumer")
        user = factory.make_User(username, password)
        get_auth_tokens(user).delete()  # Delete all tokens.
        response = client.post(
            reverse("authenticate"),
            data={
                "username": username,
                "password": password,
                "consumer": consumer,
            },
        )
        assert response.status_code == HTTPStatus.OK
        assert json_load_bytes(response.content).get("name") == consumer

    def test_rejects_unknown_username(self, client, factory):
        username = factory.make_name("username")
        password = factory.make_name("password")
        response = client.post(
            reverse("authenticate"),
            data={"username": username, "password": password},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_rejects_incorrect_password(self, client, factory):
        username = factory.make_name("username")
        password = factory.make_name("password")
        factory.make_User(username, password)
        response = client.post(
            reverse("authenticate"),
            data={"username": username, "password": password + "-garbage"},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_rejects_inactive_user(self, client, factory):
        username = factory.make_name("username")
        password = factory.make_name("password")
        user = factory.make_User(username, password)
        user.is_active = False
        user.save()
        response = client.post(
            reverse("authenticate"),
            data={"username": username, "password": password},
        )
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_rejects_GET(self, client):
        response = client.get(reverse("authenticate"))
        assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED
        assert "POST" == response["Allow"]

    def test_authenticate_creates_audit_event_with_tokens(
        self, client, factory
    ):
        username = factory.make_name("username")
        password = factory.make_name("password")
        user = factory.make_User(username, password)
        user.save()
        client.post(
            reverse("authenticate"),
            data={"username": username, "password": password},
        )
        event = Event.objects.get(type__level=AUDIT)
        assert event is not None
        assert event.description == "Retrieved API (OAuth) token."

    def test_authenticate_creates_audit_event_without_tokens(
        self, client, factory
    ):
        username = factory.make_name("username")
        password = factory.make_name("password")
        consumer = factory.make_name("consumer")
        user = factory.make_User(username, password)
        user.save()
        client.post(
            reverse("authenticate"),
            data={
                "username": username,
                "password": password,
                "consumer": consumer,
            },
        )
        event = Event.objects.get(type__level=AUDIT)
        assert event is not None
        assert event.description == "Created API (OAuth) token."


@pytest.mark.usefixtures("maasdb", "maas_region_test")
class TestCSRF:
    def test_method_not_allowed_on_get(self, client):
        response = client.get(reverse("csrf"))
        assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED

    def test_method_not_allowed_on_put(self, client):
        response = client.put(reverse("csrf"))
        assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED

    def test_method_not_allowed_on_delete(self, client):
        response = client.delete(reverse("csrf"))
        assert response.status_code == HTTPStatus.METHOD_NOT_ALLOWED

    def test_forbidden_when_not_authenticated(self, client):
        response = client.post(reverse("csrf"))
        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_returns_csrf(self, client, factory):
        # Force the client to test for CSRF because the view should be CSRF
        # exempt. If not exempt then the `client.post` would fail.
        client.handler.enforce_csrf_checks = True
        client.login(user=factory.make_User())
        response = client.post(reverse("csrf"))
        assert response.status_code == HTTPStatus.OK
        body = json_load_bytes(response.content)
        assert "csrf" in body
        # Should not have an updated CSRF cookie, because it was marked as
        # not used.
        assert response.cookies.get(settings.CSRF_COOKIE_NAME) is None
