# Copyright 2014-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the region's RPC implementation."""

from collections import defaultdict
import json
from os import urandom
import random
import re
from unittest import skip
from unittest.mock import ANY, call, MagicMock, Mock, sentinel

from django.db import IntegrityError
import pytest
from twisted.application.service import Service
from twisted.internet import reactor, tcp
from twisted.internet.address import IPv4Address
from twisted.internet.defer import (
    CancelledError,
    Deferred,
    DeferredList,
    fail,
    inlineCallbacks,
    maybeDeferred,
    succeed,
)
from twisted.internet.endpoints import TCP4ServerEndpoint
from twisted.internet.error import ConnectionClosed
from twisted.internet.interfaces import IStreamServerEndpoint
from twisted.internet.protocol import Factory
from twisted.protocols import amp
from twisted.python.failure import Failure
from twisted.python.reflect import fullyQualifiedName
from zope.interface.verify import verifyObject

from maasserver.models import RackController
from maasserver.models.trustedsshhostkey import TrustedSshHostKey
from maasserver.rpc import regionservice
from maasserver.rpc.regionservice import (
    RackClient,
    Region,
    RegionServer,
    RegionService,
)
from maasserver.rpc.testing.doubles import HandshakingRegionServer
from maasserver.secrets import SecretManager
from maasserver.security import get_shared_secret
from maasserver.testing.factory import factory
from maasserver.utils.orm import transactional
from maasserver.utils.threads import deferToDatabase
from maastesting.crochet import wait_for
from maastesting.deferred import extract_result
from maastesting.twisted import (
    always_fail_with,
    always_succeed_with,
    TwistedLoggerFixture,
)
from metadataserver.builtin_scripts import load_builtin_scripts
from provisioningserver.prometheus.metrics import PROMETHEUS_METRICS
from provisioningserver.rpc import cluster, exceptions
from provisioningserver.rpc.exceptions import (
    CannotRegisterRackController,
    NoConnectionsAvailable,
)
from provisioningserver.rpc.interfaces import IConnection
from provisioningserver.rpc.region import RegisterRackController
from provisioningserver.rpc.testing import call_responder
from provisioningserver.rpc.testing.doubles import DummyConnection
from provisioningserver.security import calculate_digest, fernet_decrypt_psk
from provisioningserver.utils import events
from provisioningserver.utils.env import MAAS_SECRET
from provisioningserver.utils.version import get_running_version

wait_for_reactor = wait_for()


@pytest.mark.usefixtures("maasdb")
class TestRegionServer:
    @pytest.fixture(autouse=True)
    def _setup_and_cleanup(self, request, maasdb, mocker):
        load_builtin_scripts()
        yield
        # Clean up database state to prevent leakage between tests
        from maasserver.models import Node, ScriptSet, TrustedSshHostKey

        # Clear FK references before deleting, in the right order
        Node.objects.filter(
            current_commissioning_script_set__isnull=False
        ).update(current_commissioning_script_set=None)
        Node.objects.filter(
            current_installation_script_set__isnull=False
        ).update(current_installation_script_set=None)
        Node.objects.filter(current_release_script_set__isnull=False).update(
            current_release_script_set=None
        )
        Node.objects.filter(
            current_deployment_script_set__isnull=False
        ).update(current_deployment_script_set=None)
        TrustedSshHostKey.objects.all().delete()
        ScriptSet.objects.all().delete()
        RackController.objects.all().delete()
        Node.objects.all().delete()

    def test_auth_status(self):
        protocol = RegionServer()
        assert not protocol.auth_status.is_authenticated

    def test_interfaces(self, mocker):
        protocol = RegionServer()
        # transport.getHandle() is used by AMP._getPeerCertificate, which we
        # call indirectly via the peerCertificate attribute in IConnection.
        mocker.patch.object(protocol, "transport")
        verifyObject(IConnection, protocol)

    def test_connectionMade_does_not_update_services_connection_set(self):
        service = RegionService(sentinel.ipcWorker)
        service.running = True  # Pretend it's running.
        service.factory.protocol = HandshakingRegionServer
        protocol = service.factory.buildProtocol(addr=None)  # addr is unused.
        assert {} == service.connections
        protocol.connectionMade()
        assert {} == service.connections

    def test_connectionMade_drops_connection_if_service_not_running(
        self, mocker
    ):
        service = RegionService(sentinel.ipcWorker)
        service.running = False  # Pretend it's not running.
        service.factory.protocol = HandshakingRegionServer
        protocol = service.factory.buildProtocol(addr=None)  # addr is unused.
        transport = mocker.patch.object(protocol, "transport")
        assert {} == service.connections
        protocol.connectionMade()
        # The protocol is not added to the connection set.
        assert {} == service.connections
        # The transport is instructed to lose the connection.
        transport.loseConnection.assert_called_with()

    def test_connectionLost_updates_services_connection_set(self, mocker):
        service = RegionService(sentinel.ipcWorker)
        service.running = True  # Pretend it's running.
        service.factory.protocol = HandshakingRegionServer
        protocol = service.factory.buildProtocol(addr=None)  # addr is unused.
        protocol.ident = factory.make_name("node")
        connectionLost_up_call = mocker.patch.object(amp.AMP, "connectionLost")
        service.connections[protocol.ident] = {protocol}

        protocol.connectionLost(reason=None)
        # The connection is removed from the set, but the key remains.
        assert {protocol.ident: set()} == service.connections
        # connectionLost() is called on the superclass.
        connectionLost_up_call.assert_called_once_with(None)

    def test_connectionLost_uses_ipcWorker_to_unregister(self, mocker):
        ipcWorker = MagicMock()
        service = RegionService(ipcWorker)
        service.running = True  # Pretend it's running.
        service.factory.protocol = HandshakingRegionServer
        protocol = service.factory.buildProtocol(addr=None)  # addr is unused.
        protocol.ident = factory.make_name("node")
        protocol.host = Mock()
        protocol.host.host = sentinel.host
        protocol.host.port = sentinel.port
        protocol.hostIsRemote = True
        connectionLost_up_call = mocker.patch.object(amp.AMP, "connectionLost")
        service.connections[protocol.ident] = {protocol}

        protocol.connectionLost(reason=None)
        ipcWorker.rpcUnregisterConnection.assert_called_once_with(
            protocol.connid
        )
        # The connection is removed from the set, but the key remains.
        assert {protocol.ident: set()} == service.connections
        # connectionLost() is called on the superclass.
        connectionLost_up_call.assert_called_once_with(None)

    def patch_authenticate_for_failure(self, client, mocker):
        authenticate = mocker.patch.object(
            client, "authenticateCluster", autospec=True
        )
        authenticate.side_effect = always_succeed_with(False)

    def patch_authenticate_for_error(self, client, exception, mocker):
        authenticate = mocker.patch.object(
            client, "authenticateCluster", autospec=True
        )
        authenticate.side_effect = always_fail_with(exception)

    def test_connectionMade_drops_connections_if_authentication_fails(
        self, mocker
    ):
        service = RegionService(sentinel.ipcWorker)
        service.running = True  # Pretend it's running.
        service.factory.protocol = HandshakingRegionServer
        protocol = service.factory.buildProtocol(addr=None)  # addr is unused.
        self.patch_authenticate_for_failure(protocol, mocker)
        transport = mocker.patch.object(protocol, "transport")
        assert {} == service.connections
        protocol.connectionMade()
        # The protocol is not added to the connection set.
        assert {} == service.connections
        # The transport is instructed to lose the connection.
        transport.loseConnection.assert_called_with()
        # Connection is not trusted
        assert not protocol.auth_status.is_authenticated

    def test_connectionMade_trusts_connection_if_authentication_succeeds(
        self, mocker
    ):
        service = RegionService(sentinel.ipcWorker)
        service.running = True  # Pretend it's running.
        service.factory.protocol = HandshakingRegionServer
        protocol = service.factory.buildProtocol(addr=None)  # addr is unused.
        assert not protocol.auth_status.is_authenticated

        transport = mocker.patch.object(protocol, "transport")
        transport.getPeer.return_value = IPv4Address(
            type="TCP", host="test", port=1337
        )

        assert not protocol.auth_status.is_authenticated
        assert {} == service.connections
        connectionMade = wait_for_reactor(protocol.connectionMade)
        connectionMade()
        # Connection is trusted
        assert protocol.auth_status.is_authenticated

    def test_connectionMade_drops_connections_if_authentication_errors(
        self, mocker
    ):
        with TwistedLoggerFixture() as logger:
            service = RegionService(sentinel.ipcWorker)
            service.running = True  # Pretend it's running.
            service.factory.protocol = HandshakingRegionServer
            protocol = service.factory.buildProtocol(
                addr=None
            )  # addr is unused.
            protocol.transport = MagicMock()
            exception_type = factory.make_exception_type()
            self.patch_authenticate_for_error(
                protocol, exception_type(), mocker
            )
            assert {} == service.connections

            connectionMade = wait_for_reactor(protocol.connectionMade)
            connectionMade()

        # The protocol is not added to the connection set.
        assert {} == service.connections
        # The transport is instructed to lose the connection.
        protocol.transport.loseConnection.assert_called_once_with()

        # The log was written to.
        assert logger.dump() == (
            "Rack controller 'None' could not be authenticated; dropping "
            "connection. Check that /var/snap/maas/common/maas/secret on "
            "the controller contains the correct shared key."
        )

    def test_handshakeFailed_does_not_log_when_connection_is_closed(self):
        server = RegionServer()
        with TwistedLoggerFixture() as logger:
            server.handshakeFailed(Failure(ConnectionClosed()))
        # Nothing was logged.
        assert "" == logger.output

    def make_handshaking_server(self):
        service = RegionService(sentinel.ipcWorker)
        service.running = True  # Pretend it's running.
        service.factory.protocol = HandshakingRegionServer
        return service.factory.buildProtocol(addr=None)  # addr is unused.

    def make_running_server(self, mocker):
        service = RegionService(sentinel.ipcWorker)
        service.running = True  # Pretend it's running.
        return service.factory.buildProtocol(addr=None)  # addr is unused.

    def test_authenticateCluster_accepts_matching_digests(self, mocker):
        server = self.make_running_server(mocker)

        def respond_as_rack(_, message):
            def got_secret(secret):
                salt = urandom(16)
                digest = calculate_digest(
                    secret, message, b"region-to-rack", salt
                )
                return {"digest": digest, "salt": salt}

            return maybeDeferred(get_shared_secret).addCallback(got_secret)

        callRemote = mocker.patch.object(server, "callRemote", autospec=True)
        callRemote.side_effect = respond_as_rack

        d = server.authenticateCluster()
        assert extract_result(d)

    def test_authenticateCluster_rejects_cross_role_digest(self, mocker):
        server = self.make_running_server(mocker)

        def respond_with_region_digest(_, message):
            return Region().authenticate(message)

        callRemote = mocker.patch.object(server, "callRemote", autospec=True)
        callRemote.side_effect = respond_with_region_digest

        d = server.authenticateCluster()
        assert not extract_result(d)

    def test_authenticateCluster_rejects_non_matching_digests(self, mocker):
        server = self.make_running_server(mocker)

        def respond_with_invalid_digest(_, message):
            response = {
                "digest": factory.make_bytes(),
                "salt": factory.make_bytes(),
            }
            return succeed(response)

        callRemote = mocker.patch.object(server, "callRemote", autospec=True)
        callRemote.side_effect = respond_with_invalid_digest

        d = server.authenticateCluster()
        assert not extract_result(d)

    def test_authenticateCluster_propagates_errors(self, mocker):
        server = self.make_running_server(mocker)
        exception_type = factory.make_exception_type()

        callRemote = mocker.patch.object(server, "callRemote", autospec=True)
        callRemote.side_effect = fail(exception_type())

        d = server.authenticateCluster()
        with pytest.raises(exception_type):
            extract_result(d)

    def make_Region(self, ipcWorker=None):
        if ipcWorker is None:
            ipcWorker = sentinel.ipcWorker
        patched_region = RegionServer()
        patched_region.factory = Factory.forProtocol(RegionServer)
        patched_region.factory.service = RegionService(ipcWorker)
        return patched_region

    def test_register_is_registered(self):
        protocol = RegionServer()
        responder = protocol.locateResponder(
            RegisterRackController.commandName
        )
        assert responder is not None

    def make_mock_rack_controller(self, system_id):
        rack = Mock()
        rack.system_id = system_id
        return rack

    @wait_for_reactor
    @inlineCallbacks
    def test_register_returns_system_id_and_uuid(self, mocker):
        uuid = "a-b-c"
        mocker.patch.object(
            regionservice, "GLOBAL_LABELS", {"maas_uuid": uuid}
        )

        system_id = factory.make_name("system_id")
        mock_rack = self.make_mock_rack_controller(system_id)
        mocker.patch.object(
            regionservice.rackcontrollers, "register"
        ).return_value = mock_rack
        MAAS_SECRET.set(factory.make_bytes())
        protocol = self.make_Region()
        protocol.transport = MagicMock()
        response = yield call_responder(
            protocol,
            RegisterRackController,
            {
                "system_id": system_id,
                "hostname": "test-host",
                "interfaces": {},
            },
        )
        assert system_id == response["system_id"]
        assert uuid == response["uuid"]

    @wait_for_reactor
    @inlineCallbacks
    def test_register_acks_beacon_support(self, mocker):
        system_id = factory.make_name("system_id")
        mock_rack = self.make_mock_rack_controller(system_id)
        mocker.patch.object(
            regionservice.rackcontrollers, "register"
        ).return_value = mock_rack
        MAAS_SECRET.set(factory.make_bytes())
        protocol = self.make_Region()
        protocol.transport = MagicMock()
        response = yield call_responder(
            protocol,
            RegisterRackController,
            {
                "system_id": system_id,
                "hostname": "test-host",
                "interfaces": {},
                "beacon_support": True,
            },
        )
        assert response["beacon_support"]

    @wait_for_reactor
    @inlineCallbacks
    def test_register_acks_version(self, mocker):
        system_id = factory.make_name("system_id")
        mock_rack = self.make_mock_rack_controller(system_id)
        mocker.patch.object(
            regionservice.rackcontrollers, "register"
        ).return_value = mock_rack
        MAAS_SECRET.set(factory.make_bytes())
        protocol = self.make_Region()
        protocol.transport = MagicMock()
        response = yield call_responder(
            protocol,
            RegisterRackController,
            {
                "system_id": system_id,
                "hostname": "test-host",
                "interfaces": {},
                "version": "2.3.0",
            },
        )
        assert response["version"] == str(get_running_version())

    @wait_for_reactor
    @inlineCallbacks
    def test_register_returns_cluster_certificates(self, mocker):
        system_id = factory.make_name("system_id")
        mock_rack = self.make_mock_rack_controller(system_id)
        mocker.patch.object(
            regionservice.rackcontrollers, "register"
        ).return_value = mock_rack
        MAAS_SECRET.set(factory.make_bytes())

        def setup_cluster_certificates():
            secret_manger = SecretManager()
            secret_manger.set_composite_secret(
                "cluster-certificate",
                {"key": "key", "cert": "cert", "cacerts": "cacerts"},
            )

        yield deferToDatabase(transactional(setup_cluster_certificates))
        protocol = self.make_Region()
        protocol.transport = MagicMock()
        response = yield call_responder(
            protocol,
            RegisterRackController,
            {
                "system_id": system_id,
                "hostname": "test-host",
                "interfaces": {},
                "version": "2.3.0",
            },
        )
        assert json.loads(
            fernet_decrypt_psk(response["encrypted_cluster_certificate"])
        ) == {"key": "key", "cert": "cert", "cacerts": "cacerts"}

    @wait_for_reactor
    @inlineCallbacks
    def test_register_sets_ident(self, mocker):
        system_id = factory.make_name("system_id")
        mock_rack = self.make_mock_rack_controller(system_id)
        mocker.patch.object(
            regionservice.rackcontrollers, "register"
        ).return_value = mock_rack
        MAAS_SECRET.set(factory.make_bytes())
        protocol = self.make_Region()
        protocol.transport = MagicMock()
        yield call_responder(
            protocol,
            RegisterRackController,
            {
                "system_id": system_id,
                "hostname": "test-host",
                "interfaces": {},
            },
        )
        assert system_id == protocol.ident

    @wait_for_reactor
    @inlineCallbacks
    def test_register_calls_addConnectionFor(self, mocker):
        system_id = factory.make_name("system_id")
        mock_rack = self.make_mock_rack_controller(system_id)
        mocker.patch.object(
            regionservice.rackcontrollers, "register"
        ).return_value = mock_rack
        MAAS_SECRET.set(factory.make_bytes())
        protocol = self.make_Region()
        protocol.transport = MagicMock()
        mock_addConnectionFor = mocker.patch.object(
            protocol.factory.service, "_addConnectionFor"
        )
        yield call_responder(
            protocol,
            RegisterRackController,
            {
                "system_id": system_id,
                "hostname": "test-host",
                "interfaces": {},
            },
        )
        mock_addConnectionFor.assert_called_once_with(system_id, protocol)

    @wait_for_reactor
    @inlineCallbacks
    def test_register_sets_hosts(self, mocker):
        system_id = factory.make_name("system_id")
        mock_rack = self.make_mock_rack_controller(system_id)
        mocker.patch.object(
            regionservice.rackcontrollers, "register"
        ).return_value = mock_rack
        MAAS_SECRET.set(factory.make_bytes())
        protocol = self.make_Region()
        protocol.transport = MagicMock()
        protocol.transport.getHost.return_value = sentinel.host
        yield call_responder(
            protocol,
            RegisterRackController,
            {
                "system_id": system_id,
                "hostname": "test-host",
                "interfaces": {},
            },
        )
        assert sentinel.host == protocol.host

    @wait_for_reactor
    @inlineCallbacks
    def test_register_sets_hostIsRemote_calls_rpcRegisterConnection(
        self, mocker
    ):
        system_id = factory.make_name("system_id")
        mock_rack = self.make_mock_rack_controller(system_id)
        ipcWorker = MagicMock()
        protocol = self.make_Region(ipcWorker)
        protocol.transport = MagicMock()
        host = IPv4Address(
            type="TCP",
            host=factory.make_ipv4_address(),
            port=random.randint(1, 400),
        )
        protocol.transport.getHost.return_value = host

        def _mock_defer_to_database(*args, **kwargs):
            if "system_id" in kwargs:
                return mock_rack
            else:
                return b'{"key": "key", "cert": "cert"}'

        mock_deferToDatabase = mocker.patch.object(
            regionservice, "deferToDatabase"
        )
        mock_deferToDatabase.side_effect = _mock_defer_to_database

        MAAS_SECRET.set(factory.make_bytes())

        yield call_responder(
            protocol,
            RegisterRackController,
            {
                "system_id": system_id,
                "hostname": "test-host",
                "interfaces": {},
            },
        )
        assert protocol.hostIsRemote
        ipcWorker.rpcRegisterConnection.assert_called_once_with(
            protocol.connid, protocol.ident, host.host, host.port
        )

    @wait_for_reactor
    @inlineCallbacks
    def test_register_creates_new_rack(self, mocker):
        system_id = None
        mock_rack = self.make_mock_rack_controller(
            factory.make_name("system_id")
        )
        mocker.patch.object(
            regionservice.rackcontrollers, "register"
        ).return_value = mock_rack
        MAAS_SECRET.set(factory.make_bytes())
        protocol = self.make_Region()
        protocol.transport = MagicMock()
        hostname = factory.make_hostname()
        yield call_responder(
            protocol,
            RegisterRackController,
            {"system_id": system_id, "hostname": hostname, "interfaces": {}},
        )

    @wait_for_reactor
    @inlineCallbacks
    def test_register_raises_CannotRegisterRackController_when_it_cant(
        self, mocker
    ):
        mocker.patch.object(
            regionservice.rackcontrollers, "register"
        ).side_effect = IntegrityError()
        MAAS_SECRET.set(factory.make_bytes())
        hostname = factory.make_name("hostname")
        msg = re.escape(
            "Failed to register rack controller 'None' with the master. "
            "Connection will be dropped."
        )

        with pytest.raises(CannotRegisterRackController, match=msg):
            yield call_responder(
                self.make_Region(),
                RegisterRackController,
                {"system_id": None, "hostname": hostname, "interfaces": {}},
            )


class TestRackClient:
    @wait_for_reactor
    @inlineCallbacks
    def test_call__records_latency_metric(self, mocker):
        mock_metrics = mocker.patch.object(PROMETHEUS_METRICS, "update")
        conn = DummyConnection()
        conn.ident = factory.make_name("ident")
        mocker.patch.object(
            conn, "callRemote", create=True
        ).return_value = succeed(sentinel.boot_images)
        client = RackClient(conn)
        yield client(cluster.PowerDriverCheck)
        mock_metrics.assert_called_with(
            "maas_region_rack_rpc_call_latency",
            "observe",
            labels={"call": "PowerDriverCheck"},
            value=ANY,
        )


class TestRegionService:
    def test_init_sets_appropriate_instance_attributes(self):
        service = RegionService(sentinel.ipcWorker)
        assert isinstance(service, Service)
        assert isinstance(service.connections, defaultdict)
        assert service.connections.default_factory is set
        for endpoints in service.endpoints:
            for endpoint in endpoints:
                assert IStreamServerEndpoint.providedBy(endpoint)
        assert isinstance(service.factory, Factory)
        assert RegionServer == service.factory.protocol
        assert isinstance(service.events.connected, events.Event)
        assert isinstance(service.events.disconnected, events.Event)

    @wait_for_reactor
    def test_starting_and_stopping_the_service(self):
        service = RegionService(sentinel.ipcWorker)
        assert service.starting is None
        service.startService()
        assert isinstance(service.starting, Deferred)

        def check_started(_):
            # Ports are saved as private instance vars.
            assert len(service.ports) == 1
            [port] = service.ports
            assert isinstance(port, tcp.Port)
            assert isinstance(port.factory, Factory)
            assert RegionServer == port.factory.protocol
            return service.stopService()

        service.starting.addCallback(check_started)

        def check_stopped(ignore, service=service):
            assert [] == service.ports

        service.starting.addCallback(check_stopped)

        return service.starting

    @wait_for_reactor
    def test_startService_returns_Deferred(self, mocker):
        service = RegionService(sentinel.ipcWorker)

        # Don't configure any endpoints.
        mocker.patch.object(service, "endpoints", [])

        d = service.startService()
        assert isinstance(d, Deferred)
        # It's actually the `starting` Deferred.
        assert service.starting is d

        def started(_):
            return service.stopService()

        return d.addCallback(started)

    @wait_for_reactor
    def test_start_up_can_be_cancelled(self, mocker):
        service = RegionService(sentinel.ipcWorker)

        # Return an inert Deferred from the listen() call.
        endpoints = mocker.patch.object(service, "endpoints", [[Mock()]])
        endpoints[0][0].listen.return_value = Deferred()

        service.startService()
        assert isinstance(service.starting, Deferred)

        service.starting.cancel()

        def check(port):
            assert port is None
            assert [] == service.ports
            return service.stopService()

        return service.starting.addCallback(check)

    @wait_for_reactor
    def test_cancelling_start_up_does_not_try_next_group(self, mocker):
        # A CancelledError from one candidate group must abort the whole
        # retry loop, not be treated as an ordinary bind failure and
        # trigger a fall-through attempt at the next candidate port.
        service = RegionService(sentinel.ipcWorker)

        endpoint_1 = Mock()
        endpoint_1.listen.return_value = Deferred()
        endpoint_2 = Mock()
        endpoint_2.listen.return_value = succeed(sentinel.port2)
        mocker.patch.object(service, "endpoints", [[endpoint_1], [endpoint_2]])

        service.startService()
        service.starting.cancel()

        def check(port):
            assert port is None
            assert [] == service.ports
            endpoint_2.listen.assert_not_called()

        return service.starting.addCallback(check)

    @wait_for_reactor
    @inlineCallbacks
    def test_start_up_errors_are_logged(self, mocker):
        ipcWorker = MagicMock()
        service = RegionService(ipcWorker)

        # Ensure that endpoint.listen fails with a obvious error.
        exception = ValueError("This is not the messiah.")
        endpoints = mocker.patch.object(service, "endpoints", [[Mock()]])
        endpoints[0][0].listen.return_value = fail(exception)

        with TwistedLoggerFixture() as logger:
            yield service.startService()

        for failure in logger.failures:
            assert failure.value is exception

    @wait_for_reactor
    @inlineCallbacks
    def test_start_up_binds_first_of_endpoint_options(self, mocker):
        service = RegionService(sentinel.ipcWorker)

        endpoint_1 = Mock()
        endpoint_1.listen.return_value = succeed(sentinel.port1)
        endpoint_2 = Mock()
        endpoint_2.listen.return_value = succeed(sentinel.port2)
        mocker.patch.object(service, "endpoints", [[endpoint_1], [endpoint_2]])

        yield service.startService()

        assert [sentinel.port1] == service.ports

    @wait_for_reactor
    @inlineCallbacks
    def test_start_up_binds_first_of_real_endpoint_options(self, mocker):
        service = RegionService(sentinel.ipcWorker)

        # endpoint_1.listen(...) will bind to a random high-numbered port.
        endpoint_1 = TCP4ServerEndpoint(reactor, 0)
        # endpoint_2.listen(...), if attempted, will crash because only root
        # (or a user with explicit capabilities) can do stuff like that. It's
        # a reasonable assumption that the user running these tests is not
        # root, but we'll check the port number later too to be sure.
        endpoint_2 = TCP4ServerEndpoint(reactor, 1)

        mocker.patch.object(service, "endpoints", [[endpoint_1], [endpoint_2]])

        yield service.startService()

        # A single port has been bound.
        assert len(service.ports) == 1

        # The port is not listening on port 1; i.e. a belt-n-braces check that
        # endpoint_2 was not used.
        [port] = service.ports
        assert isinstance(port, tcp.Port)
        assert port.getHost().port != 1

        yield service.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_start_up_binds_first_successful_of_endpoint_options(self, mocker):
        service = RegionService(sentinel.ipcWorker)

        endpoint_broken = Mock()
        endpoint_broken.listen.return_value = fail(factory.make_exception())
        endpoint_okay = Mock()
        endpoint_okay.listen.return_value = succeed(sentinel.port)
        mocker.patch.object(
            service, "endpoints", [[endpoint_broken], [endpoint_okay]]
        )

        yield service.startService()

        assert [sentinel.port] == service.ports

    @wait_for_reactor
    @inlineCallbacks
    def test_start_up_binds_every_address_in_a_successful_group(self, mocker):
        # A group models one candidate port shared across every
        # configured rpc_bind address; all endpoints in the group must
        # bind for the group to count as a success.
        service = RegionService(sentinel.ipcWorker)

        endpoint_1 = Mock()
        endpoint_1.listen.return_value = succeed(sentinel.port1)
        endpoint_2 = Mock()
        endpoint_2.listen.return_value = succeed(sentinel.port2)
        mocker.patch.object(service, "endpoints", [[endpoint_1, endpoint_2]])

        yield service.startService()

        assert [sentinel.port1, sentinel.port2] == service.ports

    @wait_for_reactor
    @inlineCallbacks
    def test_start_up_closes_partial_group_before_trying_next_port(
        self, mocker
    ):
        # If any address in a group fails to bind, every port already
        # opened for that candidate port is closed again before the next
        # candidate port is tried.
        service = RegionService(sentinel.ipcWorker)

        opened_port = Mock()
        opened_port.stopListening.return_value = succeed(None)
        endpoint_okay = Mock()
        endpoint_okay.listen.return_value = succeed(opened_port)
        endpoint_broken = Mock()
        endpoint_broken.listen.return_value = fail(factory.make_exception())
        endpoint_next = Mock()
        endpoint_next.listen.return_value = succeed(sentinel.port2)
        mocker.patch.object(
            service,
            "endpoints",
            [[endpoint_okay, endpoint_broken], [endpoint_next]],
        )

        yield service.startService()

        opened_port.stopListening.assert_called_once_with()
        assert [sentinel.port2] == service.ports

    @skip("XXX test fails far too often; bug #1582944")
    @wait_for_reactor
    @inlineCallbacks
    def test_start_up_logs_failure_if_all_endpoint_options_fail(self, mocker):
        service = RegionService(sentinel.ipcWorker)

        error_1 = factory.make_exception_type()
        error_2 = factory.make_exception_type()

        endpoint_1 = Mock()
        endpoint_1.listen.return_value = fail(error_1())
        endpoint_2 = Mock()
        endpoint_2.listen.return_value = fail(error_2())
        mocker.patch.object(service, "endpoints", [[endpoint_1], [endpoint_2]])

        with TwistedLoggerFixture() as logger:
            yield service.startService()

        assert re.search(
            rf"(?ms) RegionServer endpoint failed to listen..*Traceback (most recent call last):.*{fullyQualifiedName(error_2)}",
            logger.output,
        )

    @wait_for_reactor
    def test_stopping_cancels_startup(self, mocker):
        service = RegionService(sentinel.ipcWorker)

        # Return an inert Deferred from the listen() call.
        endpoints = mocker.patch.object(service, "endpoints", [[Mock()]])
        endpoints[0][0].listen.return_value = Deferred()

        service.startService()
        service.stopService()

        def check(_):
            # The CancelledError is suppressed.
            assert [] == service.ports

        return service.starting.addCallback(check)

    @wait_for_reactor
    @inlineCallbacks
    def test_stopping_closes_connections_cleanly(self, mocker):
        service = RegionService(sentinel.ipcWorker)
        service.starting = Deferred()
        service.starting.addErrback(
            lambda failure: failure.trap(CancelledError)
        )
        service.factory.protocol = HandshakingRegionServer
        connections = {
            service.factory.buildProtocol(None),
            service.factory.buildProtocol(None),
        }
        for conn in connections:
            # Pretend it's already connected.
            service.connections[conn.ident].add(conn)
        transports = {
            mocker.patch.object(conn, "transport") for conn in connections
        }
        yield service.stopService()
        for mock_transport in transports:
            mock_transport.loseConnection.assert_called_once_with()

    @wait_for_reactor
    @inlineCallbacks
    def test_stopping_logs_errors_when_closing_connections(self, mocker):
        service = RegionService(sentinel.ipcWorker)
        service.starting = Deferred()
        service.starting.addErrback(
            lambda failure: failure.trap(CancelledError)
        )
        service.factory.protocol = HandshakingRegionServer
        connections = {
            service.factory.buildProtocol(None),
            service.factory.buildProtocol(None),
        }
        for conn in connections:
            transport = mocker.patch.object(conn, "transport")
            transport.loseConnection.side_effect = OSError("broken")
            # Pretend it's already connected.
            service.connections[conn.ident].add(conn)
        with TwistedLoggerFixture() as logger:
            # stopService() completes without returning an error.
            yield service.stopService()
        # Connection-specific errors are logged.
        assert re.search(
            (
                r"(?ms)Failure when closing RPC connection\.\s*"
                r"Traceback \(most recent call last\):.*"
                r"builtins\.OSError: broken.*"
                r"Failure when closing RPC connection\.\s*"
                r"Traceback \(most recent call last\):.*"
                r"builtins\.OSError: broken"
            ),
            logger.dump(),
        )

    @wait_for_reactor
    def test_stopping_when_start_up_failed(self, mocker):
        service = RegionService(sentinel.ipcWorker)

        # Ensure that endpoint.listen fails with a obvious error.
        exception = ValueError("This is a very naughty boy.")
        endpoints = mocker.patch.object(service, "endpoints", [[Mock()]])
        endpoints[0][0].listen.return_value = fail(exception)

        service.startService()
        # The test is that stopService() succeeds.
        return service.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_getClientFor_errors_when_no_connections(self):
        service = RegionService(sentinel.ipcWorker)
        service.connections.clear()
        with pytest.raises(
            exceptions.NoConnectionsAvailable,
            match=r"no connections available\.$",
        ):
            yield service.getClientFor(factory.make_UUID(), timeout=0)

    @wait_for_reactor
    @inlineCallbacks
    def test_getClientFor_errors_when_no_connections_for_cluster(self):
        service = RegionService(sentinel.ipcWorker)
        uuid = factory.make_UUID()
        service.connections[uuid].clear()
        with pytest.raises(
            exceptions.NoConnectionsAvailable,
            match=r"no connections available\.$",
        ):
            yield service.getClientFor(uuid, timeout=0)

    @wait_for_reactor
    def test_getClientFor_returns_random_connection(self, mocker):
        c1 = DummyConnection()
        c2 = DummyConnection()
        chosen = DummyConnection()

        service = RegionService(sentinel.ipcWorker)
        uuid = factory.make_UUID()
        conns_for_uuid = service.connections[uuid]
        conns_for_uuid.update({c1, c2})

        def check_choice(choices):
            assert len(choices) == len(conns_for_uuid)
            assert all(c in conns_for_uuid for c in choices)
            return chosen

        mocker.patch.object(random, "choice", check_choice)

        def check(client):
            assert RackClient(chosen) == client

        return service.getClientFor(uuid).addCallback(check)

    @wait_for_reactor
    def test_getAllClients_empty(self):
        service = RegionService(sentinel.ipcWorker)
        service.connections.clear()
        assert [] == service.getAllClients()

    @wait_for_reactor
    def test_getAllClients_empty_connections(self):
        service = RegionService(sentinel.ipcWorker)
        service.connections.clear()
        uuid1 = factory.make_UUID()
        service.connections[uuid1] = set()
        assert [] == service.getAllClients()

    @wait_for_reactor
    def test_getRandomClient_empty_raises_NoConnectionsAvailable(self):
        service = RegionService(sentinel.ipcWorker)
        service.connections.clear()
        with pytest.raises(
            NoConnectionsAvailable, match=r"no connections available\.$"
        ):
            service.getRandomClient()

    @wait_for_reactor
    def test_getAllClients(self):
        service = RegionService(sentinel.ipcWorker)
        uuid1 = factory.make_UUID()
        c1 = DummyConnection()
        c2 = DummyConnection()
        service.connections[uuid1].update({c1, c2})
        uuid2 = factory.make_UUID()
        c3 = DummyConnection()
        c4 = DummyConnection()
        service.connections[uuid2].update({c3, c4})
        clients = service.getAllClients()
        (one, two) = list(clients)
        assert (one, two) in [
            (RackClient(c1), RackClient(c3)),
            (RackClient(c1), RackClient(c4)),
            (RackClient(c2), RackClient(c3)),
            (RackClient(c2), RackClient(c4)),
        ]

    def test_rack_controller_is_disconnected_returns_True_with_no_connections(
        self,
    ):
        service = RegionService(sentinel.ipcWorker)
        rack_ident = factory.make_UUID()
        assert service.rack_controller_is_disconnected(rack_ident)

    def test_rack_controller_is_disconnected_returns_False_with_connections(
        self,
    ):
        service = RegionService(sentinel.ipcWorker)
        rack_ident = factory.make_UUID()
        c1 = DummyConnection()
        c2 = DummyConnection()
        service.connections[rack_ident].update({c1, c2})
        assert not service.rack_controller_is_disconnected(rack_ident)

    def test_addConnectionFor_adds_connection(self):
        service = RegionService(sentinel.ipcWorker)
        uuid = factory.make_UUID()
        c1 = DummyConnection()
        c2 = DummyConnection()

        service._addConnectionFor(uuid, c1)
        service._addConnectionFor(uuid, c2)

        assert {uuid: {c1, c2}} == service.connections

    def test_addConnectionFor_notifies_waiters(self):
        service = RegionService(sentinel.ipcWorker)
        uuid = factory.make_UUID()
        c1 = DummyConnection()
        c2 = DummyConnection()

        waiter1 = Mock()
        waiter2 = Mock()
        service.waiters[uuid].add(waiter1)
        service.waiters[uuid].add(waiter2)

        service._addConnectionFor(uuid, c1)
        service._addConnectionFor(uuid, c2)

        assert {uuid: {c1, c2}} == service.connections
        # Both mock waiters are called twice. A real waiter would only be
        # called once because it immediately unregisters itself once called.
        waiter1.callback.assert_has_calls((call(c1), call(c2)))
        waiter2.callback.assert_has_calls((call(c1), call(c2)))

    def test_addConnectionFor_fires_connected_event(self, mocker):
        service = RegionService(sentinel.ipcWorker)
        uuid = factory.make_UUID()
        c1 = DummyConnection()

        mock_fire = mocker.patch.object(service.events.connected, "fire")
        service._addConnectionFor(uuid, c1)

        mock_fire.assert_called_once_with(uuid)

    def test_removeConnectionFor_removes_connection(self):
        service = RegionService(sentinel.ipcWorker)
        uuid = factory.make_UUID()
        c1 = DummyConnection()
        c2 = DummyConnection()

        service._addConnectionFor(uuid, c1)
        service._addConnectionFor(uuid, c2)
        service._removeConnectionFor(uuid, c1)

        assert {uuid: {c2}} == service.connections

    def test_removeConnectionFor_is_okay_if_connection_is_not_there(self):
        service = RegionService(sentinel.ipcWorker)
        uuid = factory.make_UUID()

        service._removeConnectionFor(uuid, DummyConnection())

        assert {uuid: set()} == service.connections

    def test_removeConnectionFor_fires_disconnected_event(self, mocker):
        service = RegionService(sentinel.ipcWorker)
        uuid = factory.make_UUID()
        c1 = DummyConnection()

        mock_fire = mocker.patch.object(service.events.disconnected, "fire")
        service._removeConnectionFor(uuid, c1)

        mock_fire.assert_called_once_with(uuid)

    @wait_for_reactor
    def test_getConnectionFor_returns_existing_connection(self):
        service = RegionService(sentinel.ipcWorker)
        uuid = factory.make_UUID()
        conn = DummyConnection()

        service._addConnectionFor(uuid, conn)

        d = service._getConnectionFor(uuid, 1)
        # No waiter is added because a connection is available.
        assert {uuid: set()} == service.waiters

        def check(conn_returned):
            assert conn == conn_returned

        return d.addCallback(check)

    @wait_for_reactor
    def test_getConnectionFor_waits_for_connection(self):
        service = RegionService(sentinel.ipcWorker)
        uuid = factory.make_UUID()
        conn = DummyConnection()

        # Add the connection later (we're in the reactor thread right
        # now so this won't happen until after we return).
        reactor.callLater(0, service._addConnectionFor, uuid, conn)

        d = service._getConnectionFor(uuid, 1)
        # A waiter is added for the connection we're interested in.
        assert {uuid: {d}} == service.waiters

        def check(conn_returned):
            assert conn == conn_returned
            # The waiter has been unregistered.
            assert {uuid: set()} == service.waiters

        return d.addCallback(check)

    @wait_for_reactor
    def test_getConnectionFor_with_concurrent_waiters(self):
        service = RegionService(sentinel.ipcWorker)
        uuid = factory.make_UUID()
        conn = DummyConnection()

        # Add the connection later (we're in the reactor thread right
        # now so this won't happen until after we return).
        reactor.callLater(0, service._addConnectionFor, uuid, conn)

        d1 = service._getConnectionFor(uuid, 1)
        d2 = service._getConnectionFor(uuid, 1)
        # A waiter is added for each call to _getConnectionFor().
        assert {uuid: {d1, d2}} == service.waiters

        d = DeferredList((d1, d2))

        def check(results):
            assert [(True, conn), (True, conn)] == results
            # The waiters have both been unregistered.
            assert {uuid: set()} == service.waiters

        return d.addCallback(check)

    @wait_for_reactor
    @inlineCallbacks
    def test_getConnectionFor_cancels_waiter_when_it_times_out(self):
        service = RegionService(sentinel.ipcWorker)
        uuid = factory.make_UUID()

        d = service._getConnectionFor(uuid, 1)
        # A waiter is added for the connection we're interested in.
        assert {uuid: {d}} == service.waiters
        with pytest.raises(CancelledError, match="^$"):
            yield d

        # The waiter has been unregistered.
        assert {uuid: set()} == service.waiters


@pytest.mark.usefixtures("maasdb")
class TestGetTrustedSshHostKeys:
    @pytest.fixture(autouse=True)
    def _cleanup(self, maasdb):
        yield
        from maasserver.models import TrustedSshHostKey

        TrustedSshHostKey.objects.all().delete()

    @wait_for_reactor
    @inlineCallbacks
    def test_returns_keys_registered_for_host(self):
        host = factory.make_hostname()
        public_key = factory.make_name("public_key")
        yield deferToDatabase(
            TrustedSshHostKey.objects.create,
            host=host,
            key_type="ecdsa-sha2-nistp256",
            public_key=public_key,
        )

        region = Region()
        result = yield region.get_trusted_ssh_host_keys(host=host)

        assert result == {
            "keys": [
                {
                    "key_type": "ecdsa-sha2-nistp256",
                    "public_key": public_key,
                }
            ]
        }

    @wait_for_reactor
    @inlineCallbacks
    def test_returns_empty_list_for_host_with_no_trusted_keys(self):
        # Delete any keys left from previous tests
        yield deferToDatabase(TrustedSshHostKey.objects.all().delete)
        region = Region()
        result = yield region.get_trusted_ssh_host_keys(
            host=factory.make_hostname()
        )
        assert result == {"keys": []}

    @wait_for_reactor
    @inlineCallbacks
    def test_does_not_return_keys_registered_for_other_hosts(self):
        # Delete any keys left from previous tests
        yield deferToDatabase(TrustedSshHostKey.objects.all().delete)
        yield deferToDatabase(
            TrustedSshHostKey.objects.create,
            host=factory.make_hostname(),
            key_type="ecdsa-sha2-nistp256",
            public_key=factory.make_name("public_key"),
        )

        region = Region()
        result = yield region.get_trusted_ssh_host_keys(
            host=factory.make_hostname()
        )
        assert result == {"keys": []}
