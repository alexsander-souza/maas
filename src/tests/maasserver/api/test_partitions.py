# Copyright 2015-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


import http.client
import json
import random
from uuid import uuid4

from django.conf import settings
from django.urls import reverse
import pytest

from maasserver.enum import NODE_STATUS
from maasserver.models.partition import MIN_PARTITION_SIZE
from maasserver.models.partitiontable import PARTITION_TABLE_EXTRA_SPACE
from maasserver.testing.factory import factory
from maasserver.utils.converters import (
    json_load_bytes,
    round_size_to_nearest_block,
)
from maasserver.utils.orm import reload_object


def get_partitions_uri(block_device):
    """Return a BlockDevice's partitions URI on the API."""
    return reverse(
        "partitions_handler",
        args=[block_device.node_config.node.system_id, block_device.id],
    )


def get_partition_uri(partition, by_name=False):
    """Return a BlockDevice's partition URI on the API."""
    block_device = partition.partition_table.block_device
    node = block_device.node_config.node
    partition_id = partition.id
    if by_name:
        partition_id = partition.name
    ret = reverse(
        "partition_handler",
        args=[node.system_id, block_device.id, partition_id],
    )
    # Regression test for LP:1715230 - Both partitions and partition
    # API endpoints should work
    if random.choice([True, False]):
        ret = ret.replace("partitions", "partition")
    return ret


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
class TestPartitions:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def make_partition(self, node):
        device = factory.make_PhysicalBlockDevice(
            node=node,
            size=(MIN_PARTITION_SIZE * 4) + PARTITION_TABLE_EXTRA_SPACE,
        )
        partition_table = factory.make_PartitionTable(block_device=device)
        return factory.make_Partition(
            partition_table=partition_table, size=MIN_PARTITION_SIZE
        )

    def test_create_returns_403_if_not_admin(self):
        node = factory.make_Node(status=NODE_STATUS.READY)
        block_size = 1024
        device = factory.make_PhysicalBlockDevice(
            node=node,
            size=(MIN_PARTITION_SIZE * 4) + PARTITION_TABLE_EXTRA_SPACE,
            block_size=block_size,
        )
        factory.make_PartitionTable(block_device=device)
        uri = get_partitions_uri(device)

        # Add a partition to the start of the drive.
        size = round_size_to_nearest_block(
            random.randint(MIN_PARTITION_SIZE, MIN_PARTITION_SIZE * 2),
            block_size,
        )
        response = self.client.post(uri, {"size": size})
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_create_returns_409_if_not_ready(self):
        self.user.is_superuser = True
        self.user.save()
        node = factory.make_Node(
            status=factory.pick_enum(NODE_STATUS, but_not=[NODE_STATUS.READY])
        )
        block_size = 1024
        device = factory.make_PhysicalBlockDevice(
            node=node,
            size=(MIN_PARTITION_SIZE * 4) + PARTITION_TABLE_EXTRA_SPACE,
            block_size=block_size,
        )
        factory.make_PartitionTable(block_device=device)
        uri = get_partitions_uri(device)

        # Add a partition to the start of the drive.
        size = round_size_to_nearest_block(
            random.randint(MIN_PARTITION_SIZE, MIN_PARTITION_SIZE * 2),
            block_size,
        )
        response = self.client.post(uri, {"size": size})
        assert http.client.CONFLICT == response.status_code, response.content

    def test_create_partition(self):
        self.user.is_superuser = True
        self.user.save()
        node = factory.make_Node(status=NODE_STATUS.READY)
        block_size = 1024
        device = factory.make_PhysicalBlockDevice(
            node=node,
            size=(MIN_PARTITION_SIZE * 4) + PARTITION_TABLE_EXTRA_SPACE,
            block_size=block_size,
        )
        factory.make_PartitionTable(block_device=device)
        uri = get_partitions_uri(device)

        # Add a partition to the start of the drive.
        size = round_size_to_nearest_block(
            random.randint(MIN_PARTITION_SIZE, MIN_PARTITION_SIZE * 2),
            block_size,
        )
        response = self.client.post(uri, {"size": size})
        assert http.client.OK == response.status_code, response.content

    def test_list_partitions(self):
        device = factory.make_PhysicalBlockDevice(
            size=(MIN_PARTITION_SIZE * 4) + PARTITION_TABLE_EXTRA_SPACE
        )
        partition_table = factory.make_PartitionTable(block_device=device)
        partition1 = factory.make_Partition(
            partition_table=partition_table, size=MIN_PARTITION_SIZE
        )
        partition2 = factory.make_Partition(
            partition_table=partition_table, size=MIN_PARTITION_SIZE
        )
        uri = get_partitions_uri(device)
        response = self.client.get(uri)
        assert http.client.OK == response.status_code, response.content

        partitions = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        p1 = [p for p in partitions if p["id"] == partition1.id][0]
        p2 = [p for p in partitions if p["id"] == partition2.id][0]
        assert partition1.size == p1["size"]
        assert partition1.uuid == p1["uuid"]
        assert partition2.size == p2["size"]
        assert partition2.uuid == p2["uuid"]

    def test_read_partition(self):
        device = factory.make_PhysicalBlockDevice(
            size=(MIN_PARTITION_SIZE * 4) + PARTITION_TABLE_EXTRA_SPACE
        )
        partition_table = factory.make_PartitionTable(block_device=device)
        partition = factory.make_Partition(
            partition_table=partition_table,
            size=MIN_PARTITION_SIZE,
            bootable=True,
        )
        uri = get_partition_uri(partition)
        response = self.client.get(uri)
        assert http.client.OK == response.status_code, response.content

        parsed_partition = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert parsed_partition.get("bootable") is True
        assert parsed_partition.get("id") == partition.id
        assert parsed_partition.get("size") == partition.size
        assert (
            parsed_partition.get("system_id")
            == device.node_config.node.system_id
        )
        assert parsed_partition.get("device_id") == device.id

    def test_read_partition_by_name(self):
        device = factory.make_PhysicalBlockDevice(
            size=(MIN_PARTITION_SIZE * 4) + PARTITION_TABLE_EXTRA_SPACE
        )
        partition_table = factory.make_PartitionTable(block_device=device)
        partition = factory.make_Partition(
            partition_table=partition_table,
            size=MIN_PARTITION_SIZE,
            bootable=True,
        )
        uri = get_partition_uri(partition, by_name=True)
        response = self.client.get(uri)
        assert http.client.OK == response.status_code, response.content

        parsed_partition = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert parsed_partition["bootable"]
        assert partition.id == parsed_partition["id"]
        assert partition.size == parsed_partition["size"]

    def test_read_partition_by_name_multiple(self):
        device = factory.make_PhysicalBlockDevice(
            size=(MIN_PARTITION_SIZE * 4) + PARTITION_TABLE_EXTRA_SPACE
        )
        partition_table = factory.make_PartitionTable(block_device=device)
        partition = factory.make_Partition(
            partition_table=partition_table,
            size=MIN_PARTITION_SIZE,
            bootable=True,
        )

        # a partition with same name on a different machine
        device2 = factory.make_PhysicalBlockDevice(name=device.name)
        partition_table2 = factory.make_PartitionTable(block_device=device2)
        partition2 = factory.make_Partition(partition_table=partition_table2)
        assert partition.get_name() == partition2.get_name()

        uri = get_partition_uri(partition, by_name=True)
        response = self.client.get(uri)
        assert http.client.OK == response.status_code, response.content

        parsed_partition = response.json()
        assert partition.id == parsed_partition["id"]

    def test_delete_returns_403_for_non_admin(self):
        node = factory.make_Node(owner=self.user)
        partition = self.make_partition(node)
        uri = get_partition_uri(partition)
        response = self.client.delete(uri)
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_delete_returns_409_for_not_ready_node(self):
        self.user.is_superuser = True
        self.user.save()
        node = factory.make_Node(
            status=factory.pick_enum(NODE_STATUS, but_not=[NODE_STATUS.READY])
        )
        partition = self.make_partition(node)
        uri = get_partition_uri(partition)
        response = self.client.delete(uri)
        assert http.client.CONFLICT == response.status_code, response.content

    def test_delete_partition(self):
        self.user.is_superuser = True
        self.user.save()
        node = factory.make_Node(status=NODE_STATUS.READY)
        partition = self.make_partition(node)
        uri = get_partition_uri(partition)
        response = self.client.delete(uri)

        # Returns no content and a 204 status_code.
        assert http.client.NO_CONTENT == response.status_code, response.content
        assert reload_object(partition) is None

    def test_delete_renumbers_others(self):
        self.user.is_superuser = True
        self.user.save()
        node = factory.make_Node(status=NODE_STATUS.READY)
        device = factory.make_PhysicalBlockDevice(node=node)
        partition_table = factory.make_PartitionTable(block_device=device)
        p1 = partition_table.add_partition(size=MIN_PARTITION_SIZE)
        p2 = partition_table.add_partition(size=MIN_PARTITION_SIZE)
        p3 = partition_table.add_partition(size=MIN_PARTITION_SIZE)
        uri = get_partition_uri(p1)
        response = self.client.delete(uri)
        assert http.client.NO_CONTENT == response.status_code, response.content
        assert reload_object(p2).index == 1
        assert reload_object(p3).index == 2

    def test_format_returns_409_if_not_allocated_or_ready(self):
        self.user.is_superuser = True
        self.user.save()
        status = factory.pick_enum(
            NODE_STATUS, but_not=[NODE_STATUS.READY, NODE_STATUS.ALLOCATED]
        )
        node = factory.make_Node(status=status, owner=self.user)
        partition = self.make_partition(node)
        uri = get_partition_uri(partition)
        fs_uuid = str(uuid4())
        fstype = factory.pick_filesystem_type()
        response = self.client.post(
            uri,
            {
                "op": "format",
                "uuid": fs_uuid,
                "fstype": fstype,
                "label": "mylabel",
            },
        )
        assert http.client.CONFLICT == response.status_code, response.content

    def test_format_returns_403_if_ready_and_not_admin(self):
        node = factory.make_Node(status=NODE_STATUS.READY)
        partition = self.make_partition(node)
        uri = get_partition_uri(partition)
        fs_uuid = str(uuid4())
        fstype = factory.pick_filesystem_type()
        response = self.client.post(
            uri,
            {
                "op": "format",
                "uuid": fs_uuid,
                "fstype": fstype,
                "label": "mylabel",
            },
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_format_partition_as_admin(self):
        self.user.is_superuser = True
        self.user.save()
        node = factory.make_Node(status=NODE_STATUS.READY)
        partition = self.make_partition(node)
        uri = get_partition_uri(partition)
        fs_uuid = str(uuid4())
        fstype = factory.pick_filesystem_type()
        response = self.client.post(
            uri,
            {
                "op": "format",
                "uuid": fs_uuid,
                "fstype": fstype,
                "label": "mylabel",
            },
        )
        assert http.client.OK == response.status_code, response.content
        filesystem = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )["filesystem"]
        assert fstype == filesystem["fstype"]
        assert "mylabel" == filesystem["label"]
        assert fs_uuid == filesystem["uuid"]

    def test_format_partition_as_user(self):
        node = factory.make_Node(status=NODE_STATUS.ALLOCATED, owner=self.user)
        partition = self.make_partition(node)
        uri = get_partition_uri(partition)
        fs_uuid = str(uuid4())
        fstype = factory.pick_filesystem_type()
        response = self.client.post(
            uri,
            {
                "op": "format",
                "uuid": fs_uuid,
                "fstype": fstype,
                "label": "mylabel",
            },
        )
        assert http.client.OK == response.status_code, response.content
        filesystem = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )["filesystem"]
        assert fstype == filesystem["fstype"]
        assert "mylabel" == filesystem["label"]
        assert fs_uuid == filesystem["uuid"]

    def test_format_missing_partition(self):
        self.user.is_superuser = True
        self.user.save()
        node = factory.make_Node(
            status=NODE_STATUS.READY, with_boot_disk=False
        )
        device = factory.make_PhysicalBlockDevice(
            node=node,
            size=(MIN_PARTITION_SIZE * 4) + PARTITION_TABLE_EXTRA_SPACE,
        )
        factory.make_PartitionTable(block_device=device)
        partition_id = random.randint(1, 1000)  # Most likely a bogus one
        uri = reverse(
            "partition_handler", args=[node.system_id, device.id, partition_id]
        )
        fs_uuid = str(uuid4())
        fstype = factory.pick_filesystem_type()
        response = self.client.post(
            uri,
            {
                "op": "format",
                "uuid": fs_uuid,
                "fstype": fstype,
                "label": "mylabel",
            },
        )
        # Fails with a NOT_FOUND status.
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_format_partition_with_invalid_parameters(self):
        self.user.is_superuser = True
        self.user.save()
        node = factory.make_Node(status=NODE_STATUS.READY)
        partition = self.make_partition(node)
        uri = get_partition_uri(partition)
        response = self.client.post(
            uri,
            {
                "op": "format",
                "uuid": "NOT A VALID UUID",
                "fstype": "FAT16",  # We don't support FAT16
                "label": "mylabel",
            },
        )
        # Fails with a BAD_REQUEST status.
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )

    def test_unformat_returns_409_if_not_allocated_or_ready(self):
        self.user.is_superuser = True
        self.user.save()
        status = factory.pick_enum(
            NODE_STATUS, but_not=[NODE_STATUS.READY, NODE_STATUS.ALLOCATED]
        )
        node = factory.make_Node(status=status, owner=self.user)
        partition = self.make_partition(node)
        factory.make_Filesystem(partition=partition)
        uri = get_partition_uri(partition)
        response = self.client.post(uri, {"op": "unformat"})
        assert http.client.CONFLICT == response.status_code, response.content

    def test_unformat_returns_403_if_ready_and_not_admin(self):
        node = factory.make_Node(status=NODE_STATUS.READY)
        partition = self.make_partition(node)
        factory.make_Filesystem(partition=partition)
        uri = get_partition_uri(partition)
        response = self.client.post(uri, {"op": "unformat"})
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_unformat_partition_as_admin(self):
        self.user.is_superuser = True
        self.user.save()
        node = factory.make_Node(status=NODE_STATUS.READY)
        partition = self.make_partition(node)
        factory.make_Filesystem(partition=partition)
        uri = get_partition_uri(partition)
        response = self.client.post(uri, {"op": "unformat"})
        # Returns the partition without the filesystem.
        assert http.client.OK == response.status_code, response.content
        partition = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert partition.get("filesystem") is None, (
            "Partition still has a filesystem."
        )

    def test_unformat_partition_as_user(self):
        node = factory.make_Node(status=NODE_STATUS.ALLOCATED, owner=self.user)
        partition = self.make_partition(node)
        factory.make_Filesystem(partition=partition, acquired=True)
        uri = get_partition_uri(partition)
        response = self.client.post(uri, {"op": "unformat"})
        # Returns the partition without the filesystem.
        assert http.client.OK == response.status_code, response.content
        partition = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert partition.get("filesystem") is None, (
            "Partition still has a filesystem."
        )

    def test_unformat_missing_filesystem(self):
        self.user.is_superuser = True
        self.user.save()
        node = factory.make_Node(status=NODE_STATUS.READY)
        partition = self.make_partition(node)
        uri = get_partition_uri(partition)
        response = self.client.post(uri, {"op": "unformat"})
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )

    def test_unformat_missing_partition(self):
        self.user.is_superuser = True
        self.user.save()
        node = factory.make_Node(
            status=NODE_STATUS.READY, with_boot_disk=False
        )
        device = factory.make_PhysicalBlockDevice(
            node=node,
            size=(MIN_PARTITION_SIZE * 4) + PARTITION_TABLE_EXTRA_SPACE,
        )
        factory.make_PartitionTable(block_device=device)
        partition_id = random.randint(1, 1000)  # Most likely a bogus one
        partition_id = random.randint(1, 1000)  # Most likely a bogus one
        uri = reverse(
            "partition_handler", args=[node.system_id, device.id, partition_id]
        )
        response = self.client.post(uri, {"op": "unformat"})
        # Returns nothing and a NOT_FOUND status.
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_mount_returns_409_if_not_allocated_or_ready(self):
        self.user.is_superuser = True
        self.user.save()
        status = factory.pick_enum(
            NODE_STATUS, but_not=[NODE_STATUS.READY, NODE_STATUS.ALLOCATED]
        )
        node = factory.make_Node(status=status, owner=self.user)
        block_device = factory.make_PhysicalBlockDevice(node=node)
        partition_table = factory.make_PartitionTable(
            block_device=block_device
        )
        partition = partition_table.add_partition()
        factory.make_Filesystem(partition=partition)
        uri = get_partition_uri(partition)
        mount_point = "/mnt"
        response = self.client.post(
            uri, {"op": "mount", "mount_point": mount_point}
        )
        assert http.client.CONFLICT == response.status_code, response.content

    def test_mount_returns_403_if_ready_and_not_admin(self):
        node = factory.make_Node(status=NODE_STATUS.READY)
        block_device = factory.make_PhysicalBlockDevice(node=node)
        partition_table = factory.make_PartitionTable(
            block_device=block_device
        )
        partition = partition_table.add_partition()
        factory.make_Filesystem(partition=partition)
        uri = get_partition_uri(partition)
        mount_point = "/mnt"
        response = self.client.post(
            uri, {"op": "mount", "mount_point": mount_point}
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_mount_sets_mount_path_on_filesystem_as_admin(self):
        self.user.is_superuser = True
        self.user.save()
        node = factory.make_Node(status=NODE_STATUS.READY)
        block_device = factory.make_PhysicalBlockDevice(node=node)
        partition_table = factory.make_PartitionTable(
            block_device=block_device
        )
        partition = partition_table.add_partition()
        filesystem = factory.make_Filesystem(partition=partition)
        uri = get_partition_uri(partition)
        mount_point = "/mnt"
        mount_options = factory.make_name("mount-options")
        response = self.client.post(
            uri,
            {
                "op": "mount",
                "mount_point": mount_point,
                "mount_options": mount_options,
            },
        )
        assert http.client.OK == response.status_code, response.content
        parsed_device = response.json()
        assert parsed_device["filesystem"].get("mount_point") == mount_point
        assert (
            parsed_device["filesystem"].get("mount_options") == mount_options
        )
        fs = reload_object(filesystem)
        assert fs.mount_point == mount_point
        assert fs.mount_options == mount_options
        assert fs.is_mounted is True

    def test_mount_sets_mount_path_on_filesystem_as_user(self):
        node = factory.make_Node(status=NODE_STATUS.ALLOCATED, owner=self.user)
        block_device = factory.make_PhysicalBlockDevice(node=node)
        partition_table = factory.make_PartitionTable(
            block_device=block_device
        )
        partition = partition_table.add_partition()
        filesystem = factory.make_Filesystem(
            partition=partition, acquired=True
        )
        uri = get_partition_uri(partition)
        mount_point = "/mnt"
        mount_options = factory.make_name("mount-options")
        response = self.client.post(
            uri,
            {
                "op": "mount",
                "mount_point": mount_point,
                "mount_options": mount_options,
            },
        )
        assert http.client.OK == response.status_code, response.content
        parsed_device = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert parsed_device["filesystem"].get("mount_point") == mount_point
        assert (
            parsed_device["filesystem"].get("mount_options") == mount_options
        )
        fs = reload_object(filesystem)
        assert fs.mount_point == mount_point
        assert fs.mount_options == mount_options
        assert fs.is_mounted is True

    def test_mount_returns_400_on_missing_mount_point(self):
        self.user.is_superuser = True
        self.user.save()
        node = factory.make_Node(status=NODE_STATUS.READY)
        partition = self.make_partition(node)
        factory.make_Filesystem(partition=partition)
        uri = get_partition_uri(partition)
        response = self.client.post(uri, {"op": "mount"})
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        parsed_error = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert {"mount_point": ["This field is required."]} == parsed_error

    def test_unmount_returns_409_if_not_allocated_or_ready(self):
        self.user.is_superuser = True
        self.user.save()
        status = factory.pick_enum(
            NODE_STATUS, but_not=[NODE_STATUS.READY, NODE_STATUS.ALLOCATED]
        )
        node = factory.make_Node(status=status, owner=self.user)
        partition = self.make_partition(node)
        factory.make_Filesystem(partition=partition, mount_point="/mnt")
        uri = get_partition_uri(partition)
        response = self.client.post(uri, {"op": "unmount"})
        assert http.client.CONFLICT == response.status_code, response.content

    def test_unmount_returns_403_if_ready_and_not_admin(self):
        node = factory.make_Node(status=NODE_STATUS.READY)
        partition = self.make_partition(node)
        factory.make_Filesystem(partition=partition, mount_point="/mnt")
        uri = get_partition_uri(partition)
        response = self.client.post(uri, {"op": "unmount"})
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_unmount_returns_400_if_not_formatted(self):
        self.user.is_superuser = True
        self.user.save()
        node = factory.make_Node(status=NODE_STATUS.READY)
        partition = self.make_partition(node)
        uri = get_partition_uri(partition)
        response = self.client.post(uri, {"op": "unmount"})
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        assert "Partition is not formatted." == response.content.decode(
            settings.DEFAULT_CHARSET
        )

    def test_unmount_returns_400_if_already_unmounted(self):
        self.user.is_superuser = True
        self.user.save()
        node = factory.make_Node(status=NODE_STATUS.READY)
        partition = self.make_partition(node)
        factory.make_Filesystem(partition=partition)
        uri = get_partition_uri(partition)
        response = self.client.post(uri, {"op": "unmount"})
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        assert "Filesystem is already unmounted." == response.content.decode(
            settings.DEFAULT_CHARSET
        )

    def test_unmount_unmounts_filesystem_as_admin(self):
        self.user.is_superuser = True
        self.user.save()
        node = factory.make_Node(status=NODE_STATUS.READY)
        partition = self.make_partition(node)
        filesystem = factory.make_Filesystem(
            partition=partition, mount_point="/mnt"
        )
        uri = get_partition_uri(partition)
        response = self.client.post(uri, {"op": "unmount"})
        assert http.client.OK == response.status_code, response.content
        parsed_device = response.json()
        assert parsed_device["filesystem"].get("mount_point", object()) is None
        assert (
            parsed_device["filesystem"].get("mount_options", object()) is None
        )
        fs = reload_object(filesystem)
        assert fs.mount_point is None
        assert fs.mount_options is None
        assert fs.is_mounted is False

    def test_unmount_unmounts_filesystem_as_user(self):
        node = factory.make_Node(status=NODE_STATUS.ALLOCATED, owner=self.user)
        partition = self.make_partition(node)
        filesystem = factory.make_Filesystem(
            partition=partition, mount_point="/mnt", acquired=True
        )
        uri = get_partition_uri(partition)
        response = self.client.post(uri, {"op": "unmount"})
        assert http.client.OK == response.status_code, response.content
        parsed_device = response.json()
        assert parsed_device["filesystem"].get("mount_point", object()) is None
        assert (
            parsed_device["filesystem"].get("mount_options", object()) is None
        )
        fs = reload_object(filesystem)
        assert fs.mount_point is None
        assert fs.mount_options is None
        assert fs.is_mounted is False

    def test_add_tag_returns_403_when_not_admin(self):
        node = factory.make_Node(status=NODE_STATUS.ALLOCATED, owner=self.user)
        partition = self.make_partition(node)
        uri = get_partition_uri(partition)
        response = self.client.post(
            uri, {"op": "add_tag", "tag": factory.make_name("tag")}
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_add_tag_to_partition(self):
        self.user.is_superuser = True
        self.user.save()
        node = factory.make_Node(status=NODE_STATUS.ALLOCATED, owner=self.user)
        partition = self.make_partition(node)
        uri = get_partition_uri(partition)
        tag_to_be_added = factory.make_name("tag")
        response = self.client.post(
            uri, {"op": "add_tag", "tag": tag_to_be_added}
        )

        assert http.client.OK == response.status_code, response.content
        parsed_partition = json_load_bytes(response.content)
        assert tag_to_be_added in parsed_partition["tags"]
        partition = reload_object(partition)
        assert tag_to_be_added in partition.tags

    def test_remove_tag_returns_403_when_not_admin(self):
        node = factory.make_Node(status=NODE_STATUS.ALLOCATED, owner=self.user)
        partition = self.make_partition(node)
        uri = get_partition_uri(partition)
        response = self.client.post(
            uri, {"op": "remove_tag", "tag": factory.make_name("tag")}
        )

        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_remove_tag_from_block_device(self):
        self.user.is_superuser = True
        self.user.save()
        node = factory.make_Node(status=NODE_STATUS.ALLOCATED, owner=self.user)
        partition = self.make_partition(node)
        uri = get_partition_uri(partition)
        tag_to_be_removed = partition.tags[0]
        response = self.client.post(
            uri, {"op": "remove_tag", "tag": tag_to_be_removed}
        )

        assert http.client.OK == response.status_code, response.content
        parsed_partition = json_load_bytes(response.content)
        assert tag_to_be_removed not in parsed_partition["tags"]
        partition = reload_object(partition)
        assert tag_to_be_removed not in partition.tags
