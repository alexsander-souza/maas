# Copyright 2012-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for :class:`NodeUserData` and manager."""

import pytest

from maasserver.models import NodeUserData
from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNodeUserDataManager:
    """Test NodeUserDataManager."""

    def test_set_user_data_creates_new_nodeuserdata_if_needed(self):
        node = factory.make_Node()
        data = b"foo"
        NodeUserData.objects.set_user_data_for_ephemeral_env(node, data)
        assert data == NodeUserData.objects.get(node=node).data

    def test_set_user_data_overwrites_existing_userdata(self):
        node = factory.make_Node()
        data = b"bar"
        NodeUserData.objects.set_user_data_for_ephemeral_env(node, b"old data")
        NodeUserData.objects.set_user_data_for_ephemeral_env(node, data)
        assert data == NodeUserData.objects.get(node=node).data

    def test_set_user_data_leaves_data_for_other_nodes_alone(self):
        node = factory.make_Node()
        NodeUserData.objects.set_user_data_for_ephemeral_env(node, b"intact")
        NodeUserData.objects.set_user_data_for_ephemeral_env(
            factory.make_Node(), b"unrelated"
        )
        assert b"intact" == NodeUserData.objects.get(node=node).data

    def test_set_user_data_to_None_removes_user_data(self):
        node = factory.make_Node()
        NodeUserData.objects.set_user_data_for_ephemeral_env(node, b"original")
        NodeUserData.objects.set_user_data_for_ephemeral_env(node, None)
        assert not NodeUserData.objects.filter(node=node).exists()

    def test_set_user_data_to_None_when_none_exists_does_nothing(self):
        node = factory.make_Node()
        NodeUserData.objects.set_user_data_for_ephemeral_env(node, None)
        assert not NodeUserData.objects.filter(node=node).exists()

    def test_get_user_data_retrieves_data(self):
        node = factory.make_Node()
        data = b"splat"
        NodeUserData.objects.set_user_data_for_ephemeral_env(node, data)
        assert data == NodeUserData.objects.get_user_data_for_ephemeral_env(
            node
        )

    def test_get_user_data_raises_DoesNotExist_if_not_found(self):
        node = factory.make_Node()
        with pytest.raises(NodeUserData.DoesNotExist):
            NodeUserData.objects.get_user_data_for_ephemeral_env(node)

    def test_get_user_data_ignores_other_nodes(self):
        node = factory.make_Node()
        data = b"bzzz"
        NodeUserData.objects.set_user_data_for_ephemeral_env(node, data)
        NodeUserData.objects.set_user_data_for_ephemeral_env(
            factory.make_Node(), b"unrelated"
        )
        assert data == NodeUserData.objects.get_user_data_for_ephemeral_env(
            node
        )

    def test_has_user_data_returns_False_if_node_has_no_user_data(self):
        assert not NodeUserData.objects.has_any_user_data(factory.make_Node())

    def test_has_user_data_returns_True_if_node_has_ephemeral_user_data(self):
        node = factory.make_Node()
        NodeUserData.objects.set_user_data_for_ephemeral_env(
            node, b"This node has ephemeral user data."
        )
        assert NodeUserData.objects.has_any_user_data(node)

    def test_has_user_data_returns_True_if_node_has_user_data(self):
        node = factory.make_Node()
        NodeUserData.objects.set_user_data_for_ephemeral_env(
            node, b"This node has user data."
        )
        assert NodeUserData.objects.has_any_user_data(node)
