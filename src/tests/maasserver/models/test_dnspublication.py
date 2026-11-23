# Copyright 2016-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for general DNS models."""

from datetime import datetime, timedelta
from random import randint

from django.db import connection
from django.utils import timezone
import pytest

from maasserver.models.dnspublication import DNSPublication, zone_serial
from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestZoneSerial:
    """Tests for the `maasserver_zone_serial_seq` sequence."""

    def test_parameters(self):
        assert zone_serial.maxvalue == 2**32 - 1
        assert zone_serial.minvalue == 1
        assert zone_serial.increment == 1
        assert zone_serial.cycle
        assert zone_serial.owner == "maasserver_dnspublication.serial"

    def test_parameters_in_database(self):
        query = "SELECT last_value, is_called FROM %s" % zone_serial.name
        with connection.cursor() as cursor:
            cursor.execute(query)
            last_value1, is_called1 = cursor.fetchone()
            next(zone_serial)
            cursor.execute(query)
            last_value2, is_called2 = cursor.fetchone()
            assert 1 == last_value2 - last_value1
            assert is_called1
            assert is_called2


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestDNSPublication:
    """Test the `DNSPublication` model."""

    def test_create_empty(self):
        pub = DNSPublication()
        pub.save()
        assert isinstance(pub.serial, int)
        assert isinstance(pub.created, datetime)
        assert pub.source == ""

    def test_create_with_values(self):
        serial = randint(1, 5000)
        created = timezone.now() - timedelta(minutes=1098)
        source = factory.make_name("source")
        pub = DNSPublication(serial=serial, created=created, source=source)
        pub.save()
        assert pub.serial == serial
        assert isinstance(pub.created, datetime)
        assert pub.created != created
        assert pub.source == source


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestDNSPublicationManager:
    """Test `DNSPublicationManager`."""

    @pytest.fixture(autouse=True)
    def _setup(self, maasdb):
        # These tests expect the DNSPublication table to be empty.
        DNSPublication.objects.all().delete()

    def test_get_most_recent_returns_record_with_highest_id(self):
        DNSPublication(serial=3).save()
        DNSPublication(serial=30).save()
        DNSPublication(serial=10).save()
        pub = DNSPublication.objects.get_most_recent()
        assert pub.serial == 10

    def test_get_most_recent_crashes_when_no_publications(self):
        # This is okay because we ensure (using a migration) that there is
        # never less than one publication in the table. If this crash happens
        # we have bigger problems. However, we do not currently use migrations
        # in tests, so it is important to have a deterministic outcome when
        # there are no publications.
        with pytest.raises(DNSPublication.DoesNotExist):
            DNSPublication.objects.get_most_recent()

    def test_collect_garbage_removes_all_but_most_recent_record(self):
        for serial in range(10):
            DNSPublication(serial=serial).save()
        assert DNSPublication.objects.all().count() == 10
        DNSPublication.objects.collect_garbage()
        assert DNSPublication.objects.all().count() == 1
        assert DNSPublication.objects.get_most_recent().serial == serial

    def test_collect_garbage_does_nothing_when_no_publications(self):
        assert not DNSPublication.objects.all().exists()
        DNSPublication.objects.collect_garbage()
        assert not DNSPublication.objects.all().exists()

    def test_collect_garbage_leaves_records_older_than_specified(self):
        publications = {
            timedelta(days=1): DNSPublication(source="1 day ago"),
            timedelta(minutes=1): DNSPublication(source="1 minute ago"),
            timedelta(seconds=0): DNSPublication(source="now"),
        }

        with connection.cursor() as cursor:
            cursor.execute("SELECT now()")
            [now] = cursor.fetchone()

        # Work from oldest to youngest so that the youngest gets the highest
        # primary key; the primary key is used to determine the most recent.
        for delta in sorted(publications, reverse=True):
            publication = publications[delta]
            publication.save()
            # Use SQL to set `created`; Django's field validation prevents it.
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE maasserver_dnspublication SET created = %s"
                    " WHERE id = %s",
                    [now - delta, publication.id],
                )

        def get_ages():
            pubs = DNSPublication.objects.all()
            return {now - pub.created for pub in pubs}

        deltas = set(publications)
        assert deltas == get_ages()

        one_second = timedelta(seconds=1)
        # Work from oldest to youngest again, collecting garbage each time.
        while len(deltas) > 1:
            delta = max(deltas)
            # Publications of exactly the specified age are not deleted.
            DNSPublication.objects.collect_garbage(now - delta)
            assert deltas == get_ages()
            # Publications of just a second over are deleted.
            DNSPublication.objects.collect_garbage(now - delta + one_second)
            assert deltas - {delta} == get_ages()
            # We're done with this one.
            deltas.discard(delta)

        # The most recent publication will never be deleted.
        DNSPublication.objects.collect_garbage()
        assert deltas == get_ages()
        assert len(deltas) == 1
