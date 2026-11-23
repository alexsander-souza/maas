# Copyright 2014-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for asynchronous utilities."""

from functools import partial
import random
import threading
from time import time
from unittest.mock import call, Mock, sentinel

import pytest
from twisted.internet import reactor
from twisted.internet.defer import Deferred
from twisted.internet.task import deferLater
from twisted.python.failure import Failure
from twisted.python.threadable import isInIOThread

from maasserver.exceptions import IteratorReusedError
from maasserver.testing.orm import PostCommitHooksTestMixin
from maasserver.utils import asynchronous
from maasserver.utils.asynchronous import DeferredHooks
from maastesting.crochet import wait_for
from maastesting.factory import factory
from maastesting.twisted import extract_result, TwistedLoggerFixture


class TestGather:
    def test_gather_nothing(self):
        time_before = time()
        results = list(asynchronous.gather([], timeout=10))
        time_after = time()
        assert [] == results
        # gather() should return well within 9 seconds; this shows
        # that the call is not timing out.
        assert time_after - time_before < 9


@pytest.mark.parametrize(
    "wrap",
    [
        lambda call: call,
        lambda call: partial(deferLater, reactor, 0, call),
    ],
    ids=["synchronous", "asynchronous"],
)
class TestGatherScenarios:
    def test_gather_from_calls_without_errors(self, wrap):
        values = [random.randint(0, 1000000), factory.make_name("test")]
        calls = [wrap(lambda v=value: v) for value in values]
        results = list(asynchronous.gather(calls))
        assert set(values) == set(results)

    def test_gatherCallResults_returns_use_once_iterator(self, wrap):
        calls = []
        results = asynchronous.gatherCallResults(calls)
        assert isinstance(results, asynchronous.UseOnceIterator)

    def test_gather_from_calls_with_errors(self, wrap):
        calls = [(lambda: sentinel.okay), (lambda: 1 / 0)]  # ZeroDivisionError
        calls = [wrap(call) for call in calls]
        results = list(asynchronous.gather(calls))

        assert sentinel.okay in results
        results.remove(sentinel.okay)
        assert len(results) == 1
        failure = results[0]
        assert isinstance(failure, Failure)
        assert failure.type is ZeroDivisionError

    def test_gatherCallResults_yields_call_result_tuples(self, wrap):
        values = [random.randint(0, 1000000), factory.make_name("test")]
        calls = [wrap(lambda v=value: v) for value in values]
        results = list(asynchronous.gatherCallResults(calls))
        expected_results = [(calls[0], values[0]), (calls[1], values[1])]
        assert {id(call): value for call, value in expected_results} == {
            id(call): value for call, value in results
        }


class TestUseOnceIterator:
    def test_returns_correct_items_for_list(self):
        expected_values = list(range(10))
        iterator = asynchronous.UseOnceIterator(expected_values)
        actual_values = [val for val in iterator]
        assert expected_values == actual_values

    def test_raises_stop_iteration(self):
        iterator = asynchronous.UseOnceIterator([])
        with pytest.raises(StopIteration):
            iterator.__next__()

    def test_raises_iterator_reused(self):
        iterator = asynchronous.UseOnceIterator([])
        # Loop over the iterator to get to the point where we might try
        # and reuse it.
        list(iterator)
        with pytest.raises(IteratorReusedError):
            iterator.__next__()


class TestDeferredHooks(PostCommitHooksTestMixin):
    def test_is_thread_local(self):
        dhooks = DeferredHooks()
        queues = []
        for _ in range(3):
            thread = threading.Thread(
                target=lambda: queues.append(dhooks.hooks)
            )
            thread.start()
            thread.join()
        assert len(queues) == 3
        # Each queue is distinct (deque is unhashable; use the id() of each).
        assert len({id(q) for q in queues}) == 3

    def test_add_appends_Deferred_to_queue(self):
        dhooks = DeferredHooks()
        assert len(dhooks.hooks) == 0
        dhooks.add(Deferred())
        assert len(dhooks.hooks) == 1

    def test_add_cannot_be_called_in_the_reactor(self):
        dhooks = DeferredHooks()
        add_in_reactor = wait_for()(dhooks.add)  # Wait 30 seconds.
        with pytest.raises(AssertionError):
            add_in_reactor(Deferred())

    def test_fire_calls_hooks(self):
        dhooks = DeferredHooks()
        ds = Deferred(), Deferred()
        for d in ds:
            dhooks.add(d)
        dhooks.fire()
        for d in ds:
            assert extract_result(d) is None

    def test_fire_calls_hooks_in_reactor(self):
        def validate_in_reactor(_):
            assert isInIOThread()

        dhooks = DeferredHooks()
        d = Deferred()
        d.addCallback(validate_in_reactor)
        dhooks.add(d)
        dhooks.fire()
        assert d.called

    def test_fire_propagates_error_from_hook(self):
        error = factory.make_exception()
        dhooks = DeferredHooks()
        d = Deferred()
        d.addCallback(lambda _: Failure(error))
        dhooks.add(d)
        with pytest.raises(type(error)):
            dhooks.fire()

    def test_fire_always_consumes_all_hooks(self):
        dhooks = DeferredHooks()
        d1, d2 = Deferred(), Deferred()
        d1.addCallback(lambda _: 0 / 0)  # d1 will fail.
        dhooks.add(d1)
        dhooks.add(d2)
        with pytest.raises(ZeroDivisionError):
            dhooks.fire()
        assert len(dhooks.hooks) == 0
        assert d1.called
        assert d2.called

    def test_reset_cancels_all_hooks(self):
        canceller = Mock()
        dhooks = DeferredHooks()
        d1, d2 = Deferred(canceller), Deferred(canceller)
        dhooks.add(d1)
        dhooks.add(d2)
        dhooks.reset()
        assert len(dhooks.hooks) == 0
        canceller.assert_has_calls((call(d1), call(d2)))

    def test_reset_cancels_in_reactor(self):
        def validate_in_reactor(_):
            assert isInIOThread()

        dhooks = DeferredHooks()
        d = Deferred()
        d.addBoth(validate_in_reactor)
        dhooks.add(d)
        dhooks.reset()
        assert len(dhooks.hooks) == 0
        assert d.called

    def test_reset_suppresses_CancelledError(self):
        with TwistedLoggerFixture() as logger:
            dhooks = DeferredHooks()
            d = Deferred()
            dhooks.add(d)
            dhooks.reset()
            assert len(dhooks.hooks) == 0
            assert extract_result(d) is None
            assert "" == logger.output

    def test_logs_failures_from_cancellers(self):
        canceller = Mock()
        canceller.side_effect = factory.make_exception()

        with TwistedLoggerFixture() as logger:
            dhooks = DeferredHooks()
            d = Deferred(canceller)
            dhooks.add(d)
            dhooks.reset()
            assert len(dhooks.hooks) == 0
            # The hook has not been fired, but because the user-supplied
            # canceller has failed we're not in a position to know what to
            # do. This reflects a programming error and not a run-time error
            # that we ought to be prepared for, so it is left as-is.
            assert not d.called
            assert "Failure when cancelling hook." in logger.output

    def test_logs_failures_from_cancellers_when_hook_already_fired(self):
        def canceller(d):
            d.callback(None)
            raise factory.make_exception()

        with TwistedLoggerFixture() as logger:
            dhooks = DeferredHooks()
            d = Deferred(canceller)
            dhooks.add(d)
            dhooks.reset()
            assert len(dhooks.hooks) == 0
            assert d.called
            assert "Failure when cancelling hook." in logger.output

    def test_logs_failures_from_cancelled_hooks(self):
        error = factory.make_exception()
        with TwistedLoggerFixture() as logger:
            dhooks = DeferredHooks()
            d = Deferred()
            d.addBoth(lambda _: Failure(error))
            dhooks.add(d)
            dhooks.reset()
            assert len(dhooks.hooks) == 0
            assert d.called
            assert "Failure when cancelling hook." in logger.output

    def test_savepoint_saves_and_restores_hooks(self):
        d = Deferred()
        dhooks = DeferredHooks()
        dhooks.add(d)

        with dhooks.savepoint():
            assert list(dhooks.hooks) == []

        assert list(dhooks.hooks) == [d]

    def test_savepoint_restores_hooks_with_new_hooks_on_clean_exit(self):
        d1 = Deferred()
        d2 = Deferred()
        dhooks = DeferredHooks()
        dhooks.add(d1)

        with dhooks.savepoint():
            dhooks.add(d2)
            assert list(dhooks.hooks) == [d2]

        assert list(dhooks.hooks) == [d1, d2]

    def test_savepoint_restores_hooks_only_on_dirty_exit(self):
        d1 = Deferred()
        d2 = Deferred()
        dhooks = DeferredHooks()
        dhooks.add(d1)

        exception_type = factory.make_exception_type()
        with pytest.raises(exception_type, match=None):
            with dhooks.savepoint():
                dhooks.add(d2)
                raise exception_type()

        assert list(dhooks.hooks) == [d1]
