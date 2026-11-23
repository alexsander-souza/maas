# Copyright 2015-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


from copy import copy
import re
from uuid import uuid4

from django.core.exceptions import ValidationError
import pytest

from maasserver.enum import (
    FILESYSTEM_FORMAT_TYPE_CHOICES_DICT,
    FILESYSTEM_GROUP_TYPE,
    FILESYSTEM_TYPE,
)
from maasserver.models.filesystem import Filesystem
from maasserver.models.filesystemgroup import RAID
from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestFilesystemManager:
    """Tests for the `FilesystemManager`."""

    def test_filter_by_node(self):
        node = factory.make_Node()
        boot_bd = node.current_config.blockdevice_set.first()
        root_partition = boot_bd.partitiontable_set.first().partitions.first()
        root_fs = root_partition.filesystem_set.first()
        block_device = factory.make_PhysicalBlockDevice(node=node)
        bd_for_partitions = factory.make_PhysicalBlockDevice(node=node)
        partition_table = factory.make_PartitionTable(
            block_device=bd_for_partitions
        )
        partition = factory.make_Partition(partition_table=partition_table)
        filesystem_on_bd = factory.make_Filesystem(block_device=block_device)
        filesystem_on_partition = factory.make_Filesystem(partition=partition)
        filesystem_without_backing = factory.make_Filesystem(
            node_config=node.current_config
        )
        assert sorted(
            [
                root_fs,
                filesystem_on_bd,
                filesystem_on_partition,
                filesystem_without_backing,
            ],
            key=str,
        ) == sorted(Filesystem.objects.filter_by_node(node), key=str)


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestFilesystem:
    """Tests for the `Filesystem` model."""

    def test_get_node_returns_partition_node(self):
        partition = factory.make_Partition()
        fs = factory.make_Filesystem(partition=partition)
        assert fs.partition.get_node() == fs.get_node()

    def test_get_node_returns_block_device_node(self):
        block_device = factory.make_PhysicalBlockDevice()
        fs = factory.make_Filesystem(block_device=block_device)
        assert fs.block_device.get_node() == fs.get_node()

    def test_get_node_returns_special_filesystem_node(self):
        node_config = factory.make_NodeConfig()
        fs = Filesystem(node_config=node_config)
        assert fs.get_node() == node_config.node

    def test_get_physical_block_devices_single(self):
        node = factory.make_Node()
        block_device = factory.make_PhysicalBlockDevice(node=node)
        filesystem = factory.make_Filesystem(
            fstype=FILESYSTEM_TYPE.LVM_PV, block_device=block_device
        )
        assert filesystem.get_physical_block_devices() == [block_device]

    def test_get_physical_block_devices_multiple(self):
        node = factory.make_Node()
        block_devices = [
            factory.make_PhysicalBlockDevice(node=node) for _ in range(3)
        ]
        filesystems = [
            factory.make_Filesystem(
                fstype=FILESYSTEM_TYPE.LVM_PV, block_device=block_device
            )
            for block_device in block_devices
        ]
        fsgroup = factory.make_FilesystemGroup(
            node=node,
            filesystems=filesystems,
            group_type=FILESYSTEM_GROUP_TYPE.LVM_VG,
        )
        virtual_block_device = factory.make_VirtualBlockDevice(
            filesystem_group=fsgroup
        )
        filesystem = factory.make_Filesystem(
            fstype=FILESYSTEM_TYPE.LVM_PV, block_device=virtual_block_device
        )
        assert filesystem.get_physical_block_devices() == block_devices

    def test_get_physical_block_device_raid_on_part(self):
        # Regression test for LP:1849580
        node = factory.make_Node(with_boot_disk=False)
        block_devices = []
        partitions = []
        for _ in range(2):
            block_device = factory.make_PhysicalBlockDevice(node=node)
            block_devices.append(block_device)
            pt = factory.make_PartitionTable(block_device=block_device)
            partitions.append(
                factory.make_Partition(
                    partition_table=pt, size=pt.get_available_size()
                )
            )
        fs_group = RAID.objects.create_raid(
            level=FILESYSTEM_GROUP_TYPE.RAID_1, partitions=partitions
        )
        fs = factory.make_Filesystem(block_device=fs_group.virtual_device)
        assert sorted(fs.get_physical_block_devices(), key=str) == sorted(
            block_devices, key=str
        )

    def test_get_size_returns_partition_size(self):
        partition = factory.make_Partition()
        fs = factory.make_Filesystem(partition=partition)
        assert fs.partition.size == fs.get_size()

    def test_get_size_returns_block_device_size(self):
        block_device = factory.make_PhysicalBlockDevice()
        fs = factory.make_Filesystem(block_device=block_device)
        assert fs.block_device.size == fs.get_size()

    def test_get_size_returns_0_when_partition_and_block_device_None(self):
        fs = Filesystem()
        assert 0 == fs.get_size()

    def test_get_block_size_returns_partition_block_size(self):
        partition = factory.make_Partition()
        fs = factory.make_Filesystem(partition=partition)
        assert fs.partition.get_block_size() == fs.get_block_size()

    def test_get_block_size_returns_block_device_block_size(self):
        block_device = factory.make_PhysicalBlockDevice()
        fs = factory.make_Filesystem(block_device=block_device)
        assert fs.block_device.block_size == fs.get_block_size()

    def test_get_block_size_returns_0_when_partition_and_device_None(self):
        fs = Filesystem()
        assert 0 == fs.get_block_size()

    def test_cannot_save_filesystem_if_too_much_storage(self):
        node = factory.make_Node()
        block_device = factory.make_BlockDevice(node=node)
        partition = factory.make_Partition(node=node)
        fs = Filesystem(block_device=block_device, partition=partition)
        with pytest.raises(ValidationError) as error:
            fs.save()
        assert error.value.messages == [
            "Only one of partition, block device can be specified."
        ]

    def test_save_doesnt_overwrite_uuid(self):
        uuid = uuid4()
        fs = factory.make_Filesystem(uuid=uuid)
        assert "%s" % uuid == fs.uuid

    def test_get_device_returns_block_device(self):
        block_device = factory.make_PhysicalBlockDevice()
        filesystem = factory.make_Filesystem(block_device=block_device)
        assert block_device == filesystem.get_device()

    def test_get_device_returns_partition(self):
        partition = factory.make_Partition()
        filesystem = factory.make_Filesystem(partition=partition)
        assert partition == filesystem.get_device()

    def test_get_device_returns_none_for_special_fs(self):
        filesystem = factory.make_Filesystem(
            node_config=factory.make_NodeConfig()
        )
        assert filesystem.get_device() is None

    def test_cannot_create_filesystem_directly_on_boot_disk(self):
        node = factory.make_Node(with_boot_disk=False)
        boot_disk = factory.make_PhysicalBlockDevice(node=node, bootable=True)
        with pytest.raises(
            ValidationError,
            match=re.escape(
                "{'__all__': ['Cannot place filesystem directly on the "
                "boot disk. Create a partition on the boot disk first "
                "and then format the partition.']}"
            ),
        ):
            factory.make_Filesystem(block_device=boot_disk)

    def test_can_create_filesystem_on_partition_on_boot_disk(self):
        node = factory.make_Node(with_boot_disk=False)
        boot_disk = factory.make_PhysicalBlockDevice(node=node)
        partition_table = factory.make_PartitionTable(block_device=boot_disk)
        partition = factory.make_Partition(partition_table=partition_table)
        # Test is that an error is not raised.
        factory.make_Filesystem(partition=partition)

    def test_unique_on_partition_and_acquired(self):
        # For any given partition, at most one unacquired and one acquired
        # filesystem record may exist.
        partition = factory.make_Partition()
        filesystem = factory.make_Filesystem(partition=partition)
        assert filesystem.block_device is None

        # XXX: Why no Filesystem.acquire() method?
        filesystem_acquired = copy(filesystem)
        filesystem_acquired.id = None  # Force INSERT.
        filesystem_acquired.acquired = True
        filesystem_acquired.save()

        # Create a duplicate.
        filesystem_dupe = copy(filesystem)
        filesystem_dupe.id = None  # Force INSERT.

        # Saving an unacquired duplicate fails.
        filesystem_dupe.acquired = False
        with pytest.raises(ValidationError) as error:
            filesystem_dupe.save()
        assert error.value.messages == [
            "Filesystem with this Partition and Acquired already exists."
        ]

        # Saving an acquired duplicate fails.
        filesystem_dupe.acquired = True
        with pytest.raises(ValidationError) as error:
            filesystem_dupe.save()
        assert error.value.messages == [
            "Filesystem with this Partition and Acquired already exists."
        ]

    def test_unique_on_block_device_and_acquired(self):
        # For any given block device, at most one unacquired and one acquired
        # filesystem record may exist.
        block_device = factory.make_BlockDevice()
        filesystem = factory.make_Filesystem(block_device=block_device)
        assert filesystem.partition is None

        # XXX: Why no Filesystem.acquire() method?
        filesystem_acquired = copy(filesystem)
        filesystem_acquired.id = None  # Force INSERT.
        filesystem_acquired.acquired = True
        filesystem_acquired.save()

        # Create a duplicate.
        filesystem_dupe = copy(filesystem)
        filesystem_dupe.id = None  # Force INSERT.

        # Saving an unacquired duplicate fails.
        filesystem_dupe.acquired = False
        with pytest.raises(ValidationError) as error:
            filesystem_dupe.save()
        assert error.value.messages == [
            "Filesystem with this Block device and Acquired already exists."
        ]

        # Saving an acquired duplicate fails.
        filesystem_dupe.acquired = True
        with pytest.raises(ValidationError) as error:
            filesystem_dupe.save()
        assert error.value.messages == [
            "Filesystem with this Block device and Acquired already exists."
        ]


FSTYPES_WITH_STORAGE = tuple(
    (name, displayname)
    for name, displayname in FILESYSTEM_FORMAT_TYPE_CHOICES_DICT.items()
    if name in Filesystem.TYPES_REQUIRING_STORAGE
)
FSTYPES_WITHOUT_STORAGE = tuple(
    (name, displayname)
    for name, displayname in FILESYSTEM_FORMAT_TYPE_CHOICES_DICT.items()
    if name not in Filesystem.TYPES_REQUIRING_STORAGE
)
SUBSTRATES_STORAGE = (
    (
        "partition",
        lambda: {"partition": factory.make_Partition()},
        True,
    ),
    (
        "block-device",
        lambda: {"block_device": factory.make_PhysicalBlockDevice()},
        True,
    ),
)
SUBSTRATES_NODECONFIG = (
    (
        "node",
        lambda: {"node_config": factory.make_NodeConfig()},
        False,
    ),
)
MOUNTABLE_TYPES_SCENARIOS = [
    pytest.param(
        fstype, make_substrate, can_be_unmounted, id=f"{displayname}-{subname}"
    )
    for displayname, fstype in FSTYPES_WITH_STORAGE
    for subname, make_substrate, can_be_unmounted in SUBSTRATES_STORAGE
] + [
    pytest.param(
        fstype, make_substrate, can_be_unmounted, id=f"{displayname}-{subname}"
    )
    for displayname, fstype in FSTYPES_WITHOUT_STORAGE
    for subname, make_substrate, can_be_unmounted in SUBSTRATES_NODECONFIG
]


@pytest.mark.usefixtures("maasdb", "mock_openfga")
@pytest.mark.parametrize(
    "fstype,make_substrate,can_be_unmounted", MOUNTABLE_TYPES_SCENARIOS
)
class TestFilesystemMountableTypes:
    """Tests the `Filesystem` model with mountable filesystems."""

    def test_can_create_mountable_filesystem(
        self, fstype, make_substrate, can_be_unmounted
    ):
        substrate = make_substrate()
        filesystem = factory.make_Filesystem(fstype=fstype, **substrate)
        assert isinstance(filesystem, Filesystem)
        assert fstype == filesystem.fstype
        assert filesystem.is_mountable
        for k, v in substrate.items():
            assert getattr(filesystem, k) == v

    def test_cannot_mount_two_filesystems_at_same_point(
        self, fstype, make_substrate, can_be_unmounted
    ):
        substrate = make_substrate()
        filesystem1 = factory.make_Filesystem(fstype=fstype, **substrate)
        filesystem2 = factory.make_Filesystem(
            node_config=filesystem1.get_node().current_config
        )
        mount_point = factory.make_absolute_path()
        filesystem1.mount_point = mount_point
        filesystem1.save()
        filesystem2.mount_point = mount_point
        # Filesystems that can be mounted at a directory complain when mounted
        # at the same directory as another filesystem.
        if filesystem1.uses_mount_point:
            with pytest.raises(ValidationError) as error:
                filesystem2.save()
            assert error.value.messages == [
                f"Another filesystem is already mounted at {mount_point}."
            ]
        else:
            assert filesystem2.save() is None

    def test_can_mount_unacquired_and_acquired_filesystem_at_same_point(
        self, fstype, make_substrate, can_be_unmounted
    ):
        substrate = make_substrate()
        filesystem = factory.make_Filesystem(fstype=fstype, **substrate)
        filesystem.id = None
        filesystem.acquired = True
        assert filesystem.save() is None

    def test_mount_point_is_none_for_filesystems_that_do_not_use_one(
        self, fstype, make_substrate, can_be_unmounted
    ):
        substrate = make_substrate()
        mount_point = factory.make_name("mount-point")
        filesystem = factory.make_Filesystem(
            fstype=fstype, mount_point=mount_point, **substrate
        )
        if filesystem.uses_mount_point:
            assert mount_point == filesystem.mount_point
        else:
            assert "none" == filesystem.mount_point

    def test_filesystem_is_mounted_when_mount_point_is_set(
        self, fstype, make_substrate, can_be_unmounted
    ):
        substrate = make_substrate()
        filesystem = factory.make_Filesystem(fstype=fstype, **substrate)
        if can_be_unmounted:
            # Some filesystems can be unmounted. By default that's how the
            # factory makes them, so we need to set mount_point to see how
            # is_mounted behaves.
            assert not filesystem.is_mounted
            filesystem.mount_point = factory.make_name("path")
            assert filesystem.is_mounted
        else:
            # Some filesystems cannot be unmounted, and the factory ensures
            # that they're always created with a mount point. We can unset
            # mount_point and observe a change in is_mounted, but we'll be
            # prevented from saving the amended filesystem.
            assert filesystem.is_mounted
            filesystem.mount_point = None
            assert not filesystem.is_mounted
            with pytest.raises(ValidationError) as error:
                filesystem.save()
            assert error.value.messages == [
                "Virtual filesystems must be mounted."
            ]


@pytest.mark.parametrize(
    "fstype,mounts_at_path",
    [
        pytest.param(name, name != "swap", id=displayname)
        for name, displayname in FILESYSTEM_FORMAT_TYPE_CHOICES_DICT.items()
    ],
)
@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestFilesystemsUsingMountPoints:
    """Tests the `Filesystem` model regarding use of mount points."""

    def test_uses_mount_point_is_true_for_real_filesystems(
        self, fstype, mounts_at_path
    ):
        filesystem = factory.make_Filesystem(fstype=fstype)
        assert filesystem.uses_mount_point == mounts_at_path


@pytest.mark.parametrize(
    "fstype,mounts_device_or_partition",
    [
        pytest.param(name, name != "ramfs" and name != "tmpfs", id=displayname)
        for name, displayname in FILESYSTEM_FORMAT_TYPE_CHOICES_DICT.items()
    ],
)
@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestFilesystemsUsingStorage:
    """Tests the `Filesystem` model regarding use of storage."""

    def test_uses_mount_point_is_true_for_real_filesystems(
        self, fstype, mounts_device_or_partition
    ):
        filesystem = factory.make_Filesystem(fstype=fstype)
        assert filesystem.uses_storage == mounts_device_or_partition
