# Copyright 2015-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for bcache API."""

import http.client
from unittest.mock import ANY
from uuid import uuid4

from django.urls import reverse
import pytest

from maascommon.logging.security import CREATED, DELETED, UPDATED
from maasserver.api import bcache as bcache_module
from maasserver.enum import (
    CACHE_MODE_TYPE,
    ENDPOINT,
    FILESYSTEM_GROUP_TYPE,
    FILESYSTEM_TYPE,
    NODE_STATUS,
)
from maasserver.testing.factory import factory
from maasserver.utils.converters import human_readable_bytes, json_load_bytes
from maasserver.utils.orm import reload_object
from provisioningserver.events import EVENT_TYPES


def get_bcache_devices_uri(node):
    """Return a Node's bcache devices URI on the API."""
    return reverse("bcache_devices_handler", args=[node.system_id])


def get_bcache_device_uri(bcache, node=None):
    """Return a bcache device URI on the API."""
    if node is None:
        node = bcache.get_node()
    return reverse("bcache_device_handler", args=[node.system_id, bcache.id])


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestBcacheDevicesAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_handler_path(self):
        node = factory.make_Node()
        assert (
            f"/MAAS/api/2.0/nodes/{node.system_id}/bcaches/"
            == get_bcache_devices_uri(node)
        )

    def test_read(self):
        node = factory.make_Node()
        bcaches = [
            factory.make_FilesystemGroup(
                node=node, group_type=FILESYSTEM_GROUP_TYPE.BCACHE
            )
            for _ in range(3)
        ]
        # Not bcache. Should not be in the output.
        for _ in range(3):
            factory.make_FilesystemGroup(
                node=node,
                group_type=factory.pick_enum(
                    FILESYSTEM_GROUP_TYPE,
                    but_not=[FILESYSTEM_GROUP_TYPE.BCACHE],
                ),
            )
        uri = get_bcache_devices_uri(node)
        response = self.client.get(uri)

        assert http.client.OK == response.status_code, response.content
        expected_ids = [bcache.id for bcache in bcaches]
        result_ids = [
            bcache["id"] for bcache in json_load_bytes(response.content)
        ]
        assert sorted(expected_ids) == sorted(result_ids)

    def test_create_403_if_not_admin(self):
        node = factory.make_Node(status=NODE_STATUS.READY)
        backing_size = 10 * 1000**4
        cache_set = factory.make_CacheSet(node=node)
        backing_device = factory.make_PhysicalBlockDevice(
            node=node, size=backing_size
        )
        uuid = str(uuid4())
        uri = get_bcache_devices_uri(node)
        response = self.client.post(
            uri,
            {
                "name": "bcache0",
                "uuid": uuid,
                "cache_mode": CACHE_MODE_TYPE.WRITEBACK,
                "cache_set": cache_set.id,
                "backing_device": backing_device.id,
            },
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_create_409_if_not_ready(self, admin_api_client):
        client = admin_api_client
        node = factory.make_Node(status=NODE_STATUS.ALLOCATED)
        backing_size = 10 * 1000**4
        cache_set = factory.make_CacheSet(node=node)
        backing_device = factory.make_PhysicalBlockDevice(
            node=node, size=backing_size
        )
        uuid = str(uuid4())
        uri = get_bcache_devices_uri(node)
        response = client.post(
            uri,
            {
                "name": "bcache0",
                "uuid": uuid,
                "cache_mode": CACHE_MODE_TYPE.WRITEBACK,
                "cache_set": cache_set.id,
                "backing_device": backing_device.id,
            },
        )
        assert http.client.CONFLICT == response.status_code, response.content

    def test_create(self, admin_api_client, mocker):
        """Tests Bcache device creation."""
        mock_create_audit_event = mocker.patch.object(
            bcache_module, "create_audit_event"
        )
        node = factory.make_Node(status=NODE_STATUS.READY)
        backing_size = 10 * 1000**4
        cache_set = factory.make_CacheSet(node=node)
        backing_device = factory.make_PhysicalBlockDevice(
            node=node, size=backing_size
        )
        uuid = str(uuid4())
        uri = get_bcache_devices_uri(node)
        response = admin_api_client.post(
            uri,
            {
                "name": "bcache0",
                "uuid": uuid,
                "cache_mode": CACHE_MODE_TYPE.WRITEBACK,
                "cache_set": cache_set.id,
                "backing_device": backing_device.id,
            },
        )
        assert http.client.OK == response.status_code, response.content
        parsed_device = json_load_bytes(response.content)
        assert backing_size == parsed_device["virtual_device"]["size"]
        assert "bcache0" == parsed_device["name"]
        assert uuid == parsed_device["uuid"]

        mock_create_audit_event.assert_called_once_with(
            EVENT_TYPES.NODE,
            ENDPOINT.API,
            ANY,
            node.system_id,
            "Created bcache.",
            action=CREATED,
        )

    def test_create_with_missing_cache_set_fails(self, admin_api_client):
        """Tests Bcache device creation without a cache set."""
        node = factory.make_Node(status=NODE_STATUS.READY)
        backing_size = 10 * 1000**4
        backing_device = factory.make_PhysicalBlockDevice(
            node=node, size=backing_size
        )
        uuid = str(uuid4())
        uri = get_bcache_devices_uri(node)
        response = admin_api_client.post(
            uri,
            {
                "name": "bcache0",
                "uuid": uuid,
                "cache_mode": CACHE_MODE_TYPE.WRITEBACK,
                "backing_device": backing_device.id,
            },
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        parsed_content = json_load_bytes(response.content)
        assert "Bcache requires a cache_set." in parsed_content["__all__"]
        assert backing_device.get_effective_filesystem() is None

    def test_create_with_missing_backing_fails(self, admin_api_client):
        """Tests Bcache device creation without a backing device."""
        node = factory.make_Node(status=NODE_STATUS.READY)
        cache_set = factory.make_CacheSet(node=node)
        uuid = str(uuid4())
        uri = get_bcache_devices_uri(node)
        response = admin_api_client.post(
            uri,
            {
                "name": "bcache0",
                "uuid": uuid,
                "cache_mode": CACHE_MODE_TYPE.WRITEBACK,
                "cache_set": cache_set.id,
            },
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        parsed_content = json_load_bytes(response.content)
        assert (
            "Either backing_device or backing_partition must be specified."
            in parsed_content["__all__"]
        )


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestBcacheDeviceAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_handler_path(self):
        node = factory.make_Node()
        bcache = factory.make_FilesystemGroup(
            node=node, group_type=FILESYSTEM_GROUP_TYPE.BCACHE
        )
        assert (
            f"/MAAS/api/2.0/nodes/{node.system_id}/bcache/{bcache.id}/"
            == get_bcache_device_uri(bcache, node=node)
        )

    def test_read(self):
        node = factory.make_Node()
        cache_set = factory.make_CacheSet(node=node)
        backing_block_device = factory.make_PhysicalBlockDevice(node=node)
        backing_filesystem = factory.make_Filesystem(
            fstype=FILESYSTEM_TYPE.BCACHE_BACKING,
            block_device=backing_block_device,
        )
        bcache = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.BCACHE,
            cache_set=cache_set,
            filesystems=[backing_filesystem],
        )
        uri = get_bcache_device_uri(bcache)
        response = self.client.get(uri)

        assert http.client.OK == response.status_code, response.content
        parsed_bcache = json_load_bytes(response.content)
        assert parsed_bcache.get("id") == bcache.id
        assert parsed_bcache.get("uuid") == bcache.uuid
        assert parsed_bcache.get("name") == bcache.name
        assert parsed_bcache.get("size") == bcache.get_size()
        assert parsed_bcache.get("human_size") == human_readable_bytes(
            bcache.get_size()
        )
        assert parsed_bcache.get("resource_uri") == get_bcache_device_uri(
            bcache
        )
        assert (
            parsed_bcache.get("virtual_device", {}).get("id")
            == bcache.virtual_device.id
        )
        assert parsed_bcache.get("cache_set", {}).get("id") == cache_set.id
        assert parsed_bcache.get("cache_set", {}).get("name") == cache_set.name
        assert (
            parsed_bcache.get("backing_device", {}).get("id")
            == backing_block_device.id
        )
        assert parsed_bcache.get("system_id") == bcache.get_node().system_id

    def test_read_404_when_not_bcache(self):
        not_bcache = factory.make_FilesystemGroup(
            group_type=factory.pick_enum(
                FILESYSTEM_GROUP_TYPE, but_not=[FILESYSTEM_GROUP_TYPE.BCACHE]
            )
        )
        uri = get_bcache_device_uri(not_bcache)
        response = self.client.get(uri)
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_delete_deletes_bcache(self, admin_api_client, mocker):
        mock_create_audit_event = mocker.patch.object(
            bcache_module, "create_audit_event"
        )
        node = factory.make_Node(status=NODE_STATUS.READY)
        bcache = factory.make_FilesystemGroup(
            node=node, group_type=FILESYSTEM_GROUP_TYPE.BCACHE
        )
        uri = get_bcache_device_uri(bcache)
        response = admin_api_client.delete(uri)
        assert http.client.NO_CONTENT == response.status_code, response.content
        assert reload_object(bcache) is None
        mock_create_audit_event.assert_called_once_with(
            EVENT_TYPES.NODE,
            ENDPOINT.API,
            ANY,
            node.system_id,
            "Deleted bcache.",
            action=DELETED,
            id=str(bcache.pk),
        )

    def test_delete_403_when_not_admin(self):
        node = factory.make_Node(status=NODE_STATUS.READY)
        bcache = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.BCACHE, node=node
        )
        uri = get_bcache_device_uri(bcache)
        response = self.client.delete(uri)
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_delete_404_when_not_bcache(self, admin_api_client):
        client = admin_api_client
        node = factory.make_Node(status=NODE_STATUS.READY)
        not_bcache = factory.make_FilesystemGroup(
            node=node,
            group_type=factory.pick_enum(
                FILESYSTEM_GROUP_TYPE, but_not=[FILESYSTEM_GROUP_TYPE.BCACHE]
            ),
        )
        uri = get_bcache_device_uri(not_bcache)
        response = client.delete(uri)
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_delete_409_when_not_ready(self, admin_api_client):
        client = admin_api_client
        node = factory.make_Node(status=NODE_STATUS.ALLOCATED)
        bcache = factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.BCACHE, node=node
        )
        uri = get_bcache_device_uri(bcache)
        response = client.delete(uri)
        assert http.client.CONFLICT == response.status_code, response.content

    def test_update_bcache(self, admin_api_client, mocker):
        """Tests update bcache method by changing the name, UUID and cache
        mode of a bcache."""
        mock_create_audit_event = mocker.patch.object(
            bcache_module, "create_audit_event"
        )
        node = factory.make_Node(status=NODE_STATUS.READY)
        bcache = factory.make_FilesystemGroup(
            node=node,
            group_type=FILESYSTEM_GROUP_TYPE.BCACHE,
            cache_mode=CACHE_MODE_TYPE.WRITEBACK,
        )
        uri = get_bcache_device_uri(bcache)
        uuid = str(uuid4())
        filesystem_ids = [fs.id for fs in bcache.filesystems.all()]
        response = admin_api_client.put(
            uri,
            {
                "name": "new_name",
                "uuid": uuid,
                "cache_mode": CACHE_MODE_TYPE.WRITEAROUND,
            },
        )
        assert http.client.OK == response.status_code, response.content
        parsed_device = json_load_bytes(response.content)
        assert "new_name" == parsed_device["name"]
        assert uuid == parsed_device["uuid"]
        assert CACHE_MODE_TYPE.WRITEAROUND == parsed_device["cache_mode"]
        # Ensure the filesystems were not changed.
        assert filesystem_ids == [fs.id for fs in bcache.filesystems.all()]
        mock_create_audit_event.assert_called_once_with(
            EVENT_TYPES.NODE,
            ENDPOINT.API,
            ANY,
            node.system_id,
            "Updated bcache.",
            action=UPDATED,
            id=str(bcache.pk),
        )

    def test_change_bcache_backing(self, admin_api_client, mocker):
        """Tests update bcache method by changing backing device to different
        block device."""
        mock_create_audit_event = mocker.patch.object(
            bcache_module, "create_audit_event"
        )
        node = factory.make_Node(status=NODE_STATUS.READY)
        bcache = factory.make_FilesystemGroup(
            node=node,
            group_type=FILESYSTEM_GROUP_TYPE.BCACHE,
            cache_mode=CACHE_MODE_TYPE.WRITEBACK,
        )
        uri = get_bcache_device_uri(bcache)
        new_backing = factory.make_PhysicalBlockDevice(node=node)
        response = admin_api_client.put(
            uri, {"backing_device": new_backing.id}
        )
        assert http.client.OK == response.status_code, response.content
        parsed_device = json_load_bytes(response.content)
        assert new_backing.id == parsed_device["backing_device"]["id"]
        assert "physical" == parsed_device["backing_device"]["type"]
        mock_create_audit_event.assert_called_once_with(
            EVENT_TYPES.NODE,
            ENDPOINT.API,
            ANY,
            node.system_id,
            "Updated bcache.",
            action=UPDATED,
            id=str(bcache.pk),
        )

    def test_change_storages_to_partitions_bcache(
        self, admin_api_client, mocker
    ):
        """Tests update bcache method by changing backing device to a
        partition."""
        mock_create_audit_event = mocker.patch.object(
            bcache_module, "create_audit_event"
        )
        node = factory.make_Node(status=NODE_STATUS.READY)
        bcache = factory.make_FilesystemGroup(
            node=node,
            group_type=FILESYSTEM_GROUP_TYPE.BCACHE,
            cache_mode=CACHE_MODE_TYPE.WRITEBACK,
        )
        uri = get_bcache_device_uri(bcache)
        new_backing = factory.make_PartitionTable(
            block_device=factory.make_PhysicalBlockDevice(node=node)
        ).add_partition()
        response = admin_api_client.put(
            uri, {"backing_partition": new_backing.id}
        )
        assert http.client.OK == response.status_code, response.content
        parsed_device = json_load_bytes(response.content)
        assert new_backing.id == parsed_device["backing_device"]["id"]
        assert "partition" == parsed_device["backing_device"]["type"]
        mock_create_audit_event.assert_called_once_with(
            EVENT_TYPES.NODE,
            ENDPOINT.API,
            ANY,
            node.system_id,
            "Updated bcache.",
            action=UPDATED,
            id=str(bcache.pk),
        )

    def test_invalid_change_fails(self, admin_api_client):
        """Tests changing the backing of a bcache device to None fails."""
        client = admin_api_client
        node = factory.make_Node(status=NODE_STATUS.READY)
        bcache = factory.make_FilesystemGroup(
            node=node,
            group_type=FILESYSTEM_GROUP_TYPE.BCACHE,
            cache_mode=CACHE_MODE_TYPE.WRITEBACK,
        )
        uri = get_bcache_device_uri(bcache)
        new_backing = factory.make_PhysicalBlockDevice()  # On other node.
        response = client.put(uri, {"backing_device": new_backing.id})
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        parsed_content = json_load_bytes(response.content)
        assert "Select a valid choice." in parsed_content["backing_device"][0]

    def test_update_403_if_not_admin(self):
        node = factory.make_Node(status=NODE_STATUS.READY)
        bcache = factory.make_FilesystemGroup(
            node=node,
            group_type=FILESYSTEM_GROUP_TYPE.BCACHE,
            cache_mode=CACHE_MODE_TYPE.WRITEBACK,
        )
        uri = get_bcache_device_uri(bcache)
        uuid = str(uuid4())
        response = self.client.put(
            uri,
            {
                "name": "new_name",
                "uuid": uuid,
                "cache_mode": CACHE_MODE_TYPE.WRITEAROUND,
            },
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_update_409_if_not_ready(self, admin_api_client):
        client = admin_api_client
        node = factory.make_Node(status=NODE_STATUS.ALLOCATED)
        bcache = factory.make_FilesystemGroup(
            node=node,
            group_type=FILESYSTEM_GROUP_TYPE.BCACHE,
            cache_mode=CACHE_MODE_TYPE.WRITEBACK,
        )
        uri = get_bcache_device_uri(bcache)
        uuid = str(uuid4())
        response = client.put(
            uri,
            {
                "name": "new_name",
                "uuid": uuid,
                "cache_mode": CACHE_MODE_TYPE.WRITEAROUND,
            },
        )
        assert http.client.CONFLICT == response.status_code, response.content
