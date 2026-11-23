# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the `local_config_{get,reset,set}` management commands."""

from functools import partial
import json
import random

from django.core.management import call_command
from django.core.management.base import CommandError
import pytest
import yaml

from maasserver.config import RegionConfiguration
from maasserver.management.commands import _config as config
from maasserver.testing.config import RegionConfigurationFixture
from maasserver.testing.factory import factory
from maastesting.fixtures import CaptureStandardIO
from provisioningserver.config import ConfigurationOption


def call_nnn(command, **options):
    """Call `command`, return captures standard IO.

    See `call_command`.

    :return: :class:`CaptureStandardIO` instance.
    """
    with CaptureStandardIO() as stdio:
        call_command(command, **options)
    return stdio


call_get = partial(call_nnn, "local_config_get")
call_reset = partial(call_nnn, "local_config_reset")
call_set = partial(call_nnn, "local_config_set")


@pytest.mark.parametrize(
    "option",
    [
        option.lstrip("-").replace("-", "_")
        for option, args in config.gen_configuration_options_for_getting()
    ],
)
class TestConfigurationGet:
    def test_dumps_yaml_to_stdout_by_default(self, option):
        stdio = call_get(**{option: True})
        settings = yaml.safe_load(stdio.getOutput())
        assert option in settings

    def test_dumps_yaml_to_stdout(self, option):
        stdio = call_get(**{option: True, "dump": config.dump_yaml})
        settings = yaml.safe_load(stdio.getOutput())
        assert option in settings

    def test_dumps_json_to_stdout(self, option):
        stdio = call_get(**{option: True, "dump": config.dump_json})
        settings = json.loads(stdio.getOutput())
        assert option in settings

    def test_dumps_plain_string_to_stdout(self, option):
        stdio = call_get(**{option: True, "dump": config.dump_plain})
        settings = stdio.getOutput()
        assert option not in settings
        with RegionConfiguration.open() as configuration:
            assert str(getattr(configuration, option)) in settings


@pytest.mark.parametrize(
    "option",
    [
        option.lstrip("-").replace("-", "_")
        for option, args in config.gen_configuration_options_for_resetting()
    ],
)
class TestConfigurationReset:
    def test_options_are_reset(self, option):
        with RegionConfigurationFixture():
            with RegionConfiguration.open_for_update() as configuration:
                # Give the option a random value.
                current = getattr(configuration, option)
                if isinstance(current, list):
                    value = [factory.make_ipv4_address()]
                elif isinstance(current, str):
                    value = factory.make_name("foobar")
                else:
                    value = factory.pick_port()
                setattr(configuration, option, value)
            stdio = call_reset(**{option: True})
            # Nothing is echoed back to the user.
            assert stdio.getOutput() == ""
            assert stdio.getError() == ""
            # There is no custom value in the configuration file.
            with open(RegionConfiguration.DEFAULT_FILENAME, "rb") as fd:
                settings = yaml.safe_load(fd)
            assert settings == {}


@pytest.mark.parametrize(
    "option",
    [
        option.lstrip("-").replace("-", "_")
        for option, args in config.gen_configuration_options_for_setting()
    ],
)
class TestConfigurationSet:
    def test_options_are_saved(self, option):
        with RegionConfigurationFixture():
            # Set the option to a random value.
            if option == "database_port":
                value = factory.pick_port()
            elif option in (
                "database_conn_max_age",
                "database_keepalive_count",
                "database_keepalive_interval",
                "database_keepalive_idle",
                "api_conn_limit",
                "api_rate_limit_burst",
                "dns_fetches_per_zone",
                "dns_fetches_per_server",
            ):
                value = random.randint(1, 60)
            elif option == "num_workers":
                value = random.randint(1, 16)
            elif option in [
                "debug",
                "debug_queries",
                "debug_http",
                "database_keepalive",
                "use_json_logging",
            ]:
                value = random.choice([True, False])
            else:
                value = factory.make_name("foobar")

            # Values are coming from the command-line so stringify.
            stdio = call_set(**{option: str(value)})

            # Nothing is echoed back to the user.
            assert stdio.getOutput() == ""
            assert stdio.getError() == ""

            # Some validators alter the given option, like adding an HTTP scheme
            # to a "bare" URL, so we merely check that the value contains the
            # given value, not that it exactly matches. Values are converted to a
            # str so Contains works with int values.
            with RegionConfiguration.open() as configuration:
                assert str(value) in str(getattr(configuration, option))


class TestConfigurationSet_DatabasePort:
    """Tests for setting the database port.

    Setting the port is slightly special because the other options are mostly
    (at the time of writing) defined using `UnicodeString` validators, roughly
    meaning that anything goes, but the port is defined with `Int`.
    """

    def test_exception_when_port_is_not_an_integer(self):
        with RegionConfigurationFixture():
            exc = pytest.raises(CommandError, call_set, database_port="foo")
            assert str(exc.value) == (
                "database-port: Please enter an integer value."
            )

    def test_exception_when_port_is_too_low(self):
        with RegionConfigurationFixture():
            exc = pytest.raises(CommandError, call_set, database_port=0)
            assert str(exc.value) == (
                "database-port: Please enter a number that is 1 or greater."
            )

    def test_exception_when_port_is_too_high(self):
        with RegionConfigurationFixture():
            exc = pytest.raises(CommandError, call_set, database_port=2**16)
            assert str(exc.value) == (
                "database-port: Please enter a number that is 65535 or smaller."
            )


class TestConfigurationCommon:
    def test_gen_configuration_options(self):
        for name, option in config.gen_configuration_options():
            assert isinstance(name, (str, bytes))
            assert isinstance(option, (ConfigurationOption, property))

    def test_gen_mutable_configuration_options(self):
        for name, option in config.gen_mutable_configuration_options():
            assert isinstance(name, (str, bytes))
            assert isinstance(option, ConfigurationOption)

    def test_gen_configuration_options_for_getting(self):
        for name, option in config.gen_configuration_options_for_getting():
            assert "_" not in name
            assert isinstance(option, dict)

    def test_gen_configuration_options_for_resetting(self):
        for name, option in config.gen_configuration_options_for_resetting():
            assert "_" not in name
            assert isinstance(option, dict)

    def test_gen_configuration_options_for_setting(self):
        for name, option in config.gen_configuration_options_for_setting():
            assert "_" not in name
            assert isinstance(option, dict)
