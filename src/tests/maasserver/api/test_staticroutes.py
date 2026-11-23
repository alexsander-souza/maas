# Copyright 2016-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for static route API."""

from collections import Counter
import http.client
import random

from django.urls import reverse
import pytest

from maasserver.testing.factory import factory
from maasserver.utils.converters import json_load_bytes
from maasserver.utils.orm import reload_object
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


def get_staticroutes_uri():
    """Return a static route's URI on the API."""
    return reverse("staticroutes_handler", args=[])


def get_staticroute_uri(route):
    """Return a static route URI on the API."""
    return reverse("staticroute_handler", args=[route.id])


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
class TestStaticRoutesAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_handler_path(self):
        assert "/MAAS/api/2.0/static-routes/" == get_staticroutes_uri()

    def test_read(self):
        routes = [factory.make_StaticRoute().id for _ in range(3)]
        uri = get_staticroutes_uri()
        response = self.client.get(uri)

        assert http.client.OK == response.status_code, response.content
        result_ids = [
            route["id"] for route in json_load_bytes(response.content)
        ]
        assert Counter(routes) == Counter(result_ids)

    def test_create(self):
        self.user.is_superuser = True
        self.user.save()
        source = factory.make_Subnet()
        destination = factory.make_Subnet(
            version=source.get_ipnetwork().version
        )
        gateway_ip = factory.pick_ip_in_Subnet(source)
        uri = get_staticroutes_uri()
        response = self.client.post(
            uri,
            {
                "source": source.id,
                "destination": destination.id,
                "gateway_ip": gateway_ip,
            },
        )
        assert http.client.OK == response.status_code, response.content
        assert gateway_ip == json_load_bytes(response.content)["gateway_ip"]

    def test_create_admin_only(self):
        source = factory.make_Subnet()
        destination = factory.make_Subnet(
            version=source.get_ipnetwork().version
        )
        gateway_ip = factory.pick_ip_in_Subnet(source)
        uri = get_staticroutes_uri()
        response = self.client.post(
            uri,
            {
                "source": source.id,
                "destination": destination.id,
                "gateway_ip": gateway_ip,
            },
        )
        assert http.client.FORBIDDEN == response.status_code, response.content


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
class TestStaticRouteAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_handler_path(self):
        route = factory.make_StaticRoute()
        assert (
            "/MAAS/api/2.0/static-routes/%s/" % route.id
            == get_staticroute_uri(route)
        )

    def test_read(self):
        route = factory.make_StaticRoute()
        uri = get_staticroute_uri(route)
        response = self.client.get(uri)

        assert http.client.OK == response.status_code, response.content
        parsed_route = json_load_bytes(response.content)
        assert parsed_route.get("id") == route.id
        assert parsed_route.get("source", {}).get("cidr") == route.source.cidr
        assert (
            parsed_route.get("destination", {}).get("cidr")
            == route.destination.cidr
        )
        assert parsed_route.get("gateway_ip") == route.gateway_ip
        assert parsed_route.get("metric") == route.metric

    def test_read_404_when_bad_id(self):
        uri = reverse("staticroute_handler", args=[random.randint(100, 1000)])
        response = self.client.get(uri)
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_update(self):
        self.user.is_superuser = True
        self.user.save()
        route = factory.make_StaticRoute()
        new_metric = random.randint(0, 100)
        uri = get_staticroute_uri(route)
        response = self.client.put(uri, {"metric": new_metric})
        assert http.client.OK == response.status_code, response.content
        assert new_metric == json_load_bytes(response.content)["metric"]
        assert new_metric == reload_object(route).metric

    def test_update_admin_only(self):
        route = factory.make_StaticRoute()
        new_metric = random.randint(0, 100)
        uri = get_staticroute_uri(route)
        response = self.client.put(uri, {"metric": new_metric})
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_delete_deletes_fabric(self):
        self.user.is_superuser = True
        self.user.save()
        route = factory.make_StaticRoute()
        uri = get_staticroute_uri(route)
        response = self.client.delete(uri)
        assert http.client.NO_CONTENT == response.status_code, response.content
        assert reload_object(route) is None

    def test_delete_403_when_not_admin(self):
        route = factory.make_StaticRoute()
        uri = get_staticroute_uri(route)
        response = self.client.delete(uri)
        assert http.client.FORBIDDEN == response.status_code, response.content
        assert reload_object(route) is not None

    def test_delete_404_when_invalid_id(self):
        self.user.is_superuser = True
        self.user.save()
        uri = reverse("staticroute_handler", args=[random.randint(100, 1000)])
        response = self.client.delete(uri)
        assert http.client.NOT_FOUND == response.status_code, response.content


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
class TestStaticRoutesOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_create_requires_can_edit_global_entities(self):
        self.openfga_client.can_edit_global_entities.return_value = True
        source = factory.make_Subnet()
        destination = factory.make_Subnet(
            version=source.get_ipnetwork().version
        )
        gateway_ip = factory.pick_ip_in_Subnet(source)
        uri = get_staticroutes_uri()
        response = self.client.post(
            uri,
            {
                "source": source.id,
                "destination": destination.id,
                "gateway_ip": gateway_ip,
            },
        )
        assert http.client.OK == response.status_code, response.content
        self.openfga_client.can_edit_global_entities.assert_called_once_with(
            self.user
        )
