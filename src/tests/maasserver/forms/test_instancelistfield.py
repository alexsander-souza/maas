# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `InstanceListField`."""

from collections import Counter

from django.core.exceptions import ValidationError
import pytest

from maasserver.forms import InstanceListField
from maasserver.models import Node
from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestInstanceListField:
    """Tests for `InstanceListField`."""

    def test_field_validates_valid_data(self):
        nodes = [factory.make_Node() for _ in range(3)]
        # Create other nodes.
        [factory.make_Node() for _ in range(3)]
        field = InstanceListField(model_class=Node, field_name="system_id")
        input_data = [node.system_id for node in nodes]
        assert Counter(input_data) == Counter(
            [node.system_id for node in field.clean(input_data)]
        )

    def test_field_ignores_duplicates(self):
        nodes = [factory.make_Node() for _ in range(2)]
        # Create other nodes.
        [factory.make_Node() for _ in range(3)]
        field = InstanceListField(model_class=Node, field_name="system_id")
        input_data = [node.system_id for node in nodes] * 2
        assert Counter(set(input_data)) == Counter(
            [node.system_id for node in field.clean(input_data)]
        )

    def test_field_rejects_invalid_data(self):
        nodes = [factory.make_Node() for _ in range(3)]
        field = InstanceListField(model_class=Node, field_name="system_id")
        with pytest.raises(ValidationError) as exc_info:
            field.clean([node.system_id for node in nodes] + ["unknown"])
        assert ["Unknown node(s): unknown."] == exc_info.value.messages
