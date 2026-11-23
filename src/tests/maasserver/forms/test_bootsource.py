# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `BootSourceForm`."""

from io import BytesIO

from django.core.files.uploadedfile import InMemoryUploadedFile
import pytest

from maasserver.forms import BootSourceForm
from maasserver.models.signals import bootsources
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object
from maastesting.utils import sample_binary_data


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestBootSourceForm:
    """Tests for `BootSourceForm`."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        # Disable boot source cache signals.
        bootsources.signals.disable()
        yield
        bootsources.signals.enable()

    def test_edits_boot_source_object(self):
        boot_source = factory.make_BootSource()
        params = {
            "url": "http://example.com",
            "keyring_filename": factory.make_name("keyring_filename"),
        }
        form = BootSourceForm(instance=boot_source, data=params)
        assert form.is_valid(), form._errors
        form.save()
        boot_source = reload_object(boot_source)
        assert boot_source.url == "http://example.com"
        assert boot_source.keyring_filename == params["keyring_filename"]

    def test_creates_boot_source_object_with_keyring_filename(self):
        params = {
            "url": "http://example.com",
            "keyring_filename": factory.make_name("keyring_filename"),
        }
        form = BootSourceForm(data=params)
        assert form.is_valid(), form._errors
        boot_source = form.save()
        assert boot_source.url == "http://example.com"
        assert boot_source.keyring_filename == params["keyring_filename"]

    def test_creates_boot_source_object_with_keyring_data(self):
        in_mem_file = InMemoryUploadedFile(
            BytesIO(sample_binary_data),
            name=factory.make_name("name"),
            field_name=factory.make_name("field-name"),
            content_type="application/octet-stream",
            size=len(sample_binary_data),
            charset=None,
        )
        params = {"url": "http://example.com"}
        form = BootSourceForm(data=params, files={"keyring_data": in_mem_file})
        assert form.is_valid(), form._errors
        boot_source = form.save()
        assert bytes(boot_source.keyring_data) == sample_binary_data
        assert boot_source.url == "http://example.com"

    def test_creates_boot_source_with_name(self):
        params = {
            "url": "http://example.com",
            "keyring_filename": factory.make_name("keyring_filename"),
            "name": "my-custom-source",
        }
        form = BootSourceForm(data=params)
        assert form.is_valid(), form._errors
        boot_source = form.save()
        assert boot_source.name == "my-custom-source"

    def test_creates_boot_source_with_priority(self):
        params = {
            "url": "http://example.com",
            "keyring_filename": factory.make_name("keyring_filename"),
            "priority": 5,
        }
        form = BootSourceForm(data=params)
        assert form.is_valid(), form._errors
        boot_source = form.save()
        assert boot_source.priority == 5

    def test_creates_boot_source_with_enabled_false(self):
        params = {
            "url": "http://example.com",
            "keyring_filename": factory.make_name("keyring_filename"),
            "enabled": False,
        }
        form = BootSourceForm(data=params)
        assert form.is_valid(), form._errors
        boot_source = form.save()
        assert not boot_source.enabled

    def test_creates_boot_source_without_optional_fields(self):
        params = {
            "url": "http://example.com",
            "keyring_filename": factory.make_name("keyring_filename"),
        }
        form = BootSourceForm(data=params)
        assert form.is_valid(), form._errors
        boot_source = form.save()
        assert boot_source.name == "http://example.com"
        # Stable boot source is created with priority 1 by the migrations.
        assert boot_source.priority == 2
        assert boot_source.enabled
        assert not boot_source.skip_keyring_verification
