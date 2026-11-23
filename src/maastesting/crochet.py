# Copyright 2014-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Support for testing with `crochet`."""

from functools import wraps
import inspect

import crochet
from twisted.internet.defer import ensureDeferred
import wrapt

from maastesting import get_testing_timeout


def setup_crochet():
    """Start the Twisted reactor through Crochet."""
    # Remove deprecated crochet APIs.
    if hasattr(crochet, "wait_for_reactor"):
        del crochet.wait_for_reactor
    if hasattr(crochet.EventLoop, "wait_for_reactor"):
        del crochet.EventLoop.wait_for_reactor
    if hasattr(crochet, "DeferredResult"):
        del crochet.DeferredResult

    # Make a default timeout forbidden.
    class EventualResult(crochet.EventualResult):
        def _result(self, timeout=None):
            if timeout is None:
                raise AssertionError("A time-out must be specified.")
            else:
                return super()._result(timeout)

    # Patch it back into crochet.
    crochet._eventloop.EventualResult = EventualResult
    crochet.EventualResult = EventualResult

    crochet.setup()

    # Prevent the default STDLibLogObserver from forwarding Twisted
    # log events into Python's logging module, which may try to write
    # to a closed stream (closed test-capture handler) and crash with
    # "I/O operation on closed file". Replace the observer with the
    # production-style one that writes directly to sys.__stdout__.
    from twisted.logger import globalLogPublisher

    from provisioningserver.logger._twisted import EventLogger

    globalLogPublisher._observers = [EventLogger()]


class TimeoutInTestException(Exception):
    """Nicer reporting of what actually timed-out."""

    def __init__(self, function, fargs, fkwargs, timeout, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # It's not useful to see all the decorators
        self.function = inspect.unwrap(function)
        self.args = fargs
        self.kwargs = fkwargs
        self.timeout = timeout

    def __str__(self):
        return f"Timeout after {self.timeout}s running {self.function.__name__} with args {self.args!r} and kwargs {self.kwargs!r}"


def wait_for(timeout=None):
    """Backport of wait_for from Crochet 2.0.

    This allows async def definitions to be used.
    """
    timeout = get_testing_timeout(timeout)

    def decorator(function):
        def wrapper(function, _, args, kwargs):
            @crochet.run_in_reactor
            def run():
                if inspect.iscoroutinefunction(function):
                    return ensureDeferred(function(*args, **kwargs))
                else:
                    return function(*args, **kwargs)

            eventual_result = run()
            try:
                return eventual_result.wait(timeout)
            except crochet.TimeoutError:
                eventual_result.cancel()
                raise TimeoutInTestException(function, args, kwargs, timeout)  # noqa: B904

        if inspect.iscoroutinefunction(function):
            # Create a non-async wrapper with same signature.
            @wraps(function)
            def non_async_wrapper():
                pass

        else:
            # Just use default behavior of looking at underlying object.
            non_async_wrapper = None

        wrapper = wrapt.decorator(wrapper, adapter=non_async_wrapper)
        return wrapper(function)

    return decorator
