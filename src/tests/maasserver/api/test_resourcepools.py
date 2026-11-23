# Copyright 2018-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for resource pools API."""

import http.client
import json

from django.conf import settings
from django.urls import reverse
import pytest

from maasserver.models import ResourcePool
from maasserver.testing.factory import factory
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestResourcePoolsAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_handler_path(self):
        assert "/MAAS/api/2.0/resourcepools/" == reverse(
            "resourcepools_handler"
        )

    def test_create_pool(self, admin_api_client):
        name = factory.make_name("name")
        description = factory.make_name("description")
        response = admin_api_client.post(
            reverse("resourcepools_handler"),
            {"name": name, "description": description},
        )
        assert response.status_code == http.client.OK
        pool = ResourcePool.objects.get(name=name)
        assert pool.description == description

    def test_create_requires_admin(self):
        name = factory.make_name("name")
        description = factory.make_name("description")
        response = self.client.post(
            reverse("resourcepools_handler"),
            {"name": name, "description": description},
        )
        assert response.status_code == http.client.FORBIDDEN

    def test_list_returns_pools_list(self):
        pools = [factory.make_ResourcePool() for _ in range(3)]
        # include the default pool
        pools.append(ResourcePool.objects.get_default_resource_pool())
        response = self.client.get(reverse("resourcepools_handler"), {})
        assert http.client.OK == response.status_code, response.content
        result = json.loads(response.content.decode(settings.DEFAULT_CHARSET))
        assert sorted(
            (pool["name"], pool["description"], pool["resource_uri"])
            for pool in result
        ) == sorted(
            (
                pool.name,
                pool.description,
                reverse("resourcepool_handler", args=[pool.id]),
            )
            for pool in pools
        )


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestResourcePoolsAPIOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_create_requires_can_edit_machines(self):
        self.openfga_client.can_edit_machines.return_value = True
        name = factory.make_name("name")
        description = factory.make_name("description")
        response = self.client.post(
            reverse("resourcepools_handler"),
            {"name": name, "description": description},
        )
        assert response.status_code == http.client.OK
        self.openfga_client.can_edit_machines.assert_called_once_with(
            self.user
        )
