# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the Template model."""

import pytest

from maasserver.models import VersionedTextFile
from maasserver.models.template import Template


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TemplateTest:
    def test_creates_template(self):
        default_version = VersionedTextFile(data="foo")
        default_version.save()
        template = Template(
            default_version=default_version, filename="foo/bar"
        )
        template.save()
        from_db = Template.objects.get(id=template.id)
        assert from_db.default_version.data == "foo"

    def test_creates_or_update_default_creates_new(self):
        Template.objects.create_or_update_default("foo", "bar")
        from_db = Template.objects.get(filename="foo")
        assert from_db.value == "bar"

    def test_creates_or_update_default_updates_existing(self):
        Template.objects.create_or_update_default("foo", "bar")
        Template.objects.create_or_update_default("foo", "bar2")
        from_db = Template.objects.get(filename="foo")
        assert from_db.value == "bar2"

    def test_delete_related_versionedtextfile_deletes_template(self):
        Template.objects.create_or_update_default("foo", "bar")
        assert Template.objects.count() == 1
        VersionedTextFile.objects.all().delete()
        assert Template.objects.count() == 0
