# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for IPRange API."""

import http.client
import json
import random
from urllib import parse

from django.conf import settings
from django.urls import reverse
import pytest

from maasserver.models.iprange import IPRange
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object


def get_ipranges_uri():
    """Return a Space's URI on the API."""
    return reverse("ipranges_handler", args=[])


def get_iprange_uri(iprange):
    """Return a Space URI on the API."""
    return reverse("iprange_handler", args=[iprange.id])


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("maas_user", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestIPRangesAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request):
        self.user = request.getfixturevalue(api_identity)
        self.client = request.getfixturevalue("api_client")

    def test_handler_path(self):
        assert "/MAAS/api/2.0/ipranges/" == get_ipranges_uri()

    def test_read(self):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        factory.make_IPRange(subnet, "10.0.0.2", "10.0.0.10")
        factory.make_IPRange(subnet, "10.0.0.11", "10.0.0.20")
        factory.make_IPRange(subnet, "10.0.0.21", "10.0.0.30")
        response = self.client.get(get_ipranges_uri())

        assert http.client.OK == response.status_code, response.content
        expected_ids = [iprange.id for iprange in IPRange.objects.all()]
        result_ids = [
            iprange["id"]
            for iprange in json.loads(
                response.content.decode(settings.DEFAULT_CHARSET)
            )
        ]
        assert sorted(expected_ids) == sorted(result_ids)

    def test_create_dynamic(self, admin_api_client):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        response = admin_api_client.post(
            get_ipranges_uri(),
            {
                "type": "dynamic",
                "start_ip": "10.0.0.10",
                "end_ip": "10.0.0.20",
                "subnet": "%d" % subnet.id,
            },
        )
        assert http.client.OK == response.status_code, response.content
        data = json.loads(response.content.decode(settings.DEFAULT_CHARSET))
        assert "10.0.0.10" == data["start_ip"]
        assert "10.0.0.20" == data["end_ip"]
        assert subnet.id == data["subnet"]["id"]

    def test_create_dynamic_encoded(self, admin_api_client):
        """
        There is a quirk in Django where the resulting handler will get a
        mutable dictionary in some instances (with just a json body) and an
        immutable dictionary in others (In the case for form encoded body).

        Specifying a content type of x-www-form-urlencoded should cause
        Django to produce an immutable dictionary.

        :return:
        """
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        response = admin_api_client.post(
            get_ipranges_uri(),
            parse.urlencode(
                {
                    "type": "dynamic",
                    "start_ip": "10.0.0.10",
                    "end_ip": "10.0.0.20",
                    "subnet": "%d" % subnet.id,
                }
            ),
            "application/x-www-form-urlencoded",
        )
        assert http.client.OK == response.status_code, response.content
        data = json.loads(response.content.decode(settings.DEFAULT_CHARSET))
        assert "10.0.0.10" == data["start_ip"]
        assert "10.0.0.20" == data["end_ip"]
        assert subnet.id == data["subnet"]["id"]

    def test_create_dynamic_requires_admin(self):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        response = self.client.post(
            get_ipranges_uri(),
            {
                "type": "dynamic",
                "start_ip": "10.0.0.10",
                "end_ip": "10.0.0.20",
                "subnet": "%d" % subnet.id,
            },
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_create_does_not_require_subnet(self):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        response = self.client.post(
            get_ipranges_uri(),
            {
                "type": "reserved",
                "start_ip": "10.0.0.10",
                "end_ip": "10.0.0.20",
            },
        )
        assert http.client.OK == response.status_code, response.content
        data = json.loads(response.content.decode(settings.DEFAULT_CHARSET))
        assert "10.0.0.10" == data["start_ip"]
        assert "10.0.0.20" == data["end_ip"]
        assert subnet.id == data["subnet"]["id"]

    def test_create_requires_type_and_reports_simple_error_if_missing(self):
        factory.make_Subnet(cidr="10.0.0.0/24")
        response = self.client.post(
            get_ipranges_uri(),
            {"start_ip": "10.0.0.10", "end_ip": "10.0.0.20"},
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )
        assert b'{"type": ["This field is required."]}' == response.content

    def test_create_sets_user_to_authenticated_user(self):
        factory.make_Subnet(cidr="10.0.0.0/24")
        response = self.client.post(
            get_ipranges_uri(),
            {
                "type": "reserved",
                "start_ip": "10.0.0.10",
                "end_ip": "10.0.0.20",
            },
        )
        assert http.client.OK == response.status_code, response.content
        data = json.loads(response.content.decode(settings.DEFAULT_CHARSET))
        assert self.user.username == data["user"]["username"]


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("maas_user", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestIPRangeAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request):
        self.user = request.getfixturevalue(api_identity)
        self.client = request.getfixturevalue("api_client")

    def test_handler_path(self):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        iprange = factory.make_IPRange(subnet, "10.0.0.2", "10.0.0.10")
        assert "/MAAS/api/2.0/ipranges/%s/" % iprange.id == get_iprange_uri(
            iprange
        )

    def test_read(self):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        iprange = factory.make_IPRange(subnet, "10.0.0.2", "10.0.0.10")
        factory.make_IPRange(subnet, "10.0.0.11", "10.0.0.20")
        factory.make_IPRange(subnet, "10.0.0.21", "10.0.0.30")
        response = self.client.get(get_iprange_uri(iprange))
        assert http.client.OK == response.status_code, response.content
        parsed_ipranges = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert iprange.id == parsed_ipranges.get("id")
        assert iprange.start_ip == parsed_ipranges.get("start_ip")
        assert iprange.end_ip == parsed_ipranges.get("end_ip")
        assert iprange.comment == parsed_ipranges.get("comment")
        assert iprange.type == parsed_ipranges.get("type")
        assert iprange.user == parsed_ipranges.get("user")

    def test_read_404_when_bad_id(self):
        uri = reverse("iprange_handler", args=[random.randint(10000, 20000)])
        response = self.client.get(uri)
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_update(self):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        iprange = factory.make_IPRange(
            subnet, "10.0.0.2", "10.0.0.10", user=self.user
        )
        comment = factory.make_name("comment")
        response = self.client.put(
            get_iprange_uri(iprange), {"comment": comment}
        )
        assert http.client.OK == response.status_code, response.content
        assert (
            comment
            == json.loads(response.content.decode(settings.DEFAULT_CHARSET))[
                "comment"
            ]
        )
        assert comment == reload_object(iprange).comment

    def test_update_403_when_not_user(self):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        iprange = factory.make_IPRange(
            subnet, "10.0.0.2", "10.0.0.10", user=factory.make_User()
        )
        response = self.client.put(get_iprange_uri(iprange), {})
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_update_404_when_invalid_id(self):
        uri = reverse("iprange_handler", args=[random.randint(100, 1000)])
        response = self.client.put(uri, {})
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_delete_deletes_iprange(self):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        iprange = factory.make_IPRange(
            subnet, "10.0.0.2", "10.0.0.10", user=self.user
        )
        response = self.client.delete(get_iprange_uri(iprange))
        assert http.client.NO_CONTENT == response.status_code, response.content
        assert reload_object(iprange) is None

    def test_delete_403_when_not_user(self):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        iprange = factory.make_IPRange(
            subnet, "10.0.0.2", "10.0.0.10", user=factory.make_User()
        )
        response = self.client.delete(get_iprange_uri(iprange))
        assert http.client.FORBIDDEN == response.status_code, response.content
        assert reload_object(iprange) is not None

    def test_delete_404_when_invalid_id(self):
        uri = reverse("iprange_handler", args=[random.randint(100, 1000)])
        response = self.client.delete(uri)
        assert http.client.NOT_FOUND == response.status_code, response.content
