# Copyright 2013-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the nonces cleanup module."""

from collections import Counter
import time

from piston3.models import Nonce
import pytest
from twisted.internet.defer import maybeDeferred
from twisted.internet.task import Clock

from maasserver import nonces_cleanup
from maasserver.nonces_cleanup import (
    cleanup_old_nonces,
    create_checkpoint_nonce,
    delete_old_nonces,
    find_checkpoint_nonce,
    get_time_string,
    key_prefix,
    NonceCleanupService,
    timestamp_threshold,
)
from maasserver.nonces_cleanup import time as module_time
from maasserver.testing.factory import factory


@pytest.mark.usefixtures(
    "maasdb", "factory", "mock_openfga", "mock_start_workflows"
)
class TestCleanupOldNonces:
    def test_cleanup_old_nonces_returns_0_if_no_checkpoint(self):
        assert 0 == cleanup_old_nonces()

    def test_cleanup_old_nonces_cleans_up_old_nonces(self, mocker):
        now = time.time()
        # Patch the module's time module so that the nonces appear as if
        # they were created now - timestamp_threshold seconds ago.
        timemod = mocker.patch.object(module_time, "time")
        timemod.return_value = now - timestamp_threshold
        old_nonces = [
            Nonce.objects.create(token_key=factory.make_string())
            for _ in range(3)
        ]
        assert 0 == cleanup_old_nonces()
        # Patch the module's time module back.
        timemod.return_value = now
        new_nonces = [
            Nonce.objects.create(token_key=factory.make_string())
            for _ in range(3)
        ]

        cleanup_count = cleanup_old_nonces()

        # The old nonces plus the checkpoint nonce are deleted.
        assert len(old_nonces) + 1 == cleanup_count
        assert set(Nonce.objects.all()) >= set(new_nonces)
        assert len(new_nonces) + 1 == Nonce.objects.all().count()


@pytest.mark.usefixtures(
    "maasdb", "factory", "mock_openfga", "mock_start_workflows"
)
class TestUtilities:
    def test_create_checkpoint_nonce_creates_checkpoint_nonce(self):
        before = time.time()
        create_checkpoint_nonce()
        checkpoint = Nonce.objects.get(token_key="", consumer_key="")
        after = time.time()
        checkpoint_time = checkpoint.key[len(key_prefix) :]
        assert before <= float(checkpoint_time)
        assert after >= float(checkpoint_time)

    def test_create_checkpoint_nonce_gets_checkpoint_if_exists(self, mocker):
        now = time.time()
        mocker.patch.object(module_time, "time").return_value = now
        create_checkpoint_nonce()
        nonce1 = Nonce.objects.filter(token_key="", consumer_key="").latest(
            "id"
        )
        create_checkpoint_nonce()
        nonce2 = Nonce.objects.filter(token_key="", consumer_key="").latest(
            "id"
        )
        assert nonce1.id == nonce2.id

    def test_delete_old_nonces_delete_nonces(self):
        # Create old nonces.
        [
            Nonce.objects.create(token_key=factory.make_string())
            for _ in range(3)
        ]
        checkpoint = Nonce.objects.create(token_key=factory.make_string())
        new_nonces = [
            Nonce.objects.create(token_key=factory.make_string())
            for _ in range(3)
        ]
        delete_old_nonces(checkpoint)
        assert Counter(new_nonces) == Counter(Nonce.objects.all())

    def test_find_checkpoint_nonce_returns_None_if_no_checkpoint(self):
        assert find_checkpoint_nonce() is None

    def test_find_checkpoint_nonce_returns_most_recent_checkpoint(
        self, mocker
    ):
        now = time.time()
        mocker.patch.object(module_time, "time").return_value = now
        # Create a "checkpoint" nonce created timestamp_threshold + 5
        # seconds ago.
        Nonce.objects.create(
            token_key="",
            consumer_key="",
            key=get_time_string(now - 5 - timestamp_threshold),
        )
        # Create a "checkpoint" nonce created timestamp_threshold
        # seconds ago.
        checkpoint = Nonce.objects.create(
            token_key="",
            consumer_key="",
            key=get_time_string(now - timestamp_threshold),
        )
        # Create a "checkpoint" nonce created 1 second ago.
        Nonce.objects.create(
            token_key="", consumer_key="", key=get_time_string(now - 1)
        )

        assert checkpoint == find_checkpoint_nonce()

    def test_get_time_string_returns_comparable_string(self):
        now = time.time()
        assert get_time_string(now + 1) > get_time_string(now)

    def test_get_time_string_ends_with_suffix(self):
        now = time.time()
        assert get_time_string(now).startswith(key_prefix)


@pytest.mark.usefixtures(
    "maasdb", "factory", "mock_openfga", "mock_start_workflows"
)
class TestNonceCleanupService:
    def test_init_with_default_interval(self, mocker):
        # The service itself calls `cleanup_old_nonces` in a thread, via
        # a couple of decorators. This indirection makes it clearer to
        # mock `cleanup_old_nonces` here and track calls to it.
        cleanup_old_nonces = mocker.patch.object(
            nonces_cleanup, "cleanup_old_nonces"
        )
        mocker.patch.object(nonces_cleanup, "deferToDatabase", maybeDeferred)
        service = NonceCleanupService()
        # Use a deterministic clock instead of the reactor for testing.
        service.clock = Clock()

        # The interval is stored as `step` by TimerService,
        # NonceCleanupService's parent class.
        interval = 24 * 60 * 60  # seconds.
        assert service.step == interval

        # `cleanup_old_nonces` is not called before the service is
        # started.
        cleanup_old_nonces.assert_not_called()
        # `cleanup_old_nonces` is called the moment the service is
        # started.
        service.startService()
        cleanup_old_nonces.assert_called_once_with()
        # Advancing the clock by `interval - 1` means that
        # `cleanup_old_nonces` has still only been called once.
        service.clock.advance(interval - 1)
        cleanup_old_nonces.assert_called_once_with()
        cleanup_old_nonces.reset_mock()
        # Advancing the clock one more second causes another call to
        # `cleanup_old_nonces`.
        service.clock.advance(1)
        cleanup_old_nonces.assert_called_once_with()

    def test_interval_can_be_set(self):
        interval = 37
        service = NonceCleanupService(interval)
        assert interval == service.step
