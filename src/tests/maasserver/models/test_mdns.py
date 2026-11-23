# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the mDNS model."""

import pytest

from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestMDNSModel:
    def test_accepts_invalid_hostname(self):
        mdns = factory.make_MDNS(hostname="Living room")
        # Expect no exception.
        assert "Living room" == mdns.hostname
