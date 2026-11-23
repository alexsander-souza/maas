# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for TFTP-specific logging stuff."""

import pytest
from twisted.logger import LogLevel

from maastesting.twisted import TwistedLoggerFixture
from provisioningserver.logger._tftp import observe_tftp
from provisioningserver.logger.testing import make_event


class TestObserveTwistedInternetTCP_Informational:
    """Tests for `observe_tftp` with informational messages."""

    def test_downgrades_informational_messages(self):
        event = make_event(log_level=LogLevel.info)
        with TwistedLoggerFixture() as logger:
            observe_tftp(event)
        assert event in logger.events
        assert event["log_level"] is LogLevel.debug


@pytest.mark.parametrize(
    "log_level",
    [
        level
        for level in LogLevel.iterconstants()
        if level is not LogLevel.info
    ],
    ids=[
        level.name
        for level in LogLevel.iterconstants()
        if level is not LogLevel.info
    ],
)
class TestObserveTwistedInternetTCP_Other:
    """Tests for `observe_tftp` with non-informational messages."""

    def test_propagates_other_events(self, log_level):
        event = make_event(log_level=log_level)
        with TwistedLoggerFixture() as logger:
            observe_tftp(event)
        assert event in logger.events
        assert event["log_level"] is log_level
