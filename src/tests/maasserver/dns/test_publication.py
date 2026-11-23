# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maasserver.dns.publication`."""

from datetime import timedelta

from django.utils import timezone
import pytest
from twisted.internet.defer import fail, inlineCallbacks
from twisted.internet.task import Clock

from maasserver.dns import publication
from maasserver.models.dnspublication import DNSPublication
from maastesting.crochet import wait_for
from maastesting.factory import factory
from maastesting.twisted import TwistedLoggerFixture
from provisioningserver.utils.twisted import pause


def _is_expected_interval(interval):
    return 3 * 60 * 60 <= interval <= 6 * 60 * 60


def patch_utcnow(mocker):
    utcnow = mocker.patch.object(publication, "timezone").now
    ref = utcnow.return_value = timezone.now()
    return ref


class TestDNSPublicationGarbageService:
    """Tests for `DNSPublicationGarbageService`."""

    def test_starting_and_stopping(self, mocker):
        deferToDatabase = mocker.patch.object(publication, "deferToDatabase")

        utcnow = patch_utcnow(mocker)
        cutoff = utcnow - timedelta(days=7)

        dnsgc = publication.DNSPublicationGarbageService()
        dnsgc.clock = clock = Clock()

        dnsgc.startService()
        assert dnsgc.running
        assert dnsgc._loop.running
        deferToDatabase.assert_not_called()
        assert _is_expected_interval(dnsgc._loop.interval)

        clock.advance(dnsgc._loop.interval)
        deferToDatabase.assert_called_once_with(dnsgc._collectGarbage, cutoff)
        assert _is_expected_interval(dnsgc._loop.interval)

        dnsgc.stopService()
        assert not dnsgc.running
        assert not dnsgc._loop.running

    def test_failures_are_logged(self, mocker):
        exception = factory.make_exception()
        deferToDatabase = mocker.patch.object(publication, "deferToDatabase")
        deferToDatabase.return_value = fail(exception)

        dnsgc = publication.DNSPublicationGarbageService()
        dnsgc.clock = clock = Clock()

        with TwistedLoggerFixture() as logger:
            dnsgc.startService()
            clock.advance(dnsgc._loop.interval)
            dnsgc.stopService()

        assert logger.output == (
            "Failure when removing old DNS publications.\n"
            "Traceback (most recent call last):\n"
            f"Failure: maastesting.factory.{type(exception).__name__}: \n"
        )

        assert not dnsgc.running


@pytest.mark.usefixtures("maasdb")
class TestDNSPublicationGarbageServiceWithDatabase:
    """Tests for `DNSPublicationGarbageService` with the database."""

    @wait_for()
    @inlineCallbacks
    def test_garbage_is_collected(self, mocker):
        dnsgc = publication.DNSPublicationGarbageService()

        utcnow = patch_utcnow(mocker)
        cutoff = utcnow - timedelta(days=7)

        mocker.patch.object(dnsgc, "_getInterval").side_effect = [0, 999]
        mocker.patch.object(DNSPublication.objects, "collect_garbage")

        yield dnsgc.startService()
        yield pause(0.0)  # Let the reactor tick.
        yield dnsgc.stopService()

        DNSPublication.objects.collect_garbage.assert_called_once_with(cutoff)
