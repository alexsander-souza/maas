# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


import http.client
import json

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.urls import reverse
import pytest

from maasserver.api.version import API_CAPABILITIES_LIST
from maasserver.models import ControllerInfo
from maasserver.testing.factory import factory
from maasserver.testing.testclient import MAASSensibleOAuthClient


@pytest.mark.parametrize(
    "api_identity",
    [
        pytest.param("anonymous", id="user=anonymous,client=oauth"),
        pytest.param("user", id="user=user,client=oauth"),
        pytest.param("admin", id="user=admin,client=oauth"),
    ],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestVersionAPIBasics:
    """Basic tests for /version/ API."""

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request):
        if api_identity == "anonymous":
            self.client = MAASSensibleOAuthClient(user=AnonymousUser())
        elif api_identity == "admin":
            self.client = request.getfixturevalue("admin_api_client")
        else:
            self.client = request.getfixturevalue("api_client")

    def test_handler_path(self):
        assert "/MAAS/api/2.0/version/" == reverse("version_handler")


@pytest.mark.parametrize(
    "api_identity",
    [
        pytest.param("anonymous", id="user=anonymous,client=oauth"),
        pytest.param("user", id="user=user,client=oauth"),
    ],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestVersionAPI:
    """Tests for /version/ API."""

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request):
        if api_identity == "anonymous":
            self.client = MAASSensibleOAuthClient(user=AnonymousUser())
        else:
            self.client = request.getfixturevalue("api_client")

    def test_GET_returns_details(self):
        ControllerInfo.objects.set_version(
            factory.make_RegionRackController(), "3.0.0~beta1"
        )

        response = self.client.get(reverse("version_handler"))
        assert http.client.OK == response.status_code

        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert {
            "capabilities": API_CAPABILITIES_LIST,
            "version": "3.0.0~beta1",
            "subversion": "",
        } == parsed_result
