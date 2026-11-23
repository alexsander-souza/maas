# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from unittest import TestCase as UnittestTestCase

import pytest
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks

from maasserver.regiondservices.version_update_check import (
    RegionVersionUpdateCheckService,
)
from maasserver.testing.factory import factory
from maasserver.utils.threads import deferToDatabase
from maastesting.crochet import wait_for
from provisioningserver.rackdservices import version_update_check
from provisioningserver.utils.snap import (
    SnapChannel,
    SnapVersion,
    SnapVersionsInfo,
)
from provisioningserver.utils.testing import MAASIDFixture


@pytest.mark.allow_transactions
@pytest.mark.usefixtures(
    "maasdb", "transactional_maasdb", "maas_region_test", "factory"
)
class TestRegionVersionUpdateCheckService:
    @pytest.fixture(autouse=True)
    def _setup_test_helpers(self, mocker, request):
        self._mocker = mocker
        self._request = request
        self._assertions = UnittestTestCase()

    def __getattr__(self, name):
        if name.startswith("assert") or name == "fail":
            return getattr(self._assertions, name)
        raise AttributeError(name)

    def patch(self, obj, attribute=None, value=None):
        if attribute is None:
            return self._mocker.patch(obj)
        if value is None:
            return self._mocker.patch.object(obj, attribute)
        return self._mocker.patch.object(obj, attribute, value)

    def useFixture(self, fixture):
        fixture.setUp()
        self._request.addfinalizer(fixture.cleanUp)
        return fixture

    @wait_for()
    @inlineCallbacks
    def test_update_version(self):
        region = yield deferToDatabase(factory.make_RegionController)
        # Declare this region controller as the one running here.
        self.useFixture(MAASIDFixture(region.system_id))

        versions_info = SnapVersionsInfo(
            current=SnapVersion(
                revision="1234", version="3.0.0~alpha1-111-g.deadbeef"
            ),
            channel=SnapChannel(track="3.0"),
            update=SnapVersion(
                revision="5678", version="3.0.0~alpha2-222-g.cafecafe"
            ),
        )
        self.patch(
            version_update_check, "get_versions_info"
        ).return_value = versions_info

        service = RegionVersionUpdateCheckService(reactor)
        yield service.startService()
        yield service.stopService()

        info = yield deferToDatabase(getattr, region, "info")
        self.assertEqual(info.version, "3.0.0~alpha1-111-g.deadbeef")
        self.assertEqual(info.snap_revision, "1234")
        self.assertEqual(info.update_version, "3.0.0~alpha2-222-g.cafecafe")
        self.assertEqual(info.snap_update_revision, "5678")
        self.assertEqual(info.update_origin, "3.0/stable")
