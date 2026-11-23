# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from django.db import connection
import pytest
from sqlalchemy import text

from maasserver.sqlalchemy import get_sqlalchemy_django_connection
from maastesting.querycounter import count_queries, CountQueries


@pytest.mark.usefixtures("maasdb")
class TestCountQueries:
    def test_counts_django_and_sqlalchemy_queries(self):
        with CountQueries() as counter:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            get_sqlalchemy_django_connection().execute(text("SELECT 2"))

        assert counter.count == 2
        assert len(counter.queries) == 1

    def test_counts_sqlalchemy_query(self):
        with CountQueries() as counter:
            get_sqlalchemy_django_connection().execute(text("SELECT 2"))

        assert counter.count == 1
        assert counter.queries == []

    def test_reset_starts_counting_at_context_entry(self):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")

        with CountQueries(reset=True) as counter:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 2")

        assert counter.count == 1
        assert len(counter.queries) == 1

    def test_ignored_marker_sql_is_excluded(self):
        with CountQueries() as counter:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 /* COUNTQUERIES-IGNOREME */")
                cursor.execute("SELECT 2")

        assert counter.count == 1
        assert len(counter.queries) == 1
        assert "SELECT 2" in counter.queries[0]["sql"]

    def test_query_function_returns_result_and_count(self):
        def query():
            with connection.cursor() as cursor:
                cursor.execute("SELECT 3")
                return cursor.fetchone()[0]

        count, result = count_queries(query)

        assert count == 1
        assert result == 3

    def test_exception_restores_django_debug_cursor(self):
        previous_force_debug = connection.force_debug_cursor

        with pytest.raises(RuntimeError, match="query failed"):
            with CountQueries():
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 4")
                raise RuntimeError("query failed")

        assert connection.force_debug_cursor is previous_force_debug

    def test_exception_does_not_leak_sqlalchemy_counter(self):
        with pytest.raises(RuntimeError, match="query failed"):
            with CountQueries():
                get_sqlalchemy_django_connection().execute(text("SELECT 1"))
                raise RuntimeError("query failed")

        with CountQueries() as counter:
            get_sqlalchemy_django_connection().execute(text("SELECT 2"))

        assert counter.count == 1
