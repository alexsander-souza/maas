# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `provisioningserver.drivers`."""

import random
import re
from unittest.mock import sentinel

from jsonschema import validate, ValidationError
import pytest

from maastesting.factory import factory
from provisioningserver.drivers import (
    Architecture,
    ArchitectureRegistry,
    IP_EXTRACTOR_PATTERNS,
    make_setting_field,
    SETTING_PARAMETER_FIELD_SCHEMA,
    SETTING_SCOPE,
)
from provisioningserver.utils.testing import RegistryFixture


class TestIpExtractor:
    @pytest.mark.parametrize(
        "val,expected",
        [
            (
                "http://:555/path",
                {
                    "password": None,
                    "port": "555",
                    "path": "/path",
                    "query": None,
                    "address": "",
                    "user": None,
                    "schema": "http",
                },
            ),
            ("http://[localhost]/path", None),
            ("http://[127.0.0.1]/path", None),
            ("http://[127.0.0.1/path", None),
            ("http://127.0.0.1]/path", None),
            ("http://2001:db8::1/path", None),
            (
                "http://localhost:555/path",
                {
                    "password": None,
                    "port": "555",
                    "path": "/path",
                    "query": None,
                    "address": "localhost",
                    "user": None,
                    "schema": "http",
                },
            ),
            (
                "http://127.0.0.1:555/path",
                {
                    "password": None,
                    "port": "555",
                    "path": "/path",
                    "query": None,
                    "address": "127.0.0.1",
                    "user": None,
                    "schema": "http",
                },
            ),
            (
                "http://[::ffff:127.0.0.1]:555/path",
                {
                    "password": None,
                    "port": "555",
                    "path": "/path",
                    "query": None,
                    "address": "::ffff:127.0.0.1",
                    "user": None,
                    "schema": "http",
                },
            ),
            (
                "http://[2001:db8::1]:555/path",
                {
                    "password": None,
                    "port": "555",
                    "path": "/path",
                    "query": None,
                    "address": "2001:db8::1",
                    "user": None,
                    "schema": "http",
                },
            ),
            (
                "http://127.0.0.1",
                {
                    "password": None,
                    "port": None,
                    "path": None,
                    "query": None,
                    "address": "127.0.0.1",
                    "user": None,
                    "schema": "http",
                },
            ),
            (
                "http://localhost",
                {
                    "password": None,
                    "port": None,
                    "path": None,
                    "query": None,
                    "address": "localhost",
                    "user": None,
                    "schema": "http",
                },
            ),
            (
                "http://[2001:db8::1]",
                {
                    "password": None,
                    "port": None,
                    "path": None,
                    "query": None,
                    "address": "2001:db8::1",
                    "user": None,
                    "schema": "http",
                },
            ),
            (
                "http://127.0.0.1/path",
                {
                    "password": None,
                    "port": None,
                    "path": "/path",
                    "query": None,
                    "address": "127.0.0.1",
                    "user": None,
                    "schema": "http",
                },
            ),
            (
                "http://localhost/path",
                {
                    "password": None,
                    "port": None,
                    "path": "/path",
                    "query": None,
                    "address": "localhost",
                    "user": None,
                    "schema": "http",
                },
            ),
            (
                "http://[2001:db8::1]/path",
                {
                    "password": None,
                    "port": None,
                    "path": "/path",
                    "query": None,
                    "address": "2001:db8::1",
                    "user": None,
                    "schema": "http",
                },
            ),
            (
                "http://user:pass@127.0.0.1:555/path",
                {
                    "password": "pass",
                    "port": "555",
                    "path": "/path",
                    "query": None,
                    "address": "127.0.0.1",
                    "user": "user",
                    "schema": "http",
                },
            ),
            (
                "http://user:pass@[2001:db8::1]:555/path",
                {
                    "password": "pass",
                    "port": "555",
                    "path": "/path",
                    "query": None,
                    "address": "2001:db8::1",
                    "user": "user",
                    "schema": "http",
                },
            ),
            (
                "http://user:pass@127.0.0.1/path",
                {
                    "password": "pass",
                    "port": None,
                    "path": "/path",
                    "query": None,
                    "address": "127.0.0.1",
                    "user": "user",
                    "schema": "http",
                },
            ),
            (
                "http://user:pass@[2001:db8::1]/path",
                {
                    "password": "pass",
                    "port": None,
                    "path": "/path",
                    "query": None,
                    "address": "2001:db8::1",
                    "user": "user",
                    "schema": "http",
                },
            ),
        ],
        ids=[
            "no-name",
            "name-with-brackets",
            "ipv4-with-brackets",
            "ipv4-with-leading-bracket",
            "ipv4-with-trailing-bracket",
            "ipv6-no-brackets",
            "name",
            "ipv4",
            "ipv6-formatted-ipv4",
            "ipv6",
            "ipv4-no-slash",
            "name-no-slash",
            "ipv6-no-slash",
            "ipv4-no-port",
            "name-no-port",
            "ipv6-no-port",
            "user-pass-ipv4",
            "user-pass-ipv6",
            "user-pass-ipv4-no-port",
            "user-pass-ipv6-no-port",
        ],
    )
    def test_make_ip_extractor(self, val, expected):
        actual = re.match(IP_EXTRACTOR_PATTERNS.URL, val)
        if expected is None:
            assert actual is None
        else:
            assert actual.groupdict() == expected


class TestMakeSettingField:
    def test_returns_valid_schema(self):
        setting = make_setting_field(
            factory.make_name("name"), factory.make_name("label")
        )
        # doesn't raise ValidationError
        validate(setting, SETTING_PARAMETER_FIELD_SCHEMA)

    def test_returns_dict_with_required_fields(self):
        setting = make_setting_field(
            factory.make_name("name"), factory.make_name("label")
        )
        assert {
            "name",
            "label",
            "required",
            "field_type",
            "choices",
            "default",
            "scope",
        } < setting.keys()

    def test_defaults_field_type_to_string(self):
        setting = make_setting_field(
            factory.make_name("name"), factory.make_name("label")
        )
        assert "string" == setting["field_type"]

    def test_defaults_choices_to_empty_list(self):
        setting = make_setting_field(
            factory.make_name("name"), factory.make_name("label")
        )
        assert [] == setting["choices"]

    def test_defaults_default_to_empty_string(self):
        setting = make_setting_field(
            factory.make_name("name"), factory.make_name("label")
        )
        assert "" == setting["default"]

    def test_validates_choices(self):
        choices = ["invalid"]
        with pytest.raises(ValidationError):
            make_setting_field(
                factory.make_name("name"),
                factory.make_name("label"),
                field_type="choice",
                choices=choices,
            )

    def test_returns_dict_with_correct_values(self):
        name = factory.make_name("name")
        label = factory.make_name("label")
        field_type = random.choice(["string", "mac_address", "choice"])
        choices = [
            [factory.make_name("key"), factory.make_name("value")]
            for _ in range(3)
        ]
        default = factory.make_name("default")
        setting = make_setting_field(
            name,
            label,
            field_type=field_type,
            choices=choices,
            default=default,
            required=True,
            scope=SETTING_SCOPE.NODE,
        )
        assert {
            "name": name,
            "label": label,
            "field_type": field_type,
            "choices": choices,
            "default": default,
            "required": True,
            "scope": SETTING_SCOPE.NODE,
            "secret": False,
        } == setting


class TestRegistries:
    @pytest.fixture(autouse=True)
    def _setup(self):
        # Ensure the global registry is empty for each test run.
        self._fixture = RegistryFixture()
        self._fixture.setUp()
        yield
        self._fixture.cleanUp()

    def test_architecture_registry(self):
        assert [] == list(ArchitectureRegistry)
        ArchitectureRegistry.register_item("resource", sentinel.resource)
        assert sentinel.resource in (
            item for name, item in ArchitectureRegistry
        )

    def test_get_by_pxealias_returns_valid_arch(self):
        arch1 = Architecture(
            name="arch1",
            description="arch1",
            pxealiases=["archibald", "reginald"],
        )
        arch2 = Architecture(
            name="arch2", description="arch2", pxealiases=["fake", "foo"]
        )
        ArchitectureRegistry.register_item("arch1", arch1)
        ArchitectureRegistry.register_item("arch2", arch2)
        assert arch1 == ArchitectureRegistry.get_by_pxealias("archibald")

    def test_get_by_pxealias_returns_None_if_none_matching(self):
        arch1 = Architecture(
            name="arch1",
            description="arch1",
            pxealiases=["archibald", "reginald"],
        )
        arch2 = Architecture(name="arch2", description="arch2")
        ArchitectureRegistry.register_item("arch1", arch1)
        ArchitectureRegistry.register_item("arch2", arch2)
        assert ArchitectureRegistry.get_by_pxealias("stinkywinky") is None
