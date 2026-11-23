# Copyright 2014-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for IP addresses API."""

import http.client

from django.conf import settings
from django.test import RequestFactory
from django.urls import reverse
from netaddr import IPAddress
import pytest

from maasserver.api.ip_addresses import IPAddressesHandler
from maasserver.enum import INTERFACE_LINK_TYPE, INTERFACE_TYPE, IPADDRESS_TYPE
from maasserver.models import DNSResource, StaticIPAddress
from maasserver.models import staticipaddress as staticipaddress_module
from maasserver.models.signals import vlan as vlan_signals_module
from maasserver.testing.factory import factory
from maasserver.utils.converters import json_load_bytes
from maasserver.utils.orm import reload_object, transactional
from maastesting.querycounter import count_queries


@pytest.mark.parametrize(
    "api_identity",
    [
        pytest.param("user=user,client=oauth", id="user=user,client=oauth"),
        pytest.param("admin=admin,client=oauth", id="user=admin,client=oauth"),
    ],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestIPAddressesAPI:
    @pytest.fixture(autouse=True)
    def _setup(
        self,
        api_identity,
        request,
        maas_user,
        api_client,
        admin_api_client,
        mocker,
    ):
        if api_identity.startswith("admin="):
            self.user = request.getfixturevalue("admin")
            self.client = admin_api_client
        else:
            self.user = maas_user
            self.client = api_client
        mocker.patch.object(vlan_signals_module, "post_commit_do")
        mocker.patch.object(staticipaddress_module, "post_commit_do")

    def test_handler_path(self):
        assert reverse("ipaddresses_handler") == "/MAAS/api/2.0/ipaddresses/"

    def test_GET_returns_ipaddresses(self):
        original_ipaddress = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.USER_RESERVED, user=self.user
        )
        response = self.client.get(reverse("ipaddresses_handler"))
        assert response.status_code == http.client.OK, response.content

        parsed_result = json_load_bytes(response.content)
        assert len(parsed_result) == 1, response.content
        [returned_address] = parsed_result
        fields = {"alloc_type", "alloc_type_name", "ip"}
        assert set(returned_address.keys()) == fields.union(
            {"resource_uri", "created", "subnet", "interface_set", "owner"}
        )
        expected_values = {
            field: getattr(original_ipaddress, field)
            for field in fields
            if field not in ("resource_uri", "created")
        }
        # Test that these exist, but not for exact values.
        del returned_address["created"]
        del returned_address["subnet"]
        del returned_address["owner"]
        del returned_address["interface_set"]
        expected_values["resource_uri"] = reverse("ipaddresses_handler")
        assert returned_address == expected_values

    def test_GET_returns_empty_if_no_ipaddresses(self):
        response = self.client.get(reverse("ipaddresses_handler"))
        assert response.status_code == http.client.OK, response.content
        assert json_load_bytes(response.content) == []

    def test_GET_only_returns_request_users_addresses(self):
        ipaddress = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.USER_RESERVED, user=self.user
        )
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.USER_RESERVED, user=factory.make_User()
        )
        response = self.client.get(reverse("ipaddresses_handler"))
        assert response.status_code == http.client.OK, response.content
        parsed_result = json_load_bytes(response.content)
        [returned_address] = parsed_result
        assert returned_address["ip"] == ipaddress.ip

    def test_GET_returns_all_addresses_if_admin_and_all_specified(self):
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.USER_RESERVED, user=self.user
        )
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.USER_RESERVED, user=factory.make_User()
        )
        response = self.client.get(
            reverse("ipaddresses_handler"), {"all": "1"}
        )
        if self.user.is_superuser:
            assert response.status_code == http.client.OK, response.content
            parsed_result = json_load_bytes(response.content)
            assert 2 == len(parsed_result)
        else:
            assert response.status_code == http.client.FORBIDDEN, (
                response.content
            )
            assert response.content.decode("utf-8") == (
                "Listing all IP addresses requires admin privileges."
            )

    def test_GET_returns_other_user_addresses_if_admin_and_user_specified(
        self,
    ):
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.USER_RESERVED, user=self.user
        )
        user2 = factory.make_User()
        ipaddress2 = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.USER_RESERVED, user=user2
        )
        response = self.client.get(
            reverse("ipaddresses_handler"), {"owner": user2.username}
        )
        if self.user.is_superuser:
            assert response.status_code == http.client.OK, response.content
            parsed_result = json_load_bytes(response.content)
            assert 1 == len(parsed_result)
            assert parsed_result[0]["ip"] == ipaddress2.ip
        else:
            assert response.status_code == http.client.FORBIDDEN, (
                response.content
            )
            assert response.content.decode("utf-8") == (
                "Listing another user's IP addresses requires admin privileges."
            )

    def test_GET_returns_other_users_ip_address_for_admin_with_all_with_ip(
        self,
    ):
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.USER_RESERVED, user=self.user
        )
        user2 = factory.make_User()
        ipaddress2 = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.USER_RESERVED, user=user2
        )
        response = self.client.get(
            reverse("ipaddresses_handler"),
            {"ip": str(ipaddress2.ip), "all": "true"},
        )
        if self.user.is_superuser:
            assert response.status_code == http.client.OK, response.content
            parsed_result = json_load_bytes(response.content)
            assert 1 == len(parsed_result)
            assert parsed_result[0]["ip"] == ipaddress2.ip
        else:
            assert response.status_code == http.client.FORBIDDEN, (
                response.content
            )
            assert response.content.decode("utf-8") == (
                "Listing all IP addresses requires admin privileges."
            )

    def test_GET_with_all_for_admin_returns_non_user_reserved_types(self):
        factory.make_StaticIPAddress(alloc_type=IPADDRESS_TYPE.STICKY)
        factory.make_StaticIPAddress(alloc_type=IPADDRESS_TYPE.USER_RESERVED)
        response = self.client.get(
            reverse("ipaddresses_handler"), {"all": "true"}
        )
        if self.user.is_superuser:
            assert response.status_code == http.client.OK, response.content
            parsed_result = json_load_bytes(response.content)
            assert 2 == len(parsed_result)
        else:
            assert response.status_code == http.client.FORBIDDEN, (
                response.content
            )
            assert response.content.decode("utf-8") == (
                "Listing all IP addresses requires admin privileges."
            )

    def test_GET_returns_own_ip_address_with_ip(self):
        factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.USER_RESERVED, user=self.user
        )
        ipaddress2 = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.USER_RESERVED, user=self.user
        )
        response = self.client.get(
            reverse("ipaddresses_handler"), {"ip": str(ipaddress2.ip)}
        )
        assert response.status_code == http.client.OK, response.content
        parsed_result = json_load_bytes(response.content)
        assert 1 == len(parsed_result)
        assert parsed_result[0]["ip"] == ipaddress2.ip

    def test_GET_sorts_by_id(self):
        addrs = []
        for _ in range(3):
            addrs.append(
                factory.make_StaticIPAddress(
                    alloc_type=IPADDRESS_TYPE.USER_RESERVED, user=self.user
                )
            )
        response = self.client.get(reverse("ipaddresses_handler"))
        assert response.status_code == http.client.OK, response.content
        parsed_result = json_load_bytes(response.content)
        expected = [
            addr.ip
            for addr in sorted(addrs, key=lambda addr: getattr(addr, "id"))  # noqa: B009
        ]
        observed = [result["ip"] for result in parsed_result]
        assert observed == expected


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("admin=admin,client=oauth", id="user=admin,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestIPAddressesReadPrefetch:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request, mocker):
        user_fixture = (
            "admin" if api_identity.startswith("admin=") else "maas_user"
        )
        client_fixture = (
            "admin_api_client"
            if api_identity.startswith("admin=")
            else "api_client"
        )
        self.user = request.getfixturevalue(user_fixture)
        self.client = request.getfixturevalue(client_fixture)
        mocker.patch.object(vlan_signals_module, "post_commit_do")
        mocker.patch.object(staticipaddress_module, "post_commit_do")

    def test_read_all_does_not_query_node_per_ip(self):
        # read() serializes interface_set, whose system_id/resource_uri call
        # get_node(); without prefetch that runs a query per IP. The node
        # query count must stay flat as machines are added.
        subnet = factory.make_Subnet()
        request = RequestFactory().get("/", {"all": "true"})
        request.user = self.user
        handler = IPAddressesHandler()

        def access_nodes():
            query = handler.read(request)
            return [
                iface.get_node()
                for ip in query
                for iface in ip.interface_set.all()
            ]

        def add_machines(count):
            for _ in range(count):
                node = factory.make_Node(interface=False)
                iface = factory.make_Interface(
                    INTERFACE_TYPE.PHYSICAL, node=node, vlan=subnet.vlan
                )
                factory.make_StaticIPAddress(
                    alloc_type=IPADDRESS_TYPE.AUTO,
                    subnet=subnet,
                    interface=iface,
                )

        add_machines(2)
        # Warm the permission cache; the first read() call runs one extra
        # authorization query that later calls serve from the cache.
        access_nodes()
        count_2, nodes_2 = count_queries(access_nodes)
        add_machines(3)
        count_5, nodes_5 = count_queries(access_nodes)
        assert len(nodes_2) == 2
        assert len(nodes_5) == 5
        assert count_2 == 2
        assert count_5 == count_2


@pytest.mark.parametrize(
    "api_identity,force",
    [
        pytest.param(
            "user=user,client=oauth",
            None,
            id="user=user,client=oauth,normal",
        ),
        pytest.param(
            "user=user,client=oauth",
            False,
            id="user=user,client=oauth,without_force",
        ),
        pytest.param(
            "user=user,client=oauth",
            True,
            id="user=user,client=oauth,with_force",
        ),
        pytest.param(
            "admin=admin,client=oauth",
            None,
            id="user=admin,client=oauth,normal",
        ),
        pytest.param(
            "admin=admin,client=oauth",
            False,
            id="user=admin,client=oauth,without_force",
        ),
        pytest.param(
            "admin=admin,client=oauth",
            True,
            id="user=admin,client=oauth,with_force",
        ),
    ],
)
@pytest.mark.usefixtures(
    "maasdb", "maas_region_test", "factory", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestIPAddressesReleaseAPI:
    @pytest.fixture(autouse=True)
    def _setup(
        self,
        transactional_maasdb,
        api_identity,
        force,
        request,
        maas_user,
        api_client,
        admin_api_client,
        mocker,
    ):
        self.force = force
        if api_identity.startswith("admin="):
            self.user = request.getfixturevalue("admin")
            self.client = admin_api_client
        else:
            self.user = maas_user
            self.client = api_client
        mocker.patch.object(vlan_signals_module, "post_commit_do")
        mocker.patch.object(staticipaddress_module, "post_commit_do")

    @property
    def expect_forbidden(self):
        # The 'force' parameter should only work if (1) the user-under-test
        # is a superuser, and (2) force=true was specified.
        return not self.user.is_superuser and self.force is True

    def expected_status(self, status):
        # Non-administrators always get a FORBIDDEN (403) when requesting
        # a forced delete.
        if self.force and not self.user.is_superuser:
            return http.client.FORBIDDEN
        else:
            return status

    def post_release_request(self, ip, mac=None, discovered=None):
        params = {"op": "release", "ip": ip}
        if mac is not None:
            params["mac"] = mac
        if self.force is not None:
            params["force"] = str(self.force)
        if discovered is not None:
            params["discovered"] = str(discovered)
        return self.client.post(reverse("ipaddresses_handler"), params)

    @transactional
    def test_POST_release_rejects_invalid_ip(self):
        response = self.post_release_request("1690.254.0.1")
        expected_status = self.expected_status(http.client.BAD_REQUEST)
        assert response.status_code == expected_status
        if expected_status != http.client.FORBIDDEN:
            assert json_load_bytes(response.content) == {
                "ip": ["Enter a valid IPv4 or IPv6 address."]
            }
        else:
            assert response.content.decode("utf-8") == (
                "Force-releasing an IP address requires admin privileges."
            )

    @transactional
    def test_POST_release_allows_admin_to_release_other_users_ip(self):
        factory.make_StaticIPAddress(
            user=factory.make_User(),
            alloc_type=IPADDRESS_TYPE.USER_RESERVED,
            ip="192.168.0.1",
        )
        response = self.post_release_request("192.168.0.1")
        if self.expect_forbidden:
            assert response.status_code == http.client.FORBIDDEN
            assert response.content.decode("utf-8") == (
                "Force-releasing an IP address requires admin privileges."
            )
        elif not self.force:
            assert response.status_code == http.client.BAD_REQUEST
            assert "does not belong to the requesting user" in (
                response.content.decode("utf-8")
            )
        else:
            assert response.status_code == http.client.NO_CONTENT
            assert response.content.decode("utf-8") == ""

    @transactional
    def test_POST_release_allows_admin_to_release_sticky_ip(self):
        # Make an "orphaned" IP address, like the one in bug #1630034.
        static_ip = factory.make_StaticIPAddress(
            user=factory.make_User(), alloc_type=IPADDRESS_TYPE.STICKY
        )
        response = self.post_release_request(str(static_ip.ip))
        if self.expect_forbidden:
            assert response.status_code == http.client.FORBIDDEN
            assert response.content.decode("utf-8") == (
                "Force-releasing an IP address requires admin privileges."
            )
        elif not self.force:
            assert response.status_code == http.client.BAD_REQUEST
            assert "does not belong to the requesting user" in (
                response.content.decode("utf-8")
            )
        else:
            assert response.status_code == http.client.NO_CONTENT
            assert response.content.decode("utf-8") == ""

    @transactional
    def test_POST_release_allows_admin_to_release_discovered_ip(self):
        # Make an "orphaned" IP address, like the one in bug #1630034.
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.DISCOVERED
        )
        response = self.post_release_request(
            str(static_ip.ip), discovered=True
        )
        if self.expect_forbidden:
            assert response.status_code == http.client.FORBIDDEN
            assert response.content.decode("utf-8") == (
                "Force-releasing an IP address requires admin privileges."
            )
        elif not self.force:
            assert response.status_code == http.client.BAD_REQUEST
            assert "does not belong to the requesting user" in (
                response.content.decode("utf-8")
            )
        else:
            assert response.status_code == http.client.NO_CONTENT
            assert response.content.decode("utf-8") == ""

    @transactional
    def test_POST_release_allows_admin_to_release_discovered_ip_with_interface(
        self,
    ):
        # Make an "orphaned" IP address, like the one in bug #1898122.
        static_ip = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.DISCOVERED
        )
        interface = factory.make_Interface()
        interface.ip_addresses.add(static_ip)

        response = self.post_release_request(
            str(static_ip.ip), discovered=True
        )
        if self.expect_forbidden:
            assert response.status_code == http.client.FORBIDDEN
            assert response.content.decode("utf-8") == (
                "Force-releasing an IP address requires admin privileges."
            )
        elif not self.force:
            assert response.status_code == http.client.BAD_REQUEST
            assert "does not belong to the requesting user" in (
                response.content.decode("utf-8")
            )
        else:
            assert response.status_code == http.client.NO_CONTENT
            assert response.content.decode("utf-8") == ""

    @transactional
    def test_POST_release_deallocates_address(self):
        ipaddress = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.USER_RESERVED, user=self.user
        )
        response = self.post_release_request(ipaddress.ip)
        assert response.status_code == self.expected_status(
            http.client.NO_CONTENT
        ), response.content
        if not self.expect_forbidden:
            assert reload_object(ipaddress) is None

    @transactional
    def test_POST_release_deletes_unknown_interface(self):
        subnet = factory.make_Subnet()
        unknown_nic = factory.make_Interface(INTERFACE_TYPE.UNKNOWN)
        ipaddress = unknown_nic.link_subnet(
            INTERFACE_LINK_TYPE.STATIC,
            subnet,
            alloc_type=IPADDRESS_TYPE.USER_RESERVED,
            user=self.user,
        )
        response = self.post_release_request(ipaddress.ip)
        assert response.status_code == self.expected_status(
            http.client.NO_CONTENT
        ), response.content
        if not self.expect_forbidden:
            assert reload_object(unknown_nic) is None

    @transactional
    def test_POST_release_does_not_delete_interfaces_linked_to_nodes(self):
        node = factory.make_Node()
        attached_nic = factory.make_Interface(node=node)
        subnet = factory.make_Subnet()
        ipaddress = attached_nic.link_subnet(
            INTERFACE_LINK_TYPE.STATIC,
            subnet,
            alloc_type=IPADDRESS_TYPE.USER_RESERVED,
            user=self.user,
        )

        self.post_release_request(ipaddress.ip)
        assert reload_object(attached_nic) == attached_nic

    @transactional
    def test_POST_release_does_not_delete_other_IPs_I_own(self):
        ipaddress = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.USER_RESERVED, user=self.user
        )
        other_address = factory.make_StaticIPAddress(
            alloc_type=IPADDRESS_TYPE.USER_RESERVED, user=self.user
        )
        response = self.post_release_request(ipaddress.ip)
        assert response.status_code == self.expected_status(
            http.client.NO_CONTENT
        ), response.content
        assert reload_object(other_address) is not None


@pytest.mark.parametrize(
    "api_identity,ip_param",
    [
        pytest.param(
            "user=user,client=oauth",
            "ip",
            id="user=user,client=oauth,with_ip_param",
        ),
        pytest.param(
            "user=user,client=oauth",
            "ip_address",
            id="user=user,client=oauth,with_ip_address_param",
        ),
    ],
)
@pytest.mark.usefixtures(
    "maasdb", "maas_region_test", "factory", "transactional_maasdb"
)
@pytest.mark.allow_transactions
class TestIPAddressesReserveAPI:
    @pytest.fixture(autouse=True)
    def _setup(
        self, transactional_maasdb, api_identity, request, ip_param, mocker
    ):
        user_fixture = (
            "admin" if api_identity.startswith("admin=") else "maas_user"
        )
        client_fixture = (
            "admin_api_client"
            if api_identity.startswith("admin=")
            else "api_client"
        )
        self.user = request.getfixturevalue(user_fixture)
        self.client = request.getfixturevalue(client_fixture)
        self.ip_param = ip_param
        mocker.patch.object(vlan_signals_module, "post_commit_do")
        mocker.patch.object(staticipaddress_module, "post_commit_do")

    def post_reservation_request(
        self,
        subnet=None,
        ip_address=None,
        network=None,
        mac=None,
        hostname=None,
    ):
        params = {"op": "reserve"}
        if ip_address is not None:
            params[self.ip_param] = ip_address
        if subnet is not None:
            params["subnet"] = subnet.cidr
        if network is not None and subnet is None:
            params["subnet"] = str(network)
        if mac is not None:
            params["mac"] = mac
        if hostname is not None:
            params["hostname"] = hostname
        return self.client.post(reverse("ipaddresses_handler"), params)

    def test_POST_reserve_creates_ipaddress(self):
        subnet = factory.make_Subnet()
        response = self.post_reservation_request(subnet)
        assert response.status_code == http.client.OK
        returned_address = json_load_bytes(response.content)
        [staticipaddress] = StaticIPAddress.objects.all()
        # Test that these fields exist, but don't test for exact values.
        del returned_address["created"]
        del returned_address["subnet"]
        del returned_address["interface_set"]
        del returned_address["owner"]
        expected = dict(
            alloc_type=staticipaddress.alloc_type,
            alloc_type_name=staticipaddress.alloc_type_name,
            ip=staticipaddress.ip,
            resource_uri=reverse("ipaddresses_handler"),
        )
        assert returned_address == expected
        assert staticipaddress.alloc_type == IPADDRESS_TYPE.USER_RESERVED
        assert staticipaddress.user == self.user

    def test_POST_reserve_creates_dnsresource(self):
        # The api doesn't autocreate the domain, so create one now.
        domain = factory.make_Domain()
        hostname = factory.make_name("host")
        fqdn = f"{hostname}.{domain.name}"
        subnet = factory.make_Subnet()
        response = self.post_reservation_request(subnet, hostname=fqdn)
        assert response.status_code == http.client.OK
        returned_address = json_load_bytes(response.content)
        [staticipaddress] = StaticIPAddress.objects.all()
        # We don't need to test the value of the 'created' datetime
        # field. By removing it, we also test for its presence.
        del returned_address["created"]
        del returned_address["subnet"]
        del returned_address["interface_set"]
        del returned_address["owner"]
        expected = dict(
            alloc_type=staticipaddress.alloc_type,
            alloc_type_name=staticipaddress.alloc_type_name,
            ip=staticipaddress.ip,
            resource_uri=reverse("ipaddresses_handler"),
        )
        assert returned_address == expected
        assert staticipaddress.alloc_type == IPADDRESS_TYPE.USER_RESERVED
        assert staticipaddress.user == self.user
        dnsrr = DNSResource.objects.get(name=hostname, domain=domain)
        assert set(dnsrr.ip_addresses.all()) == {staticipaddress}

    def test_POST_reserve_with_MAC_links_MAC_to_ip_address(self):
        subnet = factory.make_Subnet()
        mac = factory.make_mac_address()

        response = self.post_reservation_request(subnet=subnet, mac=mac)
        assert response.status_code == http.client.OK
        [staticipaddress] = StaticIPAddress.objects.all()
        assert mac == staticipaddress.interface_set.first().mac_address

    def test_POST_returns_error_when_MAC_exists_on_node(self):
        subnet = factory.make_Subnet()
        nic = factory.make_Interface(INTERFACE_TYPE.PHYSICAL, vlan=subnet.vlan)

        response = self.post_reservation_request(
            subnet=subnet, mac=nic.mac_address
        )
        assert response.status_code == http.client.BAD_REQUEST, (
            response.content
        )

    def test_POST_allows_claiming_of_new_static_ips_for_existing_MAC(self):
        subnet = factory.make_Subnet()
        nic = factory.make_Interface(INTERFACE_TYPE.UNKNOWN)

        response = self.post_reservation_request(
            subnet=subnet, mac=nic.mac_address
        )
        assert http.client.OK == response.status_code
        [staticipaddress] = nic.ip_addresses.all()
        assert (
            nic.mac_address
            == staticipaddress.interface_set.first().mac_address
        )

    def test_POST_reserve_errors_for_no_matching_subnet(self):
        network = factory.make_ipv4_network()
        factory.make_Subnet(cidr=str(network.cidr))
        other_net = factory.make_ipv4_network(but_not=[network])
        response = self.post_reservation_request(network=other_net)
        assert response.status_code == http.client.BAD_REQUEST, (
            response.content
        )
        expected = f"Unable to identify subnet: {other_net}."
        assert response.content == expected.encode(settings.DEFAULT_CHARSET)

    def test_POST_reserve_creates_ip_address(self):
        subnet = factory.make_Subnet()
        ip_in_network = factory.pick_ip_in_Subnet(subnet)
        response = self.post_reservation_request(ip_address=ip_in_network)
        assert response.status_code == http.client.OK, response.content
        returned_address = json_load_bytes(response.content)
        [staticipaddress] = StaticIPAddress.objects.all()
        assert IPADDRESS_TYPE.USER_RESERVED == returned_address["alloc_type"]
        assert ip_in_network == returned_address["ip"]
        assert ip_in_network == staticipaddress.ip

    def test_POST_reserve_ip_address_detects_in_use_address(self):
        subnet = factory.make_Subnet()
        ip_in_network = factory.pick_ip_in_Subnet(subnet)
        response = self.post_reservation_request(subnet, ip_in_network)
        assert response.status_code == http.client.OK, response.content
        # Do same request again and check it is rejected.
        response = self.post_reservation_request(subnet, ip_in_network)
        assert http.client.NOT_FOUND == response.status_code
        assert response.content.decode() == (
            f"The IP address {ip_in_network} is already in use."
        )

    def test_POST_reserve_ip_address_rejects_ip_in_dynamic_range(self):
        subnet = factory.make_ipv4_Subnet_with_IPRanges()
        ip = str(IPAddress(subnet.get_dynamic_maasipset().first))
        response = self.post_reservation_request(subnet, ip)
        assert response.status_code == http.client.FORBIDDEN, response.content

    def test_POST_reserve_without_hostname_creates_ip_without_hostname(self):
        subnet = factory.make_Subnet()
        response = self.post_reservation_request(subnet=subnet)
        assert response.status_code == http.client.OK
        [staticipaddress] = StaticIPAddress.objects.all()
        assert 0 == staticipaddress.dnsresource_set.all().count()

    def test_POST_reserve_with_bad_fqdn_fails(self):
        subnet = factory.make_Subnet()
        hostname = factory.make_hostname()
        domainname = factory.make_name("domain")
        fqdn = f"{hostname}.{domainname}"
        response = self.post_reservation_request(subnet=subnet, hostname=fqdn)
        assert response.status_code == http.client.NOT_FOUND

    def test_POST_reserve_with_hostname_creates_ip_with_hostname(self):
        subnet = factory.make_Subnet()
        hostname = factory.make_hostname()
        response = self.post_reservation_request(
            subnet=subnet, hostname=hostname
        )
        assert response.status_code == http.client.OK
        [staticipaddress] = StaticIPAddress.objects.all()
        assert hostname == staticipaddress.dnsresource_set.first().name

    def test_POST_reserve_with_hostname_and_ip_creates_ip_with_hostname(self):
        subnet = factory.make_Subnet()
        hostname = factory.make_hostname()
        ip_in_network = factory.pick_ip_in_Subnet(subnet)
        response = self.post_reservation_request(
            subnet=subnet, ip_address=ip_in_network, hostname=hostname
        )
        assert response.status_code == http.client.OK, response.content
        returned_address = json_load_bytes(response.content)
        [staticipaddress] = StaticIPAddress.objects.all()
        assert IPADDRESS_TYPE.USER_RESERVED == returned_address["alloc_type"]
        assert ip_in_network == returned_address["ip"]
        assert ip_in_network == staticipaddress.ip
        assert hostname == staticipaddress.dnsresource_set.first().name

    def test_POST_reserve_with_fqdn_creates_ip_with_hostname(self):
        subnet = factory.make_Subnet()
        hostname = factory.make_hostname()
        domainname = factory.make_Domain().name
        fqdn = f"{hostname}.{domainname}"
        response = self.post_reservation_request(
            subnet=subnet, hostname=f"{hostname}.{domainname}"
        )
        assert response.status_code == http.client.OK
        [staticipaddress] = StaticIPAddress.objects.all()
        assert hostname == staticipaddress.dnsresource_set.first().name
        assert fqdn == staticipaddress.dnsresource_set.first().fqdn

    def test_POST_reserve_with_fqdn_and_ip_creates_ip_with_hostname(self):
        subnet = factory.make_Subnet()
        hostname = factory.make_hostname()
        domainname = factory.make_Domain().name
        fqdn = f"{hostname}.{domainname}"
        ip_in_network = factory.pick_ip_in_Subnet(subnet)
        response = self.post_reservation_request(
            subnet=subnet,
            ip_address=ip_in_network,
            hostname=f"{hostname}.{domainname}",
        )
        assert response.status_code == http.client.OK, response.content
        returned_address = json_load_bytes(response.content)
        [staticipaddress] = StaticIPAddress.objects.all()
        assert IPADDRESS_TYPE.USER_RESERVED == returned_address["alloc_type"]
        assert ip_in_network == returned_address["ip"]
        assert ip_in_network == staticipaddress.ip
        assert fqdn == staticipaddress.dnsresource_set.first().fqdn

    def test_POST_reserve_with_no_parameters_fails_with_bad_request(self):
        response = self.post_reservation_request()
        assert response.status_code == http.client.BAD_REQUEST, (
            response.content
        )

    def test_POST_reserve_rejects_invalid_ip(self):
        response = self.post_reservation_request(ip_address="1690.254.0.1")
        assert response.status_code == http.client.BAD_REQUEST, (
            response.content
        )
        assert json_load_bytes(response.content) == {
            "ip_address": ["Enter a valid IPv4 or IPv6 address."]
        }
