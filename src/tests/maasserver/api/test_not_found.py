# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the not found handler."""

import http.client

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse
import pytest

from maasserver.testing.factory import factory
from maasserver.testing.testclient import MAASSensibleOAuthClient


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNotFoundHandler:
    @pytest.mark.parametrize(
        "user_kind",
        ["anonymous", "user", "admin"],
        ids=[
            "user=anonymous,client=oauth",
            "user=user,client=oauth",
            "user=admin,client=oauth",
        ],
    )
    @pytest.mark.parametrize(
        "method",
        [
            pytest.param("get", id="GET"),
            pytest.param("post", id="POST"),
            pytest.param("put", id="PUT"),
            pytest.param("delete", id="DELETE"),
        ],
    )
    def test_calling_bogus_handler_returns_not_found(self, user_kind, method):
        if user_kind == "anonymous":
            user = AnonymousUser()
        elif user_kind == "admin":
            user = factory.make_admin()
        else:
            user = factory.make_User()
        client = MAASSensibleOAuthClient(user=user)

        handler_url = reverse("nodes_handler")
        handler_url += "/".join(factory.make_name("path") for _ in range(5))
        response = getattr(client, method)(handler_url)

        assert http.client.NOT_FOUND == response.status_code
        assert "text/plain; charset=utf-8" == response["content-type"]
        assert (
            "Unknown API endpoint: %s." % handler_url
            == response.content.decode(settings.DEFAULT_CHARSET)
        )
