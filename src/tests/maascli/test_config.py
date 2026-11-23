# Copyright 2012-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maascli.config`."""

import contextlib
import os.path
import sqlite3

import pytest
from twisted.python.filepath import FilePath

from maascli import api


class TestProfileConfig:
    """Tests for `ProfileConfig`."""

    def test_init(self):
        database = sqlite3.connect(":memory:")
        config = api.ProfileConfig(database)
        with config.cursor() as cursor:
            # The profiles table has been created.
            assert cursor.execute(
                "SELECT COUNT(*) FROM sqlite_master"
                " WHERE type = 'table'"
                "   AND name = 'profiles'"
            ).fetchone() == (1,)

    def test_profiles_pristine(self):
        # A pristine configuration has no profiles.
        database = sqlite3.connect(":memory:")
        config = api.ProfileConfig(database)
        assert set() == set(config)

    def test_adding_profile(self):
        database = sqlite3.connect(":memory:")
        config = api.ProfileConfig(database)
        config["alice"] = {"abc": 123}
        assert {"alice"} == set(config)
        assert {"abc": 123} == config["alice"]

    def test_replacing_profile(self):
        database = sqlite3.connect(":memory:")
        config = api.ProfileConfig(database)
        config["alice"] = {"abc": 123}
        config["alice"] = {"def": 456}
        assert {"alice"} == set(config)
        assert {"def": 456} == config["alice"]

    def test_cache(self, mocker):
        database = sqlite3.connect(":memory:")
        config = api.ProfileConfig(database)
        config["alice"] = {"abc": 123}
        cursor = mocker.patch.object(config, "cursor")
        assert {"abc": 123} == config["alice"]
        cursor.assert_not_called()

    def test_getting_profile(self):
        database = sqlite3.connect(":memory:")
        config = api.ProfileConfig(database)
        config["alice"] = {"abc": 123}
        assert {"abc": 123} == config["alice"]

    def test_getting_non_existent_profile(self):
        database = sqlite3.connect(":memory:")
        config = api.ProfileConfig(database)
        with pytest.raises(KeyError):
            config["alice"]

    def test_removing_profile(self):
        database = sqlite3.connect(":memory:")
        config = api.ProfileConfig(database)
        config["alice"] = {"abc": 123}
        del config["alice"]
        assert set() == set(config)

    def test_open_no_file_fail(self, tmp_path):
        config_file = os.path.join(tmp_path, "config")
        with pytest.raises(FileNotFoundError):
            with api.ProfileConfig.open(config_file):
                pass

    def test_open_and_close(self, tmp_path):
        # ProfileConfig.open() returns a context manager that closes the
        # database on exit.
        config_file = os.path.join(tmp_path, "config")
        config = api.ProfileConfig.open(config_file, create=True)
        assert isinstance(config, contextlib._GeneratorContextManager)
        with config as config:
            assert isinstance(config, api.ProfileConfig)
            with config.cursor() as cursor:
                assert (1,) == cursor.execute("SELECT 1").fetchone()
        with pytest.raises(sqlite3.ProgrammingError):
            config.cursor()

    def test_open_permissions_new_database(self, tmp_path):
        # ProfileConfig.open() applies restrictive file permissions to newly
        # created configuration databases.
        config_file = os.path.join(tmp_path, "config")
        with api.ProfileConfig.open(config_file, create=True):
            perms = FilePath(config_file).getPermissions()
            assert "rw-------" == perms.shorthand()

    def test_open_permissions_existing_database(self, tmp_path):
        # ProfileConfig.open() leaves the file permissions of existing
        # configuration databases.
        config_file = os.path.join(tmp_path, "config")
        open(config_file, "wb").close()  # touch.
        os.chmod(config_file, 0o644)  # u=rw,go=r
        with api.ProfileConfig.open(config_file):
            perms = FilePath(config_file).getPermissions()
            assert "rw-r--r--" == perms.shorthand()
