# Copyright 2016-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for DNSData forms."""

import random

import pytest

from maasserver.forms.dnsdata import DNSDataForm
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestDNSDataForm:
    def test_creates_dnsdata(self):
        name = factory.make_name("dnsdata")
        (rrtype, rrdata) = factory.pick_rrset()
        dnsrr = factory.make_DNSResource(no_ip_addresses=True)
        form = DNSDataForm(
            {
                "name": name,
                "dnsresource": dnsrr.id,
                "rrtype": rrtype,
                "rrdata": rrdata,
            }
        )
        assert form.is_valid(), form.errors
        dnsdata = form.save()
        assert dnsrr.id == dnsdata.dnsresource.id
        assert rrtype == dnsdata.rrtype
        assert rrdata == dnsdata.rrdata

    def test_accepts_ttl(self):
        name = factory.make_name("dnsdata")
        (rrtype, rrdata) = factory.pick_rrset()
        dnsrr = factory.make_DNSResource(no_ip_addresses=True)
        ttl = random.randint(1, 10000)
        form = DNSDataForm(
            {
                "name": name,
                "dnsresource": dnsrr.id,
                "ttl": ttl,
                "rrtype": rrtype,
                "rrdata": rrdata,
            }
        )
        assert form.is_valid(), form.errors
        dnsdata = form.save()
        assert dnsrr.id == dnsdata.dnsresource.id
        assert rrtype == dnsdata.rrtype
        assert rrdata == dnsdata.rrdata
        assert ttl == dnsdata.ttl

    def test_accepts_ttl_equal_none(self):
        name = factory.make_name("dnsdata")
        (rrtype, rrdata) = factory.pick_rrset()
        dnsrr = factory.make_DNSResource(no_ip_addresses=True)
        ttl = random.randint(1, 10000)
        form = DNSDataForm(
            {
                "name": name,
                "dnsresource": dnsrr.id,
                "ttl": ttl,
                "rrtype": rrtype,
                "rrdata": rrdata,
            }
        )
        assert form.is_valid(), form.errors
        dnsdata = form.save()
        form = DNSDataForm(instance=dnsdata, data={"ttl": None})
        assert form.is_valid(), form.errors
        dnsdata = form.save()
        assert dnsrr.id == dnsdata.dnsresource.id
        assert rrtype == dnsdata.rrtype
        assert rrdata == dnsdata.rrdata
        assert dnsdata.ttl is None

    def test_doesnt_require_name_on_update(self):
        dnsdata = factory.make_DNSData()
        form = DNSDataForm(instance=dnsdata, data={})
        assert form.is_valid(), form.errors

    def test_updates_dnsdata(self):
        dnsdata = factory.make_DNSData()
        (rrtype, rrdata) = factory.pick_rrset()
        new_ttl = random.randint(1, 1000)
        form = DNSDataForm(
            instance=dnsdata,
            data={"rrtype": rrtype, "rrdata": rrdata, "ttl": new_ttl},
        )
        assert form.is_valid(), form.errors
        form.save()
        dnsdata = reload_object(dnsdata)
        assert rrtype == dnsdata.rrtype
        assert rrdata == dnsdata.rrdata
        assert new_ttl == dnsdata.ttl
