# Copyright 2018-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for resource pool API."""

import http.client
import json

from django.conf import settings
from django.urls import reverse
import pytest

from maasserver.models import ResourcePool
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestResourcePoolAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_handler_path(self):
        assert reverse("resourcepool_handler", args=[123]) == (
            "/MAAS/api/2.0/resourcepool/123/"
        )

    def test_POST_disallowed_for_creation(self, admin_api_client):
        name = factory.make_name("name")
        description = factory.make_name("description")
        response = admin_api_client.post(
            reverse("resourcepool_handler", args=[123]),
            {"name": name, "description": description},
        )
        assert response.status_code == http.client.METHOD_NOT_ALLOWED

    def test_GET_returns_pool(self):
        pool = factory.make_ResourcePool()
        response = self.client.get(
            reverse("resourcepool_handler", args=[pool.id]), {}
        )
        assert response.status_code == http.client.OK
        result = json.loads(response.content.decode(settings.DEFAULT_CHARSET))
        assert result["name"] == pool.name
        assert result["description"] == pool.description
        assert result["resource_uri"] == (
            f"/MAAS/api/2.0/resourcepool/{pool.id}/"
        )

    def test_PUT_updates_pool(self, admin_api_client):
        pool = factory.make_ResourcePool()
        new_name = factory.make_name("name")
        new_description = factory.make_name("description")
        response = admin_api_client.put(
            reverse("resourcepool_handler", args=[pool.id]),
            {"name": new_name, "description": new_description},
        )
        assert response.status_code == http.client.OK
        pool = reload_object(pool)
        assert pool.name == new_name
        assert pool.description == new_description

    def test_PUT_updates_pool_by_name(self, admin_api_client):
        pool = factory.make_ResourcePool()
        new_name = factory.make_name("name")
        new_description = factory.make_name("description")
        response = admin_api_client.put(
            reverse("resourcepool_handler", args=[pool.name]),
            {"name": new_name, "description": new_description},
        )
        assert response.status_code == http.client.OK
        pool = reload_object(pool)
        assert pool.name == new_name
        assert pool.description == new_description

    def test_PUT_missing(self, admin_api_client):
        description = factory.make_string()
        response = admin_api_client.get(
            reverse("resourcepool_handler", args=[-1]),
            {"description": description},
        )
        assert response.status_code == http.client.NOT_FOUND

    def test_PUT_requires_admin(self):
        pool = factory.make_ResourcePool()
        response = self.client.put(
            reverse("resourcepool_handler", args=[pool.id]),
            {"description": factory.make_string()},
        )
        assert response.status_code == http.client.FORBIDDEN

    def test_DELETE_removes_pool_by_id(self, admin_api_client):
        pool = factory.make_ResourcePool()
        response = admin_api_client.delete(
            reverse("resourcepool_handler", args=[pool.id]), {}
        )
        assert response.status_code == http.client.NO_CONTENT
        assert reload_object(pool) is None

    def test_DELETE_removes_pool_by_name(self, admin_api_client):
        pool = factory.make_ResourcePool()
        response = admin_api_client.delete(
            reverse("resourcepool_handler", args=[pool.name]), {}
        )
        assert response.status_code == http.client.NO_CONTENT
        assert reload_object(pool) is None

    def test_DELETE_default_pool_denied(self, admin_api_client):
        response = admin_api_client.delete(
            reverse("resourcepool_handler", args=[0]), {}
        )
        assert response.status_code == http.client.BAD_REQUEST
        assert ResourcePool.objects.get_default_resource_pool() is not None

    def test_DELETE_requires_admin(self):
        pool = factory.make_ResourcePool()
        response = self.client.delete(
            reverse("resourcepool_handler", args=[pool.id]), {}
        )
        assert response.status_code == http.client.FORBIDDEN

    def test_DELETE_is_idempotent(self, admin_api_client):
        pool = factory.make_ResourcePool()
        response = admin_api_client.delete(
            reverse("resourcepool_handler", args=[pool.id])
        )
        assert response.status_code == http.client.NO_CONTENT
        assert reload_object(pool) is None


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestResourcePoolAPIOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_read_requires_can_view_available_machines_in_pool(self):
        self.openfga_client.can_view_available_machines_in_pool.return_value = True
        pool = factory.make_ResourcePool()
        response = self.client.get(
            reverse("resourcepool_handler", args=[pool.id]), {}
        )
        assert response.status_code == http.client.OK
        self.openfga_client.can_view_available_machines_in_pool.assert_called_once_with(
            self.user, pool.id
        )

    def test_update_requires_can_edit_machines_in_pool(self):
        self.openfga_client.can_edit_machines_in_pool.return_value = True
        pool = factory.make_ResourcePool()
        new_name = factory.make_name("name")
        new_description = factory.make_name("description")
        response = self.client.put(
            reverse("resourcepool_handler", args=[pool.id]),
            {"name": new_name, "description": new_description},
        )
        assert response.status_code == http.client.OK
        self.openfga_client.can_edit_machines_in_pool.assert_called_once_with(
            self.user, pool.id
        )

    def test_delete_requires_can_edit_machines(self):
        self.openfga_client.can_edit_machines.return_value = True
        pool = factory.make_ResourcePool()
        response = self.client.delete(
            reverse("resourcepool_handler", args=[pool.id]), {}
        )
        assert response.status_code == http.client.NO_CONTENT
        self.openfga_client.can_edit_machines.assert_called_once_with(
            self.user
        )
