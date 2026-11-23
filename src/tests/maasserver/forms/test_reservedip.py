# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
import pytest

from maasserver.enum import IPRANGE_TYPE
from maasserver.forms.reservedip import ReservedIPForm
from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestReservedIPForm:
    def test_empty_form_fails_validation(self):
        form = ReservedIPForm({})
        assert not form.is_valid()

    def test_form_requires_ip_and_mac(self):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        data = {
            "subnet": subnet.id,
            "comment": factory.make_name("comment"),
        }

        form = ReservedIPForm(data=data)

        assert not form.is_valid()
        assert "This field is required." in form.errors["ip"]
        assert "This field cannot be blank." in form.errors["mac_address"]

    def test_subnet_is_optional(self):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        data = {
            "ip": "10.0.0.15",
            "mac_address": factory.make_mac_address(),
            "comment": factory.make_name("comment"),
        }

        form = ReservedIPForm(data=data)

        assert form.is_valid()
        reserved_ip = form.save()
        assert reserved_ip.subnet == subnet

    def test_cant_reserve_broadcast_address(self):
        factory.make_Subnet(cidr="10.0.0.0/24")
        data = {
            "ip": "10.0.0.255",
            "mac_address": factory.make_mac_address(),
            "comment": factory.make_name("comment"),
        }

        form = ReservedIPForm(data=data)

        assert not form.is_valid()
        assert {
            "ip": ["The broadcast address cannot be a reserved IP."]
        } == form.errors

    def test_cant_reserve_network_address(self):
        factory.make_Subnet(cidr="10.0.0.0/24")
        data = {
            "ip": "10.0.0.0",
            "mac_address": factory.make_mac_address(),
            "comment": factory.make_name("comment"),
        }

        form = ReservedIPForm(data=data)

        assert not form.is_valid()
        assert {
            "ip": ["The network address cannot be a reserved IP."]
        } == form.errors

    def test_cant_reserve_anycast_address(self):
        factory.make_Subnet(cidr="2001::/64")
        data = {
            "ip": "2001::",
            "mac_address": factory.make_mac_address(),
            "comment": factory.make_name("comment"),
        }

        form = ReservedIPForm(data=data)

        assert not form.is_valid()
        assert {
            "ip": ["The network address cannot be a reserved IP."]
        } == form.errors

    def test_invalid_mac(self):
        factory.make_Subnet(cidr="192.168.0.0/24")

        msgs = [
            "'00:11:22:33:44:gg' is not a valid MAC address.",
            "'0011:22:33:44:55' is not a valid MAC address.",
        ]
        for ip_value, mac_value, msg in [
            ("192.168.0.11", "00:11:22:33:44:gg", {"mac_address": [msgs[0]]}),
            ("192.168.0.15", "0011:22:33:44:55", {"mac_address": [msgs[1]]}),
        ]:
            form = ReservedIPForm(
                data={"ip": ip_value, "mac_address": mac_value, "comment": msg}
            )
            assert not form.is_valid()
            assert msg == form.errors

    def test_ip_outside_subnet(self):
        factory.make_Subnet(cidr="192.168.0.0/24")

        form = ReservedIPForm(
            data={
                "ip": "10.0.0.1",
                "mac_address": "00:11:22:33:44:55",
            }
        )
        assert not form.is_valid()
        assert {
            "subnet": [
                "There is no subnet for 10.0.0.1. Create the subnet and try again."
            ]
        } == form.errors

    def test_ip_already_reserved(self):
        factory.make_Subnet(cidr="192.168.0.0/24")
        factory.make_ReservedIP(
            ip="192.168.0.1", mac_address="00:11:22:33:44:55"
        )
        form = ReservedIPForm(
            data={
                "ip": "192.168.0.1",
                "mac_address": "00:11:22:33:44:56",
            }
        )
        assert not form.is_valid()
        assert {
            "ip": ["Reserved IP with this IP address already exists."]
        } == form.errors

    def test_ip_within_dynamic_range(self):
        subnet = factory.make_Subnet(cidr="192.168.0.0/24")
        factory.make_IPRange(
            subnet=subnet,
            start_ip="192.168.0.100",
            end_ip="192.168.0.200",
            alloc_type=IPRANGE_TYPE.DYNAMIC,
        )
        form = ReservedIPForm(
            data={
                "ip": "192.168.0.100",
                "mac_address": "00:11:22:33:44:56",
            }
        )
        assert not form.is_valid()
        assert {
            "ip": [
                "The reserved IP 192.168.0.100 must be outside the dynamic "
                "range 192.168.0.100 - 192.168.0.200."
            ]
        } == form.errors

    def test_mac_already_reserved(self):
        factory.make_Subnet(cidr="192.168.0.0/24")
        factory.make_ReservedIP(
            ip="192.168.0.1", mac_address="00:11:22:33:44:55"
        )
        form = ReservedIPForm(
            data={
                "ip": "192.168.0.2",
                "mac_address": "00:11:22:33:44:55",
            }
        )
        assert not form.is_valid()
        assert {
            "__all__": [
                "Reserved IP with this MAC address and Subnet already exists."
            ]
        } == form.errors

    def test_ip_must_be_valid(self):
        factory.make_Subnet(cidr="192.168.0.0/24")
        form = ReservedIPForm(
            data={
                "ip": "definitelynotanip",
                "mac_address": "00:11:22:33:44:55",
            }
        )
        assert not form.is_valid()
        assert {"ip": ["Enter a valid IPv4 or IPv6 address."]} == form.errors

    def test_comment_is_optional(self):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        data = {
            "ip": "10.0.0.15",
            "subnet": subnet.id,
            "mac_address": factory.make_mac_address(),
        }

        form = ReservedIPForm(data=data)

        assert form.is_valid()
        reserved_ip = form.save()
        assert reserved_ip.comment == ""

    def test_create_reserved_ip(self):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        data = {
            "ip": "10.0.0.15",
            "subnet": subnet.id,
            "mac_address": "00:11:22:33:44:55",
            "comment": "this is a comment",
        }

        form = ReservedIPForm(data=data)

        assert form.is_valid()
        reserved_ip = form.save()
        assert reserved_ip.ip == "10.0.0.15"
        assert reserved_ip.subnet == subnet
        assert reserved_ip.mac_address == "00:11:22:33:44:55"
        assert reserved_ip.comment == "this is a comment"

    def test_update(self):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        reserved_ip = factory.make_ReservedIP(
            ip="10.0.0.121", mac_address="00:11:22:33:44:55", subnet=subnet
        )

        form = ReservedIPForm(
            instance=reserved_ip, data={"comment": "this is a comment"}
        )

        assert form.is_valid()
        reserved_ip = form.save()
        assert reserved_ip.ip == "10.0.0.121"
        assert reserved_ip.comment == "this is a comment"

    def test_update_mac_not_editable(self):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        reserved_ip = factory.make_ReservedIP(
            ip="10.0.0.121", mac_address="00:11:22:33:44:55", subnet=subnet
        )

        form = ReservedIPForm(
            instance=reserved_ip, data={"mac_address": "00:11:22:33:44:56"}
        )

        assert not form.is_valid()
        assert {
            "__all__": [
                "The ip, mac_address and the subnet of a reserved IP are "
                "immutable. Delete the entry and recreate it."
            ]
        } == form.errors

    def test_update_ip_not_editable(self):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        reserved_ip = factory.make_ReservedIP(
            ip="10.0.0.121", mac_address="00:11:22:33:44:55", subnet=subnet
        )

        form = ReservedIPForm(instance=reserved_ip, data={"ip": "10.0.0.122"})

        assert not form.is_valid()
        assert {
            "__all__": [
                "The ip, mac_address and the subnet of a reserved IP are "
                "immutable. Delete the entry and recreate it."
            ]
        } == form.errors

    def test_update_subnet_not_editable(self):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        subnet2 = factory.make_Subnet(cidr="10.0.1.0/24")
        reserved_ip = factory.make_ReservedIP(
            ip="10.0.0.121", mac_address="00:11:22:33:44:55", subnet=subnet
        )

        form = ReservedIPForm(
            instance=reserved_ip, data={"subnet": subnet2.id}
        )

        assert not form.is_valid()
        assert {
            "ip": ["10.0.0.121 is not part of the subnet."],
            "__all__": [
                "The ip, mac_address and the subnet of a reserved IP are "
                "immutable. Delete the entry and recreate it."
            ],
        } == form.errors
