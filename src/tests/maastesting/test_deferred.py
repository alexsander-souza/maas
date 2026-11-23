# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import pytest
from twisted.internet.defer import Deferred

from maastesting.deferred import DeferredNotFiredError, extract_result


def test_extract_result_returns_fired_success_value():
    value = object()
    deferred = Deferred()
    deferred.callback(value)

    assert extract_result(deferred) is value


def test_extract_result_raises_fired_failure_exception():
    error = ValueError("deferred failed")
    deferred = Deferred()
    deferred.errback(error)

    with pytest.raises(ValueError) as exc_info:
        extract_result(deferred)

    assert exc_info.value is error


def test_extract_result_rejects_pending_deferred():
    deferred = Deferred()

    with pytest.raises(
        DeferredNotFiredError, match="has not fired yet; wait for it"
    ):
        extract_result(deferred)
