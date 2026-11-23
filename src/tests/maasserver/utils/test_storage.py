# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for storage utilities."""

import pytest

from maasserver.enum import (
    FILESYSTEM_GROUP_RAID_TYPE_CHOICES,
    FILESYSTEM_GROUP_TYPE,
    FILESYSTEM_TYPE,
    NODE_STATUS,
)
from maasserver.testing.factory import factory
from maasserver.utils.storage import get_effective_filesystem, used_for


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
@pytest.mark.parametrize(
    "make_model,filesystem_property",
    [
        pytest.param(
            factory.make_BlockDevice,
            "block_device",
            id="BlockDevice",
        ),
        pytest.param(
            factory.make_Partition,
            "partition",
            id="Partition",
        ),
    ],
)
class TestGetEffectiveFilesystem:
    def test_returns_None_when_no_filesystem(
        self, make_model, filesystem_property
    ):
        model = make_model()
        assert get_effective_filesystem(model) is None

    def test_returns_filesystem_if_node_not_in_acquired_state(
        self, make_model, filesystem_property
    ):
        node = factory.make_Node(status=NODE_STATUS.READY)
        model = make_model(node=node)
        filesystem = factory.make_Filesystem(**{filesystem_property: model})
        assert filesystem == get_effective_filesystem(model)

    def test_returns_acquired_filesystem(
        self, make_model, filesystem_property
    ):
        node = factory.make_Node(status=NODE_STATUS.ALLOCATED)
        model = make_model(node=node)
        factory.make_Filesystem(**{filesystem_property: model})
        filesystem = factory.make_Filesystem(
            **{filesystem_property: model, "acquired": True}
        )
        assert filesystem == get_effective_filesystem(model)

    def test_returns_non_mountable_filesystem(
        self, make_model, filesystem_property
    ):
        node = factory.make_Node(status=NODE_STATUS.ALLOCATED)
        model = make_model(node=node)
        filesystem = factory.make_Filesystem(
            **{
                filesystem_property: model,
                "fstype": FILESYSTEM_TYPE.BCACHE_BACKING,
            }
        )
        assert filesystem == get_effective_filesystem(model)

    def test_returns_none_when_allocated_state(
        self, make_model, filesystem_property
    ):
        node = factory.make_Node(status=NODE_STATUS.ALLOCATED)
        model = make_model(node=node)
        factory.make_Filesystem(
            **{filesystem_property: model, "fstype": FILESYSTEM_TYPE.EXT4}
        )
        assert get_effective_filesystem(model) is None


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestUsedFor:
    def test_unused(self):
        block_device = factory.make_BlockDevice()
        assert used_for(block_device) == "Unused"

    def test_fs_formatted(self):
        block_device = factory.make_BlockDevice()
        fs = factory.make_Filesystem(block_device=block_device)
        assert used_for(block_device) == (
            "Unmounted %s formatted filesystem" % fs.fstype
        )

    def test_fs_formatted_and_mounted(self):
        block_device = factory.make_BlockDevice()
        fs = factory.make_Filesystem(
            block_device=block_device, mount_point="/mnt"
        )
        assert used_for(block_device) == (
            "%s formatted filesystem mounted at %s"
            % (fs.fstype, fs.mount_point)
        )

    def test_partitioned(self):
        block_device = factory.make_BlockDevice()
        partition_table = factory.make_PartitionTable(
            block_device=block_device
        )
        partitions = partition_table.partitions.count()
        if partitions > 1:
            expected_message = "%s partitioned with %d partitions"
        else:
            expected_message = "%s partitioned with %d partition"
        assert used_for(block_device) == expected_message % (
            partition_table.table_type,
            partitions,
        )

    def test_lvm(self):
        filesystem_group = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.LVM_VG
        )
        assert used_for(filesystem_group.filesystems.first().block_device) == (
            "LVM volume for %s" % filesystem_group.name
        )

    def test_raid_active(self):
        filesystem_group = factory.make_FilesystemGroup(
            group_type=factory.pick_choice(FILESYSTEM_GROUP_RAID_TYPE_CHOICES)
        )
        assert used_for(filesystem_group.filesystems.first().block_device) == (
            "Active %s device for %s"
            % (filesystem_group.group_type, filesystem_group.name)
        )

    def test_raid_spare(self):
        filesystem_group = factory.make_FilesystemGroup(
            group_type=factory.pick_choice(FILESYSTEM_GROUP_RAID_TYPE_CHOICES)
        )
        slave_block_device = factory.make_PhysicalBlockDevice()
        factory.make_Filesystem(
            block_device=slave_block_device,
            fstype=FILESYSTEM_TYPE.RAID_SPARE,
            filesystem_group=filesystem_group,
        )
        assert used_for(slave_block_device) == (
            "Spare %s device for %s"
            % (filesystem_group.group_type, filesystem_group.name)
        )

    def test_bcache(self):
        cacheset = factory.make_CacheSet()
        blockdevice = cacheset.get_device()
        assert used_for(blockdevice) == ("Cache device for %s" % cacheset.name)

    def test_bcache_backing(self):
        filesystem_group = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.BCACHE
        )
        assert used_for(filesystem_group.filesystems.first().block_device) == (
            "Backing device for %s" % filesystem_group.name
        )

    def test_vmfs(self):
        vmfs = factory.make_VMFS()
        part = vmfs.filesystems.first().partition
        assert used_for(part) == ("VMFS extent for %s" % vmfs.name)
