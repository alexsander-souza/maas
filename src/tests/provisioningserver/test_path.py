# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for filesystem paths."""

from os import getcwd
import os.path

from fixtures import EnvironmentVariableFixture
import pytest

from maastesting.factory import factory
import provisioningserver.path
from provisioningserver.path import (
    get_data_path,
    get_maas_cache_path,
    get_maas_data_path,
    get_path,
    get_tentative_data_path,
)


@pytest.mark.parametrize(
    "get_path_function,ensures_directory,fixture",
    [
        (
            get_path,
            False,
            lambda path: EnvironmentVariableFixture("MAAS_PATH", path),
        ),
        (
            get_data_path,
            True,
            lambda path: EnvironmentVariableFixture("MAAS_ROOT", path),
        ),
        (
            get_tentative_data_path,
            False,
            lambda path: EnvironmentVariableFixture("MAAS_ROOT", path),
        ),
    ],
    ids=["get_path", "get_data_path", "get_tentative_data_path"],
)
class TestGetPathFunctions:
    """Tests for `get_path`, `get_data_path` and `get_tentative_data_path`."""

    @pytest.fixture(autouse=True)
    def _setup(self, mocker, tmp_path):
        self.mocker = mocker
        self.tmp_path = tmp_path
        self._root_fixture = None
        yield
        if self._root_fixture is not None:
            self._root_fixture.cleanUp()

    def set_root(self, fixture, root_path=None):
        """For the duration of this test, set the `MAAS_ROOT` variable`."""
        self._root_fixture = fixture(root_path)
        self._root_fixture.setUp()

    def test_defaults_to_root(
        self, get_path_function, ensures_directory, fixture
    ):
        self.set_root(fixture)
        self.mocker.patch.object(provisioningserver.path, "makedirs")
        assert "/" == get_path_function()

    def test_appends_path_elements(
        self, get_path_function, ensures_directory, fixture
    ):
        self.set_root(fixture, "/")
        self.mocker.patch.object(provisioningserver.path, "makedirs")
        part1 = factory.make_name("dir")
        part2 = factory.make_name("file")
        assert os.path.join("/", part1, part2) == get_path_function(
            part1, part2
        )

    def test_obeys_MAAS_ROOT_variable(
        self, get_path_function, ensures_directory, fixture
    ):
        root = factory.make_name("/root")
        self.set_root(fixture, root)
        self.mocker.patch.object(provisioningserver.path, "makedirs")
        path = factory.make_name("path")
        assert os.path.join(root, path) == get_path_function(path)

    def test_assumes_MAAS_ROOT_is_unset_if_empty(
        self, get_path_function, ensures_directory, fixture
    ):
        self.set_root(fixture, "")
        self.mocker.patch.object(provisioningserver.path, "makedirs")
        path = factory.make_name("path")
        assert os.path.join("/", path) == get_path_function(path)

    def test_returns_absolute_path(
        self, get_path_function, ensures_directory, fixture
    ):
        self.set_root(fixture, ".")
        self.mocker.patch.object(provisioningserver.path, "makedirs")
        assert get_path_function()[0] == "/"
        assert getcwd() == get_path_function()

    def test_concatenates_despite_leading_slash(
        self, get_path_function, ensures_directory, fixture
    ):
        root = str(self.tmp_path)
        self.set_root(fixture, root)
        self.mocker.patch.object(provisioningserver.path, "makedirs")
        filename = factory.make_name("file")
        assert os.path.join(root, filename) == get_path_function(
            "/" + filename
        )

    def test_normalises(self, get_path_function, ensures_directory, fixture):
        self.set_root(fixture)
        self.mocker.patch.object(provisioningserver.path, "makedirs")
        assert "/foo/bar" == get_path_function("foo///szut//..///bar//")

    def test_maybe_creates_dirpath_if_not_exists(
        self, get_path_function, ensures_directory, fixture
    ):
        root_path = str(self.tmp_path)
        self.set_root(fixture, root_path)
        dir_name = os.path.dirname(get_path_function("/foo/bar"))
        if ensures_directory:
            assert os.path.isdir(dir_name), dir_name
        else:
            assert not os.path.isdir(dir_name), dir_name


class TestGetMAASDataPath:
    def test_get_maas_data_path_env(self, monkeypatch):
        monkeypatch.setenv("MAAS_DATA", "/custom/path")
        assert get_maas_data_path("some/path") == "/custom/path/some/path"

    def test_get_maas_data_path_no_env(self, monkeypatch):
        monkeypatch.delenv("MAAS_DATA", raising=False)
        assert get_maas_data_path("some/path") == "/var/lib/maas/some/path"


class TestGetMAASCachePath:
    def test_get_maas_cache_path_env(self, monkeypatch):
        monkeypatch.setenv("MAAS_CACHE", "some/cache/path")
        assert get_maas_cache_path("foo") == "some/cache/path/foo"

    def test_get_maas_cache_path_no_env(self, monkeypatch):
        monkeypatch.delenv("MAAS_CACHE", raising=False)
        assert get_maas_cache_path("some/path") == "/var/cache/maas/some/path"
