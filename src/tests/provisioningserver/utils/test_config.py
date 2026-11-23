# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `provisioningserver.utils.config`."""

import os.path
import random
import re
import uuid

import formencode
import pytest

from maastesting.factory import factory
from provisioningserver.utils import config


class TestSchema:
    """Tests for `Schema`."""

    def test_inherits_from_formencode(self):
        assert isinstance(config.Schema(), formencode.Schema)


@pytest.mark.parametrize(
    "example",
    [set(), tuple(), list()],
    ids=[set.__qualname__, tuple.__qualname__, list.__qualname__],
)
class TestSchemaIterators:
    """Tests for `Schema._value_is_iterator` with iterators."""

    def test_recognises_iterators(self, example):
        assert config.Schema()._value_is_iterator(example)


@pytest.mark.parametrize(
    "example",
    [b"", "", None],
    ids=[bytes.__qualname__, str.__qualname__, "None"],
)
class TestSchemaNonIterators:
    """Tests for `Schema._value_is_iterator` with non-iterators."""

    def test_recognises_non_iterators(self, example):
        assert not config.Schema()._value_is_iterator(example)


class TestByteString:
    """Tests for `ByteString`."""

    def test_converting_from_python_accepts_byte_string(self):
        example = factory.make_bytes()
        validator = config.ByteString()
        assert example == validator.from_python(example)

    def test_converting_from_python_rejects_non_byte_string(self):
        example = factory.make_string()
        validator = config.ByteString()
        with pytest.raises(formencode.Invalid) as exc_info:
            validator.from_python(example)
        assert str(exc_info.value) == (
            f"The input must be a byte string (not a str: {example!r})"
        )

    def test_converting_to_python_accepts_byte_string(self):
        example = factory.make_bytes()
        validator = config.ByteString()
        assert example == validator.to_python(example)

    def test_converting_to_python_rejects_non_byte_string(self):
        example = factory.make_string()
        validator = config.ByteString()
        with pytest.raises(formencode.Invalid) as exc_info:
            validator.to_python(example)
        assert str(exc_info.value) == (
            f"The input must be a byte string (not a str: {example!r})"
        )

    def test_empty_value(self):
        validator = config.ByteString()
        assert b"" == validator.to_python(None)


class TestUUIDString:
    """Tests for `UUIDString`."""

    def test_validation_succeeds_when_uuid_is_good(self):
        example_uuid = str(uuid.uuid4())
        validator = config.UUIDString(accept_python=False)
        assert example_uuid == validator.from_python(example_uuid)
        assert example_uuid == validator.to_python(example_uuid)

    def test_validation_fails_when_uuid_is_bad(self):
        example_uuid = str(uuid.uuid4()) + "can't-be-a-uuid"
        validator = config.UUIDString(accept_python=False)
        with pytest.raises(
            formencode.validators.Invalid,
            match="^%s$" % re.escape("%r Failed to parse UUID" % example_uuid),
        ):
            validator.from_python(example_uuid)
        with pytest.raises(
            formencode.validators.Invalid,
            match="^%s$" % re.escape("%r Failed to parse UUID" % example_uuid),
        ):
            validator.to_python(example_uuid)


class TestUnicodeString:
    """Tests for `UnicodeString`."""

    def test_converting_from_python_accepts_Unicode_string(self):
        example = factory.make_string()
        validator = config.UnicodeString()
        assert example == validator.from_python(example)

    def test_converting_from_python_rejects_non_Uncode_string(self):
        example = factory.make_bytes()
        validator = config.UnicodeString()
        with pytest.raises(formencode.Invalid) as exc_info:
            validator.from_python(example)
        assert str(exc_info.value) == (
            f"The input must be a Unicode string (not a bytes: {example!r})"
        )

    def test_converting_to_python_accepts_Unicode_string(self):
        example = factory.make_string()
        validator = config.UnicodeString()
        assert example == validator.to_python(example)

    def test_converting_to_python_rejects_non_Unicode_string(self):
        example = factory.make_bytes()
        validator = config.UnicodeString()
        with pytest.raises(formencode.Invalid) as exc_info:
            validator.to_python(example)
        assert str(exc_info.value) == (
            f"The input must be a Unicode string (not a bytes: {example!r})"
        )

    def test_empty_value(self):
        validator = config.UnicodeString()
        assert "" == validator.to_python(None)


class TestDirectory:
    """Tests for `DirectoryString`."""

    def test_validation_succeeds_when_directory_exists(self, tmp_path):
        directory = str(tmp_path)
        validator = config.DirectoryString(accept_python=False)
        assert directory == validator.from_python(directory)
        assert directory == validator.to_python(directory)

    def test_validation_fails_when_directory_does_not_exist(self, tmp_path):
        directory = os.path.join(str(tmp_path), "not-here")
        validator = config.DirectoryString(accept_python=False)
        with pytest.raises(
            formencode.validators.Invalid,
            match="^%s$"
            % re.escape("%r does not exist or is not a directory" % directory),
        ):
            validator.from_python(directory)
        with pytest.raises(
            formencode.validators.Invalid,
            match="^%s$"
            % re.escape("%r does not exist or is not a directory" % directory),
        ):
            validator.to_python(directory)


class TestExtendedURL:
    """Tests for `ExtendedURL`."""

    def _make_validator(self):
        return config.ExtendedURL(require_tld=False, accept_python=False)

    def test_takes_numbers_anywhere(self):
        # Could use factory.make_string() here, as it contains
        # digits, but this is a little bit more explicit and
        # clear to troubleshoot.
        validator = self._make_validator()

        hostname = "%dstart" % random.randint(0, 9)
        url = factory.make_simple_http_url(netloc=hostname)
        assert url == validator.to_python(url), "url: %s" % url

        hostname = "mid%ddle" % random.randint(0, 9)
        url = factory.make_simple_http_url(netloc=hostname)
        assert url == validator.to_python(url), "url: %s" % url

        hostname = "end%d" % random.randint(0, 9)
        url = factory.make_simple_http_url(netloc=hostname)
        assert url == validator.to_python(url), "url: %s" % url

    def test_takes_hyphen_but_not_start_or_end(self):
        validator = self._make_validator()

        # Reject leading hyphen
        hostname = "-start"
        url = factory.make_simple_http_url(netloc=hostname)
        with pytest.raises(
            formencode.Invalid, match="That is not a valid URL"
        ):
            validator.to_python(url)

        # Allow hyphens in the middle
        hostname = "mid-dle"
        url = factory.make_simple_http_url(netloc=hostname)
        assert url == validator.to_python(url), "url: %s" % url

        # Reject trailing hyphen
        hostname = "end-"
        url = factory.make_simple_http_url(netloc=hostname)
        with pytest.raises(
            formencode.Invalid, match="That is not a valid URL"
        ):
            validator.to_python(url)

    def test_allows_hostnames_as_short_as_a_single_char(self):
        validator = self._make_validator()

        # Single digit
        hostname = str(random.randint(0, 9))
        url = factory.make_simple_http_url(netloc=hostname)
        assert url == validator.to_python(url), "url: %s" % url

        # Single char
        hostname = factory.make_string(1)
        url = factory.make_simple_http_url(netloc=hostname)
        assert url == validator.to_python(url), "url: %s" % url

        # Reject single hyphen
        hostname = "-"
        url = factory.make_simple_http_url(netloc=hostname)
        with pytest.raises(
            formencode.Invalid, match="That is not a valid URL"
        ):
            validator.to_python(url)

    def test_allows_hostnames_up_to_63_chars_long(self):
        validator = self._make_validator()
        max_length = 63

        # Alow 63 chars
        hostname = factory.make_string(max_length)
        url = factory.make_simple_http_url(netloc=hostname)
        assert url == validator.to_python(url), "url: %s" % url

        # Reject 64 chars
        hostname = factory.make_string(max_length + 1)
        url = factory.make_simple_http_url(netloc=hostname)
        with pytest.raises(
            formencode.Invalid, match="That is not a valid URL"
        ):
            validator.to_python(url)

    def test_allows_domain_names_up_to_63_chars_long(self):
        validator = self._make_validator()
        max_length = 63

        # Alow 63 chars without hypen
        hostname = "%s.example.com" % factory.make_string(max_length)
        url = factory.make_simple_http_url(netloc=hostname)
        assert url == validator.to_python(url), "url: %s" % url

        # Reject 64 chars without hypen
        hostname = "%s.example.com" % factory.make_string(max_length + 1)
        url = factory.make_simple_http_url(netloc=hostname)
        with pytest.raises(
            formencode.Invalid, match="That is not a valid URL"
        ):
            validator.to_python(url)

        # Alow 63 chars with hypen
        hyphen_loc = random.randint(1, max_length - 1)
        name = factory.make_string(max_length - 1)
        hname = name[:hyphen_loc] + "-" + name[hyphen_loc:]
        hostname = "%s.example.com" % hname
        url = factory.make_simple_http_url(netloc=hostname)
        assert url == validator.to_python(url), "url: %s" % url

        # Reject 64 chars with hypen
        hyphen_loc = random.randint(1, max_length)
        name = factory.make_string(max_length)
        hname = name[:hyphen_loc] + "-" + name[hyphen_loc:]
        hostname = "%s.example.com" % hname
        url = factory.make_simple_http_url(netloc=hostname)
        with pytest.raises(
            formencode.Invalid, match="That is not a valid URL"
        ):
            validator.to_python(url)

    def test_requires_brackets_on_ipv6_address(self):
        validator = self._make_validator()
        name = "[%s]" % factory.make_ipv6_address()
        url = factory.make_simple_http_url(
            netloc=name, port=factory.pick_bool()
        )
        assert url == validator.to_python(url), "url: %s" % url

        # rejects bare ipv6 address
        name = "%s" % factory.make_ipv6_address()
        url = factory.make_simple_http_url(netloc=name)
        with pytest.raises(
            formencode.Invalid, match="That is not a valid URL"
        ):
            validator.to_python(url)

    def test_allows_ipv4_addresses(self):
        validator = self._make_validator()
        name = "%s" % factory.make_ipv4_address()
        url = factory.make_simple_http_url(
            netloc=name, port=factory.pick_bool()
        )
        assert url == validator.to_python(url), "url: %s" % url

    def test_allows_ipv4_addresses_in_ipv6_format(self):
        validator = self._make_validator()
        name = "[::ffff:%s]" % factory.make_ipv4_address()
        url = factory.make_simple_http_url(
            netloc=name, port=factory.pick_bool()
        )
        assert url == validator.to_python(url), "url: %s" % url

    def test_allows_trailing_and_starting_double_colon(self):
        validator = self._make_validator()
        # we get random network addresses above, but lets play with a few that
        # we know need to work.
        addrs = ["::1", "::f", "fe80::", "fe80::1", "fe80:37::3:1"]
        for addr in addrs:
            # lower case
            url = factory.make_simple_http_url(
                netloc="[%s]" % addr, port=factory.pick_bool()
            )
            assert url == validator.to_python(url), "url: %s" % url
            # upper case
            url = factory.make_simple_http_url(
                netloc="[%s]" % addr.upper(), port=factory.pick_bool()
            )
            assert url == validator.to_python(url), "url: %s" % url


class TestOneWayStringBool:
    """Tests for `OneWayStringBool`."""

    def test_from_python(self):
        validator = config.OneWayStringBool()
        assert not validator.from_python(False)
        assert validator.from_python(True)
