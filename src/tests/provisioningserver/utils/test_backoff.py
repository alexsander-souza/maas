# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from itertools import islice

from hypothesis import given
from hypothesis.strategies import floats

from provisioningserver.utils.backoff import exponential_growth, full_jitter


class TestFunctions:
    """Test functions in `backoff`."""

    @given(floats(0.0, 10.0), floats(1.0, 3.0))
    def test_exponential_growth(self, base, rate):
        growth = exponential_growth(base, rate)
        growth_seq = list(islice(growth, 10))

        assert len(growth_seq) == 10
        for thing in growth_seq:
            assert isinstance(thing, float)
        assert growth_seq == sorted(growth_seq)

        assert (base * rate) == growth_seq[0]
        assert (base * (rate**10)) == growth_seq[-1]

    def test_full_jitter(self):
        # Test with various input values
        values = [10.0, 100.0, 1000.0]
        jittered = list(full_jitter(values))

        assert len(jittered) == len(values)
        for original, jittered_value in zip(values, jittered, strict=True):
            assert isinstance(jittered_value, float)
            assert jittered_value >= 0.0
            assert jittered_value < original

        # Test with empty list
        assert list(full_jitter([])) == []

        # Test with zero - should always produce zero
        assert list(full_jitter([0.0])) == [0.0]
