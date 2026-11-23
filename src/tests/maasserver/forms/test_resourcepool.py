# Copyright 2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `ResourcePoolForm`."""

import pytest

from maasserver.forms import ResourcePoolForm
from maasserver.models import ResourcePool
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestResourcePost:
    """Tests for `ResourcePoolForm`."""

    def test_creates_pool(self):
        name = factory.make_name("pool")
        description = factory.make_string()
        form = ResourcePoolForm(
            data={"name": name, "description": description}
        )
        form.save()
        pool = ResourcePool.objects.get(name=name)
        assert pool is not None
        assert pool.description == description

    def test_updates_pool(self):
        pool = factory.make_ResourcePool()
        new_description = factory.make_string()
        form = ResourcePoolForm(
            data={"description": new_description}, instance=pool
        )
        form.save()
        pool = reload_object(pool)
        assert pool.description == new_description

    def test_renames_pool(self):
        pool = factory.make_ResourcePool()
        new_name = factory.make_name("pool")
        form = ResourcePoolForm(data={"name": new_name}, instance=pool)
        form.save()
        pool = reload_object(pool)
        assert pool.name == new_name
