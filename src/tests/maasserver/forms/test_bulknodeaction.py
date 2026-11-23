# Copyright 2014-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `BulkNodeActionForm`."""

import pytest

from maasserver.forms import BulkNodeSetZoneForm
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestBulkNodeActionForm:
    """Tests for `BulkNodeActionForm`."""

    def test_rejects_empty_system_ids(self):
        form = BulkNodeSetZoneForm(
            user=factory.make_admin(),
            data={"system_id": [], "zone": factory.make_Zone().name},
        )
        assert not form.is_valid(), form._errors
        assert form._errors["system_id"] == ["No node selected."]

    def test_rejects_invalid_system_ids(self):
        node = factory.make_Node()
        system_ids = [node.system_id, "wrong-system_id"]
        form = BulkNodeSetZoneForm(
            user=factory.make_admin(),
            data={"system_id": system_ids, "zone": factory.make_Zone().name},
        )
        assert not form.is_valid(), form._errors
        assert form._errors["system_id"] == [
            "Some of the given system ids are invalid system ids."
        ]

    def test_set_zone_does_not_work_if_not_superuser(self):
        node = factory.make_Node()
        form = BulkNodeSetZoneForm(
            user=factory.make_User(),
            data={
                "zone": factory.make_Zone().name,
                "system_id": [node.system_id],
            },
        )
        assert not form.is_valid()

    def test_zone_field_rejects_empty_zone(self):
        # If the field is present, the zone name has to be valid
        # and the empty string is not a valid zone name.
        form = BulkNodeSetZoneForm(
            user=factory.make_admin(), data={"zone": ""}
        )
        assert not form.is_valid(), form._errors
        assert form._errors["zone"] == ["This field is required."]

    def test_set_zone_sets_zone_on_node(self):
        node = factory.make_Node()
        zone = factory.make_Zone()
        form = BulkNodeSetZoneForm(
            user=factory.make_admin(),
            data={"zone": zone.name, "system_id": [node.system_id]},
        )
        assert form.is_valid(), form._errors

        done, not_actionable, not_permitted = form.save()

        assert [done, not_actionable, not_permitted] == [1, 0, 0]

        node = reload_object(node)
        assert node.zone == zone

    def test_set_zone_leaves_unselected_nodes_alone(self):
        unselected_node = factory.make_Node()
        original_zone = unselected_node.zone
        form = BulkNodeSetZoneForm(
            user=factory.make_admin(),
            data={
                "zone": factory.make_Zone().name,
                "system_id": [factory.make_Node().system_id],
            },
        )
        assert form.is_valid(), form._errors

        done, not_actionable, not_permitted = form.save()

        assert [done, not_actionable, not_permitted] == [1, 0, 0]

        unselected_node = reload_object(unselected_node)
        assert unselected_node.zone == original_zone
