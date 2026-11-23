# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Supported helpers for working with Twisted Deferreds in tests."""


class DeferredNotFiredError(Exception):
    """Raised when a result is requested from a Deferred that has not fired."""

    def __init__(self, deferred):
        super().__init__(
            f"{deferred!r} has not fired yet; "
            "wait for it before extracting its result."
        )


def extract_result(deferred):
    """Return a fired Deferred's result or raise its failure.

    This is intended for synchronous tests that already know the Deferred has
    completed. Use an async wait helper when it may still be pending.
    """
    successes = []
    failures = []
    deferred.addCallbacks(successes.append, failures.append)

    if failures:
        failures[0].raiseException()
    if successes:
        return successes[0]
    raise DeferredNotFiredError(deferred)
