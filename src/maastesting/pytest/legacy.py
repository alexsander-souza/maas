# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""pytest hooks for legacy and Crochet-managed test suites.

The rack reactor guard is opt-in so only migrated rack tests receive per-test
resource checks.
"""

from contextlib import contextmanager
import inspect
import sys
import threading
import traceback
import types

import crochet
import pytest
from twisted.internet import defer
from twisted.internet.defer import Deferred
from twisted.internet.process import reapAllProcesses
from twisted.internet.task import deferLater, LoopingCall
from twisted.internet.threads import blockingCallFromThread

from maastesting.crochet import setup_crochet

_RACK_REACTOR_CLEANUP_TIMEOUT = 90.0
_RACK_REACTOR_TICK_TIMEOUT = 0.5


def _check_rack_test_result(result, nodeid):
    if isinstance(result, types.GeneratorType):
        result.close()
        pytest.fail(
            f"{nodeid} returned a generator; decorate Deferred tests with "
            "inlineCallbacks and wait_for.",
            pytrace=False,
        )
    if isinstance(result, Deferred):
        result.cancel()
        pytest.fail(
            f"{nodeid} returned an unawaited Deferred; use wait_for(timeout).",
            pytrace=False,
        )
    if inspect.iscoroutine(result):
        result.close()
        pytest.fail(
            f"{nodeid} returned an unawaited coroutine; use wait_for(timeout).",
            pytrace=False,
        )


def _pool_is_quiet(pool):
    lock = getattr(pool, "lock", None)
    if isinstance(lock, defer.DeferredLock):
        return not lock.locked
    if isinstance(lock, defer.DeferredSemaphore):
        return lock.tokens == lock.limit
    return not pool.working


def _thread_stacks():
    threads = {thread.ident: thread for thread in threading.enumerate()}
    return [
        f"{threads.get(ident, f'<unknown thread {ident}>')!r}:\n"
        + "".join(traceback.format_stack(frame))
        for ident, frame in sys._current_frames().items()
    ]


def _wait_for_rack_threadpools(reactor, timeout):
    pools = [
        pool
        for name in ("threadpool", "threadpoolForDatabase")
        if (pool := getattr(reactor, name, None)) is not None
    ]

    @defer.inlineCallbacks
    def wait():
        deadline = reactor.seconds() + timeout
        while any(not _pool_is_quiet(pool) for pool in pools):
            remaining = deadline - reactor.seconds()
            if remaining <= 0:
                raise TimeoutError(
                    "Threadpools did not quiesce before timeout: "
                    + ", ".join(
                        repr(pool)
                        for pool in pools
                        if not _pool_is_quiet(pool)
                    )
                    + "\n"
                    + "\n".join(_thread_stacks())
                )
            yield deferLater(reactor, min(0.1, remaining), lambda: None)

    return wait()


def _cleanup_rack_reactor(
    reactor, nodeid, timeout=_RACK_REACTOR_CLEANUP_TIMEOUT
):
    ticked = threading.Event()
    reactor.callFromThread(ticked.set)
    if not ticked.wait(_RACK_REACTOR_TICK_TIMEOUT):
        pytest.fail(
            f"{nodeid}: reactor did not respond within "
            f"{_RACK_REACTOR_TICK_TIMEOUT}s during cleanup.",
            pytrace=False,
        )

    try:
        blockingCallFromThread(
            reactor, lambda: _wait_for_rack_threadpools(reactor, timeout)
        )
    except Exception as error:
        pool_error = f"{nodeid}: threadpool cleanup failed: {error}"
    else:
        pool_error = None

    def clean_reactor():
        delayed_calls = []
        for call in reactor.getDelayedCalls():
            if call.active() and not _is_internal_delayed_call(call):
                delayed_calls.append(str(call))
                call.cancel()
        selectables = []
        for selectable in reactor.removeAll():
            selectables.append(repr(selectable))
            if getattr(selectable, "signalProcess", None) is not None:
                selectable.signalProcess("KILL")
        return delayed_calls, selectables

    delayed_calls, selectables = blockingCallFromThread(reactor, clean_reactor)
    problems = []
    if pool_error:
        problems.append(pool_error)
    if delayed_calls:
        problems.append(
            f"{nodeid}: leaked delayed calls (cancelled during cleanup):\n"
            + "\n".join(delayed_calls)
        )
    if selectables:
        problems.append(
            f"{nodeid}: leaked selectables (removed during cleanup):\n"
            + "\n".join(selectables)
        )
    if problems:
        pytest.fail("\n".join(problems), pytrace=False)


def _is_internal_delayed_call(call):
    function = getattr(call, "func", None)
    if (
        getattr(function, "__module__", "")
        == "twisted.internet.asyncioreactor"
    ):
        return True
    return isinstance(function, LoopingCall) and function.f is reapAllProcesses


@pytest.fixture(autouse=True)
def _rack_reactor_guard(request):
    if request.node.get_closest_marker("rack_reactor_guard") is None:
        yield
        return
    from twisted.internet import reactor

    try:
        yield
    except BaseException as test_error:
        try:
            _cleanup_rack_reactor(reactor, request.node.nodeid)
        except BaseException as cleanup_error:
            raise RuntimeError(
                f"{request.node.nodeid}: test failed with {test_error!r}; "
                f"reactor cleanup failed with {cleanup_error!r}"
            ) from cleanup_error
        raise
    else:
        _cleanup_rack_reactor(reactor, request.node.nodeid)


@pytest.hookimpl(tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    if pyfuncitem.get_closest_marker("rack_reactor_guard") is None:
        return None
    testfunction = pyfuncitem.obj
    testargs = {
        arg: pyfuncitem.funcargs[arg]
        for arg in pyfuncitem._fixtureinfo.argnames
    }
    result = testfunction(**testargs)
    _check_rack_test_result(result, pyfuncitem.nodeid)
    return True


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "rack_reactor_guard: opt in to per-test Crochet reactor cleanup checks",
    )


@contextmanager
def _track_eventual_results(registry):
    with registry._lock:
        original_results = registry._results
        results = set()
        registry._results = results
    try:
        yield results
    finally:
        with registry._lock:
            registry._results = original_results


def _eventual_result_failures(results):
    failures = []
    for result in results:
        if result._result_retrieved:
            continue
        if result._result_set.is_set():
            failures.append(
                f"EventualResult fired but was not retrieved: {result!r}; "
                f"result={result._value!r}"
            )
        else:
            failures.append(f"EventualResult did not fire: {result!r}")
    return failures


@pytest.fixture(autouse=True)
def _eventual_result_guard():
    registry = getattr(crochet._main, "_registry", None)
    if registry is None:
        yield
        return

    with _track_eventual_results(registry) as results:
        try:
            yield
        finally:
            failures = _eventual_result_failures(results)
            if failures:
                pytest.fail("\n".join(failures), pytrace=False)


@pytest.fixture(scope="session", autouse=True)
def _crochet_reactor():
    """Start the Twisted reactor once per pytest session."""
    setup_crochet()

    from twisted.internet import reactor as _reactor

    from maasserver.utils import orm, threads

    if getattr(_reactor, "threadpool", None) is None:
        threads.install_default_pool(maxthreads=1)
    if getattr(_reactor, "threadpoolForDatabase", None) is None:
        threads.install_database_unpool(maxthreads=1)
        _reactor.callFromThread(orm.disable_all_database_connections)

    from provisioningserver.logger._common import (
        make_logging_level_names_consistent,
    )

    make_logging_level_names_consistent()
