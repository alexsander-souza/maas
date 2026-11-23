# Copyright 2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the behaviour of dnsresource signals."""

import pytest

from maasserver.models import DNSPublication
from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestPostSaveDNSDataSignal:
    def test_save_dnsdata_creates_dnspublication(self):
        domain = factory.make_Domain("example.com", authoritative=True)
        dnsresource = factory.make_DNSResource(
            domain=domain, name="maas", address_ttl=300, ip_addresses=[]
        )
        factory.make_DNSData(
            dnsresource=dnsresource,
            rrtype="TXT",
            rrdata="U29ycnkgZm9yIHRoaXMh",
        )
        dnspublication = DNSPublication.objects.get_most_recent()
        assert "added TXT to resource maas on zone example.com" == (
            dnspublication.source
        )


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestPostDeleteSubnetSignal:
    def test_delete_dnsresource(self):
        domain = factory.make_Domain("example.com", authoritative=True)
        dnsresource = factory.make_DNSResource(
            domain=domain, name="maas", address_ttl=300
        )
        dnsdata = factory.make_DNSData(
            dnsresource=dnsresource,
            rrtype="TXT",
            rrdata="U29ycnkgZm9yIHRoaXMh",
        )
        dnsdata.delete()

        dnspublication = DNSPublication.objects.get_most_recent()
        assert "removed TXT from resource maas on zone example.com" == (
            dnspublication.source
        )


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestUpdateDNSDataSignal:
    def test_update_dnsdata_creates_dnspublication(self):
        domain = factory.make_Domain("example.com", authoritative=True)
        dnsresource = factory.make_DNSResource(
            domain=domain, name="maas", address_ttl=300
        )
        dnsdata = factory.make_DNSData(
            dnsresource=dnsresource,
            rrtype="TXT",
            rrdata="U29ycnkgZm9yIHRoaXMh",
        )
        dnsdata.rrdata = "a2l3aQ=="
        dnsdata.save()
        dnspublication = DNSPublication.objects.get_most_recent()

        assert "updated TXT in resource maas on zone example.com" == (
            dnspublication.source
        )
