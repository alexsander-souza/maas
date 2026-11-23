# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from types import SimpleNamespace

import crochet
import pytest
from twisted.internet import reactor
from twisted.internet.defer import Deferred

from maastesting.crochet import TimeoutInTestException, wait_for
from maastesting.pytest import legacy
from maastesting.pytest.legacy import (
    _check_rack_test_result,
    _cleanup_rack_reactor,
    _eventual_result_failures,
    _eventual_result_guard,
)


class _FakeDelayedCall:
    def __init__(self):
        self.cancelled = False

    def active(self):
        return not self.cancelled

    def cancel(self):
        self.cancelled = True

    def __str__(self):
        return "delayed test call"


class _FakeReactor:
    def __init__(self, delayed=(), selectables=()):
        self.delayed = list(delayed)
        self.selectables = list(selectables)

    def seconds(self):
        return 0.0

    def callFromThread(self, callback):
        callback()

    def getDelayedCalls(self):
        return self.delayed

    def removeAll(self):
        selectables, self.selectables = self.selectables, []
        return selectables


class _FakeBlockingCall:
    def __init__(self, first_error=None):
        self.first_error = first_error
        self.calls = 0

    def __call__(self, reactor, function):
        self.calls += 1
        if self.calls == 1 and self.first_error is not None:
            raise self.first_error
        result = function()
        if isinstance(result, Deferred):
            if not result.called:
                raise AssertionError("threadpool wait unexpectedly pending")
            return result.result
        return result


class TestRackReactorGuard:
    def test_clean_reactor_passes(self, monkeypatch):
        monkeypatch.setattr(
            legacy, "blockingCallFromThread", _FakeBlockingCall()
        )

        _cleanup_rack_reactor(_FakeReactor(), "rack/test.py::test_clean")

    @pytest.mark.parametrize("resource", ["delayed", "selectable"])
    def test_leaked_reactor_resources_fail_and_are_removed(
        self, monkeypatch, resource
    ):
        delayed = _FakeDelayedCall() if resource == "delayed" else None
        selectable = object() if resource == "selectable" else None
        fake_reactor = _FakeReactor(
            delayed=[delayed] if delayed is not None else (),
            selectables=[selectable] if selectable is not None else (),
        )
        monkeypatch.setattr(
            legacy, "blockingCallFromThread", _FakeBlockingCall()
        )

        with pytest.raises(
            pytest.fail.Exception, match="rack/test.py::test_leak"
        ):
            _cleanup_rack_reactor(fake_reactor, "rack/test.py::test_leak")

        if delayed is not None:
            assert delayed.cancelled
        assert fake_reactor.selectables == []

    def test_unawaited_deferred_is_cancelled(self):
        deferred = Deferred(lambda _: None)

        with pytest.raises(pytest.fail.Exception, match="unawaited Deferred"):
            _check_rack_test_result(deferred, "rack/test.py::test_deferred")

        assert deferred.called

    def test_unawaited_coroutine_is_closed(self):
        async def coroutine():
            return None

        result = coroutine()

        with pytest.raises(pytest.fail.Exception, match="unawaited coroutine"):
            _check_rack_test_result(result, "rack/test.py::test_coroutine")

        assert result.cr_frame is None

    def test_unawaited_generator_is_closed(self):
        def generator():
            yield None

        result = generator()

        with pytest.raises(
            pytest.fail.Exception, match="returned a generator"
        ):
            _check_rack_test_result(result, "rack/test.py::test_generator")

        assert result.gi_frame is None

    def test_wait_for_returns_completed_result(self, monkeypatch):
        class CompletedResult:
            def wait(self, timeout):
                assert timeout == 0.25
                return "complete"

        result = CompletedResult()
        monkeypatch.setattr(
            crochet, "run_in_reactor", lambda function: lambda: result
        )

        assert wait_for(0.25)(lambda: None)() == "complete"

    def test_wait_for_timeout_cancels_crochet_result(self, monkeypatch):
        class TimedOutResult:
            cancelled = False

            def wait(self, timeout):
                assert timeout == 0.25
                raise crochet.TimeoutError()

            def cancel(self):
                self.cancelled = True

        result = TimedOutResult()
        monkeypatch.setattr(
            crochet, "run_in_reactor", lambda function: lambda: result
        )

        with pytest.raises(TimeoutInTestException):
            wait_for(0.25)(lambda: None)()

        assert result.cancelled

    def test_cleanup_runs_after_test_exception(self, monkeypatch):
        fake_reactor = _FakeReactor()
        blocking_call = _FakeBlockingCall()
        monkeypatch.setattr(legacy, "blockingCallFromThread", blocking_call)
        request = SimpleNamespace(
            node=SimpleNamespace(
                get_closest_marker=lambda marker: object(),
                nodeid="rack/test.py::test_exception",
            ),
            cls=None,
        )
        fixture = legacy._rack_reactor_guard.__wrapped__(request)
        monkeypatch.setattr("twisted.internet.reactor", fake_reactor)

        next(fixture)
        with pytest.raises(RuntimeError, match="test failure"):
            fixture.throw(RuntimeError("test failure"))

    def test_unmarked_tests_are_not_cleaned_up(self, monkeypatch):
        blocking_call = _FakeBlockingCall()
        monkeypatch.setattr(legacy, "blockingCallFromThread", blocking_call)
        request = SimpleNamespace(
            node=SimpleNamespace(
                get_closest_marker=lambda marker: None,
                nodeid="ordinary/test.py::test_unmarked",
            ),
            cls=None,
        )
        fixture = legacy._rack_reactor_guard.__wrapped__(request)

        next(fixture)
        with pytest.raises(StopIteration):
            next(fixture)

        assert blocking_call.calls == 0


def make_result():
    return crochet.EventualResult(None, reactor)


class TestEventualResultFailures:
    def test_awaited_result_is_accepted(self):
        result = make_result()
        result._set_result("ready")

        assert result.wait(timeout=0) == "ready"
        assert _eventual_result_failures({result}) == []

    def test_unfired_result_is_reported(self):
        result = make_result()

        failures = _eventual_result_failures({result})

        assert len(failures) == 1
        assert "EventualResult did not fire" in failures[0]
        assert repr(result) in failures[0]

    def test_fired_unretrieved_result_is_reported(self):
        result = make_result()
        result._set_result("ready")

        failures = _eventual_result_failures({result})

        assert len(failures) == 1
        assert "fired but was not retrieved" in failures[0]
        assert "result='ready'" in failures[0]

    @pytest.mark.parametrize(
        "result_state, message",
        [
            ("unfired", "EventualResult did not fire"),
            ("fired", "fired but was not retrieved"),
        ],
    )
    def test_guard_fails_for_unhandled_results(
        self, monkeypatch, result_state, message
    ):
        registry = crochet._eventloop.ResultRegistry()
        monkeypatch.setattr(crochet._main, "_registry", registry)
        fixture = _eventual_result_guard.__wrapped__()
        next(fixture)
        result = make_result()
        registry.register(result)
        if result_state == "fired":
            result._set_result("lost result")

        with pytest.raises(pytest.fail.Exception, match=message):
            next(fixture)

        assert len(registry._results) == 0


class TestGuardFixture:
    def test_plain_pytest_class_tracks_and_checks_results(self, monkeypatch):
        registry = crochet._eventloop.ResultRegistry()
        monkeypatch.setattr(crochet._main, "_registry", registry)
        fixture = _eventual_result_guard.__wrapped__()

        next(fixture)
        result = make_result()
        registry.register(result)
        result._set_result("ready")
        result.wait(timeout=0)

        with pytest.raises(StopIteration):
            next(fixture)

        assert len(registry._results) == 0

    def test_registry_is_restored_after_exception(self, monkeypatch):
        registry = crochet._eventloop.ResultRegistry()
        previous = make_result()
        previous._set_result("previous test")
        registry.register(previous)
        original_results = registry._results
        monkeypatch.setattr(crochet._main, "_registry", registry)
        fixture = _eventual_result_guard.__wrapped__()

        next(fixture)
        result = make_result()
        registry.register(result)
        result._set_result("current test")
        result.wait(timeout=0)

        with pytest.raises(RuntimeError, match="test failure"):
            fixture.throw(RuntimeError("test failure"))

        assert registry._results is original_results
        assert set(registry._results) == {previous}

    def test_unretrieved_previous_result_does_not_leak_into_next_test(
        self, monkeypatch
    ):
        registry = crochet._eventloop.ResultRegistry()
        previous = make_result()
        previous._set_result("previous test")
        registry.register(previous)
        original_results = registry._results
        monkeypatch.setattr(crochet._main, "_registry", registry)
        fixture = _eventual_result_guard.__wrapped__()

        next(fixture)

        assert registry._results == set()
        with pytest.raises(StopIteration):
            next(fixture)

        assert registry._results is original_results
        assert set(registry._results) == {previous}
