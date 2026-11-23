# Copyright 2013-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for dhcp/detect.py"""

import errno
import random
import re
import socket
from unittest import mock
from unittest.mock import call

import pytest
from twisted.internet import reactor
from twisted.internet.defer import (
    CancelledError,
    DeferredList,
    inlineCallbacks,
)
from twisted.internet.task import Clock, deferLater
from twisted.python.failure import Failure

from maastesting.crochet import wait_for
from maastesting.factory import factory
from maastesting.twisted import TwistedLoggerFixture
import provisioningserver.dhcp.detect as detect_module
from provisioningserver.dhcp.detect import (
    BOOTP_CLIENT_PORT,
    BOOTP_SERVER_PORT,
    DHCP_REQUEST_TIMING,
    DHCPDiscoverPacket,
    DHCPProbeException,
    DHCPRequestMonitor,
    DHCPServer,
    get_interface_ip,
    get_interface_mac,
    InterfaceNotFound,
    IPAddressNotAvailable,
    MACAddressNotAvailable,
    make_dhcp_transaction_id,
    probe_interface,
    send_dhcp_request_packet,
    udp_socket,
)


@pytest.fixture
def logger():
    with TwistedLoggerFixture() as captured:
        yield captured


class TestMakeDHCPTransactionID:
    def test_produces_well_formed_id(self):
        # The DHCP transaction ID should be 4 bytes long.
        transaction_id = make_dhcp_transaction_id()
        assert isinstance(transaction_id, bytes)
        assert 4 == len(transaction_id)

    def test_randomises(self):
        assert make_dhcp_transaction_id() != make_dhcp_transaction_id()


class TestDHCPDiscoverPacket:
    def test_init_sets_transaction_id(self, mocker):
        transaction_id = make_dhcp_transaction_id()
        mocker.patch.object(
            detect_module, "make_dhcp_transaction_id"
        ).return_value = transaction_id
        discover = DHCPDiscoverPacket(factory.make_mac_address())
        assert transaction_id == discover.transaction_id

    def test_init_sets_mac_bytes(self):
        mac = factory.make_mac_address()
        discover = DHCPDiscoverPacket(mac)
        assert discover.mac_string_to_bytes(mac) == discover.mac_bytes

    def test_packet_property_after_init_with_mac_and_no_transaction_id(self):
        discover = DHCPDiscoverPacket(factory.make_mac_address())
        assert discover.packet is not None

    def test_converts_byte_string_to_bytes(self):
        discover = DHCPDiscoverPacket
        expected = b"\x01\x22\x33\x99\xaa\xff"
        input = "01:22:33:99:aa:ff"
        assert expected == discover.mac_string_to_bytes(input)

    def test_builds_packet(self):
        mac = factory.make_mac_address()
        seconds = random.randint(0, 1024)
        xid = factory.make_bytes(4)
        discover = DHCPDiscoverPacket(
            transaction_id=xid, mac=mac, seconds=seconds
        )
        seconds_bytes = seconds.to_bytes(2, "big")
        expected = (
            b"\x01\x01\x06\x00"
            + xid
            + seconds_bytes
            + b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            + b"\x00\x00\x00\x00\x00\x00"
            + discover.mac_bytes
            + b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
            + b"\x00" * 67
            + b"\x00" * 125
            + b"\x63\x82\x53\x63\x35\x01\x01"
            + discover.client_uid_option
            + b"\x37\x03\x03\x01\x06\xff"
        )
        assert expected == discover.packet


class TestGetInterfaceMAC:
    """Tests for `get_interface_mac`."""

    def test_loopback_has_zero_mac(self):
        # It's a lame test, but what other network interfaces can we reliably
        # test this on?
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        assert "00:00:00:00:00:00" == get_interface_mac(sock, "lo")

    def test_invalid_interface_raises_interfacenotfound(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        with pytest.raises(InterfaceNotFound, match="not found"):
            get_interface_mac(sock, factory.make_unicode_string(size=15))

    def test_no_mac_raises_macaddressnotavailable(self, mocker):
        mock_ioerror = IOError()
        mock_ioerror.errno = errno.EOPNOTSUPP
        mocker.patch.object(
            detect_module.fcntl, "ioctl"
        ).side_effect = mock_ioerror
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Drive-by test for the strerror() call.
        with pytest.raises(MACAddressNotAvailable, match="not supported"):
            get_interface_mac(sock, "lo")


class TestGetInterfaceIP:
    """Tests for `get_interface_ip`."""

    def test_loopback_has_localhost_address(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        assert "127.0.0.1" == get_interface_ip(sock, "lo")

    def test_invalid_interface_raises_interfacenotfound(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        with pytest.raises(detect_module.InterfaceNotFound, match="not found"):
            get_interface_ip(sock, factory.make_unicode_string(size=15))

    def test_no_ip_raises_ipaddressnotavailable(self, mocker):
        mock_ioerror = IOError()
        mock_ioerror.errno = errno.EADDRNOTAVAIL
        mocker.patch.object(
            detect_module.fcntl, "ioctl"
        ).side_effect = mock_ioerror
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        with pytest.raises(IPAddressNotAvailable, match="No IP address"):
            get_interface_ip(sock, "lo")

    def test_unknown_errno_ip_raises_ipaddressnotavailable(self, mocker):
        mock_ioerror = IOError()
        mock_ioerror.errno = errno.EACCES
        mocker.patch.object(
            detect_module.fcntl, "ioctl"
        ).side_effect = mock_ioerror
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Drive-by test for the strerror() call.
        with pytest.raises(
            IPAddressNotAvailable, match="Failed.*Permission denied."
        ):
            get_interface_ip(sock, "lo")


def patch_socket(mocker):
    """Patch `socket.socket` to return a mock."""
    sock = mock.MagicMock()
    mocker.patch.object(
        detect_module.socket, "socket", mock.MagicMock(return_value=sock)
    )
    return sock


class TestUDPSocket:
    """Tests for `udp_socket`."""

    def test_yields_open_socket(self, mocker):
        patch_socket(mocker)
        with udp_socket() as sock:
            socket_calls = list(socket.socket.mock_calls)
            close_calls = list(sock.close.mock_calls)
        assert [mock.call(socket.AF_INET, socket.SOCK_DGRAM)] == socket_calls
        assert [] == close_calls

    def test_closes_socket_on_exit(self, mocker):
        patch_socket(mocker)
        with udp_socket() as sock:
            pass
        assert [mock.call()] == sock.close.mock_calls

    def test_sets_reuseaddr(self, mocker):
        patch_socket(mocker)
        with udp_socket() as sock:
            pass
        assert [
            mock.call(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ] == sock.setsockopt.mock_calls


class TestSendDHCPRequestPacket:
    def test_sends_expected_packet(self, mocker):
        mock_socket = patch_socket(mocker)
        mock_socket.bind = mock.MagicMock()
        mock_socket.sendto = mock.MagicMock()
        mocker.patch.object(
            detect_module, "get_interface_ip"
        ).return_value = "127.0.0.1"
        mocker.patch.object(
            detect_module, "get_interface_mac"
        ).return_value = "00:00:00:00:00:00"
        request = DHCPDiscoverPacket()
        send_dhcp_request_packet(request, "lo")
        mock_socket.bind.assert_called_once_with(
            ("127.0.0.1", BOOTP_CLIENT_PORT)
        )
        mock_socket.sendto.assert_called_once_with(
            request.packet, ("<broadcast>", BOOTP_SERVER_PORT)
        )


def make_Failure(exception_type, *args, **kwargs):
    try:
        raise exception_type(*args, **kwargs)
    except Exception:
        return Failure()


@pytest.mark.rack_reactor_guard
class TestDHCPRequestMonitor:
    def test_send_requests_and_await_replies(self, mocker, logger):
        # This test is a bit large because it covers the entire functionality
        # of the `send_requests_and_await_replies()` method. (It could be
        # split apart into multiple tests, but the large amount of setup work
        # and interdependencies makes that a maintenance burden.)
        mock_socket = patch_socket(mocker)
        mock_socket.bind = mock.MagicMock()
        mock_socket.recvfrom = mock.MagicMock()
        mock_socket.setsockopt = mock.MagicMock()
        mock_socket.settimeout = mock.MagicMock()
        # Pretend we were successful at deferring the DHCP requests.
        mocker.patch.object(
            detect_module, "blockingCallFromThread", autospec=True
        )
        # This method normally blocks for ~10 seconds, so take control of the
        # monotonic clock and make sure the last call to `recvfrom()` happens
        # just as we hit the reply timeout.
        mock_time_monotonic = mocker.patch.object(
            detect_module.time, "monotonic"
        )
        mock_time_monotonic.side_effect = (
            # Start time (before loop starts).
            10,
            # First reply (truncated packet).
            11,
            # Second reply (not a match to our transaction).
            12,
            # Third reply (Matching reply with server identifier option).
            13,
            # First socket timeout (need to make sure the loop continues).
            14,
            # Second socket timeout (hey, we're done!).
            10 + detect_module.REPLY_TIMEOUT,
        )
        mock_xid = factory.make_bytes(4)
        valid_dhcp_reply = factory.make_dhcp_packet(
            transaction_id=mock_xid,
            include_server_identifier=True,
            server_ip="127.1.1.1",
        )
        mock_get_xid = mocker.patch.object(
            detect_module, "make_dhcp_transaction_id"
        )
        mock_get_xid.return_value = mock_xid
        # Valid DHCP packet, but not a match because it doesn't have a
        # Server Identifier option.
        valid_non_match = DHCPDiscoverPacket(
            mac="01:02:03:04:05:06", transaction_id=mock_xid
        ).packet
        mock_socket.recvfrom.side_effect = (
            # Truncated packet, to test logging.
            (b"", ("127.0.0.1", BOOTP_SERVER_PORT)),
            (valid_non_match, ("127.0.0.2", BOOTP_SERVER_PORT)),
            (valid_dhcp_reply, ("127.0.0.3", BOOTP_SERVER_PORT)),
            socket.timeout,
            socket.timeout,
        )
        monitor = DHCPRequestMonitor("lo", Clock())
        result = monitor.send_requests_and_await_replies()
        mock_socket.setsockopt.assert_has_calls(
            [
                call(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1),
                call(socket.SOL_SOCKET, socket.SO_BROADCAST, 1),
            ]
        )
        mock_socket.bind.assert_called_once_with(("", 68))
        mock_socket.settimeout.assert_called_once_with(
            detect_module.SOCKET_TIMEOUT
        )
        mock_socket.recvfrom.assert_has_calls(
            [call(2048), call(2048), call(2048), call(2048), call(2048)]
        )
        # One of the response packets was truncated.
        assert (
            "Invalid DHCP response received from 127.0.0.1 on 'lo': Truncated DHCP packet."
            in logger.messages
        )
        # Ensure we record the fact that the reply packet came from a different
        # IP address than the server claimed to be.
        assert {DHCPServer("127.1.1.1", "127.0.0.3")} == result

    @wait_for(timeout=5)
    @inlineCallbacks
    def test_cancelAll(self):
        errbacks_called = [0]

        def mock_errback(result: Failure):
            assert result.check(CancelledError)
            errbacks_called[0] += 1

        a = deferLater(reactor, 6, lambda: "a")
        b = deferLater(reactor, 6, lambda: "b")
        a.addBoth(mock_errback)
        b.addBoth(mock_errback)
        deferreds = [a, b]
        DHCPRequestMonitor.cancelAll(deferreds)
        deferredList = DeferredList(deferreds)
        yield deferredList
        assert 2 == errbacks_called[0]

    @wait_for(timeout=5)
    @inlineCallbacks
    def test_deferredDHCPRequestErrback_cancels_all_on_FirstError(
        self, mocker
    ):
        mock_cancelAll = mocker.patch.object(DHCPRequestMonitor, "cancelAll")

        def raise_ioerror():
            raise OSError()

        a = deferLater(reactor, 0.0, raise_ioerror)
        b = deferLater(reactor, 6, lambda: "b")
        monitor = DHCPRequestMonitor("lo")
        monitor.deferredDHCPRequests = [a, b]
        deferredList = DeferredList(
            monitor.deferredDHCPRequests,
            consumeErrors=True,
            fireOnOneErrback=True,
        )
        deferredList.addErrback(monitor.deferredDHCPRequestErrback)
        yield deferredList
        # Still have one call left in the reactor, since we mocked cancelAll().
        b.cancel()
        mock_cancelAll.assert_called_once_with(([a, b]))

    def test_deferredDHCPRequestErrback_logs_known_exceptions(self, logger):
        monitor = DHCPRequestMonitor("lo")
        error = factory.make_string()
        monitor.deferredDHCPRequestErrback(
            make_Failure(DHCPProbeException, error)
        )
        assert [f"DHCP probe failed. {error}"] == logger.messages

    def test_deferredDHCPRequestErrback_logs_unknown_exceptions(self, logger):
        monitor = DHCPRequestMonitor("lo")
        error = factory.make_string()
        monitor.deferredDHCPRequestErrback(make_Failure(IOError, error))
        assert [
            "DHCP probe on 'lo' failed with an unknown error."
        ] == logger.messages
        assert re.search(rf"(?ms)Traceback.*{error}", logger.output)

    def test_deferredDHCPRequestErrback_ignores_cancelled(self, logger):
        monitor = DHCPRequestMonitor("lo")
        error = factory.make_string()
        monitor.deferredDHCPRequestErrback(make_Failure(CancelledError, error))
        assert [] == logger.messages

    def test_deferDHCPRequests(self, mocker):
        clock = Clock()
        monitor = DHCPRequestMonitor("lo", clock)
        mock_deferLater = mocker.patch.object(detect_module, "deferLater")
        mock_DeferredList = mocker.patch.object(detect_module, "DeferredList")

        def _generate_expected_calls():
            for seconds in DHCP_REQUEST_TIMING:
                yield call(
                    clock,
                    seconds + 0.1,
                    send_dhcp_request_packet,
                    DHCPDiscoverPacket(
                        transaction_id=monitor.transaction_id, seconds=seconds
                    ),
                    "lo",
                )
                # each call should have an errback
                yield call().addErrback(monitor.deferredDHCPRequestErrback)

        expected_calls = list(_generate_expected_calls())
        monitor.deferDHCPRequests()
        mock_deferLater.assert_has_calls(expected_calls)
        mock_DeferredList.assert_called_once_with(
            monitor.deferredDHCPRequests,
            fireOnOneErrback=True,
            consumeErrors=True,
        )
        # Expect addErrback to be called both on each individual Deferred, plus
        # one more time on the DeferredList.
        mock_DeferredList.return_value.addErrback.assert_called_once_with(
            monitor.deferredDHCPRequestErrback
        )

    @wait_for(timeout=5)
    @inlineCallbacks
    def test_run_logs_result_and_makes_properties_available(
        self, mocker, logger
    ):
        monitor = DHCPRequestMonitor("lo")
        mock_send_and_await = mocker.patch.object(
            monitor, "send_requests_and_await_replies"
        )
        mock_send_and_await.return_value = {
            DHCPServer("127.0.0.1", "127.0.0.1"),
            DHCPServer("127.1.1.1", "127.2.2.2"),
        }
        yield monitor.run()
        mock_send_and_await.assert_called_once_with()
        assert (
            "External DHCP server(s) discovered on interface 'lo': 127.0.0.1, 127.1.1.1 (via 127.2.2.2)"
            in logger.messages
        )
        assert {"127.0.0.1", "127.1.1.1"} == monitor.dhcp_servers
        assert {"127.0.0.1", "127.2.2.2"} == monitor.dhcp_addresses

    @wait_for(timeout=5)
    @inlineCallbacks
    def test_run_skips_logging_if_no_servers_found(self, mocker, logger):
        monitor = DHCPRequestMonitor("lo")
        mock_send_and_await = mocker.patch.object(
            monitor, "send_requests_and_await_replies"
        )
        mock_send_and_await.return_value = {}
        yield monitor.run()
        mock_send_and_await.assert_called_once_with()
        assert logger.messages == []

    @wait_for(timeout=5)
    @inlineCallbacks
    def test_run_via_probe_interface_returns_servers(self, mocker):
        mock_send_and_await = mocker.patch.object(
            DHCPRequestMonitor, "send_requests_and_await_replies"
        )
        mock_send_and_await.return_value = {
            DHCPServer("127.0.0.1", "127.0.0.1"),
            DHCPServer("127.1.1.1", "127.2.2.2"),
        }
        result = yield probe_interface("lo")
        mock_send_and_await.assert_called_once_with()
        assert {"127.0.0.1", "127.1.1.1"} == result
