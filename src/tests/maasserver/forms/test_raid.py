# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for all forms that are used with `RAID`."""

from collections import Counter
import random
from uuid import uuid4

import pytest

from maasserver.enum import FILESYSTEM_GROUP_TYPE, FILESYSTEM_TYPE
from maasserver.forms import CreateRaidForm, UpdateRaidForm
from maasserver.models.filesystemgroup import RAID, RAID_SUPERBLOCK_OVERHEAD
from maasserver.testing.factory import factory


def _make_interesting_RAID(
    node,
    level=FILESYSTEM_GROUP_TYPE.RAID_6,
    num_devices=10,
    num_partitions=10,
    num_spare_devices=2,
    num_spare_partitions=2,
):
    """Returns a RAID that is interesting for our tests."""
    size = 1000**4  # A Terabyte.
    block_devices = [
        factory.make_BlockDevice(node=node, size=size)
        for _ in range(num_devices)
    ]
    partitions = [
        factory.make_Partition(node=node, block_device_size=size)
        for _ in range(num_partitions)
    ]
    spare_devices = [
        factory.make_BlockDevice(node=node, size=size)
        for _ in range(num_spare_devices)
    ]
    spare_partitions = [
        factory.make_Partition(node=node, block_device_size=size)
        for _ in range(num_spare_partitions)
    ]

    return RAID.objects.create_raid(
        name="md%d" % random.randint(1, 1000),
        level=level,
        uuid=uuid4(),
        block_devices=block_devices,
        partitions=partitions,
        spare_devices=spare_devices,
        spare_partitions=spare_partitions,
    )


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestCreateRaidForm:
    def test_requires_fields(self):
        node = factory.make_Node()
        form = CreateRaidForm(node=node, data={})
        assert not form.is_valid(), form.errors
        assert form.errors["level"] == ["This field is required."]

    def test_choices_are_being_populated_correctly(self):
        node = factory.make_Node(with_boot_disk=False)
        bds = [
            factory.make_PhysicalBlockDevice(node=node, size=10 * 1000**4)
            for _ in range(10)
        ]
        for bd in bds[5:]:
            factory.make_PartitionTable(block_device=bd)
        block_devices_choices = [
            bd.id for bd in bds if bd.get_partitiontable() is None
        ] + [bd.name for bd in bds if bd.get_partitiontable() is None]
        partitions = [
            bd.get_partitiontable().add_partition() for bd in bds[5:]
        ]
        partitions_choices = [part.id for part in partitions] + [
            part.name for part in partitions
        ]
        form = CreateRaidForm(node=node, data={})
        assert Counter(block_devices_choices) == Counter(
            k for k, _ in form.fields["block_devices"].choices
        )
        assert Counter(partitions_choices) == Counter(
            k for k, _ in form.fields["partitions"].choices
        )
        assert Counter(block_devices_choices) == Counter(
            k for k, _ in form.fields["spare_devices"].choices
        )
        assert Counter(partitions_choices) == Counter(
            k for k, _ in form.fields["spare_partitions"].choices
        )

    def test_raid_creation_on_save(self):
        node = factory.make_Node()
        device_size = 10 * 1000**4
        bds = [
            factory.make_PhysicalBlockDevice(node=node, size=device_size)
            for _ in range(10)
        ]
        for bd in bds[5:]:
            factory.make_PartitionTable(block_device=bd)
        block_devices = [
            bd.id for bd in bds if bd.get_partitiontable() is None
        ]
        partition_objs = [
            bd.get_partitiontable().add_partition() for bd in bds[5:]
        ]
        partitions = [partition.id for partition in partition_objs]
        form = CreateRaidForm(
            node=node,
            data={
                "name": "md1",
                "level": FILESYSTEM_GROUP_TYPE.RAID_6,
                "block_devices": block_devices,
                "partitions": partitions,
            },
        )
        assert form.is_valid(), form.errors
        raid = form.save()
        assert "md1" == raid.name
        assert (8 * partition_objs[0].size) - RAID_SUPERBLOCK_OVERHEAD == (
            raid.get_size()
        )
        assert FILESYSTEM_GROUP_TYPE.RAID_6 == raid.group_type
        assert Counter(block_devices) == Counter(
            fs.block_device.id
            for fs in raid.filesystems.exclude(block_device=None)
        )
        assert Counter(partitions) == Counter(
            fs.partition.id for fs in raid.filesystems.exclude(partition=None)
        )

    def test_raid_creation_with_names(self):
        node = factory.make_Node()
        device_size = 10 * 1000**4
        bds = [
            factory.make_PhysicalBlockDevice(node=node, size=device_size)
            for _ in range(10)
        ]
        for bd in bds[5:]:
            factory.make_PartitionTable(block_device=bd)
        block_devices_ids = [
            bd.id for bd in bds if bd.get_partitiontable() is None
        ]
        block_device_names = [
            bd.name for bd in bds if bd.get_partitiontable() is None
        ]
        partitions = [
            bd.get_partitiontable().add_partition() for bd in bds[5:]
        ]
        partition_ids = [part.id for part in partitions]
        partition_names = [part.name for part in partitions]
        form = CreateRaidForm(
            node=node,
            data={
                "name": "md1",
                "level": FILESYSTEM_GROUP_TYPE.RAID_6,
                "block_devices": block_device_names,
                "partitions": partition_names,
            },
        )
        assert form.is_valid(), form.errors
        raid = form.save()
        assert "md1" == raid.name
        assert (
            8 * partitions[0].size
        ) - RAID_SUPERBLOCK_OVERHEAD == raid.get_size()
        assert FILESYSTEM_GROUP_TYPE.RAID_6 == raid.group_type
        assert Counter(block_devices_ids) == Counter(
            [
                fs.block_device.id
                for fs in raid.filesystems.exclude(block_device=None)
            ]
        )
        assert Counter(partition_ids) == Counter(
            [
                fs.partition.id
                for fs in raid.filesystems.exclude(partition=None)
            ]
        )

    def test_raid_creation_on_boot_disk(self):
        node = factory.make_Node(with_boot_disk=False)
        bds = [
            factory.make_PhysicalBlockDevice(node=node, bootable=True)
            for _ in range(10)
        ]
        partitions = []
        block_devices = [bd.id for bd in bds[:5]]
        for bd in bds[5:]:
            partition_table = factory.make_PartitionTable(block_device=bd)
            partition = partition_table.add_partition()
            partitions.append(partition.id)
        form = CreateRaidForm(
            node=node,
            data={
                "name": "md1",
                "level": FILESYSTEM_GROUP_TYPE.RAID_6,
                "block_devices": block_devices,
                "partitions": partitions,
            },
        )
        assert form.is_valid(), form.errors
        raid = form.save()
        assert "md1" == raid.name
        assert FILESYSTEM_GROUP_TYPE.RAID_6 == raid.group_type
        assert not raid.filesystems.exclude(block_device=None).exists()
        assert raid.filesystems.exclude(partition=None).count() == 10

    def test_raid_creation_without_storage_fails(self):
        node = factory.make_Node()
        for level in [
            FILESYSTEM_GROUP_TYPE.RAID_0,
            FILESYSTEM_GROUP_TYPE.RAID_1,
            FILESYSTEM_GROUP_TYPE.RAID_5,
            FILESYSTEM_GROUP_TYPE.RAID_6,
            FILESYSTEM_GROUP_TYPE.RAID_10,
        ]:
            form = CreateRaidForm(
                node=node,
                data={
                    "name": "md1",
                    "level": level,
                    "block_devices": [],
                    "partitions": [],
                },
            )
            assert not form.is_valid()
        assert form.errors["__all__"] == [
            "At least one block device or partition must "
            "be added to the array."
        ]


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestUpdateRaidForm:
    # Add devices and partitions
    def test_add_valid_blockdevice(self):
        raid = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.RAID_6
        )
        # Add 5 new blockdevices to the node.
        bd_ids = [
            factory.make_BlockDevice(node=raid.get_node()).id for _ in range(5)
        ]
        form = UpdateRaidForm(raid, data={"add_block_devices": bd_ids})
        assert form.is_valid(), form.errors

    def test_add_valid_blockdevice_by_name(self):
        raid = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.RAID_6
        )
        # Add 5 new blockdevices to the node.
        bd_names = [
            factory.make_BlockDevice(node=raid.get_node()).name
            for _ in range(5)
        ]
        form = UpdateRaidForm(raid, data={"add_block_devices": bd_names})
        assert form.is_valid(), form.errors

    def test_add_valid_boot_disk(self):
        node = factory.make_Node(with_boot_disk=False)
        boot_disk = factory.make_PhysicalBlockDevice(node=node, bootable=True)
        raid = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.RAID_6, node=node
        )
        raid = RAID.objects.get(id=raid.id)
        form = UpdateRaidForm(raid, data={"add_block_devices": [boot_disk.id]})
        assert form.is_valid(), form.errors
        raid = form.save()
        boot_partition = boot_disk.get_partitiontable().partitions.first()
        assert (
            boot_partition.get_effective_filesystem().filesystem_group.id
            == raid.id
        )

    def test_add_valid_partition(self):
        raid = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.RAID_6
        )
        # Add 5 new partitions to the node.
        part_ids = [
            factory.make_Partition(node=raid.get_node()).id for _ in range(5)
        ]
        form = UpdateRaidForm(raid, data={"add_partitions": part_ids})
        assert form.is_valid(), form.errors

    def test_add_valid_spare_device(self):
        raid = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.RAID_6
        )
        # Add 5 new blockdevices to the node.
        bd_ids = [
            factory.make_BlockDevice(node=raid.get_node()).id for _ in range(5)
        ]
        form = UpdateRaidForm(raid, data={"add_spare_devices": bd_ids})
        assert form.is_valid(), form.errors

    def test_add_valid_spare_boot_disk(self):
        node = factory.make_Node(with_boot_disk=False)
        boot_disk = factory.make_PhysicalBlockDevice(node=node, bootable=True)
        raid = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.RAID_6, node=node
        )
        raid = RAID.objects.get(id=raid.id)
        form = UpdateRaidForm(raid, data={"add_spare_devices": [boot_disk.id]})
        assert form.is_valid(), form.errors
        raid = form.save()
        boot_partition = boot_disk.get_partitiontable().partitions.first()
        assert (
            boot_partition.get_effective_filesystem().filesystem_group.id
            == raid.id
        )

    def test_add_valid_spare_partition(self):
        raid = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.RAID_6
        )
        # Add 5 new partitions to the node.
        part_ids = [
            factory.make_Partition(node=raid.get_node()).id for _ in range(5)
        ]
        form = UpdateRaidForm(raid, data={"add_spare_partitions": part_ids})
        assert form.is_valid(), form.errors

    def test_add_invalid_blockdevice_fails(self):
        raid = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.RAID_6
        )
        # Add 5 new blockdevices to other nodes.
        bd_ids = [factory.make_BlockDevice().id for _ in range(5)]
        form = UpdateRaidForm(raid, data={"add_block_devices": bd_ids})
        assert not form.is_valid(), form.errors
        assert "add_block_devices" in form.errors
        assert (
            "is not one of the available choices."
            in form.errors["add_block_devices"][0]
        )

    def test_add_invalid_spare_blockdevice_fails(self):
        raid = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.RAID_6
        )
        # Add 5 new blockdevices to other nodes.
        bd_ids = [factory.make_BlockDevice().id for _ in range(5)]
        form = UpdateRaidForm(raid, data={"add_spare_devices": bd_ids})
        assert not form.is_valid(), form.errors
        assert "add_spare_devices" in form.errors
        assert (
            "is not one of the available choices."
            in form.errors["add_spare_devices"][0]
        )

    def test_add_invalid_partition_fails(self):
        raid = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.RAID_6
        )
        # Add 5 new partitions to other nodes.
        part_ids = [factory.make_Partition().id for _ in range(5)]
        form = UpdateRaidForm(raid, data={"add_partitions": part_ids})
        assert not form.is_valid(), form.errors
        assert "add_partitions" in form.errors
        assert (
            "is not one of the available choices."
            in form.errors["add_partitions"][0]
        )

    def test_add_invalid_spare_partition_fails(self):
        raid = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.RAID_6
        )
        # Add 5 new partitions to other nodes.
        part_ids = [factory.make_Partition().id for _ in range(5)]
        form = UpdateRaidForm(raid, data={"add_spare_partitions": part_ids})
        assert not form.is_valid(), form.errors
        assert "add_spare_partitions" in form.errors
        assert (
            "is not one of the available choices."
            in form.errors["add_spare_partitions"][0]
        )

    # Removal tests

    def test_remove_valid_blockdevice(self):
        raid = _make_interesting_RAID(node=factory.make_Node())
        ids = [
            fs.block_device.id
            for fs in raid.filesystems.filter(
                fstype=FILESYSTEM_TYPE.RAID
            ).exclude(block_device=None)[:2]
        ]  # Select 2 items for removal
        form = UpdateRaidForm(raid, data={"remove_block_devices": ids})
        assert form.is_valid(), form.errors

    def test_remove_valid_partition(self):
        raid = _make_interesting_RAID(node=factory.make_Node())
        ids = [
            fs.partition.id
            for fs in raid.filesystems.filter(
                fstype=FILESYSTEM_TYPE.RAID
            ).exclude(partition=None)[:2]
        ]  # Select 2 items for removal
        form = UpdateRaidForm(raid, data={"remove_partitions": ids})
        assert form.is_valid(), form.errors

    def test_remove_valid_spare_device(self):
        raid = _make_interesting_RAID(node=factory.make_Node())
        ids = [
            fs.block_device.id
            for fs in raid.filesystems.filter(
                fstype=FILESYSTEM_TYPE.RAID_SPARE
            ).exclude(block_device=None)[:2]
        ]  # Select 2 items for removal
        form = UpdateRaidForm(raid, data={"remove_block_devices": ids})
        assert form.is_valid(), form.errors

    def test_remove_valid_spare_partition(self):
        raid = _make_interesting_RAID(node=factory.make_Node())
        ids = [
            fs.partition.id
            for fs in raid.filesystems.filter(
                fstype=FILESYSTEM_TYPE.RAID_SPARE
            ).exclude(partition=None)[:2]
        ]  # Select 2 items for removal
        form = UpdateRaidForm(raid, data={"remove_partitions": ids})
        assert form.is_valid(), form.errors

    def test_remove_invalid_blockdevice_fails(self):
        raid = _make_interesting_RAID(node=factory.make_Node())
        ids = [factory.make_BlockDevice().id for _ in range(2)]
        form = UpdateRaidForm(raid, data={"remove_block_devices": ids})
        assert not form.is_valid(), form.errors
        assert "remove_block_devices" in form.errors
        assert (
            "is not one of the available choices."
            in form.errors["remove_block_devices"][0]
        )

    def test_remove_invalid_spare_blockdevice_fails(self):
        raid = _make_interesting_RAID(node=factory.make_Node())
        ids = [factory.make_BlockDevice().id for _ in range(2)]
        form = UpdateRaidForm(raid, data={"remove_spare_devices": ids})
        assert not form.is_valid(), form.errors
        assert "remove_spare_devices" in form.errors
        assert (
            "is not one of the available choices."
            in form.errors["remove_spare_devices"][0]
        )

    def test_remove_invalid_partition_fails(self):
        raid = _make_interesting_RAID(node=factory.make_Node())
        ids = [factory.make_Partition().id for _ in range(2)]
        form = UpdateRaidForm(raid, data={"remove_partitions": ids})
        assert not form.is_valid(), form.errors
        assert "remove_partitions" in form.errors
        assert (
            "is not one of the available choices."
            in form.errors["remove_partitions"][0]
        )

    def test_remove_invalid_spare_partition_fails(self):
        raid = _make_interesting_RAID(node=factory.make_Node())
        ids = [factory.make_Partition().id for _ in range(2)]
        form = UpdateRaidForm(raid, data={"remove_spare_partitions": ids})
        assert not form.is_valid(), form.errors
        assert "remove_spare_partitions" in form.errors
        assert (
            "is not one of the available choices."
            in form.errors["remove_spare_partitions"][0]
        )
