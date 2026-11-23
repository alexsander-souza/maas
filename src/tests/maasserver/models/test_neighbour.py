# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the Neighbour model."""

import pytest

from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNeighbourModel:
    def test_mac_organization(self):
        neighbour = factory.make_Neighbour(mac_address="48:51:b7:00:00:00")
        assert neighbour.mac_organization == "Intel Corporate"
