# Copyright 2014-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `BootSourceForm`."""

import random

import pytest

from maascommon.osystem import CustomOS, OperatingSystemRegistry
from maasserver.enum import BOOT_RESOURCE_FILE_TYPE, BOOT_RESOURCE_TYPE
from maasserver.forms import BootResourceForm, get_uploaded_filename
from maasserver.models import (
    BootResource,
    BootResourceFile,
    bootresourcefile,
    Config,
)
from maasserver.models.signals import bootsources
from maasserver.testing.architecture import make_arch
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object
from provisioningserver.utils.env import MAAS_ID


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestBootResourceForm:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker, request, maasdb, maas_region_test, factory):
        self._mocker = mocker
        self._request = request
        bootsources.signals.disable()
        request.addfinalizer(bootsources.signals.enable)
        self.region = factory.make_RegionController()
        MAAS_ID.set(self.region.system_id)
        mocker.patch.object(bootresourcefile, "execute_workflow")

    def _make_usable_architecture(self):
        architecture = make_arch()
        self._mocker.patch(
            "maasserver.forms.list_all_usable_architectures",
            return_value=[architecture],
        )
        return architecture

    def _register_osystem(self, name):
        OperatingSystemRegistry.register_item(name, CustomOS())
        self._request.addfinalizer(
            lambda: OperatingSystemRegistry.unregister_item(name)
        )

    def pick_filetype(self):
        filetypes = {
            "tgz": BOOT_RESOURCE_FILE_TYPE.ROOT_TGZ,
            "tbz": BOOT_RESOURCE_FILE_TYPE.ROOT_TBZ,
            "txz": BOOT_RESOURCE_FILE_TYPE.ROOT_TXZ,
            "ddtgz": BOOT_RESOURCE_FILE_TYPE.ROOT_DDTGZ,
            "ddtar": BOOT_RESOURCE_FILE_TYPE.ROOT_DDTAR,
            "ddraw": BOOT_RESOURCE_FILE_TYPE.ROOT_DDRAW,
            "ddtbz": BOOT_RESOURCE_FILE_TYPE.ROOT_DDTBZ,
            "ddtxz": BOOT_RESOURCE_FILE_TYPE.ROOT_DDTXZ,
            "ddbz2": BOOT_RESOURCE_FILE_TYPE.ROOT_DDBZ2,
            "ddgz": BOOT_RESOURCE_FILE_TYPE.ROOT_DDGZ,
            "ddxz": BOOT_RESOURCE_FILE_TYPE.ROOT_DDXZ,
        }
        return random.choice(list(filetypes.items()))

    def test_creates_boot_resource(self):
        name = factory.make_name("name")
        title = factory.make_name("title")
        architecture = self._make_usable_architecture()
        subarch = architecture.split("/")[1]
        upload_type, filetype = self.pick_filetype()
        size = random.randint(1024, 2048)
        data = {
            "name": f"custom/{name}",
            "title": title,
            "architecture": architecture,
            "filetype": upload_type,
            "size": size,
            "sha256": factory.make_string(size=64),
            "base_image": factory.make_base_image_name(),
        }
        form = BootResourceForm(data=data)
        assert form.is_valid(), form._errors
        form.save()
        resource = BootResource.objects.get(
            rtype=BOOT_RESOURCE_TYPE.UPLOADED,
            name=name,
            architecture=architecture,
        )
        resource_set = resource.sets.first()
        rfile = resource_set.files.first()
        assert title == resource.extra["title"]
        assert subarch == resource.extra["subarches"]
        assert filetype == rfile.filetype
        assert get_uploaded_filename(filetype) == rfile.filename
        assert size == rfile.size

    def test_prevents_reserved_name(self):
        bsc = factory.make_BootSourceCache()
        upload_type, _ = self.pick_filetype()
        data = {
            "name": f"{bsc.os}/{bsc.release}",
            "title": factory.make_name("title"),
            "architecture": self._make_usable_architecture(),
            "filetype": upload_type,
            "size": random.randint(1024, 2048),
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        assert not form.is_valid()

    def test_prevents_reserved_osystem(self):
        bsc = factory.make_BootSourceCache()
        upload_type, _ = self.pick_filetype()
        data = {
            "name": bsc.os,
            "title": factory.make_name("title"),
            "architecture": self._make_usable_architecture(),
            "filetype": upload_type,
            "size": random.randint(1024, 2048),
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        assert not form.is_valid()

    def test_prevents_reserved_release(self):
        bsc = factory.make_BootSourceCache()
        upload_type, _ = self.pick_filetype()
        data = {
            "name": bsc.release,
            "title": factory.make_name("title"),
            "architecture": self._make_usable_architecture(),
            "filetype": upload_type,
            "size": random.randint(1024, 2048),
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        assert not form.is_valid()

    def test_prevents_reversed_osystem_from_driver(self):
        reserved_name = factory.make_name("name")
        self._register_osystem(reserved_name)
        upload_type, _ = self.pick_filetype()
        data = {
            "name": reserved_name,
            "title": factory.make_name("title"),
            "architecture": self._make_usable_architecture(),
            "filetype": upload_type,
            "size": random.randint(1024, 2048),
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        assert not form.is_valid()

    def test_prevents_reserved_centos_names(self):
        reserved_name = f"centos{random.randint(0, 99)}"
        upload_type, _ = self.pick_filetype()
        data = {
            "name": reserved_name,
            "title": factory.make_name("title"),
            "architecture": self._make_usable_architecture(),
            "filetype": upload_type,
            "size": random.randint(1024, 2048),
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        assert not form.is_valid()

    def test_prevents_unsupported_osystem(self):
        reserved_name = (
            f"{factory.make_name('osystem')}/{factory.make_name('series')}"
        )
        upload_type, _ = self.pick_filetype()
        data = {
            "name": reserved_name,
            "title": factory.make_name("title"),
            "architecture": self._make_usable_architecture(),
            "filetype": upload_type,
            "size": random.randint(1024, 2048),
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        assert not form.is_valid()

    def test_windows_does_not_require_base_image(self):
        name = f"windows/{factory.make_name('name')}"
        upload_type, _ = self.pick_filetype()
        data = {
            "name": name,
            "title": factory.make_name("title"),
            "architecture": self._make_usable_architecture(),
            "filetype": upload_type,
            "size": random.randint(1024, 2048),
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        assert form.is_valid()

    def test_esxi_does_not_require_base_image(self):
        name = f"esxi/{factory.make_name('name')}"
        upload_type, _ = self.pick_filetype()
        data = {
            "name": name,
            "title": factory.make_name("title"),
            "architecture": self._make_usable_architecture(),
            "filetype": upload_type,
            "size": random.randint(1024, 2048),
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        assert form.is_valid()

    def test_rhel_does_not_require_base_image(self):
        name = f"rhel/{factory.make_name('name')}"
        upload_type, _ = self.pick_filetype()
        data = {
            "name": name,
            "title": factory.make_name("title"),
            "architecture": self._make_usable_architecture(),
            "filetype": upload_type,
            "size": random.randint(1024, 2048),
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        assert form.is_valid()

    def test_validates_custom_image_base_os(self):
        name = f"custom/{factory.make_name('name')}"
        upload_type, _ = self.pick_filetype()
        data = {
            "name": name,
            "title": factory.make_name("title"),
            "architecture": self._make_usable_architecture(),
            "filetype": upload_type,
            "base_image": factory.make_base_image_name(),
            "size": random.randint(1024, 2048),
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        assert form.is_valid()

    def test_validates_custom_image_base_image_no_prefix(self):
        name = factory.make_name("name")
        upload_type, _ = self.pick_filetype()
        data = {
            "name": name,
            "title": factory.make_name("title"),
            "architecture": self._make_usable_architecture(),
            "filetype": upload_type,
            "base_image": factory.make_base_image_name(),
            "size": random.randint(1024, 2048),
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        assert form.is_valid()

    def test_saved_bootresource_saves_base_image(self):
        name = f"custom/{factory.make_name('name')}"
        upload_type, _ = self.pick_filetype()
        data = {
            "name": name,
            "title": factory.make_name("title"),
            "architecture": self._make_usable_architecture(),
            "filetype": upload_type,
            "base_image": factory.make_base_image_name(),
            "size": random.randint(1024, 2048),
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        image = form.save()
        assert image.base_image == data["base_image"]

    def test_update_does_not_require_base_image(self):
        name = f"custom/{factory.make_name('name')}"
        upload_type, _ = self.pick_filetype()
        data = {
            "name": name,
            "title": factory.make_name("title"),
            "architecture": self._make_usable_architecture(),
            "filetype": upload_type,
            "base_image": factory.make_base_image_name(),
            "size": random.randint(1024, 2048),
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        form.save()
        del form.data["base_image"]
        image = form.save()
        assert image.base_image == data["base_image"]

    def test_uses_commissioning_os_for_nonexistent_custom_image_base_os(self):
        name = f"custom/{factory.make_name('name')}"
        upload_type, _ = self.pick_filetype()
        data = {
            "name": name,
            "title": factory.make_name("title"),
            "architecture": self._make_usable_architecture(),
            "filetype": upload_type,
            "base_image": "",
            "size": random.randint(1024, 2048),
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        form.save()
        cfg = Config.objects.get_configs(
            ["commissioning_osystem", "commissioning_distro_series"]
        )
        assert (
            f"{cfg['commissioning_osystem']}/{cfg['commissioning_distro_series']}"
            == form.instance.base_image
        )

    def test_invalidates_nonexistent_custom_image_base_os_no_prefix(self):
        name = factory.make_name("name")
        upload_type, _ = self.pick_filetype()
        data = {
            "name": name,
            "title": factory.make_name("title"),
            "architecture": self._make_usable_architecture(),
            "filetype": upload_type,
            "base_image": factory.make_name("invalid"),
            "size": random.randint(1024, 2048),
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        assert not form.is_valid()

    def test_adds_boot_resource_set_to_existing_boot_resource(self):
        name = factory.make_name("name")
        architecture = self._make_usable_architecture()
        resource = factory.make_usable_boot_resource(
            rtype=BOOT_RESOURCE_TYPE.UPLOADED,
            name=name,
            architecture=architecture,
            base_image="ubuntu/focal",
        )
        upload_type, filetype = self.pick_filetype()
        size = random.randint(1024, 2048)
        data = {
            "name": name,
            "architecture": architecture,
            "filetype": upload_type,
            "keep_old": True,
            "size": size,
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        assert form.is_valid(), form._errors
        form.save()
        resource = reload_object(resource)
        resource_set = resource.sets.order_by("id").last()
        rfile = resource_set.files.first()
        assert filetype == rfile.filetype
        assert get_uploaded_filename(filetype) == rfile.filename
        assert size == rfile.size

    def test_creates_boot_resoures_with_uploaded_rtype(self):
        os = factory.make_name("os")
        series = factory.make_name("series")
        self._register_osystem(os)
        name = f"{os}/{series}"
        architecture = self._make_usable_architecture()
        upload_type, filetype = self.pick_filetype()
        size = random.randint(1024, 2048)
        data = {
            "name": name,
            "architecture": architecture,
            "filetype": upload_type,
            "base_image": "ubuntu/focal",
            "size": size,
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        assert form.is_valid(), form._errors
        form.save()
        resource = BootResource.objects.get(
            rtype=BOOT_RESOURCE_TYPE.UPLOADED,
            name=name,
            architecture=architecture,
        )
        resource_set = resource.sets.first()
        rfile = resource_set.files.first()
        assert filetype == rfile.filetype
        assert get_uploaded_filename(filetype) == rfile.filename
        assert size == rfile.size

    def test_adds_boot_resource_set_to_existing_uploaded_boot_resource(self):
        os = factory.make_name("os")
        series = factory.make_name("series")
        self._register_osystem(os)
        name = f"{os}/{series}"
        architecture = self._make_usable_architecture()
        resource = factory.make_usable_boot_resource(
            rtype=BOOT_RESOURCE_TYPE.UPLOADED,
            name=name,
            architecture=architecture,
            base_image="ubuntu/focal",
        )
        upload_type, filetype = self.pick_filetype()
        size = random.randint(1024, 2048)
        data = {
            "name": name,
            "architecture": architecture,
            "filetype": upload_type,
            "keep_old": True,
            "size": size,
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        assert form.is_valid(), form._errors
        form.save()
        resource = reload_object(resource)
        resource_set = resource.sets.order_by("id").last()
        rfile = resource_set.files.first()
        assert filetype == rfile.filetype
        assert get_uploaded_filename(filetype) == rfile.filename
        assert size == rfile.size
        assert resource.rtype == BOOT_RESOURCE_TYPE.UPLOADED

    def test_requires_fields(self):
        form = BootResourceForm(data={})
        assert not form.is_valid(), form.errors
        assert {"name", "architecture", "filetype", "sha256", "size"} == set(
            form.errors.keys()
        )

    def test_removes_old_bootresourcefiles(self):
        # Regression test for LP:1660418
        os = factory.make_name("os")
        series = factory.make_name("series")
        self._register_osystem(os)
        name = f"{os}/{series}"
        architecture = self._make_usable_architecture()
        resource = factory.make_usable_boot_resource(
            rtype=BOOT_RESOURCE_TYPE.UPLOADED,
            name=name,
            architecture=architecture,
        )
        upload_type, _ = self.pick_filetype()
        data = {
            "name": name,
            "architecture": architecture,
            "filetype": upload_type,
            "base_image": "ubuntu/focal",
            "size": random.randint(1024, 2048),
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        assert form.is_valid(), form._errors
        form.save()
        assert (
            1
            == BootResourceFile.objects.filter(
                resource_set__resource=resource
            ).count()
        )

    def test_clean_base_image_sets_commissioning_osystem_and_distro_series_where_none_is_given(
        self,
    ):
        architecture = self._make_usable_architecture()
        upload_type, _ = self.pick_filetype()
        data = {
            "name": f"custom/{factory.make_name()}",
            "architecture": architecture,
            "filetype": upload_type,
            "size": random.randint(1024, 2048),
            "sha256": factory.make_string(size=64),
        }
        form = BootResourceForm(data=data)
        form.save()
        cfg = Config.objects.get_configs(
            ["commissioning_osystem", "commissioning_distro_series"]
        )
        assert (
            "/".join(
                [
                    cfg["commissioning_osystem"],
                    cfg["commissioning_distro_series"],
                ]
            )
            == form.instance.base_image
        )
