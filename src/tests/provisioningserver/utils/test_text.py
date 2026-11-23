# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for text processing utilities."""

from itertools import repeat
import string

import hypothesis.strategies
import pytest

from maastesting.factory import factory
from provisioningserver.utils.text import (
    make_gecos_field,
    normalise_to_comma_list,
    normalise_whitespace,
    split_string_list,
)


class TestNormaliseWhitespace:
    def test_preserves_text_without_whitespace(self):
        word = factory.make_name("word")
        assert word == normalise_whitespace(word)

    def test_eliminates_leading_space(self):
        assert "word" == normalise_whitespace(" word")

    def test_eliminates_trailing_space(self):
        assert "word" == normalise_whitespace("word ")

    def test_replaces_any_whitespace_sequence_with_single_space(self):
        assert "one two three" == normalise_whitespace("one   two\t\nthree")

    def test_treats_punctuation_as_non_space(self):
        punctuation = ".?;:!"
        assert punctuation == normalise_whitespace(punctuation)


class TestNormaliseToCommaList:
    """Tests for `normalise_to_comma_list`."""

    delimiters = hypothesis.strategies.text(
        string.whitespace + ",", min_size=1, max_size=10
    )

    @hypothesis.given(delimiters)
    def test_normalises_space_or_comma_list_to_comma_list(self, delimiter):
        words = [factory.make_name("word") for _ in range(5)]
        string = delimiter.join(words)
        assert ", ".join(words) == normalise_to_comma_list(string)

    @hypothesis.given(delimiters)
    def test_normalises_nothing_but_delimiter_to_empty(self, delimiter):
        assert "" == normalise_to_comma_list(delimiter)

    @hypothesis.given(delimiters)
    def test_eliminates_empty_words(self, delimiter):
        word = factory.make_name("word")
        assert word == normalise_to_comma_list(delimiter + word + delimiter)


@pytest.mark.parametrize(
    "test_input,unquoted,quoted",
    [
        ("", "", ""),
        ("foo", "foo", '"foo"'),
        ("foo bar", "foo, bar", '"foo", "bar"'),
        ("foo, bar", "foo, bar", '"foo", "bar"'),
        ("  foo   bar  ", "foo, bar", '"foo", "bar"'),
        ("  foo ,  bar  ", "foo, bar", '"foo", "bar"'),
    ],
    ids=[
        "empty string",
        "one token",
        "two tokens with space",
        "two tokens with comma",
        "extra spaces",
        "extra spaces with comma",
    ],
)
class TestNormalizeToCommaListScenarios:
    """Tests for `normalize_to_comma_list`."""

    def test_scenarios(self, test_input, unquoted, quoted):
        result_unquoted = normalise_to_comma_list(test_input)
        assert result_unquoted == unquoted
        result_quoted = normalise_to_comma_list(test_input, quoted=True)
        assert result_quoted == quoted


class TestSplitStringList:
    """Tests for `split_string_list`."""

    delimiters = hypothesis.strategies.text(
        string.whitespace + ",", min_size=1, max_size=10
    )

    @hypothesis.given(delimiters)
    def test_splits_at_delimiters(self, delimiter):
        words = [factory.make_name("word") for _ in range(5)]
        string = delimiter.join(words)
        assert words == list(split_string_list(string))

    @hypothesis.given(delimiters)
    def test_normalises_nothing_but_delimiter_to_empty_list(self, delimiter):
        assert [] == list(split_string_list(delimiter))

    @hypothesis.given(delimiters)
    def test_eliminates_empty_words(self, delimiter):
        word = factory.make_name("word")
        assert [word] == list(split_string_list(delimiter + word + delimiter))


class TestMakeGecosField:
    """Tests for `make_gecos_field`."""

    def test_returns_basic_gecos_field_without_input(self):
        assert ",,,," == make_gecos_field()

    def test_includes_full_name(self):
        assert "Bernard Bierkeller,,,,", make_gecos_field(
            fullname="Bernard Bierkeller"
        )

    def test_includes_room_number(self):
        room = factory.make_name("room")
        assert ",%s,,," % room == make_gecos_field(room=room)

    def test_includes_work_telephone_number(self):
        worktel = factory.make_name("worktel")
        assert ",,%s,," % worktel == make_gecos_field(worktel=worktel)

    def test_includes_home_telephone_number(self):
        hometel = factory.make_name("hometel")
        assert ",,,%s," % hometel == make_gecos_field(hometel=hometel)

    def test_includes_other_information(self):
        other = factory.make_name("other")
        assert ",,,,%s" % other == make_gecos_field(other=other)

    def test_cleans_all_fields(self):
        broken = "colon : comma , non-ascii \xa3 white-space \n\t  "
        fixed = "colon _ comma _ non-ascii ? white-space"
        assert ",".join(repeat(fixed, 5)) == make_gecos_field(
            broken, broken, broken, broken, broken
        )
