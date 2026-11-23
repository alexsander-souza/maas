# Copyright 2012-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the FileStorage model."""

from io import BytesIO

import pytest

from maasserver.models import FileStorage
from maasserver.testing.factory import factory
from maastesting.utils import sample_binary_data


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestFileStorage:
    def make_data(self, including_text="data"):
        """Return arbitrary data.

        :param including_text: Text to include in the data.  Leave something
            here to make failure messages more recognizable.
        :type including_text: unicode
        :return: A string of bytes, including `including_text`.
        :rtype: bytes
        """
        # Note that this won't automatically insert any non-ASCII bytes.
        # Proper handling of real binary data is tested separately.
        text = f"{including_text} {factory.make_string()}"
        return text.encode("ascii")

    def test_save_file_creates_storage(self):
        filename = factory.make_string()
        content = self.make_data()
        user = factory.make_User()
        storage = FileStorage.objects.save_file(
            filename, BytesIO(content), user
        )
        assert (filename, content, user) == (
            storage.filename,
            storage.content,
            storage.owner,
        )

    def test_storage_can_be_retrieved(self):
        filename = factory.make_string()
        content = self.make_data()
        factory.make_FileStorage(filename=filename, content=content)
        storage = FileStorage.objects.get(filename=filename)
        assert (filename, content) == (storage.filename, storage.content)

    def test_stores_binary_data(self):
        storage = factory.make_FileStorage(content=sample_binary_data)
        assert sample_binary_data == storage.content

    def test_overwrites_file(self):
        # If a file of the same name has already been stored, the
        # reference to the old data gets overwritten with one to the new
        # data.
        filename = factory.make_name("filename")
        old_storage = factory.make_FileStorage(
            filename=filename, content=self.make_data("old data")
        )
        new_data = self.make_data("new-data")
        new_storage = factory.make_FileStorage(
            filename=filename, content=new_data
        )
        assert old_storage.filename == new_storage.filename
        assert new_data == FileStorage.objects.get(filename=filename).content

    def test_key_gets_generated(self):
        # The generated system_id looks good.
        storage = factory.make_FileStorage()
        assert len(storage.key) == 36

    def test_key_includes_random_part(self):
        storage1 = factory.make_FileStorage()
        storage2 = factory.make_FileStorage()
        assert storage1.key != storage2.key
