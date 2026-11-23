# Copyright 2012-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test ORM utilities."""

from contextlib import contextmanager
from itertools import count, islice, repeat
from random import randint
import threading
from unittest.mock import ANY, call, Mock, sentinel

from django.core.exceptions import MultipleObjectsReturned
from django.db import (
    close_old_connections,
    connection,
    connections,
    IntegrityError,
    OperationalError,
    transaction,
)
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.transaction import TransactionManagementError
import psycopg2
from psycopg2.errorcodes import (
    DEADLOCK_DETECTED,
    FOREIGN_KEY_VIOLATION,
    SERIALIZATION_FAILURE,
    UNIQUE_VIOLATION,
)
import pytest
from twisted.internet.defer import _failthru, CancelledError, Deferred
from twisted.python.failure import Failure

from maasserver.models import Node
from maasserver.sqlalchemy import service_layer
from maasserver.utils import orm
from maasserver.utils.orm import (
    count_queries,
    disable_all_database_connections,
    DisabledDatabaseConnection,
    enable_all_database_connections,
    FullyConnected,
    get_first,
    get_model_object_name,
    get_one,
    get_psycopg2_deadlock_exception,
    get_psycopg2_exception,
    get_psycopg2_foreign_key_violation_exception,
    get_psycopg2_serialization_exception,
    get_psycopg2_unique_violation_exception,
    in_transaction,
    is_deadlock_failure,
    is_foreign_key_violation,
    is_retryable_failure,
    is_serialization_failure,
    is_unique_violation,
    log_sql_calls,
    post_commit,
    post_commit_do,
    post_commit_hooks,
    postgresql_major_version,
    psql_array,
    request_transaction_retry,
    retry_on_retryable_failure,
    savepoint,
    TotallyDisconnected,
    validate_in_transaction,
)
from maastesting.deferred import extract_result
from maastesting.doubles import StubContext
from maastesting.factory import factory
from provisioningserver.utils.twisted import callOut, DeferredValue


def create_stest_table():
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE IF NOT EXISTS stest (a INTEGER)")


def cause_serialization_failure():
    """Trigger an honest, from the database, serialization failure."""

    # Helper to switch the transaction to SERIALIZABLE.
    def set_serializable():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")

    # Perform a conflicting update. This must run in a separate thread. It
    # also must begin after the beginning of the transaction in which we
    # will trigger a serialization failure AND commit before that other
    # transaction commits. This doesn't need to run with serializable
    # isolation.
    def do_conflicting_update():
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE stest SET a = 2")
        finally:
            close_old_connections()

    def trigger_serialization_failure():
        # Fetch something first. This ensures that we're inside the
        # transaction, and that the database has a reference point for
        # calculating serialization failures.
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM stest")
            cursor.fetchall()

        # Run do_conflicting_update() in a separate thread.
        thread = threading.Thread(target=do_conflicting_update)
        thread.start()
        thread.join()

        # Updating the same rows as do_conflicting_update() did will
        # trigger a serialization failure. We have to check the __cause__
        # to confirm the failure type as reported by PostgreSQL.
        with connection.cursor() as cursor:
            cursor.execute("UPDATE stest SET a = 4")

    if connection.in_atomic_block:
        # We're already in a transaction.
        set_serializable()
        trigger_serialization_failure()
    else:
        # Start a transaction in this thread.
        with transaction.atomic():
            set_serializable()
            trigger_serialization_failure()


def create_uvtest_table():
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE IF EXISTS uvtest")
        cursor.execute("CREATE TABLE uvtest (a INTEGER PRIMARY KEY)")


def cause_unique_violation(conflicting_values):
    """Trigger an honest, from the database, unique violation.

    This may appear needlessly elaborate, but it's for a good reason.
    Indexes in PostgreSQL are a bit weird; they don't fully support MVCC
    so it's possible for situations like the following:

      CREATE TABLE foo (id SERIAL PRIMARY KEY);
      -- Session A:
      BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ;
      INSERT INTO foo (id) VALUES (1);
      -- Session B:
      BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ;
      SELECT id FROM foo;  -- Nothing.
      INSERT INTO foo (id) VALUES (1);  -- Hangs.
      -- Session A:
      COMMIT;
      -- Session B:
      ERROR:  duplicate key value violates unique constraint "..."
      DETAIL:  Key (id)=(1) already exists.

    Two things to note:

      1. Session B hangs when there's a potential conflict on id's index.

      2. Session B fails with a duplicate key error.

    Both differ from expectations:

      1. I would expect the transaction to continue optimistically and
         only fail if session A commits.

      2. I would expect a serialisation failure instead.

    This function jumps through hoops to reproduce the situation above so
    that we're testing against PostgreSQL's exact behaviour as of today,
    not the behaviour that we observed at a single moment in time.
    PostgreSQL may change its behaviour in later versions and this test
    ought to tell us about it.

    """

    # Helper to switch the transaction to REPEATABLE READ.
    def set_repeatable_read():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")

    # Both threads / database sessions will attempt to insert this.
    conflicting_value = next(conflicting_values)

    # Perform a conflicting insert. This must run in a separate thread. It
    # also must begin after the beginning of the transaction in which we
    # will trigger a unique violation AND commit before that other
    # transaction commits. This doesn't need to run with any special
    # isolation; it just needs to be in a transaction.
    def do_conflicting_insert():
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO uvtest VALUES (%s)",
                        [conflicting_value],
                    )
        finally:
            close_old_connections()

    def trigger_unique_violation():
        # Fetch something first. This ensures that we're inside the
        # transaction, and so the database has a reference point for
        # repeatable reads.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM uvtest WHERE a = %s", [conflicting_value]
            )
            assert cursor.fetchone() is None, (
                "We've seen through PostgreSQL impenetrable transaction "
                "isolation — or so we once thought — to witness a "
                "conflicting value from another database session. "
                "Needless to say, this requires investigation."
            )

        # Run do_conflicting_insert() in a separate thread and wait for it
        # to commit and return.
        thread = threading.Thread(target=do_conflicting_insert)
        thread.start()
        thread.join()

        # Still no sign of that conflicting value from here.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM uvtest WHERE a = %s", [conflicting_value]
            )
            assert cursor.fetchone() is None, (
                "PostgreSQL, once thought of highly in transactional "
                "circles, has dropped its kimono and disgraced itself "
                "with its wanton exhibition of conflicting values from "
                "another's session."
            )

        # Inserting the same row will trigger a unique violation.
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO uvtest VALUES (%s)", [conflicting_value]
            )

    if connection.in_atomic_block:
        # We're already in a transaction.
        set_repeatable_read()
        trigger_unique_violation()
    else:
        # Start a transaction in this thread.
        with transaction.atomic():
            set_repeatable_read()
            trigger_unique_violation()


class FakeModel:
    class MultipleObjectsReturned(MultipleObjectsReturned):
        pass

    def __init__(self, name):
        self.name == name  # noqa: B015

    def __repr__(self):
        return self.name


class FakeQueryResult:
    """Something that looks, to `get_one`, close enough to a Django model."""

    def __init__(self, model, items):
        self.model = model
        self.items = items

    def __iter__(self):
        return self.items.__iter__()

    def __repr__(self):
        return "<FakeQueryResult: %r>" % self.items


class TestPostgreSQLMajorVersion:
    def test_version(self):
        conn = Mock(server_version=140002)
        assert postgresql_major_version(conn=conn) == 14


class TestGetOne:
    def test_get_one_returns_None_for_empty_list(self):
        assert get_one([]) is None

    def test_get_one_returns_single_list_item(self):
        item = factory.make_string()
        assert item == get_one([item])

    def test_get_one_returns_None_from_any_empty_sequence(self):
        assert get_one("no item" for counter in range(0)) is None

    def test_get_one_returns_item_from_any_sequence_of_length_one(self):
        item = factory.make_string()
        assert item == get_one(item for counter in range(1))

    def test_get_one_does_not_trigger_database_counting(self):
        # Avoid typical performance pitfall of querying objects *and*
        # the number of objects.
        item = factory.make_string()
        sequence = FakeQueryResult(type(item), [item])
        sequence.__len__ = Mock(side_effect=Exception("len() was called"))
        assert item == get_one(sequence)

    def test_get_one_does_not_iterate_long_sequence_indefinitely(self):
        # Avoid typical performance pitfall of retrieving all objects.
        # In rare failure cases, there may be large numbers.  Fail fast.

        class InfinityException(Exception):
            """Iteration went on indefinitely."""

        def infinite_sequence():
            """Generator: count to infinity (more or less), then fail."""
            yield from range(3)
            raise InfinityException()

        # Raises MultipleObjectsReturned as spec'ed.  It does not
        # iterate to infinity first!
        with pytest.raises(MultipleObjectsReturned):
            get_one(infinite_sequence())

    def test_get_one_raises_model_error_if_query_result_is_too_big(self):
        with pytest.raises(FakeModel.MultipleObjectsReturned):
            get_one(FakeQueryResult(FakeModel, list(range(2))))

    def test_get_one_raises_generic_error_if_other_sequence_is_too_big(self):
        with pytest.raises(MultipleObjectsReturned):
            get_one(list(range(2)))


class TestGetFirst:
    def test_get_first_returns_None_for_empty_list(self):
        assert get_first([]) is None

    def test_get_first_returns_first_item(self):
        items = [factory.make_string() for counter in range(10)]
        assert items[0] == get_first(items)

    def test_get_first_accepts_any_sequence(self):
        item = factory.make_string()
        assert item == get_first(repeat(item))

    def test_get_first_does_not_retrieve_beyond_first_item(self):
        class SecondItemRetrieved(Exception):
            """Second item as retrieved.  It shouldn't be."""

        def multiple_items():
            yield "Item 1"
            raise SecondItemRetrieved()

        assert "Item 1" == get_first(multiple_items())


@pytest.mark.allow_transactions
class TestSerializationFailure:
    """Detecting SERIALIZABLE isolation failures."""

    @pytest.fixture(autouse=True)
    def _setup(self, transactional_maasdb):
        assert len(post_commit_hooks.hooks) == 0, (
            "One or more post-commit tasks were present before commencing "
            "this test."
        )
        post_commit_hooks.reset()
        create_stest_table()
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO stest VALUES (1)")
        yield
        assert len(post_commit_hooks.hooks) == 0, (
            "One or more post-commit tasks were present at the end of this "
            "test."
        )
        post_commit_hooks.reset()

    def test_serialization_failure_detectable_via_error_cause(self):
        with pytest.raises(OperationalError) as error:
            cause_serialization_failure()
        assert error.value.__cause__.pgcode == SERIALIZATION_FAILURE


@pytest.mark.allow_transactions
class TestUniqueViolation:
    """Detecting UNIQUE_VIOLATION failures."""

    @pytest.fixture(autouse=True)
    def _setup(self, transactional_maasdb):
        assert len(post_commit_hooks.hooks) == 0, (
            "One or more post-commit tasks were present before commencing "
            "this test."
        )
        post_commit_hooks.reset()
        create_uvtest_table()
        yield
        assert len(post_commit_hooks.hooks) == 0, (
            "One or more post-commit tasks were present at the end of this "
            "test."
        )
        post_commit_hooks.reset()

    def test_unique_violation_detectable_via_error_cause(self):
        with pytest.raises(IntegrityError) as error:
            cause_unique_violation(count(1))
        assert error.value.__cause__.pgcode == UNIQUE_VIOLATION


class TestGetPsycopg2Exception:
    """Tests for `get_psycopg2_exception`."""

    def test_returns_psycopg2_error(self):
        exception = psycopg2.Error()
        assert exception is get_psycopg2_exception(exception)

    def test_returns_None_for_other_error(self):
        exception = factory.make_exception()
        assert get_psycopg2_serialization_exception(exception) is None

    def test_returns_psycopg2_error_root_cause_for_serialization(self):
        exception = Exception()
        exception.__cause__ = orm.SerializationFailure()
        assert exception.__cause__ is get_psycopg2_exception(exception)

    def test_returns_psycopg2_error_root_cause_for_deadlock(self):
        exception = Exception()
        exception.__cause__ = orm.DeadlockFailure()
        assert exception.__cause__ is get_psycopg2_exception(exception)

    def test_returns_psycopg2_error_root_cause_for_foreign_key(self):
        exception = Exception()
        exception.__cause__ = orm.ForeignKeyViolation()
        assert exception.__cause__ is get_psycopg2_exception(exception)


class TestGetPsycopg2SerializationException:
    """Tests for `get_psycopg2_serialization_exception`."""

    def test_returns_None_for_plain_psycopg2_error(self):
        exception = psycopg2.Error()
        assert get_psycopg2_serialization_exception(exception) is None

    def test_returns_None_for_other_error(self):
        exception = factory.make_exception()
        assert get_psycopg2_serialization_exception(exception) is None

    def test_returns_psycopg2_error_root_cause(self):
        exception = Exception()
        exception.__cause__ = orm.SerializationFailure()
        assert exception.__cause__ is get_psycopg2_serialization_exception(
            exception
        )


class TestGetPsycopg2DeadlockException:
    """Tests for `get_psycopg2_deadlock_exception`."""

    def test_returns_None_for_plain_psycopg2_error(self):
        exception = psycopg2.Error()
        assert get_psycopg2_deadlock_exception(exception) is None

    def test_returns_None_for_other_error(self):
        exception = factory.make_exception()
        assert get_psycopg2_deadlock_exception(exception) is None

    def test_returns_psycopg2_error_root_cause(self):
        exception = Exception()
        exception.__cause__ = orm.DeadlockFailure()
        assert exception.__cause__ is get_psycopg2_deadlock_exception(
            exception
        )


class TestGetPsycopg2UniqueViolationException:
    """Tests for `get_psycopg2_unique_violation_exception`."""

    def test_returns_None_for_plain_psycopg2_error(self):
        exception = psycopg2.Error()
        assert get_psycopg2_unique_violation_exception(exception) is None

    def test_returns_None_for_other_error(self):
        exception = factory.make_exception()
        assert get_psycopg2_unique_violation_exception(exception) is None

    def test_returns_psycopg2_error_root_cause(self):
        exception = Exception()
        exception.__cause__ = orm.UniqueViolation()
        assert exception.__cause__ is get_psycopg2_unique_violation_exception(
            exception
        )


class TestGetPsycopg2ForeignKeyException:
    """Tests for `get_psycopg2_foreign_key_violation_exception`."""

    def test_returns_None_for_plain_psycopg2_error(self):
        exception = psycopg2.Error()
        assert get_psycopg2_foreign_key_violation_exception(exception) is None

    def test_returns_None_for_other_error(self):
        exception = factory.make_exception()
        assert get_psycopg2_foreign_key_violation_exception(exception) is None

    def test_returns_psycopg2_error_root_cause(self):
        exception = Exception()
        exception.__cause__ = orm.ForeignKeyViolation()
        assert (
            exception.__cause__
            is get_psycopg2_foreign_key_violation_exception(exception)
        )


@pytest.mark.allow_transactions
class TestIsSerializationFailure:
    """Tests relating to MAAS's use of SERIALIZABLE isolation."""

    @pytest.fixture(autouse=True)
    def _setup(self, transactional_maasdb):
        assert len(post_commit_hooks.hooks) == 0, (
            "One or more post-commit tasks were present before commencing "
            "this test."
        )
        post_commit_hooks.reset()
        create_stest_table()
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO stest VALUES (1)")
        yield
        assert len(post_commit_hooks.hooks) == 0, (
            "One or more post-commit tasks were present at the end of this "
            "test."
        )
        post_commit_hooks.reset()

    def test_detects_operational_error_with_matching_cause(self):
        with pytest.raises(OperationalError) as error:
            cause_serialization_failure()
        assert is_serialization_failure(error.value)

    def test_rejects_operational_error_without_matching_cause(self):
        error = OperationalError()
        cause = Exception()
        cause.pgcode = factory.make_name("pgcode")
        error.__cause__ = cause
        assert not is_serialization_failure(error)

    def test_rejects_operational_error_with_unrelated_cause(self):
        error = OperationalError()
        error.__cause__ = Exception()
        assert not is_serialization_failure(error)

    def test_rejects_operational_error_without_cause(self):
        error = OperationalError()
        assert not is_serialization_failure(error)

    def test_rejects_non_operational_error_with_matching_cause(self):
        error = factory.make_exception()
        cause = Exception()
        cause.pgcode = SERIALIZATION_FAILURE
        error.__cause__ = cause
        assert not is_serialization_failure(error)


class TestIsDeadlockFailure:
    """Tests relating to MAAS's use of catching deadlock failures."""

    def test_detects_operational_error_with_matching_cause(self):
        error = orm.make_deadlock_failure()
        assert is_deadlock_failure(error)

    def test_rejects_operational_error_without_matching_cause(self):
        error = OperationalError()
        cause = Exception()
        cause.pgcode = factory.make_name("pgcode")
        error.__cause__ = cause
        assert not is_deadlock_failure(error)

    def test_rejects_operational_error_with_unrelated_cause(self):
        error = OperationalError()
        error.__cause__ = Exception()
        assert not is_deadlock_failure(error)

    def test_rejects_operational_error_without_cause(self):
        error = OperationalError()
        assert not is_deadlock_failure(error)

    def test_rejects_non_operational_error_with_matching_cause(self):
        error = factory.make_exception()
        cause = Exception()
        cause.pgcode = DEADLOCK_DETECTED
        error.__cause__ = cause
        assert not is_deadlock_failure(error)


@pytest.mark.allow_transactions
class TestIsUniqueViolation:
    """Tests relating to MAAS's identification of unique violations."""

    @pytest.fixture(autouse=True)
    def _setup(self, transactional_maasdb):
        assert len(post_commit_hooks.hooks) == 0, (
            "One or more post-commit tasks were present before commencing "
            "this test."
        )
        post_commit_hooks.reset()
        create_uvtest_table()
        yield
        assert len(post_commit_hooks.hooks) == 0, (
            "One or more post-commit tasks were present at the end of this "
            "test."
        )
        post_commit_hooks.reset()

    def test_detects_integrity_error_with_matching_cause(self):
        with pytest.raises(IntegrityError) as error:
            cause_unique_violation(count(1))
        assert is_unique_violation(error.value)

    def test_rejects_integrity_error_without_matching_cause(self):
        error = IntegrityError()
        cause = Exception()
        cause.pgcode = factory.make_name("pgcode")
        error.__cause__ = cause
        assert not is_unique_violation(error)

    def test_rejects_integrity_error_with_unrelated_cause(self):
        error = IntegrityError()
        error.__cause__ = Exception()
        assert not is_unique_violation(error)

    def test_rejects_integrity_error_without_cause(self):
        error = IntegrityError()
        assert not is_unique_violation(error)

    def test_rejects_non_integrity_error_with_matching_cause(self):
        error = factory.make_exception()
        cause = Exception()
        cause.pgcode = UNIQUE_VIOLATION
        error.__cause__ = cause
        assert not is_unique_violation(error)


class TestIsForeignKeyViolation:
    """Tests relating to MAAS's use of catching foreign key violations."""

    def test_detects_violation_with_matching_cause(self):
        error = orm.make_foreign_key_violation()
        assert is_foreign_key_violation(error)

    def test_rejects_violation_without_matching_cause(self):
        error = OperationalError()
        cause = Exception()
        cause.pgcode = factory.make_name("pgcode")
        error.__cause__ = cause
        assert not is_foreign_key_violation(error)

    def test_rejects_violation_with_unrelated_cause(self):
        error = OperationalError()
        error.__cause__ = Exception()
        assert not is_foreign_key_violation(error)

    def test_rejects_violation_without_cause(self):
        error = OperationalError()
        assert not is_foreign_key_violation(error)

    def test_rejects_non_violation_with_matching_cause(self):
        error = factory.make_exception()
        cause = Exception()
        cause.pgcode = FOREIGN_KEY_VIOLATION
        error.__cause__ = cause
        assert not is_foreign_key_violation(error)


class TestIsRetryableFailure:
    """Tests relating to MAAS's use of catching retryable failures."""

    def test_detects_serialization_failure(self):
        error = orm.make_serialization_failure()
        assert is_retryable_failure(error)

    def test_detects_deadlock_failure(self):
        error = orm.make_deadlock_failure()
        assert is_retryable_failure(error)

    def test_detects_unique_violation(self):
        error = orm.make_unique_violation()
        assert is_retryable_failure(error)

    def test_detects_foreign_key_violation(self):
        error = orm.make_foreign_key_violation()
        assert is_retryable_failure(error)

    def test_rejects_operational_error_without_matching_cause(self):
        error = OperationalError()
        cause = Exception()
        cause.pgcode = factory.make_name("pgcode")
        error.__cause__ = cause
        assert not is_retryable_failure(error)

    def test_rejects_integrity_error_without_matching_cause(self):
        error = IntegrityError()
        cause = Exception()
        cause.pgcode = factory.make_name("pgcode")
        error.__cause__ = cause
        assert not is_retryable_failure(error)

    def test_rejects_operational_error_with_unrelated_cause(self):
        error = OperationalError()
        error.__cause__ = Exception()
        assert not is_retryable_failure(error)

    def test_rejects_integrity_error_with_unrelated_cause(self):
        error = IntegrityError()
        error.__cause__ = Exception()
        assert not is_retryable_failure(error)

    def test_rejects_operational_error_without_cause(self):
        error = OperationalError()
        assert not is_retryable_failure(error)

    def test_rejects_integrity_error_without_cause(self):
        error = IntegrityError()
        assert not is_retryable_failure(error)

    def test_rejects_non_database_error_with_cause_serialization(self):
        error = factory.make_exception()
        cause = Exception()
        cause.pgcode = SERIALIZATION_FAILURE
        error.__cause__ = cause
        assert not is_retryable_failure(error)

    def test_rejects_non_database_error_with_cause_deadlock(self):
        error = factory.make_exception()
        cause = Exception()
        cause.pgcode = DEADLOCK_DETECTED
        error.__cause__ = cause
        assert not is_retryable_failure(error)

    def test_rejects_non_database_error_with_cause_unique_violation(self):
        error = factory.make_exception()
        cause = Exception()
        cause.pgcode = UNIQUE_VIOLATION
        error.__cause__ = cause
        assert not is_retryable_failure(error)

    def test_rejects_non_database_error_with_cause_foreign_key_violation(self):
        error = factory.make_exception()
        cause = Exception()
        cause.pgcode = FOREIGN_KEY_VIOLATION
        error.__cause__ = cause
        assert not is_retryable_failure(error)


@pytest.mark.allow_transactions
class TestRetryOnRetryableFailure:
    @pytest.fixture(autouse=True)
    def _setup(self, transactional_maasdb, mocker):
        # Prevent real sleeps in the `orm` module.
        mocker.patch.object(orm, "sleep", lambda _: None)
        assert len(post_commit_hooks.hooks) == 0, (
            "One or more post-commit tasks were present before commencing "
            "this test."
        )
        post_commit_hooks.reset()
        create_stest_table()
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO stest VALUES (1)")
        yield
        assert len(post_commit_hooks.hooks) == 0, (
            "One or more post-commit tasks were present at the end of this "
            "test."
        )
        post_commit_hooks.reset()

    def make_mock_function(self):
        function_name = factory.make_name("function")
        function = Mock(__name__=function_name)
        return function

    def test_retries_on_serialization_failure(self):
        function = self.make_mock_function()
        function.side_effect = cause_serialization_failure
        function_wrapped = retry_on_retryable_failure(function)
        with pytest.raises(OperationalError):
            function_wrapped()
        expected_calls = [call()] * 10
        function.assert_has_calls(expected_calls)

    def test_retries_on_serialization_failure_until_successful(self):
        with pytest.raises(OperationalError) as error:
            cause_serialization_failure()
        serialization_error = error.value
        function = self.make_mock_function()
        function.side_effect = [serialization_error, sentinel.result]
        function_wrapped = retry_on_retryable_failure(function)
        assert sentinel.result == function_wrapped()
        function.assert_has_calls((call(), call()))

    def test_retries_on_deadlock_failure(self):
        function = self.make_mock_function()
        function.side_effect = orm.make_deadlock_failure()
        function_wrapped = retry_on_retryable_failure(function)
        with pytest.raises(OperationalError):
            function_wrapped()
        expected_calls = [call()] * 10
        function.assert_has_calls(expected_calls)

    def test_retries_on_deadlock_failure_until_successful(self):
        function = self.make_mock_function()
        function.side_effect = [orm.make_deadlock_failure(), sentinel.result]
        function_wrapped = retry_on_retryable_failure(function)
        assert sentinel.result == function_wrapped()
        function.assert_has_calls((call(), call()))

    def test_retries_on_unique_violation(self):
        function = self.make_mock_function()
        function.side_effect = orm.make_unique_violation()
        function_wrapped = retry_on_retryable_failure(function)
        with pytest.raises(IntegrityError):
            function_wrapped()
        expected_calls = [call()] * 10
        function.assert_has_calls(expected_calls)

    def test_retries_on_unique_violation_until_successful(self):
        function = self.make_mock_function()
        function.side_effect = [orm.make_unique_violation(), sentinel.result]
        function_wrapped = retry_on_retryable_failure(function)
        assert sentinel.result == function_wrapped()
        function.assert_has_calls((call(), call()))

    def test_retries_on_foreign_key_violation(self):
        function = self.make_mock_function()
        function.side_effect = orm.make_foreign_key_violation()
        function_wrapped = retry_on_retryable_failure(function)
        with pytest.raises(IntegrityError):
            function_wrapped()
        expected_calls = [call()] * 10
        function.assert_has_calls(expected_calls)

    def test_retries_on_foreign_key_violation_until_successful(self):
        function = self.make_mock_function()
        function.side_effect = [
            orm.make_foreign_key_violation(),
            sentinel.result,
        ]
        function_wrapped = retry_on_retryable_failure(function)
        assert sentinel.result == function_wrapped()
        function.assert_has_calls((call(), call()))

    def test_retries_on_retry_transaction(self):
        function = self.make_mock_function()
        function.side_effect = orm.RetryTransaction()
        function_wrapped = retry_on_retryable_failure(function)
        with pytest.raises(orm.TooManyRetries):
            function_wrapped()
        expected_calls = [call()] * 10
        function.assert_has_calls(expected_calls)

    def test_retries_on_retry_transaction_until_successful(self):
        function = self.make_mock_function()
        function.side_effect = [orm.RetryTransaction(), sentinel.result]
        function_wrapped = retry_on_retryable_failure(function)
        assert sentinel.result == function_wrapped()
        function.assert_has_calls((call(), call()))

    def test_passes_args_to_wrapped_function(self):
        function_wrapped = retry_on_retryable_failure(lambda a, b: (a, b))
        assert (sentinel.a, sentinel.b) == function_wrapped(
            sentinel.a, b=sentinel.b
        )

    def test_calls_reset_between_retries(self):
        reset = Mock()
        function = self.make_mock_function()
        function.side_effect = cause_serialization_failure
        function_wrapped = retry_on_retryable_failure(function, reset)
        with pytest.raises(OperationalError):
            function_wrapped()
        expected_function_calls = [call()] * 10
        function.assert_has_calls(expected_function_calls)
        # There's one fewer reset than calls to the function.
        expected_reset_calls = expected_function_calls[:-1]
        reset.assert_has_calls(expected_reset_calls)

    def test_does_not_call_reset_before_first_attempt(self):
        reset = Mock()
        function = self.make_mock_function()
        function.return_value = sentinel.all_is_okay
        function_wrapped = retry_on_retryable_failure(function, reset)
        function_wrapped()
        reset.assert_not_called()

    def test_uses_retry_context(self):
        @retry_on_retryable_failure
        def function_that_will_be_retried():
            assert orm.retry_context.active

        assert not orm.retry_context.active
        function_that_will_be_retried()
        assert not orm.retry_context.active

    def test_retry_contexts_accumulate(self):
        accumulated, entered, exited = [], [], []

        @contextmanager
        def observe(thing):
            # Record `thing` on entry.
            entered.append(thing)
            try:
                yield sentinel.ignored
            finally:
                # Record `thing` on exit.
                exited.append(thing)

        @retry_on_retryable_failure
        def accumulate_and_observe():
            # `accumulated` is a record of every time this function is called.
            # `entered` and `exited` record what's going on with the contexts
            # we're throwing up into the retry machinery.
            count = len(accumulated)
            accumulated.append(count)
            request_transaction_retry(observe(count))

        with pytest.raises(orm.TooManyRetries):
            accumulate_and_observe()
        # `entered` and `exited` will contain all but the highest element in
        # `accumulated` because the final context is not entered nor exited.
        expected = accumulated[:-1]
        assert expected == entered
        expected.reverse()
        assert expected == exited


class TestMakeSerializationFailure:
    """Tests for `make_serialization_failure`."""

    def test_makes_a_serialization_failure(self):
        exception = orm.make_serialization_failure()
        assert is_serialization_failure(exception), (
            f"{exception} is not a serialization failure."
        )


class TestMakeDeadlockFailure:
    """Tests for `make_deadlock_failure`."""

    def test_makes_a_deadlock_failure(self):
        exception = orm.make_deadlock_failure()
        assert is_deadlock_failure(exception), (
            f"{exception} is not a deadlock failure."
        )


class TestMakeUniqueViolation:
    """Tests for `make_unique_violation`."""

    def test_makes_a_unique_violation(self):
        exception = orm.make_unique_violation()
        assert is_unique_violation(exception), (
            f"{exception} is not a unique violation."
        )


class TestMakeForeignKeyViolation:
    """Tests for `make_foreign_key_violation`."""

    def test_makes_a_foreign_key_violation(self):
        exception = orm.make_foreign_key_violation()
        assert is_foreign_key_violation(exception), (
            f"{exception} is not a foreign key violation."
        )


class PopulateContext:
    """A simple context manager that puts `thing` in `alist`."""

    def __init__(self, alist, thing):
        self.alist, self.thing = alist, thing

    def __enter__(self):
        self.alist.append(self.thing)
        return sentinel.irrelevant

    def __exit__(self, *exc_info):
        assert self.alist.pop() is self.thing


class CrashEntryContext:
    """A simple context manager that crashes on entry."""

    def __enter__(self):
        0 / 0  # Divide by zero and break everything.  # noqa: B018

    def __exit__(self, *exc_info):
        pass  # Nothing left to break.


class CrashExitContext:
    """A simple context manager that crashes on exit."""

    def __enter__(self):
        pass  # What a lovely day this is...

    def __exit__(self, *exc_info):
        0 / 0  # Nah, destroy everything.  # noqa: B018


class TestRetryStack:
    """Tests for `RetryStack`."""

    def test_add_and_enter_pending_contexts(self):
        names = []
        with orm.RetryStack() as stack:
            stack.add_pending_contexts(
                [
                    PopulateContext(names, "alice"),
                    PopulateContext(names, "bob"),
                    PopulateContext(names, "carol"),
                ]
            )
            # These contexts haven't been entered yet.
            assert names == []
            # They're entered when `enter_pending_contexts` is called.
            stack.enter_pending_contexts()
            # The contexts are entered in the order specified.
            assert names == ["alice", "bob", "carol"]
        # These contexts have been exited again.
        assert names == []

    def test_each_context_entered_only_once_even_if_added_twice(self):
        names = []
        with orm.RetryStack() as stack:
            dave = PopulateContext(names, "dave")
            stack.add_pending_contexts([dave, dave])
            stack.enter_pending_contexts()
            # The `dave` context is entered only once.
            assert names == ["dave"]
        # The `dave` context has been exited.
        assert names == []

    def test_each_context_entered_only_once_even_if_enter_called_twice(self):
        names = []
        with orm.RetryStack() as stack:
            dave = PopulateContext(names, "dave")
            stack.add_pending_contexts([dave])
            stack.enter_pending_contexts()
            stack.enter_pending_contexts()
            # The `dave` context is entered only once.
            assert names == ["dave"]
        # The `dave` context has been exited.
        assert names == []

    def test_crash_entering_context_is_propagated(self):
        with orm.RetryStack() as stack:
            stack.add_pending_contexts([CrashEntryContext()])
            with pytest.raises(ZeroDivisionError):
                stack.enter_pending_contexts()

    def test_crash_exiting_context_is_propagated(self):
        with orm.RetryStack() as stack:
            stack.add_pending_contexts([CrashExitContext()])
            stack.enter_pending_contexts()
            # Use `ExitStack.close` here to elicit the crash.
            with pytest.raises(ZeroDivisionError):
                stack.close()


class TestRetryContext:
    """Tests for `RetryContext`."""

    def test_starts_off_with_nothing(self):
        context = orm.RetryContext()
        assert not context.active
        assert context.stack is None

    def test_creates_stack_on_entry(self):
        context = orm.RetryContext()
        with context:
            assert context.active
            assert isinstance(context.stack, orm.RetryStack)

    def test_prepare_enters_pending_contexts(self):
        context = orm.RetryContext()
        with context:
            context.stack.add_pending_contexts([CrashEntryContext()])
            with pytest.raises(ZeroDivisionError):
                context.prepare()

    def test_destroys_stack_on_exit(self):
        names = []
        context = orm.RetryContext()
        with context:
            assert context.active
            context.stack.add_pending_contexts(
                [
                    PopulateContext(names, "alice"),
                    PopulateContext(names, "bob"),
                ]
            )
            context.prepare()
            assert names == ["alice", "bob"]
        assert not context.active
        assert context.stack is None
        assert names == []

    def test_destroys_stack_on_exit_even_when_there_is_a_crash(self):
        names = []
        context = orm.RetryContext()
        with pytest.raises(ZeroDivisionError, match="division by zero"):
            with context:
                context.stack.add_pending_contexts(
                    [
                        PopulateContext(names, "alice"),
                        CrashEntryContext(),
                        PopulateContext(names, "bob"),
                    ]
                )
                context.prepare()
                assert names == ["alice", "bob"]
        assert not context.active
        assert context.stack is None
        assert names == []


class TestRequestTransactionRetry:
    """Tests for `request_transaction_retry`."""

    def test_raises_a_retry_transaction_exception(self):
        with orm.retry_context:
            with pytest.raises(orm.RetryTransaction):
                request_transaction_retry()

    def test_adds_additional_contexts_to_retry_context(self):
        contexts = []
        with orm.retry_context:
            with pytest.raises(orm.RetryTransaction):
                request_transaction_retry(
                    PopulateContext(contexts, "alice"),
                    PopulateContext(contexts, "bob"),
                    PopulateContext(contexts, "carol"),
                )
            # These contexts are added as "pending"...
            assert contexts == []
            # They're entered when `prepare` is called (which is done by the
            # retry machinery; normal application code doesn't do this).
            orm.retry_context.prepare()
            # The contexts are entered in the order specified.
            assert contexts == ["alice", "bob", "carol"]
        # The contexts are exited in the order specified.
        assert contexts == []


class TestGenRetryIntervals:
    """Tests for `orm.gen_retry_intervals`."""

    def remove_jitter(self, mocker):
        # Remove the effect of randomness.
        full_jitter = mocker.patch.object(orm, "full_jitter")
        full_jitter.side_effect = lambda thing: thing

    def test_unjittered_series_begins(self, mocker):
        self.remove_jitter(mocker)
        # Get the first 10 intervals, without jitter.
        intervals = islice(orm.gen_retry_intervals(), 10)
        # Convert from seconds to milliseconds, and round.
        intervals = [int(interval * 1000) for interval in intervals]
        # They start off small, but grow rapidly to the maximum.
        assert intervals == [
            25,
            62,
            156,
            390,
            976,
            2441,
            6103,
            10000,
            10000,
            10000,
        ]

    def test_pulls_from_exponential_series_until_maximum_is_reached(
        self, mocker
    ):
        self.remove_jitter(mocker)
        # repeat() is the tail-end of the interval series.
        repeat = mocker.patch.object(orm, "repeat")
        repeat.return_value = [sentinel.end]
        maximum = randint(10, 100)
        intervals = list(orm.gen_retry_intervals(maximum=maximum))
        assert intervals[-1] is sentinel.end
        for interval in intervals[:-1]:
            assert interval <= maximum


class TestPostCommitHooks:
    """Tests for the `post_commit_hooks` singleton."""

    @pytest.fixture(autouse=True)
    def _hooks(self):
        yield
        post_commit_hooks.reset()

    def test_crashes_on_enter_if_hooks_exist(self):
        hook = Deferred()
        post_commit_hooks.add(hook)
        with pytest.raises(
            TransactionManagementError, match="Orphaned post-commit hooks"
        ):
            with post_commit_hooks:
                pass
        # The hook has been cancelled, but CancelledError is suppressed in
        # hooks, so we don't see it here.
        assert hook.called
        # The hook list is cleared so that the exception is raised only once.
        assert list(post_commit_hooks.hooks) == []

    def test_fires_hooks_on_exit_if_no_exception(self, mocker):
        hooks_fire = mocker.patch.object(
            post_commit_hooks, "fire", autospec=True
        )
        with post_commit_hooks:
            post_commit_hooks.add(Deferred())
        # Hooks are fired.
        hooks_fire.assert_called_once_with()

    def test_resets_hooks_on_exit_if_exception(self, mocker):
        hooks_fire = mocker.patch.object(
            post_commit_hooks, "fire", autospec=True
        )
        hooks_reset = mocker.patch.object(
            post_commit_hooks, "reset", autospec=True
        )
        exception_type = factory.make_exception_type()
        with pytest.raises(exception_type, match=r"^$"):
            with post_commit_hooks:
                post_commit_hooks.add(Deferred())
                raise exception_type()
        # No hooks were fired; they were reset immediately.
        hooks_fire.assert_not_called()
        hooks_reset.assert_called_once_with()


class TestPostCommit:
    """Tests for the `post_commit` function."""

    @pytest.fixture(autouse=True)
    def _hooks(self):
        yield
        post_commit_hooks.reset()

    def test_adds_Deferred_as_hook(self):
        hook = Deferred()
        hook_added = post_commit(hook)
        assert [hook] == list(post_commit_hooks.hooks)
        assert hook_added is hook

    def test_adds_new_Deferred_as_hook_when_called_without_args(self):
        hook_added = post_commit()
        assert [hook_added] == list(post_commit_hooks.hooks)
        assert isinstance(hook_added, Deferred)

    def test_adds_callable_as_hook(self):
        def hook(arg):
            pass

        hook_added = post_commit(hook)
        assert len(post_commit_hooks.hooks) == 1
        assert isinstance(hook_added, Deferred)

    def test_fire_calls_back_with_None_to_Deferred_hook(self):
        hook = Deferred()
        spy = DeferredValue()
        spy.observe(hook)
        post_commit(hook)
        post_commit_hooks.fire()
        assert extract_result(spy.get()) is None

    def test_fire_calls_back_with_None_to_new_Deferred_hook(self):
        hook_added = post_commit()
        spy = DeferredValue()
        spy.observe(hook_added)
        post_commit_hooks.fire()
        assert extract_result(spy.get()) is None

    def test_reset_cancels_Deferred_hook(self):
        hook = Deferred()
        spy = DeferredValue()
        spy.observe(hook)
        post_commit(hook)
        post_commit_hooks.reset()
        with pytest.raises(CancelledError):
            extract_result(spy.get())

    def test_reset_cancels_new_Deferred_hook(self):
        hook_added = post_commit()
        spy = DeferredValue()
        spy.observe(hook_added)
        post_commit_hooks.reset()
        with pytest.raises(CancelledError):
            extract_result(spy.get())

    def test_fire_passes_None_to_callable_hook(self):
        hook = Mock()
        post_commit(hook)
        post_commit_hooks.fire()
        hook.assert_called_once_with(None)

    def test_reset_passes_Failure_to_callable_hook(self):
        hook = Mock()
        post_commit(hook)
        post_commit_hooks.reset()
        hook.assert_called_once_with(ANY)
        arg = hook.call_args[0][0]
        assert isinstance(arg, Failure)
        assert isinstance(arg.value, CancelledError)

    def test_rejects_other_hook_types(self):
        with pytest.raises(AssertionError):
            post_commit(sentinel.hook)


class TestPostCommitDo:
    """Tests for the `post_commit_do` function."""

    @pytest.fixture(autouse=True)
    def _hooks(self):
        yield
        post_commit_hooks.reset()

    def test_adds_callable_as_hook(self):
        def hook(arg):
            pass

        post_commit_do(hook)
        assert len(post_commit_hooks.hooks) == 1

    def test_returns_actual_hook(self):
        hook = Mock()
        hook_added = post_commit_do(hook, sentinel.foo, bar=sentinel.bar)
        assert isinstance(hook_added, Deferred)
        callback, errback = hook_added.callbacks.pop(0)
        # Errors are passed through; they're not passed to our hook.
        assert errback == (_failthru, (), {})
        # Our hook is set to be called via callOut.
        assert callback == (
            (callOut, (hook, sentinel.foo), {"bar": sentinel.bar})
        )

    def test_fire_passes_only_args_to_hook(self):
        hook = Mock()
        post_commit_do(hook, sentinel.arg, foo=sentinel.bar)
        post_commit_hooks.fire()
        hook.assert_called_once_with(sentinel.arg, foo=sentinel.bar)

    def test_reset_does_not_call_hook(self):
        hook = Mock()
        post_commit_do(hook)
        post_commit_hooks.reset()
        hook.assert_not_called()

    def test_rejects_other_hook_types(self):
        with pytest.raises(AssertionError):
            post_commit_do(sentinel.hook)


@pytest.mark.allow_transactions
@pytest.mark.usefixtures("transactional_maasdb")
class TestConnected:
    """Tests for the `orm.connected` context manager."""

    def test_ensures_connection(self):
        with orm.connected():
            assert connection.connection is not None

    def test_opens_and_closes_connection_when_no_preexisting_connection(self):
        connection.close()

        assert connection.connection is None
        with orm.connected():
            assert connection.connection is not None
        assert connection.connection is None

    def test_leaves_preexisting_connections_alone(self):
        connection.ensure_connection()
        preexisting_connection = connection.connection

        assert connection.connection is not None
        with orm.connected():
            assert connection.connection is preexisting_connection
        assert connection.connection is preexisting_connection

    def test_disconnects_and_reconnects_if_not_usable(self, mocker):
        connection.ensure_connection()
        preexisting_connection = connection.connection

        connection.errors_occurred = True
        mocker.patch.object(connection, "is_usable", return_value=False)

        assert connection.connection is not None
        with orm.connected():
            assert connection.connection is not preexisting_connection
            assert connection.connection is not None

        assert connection.connection is not preexisting_connection
        assert connection.connection is not None


@pytest.mark.allow_transactions
@pytest.mark.usefixtures("transactional_maasdb")
class TestWithConnection:
    """Tests for the `orm.with_connection` decorator."""

    def test_exposes_original_function(self):
        function = Mock(__name__=factory.make_name("function"))
        assert orm.with_connection(function).func is function

    def test_ensures_function_is_called_within_connected_context(self, mocker):
        context = mocker.patch.object(orm, "connected").return_value = (
            StubContext()
        )

        @orm.with_connection
        def function(arg, kwarg):
            assert arg is sentinel.arg
            assert kwarg is sentinel.kwarg
            assert context.active
            return sentinel.result

        assert context.unused
        assert function(sentinel.arg, kwarg=sentinel.kwarg) is sentinel.result
        assert context.used


@pytest.mark.allow_transactions
class TestTransactional:
    @pytest.fixture(autouse=True)
    def _setup(self, transactional_maasdb):
        assert len(post_commit_hooks.hooks) == 0, (
            "One or more post-commit tasks were present before commencing "
            "this test."
        )
        post_commit_hooks.reset()
        yield
        assert len(post_commit_hooks.hooks) == 0, (
            "One or more post-commit tasks were present at the end of this "
            "test."
        )
        post_commit_hooks.reset()

    def test_exposes_original_function(self):
        function = Mock(__name__=factory.make_name("function"))
        assert orm.transactional(function).func is function

    def test_calls_function_within_transaction_then_closes_connections(self):
        # Close the database connection to begin with.
        connection.close()

        # No transaction has been entered (what Django calls an atomic block),
        # and the connection has not yet been established.
        assert not connection.in_atomic_block
        assert connection.connection is None

        def check_inner(*args, **kwargs):
            # In here, the transaction (`atomic`) has been started but is not
            # over, and the connection to the database is open.
            assert connection.in_atomic_block
            assert connection.connection is not None

        function = Mock()
        function.__name__ = factory.make_name("function")
        function.side_effect = check_inner

        # Call `function` via the `transactional` decorator.
        decorated_function = orm.transactional(function)
        decorated_function(sentinel.arg, kwarg=sentinel.kwarg)

        # `function` was called -- and therefore `check_inner` too --
        # and the arguments passed correctly.
        function.assert_called_once_with(sentinel.arg, kwarg=sentinel.kwarg)

        # After the decorated function has returned the transaction has
        # been exited, and the connection has been closed.
        assert not connection.in_atomic_block
        assert connection.connection is None

    def test_leaves_preexisting_connections_open(self):
        # Ensure there's a database connection to begin with.
        connection.ensure_connection()

        # No transaction has been entered (what Django calls an atomic block),
        # but the connection has been established.
        assert not connection.in_atomic_block
        assert connection.connection is not None

        # Call a function via the `transactional` decorator.
        decorated_function = orm.transactional(lambda: None)
        decorated_function()

        # After the decorated function has returned the transaction has
        # been exited, but the preexisting connection remains open.
        assert not connection.in_atomic_block
        assert connection.connection is not None

    def test_closes_connections_only_when_leaving_atomic_block(self):
        # Close the database connection to begin with.
        connection.close()
        assert connection.connection is None

        @orm.transactional
        def inner():
            # We're inside a `transactional` context here.
            assert connection.connection is not None
            return "inner"

        @orm.transactional
        def outer():
            # We're inside a `transactional` context here too.
            assert connection.connection is not None
            # Call `inner`, thus nesting `transactional` contexts.
            return "outer > " + inner()

        assert "outer > inner" == outer()
        # The connection has been closed.
        assert connection.connection is None

    def test_fires_post_commit_hooks_when_done(self, mocker):
        fire = mocker.patch.object(orm.post_commit_hooks, "fire")

        def function():
            return sentinel.something

        decorated_function = orm.transactional(function)
        assert decorated_function() is sentinel.something
        fire.assert_called_once_with()

    def test_crashes_if_hooks_exist_before_entering_transaction(self):
        post_commit(lambda failure: None)
        decorated_function = orm.transactional(lambda: None)
        with pytest.raises(TransactionManagementError):
            decorated_function()
        # The hook list is cleared so that the exception is raised only once.
        assert list(post_commit_hooks.hooks) == []

    def test_creates_post_commit_hook_savepoint_on_inner_block(self):
        hooks = post_commit_hooks.hooks

        @orm.transactional
        def inner():
            # We're inside a savepoint context here.
            assert post_commit_hooks.hooks is not hooks
            return "inner"

        @orm.transactional
        def outer():
            # We're inside a transaction here, but not yet a savepoint.
            assert post_commit_hooks.hooks is hooks
            return "outer > " + inner()

        assert "outer > inner" == outer()


@pytest.mark.allow_transactions
class TestTransactionalRetries:
    @pytest.fixture(autouse=True)
    def _setup(self, transactional_maasdb, mocker):
        # Prevent real sleeps in the `orm` module.
        mocker.patch.object(orm, "sleep", lambda _: None)
        assert len(post_commit_hooks.hooks) == 0, (
            "One or more post-commit tasks were present before commencing "
            "this test."
        )
        post_commit_hooks.reset()
        create_stest_table()
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("INSERT INTO stest VALUES (1)")
        yield
        assert len(post_commit_hooks.hooks) == 0, (
            "One or more post-commit tasks were present at the end of this "
            "test."
        )
        post_commit_hooks.reset()

    def test_retries_upon_serialization_failures(self):
        function = Mock()
        function.__name__ = factory.make_name("function")
        function.side_effect = cause_serialization_failure
        decorated_function = orm.transactional(function)

        with pytest.raises(OperationalError):
            decorated_function()
        expected_calls = [call()] * 10
        function.assert_has_calls(expected_calls)

    def test_resets_post_commit_hooks_when_retrying(self, mocker):
        reset = mocker.patch.object(orm.post_commit_hooks, "reset")

        function = Mock()
        function.__name__ = factory.make_name("function")
        function.side_effect = cause_serialization_failure
        decorated_function = orm.transactional(function)

        with pytest.raises(OperationalError):
            decorated_function()
        # reset() is called 9 times by retry_on_serialization_failure() then
        # once more by transactional().
        expected_reset_calls = [call()] * 10
        reset.assert_has_calls(expected_reset_calls)

    def test_post_commit_hooks_from_failed_attempt_do_not_fire_on_retry(self):
        stale_hook = Mock()
        successful_hook = Mock()
        call_count = [0]

        with pytest.raises(OperationalError) as error:
            cause_serialization_failure()
        serialization_error = error.value

        def foo():
            call_count[0] += 1
            if call_count[0] == 1:
                # Register a hook that should be discarded and raise a retriable serialization error. This post
                # commit hook should be discarded between retries.
                post_commit_do(stale_hook)
                raise serialization_error
            else:
                post_commit_do(successful_hook)

        decorated_function = orm.transactional(foo)
        decorated_function()

        stale_hook.assert_not_called()
        successful_hook.assert_called_once_with()


@pytest.mark.allow_transactions
@pytest.mark.usefixtures("transactional_maasdb")
class TestSavepoint:
    """Tests for `savepoint`."""

    def test_crashes_if_not_already_within_transaction(self):
        with pytest.raises(
            TransactionManagementError,
            match="Savepoints cannot be created outside of a transaction",
        ):
            with savepoint():
                pass

    def test_creates_savepoint_for_transaction_and_post_commit_hooks(self):
        hooks = post_commit_hooks.hooks
        with transaction.atomic():
            assert len(connection.savepoint_ids) == 0
            with savepoint():
                # We're one savepoint in.
                assert len(connection.savepoint_ids) == 1
                # Post-commit hooks have been saved.
                assert post_commit_hooks.hooks is not hooks
            assert len(connection.savepoint_ids) == 0


@pytest.mark.allow_transactions
@pytest.mark.usefixtures("transactional_maasdb")
class TestInTransaction:
    """Tests for `in_transaction`."""

    def test_true_within_atomic_block(self):
        with transaction.atomic():
            assert in_transaction()

    def test_false_when_no_transaction_is_active(self):
        assert not in_transaction()


@pytest.mark.allow_transactions
@pytest.mark.usefixtures("transactional_maasdb")
class TestValidateInTransaction:
    """Tests for `validate_in_transaction`."""

    def test_does_nothing_within_atomic_block(self):
        with transaction.atomic():
            validate_in_transaction(connection)

    def test_explodes_when_no_transaction_is_active(self):
        with pytest.raises(TransactionManagementError):
            validate_in_transaction(connection)


class TestPsqlArray:
    def test_returns_empty_array(self):
        assert ("ARRAY[]", []) == psql_array([])

    def test_returns_params_in_array(self):
        assert "ARRAY[%s,%s,%s]" == psql_array(["a", "a", "a"])[0]

    def test_returns_params_in_tuple(self):
        params = [factory.make_name("param") for _ in range(3)]
        assert params == psql_array(params)[1]

    def test_returns_cast_to_type(self):
        assert ("ARRAY[]::integer[]", []) == psql_array([], sql_type="integer")


@pytest.mark.allow_transactions
class TestDisablingDatabaseConnections:
    @pytest.fixture(autouse=True)
    def _enable_connections(self, transactional_maasdb):
        yield
        enable_all_database_connections()

    def assertConnectionsEnabled(self):
        for alias in connections:
            assert isinstance(connections[alias], BaseDatabaseWrapper)

    def assertConnectionsDisabled(self):
        for alias in connections:
            assert DisabledDatabaseConnection is type(connections[alias])

    def test_disable_and_enable_connections(self):
        # By default connections are enabled.
        self.assertConnectionsEnabled()

        # Disable all connections.
        disable_all_database_connections()
        self.assertConnectionsDisabled()

        # Back to the start again.
        enable_all_database_connections()
        self.assertConnectionsEnabled()

    def test_disable_can_be_called_multiple_times(self):
        disable_all_database_connections()
        self.assertConnectionsDisabled()
        disable_all_database_connections()
        self.assertConnectionsDisabled()

    def test_DisabledDatabaseConnection(self):
        connection = DisabledDatabaseConnection()
        with pytest.raises(RuntimeError):
            connection.connect  # noqa: B018
        with pytest.raises(RuntimeError):
            connection.__call__  # noqa: B018
        with pytest.raises(RuntimeError):
            connection.foo = "bar"
        with pytest.raises(RuntimeError):
            del connection.baz
        assert connection.close() is None


@pytest.mark.allow_transactions
class TestTotallyDisconnected:
    """Tests for `TotallyDisconnected`."""

    @pytest.fixture(autouse=True)
    def _close_connection(self, transactional_maasdb):
        yield
        connection.close()

    def test_enter_closes_open_connections_and_disables_new_ones(self):
        connection.ensure_connection()
        with TotallyDisconnected():
            with pytest.raises(RuntimeError):
                connection.connect  # noqa: B018
        connection.ensure_connection()

    def test_exit_removes_block_on_database_connections(self):
        with TotallyDisconnected():
            with pytest.raises(RuntimeError):
                connection.connect  # noqa: B018
        connection.ensure_connection()


@pytest.mark.allow_transactions
class TestFullyConnected:
    """Tests for `FullyConnected`."""

    @pytest.fixture(autouse=True)
    def _setup(self, transactional_maasdb):
        yield
        # Leave all connections closed.
        for alias in connections:
            connections[alias].close()

    def assertOpen(self, alias):
        assert connections[alias].connection is not None

    def assertClosed(self, alias):
        assert connections[alias].connection is None

    def test_opens_and_closes_connections(self):
        for alias in connections:
            connections[alias].close()
        for alias in connections:
            self.assertClosed(alias)
        with FullyConnected():
            for alias in connections:
                self.assertOpen(alias)
        for alias in connections:
            self.assertClosed(alias)

    def test_closes_connections_even_if_open_on_entry(self):
        for alias in connections:
            connections[alias].ensure_connection()
        for alias in connections:
            self.assertOpen(alias)
        with FullyConnected():
            for alias in connections:
                self.assertOpen(alias)
        for alias in connections:
            self.assertClosed(alias)

    def test_service_layer_initialized_and_closed(self, mocker):
        mocker.patch.object(service_layer, "init")
        mocker.patch.object(service_layer, "close")
        for alias in connections:
            connections[alias].ensure_connection()
        for alias in connections:
            self.assertOpen(alias)

        with FullyConnected():
            pass
        service_layer.init.assert_called_once()
        service_layer.close.assert_called_once()


@pytest.mark.usefixtures("maasdb")
class TestGetModelObjectName:
    def test_gets_model_object_name_from_manager(self):
        assert "Node" == get_model_object_name(Node.objects)

    def test_gets_model_object_name_from_queryset(self):
        assert "Node" == get_model_object_name(Node.objects.all())

    def test_gets_model_object_name_returns_none_if_not_found(self):
        assert get_model_object_name("crazytalk") is None


@pytest.mark.usefixtures("maasdb")
class TestCountQueries:
    def test_logs_all_queries_made_by_func(self):
        def query_func():
            return list(Node.objects.all())

        mock_print = Mock()
        wrapped = count_queries(mock_print)(query_func)
        wrapped()

        query_time = sum(
            float(query.get("time", 0)) for query in connection.queries
        )
        mock_print.assert_called_once_with(
            f"[QUERIES] query_func executed 1 queries in {query_time} seconds"
        )

    def test_resets_queries_between_calls(self):
        def query_func():
            return list(Node.objects.all())

        mock_print = Mock()
        wrapped = count_queries(mock_print)(query_func)

        # First call.
        wrapped()
        query_time_one = sum(
            float(query.get("time", 0)) for query in connection.queries
        )

        # Second call.
        wrapped()
        query_time_two = sum(
            float(query.get("time", 0)) for query in connection.queries
        )

        # Print called twice.
        mock_print.assert_has_calls(
            (
                call(
                    f"[QUERIES] query_func executed 1 queries in {query_time_one} seconds"
                ),
                call(
                    f"[QUERIES] query_func executed 1 queries in {query_time_two} seconds"
                ),
            ),
        )

    def test_logs_all_queries_made(self):
        def query_func():
            return list(Node.objects.all())

        log_sql_calls(query_func)

        mock_print = Mock()
        wrapped = count_queries(mock_print)(query_func)
        wrapped()
        query_time = sum(
            float(query.get("time", 0)) for query in connection.queries
        )

        # Print called twice.
        mock_print.assert_has_calls(
            [
                call(
                    "[QUERIES] query_func executed 1 queries in %s seconds"
                    % query_time
                ),
                call("[QUERIES] === Start SQL Log: query_func ==="),
                call("[QUERIES] %s" % connection.queries[0]["sql"]),
                call("[QUERIES] === End SQL Log: query_func ==="),
            ]
        )
