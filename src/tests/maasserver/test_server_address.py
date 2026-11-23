# Copyright 2012-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the server_address module."""

from collections import Counter, defaultdict
from random import randint

from netaddr import IPAddress
import pytest

from maasserver import server_address
from maasserver.exceptions import UnresolvableHost
from maasserver.server_address import get_maas_facing_server_addresses
from maasserver.testing.config import RegionConfigurationFixture
from maasserver.testing.factory import factory


def make_hostname():
    return "%s.example.com" % factory.make_hostname()


@pytest.fixture
def configure_maas_url():
    fixtures = []

    def configure(hostname, with_port=False):
        """Set configured maas URL to be a (partly) random URL."""
        url = factory.make_simple_http_url(netloc=hostname, port=with_port)
        fixture = RegionConfigurationFixture(maas_url=url)
        fixture.setUp()
        fixtures.append(fixture)

    yield configure
    for fixture in reversed(fixtures):
        fixture.cleanUp()


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestGetMAASFacingServerHost:
    def test_get_maas_facing_server_host_returns_host_name(
        self, configure_maas_url
    ):
        hostname = make_hostname()
        configure_maas_url(hostname)
        assert server_address.get_maas_facing_server_host() == hostname

    def test_get_maas_facing_server_host_returns_ip_if_ip_configured(
        self, configure_maas_url
    ):
        ip = factory.make_ipv4_address()
        configure_maas_url(ip)
        assert server_address.get_maas_facing_server_host() == ip

    def test_get_maas_facing_server_host_returns_rack_maas_url(self):
        hostname = factory.make_hostname()
        maas_url = "http://%s" % hostname
        rack = factory.make_RackController(url=maas_url)
        assert server_address.get_maas_facing_server_host(rack) == hostname

    def test_get_maas_facing_server_host_strips_out_port(
        self, configure_maas_url
    ):
        hostname = make_hostname()
        configure_maas_url(hostname, with_port=True)
        assert server_address.get_maas_facing_server_host() == hostname

    def test_get_maas_facing_server_host_parses_IPv6_address_in_URL(
        self, configure_maas_url
    ):
        ip = factory.make_ipv6_address()
        configure_maas_url("[%s]" % ip)
        assert server_address.get_maas_facing_server_host() == str(ip)


class FakeResolveHostname:
    """Fake implementation for `resolve_hostname`.

    Makes `resolve_hostname` return the given IP addresses (always as
    `IPAddress`, even though you may pass them as text).  It will return just
    the IPv4 ones, or just the IPv6 ones, depending on which kind of address
    the caller requests.

    :ivar results_by_ip_version: Return values, as a dict mapping IP version
        to the set of results for that IP version.
    :ivar hostname: Host name that was passed by the last invocation.
    """

    def __init__(self, *addresses):
        self.hostname = None
        self.results_by_ip_version = defaultdict(set)
        for addr in addresses:
            addr = IPAddress(addr)
            self.results_by_ip_version[addr.version].add(addr)
            self.results_by_ip_version[0].add(addr)

    def __call__(self, hostname, ip_version):
        assert ip_version in (0, 4, 6)
        self.hostname = hostname
        return self.results_by_ip_version[ip_version]


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestGetMAASFacingServerAddresses:
    def test_integrates_with_get_maas_facing_server_host(self):
        ip = factory.make_ipv4_address()
        maas_url = "http://%s" % ip
        rack = factory.make_RackController(url=maas_url)
        assert str(ip) == server_address.get_maas_facing_server_host(rack)

    def test_resolves_hostname(self, mocker):
        hostname = make_hostname()
        mocker.patch.object(
            server_address,
            "get_maas_facing_server_host",
            return_value=hostname,
        )
        ip = factory.make_ipv4_address()
        fake_resolve = FakeResolveHostname(ip)
        mocker.patch.object(server_address, "resolve_hostname", fake_resolve)
        result = get_maas_facing_server_addresses()
        assert [IPAddress(ip)] == result
        assert hostname == fake_resolve.hostname

    def test_returns_v4_and_v6_addresses(self, mocker):
        # If a server has mixed v4 and v6 addresses,
        # get_maas_facing_server_addresses() will return both.
        v4_ip = factory.make_ipv4_address()
        v6_ip = factory.make_ipv6_address()
        mocker.patch.object(
            server_address,
            "resolve_hostname",
            FakeResolveHostname(v4_ip, v6_ip),
        )
        assert Counter(
            get_maas_facing_server_addresses(ipv4=True, ipv6=True)
        ) == Counter([IPAddress(v4_ip), IPAddress(v6_ip)])

    def test_ignores_IPv4_if_ipv4_not_set(self, mocker):
        v4_ip = factory.make_ipv4_address()
        v6_ip = factory.make_ipv6_address()
        mocker.patch.object(
            server_address,
            "resolve_hostname",
            FakeResolveHostname(v4_ip, v6_ip),
        )
        mocker.patch.object(server_address, "get_maas_facing_server_host")
        assert [IPAddress(v6_ip)] == get_maas_facing_server_addresses(
            ipv4=False, ipv6=True
        )

    def test_falls_back_on_IPv6_if_ipv4_set_but_no_IPv4_address_found(
        self, mocker
    ):
        v6_ip = factory.make_ipv6_address()
        mocker.patch.object(
            server_address, "resolve_hostname", FakeResolveHostname(v6_ip)
        )
        mocker.patch.object(server_address, "get_maas_facing_server_host")
        assert [IPAddress(v6_ip)] == get_maas_facing_server_addresses(
            ipv4=True, ipv6=True
        )

    def test_does_not_return_link_local_addresses(self, mocker):
        global_ipv6 = factory.make_ipv6_address()
        local_ipv6 = {
            "fe80::%d:9876:5432:10" % randint(0, 9999) for _ in range(5)
        }
        mocker.patch.object(
            server_address,
            "resolve_hostname",
            FakeResolveHostname(global_ipv6, *local_ipv6),
        )
        mocker.patch.object(server_address, "get_maas_facing_server_host")
        assert [IPAddress(global_ipv6)] == get_maas_facing_server_addresses()

    def test_returns_link_local_addresses_if_asked(self, mocker):
        global_ipv6 = factory.make_ipv6_address()
        local_ipv6 = {
            "fe80::%d:9876:5432:10" % randint(0, 9999) for _ in range(5)
        }
        mocker.patch.object(
            server_address,
            "resolve_hostname",
            FakeResolveHostname(global_ipv6, *local_ipv6),
        )
        mocker.patch.object(server_address, "get_maas_facing_server_host")
        assert Counter(
            get_maas_facing_server_addresses(link_local=True)
        ) == Counter(
            [IPAddress(ip) for ip in local_ipv6] + [IPAddress(global_ipv6)]
        )

    def test_fails_if_neither_ipv4_nor_ipv6_set(self, mocker):
        mocker.patch.object(
            server_address, "resolve_hostname", FakeResolveHostname()
        )
        mocker.patch.object(server_address, "get_maas_facing_server_host")
        with pytest.raises(UnresolvableHost):
            get_maas_facing_server_addresses(ipv4=False, ipv6=False)

    def test_raises_error_if_hostname_does_not_resolve(self, mocker):
        mocker.patch.object(
            server_address, "resolve_hostname", FakeResolveHostname()
        )
        mocker.patch.object(server_address, "get_maas_facing_server_host")
        with pytest.raises(UnresolvableHost):
            get_maas_facing_server_addresses()

    def test_alternates_include_other_regions_on_same_subnet(self, mocker):
        factory.make_Subnet(cidr="192.168.0.0/24")
        maas_url = "http://192.168.0.254/MAAS"
        rack = factory.make_RackController(url=maas_url)
        r1 = factory.make_RegionController()
        factory.make_Interface(node=r1, ip="192.168.0.1")
        factory.make_Interface(node=r1, ip="192.168.0.254")
        r2 = factory.make_RegionController()
        factory.make_Interface(node=r2, ip="192.168.0.2")
        r3 = factory.make_RegionController()
        factory.make_Interface(node=r3, ip="192.168.0.4")
        # Make the "current" region controller r1.
        mocker.patch.object(
            server_address.MAAS_ID, "get", return_value=r1.system_id
        )
        region_ips = get_maas_facing_server_addresses(
            rack, include_alternates=True
        )
        assert region_ips == [
            IPAddress("192.168.0.254"),
            IPAddress("192.168.0.1"),
            IPAddress("192.168.0.2"),
            IPAddress("192.168.0.4"),
        ]

    def test_alternates_do_not_contain_duplicate_for_maas_url_ip(self, mocker):
        # See bug #1753493. (This tests to ensure we don't provide the same
        # IP address from maas_url twice.) Also ensures that the IP address
        # from maas_url comes first.
        factory.make_Subnet(cidr="192.168.0.0/24")
        maas_url = "http://192.168.0.2/MAAS"
        rack = factory.make_RackController(url=maas_url)
        r1 = factory.make_RegionController()
        factory.make_Interface(node=r1, ip="192.168.0.1")
        r2 = factory.make_RegionController()
        factory.make_Interface(node=r2, ip="192.168.0.2")
        # Make the "current" region controller r1.
        mocker.patch.object(
            server_address.MAAS_ID, "get", return_value=r1.system_id
        )
        region_ips = get_maas_facing_server_addresses(
            rack, include_alternates=True
        )
        assert [
            IPAddress("192.168.0.2"),
            IPAddress("192.168.0.1"),
        ] == region_ips

    def test_alternates_include_one_ip_address_per_region_and_maas_url(
        self, mocker
    ):
        factory.make_Subnet(cidr="192.168.0.0/24")
        maas_url = "http://192.168.0.254/MAAS"
        rack = factory.make_RackController(url=maas_url)
        r1 = factory.make_RegionController()
        factory.make_Interface(node=r1, ip="192.168.0.1")
        factory.make_Interface(node=r1, ip="192.168.0.254")
        r2 = factory.make_RegionController()
        factory.make_Interface(node=r2, ip="192.168.0.2")
        factory.make_Interface(node=r2, ip="192.168.0.3")
        r3 = factory.make_RegionController()
        factory.make_Interface(node=r3, ip="192.168.0.4")
        factory.make_Interface(node=r3, ip="192.168.0.5")
        # Make the "current" region controller r1.
        mocker.patch.object(
            server_address.MAAS_ID, "get", return_value=r1.system_id
        )
        region_ips = get_maas_facing_server_addresses(
            rack, include_alternates=True
        )
        assert region_ips == [
            IPAddress("192.168.0.254"),
            IPAddress("192.168.0.1"),
            IPAddress("192.168.0.2"),
            IPAddress("192.168.0.4"),
        ]

    def test_alternates_use_consistent_subnet(self, mocker):
        factory.make_Subnet(cidr="192.168.0.0/24")
        factory.make_Subnet(cidr="192.168.1.0/24")
        maas_url = "http://192.168.0.1/MAAS"
        rack = factory.make_RackController(url=maas_url)
        r1 = factory.make_RegionController()
        factory.make_Interface(node=r1, ip="192.168.0.1")
        factory.make_Interface(node=r1, ip="192.168.1.254")
        r2 = factory.make_RegionController()
        factory.make_Interface(node=r2, ip="192.168.0.2")
        factory.make_Interface(node=r2, ip="192.168.1.3")
        r3 = factory.make_RegionController()
        factory.make_Interface(node=r3, ip="192.168.0.4")
        factory.make_Interface(node=r3, ip="192.168.1.5")
        # Make the "current" region controller r1.
        mocker.patch.object(
            server_address.MAAS_ID, "get", return_value=r1.system_id
        )
        region_ips = get_maas_facing_server_addresses(
            rack, include_alternates=True
        )
        assert region_ips == [
            IPAddress("192.168.0.1"),
            IPAddress("192.168.0.2"),
            IPAddress("192.168.0.4"),
        ]

    def test_alternates_support_ipv4_and_ipv6(self, mocker):
        factory.make_Subnet(cidr="192.168.0.0/24")
        factory.make_Subnet(cidr="192.168.1.0/24")
        factory.make_Subnet(cidr="2001:db8::/64")
        maas_url = "http://maas.io/MAAS"
        mocker.patch.object(
            server_address,
            "resolve_hostname",
            FakeResolveHostname("192.168.0.1", "2001:db8::1"),
        )
        rack = factory.make_RackController(url=maas_url)
        r1 = factory.make_RegionController()
        factory.make_Interface(node=r1, ip="192.168.0.1")
        factory.make_Interface(node=r1, ip="2001:db8::1")
        factory.make_Interface(node=r1, ip="192.168.1.254")
        r2 = factory.make_RegionController()
        factory.make_Interface(node=r2, ip="192.168.0.2")
        factory.make_Interface(node=r2, ip="2001:db8::2")
        r3 = factory.make_RegionController()
        factory.make_Interface(node=r3, ip="192.168.0.4")
        factory.make_Interface(node=r3, ip="2001:db8::4")
        # Make the "current" region controller r1.
        mocker.patch.object(
            server_address.MAAS_ID, "get", return_value=r1.system_id
        )
        region_ips = get_maas_facing_server_addresses(
            rack, include_alternates=True
        )
        assert region_ips == [
            IPAddress("192.168.0.1"),
            IPAddress("2001:db8::1"),
            IPAddress("192.168.0.2"),
            IPAddress("192.168.0.4"),
            IPAddress("2001:db8::2"),
            IPAddress("2001:db8::4"),
        ]
