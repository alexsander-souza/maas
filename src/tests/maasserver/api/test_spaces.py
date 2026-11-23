# Copyright 2015-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for Space API."""

import http.client
import random

from django.urls import reverse
import pytest

from maasserver.models import VLAN
from maasserver.models.space import Space
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


def get_spaces_uri():
    """Return a Space's URI on the API."""
    return reverse("spaces_handler", args=[])


def get_space_uri(space):
    """Return a Space URI on the API."""
    return reverse("space_handler", args=[space.id])


def get_undefined_space_uri():
    """Return a Space URI on the API."""
    return reverse("space_handler", args=["undefined"])


def fill_empty_spaces(space=None):
    if space is None:
        space = Space.objects.first()
    for vlan in VLAN.objects.all():
        if vlan.space is None:
            vlan.space = space
            vlan.save()


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestSpacesAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_handler_path(self):
        assert "/MAAS/api/2.0/spaces/" == get_spaces_uri()

    def test_read(self):
        for _ in range(3):
            factory.make_Space()
        uri = get_spaces_uri()
        fill_empty_spaces()
        response = self.client.get(uri)

        assert http.client.OK == response.status_code, response.content
        expected_ids = [space.id for space in Space.objects.all()]
        result_ids = [space["id"] for space in response.json()]
        assert sorted(expected_ids) == sorted(result_ids)

    def test_read_undefined_space(self):
        factory.make_VLAN(space=None)
        uri = get_spaces_uri()
        response = self.client.get(uri)

        assert http.client.OK == response.status_code, response.content
        assert [-1] == [space["id"] for space in response.json()]

    def test_read_with_no_undefined_space(self):
        factory.make_VLAN()
        space = factory.make_Space()
        uri = get_spaces_uri()
        fill_empty_spaces(space)
        response = self.client.get(uri)

        assert http.client.OK == response.status_code, response.content
        # Does not include the undefined space.
        expected_ids = [space.id]
        result_ids = [space["id"] for space in response.json()]
        assert sorted(expected_ids) == sorted(result_ids)

    def test_create(self):
        self.user.is_superuser = True
        self.user.save()
        space_name = factory.make_name("space")
        uri = get_spaces_uri()
        fill_empty_spaces()
        response = self.client.post(uri, {"name": space_name})
        assert http.client.OK == response.status_code, response.content
        assert space_name == response.json()["name"]

    def test_create_admin_only(self):
        space_name = factory.make_name("space")
        uri = get_spaces_uri()
        response = self.client.post(uri, {"name": space_name})
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_create_does_not_require_name(self):
        self.user.is_superuser = True
        self.user.save()
        uri = get_spaces_uri()
        response = self.client.post(uri, {})
        assert http.client.OK == response.status_code, response.content
        data = response.json()
        assert "space-%d" % data["id"] == data["name"]


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestSpaceAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_handler_path(self):
        space = factory.make_Space()
        assert "/MAAS/api/2.0/spaces/%s/" % space.id == get_space_uri(space)

    def test_read(self):
        name = factory.make_name("name")
        description = factory.make_name("description")
        space = factory.make_Space(name=name, description=description)
        subnet_ids = [factory.make_Subnet(space=space).id for _ in range(3)]
        uri = get_space_uri(space)
        response = self.client.get(uri)

        assert http.client.OK == response.status_code, response.content
        parsed_space = response.json()
        assert space.id == parsed_space["id"]
        assert space.get_name() == parsed_space["name"]
        assert space.description == parsed_space["description"]
        parsed_subnets = [subnet["id"] for subnet in parsed_space["subnets"]]
        assert sorted(subnet_ids) == sorted(parsed_subnets)

    def test_read_undefined(self):
        for _ in range(3):
            factory.make_VLAN(space=None).id  # noqa: B018
        vlan_ids = VLAN.objects.all().values_list("id", flat=True)
        uri = get_undefined_space_uri()
        response = self.client.get(uri)

        assert http.client.OK == response.status_code, response.content
        parsed_space = response.json()
        assert -1 == parsed_space.get("id")
        assert Space.UNDEFINED == parsed_space.get("name")
        parsed_vlans = [vlan["id"] for vlan in parsed_space["vlans"]]
        assert sorted(vlan_ids) == sorted(parsed_vlans)

    def test_includes_vlan_objects(self):
        space = factory.make_Space()
        vlan = factory.make_VLAN(space=space)
        uri = get_space_uri(space)
        response = self.client.get(uri)
        assert http.client.OK == response.status_code, response.content
        parsed_vlan = response.json()["vlans"][0]
        assert vlan.id == parsed_vlan.get("id")
        assert vlan.vid == parsed_vlan.get("vid")
        assert vlan.fabric.id == parsed_vlan.get("fabric_id")

    def test_includes_legacy_subnet_objects(self):
        space = factory.make_Space()
        subnet = factory.make_Subnet(space=space)
        uri = get_space_uri(space)
        response = self.client.get(uri)
        assert http.client.OK == response.status_code, response.content
        parsed_subnet = response.json()["subnets"][0]
        assert subnet.id == parsed_subnet.get("id")
        assert str(subnet.cidr) == parsed_subnet.get("cidr")
        assert subnet.vlan.id == parsed_subnet["vlan"].get("id")
        assert subnet.vlan.vid == parsed_subnet["vlan"].get("vid")
        assert subnet.vlan.fabric_id == parsed_subnet["vlan"].get("fabric_id")

    def test_read_404_when_bad_id(self):
        uri = reverse("space_handler", args=[random.randint(100, 1000)])
        response = self.client.get(uri)
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_update(self):
        self.user.is_superuser = True
        self.user.save()
        space = factory.make_Space()
        new_name = factory.make_name("space")
        uri = get_space_uri(space)
        response = self.client.put(uri, {"name": new_name})
        assert http.client.OK == response.status_code, response.content
        assert new_name == response.json()["name"]
        assert new_name == reload_object(space).name

    def test_update_undefined_space_not_allowed(self):
        self.user.is_superuser = True
        self.user.save()
        factory.make_VLAN(space=None)
        uri = get_undefined_space_uri()
        response = self.client.put(uri, {"name": "defined"})
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )

    def test_update_admin_only(self):
        space = factory.make_Space()
        new_name = factory.make_name("space")
        uri = get_space_uri(space)
        response = self.client.put(uri, {"name": new_name})
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_delete_deletes_space(self):
        self.user.is_superuser = True
        self.user.save()
        space = factory.make_Space()
        uri = get_space_uri(space)
        response = self.client.delete(uri)
        assert http.client.NO_CONTENT == response.status_code, response.content
        assert reload_object(space) is None

    def test_delete_undefined_vlan_not_allowed(self):
        self.user.is_superuser = True
        self.user.save()
        factory.make_VLAN(space=None)
        uri = get_undefined_space_uri()
        response = self.client.delete(uri)
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )

    def test_delete_404_when_invalid_id(self):
        self.user.is_superuser = True
        self.user.save()
        uri = reverse("space_handler", args=[random.randint(100, 1000)])
        response = self.client.delete(uri)
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_delete_403_when_not_admin(self):
        space = factory.make_Space()
        uri = get_space_uri(space)
        response = self.client.delete(uri)
        assert http.client.FORBIDDEN == response.status_code, response.content
        assert reload_object(space) is not None


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestSpacesOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_create_requires_can_edit_global_entities(self):
        self.openfga_client.can_edit_global_entities.return_value = True
        space_name = factory.make_name("space")
        uri = get_spaces_uri()
        response = self.client.post(uri, {"name": space_name})
        assert http.client.OK == response.status_code, response.content
        self.openfga_client.can_edit_global_entities.assert_called_once_with(
            self.user
        )
