# Copyright 2016-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import random
from unittest.mock import Mock

from django.core.exceptions import ValidationError
import pytest

from maasserver.models.versionedtextfile import VersionedTextFile
from maasserver.testing.factory import factory

SAMPLE_TEXT = """\
Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor
incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis
nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.
Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu
fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in
culpa qui officia deserunt mollit anim id est laborum.
"""


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestVersionedTextFile:
    def test_creates_versionedtextfile(self):
        textfile = VersionedTextFile(data=SAMPLE_TEXT)
        textfile.save()
        from_db = VersionedTextFile.objects.get(id=textfile.id)
        assert (from_db.id, from_db.data) == (textfile.id, SAMPLE_TEXT)

    def test_contents_immutable(self):
        textfile = VersionedTextFile(data=SAMPLE_TEXT)
        textfile.save()
        textfile.data = "foo"
        with pytest.raises(ValidationError, match="immutable"):
            textfile.save()

    def test_update_links_previous_revision(self):
        textfile = VersionedTextFile(data=SAMPLE_TEXT)
        textfile.save()
        textfile2 = textfile.update(SAMPLE_TEXT + " 2")
        from_db = VersionedTextFile.objects.get(id=textfile2.id)
        assert SAMPLE_TEXT + " 2" == from_db.data
        assert textfile == from_db.previous_version

    def test_update_with_no_changes_returns_current_vision(self):
        textfile = VersionedTextFile(data=SAMPLE_TEXT)
        textfile.save()
        textfile2 = textfile.update(SAMPLE_TEXT)
        from_db = VersionedTextFile.objects.get(id=textfile2.id)
        assert SAMPLE_TEXT == from_db.data
        assert from_db.previous_version is None

    def test_deletes_upstream_revisions(self):
        textfile = VersionedTextFile(data=SAMPLE_TEXT)
        textfile.save()
        textfile.update(SAMPLE_TEXT + " 2")
        assert VersionedTextFile.objects.count() == 2
        textfile.delete()
        assert VersionedTextFile.objects.count() == 0

    def test_deletes_all_upstream_revisions_from_oldest_parent(self):
        textfile = VersionedTextFile(data=SAMPLE_TEXT)
        textfile.save()
        textfile2 = textfile.update(SAMPLE_TEXT + " 2")
        textfile3 = textfile.update(SAMPLE_TEXT + " 3")
        # Create a text file with multiple children.
        textfile2.update(SAMPLE_TEXT + " 20")
        textfile2.update(SAMPLE_TEXT + " 21")
        assert VersionedTextFile.objects.count() == 5
        textfile3.get_oldest_version().delete()
        assert VersionedTextFile.objects.count() == 0

    def test_previous_versions(self):
        textfile = VersionedTextFile(data=factory.make_string())
        textfile.save()
        textfiles = [textfile]
        for _ in range(10):
            textfile = textfile.update(factory.make_string())
            textfiles.append(textfile)
        for f in textfile.previous_versions():
            assert f in textfiles

    def test_revert_zero_does_nothing(self):
        textfile = VersionedTextFile(data=SAMPLE_TEXT)
        textfile.save()
        textfile_ids = [textfile.id]
        for _ in range(10):
            textfile = textfile.update(factory.make_string())
            textfile_ids.append(textfile.id)
        assert textfile == textfile.revert(0)
        assert sorted(textfile_ids) == sorted(
            f.id for f in textfile.previous_versions()
        )

    def test_revert_by_negative_with_garbage_collection(self):
        textfile = VersionedTextFile(data=SAMPLE_TEXT)
        textfile.save()
        textfile_ids = [textfile.id]
        for _ in range(10):
            textfile = textfile.update(factory.make_string())
            textfile_ids.append(textfile.id)
        revert_to = random.randint(-10, -1)
        reverted_ids = textfile_ids[revert_to:]
        remaining_ids = textfile_ids[:revert_to]
        assert textfile_ids[revert_to - 1] == textfile.revert(revert_to).id
        for i in reverted_ids:
            with pytest.raises(VersionedTextFile.DoesNotExist):
                VersionedTextFile.objects.get(id=i)
        for i in remaining_ids:
            assert VersionedTextFile.objects.get(id=i) is not None

    def test_revert_by_negative_without_garbage_collection(self):
        textfile = VersionedTextFile(data=SAMPLE_TEXT)
        textfile.save()
        textfile_ids = [textfile.id]
        for _ in range(10):
            textfile = textfile.update(factory.make_string())
            textfile_ids.append(textfile.id)
        revert_to = random.randint(-10, -1)
        assert (
            textfile_ids[revert_to - 1] == textfile.revert(revert_to, False).id
        )
        for i in textfile_ids:
            assert VersionedTextFile.objects.get(id=i) is not None

    def test_revert_by_negative_raises_value_error_when_too_far_back(self):
        textfile = VersionedTextFile(data=SAMPLE_TEXT)
        textfile.save()
        textfile_ids = [textfile.id]
        for _ in range(10):
            textfile = textfile.update(factory.make_string())
            textfile_ids.append(textfile.id)
        with pytest.raises(ValueError):
            textfile.revert(-11)

    def test_revert_by_id_with_garbage_collection(self):
        textfile = VersionedTextFile(data=SAMPLE_TEXT)
        textfile.save()
        textfile_ids = [textfile.id]
        for _ in range(10):
            textfile = textfile.update(factory.make_string())
            textfile_ids.append(textfile.id)
        revert_to = random.choice(textfile_ids)
        reverted_ids = []
        remaining_ids = []
        reverted_or_remaining = remaining_ids
        for i in textfile_ids:
            reverted_or_remaining.append(i)
            if i == revert_to:
                reverted_or_remaining = reverted_ids
        assert VersionedTextFile.objects.get(id=revert_to) == textfile.revert(
            revert_to
        )
        for i in reverted_ids:
            with pytest.raises(VersionedTextFile.DoesNotExist):
                VersionedTextFile.objects.get(id=i)
        for i in remaining_ids:
            assert VersionedTextFile.objects.get(id=i) is not None

    def test_revert_by_id_without_garbage_collection(self):
        textfile = VersionedTextFile(data=SAMPLE_TEXT)
        textfile.save()
        textfile_ids = [textfile.id]
        for _ in range(10):
            textfile = textfile.update(factory.make_string())
            textfile_ids.append(textfile.id)
        revert_to = random.choice(textfile_ids)
        assert VersionedTextFile.objects.get(id=revert_to) == textfile.revert(
            revert_to, False
        )
        for i in textfile_ids:
            assert VersionedTextFile.objects.get(id=i) is not None

    def test_revert_by_id_raises_value_error_when_id_not_in_history(self):
        textfile = VersionedTextFile(data=SAMPLE_TEXT)
        textfile.save()
        textfile_ids = [textfile.id]
        for _ in range(10):
            textfile = textfile.update(factory.make_string())
            textfile_ids.append(textfile.id)
        other_textfile = VersionedTextFile(data=SAMPLE_TEXT)
        other_textfile.save()
        with pytest.raises(ValueError):
            textfile.revert(other_textfile.id)

    def test_revert_call_gc_hook(self):
        textfile = VersionedTextFile(data=SAMPLE_TEXT)
        textfile.save()
        textfile_ids = [textfile.id]
        for _ in range(10):
            textfile = textfile.update(factory.make_string())
            textfile_ids.append(textfile.id)
        # gc_hook only runs when there is something to revert to so
        # make sure we're actually reverting
        revert_to = random.choice(textfile_ids[:-1])
        reverted_ids = []
        remaining_ids = []
        reverted_or_remaining = remaining_ids
        for i in textfile_ids:
            reverted_or_remaining.append(i)
            if i == revert_to:
                reverted_or_remaining = reverted_ids
        gc_hook = Mock()
        textfile = textfile.revert(revert_to, gc_hook=gc_hook)
        for i in reverted_ids:
            with pytest.raises(VersionedTextFile.DoesNotExist):
                VersionedTextFile.objects.get(id=i)
        for i in remaining_ids:
            assert VersionedTextFile.objects.get(id=i) is not None
        gc_hook.assert_called_once_with(textfile)

    def test_converts_dos_formatted_to_unix_formatted(self):
        textfile = VersionedTextFile.objects.create(
            data='#!/bin/sh\r\necho "Created on Windows!"\r\n'
        )
        assert '#!/bin/sh\necho "Created on Windows!"\n' == textfile.data
        updated_textfile = textfile.update(
            '#!/bin/sh\r\necho "Updated on Windows!"\r\n'
        )
        assert textfile != updated_textfile
        assert (
            '#!/bin/sh\necho "Updated on Windows!"\n' == updated_textfile.data
        )
