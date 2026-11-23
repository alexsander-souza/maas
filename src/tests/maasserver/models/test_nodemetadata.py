# Copyright 2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test maasserver NodeMetadata model."""

from django.core.exceptions import ValidationError
import pytest

from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNodeMetadata:
    def test_str(self):
        # A NodeMetadata object string representation references the parent
        # node hostname.
        node = factory.make_Machine(hostname="foobar")
        entry = factory.make_NodeMetadata(node=node, key="key")
        assert "NodeMetadata (foobar/key)" == str(entry)

    def test_unique_on_node_and_key(self):
        # We can only ever have one NodeMetadata object for a particular node
        # and key.
        entry = factory.make_NodeMetadata()
        with pytest.raises(ValidationError):
            factory.make_NodeMetadata(
                node=entry.node,
                key=entry.key,
            )

    def test_multiple_keys_on_node(self):
        # We can only ever have one NodeMetadata object for a particular node
        # and key.
        entry1 = factory.make_NodeMetadata(key="key1", value="value")
        entry2 = factory.make_NodeMetadata(
            node=entry1.node, key="key2", value="value"
        )
        assert entry1 != entry2
