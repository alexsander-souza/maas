# Copyright 2013-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from django.core.exceptions import ValidationError
import pytest

from maasserver.models.numa import NUMANodeHugepages
from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "maas_region_test")
class TestCreateDefaultNUMANode:
    def test_create_for_machine(self):
        node = factory.make_Node(memory=1024, cpu_count=4)
        # the default NUMA node is created automatically on node creation
        numa_node = node.default_numanode
        assert numa_node.node is node
        assert numa_node.index == 0
        assert numa_node.memory == 1024
        assert numa_node.cores == [0, 1, 2, 3]


@pytest.mark.usefixtures("maasdb", "maas_region_test")
class TestNUMANodeHugepages:
    def test_unique(self):
        numa_node = factory.make_NUMANode()
        NUMANodeHugepages.objects.create(
            numanode=numa_node, page_size=2048, total=20480
        )
        with pytest.raises(ValidationError):
            NUMANodeHugepages.objects.create(
                numanode=numa_node, page_size=2048, total=20480
            )
