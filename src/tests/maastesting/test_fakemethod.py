# Copyright 2012-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for :class:`FakeMethod`."""

import pytest

from maastesting.fakemethod import FakeMethod, MultiFakeMethod


class TestFakeMethod:
    def test_fakemethod_returns_None_by_default(self):
        assert FakeMethod()() is None

    def test_fakemethod_returns_given_value(self):
        assert FakeMethod("Input value")() == "Input value"

    def test_fakemethod_raises_given_failure(self):
        class AnException(Exception):
            pass

        with pytest.raises(AnException):
            FakeMethod(failure=AnException())()

    def test_fakemethod_has_no_calls_initially(self):
        assert FakeMethod().calls == []

    def test_fakemethod_records_call(self):
        stub = FakeMethod()
        stub()
        assert stub.calls == [((), {})]

    def test_fakemethod_records_args(self):
        stub = FakeMethod()
        stub(1, 2)
        assert stub.calls == [((1, 2), {})]

    def test_fakemethod_records_kwargs(self):
        stub = FakeMethod()
        stub(x=10)
        assert stub.calls == [((), {"x": 10})]

    def test_call_count_is_zero_initially(self):
        assert FakeMethod().call_count == 0

    def test_call_count_counts_calls(self):
        stub = FakeMethod()
        stub()
        assert stub.call_count == 1

    def test_extract_args_returns_just_call_args(self):
        stub = FakeMethod()
        stub(1, 2, 3, x=12)
        assert stub.extract_args() == [(1, 2, 3)]

    def test_extract_kwargs_returns_just_call_kwargs(self):
        stub = FakeMethod()
        stub(1, 2, 3, x=12)
        assert stub.extract_kwargs() == [{"x": 12}]


class TestMultiFakeMethod:
    def test_call_calls_all_given_methods(self):
        methods = FakeMethod(), FakeMethod()
        method = MultiFakeMethod(methods)
        call1_args = "input 1"
        call2_args = "input 2"
        method(call1_args)
        method(call2_args)
        assert [
            [("input 1",)],
            [("input 2",)],
        ] == [methods[0].extract_args(), methods[1].extract_args()]

    def test_raises_if_called_one_time_too_many(self):
        method = MultiFakeMethod([FakeMethod()])
        method()
        with pytest.raises(ValueError):
            method()
