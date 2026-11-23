# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from django.core.exceptions import ValidationError
import pytest

from maasserver.models.nodeconfig import NODE_CONFIG_TYPE, NodeConfig
from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestCreateCommissioningNodeConfig:
    def test_create_for_node(self):
        node = factory.make_Node()
        [node_config] = node.nodeconfig_set.all()
        assert node_config.node is node
        assert node_config.name == "discovered"
        assert node_config == node.current_config


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNodeConfig:
    def test_unique(self):
        node = factory.make_Node()
        with pytest.raises(ValidationError):
            NodeConfig.objects.create(
                node=node,
                name=NODE_CONFIG_TYPE.DISCOVERED,
            )
