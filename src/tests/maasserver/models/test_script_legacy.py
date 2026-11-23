# Copyright 2017-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


from datetime import timedelta
import random

import pytest

from maasserver.models import Script, VersionedTextFile
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object
from metadataserver.enum import HARDWARE_TYPE_CHOICES


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestScriptManager:
    """Test the ScriptManager."""

    def test_create_accepts_str_for_script(self):
        name = factory.make_name("name")
        script_str = factory.make_string()
        comment = factory.make_name("comment")

        script = Script.objects.create(
            name=name, script=script_str, comment=comment
        )

        assert script_str == script.script.data
        assert comment == script.script.comment

    def test_create_accepts_ver_txt_file_for_script(self):
        name = factory.make_name("name")
        script_str = factory.make_string()
        ver_txt_file = VersionedTextFile.objects.create(data=script_str)

        script = Script.objects.create(name=name, script=ver_txt_file)

        assert script_str == script.script.data
        assert ver_txt_file == script.script

    def test_create_accepts_int_for_timeout(self):
        name = factory.make_name("name")
        script_str = factory.make_string()
        timeout = random.randint(0, 1000)

        script = Script.objects.create(
            name=name, script=script_str, timeout=timeout
        )

        assert timedelta(seconds=timeout) == script.timeout

    def test_create_accepts_timedelta_for_timeout(self):
        name = factory.make_name("name")
        script_str = factory.make_string()
        timeout = timedelta(random.randint(0, 1000))

        script = Script.objects.create(
            name=name, script=script_str, timeout=timeout
        )

        assert timeout == script.timeout


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestScript:
    """Test the Script model."""

    def test_add_tag(self):
        script = factory.make_Script()
        new_tag = factory.make_name("tag")
        script.add_tag(new_tag)
        script.save()
        assert new_tag in reload_object(script).tags

    def test_add_tag_only_adds_new_tag(self):
        script = factory.make_Script()
        new_tag = factory.make_name("tag")
        script.add_tag(new_tag)
        script.add_tag(new_tag)
        script.save()
        script = reload_object(script)
        assert len(set(script.tags)) == len(script.tags)

    def test_remove_tag(self):
        script = factory.make_Script()
        removed_tag = random.choice(
            [tag for tag in script.tags if "tag" in tag]
        )
        script.remove_tag(removed_tag)
        script.save()
        assert removed_tag not in reload_object(script).tags

    def test_remove_tags_ignores_nonexistant_tag(self):
        script = factory.make_Script()
        tag_count = len(script.tags)
        script.remove_tag(factory.make_name("tag"))
        script.save()
        assert tag_count == len(reload_object(script).tags)

    def test_destructive_true_adds_tag(self):
        script = factory.make_Script(destructive=False)
        script.destructive = True
        script.save()
        assert "destructive" in reload_object(script).tags

    def test_destructive_false_removes_tag(self):
        script = factory.make_Script(destructive=True)
        script.destructive = False
        script.save()
        assert "destructive" not in reload_object(script).tags

    def test_adds_tags_for_hardware_types(self):
        script = factory.make_Script(tags=[], destructive=False)
        for hw_type, hw_type_label in HARDWARE_TYPE_CHOICES:
            script.hardware_type = hw_type
            script.save()
            assert [hw_type_label.lower()] == script.tags
