# Copyright 2013-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for physical `Zone` API."""

import http.client
import json

from django.conf import settings
from django.urls import reverse
import pytest

from maasserver.models.defaultresource import DefaultResource
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


def get_zone_uri(zone):
    """Return a zone's URI on the API."""
    return reverse("zone_handler", args=[zone.name])


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
class TestZoneAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_handler_path(self):
        assert "/MAAS/api/2.0/zones/name/" == reverse(
            "zone_handler", args=["name"]
        )

    def test_POST_is_prohibited(self):
        self.user.is_superuser = True
        self.user.save()
        zone = factory.make_Zone()
        response = self.client.post(
            get_zone_uri(zone),
            {"name": zone.name, "description": zone.description},
        )
        assert http.client.METHOD_NOT_ALLOWED == response.status_code

    def test_GET_returns_zone(self):
        zone = factory.make_Zone()
        response = self.client.get(get_zone_uri(zone))
        assert http.client.OK == response.status_code
        returned_zone = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert (zone.name, zone.description) == (
            returned_zone["name"],
            returned_zone["description"],
        )

    def test_PUT_updates_zone(self):
        self.user.is_superuser = True
        self.user.save()
        zone = factory.make_Zone()
        new_description = factory.make_string()

        response = self.client.put(
            get_zone_uri(zone), {"description": new_description}
        )
        assert http.client.OK == response.status_code

        zone = reload_object(zone)
        assert new_description == zone.description

    def test_PUT_requires_admin(self):
        zone = factory.make_Zone()
        response = self.client.put(
            get_zone_uri(zone), {"description": factory.make_string()}
        )
        assert http.client.FORBIDDEN == response.status_code

    def test_PUT_updates_zone_name(self):
        self.user.is_superuser = True
        self.user.save()
        zone = factory.make_Zone()
        new_name = factory.make_name("zone-new")

        response = self.client.put(get_zone_uri(zone), {"name": new_name})
        assert http.client.OK == response.status_code

        zone = reload_object(zone)
        assert new_name == zone.name

    def test_PUT_rejects_change_of_default_zone_name(self):
        self.user.is_superuser = True
        self.user.save()
        zone = DefaultResource.objects.get_default_zone()
        new_name = factory.make_name("zone")
        response = self.client.put(get_zone_uri(zone), {"name": new_name})
        assert http.client.OK == response.status_code
        zone = reload_object(zone)
        assert new_name == zone.name

    def test_PUT_changing_name_maintains_foreign_keys(self):
        self.user.is_superuser = True
        self.user.save()
        zone = factory.make_Zone()
        node = factory.make_Node(zone=zone)

        response = self.client.put(
            get_zone_uri(zone), {"name": factory.make_name("new")}
        )
        assert http.client.OK == response.status_code

        node = reload_object(node)
        zone = reload_object(zone)
        assert zone == node.zone

    def test_DELETE_removes_zone(self):
        self.user.is_superuser = True
        self.user.save()
        zone = factory.make_Zone()
        response = self.client.delete(get_zone_uri(zone))
        assert http.client.NO_CONTENT == response.status_code
        assert reload_object(zone) is None

    def test_DELETE_rejects_deletion_of_default_zone(self):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.delete(
            get_zone_uri(DefaultResource.objects.get_default_zone())
        )
        assert http.client.BAD_REQUEST == response.status_code
        assert DefaultResource.objects.get_default_zone() is not None

    def test_DELETE_requires_admin(self):
        zone = factory.make_Zone()
        response = self.client.delete(get_zone_uri(zone))
        assert http.client.FORBIDDEN == response.status_code

    def test_DELETE_cannot_delete_default_zone(self):
        self.user.is_superuser = True
        self.user.save()
        zone = DefaultResource.objects.get_default_zone()

        response = self.client.delete(get_zone_uri(zone))

        assert (
            http.client.BAD_REQUEST.value,
            "This zone is the default zone, it cannot be deleted.",
        ) == (
            response.status_code,
            response.content.decode(settings.DEFAULT_CHARSET),
        )

    def test_DELETE_sets_foreign_keys_to_default(self):
        default_zone = DefaultResource.objects.get_default_zone()
        self.user.is_superuser = True
        self.user.save()
        zone = factory.make_Zone()
        node = factory.make_Node(zone=zone)

        response = self.client.delete(get_zone_uri(zone))
        assert http.client.NO_CONTENT == response.status_code

        node = reload_object(node)
        assert node is not None
        assert default_zone == node.zone

    def test_DELETE_is_idempotent(self):
        self.user.is_superuser = True
        self.user.save()
        zone = factory.make_Zone()
        response = self.client.delete(get_zone_uri(zone))
        assert http.client.NO_CONTENT == response.status_code

        response = self.client.delete(get_zone_uri(zone))
        assert http.client.NO_CONTENT == response.status_code


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
class TestZoneOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_update_requires_can_edit_global_entities(self):
        self.openfga_client.can_edit_global_entities.return_value = True
        zone = factory.make_Zone()
        new_name = factory.make_name("name")
        response = self.client.put(
            get_zone_uri(zone),
            {"name": new_name},
        )
        assert http.client.OK == response.status_code, response.content
        self.openfga_client.can_edit_global_entities.assert_called()

    def test_delete_requires_can_edit_global_entities(self):
        self.openfga_client.can_edit_global_entities.return_value = True
        zone = factory.make_Zone()
        response = self.client.delete(get_zone_uri(zone))
        assert http.client.NO_CONTENT == response.status_code, response.content
        self.openfga_client.can_edit_global_entities.assert_called()
