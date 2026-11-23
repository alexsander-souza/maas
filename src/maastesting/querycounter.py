# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Helpers for counting database queries in tests."""

from django.core.signals import request_started
from django.db import connections, DEFAULT_DB_ALIAS, reset_queries

from maastesting.sqlalchemy import SQLAlchemyQueryCounter


class CountQueries:
    """Count Django and SQLAlchemy queries issued inside a context."""

    def __init__(self, reset=False):
        self.reset = reset
        self.connection = connections[DEFAULT_DB_ALIAS]
        self._start_count = 0
        self._queries = []
        self._sqlalchemy_count = 0
        self._sqlalchemy_counter = SQLAlchemyQueryCounter()

    def __enter__(self):
        self.force_debug_cursor = self.connection.force_debug_cursor
        self.connection.force_debug_cursor = True
        if self.reset:
            reset_queries()
        self._sqlalchemy_counter.install()
        self._start_count = len(self.connection.queries)
        request_started.disconnect(reset_queries)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            recent = self.connection.queries[self._start_count :]
            self._queries = [
                query
                for query in recent
                if "COUNTQUERIES-IGNOREME" not in query.get("sql", "")
            ]
            self._sqlalchemy_count = self._sqlalchemy_counter.count
        finally:
            self.connection.force_debug_cursor = self.force_debug_cursor
            request_started.connect(reset_queries)
            self._sqlalchemy_counter.remove()

    @property
    def count(self):
        return len(self._queries) + self._sqlalchemy_count

    @property
    def queries(self):
        """Return the non-ignored Django query records from this context."""
        return self._queries


def count_queries(func, *args, **kwargs):
    """Execute `func`, returning its query count and result."""
    counter = CountQueries()
    with counter:
        result = func(*args, **kwargs)
    return counter.count, result
