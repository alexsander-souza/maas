# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test AMP argument classes."""

import random

import attr
import netaddr
import pytest
from twisted.protocols import amp

from maastesting.factory import factory
from provisioningserver.rpc import arguments


class TestBytes(object):
    def test_round_trip(self):
        argument = arguments.Bytes()
        example = factory.make_bytes()
        encoded = argument.toString(example)
        assert isinstance(encoded, bytes)
        decoded = argument.fromString(encoded)
        assert example == decoded

    def test_error_when_input_is_not_a_byte_string(self):
        with pytest.raises(TypeError, match="^Not a byte string: <.*"):
            arguments.Bytes().toString(object())


class TestChoice(object):
    def test_round_trip(self):
        choices = {
            factory.make_name("name"): factory.make_bytes() for _ in range(10)
        }
        argument = arguments.Choice(choices)
        choice = random.choice(list(choices))
        encoded = argument.toString(choice)
        assert isinstance(encoded, bytes)
        decoded = argument.fromString(encoded)
        assert choice == decoded

    def test_error_when_input_is_not_in_choices(self):
        with pytest.raises(KeyError, match="^<object .*"):
            arguments.Choice({}).toString(object())

    def test_error_when_choices_is_not_mapping(self):
        with pytest.raises(TypeError, match=r"^Not a mapping: \[\]"):
            arguments.Choice([])

    def test_error_when_choices_values_are_not_byte_strings(self):
        with pytest.raises(TypeError, match="^Not byte strings: 'foo', 12345"):
            arguments.Choice({object(): 12345, object(): "foo"})


class TestStructureAsJSON(object):
    example = {
        "an": "example",
        "structure": 12.34,
        "with": None,
        "and": ["lists", "of", "things"],
        "and also": {"an": "embedded structure"},
    }

    def test_round_trip(self):
        argument = arguments.StructureAsJSON()
        encoded = argument.toString(self.example)
        assert isinstance(encoded, bytes)
        decoded = argument.fromString(encoded)
        assert self.example == decoded


@attr.s
class SampleAttrs:
    foo = attr.ib(converter=str)
    bar = attr.ib(converter=int)


class TestAttrsClassArgument(object):
    def test_round_trip(self):
        sample = SampleAttrs(foo="foo", bar=10)
        argument = arguments.AttrsClassArgument(
            "tests.provisioningserver.rpc.test_arguments.SampleAttrs"
        )
        encoded = argument.toString(sample)
        assert isinstance(encoded, bytes)
        decoded = argument.fromString(encoded)
        assert decoded == sample


class TestParsedURL(object):
    def test_round_trip(self):
        argument = arguments.ParsedURL()
        example = factory.make_parsed_url()
        encoded = argument.toString(example)
        assert isinstance(encoded, bytes)
        decoded = argument.fromString(encoded)
        assert example.geturl() == decoded.geturl()

    def test_error_when_input_is_not_a_url_object(self):
        with pytest.raises(TypeError, match="^Not a URL-like object: <.*"):
            arguments.ParsedURL().toString(object())

    def test_netloc_containing_non_ascii_characters_is_encoded_to_idna(self):
        argument = arguments.ParsedURL()
        example = factory.make_parsed_url()._replace(
            netloc="\u24b8\u211d\U0001d538\u24b5\U0001d502"
        )
        encoded = argument.toString(example)
        assert isinstance(encoded, bytes)
        decoded = argument.fromString(encoded)
        # The non-ASCII netloc was encoded using IDNA.
        expected = example._replace(netloc="cra(z)y")
        assert expected.geturl() == decoded.geturl()


class TestAmpList(object):
    def test_round_trip(self):
        argument = arguments.AmpList([(b"thing", amp.Unicode())])
        example = [{"thing": factory.make_name("thing")}]
        encoded = argument.toStringProto(example, proto=None)
        assert isinstance(encoded, bytes)
        decoded = argument.fromStringProto(encoded, proto=None)
        assert example == decoded


class TestIPAddress(object):
    argument = arguments.IPAddress()

    def test_round_trips_ipv4_address(self):
        address = netaddr.IPAddress("192.168.34.87")
        encoded = self.argument.toString(address)
        assert isinstance(encoded, bytes)
        assert len(encoded) == 4, encoded
        decoded = self.argument.fromString(encoded)
        assert address == decoded

    def test_round_trips_ipv6_address(self):
        address = netaddr.IPAddress("fd28:8d1a:6c8e::345")
        encoded = self.argument.toString(address)
        assert isinstance(encoded, bytes)
        assert len(encoded) == 16, encoded
        decoded = self.argument.fromString(encoded)
        assert address == decoded

    def test_round_trips_ipv6_mapped_ipv4_address(self):
        address = netaddr.IPAddress("::ffff:10.78.45.9")
        encoded = self.argument.toString(address)
        assert isinstance(encoded, bytes)
        assert len(encoded) == 16, encoded
        decoded = self.argument.fromString(encoded)
        assert address == decoded


class TestIPNetwork(object):
    argument = arguments.IPNetwork()

    def test_round_trips_ipv4_address(self):
        network = factory.make_ipv4_network()
        encoded = self.argument.toString(network)
        assert isinstance(encoded, bytes)
        assert len(encoded) == 5, encoded
        decoded = self.argument.fromString(encoded)
        assert network == decoded

    def test_round_trips_ipv6_address(self):
        network = factory.make_ipv6_network()
        encoded = self.argument.toString(network)
        assert isinstance(encoded, bytes)
        assert len(encoded) == 17, encoded
        decoded = self.argument.fromString(encoded)
        assert network == decoded
