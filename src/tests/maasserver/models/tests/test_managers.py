# Copyright 2012-2016 Canonical Ltd. This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from django.db import connection
from django.test.utils import CaptureQueriesContext
import pytest

from maasserver.tests.models import (
    BulkManagerParentTestModel,
    BulkManagerTestModel,
)


@pytest.mark.usefixtures("maasdb", "maas_region_test", "transactional_maasdb")
@pytest.mark.allow_transactions
class TestBulkManager:
    def test_manager_iterator_uses_cache(self):
        parents = set()
        for _ in range(3):
            parents.add(BulkManagerParentTestModel.objects.create())
        for _ in range(10):
            for parent in parents:
                BulkManagerTestModel.objects.create(parent=parent)
        parents = BulkManagerParentTestModel.objects.all().prefetch_related(
            "bulkmanagertestmodel_set"
        )
        # Only two queries are used to fetch all the objects:
        # One to fetch the parents, one to fetch the children (the query from
        # the prefetch_related statement).
        # Even if we call iterator() on the related objects, the cache is
        # used because BulkManagerTestModel has a manager based on BulkManager.
        with CaptureQueriesContext(connection) as queries:
            [
                list(parent.bulkmanagertestmodel_set.iterator())
                for parent in parents
            ]
        assert len(queries) == 2
