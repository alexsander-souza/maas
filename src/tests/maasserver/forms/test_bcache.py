# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from collections import Counter
from uuid import uuid4

import pytest

from maasserver.enum import (
    CACHE_MODE_TYPE,
    FILESYSTEM_GROUP_TYPE,
    FILESYSTEM_TYPE,
)
from maasserver.forms import CreateBcacheForm, UpdateBcacheForm
from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestCreateBcacheForm:
    def test_required_fields(self):
        node = factory.make_Node()
        form = CreateBcacheForm(node=node, data={})

        assert not form.is_valid(), form.errors
        assert ["This field is required."] == form.errors["cache_mode"]

    def test_choices_are_being_populated_correctly(self):
        node = factory.make_Node(with_boot_disk=False)
        # Make 10 block devices.
        bds = [
            factory.make_PhysicalBlockDevice(node=node, size=10 * 1000**4)
            for _ in range(10)
        ]
        # Make 3 cache sets.
        cache_sets = [factory.make_CacheSet(node=node) for _ in range(3)]
        cache_set_choices = [cache_set.id for cache_set in cache_sets] + [
            cache_set.name for cache_set in cache_sets
        ]
        # Partition the last 5 devices with a single partition.
        partitions = [
            factory.make_PartitionTable(block_device=bd).add_partition()
            for bd in bds[5:]
        ]
        partition_choices = [partition.id for partition in partitions] + [
            partition.name for partition in partitions
        ]
        # Get the IDs of the non-partitioned devices.
        block_devices = [
            bd.id for bd in bds if bd.get_partitiontable() is None
        ] + [bd.name for bd in bds if bd.get_partitiontable() is None]
        form = CreateBcacheForm(node=node, data={})
        assert Counter(cache_set_choices) == Counter(
            k for k, _ in form.fields["cache_set"].choices
        )
        assert Counter(block_devices) == Counter(
            k for k, _ in form.fields["backing_device"].choices
        )
        assert Counter(partition_choices) == Counter(
            k for k, _ in form.fields["backing_partition"].choices
        )

    def test_bcache_creation_on_save(self):
        node = factory.make_Node()
        backing_size = 10 * 1000**4
        cache_set = factory.make_CacheSet(node=node)
        backing_device = factory.make_PhysicalBlockDevice(
            node=node, size=backing_size
        )
        uuid = str(uuid4())
        form = CreateBcacheForm(
            node=node,
            data={
                "name": "bcache0",
                "uuid": uuid,
                "cache_set": cache_set.id,
                "backing_device": backing_device.id,
                "cache_mode": CACHE_MODE_TYPE.WRITEBACK,
            },
        )

        assert form.is_valid(), form.errors
        bcache = form.save()
        assert bcache.name == "bcache0"
        assert bcache.uuid == uuid
        assert bcache.cache_set == cache_set
        assert (
            bcache.filesystems.get(fstype=FILESYSTEM_TYPE.BCACHE_BACKING)
            == backing_device.get_effective_filesystem()
        )
        assert bcache.get_size() == backing_size
        assert bcache.group_type == FILESYSTEM_GROUP_TYPE.BCACHE

    def test_bcache_creation_with_names(self):
        node = factory.make_Node()
        backing_size = 10 * 1000**4
        cache_set = factory.make_CacheSet(node=node)
        backing_device = factory.make_PhysicalBlockDevice(
            node=node, size=backing_size
        )
        backing_partition_table = factory.make_PartitionTable(
            block_device=backing_device
        )
        backing_partition = backing_partition_table.add_partition()
        uuid = str(uuid4())
        form = CreateBcacheForm(
            node=node,
            data={
                "name": "bcache0",
                "uuid": uuid,
                "cache_set": cache_set.name,
                "backing_partition": backing_partition.name,
                "cache_mode": CACHE_MODE_TYPE.WRITEBACK,
            },
        )

        assert form.is_valid(), form.errors
        bcache = form.save()
        assert bcache.name == "bcache0"
        assert bcache.uuid == uuid
        assert bcache.cache_set == cache_set
        assert (
            bcache.filesystems.get(fstype=FILESYSTEM_TYPE.BCACHE_BACKING)
            == backing_partition.get_effective_filesystem()
        )
        assert bcache.group_type == FILESYSTEM_GROUP_TYPE.BCACHE

    def test_bcache_creation_on_boot_disk(self):
        node = factory.make_Node(with_boot_disk=False)
        boot_disk = factory.make_PhysicalBlockDevice(node=node, bootable=True)
        cache_set = factory.make_CacheSet(node=node)
        form = CreateBcacheForm(
            node=node,
            data={
                "name": "bcache0",
                "cache_set": cache_set.id,
                "backing_device": boot_disk.id,
                "cache_mode": CACHE_MODE_TYPE.WRITEBACK,
            },
        )

        assert form.is_valid(), form.errors
        bcache = form.save()
        assert bcache.name == "bcache0"
        assert bcache.cache_set == cache_set
        assert bcache.group_type == FILESYSTEM_GROUP_TYPE.BCACHE
        boot_partition = boot_disk.get_partitiontable().partitions.first()
        assert (
            bcache.filesystems.get(fstype=FILESYSTEM_TYPE.BCACHE_BACKING)
            == boot_partition.get_effective_filesystem()
        )

    def test_bcache_creation_with_invalid_names_fails(self):
        node = factory.make_Node()
        uuid = str(uuid4())
        form = CreateBcacheForm(
            node=node,
            data={
                "name": "bcache0",
                "uuid": uuid,
                "cache_set": "sdapart1",
                "backing_partition": "sda-partXD",
                "cache_mode": CACHE_MODE_TYPE.WRITEBACK,
            },
        )

        assert not form.is_valid(), form.errors
        assert form.errors == {
            "cache_set": [
                "Select a valid choice. sdapart1 is not one of the "
                "available choices."
            ],
            "backing_partition": [
                "Select a valid choice. sda-partXD is not one of the "
                "available choices."
            ],
            "__all__": ["Bcache requires a cache_set."],
        }

    def test_bcache_creation_without_storage_fails(self):
        node = factory.make_Node()
        form = CreateBcacheForm(
            node=node, data={"cache_mode": CACHE_MODE_TYPE.WRITEAROUND}
        )

        assert not form.is_valid(), form.errors
        assert ["This field is required."] == form.errors["cache_set"]

    def test_bcache_creation_without_cache_set_fails(self):
        node = factory.make_Node()
        backing_size = 10 * 1000**4
        backing_device = factory.make_PhysicalBlockDevice(
            node=node, size=backing_size
        )
        form = CreateBcacheForm(
            node=node,
            data={
                "cache_mode": CACHE_MODE_TYPE.WRITEAROUND,
                "backing_device": backing_device.id,
            },
        )

        assert not form.is_valid(), form.errors
        assert ["This field is required."] == form.errors["cache_set"]

    def test_bcache_creation_without_backing_fails(self):
        node = factory.make_Node()
        cache_set = factory.make_CacheSet(node=node)
        form = CreateBcacheForm(
            node=node,
            data={
                "cache_mode": CACHE_MODE_TYPE.WRITEAROUND,
                "cache_set": cache_set.id,
            },
        )

        assert not form.is_valid(), form.errors
        assert form.errors["__all__"] == [
            "Either backing_device or backing_partition must be specified."
        ]


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestUpdateBcacheForm:
    def test_choices_are_being_populated_correctly(self):
        node = factory.make_Node(with_boot_disk=False)
        device_size = 1 * 1000**4
        # Make 10 block devices.
        bds = [
            factory.make_PhysicalBlockDevice(node=node, size=device_size)
            for _ in range(10)
        ]
        # Make 3 cache sets.
        cache_sets = [factory.make_CacheSet(node=node) for _ in range(3)]
        cache_set_choices = [cache_set.id for cache_set in cache_sets] + [
            cache_set.name for cache_set in cache_sets
        ]
        # Partition the last 5 devices with a single partition.
        partitions = [
            factory.make_PartitionTable(block_device=bd).add_partition()
            for bd in bds[5:]
        ]
        partition_choices = [p.id for p in partitions] + [
            p.name for p in partitions
        ]
        # Get the chocies of the non-partitioned devices.
        block_device_choices = [
            bd.id for bd in bds if bd.get_partitiontable() is None
        ] + [bd.name for bd in bds if bd.get_partitiontable() is None]
        # Use one of the cache sets and one of the backing devices.
        filesystems = [
            factory.make_Filesystem(
                partition=partitions[0], fstype=FILESYSTEM_TYPE.BCACHE_BACKING
            )
        ]
        bcache = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.BCACHE,
            cache_set=cache_sets[0],
            filesystems=filesystems,
        )
        form = UpdateBcacheForm(bcache=bcache, data={})
        # Should allow all devices and partitions, including the ones currently
        # allocated for bcache.
        assert Counter(cache_set_choices) == Counter(
            k for k, _ in form.fields["cache_set"].choices
        )
        assert Counter(block_device_choices) == Counter(
            k for k, _ in form.fields["backing_device"].choices
        )
        assert Counter(partition_choices) == Counter(
            k for k, _ in form.fields["backing_partition"].choices
        )

    def test_lookup_by_name(self):
        node = factory.make_Node(with_boot_disk=True)
        disk = factory.make_PhysicalBlockDevice(node=node)
        cache_set = factory.make_CacheSet(node=node)
        filesystems = [
            factory.make_Filesystem(
                partition=factory.make_PartitionTable(
                    block_device=factory.make_PhysicalBlockDevice(node=node)
                ).add_partition(),
                fstype=FILESYSTEM_TYPE.BCACHE_BACKING,
            )
        ]
        bcache = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.BCACHE,
            cache_set=cache_set,
            filesystems=filesystems,
        )

        # create a disk with same name on another machine
        factory.make_PhysicalBlockDevice(
            node=factory.make_Node(with_boot_disk=False),
            name=disk.name,
        )

        form = UpdateBcacheForm(
            bcache=bcache, data={"backing_device": disk.name}
        )
        assert form.is_valid(), form.errors
        bcache = form.save()
        assert (
            bcache.filesystems.get(fstype=FILESYSTEM_TYPE.BCACHE_BACKING)
            == disk.get_effective_filesystem()
        )

    def test_bcache_update_with_invalid_mode(self):
        """Tests the mode field validation."""
        node = factory.make_Node()
        cache_set = factory.make_CacheSet(node=node)
        filesystems = [
            factory.make_Filesystem(
                partition=factory.make_PartitionTable(
                    block_device=factory.make_PhysicalBlockDevice(node=node)
                ).add_partition(),
                fstype=FILESYSTEM_TYPE.BCACHE_BACKING,
            )
        ]
        bcache = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.BCACHE,
            cache_set=cache_set,
            filesystems=filesystems,
        )
        form = UpdateBcacheForm(
            bcache=bcache, data={"cache_mode": "Writeonly"}
        )
        assert not form.is_valid(), form.errors
        assert "Select a valid choice." in form.errors["cache_mode"][0]
        assert (
            "is not one of the available choices."
            in form.errors["cache_mode"][0]
        )

    def test_bcache_with_invalid_block_device_fails(self):
        """Tests allowable device list validation."""
        node = factory.make_Node()
        cache_set = factory.make_CacheSet(node=node)
        filesystems = [
            factory.make_Filesystem(
                partition=factory.make_PartitionTable(
                    block_device=factory.make_PhysicalBlockDevice(node=node)
                ).add_partition(),
                fstype=FILESYSTEM_TYPE.BCACHE_BACKING,
            )
        ]
        backing_device = factory.make_PhysicalBlockDevice()
        bcache = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.BCACHE,
            cache_set=cache_set,
            filesystems=filesystems,
        )
        form = UpdateBcacheForm(
            bcache=bcache, data={"backing_device": backing_device.id}
        )
        assert not form.is_valid(), form.errors
        assert "Select a valid choice." in form.errors["backing_device"][0]
        assert (
            "is not one of the available choices."
            in form.errors["backing_device"][0]
        )

    def test_bcache_update_with_boot_disk(self):
        node = factory.make_Node(with_boot_disk=False)
        boot_disk = factory.make_PhysicalBlockDevice(node=node, bootable=True)
        cache_set = factory.make_CacheSet(node=node)
        filesystems = [
            factory.make_Filesystem(
                partition=factory.make_PartitionTable(
                    block_device=factory.make_PhysicalBlockDevice(node=node)
                ).add_partition(),
                fstype=FILESYSTEM_TYPE.BCACHE_BACKING,
            )
        ]
        bcache = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.BCACHE,
            cache_set=cache_set,
            filesystems=filesystems,
        )
        form = UpdateBcacheForm(
            bcache=bcache, data={"backing_device": boot_disk.id}
        )
        assert form.is_valid(), form.errors
        bcache = form.save()
        boot_partition = boot_disk.get_partitiontable().partitions.first()
        assert (
            bcache.filesystems.get(fstype=FILESYSTEM_TYPE.BCACHE_BACKING)
            == boot_partition.get_effective_filesystem()
        )
