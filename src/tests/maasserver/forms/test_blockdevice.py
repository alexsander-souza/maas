# Copyright 2015-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import random
import uuid

from django.core.exceptions import ValidationError
import pytest

from maasserver.enum import FILESYSTEM_TYPE
from maasserver.forms import (
    CreatePhysicalBlockDeviceForm,
    FormatBlockDeviceForm,
    UpdateDeployedPhysicalBlockDeviceForm,
    UpdatePhysicalBlockDeviceForm,
    UpdateVirtualBlockDeviceForm,
)
from maasserver.models import Filesystem
from maasserver.models.blockdevice import MIN_BLOCK_DEVICE_SIZE
from maasserver.models.partition import PARTITION_ALIGNMENT_SIZE
from maasserver.models.partitiontable import PARTITION_TABLE_TYPE
from maasserver.testing.factory import factory
from maasserver.utils.converters import round_size_to_nearest_block
from maasserver.utils.orm import get_one, reload_object


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestFormatBlockDeviceForm:
    def test_requires_fields(self):
        form = FormatBlockDeviceForm(
            block_device=factory.make_BlockDevice(), data={}
        )
        assert not form.is_valid(), form.errors
        assert form.errors.keys() == {"fstype"}

    def test_is_not_valid_if_block_device_has_partition_table(self):
        fstype = factory.pick_filesystem_type()
        block_device = factory.make_PhysicalBlockDevice()
        factory.make_PartitionTable(block_device=block_device)
        data = {"fstype": fstype}
        form = FormatBlockDeviceForm(block_device, data=data)
        assert not form.is_valid(), (
            "Should be invalid because block device has a partition table."
        )
        assert form._errors == {
            "__all__": ["Cannot format block device with a partition table."]
        }

    def test_is_not_valid_if_invalid_format_fstype(self):
        block_device = factory.make_PhysicalBlockDevice()
        data = {"fstype": FILESYSTEM_TYPE.LVM_PV}
        form = FormatBlockDeviceForm(block_device, data=data)
        assert not form.is_valid(), (
            "Should be invalid because of an invalid fstype."
        )
        assert form._errors == {
            "fstype": [
                "Select a valid choice. lvm-pv is not one of the "
                "available choices."
            ]
        }

    def test_is_not_valid_if_invalid_uuid(self):
        fstype = factory.pick_filesystem_type()
        block_device = factory.make_PhysicalBlockDevice()
        data = {"fstype": fstype, "uuid": factory.make_string(size=32)}
        form = FormatBlockDeviceForm(block_device, data=data)
        assert not form.is_valid(), (
            "Should be invalid because of an invalid uuid."
        )
        assert form._errors == {"uuid": ["Enter a valid value."]}

    def test_is_not_valid_if_invalid_uuid_append_XYZ(self):
        fstype = factory.pick_filesystem_type()
        block_device = factory.make_PhysicalBlockDevice()
        data = {
            "fstype": fstype,
            "uuid": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaXYZ",
        }
        form = FormatBlockDeviceForm(block_device, data=data)
        assert not form.is_valid(), (
            "Should be invalid because of an invalid uuid."
        )
        assert form._errors == {"uuid": ["Enter a valid value."]}

    def test_is_not_valid_if_invalid_uuid_prepend_XYZ(self):
        fstype = factory.pick_filesystem_type()
        block_device = factory.make_PhysicalBlockDevice()
        data = {
            "fstype": fstype,
            "uuid": "XYZaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        }
        form = FormatBlockDeviceForm(block_device, data=data)
        assert not form.is_valid(), (
            "Should be invalid because of an invalid uuid."
        )
        assert form._errors == {"uuid": ["Enter a valid value."]}

    def test_is_not_valid_if_non_user_format_fstype(self):
        block_device = factory.make_PhysicalBlockDevice()
        factory.make_Filesystem(
            fstype="bcache-backing", block_device=block_device
        )
        data = {"fstype": FILESYSTEM_TYPE.EXT4}
        form = FormatBlockDeviceForm(block_device, data=data)
        with pytest.raises(ValidationError):
            form.save()

    def test_creates_filesystem(self):
        fsuuid = "%s" % uuid.uuid4()
        fstype = factory.pick_filesystem_type()
        block_device = factory.make_PhysicalBlockDevice()
        data = {"uuid": fsuuid, "fstype": fstype}
        form = FormatBlockDeviceForm(block_device, data=data)
        assert form.is_valid(), form._errors
        form.save()
        filesystem = get_one(
            Filesystem.objects.filter(block_device=block_device)
        )
        assert filesystem is not None
        assert filesystem.fstype == fstype
        assert filesystem.uuid == fsuuid

    def test_deletes_old_filesystem_and_creates_new_one(self):
        fstype = factory.pick_filesystem_type()
        block_device = factory.make_PhysicalBlockDevice()
        prev_filesystem = factory.make_Filesystem(block_device=block_device)
        data = {"fstype": fstype}
        form = FormatBlockDeviceForm(block_device, data=data)
        assert form.is_valid(), form._errors
        form.save()
        assert (
            Filesystem.objects.filter(block_device=block_device).count() == 1
        ), "Should only be one filesystem that exists for block device."
        assert reload_object(prev_filesystem) is None
        filesystem = get_one(
            Filesystem.objects.filter(block_device=block_device)
        )
        assert filesystem is not None
        assert filesystem.fstype == fstype


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestCreatePhysicalBlockDeviceForm:
    def test_requires_fields(self):
        node = factory.make_Node()
        form = CreatePhysicalBlockDeviceForm(node, data={})
        assert not form.is_valid(), form.errors
        assert form.errors == {
            "name": ["This field is required."],
            "size": ["This field is required."],
            "block_size": ["This field is required."],
            "__all__": [
                "serial/model are required if id_path is not provided."
            ],
        }

    def test_creates_physical_block_device_with_model_serial(self):
        node = factory.make_Node()
        name = factory.make_name("sd")
        model = factory.make_name("model")
        serial = factory.make_name("serial")
        size = random.randint(
            MIN_BLOCK_DEVICE_SIZE, MIN_BLOCK_DEVICE_SIZE * 10
        )
        block_size = 4096
        form = CreatePhysicalBlockDeviceForm(
            node,
            data={
                "name": name,
                "model": model,
                "serial": serial,
                "size": size,
                "block_size": block_size,
            },
        )
        assert form.is_valid(), form.errors
        block_device = form.save()
        assert name == block_device.name
        assert model == block_device.model
        assert serial == block_device.serial
        assert size == block_device.size
        assert block_size == block_device.block_size
        assert node.default_numanode == block_device.numa_node

    def test_creates_physical_block_device_with_id_path(self):
        node = factory.make_Node()
        name = factory.make_name("sd")
        id_path = factory.make_absolute_path()
        size = random.randint(
            MIN_BLOCK_DEVICE_SIZE, MIN_BLOCK_DEVICE_SIZE * 10
        )
        block_size = 4096
        form = CreatePhysicalBlockDeviceForm(
            node,
            data={
                "name": name,
                "id_path": id_path,
                "size": size,
                "block_size": block_size,
            },
        )
        assert form.is_valid(), form.errors
        block_device = form.save()
        assert name == block_device.name
        assert id_path == block_device.id_path
        assert size == block_device.size
        assert block_size == block_device.block_size
        assert node.default_numanode == block_device.numa_node

    def test_creates_physical_block_device_with_numa_node(self):
        node = factory.make_Node()
        numa_node = factory.make_NUMANode(node=node)
        name = factory.make_name("sd")
        id_path = factory.make_absolute_path()
        size = random.randint(
            MIN_BLOCK_DEVICE_SIZE, MIN_BLOCK_DEVICE_SIZE * 10
        )
        block_size = 4096
        form = CreatePhysicalBlockDeviceForm(
            node,
            data={
                "name": name,
                "id_path": id_path,
                "size": size,
                "block_size": block_size,
                "numa_node": numa_node.index,
            },
        )
        assert form.is_valid(), form.errors
        block_device = form.save()
        assert name == block_device.name
        assert id_path == block_device.id_path
        assert size == block_device.size
        assert block_size == block_device.block_size
        assert numa_node == block_device.numa_node

    def test_creates_physical_block_device_invalid_numa_node(self):
        node = factory.make_Node()
        name = factory.make_name("sd")
        id_path = factory.make_absolute_path()
        size = random.randint(
            MIN_BLOCK_DEVICE_SIZE, MIN_BLOCK_DEVICE_SIZE * 10
        )
        block_size = 4096
        form = CreatePhysicalBlockDeviceForm(
            node,
            data={
                "name": name,
                "id_path": id_path,
                "size": size,
                "block_size": block_size,
                "numa_node": 4,
            },
        )
        assert not form.is_valid(), form.errors
        assert form.errors == {"numa_node": ["Invalid NUMA node"]}


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestUpdatePhysicalBlockDeviceForm:
    def test_requires_no_fields(self):
        block_device = factory.make_PhysicalBlockDevice()
        form = UpdatePhysicalBlockDeviceForm(instance=block_device, data={})
        assert form.is_valid(), form.errors
        assert form.errors.keys() == set()

    def test_updates_physical_block_device(self):
        block_device = factory.make_PhysicalBlockDevice()
        node = block_device.node_config.node
        numa_node = factory.make_NUMANode(node=node)
        name = factory.make_name("sd")
        model = factory.make_name("model")
        serial = factory.make_name("serial")
        id_path = factory.make_absolute_path()
        size = random.randint(
            MIN_BLOCK_DEVICE_SIZE, MIN_BLOCK_DEVICE_SIZE * 10
        )
        block_size = 4096
        form = UpdatePhysicalBlockDeviceForm(
            instance=block_device,
            data={
                "name": name,
                "model": model,
                "serial": serial,
                "id_path": id_path,
                "size": size,
                "block_size": block_size,
                "numa_node": numa_node.index,
            },
        )
        assert form.is_valid(), form.errors
        block_device = form.save()
        assert name == block_device.name
        assert model == block_device.model
        assert serial == block_device.serial
        assert id_path == block_device.id_path
        assert size == block_device.size
        assert block_size == block_device.block_size
        assert numa_node == block_device.numa_node

    def test_update_invalid_numa_node(self):
        block_device = factory.make_PhysicalBlockDevice()
        form = UpdatePhysicalBlockDeviceForm(
            instance=block_device, data={"numa_node": 3}
        )
        assert not form.is_valid()
        assert form.errors == {"numa_node": ["Invalid NUMA node"]}

    def test_update_no_numa_node_change(self):
        node = factory.make_Node()
        numa_node = factory.make_NUMANode(node=node)
        # associate with a node different from the default one
        block_device = factory.make_PhysicalBlockDevice(numa_node=numa_node)
        form = UpdatePhysicalBlockDeviceForm(instance=block_device, data={})
        assert form.is_valid(), form.errors
        block_device = form.save()
        assert numa_node == block_device.numa_node

    def test_udpate_partitiontable_type(self):
        block_device = factory.make_PhysicalBlockDevice()
        factory.make_PartitionTable(
            table_type=PARTITION_TABLE_TYPE.GPT, block_device=block_device
        )
        form = UpdatePhysicalBlockDeviceForm(
            instance=block_device,
            data={"partition_table_type": PARTITION_TABLE_TYPE.MBR},
        )
        assert form.is_valid(), form.errors
        block_device = form.save()
        assert (
            PARTITION_TABLE_TYPE.MBR
            == block_device.get_partitiontable().table_type
        )

    def test_udpate_partitiontable_type_no_table(self):
        block_device = factory.make_PhysicalBlockDevice()
        assert block_device.get_partitiontable() is None
        form = UpdatePhysicalBlockDeviceForm(
            instance=block_device,
            data={"partition_table_type": PARTITION_TABLE_TYPE.MBR},
        )
        assert not form.is_valid()
        assert form.errors["partition_table_type"] == [
            "Block device has no partition table"
        ]


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestUpdateDeployedPhysicalBlockDeviceForm:
    def test_requires_no_fields(self):
        block_device = factory.make_PhysicalBlockDevice()
        form = UpdateDeployedPhysicalBlockDeviceForm(
            instance=block_device, data={}
        )
        assert form.is_valid(), form.errors
        assert form.errors.keys() == set()

    def test_updates_deployed_physical_block_device(self):
        block_device = factory.make_PhysicalBlockDevice()
        name = factory.make_name("sd")
        model = factory.make_name("model")
        serial = factory.make_name("serial")
        id_path = factory.make_absolute_path()
        form = UpdateDeployedPhysicalBlockDeviceForm(
            instance=block_device,
            data={
                "name": name,
                "model": model,
                "serial": serial,
                "id_path": id_path,
            },
        )
        assert form.is_valid(), form.errors
        block_device = form.save()
        assert name == block_device.name
        assert model == block_device.model
        assert serial == block_device.serial
        assert id_path == block_device.id_path
        assert block_device.size == block_device.size
        assert block_device.block_size == block_device.block_size


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestUpdateVirtualBlockDeviceForm:
    def test_requires_no_fields(self):
        block_device = factory.make_VirtualBlockDevice()
        form = UpdateVirtualBlockDeviceForm(instance=block_device, data={})
        assert form.is_valid(), form.errors
        assert form.errors.keys() == set()

    def test_updates_virtual_block_device(self):
        block_device = factory.make_VirtualBlockDevice()
        name = factory.make_name("lv")
        vguuid = "%s" % uuid.uuid4()
        size = random.randint(
            MIN_BLOCK_DEVICE_SIZE, block_device.filesystem_group.get_size()
        )
        form = UpdateVirtualBlockDeviceForm(
            instance=block_device,
            data={"name": name, "uuid": vguuid, "size": size},
        )
        assert form.is_valid(), form.errors
        block_device = form.save()
        expected_size = round_size_to_nearest_block(
            size, PARTITION_ALIGNMENT_SIZE, False
        )
        assert name == block_device.name
        assert vguuid == block_device.uuid
        assert expected_size == block_device.size
