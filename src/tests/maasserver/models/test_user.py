# Copyright 2012-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from unittest.mock import sentinel

from django.contrib.auth.models import User
from django.db import IntegrityError
from piston3.models import KEY_SIZE, SECRET_SIZE
import pytest

from apiclient.creds import convert_string_to_tuple, convert_tuple_to_string
from maasserver import models
from maasserver.models.user import (
    create_auth_token,
    get_auth_tokens,
    get_creds_tuple,
)
from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestUser:
    def test_user_email_null(self):
        user = User.objects.create_user(username=factory.make_string())
        assert user.email is None

    def test_user_email_blank(self):
        user = User.objects.create_user(
            username=factory.make_string(), email=""
        )
        assert user.email is None

    def test_user_email_unique(self):
        email = factory.make_email()
        User.objects.create_user(username=factory.make_string(), email=email)
        with pytest.raises(IntegrityError):
            User.objects.create_user(
                username=factory.make_string(), email=email
            )

    def test_has_perm_is_patched(self, mocker):
        mock_has_perm = mocker.patch.object(models, "_user_has_perm")
        user = factory.make_User()
        user.has_perm(sentinel.perm, sentinel.obj)
        mock_has_perm.assert_called_once_with(
            user, sentinel.perm, sentinel.obj
        )


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestAuthTokens:
    """Test creation and retrieval of auth tokens."""

    @staticmethod
    def _assert_token_valid(token):
        assert isinstance(token.key, str)
        assert len(token.key) == KEY_SIZE
        assert isinstance(token.secret, str)
        assert len(token.secret) == SECRET_SIZE

    @staticmethod
    def _assert_consumer_valid(consumer):
        assert isinstance(consumer.key, str)
        assert len(consumer.key) == KEY_SIZE
        assert consumer.secret == ""

    def test_create_auth_token(self):
        user = factory.make_User()
        token = create_auth_token(user)
        assert token.user == user
        assert token.consumer.user == user
        assert token.is_approved
        TestAuthTokens._assert_consumer_valid(token.consumer)
        TestAuthTokens._assert_token_valid(token)

    def test_get_auth_tokens_finds_tokens_for_user(self):
        user = factory.make_User()
        token = create_auth_token(user)
        assert token in get_auth_tokens(user)

    def test_get_auth_tokens_ignores_other_users(self):
        user, other_user = factory.make_User(), factory.make_User()
        unrelated_token = create_auth_token(other_user)
        assert unrelated_token not in get_auth_tokens(user)

    def test_get_auth_tokens_ignores_unapproved_tokens(self):
        user = factory.make_User()
        token = create_auth_token(user)
        token.is_approved = False
        token.save()
        assert token not in get_auth_tokens(user)

    def test_get_creds_tuple_returns_creds(self):
        token = create_auth_token(factory.make_User())
        assert get_creds_tuple(token) == (
            token.consumer.key,
            token.key,
            token.secret,
        )

    def test_get_creds_tuple_integrates_with_api_client(self):
        creds_tuple = get_creds_tuple(create_auth_token(factory.make_User()))
        assert (
            convert_string_to_tuple(convert_tuple_to_string(creds_tuple))
            == creds_tuple
        )
