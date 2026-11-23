# Copyright 2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maascli.configfile`."""

import pytest
import yaml

from maascli.configfile import MAASConfiguration
from maastesting.factory import factory


class TestMAASConfiguration:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.config_dir = tmp_path
        self.environ = {"SNAP_DATA": self.config_dir}
        self.config_manager = MAASConfiguration(environ=self.environ)

    def write_config(self, config, filename):
        config_file = self.config_dir / filename
        config_file.write_text(yaml.safe_dump(config))

    def read_config(self, filename):
        config_file = self.config_dir / filename
        if not config_file.exists():
            return None
        return yaml.safe_load(config_file.read_text())

    def test_get_not_in_snap(self):
        config_manager = MAASConfiguration(environ={})
        # use mocked dir instead of /etc/maas
        config_manager.DEFAULT_CONFIG_DIR = self.config_dir
        config = {
            factory.make_name("key"): factory.make_name("value"),
            factory.make_name("key"): factory.make_name("value"),
        }
        self.write_config(config, "regiond.conf")
        assert config_manager.get() == config

    def test_get(self):
        config = {
            factory.make_name("key"): factory.make_name("value"),
            factory.make_name("key"): factory.make_name("value"),
        }
        self.write_config(config, "regiond.conf")
        assert self.config_manager.get() == config

    def test_get_empty(self):
        assert self.config_manager.get() == {}

    def test_write_to_file(self):
        config = {
            factory.make_name("key"): factory.make_name("value"),
            factory.make_name("key"): factory.make_name("value"),
        }
        filename = factory.make_name("file")
        self.config_manager.write_to_file(config, filename)
        assert self.read_config(filename) == config

    def test_update_updates(self):
        config1 = {"foo": "bar"}
        config2 = {"foo": "baz"}
        self.config_manager.update(config1)
        self.config_manager.update(config2)
        assert self.read_config("regiond.conf") == config2

    def test_update_from_empty_file(self):
        config = {factory.make_name("key"): factory.make_name("value")}
        (self.config_dir / "regiond.conf").touch()
        self.config_manager.update(config)
        assert self.read_config("regiond.conf") == config

    def test_update_sets(self):
        config = {
            factory.make_name("key"): factory.make_name("value"),
            factory.make_name("key"): factory.make_name("value"),
        }
        self.config_manager.update(config)
        assert self.read_config("regiond.conf") == config
        # no rackd config is written
        assert self.read_config("rackd.conf") is None

    def test_update_extends(self):
        config1 = {"foo": "bar"}
        config2 = {"baz": "bza"}
        self.config_manager.update(config1)
        self.config_manager.update(config2)
        full_config = {}
        full_config.update(config1)
        full_config.update(config2)
        assert self.read_config("regiond.conf") == full_config

    def test_update_removes_empty(self):
        config = {"foo": "bar", "baz": "bza"}
        self.config_manager.update(config)
        self.config_manager.update({"foo": None})
        assert self.read_config("regiond.conf") == {"baz": "bza"}

    def test_update_with_maas_url(self):
        url = factory.make_name("url")
        self.config_manager.update({"maas_url": url})
        expected = {"maas_url": url}
        assert self.read_config("regiond.conf") == expected
        # MAAS url is set in rackd config as well
        assert self.read_config("rackd.conf") == expected

    def test_update_with_debug(self):
        self.config_manager.update({"debug": True})
        expected = {"debug": True}
        assert self.read_config("regiond.conf") == expected
        # Debug is set in rackd config as well
        assert self.read_config("rackd.conf") == expected

    def test_unset_maas_url(self):
        config = {"maas_url": factory.make_name("url")}
        self.write_config(config, "regiond.conf")
        self.write_config(config, "rackd.conf")
        self.config_manager.update({"maas_url": None})
        assert self.read_config("regiond.conf") == {}
        assert self.read_config("rackd.conf") == {}

    def test_update_with_temporal_server(self):
        self.config_manager.update({"temporal_server": "127.0.0.1"})
        # temporal_server is rack-only; it must not be written to regiond.conf
        assert self.read_config("regiond.conf") == {}
        assert self.read_config("rackd.conf") == {
            "temporal_server": "127.0.0.1"
        }
