# Copyright 2023-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


from collections import Counter
import http.client
import json
import random

from django.urls import reverse
import pytest

from maasserver.enum import BOOT_RESOURCE_TYPE
from maasserver.models.user import create_auth_token
from maasserver.testing.factory import factory
from maasserver.testing.testclient import MAASSensibleOAuthClient
from maasserver.worker_user import get_worker_user


def get_image_sync_uri(file_id, system_id):
    return reverse("image_sync_progress_handler", args=[file_id, system_id])


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=worker,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestImageSyncProgressHandler:
    @pytest.fixture(autouse=True)
    def _setup(self, maas_region_test, api_identity):
        self.user = get_worker_user()
        token = create_auth_token(self.user)
        self.client = MAASSensibleOAuthClient(user=self.user, token=token)

    def test_handler_path(self):
        assert "/MAAS/api/2.0/images-sync-progress/1/a/" == get_image_sync_uri(
            1, "a"
        )

    def test_update_creates_default_size(self):
        region = factory.make_RegionController()
        total_size = random.randint(1024, 2048)
        resource = factory.make_BootResource(rtype=BOOT_RESOURCE_TYPE.UPLOADED)
        resource_set = factory.make_BootResourceSet(resource)
        file = factory.make_boot_resource_file_with_content(
            resource_set, size=total_size
        )
        uri = get_image_sync_uri(file.id, region.system_id)
        response = self.client.put(uri, {})
        assert http.client.OK == response.status_code, response.content
        syncstatus = file.bootresourcefilesync_set.get(region=region)
        assert syncstatus.size == 0

    def test_update(self):
        region = factory.make_RegionController()
        total_size = random.randint(1024, 2048)
        resource = factory.make_BootResource(rtype=BOOT_RESOURCE_TYPE.UPLOADED)
        resource_set = factory.make_BootResourceSet(resource)
        file = factory.make_boot_resource_file_with_content(
            resource_set, size=total_size
        )
        test_size = random.randint(1, 30)
        uri = get_image_sync_uri(file.id, region.system_id)
        response = self.client.put(uri, {"size": test_size})
        assert http.client.OK == response.status_code, response.content
        syncstatus = file.bootresourcefilesync_set.get(region=region)
        assert test_size == syncstatus.size

    def test_update_existing_brfsync(self):
        region = factory.make_RegionController()
        total_size = random.randint(1024, 2048)
        resource = factory.make_BootResource(rtype=BOOT_RESOURCE_TYPE.UPLOADED)
        resource_set = factory.make_BootResourceSet(resource)
        file = factory.make_boot_resource_file_with_content(
            resource_set, size=total_size
        )
        syncset = file.bootresourcefilesync_set.create(region=region)
        test_size = random.randint(1, 30)
        uri = get_image_sync_uri(file.id, region.system_id)
        response = self.client.put(uri, {"size": test_size})
        assert http.client.OK == response.status_code, response.content
        syncset = file.bootresourcefilesync_set.get(region=region)
        assert syncset.size == test_size

    def test_update_fail_no_file(self):
        region = factory.make_RegionController()
        total_size = random.randint(1024, 2048)
        resource = factory.make_BootResource(rtype=BOOT_RESOURCE_TYPE.UPLOADED)
        resource_set = factory.make_BootResourceSet(resource)
        file = factory.make_boot_resource_file_with_content(
            resource_set, size=total_size
        )
        test_size = random.randint(1, 30)
        uri = get_image_sync_uri((file.id + 1), region.system_id)
        response = self.client.put(uri, {"size": test_size})
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_read_nonexistent_brfsync(self):
        region = factory.make_RegionController()
        total_size = random.randint(1024, 2048)
        resource = factory.make_BootResource(rtype=BOOT_RESOURCE_TYPE.UPLOADED)
        resource_set = factory.make_BootResourceSet(resource)
        file = factory.make_boot_resource_file_with_content(
            resource_set, size=total_size
        )
        uri = get_image_sync_uri(file.id, region.system_id)
        response = self.client.get(uri)
        assert http.client.OK == response.status_code, response.content
        r = json.loads(response.content)
        assert r.get("size") == 0

    def test_read_existing_brfsync(self):
        region = factory.make_RegionController()
        total_size = random.randint(1024, 2048)
        resource = factory.make_BootResource(rtype=BOOT_RESOURCE_TYPE.UPLOADED)
        resource_set = factory.make_BootResourceSet(resource)
        file = factory.make_boot_resource_file_with_content(
            resource_set, size=total_size
        )
        test_size = random.randint(1, 10)
        filesync = file.bootresourcefilesync_set.create(
            region=region, size=test_size
        )
        uri = get_image_sync_uri(file.id, region.system_id)
        response = self.client.get(uri)
        assert http.client.OK == response.status_code, response.content
        r = json.loads(response.content)
        assert r.get("size") == filesync.size

    def test_read_nonexistent_file(self):
        region = factory.make_RegionController()
        total_size = random.randint(1024, 2048)
        resource = factory.make_BootResource(rtype=BOOT_RESOURCE_TYPE.UPLOADED)
        resource_set = factory.make_BootResourceSet(resource)
        file = factory.make_boot_resource_file_with_content(
            resource_set, size=total_size
        )
        uri = get_image_sync_uri((file.id + 1), region.system_id)
        response = self.client.get(uri)
        assert http.client.NOT_FOUND == response.status_code, response.content


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=worker,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestImagesSyncProgressHandler:
    @pytest.fixture(autouse=True)
    def _setup(self, maas_region_test, api_identity):
        self.user = get_worker_user()
        token = create_auth_token(self.user)
        self.client = MAASSensibleOAuthClient(user=self.user, token=token)

    def test_read(self):
        regions = [factory.make_RegionController() for _ in range(3)]
        resource = factory.make_BootResource(rtype=BOOT_RESOURCE_TYPE.UPLOADED)
        resource_set = factory.make_BootResourceSet(resource)

        complete = factory.make_BootResourceFile(
            resource_set=resource_set,
            synced=[(r, -1) for r in regions],
        )
        partial_sync = factory.make_BootResourceFile(
            resource_set=resource_set,
            synced=[(r, -1) for r in regions[2:]],
        )
        factory.make_BootResourceFile(
            resource_set=resource_set,
            size=512,
            synced=[(regions[0], 256)],
        )
        response = self.client.get(reverse("images_sync_progress_handler"))
        assert http.client.OK == response.status_code, response.content
        status = response.json()
        assert complete.size == status[str(complete.id)]["size"]
        assert complete.sha256 == status[str(complete.id)]["sha256"]
        assert partial_sync.size == status[str(partial_sync.id)]["size"]
        assert partial_sync.sha256 == status[str(partial_sync.id)]["sha256"]
        assert Counter((str(partial_sync.id), str(complete.id))) == Counter(
            set(status.keys())
        )
        assert Counter([r.system_id for r in regions]) == Counter(
            status[str(complete.id)]["sources"]
        )
        assert Counter([r.system_id for r in regions[2:]]) == Counter(
            status[str(partial_sync.id)]["sources"]
        )

    def test_bulk_create(self):
        regions = [factory.make_RegionController() for _ in range(2)]
        resource = factory.make_BootResource(rtype=BOOT_RESOURCE_TYPE.UPLOADED)
        resource_set = factory.make_BootResourceSet(resource)
        rfiles = [
            factory.make_BootResourceFile(resource_set=resource_set)
            for _ in range(3)
        ]
        response = self.client.post(
            reverse("images_sync_progress_handler"),
            {
                "ids": [f.id for f in rfiles[:1]],
                "system_id": regions[0].system_id,
                "size": 1,
            },
        )
        assert http.client.OK == response.status_code, response.content
        for f in rfiles[:1]:
            assert 1 == f.bootresourcefilesync_set.get(region=regions[0]).size
        assert (
            not rfiles[0]
            .bootresourcefilesync_set.filter(region=regions[1])
            .exists()
        )
        assert (
            not rfiles[2]
            .bootresourcefilesync_set.filter(region=regions[0])
            .exists()
        )

    def test_bulk_create_single_val(self):
        regions = [factory.make_RegionController() for _ in range(2)]
        resource = factory.make_BootResource(rtype=BOOT_RESOURCE_TYPE.UPLOADED)
        resource_set = factory.make_BootResourceSet(resource)
        rfiles = [factory.make_BootResourceFile(resource_set=resource_set)]
        response = self.client.post(
            reverse("images_sync_progress_handler"),
            {
                "ids": [f.id for f in rfiles],
                "system_id": regions[0].system_id,
                "size": 1,
            },
        )
        assert http.client.OK == response.status_code, response.content
        for f in rfiles:
            assert 1 == f.bootresourcefilesync_set.get(region=regions[0]).size
