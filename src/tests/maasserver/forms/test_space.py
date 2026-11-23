# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for Space forms."""

import pytest

from maasserver.forms.space import SpaceForm
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestSpaceForm:
    def test_requires_name(self):
        form = SpaceForm({})
        assert form.is_valid(), form.errors

    def test_creates_space(self):
        space_name = factory.make_name("space")
        space_description = factory.make_name("description")
        form = SpaceForm(
            {"name": space_name, "description": space_description}
        )
        assert form.is_valid(), form.errors
        space = form.save()
        assert space.get_name() == space_name
        assert space.description == space_description

    def test_doest_require_name_on_update(self):
        space = factory.make_Space()
        form = SpaceForm(instance=space, data={})
        assert form.is_valid(), form.errors

    def test_updates_space(self):
        new_name = factory.make_name("space")
        new_description = factory.make_name("description")
        space = factory.make_Space()
        form = SpaceForm(
            instance=space,
            data={"name": new_name, "description": new_description},
        )
        assert form.is_valid(), form.errors
        form.save()
        assert reload_object(space).name == new_name
        assert reload_object(space).description == new_description
