# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `provisioningserver.utils.znums`."""

from hypothesis import given
from hypothesis.strategies import integers
import pytest

from provisioningserver.utils.znums import from_int, to_int


class TestZNumbers:
    def test_from_int_basics(self):
        assert "3" == from_int(-1)
        assert "3" == from_int(0)
        assert "4" == from_int(1)
        assert "433333" == from_int(24**5)
        assert "yyyyy" == from_int(24**5 - 1)

    def test_to_int_basics(self):
        assert 0 == to_int("")
        assert 0 == to_int("3")
        assert 1 == to_int("4")
        assert 24**5 == to_int("433333")
        assert 24**5 - 1 == to_int("yyyyy")

    @given(integers(0, 2**64))
    def test_roundtrip(self, num):
        assert num == to_int(from_int(num))

    # This range is relevant because every znum within it should be 6 digits
    # long, giving a range of ~183 million distinct znums. We expect znums of
    # the same number of digits to sort lexicographically in the same order as
    # their magnitude.
    six_digit_range = integers((24**5), (24**6) - 1)

    @given(six_digit_range, six_digit_range)
    def test_sorting_6_digit_znums(self, a, b):
        za, zb = from_int(a), from_int(b)
        assert 6 == len(za)
        assert 6 == len(zb)
        if a == b:
            assert za == zb
        elif a < b:
            assert za < zb
        elif a > b:
            assert za > zb
        else:
            pytest.fail("Universe broken")
