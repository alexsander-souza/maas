# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from collections import Counter
from contextlib import contextmanager
import itertools
import json
import re
import socket
from socket import (
    AF_INET,
    AF_INET6,
    EAI_BADFLAGS,
    EAI_NODATA,
    EAI_NONAME,
    gaierror,
    IPPROTO_TCP,
)
from typing import List
from unittest import mock
from unittest.mock import Mock

from netaddr import EUI, IPAddress, IPNetwork, IPRange
import netifaces
from netifaces import AF_LINK
import pytest
from twisted.internet.defer import inlineCallbacks, succeed
from twisted.names.error import (
    AuthoritativeDomainError,
    DNSQueryTimeoutError,
    DomainError,
    ResolverError,
)

from maascommon.utils.network import (
    get_eui_organization,
    get_mac_organization,
    inet_ntop,
    IPRangeStatistics,
    MAASIPRange,
    MAASIPSet,
    make_iprange,
)
from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.factory import factory
import provisioningserver.utils
from provisioningserver.utils import network as network_module
from provisioningserver.utils.network import (
    annotate_with_default_monitored_interfaces,
    bytes_to_hex,
    bytes_to_int,
    clean_up_netifaces_address,
    convert_host_to_uri_str,
    enumerate_assigned_ips,
    enumerate_ipv4_addresses,
    find_ip_via_arp,
    find_mac_via_arp,
    fix_link_addresses,
    format_eui,
    generate_mac_address,
    get_all_addresses_for_interface,
    get_all_interface_addresses,
    get_all_interface_source_addresses,
    get_all_interface_subnets,
    get_all_interfaces_definition,
    get_default_monitored_interfaces,
    get_ifname_for_label,
    get_ifname_ifdata_for_destination,
    get_interface_children,
    get_source_address,
    get_source_address_for_url,
    has_ipv4_address,
    hex_str_to_bytes,
    interface_children,
    intersect_iprange,
    ip_range_within_network,
    is_loopback_address,
    is_mac,
    LOOPBACK_INTERFACE_INFO,
    make_network,
    parse_integer,
    partition_by_family,
    preferred_hostnames_sort_key,
    resolve_bind_address,
    resolve_bind_addresses,
    resolve_connect_address,
    resolve_dual_stack_bind_addresses,
    resolve_dual_stack_service_bind,
    resolve_host_to_addrinfo,
    resolve_hostname,
    resolve_service_bind,
    resolves_to_loopback_address,
    reverseResolve,
)
from provisioningserver.utils.shell import get_env_with_locale

TIMEOUT = get_testing_timeout()


class TestNetworkBase:
    @pytest.fixture(autouse=True)
    def _setup_mocker(self, mocker):
        self.mocker = mocker

    def patch(self, obj, name, **kwargs):
        return self.mocker.patch.object(obj, name, **kwargs)


def get_interfaces_result(
    mocker, ip_addr, iproute_info, dhclient_info, in_container=False
):
    mocker.patch.object(network_module, "get_ip_addr").return_value = ip_addr
    mocker.patch.object(
        network_module, "get_ip_route"
    ).return_value = iproute_info
    mocker.patch.object(
        network_module, "get_dhclient_info"
    ).return_value = dhclient_info
    mocker.patch.object(
        network_module, "running_in_container"
    ).return_value = in_container
    return get_all_interfaces_definition(annotate_with_monitored=False)


class TestFixLinkAddresses(TestNetworkBase):
    def test_fixes_with_cidr(self):
        links = [
            {"address": "1.2.3.1/24", "mode": "static"},
            {"address": "1.2.3.4/32", "mode": "static"},
            {"address": "2001::1/96", "mode": "static"},
            {"address": "2001::123/128", "mode": "static"},
        ]
        fix_link_addresses(links)
        assert links == [
            {"address": "1.2.3.1/24", "mode": "static"},
            {"address": "1.2.3.4/24", "mode": "static"},
            {"address": "2001::1/96", "mode": "static"},
            {"address": "2001::123/96", "mode": "static"},
        ]

    def test_fixes_with_netmask(self):
        links = [
            {"address": "1.2.3.1", "netmask": 24, "mode": "static"},
            {"address": "1.2.3.4", "netmask": 32, "mode": "static"},
            {"address": "2001::1", "netmask": 96, "mode": "static"},
            {"address": "2001::123", "netmask": 128, "mode": "static"},
        ]
        fix_link_addresses(links)
        assert links == [
            {"address": "1.2.3.1", "netmask": 24, "mode": "static"},
            {"address": "1.2.3.4", "netmask": 24, "mode": "static"},
            {"address": "2001::1", "netmask": 96, "mode": "static"},
            {"address": "2001::123", "netmask": 96, "mode": "static"},
        ]


class TestMakeNetwork(TestNetworkBase):
    def test_constructs_IPNetwork(self):
        network = make_network("10.22.82.0", 24)
        assert isinstance(network, IPNetwork)
        assert IPNetwork("10.22.82.0/24") == network

    def test_passes_args_to_IPNetwork(self):
        self.patch(network_module, "IPNetwork")
        make_network("10.1.2.0", 24, foo=9)
        assert [
            mock.call("10.1.2.0/24", foo=9)
        ] == network_module.IPNetwork.mock_calls


class TestInetNtop(TestNetworkBase):
    def test_ipv4(self):
        ip = factory.make_ipv4_address()
        assert ip == inet_ntop(IPAddress(ip).value)

    def test_ipv6(self):
        ip = factory.make_ipv6_address()
        assert ip == inet_ntop(IPAddress(ip).value)


class TestConversionFunctions(TestNetworkBase):
    def test_bytes_to_hex(self):
        assert b"01ff" == bytes_to_hex(b"\x01\xff")
        assert b"0001ff" == bytes_to_hex(b"\x00\x01\xff")

    def test_bytes_to_int(self):
        assert 65535 == bytes_to_int(b"\xff\xff")
        assert 16777215 == bytes_to_int(b"\xff\xff\xff")
        assert 281474976710655 == bytes_to_int(b"\xff\xff\xff\xff\xff\xff")

    def test_hex_str_to_bytes(self):
        assert b"\x00\x00" == hex_str_to_bytes("0x0000")
        assert b"\xff\xff" == hex_str_to_bytes("ff:ff")
        assert b"\xff\xff" == hex_str_to_bytes("ff ff  ")
        assert b"\xff\xff" == hex_str_to_bytes("  ff-ff")
        assert b"\xff\xff" == hex_str_to_bytes("ff-ff")
        assert b"\xff\xff" == hex_str_to_bytes("0xffff")
        assert b"\xff\xff" == hex_str_to_bytes(" 0xffff")
        assert b"\x01\x02\x03\x04\x05\x06" == hex_str_to_bytes(
            "01:02:03:04:05:06"
        )
        assert b"\x0a\x0b\x0c\x0d\x0e\x0f" == hex_str_to_bytes(
            "0A:0B:0C:0D:0E:0F"
        )
        assert b"\x0a\x0b\x0c\x0d\x0e\x0f" == hex_str_to_bytes(
            "0a:0b:0c:0d:0e:0f"
        )

    def test_format_eui(self):
        assert "0a:0b:0c:0d:0e:0f" == format_eui(EUI("0A-0B-0C-0D-0E-0F"))


class TestFindIPViaARP(TestNetworkBase):
    def patch_call(self, output):
        """Replace `call_and_check` with one that returns `output`."""
        fake = self.patch(network_module, "call_and_check")
        fake.return_value = output.encode("ascii")
        return fake

    def test_resolves_MAC_address_to_IP(self):
        sample = """\
        Address HWtype  HWaddress Flags Mask            Iface
        192.168.100.20 (incomplete)                              virbr1
        192.168.0.104 (incomplete)                              eth0
        192.168.0.5 (incomplete)                              eth0
        192.168.0.2 (incomplete)                              eth0
        192.168.0.100 (incomplete)                              eth0
        192.168.122.20 ether   52:54:00:02:86:4b   C                     virbr0
        192.168.0.4 (incomplete)                              eth0
        192.168.0.1 ether   90:f6:52:f6:17:92   C                     eth0
        """

        call_and_check = self.patch_call(sample)
        ip_address_observed = find_ip_via_arp("90:f6:52:f6:17:92")
        call_and_check.assert_called_once_with(["arp", "-n"])
        assert "192.168.0.1" == ip_address_observed

    def test_returns_consistent_output(self):
        mac = factory.make_mac_address()
        ips = ["10.0.0.11", "10.0.0.99"]
        lines = [f"{ip} ether {mac} C eth0" for ip in ips]
        self.patch_call("\n".join(lines))
        one_result = find_ip_via_arp(mac)
        self.patch_call("\n".join(reversed(lines)))
        other_result = find_ip_via_arp(mac)

        assert one_result in ips
        assert one_result == other_result

    def test_ignores_case(self):
        sample = """\
        192.168.0.1 ether   90:f6:52:f6:17:92   C                     eth0
        """
        self.patch_call(sample)
        ip_address_observed = find_ip_via_arp("90:f6:52:f6:17:92".upper())
        assert "192.168.0.1" == ip_address_observed


class TestIsMac(TestNetworkBase):
    def test_true(self):
        assert is_mac("aa:bb:cc:dd:ee:ff")

    def test_false(self):
        assert not (is_mac(factory.make_name("bad")))


class TestGetMACOrganization(TestNetworkBase):
    """Tests for `get_mac_organization()` and `get_eui_organization()`."""

    def test_get_mac_organization(self):
        mac_address = "48:51:b7:00:00:00"
        assert re.search(r"[^\s]", get_mac_organization(mac_address))

    def test_get_eui_organization(self):
        mac_address = "48:51:b7:00:00:00"
        assert re.search(r"[^\s]", get_eui_organization(EUI(mac_address)))

    def test_get_eui_organization_returns_None_for_UnicodeError(self):
        mock_eui = Mock()
        mock_eui.oui = Mock()
        mock_eui.oui.registration = Mock()
        mock_eui.oui.registration.side_effect = UnicodeError
        organization = get_eui_organization(mock_eui)
        assert organization is None

    def test_get_eui_organization_returns_None_for_IndexError(self):
        mock_eui = Mock()
        mock_eui.oui = Mock()
        mock_eui.oui.registration = Mock()
        mock_eui.oui.registration.side_effect = IndexError
        organization = get_eui_organization(mock_eui)
        assert organization is None

    def test_get_eui_organization_returns_none_for_invalid_mac(self):
        organization = get_eui_organization(EUI("FF:FF:b7:00:00:00"))
        assert organization is None


class TestFindMACViaARP(TestNetworkBase):
    def patch_call(self, output):
        """Replace `call_and_check` with one that returns `output`."""
        fake = self.patch(provisioningserver.utils.network, "call_and_check")
        fake.return_value = output.encode("ascii")
        return fake

    def make_output(self, ip=None, mac=None, dev=None, state="REACHABLE"):
        """Compose an `ip --json neigh` output for given `ip` and `mac`."""
        if ip is None:
            ip = factory.make_ipv4_address()
        if mac is None:
            mac = factory.make_mac_address()
        if dev is None:
            dev = factory.make_name("eth", sep="")
        entry = {
            "dst": ip,
            "dev": dev,
            "state": [state],
        }
        if state != "FAILED":
            entry["lladdr"] = mac
        return json.dumps([entry])

    def test_calls_ip_neigh(self):
        call_and_check = self.patch_call("")
        find_mac_via_arp(factory.make_ipv4_address())
        env = get_env_with_locale(locale="C")
        call_and_check.assert_called_once_with(
            ["ip", "--json", "neigh"], env=env
        )

    def test_works_with_real_call(self):
        # No error.
        find_mac_via_arp(factory.make_ipv4_address())

    def test_fails_on_nonsensical_output(self):
        self.patch_call("Weird output...")
        with pytest.raises(json.JSONDecodeError):
            find_mac_via_arp(factory.make_ipv4_address())

    def test_returns_None_if_not_found(self):
        self.patch_call(self.make_output())
        assert find_mac_via_arp(factory.make_ipv4_address()) is None

    def test_resolves_IPv4_address_to_MAC(self):
        self.patch_call(
            self.make_output(ip="10.55.60.9", mac="3c:41:92:68:2e:00")
        )
        mac_address_observed = find_mac_via_arp("10.55.60.9")
        assert "3c:41:92:68:2e:00" == mac_address_observed

    def test_resolves_IPv6_address_to_MAC(self):
        self.patch_call(
            self.make_output(
                ip="fd10::a76:d7fe:fe93:7cb", mac="3c:41:92:6b:2e:00"
            )
        )
        mac_address_observed = find_mac_via_arp("fd10::a76:d7fe:fe93:7cb")
        assert "3c:41:92:6b:2e:00" == mac_address_observed

    def test_ignores_failed_neighbours(self):
        ip = factory.make_ipv4_address()
        self.patch_call(self.make_output(ip=ip, state="FAILED"))
        assert find_mac_via_arp(ip) is None

    def test_is_not_fooled_by_different_notations(self):
        mac = factory.make_mac_address()
        self.patch_call(self.make_output(ip="9::0:05", mac=mac))
        assert mac == find_mac_via_arp("09:0::5")

    def test_returns_consistent_output(self):
        ip = factory.make_ipv4_address()
        macs = ["52:54:00:02:86:4b", "90:f6:52:f6:17:92"]
        entries = [{"dst": ip, "dev": "eth0", "lladdr": mac} for mac in macs]
        self.patch_call(json.dumps(entries))
        one_result = find_mac_via_arp(ip)
        self.patch_call(json.dumps(list(reversed(entries))))
        other_result = find_mac_via_arp(ip)
        assert one_result in macs
        assert one_result == other_result

    def test_skips_failed(self):
        ip = factory.make_ipv4_address()
        mac = factory.make_mac_address()
        entries = [
            {
                "dst": ip,
                "dev": "eth0",
                "state": ["FAILED"],
            },
            {
                "dst": ip,
                "dev": "eth0",
                "lladdr": mac,
                "state": ["REACHABLE"],
            },
        ]
        self.patch_call(json.dumps(entries))
        assert find_mac_via_arp(ip) == mac


def patch_interfaces(testcase, interfaces):
    """Patch `netifaces` to show the given `interfaces`.

    :param testcase: The testcase that's doing the patching.
    :param interfaces: A dict mapping interface names to `netifaces`
        interface entries: dicts with keys like `AF_INET` etc.
    """
    # These two netifaces functions map conveniently onto dict methods.
    testcase.mocker.patch.object(netifaces, "interfaces", new=interfaces.keys)
    testcase.mocker.patch.object(netifaces, "ifaddresses", new=interfaces.get)


class TestGetAllAddressesForInterface(TestNetworkBase):
    """Tests for `get_all_addresses_for_interface`."""

    @pytest.mark.parametrize(
        "inet_class,network_factory,ip_address_factory,loopback_address",
        [
            pytest.param(
                AF_INET,
                factory.make_ipv4_network,
                factory.make_ipv4_address,
                "127.0.0.1",
                id="ipv4",
            ),
            pytest.param(
                AF_INET6,
                factory.make_ipv6_network,
                factory.make_ipv6_address,
                "::1",
                id="ipv6",
            ),
        ],
    )
    def test_returns_address_for_inet_class(
        self, inet_class, network_factory, ip_address_factory, loopback_address
    ):
        ip = ip_address_factory()
        interface = factory.make_name("eth", sep="")
        patch_interfaces(self, {interface: {inet_class: [{"addr": str(ip)}]}})
        assert [ip] == list(get_all_addresses_for_interface(interface))

    @pytest.mark.parametrize(
        "inet_class,network_factory,ip_address_factory,loopback_address",
        [
            pytest.param(
                AF_INET,
                factory.make_ipv4_network,
                factory.make_ipv4_address,
                "127.0.0.1",
                id="ipv4",
            ),
            pytest.param(
                AF_INET6,
                factory.make_ipv6_network,
                factory.make_ipv6_address,
                "::1",
                id="ipv6",
            ),
        ],
    )
    def test_ignores_non_address_information(
        self, inet_class, network_factory, ip_address_factory, loopback_address
    ):
        network = network_factory()
        ip = factory.pick_ip_in_network(network)
        interface = factory.make_name("eth", sep="")
        patch_interfaces(
            self,
            {
                interface: {
                    inet_class: [
                        {
                            "addr": str(ip),
                            "broadcast": str(network.broadcast),
                            "netmask": str(network.netmask),
                            "peer": str(
                                factory.pick_ip_in_network(
                                    network, but_not=[ip]
                                )
                            ),
                        }
                    ]
                }
            },
        )
        assert [ip] == list(get_all_addresses_for_interface(interface))

    @pytest.mark.parametrize(
        "inet_class,network_factory,ip_address_factory,loopback_address",
        [
            pytest.param(
                AF_INET,
                factory.make_ipv4_network,
                factory.make_ipv4_address,
                "127.0.0.1",
                id="ipv4",
            ),
            pytest.param(
                AF_INET6,
                factory.make_ipv6_network,
                factory.make_ipv6_address,
                "::1",
                id="ipv6",
            ),
        ],
    )
    def test_ignores_link_address(
        self, inet_class, network_factory, ip_address_factory, loopback_address
    ):
        interface = factory.make_name("eth", sep="")
        patch_interfaces(
            self,
            {
                interface: {
                    AF_LINK: [
                        {
                            "addr": str(factory.make_mac_address()),
                            "peer": str(factory.make_mac_address()),
                        }
                    ]
                }
            },
        )
        assert [] == list(get_all_addresses_for_interface(interface))

    @pytest.mark.parametrize(
        "inet_class,network_factory,ip_address_factory,loopback_address",
        [
            pytest.param(
                AF_INET,
                factory.make_ipv4_network,
                factory.make_ipv4_address,
                "127.0.0.1",
                id="ipv4",
            ),
            pytest.param(
                AF_INET6,
                factory.make_ipv6_network,
                factory.make_ipv6_address,
                "::1",
                id="ipv6",
            ),
        ],
    )
    def test_ignores_interface_without_address(
        self, inet_class, network_factory, ip_address_factory, loopback_address
    ):
        network = network_factory()
        interface = factory.make_name("eth", sep="")
        patch_interfaces(
            self,
            {
                interface: {
                    inet_class: [
                        {
                            "broadcast": str(network.broadcast),
                            "netmask": str(network.netmask),
                        }
                    ]
                }
            },
        )
        assert [] == list(get_all_addresses_for_interface(interface))


class TestGetAllInterfaceAddresses(TestNetworkBase):
    """Tests for get_all_interface_addresses()."""

    def test_includes_loopback(self):
        v4_loopback_address = "127.0.0.1"
        v6_loopback_address = "::1"
        patch_interfaces(
            self,
            {
                "lo": {
                    AF_INET: [{"addr": v4_loopback_address}],
                    AF_INET6: [{"addr": v6_loopback_address}],
                }
            },
        )
        assert [v4_loopback_address, v6_loopback_address] == list(
            get_all_interface_addresses()
        )

    def test_returns_all_addresses_for_all_interfaces(self):
        v4_ips = [factory.make_ipv4_address() for _ in range(2)]
        v6_ips = [factory.make_ipv6_address() for _ in range(2)]
        ips = zip(v4_ips, v6_ips, strict=True)
        interfaces = {
            factory.make_name("eth", sep=""): {
                AF_INET: [{"addr": str(ipv4)}],
                AF_INET6: [{"addr": str(ipv6)}],
            }
            for ipv4, ipv6 in ips
        }
        patch_interfaces(self, interfaces)
        assert Counter(v4_ips + v6_ips) == Counter(
            get_all_interface_addresses()
        )


class TestGetAllInterfaceAddressesWithMultipleClasses(TestNetworkBase):
    """Tests for get_all_interface_addresses() with multiple inet classes."""

    def patch_interfaces(self, interfaces):
        """Patch `netifaces` to show the given `interfaces`.

        :param interfaces: A dict mapping interface names to `netifaces`
            interface entries: dicts with keys like `AF_INET` etc.
        """
        # These two netifaces functions map conveniently onto dict methods.
        self.patch(netifaces, "interfaces", interfaces.keys)
        self.patch(netifaces, "ifaddresses", interfaces.get)

    def test_returns_all_addresses_for_interface(self):
        v4_ip = factory.make_ipv4_address()
        v6_ip = factory.make_ipv6_address()
        interface = factory.make_name("eth", sep="")
        patch_interfaces(
            self,
            {
                interface: {
                    AF_INET: [{"addr": str(v4_ip)}],
                    AF_INET6: [{"addr": str(v6_ip)}],
                }
            },
        )
        assert [v4_ip, v6_ip] == list(get_all_interface_addresses())


class TestCleanUpNetifacesAddress(TestNetworkBase):
    """Tests for `clean_up_netifaces_address`."""

    def test_leaves_IPv4_intact(self):
        ip = str(factory.make_ipv4_address())
        interface = factory.make_name("eth")
        assert ip == clean_up_netifaces_address(ip, interface)

    def test_leaves_clean_IPv6_intact(self):
        ip = str(factory.make_ipv6_address())
        interface = factory.make_name("eth")
        assert ip == clean_up_netifaces_address(ip, interface)

    def test_removes_zone_index_suffix(self):
        ip = str(factory.make_ipv6_address())
        interface = factory.make_name("eth")
        assert ip == clean_up_netifaces_address(f"{ip}%{interface}", interface)


class TestResolveHostToAddrs(TestNetworkBase):
    """Tests for `resolve_hostname`."""

    def patch_getaddrinfo(self, *addrs):
        fake = self.patch(network_module, "getaddrinfo")
        fake.return_value = [
            (None, None, None, None, (str(address), 0)) for address in addrs
        ]
        return fake

    def patch_getaddrinfo_fail(self, exception):
        fake = self.patch(network_module, "getaddrinfo")
        fake.side_effect = exception
        return fake

    def test_rejects_weird_IP_version(self):
        with pytest.raises(AssertionError):
            resolve_hostname(factory.make_hostname(), ip_version=5)

    def test_integrates_with_getaddrinfo(self):
        result = resolve_hostname("localhost", 4)
        assert isinstance(result, set)
        [localhost] = result
        assert isinstance(localhost, IPAddress)
        assert localhost in IPNetwork("127.0.0.0/8")

    def test_resolves_IPv4_address(self):
        ip = factory.make_ipv4_address()
        fake = self.patch_getaddrinfo(ip)
        hostname = factory.make_hostname()
        result = resolve_hostname(hostname, 4)
        assert isinstance(result, set)
        assert {IPAddress(ip)} == result
        fake.assert_called_once_with(
            hostname, 0, family=AF_INET, proto=IPPROTO_TCP
        )

    def test_resolves_IPv6_address(self):
        ip = factory.make_ipv6_address()
        fake = self.patch_getaddrinfo(ip)
        hostname = factory.make_hostname()
        result = resolve_hostname(hostname, 6)
        assert isinstance(result, set)
        assert {IPAddress(ip)} == result
        fake.assert_called_once_with(
            hostname, 0, family=AF_INET6, proto=IPPROTO_TCP
        )

    def test_returns_empty_if_address_does_not_resolve(self):
        self.patch_getaddrinfo_fail(
            gaierror(EAI_NONAME, "Name or service not known")
        )
        assert set() == resolve_hostname(factory.make_hostname(), 4)

    def test_returns_empty_if_address_resolves_to_no_data(self):
        self.patch_getaddrinfo_fail(gaierror(EAI_NODATA, "No data returned"))
        assert set() == resolve_hostname(factory.make_hostname(), 4)

    def test_propagates_other_gaierrors(self):
        self.patch_getaddrinfo_fail(gaierror(EAI_BADFLAGS, "Bad parameters"))
        with pytest.raises(gaierror):
            resolve_hostname(factory.make_hostname(), 4)

    def test_propagates_unexpected_errors(self):
        self.patch_getaddrinfo_fail(KeyError("Huh what?"))
        with pytest.raises(KeyError):
            resolve_hostname(factory.make_hostname(), 4)

    def test_resolve_host_to_addrinfo_returns_full_information(self):
        ip = factory.make_ipv4_address()
        fake = self.patch_getaddrinfo(ip)
        hostname = factory.make_hostname()
        result = resolve_host_to_addrinfo(hostname, 4)
        assert isinstance(result, list)
        assert [(None, None, None, None, (ip, 0))] == result
        fake.assert_called_once_with(
            hostname, 0, family=AF_INET, proto=IPPROTO_TCP
        )


class TestIntersectIPRange(TestNetworkBase):
    """Tests for `intersect_iprange()`."""

    def test_finds_intersection_between_two_ranges(self):
        range_1 = IPRange("10.0.0.1", "10.0.0.255")
        range_2 = IPRange("10.0.0.128", "10.0.0.200")
        intersect = intersect_iprange(range_1, range_2)
        assert IPAddress(intersect.first) == IPAddress("10.0.0.128")
        assert IPAddress(intersect.last) == IPAddress("10.0.0.200")

    def test_ignores_non_intersecting_ranges(self):
        range_1 = IPRange("10.0.0.1", "10.0.0.255")
        range_2 = IPRange("10.0.1.128", "10.0.1.200")
        assert intersect_iprange(range_1, range_2) is None

    def test_finds_partial_intersection(self):
        range_1 = IPRange("10.0.0.1", "10.0.0.128")
        range_2 = IPRange("10.0.0.64", "10.0.0.200")
        intersect = intersect_iprange(range_1, range_2)
        assert IPAddress(intersect.first) == IPAddress("10.0.0.64")
        assert IPAddress(intersect.last) == IPAddress("10.0.0.128")


class TestIPRangeWithinNetwork(TestNetworkBase):
    def test_returns_true_when_ip_range_is_within_network(self):
        ip_range = IPRange("10.0.0.55", "10.0.255.55")
        ip_network = IPNetwork("10.0.0.0/16")
        assert ip_range_within_network(ip_range, ip_network)

    def test_returns_false_when_ip_range_is_within_network(self):
        ip_range = IPRange("192.0.0.55", "192.0.255.55")
        ip_network = IPNetwork("10.0.0.0/16")
        assert not (ip_range_within_network(ip_range, ip_network))

    def test_returns_false_when_ip_range_is_partially_within_network(self):
        ip_range = IPRange("10.0.0.55", "10.1.0.55")
        ip_network = IPNetwork("10.0.0.0/16")
        assert not (ip_range_within_network(ip_range, ip_network))

    def test_works_with_two_ip_networks(self):
        network_1 = IPNetwork("10.0.0.0/16")
        network_2 = IPNetwork("10.0.0.0/24")
        assert ip_range_within_network(network_2, network_1)


class TestMAASIPSet(TestNetworkBase):
    def test_contains_method(self):
        s = MAASIPSet(
            [
                make_iprange("10.0.0.1", "10.0.0.100"),
                make_iprange("10.0.0.200", "10.0.0.254"),
            ]
        )
        assert "10.0.0.1" in s
        assert IPAddress("10.0.0.1") in s
        assert IPRange("10.0.0.1", "10.0.0.100") in s
        assert IPRange("10.0.0.1", "10.0.0.101") not in s
        assert "10.0.0.101" not in s
        assert "10.0.0.199" not in s
        assert IPRange("10.0.0.200", "10.0.0.254") in s
        assert IPRange("10.0.0.99", "10.0.0.254") not in s
        assert "10.0.0.255" not in s

    def test_normalizes_range(self):
        addr1 = "10.0.0.1"
        addr2 = IPAddress("10.0.0.2")
        range1 = make_iprange("10.0.0.3", purpose="DNS")
        range2 = make_iprange("10.0.0.4", "10.0.0.100", purpose="DHCP")
        s = MAASIPSet([range2, range1, addr1, addr2])
        for item in s:
            assert type(item) is MAASIPRange
        assert "10.0.0.1" in s
        assert "10.0.0.2" in s
        assert "10.0.0.3" in s
        assert "10.0.0.4" in s
        assert "10.0.0.50" in s
        assert "10.0.0.100" in s
        assert "10.0.0.101" not in s
        assert "10.0.0.0" not in s

    def test_normalizes_ipv6_range(self):
        addr1 = "fe80::1"
        addr2 = IPAddress("fe80::2")
        range1 = make_iprange("fe80::3", purpose="DNS")
        range2 = make_iprange(
            "fe80::100", "fe80::ffff:ffff:ffff:ffff", purpose="DHCP"
        )
        s = MAASIPSet([range2, range1, addr1, addr2])
        for item in s:
            assert type(item) is MAASIPRange
        assert "fe80::1" in s
        assert "fe80::2" in s
        assert "fe80::3" in s
        assert "fe80::100" in s
        assert "fe80::ffff:ffff:ffff:ffff" in s
        assert "fe80::1:ffff:ffff:ffff:ffff" not in s

    def test_normalizes_range_with_iprange(self):
        addr1 = "10.0.0.1"
        addr2 = IPAddress("10.0.0.2")
        range1 = make_iprange("10.0.0.3", purpose="DNS")
        range2 = IPRange("10.0.0.4", "10.0.0.100")
        s = MAASIPSet([range2, range1, addr1, addr2])
        for item in s:
            assert type(item) is MAASIPRange
        assert "10.0.0.1" in s
        assert "10.0.0.2" in s
        assert "10.0.0.3" in s
        assert "10.0.0.4" in s
        assert "10.0.0.50" in s
        assert "10.0.0.100" in s
        assert "10.0.0.101" not in s
        assert "10.0.0.0" not in s

    def test_calculates_simple_unused_range(self):
        addr1 = "10.0.0.2"
        addr2 = IPAddress("10.0.0.3")
        range1 = make_iprange("10.0.0.4", purpose="DNS")
        range2 = IPRange("10.0.0.5", "10.0.0.100")
        s = MAASIPSet([range2, range1, addr1, addr2])
        u = s.get_unused_ranges_for_network(IPNetwork("10.0.0.0/24"))
        assert "10.0.0.0" not in u
        assert "10.0.0.1" in u
        assert "10.0.0.101" in u
        assert "10.0.0.150" in u
        assert "10.0.0.254" in u
        assert "10.0.0.255" not in u

    def test_calculates_simple_unused_range_with_iprange_input(self):
        addr1 = "10.0.0.1"
        addr2 = IPAddress("10.0.0.2")
        range1 = make_iprange("10.0.0.3", purpose="DNS")
        range2 = IPRange("10.0.0.4", "10.0.0.100")
        s = MAASIPSet([range2, range1, addr1, addr2])
        u = s.get_unused_ranges_for_range(
            [MAASIPRange("10.0.0.0", "10.0.0.255")]
        )
        assert "10.0.0.0" in u
        assert "10.0.0.101" in u
        assert "10.0.0.150" in u
        assert "10.0.0.254" in u
        assert "10.0.0.255" in u

    def test_calculates_unused_range_with_overlap(self):
        range1 = make_iprange("10.0.0.3", purpose="DNS")
        range2 = make_iprange("10.0.0.3", "10.0.0.20", purpose="DHCP")
        rangeset = MAASIPSet([range2, range1])
        u = rangeset.get_unused_ranges_for_network(IPNetwork("10.0.0.0/24"))
        assert "10.0.0.1" in u
        assert "10.0.0.2" in u
        assert "10.0.0.3" not in u
        assert "10.0.0.4" not in u
        assert "10.0.0.20" not in u
        assert "10.0.0.21" in u

    def test_calculates_unused_range_with_multiple_overlap(self):
        range1 = make_iprange("10.0.0.3", purpose="DNS")
        range2 = make_iprange("10.0.0.3", purpose="WINS")
        range3 = make_iprange("10.0.0.3", "10.0.0.20", purpose="DHCP")
        range4 = make_iprange("10.0.0.5", "10.0.0.20", purpose="DHCP")
        range5 = make_iprange("10.0.0.5", "10.0.0.18", purpose="DHCP")
        s = MAASIPSet([range1, range2, range3, range4, range5])
        u = s.get_unused_ranges_for_network(IPNetwork("10.0.0.0/24"))
        assert "10.0.0.0" not in u
        assert "10.0.0.1" in u
        assert "10.0.0.2" in u
        assert "10.0.0.3" not in u
        assert "10.0.0.4" not in u
        assert "10.0.0.5" not in u
        assert "10.0.0.6" not in u
        assert "10.0.0.10" not in u
        assert "10.0.0.18" not in u
        assert "10.0.0.19" not in u
        assert "10.0.0.20" not in u
        assert "10.0.0.21" in u
        assert "10.0.0.254" in u
        assert "10.0.0.255" not in u

    def test_deals_with_small_gaps(self):
        s = MAASIPSet(["10.0.0.2", "10.0.0.4", "10.0.0.6", "10.0.0.8"])
        u = s.get_unused_ranges_for_network(IPNetwork("10.0.0.0/24"))
        assert "10.0.0.0" not in u
        assert "10.0.0.1" in u
        assert "10.0.0.2" not in u
        assert "10.0.0.3" in u
        assert "10.0.0.4" not in u
        assert "10.0.0.5" in u
        assert "10.0.0.6" not in u
        assert "10.0.0.7" in u
        assert "10.0.0.8" not in u
        assert "10.0.0.9" in u
        assert "10.0.0.254" in u
        assert "10.0.0.255" not in u

    def test_calculates_ipv6_unused_range(self):
        addr1 = "fe80::1"
        addr2 = IPAddress("fe80::2")
        range1 = make_iprange("fe80::3", purpose="DNS")
        range2 = make_iprange(
            "fe80::100", "fe80::ffff:ffff:ffff:fffe", purpose="DHCP"
        )
        s = MAASIPSet([range2, range1, addr1, addr2])
        u = s.get_unused_ranges_for_network(IPNetwork("fe80::/64"))
        assert "fe80::1" not in u
        assert "fe80::2" not in u
        assert "fe80::3" not in u
        assert "fe80::100" not in u
        assert "fe80::ffff:ffff:ffff:fffe" not in u
        assert "fe80::ffff:ffff:ffff:ffff" in u
        assert "fe80::5" in u
        assert "fe80::50" in u
        assert "fe80::99" in u
        assert "fe80::ff" in u

    def test_calculates_ipv6_unused_range_for_huge_range(self):
        addr1 = "fe80::1"
        addr2 = IPAddress("fe80::2")
        range1 = make_iprange("fe80::3", purpose="DNS")
        range2 = make_iprange(
            "fe80::100", "fe80::ffff:ffff:ffff:fffe", purpose="DHCP"
        )
        s = MAASIPSet([range2, range1, addr1, addr2])
        u = s.get_unused_ranges_for_network(IPNetwork("fe80::/32"))
        assert "fe80::1" not in u
        assert "fe80::2" not in u
        assert "fe80::3" not in u
        assert "fe80::100" not in u
        assert "fe80::ffff:ffff:ffff:fffe" not in u
        assert "fe80::ffff:ffff:ffff:ffff" in u
        assert "fe80::5" in u
        assert "fe80::50" in u
        assert "fe80::99" in u
        assert "fe80::ff" in u
        assert "fe80:0:ffff:ffff:ffff:ffff:ffff:ffff" in u

    def test_calculates_full_range(self):
        s = MAASIPSet(["10.0.0.2", "10.0.0.4", "10.0.0.6", "10.0.0.8"])
        u = s.get_full_range(IPNetwork("10.0.0.0/24"))
        for ip in range(1, 254):
            assert "10.0.0.%d" % ip in u
        assert "unused" in u["10.0.0.1"].purpose
        assert "unused" not in u["10.0.0.2"].purpose
        assert "unused" in u["10.0.0.254"].purpose

    def test_calculates_full_range_for_small_ipv6(self):
        s = MAASIPSet([])
        u = s.get_full_range(IPNetwork("2001:db8::/127"))
        assert "unused" in u["2001:db8::"].purpose
        assert "unused" in u["2001:db8::1"].purpose

    def test_supports_ior(self):
        s1 = MAASIPSet(["10.0.0.2", "10.0.0.4", "10.0.0.6", "10.0.0.8"])
        s2 = MAASIPSet(["10.0.0.1", "10.0.0.3", "10.0.0.5", "10.0.0.7"])
        s1 |= s2
        for ip in IPRange("10.0.0.1", "10.0.0.8"):
            assert ip in s1

    def test_ior_coalesces_adjacent_ranges(self):
        s1 = MAASIPSet(["10.0.0.2", "10.0.0.4", "10.0.0.6", "10.0.0.8"])
        s2 = MAASIPSet(["10.0.0.1", "10.0.0.3", "10.0.0.5", "10.0.0.7"])
        s1 |= s2
        # Since all these IP addresses are adjacent (and have the same
        # purpose), we should present them as a single entity. That is,
        # it will appear to the user as "10.0.0.1 through 10.0.0.8".
        assert len(s1.ranges) == 1
        assert "10.0.0.1" == str(IPAddress(s1.first))
        assert "10.0.0.8" == str(IPAddress(s1.last))

    def test_ior_doesnt_combine_adjacent_ranges_with_different_purposes(self):
        s1 = MAASIPSet(
            [
                make_iprange("10.0.0.2", purpose="foo"),
                make_iprange("10.0.0.4", purpose="foo"),
                make_iprange("10.0.0.6", purpose="foo"),
                make_iprange("10.0.0.8", purpose="foo"),
            ]
        )
        s2 = MAASIPSet(
            [
                make_iprange("10.0.0.1", purpose="bar"),
                make_iprange("10.0.0.3", purpose="bar"),
                make_iprange("10.0.0.5", purpose="bar"),
                make_iprange("10.0.0.7", purpose="bar"),
            ]
        )
        s1 |= s2
        # Expect the individual addresses to be preserved in unique ranges,
        # since adjacent addresses have different purposes and thus will not
        # be combined.
        assert len(s1.ranges) == 8
        assert "10.0.0.1" == str(IPAddress(s1.first))
        assert "10.0.0.8" == str(IPAddress(s1.last))


class TestIPRangeStatistics(TestNetworkBase):
    def test_statistics_are_accurate(self):
        s = MAASIPSet(["10.0.0.2", "10.0.0.4", "10.0.0.6", "10.0.0.8"])
        u = s.get_full_range(IPNetwork("10.0.0.0/24"))
        stats = IPRangeStatistics(u)
        json = stats.render_json()
        assert 250 == json["num_available"]
        assert 246 == json["largest_available"]
        assert 4 == json["num_unavailable"]
        assert float(4) / float(254) == json["usage"]
        assert "2%" == json["usage_string"]
        assert "98%" == json["available_string"]
        assert "ranges" not in json

    def test_statistics_are_accurate_and_ranges_are_returned_if_desired(self):
        s = MAASIPSet(["10.0.0.2", "10.0.0.4", "10.0.0.6", "10.0.0.8"])
        u = s.get_full_range(IPNetwork("10.0.0.0/24"))
        stats = IPRangeStatistics(u)
        json = stats.render_json(include_ranges=True)
        assert 250 == json["num_available"]
        assert 246 == json["largest_available"]
        assert 4 == json["num_unavailable"]
        assert float(4) / float(254) == json["usage"]
        assert "2%" == json["usage_string"]
        assert "98%" == json["available_string"]
        assert "ranges" in json
        assert stats.ranges.render_json() == json["ranges"]

    def test_statistics_are_accurate_for_full_slash_32(self):
        s = MAASIPSet(["10.0.0.1"])
        u = s.get_full_range(IPNetwork("10.0.0.1/32"))
        stats = IPRangeStatistics(u)
        json = stats.render_json()
        assert 0 == json["num_available"]
        assert 0 == json["largest_available"]
        assert 1 == json["num_unavailable"]
        assert float(1) / float(1) == json["usage"]
        assert "100%" == json["usage_string"]
        assert "0%" == json["available_string"]
        assert "ranges" not in json

    def test_statistics_are_accurate_for_empty_slash_32(self):
        s = MAASIPSet([])
        u = s.get_full_range(IPNetwork("10.0.0.1/32"))
        stats = IPRangeStatistics(u)
        json = stats.render_json()
        assert 1 == json["num_available"]
        assert 1 == json["largest_available"]
        assert 0 == json["num_unavailable"]
        assert float(0) / float(1) == json["usage"]
        assert "0%" == json["usage_string"]
        assert "100%" == json["available_string"]
        assert "ranges" not in json

    def test_statistics_are_accurate_for_full_slash_128(self):
        s = MAASIPSet(["2001:db8::1"])
        u = s.get_full_range(IPNetwork("2001:db8::1/128"))
        stats = IPRangeStatistics(u)
        json = stats.render_json()
        assert 0 == json["num_available"]
        assert 0 == json["largest_available"]
        assert 1 == json["num_unavailable"]
        assert float(1) / float(1) == json["usage"]
        assert "100%" == json["usage_string"]
        assert "0%" == json["available_string"]
        assert "ranges" not in json

    def test_statistics_are_accurate_for_empty_slash_128(self):
        s = MAASIPSet([])
        u = s.get_full_range(IPNetwork("2001:db8::1/128"))
        stats = IPRangeStatistics(u)
        json = stats.render_json()
        assert 1 == json["num_available"]
        assert 1 == json["largest_available"]
        assert 0 == json["num_unavailable"]
        assert float(0) / float(1) == json["usage"]
        assert "0%" == json["usage_string"]
        assert "100%" == json["available_string"]
        assert "ranges" not in json

    def test_statistics_are_accurate_for_empty_slash_127(self):
        s = MAASIPSet([])
        u = s.get_full_range(IPNetwork("2001:db8::1/127"))
        stats = IPRangeStatistics(u)
        json = stats.render_json()
        assert 2 == json["num_available"]
        assert 2 == json["largest_available"]
        assert 0 == json["num_unavailable"]
        assert float(0) / float(2) == json["usage"]
        assert "0%" == json["usage_string"]
        assert "100%" == json["available_string"]
        assert "ranges" not in json

    def test_statistics_are_accurate_for_empty_slash_31(self):
        s = MAASIPSet([])
        u = s.get_full_range(IPNetwork("10.0.0.0/31"))
        stats = IPRangeStatistics(u)
        json = stats.render_json()
        assert 2 == json["num_available"]
        assert 2 == json["largest_available"]
        assert 0 == json["num_unavailable"]
        assert float(0) / float(2) == json["usage"]
        assert "0%" == json["usage_string"]
        assert "100%" == json["available_string"]
        assert "ranges" not in json

    def test_suggests_subnet_anycast_address_for_ipv6(self):
        s = MAASIPSet([])
        u = s.get_full_range(IPNetwork("2001:db8::/64"))
        stats = IPRangeStatistics(u)
        assert "2001:db8::" == stats.suggested_gateway

    def test_suggests_first_ip_as_default_gateway_if_available(self):
        s = MAASIPSet(["10.0.0.2", "10.0.0.4", "10.0.0.6", "10.0.0.8"])
        u = s.get_full_range(IPNetwork("10.0.0.0/24"))
        stats = IPRangeStatistics(u)
        assert "10.0.0.1" == stats.suggested_gateway

    def test_suggests_last_ip_as_default_gateway_if_needed(self):
        s = MAASIPSet(["10.0.0.1", "10.0.0.4", "10.0.0.6", "10.0.0.8"])
        u = s.get_full_range(IPNetwork("10.0.0.0/24"))
        stats = IPRangeStatistics(u)
        assert "10.0.0.254" == stats.suggested_gateway

    def test_suggests_first_available_ip_as_default_gateway_if_needed(self):
        s = MAASIPSet(["10.0.0.1", "10.0.0.4", "10.0.0.6", "10.0.0.254"])
        u = s.get_full_range(IPNetwork("10.0.0.0/24"))
        stats = IPRangeStatistics(u)
        assert "10.0.0.2" == stats.suggested_gateway

    def test_suggests_no_gateway_if_range_full(self):
        s = MAASIPSet(["10.0.0.1"])
        u = s.get_full_range(IPNetwork("10.0.0.1/32"))
        stats = IPRangeStatistics(u)
        assert stats.suggested_gateway is None

    def test_suggests_no_dynamic_range_if_dynamic_range_exists(self):
        s = MAASIPSet(
            [MAASIPRange(start="10.0.0.2", end="10.0.0.99", purpose="dynamic")]
        )
        u = s.get_full_range(IPNetwork("10.0.0.0/24"))
        stats = IPRangeStatistics(u)
        json = stats.render_json(include_suggestions=True)
        assert stats.suggested_dynamic_range is None
        assert json["suggested_dynamic_range"] is None

    def test_suggests_upper_one_fourth_range_for_dynamic_by_default(self):
        s = MAASIPSet([])
        u = s.get_full_range(IPNetwork("10.0.0.0/24"))
        stats = IPRangeStatistics(u)
        assert "10.0.0.1" == stats.suggested_gateway
        assert len(stats.suggested_dynamic_range) == 64
        assert "10.0.0.191" in stats.suggested_dynamic_range
        assert "10.0.0.254" in stats.suggested_dynamic_range
        assert "10.0.0.255" not in stats.suggested_dynamic_range
        assert "10.0.0.190" not in stats.suggested_dynamic_range

    def test_suggests_half_available_if_available_less_than_one_fourth(self):
        s = MAASIPSet([MAASIPRange("10.0.0.2", "10.0.0.205")])
        u = s.get_full_range(IPNetwork("10.0.0.0/24"))
        stats = IPRangeStatistics(u)
        assert "10.0.0.1" == stats.suggested_gateway
        assert 50 == stats.num_available
        assert len(stats.suggested_dynamic_range) == 25
        assert "10.0.0.230" in stats.suggested_dynamic_range
        assert "10.0.0.254" in stats.suggested_dynamic_range
        assert "10.0.0.255" not in stats.suggested_dynamic_range
        assert "10.0.0.229" not in stats.suggested_dynamic_range

    def test_suggested_range_excludes_suggested_gateway(self):
        s = MAASIPSet([MAASIPRange("10.0.0.1", "10.0.0.204")])
        u = s.get_full_range(IPNetwork("10.0.0.0/24"))
        stats = IPRangeStatistics(u)
        assert "10.0.0.254" == stats.suggested_gateway
        assert 50 == stats.num_available
        assert len(stats.suggested_dynamic_range) == 25
        assert "10.0.0.229" in stats.suggested_dynamic_range
        assert "10.0.0.253" in stats.suggested_dynamic_range
        assert "10.0.0.255" not in stats.suggested_dynamic_range
        assert "10.0.0.228" not in stats.suggested_dynamic_range

    def test_suggested_range_excludes_suggested_gateway_when_gw_first(self):
        s = MAASIPSet([MAASIPRange("10.0.0.1", "10.0.0.203"), "10.0.0.254"])
        u = s.get_full_range(IPNetwork("10.0.0.0/24"))
        stats = IPRangeStatistics(u)
        assert "10.0.0.204" == stats.suggested_gateway
        assert 50 == stats.num_available
        assert len(stats.suggested_dynamic_range) == 25
        assert "10.0.0.229" in stats.suggested_dynamic_range
        assert "10.0.0.253" in stats.suggested_dynamic_range
        assert "10.0.0.255" not in stats.suggested_dynamic_range
        assert "10.0.0.228" not in stats.suggested_dynamic_range

    def test_suggests_upper_one_fourth_range_for_ipv6(self):
        s = MAASIPSet([])
        u = s.get_full_range(IPNetwork("2001:db8::/64"))
        stats = IPRangeStatistics(u)
        assert "2001:db8::" == stats.suggested_gateway
        assert (2**64) >> 2 == stats.suggested_dynamic_range.size
        assert "2001:db8:0:0:c000::" in stats.suggested_dynamic_range
        assert "2001:db8::ffff:ffff:ffff:ffff" in stats.suggested_dynamic_range
        assert "2001:db8::1" not in stats.suggested_dynamic_range
        assert (
            "2001:db8::bfff:ffff:ffff:ffff"
            not in stats.suggested_dynamic_range
        )

    def test_no_suggestion_for_small_ipv6_slash_126(self):
        s = MAASIPSet([])
        u = s.get_full_range(IPNetwork("2001:db8::/126"))
        stats = IPRangeStatistics(u)
        assert "2001:db8::" == stats.suggested_gateway
        assert stats.suggested_dynamic_range is None

    def test_no_suggestion_for_small_ipv6_slash_127(self):
        s = MAASIPSet([])
        u = s.get_full_range(IPNetwork("2001:db8::/127"))
        stats = IPRangeStatistics(u)
        assert stats.suggested_gateway is None

    def test_no_suggestion_and_no_gateway_for_small_ipv6_slash_128(self):
        s = MAASIPSet([])
        u = s.get_full_range(IPNetwork("2001:db8::/128"))
        stats = IPRangeStatistics(u)
        assert stats.suggested_gateway is None

    def test_suggests_half_available_for_ipv6(self):
        s = MAASIPSet(
            [MAASIPRange("2001:db8::1", "2001:db8::ffff:ffff:ffff:ff00")]
        )
        u = s.get_full_range(IPNetwork("2001:db8::/64"))
        stats = IPRangeStatistics(u)
        assert "2001:db8::" == stats.suggested_gateway
        assert 255 == stats.num_available
        assert len(stats.suggested_dynamic_range) == 127
        assert "2001:db8::ffff:ffff:ffff:ff81" in stats.suggested_dynamic_range
        assert "2001:db8::ffff:ffff:ffff:ffff" in stats.suggested_dynamic_range
        assert "2001:db8::1" not in stats.suggested_dynamic_range
        assert (
            "2001:db8::ffff:ffff:ffff:ff80"
            not in stats.suggested_dynamic_range
        )


class TestParseInteger(TestNetworkBase):
    def test_parses_decimal_integer(self):
        assert 0 == parse_integer("0")
        assert 1 == parse_integer("1")
        assert -1 == parse_integer("-1")
        assert 1000 == parse_integer("1000")
        assert 10000000 == parse_integer("10000000")

    def test_parses_hexadecimal_integer(self):
        assert 0 == parse_integer("0x0")
        assert 1 == parse_integer("0x1")
        assert 0x1000 == parse_integer("0x1000")
        assert 0x10000000 == parse_integer("0x10000000")

    def test_parses_binary_integer(self):
        assert 0 == parse_integer("0b0")
        assert 1 == parse_integer("0b1")
        assert 0b1000 == parse_integer("0b1000")
        assert 0b10000000 == parse_integer("0b10000000")


class TestGetAllInterfacesDefinition(TestNetworkBase):
    """Tests for `get_all_interfaces_definition` and all helper methods."""

    def test_ignores_loopback(self):
        ip_addr = {
            "vnet": {
                "type": "loopback",
                "enabled": True,
                "addresses": ["127.0.0.1/32", ["::1"]],
                "parents": [],
                "mac": [],
            }
        }
        assert {} == get_interfaces_result(self.mocker, ip_addr, {}, {})

    def test_ignores_ethernet(self):
        ip_addr = {
            "vnet": {
                "type": "ethernet",
                "mac": factory.make_mac_address(),
                "enabled": True,
                "addresses": ["192.168.122.2/24"],
                "parents": [],
            }
        }
        assert {} == get_interfaces_result(self.mocker, ip_addr, {}, {})

    def test_ignores_ipip(self):
        ip_addr = {
            "vnet": {
                "type": "ipip",
                "enabled": True,
                "mac": factory.make_mac_address(),
            }
        }
        assert {} == get_interfaces_result(self.mocker, ip_addr, {}, {})

    def test_ignores_tunnel(self):
        ip_addr = {
            "vnet": {
                "type": "tunnel",
                "enabled": True,
                "mac": factory.make_mac_address(),
            }
        }
        assert {} == get_interfaces_result(self.mocker, ip_addr, {}, {})

    def test_simple(self):
        ip_addr = {
            "eth0": {
                "type": "physical",
                "mac": factory.make_mac_address(),
                "enabled": True,
                "addresses": ["192.168.122.2/24"],
                "parents": [],
            }
        }
        expected_result = {
            "eth0": {
                "type": "physical",
                "mac_address": ip_addr["eth0"]["mac"],
                "enabled": True,
                "parents": [],
                "links": [{"mode": "static", "address": "192.168.122.2/24"}],
                "source": "machine-resources",
            }
        }
        assert expected_result == get_interfaces_result(
            self.mocker, ip_addr, {}, {}
        )

    def test_simple_with_default_gateway(self):
        ip_addr = {
            "eth0": {
                "type": "ethernet.physical",
                "mac": factory.make_mac_address(),
                "enabled": True,
                "addresses": ["192.168.122.2/24"],
                "parents": [],
            }
        }
        iproute_info = {"default": {"gateway": "192.168.122.1"}}
        expected_result = {
            "eth0": {
                "type": "physical",
                "mac_address": ip_addr["eth0"]["mac"],
                "enabled": True,
                "parents": [],
                "links": [
                    {
                        "mode": "static",
                        "address": "192.168.122.2/24",
                        "gateway": "192.168.122.1",
                    }
                ],
                "source": "machine-resources",
            }
        }
        assert expected_result == get_interfaces_result(
            self.mocker, ip_addr, iproute_info, {}
        )

    def test_doesnt_ignore_ethernet_in_container(self):
        ip_addr = {
            "eth0": {
                "type": "ethernet",
                "mac": factory.make_mac_address(),
                "enabled": True,
                "addresses": ["192.168.122.2/24"],
                "parents": [],
            }
        }
        expected_result = {
            "eth0": {
                "type": "physical",
                "mac_address": ip_addr["eth0"]["mac"],
                "enabled": True,
                "parents": [],
                "links": [{"mode": "static", "address": "192.168.122.2/24"}],
                "source": "machine-resources",
            }
        }

        assert expected_result == get_interfaces_result(
            self.mocker, ip_addr, {}, {}, in_container=True
        )

    def test_simple_with_dhcp(self):
        ip_addr = {
            "eth0": {
                "type": "physical",
                "mac": factory.make_mac_address(),
                "enabled": True,
                "addresses": ["192.168.122.2/24", "192.168.122.200/32"],
                "parents": [],
            }
        }
        dhclient_info = {"eth0": "192.168.122.2"}
        expected_result = {
            "eth0": {
                "type": "physical",
                "mac_address": ip_addr["eth0"]["mac"],
                "enabled": True,
                "parents": [],
                "links": [
                    {"mode": "dhcp", "address": "192.168.122.2/24"},
                    {"mode": "static", "address": "192.168.122.200/24"},
                ],
                "source": "machine-resources",
            }
        }
        assert expected_result == get_interfaces_result(
            self.mocker, ip_addr, {}, dhclient_info
        )

    def test_fixing_links(self):
        ip_addr = {
            "eth0": {
                "type": "physical",
                "mac": factory.make_mac_address(),
                "enabled": True,
                "addresses": [
                    "192.168.122.2/24",
                    "192.168.122.3/32",
                    "192.168.123.3/32",
                    "2001:db8:a0b:12f0::1/96",
                    "2001:db8:a0b:12f0::2/128",
                ],
                "parents": [],
            }
        }
        expected_result = {
            "eth0": {
                "type": "physical",
                "mac_address": ip_addr["eth0"]["mac"],
                "enabled": True,
                "parents": [],
                "links": [
                    {"mode": "static", "address": "192.168.122.2/24"},
                    {"mode": "static", "address": "192.168.122.3/24"},
                    {"mode": "static", "address": "192.168.123.3/32"},
                    {"mode": "static", "address": "2001:db8:a0b:12f0::1/96"},
                    {"mode": "static", "address": "2001:db8:a0b:12f0::2/96"},
                ],
                "source": "machine-resources",
            }
        }
        assert expected_result == get_interfaces_result(
            self.mocker, ip_addr, {}, {}
        )

    def test_complex(self):
        ip_addr = {
            "eth0": {
                "type": "physical",
                "mac": factory.make_mac_address(),
                "enabled": False,
                "parents": [],
                "addresses": [],
            },
            "eth1": {
                "type": "physical",
                "mac": factory.make_mac_address(),
                "enabled": True,
                "parents": [],
                "addresses": [],
            },
            "eth2": {
                "type": "physical",
                "mac": factory.make_mac_address(),
                "enabled": True,
                "parents": [],
                "addresses": [],
            },
            "bond0": {
                "type": "bond",
                "mac": factory.make_mac_address(),
                "enabled": True,
                "parents": ["eth1", "eth2"],
                "addresses": [
                    "192.168.122.2/24",
                    "192.168.122.3/32",
                    "2001:db8::3:2:2/96",
                ],
            },
            "bond0.10": {
                "type": "vlan",
                "mac": factory.make_mac_address(),
                "enabled": True,
                "vid": 10,
                "parents": ["bond0"],
                "addresses": ["192.168.123.2/24", "192.168.123.3/32"],
            },
            "vlan20": {
                "type": "vlan",
                "mac": factory.make_mac_address(),
                "enabled": True,
                "vid": 20,
                "parents": ["eth0"],
                "addresses": [],
            },
            "wlan0": {
                "type": "wireless",
                "mac": factory.make_mac_address(),
                "enabled": True,
                "parents": [],
                "addresses": [],
            },
            "br0": {
                "type": "bridge",
                "mac": factory.make_mac_address(),
                "enabled": True,
                "parents": ["eth0"],
                "addresses": ["192.168.124.2/24"],
            },
            "gretap": {
                "type": "gretap",
                "mac": "",
                "enabled": True,
                "parents": [],
                "addresses": [],
            },
        }
        iproute_info = {
            "default": {"gateway": "192.168.122.1"},
            "192.168.124.0/24": {"gateway": "192.168.124.1"},
        }
        expected_result = {
            "eth0": {
                "type": "physical",
                "mac_address": ip_addr["eth0"]["mac"],
                "enabled": False,
                "parents": [],
                "links": [],
                "source": "machine-resources",
            },
            "eth1": {
                "type": "physical",
                "mac_address": ip_addr["eth1"]["mac"],
                "enabled": True,
                "parents": [],
                "links": [],
                "source": "machine-resources",
            },
            "eth2": {
                "type": "physical",
                "mac_address": ip_addr["eth2"]["mac"],
                "enabled": True,
                "parents": [],
                "links": [],
                "source": "machine-resources",
            },
            "bond0": {
                "type": "bond",
                "mac_address": ip_addr["bond0"]["mac"],
                "enabled": True,
                "parents": ["eth1", "eth2"],
                "links": [
                    {
                        "mode": "static",
                        "address": "192.168.122.2/24",
                        "gateway": "192.168.122.1",
                    },
                    {
                        "mode": "static",
                        "address": "192.168.122.3/24",
                        "gateway": "192.168.122.1",
                    },
                    {"mode": "static", "address": "2001:db8::3:2:2/96"},
                ],
                "source": "machine-resources",
            },
            "bond0.10": {
                "type": "vlan",
                "mac_address": ip_addr["bond0.10"]["mac"],
                "enabled": True,
                "vid": 10,
                "parents": ["bond0"],
                "links": [
                    {
                        "mode": "static",
                        "address": "192.168.123.2/24",
                    },
                    {
                        "mode": "static",
                        "address": "192.168.123.3/24",
                    },
                ],
                "source": "machine-resources",
            },
            "vlan20": {
                "type": "vlan",
                "mac_address": ip_addr["vlan20"]["mac"],
                "enabled": True,
                "vid": 20,
                "parents": ["eth0"],
                "links": [],
                "source": "machine-resources",
            },
            "wlan0": {
                "type": "physical",
                "mac_address": ip_addr["wlan0"]["mac"],
                "enabled": True,
                "parents": [],
                "links": [],
                "source": "machine-resources",
            },
            "br0": {
                "type": "bridge",
                "mac_address": ip_addr["br0"]["mac"],
                "enabled": True,
                "parents": ["eth0"],
                "links": [
                    {
                        "mode": "static",
                        "address": "192.168.124.2/24",
                        "gateway": "192.168.124.1",
                    },
                ],
                "source": "machine-resources",
            },
        }
        assert expected_result == get_interfaces_result(
            self.mocker, ip_addr, iproute_info, {}
        )


class TestGetAllInterfacesSubnets(TestNetworkBase):
    """Tests for `get_all_interface_subnets()`."""

    def test_includes_unique_subnets(self):
        interface_definition = {
            "eth0": {
                "links": [
                    {"address": "192.168.122.1/24"},
                    {"address": "192.168.122.3/24"},
                ]
            },
            "eth1": {
                "links": [
                    {"address": "192.168.123.1/24"},
                    {"address": "192.168.123.2/24"},
                ]
            },
        }
        self.patch(
            network_module, "get_all_interfaces_definition"
        ).return_value = interface_definition
        assert {
            IPNetwork("192.168.122.1/24"),
            IPNetwork("192.168.123.1/24"),
        } == get_all_interface_subnets()


class TestGetAllInterfacesSourceAddresses(TestNetworkBase):
    """Tests for `get_all_interface_source_addresses()`."""

    def test_includes_unique_subnets(self):
        interface_subnets = {
            IPNetwork("192.168.122.1/24"),
            IPNetwork("192.168.123.1/24"),
        }
        self.patch(
            network_module, "get_all_interface_subnets"
        ).return_value = interface_subnets
        self.patch(network_module, "get_source_address").side_effect = [
            "192.168.122.1",
            None,
        ]
        assert {"192.168.122.1"} == get_all_interface_source_addresses()


class InterfaceLinksMixin(TestNetworkBase):
    """Test case for `TestHasIPv4Address` and `TestEnumerateAddresses`."""

    def make_interface(self, addresses=None):
        links = []
        if addresses is not None:
            for address in addresses:
                links.append({"address": address, "mode": "static"})
        return {
            "enabled": True,
            "links": links,
            "mac_address": "52:54:00:e7:d9:2c",
            "monitored": True,
            "parents": [],
            "source": "machine-resources",
            "type": "physical",
        }


class TestHasIPv4Address(InterfaceLinksMixin):
    """Tests for `has_ipv4_address()`."""

    def test_returns_false_for_no_ip_address(self):
        assert not (has_ipv4_address(self.make_interface()))

    def test_returns_false_for_ipv6_address(self):
        address = "%s/64" % factory.make_ipv6_address()
        assert not (has_ipv4_address(self.make_interface(addresses=[address])))

    def test_returns_true_for_ipv4_address(self):
        address = "%s/24" % factory.make_ipv4_address()
        assert self.make_interface(addresses=[address])


class TestGetIfnameIfdataForDestination(TestNetworkBase):
    """Tests for `get_ifname_ifdata_for_destination()`."""

    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        self.interfaces = {
            "eth0": {"links": [{"address": "192.168.0.1/24"}]},
            "eth1": {
                "links": [
                    {"address": "2001:db8::1/64"},
                    {"address": "172.16.0.1/24"},
                ]
            },
        }
        self.get_source_address_mock = mocker.patch.object(
            network_module, "get_source_address"
        )

    def test_returns_interface_for_expected_source_ip(self):
        self.get_source_address_mock.return_value = "2001:db8::1"
        ifname, ifdata = get_ifname_ifdata_for_destination(
            "2001:db8::2", self.interfaces
        )
        assert "eth1" == ifname
        assert self.interfaces["eth1"] == ifdata
        self.get_source_address_mock.return_value = "192.168.0.1"
        ifname, ifdata = get_ifname_ifdata_for_destination(
            "192.168.0.2", self.interfaces
        )
        assert "eth0" == ifname
        assert self.interfaces["eth0"] == ifdata
        self.get_source_address_mock.return_value = "172.16.0.1"
        ifname, ifdata = get_ifname_ifdata_for_destination(
            "172.16.0.2", self.interfaces
        )
        assert "eth1" == ifname
        assert self.interfaces["eth1"] == ifdata

    def test_handles_loopback_addresses(self):
        self.get_source_address_mock.return_value = "127.0.0.1"
        ifname, ifdata = get_ifname_ifdata_for_destination(
            "127.0.0.1", self.interfaces
        )
        assert "lo" == ifname
        assert LOOPBACK_INTERFACE_INFO == ifdata
        self.get_source_address_mock.return_value = "::1"
        ifname, ifdata = get_ifname_ifdata_for_destination(
            "::1", self.interfaces
        )
        assert "lo" == ifname
        assert LOOPBACK_INTERFACE_INFO == ifdata

    def test_raises_valueerror_if_no_route_to_host(self):
        self.get_source_address_mock.return_value = None
        with pytest.raises(ValueError):
            get_ifname_ifdata_for_destination("2001:db8::2", self.interfaces)

    def test_raises_valueerror_if_source_ip_not_found(self):
        self.get_source_address_mock.return_value = "192.168.0.2"
        with pytest.raises(ValueError):
            get_ifname_ifdata_for_destination("192.168.0.3", self.interfaces)


class TestEnumerateAddresses(InterfaceLinksMixin):
    """Tests for `enumerate_assigned_ips` and `enumerate_ipv4_addresses()`."""

    def test_returns_appropriate_assigned_ip_addresses(self):
        ipv6_address = factory.make_ipv6_address()
        ipv4_address = factory.make_ipv4_address()
        interface = self.make_interface(
            addresses=[ipv6_address + "/64", ipv4_address + "/24"]
        )
        ip_addresses = list(enumerate_assigned_ips(interface))
        ipv4_addresses = list(enumerate_ipv4_addresses(interface))
        assert [ipv6_address, ipv4_address] == ip_addresses
        assert [ipv4_address] == ipv4_addresses


class TestGetInterfaceChildren(TestNetworkBase):
    """Tests for `get_interface_children()`."""

    def test_calculates_children_from_bond_parents(self):
        interfaces = {
            "eth0": {"parents": []},
            "eth1": {"parents": []},
            "bond0": {"parents": ["eth0", "eth1"]},
        }
        children_map = get_interface_children(interfaces)
        assert {"eth0": {"bond0"}, "eth1": {"bond0"}} == children_map

    def test_calculates_children_from_vlan_parents(self):
        interfaces = {
            "eth0": {"parents": []},
            "eth1": {"parents": []},
            "eth0.100": {"parents": ["eth0"]},
            "eth1.100": {"parents": ["eth1"]},
        }
        children_map = get_interface_children(interfaces)
        assert {"eth0": {"eth0.100"}, "eth1": {"eth1.100"}} == children_map

    def test_calculates_children_from_bond_and_vlan_parents(self):
        interfaces = {
            "eth0": {"parents": []},
            "eth1": {"parents": []},
            "eth0.100": {"parents": ["eth0"]},
            "eth1.100": {"parents": ["eth1"]},
            "bond0": {"parents": ["eth0", "eth1"]},
        }
        children_map = get_interface_children(interfaces)
        assert children_map == {
            "eth0": {"eth0.100", "bond0"},
            "eth1": {"eth1.100", "bond0"},
        }


class TestInterfaceChildren(TestNetworkBase):
    """Tests for `interface_children()`."""

    def test_yields_each_child(self):
        interfaces = {
            "eth0": {"parents": []},
            "eth1": {"parents": []},
            "eth0.100": {"parents": ["eth0"]},
            "eth1.100": {"parents": ["eth1"]},
            "bond0": {"parents": ["eth0", "eth1"]},
        }
        children_map = get_interface_children(interfaces)
        eth0_children = list(
            interface_children("eth0", interfaces, children_map)
        )
        assert {child.name: child.data for child in eth0_children} == {
            "eth0.100": {"parents": ["eth0"]},
            "bond0": {"parents": ["eth0", "eth1"]},
        }
        eth1_children = list(
            interface_children("eth1", interfaces, children_map)
        )
        assert {child.name: child.data for child in eth1_children} == {
            "eth1.100": {"parents": ["eth1"]},
            "bond0": {"parents": ["eth0", "eth1"]},
        }

    def test_returns_namedtuple(self):
        interfaces = {
            "eth0": {"parents": []},
            "eth0.100": {"parents": ["eth0"]},
        }
        children_map = get_interface_children(interfaces)
        eth0_children = list(
            interface_children("eth0", interfaces, children_map)
        )
        assert "eth0.100" == eth0_children[0].name
        assert {"parents": ["eth0"]} == eth0_children[0].data


class TestGetDefaultMonitoredInterfaces(TestNetworkBase):
    """Tests for `get_default_monitored_interfaces()`."""

    def test_returns_enabled_physical_interfaces(self):
        interfaces = {
            "eth0": {"parents": [], "type": "physical", "enabled": False},
            "eth1": {"parents": [], "type": "physical", "enabled": True},
        }
        assert get_default_monitored_interfaces(interfaces) == ["eth1"]

    def test_returns_enabled_bond_interfaces_instead_of_physical(self):
        interfaces = {
            "eth0": {"parents": [], "type": "physical", "enabled": True},
            "eth1": {"parents": [], "type": "physical", "enabled": True},
            "eth2": {"parents": [], "type": "physical", "enabled": True},
            "eth3": {"parents": [], "type": "physical", "enabled": True},
            "bond0": {
                "parents": ["eth0", "eth1"],
                "type": "bond",
                "enabled": True,
            },
            "bond1": {
                "parents": ["eth2", "eth3"],
                "type": "bond",
                "enabled": False,
            },
        }
        assert get_default_monitored_interfaces(interfaces) == ["bond0"]

    def test_monitors_virtual_bridges_but_not_physical_bridges(self):
        interfaces = {
            "eth0": {"parents": [], "type": "physical", "enabled": True},
            "eth1": {"parents": [], "type": "physical", "enabled": True},
            "br0": {"parents": ["eth0"], "type": "bridge", "enabled": True},
            "virbr0": {"parents": [], "type": "bridge", "enabled": True},
        }
        assert get_default_monitored_interfaces(interfaces) == [
            "eth0",
            "eth1",
            "virbr0",
        ]

    def test_monitors_physical_interfaces_but_not_child_vlans(self):
        interfaces = {
            "eth0": {"parents": [], "type": "physical", "enabled": True},
            "eth0.100": {"parents": ["eth0"], "type": "vlan", "enabled": True},
        }
        assert get_default_monitored_interfaces(interfaces) == ["eth0"]


class TestAnnotateWithDefaultMonitoredInterfaces(TestNetworkBase):
    """Tests for `get_default_monitored_interfaces()`."""

    def test_adds_monitored_bool_to_interfaces_dictionary(self):
        interfaces = {
            "eth0": {"parents": [], "type": "physical", "enabled": False},
            "eth1": {"parents": [], "type": "physical", "enabled": True},
        }
        annotate_with_default_monitored_interfaces(interfaces)
        assert interfaces == {
            "eth0": {
                "parents": [],
                "type": "physical",
                "enabled": False,
                "monitored": False,
            },
            "eth1": {
                "parents": [],
                "type": "physical",
                "enabled": True,
                "monitored": True,
            },
        }


class TestIsLoopbackAddress(TestNetworkBase):
    def test_handles_ipv4_loopback(self):
        network = IPNetwork("127.0.0.0/8")
        address = factory.pick_ip_in_network(network)
        assert is_loopback_address(address)

    def test_handles_ipv6_loopback(self):
        address = "::1"
        assert is_loopback_address(address)

    def test_handles_random_ipv4_address(self):
        address = factory.make_ipv4_address()
        assert is_loopback_address(address) == IPAddress(address).is_loopback()

    def test_handles_random_ipv6_address(self):
        address = factory.make_ipv6_address()
        assert is_loopback_address(address) == IPAddress(address).is_loopback()

    def test_handles_ipv6_format_ipv4_loopback(self):
        network = IPNetwork("127.0.0.0/8")
        address = factory.pick_ip_in_network(network)
        assert is_loopback_address("::ffff:%s" % address)

    def test_handles_ipv6_format_ipv4_nonloopback(self):
        address = factory.make_ipv4_address()
        assert (
            is_loopback_address("::ffff:%s" % address)
            == IPAddress(address).is_loopback()
        )

    def test_does_not_resolve_hostnames(self):
        gai = self.patch(socket, "getaddrinfo")
        gai.return_value = (
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("::1", None, 0, 1),
            ),
        )
        name = factory.make_name("name")
        assert not (is_loopback_address(name))
        gai.assert_not_called()

    def test_handles_localhost(self):
        gai = self.patch(socket, "getaddrinfo")
        gai.return_value = (
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("2001:db8::1", None, 0, 1),
            ),
        )
        assert is_loopback_address("localhost")
        gai.assert_not_called()


class TestResolvesToLoopbackAddress(TestNetworkBase):
    def test_resolves_hostnames(self):
        gai = self.patch(network_module, "getaddrinfo")
        gai.return_value = (
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("::1", None, 0, 1),
            ),
        )
        name = factory.make_name("name")
        assert resolves_to_loopback_address(name)
        gai.assert_called_once_with(name, None, proto=IPPROTO_TCP)

    def test_resolves_hostnames_non_loopback(self):
        gai = self.patch(network_module, "getaddrinfo")
        gai.return_value = (
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                socket.IPPROTO_TCP,
                "",
                ("2001:db8::1", None, 0, 1),
            ),
        )
        name = factory.make_name("name")
        assert not (resolves_to_loopback_address(name))
        gai.assert_called_once_with(name, None, proto=IPPROTO_TCP)


class TestPreferredHostnamesSortKey(TestNetworkBase):
    """Tests for `preferred_hostnames_sort_key()`."""

    def test_sorts_flat_names(self):
        names = ("c", "b", "a", "z")
        assert ["a", "b", "c", "z"] == sorted(
            names, key=preferred_hostnames_sort_key
        )

    def test_sorts_more_qualified_names_first(self):
        names = (
            "diediedie.archive.ubuntu.com",
            "wpps.org.za",
            "ubuntu.com",
            "ubuntu.sets.a.great.example.com",
        )
        assert sorted(names, key=preferred_hostnames_sort_key) == [
            "ubuntu.sets.a.great.example.com",
            "diediedie.archive.ubuntu.com",
            "wpps.org.za",
            "ubuntu.com",
        ]

    def test_sorts_by_domains_then_hostnames_within_each_domain(self):
        names = (
            "www.ubuntu.com",
            "maas.ubuntu.com",
            "us.archive.ubuntu.com",
            "uk.archive.ubuntu.com",
            "foo.maas.ubuntu.com",
            "archive.ubuntu.com",
            "maas-xenial",
            "juju-xenial",
        )
        assert sorted(names, key=preferred_hostnames_sort_key) == [
            "uk.archive.ubuntu.com",
            "us.archive.ubuntu.com",
            "foo.maas.ubuntu.com",
            "archive.ubuntu.com",
            "maas.ubuntu.com",
            "www.ubuntu.com",
            "juju-xenial",
            "maas-xenial",
        ]

    def test_sorts_by_tlds_first(self):
        names = (
            "com.za",
            "com.com",
            "com.org",
            "www.ubuntu.org",
            "www.ubuntu.com",
            "www.ubuntu.za",
        )
        assert sorted(names, key=preferred_hostnames_sort_key) == [
            "www.ubuntu.com",
            "www.ubuntu.org",
            "www.ubuntu.za",
            "com.com",
            "com.org",
            "com.za",
        ]

    def test_ignores_trailing_periods(self):
        names = (
            "com.za.",
            "com.com",
            "com.org.",
            "www.ubuntu.org",
            "www.ubuntu.com.",
            "www.ubuntu.za",
        )
        assert sorted(names, key=preferred_hostnames_sort_key) == [
            "www.ubuntu.com.",
            "www.ubuntu.org",
            "www.ubuntu.za",
            "com.com",
            "com.org.",
            "com.za.",
        ]


class TestReverseResolveMixIn(TestNetworkBase):
    """Test fixture mix-in for unit tests calling `reverseResolve()`."""

    def set_fake_twisted_dns_reply(self, hostnames: List[str]):
        """Sets up the rrset data structure for the mock resolver.

        This method must be called for any test cases in this suite which
        intend to test the data being returned.
        """
        rrset = []
        data = (rrset,)
        for hostname in hostnames:
            rr = Mock()
            decode = rr.payload.name.name.decode
            decode.return_value = hostname
            rrset.append(rr)
        self.reply = data

    def mock_lookupPointer(self, ip, timeout=None):
        self.timeout = timeout
        return succeed(self.reply)

    def get_mock_iresolver(self):
        resolver = Mock()
        resolver.lookupPointer = Mock()
        resolver.lookupPointer.side_effect = self.mock_lookupPointer
        return resolver

    @pytest.fixture(autouse=True)
    def _setup_reverse_resolve(self, mocker):
        self.timeout = object()
        self.resolver = self.get_mock_iresolver()
        self.lookupPointer = self.resolver.lookupPointer
        self.getResolver = mocker.patch.object(network_module, "getResolver")
        self.getResolver.return_value = self.resolver


@pytest.mark.rack_reactor_guard
class TestReverseResolve(TestReverseResolveMixIn):
    """Tests for `reverseResolve`."""

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_uses_resolver_from_getResolver_by_default(self):
        self.set_fake_twisted_dns_reply([])
        yield reverseResolve(factory.make_ip_address())
        self.getResolver.assert_called_once_with()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_uses_passed_in_IResolver_if_specified(self):
        self.set_fake_twisted_dns_reply([])
        some_other_resolver = self.get_mock_iresolver()
        yield reverseResolve(
            factory.make_ip_address(), resolver=some_other_resolver
        )
        self.getResolver.assert_not_called()
        some_other_resolver.lookupPointer.assert_called_once()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_returns_single_domain(self):
        reverse_dns_reply = ["example.com"]
        self.set_fake_twisted_dns_reply(reverse_dns_reply)
        result = yield reverseResolve(factory.make_ip_address())
        assert result == reverse_dns_reply

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_returns_multiple_sorted_domains(self):
        reverse_dns_reply = ["ubuntu.com", "example.com"]
        self.set_fake_twisted_dns_reply(reverse_dns_reply)
        result = yield reverseResolve(factory.make_ip_address())
        assert result == sorted(
            reverse_dns_reply, key=preferred_hostnames_sort_key
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_empty_list_for_empty_rrset(self):
        reverse_dns_reply = []
        self.set_fake_twisted_dns_reply(reverse_dns_reply)
        result = yield reverseResolve(factory.make_ip_address())
        assert result == reverse_dns_reply

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_returns_empty_list_for_domainerror(self):
        self.lookupPointer.side_effect = DomainError
        result = yield reverseResolve(factory.make_ip_address())
        assert result == []

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_returns_empty_list_for_authoritativedomainerror(self):
        self.lookupPointer.side_effect = AuthoritativeDomainError
        result = yield reverseResolve(factory.make_ip_address())
        assert result == []

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_returns_none_for_dnsquerytimeouterror(self):
        self.lookupPointer.side_effect = DNSQueryTimeoutError(None)
        result = yield reverseResolve(factory.make_ip_address())
        assert result is None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_returns_none_for_resolvererror(self):
        self.lookupPointer.side_effect = ResolverError
        result = yield reverseResolve(factory.make_ip_address())
        assert result is None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_raises_for_unhandled_error(self):
        self.lookupPointer.side_effect = TypeError
        with pytest.raises(TypeError):
            yield reverseResolve(factory.make_ip_address())


class TestGetSourceAddress(TestNetworkBase):
    def test_accepts_ipnetwork(self):
        assert "127.0.0.1" == get_source_address(IPNetwork("127.0.0.1/8"))

    def test_ipnetwork_works_for_ipv4_slash32(self):
        mock = self.patch(network_module, "get_source_address_for_ipaddress")
        mock.return_value = "10.0.0.1"
        assert "10.0.0.1" == get_source_address(IPNetwork("10.0.0.1/32"))

    def test_ipnetwork_works_for_ipv6_slash128(self):
        mock = self.patch(network_module, "get_source_address_for_ipaddress")
        mock.return_value = "2001:67c:1560::1"
        assert "2001:67c:1560::1" == get_source_address(
            IPNetwork("2001:67c:1560::/128")
        )

    def test_ipnetwork_works_for_ipv6_slash48(self):
        mock = self.patch(network_module, "get_source_address_for_ipaddress")
        mock.return_value = "2001:67c:1560::1"
        assert "2001:67c:1560::1" == get_source_address(
            IPNetwork("2001:67c:1560::/48")
        )

    def test_ipnetwork_works_for_ipv6_slash64(self):
        mock = self.patch(network_module, "get_source_address_for_ipaddress")
        mock.return_value = "2001:67c:1560::1"
        assert "2001:67c:1560::1" == get_source_address(
            IPNetwork("2001:67c:1560::1/64")
        )

    def test_accepts_ipaddress(self):
        assert "127.0.0.1" == get_source_address(IPAddress("127.0.0.1"))

    def test_accepts_string(self):
        assert "127.0.0.1" == get_source_address("127.0.0.1")

    def test_converts_ipv4_mapped_ipv6_to_ipv4(self):
        assert "127.0.0.1" == get_source_address("::ffff:127.0.0.1")

    def test_supports_ipv6(self):
        assert "::1" == get_source_address("::1")

    def test_returns_none_if_no_route_found(self):
        assert get_source_address("255.255.255.255") is None

    def test_returns_appropriate_address_for_global_ip(self):
        assert get_source_address("8.8.8.8") is not None


class TestGetSourceAddressForUrl(TestNetworkBase):
    def test_returns_source_address_for_url_host(self):
        mock_getaddrinfo = self.patch(network_module, "getaddrinfo")
        mock_getaddrinfo.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.0.0.5", 0))
        ]
        mock_get_source = self.patch(
            network_module, "get_source_address_for_ipaddress"
        )
        mock_get_source.return_value = "10.0.0.1"

        result = get_source_address_for_url("http://maas.example:5240/MAAS")

        mock_getaddrinfo.assert_called_once_with(
            "maas.example", None, proto=socket.IPPROTO_TCP
        )
        mock_get_source.assert_called_once_with(IPAddress("10.0.0.5"))
        assert "10.0.0.1" == result

    def test_returns_source_address_for_ipv6_url_host(self):
        """An IPv6-only hostname resolves via getaddrinfo, unlike the
        IPv4-only socket.gethostbyname this used to call."""
        mock_getaddrinfo = self.patch(network_module, "getaddrinfo")
        mock_getaddrinfo.return_value = [
            (
                socket.AF_INET6,
                socket.SOCK_STREAM,
                0,
                "",
                ("fd00::1", 0, 0, 0),
            )
        ]
        mock_get_source = self.patch(
            network_module, "get_source_address_for_ipaddress"
        )
        mock_get_source.return_value = "fd00::5"

        result = get_source_address_for_url("http://maas.example:5240/MAAS")

        mock_get_source.assert_called_once_with(IPAddress("fd00::1"))
        assert "fd00::5" == result

    def test_returns_none_when_url_has_no_hostname(self):
        assert get_source_address_for_url("not-a-url") is None

    def test_returns_none_when_hostname_does_not_resolve(self):
        self.patch(network_module, "getaddrinfo").side_effect = gaierror()
        assert (
            get_source_address_for_url("http://nonexistent.invalid/MAAS")
            is None
        )


class TestResolveBindAddress(TestNetworkBase):
    def test_explicit_address_returned_unchanged(self):
        result = resolve_bind_address(
            "10.0.0.1", "http://10.0.0.1:5240/MAAS", hardening_active=True
        )
        assert "10.0.0.1" == result

    def test_empty_derives_from_maas_url(self):
        self.patch(
            network_module, "get_source_address_for_url"
        ).return_value = "10.0.0.5"

        result = resolve_bind_address(
            "", "http://10.0.0.5:5240/MAAS", hardening_active=True
        )
        assert "10.0.0.5" == result

    def test_empty_hardening_active_falls_back_to_loopback(self):
        self.patch(
            network_module, "get_source_address_for_url"
        ).return_value = None

        result = resolve_bind_address(
            "", "http://unreachable:5240/MAAS", hardening_active=True
        )
        assert "127.0.0.1" == result

    def test_empty_hardening_inactive_falls_back_to_any(self):
        self.patch(
            network_module, "get_source_address_for_url"
        ).return_value = None

        result = resolve_bind_address(
            "", "http://unreachable:5240/MAAS", hardening_active=False
        )
        assert "0.0.0.0" == result

    def test_empty_hardening_inactive_ignores_resolvable_maas_url(self):
        # A resolvable maas_url must not narrow the bind outside
        # hardening (e.g. a floating VIP fronting the region controller
        # would otherwise be unreachable, since nothing would listen on
        # the VIP itself -- only on the node's own derived address).
        mock_derive = self.patch(network_module, "get_source_address_for_url")
        mock_derive.return_value = "10.0.0.5"

        result = resolve_bind_address(
            "", "http://10.0.0.5:5240/MAAS", hardening_active=False
        )
        assert "0.0.0.0" == result
        mock_derive.assert_not_called()

    def test_empty_ipv6_hardening_active_falls_back_to_ipv6_loopback(self):
        self.patch(
            network_module, "get_source_address_for_url"
        ).return_value = None

        result = resolve_bind_address(
            "",
            "http://unreachable:5240/MAAS",
            hardening_active=True,
            family=socket.AF_INET6,
        )
        assert "::1" == result

    def test_empty_ipv6_hardening_inactive_falls_back_to_any(self):
        self.patch(
            network_module, "get_source_address_for_url"
        ).return_value = None

        result = resolve_bind_address(
            "",
            "http://unreachable:5240/MAAS",
            hardening_active=False,
            family=socket.AF_INET6,
        )
        assert "::" == result

    def test_empty_ipv6_derives_from_maas_url(self):
        mock_derive = self.patch(network_module, "get_source_address_for_url")
        mock_derive.return_value = "fd00::5"

        result = resolve_bind_address(
            "",
            "http://[fd00::5]:5240/MAAS",
            hardening_active=True,
            family=socket.AF_INET6,
        )
        assert "fd00::5" == result
        mock_derive.assert_called_once_with(
            "http://[fd00::5]:5240/MAAS", family=socket.AF_INET6
        )


class TestResolveBindAddresses(TestNetworkBase):
    def test_explicit_list_returned_unchanged(self):
        result = resolve_bind_addresses(
            ["10.0.0.1", "10.0.0.2"],
            "http://10.0.0.1:5240/MAAS",
            hardening_active=True,
        )
        assert ["10.0.0.1", "10.0.0.2"] == result

    def test_empty_hardening_inactive_stays_empty(self):
        result = resolve_bind_addresses(
            [], "http://10.0.0.1:5240/MAAS", hardening_active=False
        )
        assert [] == result

    def test_empty_hardening_active_derives_single_address(self):
        self.patch(
            network_module, "get_source_address_for_url"
        ).return_value = "10.0.0.5"

        result = resolve_bind_addresses(
            [], "http://10.0.0.5:5240/MAAS", hardening_active=True
        )
        assert ["10.0.0.5"] == result

    def test_empty_hardening_active_unresolvable_falls_back_to_loopback(
        self,
    ):
        self.patch(
            network_module, "get_source_address_for_url"
        ).return_value = None

        result = resolve_bind_addresses(
            [], "http://unreachable:5240/MAAS", hardening_active=True
        )
        assert ["127.0.0.1"] == result

    def test_filters_out_blank_entries(self):
        result = resolve_bind_addresses(
            ["10.0.0.1", ""],
            "http://10.0.0.1:5240/MAAS",
            hardening_active=True,
        )
        assert ["10.0.0.1"] == result


class TestResolveServiceBind(TestNetworkBase):
    def test_reads_configured_list_and_maas_url(self):
        config = Mock(
            bind_key=["10.0.0.1", "10.0.0.2"],
            maas_url="http://10.0.0.1:5240/MAAS",
        )

        @contextmanager
        def open_config():
            yield config

        result = resolve_service_bind(
            open_config, "bind_key", hardening_active=True
        )
        assert ["10.0.0.1", "10.0.0.2"] == result

    def test_list_valued_maas_url_uses_first_entry(self):
        config = Mock(bind_key=[], maas_url=["http://10.0.0.5:5240/MAAS"])

        @contextmanager
        def open_config():
            yield config

        self.patch(
            network_module, "get_source_address_for_url"
        ).return_value = "10.0.0.5"

        result = resolve_service_bind(
            open_config, "bind_key", hardening_active=True
        )
        assert ["10.0.0.5"] == result

    def test_open_config_error_is_logged_and_falls_back(self):
        def open_config():
            raise OSError("no such file")

        warning = self.patch(network_module.maaslog, "warning")

        result = resolve_service_bind(
            open_config, "bind_key", hardening_active=False
        )

        assert [] == result
        warning.assert_called_once()
        assert warning.call_args.kwargs.get("exc_info") is True


class TestPartitionByFamily(TestNetworkBase):
    def test_splits_mixed_addresses_by_family(self):
        v4, v6 = partition_by_family(["10.0.0.1", "fd00::1", "10.0.0.2"])
        assert ["10.0.0.1", "10.0.0.2"] == v4
        assert ["fd00::1"] == v6

    def test_empty_input_returns_empty_lists(self):
        assert ([], []) == partition_by_family([])

    def test_malformed_address_is_dropped_with_a_warning(self):
        warning = self.patch(network_module.maaslog, "warning")

        v4, v6 = partition_by_family(["10.0.0.1", "not-an-ip", "fd00::1"])

        assert ["10.0.0.1"] == v4
        assert ["fd00::1"] == v6
        warning.assert_called_once()


class TestResolveDualStackBindAddresses(TestNetworkBase):
    def test_explicit_v4_only_still_backfills_v6_default(self):
        def fake_derive(maas_url, family=None):
            return {AF_INET: "10.0.0.5", AF_INET6: "fd00::5"}[family]

        self.patch(
            network_module, "get_source_address_for_url"
        ).side_effect = fake_derive

        result = resolve_dual_stack_bind_addresses(
            ["10.0.0.9"], "http://10.0.0.5:5240/MAAS", hardening_active=True
        )
        assert ["10.0.0.9", "fd00::5"] == result

    def test_explicit_v6_only_still_backfills_v4_default(self):
        def fake_derive(maas_url, family=None):
            return {AF_INET: "10.0.0.5", AF_INET6: "fd00::5"}[family]

        self.patch(
            network_module, "get_source_address_for_url"
        ).side_effect = fake_derive

        result = resolve_dual_stack_bind_addresses(
            ["fd00::9"], "http://10.0.0.5:5240/MAAS", hardening_active=True
        )
        assert ["fd00::9", "10.0.0.5"] == result

    def test_explicit_both_families_returned_unchanged(self):
        derive = self.patch(network_module, "get_source_address_for_url")

        result = resolve_dual_stack_bind_addresses(
            ["10.0.0.9", "fd00::9"],
            "http://10.0.0.5:5240/MAAS",
            hardening_active=True,
        )
        assert ["10.0.0.9", "fd00::9"] == result
        derive.assert_not_called()

    def test_empty_configured_derives_both_families(self):
        def fake_derive(maas_url, family=None):
            return {AF_INET: "10.0.0.5", AF_INET6: "fd00::5"}[family]

        self.patch(
            network_module, "get_source_address_for_url"
        ).side_effect = fake_derive

        result = resolve_dual_stack_bind_addresses(
            [], "http://10.0.0.5:5240/MAAS", hardening_active=True
        )
        assert ["10.0.0.5", "fd00::5"] == result

    def test_empty_configured_outside_hardening_stays_empty(self):
        result = resolve_dual_stack_bind_addresses(
            [], "http://10.0.0.5:5240/MAAS", hardening_active=False
        )
        assert [] == result

    def test_malformed_address_is_dropped_not_raised(self):
        # partition_by_family runs at service-config render time, not
        # validation time -- a typo in a conf file must not crash
        # nginx/squid/BIND9 config generation.
        warning = self.patch(network_module.maaslog, "warning")

        result = resolve_dual_stack_bind_addresses(
            ["10.0.0.9", "not-an-ip"],
            "http://10.0.0.5:5240/MAAS",
            hardening_active=False,
        )
        assert ["10.0.0.9"] == result
        warning.assert_called_once()


class TestResolveDualStackServiceBind(TestNetworkBase):
    def test_reads_configured_list_and_backfills_missing_family(self):
        config = Mock(
            bind_key=["10.0.0.9"],
            maas_url="http://10.0.0.5:5240/MAAS",
        )

        @contextmanager
        def open_config():
            yield config

        self.patch(
            network_module, "get_source_address_for_url"
        ).return_value = "fd00::5"

        result = resolve_dual_stack_service_bind(
            open_config, "bind_key", hardening_active=True
        )
        assert ["10.0.0.9", "fd00::5"] == result

    def test_open_config_error_is_logged_and_falls_back(self):
        def open_config():
            raise OSError("no such file")

        warning = self.patch(network_module.maaslog, "warning")

        result = resolve_dual_stack_service_bind(
            open_config, "bind_key", hardening_active=False
        )

        assert [] == result
        warning.assert_called_once()


class TestResolveConnectAddress(TestNetworkBase):
    def test_specific_bind_returned_unchanged(self):
        result = resolve_connect_address(
            "10.0.0.1", "http://10.0.0.1:5240/MAAS", hardening_active=True
        )
        assert "10.0.0.1" == result

    def test_wildcard_bind_maps_to_loopback(self):
        self.patch(
            network_module, "get_source_address_for_url"
        ).return_value = None

        result = resolve_connect_address(
            "", "http://unreachable:5240/MAAS", hardening_active=False
        )
        assert "127.0.0.1" == result

    def test_ipv6_wildcard_bind_maps_to_ipv6_loopback(self):
        result = resolve_connect_address(
            "::", "http://unreachable:5240/MAAS", hardening_active=False
        )
        assert "::1" == result


class TestGenerateMACAddress(TestNetworkBase):
    def test_starts_with_virsh_prefix(self):
        assert re.search(r"^52:54:00:", generate_mac_address())

    def test_never_the_same(self):
        random_macs = [generate_mac_address() for _ in range(10)]
        for mac1, mac2 in itertools.permutations(random_macs, 2):
            assert mac1 != mac2


class TestConvertHostToUriStr(TestNetworkBase):
    def test_hostname(self):
        hostname = factory.make_hostname()
        assert hostname == convert_host_to_uri_str(hostname)

    def test_ipv4(self):
        ipv4 = factory.make_ipv4_address()
        assert ipv4 == convert_host_to_uri_str(ipv4)

    def test_ipv6_mapped(self):
        ipv4 = factory.make_ipv4_address()
        ipv6_mapped = IPAddress(ipv4).ipv6()
        assert ipv4 == convert_host_to_uri_str(str(ipv6_mapped))

    def test_ipv6(self):
        ipv6 = factory.make_ipv6_address()
        assert "[%s]" % ipv6 == convert_host_to_uri_str(ipv6)


class TestGetIfnameForLabel(TestNetworkBase):
    @pytest.mark.parametrize(
        "input,expected",
        [
            pytest.param("0", "eth0", id="numeric"),
            pytest.param(
                "0000000000000000000000000000000000000000000000000000200",
                "eth200",
                id="numeric_zero_pad",
            ),
            pytest.param("eth0", "eth0", id="normal_interface_name"),
            pytest.param(
                "eth012345678901",
                "eth012345678901",
                id="long_but_not_too_long_name",
            ),
            pytest.param(
                "eth0123456789012",
                "eth-ff5c2-89012",
                id="name_a_little_too_long",
            ),
            pytest.param(
                "1000000000000000000000000000000000000000000000000000001",
                "eth-8d3de-00001",
                id="crazy_long_numeric_name",
            ),
        ],
    )
    def test_scenarios(self, input, expected):
        assert expected == get_ifname_for_label(input)
