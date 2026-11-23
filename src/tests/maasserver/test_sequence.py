# Copyright 2012-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test :class:`Sequence`."""

from itertools import islice
import random

from django.db import connection, transaction
from django.db.utils import DataError, ProgrammingError
import pytest

from maasserver.sequence import Sequence
from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestSequence:
    def query_seq(self, name):
        with connection.cursor() as cursor:
            cursor.execute("SELECT nextval(%s)", [name])
            return cursor.fetchone()[0]

    def test_create_sequence(self):
        name = factory.make_name("seq", sep="")
        seq = Sequence(name)
        seq.create_if_not_exists()
        val = self.query_seq(seq.name)
        assert val == 1

    def test_create_if_not_exists_does_not_fail_if_sequence_exists(self):
        name = factory.make_name("seq", sep="")
        seq = Sequence(name)
        seq.create_if_not_exists()
        seq.create_if_not_exists()
        assert next(seq) == 1

    def test_sequence_respects_minvalue(self):
        name = factory.make_name("seq", sep="")
        minvalue = random.randint(1, 50)
        seq = Sequence(name, minvalue=minvalue)
        seq.create_if_not_exists()
        val = self.query_seq(seq.name)
        assert val == minvalue

    def test_sequence_respects_start(self):
        name = factory.make_name("seq", sep="")
        start = random.randint(5, 50)
        seq = Sequence(name, start=start)
        seq.create_if_not_exists()
        val = self.query_seq(seq.name)
        assert val == start

    def test_sequence_respects_increment(self):
        name = factory.make_name("seq", sep="")
        increment = random.randint(1, 50)
        seq = Sequence(name, increment=increment)
        seq.create_if_not_exists()
        val = self.query_seq(seq.name)
        val = self.query_seq(seq.name)
        assert val == 1 + increment

    def test_sequence_respects_maxvalue_and_cycles(self):
        name = factory.make_name("seq", sep="")
        maxvalue = random.randint(10, 50)
        seq = Sequence(name, maxvalue=maxvalue)
        seq.create_if_not_exists()
        cursor = connection.cursor()
        query = "ALTER SEQUENCE %s" % seq.name
        cursor.execute(query + " RESTART WITH %s", [maxvalue])
        val = self.query_seq(seq.name)
        val = self.query_seq(seq.name)
        assert val == 1

    def test_sequence_cycling_can_be_prevented(self):
        seq = Sequence("alice", maxvalue=2, cycle=False)
        seq.create_if_not_exists()
        assert [next(seq), next(seq)] == [1, 2]
        with pytest.raises(
            DataError, match="nextval: reached maximum value of sequence"
        ):
            with transaction.atomic():
                next(seq)

    def test_sequence_can_be_owned(self):
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE alice (bob INT)")
        seq = Sequence("carol", owner="alice.bob")
        seq.create_if_not_exists()
        assert next(seq) == 1
        # Dropping the table drops the sequence too.
        with connection.cursor() as cursor:
            cursor.execute("DROP TABLE alice")
        with pytest.raises(
            ProgrammingError, match='relation "carol" does not exist'
        ):
            with transaction.atomic():
                self.query_seq(seq.name)

    def test_sequence_will_be_created_automatically_on_first_access(self):
        seq = Sequence("dave")
        # Accessing the sequence directly in the database we find that it's
        # not there.
        with pytest.raises(ProgrammingError, match="does not exist"):
            with transaction.atomic():
                self.query_seq(seq.name)
        # Iterating via `Sequence` automatically vivifies it.
        assert next(seq) == 1
        assert self.query_seq(seq.name) == 2

    def test_next_returns_sequential_values(self):
        name = factory.make_name("seq", sep="")
        seq = Sequence(name)
        seq.create_if_not_exists()
        assert [next(seq) for _ in range(10)] == list(range(1, 11))

    def test_iteration_returns_sequential_values(self):
        name = factory.make_name("seq", sep="")
        seq = Sequence(name)
        seq.create_if_not_exists()
        assert list(islice(seq, 10)) == list(range(1, 11))

    def test_set_value_sets_value(self):
        name = factory.make_name("seq", sep="")
        seq = Sequence(name)
        seq.create_if_not_exists()
        expected = random.randint(2000, 9999)
        seq.set_value(expected)
        assert next(seq) == expected
