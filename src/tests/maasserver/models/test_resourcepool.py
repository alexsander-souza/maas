# Copyright 2013-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test ResourcePool objects."""

from collections import Counter

from django.core.exceptions import PermissionDenied, ValidationError
import pytest

from maasserver.models.resourcepool import (
    DEFAULT_RESOURCEPOOL_DESCRIPTION,
    DEFAULT_RESOURCEPOOL_NAME,
    ResourcePool,
)
from maasserver.permissions import ResourcePoolPermission
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestResourcePoolManager:
    """Tests for `ResourcePool` manager."""

    def test_get_default_resource_pool_returns_default_pool(self):
        pool = ResourcePool.objects.get_default_resource_pool()
        assert pool.id == 0
        assert pool.name == DEFAULT_RESOURCEPOOL_NAME
        assert pool.description == DEFAULT_RESOURCEPOOL_DESCRIPTION
        assert pool.created is not None
        assert pool.updated is not None

    def test_get_default_resource_pool_ignores_other_pools(self):
        factory.make_ResourcePool()
        assert (
            ResourcePool.objects.get_default_resource_pool().name
            == DEFAULT_RESOURCEPOOL_NAME
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestResourcePool:
    def test_init(self):
        name = factory.make_name("name")
        description = factory.make_name("description")
        pool = ResourcePool(name=name, description=description)
        pool.save()
        pool = reload_object(pool)
        assert pool.name == name
        assert pool.description == description

    def test_is_default_true(self):
        assert ResourcePool.objects.get_default_resource_pool().is_default()

    def test_is_default_false(self):
        assert not factory.make_ResourcePool().is_default()

    def test_delete(self):
        pool = factory.make_ResourcePool()
        pool.delete()
        assert reload_object(pool) is None

    def test_delete_default_fails(self):
        pool = ResourcePool.objects.get_default_resource_pool()
        with pytest.raises(ValidationError):
            pool.delete()

    def test_delete_pool_with_machines_fails(self):
        pool = ResourcePool.objects.get_default_resource_pool()
        factory.make_Node(pool=pool)
        with pytest.raises(ValidationError):
            pool.delete()


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestResourcePoolManagerGetResourcePoolOr404:
    def test_user_view_returns_resource_pool(self):
        user = factory.make_User()
        pool = factory.make_ResourcePool()
        assert pool == ResourcePool.objects.get_resource_pool_or_404(
            pool.id, user, ResourcePoolPermission.view
        )

    def test_user_edit_raises_PermissionError(self):
        user = factory.make_User()
        pool = factory.make_ResourcePool()
        with pytest.raises(PermissionDenied):
            ResourcePool.objects.get_resource_pool_or_404(
                pool.id, user, ResourcePoolPermission.edit
            )

    def test_admin_view_returns_resource_pool(self):
        admin = factory.make_admin()
        pool = factory.make_ResourcePool()
        assert pool == ResourcePool.objects.get_resource_pool_or_404(
            pool.id, admin, ResourcePoolPermission.view
        )

    def test_admin_edit_returns_resource_pool(self):
        admin = factory.make_admin()
        pool = factory.make_ResourcePool()
        assert pool == ResourcePool.objects.get_resource_pool_or_404(
            pool.id, admin, ResourcePoolPermission.edit
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestResourcePoolManagerGetResourcePools:
    def test_user_returns_all(self):
        user = factory.make_User()
        factory.make_ResourcePool()
        assert Counter(ResourcePool.objects.all()) == Counter(
            ResourcePool.objects.get_resource_pools(user)
        )
