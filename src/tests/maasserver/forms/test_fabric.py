# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for Fabric forms."""

import pytest

from maasserver.forms.fabric import FabricForm
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestFabricForm:
    def test_creates_fabric(self):
        fabric_name = factory.make_name("fabric")
        fabric_description = factory.make_name("description")
        fabric_class_type = factory.make_name("class_type")
        form = FabricForm(
            {
                "name": fabric_name,
                "description": fabric_description,
                "class_type": fabric_class_type,
            }
        )
        assert form.is_valid(), form.errors
        fabric = form.save()
        assert fabric_name == fabric.name
        assert fabric_description == fabric.description
        assert fabric_class_type == fabric.class_type

    def test_doest_require_name_on_update(self):
        fabric = factory.make_Fabric()
        form = FabricForm(instance=fabric, data={})
        assert form.is_valid(), form.errors

    def test_updates_fabric(self):
        new_name = factory.make_name("fabric")
        new_fabric_description = factory.make_name("description")
        new_class_type = factory.make_name("class_type")
        fabric = factory.make_Fabric()
        form = FabricForm(
            instance=fabric,
            data={
                "name": new_name,
                "description": new_fabric_description,
                "class_type": new_class_type,
            },
        )
        assert form.is_valid(), form.errors
        form.save()
        assert new_name == reload_object(fabric).name
        assert new_fabric_description == reload_object(fabric).description
        assert new_class_type == reload_object(fabric).class_type
