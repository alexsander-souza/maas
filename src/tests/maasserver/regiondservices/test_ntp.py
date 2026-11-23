# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maasserver.regiondservices.ntp`."""

import pytest
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks

from maasserver.models.config import Config
from maasserver.regiondservices import ntp
from maasserver.service_monitor import service_monitor
from maasserver.testing.factory import factory
from maasserver.utils.orm import transactional
from maasserver.utils.threads import deferToDatabase
from maastesting.crochet import wait_for
from maastesting.twisted import always_succeed_with, TwistedLoggerFixture
from provisioningserver.utils.env import MAAS_ID

wait_for_reactor = wait_for()


@pytest.fixture(autouse=True)
def _disable_post_commit_hooks(mocker):
    mocker.patch("maasserver.utils.orm.post_commit_hooks")
    mocker.patch("maasserver.utils.orm.post_commit_do")


def make_region_with_address(space):
    region = factory.make_RegionController()
    iface = factory.make_Interface(node=region)
    cidr4 = factory.make_ipv4_network(24)
    subnet4 = factory.make_Subnet(space=space, cidr=cidr4)
    cidr6 = factory.make_ipv6_network(64)
    subnet6 = factory.make_Subnet(space=space, cidr=cidr6)
    sip4 = factory.make_StaticIPAddress(interface=iface, subnet=subnet4)
    sip6 = factory.make_StaticIPAddress(interface=iface, subnet=subnet6)
    return region, sip4, sip6


class TestRegionNetworkTimeProtocolService_Basic:
    """Basic tests for `RegionNetworkTimeProtocolService`."""

    def test_service_uses__tryUpdate_as_periodic_function(self):
        service = ntp.RegionNetworkTimeProtocolService(reactor)
        assert (service._tryUpdate, (), {}) == service.call

    def test_service_iterates_every_30_seconds(self):
        service = ntp.RegionNetworkTimeProtocolService(reactor)
        assert 30.0 == service.step


@pytest.mark.allow_transactions
@pytest.mark.usefixtures("maasdb")
class TestRegionNetworkTimeProtocolService:
    """Tests for `RegionNetworkTimeProtocolService`."""

    @transactional
    def make_example_configuration(self):
        # Configure example time references.
        ntp_servers = {factory.make_name("ntp-server") for _ in range(5)}
        Config.objects.set_config("ntp_servers", " ".join(ntp_servers))
        # Populate the database with example peers.
        space = factory.make_Space()
        region, addr4, addr6 = make_region_with_address(space)
        MAAS_ID.set(region.system_id)
        peer1, addr1_4, addr1_6 = make_region_with_address(space)
        peer2, addr2_4, addr2_6 = make_region_with_address(space)
        # Return the servers and all possible peer IP addresses.
        return ntp_servers, {addr1_4.ip, addr1_6.ip, addr2_4.ip, addr2_6.ip}

    @wait_for_reactor
    @inlineCallbacks
    def test_tryUpdate_updates_ntp_server(self, mocker):
        service = ntp.RegionNetworkTimeProtocolService(reactor)
        refs, peers = yield deferToDatabase(self.make_example_configuration)
        configure_region = mocker.patch.object(
            ntp, "configure_region", autospec=True
        )
        restartService = mocker.patch.object(
            service_monitor, "restartService", autospec=True
        )
        yield service._tryUpdate()
        assert configure_region.call_count == 1
        (called_refs, called_peers) = configure_region.call_args[0]
        assert called_refs == refs
        assert peers >= called_peers

        restartService.assert_called_once_with("ntp_region")
        # If the configuration has not changed then a second call to
        # `_tryUpdate` does not result in another call to `configure_region`.
        configure_region.reset_mock()
        restartService.reset_mock()
        yield service._tryUpdate()
        configure_region.assert_not_called()
        restartService.assert_not_called()


@pytest.mark.allow_transactions
@pytest.mark.usefixtures("maasdb")
class TestRegionNetworkTimeProtocolService_Errors:
    """Tests for error handing in `RegionNetworkTimeProtocolService`."""

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
        service = ntp.RegionNetworkTimeProtocolService(reactor)
        broken_method = mocker.patch.object(service, method, autospec=True)
        broken_method.side_effect = factory.make_exception()

        # Ensure that we never actually execute against systemd or write an
        # actual configuration file.
        mocker.patch.object(
            ntp, "deferToThread", autospec=True
        ).side_effect = always_succeed_with(None)
        mocker.patch.object(service_monitor, "restartService", autospec=True)

        with TwistedLoggerFixture() as logger:
            yield service._tryUpdate()

        assert (
            "Failed to update NTP configuration.\nTraceback (most recent call last):"
            in logger.output
        )
        assert str(broken_method.side_effect) in logger.output


@pytest.mark.usefixtures("maasdb")
class TestRegionNetworkTimeProtocolService_Database:
    """Database tests for `RegionNetworkTimeProtocolService`."""

    def test_getConfiguration_returns_configuration_object(self):
        service = ntp.RegionNetworkTimeProtocolService(reactor)

        # Configure example time references.
        ntp_servers = {factory.make_name("ntp-server") for _ in range(5)}
        Config.objects.set_config("ntp_servers", " ".join(ntp_servers))

        # Put all addresses in the same space so they're mutually routable.
        space = factory.make_Space()
        # Populate the database with "this" region and an example peer.
        region, _, _ = make_region_with_address(space)
        MAAS_ID.set(region.system_id)
        peer, addr4, addr6 = make_region_with_address(space)

        observed = service._getConfiguration()
        assert isinstance(observed, ntp._Configuration)

        assert observed.references == ntp_servers
        assert {addr4.ip, addr6.ip} > observed.peers
