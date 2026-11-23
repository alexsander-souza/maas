# Copyright 2014-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maasserver.utils.dblocks`."""

from contextlib import closing, contextmanager
import re
import sys

from django.db import connection, reset_queries, transaction
import pytest

from maasserver.testing.dblocks import lock_held_in_other_thread
from maasserver.utils import dblocks

# Use "high" objid numbers to avoid conflicts with predeclared locks.
objid_min = 2 << 10

MODE_IDS = ["%s/%s" % mode for mode in dblocks.DatabaseLock.MODE_CHOICES]


@pytest.fixture
def transactional_maasdb(maasdb):
    """Provide the database as `MAASTransactionServerTestCase` did.

    The `maasdb` fixture leaves autocommit disabled, under which
    `transaction.atomic()` only creates savepoints (subtransactions). The
    tests using this fixture need top-level transactions and real commits,
    so autocommit is restored here.
    """
    transaction.rollback()
    transaction.set_autocommit(True)
    yield


def get_locks():
    """Return the set of locks held that's greater than `objid_min`"""
    with closing(connection.cursor()) as cursor:
        cursor.execute(
            "SELECT objid FROM pg_locks, pg_database "
            "WHERE classid = %s AND objid >= %s"
            "   AND pg_locks.database = pg_database.oid"
            "   AND pg_database.datname = current_database()",
            [dblocks.classid, objid_min],
        )
        return {result[0] for result in cursor.fetchall()}


def get_objid():
    """Return a 'high' objid that's won't coincide with predeclared locks.

    It makes use of a DB sequence to ensure that all tests have unique objids.
    """
    with closing(connection.cursor()) as cursor:
        cursor.execute("CREATE SEQUENCE IF NOT EXISTS dblocks_test_seq")
        cursor.execute("select nextval('dblocks_test_seq')")
        [next_value] = cursor.fetchone()
    return objid_min + next_value


@transaction.atomic
def divide_by_zero():
    """Do something stupid in a transaction."""
    0 / 0  # noqa: B018


@contextmanager
def force_debug_cursor():
    """Set `force_debug_cursor` on Django's default connection."""
    force_debug_cursor = connection.force_debug_cursor
    connection.force_debug_cursor = True
    try:
        yield
    finally:
        connection.force_debug_cursor = force_debug_cursor


def capture_queries_while_holding_lock(lock):
    """Capture SQL being issued to the database.

    Return as a single string with each statement separated by new-line "--"
    new-line.
    """
    with force_debug_cursor():
        reset_queries()
        with lock:
            pass  # Just being here is enough.
    return "\n--\n".join(query["sql"] for query in connection.queries)


@pytest.mark.allow_transactions
@pytest.mark.usefixtures("transactional_maasdb")
@pytest.mark.parametrize(
    "mode", dblocks.DatabaseLock.MODE_CHOICES, ids=MODE_IDS
)
class TestDatabaseLock:
    def make_lock(self, objid, mode):
        return dblocks.DatabaseLock(objid, mode=mode)

    def test_create_lock(self, mode):
        objid = get_objid()
        lock = self.make_lock(objid, mode)
        assert lock == (dblocks.classid, objid)

    def test_properties(self, mode):
        lock = self.make_lock(get_objid(), mode)
        assert lock == (lock.classid, lock.objid)

    @transaction.atomic
    def test_lock_actually_locked(self, mode):
        objid = get_objid()
        lock = self.make_lock(objid, mode)

        locks_held_before = get_locks()
        with lock:
            locks_held = get_locks()
        locks_held_after = get_locks()

        locks_obtained = locks_held - locks_held_before
        assert objid in locks_obtained

        locks_released = locks_held - locks_held_after
        assert objid in locks_released

    @transaction.atomic
    def test_is_locked(self, mode):
        objid = get_objid()
        lock = self.make_lock(objid, mode)

        assert not lock.is_locked()
        with lock:
            assert lock.is_locked()
        assert not lock.is_locked()

    def test_lock_remains_held_when_committing_transaction(self, mode):
        objid = get_objid()
        lock = self.make_lock(objid, mode)
        txn = transaction.atomic()

        assert not lock.is_locked()
        txn.__enter__()
        assert not lock.is_locked()
        lock.__enter__()
        assert lock.is_locked()
        txn.__exit__(None, None, None)
        assert lock.is_locked()
        lock.__exit__(None, None, None)
        assert not lock.is_locked()

    def test_lock_remains_held_when_aborting_transaction(self, mode):
        objid = get_objid()
        lock = self.make_lock(objid, mode)
        txn = transaction.atomic()

        assert not lock.is_locked()
        txn.__enter__()
        assert not lock.is_locked()
        lock.__enter__()
        assert lock.is_locked()

        try:
            divide_by_zero()
        except ZeroDivisionError:
            exc_info = sys.exc_info()
        else:
            raise AssertionError("ZeroDivisionError not raised.")

        txn.__exit__(*exc_info)
        assert lock.is_locked()
        lock.__exit__(None, None, None)
        assert not lock.is_locked()

    def test_lock_is_held_around_transaction(self, mode):
        objid = get_objid()
        lock = self.make_lock(objid, mode)

        assert not lock.is_locked()
        with lock:
            assert lock.is_locked()
            with transaction.atomic():
                assert lock.is_locked()
            assert lock.is_locked()
        assert not lock.is_locked()

    def test_lock_is_held_around_breaking_transaction(self, mode):
        objid = get_objid()
        lock = self.make_lock(objid, mode)

        assert not lock.is_locked()
        with lock:
            assert lock.is_locked()
            try:
                divide_by_zero()
            except ZeroDivisionError:
                pass
            else:
                raise AssertionError("ZeroDivisionError not raised.")
            assert lock.is_locked()
        assert not lock.is_locked()

    def test_lock_requires_preexisting_connection(self, mode):
        objid = get_objid()
        connection.close()
        lock = self.make_lock(objid, mode)
        with pytest.raises(dblocks.DatabaseLockAttemptWithoutConnection):
            lock.__enter__()

    def test_releasing_lock_fails_when_lock_not_held(self, mode):
        objid = get_objid()
        lock = self.make_lock(objid, mode)
        with pytest.raises(dblocks.DatabaseLockNotHeld):
            lock.__exit__()

    def test_repr(self, mode):
        lock = self.make_lock(get_objid(), mode)
        assert repr(lock) == (
            "<DatabaseLock classid=%d objid=%d lock=%s unlock=%s>"
            % (lock[0], lock[1], mode[0], mode[1])
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestDatabaseLockVariations:
    def test_plain_variation(self):
        objid = get_objid()
        lock = dblocks.DatabaseLock(objid)
        assert re.search(
            rf"(?m)SELECT pg_advisory_lock\(\d+, {objid}\)\n"
            "--\n"
            rf"SELECT pg_advisory_unlock\(\d+, {objid}\)",
            capture_queries_while_holding_lock(lock),
        )

    def test_try_variation(self):
        objid = get_objid()
        lock = dblocks.DatabaseLock(objid)
        assert lock == lock.TRY
        assert re.search(
            rf"(?m)SELECT pg_try_advisory_lock\(\d+, {objid}\)\n"
            "--\n"
            rf"SELECT pg_advisory_unlock\(\d+, {objid}\)",
            capture_queries_while_holding_lock(lock.TRY),
        )

    def test_shared_variation(self):
        objid = get_objid()
        lock = dblocks.DatabaseLock(objid)
        assert lock == lock.SHARED
        assert re.search(
            rf"(?m)SELECT pg_advisory_lock_shared\(\d+, {objid}\)\n"
            "--\n"
            rf"SELECT pg_advisory_unlock_shared\(\d+, {objid}\)",
            capture_queries_while_holding_lock(lock.SHARED),
        )

    def test_try_shared_variation(self):
        objid = get_objid()
        lock = dblocks.DatabaseLock(objid)
        assert lock == lock.TRY.SHARED
        assert re.search(
            rf"(?m)SELECT pg_try_advisory_lock_shared\(\d+, {objid}\)\n"
            "--\n"
            rf"SELECT pg_advisory_unlock_shared\(\d+, {objid}\)",
            capture_queries_while_holding_lock(lock.TRY.SHARED),
        )


@pytest.mark.allow_transactions
@pytest.mark.usefixtures("transactional_maasdb")
@pytest.mark.parametrize(
    "mode", dblocks.DatabaseXactLock.MODE_CHOICES, ids=MODE_IDS
)
class TestDatabaseXactLock:
    def make_lock(self, objid, mode):
        return dblocks.DatabaseXactLock(objid, mode=mode)

    def test_create_lock(self, mode):
        objid = get_objid()
        lock = self.make_lock(objid, mode)
        assert lock == (dblocks.classid, objid)

    def test_properties(self, mode):
        lock = self.make_lock(get_objid(), mode)
        assert lock == (lock.classid, lock.objid)

    def test_lock_actually_locked(self, mode):
        objid = get_objid()
        lock = self.make_lock(objid, mode)

        with transaction.atomic():
            locks_held_before = get_locks()
            with lock:
                locks_held = get_locks()
            locks_held_after = get_locks()
        locks_held_after_txn = get_locks()

        locks_obtained = locks_held - locks_held_before
        assert objid in locks_obtained

        locks_released = locks_held - locks_held_after
        assert objid not in locks_released

        locks_released_with_txn = locks_held - locks_held_after_txn
        assert objid in locks_released_with_txn

    def test_is_locked(self, mode):
        objid = get_objid()
        lock = self.make_lock(objid, mode)

        with transaction.atomic():
            assert not lock.is_locked()
            with lock:
                assert lock.is_locked()
            assert lock.is_locked()

        # The lock is released with the end of the transaction.
        assert not lock.is_locked()

    def test_obtaining_lock_fails_when_outside_of_transaction(self, mode):
        objid = get_objid()
        lock = self.make_lock(objid, mode)
        with pytest.raises(dblocks.DatabaseLockAttemptOutsideTransaction):
            lock.__enter__()

    def test_releasing_lock_does_nothing(self, mode):
        objid = get_objid()
        lock = self.make_lock(objid, mode)
        assert lock.__exit__() is None

    def test_repr(self, mode):
        lock = self.make_lock(get_objid(), mode)
        assert repr(lock) == (
            "<DatabaseXactLock classid=%d objid=%d lock=%s unlock=%s>"
            % (lock[0], lock[1], mode[0], mode[1])
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestDatabaseXactLockVariations:
    def test_plain_variation(self):
        objid = get_objid()
        lock = dblocks.DatabaseXactLock(objid)
        assert re.search(
            rf"SELECT pg_advisory_xact_lock\(\d+, {objid}\)",
            capture_queries_while_holding_lock(lock),
        )

    def test_try_variation(self):
        objid = get_objid()
        lock = dblocks.DatabaseXactLock(objid)
        assert lock == lock.TRY
        assert re.search(
            rf"SELECT pg_try_advisory_xact_lock\(\d+, {objid}\)",
            capture_queries_while_holding_lock(lock.TRY),
        )

    def test_shared_variation(self):
        objid = get_objid()
        lock = dblocks.DatabaseXactLock(objid)
        assert lock == lock.SHARED
        assert re.search(
            rf"SELECT pg_advisory_xact_lock_shared\(\d+, {objid}\)",
            capture_queries_while_holding_lock(lock.SHARED),
        )

    def test_try_shared_variation(self):
        objid = get_objid()
        lock = dblocks.DatabaseXactLock(objid)
        assert lock == lock.TRY.SHARED
        assert re.search(
            rf"SELECT pg_try_advisory_xact_lock_shared\(\d+, {objid}\)",
            capture_queries_while_holding_lock(lock.TRY.SHARED),
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga")
@pytest.mark.parametrize(
    "make_lock",
    [dblocks.DatabaseLock, dblocks.DatabaseXactLock],
    ids=["DatabaseLock", "DatabaseXactLock"],
)
class TestTryingToAcquireLockedLock:
    """Test what happens when trying to acquire a lock that's already taken."""

    def test_try_variation_when_already_exclusively_locked(self, make_lock):
        lock = make_lock(get_objid())
        with lock_held_in_other_thread(lock):
            with pytest.raises(dblocks.DatabaseLockNotHeld):
                lock.TRY.__enter__()

    def test_try_variation_when_already_share_locked(self, make_lock):
        lock = make_lock(get_objid())
        with lock_held_in_other_thread(lock.SHARED):
            with pytest.raises(dblocks.DatabaseLockNotHeld):
                lock.TRY.__enter__()

    def test_try_shared_variation_when_already_exclusively_locked(
        self, make_lock
    ):
        lock = make_lock(get_objid())
        with lock_held_in_other_thread(lock):
            with pytest.raises(dblocks.DatabaseLockNotHeld):
                lock.TRY.SHARED.__enter__()

    def test_try_shared_variation_when_already_share_locked(self, make_lock):
        lock = make_lock(get_objid())
        with lock_held_in_other_thread(lock.SHARED):
            with lock.SHARED:
                pass  # No exception.
