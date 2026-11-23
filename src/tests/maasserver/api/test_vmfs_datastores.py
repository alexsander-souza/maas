# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for VMFS datastore API."""

from collections import Counter
import http.client
import random
import uuid

from django.urls import reverse
import pytest

from maasserver.enum import FILESYSTEM_GROUP_TYPE, NODE_STATUS
from maasserver.models.filesystemgroup import VMFS
from maasserver.models.partition import MIN_PARTITION_SIZE
from maasserver.models.partitiontable import PARTITION_TABLE_EXTRA_SPACE
from maasserver.storage_layouts import VMFS6StorageLayout
from maasserver.testing.factory import factory
from maasserver.utils.converters import human_readable_bytes, json_load_bytes
from maasserver.utils.orm import reload_object
from tests.maasserver.test_storage_layouts import LARGE_BLOCK_DEVICE


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestVMFSDatastoresAPI:
    """Tests for /api/2.0/nodes/<system_id>/vmfs-datastores/."""

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user):
        self.user = maas_user

    def get_vmfs_uri(self, node):
        """Return the VMFS's URI on the API."""
        return reverse("vmfs_datastores_handler", args=[node.system_id])

    def test_handler_path(self):
        node = factory.make_Machine()
        assert "/MAAS/api/2.0/nodes/%s/vmfs-datastores/" % (
            node.system_id
        ) == self.get_vmfs_uri(node)

    def test_GET(self, api_client):
        node = factory.make_Machine()
        vmfs_datastores = [factory.make_VMFS(node=node) for _ in range(3)]
        # VMFS datastores not assoicated with the node, should not be seen.
        for _ in range(3):
            factory.make_VMFS()

        response = api_client.get(self.get_vmfs_uri(node))
        assert response.status_code == http.client.OK
        parsed_results = json_load_bytes(response.content)
        assert Counter(vmfs.id for vmfs in vmfs_datastores) == Counter(
            result["id"] for result in parsed_results
        )

    def test_POST_raises_403_if_not_admin(self, api_client):
        node = factory.make_Machine(status=NODE_STATUS.READY)
        block_device = factory.make_PhysicalBlockDevice(node=node)

        response = api_client.post(
            self.get_vmfs_uri(node),
            {
                "name": factory.make_name("name"),
                "block_devices": [block_device.id],
            },
        )
        assert response.status_code == http.client.FORBIDDEN

    def test_POST_raises_409_if_not_ready(self, admin_api_client):
        node = factory.make_Machine(status=NODE_STATUS.ALLOCATED)
        block_device = factory.make_PhysicalBlockDevice(node=node)

        response = admin_api_client.post(
            self.get_vmfs_uri(node),
            {
                "name": factory.make_name("name"),
                "block_devices": [block_device.id],
            },
        )
        assert response.status_code == http.client.CONFLICT

    def test_POST_raises_400_if_form_validation_fails(self, admin_api_client):
        node = factory.make_Machine(status=NODE_STATUS.READY)

        response = admin_api_client.post(self.get_vmfs_uri(node), {})
        assert response.status_code == http.client.BAD_REQUEST

    def test_POST_creates_with_block_devices_and_partitions(
        self, admin_api_client
    ):
        node = factory.make_Machine(
            status=NODE_STATUS.READY, with_boot_disk=False
        )
        node.boot_disk = factory.make_PhysicalBlockDevice(
            node=node, size=LARGE_BLOCK_DEVICE
        )
        layout = VMFS6StorageLayout(node)
        layout.configure()
        block_devices = [
            factory.make_PhysicalBlockDevice(node=node) for _ in range(3)
        ]
        block_device = factory.make_PhysicalBlockDevice(
            node=node,
            size=MIN_PARTITION_SIZE * 3 + PARTITION_TABLE_EXTRA_SPACE,
        )
        partition_table = factory.make_PartitionTable(
            block_device=block_device
        )
        partitions = [
            partition_table.add_partition(size=MIN_PARTITION_SIZE)
            for _ in range(2)
        ]
        name = factory.make_name("name")
        vmfs_uuid = uuid.uuid4()

        response = admin_api_client.post(
            self.get_vmfs_uri(node),
            {
                "name": name,
                "uuid": vmfs_uuid,
                "block_devices": [bd.id for bd in block_devices],
                "partitions": [part.id for part in partitions],
            },
        )
        assert response.status_code == http.client.OK
        parsed_results = json_load_bytes(response.content)
        assert node.system_id == parsed_results["system_id"]
        # VMFS should be using the 5 devices we listed above.
        assert len(parsed_results["devices"]) == 5
        # VMFS should be using all the block devices we created.
        expected_device_ids = Counter(
            [bd.id for bd in block_devices]
            + [block_device.id for _ in partitions]
        )
        actual_device_ids = Counter(
            result["device_id"] for result in parsed_results["devices"]
        )
        assert expected_device_ids == actual_device_ids


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestVMFSDatastoreAPI:
    """Tests for /api/2.0/nodes/<system_id>/vmfs/<id>."""

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user):
        self.user = maas_user

    def get_vmfs_uri(self, vmfs):
        """Return the VMFS's URI on the API."""
        return reverse(
            "vmfs_datastore_handler", args=[vmfs.get_node().system_id, vmfs.id]
        )

    def test_handler_path(self):
        node = factory.make_Machine()
        vmfs = factory.make_VMFS(node=node)
        assert "/MAAS/api/2.0/nodes/%s/vmfs-datastore/%s/" % (
            node.system_id,
            vmfs.id,
        ) == self.get_vmfs_uri(vmfs)

    def test_GET(self, api_client):
        part = factory.make_Partition()
        name = factory.make_name("datastore")
        vmfs = VMFS.objects.create_vmfs(name, [part])

        response = api_client.get(self.get_vmfs_uri(vmfs))
        assert response.status_code == http.client.OK
        parsed_result = json_load_bytes(response.content)

        assert parsed_result.get("id") == vmfs.id
        assert parsed_result.get("system_id") == vmfs.get_node().system_id
        assert parsed_result.get("uuid") == vmfs.uuid
        assert parsed_result.get("name") == vmfs.name
        assert parsed_result.get("size") == vmfs.get_size()
        assert parsed_result.get("human_size") == human_readable_bytes(
            vmfs.get_size()
        )
        assert parsed_result.get("filesystem") == {
            "fstype": "vmfs6",
            "mount_point": f"/vmfs/volumes/{name}",
        }
        assert vmfs.filesystems.count() == len(parsed_result["devices"])

    def test_GET_404_when_not_vmfs(self, api_client):
        not_vmfs = factory.make_FilesystemGroup(
            group_type=factory.pick_enum(
                FILESYSTEM_GROUP_TYPE, but_not=[FILESYSTEM_GROUP_TYPE.VMFS6]
            )
        )
        response = api_client.get(self.get_vmfs_uri(not_vmfs))
        assert response.status_code == http.client.NOT_FOUND

    def test_PUT_403_when_not_admin(self, api_client):
        node = factory.make_Machine(status=NODE_STATUS.READY)
        vmfs = factory.make_VMFS(node=node)
        response = api_client.put(self.get_vmfs_uri(vmfs))
        assert response.status_code == http.client.FORBIDDEN

    def test_PUT_409_when_not_ready(self, admin_api_client):
        node = factory.make_Machine(status=NODE_STATUS.ALLOCATED)
        vmfs = factory.make_VMFS(node=node)
        response = admin_api_client.put(self.get_vmfs_uri(vmfs))
        assert response.status_code == http.client.CONFLICT

    def test_PUT(self, admin_api_client):
        node = factory.make_Machine(status=NODE_STATUS.READY)
        vmfs = factory.make_VMFS(node=node)
        new_name = factory.make_name("name")
        new_uuid = str(uuid.uuid4())
        new_bd = factory.make_PhysicalBlockDevice(node=node)
        new_partition = factory.make_Partition(node=node)
        del_partition = random.choice(vmfs.filesystems.all()).partition
        partition_ids = {fs.partition_id for fs in vmfs.filesystems.all()}
        partition_ids.add(new_partition.id)
        partition_ids.remove(del_partition.id)

        response = admin_api_client.put(
            self.get_vmfs_uri(vmfs),
            {
                "name": new_name,
                "uuid": new_uuid,
                "add_block_devices": [random.choice([new_bd.id, new_bd.name])],
                "add_partitions": [
                    random.choice([new_partition.id, new_partition.name])
                ],
                "remove_partitions": [
                    random.choice([del_partition.id, del_partition.name])
                ],
            },
        )
        assert response.status_code == http.client.OK
        vmfs = reload_object(vmfs)
        partition_ids.add(new_bd.get_partitiontable().partitions.first().id)

        assert new_name == vmfs.name
        assert new_uuid == vmfs.uuid
        assert Counter(partition_ids) == Counter(
            fs.partition_id for fs in vmfs.filesystems.all()
        )

    def test_DELETE(self, admin_api_client):
        node = factory.make_Machine(status=NODE_STATUS.READY)
        vmfs = factory.make_VMFS(node=node)
        response = admin_api_client.delete(self.get_vmfs_uri(vmfs))
        assert response.status_code == http.client.NO_CONTENT
        assert reload_object(vmfs) is None

    def test_DELETE_403_when_not_admin(self, api_client):
        node = factory.make_Machine(status=NODE_STATUS.READY)
        vmfs = factory.make_VMFS(node=node)
        response = api_client.delete(self.get_vmfs_uri(vmfs))
        assert response.status_code == http.client.FORBIDDEN

    def test_DELETE_409_when_not_ready(self, admin_api_client):
        node = factory.make_Machine(status=NODE_STATUS.ALLOCATED)
        vmfs = factory.make_VMFS(node=node)
        response = admin_api_client.delete(self.get_vmfs_uri(vmfs))
        assert response.status_code == http.client.CONFLICT

    def test_DELETE_404_when_not_vmfs(self, admin_api_client):
        node = factory.make_Machine(status=NODE_STATUS.READY)
        not_vmfs = factory.make_FilesystemGroup(
            node=node,
            group_type=factory.pick_enum(
                FILESYSTEM_GROUP_TYPE, but_not=[FILESYSTEM_GROUP_TYPE.VMFS6]
            ),
        )
        response = admin_api_client.delete(self.get_vmfs_uri(not_vmfs))
        assert response.status_code == http.client.NOT_FOUND
