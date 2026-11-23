# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for constraints helpers."""

from unittest import TestCase

from provisioningserver.utils.constraints import (
    LabeledConstraintMap,
    parse_labeled_constraint_map,
    validate_constraint_label_name,
)


class ConstraintTestException(Exception):
    """Dummy exception class used to test that specifying an exception class
    to throw works properly."""


class TestValidateLabelName:
    EXPECTED_BAD_NAMES = ["", " ", "_", "-", " ", "a ", "a ", "-a", "*", "%"]

    EXPECTED_GOOD_NAMES = ["a", "0", "A", "a-", "a-b", "a_b", "a_b"]

    def test_rejects_bad_names(self):
        for name in self.EXPECTED_BAD_NAMES:
            with TestCase.assertRaises(
                TestCase(), ConstraintTestException, msg=f"name={name}"
            ):
                validate_constraint_label_name(
                    name, exception_type=ConstraintTestException
                )

    def test_accepts_good_names(self):
        for name in self.EXPECTED_GOOD_NAMES:
            validate_constraint_label_name(name)


class TestGetLabeledConstraintsMap:
    assertRaises = TestCase.assertRaises

    def test_missing_key_value_pair_raises(self):
        with self.assertRaises(ConstraintTestException):
            parse_labeled_constraint_map(
                "a:bc", exception_type=ConstraintTestException
            )

    def test_duplicate_label_raises(self):
        with self.assertRaises(ConstraintTestException):
            parse_labeled_constraint_map(
                "a:b=c;a:d=e", exception_type=ConstraintTestException
            )

    def test_invalid_label_raises(self):
        with self.assertRaises(ConstraintTestException):
            parse_labeled_constraint_map(
                "*:b=c", exception_type=ConstraintTestException
            )

    def test_label_with_no_constraints_raises(self):
        with self.assertRaises(ConstraintTestException):
            parse_labeled_constraint_map(
                "a:", exception_type=ConstraintTestException
            )

    def test_single_value_map(self):
        result = parse_labeled_constraint_map("a:b=c")
        assert {"a": {"b": ["c"]}} == result

    def test_non_string_returns_None(self):
        result = parse_labeled_constraint_map(dict())
        assert result is None

    def test_empty_string_returns_empty_map(self):
        result = parse_labeled_constraint_map("")
        assert {} == result

    def test_multiple_value_map(self):
        result = parse_labeled_constraint_map("a:b=c,d=e")
        assert {"a": {"b": ["c"], "d": ["e"]}} == result

    def test_multiple_value_map_with_duplicate_keys_appends_to_list(self):
        result = parse_labeled_constraint_map("a:a=abc,a=def,a=ghi")
        assert {"a": {"a": ["abc", "def", "ghi"]}} == result

    def test_multiple_label_map(self):
        result = parse_labeled_constraint_map("foo:a=b;bar:c=d")
        assert {"foo": {"a": ["b"]}, "bar": {"c": ["d"]}} == result

    def test_multiple_value_map_multiple_label_map(self):
        result = parse_labeled_constraint_map("foo:a=b,c=d;bar:e=f,g=h")
        assert result == {
            "foo": {"a": ["b"], "c": ["d"]},
            "bar": {"e": ["f"], "g": ["h"]},
        }


class TestLabeledConstraintMap:
    def test_len__for_null_map(self):
        lcm = LabeledConstraintMap(None)
        assert len(lcm) == 0

    def test_len__for_empty_map(self):
        lcm = LabeledConstraintMap("")
        assert len(lcm) == 0

    def test_len__for_populated_map(self):
        lcm = LabeledConstraintMap("eth0:space=1;eth1:space=2")
        assert len(lcm) == 2
