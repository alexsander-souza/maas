# Copyright 2012-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for provisioning configuration."""

import contextlib
from operator import delitem, methodcaller, setitem
import os.path
import sqlite3
from unittest.mock import sentinel

import formencode
import formencode.validators
import pytest
from twisted.python.filepath import FilePath
import yaml

from maastesting.factory import factory
from maastesting.fixtures import ImportErrorFixture
from provisioningserver import config as config_module
from provisioningserver.config import (
    ClusterConfiguration,
    Configuration,
    ConfigurationDatabase,
    ConfigurationFile,
    ConfigurationImmutable,
    ConfigurationMeta,
    ConfigurationOption,
    debug_enabled,
    is_dev_environment,
)
from provisioningserver.path import get_data_path
from provisioningserver.testing.config import ClusterConfigurationFixture
from provisioningserver.utils.fs import RunLock

###############################################################################
# New configuration API follows.
###############################################################################


class ExampleConfigurationMeta(ConfigurationMeta):
    envvar = "MAAS_TESTING_SETTINGS"
    default = get_data_path("example.db")
    backend = None  # Define this in sub-classes.


class ExampleConfiguration(Configuration, metaclass=ExampleConfigurationMeta):
    """An example configuration object.

    It derives from :class:`ConfigurationBase` and has a metaclass derived
    from :class:`ConfigurationMeta`, just as a "real" configuration object
    must.
    """

    something = ConfigurationOption(
        "something",
        "Something alright, don't know what, just something.",
        formencode.validators.IPAddress(if_missing=sentinel.missing),
    )


class ExampleConfigurationForDatabase(ExampleConfiguration):
    """An example configuration object using an SQLite3 database."""

    backend = ConfigurationDatabase


class ExampleConfigurationForFile(ExampleConfiguration):
    """An example configuration object using a file."""

    backend = ConfigurationFile


@pytest.mark.parametrize(
    "example_configuration",
    [
        ExampleConfigurationForDatabase,
        ExampleConfigurationForFile,
    ],
    ids=["db", "file"],
)
class TestConfigurationMeta:
    """Tests for `ConfigurationMeta`."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        self.monkeypatch = monkeypatch

    def set_envvar(self, example_configuration, filepath=None):
        """Set the env. variable named by `ExampleConfiguration.envvar"."""
        if filepath is None:
            self.monkeypatch.delenv(
                example_configuration.envvar, raising=False
            )
        else:
            self.monkeypatch.setenv(example_configuration.envvar, filepath)

    def test_gets_filename_from_environment(self, example_configuration):
        dummy_filename = factory.make_name("config")
        self.set_envvar(example_configuration, dummy_filename)
        assert dummy_filename == example_configuration.DEFAULT_FILENAME

    def test_falls_back_to_default(self, example_configuration):
        self.set_envvar(example_configuration, None)
        assert (
            get_data_path(example_configuration.default)
            == example_configuration.DEFAULT_FILENAME
        )

    def test_set(self, example_configuration):
        dummy_filename = factory.make_name("config")
        example_configuration.DEFAULT_FILENAME = dummy_filename
        assert dummy_filename == example_configuration.DEFAULT_FILENAME

    def test_delete(self, example_configuration):
        self.set_envvar(example_configuration, None)
        example_file = factory.make_name("config")
        example_configuration.DEFAULT_FILENAME = example_file
        del example_configuration.DEFAULT_FILENAME
        assert (
            get_data_path(example_configuration.default)
            == example_configuration.DEFAULT_FILENAME
        )
        # The delete does not fail when called multiple times.
        del example_configuration.DEFAULT_FILENAME


class TestConfiguration:
    """Tests for `Configuration`.

    The most interesting tests that exercise `Configuration` are actually in
    `TestConfigurationOption`.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, mocker):
        self.tmp_path = tmp_path
        self.mocker = mocker

    def _make_file(self):
        """Create a temporary file and return its path."""
        make_dir = os.path.join(str(self.tmp_path), factory.make_name("dir"))
        os.makedirs(make_dir, exist_ok=True)
        return factory.make_file(make_dir)

    def test_create(self):
        config = Configuration({})
        assert {} == config.store

    def test_cannot_set_attributes(self):
        config = Configuration({})
        with pytest.raises(
            AttributeError,
            match="^'Configuration' object has no attribute 'foo'$",
        ):
            config.foo = "bar"

    def test_open_uses_backend_as_context_manager(self):
        config_file = self._make_file()
        backend = self.mocker.patch.object(ExampleConfiguration, "backend")
        with ExampleConfiguration.open(config_file) as config:
            # The backend was opened using open() too.
            backend.open.assert_called_once_with(config_file)
            # The object returned from backend.open() has been used as the
            # context manager, providing `config`.
            backend_ctx = backend.open.return_value
            assert config.store is backend_ctx.__enter__.return_value
            # We're within the context, as expected.
            backend_ctx.__exit__.assert_not_called()
        # The backend context has also been exited.
        backend_ctx.__exit__.assert_called_once_with(None, None, None)

    def test_open_for_update_uses_backend_as_context_manager(self):
        config_file = self._make_file()
        backend = self.mocker.patch.object(ExampleConfiguration, "backend")
        with ExampleConfiguration.open_for_update(config_file) as config:
            # The backend was opened using open_for_update() too.
            backend.open_for_update.assert_called_once_with(config_file)
            # The object returned from backend.open_for_update() has been used
            # as the context manager, providing `config`.
            backend_ctx = backend.open_for_update.return_value
            assert config.store is backend_ctx.__enter__.return_value
            # We're within the context, as expected.
            backend_ctx.__exit__.assert_not_called()
        # The backend context has also been exited.
        backend_ctx.__exit__.assert_called_once_with(None, None, None)


@pytest.mark.parametrize(
    "make_store",
    [
        methodcaller("make_database_store"),
        methodcaller("make_file_store"),
    ],
    ids=["db", "file"],
)
class TestConfigurationOption:
    """Tests for `ConfigurationOption`."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.tmp_path = tmp_path

    def _make_dir(self):
        path = os.path.join(str(self.tmp_path), factory.make_name("dir"))
        os.makedirs(path, exist_ok=True)
        return path

    def make_database_store(self):
        database = sqlite3.connect(":memory:")
        return ConfigurationDatabase(database, mutable=True)

    def make_file_store(self):
        return ConfigurationFile(
            factory.make_file(self._make_dir()), mutable=True
        )

    def make_config(self, make_store):
        store = make_store(self)
        return ExampleConfiguration(store)

    def test_getting_something(self, make_store):
        config = self.make_config(make_store)
        assert sentinel.missing is config.something

    def test_getting_something_is_not_validated(self, make_store):
        # The value in the database is trusted.
        config = self.make_config(make_store)
        example_value = factory.make_name("not-an-ip-address")
        config.store[config.__class__.something.name] = example_value
        assert example_value == config.something

    def test_setting_something(self, make_store):
        config = self.make_config(make_store)
        example_value = factory.make_ipv4_address()
        config.something = example_value
        assert example_value == config.something

    def test_setting_something_is_validated(self, make_store):
        config = self.make_config(make_store)
        with pytest.raises(
            formencode.validators.Invalid,
            match="^Please enter a valid IP address",
        ):
            config.something = factory.make_name("not-an-ip-address")

    def test_deleting_something(self, make_store):
        config = self.make_config(make_store)
        config.something = factory.make_ipv4_address()
        del config.something
        assert sentinel.missing is config.something


class TestConfigurationDatabase:
    """Tests for `ConfigurationDatabase`."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.tmp_path = tmp_path

    def _make_dir(self):
        path = os.path.join(str(self.tmp_path), factory.make_name("dir"))
        os.makedirs(path, exist_ok=True)
        return path

    def test_init(self):
        database = sqlite3.connect(":memory:")
        config = ConfigurationDatabase(database)
        with config.cursor() as cursor:
            # The "configuration" table has been created.
            assert (1,) == cursor.execute(
                "SELECT COUNT(*) FROM sqlite_master"
                " WHERE type = 'table'"
                "   AND name = 'configuration'"
            ).fetchone()

    def test_configuration_pristine(self):
        # A pristine configuration has no entries.
        database = sqlite3.connect(":memory:")
        config = ConfigurationDatabase(database)
        assert set() == set(config)

    def test_adding_configuration_option(self):
        database = sqlite3.connect(":memory:")
        config = ConfigurationDatabase(database, mutable=True)
        config["alice"] = {"abc": 123}
        assert {"alice"} == set(config)
        assert {"abc": 123} == config["alice"]

    def test_replacing_configuration_option(self):
        database = sqlite3.connect(":memory:")
        config = ConfigurationDatabase(database, mutable=True)
        config["alice"] = {"abc": 123}
        config["alice"] = {"def": 456}
        assert {"alice"} == set(config)
        assert {"def": 456} == config["alice"]

    def test_getting_configuration_option(self):
        database = sqlite3.connect(":memory:")
        config = ConfigurationDatabase(database, mutable=True)
        config["alice"] = {"abc": 123}
        assert {"abc": 123} == config["alice"]

    def test_getting_non_existent_configuration_option(self):
        database = sqlite3.connect(":memory:")
        config = ConfigurationDatabase(database)
        with pytest.raises(KeyError):
            config["alice"]

    def test_removing_configuration_option(self):
        database = sqlite3.connect(":memory:")
        config = ConfigurationDatabase(database, mutable=True)
        config["alice"] = {"abc": 123}
        del config["alice"]
        assert set() == set(config)

    def test_open_and_close(self):
        # ConfigurationDatabase.open() returns a context manager that closes
        # the database on exit.
        config_file = os.path.join(self._make_dir(), "config")
        config = ConfigurationDatabase.open_for_update(config_file)
        assert isinstance(config, contextlib._GeneratorContextManager)
        with config as config:
            assert isinstance(config, ConfigurationDatabase)
            with config.cursor() as cursor:
                assert (1,) == cursor.execute("SELECT 1").fetchone()
        with pytest.raises(sqlite3.ProgrammingError):
            config.cursor()

    def test_open_permissions_new_database(self):
        # ConfigurationDatabase.open() applies restrictive file permissions to
        # newly created configuration databases.
        config_file = os.path.join(self._make_dir(), "config")
        with ConfigurationDatabase.open(config_file):
            perms = FilePath(config_file).getPermissions()
            assert "rw-r-----" == perms.shorthand()

    def test_open_permissions_existing_database(self):
        # ConfigurationDatabase.open() leaves the file permissions of existing
        # configuration databases.
        config_file = os.path.join(self._make_dir(), "config")
        open(config_file, "wb").close()  # touch.
        os.chmod(config_file, 0o644)  # u=rw,go=r
        with ConfigurationDatabase.open(config_file):
            perms = FilePath(config_file).getPermissions()
            assert "rw-r--r--" == perms.shorthand()

    def test_opened_database_commits_on_exit(self):
        config_file = os.path.join(self._make_dir(), "config")
        config_key = factory.make_name("key")
        config_value = factory.make_name("value")
        with ConfigurationDatabase.open_for_update(config_file) as config:
            config[config_key] = config_value
        with ConfigurationDatabase.open(config_file) as config:
            assert config_value == config[config_key]

    def test_opened_database_rolls_back_on_unclean_exit(self):
        config_file = os.path.join(self._make_dir(), "config")
        config_key = factory.make_name("key")
        config_value = factory.make_name("value")
        exception_type = factory.make_exception_type()
        # Set a configuration option, then crash.
        with pytest.raises(exception_type, match="^$"):
            with ConfigurationDatabase.open_for_update(config_file) as config:
                config[config_key] = config_value
                raise exception_type()
        # No value has been saved for `config_key`.
        with ConfigurationDatabase.open(config_file) as config:
            with pytest.raises(KeyError):
                config[config_key]

    def test_as_string(self):
        database = sqlite3.connect(":memory:")
        config = ConfigurationDatabase(database)
        assert "ConfigurationDatabase(main=:memory:)" == str(config)


class TestConfigurationDatabaseMutability:
    """Tests for `ConfigurationDatabase` mutability."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.tmp_path = tmp_path

    def _make_dir(self):
        path = os.path.join(str(self.tmp_path), factory.make_name("dir"))
        os.makedirs(path, exist_ok=True)
        return path

    def test_immutable(self):
        database = sqlite3.connect(":memory:")
        config = ConfigurationDatabase(database, mutable=False)
        with pytest.raises(ConfigurationImmutable):
            setitem(config, "alice", 1)
        with pytest.raises(ConfigurationImmutable):
            delitem(config, "alice")

    def test_mutable(self):
        database = sqlite3.connect(":memory:")
        config = ConfigurationDatabase(database, mutable=True)
        config["alice"] = 1234
        del config["alice"]

    def test_open_yields_immutable_backend(self):
        config_file = os.path.join(self._make_dir(), "config")
        config_key = factory.make_name("key")
        with ConfigurationDatabase.open(config_file) as config:
            with pytest.raises(
                ConfigurationImmutable,
                match=f"Cannot set `{config_key}'",
            ):
                config[config_key] = factory.make_name("value")
            with pytest.raises(
                ConfigurationImmutable,
                match=f"Cannot set `{config_key}'",
            ):
                del config[config_key]

    def test_open_for_update_yields_mutable_backend(self):
        config_file = os.path.join(self._make_dir(), "config")
        config_key = factory.make_name("key")
        with ConfigurationDatabase.open_for_update(config_file) as config:
            config[config_key] = factory.make_name("value")
            del config[config_key]


class TestConfigurationFile:
    """Tests for `ConfigurationFile`."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.tmp_path = tmp_path

    def _make_dir(self):
        path = os.path.join(str(self.tmp_path), factory.make_name("dir"))
        os.makedirs(path, exist_ok=True)
        return path

    def test_configuration_pristine(self):
        # A pristine configuration has no entries.
        config = ConfigurationFile(sentinel.filename)
        assert {} == config.config
        assert not config.dirty
        assert sentinel.filename == config.path

    def test_adding_configuration_option(self):
        config = ConfigurationFile(sentinel.filename, mutable=True)
        config["alice"] = {"abc": 123}
        assert {"alice"} == set(config)
        assert {"abc": 123} == config["alice"]
        assert config.dirty

    def test_replacing_configuration_option(self):
        config = ConfigurationFile(sentinel.filename, mutable=True)
        config["alice"] = {"abc": 123}
        config["alice"] = {"def": 456}
        assert {"alice"} == set(config)
        assert {"def": 456} == config["alice"]
        assert config.dirty

    def test_getting_configuration_option(self):
        config = ConfigurationFile(sentinel.filename, mutable=True)
        config["alice"] = {"abc": 123}
        assert {"abc": 123} == config["alice"]

    def test_getting_non_existent_configuration_option(self):
        config = ConfigurationFile(sentinel.filename)
        with pytest.raises(KeyError):
            config["alice"]

    def test_removing_configuration_option(self):
        config = ConfigurationFile(sentinel.filename, mutable=True)
        config["alice"] = {"abc": 123}
        del config["alice"]
        assert set() == set(config)
        assert config.dirty

    def test_load_non_existent_file_crashes(self):
        config_file = os.path.join(self._make_dir(), "config")
        config = ConfigurationFile(config_file)
        with pytest.raises(IOError):
            config.load()

    def test_load_empty_file_results_in_empty_config(self):
        config_file = os.path.join(self._make_dir(), "config")
        with open(config_file, "w"):
            pass  # Write nothing to the file.
        config = ConfigurationFile(config_file)
        config.load()
        assert set(config) == set()

    def test_load_file_with_non_mapping_crashes(self):
        config_file = os.path.join(self._make_dir(), "config")
        with open(config_file, "w") as fd:
            yaml.safe_dump([1, 2, 3], stream=fd)
        config = ConfigurationFile(config_file)
        with pytest.raises(ValueError) as exc_info:
            config.load()
        assert (
            f"Configuration in {config_file} is not a mapping: [1, 2, 3]"
            == str(exc_info.value)
        )

    def test_open_and_close(self):
        # ConfigurationFile.open() returns a context manager.
        config_file = os.path.join(self._make_dir(), "config")
        config_ctx = ConfigurationFile.open(config_file)
        assert isinstance(config_ctx, contextlib._GeneratorContextManager)
        with config_ctx as config:
            assert isinstance(config, ConfigurationFile)
            assert os.path.isfile(config_file)
            assert {} == config.config
            assert not config.dirty
        with open(config_file, "r") as fh:
            assert "" == fh.read()

    def test_open_permissions_new_database(self):
        # ConfigurationFile.open() applies restrictive file permissions to
        # newly created configuration databases.
        config_file = os.path.join(self._make_dir(), "config")
        with ConfigurationFile.open(config_file):
            perms = FilePath(config_file).getPermissions()
            assert "rw-r-----" == perms.shorthand()

    def test_unmodified_database_retains_permissions(self):
        # ConfigurationFile.open() leaves the file permissions of existing
        # configuration databases if they're not modified.
        config_file = os.path.join(self._make_dir(), "config")
        open(config_file, "wb").close()  # touch.
        os.chmod(config_file, 0o644)  # u=rw,go=r
        with ConfigurationFile.open_for_update(config_file):
            perms = FilePath(config_file).getPermissions()
            assert "rw-r--r--" == perms.shorthand()
        perms = FilePath(config_file).getPermissions()
        assert "rw-r--r--" == perms.shorthand()

    def test_modified_database_retains_permissions(self):
        # ConfigurationFile.open() leaves the file permissions of existing
        # configuration databases if they're modified.
        config_file = os.path.join(self._make_dir(), "config")
        open(config_file, "wb").close()  # touch.
        os.chmod(config_file, 0o644)  # u=rw,go=r
        with ConfigurationFile.open_for_update(config_file) as config:
            perms = FilePath(config_file).getPermissions()
            assert "rw-r--r--" == perms.shorthand()
            config["foobar"] = "I am a modification"
        perms = FilePath(config_file).getPermissions()
        assert "rw-r--r--" == perms.shorthand()

    def test_modified_database_uses_safe_permissions_if_file_missing(self):
        # ConfigurationFile.open() uses a sensible u=rw,g=r file mode when
        # saving if the database file has been inexplicably removed. This is
        # the same mode as used when opening a new database.
        config_file = os.path.join(self._make_dir(), "config")
        open(config_file, "wb").close()  # touch.
        os.chmod(config_file, 0o644)  # u=rw,go=r
        with ConfigurationFile.open_for_update(config_file) as config:
            config["foobar"] = "I am a modification"
            os.unlink(config_file)
        perms = FilePath(config_file).getPermissions()
        assert "rw-r-----" == perms.shorthand()

    def test_opened_configuration_file_saves_on_exit(self):
        # ConfigurationFile.open() returns a context manager that will save an
        # updated configuration on a clean exit.
        config_file = os.path.join(self._make_dir(), "config")
        config_key = factory.make_name("key")
        config_value = factory.make_name("value")
        with ConfigurationFile.open_for_update(config_file) as config:
            config[config_key] = config_value
            assert {config_key: config_value} == config.config
            assert config.dirty
        with ConfigurationFile.open(config_file) as config:
            assert config_value == config[config_key]

    def test_opened_configuration_file_does_not_save_on_unclean_exit(self):
        config_file = os.path.join(self._make_dir(), "config")
        config_key = factory.make_name("key")
        config_value = factory.make_name("value")
        exception_type = factory.make_exception_type()
        # Set a configuration option, then crash.
        with pytest.raises(exception_type, match="foo"):
            with ConfigurationFile.open_for_update(config_file) as config:
                config[config_key] = config_value
                raise exception_type("foo")
        # No value has been saved for `config_key`.
        with ConfigurationFile.open(config_file) as config:
            with pytest.raises(KeyError):
                config[config_key]

    def test_open_takes_exclusive_lock(self):
        config_file = os.path.join(self._make_dir(), "config")
        config_lock = RunLock(config_file)
        assert not config_lock.is_locked()
        with ConfigurationFile.open_for_update(config_file):
            assert config_lock.is_locked()
        assert not config_lock.is_locked()

    def test_as_string(self):
        config_file = os.path.join(self._make_dir(), "config")
        config = ConfigurationFile(config_file)
        assert "ConfigurationFile(%r)" % config_file == str(config)


class TestConfigurationFileMutability:
    """Tests for `ConfigurationFile` mutability."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.tmp_path = tmp_path

    def _make_dir(self):
        path = os.path.join(str(self.tmp_path), factory.make_name("dir"))
        os.makedirs(path, exist_ok=True)
        return path

    def test_immutable(self):
        config_file = os.path.join(self._make_dir(), "config")
        config = ConfigurationFile(config_file, mutable=False)
        with pytest.raises(ConfigurationImmutable):
            setitem(config, "alice", 1)
        with pytest.raises(ConfigurationImmutable):
            delitem(config, "alice")

    def test_mutable(self):
        config_file = os.path.join(self._make_dir(), "config")
        config = ConfigurationFile(config_file, mutable=True)
        config["alice"] = 1234
        del config["alice"]

    def test_open_yields_immutable_backend(self):
        config_file = os.path.join(self._make_dir(), "config")
        config_key = factory.make_name("key")
        with ConfigurationFile.open(config_file) as config:
            with pytest.raises(ConfigurationImmutable, match=config_key):
                config[config_key] = factory.make_name("value")
            with pytest.raises(ConfigurationImmutable, match=config_key):
                del config[config_key]

    def test_open_for_update_yields_mutable_backend(self):
        config_file = os.path.join(self._make_dir(), "config")
        config_key = factory.make_name("key")
        with ConfigurationFile.open_for_update(config_file) as config:
            config[config_key] = factory.make_name("value")
            del config[config_key]


class TestClusterConfiguration:
    """Tests for `ClusterConfiguration`."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.tmp_path = tmp_path

    def _make_dir(self):
        path = os.path.join(str(self.tmp_path), factory.make_name("dir"))
        os.makedirs(path, exist_ok=True)
        return path

    def test_default_maas_url(self):
        config = ClusterConfiguration({})
        assert ["http://localhost:5240/MAAS"] == config.maas_url

    def test_set_and_get_maas_url(self):
        config = ClusterConfiguration({})
        example_url = factory.make_simple_http_url()
        config.maas_url = example_url
        assert [example_url] == config.maas_url
        # It's also stored in the configuration database.
        assert {"maas_url": [example_url]} == config.store

    def test_set_maas_url_accepts_hostnames(self):
        config = ClusterConfiguration({})
        example_url = factory.make_simple_http_url()
        config.maas_url = example_url
        assert [example_url] == config.maas_url
        assert {"maas_url": [example_url]} == config.store

    def test_set_maas_url_accepts_very_short_hostnames(self):
        config = ClusterConfiguration({})
        example_url = factory.make_simple_http_url(
            netloc=factory.make_string(size=1)
        )
        config.maas_url = example_url
        assert [example_url] == config.maas_url
        assert {"maas_url": [example_url]} == config.store

    def test_set_maas_url_rejects_bare_ipv6_addresses(self):
        config = ClusterConfiguration({})
        example_url = factory.make_simple_http_url(
            netloc=factory.make_ipv6_address()
        )
        with pytest.raises(formencode.api.Invalid, match="valid URL"):
            config.maas_url = example_url

    def test_set_maas_url_accepts_ipv6_addresses_with_brackets(self):
        config = ClusterConfiguration({})
        example_url = factory.make_simple_http_url(
            netloc="[%s]" % factory.make_ipv6_address()
        )
        config.maas_url = example_url
        assert [example_url] == config.maas_url
        assert {"maas_url": [example_url]} == config.store

    def test_default_tftp_port(self):
        config = ClusterConfiguration({})
        assert 69 == config.tftp_port

    def test_set_and_get_tftp_port(self):
        config = ClusterConfiguration({})
        example_port = factory.pick_port()
        config.tftp_port = example_port
        assert example_port == config.tftp_port
        # It's also stored in the configuration database.
        assert {"tftp_port": example_port} == config.store

    def test_default_tftp_root(self):
        config = ClusterConfiguration({})
        assert config.tftp_root.endswith("tftp_root")

    def test_set_and_get_tftp_root(self):
        config = ClusterConfiguration({})
        example_dir = self._make_dir()
        config.tftp_root = example_dir
        assert example_dir == config.tftp_root
        # It's also stored in the configuration database.
        assert {"tftp_root": example_dir} == config.store

    def test_default_debug(self):
        config = ClusterConfiguration({})
        assert not config.debug

    def test_set_and_get_debug_false(self):
        config = ClusterConfiguration({})
        config.debug = False
        assert not config.debug

    def test_set_and_get_debug_false_str(self):
        config = ClusterConfiguration({})
        config.debug = "false"
        assert not config.debug

    def test_set_and_get_debug_true(self):
        config = ClusterConfiguration({})
        config.debug = True
        assert config.debug

    def test_set_and_get_debug_true_str(self):
        config = ClusterConfiguration({})
        config.debug = "true"
        assert config.debug

    def test_default_use_json_logging(self):
        config = ClusterConfiguration({})
        assert config.use_json_logging

    def test_test_set_and_get_use_json_logging_false_str(self):
        config = ClusterConfiguration({})
        config.use_json_logging = "false"
        assert not config.debug

    def test_default_temporal_server(self):
        config = ClusterConfiguration({})
        assert "" == config.temporal_server

    def test_set_and_get_temporal_server(self):
        config = ClusterConfiguration({})
        config.temporal_server = "127.0.0.1"
        assert "127.0.0.1" == config.temporal_server


class TestClusterConfigurationGRUBRoot:
    """Tests for `ClusterConfiguration.grub_root`."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.tmp_path = tmp_path

    def _make_dir(self):
        path = os.path.join(str(self.tmp_path), factory.make_name("dir"))
        os.makedirs(path, exist_ok=True)
        return path

    def test_is_relative_to_tftp_root_without_trailing_slash(self):
        random_dir = self._make_dir().rstrip("/")
        with ClusterConfigurationFixture(tftp_root=random_dir):
            with ClusterConfiguration.open() as configuration:
                assert random_dir + "/grub" == configuration.grub_root

    def test_is_relative_to_tftp_root_with_trailing_slash(self):
        random_dir = self._make_dir().rstrip("/") + "/"
        with ClusterConfigurationFixture(tftp_root=random_dir):
            with ClusterConfiguration.open() as configuration:
                assert random_dir + "grub" == configuration.grub_root


class TestConfig:
    """Tests for `maasserver.config`."""

    def test_is_dev_environment_returns_false(self):
        with ImportErrorFixture("maastesting", "dev_root"):
            assert not is_dev_environment()

    def test_is_dev_environment_returns_true(self):
        assert is_dev_environment()


class TestDebugEnabled:
    """Tests for `debug_enabled`."""

    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        self.mocker = mocker
        # Make sure things aren't pulled from cache
        debug_enabled.cache_clear()

    def test_debug_enabled_false(self):
        # Verifies that the default state of debug is false.
        assert not debug_enabled()

    def test_debug_enabled(self):
        debug = factory.pick_bool()
        with ClusterConfigurationFixture(debug=debug):
            assert debug == debug_enabled()

    def test_debug_enabled_cached(self):
        debug = factory.pick_bool()
        with ClusterConfigurationFixture(debug=debug):
            # Prime cache
            debug_enabled()
            mock_open = self.mocker.patch.object(
                config_module.ClusterConfiguration, "open"
            )
            assert debug == debug_enabled()
            mock_open.assert_not_called()
