# Copyright 2016-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for DNSResourceRecord API."""

import http.client
import json
import random

from django.conf import settings
from django.urls import reverse
import pytest

from maasserver.models.dnsdata import DNSData
from maasserver.testing.factory import factory
from maasserver.utils.orm import post_commit_hooks, reload_object
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


def get_dnsresourcerecords_uri():
    """Return a DNSResourceRecord's URI on the API."""
    return reverse("dnsresourcerecords_handler", args=[])


def get_dnsresourcerecord_uri(dnsresourcerecord):
    """Return a DNSResourceRecord URI on the API."""
    return reverse("dnsresourcerecord_handler", args=[dnsresourcerecord.id])


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestDNSResourceRecordsAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_handler_path(self):
        assert (
            "/MAAS/api/2.0/dnsresourcerecords/" == get_dnsresourcerecords_uri()
        )

    def test_read(self):
        for _ in range(3):
            factory.make_DNSData()
        uri = get_dnsresourcerecords_uri()
        response = self.client.get(uri)

        assert http.client.OK == response.status_code, response.content
        expected_ids = [dnsdata.id for dnsdata in DNSData.objects.all()]
        result_ids = [
            dnsrr["id"]
            for dnsrr in json.loads(
                response.content.decode(settings.DEFAULT_CHARSET)
            )
        ]
        assert sorted(expected_ids) == sorted(result_ids)

    def test_read_with_domain(self):
        for _ in range(3):
            dnsdata = factory.make_DNSData()
        uri = get_dnsresourcerecords_uri()
        response = self.client.get(
            uri, {"domain": [dnsdata.dnsresource.domain.name]}
        )
        assert http.client.OK == response.status_code, response.content
        expected_ids = [dnsdata.id]
        result_ids = [
            data["id"]
            for data in json.loads(
                response.content.decode(settings.DEFAULT_CHARSET)
            )
        ]
        assert sorted(expected_ids) == sorted(result_ids)

    def test_read_with_name(self):
        for _ in range(3):
            dnsdata = factory.make_DNSData()
        uri = get_dnsresourcerecords_uri()
        response = self.client.get(uri, {"name": [dnsdata.dnsresource.name]})
        assert http.client.OK == response.status_code, response.content
        expected_ids = [dnsdata.id]
        result_ids = [
            data["id"]
            for data in json.loads(
                response.content.decode(settings.DEFAULT_CHARSET)
            )
        ]
        assert sorted(expected_ids) == sorted(result_ids)

    def test_read_with_type(self):
        for _ in range(3):
            dnsdata = factory.make_DNSData()
        rrtype = dnsdata.rrtype
        uri = get_dnsresourcerecords_uri()
        response = self.client.get(uri, {"rrtype": [rrtype]})
        assert http.client.OK == response.status_code, response.content
        expected_ids = [
            data.id for data in DNSData.objects.filter(rrtype=rrtype)
        ]
        result_ids = [
            data["id"]
            for data in json.loads(
                response.content.decode(settings.DEFAULT_CHARSET)
            )
        ]
        assert sorted(expected_ids) == sorted(result_ids)

    def test_create_by_name_domain_id(self):
        self.user.is_superuser = True
        self.user.save()
        dnsresource_name = factory.make_name("dnsresource")
        domain = factory.make_Domain()
        fqdn = f"{dnsresource_name}.{domain.name}"
        uri = get_dnsresourcerecords_uri()
        response = self.client.post(
            uri,
            {
                "name": dnsresource_name,
                "domain": domain.id,
                "rrtype": "TXT",
                "rrdata": "Sample Text.",
            },
        )
        assert http.client.OK == response.status_code, response.content
        payload = json.loads(response.content.decode(settings.DEFAULT_CHARSET))
        assert fqdn == payload["fqdn"]
        assert "TXT" == payload["rrtype"]
        assert "Sample Text." == payload["rrdata"]

    def test_create_by_name_domain_name(self):
        self.user.is_superuser = True
        self.user.save()
        dnsresource_name = factory.make_name("dnsresource")
        domain = factory.make_Domain()
        fqdn = f"{dnsresource_name}.{domain.name}"
        uri = get_dnsresourcerecords_uri()
        response = self.client.post(
            uri,
            {
                "name": dnsresource_name,
                "domain": domain.name,
                "rrtype": "TXT",
                "rrdata": "Sample Text.",
            },
        )
        assert http.client.OK == response.status_code, response.content
        payload = json.loads(response.content.decode(settings.DEFAULT_CHARSET))
        assert fqdn == payload["fqdn"]
        assert "TXT" == payload["rrtype"]
        assert "Sample Text." == payload["rrdata"]

    def test_create_by_fqdn(self):
        self.user.is_superuser = True
        self.user.save()
        dnsresource_name = factory.make_name("dnsresource")
        domain = factory.make_Domain()
        fqdn = f"{dnsresource_name}.{domain.name}"
        uri = get_dnsresourcerecords_uri()
        response = self.client.post(
            uri, {"fqdn": fqdn, "rrtype": "TXT", "rrdata": "Sample Text."}
        )
        assert http.client.OK == response.status_code, response.content
        payload = json.loads(response.content.decode(settings.DEFAULT_CHARSET))
        assert fqdn == payload["fqdn"]
        assert "TXT" == payload["rrtype"]
        assert "Sample Text." == payload["rrdata"]

    def test_create_resource_exists(self):
        self.user.is_superuser = True
        self.user.save()
        dnsresource_name = factory.make_name("dnsresource")
        domain = factory.make_Domain()
        # create a resource with the same details
        factory.make_DNSResource(domain=domain, name=dnsresource_name)
        uri = get_dnsresourcerecords_uri()
        response = self.client.post(
            uri,
            {
                "name": dnsresource_name,
                "domain": domain.name,
                "rrtype": "TXT",
                "rrdata": "Sample Text.",
            },
        )
        payload = json.loads(response.content.decode(settings.DEFAULT_CHARSET))
        assert payload["fqdn"] == f"{dnsresource_name}.{domain.name}"

    def test_create_fails_with_no_name(self):
        self.user.is_superuser = True
        self.user.save()
        domain = factory.make_Domain()
        uri = get_dnsresourcerecords_uri()
        response = self.client.post(
            uri,
            {"domain": domain.name, "rrtype": "TXT", "rrdata": "Sample Text."},
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )

    def test_create_fails_with_no_domain(self):
        self.user.is_superuser = True
        self.user.save()
        dnsresource_name = factory.make_name("dnsresource")
        uri = get_dnsresourcerecords_uri()
        response = self.client.post(
            uri,
            {
                "name": dnsresource_name,
                "rrtype": "TXT",
                "rrdata": "Sample Text.",
            },
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )

    def test_create_admin_only(self):
        dnsresource_name = factory.make_name("dnsresource")
        uri = get_dnsresourcerecords_uri()
        response = self.client.post(
            uri,
            {
                "name": dnsresource_name,
                "rrtype": "TXT",
                "rrdata": "Sample Text.",
            },
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_create_requires_name(self):
        self.user.is_superuser = True
        self.user.save()
        uri = get_dnsresourcerecords_uri()
        response = self.client.post(uri, {})
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestDNSResourceRecordAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_handler_path(self):
        dnsdata = factory.make_DNSData()
        assert (
            "/MAAS/api/2.0/dnsresourcerecords/%s/" % dnsdata.id
            == get_dnsresourcerecord_uri(dnsdata)
        )

    def test_read(self):
        dnsdata = factory.make_DNSData()
        for _ in range(3):
            factory.make_DNSData()
        uri = get_dnsresourcerecord_uri(dnsdata)
        response = self.client.get(uri)
        assert http.client.OK == response.status_code, response.content
        parsed_dnsresource = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert parsed_dnsresource.get("id") == dnsdata.id
        assert parsed_dnsresource.get("fqdn") == dnsdata.fqdn
        assert parsed_dnsresource.get("rrtype") == dnsdata.rrtype
        assert parsed_dnsresource.get("rrdata") == dnsdata.rrdata

    def test_read_404_when_bad_id(self):
        uri = reverse(
            "dnsresourcerecord_handler", args=[random.randint(100, 1000)]
        )
        response = self.client.get(uri)
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_update(self):
        self.user.is_superuser = True
        self.user.save()
        dnsdata = factory.make_DNSData(rrtype="TXT", rrdata="1")
        new_data = factory.make_name("data")
        uri = get_dnsresourcerecord_uri(dnsdata)
        response = self.client.put(uri, {"rrdata": new_data})
        assert http.client.OK == response.status_code, response.content
        payload = json.loads(response.content.decode(settings.DEFAULT_CHARSET))
        assert payload["rrdata"] == new_data

    def test_update_admin_only(self):
        dnsdata = factory.make_DNSData()
        new_ttl = random.randint(10, 100)
        uri = get_dnsresourcerecord_uri(dnsdata)
        response = self.client.put(uri, {"ttl": new_ttl})
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_delete_deletes_dnsresource_record(self):
        self.user.is_superuser = True
        self.user.save()
        dnsdata = factory.make_DNSData()
        uri = get_dnsresourcerecord_uri(dnsdata)
        response = self.client.delete(uri)
        assert http.client.NO_CONTENT == response.status_code, response.content
        assert reload_object(dnsdata) is None

    def test_delete_deletes_dnsresource_if_no_data(self):
        self.user.is_superuser = True
        self.user.save()
        dnsdata = factory.make_DNSData()
        dnsrr = dnsdata.dnsresource
        uri = get_dnsresourcerecord_uri(dnsdata)
        response = self.client.delete(uri)
        assert http.client.NO_CONTENT == response.status_code, response.content
        assert reload_object(dnsdata) is None
        assert reload_object(dnsrr) is None

    def test_delete_does_not_delete_dnsresource_if_data_present(self):
        self.user.is_superuser = True
        self.user.save()
        dnsdata = factory.make_DNSData()
        dnsrr = dnsdata.dnsresource
        while dnsdata.rrtype == "CNAME":
            with post_commit_hooks:
                dnsdata.delete()
            dnsdata = factory.make_DNSData(dnsresource=dnsrr)
        # Now create a second DNSData record for this DNSRR.
        factory.make_DNSData(rrtype=dnsdata.rrtype, dnsresource=dnsrr)
        uri = get_dnsresourcerecord_uri(dnsdata)
        response = self.client.delete(uri)
        assert http.client.NO_CONTENT == response.status_code, response.content
        assert reload_object(dnsdata) is None
        assert reload_object(dnsrr) == dnsrr

    def test_delete_403_when_not_admin(self):
        dnsdata = factory.make_DNSData()
        uri = get_dnsresourcerecord_uri(dnsdata)
        response = self.client.delete(uri)
        assert http.client.FORBIDDEN == response.status_code, response.content
        assert reload_object(dnsdata) is not None

    def test_delete_404_when_invalid_id(self):
        self.user.is_superuser = True
        self.user.save()
        uri = reverse(
            "dnsresourcerecord_handler", args=[random.randint(100, 1000)]
        )
        response = self.client.delete(uri)
        assert http.client.NOT_FOUND == response.status_code, response.content


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestDNSResourceRecordAPIOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_create_requires_can_edit_global_entities(self):
        self.openfga_client.can_edit_global_entities.return_value = True
        dnsresource_name = factory.make_name("dnsresource")
        domain = factory.make_Domain()
        fqdn = f"{dnsresource_name}.{domain.name}"
        uri = get_dnsresourcerecords_uri()
        response = self.client.post(
            uri, {"fqdn": fqdn, "rrtype": "TXT", "rrdata": "Sample Text."}
        )
        assert http.client.OK == response.status_code, response.content
        self.openfga_client.can_edit_global_entities.assert_called_once_with(
            self.user
        )
