# Copyright 2014-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from functools import partial
import io
from itertools import cycle, product
import operator
import os
from random import randint, random
import re
import signal
import sys
import threading
from unittest import mock
from unittest.mock import ANY, Mock, sentinel

from crochet import EventualResult
import pytest
from twisted import internet
from twisted.internet import address, reactor
from twisted.internet.defer import (
    AlreadyCalledError,
    CancelledError,
    Deferred,
    DeferredSemaphore,
    inlineCallbacks,
    succeed,
)
from twisted.internet.error import ProcessDone, ProcessTerminated
from twisted.internet.protocol import ProcessProtocol
from twisted.internet.task import Clock
from twisted.internet.threads import deferToThread, deferToThreadPool
from twisted.python import context, threadable
from twisted.python.failure import Failure
from twisted.web.test import requesthelper

from maascommon.tracing import get_trace_id, set_trace_id
from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.deferred import extract_result
from maastesting.factory import factory
from maastesting.twisted import TwistedLoggerFixture
from provisioningserver.utils import twisted as twisted_module
from provisioningserver.utils.twisted import (
    asynchronous,
    call,
    callInReactor,
    callInReactorWithTimeout,
    callOut,
    callOutToThread,
    DeferredValue,
    deferToNewThread,
    deferWithTimeout,
    FOREVER,
    IAsynchronous,
    ISynchronous,
    LONGTIME,
    makeDeferredWithProcessProtocol,
    pause,
    reducedWebLogFormatter,
    retries,
    retry,
    RPCFetcher,
    suppress,
    synchronous,
    terminateProcess,
    threadDeferred,
    ThreadPool,
    ThreadPoolLimiter,
    ThreadUnpool,
)

TIMEOUT = get_testing_timeout()


def _expand_scenarios(*dimensions):
    """Return pytest scenario parameters with their legacy descriptive IDs."""
    return [
        (
            ",".join(name for name, _ in combination),
            {
                key: value
                for _, values in combination
                for key, value in values.items()
            },
        )
        for combination in product(*dimensions)
    ]


def _parametrize_scenarios(test_class):
    scenarios = test_class.scenarios
    test_class.scenarios = None
    return pytest.mark.parametrize(
        "scenario",
        [pytest.param(values, id=name) for name, values in scenarios],
    )(test_class)


def _patch(mocker, obj, attribute, value=mock.sentinel.unset):
    if value is mock.sentinel.unset:
        value = mock.MagicMock(__name__=attribute)
    return mocker.patch.object(obj, attribute, value)


@pytest.fixture(autouse=True)
def _pytest_test_helpers(request, mocker, tmp_path):
    instance = request.instance
    if instance is not None:
        instance.request = request
        instance.mocker = mocker
        instance.tmp_path = tmp_path
        scenario = getattr(
            getattr(request.node, "callspec", None), "params", {}
        ).get("scenario")
        if scenario is not None:
            vars(instance).update(scenario)


def _record_process_output(request, title, protocol, stream):
    output = stream.getvalue().decode("utf-8", errors="replace")
    request.node.add_report_section("teardown", title, output)


def return_args(*args, **kwargs):
    return args, kwargs


@pytest.mark.rack_reactor_guard
class TestAsynchronousDecorator:
    @wait_for(timeout=TIMEOUT)
    def test_calls_in_current_thread_when_current_thread_is_reactor(self):
        result = asynchronous(return_args)(1, 2, three=3)
        assert ((1, 2), {"three": 3}) == result

    def test_calls_in_current_thread_when_io_thread_is_not_set(self):
        # Patch ioThread such that isInIOThread() returns False. It will
        # return False for every thread too, so asynchronous() explicitly
        # checks ioThread. It can be unset as twistd starts an application, so
        # we assume we're in the reactor thread anyway.
        self.mocker.patch.object(threadable, "ioThread", None)
        assert not (threadable.isInIOThread())
        result = asynchronous(return_args)(1, 2, three=3)
        assert ((1, 2), {"three": 3}) == result

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_calls_into_reactor_when_current_thread_is_not_reactor(self):
        def do_stuff_in_thread():
            result = asynchronous(return_args)(3, 4, five=5)
            assert isinstance(result, EventualResult)
            return result.wait(TIMEOUT)

        # Call do_stuff_in_thread() from another thread.
        result = yield deferToThread(do_stuff_in_thread)
        # do_stuff_in_thread() waited for the result of return_args().
        # The arguments passed back match those passed in from
        # do_stuff_in_thread().
        assert ((3, 4), {"five": 5}) == result

    def test_provides_marker_interface(self):
        assert not (IAsynchronous.providedBy(return_args))
        assert IAsynchronous.providedBy(asynchronous(return_args))


def noop():
    pass


@pytest.mark.rack_reactor_guard
class TestThreadDeferred:
    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_thread_deferred(self):
        @threadDeferred
        def func():
            return threading.get_ident()

        ident = yield func()
        assert ident != threading.get_ident()


@pytest.mark.rack_reactor_guard
class TestAsynchronousDecoratorWithTimeout:
    def test_timeout_cannot_be_None(self):
        pytest.raises(ValueError, asynchronous, noop, timeout=None)

    def test_timeout_cannot_be_negative(self):
        pytest.raises(ValueError, asynchronous, noop, timeout=-1)

    def test_timeout_can_be_int(self):
        assert callable(asynchronous(noop, timeout=1))

    def test_timeout_can_be_long(self):
        assert callable(asynchronous(noop, timeout=1))

    def test_timeout_can_be_float(self):
        assert callable(asynchronous(noop, timeout=1.0))

    def test_timeout_can_be_forever(self):
        assert callable(asynchronous(noop, timeout=FOREVER))


@pytest.mark.rack_reactor_guard
class TestAsynchronousDecoratorWithTimeoutDefined:
    scenarios = (
        ("finite", {"timeout": random()}),
        ("forever", {"timeout": FOREVER}),
    )

    @wait_for(timeout=TIMEOUT)
    def test_in_reactor_thread(self, scenario):
        return_args_async = asynchronous(return_args, timeout=self.timeout)
        result = return_args_async(1, 2, three=3)
        assert ((1, 2), {"three": 3}) == result

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_in_other_thread(self, scenario):
        return_args_async = asynchronous(return_args, timeout=self.timeout)
        # Call self.return_args from another thread.
        result = yield deferToThread(return_args_async, 3, 4, five=5)
        # The arguments passed back match those passed in.
        assert ((3, 4), {"five": 5}) == result

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_passes_timeout_to_wait(self, scenario):
        # These mocks are going to help us tell a story of a timeout.
        run_in_reactor = _patch(self.mocker, twisted_module, "run_in_reactor")
        func_in_reactor = run_in_reactor.return_value
        eventual_result = func_in_reactor.return_value
        wait = eventual_result.wait
        wait.return_value = sentinel.result

        # Our placeholder function, and its wrapped version.
        def do_nothing():
            pass

        do_nothing_async = asynchronous(do_nothing, timeout=self.timeout)

        # Call our wrapped function in a thread so that the wrapper calls back
        # into the IO thread, via the time-out logic.
        result = yield deferToThread(do_nothing_async)
        assert result == sentinel.result

        # Here's what happened, or should have:
        # 1. do_nothing was wrapped by run_in_reactor, producing
        #    func_in_reactor.
        run_in_reactor.assert_called_once_with(do_nothing)
        # 2. func_in_reactor was called with no arguments, because we didn't
        #    pass any, producing eventual_result.
        func_in_reactor.assert_called_once_with()
        # 3. eventual_result.wait was called...
        if self.timeout is FOREVER:
            # ...without arguments.
            wait.assert_called_once_with(LONGTIME)
        else:
            # ...with the timeout we passed when we wrapped do_nothing.
            wait.assert_called_once_with(self.timeout)


@pytest.mark.rack_reactor_guard
class TestSynchronousDecorator:
    @synchronous
    def return_args(self, *args, **kwargs):
        return args, kwargs

    @wait_for(timeout=TIMEOUT)
    def test_in_reactor_thread(self):
        with pytest.raises(
            AssertionError,
            match=re.escape(
                "Function return_args(...) must not be called in the reactor thread."
            ),
        ):
            self.return_args()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_in_other_thread(self):
        def do_stuff_in_thread():
            return self.return_args(3, 4, five=5)

        # Call do_stuff_in_thread() from another thread.
        result = yield deferToThread(do_stuff_in_thread)
        # do_stuff_in_thread() ran straight through, without
        # modification. The arguments passed back match those passed in
        # from do_stuff_in_thread().
        assert ((3, 4), {"five": 5}) == result

    def test_allows_call_in_any_thread_when_reactor_not_running(self):
        self.mocker.patch.object(reactor, "running", False)
        assert ((3, 4), {"five": 5}) == self.return_args(3, 4, five=5)

    def test_provides_marker_interface(self):
        assert not (ISynchronous.providedBy(return_args))
        assert ISynchronous.providedBy(synchronous(return_args))


class TestSynchronousDecoratorSychronously:
    """Test `synchronous` outside of the reactor thread."""

    def test_raises_TypeError_when_call_returns_Deferred(self):
        @synchronous
        def deferSomething(*args, **kwargs):
            return Deferred()

        a, b = factory.make_name("a"), factory.make_name("b")
        with pytest.raises(TypeError) as cm:
            deferSomething(a, b=b)

        assert str(cm.value) == (
            "Synchronous call returned a Deferred: %s(%r, b=%r)"
            % (deferSomething.__qualname__, a, b)
        )

    def test_raises_TypeError_when_callable_returns_Deferred(self):
        class Something:
            def __call__(self, *args, **kwargs):
                return Deferred()

        something = synchronous(Something())
        a, b = factory.make_name("a"), factory.make_name("b")
        with pytest.raises(TypeError) as cm:
            something(a, b=b)
        assert str(cm.value) == (
            "Synchronous call returned a Deferred: %s(%r, b=%r)"
            % (Something.__qualname__, a, b)
        )


class TestSuppress:
    """Tests for `suppress`."""

    def test_suppresses_given_exception(self):
        error_type = factory.make_exception_type()
        failure = Failure(error_type())
        assert suppress(failure, error_type) is None

    def test_does_not_suppress_other_exceptions(self):
        error_type = factory.make_exception_type()
        failure = Failure(factory.make_exception())
        assert suppress(failure, error_type) is failure

    def test_returns_instead_value_when_suppressing(self):
        error_type = factory.make_exception_type()
        failure = Failure(error_type())
        assert (
            suppress(failure, error_type, instead=sentinel.instead)
            is sentinel.instead
        )


@pytest.mark.rack_reactor_guard
class TestRetry:
    def _assert_no_result(self, d: Deferred):
        assert not (d.called), "Deferred has already fired"

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_retry_succeeds_immediately(self):
        clock = Clock()

        def succeed_func():
            return "done"

        result = yield retry(succeed_func, timeout=5, intervals=1, clock=clock)
        assert result == "done"

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_retry_succeeds_after_retries(self):
        clock = Clock()
        attempts = {"n": 0}

        def flaky_func():
            attempts["n"] += 1
            if attempts["n"] < 4:
                raise RuntimeError("BOOM")
            return "ok"

        d = retry(flaky_func, timeout=10, intervals=[1, 1, 1, 1], clock=clock)
        self._assert_no_result(d)

        clock.advance(1)
        self._assert_no_result(d)

        clock.advance(1)
        self._assert_no_result(d)

        clock.advance(1)
        result = yield d
        assert result == "ok"

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_retry_times_out(self):
        clock = Clock()

        attempts = {"n": 0}

        def always_fail():
            attempts["n"] += 1
            raise RuntimeError("BOOM")

        d = retry(always_fail, timeout=3, intervals=1, clock=clock)
        assert attempts["n"] == 1

        clock.advance(1)
        assert attempts["n"] == 2

        clock.advance(1)
        assert attempts["n"] == 3

        clock.advance(2)  # exceed timeout, no call should be made.
        assert attempts["n"] == 3

        try:
            yield d
        except TimeoutError as e:
            assert "Retries exhausted" in str(e)


class TestRetries:
    def _assert_retry(
        self,
        clock,
        observed,
        expected_elapsed,
        expected_remaining,
        expected_wait,
    ):
        """Assert that the retry tuple matches the given expectations.

        Retry tuples are those returned by `retries`.
        """
        elapsed, remaining, wait = observed
        assert elapsed == expected_elapsed
        assert remaining == expected_remaining
        assert wait == expected_wait

    def test_yields_elapsed_remaining_and_wait(self):
        # Take control of time.
        clock = Clock()

        gen_retries = retries(5, 2, clock=clock)
        # No time has passed, 5 seconds remain, and it suggests sleeping
        # for 2 seconds.
        self._assert_retry(clock, next(gen_retries), 0, 5, 2)
        # Mimic sleeping for the suggested sleep time.
        clock.advance(2)
        # Now 2 seconds have passed, 3 seconds remain, and it suggests
        # sleeping for 2 more seconds.
        self._assert_retry(clock, next(gen_retries), 2, 3, 2)
        # Mimic sleeping for the suggested sleep time.
        clock.advance(2)
        # Now 4 seconds have passed, 1 second remains, and it suggests
        # sleeping for just 1 more second.
        self._assert_retry(clock, next(gen_retries), 4, 1, 1)
        # Mimic sleeping for the suggested sleep time.
        clock.advance(1)
        # There's always a final chance to try something.
        self._assert_retry(clock, next(gen_retries), 5, 0, 0)
        # All done.
        pytest.raises(StopIteration, next, gen_retries)

    def test_calculates_times_with_reference_to_current_time(self):
        # Take control of time.
        clock = Clock()

        gen_retries = retries(5, 2, clock=clock)
        # No time has passed, 5 seconds remain, and it suggests sleeping
        # for 2 seconds.
        self._assert_retry(clock, next(gen_retries), 0, 5, 2)
        # Mimic sleeping for 4 seconds, more than the suggested.
        clock.advance(4)
        # Now 4 seconds have passed, 1 second remains, and it suggests
        # sleeping for just 1 more second.
        self._assert_retry(clock, next(gen_retries), 4, 1, 1)
        # Don't sleep, ask again immediately, and the same answer is given.
        self._assert_retry(clock, next(gen_retries), 4, 1, 1)
        # Mimic sleeping for 100 seconds, much more than the suggested.
        clock.advance(100)
        # There's always a final chance to try something, but the elapsed and
        # remaining figures are still calculated with reference to the current
        # time. The wait time never goes below zero.
        self._assert_retry(clock, next(gen_retries), 104, -99, 0)
        # All done.
        pytest.raises(StopIteration, next, gen_retries)

    def test_captures_start_time_when_called(self):
        # Take control of time.
        clock = Clock()

        gen_retries = retries(5, 2, clock=clock)
        clock.advance(4)
        # 4 seconds have passed, so 1 second remains, and it suggests sleeping
        # for 1 second.
        self._assert_retry(clock, next(gen_retries), 4, 1, 1)

    def test_intervals_can_be_an_iterable(self):
        # Take control of time.
        clock = Clock()
        # Use intervals of 1s, 2s, 3, and then back to 1s.
        intervals = cycle((1.0, 2.0, 3.0))

        gen_retries = retries(5, intervals, clock=clock)
        # No time has passed, 5 seconds remain, and it suggests sleeping
        # for 1 second, then 2, then 3, then 1 again.
        self._assert_retry(clock, next(gen_retries), 0, 5, 1)
        self._assert_retry(clock, next(gen_retries), 0, 5, 2)
        self._assert_retry(clock, next(gen_retries), 0, 5, 3)
        self._assert_retry(clock, next(gen_retries), 0, 5, 1)
        # Mimic sleeping for 3.5 seconds, more than the suggested.
        clock.advance(3.5)
        # Now 3.5 seconds have passed, 1.5 seconds remain, and it suggests
        # sleeping for 1.5 seconds, 0.5 less than the next expected interval
        # of 2.0 seconds.
        self._assert_retry(clock, next(gen_retries), 3.5, 1.5, 1.5)
        # Don't sleep, ask again immediately, and the same answer is given.
        self._assert_retry(clock, next(gen_retries), 3.5, 1.5, 1.5)
        # Don't sleep, ask again immediately, and 1.0 seconds is given,
        # because we're back to the 1.0 second interval.
        self._assert_retry(clock, next(gen_retries), 3.5, 1.5, 1.0)
        # Mimic sleeping for 100 seconds, much more than the suggested.
        clock.advance(100)
        # There's always a final chance to try something, but the elapsed and
        # remaining figures are still calculated with reference to the current
        # time. The wait time never goes below zero.
        self._assert_retry(clock, next(gen_retries), 103.5, -98.5, 0.0)
        # All done.
        pytest.raises(StopIteration, next, gen_retries)


class TestPause:
    def test_pause_returns_a_deferred_that_fires_after_a_delay(self):
        # Take control of time.
        clock = Clock()
        wait = randint(4, 4000)

        d = pause(wait, clock=clock)

        # pause() returns an uncalled deferred.
        assert isinstance(d, Deferred)
        assert not (d.called)
        # pause() has scheduled a call to happen in `wait` seconds.
        assert len(clock.getDelayedCalls()) == 1
        [delayed_call] = clock.getDelayedCalls()
        assert delayed_call.getTime() == wait
        assert not (delayed_call.cancelled)
        assert not (delayed_call.called)

        # Nothing has changed right before the deadline.
        clock.advance(wait - 1)
        assert not (d.called)
        assert not (delayed_call.cancelled)
        assert not (delayed_call.called)

        # After `wait` seconds the deferred is called.
        clock.advance(1)
        assert d.called
        assert not (delayed_call.cancelled)
        assert delayed_call.called

        # The result is unexciting.
        assert d.result is None

    def test_pause_can_be_cancelled(self):
        # Take control of time.
        clock = Clock()
        wait = randint(4, 4000)

        d = pause(wait, clock=clock)
        [delayed_call] = clock.getDelayedCalls()

        d.cancel()

        # The deferred has been cancelled.
        assert d.called
        assert isinstance(d.result, Failure)
        assert isinstance(d.result.value, CancelledError)

        # We must suppress the cancellation error here or the test suite
        # will get huffy about it.
        d.addErrback(lambda failure: None)

        # The delayed call was cancelled too.
        assert delayed_call.cancelled
        assert not (delayed_call.called)


class TestDeferWithTimeout:
    def test_returns_Deferred_that_will_be_cancelled_after_timeout(self):
        clock = self.mocker.patch.object(internet, "reactor", Clock())

        # Called with only a timeout, `deferWithTimeout` returns a Deferred.
        timeout = randint(10, 100)
        d = deferWithTimeout(timeout)
        assert isinstance(d, Deferred)
        assert not (d.called)

        # It's been scheduled for cancellation in `timeout` seconds.
        assert len(clock.getDelayedCalls()) == 1
        [delayed_call] = clock.getDelayedCalls()
        assert not (delayed_call.cancelled)
        assert not (delayed_call.called)

        assert delayed_call.time == timeout
        assert delayed_call.func == d.cancel
        assert delayed_call.args == ()
        assert delayed_call.kw == {}

        # Once the timeout is reached, the delayed call is called, and this
        # cancels `d`. The default canceller for Deferred errbacks with
        # CancelledError.
        clock.advance(timeout)
        assert not (delayed_call.cancelled)
        assert delayed_call.called
        pytest.raises(CancelledError, extract_result, d)

    def test_returns_Deferred_that_wont_be_cancelled_if_called(self):
        clock = self.mocker.patch.object(internet, "reactor", Clock())

        # Called without a function argument, `deferWithTimeout` returns a new
        # Deferred, and schedules it to be cancelled in `timeout` seconds.
        timeout = randint(10, 100)
        d = deferWithTimeout(timeout)
        [delayed_call] = clock.getDelayedCalls()

        # Advance some amount of time to simulate something happening.
        clock.advance(5)
        # The timeout call is still in place.
        assert not (delayed_call.cancelled)
        assert not (delayed_call.called)

        d.callback(sentinel.result)
        # After calling d the timeout call has been cancelled.
        assert delayed_call.cancelled
        assert not (delayed_call.called)
        # The result has been safely passed on.
        assert extract_result(d) is sentinel.result

    def test_returns_Deferred_that_wont_be_cancelled_if_errored(self):
        clock = self.mocker.patch.object(internet, "reactor", Clock())

        # Called without a function argument, `deferWithTimeout` returns a new
        # Deferred, and schedules it to be cancelled in `timeout` seconds.
        timeout = randint(10, 100)
        d = deferWithTimeout(timeout)
        [delayed_call] = clock.getDelayedCalls()

        # Advance some amount of time to simulate something happening, but
        # less than the timeout.
        clock.advance(timeout - 1)
        # The timeout call is still in place.
        assert not (delayed_call.cancelled)
        assert not (delayed_call.called)

        error = RuntimeError()
        d.errback(error)
        # After calling d the timeout call has been cancelled.
        assert delayed_call.cancelled
        assert not (delayed_call.called)
        # The error has been passed safely on.
        pytest.raises(RuntimeError, extract_result, d)

    def test_calls_given_function(self):
        clock = self.mocker.patch.object(internet, "reactor", Clock())

        class OurDeferred(Deferred):
            """A Deferred subclass that we use as a marker."""

        # Any given function is called via `maybeDeferred`. In this case, we
        # get an instance of our marker class back because it is a Deferred.
        timeout = randint(10, 100)
        d = deferWithTimeout(timeout, OurDeferred)
        assert isinstance(d, OurDeferred)
        assert not (d.called)

        # Just as with the non-function form, it's been scheduled for
        # cancellation in `timeout` seconds.
        assert len(clock.getDelayedCalls()) == 1
        [delayed_call] = clock.getDelayedCalls()
        assert not (delayed_call.cancelled)
        assert not (delayed_call.called)
        assert delayed_call.time == timeout
        assert delayed_call.func == d.cancel
        assert delayed_call.args == ()
        assert delayed_call.kw == {}

        # Once the timeout is reached, the delayed call is called, and this
        # cancels `d`. The default canceller for Deferred errbacks with
        # CancelledError.
        clock.advance(timeout)
        assert not (delayed_call.cancelled)
        assert delayed_call.called

        pytest.raises(CancelledError, extract_result, d)

    def test_calls_given_function_and_always_returns_Deferred(self):
        clock = self.mocker.patch.object(internet, "reactor", Clock())

        def do_something(a, *b, **c):
            return do_something, a, b, c

        # Any given function is called via `maybeDeferred`. In this case, we
        # get an already-called Deferred, because `do_something` is
        # synchronous.
        timeout = randint(10, 100)
        d = deferWithTimeout(
            timeout, do_something, sentinel.a, sentinel.b, c=sentinel.c
        )
        assert isinstance(d, Deferred)
        assert (
            do_something,
            sentinel.a,
            (sentinel.b,),
            {"c": sentinel.c},
        ) == extract_result(d)

        # The timeout has already been cancelled.
        assert [] == clock.getDelayedCalls()


class TestCall:
    """Tests for `call`."""

    def test_without_arguments(self):
        func = Mock(return_value=sentinel.something)
        # The result going in is discarded; func's result is passed on.
        d = call(sentinel.result, func)
        assert extract_result(d) is sentinel.something
        func.mock_called_once_with()

    def test_with_arguments(self):
        func = Mock(return_value=sentinel.something)
        # The result going in is discarded; func's result is passed on.
        d = call(sentinel.r, func, sentinel.a, sentinel.b, c=sentinel.c)
        assert extract_result(d) is sentinel.something
        func.mock_called_once_with(sentinel.a, sentinel.b, c=sentinel.c)

    def test_does_not_suppress_errors(self):
        d = call(sentinel.result, operator.truediv, 0, 0)
        pytest.raises(ZeroDivisionError, extract_result, d)


class TestCallOut:
    """Tests for `callOut`."""

    def test_without_arguments(self):
        func = Mock()
        # The result is passed through untouched.
        d = callOut(sentinel.result, func)
        assert extract_result(d) is sentinel.result
        func.assert_called_once_with()

    def test_with_arguments(self):
        func = Mock()
        # The result is passed through untouched.
        d = callOut(sentinel.r, func, sentinel.a, sentinel.b, c=sentinel.c)
        assert extract_result(d) is sentinel.r
        func.mock_called_once_with(sentinel.a, sentinel.b, c=sentinel.c)

    def test_does_not_suppress_errors(self):
        d = callOut(sentinel.result, operator.truediv, 0, 0)
        pytest.raises(ZeroDivisionError, extract_result, d)


@pytest.mark.rack_reactor_guard
class TestCallOutToThread:
    """Tests for `callOutToThread`."""

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_without_arguments(self):
        func = Mock()
        # The result is passed through untouched.
        result = yield callOutToThread(sentinel.result, func)
        assert result is sentinel.result
        func.assert_called_once_with()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_with_arguments(self):
        func = Mock()
        # The result is passed through untouched.
        result = yield callOutToThread(
            sentinel.r, func, sentinel.a, sentinel.b, c=sentinel.c
        )
        assert result is sentinel.r
        func.mock_called_once_with(sentinel.a, sentinel.b, c=sentinel.c)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_does_not_suppress_errors(self):
        with pytest.raises(ZeroDivisionError):
            yield callOutToThread(sentinel.result, operator.truediv, 0, 0)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_defers_to_thread(self):
        threads = {threading.current_thread()}

        def captureThread():
            threads.add(threading.current_thread())

        yield callOutToThread(None, captureThread)
        assert len(threads) == 2, threads


@pytest.mark.rack_reactor_guard
class TestCallInReactor:
    """Tests for `callInReactor`."""

    def returnThreadIdent(self, *_, **__):
        return threading.get_ident()

    @wait_for(timeout=TIMEOUT)
    def test_without_arguments_from_reactor(self):
        func = Mock(side_effect=self.returnThreadIdent)
        result = callInReactor(func)
        assert threading.get_ident() == result
        func.assert_called_once_with()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_without_arguments_from_thread(self):
        func = Mock(side_effect=self.returnThreadIdent)
        result = yield deferToNewThread(callInReactor, func)
        assert threading.get_ident() == result
        func.assert_called_once_with()

    @wait_for(timeout=TIMEOUT)
    def test_with_arguments_in_reactor(self):
        func = Mock(side_effect=self.returnThreadIdent)
        result = callInReactor(func, sentinel.a, b=sentinel.b)
        assert threading.get_ident() == result
        func.assert_called_once_with(sentinel.a, b=sentinel.b)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_with_arguments_in_thread(self):
        func = Mock(side_effect=self.returnThreadIdent)
        result = yield deferToNewThread(
            callInReactor, func, sentinel.a, b=sentinel.b
        )
        assert threading.get_ident() == result
        func.assert_called_once_with(sentinel.a, b=sentinel.b)


@pytest.mark.rack_reactor_guard
class TestCallInReactorErrors:
    """Tests for error behaviour in `callInReactor`."""

    @wait_for(timeout=TIMEOUT)
    def test_propagates_exceptions_in_reactor(self):
        with pytest.raises(ZeroDivisionError):
            callInReactor(operator.truediv, 0, 0)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_propagates_exceptions_in_thread(self):
        with pytest.raises(ZeroDivisionError):
            yield deferToNewThread(callInReactor, operator.truediv, 0, 0)


@pytest.mark.rack_reactor_guard
class TestCallInReactorWithTimeout:
    """Tests for `callInReactorWithTimeout`."""

    @pytest.fixture(autouse=True)
    def _set_up(self, mocker):
        self.deferWithTimeout = mocker.patch.object(
            twisted_module, "deferWithTimeout"
        )
        self.deferWithTimeout.side_effect = self.returnThreadIdent

    def returnThreadIdent(self, *_, **__):
        return threading.get_ident()

    @wait_for(timeout=TIMEOUT)
    def test_without_arguments_from_reactor(self):
        result = callInReactorWithTimeout(sentinel.timeout, sentinel.func)
        assert threading.get_ident() == result
        self.deferWithTimeout.assert_called_once_with(
            sentinel.timeout, sentinel.func
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_without_arguments_from_thread(self):
        result = yield deferToNewThread(
            callInReactorWithTimeout, sentinel.timeout, sentinel.func
        )
        assert threading.get_ident() == result
        self.deferWithTimeout.assert_called_once_with(
            sentinel.timeout, sentinel.func
        )

    @wait_for(timeout=TIMEOUT)
    def test_with_arguments_in_reactor(self):
        result = callInReactorWithTimeout(
            sentinel.timeout, sentinel.func, sentinel.a, b=sentinel.b
        )
        assert threading.get_ident() == result
        self.deferWithTimeout.assert_called_once_with(
            sentinel.timeout, sentinel.func, sentinel.a, b=sentinel.b
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_with_arguments_in_thread(self):
        result = yield deferToNewThread(
            callInReactorWithTimeout,
            sentinel.timeout,
            sentinel.func,
            sentinel.a,
            b=sentinel.b,
        )
        assert threading.get_ident() == result
        self.deferWithTimeout.assert_called_once_with(
            sentinel.timeout, sentinel.func, sentinel.a, b=sentinel.b
        )


@pytest.mark.rack_reactor_guard
class TestCallInReactorWithTimeoutErrors:
    """Tests for error behaviour in `callInReactorWithTimeout`."""

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_propagates_exceptions_in_reactor(self):
        with pytest.raises(ZeroDivisionError):
            yield callInReactorWithTimeout(5.0, operator.truediv, 0, 0)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_propagates_exceptions_in_thread(self):
        with pytest.raises(ZeroDivisionError):
            yield deferToNewThread(
                callInReactorWithTimeout, 5.0, operator.truediv, 0, 0
            )


class TestDeferredValue:
    """Tests for `DeferredValue`."""

    def test_create(self):
        dvalue = DeferredValue()
        assert dvalue.waiters == set()
        assert dvalue.capturing is None
        assert dvalue.observing is None

    def test_get_returns_a_Deferred(self):
        dvalue = DeferredValue()
        assert isinstance(dvalue.get(), Deferred)

    def test_get_returns_a_Deferred_with_a_timeout(self):
        clock = self.mocker.patch.object(internet, "reactor", Clock())
        dvalue = DeferredValue()
        waiter = dvalue.get(10)
        assert isinstance(waiter, Deferred)
        assert not (waiter.called)
        clock.advance(9)
        assert isinstance(waiter, Deferred)
        assert not (waiter.called)
        clock.advance(1)
        pytest.raises(CancelledError, extract_result, waiter)

    def test_set_notifies_all_waiters(self):
        dvalue = DeferredValue()
        waiter1 = dvalue.get()
        waiter2 = dvalue.get()
        dvalue.set(sentinel.value)
        assert extract_result(waiter1) is sentinel.value
        assert extract_result(waiter2) is sentinel.value

    def test_set_notifies_all_waiters_that_have_not_timed_out(self):
        clock = self.mocker.patch.object(internet, "reactor", Clock())
        dvalue = DeferredValue()
        waiter0 = dvalue.get()
        waiter1 = dvalue.get(1)
        waiter2 = dvalue.get(3)
        clock.advance(2)
        dvalue.set(sentinel.value)
        assert extract_result(waiter0) is sentinel.value
        assert extract_result(waiter2) is sentinel.value
        pytest.raises(CancelledError, extract_result, waiter1)

    def test_set_clears_and_cancels_capturing(self):
        dvalue = DeferredValue()
        source = Deferred()
        dvalue.capturing = source
        dvalue.set(sentinel.value)
        assert dvalue.capturing is None
        pytest.raises(CancelledError, extract_result, source)

    def test_set_clears_observing(self):
        dvalue = DeferredValue()
        source = Deferred()
        dvalue.observing = source
        dvalue.set(sentinel.value)
        assert dvalue.observing is None
        assert not (source.called)

    def test_get_after_set_returns_the_value(self):
        dvalue = DeferredValue()
        dvalue.set(sentinel.value)
        waiter = dvalue.get()
        assert extract_result(waiter) is sentinel.value

    def test_get_can_be_cancelled(self):
        dvalue = DeferredValue()
        waiter = dvalue.get()
        waiter.cancel()
        pytest.raises(CancelledError, extract_result, waiter)
        assert set() == dvalue.waiters

    def test_set_can_only_be_called_once(self):
        dvalue = DeferredValue()
        dvalue.set(sentinel.value)
        pytest.raises(AlreadyCalledError, dvalue.set, sentinel.foobar)

    def test_cancel_stops_everything(self):
        dvalue = DeferredValue()
        waiter = dvalue.get()
        dvalue.cancel()
        pytest.raises(CancelledError, extract_result, waiter)
        pytest.raises(CancelledError, extract_result, dvalue.get())
        pytest.raises(AlreadyCalledError, dvalue.set, sentinel.value)

    def test_cancel_can_be_called_multiple_times(self):
        dvalue = DeferredValue()
        dvalue.cancel()
        pytest.raises(AlreadyCalledError, dvalue.set, sentinel.value)
        dvalue.cancel()
        pytest.raises(AlreadyCalledError, dvalue.set, sentinel.value)

    def test_cancel_does_nothing_if_value_already_set(self):
        dvalue = DeferredValue()
        dvalue.set(sentinel.value)
        dvalue.cancel()
        assert sentinel.value == extract_result(dvalue.get())

    def test_cancel_clears_and_cancels_capturing(self):
        dvalue = DeferredValue()
        source = Deferred()
        dvalue.capturing = source
        dvalue.cancel()
        assert dvalue.capturing is None
        pytest.raises(CancelledError, extract_result, source)

    def test_cancel_clears_observing(self):
        dvalue = DeferredValue()
        source = Deferred()
        dvalue.observing = source
        dvalue.cancel()
        assert dvalue.observing is None
        assert not (source.called)

    def test_set_exception_results_in_a_callback(self):
        exception = factory.make_exception()
        dvalue = DeferredValue()
        dvalue.set(exception)
        assert exception is dvalue.value

    def test_set_failure_results_in_an_errback(self):
        exception_type = factory.make_exception_type()
        dvalue = DeferredValue()
        dvalue.set(Failure(exception_type()))
        pytest.raises(exception_type, extract_result, dvalue.get())

    def test_fail_results_in_an_errback(self):
        exception_type = factory.make_exception_type()
        dvalue = DeferredValue()
        dvalue.fail(exception_type())
        pytest.raises(exception_type, extract_result, dvalue.get())

    def test_fail_None_results_in_an_errback_with_current_exception(self):
        exception_type = factory.make_exception_type()
        dvalue = DeferredValue()
        try:
            raise exception_type()
        except exception_type:
            dvalue.fail()
        pytest.raises(exception_type, extract_result, dvalue.get())

    def test_fail_can_only_be_called_once(self):
        exception = factory.make_exception()
        dvalue = DeferredValue()
        dvalue.fail(exception)
        pytest.raises(AlreadyCalledError, dvalue.fail, exception)

    def test_value_is_not_available_until_set(self):
        dvalue = DeferredValue()
        pytest.raises(AttributeError, lambda: dvalue.value)

    def test_capture_captures_callback(self):
        dvalue = DeferredValue()
        d = Deferred()
        dvalue.capture(d)
        waiter = dvalue.get()
        assert isinstance(waiter, Deferred)
        assert not (waiter.called)
        d.callback(sentinel.result)
        assert sentinel.result == extract_result(waiter)
        assert extract_result(d) is None

    def test_capture_captures_errback(self):
        dvalue = DeferredValue()
        d = Deferred()
        dvalue.capture(d)
        waiter = dvalue.get()
        assert isinstance(waiter, Deferred)
        assert not (waiter.called)
        exception = factory.make_exception()
        d.errback(exception)
        pytest.raises(type(exception), extract_result, waiter)
        assert extract_result(d) is None

    def test_capture_records_source_as_capturing_attribute(self):
        dvalue = DeferredValue()
        d = Deferred()
        dvalue.capture(d)
        assert d is dvalue.capturing

    def test_capture_can_only_be_called_once(self):
        dvalue = DeferredValue()
        d = Deferred()
        dvalue.capture(d)
        pytest.raises(AlreadyCalledError, dvalue.capture, d)
        # It's not possible to call observe() once capture() has been called.
        pytest.raises(AlreadyCalledError, dvalue.observe, d)

    def test_capture_cannot_be_called_once_value_is_set(self):
        dvalue = DeferredValue()
        dvalue.set(sentinel.value)
        pytest.raises(AlreadyCalledError, dvalue.capture, sentinel.unused)

    def test_observe_observes_callback(self):
        dvalue = DeferredValue()
        d = Deferred()
        dvalue.observe(d)
        waiter = dvalue.get()
        assert isinstance(waiter, Deferred)
        assert not (waiter.called)
        d.callback(sentinel.result)
        assert sentinel.result == extract_result(waiter)
        assert sentinel.result == extract_result(d)

    def test_observe_observes_errback(self):
        dvalue = DeferredValue()
        d = Deferred()
        dvalue.observe(d)
        waiter = dvalue.get()
        assert isinstance(waiter, Deferred)
        assert not (waiter.called)
        exception = factory.make_exception()
        d.errback(exception)
        pytest.raises(type(exception), extract_result, waiter)
        pytest.raises(type(exception), extract_result, d)

    def test_observe_records_source_as_observing_attribute(self):
        dvalue = DeferredValue()
        d = Deferred()
        dvalue.observe(d)
        assert d is dvalue.observing

    def test_observe_can_only_be_called_once(self):
        dvalue = DeferredValue()
        d = Deferred()
        dvalue.observe(d)
        pytest.raises(AlreadyCalledError, dvalue.observe, d)
        # It's not possible to call capture() once observe() has been called.
        pytest.raises(AlreadyCalledError, dvalue.capture, d)

    def test_observe_cannot_be_called_once_value_is_set(self):
        dvalue = DeferredValue()
        dvalue.set(sentinel.value)
        pytest.raises(AlreadyCalledError, dvalue.observe, sentinel.unused)

    def test_isSet_is_False_when_there_is_no_value(self):
        dvalue = DeferredValue()
        assert not (dvalue.isSet)

    def test_isSet_is_True_when_there_is_a_value(self):
        dvalue = DeferredValue()
        dvalue.set(sentinel.foobar)
        assert dvalue.isSet

    def test_isSet_is_True_when_there_is_a_failure(self):
        dvalue = DeferredValue()
        dvalue.fail(factory.make_exception())
        assert dvalue.isSet


class TestRPCFetcher:
    """Tests for `RPCFetcher`."""

    @pytest.fixture(autouse=True)
    def _set_up(self):
        self.fake_command = Mock(__name__="Command")

    def test_call_returns_deferred(self):
        client = Mock()
        fetcher = RPCFetcher()
        d = fetcher(client, self.fake_command, test=sentinel.kwarg_test)

        assert isinstance(d, Deferred)
        client.assert_called_once_with(
            self.fake_command, test=sentinel.kwarg_test
        )

    def test_deferred_fires_when_client_completes(self):
        client = Mock()
        client.return_value = Deferred()

        fetcher = RPCFetcher()
        d = fetcher(client, self.fake_command, test=sentinel.kwarg_test)

        assert isinstance(d, Deferred)
        assert not (d.called)
        client.return_value.callback(sentinel.content)
        assert d.called
        assert extract_result(d) is sentinel.content
        assert client not in fetcher.pending

    def test_concurrent_gets_become_related(self):
        client = Mock()
        client.return_value = Deferred()

        fetcher = RPCFetcher()
        d1 = fetcher(client, self.fake_command, test=sentinel.kwarg_test)
        d2 = fetcher(client, self.fake_command, test=sentinel.kwarg_test)

        assert isinstance(d1, Deferred)
        assert not (d1.called)
        assert isinstance(d2, Deferred)
        assert not (d2.called)
        assert d1 is not d2

        client.return_value.callback(sentinel.content)
        assert extract_result(d1) is sentinel.content
        assert extract_result(d2) is sentinel.content

    def test_non_concurrent_gets_do_not_become_related(self):
        client_d1, client_d2 = Deferred(), Deferred()

        client = Mock()
        client.side_effect = [client_d1, client_d2]

        fetcher = RPCFetcher()

        d1 = fetcher(client, self.fake_command, test=sentinel.kwarg_test)
        assert isinstance(d1, Deferred)
        assert not (d1.called)
        client_d1.callback(sentinel.foo)
        assert extract_result(d1) is sentinel.foo

        d2 = fetcher(client, self.fake_command, test=sentinel.kwarg_test)
        assert isinstance(d2, Deferred)
        assert not (d2.called)
        client_d2.callback(sentinel.bar)
        assert extract_result(d2) is sentinel.bar

    def test_errors_are_treated_just_the_same(self):
        client = Mock()
        client.return_value = Deferred()

        fetcher = RPCFetcher()
        d1 = fetcher(client, self.fake_command, test=sentinel.kwarg_test)
        d2 = fetcher(client, self.fake_command, test=sentinel.kwarg_test)

        exception_type = factory.make_exception_type()
        client.return_value.errback(exception_type())

        pytest.raises(exception_type, extract_result, d1)
        pytest.raises(exception_type, extract_result, d2)

    def test_clients_are_treated_differently(self):
        client1_d, client2_d = Deferred(), Deferred()

        client1 = Mock()
        client1.return_value = client1_d
        client2 = Mock()
        client2.return_value = client2_d

        fetcher = RPCFetcher()

        d1 = fetcher(client1, self.fake_command, test=sentinel.kwarg_test)
        assert isinstance(d1, Deferred)
        assert not (d1.called)
        client1_d.callback(sentinel.foo)
        assert extract_result(d1) is sentinel.foo

        d2 = fetcher(client2, self.fake_command, test=sentinel.kwarg_test)
        assert isinstance(d2, Deferred)
        assert not (d2.called)
        client2_d.callback(sentinel.bar)
        assert extract_result(d2) is sentinel.bar


@pytest.mark.rack_reactor_guard
class TestDeferToNewThread:
    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_runs_given_func_in_new_thread(self):
        def thing_to_call(*args, **kwargs):
            thread = threading.current_thread()
            return thread, args, kwargs

        thread, args, kwargs = yield deferToNewThread(
            thing_to_call, sentinel.arg, thing=sentinel.kwarg
        )

        assert thread is not threading.current_thread()
        assert args == (sentinel.arg,)
        assert kwargs == {"thing": sentinel.kwarg}

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_gives_new_thread_informative_name(self):
        def get_name_of_thread():
            return threading.current_thread().name

        name = yield deferToNewThread(get_name_of_thread)
        assert "deferToNewThread(get_name_of_thread)" == name

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_gives_new_thread_generic_name_if_func_has_no_name(self):
        def get_name_of_thread():
            return threading.current_thread().name

        # Mocks don't have a __name__ property by default.
        func = Mock(side_effect=get_name_of_thread)

        name = yield deferToNewThread(func)
        assert "deferToNewThread(...)" == name

    @wait_for(timeout=TIMEOUT)
    def test_propagates_context_into_thread(self):
        name = factory.make_name("name")
        value = factory.make_name("value")

        def check_context_in_thread():
            assert value == context.get(name)

        return context.call(
            {name: value}, deferToNewThread, check_context_in_thread
        )

    @wait_for(timeout=TIMEOUT)
    def test_propagates_context_into_callback_from_thread(self):
        name = factory.make_name("name")
        value = factory.make_name("value")

        def do_nothing():
            pass

        def check_context_in_callback(_):
            assert value == context.get(name)

        d = context.call({name: value}, deferToNewThread, do_nothing)
        d.addCallbacks(check_context_in_callback, pytest.fail)
        return d

    @wait_for(timeout=TIMEOUT)
    def test_propagates_context_into_errback_from_thread(self):
        name = factory.make_name("name")
        value = factory.make_name("value")

        def break_something():
            0 / 0  # noqa: B018

        def check_context_in_errback(_):
            assert value == context.get(name)

        d = context.call({name: value}, deferToNewThread, break_something)
        d.addCallbacks(pytest.fail, check_context_in_errback)
        return d


class ThreadUnpoolMixin:
    """Helpers for testing `ThreadUnpool`."""

    def make_semaphore(self, tokens=1):
        lock = DeferredSemaphore(1)

        def assert_empty_waiting():
            assert len(lock.waiting) == 0, lock.waiting

        def assert_tokens_at_limit():
            assert lock.tokens == lock.limit, (
                f"Tokens {lock.tokens} ain't at the limit {lock.limit}"
            )

        self.request.addfinalizer(partial(assert_empty_waiting))
        self.request.addfinalizer(partial(assert_tokens_at_limit))
        return lock


@pytest.mark.rack_reactor_guard
class TestThreadUnpool(ThreadUnpoolMixin):
    """Tests for `ThreadUnpool`."""

    def test_init(self):
        lock = self.make_semaphore()
        unpool = ThreadUnpool(lock)
        assert unpool.lock is lock

    def test_start_sets_started(self):
        unpool = ThreadUnpool(sentinel.lock)
        assert unpool.started is None
        unpool.start()
        assert unpool.started

    def test_stop_unsets_started(self):
        unpool = ThreadUnpool(sentinel.lock)
        assert unpool.started is None
        unpool.stop()
        assert not (unpool.started)

    @wait_for(timeout=TIMEOUT)
    def test_callInThreadWithCallback_makes_callback(self):
        lock = self.make_semaphore()
        unpool = ThreadUnpool(lock)
        callback = Mock()
        d = unpool.callInThreadWithCallback(callback, lambda: sentinel.thing)
        d.addCallback(
            callOut,
            callback.assert_called_once_with,
            True,
            sentinel.thing,
        )
        return d

    @wait_for(timeout=TIMEOUT)
    def test_callInThreadWithCallback_makes_callback_on_error(self):
        lock = self.make_semaphore()
        unpool = ThreadUnpool(lock)
        callback = Mock()
        failure = Failure(factory.make_exception())
        d = unpool.callInThreadWithCallback(callback, lambda: failure)
        d.addCallback(
            callOut,
            callback.assert_called_once_with,
            False,
            failure,
        )
        return d

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_callInThreadWithCallback_logs_failure_reporting_result(self):
        unpool = ThreadUnpool(self.make_semaphore())
        onResult = Mock(side_effect=factory.make_exception())
        with TwistedLoggerFixture() as logger:
            yield unpool.callInThreadWithCallback(onResult, return_args)

        assert logger.output.startswith(
            "Failure reporting result from thread.\nTraceback (most recent call last):\n"
        ), logger.output

        assert "maastesting.factory.TestException#" in logger.output


@pytest.mark.rack_reactor_guard
class TestThreadUnpoolCommonBehaviour(ThreadUnpoolMixin):
    """Tests for `ThreadUnpool`.

    These test behaviour that's common between `callInThread` and
    `callInThreadWithCallback`.
    """

    scenarios = (
        (
            "callInThread",
            dict(
                method=lambda unpool, func, *args, **kw: (
                    unpool.callInThread(func, *args, **kw)
                )
            ),
        ),
        (
            "callInThreadWithCallback",
            dict(
                method=lambda unpool, func, *args, **kw: (
                    unpool.callInThreadWithCallback(None, func, *args, **kw)
                )
            ),
        ),
    )

    @wait_for(timeout=TIMEOUT)
    def test_passes_args_through(self, scenario):
        lock = self.make_semaphore()
        unpool = ThreadUnpool(lock)
        func = Mock(__name__="fred")
        func.return_value = None
        d = self.method(unpool, func, sentinel.arg, kwarg=sentinel.kwarg)
        d.addCallback(
            callOut,
            func.assert_called_once_with,
            sentinel.arg,
            kwarg=sentinel.kwarg,
        )
        return d

    def test_defers_to_new_thread(self, scenario):
        lock = self.make_semaphore()
        unpool = ThreadUnpool(lock)
        deferToNewThread = _patch(
            self.mocker, twisted_module, "deferToNewThread"
        )
        deferToNewThread.return_value = succeed(None)
        d = self.method(unpool, sentinel.func)
        assert isinstance(d, Deferred)
        assert d.called
        deferToNewThread.assert_called_once_with(sentinel.func)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_logs_failure_deferring_to_thread(self, scenario):
        lock = self.make_semaphore()
        # Have to manually schedule the lock release, since mocking
        # `deferToNewThread` will prevent the `addBoth` line in
        # callInThreadWithCallback.callInThreadWithLock
        self.request.addfinalizer(partial(lock.release))
        unpool = ThreadUnpool(lock)
        deferToNewThread = _patch(
            self.mocker, twisted_module, "deferToNewThread"
        )
        deferToNewThread.side_effect = factory.make_exception()
        with TwistedLoggerFixture() as logger:
            yield self.method(unpool, sentinel.func)

        assert logger.output.startswith(
            "Failure when calling out to thread.\nTraceback (most recent call last):"
        )
        assert "maastesting.factory.TestException#" in logger.output

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_context_is_active_in_new_thread(self, scenario):
        steps = []
        threads = []

        class Context:
            def __enter__(self):
                steps.append("__enter__")
                ct = threading.current_thread()
                threads.append(ct.ident)

            def __exit__(self, *exc_info):
                steps.append("__exit__")
                ct = threading.current_thread()
                threads.append(ct.ident)

        def function():
            steps.append("function")
            ct = threading.current_thread()
            threads.append(ct.ident)

        unpool = ThreadUnpool(self.make_semaphore(), Context)
        yield self.method(unpool, function)

        # The context was active when the function was called.
        assert ["__enter__", "function", "__exit__"] == steps
        # All steps happened in the same thread.
        assert len(set(threads)) == 1, threads
        # That thread was not this thread.
        current_thread = threading.current_thread()
        assert current_thread.ident not in threads


class ContextBrokenOnEntry:
    def __init__(self, exception):
        super().__init__()
        self.exception = exception

    def __enter__(self):
        raise self.exception

    def __exit__(self, *exc_info):
        pass


class ContextBrokenOnExit:
    def __init__(self, exception):
        super().__init__()
        self.exception = exception

    def __enter__(self):
        pass

    def __exit__(self, *exc_info):
        raise self.exception


@pytest.mark.rack_reactor_guard
class TestThreadPool:
    """Tests for `ThreadPool`."""

    def test_init(self):
        pool = ThreadPool()
        assert pool.min == 5
        assert pool.max == 20
        assert pool.name is None
        assert isinstance(pool.context, twisted_module.ThreadWorkerContext)
        assert pool.context.contextFactory is twisted_module.NullContext

    def test_init_with_parameters(self):
        minthreads = randint(0, 100)
        maxthreads = randint(100, 200)
        pool = ThreadPool(
            minthreads=minthreads,
            maxthreads=maxthreads,
            name=sentinel.name,
            contextFactory=sentinel.contextFactory,
        )
        assert pool.min == minthreads
        assert pool.max == maxthreads
        assert pool.name is sentinel.name
        assert isinstance(pool.context, twisted_module.ThreadWorkerContext)
        assert pool.context.contextFactory is sentinel.contextFactory

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_context_entry_failures_are_propagated_to_tasks(self):
        exception = factory.make_exception()

        pool = ThreadPool(
            contextFactory=partial(ContextBrokenOnEntry, exception),
            minthreads=1,
            maxthreads=1,
        )
        self.request.addfinalizer(partial(stop_pool_if_running, pool))
        pool.start()

        with pytest.raises(type(exception)):
            yield deferToThreadPool(reactor, pool, lambda: None)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_context_exit_failures_are_logged(self):
        exception = factory.make_exception()

        pool = ThreadPool(
            contextFactory=partial(ContextBrokenOnExit, exception),
            minthreads=1,
            maxthreads=1,
        )
        self.request.addfinalizer(partial(stop_pool_if_running, pool))
        pool.start()

        result = yield deferToThreadPool(reactor, pool, lambda: sentinel.foo)
        assert result is sentinel.foo

        with TwistedLoggerFixture() as logger:
            pool.stop()

        assert logger.output.startswith(
            "Failure exiting worker context.\nTraceback (most recent call last):"
        )
        assert "maastesting.factory.TestException#" in logger.output

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_trace_id_is_generated_and_propagated(self):
        self.request.addfinalizer(partial(set_trace_id, ""))
        set_trace_id("")
        trace_id = get_trace_id()
        pool = ThreadPool(
            minthreads=1,
            maxthreads=1,
        )
        self.request.addfinalizer(partial(stop_pool_if_running, pool))
        pool.start()

        def _extract_trace_id_in_thread():
            return get_trace_id()

        result = yield deferToThreadPool(
            reactor, pool, _extract_trace_id_in_thread
        )
        assert result is not trace_id

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_trace_id_is_copied_if_present(self):
        self.request.addfinalizer(partial(set_trace_id, ""))
        set_trace_id("test-trace-id")
        pool = ThreadPool(
            minthreads=1,
            maxthreads=1,
        )
        self.request.addfinalizer(partial(stop_pool_if_running, pool))
        pool.start()

        def _extract_trace_id_in_thread():
            return get_trace_id()

        result = yield deferToThreadPool(
            reactor, pool, _extract_trace_id_in_thread
        )
        assert result == "test-trace-id"


def stop_pool_if_running(pool):
    """Stop the given thread-pool if it's running."""
    if pool.started:
        pool.stop()


@pytest.mark.rack_reactor_guard
class TestThreadPoolCommonBehaviour:
    """Tests for `ThreadPool`.

    These test behaviour that's common between `callInThread` and
    `callInThreadWithCallback`.
    """

    scenarios = (
        (
            "callInThread",
            dict(
                method=lambda pool, func, *args, **kw: (
                    pool.callInThread(func, *args, **kw)
                )
            ),
        ),
        (
            "callInThreadWithCallback",
            dict(
                method=lambda pool, func, *args, **kw: (
                    pool.callInThreadWithCallback(None, func, *args, **kw)
                )
            ),
        ),
    )

    def test_context_is_active_in_new_thread(self, scenario):
        steps = []
        threads = []

        class Context:
            def __enter__(self):
                steps.append("__enter__")
                ct = threading.current_thread()
                threads.append(ct.ident)

            def __exit__(self, *exc_info):
                steps.append("__exit__")
                ct = threading.current_thread()
                threads.append(ct.ident)

        def function():
            steps.append("function")
            ct = threading.current_thread()
            threads.append(ct.ident)

        pool = ThreadPool(minthreads=1, maxthreads=1, contextFactory=Context)

        pool.start()
        try:
            self.method(pool, function)
            self.method(pool, function)
        finally:
            pool.stop()

        # The context was active when the function was called both times, and
        # wasn't exited and re-entered in-between.
        assert ["__enter__", "function", "function", "__exit__"] == steps
        # All steps happened in the same thread.
        assert len(set(threads)) == 1
        # That thread was not this thread.
        current_thread = threading.current_thread()
        assert current_thread.ident not in threads


class DummyThreadPool:
    start = sentinel.start
    started = sentinel.started
    stop = sentinel.stop


@pytest.mark.rack_reactor_guard
class TestThreadPoolLimiter:
    """Tests for `ThreadPoolLimiter`."""

    def test_init(self):
        pool_beneath = DummyThreadPool()
        pool = ThreadPoolLimiter(pool_beneath, sentinel.lock)
        assert pool.pool is pool_beneath
        assert pool.lock is sentinel.lock
        assert pool.start is pool.pool.start
        assert pool.started is pool.pool.started
        assert pool.stop is pool.pool.stop

    def make_pool(self):
        # Create a pool limited to one thread, with an underlying pool that
        # allows a greater number of concurrent threads so it won't interfere
        # with the test.
        pool_beneath = ThreadUnpool(DeferredSemaphore(2))
        pool = ThreadPoolLimiter(pool_beneath, DeferredSemaphore(1))
        return pool

    def test_callInThread_calls_callInThreadWithCallback(self):
        pool = self.make_pool()
        self.mocker.patch.object(
            pool, "callInThreadWithCallback", autospec=True
        )
        pool.callInThreadWithCallback.return_value = sentinel.called
        pool.callInThread(sentinel.func, sentinel.arg, kwarg=sentinel.kwarg)
        pool.callInThreadWithCallback.assert_called_once_with(
            None, sentinel.func, sentinel.arg, kwarg=sentinel.kwarg
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_without_callback_acquires_and_releases_lock(self):
        pool = self.make_pool()  # Limit to a single thread.
        # Callback from a thread.
        d = Deferred()

        def function():
            reactor.callFromThread(d.callback, sentinel.done)
            return sentinel.result

        pool.callInThreadWithCallback(None, function)
        assert (yield d) is sentinel.done
        # The lock has not yet been released.
        assert 0 == pool.lock.tokens
        # Wait and it shall be released.
        yield pool.lock.run(noop)
        assert 1 == pool.lock.tokens

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_with_callback_acquires_and_releases_lock(self):
        pool = self.make_pool()  # Limit to a single thread.
        # Callback from a thread.
        d, callback = Deferred(), Mock()

        def function():
            reactor.callFromThread(d.callback, sentinel.done)
            return sentinel.result

        pool.callInThreadWithCallback(callback, function)
        assert (yield d) is sentinel.done
        # The lock has not yet been released.
        assert 0 == pool.lock.tokens
        # Wait and it shall be released.
        yield pool.lock.run(noop)
        assert 1 == pool.lock.tokens
        # The callback has also been called.
        callback.assert_called_once_with(True, sentinel.result)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_without_callback_releases_lock_when_underlying_pool_breaks(self):
        pool = self.make_pool()  # Limit to a single thread.

        exception_type = factory.make_exception_type()
        citwc = self.mocker.patch.object(
            pool.pool, "callInThreadWithCallback", autospec=True
        )
        citwc.side_effect = exception_type

        with TwistedLoggerFixture() as logger:
            yield pool.callInThreadWithCallback(None, noop)

        # Wait and it shall be released.
        yield pool.lock.run(noop)
        assert 1 == pool.lock.tokens

        # An alarming message is logged.
        assert logger.output.startswith(
            "Critical failure arranging call in thread\nTraceback (most recent call last):"
        )
        assert "maastesting.factory.TestException#" in logger.output

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_with_callback_releases_lock_when_underlying_pool_breaks(self):
        pool = self.make_pool()  # Limit to a single thread.

        exception_type = factory.make_exception_type()
        citwc = self.mocker.patch.object(
            pool.pool, "callInThreadWithCallback", autospec=True
        )
        citwc.side_effect = exception_type

        callback = Mock()
        with TwistedLoggerFixture() as logger:
            yield pool.callInThreadWithCallback(callback, noop)

        # Wait and it shall be released.
        yield pool.lock.run(noop)
        assert 1 == pool.lock.tokens

        # Nothing is logged...
        assert "" == logger.output
        # ... but the callback has been called.
        callback.assert_called_once_with(False, ANY)
        [success, result] = callback.call_args[0]
        assert isinstance(result, Failure)
        assert isinstance(result.value, exception_type)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_when_deferring_acquires_and_releases_lock(self):
        pool = self.make_pool()
        # Within the thread the lock had been acquired.
        tokens_in_thread = yield deferToThreadPool(
            reactor, pool, lambda: pool.lock.tokens
        )
        assert 0 == tokens_in_thread
        # The lock has not yet been released.
        assert 0 == pool.lock.tokens
        # Wait and it shall be released.
        yield pool.lock.run(noop)
        assert 1 == pool.lock.tokens

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_when_deferring_acquires_and_releases_lock_on_error(self):
        pool = self.make_pool()
        # Within the thread the lock had been acquired.
        with pytest.raises(ZeroDivisionError):
            yield deferToThreadPool(reactor, pool, lambda: 0 / 0)
        # The lock has not yet been released.
        assert 0 == pool.lock.tokens
        # Wait and it shall be released.
        yield pool.lock.run(noop)
        assert 1 == pool.lock.tokens


@pytest.mark.rack_reactor_guard
class TestMakeDeferredWithProcessProtocol:
    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_calls_callback_when_processended_called_with_none(self):
        d, protocol = makeDeferredWithProcessProtocol()
        protocol.processEnded(None)
        result = yield d
        assert result is None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_calls_callback_when_process_called_with_processdone(self):
        d, protocol = makeDeferredWithProcessProtocol()
        protocol.processEnded(Failure(ProcessDone(0)))
        result = yield d
        assert result is None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_calls_errback_when_processEnded_called_with_failure(self):
        d, protocol = makeDeferredWithProcessProtocol()
        exception = factory.make_exception()
        protocol.processEnded(Failure(exception))
        with pytest.raises(type(exception)):
            yield d


# A script that prints the signals it receives, as long as they're SIGTERM or
# SIGQUIT. It prints "Ready." on stderr once it's registered signal handlers.

# This sets itself as process group leader.
signal_printer_pgl = """\
from os import setpgrp
from signal import Signals, signal
from sys import stderr
from time import sleep
from traceback import print_exc

def print_signal(signum, frame):
    print(Signals(signum).name, flush=True)

signal(Signals.SIGTERM, print_signal)
signal(Signals.SIGQUIT, print_signal)

setpgrp()

print("Ready.", file=stderr, flush=True)

sleep(5.0)
"""

# This variant should be identical, except that it does
# not set itself as process group leader.
signal_printer = """\
from signal import Signals, signal
from sys import stderr
from time import sleep
from traceback import print_exc

def print_signal(signum, frame):
    print(Signals(signum).name, flush=True)

signal(Signals.SIGTERM, print_signal)
signal(Signals.SIGQUIT, print_signal)

print("Ready.", file=stderr, flush=True)

sleep(5.0)
"""


class SignalPrinterProtocol(ProcessProtocol):
    """Process protocol for use with `signal_printer`."""

    def __init__(self):
        super().__init__()
        self.ready = Deferred()
        self.done = Deferred()
        self.out = io.BytesIO()
        self.err = io.BytesIO()

    def outReceived(self, data):
        self.out.write(data)

    def errReceived(self, data):
        self.err.write(data)
        if not self.ready.called:
            self.ready.callback(data)

    def processEnded(self, reason):
        self.done.callback(reason)


@pytest.mark.rack_reactor_guard
class TestTerminateProcess:
    """Tests for `terminateProcess`."""

    @pytest.fixture(autouse=True)
    def _set_up(self, mocker):
        assert twisted_module._os_kill is os.kill
        mocker.patch.object(
            twisted_module, "_os_kill", Mock(wraps=twisted_module._os_kill)
        )
        assert twisted_module._os_killpg is os.killpg
        mocker.patch.object(
            twisted_module, "_os_killpg", Mock(wraps=twisted_module._os_killpg)
        )

    def startSignalPrinter(self, protocol, *, pgrp=False):
        script_filename = factory.make_file(
            str(self.tmp_path),
            "sigprint.py",
            signal_printer_pgl if pgrp else signal_printer,
        )

        assert isinstance(protocol, SignalPrinterProtocol)
        self.request.addfinalizer(
            partial(
                _record_process_output,
                self.request,
                "out",
                protocol,
                protocol.out,
            )
        )
        self.request.addfinalizer(
            partial(
                _record_process_output,
                self.request,
                "err",
                protocol,
                protocol.err,
            )
        )
        python = sys.executable.encode("utf-8")
        process = reactor.spawnProcess(
            protocol, python, (python, script_filename.encode("utf-8"))
        )

        # Wait for the spawned subprocess to tell us that it's ready.
        def cbReady(message):
            assert "Ready.\n" == message.decode("utf-8")
            return process

        return protocol.ready.addCallback(cbReady)

    def terminateSignalPrinter(self, process, protocol):
        # Terminate with some short timings; no point waiting long in a test,
        # and we need to do it before the subprocess finishes sleeping.
        terminateProcess(
            process.pid, protocol.done, quit_after=0.1, kill_after=0.2
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_terminates_process_with_TERM_QUIT_then_KILL(self):
        protocol = SignalPrinterProtocol()
        process = yield self.startSignalPrinter(protocol)
        self.terminateSignalPrinter(process, protocol)
        # The subprocess is terminated with SIGKILL but received SIGTERM then
        # SIGQUIT prior to that.
        try:
            yield protocol.done
        except ProcessTerminated as reason:
            assert isinstance(reason, ProcessTerminated)
            assert signal.SIGKILL == reason.signal
            assert ["SIGTERM", "SIGQUIT"] == protocol.out.getvalue().decode(
                "utf-8"
            ).split()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_terminates_with_kill_and_killpg(self):
        protocol = SignalPrinterProtocol()
        process = yield self.startSignalPrinter(protocol, pgrp=True)
        # Capture the pid now; it gets cleared when the process exits.
        pid = process.pid
        # Terminate and wait for it to exit.
        self.terminateSignalPrinter(process, protocol)
        yield protocol.done.addErrback(suppress, ProcessTerminated)
        # os.kill was called once then os.killpg was called twice because the
        # subprocess made itself a process group leader.
        twisted_module._os_kill.assert_called_once_with(pid, signal.SIGTERM)
        twisted_module._os_killpg.assert_has_calls(
            [mock.call(pid, signal.SIGQUIT), mock.call(pid, signal.SIGKILL)]
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_terminates_with_kill_if_not_in_separate_process_group(self):
        protocol = SignalPrinterProtocol()
        process = yield self.startSignalPrinter(protocol, pgrp=False)
        # Capture the pid now; it gets cleared when the process exits.
        pid = process.pid
        # Terminate and wait for it to exit.
        self.terminateSignalPrinter(process, protocol)
        yield protocol.done.addErrback(suppress, ProcessTerminated)
        # os.kill was called 3 times because the subprocess did not make
        # itself a process group leader.
        twisted_module._os_kill.assert_has_calls(
            [
                mock.call(pid, signal.SIGTERM),
                mock.call(pid, signal.SIGQUIT),
                mock.call(pid, signal.SIGKILL),
            ]
        )
        twisted_module._os_killpg.assert_not_called()


class TestReducedWebLogFormatter:
    """Tests for `reducedWebLogFormatter`."""

    ipv4_address = factory.make_ipv4_address()
    ipv6_address = factory.make_ipv6_address()
    simple_http_url = factory.make_simple_http_url()
    simple_uri = factory.make_absolute_path()
    agent_name = factory.make_name("agent")
    status = factory.make_status_code()

    scenarios_methods = (
        ("no-method", {"method": None, "method_expected": "???"}),
        ("method", {"method": "GET", "method_expected": "GET"}),
    )

    scenarios_clients = (
        ("no-client", {"client": None, "client_expected": "-"}),
        (
            "ipv4-client",
            {"client": ipv4_address, "client_expected": ipv4_address},
        ),
        (
            "ipv6-client",
            {"client": ipv6_address, "client_expected": ipv6_address},
        ),
        (
            "ipv4-mapped-client",
            {
                "client": "::ffff:" + ipv4_address,
                "client_expected": ipv4_address,
            },
        ),
    )

    scenarios_referrers = (
        ("no-referrer", {"referrer": None, "referrer_expected": "-"}),
        (
            "referrer",
            {
                "referrer": simple_http_url,
                "referrer_expected": simple_http_url,
            },
        ),
    )

    scenarios_agents = (
        ("no-agent", {"agent": None, "agent_expected": "-"}),
        ("agent", {"agent": agent_name, "agent_expected": agent_name}),
    )

    scenarios_uris = (
        ("no-uri", {"uri": None, "uri_expected": "-"}),
        ("uri", {"uri": simple_uri, "uri_expected": simple_uri}),
    )

    scenarios_statuses = (
        ("no-status", {"status": None, "status_expected": "???"}),
        (
            "status",
            {
                "status": status.value,
                "status_expected": "%d %s" % (status.value, status.name),
            },
        ),
        ("status-unknown", {"status": 678, "status_expected": "678"}),
    )

    scenarios_types = (
        ("plain", {"prep": lambda string: string}),
        (
            "bytes",
            {
                "prep": lambda string: (
                    None if string is None else string.encode("ascii")
                )
            },
        ),
    )

    scenarios = _expand_scenarios(
        scenarios_methods,
        scenarios_clients,
        scenarios_referrers,
        scenarios_agents,
        scenarios_uris,
        scenarios_statuses,
        scenarios_types,
    )

    def test_renders_full_request(self, scenario):
        request = requesthelper.DummyRequest("foo/bar")
        request.method = self.prep(self.method)
        request.client = address.IPv4Address(
            "TCP", self.prep(self.client), 12345
        )
        referer = self.prep(self.referrer)
        if referer is not None:
            request.requestHeaders.addRawHeader("referer", referer)
        user_agent = self.prep(self.agent)
        if user_agent is not None:
            request.requestHeaders.addRawHeader("user-agent", user_agent)
        request.uri = self.prep(self.uri)
        request.code = self.status

        assert reducedWebLogFormatter(
            sentinel.timestamp, request
        ) == "%s %s %s HTTP/1.0 --> %s (referrer: %s; agent: %s)" % (
            self.client_expected,
            self.method_expected,
            self.uri_expected,
            self.status_expected,
            self.referrer_expected,
            self.agent_expected,
        )


TestAsynchronousDecoratorWithTimeoutDefined = _parametrize_scenarios(
    TestAsynchronousDecoratorWithTimeoutDefined
)
TestThreadUnpoolCommonBehaviour = _parametrize_scenarios(
    TestThreadUnpoolCommonBehaviour
)
TestThreadPoolCommonBehaviour = _parametrize_scenarios(
    TestThreadPoolCommonBehaviour
)

TestReducedWebLogFormatter = _parametrize_scenarios(TestReducedWebLogFormatter)
