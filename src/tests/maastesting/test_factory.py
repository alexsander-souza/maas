# Copyright 2012-2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the factory where appropriate.  Don't overdo this."""

from datetime import datetime
from itertools import count
import os.path
from random import randint
import subprocess
from unittest.mock import sentinel

from netaddr import IPAddress, IPNetwork
import pytest

from maastesting import factory as factory_module
from maastesting.factory import factory, TooManyRandomRetries


class TestFactory:
    def test_make_string_respects_size(self):
        sizes = [1, 10, 100]
        random_strings = [factory.make_string(size) for size in sizes]
        assert sizes == [len(string) for string in random_strings]

    def test_pick_bool_returns_bool(self):
        assert isinstance(factory.pick_bool(), bool)

    def test_pick_port_returns_int(self):
        assert isinstance(factory.pick_port(), int)

    def test_make_vlan_tag_excludes_None_by_default(self, mocker):
        # Artificially limit randint to a very narrow range, to guarantee
        # some repetition in its output, and virtually guarantee that we test
        # both outcomes of the flip-a-coin call in make_vlan_tag.
        random = mocker.patch.object(factory_module, "random")
        random.randint.side_effect = [1, 2]
        outcomes = {factory.make_vlan_tag(), factory.make_vlan_tag()}
        assert {1, 2} == outcomes

    def test_make_vlan_tag_includes_None_if_allow_none(self, mocker):
        random = mocker.patch.object(factory_module, "random")
        random.choice.side_effect = [True, False, False]
        random.randint.side_effect = [1, 2]
        assert {None, 1, 2} == {
            factory.make_vlan_tag(allow_none=True),
            factory.make_vlan_tag(allow_none=True),
            factory.make_vlan_tag(allow_none=True),
        }

    def test_make_ipv4_address(self):
        ip_address = factory.make_ipv4_address()
        assert isinstance(ip_address, str)
        octets = ip_address.split(".")
        assert 4 == len(octets)
        for octet in octets:
            assert 0 <= int(octet) <= 255

    def test_make_ipv4_address_but_not(self, mocker):
        # We want to look for clashes between identical IPs and/or netmasks.
        # Narrow down the range of randomness so we have a decent chance of
        # triggering a clash, but not so far that we'll loop for very long
        # trying to find a network we haven't seen already.
        mocker.patch.object(
            factory, "make_ipv4_address", lambda: "10.%d.0.0" % randint(1, 200)
        )
        networks = []
        for _ in range(100):
            networks.append(factory.make_ipv4_network(but_not=networks))
        assert len(networks) == len(set(networks))

    def test_make_UUID(self):
        uuid = factory.make_UUID()
        assert isinstance(uuid, str)
        assert 36 == len(uuid)

    def test_make_ipv4_network(self):
        network = factory.make_ipv4_network()
        assert isinstance(network, IPNetwork)

    def test_make_ipv4_network_respects_but_not(self, mocker):
        mocker.patch.object(
            factory, "make_ipv4_address"
        ).return_value = IPAddress("10.1.1.0")
        with pytest.raises(TooManyRandomRetries):
            factory.make_ipv4_network(
                slash=24,
                but_not=[IPNetwork("10.1.1.0/24")],
            )

    def test_make_ipv4_network_returns_network_not_in_but_not(self, mocker):
        mocker.patch.object(
            factory, "make_ipv4_address"
        ).return_value = IPAddress("10.1.1.0")
        assert IPNetwork("10.1.1.0/24") == factory.make_ipv4_network(
            slash=24, but_not=[IPNetwork("10.9.9.0/24")]
        )

    def test_make_ipv4_network_may_overlap_but_not(self, mocker):
        mocker.patch.object(
            factory, "make_ipv4_address"
        ).return_value = IPAddress("10.1.1.0")
        assert IPNetwork("10.1.1.0/24") == factory.make_ipv4_network(
            slash=24, but_not=[IPNetwork("10.1.0.0/16")]
        )

    def test_make_ipv4_network_avoids_network_in_disjoint_from(self, mocker):
        mocker.patch.object(
            factory, "make_ipv4_address"
        ).return_value = IPAddress("10.1.1.0")
        with pytest.raises(TooManyRandomRetries):
            factory.make_ipv4_network(
                slash=24,
                disjoint_from=[IPNetwork("10.1.1.0/24")],
            )

    def test_make_ipv4_network_avoids_network_overlapping_disjoint_from(
        self, mocker
    ):
        mocker.patch.object(
            factory, "make_ipv4_address"
        ).return_value = IPAddress("10.1.1.0")
        with pytest.raises(TooManyRandomRetries):
            factory.make_ipv4_network(
                slash=24,
                disjoint_from=[IPNetwork("10.1.0.0/16")],
            )

    def test_make_ipv4_network_returns_network_disjoint_from(self):
        existing_network = factory.make_ipv4_network()
        new_network = factory.make_ipv4_network(
            disjoint_from=[existing_network]
        )
        assert existing_network != new_network
        assert new_network not in existing_network
        assert existing_network not in new_network

    def test_pick_ip_in_network_for_ipv4_slash_31(self):
        network = factory.make_ipv4_network(slash=31)
        ip = factory.pick_ip_in_network(network)
        assert network.first <= IPAddress(ip).value <= network.last

    def test_pick_ip_in_network_for_ipv4_slash_30(self):
        network = factory.make_ipv4_network(slash=30)
        ip = factory.pick_ip_in_network(network)
        assert network.first < IPAddress(ip).value < network.last

    def test_pick_ip_in_network_for_ipv6(self):
        # For IPv6, pick_ip_in_network will not consider the very first
        # address in a network because this is reserved for routers.
        network = factory.make_ipv6_network(slash=126)
        ip = factory.pick_ip_in_network(network)
        assert network.first < IPAddress(ip).value <= network.last

    def test_make_date_returns_datetime(self):
        assert isinstance(factory.make_date(), datetime)

    def test_make_mac_address(self):
        mac_address = factory.make_mac_address()
        assert isinstance(mac_address, str)
        assert 17 == len(mac_address)
        for hex_octet in mac_address.split(":"):
            assert 0 <= int(hex_octet, 16) <= 255

    def test_make_mac_address_alternative_delimiter(self, mocker):
        mocker.patch.object(factory, "random_octets", count(0x3A))
        mac_address = factory.make_mac_address(delimiter="-")
        assert "3a-3b-3c-3d-3e-3f" == mac_address

    def test_make_random_leases_maps_ips_to_macs(self):
        [(ip, mac)] = factory.make_random_leases().items()
        assert 4 == len(ip.split(".")), (
            "IP address does not look like an IP address: '%s'" % ip
        )
        assert 6 == len(mac.split(":")), (
            "MAC address does not look like a MAC address: '%s'" % mac
        )

    def test_make_random_leases_randomizes_ips(self):
        assert list(factory.make_random_leases().keys()) != list(
            factory.make_random_leases().keys()
        )

    def test_make_random_leases_randomizes_macs(self):
        assert list(factory.make_random_leases().values()) != list(
            factory.make_random_leases().values()
        )

    def test_make_random_leases_returns_requested_number_of_leases(self):
        num_leases = randint(0, 3)
        assert num_leases == len(factory.make_random_leases(num_leases))

    def test_make_file_creates_file(self, tmp_path):
        assert os.path.isfile(factory.make_file(tmp_path))

    def test_make_file_writes_binary_contents(self, tmp_path):
        contents = factory.make_string().encode("ascii")
        file_path = factory.make_file(tmp_path, contents=contents)
        with open(file_path, "rb") as fh:
            actual_contents = fh.read()
        assert contents == actual_contents

    def test_make_file_writes_textual_contents_as_utf8(self, tmp_path):
        contents = factory.make_string() + "\xa3\u20ac"
        file_path = factory.make_file(tmp_path, contents=contents)
        with open(file_path, "rb") as fh:
            actual_contents = fh.read()
        assert contents == actual_contents.decode("utf-8")

    def test_make_file_makes_up_contents_if_none_given(self, tmp_path):
        with open(factory.make_file(tmp_path)) as temp_file:
            contents = temp_file.read()
        assert "" != contents

    def test_make_file_uses_given_name(self, tmp_path):
        name = factory.make_string()
        assert name == os.path.basename(factory.make_file(tmp_path, name=name))

    def test_make_file_uses_given_dir(self, tmp_path):
        name = factory.make_string()
        directory = str(tmp_path)
        assert (directory, name) == os.path.split(
            factory.make_file(directory, name=name)
        )

    def test_make_name_returns_unicode(self):
        assert isinstance(factory.make_name(), str)

    def test_make_name_includes_prefix_and_separator(self):
        assert factory.make_name("abc").startswith("abc-")

    def test_make_name_includes_random_text_of_requested_length(self):
        size = randint(1, 99)
        assert len("prefix") + len("-") + size == len(
            factory.make_name("prefix", size=size)
        )

    def test_make_name_includes_random_text(self):
        assert factory.make_name(size=100) != factory.make_name(size=100)

    def test_make_name_uses_configurable_separator(self):
        sep = "SEPARATOR"
        prefix = factory.make_string(3)
        assert factory.make_name(prefix, sep=sep).startswith(prefix + sep)

    def test_make_name_does_not_require_prefix(self):
        size = randint(1, 99)
        unprefixed_name = factory.make_name(sep="-", size=size)
        assert size == len(unprefixed_name)
        assert not unprefixed_name.startswith("-")

    def test_make_name_does_not_include_weird_characters(self):
        name = factory.make_name(size=100)
        for char in "/ \t\n\r\\":
            assert char not in name

    def test_make_names_calls_make_name_with_each_prefix(self, mocker):
        mocker.patch.object(
            factory, "make_name", lambda prefix: prefix + "-xxx"
        )
        assert ["abc-xxx", "def-xxx", "ghi-xxx"] == list(
            factory.make_names("abc", "def", "ghi")
        )

    def test_make_tarball_writes_tarball(self, tmp_path):
        filename = factory.make_name()
        contents = {filename: factory.make_string().encode("ascii")}

        tarball = factory.make_tarball(tmp_path, contents)

        dest = tmp_path
        subprocess.check_call(["tar", "-xzf", tarball, "-C", dest])
        with open(os.path.join(dest, filename), "rb") as fh:
            actual_contents = fh.read()
        assert actual_contents == contents[filename]

    def test_make_tarball_makes_up_content_if_None(self, tmp_path):
        filename = factory.make_name()
        tarball = factory.make_tarball(tmp_path, {filename: None})

        dest = tmp_path
        subprocess.check_call(["tar", "-xzf", tarball, "-C", dest])
        assert os.path.exists(os.path.join(dest, filename))
        with open(os.path.join(dest, filename), "rb") as unpacked_file:
            contents = unpacked_file.read()
        assert len(contents) > 0

    def test_make_parsed_url_accepts_explicit_port(self):
        port = factory.pick_port()
        url = factory.make_parsed_url(port=port)
        assert url.netloc.endswith(f":{port}"), (
            "The generated URL does not contain"
            f"a port specification for port {port}"
        )

    def test_make_parsed_url_can_omit_port(self):
        url = factory.make_parsed_url(port=False)
        assert ":" not in url.netloc, (
            f"Generated url: {url.geturl()} contains a port number in netloc segment"
        )

    def test_make_parsed_url_pics_random_port(self):
        url = factory.make_parsed_url()
        assert ":" in url.netloc, (
            f"Generated url: {url.geturl()} does not contain a port number in netloc segment"
        )

        assert url.netloc.split(":")[1].isdigit(), (
            f"Generated url: {url.geturl()} does not contain a valid port number in netloc segment"
        )

        url = factory.make_parsed_url(port=True)

        assert ":" in url.netloc, (
            f"Generated url: {url.geturl()} does not contain a port number in netloc segment"
        )

        assert url.netloc.split(":")[1].isdigit(), (
            f"Generated url: {url.geturl()} does not contain a valid port number in netloc segment"
        )

    def test_make_parsed_url_asserts_with_conflicting_port_numbers(self):
        netloc = ":".join((factory.make_hostname(), str(factory.pick_port())))
        with pytest.raises(AssertionError):
            factory.make_parsed_url(
                netloc=netloc,
                port=factory.pick_port(),
            )
        with pytest.raises(AssertionError):
            factory.make_parsed_url(netloc=netloc, port=True)


# We shouldn't mix pytest tests and nosetests in the same module -
# these will only be executed by pytest, since the automatic fixture
# injection isn't supported by unittest/nosetests.


@pytest.mark.parametrize(
    "version,make_network,make_range",
    [
        (4, factory.make_ipv4_network, factory.make_ipv4_range),
        (6, factory.make_ipv6_network, factory.make_ipv6_range),
    ],
)
class TestMakeIPRange:
    """Tests for `factory.make_ip_range`.

    Tests specialised factory methods `make_ipv4_range` and `make_ipv6_range`
    too, which are each a thin wrapper around `make_ip_range`.
    """

    def test_make_ip_range_returns_IPs(
        self, version, make_network, make_range
    ):
        network = make_network()
        low, high = factory.make_ip_range(network)
        assert isinstance(low, IPAddress)
        assert isinstance(high, IPAddress)
        assert version == low.version
        assert version == high.version
        assert low < high

    def test_make_ip_range_obeys_network(
        self, version, make_network, make_range
    ):
        network = make_network()
        low, high = factory.make_ip_range(network)
        assert low in network
        assert high in network

    def test_make_ip_range_returns_low_and_high(
        self, version, make_network, make_range
    ):
        # Make a very very small network, to maximise the chances of exposure
        # if the method gets this wrong e.g. by returning identical addresses.
        low, high = factory.make_ip_range(
            make_network(slash=(31 if version == 4 else 126))
        )
        assert low < high

    def test_make_ipvN_range_calls_make_ip_range(
        self, mocker, version, make_network, make_range
    ):
        mocker.patch.object(factory, "make_ip_range", autospec=True)
        factory.make_ip_range.return_value = sentinel.ip_range
        network = make_network()
        ip_range = make_range(network)
        assert ip_range is sentinel.ip_range
        factory.make_ip_range.assert_called_once_with(network=network)

    def test_make_ipvN_range_creates_random_network_if_not_supplied(
        self, mocker, version, make_network, make_range
    ):
        mocker.patch.object(factory, "make_ip_range", autospec=True)
        factory.make_ip_range.return_value = sentinel.ip_range
        ip_range = make_range()
        assert ip_range is sentinel.ip_range
        [call] = factory.make_ip_range.mock_calls
        call_network = call.kwargs["network"]
        assert call_network.version == version
