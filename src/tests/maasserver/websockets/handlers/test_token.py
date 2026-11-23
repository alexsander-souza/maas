# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maasserver.websockets.handlers.token`"""

import pytest

from maascommon.events import AUDIT
from maasserver.models.event import Event
from maasserver.models.user import create_auth_token, get_auth_tokens
from maasserver.testing.factory import factory
from maasserver.utils.orm import get_one
from maasserver.websockets.base import HandlerDoesNotExistError
from maasserver.websockets.handlers.token import TokenHandler


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestTokenHandler:
    def dehydrate_token(self, token):
        return {
            "id": token.id,
            "key": token.key,
            "secret": token.secret,
            "consumer": {
                "key": token.consumer.key,
                "name": token.consumer.name,
            },
        }

    def test_get(self):
        user = factory.make_User()
        handler = TokenHandler(user, {}, None)
        token = create_auth_token(user)
        assert self.dehydrate_token(token) == handler.get({"id": token.id})

    def test_get_doesnt_work_if_not_owned(self):
        user = factory.make_User()
        handler = TokenHandler(user, {}, None)
        not_owned_token = create_auth_token(factory.make_User())
        pytest.raises(
            HandlerDoesNotExistError, handler.get, {"id": not_owned_token.id}
        )

    def test_list(self):
        user = factory.make_User()
        handler = TokenHandler(user, {}, None)
        create_auth_token(user)
        expected_tokens = [
            self.dehydrate_token(token) for token in get_auth_tokens(user)
        ]
        assert sorted(expected_tokens, key=repr) == sorted(
            handler.list({}), key=repr
        )

    def test_create_no_name(self):
        user = factory.make_User()
        handler = TokenHandler(user, {}, None)
        new_token = handler.create({})
        assert new_token.keys() == {"id", "key", "secret", "consumer"}
        event = Event.objects.get(type__level=AUDIT)
        assert event is not None
        assert event.description == "Created token."

    def test_create_with_name(self):
        user = factory.make_User()
        handler = TokenHandler(user, {}, None)
        name = factory.make_name("name")
        new_token = handler.create({"name": name})
        assert new_token.keys() == {"id", "key", "secret", "consumer"}
        assert name == new_token["consumer"]["name"]
        event = Event.objects.get(type__level=AUDIT)
        assert event is not None
        assert event.description == "Created token."

    def test_update(self):
        user = factory.make_User()
        handler = TokenHandler(user, {}, None)
        name = factory.make_name("name")
        token = create_auth_token(user, name)
        new_name = factory.make_name("name")
        updated_token = handler.update({"id": token.id, "name": new_name})
        assert updated_token.keys() == {"id", "key", "secret", "consumer"}
        assert new_name == updated_token["consumer"]["name"]
        event = Event.objects.get(type__level=AUDIT)
        assert event is not None
        assert event.description == "Modified consumer name of token."

    def test_delete(self):
        user = factory.make_User()
        token = create_auth_token(user)
        handler = TokenHandler(user, {}, None)
        handler.delete({"id": token.id})
        assert get_one(get_auth_tokens(user).filter(id=token.id)) is None
