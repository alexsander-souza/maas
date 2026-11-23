# Copyright 2015-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


import http.client
import random
from unittest.mock import ANY

from django.urls import reverse
import pytest

from maascommon.logging.security import CREATED, DELETED, UPDATED
from maasserver.api import bcache_cacheset as bcache_cacheset_module
from maasserver.enum import ENDPOINT, FILESYSTEM_GROUP_TYPE, NODE_STATUS
from maasserver.testing.factory import factory
from maasserver.utils.converters import json_load_bytes
from maasserver.utils.orm import reload_object
from provisioningserver.events import EVENT_TYPES


def get_bcache_cache_sets_uri(node):
    """Return a Node's bcache cache sets URI on the API."""
    return reverse("bcache_cache_sets_handler", args=[node.system_id])


def get_bcache_cache_set_uri(cache_set, node=None):
    """Return a bcache cache set URI on the API."""
    if node is None:
        node = cache_set.get_node()
    return reverse(
        "bcache_cache_set_handler", args=[node.system_id, cache_set.id]
    )


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestBcacheCacheSetsAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_handler_path(self):
        node = factory.make_Node()
        assert (
            get_bcache_cache_sets_uri(node)
            == f"/MAAS/api/2.0/nodes/{node.system_id}/bcache-cache-sets/"
        )

    def test_read(self):
        node = factory.make_Node()
        cache_sets = [factory.make_CacheSet(node=node) for _ in range(3)]
        uri = get_bcache_cache_sets_uri(node)
        response = self.client.get(uri)

        assert http.client.OK == response.status_code, response.content
        expected_ids = [cache_set.id for cache_set in cache_sets]
        expected_names = [cache_set.name for cache_set in cache_sets]
        result_ids = [
            cache_set["id"] for cache_set in json_load_bytes(response.content)
        ]
        result_names = [
            cache_set["name"]
            for cache_set in json_load_bytes(response.content)
        ]
        assert sorted(expected_ids) == sorted(result_ids)
        assert sorted(expected_names) == sorted(result_names)

    def test_create(self, admin_api_client, mocker):
        mock_create_audit_event = mocker.patch.object(
            bcache_cacheset_module, "create_audit_event"
        )
        node = factory.make_Node(status=NODE_STATUS.READY)
        cache_device = factory.make_PhysicalBlockDevice(node=node)
        uri = get_bcache_cache_sets_uri(node)
        response = admin_api_client.post(
            uri, {"cache_device": cache_device.id}
        )
        assert http.client.OK == response.status_code, response.content
        parsed_device = json_load_bytes(response.content)
        assert cache_device.id == parsed_device["cache_device"]["id"]
        mock_create_audit_event.assert_called_once_with(
            EVENT_TYPES.NODE,
            ENDPOINT.API,
            ANY,
            node.system_id,
            "Created bcache cache set.",
            action=CREATED,
            id=parsed_device["id"],
        )

    def test_create_403_when_not_admin(self):
        node = factory.make_Node(status=NODE_STATUS.READY)
        cache_device = factory.make_PhysicalBlockDevice(node=node)
        uri = get_bcache_cache_sets_uri(node)
        response = self.client.post(uri, {"cache_device": cache_device.id})
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_create_409_when_not_ready(self, admin_api_client):
        node = factory.make_Node(status=NODE_STATUS.ALLOCATED)
        cache_device = factory.make_PhysicalBlockDevice(node=node)
        uri = get_bcache_cache_sets_uri(node)
        response = admin_api_client.post(
            uri, {"cache_device": cache_device.id}
        )
        assert http.client.CONFLICT == response.status_code, response.content

    def test_create_with_missing_cache_fails(self, admin_api_client):
        node = factory.make_Node(status=NODE_STATUS.READY)
        uri = get_bcache_cache_sets_uri(node)
        response = admin_api_client.post(uri, {})
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        parsed_content = json_load_bytes(response.content)
        assert (
            "Either cache_device or cache_partition must be specified."
            in parsed_content["__all__"]
        )


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestBcacheCacheSetAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_handler_path(self):
        node = factory.make_Node()
        cache_set = factory.make_CacheSet(node=node)
        assert (
            f"/MAAS/api/2.0/nodes/{node.system_id}/bcache-cache-set/{cache_set.id}/"
            == get_bcache_cache_set_uri(cache_set, node=node)
        )

    def test_read(self):
        node = factory.make_Node()
        cache_block_device = factory.make_PhysicalBlockDevice(node=node)
        cache_set = factory.make_CacheSet(block_device=cache_block_device)
        uri = get_bcache_cache_set_uri(cache_set)
        response = self.client.get(uri)

        assert http.client.OK == response.status_code, response.content
        parsed_cache_set = json_load_bytes(response.content)
        assert parsed_cache_set.get("id") == cache_set.id
        assert parsed_cache_set.get("name") == cache_set.name
        assert parsed_cache_set.get(
            "resource_uri"
        ) == get_bcache_cache_set_uri(cache_set)
        assert (
            parsed_cache_set.get("cache_device", {}).get("id")
            == cache_block_device.id
        )

        assert (
            parsed_cache_set.get("system_id") == cache_set.get_node().system_id
        )

    def test_read_404_when_invalid_id(self):
        node = factory.make_Node(owner=self.user)
        uri = reverse(
            "bcache_cache_set_handler",
            args=[node.system_id, random.randint(100, 1000)],
        )
        response = self.client.get(uri)
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_read_404_when_node_mismatch(self):
        node = factory.make_Node(owner=self.user)
        cache_set = factory.make_CacheSet(node=node)
        uri = get_bcache_cache_set_uri(cache_set, node=factory.make_Node())
        response = self.client.get(uri)
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_delete_deletes_cache_set(self, admin_api_client, mocker):
        mock_create_audit_event = mocker.patch.object(
            bcache_cacheset_module, "create_audit_event"
        )
        node = factory.make_Node(status=NODE_STATUS.READY)
        cache_set = factory.make_CacheSet(node=node)
        uri = get_bcache_cache_set_uri(cache_set)
        response = admin_api_client.delete(uri)
        assert http.client.NO_CONTENT == response.status_code, response.content
        assert reload_object(cache_set) is None
        mock_create_audit_event.assert_called_once_with(
            EVENT_TYPES.NODE,
            ENDPOINT.API,
            ANY,
            node.system_id,
            "Deleted bcache cache set.",
            action=DELETED,
            id=str(cache_set.id),
        )

    def test_delete_403_when_not_admin(self):
        node = factory.make_Node(status=NODE_STATUS.READY)
        cache_set = factory.make_CacheSet(node=node)
        uri = get_bcache_cache_set_uri(cache_set)
        response = self.client.delete(uri)
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_delete_404_when_invalid_id(self, admin_api_client):
        node = factory.make_Node(status=NODE_STATUS.READY)
        uri = reverse(
            "bcache_cache_set_handler",
            args=[node.system_id, random.randint(100, 1000)],
        )
        response = admin_api_client.delete(uri)
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_delete_409_when_not_ready(self, admin_api_client):
        node = factory.make_Node(status=NODE_STATUS.ALLOCATED)
        cache_set = factory.make_CacheSet(node=node)
        uri = get_bcache_cache_set_uri(cache_set)
        response = admin_api_client.delete(uri)
        assert http.client.CONFLICT == response.status_code, response.content

    def test_delete_400_when_cache_set_in_use(self, admin_api_client):
        node = factory.make_Node(status=NODE_STATUS.READY)
        cache_set = factory.make_CacheSet(node=node)
        factory.make_FilesystemGroup(
            group_type=FILESYSTEM_GROUP_TYPE.BCACHE,
            cache_set=cache_set,
            node=node,
        )
        uri = get_bcache_cache_set_uri(cache_set)
        response = admin_api_client.delete(uri)
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        assert (
            b"Cannot delete cache set; it's currently in use."
            == response.content
        )

    def test_update_change_cache_device(self, admin_api_client, mocker):
        mock_create_audit_event = mocker.patch.object(
            bcache_cacheset_module, "create_audit_event"
        )
        node = factory.make_Node(status=NODE_STATUS.READY)
        cache_set = factory.make_CacheSet(node=node)
        new_device = factory.make_PhysicalBlockDevice(node=node)
        uri = get_bcache_cache_set_uri(cache_set)
        response = admin_api_client.put(uri, {"cache_device": new_device.id})
        assert http.client.OK == response.status_code, response.content
        parsed_device = json_load_bytes(response.content)
        assert new_device.id == parsed_device["cache_device"]["id"]
        mock_create_audit_event.assert_called_once_with(
            EVENT_TYPES.NODE,
            ENDPOINT.API,
            ANY,
            node.system_id,
            "Updated bcache cache set.",
            action=UPDATED,
            id=str(parsed_device["id"]),
        )

    def test_update_403_when_not_admin(self):
        node = factory.make_Node(status=NODE_STATUS.READY)
        cache_set = factory.make_CacheSet(node=node)
        uri = get_bcache_cache_set_uri(cache_set)
        response = self.client.put(uri, {})
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_update_409_when_not_ready(self, admin_api_client):
        node = factory.make_Node(status=NODE_STATUS.ALLOCATED)
        cache_set = factory.make_CacheSet(node=node)
        uri = get_bcache_cache_set_uri(cache_set)
        response = admin_api_client.put(uri, {})
        assert http.client.CONFLICT == response.status_code, response.content

    def test_update_400_when_invalid_id(self, admin_api_client):
        node = factory.make_Node(status=NODE_STATUS.READY)
        cache_set = factory.make_CacheSet(node=node)
        new_device = factory.make_PhysicalBlockDevice(node=node)
        factory.make_Filesystem(block_device=new_device)
        uri = get_bcache_cache_set_uri(cache_set)
        response = admin_api_client.put(uri, {"cache_device": new_device})
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
