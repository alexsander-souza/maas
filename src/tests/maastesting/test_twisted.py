# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from unittest.mock import Mock

from twisted.logger import globalLogPublisher, Logger

from maastesting.twisted import TwistedLoggerFixture


def test_twisted_logger_fixture_restores_modern_observers():
    observer = Mock()
    logger = Logger()
    globalLogPublisher.addObserver(observer)
    try:
        logger.info("fixture lifecycle")
        observer.assert_called_once()
        observer.reset_mock()

        with TwistedLoggerFixture():
            logger.info("fixture lifecycle")
            observer.assert_not_called()

        logger.info("fixture lifecycle")
        observer.assert_called_once()
    finally:
        globalLogPublisher.removeObserver(observer)
