# Copyright 2013-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the `describe` view."""

import http.client
from urllib.parse import urlparse

from django.test.client import RequestFactory
from django.urls import get_script_prefix, reverse, set_script_prefix
import pytest

from maasserver.api.doc import get_api_description
from maasserver.api.doc_handler import describe
from maasserver.testing.factory import factory
from maasserver.testing.testclient import MAASSensibleOAuthClient
from maasserver.utils.converters import json_load_bytes


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestDescribe:
    """Tests for the `describe` view."""

    @pytest.fixture(
        params=["anonymous", "user", "admin"],
        ids=[
            "user=anonymous,client=oauth",
            "user=user,client=oauth",
            "user=admin,client=oauth",
        ],
    )
    def client(self, request):
        if request.param == "user":
            return request.getfixturevalue("api_client")
        elif request.param == "admin":
            return request.getfixturevalue("admin_api_client")
        else:
            return MAASSensibleOAuthClient()

    def test_describe_returns_json(self, client):
        response = client.get(reverse("describe"))
        assert response.status_code == http.client.OK
        assert response["Content-Type"] == "application/json"
        assert response.json() is not None

    def test_describe(self, client):
        response = client.get(reverse("describe"))
        description = json_load_bytes(response.content)
        assert set(description) == {"doc", "handlers", "resources", "hash"}
        assert isinstance(description["handlers"], list)

    def test_describe_hash_is_the_api_hash(self, client):
        response = client.get(reverse("describe"))
        description = json_load_bytes(response.content)
        assert description["hash"] == get_api_description()["hash"]


class TestDescribeAbsoluteURIs:
    """Tests for the `describe` view's URI manipulation."""

    def make_params(self, path_info, script_name, scheme):
        """Create parameters for http request, based on current scenario."""
        return {
            "PATH_INFO": path_info,
            "SCRIPT_NAME": script_name,
            "SERVER_NAME": factory.make_name("server").lower(),
            "wsgi.url_scheme": scheme,
        }

    def get_description(self, params):
        """GET the API description (at a random API path), as JSON."""
        path = "/%s/describe" % factory.make_name("path")
        request = RequestFactory().get(path, **params)
        response = describe(request)
        assert http.client.OK == response.status_code, (
            "API description failed with code %s:\n%s"
            % (
                response.status_code,
                response.content,
            )
        )
        return json_load_bytes(response.content)

    def patch_script_prefix(self, script_name):
        """Patch up Django's and Piston's notion of the script_name prefix.

        This manipulates how Piston gets Django's version of script_name
        which it needs so that it can prefix script_name to URL paths.
        """
        # clear the cached API description since the following patching causes
        # changes in the handlers URIs
        get_api_description.cache_clear()
        # Patching up get_script_prefix doesn't seem to do the trick,
        # and patching it in the right module requires unwarranted
        # intimacy with Piston.  So just go through the proper call and
        # set the prefix.  But clean this up after the test or it will
        # break other tests!
        original_prefix = get_script_prefix()
        set_script_prefix(script_name)
        return original_prefix

    @pytest.mark.parametrize(
        "scheme", ["http", "https"], ids=["http", "https"]
    )
    @pytest.mark.parametrize(
        "script_name,path_info",
        [
            ("", ""),
            ("/foo/bar", ""),
            ("/foo", "/bar"),
        ],
        ids=["script-at-root", "script-below-root-1", "script-below-root-2"],
    )
    def test_handler_uris_are_absolute(self, scheme, script_name, path_info):
        params = self.make_params(path_info, script_name, scheme)
        server = params["SERVER_NAME"]

        # Without this, the test wouldn't be able to detect accidental
        # duplication of the script_name portion of the URL path:
        # /MAAS/MAAS/api/...
        original_prefix = self.patch_script_prefix(script_name)
        try:
            description = self.get_description(params)
            resources = description["resources"]

            assert resources != []
            for resource in resources:
                anon_response = resource["anon"]
                auth_response = resource["auth"]

                if anon_response is None:
                    matcher = auth_response
                else:
                    matcher = anon_response
                url = urlparse(matcher["uri"])
                assert url.scheme == scheme
                assert url.hostname == server
                assert url.path.startswith(f"{script_name}/api/")
        finally:
            set_script_prefix(original_prefix)
