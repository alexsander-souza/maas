# Copyright 2013-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for physical `Zone` API."""

import http.client
import json

from django.conf import settings
from django.urls import reverse
import pytest

from maasserver.models import Zone
from maasserver.testing.factory import factory
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
class TestZonesAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_handler_path(self):
        assert "/MAAS/api/2.0/zones/" == reverse("zones_handler")

    def test_new_creates_zone(self):
        self.user.is_superuser = True
        self.user.save()
        name = factory.make_name("name")
        description = factory.make_name("description")
        response = self.client.post(
            reverse("zones_handler"),
            {"name": name, "description": description},
        )
        assert http.client.OK == response.status_code, response.content
        zone = Zone.objects.get(name=name)
        assert name == zone.name
        assert description == zone.description

    def test_new_requires_admin(self):
        name = factory.make_name("name")
        description = factory.make_name("description")
        response = self.client.post(
            reverse("zones_handler"),
            {"name": name, "description": description},
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_list_returns_zone_list(self):
        [factory.make_Zone(sortable_name=True) for _ in range(3)]
        zones = Zone.objects.all()
        response = self.client.get(reverse("zones_handler"), {})
        assert http.client.OK == response.status_code, response.content
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert sorted(
            (
                zone.name,
                zone.description,
                reverse("zone_handler", args=[zone.name]),
            )
            for zone in zones
        ) == sorted(
            (
                zone.get("name"),
                zone.get("description"),
                zone.get("resource_uri"),
            )
            for zone in parsed_result
        )

    def test_list_returns_sorted_zone_list(self):
        [factory.make_Zone(sortable_name=True) for _ in range(10)]
        zones = Zone.objects.all()
        response = self.client.get(reverse("zones_handler"), {})
        assert http.client.OK == response.status_code, response.content
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        # Sorting is case-insensitive.
        assert sorted(
            (zone.name for zone in zones), key=lambda s: s.lower()
        ) == [zone.get("name") for zone in parsed_result]


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
class TestZonesOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_create_requires_can_edit_global_entities(self):
        self.openfga_client.can_edit_global_entities.return_value = True
        name = factory.make_name("name")
        description = factory.make_name("description")
        response = self.client.post(
            reverse("zones_handler"),
            {"name": name, "description": description},
        )
        assert http.client.OK == response.status_code, response.content
        self.openfga_client.can_edit_global_entities.assert_called_once_with(
            self.user
        )
