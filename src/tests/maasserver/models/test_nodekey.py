# Copyright 2012-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for :class:`NodeKey` model and manager."""

import pytest

from maasserver.models import NodeKey
from maasserver.testing.factory import factory
from maastesting.querycounter import CountQueries


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNodeKeyManager:
    """Test NodeKeyManager."""

    def test_get_token_for_node_registers_node_key(self):
        node = factory.make_Node()
        token = NodeKey.objects.get_token_for_node(node)
        nodekey = NodeKey.objects.get(node=node)
        assert nodekey is not None
        assert token == nodekey.token

    def test_get_node_for_key_finds_node(self):
        node = factory.make_Node()
        token = NodeKey.objects.get_token_for_node(node)
        assert node == NodeKey.objects.get_node_for_key(token.key)

    def test_get_node_for_key_raises_DoesNotExist_if_key_not_found(self):
        non_key = factory.make_string()
        with pytest.raises(NodeKey.DoesNotExist):
            NodeKey.objects.get_node_for_key(non_key)

    def test_get_token_for_node_creates_token(self):
        node = factory.make_Node()
        token = NodeKey.objects.get_token_for_node(node)
        assert node == NodeKey.objects.get_node_for_key(token.key)

    def test_get_token_for_node_returns_existing_token(self):
        node = factory.make_Node()
        original_token = NodeKey.objects.get_token_for_node(node)
        repeated_token = NodeKey.objects.get_token_for_node(node)
        assert original_token == repeated_token

    def test_get_token_for_node_inverts_get_node_for_key(self):
        node = factory.make_Node()
        assert node == NodeKey.objects.get_node_for_key(
            NodeKey.objects.get_token_for_node(node).key
        )

    def test_get_token_for_node_prefetches(self):
        # token.consumer.key is almost always used when retrieving the token.
        # Prefetch it so it can be called in one deferToDatabase.
        node = factory.make_Node()
        consumer_key = NodeKey.objects.get_token_for_node(node).consumer.key
        with CountQueries() as prefetch_count:
            token = NodeKey.objects.get_token_for_node(node)
        assert prefetch_count.count == 3
        # Verify consumer was prefetched
        with CountQueries() as access_count:
            assert consumer_key == token.consumer.key
        assert access_count.count == 0

    def test_clear_token_for_node_deletes_related_NodeKey(self):
        node = factory.make_Node()
        NodeKey.objects.get_token_for_node(node)
        NodeKey.objects.clear_token_for_node(node)
        assert NodeKey.objects.filter(node=node).count() == 0

    def test_get_node_for_key_inverts_get_token_for_node(self):
        key = NodeKey.objects.get_token_for_node(factory.make_Node()).key
        assert (
            key
            == NodeKey.objects.get_token_for_node(
                NodeKey.objects.get_node_for_key(key)
            ).key
        )
