# Copyright 2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maasserver.regiondservices.syslog`."""

from netaddr import IPAddress
import pytest
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks

from maasserver.config import RegionConfiguration
from maasserver.models.config import Config
from maasserver.regiondservices import syslog
from maasserver.service_monitor import service_monitor
from maasserver.testing.factory import factory
from maasserver.utils.orm import transactional
from maasserver.utils.threads import deferToDatabase
from maastesting.crochet import wait_for
from maastesting.twisted import TwistedLoggerFixture
from provisioningserver.utils.env import MAAS_ID
import provisioningserver.utils.network as network_module

wait_for_reactor = wait_for()


@pytest.fixture(autouse=True)
def _disable_post_commit_hooks(mocker):
    mocker.patch("maasserver.utils.orm.post_commit_hooks")
    mocker.patch("maasserver.utils.orm.post_commit_do")


def make_region_rack_with_address(space):
    region = factory.make_RegionRackController()
    iface = factory.make_Interface(node=region)
    cidr4 = factory.make_ipv4_network(24)
    subnet4 = factory.make_Subnet(space=space, cidr=cidr4)
    cidr6 = factory.make_ipv6_network(64)
    subnet6 = factory.make_Subnet(space=space, cidr=cidr6)
    sip4 = factory.make_StaticIPAddress(interface=iface, subnet=subnet4)
    sip6 = factory.make_StaticIPAddress(interface=iface, subnet=subnet6)
    return region, sip4, sip6


class TestRegionSyslogService_Basic:
    """Basic tests for `RegionSyslogService`."""

    def test_service_uses__tryUpdate_as_periodic_function(self):
        service = syslog.RegionSyslogService(reactor)
        assert (service._tryUpdate, (), {}) == service.call

    def test_service_iterates_every_30_seconds(self):
        service = syslog.RegionSyslogService(reactor)
        assert 30.0 == service.step


@pytest.mark.allow_transactions
@pytest.mark.usefixtures("maasdb")
class TestRegionSyslogService:
    """Tests for `RegionSyslogService`."""

    @transactional
    def make_example_configuration(self):
        # Set the syslog port.
        port = factory.pick_port()
        Config.objects.set_config("maas_syslog_port", port)
        # Populate the database with example peers.
        space = factory.make_Space()
        region, addr4, addr6 = make_region_rack_with_address(space)
        MAAS_ID.set(region.system_id)
        peer1, addr1_4, addr1_6 = make_region_rack_with_address(space)
        peer2, addr2_4, addr2_6 = make_region_rack_with_address(space)
        # Return the servers and all possible peer IP addresses.
        return (
            port,
            [
                (
                    peer1,
                    sorted([IPAddress(addr1_4.ip), IPAddress(addr1_6.ip)])[0],
                ),
                (
                    peer2,
                    sorted([IPAddress(addr2_4.ip), IPAddress(addr2_6.ip)])[0],
                ),
            ],
        )

    @wait_for_reactor
    @inlineCallbacks
    def test_tryUpdate_updates_syslog_server(self, mocker):
        service = syslog.RegionSyslogService(reactor)
        port, peers = yield deferToDatabase(self.make_example_configuration)
        write_config = mocker.patch.object(
            syslog, "write_config", autospec=True
        )
        restartService = mocker.patch.object(
            service_monitor, "restartService", autospec=True
        )
        yield service._tryUpdate()
        assert write_config.call_count == 1
        assert write_config.call_args.kwargs == {
            "port": port,
            "promtail_port": None,
            "bind": [],
        }
        write_local, called_peers = write_config.call_args.args
        assert write_local
        expected_peers = [
            {"ip": service._formatIP(ip), "name": node.hostname}
            for node, ip in peers
        ]
        assert sorted(called_peers, key=lambda peer: peer["ip"]) == sorted(
            expected_peers, key=lambda peer: peer["ip"]
        )

        restartService.assert_called_once_with("syslog_region")
        write_config.reset_mock()
        restartService.reset_mock()
        # If the configuration has not changed then a second call to
        # `_tryUpdate` does not result in another call to `write_config`.
        yield service._tryUpdate()
        write_config.assert_not_called()
        restartService.assert_not_called()

    @wait_for_reactor
    @inlineCallbacks
    def test_syslog_bind_hardening_off_stays_wildcard(self, mocker):
        mocker.patch.object(syslog, "is_hardening_enabled", return_value=False)
        service = syslog.RegionSyslogService(reactor)
        port, _ = yield deferToDatabase(self.make_example_configuration)
        write_config = mocker.patch.object(
            syslog, "write_config", autospec=True
        )
        mocker.patch.object(service_monitor, "restartService", autospec=True)
        yield service._tryUpdate()
        assert write_config.call_args.kwargs["bind"] == []

    @wait_for_reactor
    @inlineCallbacks
    def test_syslog_bind_derives_from_maas_url_under_hardening(self, mocker):
        mocker.patch.object(syslog, "is_hardening_enabled", return_value=True)
        mocker.patch.object(
            network_module,
            "get_source_address_for_url",
            return_value="10.0.0.9",
        )
        mock_open = mocker.patch.object(RegionConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.syslog_bind = []
        mock_cfg.maas_url = "http://10.0.0.9:5240/MAAS"
        mock_open.return_value.__exit__.return_value = False
        service = syslog.RegionSyslogService(reactor)
        port, _ = yield deferToDatabase(self.make_example_configuration)
        write_config = mocker.patch.object(
            syslog, "write_config", autospec=True
        )
        mocker.patch.object(service_monitor, "restartService", autospec=True)
        yield service._tryUpdate()
        assert write_config.call_args.kwargs["bind"] == ["10.0.0.9"]

    @wait_for_reactor
    @inlineCallbacks
    def test_syslog_bind_explicit_value_used(self, mocker):
        mocker.patch.object(syslog, "is_hardening_enabled", return_value=True)
        mock_open = mocker.patch.object(RegionConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.syslog_bind = ["10.0.0.5"]
        mock_cfg.maas_url = "http://10.0.0.9:5240/MAAS"
        mock_open.return_value.__exit__.return_value = False
        service = syslog.RegionSyslogService(reactor)
        port, _ = yield deferToDatabase(self.make_example_configuration)
        write_config = mocker.patch.object(
            syslog, "write_config", autospec=True
        )
        mocker.patch.object(service_monitor, "restartService", autospec=True)
        yield service._tryUpdate()
        assert write_config.call_args.kwargs["bind"] == ["10.0.0.5"]


@pytest.mark.allow_transactions
@pytest.mark.usefixtures("maasdb")
class TestRegionSyslogService_Errors:
    """Tests for error handing in `RegionSyslogService`."""

    @wait_for_reactor
    @inlineCallbacks
    @pytest.mark.parametrize(
        "method",
        [
            "_getConfiguration",
            "_maybeApplyConfiguration",
            "_applyConfiguration",
            "_configurationApplied",
        ],
    )
    def test_tryUpdate_logs_errors_from_broken_method(self, method, mocker):
        service = syslog.RegionSyslogService(reactor)
        broken_method = mocker.patch.object(service, method, autospec=True)
        broken_method.side_effect = factory.make_exception()

        # Don't actually write the file.
        mocker.patch.object(syslog, "write_config", autospec=True)

        # Ensure that we never actually execute against systemd.
        mocker.patch.object(service_monitor, "restartService", autospec=True)

        with TwistedLoggerFixture() as logger:
            yield service._tryUpdate()

        assert (
            "Failed to update syslog configuration.\nTraceback (most recent call last):"
            in logger.output
        )
        assert str(broken_method.side_effect) in logger.output


@pytest.mark.usefixtures("maasdb")
class TestRegionSyslogService_Database:
    """Database tests for `RegionSyslogService`."""

    def test_getConfiguration_returns_configuration_object(self):
        service = syslog.RegionSyslogService(reactor)

        # Put all addresses in the same space so they're mutually routable.
        space = factory.make_Space()
        # Populate the database with "this" region rack and an example peer.
        region_rack, _, _ = make_region_rack_with_address(space)
        MAAS_ID.set(region_rack.system_id)
        peer, addr4, addr6 = make_region_rack_with_address(space)

        observed = service._getConfiguration()
        assert isinstance(observed, syslog._Configuration)

        assert observed.peers == {(peer.hostname, IPAddress(addr4.ip))}
