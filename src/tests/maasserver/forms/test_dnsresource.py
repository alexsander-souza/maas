# Copyright 2016-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for DNSResource forms."""

from collections import Counter
import random
from unittest.mock import Mock

import pytest

from maasserver.forms.dnsresource import DNSResourceForm
from maasserver.testing.factory import factory
from maasserver.utils.orm import post_commit_hooks, reload_object


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestDNSResourceForm:
    def test_creates_dnsresource(self):
        name = factory.make_name("dnsresource")
        sip = factory.make_StaticIPAddress()
        domain = factory.make_Domain()
        request = Mock()
        request.user = factory.make_User()
        form = DNSResourceForm(
            {"name": name, "domain": domain.id, "ip_addresses": [sip.id]},
            request=request,
        )
        assert form.is_valid(), form.errors
        dnsresource = form.save()
        assert name == dnsresource.name
        assert domain.id == dnsresource.domain.id
        assert sip.id == dnsresource.ip_addresses.first().id

    def test_accepts_string_for_ip_addresses(self):
        name = factory.make_name("dnsresource")
        sip = factory.make_StaticIPAddress()
        domain = factory.make_Domain()
        form = DNSResourceForm(
            {"name": name, "domain": domain.id, "ip_addresses": str(sip.id)}
        )
        assert form.is_valid(), form.errors
        dnsresource = form.save()
        assert name == dnsresource.name
        assert domain.id == dnsresource.domain.id
        assert sip.id == dnsresource.ip_addresses.first().id

    def test_creates_staticipaddresses(self):
        name = factory.make_name("dnsresource")
        domain = factory.make_Domain()
        ips = [factory.make_ip_address() for _ in range(3)]
        request = Mock()
        request.user = factory.make_User()
        form = DNSResourceForm(
            {"name": name, "domain": domain.id, "ip_addresses": " ".join(ips)},
            request=request,
        )
        assert form.is_valid(), form.errors
        with post_commit_hooks:
            dnsresource = form.save()
        assert name == dnsresource.name
        assert domain.id == dnsresource.domain.id
        actual_ips = dnsresource.ip_addresses.all()
        actual = {str(ip.ip) for ip in actual_ips}
        assert Counter(set(ips)) == Counter(actual)
        actual_users = {ip.user_id for ip in actual_ips}
        assert {request.user.id} == actual_users

    def test_accepts_mix_of_id_and_ipaddress(self):
        name = factory.make_name("dnsresource")
        domain = factory.make_Domain()
        ips = [factory.make_StaticIPAddress() for _ in range(6)]
        in_vals = [
            str(ip.id) if factory.pick_bool() else str(ip.ip) for ip in ips
        ]
        form = DNSResourceForm(
            {
                "name": name,
                "domain": domain.id,
                "ip_addresses": " ".join(in_vals),
            }
        )
        assert form.is_valid(), form.errors
        dnsresource = form.save()
        assert name == dnsresource.name
        assert domain.id == dnsresource.domain.id
        actual = {ip.id for ip in dnsresource.ip_addresses.all()}
        assert Counter({ip.id for ip in ips}) == Counter(actual)

    def test_does_not_require_ip_addresses(self):
        name = factory.make_name("dnsresource")
        domain = factory.make_Domain()
        form = DNSResourceForm({"name": name, "domain": domain.id})
        assert form.is_valid(), form.errors
        dnsresource = form.save()
        assert name == dnsresource.name
        assert domain.id == dnsresource.domain.id

    def test_accepts_address_ttl(self):
        name = factory.make_name("dnsresource")
        domain = factory.make_Domain()
        ttl = random.randint(1, 1000)
        form = DNSResourceForm(
            {"name": name, "domain": domain.id, "address_ttl": ttl}
        )
        assert form.is_valid(), form.errors
        dnsresource = form.save()
        assert name == dnsresource.name
        assert domain.id == dnsresource.domain.id
        assert ttl == dnsresource.address_ttl

    def test_accepts_address_ttl_equals_none(self):
        name = factory.make_name("dnsresource")
        domain = factory.make_Domain()
        ttl = random.randint(1, 1000)
        form = DNSResourceForm(
            {"name": name, "domain": domain.id, "address_ttl": ttl}
        )
        assert form.is_valid(), form.errors
        dnsresource = form.save()
        form = DNSResourceForm(
            instance=dnsresource, data={"address_ttl": None}
        )
        assert form.is_valid(), form.errors
        dnsresource = form.save()
        assert name == dnsresource.name
        assert domain.id == dnsresource.domain.id
        assert dnsresource.address_ttl is None

    def test_doesnt_require_name_on_update(self):
        dnsresource = factory.make_DNSResource()
        form = DNSResourceForm(instance=dnsresource, data={})
        assert form.is_valid(), form.errors

    def test_updates_dnsresource(self):
        dnsresource = factory.make_DNSResource()
        new_name = factory.make_name("new")
        new_sip_ids = [factory.make_StaticIPAddress().id]
        new_ttl = random.randint(1, 1000)
        form = DNSResourceForm(
            instance=dnsresource,
            data={
                "name": new_name,
                "ip_addresses": new_sip_ids,
                "address_ttl": new_ttl,
            },
        )
        assert form.is_valid(), form.errors
        form.save()
        assert new_name == reload_object(dnsresource).name
        assert new_ttl == reload_object(dnsresource).address_ttl
        assert Counter(new_sip_ids) == Counter(
            [ip.id for ip in reload_object(dnsresource).ip_addresses.all()]
        )

    def test_update_allows_multiple_ips(self):
        dnsresource = factory.make_DNSResource()
        new_name = factory.make_name("new")
        new_sip_ids = [factory.make_StaticIPAddress().id for _ in range(3)]
        form = DNSResourceForm(
            instance=dnsresource,
            data={
                "name": new_name,
                "ip_addresses": " ".join(str(id) for id in new_sip_ids),
            },
        )
        assert form.is_valid(), form.errors
        form.save()
        assert new_name == reload_object(dnsresource).name
        assert Counter(new_sip_ids) == Counter(
            [ip.id for ip in reload_object(dnsresource).ip_addresses.all()]
        )

    def test_does_not_create_invalid_label(self):
        name = factory.make_name("under_score")
        domain = factory.make_Domain()
        ip = factory.make_ip_address()
        request = Mock()
        request.user = factory.make_User()
        form = DNSResourceForm(
            {
                "name": name,
                "domain": domain.id,
                "ip_addresses": ip,
            },
            request=request,
        )
        assert not form.is_valid()

    def test_create_atsign(self):
        name = "@"
        domain = factory.make_Domain()
        ip = factory.make_ip_address()
        request = Mock()
        request.user = factory.make_User()
        form = DNSResourceForm(
            {
                "name": name,
                "domain": domain.id,
                "ip_addresses": ip,
            },
            request=request,
        )
        assert form.is_valid(), form.errors
        with post_commit_hooks:
            dnsresource = form.save()
        assert name == dnsresource.name

    def test_create_wildcard(self):
        name = "*"
        domain = factory.make_Domain()
        ip = factory.make_ip_address()
        request = Mock()
        request.user = factory.make_User()
        form = DNSResourceForm(
            {
                "name": name,
                "domain": domain.id,
                "ip_addresses": ip,
            },
            request=request,
        )
        assert form.is_valid(), form.errors
        with post_commit_hooks:
            dnsresource = form.save()
        assert name == dnsresource.name
