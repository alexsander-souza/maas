# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the DHCPv4 and DHCPv6 service driver."""

from provisioningserver.service_monitor import (
    DHCPv4Service,
    DHCPv6Service,
    NTPServiceOnRack,
    ProxyServiceOnRack,
    RackControllerServiceOnRack,
    service_monitor,
    SERVICE_STATE,
    SyslogServiceOnRack,
)


class TestDHCPv4Service:
    def test_name(self):
        service = DHCPv4Service()
        assert "dhcpd" == service.name

    def test_service_name(self):
        service = DHCPv4Service()
        assert "maas-dhcpd" == service.service_name


class TestDHCPv6Service:
    def test_name(self):
        service = DHCPv6Service()
        assert "dhcpd6" == service.name

    def test_service_name(self):
        service = DHCPv6Service()
        assert "maas-dhcpd6" == service.service_name


class TestNTPServiceOnRack:
    def test_name_and_service_name(self):
        ntp = NTPServiceOnRack()
        assert "chrony" == ntp.service_name
        assert "ntp_rack" == ntp.name
        assert SERVICE_STATE.ANY == ntp.expected_state


class TestProxyServiceOnRack:
    def test_name_and_service_name(self):
        proxy = ProxyServiceOnRack()
        assert "maas-proxy" == proxy.service_name
        assert "proxy" == proxy.snap_service_name
        assert "proxy_rack" == proxy.name
        assert SERVICE_STATE.ANY == proxy.expected_state


class TestSyslogServiceOnRack:
    def test_name_and_service_name(self):
        syslog = SyslogServiceOnRack()
        assert "maas-syslog" == syslog.service_name
        assert "syslog" == syslog.snap_service_name
        assert "syslog_rack" == syslog.name
        assert SERVICE_STATE.ANY == syslog.expected_state


class TestRackControllerServiceOnRack:
    def test_name_and_service_name(self):
        service = RackControllerServiceOnRack()
        assert "maas-rack-controller" == service.service_name
        assert "rack-controller" == service.snap_service_name
        assert "rack-controller" == service.name


class TestGlobalServiceMonitor:
    def test_includes_all_services(self):
        assert {
            "http",
            "dhcpd",
            "dhcpd6",
            "ntp_rack",
            "proxy_rack",
            "syslog_rack",
            "rack-controller",
        } == service_monitor._services.keys()


