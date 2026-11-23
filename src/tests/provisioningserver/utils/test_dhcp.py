# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


from netaddr import IPAddress

from maastesting.factory import factory
from provisioningserver.utils.dhcp import DHCP


class TestDHCP:
    def test_valid_returns_false_for_truncated_packet(self):
        packet = factory.make_dhcp_packet(truncated=True)
        dhcp = DHCP(packet)
        assert not dhcp.valid
        assert dhcp.invalid_reason == "Truncated DHCP packet."

    def test_valid_returns_false_for_invalid_cookie(self):
        packet = factory.make_dhcp_packet(bad_cookie=True)
        dhcp = DHCP(packet)
        assert not dhcp.valid
        assert dhcp.invalid_reason == "Invalid DHCP cookie."

    def test_valid_returns_false_for_truncated_option_length(self):
        packet = factory.make_dhcp_packet(truncated_option_length=True)
        dhcp = DHCP(packet)
        assert not dhcp.valid
        assert dhcp.invalid_reason == "Truncated length field in DHCP option."

    def test_valid_returns_false_for_truncated_option_value(self):
        packet = factory.make_dhcp_packet(truncated_option_value=True)
        dhcp = DHCP(packet)
        assert not dhcp.valid
        assert dhcp.invalid_reason == "Truncated DHCP option value."

    def test_valid_return_true_for_valid_packet(self):
        packet = factory.make_dhcp_packet()
        dhcp = DHCP(packet)
        assert dhcp.valid

    def test_returns_server_identifier_if_included(self):
        server_ip = factory.make_ip_address(ipv6=False)
        packet = factory.make_dhcp_packet(
            include_server_identifier=True, server_ip=server_ip
        )
        dhcp = DHCP(packet)
        assert dhcp.valid
        assert IPAddress(server_ip) == dhcp.server_identifier

    def test_server_identifier_none_if_not_included(self):
        packet = factory.make_dhcp_packet(include_server_identifier=False)
        dhcp = DHCP(packet)
        assert dhcp.valid
        assert dhcp.server_identifier is None
