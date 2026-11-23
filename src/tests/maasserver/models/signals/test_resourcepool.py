# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the behaviour of resourcepool signals."""

from django.db import connection
import pytest

from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestPostSaveResourcePoolSignal:
    def test_save_creates_openfga_tuple(self):
        pool = factory.make_ResourcePool()

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT _user, relation FROM openfga.tuple WHERE object_type = 'pool' AND object_id = '%s'",
                [pool.id],
            )
            openfga_tuple = cursor.fetchone()

        assert "maas:0" == openfga_tuple[0]
        assert "parent" == openfga_tuple[1]


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestPostDeleteResourcePoolSignal:
    def test_delete_removes_openfga_tuple(self):
        pool = factory.make_ResourcePool()
        pool_id = pool.id

        pool.delete()

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT object_type, object_id, relation FROM openfga.tuple WHERE _user = 'pool:%s'",
                [pool_id],
            )
            openfga_tuple = cursor.fetchone()

        assert openfga_tuple is None
