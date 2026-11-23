# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for common RPC code."""

import random
import re
from unittest.mock import ANY, sentinel

import pytest
from twisted.internet.defer import Deferred, inlineCallbacks
from twisted.internet.protocol import connectionDone
from twisted.internet.testing import StringTransport
from twisted.protocols import amp
from twisted.python.failure import Failure

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.deferred import extract_result
from maastesting.factory import factory
from maastesting.twisted import always_fail_with, TwistedLoggerFixture
from provisioningserver.prometheus.metrics import PROMETHEUS_METRICS
from provisioningserver.rpc import common
from provisioningserver.rpc.common import (
    ConnectionAuthStatus,
    RPCUnauthorizedException,
)
from provisioningserver.rpc.testing.doubles import (
    DummyConnection,
    FakeConnection,
    FakeConnectionToRegion,
)

wait_for_reactor = wait_for()


@pytest.mark.rack_reactor_guard
class TestClient:
    @pytest.fixture(autouse=True)
    def set_command(self):
        self.command = sentinel.command
        self.command.__name__ = "Command"  # needed for metrics labels

    def test_init(self):
        conn = DummyConnection()
        client = common.Client(conn)
        assert client._conn is conn

    def make_connection_and_client(self):
        conn = FakeConnectionToRegion()
        client = common.Client(conn)
        return conn, client

    def test_ident(self):
        conn, client = self.make_connection_and_client()
        conn.ident = factory.make_name("ident")
        assert conn.ident == client.ident

    def test_localIdent(self):
        conn, client = self.make_connection_and_client()
        conn.localIdent = factory.make_name("localIdent")
        assert conn.localIdent == client.localIdent

    def test_localIdent_for_IConnection(self):
        conn = FakeConnection()
        client = common.Client(conn)
        with pytest.raises(
            NotImplementedError, match=".* only available in the rack\\b"
        ):
            client.localIdent  # noqa: B018

    def test_address(self):
        conn, client = self.make_connection_and_client()
        conn.address = factory.make_name("address")
        assert conn.address == client.address

    def test_address_for_IConnection(self):
        conn = FakeConnection()
        client = common.Client(conn)
        with pytest.raises(
            NotImplementedError, match=".* only available in the rack\\b"
        ):
            client.address  # noqa: B018

    @wait_for(timeout=get_testing_timeout())
    def test_call_no_timeout(self, mocker):
        conn, client = self.make_connection_and_client()
        mocker.patch.object(conn, "callRemote", autospec=True)
        conn.callRemote.return_value = sentinel.response
        response = client(
            self.command, _timeout=None, foo=sentinel.foo, bar=sentinel.bar
        )
        assert response is sentinel.response
        conn.callRemote.assert_called_once_with(
            self.command, foo=sentinel.foo, bar=sentinel.bar
        )

    @wait_for(timeout=get_testing_timeout())
    def test_call_zero_timeout(self, mocker):
        conn, client = self.make_connection_and_client()
        mocker.patch.object(conn, "callRemote", autospec=True)
        conn.callRemote.return_value = sentinel.response
        response = client(
            self.command, _timeout=0, foo=sentinel.foo, bar=sentinel.bar
        )
        assert response is sentinel.response
        conn.callRemote.assert_called_once_with(
            self.command, foo=sentinel.foo, bar=sentinel.bar
        )

    @wait_for(timeout=get_testing_timeout())
    def test_call_default_timeout(self, mocker):
        conn, client = self.make_connection_and_client()
        mock_defer_with_timeout = mocker.patch.object(
            common, "deferWithTimeout", autospec=True
        )
        mock_defer_with_timeout.return_value = sentinel.response
        response = client(self.command, foo=sentinel.foo, bar=sentinel.bar)
        assert response is sentinel.response
        mock_defer_with_timeout.assert_called_once_with(
            120,
            conn.callRemote,
            self.command,
            foo=sentinel.foo,
            bar=sentinel.bar,
        )

    @wait_for(timeout=get_testing_timeout())
    def test_call_custom_timeout(self, mocker):
        conn, client = self.make_connection_and_client()
        timeout = random.randint(10, 20)
        mock_defer_with_timeout = mocker.patch.object(
            common, "deferWithTimeout", autospec=True
        )
        mock_defer_with_timeout.return_value = sentinel.response
        response = client(
            self.command,
            _timeout=timeout,
            foo=sentinel.foo,
            bar=sentinel.bar,
        )
        assert response is sentinel.response
        mock_defer_with_timeout.assert_called_once_with(
            timeout,
            conn.callRemote,
            self.command,
            foo=sentinel.foo,
            bar=sentinel.bar,
        )

    @wait_for(timeout=get_testing_timeout())
    def test_call_with_keyword_arguments_raises_useful_error(self):
        conn = DummyConnection()
        client = common.Client(conn)
        expected_message = re.escape(
            "provisioningserver.rpc.common.Client called with 3 positional "
            "arguments, (1, 2, 3), but positional arguments are not "
            "supported. Usage: client(command, arg1=value1, ...)"
        )
        with pytest.raises(TypeError, match=expected_message):
            client(self.command, 1, 2, 3)

    @wait_for(timeout=get_testing_timeout())
    def test_call_records_latency_metric(self, mocker):
        mock_metrics = mocker.patch.object(PROMETHEUS_METRICS, "update")
        conn, client = self.make_connection_and_client()
        mocker.patch.object(conn, "callRemote", autospec=True)
        conn.callRemote.return_value = sentinel.response
        client(self.command, _timeout=None, foo=sentinel.foo, bar=sentinel.bar)
        mock_metrics.assert_called_with(
            "maas_rack_region_rpc_call_latency",
            "observe",
            labels={"call": "Command"},
            value=ANY,
        )

    @wait_for(timeout=get_testing_timeout())
    def test_getHostCertificate(self):
        conn, client = self.make_connection_and_client()
        conn.hostCertificate = sentinel.hostCertificate
        assert client.getHostCertificate() is sentinel.hostCertificate

    @wait_for(timeout=get_testing_timeout())
    def test_getPeerCertificate(self):
        conn, client = self.make_connection_and_client()
        conn.peerCertificate = sentinel.peerCertificate
        assert client.getPeerCertificate() is sentinel.peerCertificate

    @wait_for(timeout=get_testing_timeout())
    def test_isSecure(self):
        conn, client = self.make_connection_and_client()
        conn.peerCertificate = sentinel.peerCertificate
        assert client.isSecure()

    @wait_for(timeout=get_testing_timeout())
    def test_isSecure_not(self):
        conn, client = self.make_connection_and_client()
        conn.peerCertificate = None
        assert not client.isSecure()

    def test_eq__(self):
        conn, client = self.make_connection_and_client()
        assert client == client
        client_for_same_connection = common.Client(conn)
        assert client_for_same_connection == client
        _, client_for_another_connection = self.make_connection_and_client()
        assert client_for_another_connection != client

    def test_hash__(self):
        conn, client = self.make_connection_and_client()
        # The hash of a common.Client object is that of its connection.
        assert hash(client) == hash(conn)


class TestRPCProtocol:
    def test_init(self):
        protocol = common.RPCProtocol()
        assert isinstance(protocol.onConnectionMade, Deferred)
        assert not protocol.onConnectionMade.called
        assert isinstance(protocol.onConnectionLost, Deferred)
        assert not protocol.onConnectionLost.called
        assert isinstance(protocol, amp.AMP)

    def test_onConnectionMade_fires_when_connection_is_made(self):
        protocol = common.RPCProtocol()
        protocol.connectionMade()
        assert isinstance(protocol.onConnectionMade, Deferred)
        assert protocol.onConnectionMade.called

    def test_onConnectionLost_fires_when_connection_is_lost(self):
        protocol = common.RPCProtocol()
        protocol.makeConnection(StringTransport())
        protocol.connectionLost(connectionDone)
        assert isinstance(protocol.onConnectionLost, Deferred)
        assert protocol.onConnectionLost.called

    def test_unhandled_error_handler_closed(self, mocker):
        """
        Test the unhandledError method when the handler is closed.
        """
        amp_unhandledError = mocker.patch.object(
            amp.AMP, "unhandledError", autospec=True
        )

        protocol = common.RPCProtocol()

        fake_failure = Failure(
            RuntimeError(
                "unable to perform operation on <UVPoll closed=True 0x7f3506bd4c10>; the handler is closed"
            )
        )

        protocol.unhandledError(fake_failure)

        amp_unhandledError.assert_called_once()

    def test_unhandled_error_generic(self, mocker):
        """
        Test the unhandledError method for a generic failure.
        """
        amp_unhandledError = mocker.patch.object(
            amp.AMP, "unhandledError", autospec=True
        )

        protocol = common.RPCProtocol()

        fake_failure = Failure(Exception("Some generic error"))

        protocol.unhandledError(fake_failure)

        amp_unhandledError.assert_not_called()


class TestConnectionAuthStatus:
    def test_default_auth_status(self):
        auth_status = ConnectionAuthStatus()
        assert auth_status.is_authenticated is False

    def test_set_is_authenticated(self):
        auth_status = ConnectionAuthStatus(True)
        assert auth_status.is_authenticated is True
        auth_status.set_is_authenticated(False)
        assert auth_status.is_authenticated is False


@pytest.mark.rack_reactor_guard
class TestSecuredRPCProtocol:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        mocker.patch.object(
            common.RPCProtocol,
            "dispatchCommand",
            lambda *args, **kwargs: True,
        )

    @wait_for_reactor
    @inlineCallbacks
    def test_unauthenticated_connection_is_dropped(self, mocker):
        protocol = common.SecuredRPCProtocol(
            unauthenticated_commands=[],
            auth_status=ConnectionAuthStatus(False),
        )
        protocol.makeConnection(StringTransport())

        seq = b"%d" % random.randrange(0, 2**32)
        cmd = factory.make_string().encode("ascii")
        box = amp.AmpBox(_ask=seq, _command=cmd)
        mocker.patch.object(common, "pause", lambda *args, **kwargs: True)
        with pytest.raises(
            RPCUnauthorizedException,
            match="The RPC command requires authentication. ",
        ):
            yield protocol.dispatchCommand(box)

    @wait_for_reactor
    @inlineCallbacks
    def test_authenticated_connection(self):
        protocol = common.SecuredRPCProtocol(
            unauthenticated_commands=[], auth_status=ConnectionAuthStatus(True)
        )
        protocol.makeConnection(StringTransport())

        seq = b"%d" % random.randrange(0, 2**32)
        cmd = factory.make_string().encode("ascii")
        box = amp.AmpBox(_ask=seq, _command=cmd)

        result = yield protocol.dispatchCommand(box)
        assert result is True

    @wait_for_reactor
    @inlineCallbacks
    def test_unauthenticated_command(self):
        cmd = factory.make_string()
        protocol = common.SecuredRPCProtocol(
            unauthenticated_commands=[cmd.encode("ascii")],
            auth_status=ConnectionAuthStatus(False),
        )
        protocol.makeConnection(StringTransport())

        seq = b"%d" % random.randrange(0, 2**32)
        box = amp.AmpBox(_ask=seq, _command=cmd.encode("ascii"))

        result = yield protocol.dispatchCommand(box)
        assert result is True

    @wait_for_reactor
    @inlineCallbacks
    def test_connection_is_trusted_after_retries(self, mocker):
        cmd = factory.make_string()
        auth_status = ConnectionAuthStatus(False)
        protocol = common.SecuredRPCProtocol(
            unauthenticated_commands=[],
            auth_status=auth_status,
        )
        protocol.makeConnection(StringTransport())

        seq = b"%d" % random.randrange(0, 2**32)
        box = amp.AmpBox(_ask=seq, _command=cmd.encode("ascii"))

        class Pauser:
            def __init__(self):
                self.retry = 0
                self.calls = []

            def mock(self, time):
                self.retry += 1
                # At the last try, simulate that the connection become trusted
                if self.retry == 4:
                    auth_status.set_is_authenticated(True)
                self.calls.append(time)

        pauser = Pauser()
        mocker.patch.object(common, "pause", lambda time: pauser.mock(time))

        result = yield protocol.dispatchCommand(box)
        assert result is True
        assert pauser.retry == 4
        # exponential backoff
        assert pauser.calls == [0.0, 0.5, 1.5, 3.5]


@pytest.mark.rack_reactor_guard
class TestRPCProtocol_UnhandledErrorsWhenHandlingResponses:
    answer_seq = b"%d" % random.randrange(0, 2**32)
    answer_box = amp.AmpBox(_answer=answer_seq)

    error_seq = b"%d" % random.randrange(0, 2**32)
    error_box = amp.AmpBox(
        _error=error_seq,
        _error_code=amp.UNHANDLED_ERROR_CODE,
        _error_description=factory.make_string(),
    )

    @pytest.mark.parametrize(
        "seq, box",
        [(answer_seq, answer_box), (error_seq, error_box)],
        ids=["_answerReceived", "_errorReceived"],
    )
    def test_unhandled_errors_logged_and_do_not_cause_disconnection(
        self, seq, box, mocker
    ):
        mocker.patch.object(common.log, "debug")
        protocol = common.RPCProtocol()
        protocol.makeConnection(StringTransport())
        # Poke a request into the dispatcher that will always fail.
        d = Deferred().addCallback(lambda _: 0 / 0)
        protocol._outstandingRequests[seq] = d
        # Push a box in response to the request.
        with TwistedLoggerFixture() as logger:
            protocol.ampBoxReceived(box)
        # The Deferred does not have a dangling error.
        assert extract_result(d) is None
        # The transport is still connected.
        assert not protocol.transport.disconnecting
        # The error has been logged.
        assert (
            "Unhandled failure during AMP request. This is probably a bug. "
            "Please ensure that this error is handled within application code.\n"
            "Traceback (most recent call last):"
        ) in logger.output


class TestRPCProtocol_UnhandledErrorsWhenHandlingCommands:
    def test_unhandled_errors_do_not_cause_disconnection(self, mocker):
        mocker.patch.object(common.log, "debug")
        protocol = common.RPCProtocol()
        protocol.makeConnection(StringTransport())
        # Ensure that the superclass dispatchCommand() will fail.
        dispatchCommand = mocker.patch.object(amp.AMP, "dispatchCommand")
        dispatchCommand.side_effect = always_fail_with(ZeroDivisionError())
        # Push a command box into the protocol.
        seq = b"%d" % random.randrange(0, 2**32)
        cmd = factory.make_string().encode("ascii")
        box = amp.AmpBox(_ask=seq, _command=cmd)
        with TwistedLoggerFixture() as logger:
            protocol.ampBoxReceived(box)
        # The transport is still connected.
        assert not protocol.transport.disconnecting
        # The error has been logged on the originating side of the AMP
        # session, along with an explanatory message. The message includes a
        # command reference.
        cmd_ref = common.make_command_ref(box)
        assert (
            "Unhandled failure dispatching AMP command. This is probably a bug. "
            "Please ensure that this error is handled within application code or "
            f"declared in the signature of the {cmd} command. [{cmd_ref}]\n"
            "Traceback (most recent call last):"
        ) in logger.output
        # A simpler error message has been transmitted over the wire. It
        # includes the same command reference as logged locally.
        protocol.transport.io.seek(0)
        observed_boxes_sent = amp.parse(protocol.transport.io)
        expected_boxes_sent = [
            amp.AmpBox(
                _error=seq,
                _error_code=amp.UNHANDLED_ERROR_CODE,
                _error_description=(
                    b"Unknown Error [%s]" % cmd_ref.encode("ascii")
                ),
            )
        ]
        assert expected_boxes_sent == observed_boxes_sent


class TestMakeCommandRef:
    """Tests for `common.make_command_ref`."""

    def test_command_ref_includes_host_pid_command_and_ask_sequence(
        self, mocker
    ):
        host = factory.make_name("hostname")
        pid = random.randint(99, 9999999)
        cmd = factory.make_name("command").encode("ascii")
        ask = str(random.randint(99, 9999999)).encode("ascii")
        box = amp.AmpBox(_command=cmd, _ask=ask)

        mocker.patch.object(common, "gethostname", return_value=host)
        mocker.patch.object(common, "getpid", return_value=pid)

        assert common.make_command_ref(box) == (
            "%s:pid=%s:cmd=%s:ask=%s"
            % (host, pid, cmd.decode("ascii"), ask.decode("ascii"))
        )

    def test_replaces_missing_ask_with_none(self, mocker):
        box = amp.AmpBox(_command=b"command")

        mocker.patch.object(common, "gethostname", return_value="host")
        mocker.patch.object(common, "getpid", return_value=1234)

        assert "host:pid=1234:cmd=command:ask=none" == common.make_command_ref(
            box
        )
