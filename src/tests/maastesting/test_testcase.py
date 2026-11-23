# Copyright 2012-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `MAASTestCase`."""

import os.path
from unittest import mock as mock_module
from unittest.mock import call, MagicMock, sentinel

import pytest

from maastesting.factory import factory
from maastesting.testcase import MAASTestCase


class TestTestCase:
    """Tests the base `MAASTestCase` facilities."""

    def test_make_dir_creates_directory(self, tmp_path):
        assert os.path.isdir(tmp_path)

    def test_make_dir_creates_temporary_directory(self, tmp_path):
        # tmp_path is a temporary directory in the system temp location
        temp_root, subdir = os.path.split(str(tmp_path))
        assert subdir not in [b"", "", None]

    def test_make_dir_creates_one_directory_per_call(self, tmp_path):
        subdir1 = tmp_path / "1"
        subdir2 = tmp_path / "2"
        subdir1.mkdir()
        subdir2.mkdir()
        assert subdir1 != subdir2

    def test_make_file_creates_file(self, tmp_path):
        test_file = tmp_path / "test_file"
        test_file.touch()
        assert os.path.isfile(test_file)

    def test_make_file_uses_temporary_directory(self, tmp_path):
        test_file = tmp_path / "test_file"
        test_file.touch()
        dir_part, file_part = os.path.split(str(test_file))
        assert str(tmp_path) == dir_part

    def test_patch_can_mock(self, mocker):
        attribute_name = factory.make_name("attribute")
        obj = type("Obj", (), {})()
        with pytest.raises(AttributeError):
            getattr(obj, attribute_name)
        attribute = mocker.patch.object(obj, attribute_name, create=True)
        assert getattr(obj, attribute_name) is attribute
        assert isinstance(attribute, MagicMock)

    def method_to_be_patched(self, a, b):
        return sentinel.method_to_be_patched

    def test_patch_autospec_creates_autospec_from_target(self, mocker):
        # This test exercises MAASTestCase.patch_autospec directly since
        # it tests MAASTestCase's own delegation to mock.create_autospec.
        test_case = MAASTestCase()
        test_case.method_to_be_patched = self.method_to_be_patched
        method_to_be_patched = test_case.method_to_be_patched

        # It's simpler to test that create_autospec has been called than it is
        # to test the result of calling it; mock does some clever things to do
        # what it does that make comparisons hard.
        create_autospec = mocker.patch.object(mock_module, "create_autospec")
        create_autospec.return_value = sentinel.autospec

        method_to_be_patched_autospec = test_case.patch_autospec(
            test_case,
            "method_to_be_patched",
            spec_set=sentinel.spec_set,
            instance=sentinel.instance,
        )

        assert sentinel.autospec is method_to_be_patched_autospec
        assert sentinel.autospec is test_case.method_to_be_patched
        create_autospec.assert_called_once_with(
            method_to_be_patched, sentinel.spec_set, sentinel.instance
        )

    def test_patch_autospec_really_leaves_an_autospec_behind(self, mocker):
        mocker.patch.object(self, "method_to_be_patched", autospec=True)
        # The patched method can be called with positional or keyword
        # arguments.
        self.method_to_be_patched(1, 2)
        self.method_to_be_patched(3, b=4)
        self.method_to_be_patched(a=5, b=6)
        self.method_to_be_patched.assert_has_calls(
            [call(1, 2), call(3, b=4), call(a=5, b=6)]
        )
        # Calling the patched method with unrecognised arguments or not
        # enough arguments results in an exception.
        with pytest.raises(TypeError):
            self.method_to_be_patched(c=7)
        with pytest.raises(TypeError):
            self.method_to_be_patched(8)
        with pytest.raises(TypeError):
            self.method_to_be_patched(b=9)

    def test_assertSequenceEqual_rejects_mappings(self):
        test_case = MAASTestCase()
        with pytest.raises(AssertionError):
            test_case.assertSequenceEqual({}, [])
        with pytest.raises(AssertionError):
            test_case.assertSequenceEqual([], {})
        with pytest.raises(AssertionError):
            test_case.assertSequenceEqual({}, {})
        test_case.assertSequenceEqual([], [])

    def test_assertSequenceEqual_ignores_mappings_if_seq_type_is_set(self):
        MAASTestCase().assertSequenceEqual({}, {}, seq_type=dict)

    def test_assertSequenceEqual_forwards_message(self):
        message = factory.make_name("message")
        test_case = MAASTestCase()
        with pytest.raises(AssertionError) as exc_info:
            test_case.assertSequenceEqual([1], [2], message)
        assert message in str(exc_info.value)
