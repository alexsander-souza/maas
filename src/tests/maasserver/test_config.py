# Copyright 2015-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maasserver.config`."""

import random

import formencode.api
import pytest

from maasserver.config import get_temporal_connect_address, RegionConfiguration
from maastesting.factory import factory


class TestRegionConfiguration:
    """Tests for `RegionConfiguration`."""

    def test_default_maas_url(self):
        config = RegionConfiguration({})
        assert config.maas_url == "http://localhost:5240/MAAS"

    def test_default_database_conn_max_age(self):
        config = RegionConfiguration({})
        assert config.database_conn_max_age == 60 * 5

    def test_set_and_get_maas_url(self):
        config = RegionConfiguration({})
        example_url = factory.make_simple_http_url()
        config.maas_url = example_url
        assert config.maas_url == example_url
        # It's also stored in the configuration database.
        assert config.store == {"maas_url": example_url}

    def test_set_maas_url_accepts_hostnames(self):
        config = RegionConfiguration({})
        example_url = factory.make_simple_http_url()
        config.maas_url = example_url
        assert config.maas_url == example_url
        assert config.store == {"maas_url": example_url}

    def test_set_maas_url_accepts_very_short_hostnames(self):
        config = RegionConfiguration({})
        example_url = factory.make_simple_http_url(
            netloc=factory.make_string(size=1)
        )
        config.maas_url = example_url
        assert config.maas_url == example_url
        assert config.store == {"maas_url": example_url}

    def test_set_maas_url_rejects_bare_ipv6_addresses(self):
        config = RegionConfiguration({})
        example_url = factory.make_simple_http_url(
            netloc=factory.make_ipv6_address()
        )
        with pytest.raises(
            formencode.api.Invalid, match="^That is not a valid URL$"
        ):
            config.maas_url = example_url

    def test_set_maas_url_accepts_ipv6_addresses_with_brackets(self):
        config = RegionConfiguration({})
        example_url = factory.make_simple_http_url(
            netloc="[%s]" % factory.make_ipv6_address()
        )
        config.maas_url = example_url
        assert config.maas_url == example_url
        assert config.store == {"maas_url": example_url}


class TestRegionConfigurationDatabaseOptions:
    """Tests for the database options in `RegionConfiguration`."""

    options_and_defaults = {
        "database_host": "localhost",
        "database_port": 5432,
        "database_name": "maasdb",
        "database_user": "maas",
        "database_pass": "",
        "database_sslmode": "prefer",
        "database_conn_max_age": 5 * 60,
        "database_keepalive": True,
        "database_keepalive_idle": 15,
        "database_keepalive_interval": 15,
        "database_keepalive_count": 2,
    }

    scenarios = tuple(
        (name, {"option": name, "default": default})
        for name, default in options_and_defaults.items()
    )

    def test_default(self):
        config = RegionConfiguration({})
        assert getattr(config, self.option) == self.default

    def test_set_and_get(self):
        config = RegionConfiguration({})
        if isinstance(getattr(config, self.option), str):
            example_value = factory.make_name(self.option)
        elif self.option == "database_keepalive":
            example_value = random.choice([True, False])
        else:
            example_value = factory.pick_port()
        # Argument values will most often be passed in from the command-line,
        # so convert to a string before use to reflect that usage.
        setattr(config, self.option, str(example_value))
        assert getattr(config, self.option) == example_value
        # It's also stored in the configuration database.
        expected_value = example_value
        if example_value == "true":
            expected_value = True
        elif expected_value == "false":
            expected_value = False
        assert config.store == {self.option: expected_value}


class TestRegionConfigurationWorkerOptions:
    """Tests for the worker options in `RegionConfiguration`."""

    def test_default(self):
        config = RegionConfiguration({})
        assert config.num_workers == 4

    def test_set_and_get(self):
        config = RegionConfiguration({})
        workers = random.randint(8, 12)
        config.num_workers = workers
        assert config.num_workers == workers
        # It's also stored in the configuration database.
        assert config.store == {"num_workers": workers}


class TestRegionConfigurationDebugOptions:
    """Tests for the debug options in `RegionConfiguration`."""

    options_and_defaults = {"debug": False, "debug_queries": False}

    scenarios = tuple(
        (name, {"option": name, "default": default})
        for name, default in options_and_defaults.items()
    )

    def test_default(self):
        config = RegionConfiguration({})
        assert getattr(config, self.option) == self.default

    def test_set_and_get(self):
        config = RegionConfiguration({})
        example_value = random.choice(["true", "yes", "True"])
        # Argument values will most often be passed in from the command-line,
        # so convert to a string before use to reflect that usage.
        setattr(config, self.option, example_value)
        assert getattr(config, self.option)
        # It's also stored in the configuration database.
        assert config.store == {self.option: True}


class TestRegionConfigurationUseJSONLogging:
    options_and_defaults = {"use_json_logging": True}

    scenarios = tuple(
        (name, {"option": name, "default": default})
        for name, default in options_and_defaults.items()
    )

    def test_default(self):
        config = RegionConfiguration({})
        assert getattr(config, self.option) == self.default

    def test_set_and_get(self):
        config = RegionConfiguration({})
        example_value = random.choice(["false", "no", "False"])
        # Argument values will most often be passed in from the command-line,
        # so convert to a string before use to reflect that usage.
        setattr(config, self.option, example_value)
        assert not getattr(config, self.option)
        # It's also stored in the configuration database.
        assert config.store == {self.option: False}


class TestGetTemporalConnectAddress:
    """Tests for `get_temporal_connect_address`."""

    def _patch_region_config(self, mocker, *, temporal_bind, maas_url):
        mock_open = mocker.patch.object(RegionConfiguration, "open")
        ctx = mock_open.return_value.__enter__.return_value
        ctx.temporal_bind = temporal_bind
        ctx.maas_url = maas_url
        return ctx

    def test_explicit_bind_returned_unchanged(self, mocker):
        self._patch_region_config(
            mocker,
            temporal_bind="10.0.0.1",
            maas_url="http://10.0.0.1:5240/MAAS",
        )
        mocker.patch(
            "maasserver.config.is_hardening_enabled", return_value=True
        )
        assert get_temporal_connect_address() == "10.0.0.1"

    def test_unset_wildcard_bind_maps_to_loopback(self, mocker):
        self._patch_region_config(
            mocker, temporal_bind="", maas_url="http://unreachable:5240/MAAS"
        )
        mocker.patch(
            "maasserver.config.is_hardening_enabled", return_value=False
        )
        mocker.patch(
            "provisioningserver.utils.network.get_source_address_for_url",
            return_value=None,
        )
        assert get_temporal_connect_address() == "127.0.0.1"
