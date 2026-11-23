# Copyright 2014-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
from hashlib import sha256
from hmac import HMAC
import json
import os
import random
import socket
from unittest.mock import ANY, call, MagicMock, Mock, sentinel
from urllib.parse import urlparse

from netaddr import IPNetwork
import pytest
from twisted import web
from twisted.application.internet import TimerService
from twisted.internet import error, reactor
from twisted.internet.defer import Deferred, fail, inlineCallbacks, succeed
from twisted.internet.endpoints import TCP6ClientEndpoint
from twisted.internet.error import ConnectionClosed
from twisted.internet.task import Clock
from twisted.internet.testing import StringTransportWithDisconnection
from twisted.python.failure import Failure
from twisted.web.client import Headers
from zope.interface.verify import verifyObject

from apiclient.utils import ascii_url
from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.deferred import extract_result
from maastesting.factory import factory
from maastesting.twisted import (
    always_fail_with,
    always_succeed_with,
    TwistedLoggerFixture,
)
from provisioningserver import certificates
from provisioningserver.certificates import (
    Certificate,
    CertificateRequest,
    get_maas_cluster_cert_paths,
    get_maas_rack_controller_cert_paths,
)
from provisioningserver.drivers.power import PowerError
from provisioningserver.drivers.power.registry import PowerDriverRegistry
from provisioningserver.rpc import (
    cluster,
    clusterservice,
    common,
    exceptions,
    getRegionClient,
)
from provisioningserver.rpc import power as power_module
from provisioningserver.rpc.clusterservice import (
    Cluster,
    ClusterClient,
    ClusterClientCheckerService,
    ClusterClientService,
    executeScanNetworksSubprocess,
    get_scan_all_networks_args,
    spawnProcessAndNullifyStdout,
)
from provisioningserver.rpc.interfaces import IConnection
from provisioningserver.rpc.testing import (
    call_responder,
    MockLiveClusterToRegionRPCFixture,
)
from provisioningserver.rpc.testing.doubles import FakeConnection
from provisioningserver.security import calculate_digest, fernet_encrypt_psk
from provisioningserver.testing.config import ClusterConfigurationFixture
from provisioningserver.utils import env as utils_env
from provisioningserver.utils.env import MAAS_ID, MAAS_SECRET, MAAS_UUID
from provisioningserver.utils.fs import get_maas_common_command, NamedLock
from provisioningserver.utils.shell import ExternalProcessError
from provisioningserver.utils.testing import MAASIDFixture
from provisioningserver.utils.twisted import makeDeferredWithProcessProtocol
from provisioningserver.utils.version import get_running_version

TIMEOUT = get_testing_timeout()


@inlineCallbacks
def _cleanup_rpc_fixture(fixture, shutdown):
    try:
        yield shutdown[0]()
    finally:
        yield fixture.cleanUp()


def _register_rpc_fixture_cleanup(request, fixture, shutdown):
    request.addfinalizer(
        lambda: wait_for(timeout=TIMEOUT)(_cleanup_rpc_fixture)(
            fixture, shutdown
        )
    )


class TestClusterProtocol:
    def test_unauthenticated_allowed_commands(self):
        protocol = Cluster()
        assert protocol.unauthenticated_commands == [
            cluster.Authenticate.commandName
        ]

    def test_default_auth_status(self):
        protocol = Cluster()
        assert protocol.auth_status.is_authenticated is False


@pytest.mark.rack_reactor_guard
class TestClusterProtocol_Identify:
    def test_identify_is_registered(self):
        protocol = Cluster()
        responder = protocol.locateResponder(cluster.Identify.commandName)
        assert responder is not None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_identify_reports_system_id(self, request):
        system_id = factory.make_name("id")
        fixture = MAASIDFixture(system_id)
        fixture.setUp()
        request.addfinalizer(fixture.cleanUp)
        response = yield call_responder(Cluster(), cluster.Identify, {})
        assert response == {"ident": system_id}


@pytest.mark.rack_reactor_guard
class TestClusterProtocol_Authenticate:
    def test_authenticate_is_registered(self):
        protocol = Cluster()
        responder = protocol.locateResponder(cluster.Authenticate.commandName)
        assert responder is not None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_authenticate_calculates_digest_with_salt(self, request):
        message = factory.make_bytes()
        secret = factory.make_bytes()
        old_secret = MAAS_SECRET.get()
        request.addfinalizer(lambda: MAAS_SECRET.set(old_secret))
        MAAS_SECRET.set(secret)

        args = {"message": message}
        response = yield call_responder(Cluster(), cluster.Authenticate, args)
        digest = response["digest"]
        salt = response["salt"]

        assert len(salt) == 16
        expected_digest = HMAC(
            secret, message + b"region-to-rack" + salt, sha256
        ).digest()
        assert expected_digest == digest


def make_inert_client_service():
    service = ClusterClientService(Clock())
    # ClusterClientService's superclass, TimerService, creates a
    # LoopingCall with now=True. We neuter it here to allow
    # observation of the behaviour of _update_interval() for
    # example.
    service.call = (lambda: None, (), {})
    return service


@pytest.mark.rack_reactor_guard
class TestClusterClientService:
    @pytest.fixture(autouse=True)
    def track_services(self, mocker, request):
        services = set()
        start_service = ClusterClientService.startService

        def start_and_track(service, *args, **kwargs):
            services.add(service)
            return start_service(service, *args, **kwargs)

        mocker.patch.object(
            ClusterClientService, "startService", start_and_track
        )

        @wait_for(timeout=TIMEOUT)
        @inlineCallbacks
        def stop_services():
            for service in services:
                if service.running:
                    yield service.stopService()

        request.addfinalizer(stop_services)

    def make_service(self, clock, request):
        service = ClusterClientService(clock)
        request.addfinalizer(
            lambda: service.stopService() if service.running else None
        )
        return service

    def use_logger(self, request):
        fixture = TwistedLoggerFixture()
        fixture.setUp()
        request.addfinalizer(fixture.cleanUp)
        return fixture

    def use_configuration(self, request, fixture):
        fixture.setUp()
        request.addfinalizer(fixture.cleanUp)
        return fixture

    def fakeAgentResponse(self, mocker, data="", code=200):
        mocker.patch.object(clusterservice, "readBody").return_value = succeed(
            data
        )
        mock_agent = MagicMock()
        response = MagicMock(code=code)
        mock_agent.request.return_value = succeed(response)
        mocker.patch.object(clusterservice, "Agent").return_value = mock_agent

    def test_init_sets_appropriate_instance_attributes(self):
        service = ClusterClientService(sentinel.reactor)
        assert isinstance(service, TimerService)
        assert service.clock is sentinel.reactor

    def test_get_config_rpc_info_urls(self, request):
        maas_urls = [factory.make_simple_http_url() for _ in range(3)]
        self.use_configuration(
            request, ClusterConfigurationFixture(maas_url=maas_urls)
        )
        service = ClusterClientService(reactor)
        observed_urls = service._get_config_rpc_info_urls()
        assert maas_urls == observed_urls

    def test_get_saved_rpc_info_urls(self):
        saved_urls = [factory.make_simple_http_url() for _ in range(3)]
        service = ClusterClientService(reactor)
        with open(service._get_saved_rpc_info_path(), "w") as stream:
            for url in saved_urls:
                stream.write("%s\n" % url)
        observed_urls = service._get_saved_rpc_info_urls()
        assert saved_urls == observed_urls

    def test_update_saved_rpc_info_state(self):
        service = ClusterClientService(reactor)
        ipv4client = ClusterClient(("1.1.1.1", 1111), "host1:pid=1", service)
        ipv6client = ClusterClient(("::ffff", 2222), "host2:pid=2", service)
        ipv6mapped = ClusterClient(
            ("::ffff:3.3.3.3", 3333), "host3:pid=3", service
        )
        hostclient = ClusterClient(
            ("example.com", 4444), "host4:pid=4", service
        )

        # Fake some connections.
        service.connections = {
            ipv4client.eventloop: ipv4client,
            ipv6client.eventloop: ipv6client,
            ipv6mapped.eventloop: ipv6mapped,
            hostclient.eventloop: hostclient,
        }

        assert service._rpc_info_state is None
        service._update_saved_rpc_info_state()

        # Ensure that the info state is set.
        assert service._rpc_info_state == {
            client.address[0] for _, client in service.connections.items()
        }

        # Check that the written rpc state is valid.
        assert service._get_saved_rpc_info_urls() == [
            "http://1.1.1.1:5240/MAAS",
            "http://[::ffff]:5240/MAAS",
            "http://3.3.3.3:5240/MAAS",
            "http://example.com:5240/MAAS",
        ]

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_build_rpc_info_urls(self):
        # Because this actually will try to resolve the URL's in the test we
        # keep them to localhost so it works on all systems.
        maas_urls = ["http://127.0.0.1:5240/" for _ in range(3)]
        expected_urls = [
            ([b"http://127.0.0.1:5240/rpc/"], "http://127.0.0.1:5240/")
            for url in maas_urls
        ]
        service = ClusterClientService(reactor)
        observed_urls = yield service._build_rpc_info_urls(maas_urls)
        assert expected_urls == observed_urls

    def test_doUpdate_connect_502_error_is_logged_tersely(
        self, mocker, request
    ):
        self.fakeAgentResponse(mocker, code=502)
        logger = self.use_logger(request)
        service = ClusterClientService(Clock())
        # Starting the service causes the first update to be performed.
        service.startService()

        dump = logger.dump()
        assert "Region is not advertising RPC endpoints." in dump

    def test_doUpdate_connect_503_error_is_logged_tersely(
        self, mocker, request
    ):
        self.fakeAgentResponse(mocker, code=503)
        logger = self.use_logger(request)
        service = ClusterClientService(Clock())
        # Starting the service causes the first update to be performed.
        service.startService()

        dump = logger.dump()
        assert "Region is not advertising RPC endpoints." in dump

    def test_doUpdate_makes_parallel_requests(self, mocker, request):
        mock_agent = MagicMock()
        mock_agent.request.return_value = always_fail_with(
            web.error.Error(500)
        )
        mocker.patch.object(clusterservice, "Agent").return_value = mock_agent

        logger = self.use_logger(request)

        service = ClusterClientService(Clock())
        _get_config_rpc_info_urls = mocker.patch.object(
            service, "_get_config_rpc_info_urls"
        )
        _get_config_rpc_info_urls.return_value = [
            "http://127.0.0.1/MAAS",
            "http://127.0.0.1/MAAS",
        ]
        _build_rpc_info_urls = mocker.patch.object(
            service, "_build_rpc_info_urls"
        )
        _build_rpc_info_urls.return_value = succeed(
            [
                ([b"http://[::ffff:127.0.0.1]/MAAS"], "http://127.0.0.1/MAAS"),
                ([b"http://[::ffff:127.0.0.1]/MAAS"], "http://127.0.0.1/MAAS"),
            ]
        )

        # Starting the service causes the first update to be performed.
        service.startService()

        mock_agent.request.assert_has_calls(
            [
                call(
                    b"GET",
                    ascii_url("http://[::ffff:127.0.0.1]/MAAS"),
                    Headers(
                        {
                            "User-Agent": [
                                "provisioningserver.rpc.clusterservice.ClusterClientService"
                            ],
                            "Host": ["127.0.0.1"],
                        }
                    ),
                ),
                call(
                    b"GET",
                    ascii_url("http://[::ffff:127.0.0.1]/MAAS"),
                    Headers(
                        {
                            "User-Agent": [
                                "provisioningserver.rpc.clusterservice.ClusterClientService"
                            ],
                            "Host": ["127.0.0.1"],
                        }
                    ),
                ),
            ]
        )
        dump = logger.dump()
        assert (
            "Failed to contact region. (While requesting RPC info at "
            "http://127.0.0.1/MAAS, http://127.0.0.1/MAAS)"
        ) in dump

    def test_doUpdate_makes_parallel_with_serial_requests(
        self, mocker, request
    ):
        mock_agent = MagicMock()
        mock_agent.request.return_value = always_fail_with(
            web.error.Error(500)
        )
        mocker.patch.object(clusterservice, "Agent").return_value = mock_agent

        logger = self.use_logger(request)

        service = ClusterClientService(Clock())
        _get_config_rpc_info_urls = mocker.patch.object(
            service, "_get_config_rpc_info_urls"
        )
        _get_config_rpc_info_urls.return_value = [
            "http://127.0.0.1/MAAS",
            "http://127.0.0.1/MAAS",
        ]
        _build_rpc_info_urls = mocker.patch.object(
            service, "_build_rpc_info_urls"
        )
        _build_rpc_info_urls.return_value = succeed(
            [
                (
                    [
                        b"http://[::ffff:127.0.0.1]/MAAS",
                        b"http://127.0.0.1/MAAS",
                    ],
                    "http://127.0.0.1/MAAS",
                ),
                (
                    [
                        b"http://[::ffff:127.0.0.1]/MAAS",
                        b"http://127.0.0.1/MAAS",
                    ],
                    "http://127.0.0.1/MAAS",
                ),
            ]
        )

        # Starting the service causes the first update to be performed.
        service.startService()

        mock_agent.request.assert_has_calls(
            [
                call(
                    b"GET",
                    ascii_url("http://[::ffff:127.0.0.1]/MAAS"),
                    Headers(
                        {
                            "User-Agent": [
                                "provisioningserver.rpc.clusterservice.ClusterClientService"
                            ],
                            "Host": ["127.0.0.1"],
                        }
                    ),
                ),
                call(
                    b"GET",
                    ascii_url("http://127.0.0.1/MAAS"),
                    Headers(
                        {
                            "User-Agent": [
                                "provisioningserver.rpc.clusterservice.ClusterClientService"
                            ],
                            "Host": ["127.0.0.1"],
                        }
                    ),
                ),
                call(
                    b"GET",
                    ascii_url("http://[::ffff:127.0.0.1]/MAAS"),
                    Headers(
                        {
                            "User-Agent": [
                                "provisioningserver.rpc.clusterservice.ClusterClientService"
                            ],
                            "Host": ["127.0.0.1"],
                        }
                    ),
                ),
                call(
                    b"GET",
                    ascii_url("http://127.0.0.1/MAAS"),
                    Headers(
                        {
                            "User-Agent": [
                                "provisioningserver.rpc.clusterservice.ClusterClientService"
                            ],
                            "Host": ["127.0.0.1"],
                        }
                    ),
                ),
            ]
        )
        dump = logger.dump()
        assert (
            "Failed to contact region. (While requesting RPC info at "
            "http://127.0.0.1/MAAS, http://127.0.0.1/MAAS)"
        ) in dump

    def test_doUpdate_falls_back_to_rpc_info_state(self, mocker, request):
        mock_agent = MagicMock()
        mock_agent.request.return_value = always_fail_with(
            web.error.Error(500)
        )
        mocker.patch.object(clusterservice, "Agent").return_value = mock_agent

        logger = self.use_logger(request)

        service = ClusterClientService(Clock())
        _get_config_rpc_info_urls = mocker.patch.object(
            service, "_get_config_rpc_info_urls"
        )
        _get_config_rpc_info_urls.return_value = [
            "http://127.0.0.1/MAAS",
            "http://127.0.0.1/MAAS",
        ]
        _get_saved_rpc_info_urls = mocker.patch.object(
            service, "_get_saved_rpc_info_urls"
        )
        _get_saved_rpc_info_urls.return_value = [
            "http://127.0.0.1/MAAS",
            "http://127.0.0.1/MAAS",
        ]
        _build_rpc_info_urls = mocker.patch.object(
            service, "_build_rpc_info_urls"
        )
        _build_rpc_info_urls.side_effect = [
            succeed(
                [
                    (
                        [b"http://[::ffff:127.0.0.1]/MAAS"],
                        "http://127.0.0.1/MAAS",
                    ),
                    (
                        [b"http://[::ffff:127.0.0.1]/MAAS"],
                        "http://127.0.0.1/MAAS",
                    ),
                ]
            ),
            succeed(
                [
                    (
                        [b"http://[::ffff:127.0.0.1]/MAAS"],
                        "http://127.0.0.1/MAAS",
                    ),
                    (
                        [b"http://[::ffff:127.0.0.1]/MAAS"],
                        "http://127.0.0.1/MAAS",
                    ),
                ]
            ),
        ]

        # Starting the service causes the first update to be performed.
        service.startService()

        mock_agent.request.assert_has_calls(
            [
                call(
                    b"GET",
                    ascii_url("http://[::ffff:127.0.0.1]/MAAS"),
                    Headers(
                        {
                            "User-Agent": [
                                "provisioningserver.rpc.clusterservice.ClusterClientService"
                            ],
                            "Host": ["127.0.0.1"],
                        }
                    ),
                ),
                call(
                    b"GET",
                    ascii_url("http://[::ffff:127.0.0.1]/MAAS"),
                    Headers(
                        {
                            "User-Agent": [
                                "provisioningserver.rpc.clusterservice.ClusterClientService"
                            ],
                            "Host": ["127.0.0.1"],
                        }
                    ),
                ),
                call(
                    b"GET",
                    ascii_url("http://[::ffff:127.0.0.1]/MAAS"),
                    Headers(
                        {
                            "User-Agent": [
                                "provisioningserver.rpc.clusterservice.ClusterClientService"
                            ],
                            "Host": ["127.0.0.1"],
                        }
                    ),
                ),
                call(
                    b"GET",
                    ascii_url("http://[::ffff:127.0.0.1]/MAAS"),
                    Headers(
                        {
                            "User-Agent": [
                                "provisioningserver.rpc.clusterservice.ClusterClientService"
                            ],
                            "Host": ["127.0.0.1"],
                        }
                    ),
                ),
            ]
        )
        dump = logger.dump()
        assert (
            "Failed to contact region. (While requesting RPC info at "
            "http://127.0.0.1/MAAS, http://127.0.0.1/MAAS)"
        ) in dump

    def test_failed_update_is_logged(self, mocker, request):
        logger = self.use_logger(request)

        service = ClusterClientService(Clock())
        _doUpdate = mocker.patch.object(service, "_doUpdate")
        _doUpdate.side_effect = error.ConnectionRefusedError()

        # Starting the service causes the first update to be performed, which
        # will fail because of above.
        service.startService()
        _doUpdate.assert_called_once_with()

        dump = logger.dump()
        assert "Connection was refused by other side." in dump

    def test_update_connect_error_is_logged_tersely(self, mocker, request):
        mock_agent = MagicMock()
        mock_agent.request.side_effect = error.ConnectionRefusedError()
        mocker.patch.object(clusterservice, "Agent").return_value = mock_agent

        logger = self.use_logger(request)
        service = ClusterClientService(Clock())
        _get_config_rpc_info_urls = mocker.patch.object(
            service, "_get_config_rpc_info_urls"
        )
        _get_config_rpc_info_urls.return_value = ["http://127.0.0.1/MAAS"]
        _build_rpc_info_urls = mocker.patch.object(
            service, "_build_rpc_info_urls"
        )
        _build_rpc_info_urls.return_value = succeed(
            [([b"http://[::ffff:127.0.0.1]/MAAS"], "http://127.0.0.1/MAAS")]
        )

        # Starting the service causes the first update to be performed.
        service.startService()

        mock_agent.request.assert_called_once_with(
            b"GET",
            ascii_url("http://[::ffff:127.0.0.1]/MAAS"),
            Headers(
                {
                    "User-Agent": [
                        "provisioningserver.rpc.clusterservice.ClusterClientService"
                    ],
                    "Host": ["127.0.0.1"],
                }
            ),
        )
        dump = logger.dump()
        assert (
            "Region not available: Connection was refused by other side."
            in dump
        )
        assert "While requesting RPC info at" in dump

    def test_update_connect_includes_host(self, mocker):
        # Regression test for LP:1792462
        mock_agent = MagicMock()
        mock_agent.request.side_effect = error.ConnectionRefusedError()
        mocker.patch.object(clusterservice, "Agent").return_value = mock_agent

        service = ClusterClientService(Clock())
        fqdn = "%s.example.com" % factory.make_hostname()
        _get_config_rpc_info_urls = mocker.patch.object(
            service, "_get_config_rpc_info_urls"
        )
        _get_config_rpc_info_urls.return_value = ["http://%s/MAAS" % fqdn]
        _build_rpc_info_urls = mocker.patch.object(
            service, "_build_rpc_info_urls"
        )
        _build_rpc_info_urls.return_value = succeed(
            [([b"http://[::ffff:127.0.0.1]/MAAS"], "http://%s/MAAS" % fqdn)]
        )

        # Starting the service causes the first update to be performed.
        service.startService()

        mock_agent.request.assert_called_once_with(
            b"GET",
            ascii_url("http://[::ffff:127.0.0.1]/MAAS"),
            Headers(
                {
                    "User-Agent": [
                        "provisioningserver.rpc.clusterservice.ClusterClientService"
                    ],
                    "Host": [fqdn],
                }
            ),
        )

    # The following represents an example response from the RPC info
    # view in maasserver. Event-loops listen on ephemeral ports, and
    # it's up to the RPC info view to direct clients to them.
    example_rpc_info_view_response = json.dumps(
        {
            "eventloops": {
                # An event-loop in pid 1001 on host1. This host has two
                # configured IP addresses, 1.1.1.1 and 1.1.1.2.
                "host1:pid=1001": [
                    ("::ffff:1.1.1.1", 1111),
                    ("::ffff:1.1.1.2", 2222),
                ],
                # An event-loop in pid 2002 on host1. This host has two
                # configured IP addresses, 1.1.1.1 and 1.1.1.2.
                "host1:pid=2002": [
                    ("::ffff:1.1.1.1", 3333),
                    ("::ffff:1.1.1.2", 4444),
                ],
                # An event-loop in pid 3003 on host2. This host has one
                # configured IP address, 2.2.2.2.
                "host2:pid=3003": [("::ffff:2.2.2.2", 5555)],
            }
        }
    ).encode("ascii")

    def test_doUpdate_calls__update_connections(self, mocker, request):
        maas_url = "http://localhost/%s/" % factory.make_name("path")
        self.use_configuration(
            request, ClusterConfigurationFixture(maas_url=maas_url)
        )
        mocker.patch.object(
            socket, "getaddrinfo", autospec=True
        ).return_value = (
            None,
            None,
            None,
            None,
            ("::ffff:127.0.0.1", 80, 0, 1),
        )
        self.fakeAgentResponse(
            mocker, data=self.example_rpc_info_view_response
        )
        service = ClusterClientService(Clock())
        _update_connections = mocker.patch.object(
            service, "_update_connections"
        )
        service.startService()
        _update_connections.assert_called_once_with(
            {
                "host2:pid=3003": [["::ffff:2.2.2.2", 5555]],
                "host1:pid=2002": [
                    ["::ffff:1.1.1.1", 3333],
                    ["::ffff:1.1.1.2", 4444],
                ],
                "host1:pid=1001": [
                    ["::ffff:1.1.1.1", 1111],
                    ["::ffff:1.1.1.2", 2222],
                ],
            }
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_update_connections_initially(self, mocker):
        service = ClusterClientService(Clock())
        mock_client = Mock()
        _make_connection = mocker.patch.object(service, "_make_connection")
        _make_connection.side_effect = lambda *args: succeed(mock_client)
        _drop_connection = mocker.patch.object(service, "_drop_connection")

        info = json.loads(self.example_rpc_info_view_response.decode("ascii"))
        yield service._update_connections(info["eventloops"])

        _make_connection_expected = [
            call("host1:pid=1001", ("::ffff:1.1.1.1", 1111)),
            call("host1:pid=2002", ("::ffff:1.1.1.1", 3333)),
            call("host2:pid=3003", ("::ffff:2.2.2.2", 5555)),
        ]
        assert _make_connection_expected == _make_connection.call_args_list
        assert service.try_connections == {
            "host1:pid=1001": mock_client,
            "host1:pid=2002": mock_client,
            "host2:pid=3003": mock_client,
        }

        assert _drop_connection.mock_calls == []

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_update_connections_logs_fully_connected(self, request):
        service = ClusterClientService(Clock())
        eventloops = {
            "region1:123": [("::ffff:127.0.0.1", 1234)],
            "region1:124": [("::ffff:127.0.0.1", 1235)],
            "region2:123": [("::ffff:127.0.0.2", 1234)],
            "region2:124": [("::ffff:127.0.0.2", 1235)],
        }
        for eventloop, addresses in eventloops.items():
            for address in addresses:
                client = Mock()
                client.address = address
                service.connections[eventloop] = client

        logger = self.use_logger(request)

        yield service._update_connections(eventloops)
        # Second call should not add it to the log.
        yield service._update_connections(eventloops)

        assert logger.dump() == (
            "Fully connected to all 4 event-loops on all 2 region "
            "controllers (region1, region2)."
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_update_connections_connect_error_is_logged_tersely(
        self, mocker, request
    ):
        service = ClusterClientService(Clock())
        _make_connection = mocker.patch.object(service, "_make_connection")
        _make_connection.side_effect = error.ConnectionRefusedError()
        logger = self.use_logger(request)

        eventloops = {"an-event-loop": [("127.0.0.1", 1234)]}
        yield service._update_connections(eventloops)

        _make_connection.assert_called_once_with(
            "an-event-loop", ("::ffff:127.0.0.1", 1234)
        )

        assert logger.dump() == (
            "Making connections to event-loops: an-event-loop\n"
            "---\n"
            "Event-loop an-event-loop (::ffff:127.0.0.1:1234): Connection "
            "was refused by other side."
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_update_connections_unknown_error_is_logged_with_stack(
        self, mocker, request
    ):
        service = ClusterClientService(Clock())
        _make_connection = mocker.patch.object(service, "_make_connection")
        _make_connection.side_effect = RuntimeError("Something went wrong.")
        logger = self.use_logger(request)

        eventloops = {"an-event-loop": [("127.0.0.1", 1234)]}
        yield service._update_connections(eventloops)

        _make_connection.assert_called_once_with(
            "an-event-loop", ("::ffff:127.0.0.1", 1234)
        )

        assert logger.messages == [
            "Making connections to event-loops: an-event-loop",
            "Failure with event-loop an-event-loop (::ffff:127.0.0.1:1234)",
        ]
        failure_messages = [
            failure.getErrorMessage() for failure in logger.failures
        ]
        assert failure_messages == ["Something went wrong."]

    def test_update_connections_when_there_are_existing_connections(
        self, mocker
    ):
        service = ClusterClientService(Clock())
        _connect = mocker.patch.object(service, "_make_connection")
        _disconnect = mocker.patch.object(service, "_drop_connection")

        host1client = ClusterClient(
            ("::ffff:1.1.1.1", 1111), "host1:pid=1", service
        )
        host2client = ClusterClient(
            ("::ffff:2.2.2.2", 2222), "host2:pid=2", service
        )
        host3client = ClusterClient(
            ("::ffff:3.3.3.3", 3333), "host3:pid=3", service
        )

        # Fake some connections.
        service.connections = {
            host1client.eventloop: host1client,
            host2client.eventloop: host2client,
        }

        # Request a new set of connections that overlaps with the
        # existing connections.
        service._update_connections(
            {
                host1client.eventloop: [host1client.address],
                host3client.eventloop: [host3client.address],
            }
        )

        # A connection is made for host3's event-loop, and the
        # connection to host2's event-loop is dropped.
        _connect.assert_called_once_with(
            host3client.eventloop, host3client.address
        )
        _disconnect.assert_called_once_with(host2client)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_update_connections_replaces_connection_when_address_changes(
        self, mocker
    ):
        service = ClusterClientService(Clock())
        old_client = ClusterClient(
            ("::ffff:1.1.1.1", 1111), "host1:pid=1", service
        )
        new_client = Mock(address=("::ffff:2.2.2.2", 2222))
        _connect = mocker.patch.object(service, "_make_connection")
        _connect.return_value = succeed(new_client)
        # The old connection stays open until connectionLost fires later.
        _disconnect = mocker.patch.object(service, "_drop_connection")
        service.connections = {old_client.eventloop: old_client}

        yield service._update_connections(
            {old_client.eventloop: [new_client.address]}
        )

        _disconnect.assert_called_once_with(old_client)
        _connect.assert_called_once_with(
            old_client.eventloop, new_client.address
        )
        assert service.connections == {}
        assert service.try_connections == {old_client.eventloop: new_client}

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_update_connections_drops_both_tracked_and_pending_connections(
        self, mocker
    ):
        service = ClusterClientService(Clock())
        _disconnect = mocker.patch.object(service, "_drop_connection")
        connected = Mock(address=("::ffff:1.1.1.1", 1111))
        pending = Mock(address=("::ffff:1.1.1.1", 1111))
        service.connections = {"host1:pid=1": connected}
        service.try_connections = {"host1:pid=1": pending}

        yield service._update_connections({})

        assert sorted(_disconnect.mock_calls, key=str) == sorted(
            [call(connected), call(pending)], key=str
        )
        assert service.connections == {}
        assert service.try_connections == {}

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_update_only_updates_interval_when_eventloops_are_unknown(
        self, mocker, request
    ):
        service = ClusterClientService(Clock())
        mocker.patch.object(
            service, "_get_config_rpc_info_urls", autospec=True
        )
        mocker.patch.object(service, "_build_rpc_info_urls", autospec=True)
        mocker.patch.object(service, "_parallel_fetch_rpc_info", autospec=True)
        mocker.patch.object(service, "_update_connections", autospec=True)
        # Return urls from _get_config_rpc_info_urls and _build_rpc_info_urls.
        service._get_config_rpc_info_urls.return_value = [
            "http://127.0.0.1/MAAS"
        ]
        service._build_rpc_info_urls.return_value = succeed(
            [([b"http://[::ffff:127.0.0.1]/MAAS"], "http://127.0.0.1/MAAS")]
        )
        # Return None instead of a list of event-loop endpoints. This is the
        # response that the region will give when the advertising service is
        # not running.
        service._parallel_fetch_rpc_info.return_value = succeed((None, None))
        # Set the step to a bogus value so we can see it change.
        service.step = 999

        logger = self.use_logger(request)

        yield service.startService()

        service._update_connections.assert_not_called()
        assert service.INTERVAL_LOW == service.step
        assert logger.dump() == (
            "Region is not advertising RPC endpoints. (While requesting RPC"
            " info at http://127.0.0.1/MAAS)"
        )

    def test_make_connection(self, mocker):
        service = ClusterClientService(Clock())
        connectProtocol = mocker.patch.object(
            clusterservice, "connectProtocol"
        )
        service._make_connection("an-event-loop", ("a.example.com", 1111))
        connectProtocol.assert_called_once()
        endpoint, protocol = connectProtocol.call_args.args
        assert isinstance(endpoint, TCP6ClientEndpoint)
        assert endpoint._reactor is service.clock
        assert endpoint._host == "a.example.com"
        assert endpoint._port == 1111
        assert isinstance(protocol, ClusterClient)
        assert protocol.address == ("a.example.com", 1111)
        assert protocol.eventloop == "an-event-loop"
        assert protocol.service is service

    def test_drop_connection(self):
        connection = Mock()
        service = make_inert_client_service()
        service.startService()
        service._drop_connection(connection)
        connection.transport.loseConnection.assert_called_once_with()

    def test_drop_connection_if_connection_already_dropped(self):
        connection = Mock()
        connection.transport = None
        service = make_inert_client_service()
        service.startService()
        assert service._drop_connection(connection) is None

    def test_add_connection_removes_from_try_connections(self):
        service = make_inert_client_service()
        service.startService()
        endpoint = Mock()
        connection = Mock()
        connection.address = (":::ffff", 2222)
        service.try_connections[endpoint] = connection
        service.add_connection(endpoint, connection)
        assert service.try_connections == {}

    def test_add_connection_adds_to_connections(self):
        service = make_inert_client_service()
        service.startService()
        endpoint = Mock()
        connection = Mock()
        connection.address = (":::ffff", 2222)
        service.add_connection(endpoint, connection)
        assert service.connections == {endpoint: connection}

    def test_add_connection_calls__update_saved_rpc_info_state(self, mocker):
        service = make_inert_client_service()
        service.startService()
        endpoint = Mock()
        connection = Mock()
        connection.address = (":::ffff", 2222)
        update_saved_rpc_info_state = mocker.patch.object(
            service, "_update_saved_rpc_info_state", autospec=True
        )
        service.add_connection(endpoint, connection)
        update_saved_rpc_info_state.assert_called_once_with()

    def test_remove_connection_removes_from_try_connections(self):
        service = make_inert_client_service()
        service.startService()
        endpoint = Mock()
        connection = Mock()
        service.try_connections[endpoint] = connection
        service.remove_connection(endpoint, connection)
        assert service.try_connections == {}

    def test_remove_connection_removes_from_connections(self):
        service = make_inert_client_service()
        service.startService()
        endpoint = Mock()
        connection = Mock()
        service.connections[endpoint] = connection
        service.remove_connection(endpoint, connection)
        assert service.connections == {}

    def test_remove_connection_lowers_recheck_interval(self):
        service = make_inert_client_service()
        service.startService()
        endpoint = Mock()
        connection = Mock()
        service.connections[endpoint] = connection
        service.remove_connection(endpoint, connection)
        assert service.step == service.INTERVAL_LOW

    def test_getClient(self):
        service = ClusterClientService(Clock())
        service.connections = {
            sentinel.eventloop01: FakeConnection(),
            sentinel.eventloop02: FakeConnection(),
            sentinel.eventloop03: FakeConnection(),
        }
        assert service.getClient() in {
            common.Client(conn) for conn in service.connections.values()
        }

    def test_getClient_when_there_are_no_connections(self):
        service = ClusterClientService(Clock())
        service.connections = {}
        with pytest.raises(exceptions.NoConnectionsAvailable):
            service.getClient()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_getClientNow_returns_current_connection(self):
        service = ClusterClientService(Clock())
        service.connections = {
            sentinel.eventloop01: FakeConnection(),
            sentinel.eventloop02: FakeConnection(),
            sentinel.eventloop03: FakeConnection(),
        }
        client = yield service.getClientNow()
        assert client in [
            common.Client(conn) for conn in service.connections.values()
        ]

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_getClientNow_calls__tryUpdate_when_there_are_no_connections(
        self, mocker
    ):
        service = ClusterClientService(Clock())

        def addConnections():
            service.connections = {
                sentinel.eventloop01: FakeConnection(),
                sentinel.eventloop02: FakeConnection(),
                sentinel.eventloop03: FakeConnection(),
            }
            return succeed(None)

        mocker.patch.object(service, "_tryUpdate").side_effect = addConnections
        client = yield service.getClientNow()
        assert client in {
            common.Client(conn) for conn in service.connections.values()
        }

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_getClientNow_raises_exception_when_no_clients(self, mocker):
        service = ClusterClientService(Clock())

        mocker.patch.object(service, "_tryUpdate").return_value = succeed(None)
        with pytest.raises(exceptions.NoConnectionsAvailable):
            yield service.getClientNow()

    @wait_for(timeout=TIMEOUT)
    def test_tryUpdate_prevents_concurrent_calls_to__doUpdate(self, mocker):
        service = ClusterClientService(Clock())

        d_doUpdate_1, d_doUpdate_2 = Deferred(), Deferred()
        _doUpdate = mocker.patch.object(service, "_doUpdate")
        _doUpdate.side_effect = [d_doUpdate_1, d_doUpdate_2]

        # Try updating a couple of times concurrently.
        d_tryUpdate_1 = service._tryUpdate()
        d_tryUpdate_2 = service._tryUpdate()
        # _doUpdate completes and returns `done`.
        d_doUpdate_1.callback(sentinel.done1)
        # Both _tryUpdate calls yield the same result.
        assert extract_result(d_tryUpdate_1) is sentinel.done1
        assert extract_result(d_tryUpdate_2) is sentinel.done1
        # _doUpdate was called only once.
        _doUpdate.assert_called_once_with()

        # The mechanism has reset and is ready to go again.
        d_tryUpdate_3 = service._tryUpdate()
        d_doUpdate_2.callback(sentinel.done2)
        assert extract_result(d_tryUpdate_3) is sentinel.done2

    def test_getAllClients(self):
        service = ClusterClientService(Clock())
        uuid1 = factory.make_UUID()
        c1 = FakeConnection()
        service.connections[uuid1] = c1
        uuid2 = factory.make_UUID()
        c2 = FakeConnection()
        service.connections[uuid2] = c2
        clients = service.getAllClients()
        assert clients == [common.Client(c1), common.Client(c2)]

    def test_getAllClients_when_there_are_no_connections(self):
        service = ClusterClientService(Clock())
        assert service.getAllClients() == []


@pytest.mark.rack_reactor_guard
class TestClusterClientServiceIntervals:
    @pytest.mark.parametrize(
        "time_running,num_eventloops,num_connections,expected",
        [
            pytest.param(
                0, None, None, ClusterClientService.INTERVAL_LOW, id="initial"
            ),
            pytest.param(
                10,
                1,
                1,
                ClusterClientService.INTERVAL_LOW,
                id="shortly-after-start",
            ),
            pytest.param(
                1000,
                0,
                sentinel.undefined,
                ClusterClientService.INTERVAL_LOW,
                id="no-event-loops",
            ),
            pytest.param(
                1000,
                1,
                0,
                ClusterClientService.INTERVAL_LOW,
                id="no-connections",
            ),
            pytest.param(
                1000,
                2,
                1,
                ClusterClientService.INTERVAL_MID,
                id="fewer-connections-than-event-loops",
            ),
            pytest.param(
                1000,
                3,
                3,
                ClusterClientService.INTERVAL_HIGH,
                id="default",
            ),
        ],
    )
    def test_calculate_interval(
        self, time_running, num_eventloops, num_connections, expected
    ):
        service = make_inert_client_service()
        service.startService()
        service.clock.advance(time_running)
        assert expected == service._calculate_interval(
            num_eventloops, num_connections
        )


class TestClusterClientBase:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker, request):
        self.request = request
        self.mocker = mocker
        prior_secret = MAAS_SECRET.get()
        request.addfinalizer(lambda: MAAS_SECRET.set(prior_secret))
        fixture = ClusterConfigurationFixture(
            maas_url=factory.make_simple_http_url(),
        )
        fixture.setUp()
        request.addfinalizer(fixture.cleanUp)
        mocker.patch.object(
            clusterservice, "get_all_interfaces_definition"
        ).return_value = {}

    def make_running_client(self):
        client = clusterservice.ClusterClient(
            address=("example.com", 1234),
            eventloop="eventloop:pid=12345",
            service=make_inert_client_service(),
        )
        client.service.startService()
        return client


@pytest.mark.rack_reactor_guard
class TestClusterClientClusterCertificatesAreStored(TestClusterClientBase):
    @pytest.fixture(autouse=True)
    def _set_secret(self, request):
        prior_secret = MAAS_SECRET.get()
        MAAS_SECRET.set(factory.make_bytes())
        request.addfinalizer(lambda: MAAS_SECRET.set(prior_secret))

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_cluster_certificates_are_stored(self):
        maas_data = os.getenv("MAAS_ROOT")
        certs_dir = f"{maas_data}/certificates"
        os.mkdir(certs_dir)

        client = self.make_running_client()

        maasca = Certificate.generate_ca_certificate("maas")
        certificate_request = CertificateRequest.generate("request")
        certificate = maasca.sign_certificate_request(certificate_request)

        callRemote = self.mocker.patch.object(
            client, "callRemote", autospec=True
        )
        callRemote.side_effect = always_succeed_with(
            {
                "system_id": "...",
                "encrypted_cluster_certificate": fernet_encrypt_psk(
                    json.dumps(
                        {
                            "cert": certificate.certificate_pem(),
                            "key": certificate.private_key_pem(),
                            "cacerts": certificate.ca_certificates_pem(),
                        }
                    )
                ),
            }
        )

        result = yield client.registerRackWithRegion()
        assert result
        assert get_maas_cluster_cert_paths() == (
            f"{certs_dir}/cluster.pem",
            f"{certs_dir}/cluster.key",
            f"{certs_dir}/cacerts.pem",
        )


@pytest.mark.rack_reactor_guard
class TestClusterClientRackControllerCertificatesAreStored(
    TestClusterClientBase
):
    @pytest.fixture(autouse=True)
    def _set_secret(self, request):
        prior_secret = MAAS_SECRET.get()
        MAAS_SECRET.set(factory.make_bytes())
        request.addfinalizer(lambda: MAAS_SECRET.set(prior_secret))

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_rack_controller_certificates_are_stored(self):
        maas_data = os.getenv("MAAS_ROOT")
        certs_dir = f"{maas_data}/certificates"
        os.mkdir(certs_dir)

        client = self.make_running_client()

        maasca = Certificate.generate_ca_certificate("maas")
        certificate_request = CertificateRequest.generate("request")
        certificate = maasca.sign_certificate_request(certificate_request)

        callRemote = self.mocker.patch.object(
            client, "callRemote", autospec=True
        )
        callRemote.side_effect = always_succeed_with(
            {
                "system_id": "...",
                "encrypted_cluster_certificate": fernet_encrypt_psk(
                    json.dumps(
                        {
                            "cert": certificate.certificate_pem(),
                            "key": certificate.private_key_pem(),
                            "cacerts": certificate.ca_certificates_pem(),
                        }
                    )
                ),
            }
        )

        result = yield client.registerRackWithRegion()
        assert result
        assert get_maas_rack_controller_cert_paths() == (
            f"{certs_dir}/rackcontroller.crt",
            f"{certs_dir}/rackcontroller.key",
            f"{certs_dir}/ca.pem",
        )


@pytest.mark.rack_reactor_guard
class TestClusterClient(TestClusterClientBase):
    @pytest.fixture(autouse=True)
    def _setup_client_paths(self, mocker):
        mocker.patch.object(
            certificates, "get_maas_cluster_cert_paths"
        ).return_value = ("/test", "/test", "/test")

    def patch_authenticate_for_success(self, client):
        authenticate = self.mocker.patch.object(
            client, "authenticateRegion", autospec=True
        )
        authenticate.side_effect = always_succeed_with(True)

    def patch_authenticate_for_failure(self, client):
        authenticate = self.mocker.patch.object(
            client, "authenticateRegion", autospec=True
        )
        authenticate.side_effect = always_succeed_with(False)

    def patch_authenticate_for_error(self, client, exception):
        authenticate = self.mocker.patch.object(
            client, "authenticateRegion", autospec=True
        )
        authenticate.side_effect = always_fail_with(exception)

    def patch_register_for_success(self, client):
        register = self.mocker.patch.object(
            client, "registerRackWithRegion", autospec=True
        )
        register.side_effect = always_succeed_with(True)

    def patch_register_for_failure(self, client):
        register = self.mocker.patch.object(
            client, "registerRackWithRegion", autospec=True
        )
        register.side_effect = always_succeed_with(False)

    def patch_register_for_error(self, client, exception):
        register = self.mocker.patch.object(
            client, "registerRackWithRegion", autospec=True
        )
        register.side_effect = always_fail_with(exception)

    def test_interfaces(self):
        client = self.make_running_client()
        # transport.getHandle() is used by AMP._getPeerCertificate, which we
        # call indirectly via the peerCertificate attribute in IConnection.
        self.mocker.patch.object(client, "transport")
        verifyObject(IConnection, client)

    def test_ident(self):
        client = self.make_running_client()
        client.eventloop = factory.make_name("eventloop")
        assert client.eventloop == client.ident

    def test_connecting(self):
        client = self.make_running_client()
        client.service.try_connections[client.eventloop] = client
        self.patch_authenticate_for_success(client)
        self.patch_register_for_success(client)
        assert client.service.connections == {}
        wait_for_authenticated = client.authenticated.get()
        assert isinstance(wait_for_authenticated, Deferred)
        assert not wait_for_authenticated.called
        wait_for_ready = client.ready.get()
        assert isinstance(wait_for_ready, Deferred)
        assert not wait_for_ready.called
        client.connectionMade()
        # authenticated has been set to True, denoting a successfully
        # authenticated region.
        assert extract_result(wait_for_authenticated)
        # ready has been set with the name of the event-loop.
        assert client.eventloop == extract_result(wait_for_ready)
        assert len(client.service.try_connections) == 0
        assert client.service.connections == {client.eventloop: client}

    def test_disconnects_when_there_is_an_existing_connection(self):
        client = self.make_running_client()

        # Pretend that a connection already exists for this address.
        client.service.connections[client.eventloop] = sentinel.connection

        # Connect via an in-memory transport.
        transport = StringTransportWithDisconnection()
        transport.protocol = client
        client.makeConnection(transport)

        # authenticated was set to None to signify that authentication was not
        # attempted.
        assert extract_result(client.authenticated.get()) is None
        # ready was set with KeyError to signify that a connection to the
        # same event-loop already existed.
        with pytest.raises(KeyError):
            extract_result(client.ready.get())

        # The connections list is unchanged because the new connection
        # immediately disconnects.
        assert client.service.connections == {
            client.eventloop: sentinel.connection
        }
        assert not client.connected
        assert client.transport is None

    def test_disconnects_when_service_is_not_running(self):
        client = self.make_running_client()
        client.service.running = False

        # Connect via an in-memory transport.
        transport = StringTransportWithDisconnection()
        transport.protocol = client
        client.makeConnection(transport)

        # authenticated was set to None to signify that authentication was not
        # attempted.
        assert extract_result(client.authenticated.get()) is None
        # ready was set with RuntimeError to signify that the client
        # service was not running.
        with pytest.raises(RuntimeError):
            extract_result(client.ready.get())

        # The connections list is unchanged because the new connection
        # immediately disconnects.
        assert client.service.connections == {}
        assert not client.connected

    def test_disconnects_when_authentication_fails(self):
        client = self.make_running_client()
        self.patch_authenticate_for_failure(client)
        self.patch_register_for_success(client)

        # Connect via an in-memory transport.
        transport = StringTransportWithDisconnection()
        transport.protocol = client
        client.makeConnection(transport)

        # authenticated was set to False.
        assert not extract_result(client.authenticated.get())
        # ready was set with AuthenticationFailed.
        with pytest.raises(exceptions.AuthenticationFailed):
            extract_result(client.ready.get())

        # The connections list is unchanged because the new connection
        # immediately disconnects.
        assert client.service.connections == {}
        assert not client.connected

    def test_disconnects_when_authentication_errors(self):
        client = self.make_running_client()
        exception_type = factory.make_exception_type()
        self.patch_authenticate_for_error(client, exception_type())
        self.patch_register_for_success(client)

        logger = TwistedLoggerFixture()
        logger.setUp()
        self.request.addfinalizer(logger.cleanUp)

        # Connect via an in-memory transport.
        transport = StringTransportWithDisconnection()
        transport.protocol = client
        client.makeConnection(transport)

        # authenticated errbacks with the error.
        with pytest.raises(exception_type):
            extract_result(client.authenticated.get())
        # ready also errbacks with the same error.
        with pytest.raises(exception_type):
            extract_result(client.ready.get())

        # The log was written to.
        assert (
            "Event-loop 'eventloop:pid=12345' handshake failed; dropping connection."
            in {err["why"] for err in logger.errors}
        )

        # The connections list is unchanged because the new connection
        # immediately disconnects.
        assert client.service.connections == {}
        assert not client.connected

    def test_disconnects_when_registration_fails(self):
        client = self.make_running_client()
        self.patch_authenticate_for_success(client)
        self.patch_register_for_failure(client)

        # Connect via an in-memory transport.
        transport = StringTransportWithDisconnection()
        transport.protocol = client
        client.makeConnection(transport)

        # authenticated was set to True because it succeeded.
        assert extract_result(client.authenticated.get())
        # ready was set with AuthenticationFailed.
        with pytest.raises(exceptions.RegistrationFailed):
            extract_result(client.ready.get())

        # The connections list is unchanged because the new connection
        # immediately disconnects.
        assert client.service.connections == {}
        assert not client.connected

    def test_disconnects_when_registration_errors(self):
        client = self.make_running_client()
        exception_type = factory.make_exception_type()
        self.patch_authenticate_for_success(client)
        self.patch_register_for_error(client, exception_type())

        logger = TwistedLoggerFixture()
        logger.setUp()
        self.request.addfinalizer(logger.cleanUp)

        # Connect via an in-memory transport.
        transport = StringTransportWithDisconnection()
        transport.protocol = client
        client.makeConnection(transport)

        # authenticated was set to True because it succeeded.
        assert extract_result(client.authenticated.get())
        # ready was set with the exception we made.
        with pytest.raises(exception_type):
            extract_result(client.ready.get())

        # The log was written to.
        assert (
            "Event-loop 'eventloop:pid=12345' handshake failed; dropping connection."
            in {err["why"] for err in logger.errors}
        )

        # The connections list is unchanged because the new connection
        # immediately disconnects.
        assert client.service.connections == {}
        assert not client.connected

    def test_handshakeFailed_does_not_log_when_connection_is_closed(self):
        client = self.make_running_client()
        with TwistedLoggerFixture() as logger:
            client.handshakeFailed(Failure(ConnectionClosed()))
        # ready was set with ConnectionClosed.
        with pytest.raises(ConnectionClosed):
            extract_result(client.ready.get())
        # Nothing was logged.
        assert logger.output == ""

    def test_authenticateRegion_accepts_matching_digests(self):
        MAAS_SECRET.set(factory.make_bytes())
        client = self.make_running_client()

        def respond_as_region(_, message):
            salt = os.urandom(16)
            digest = calculate_digest(
                MAAS_SECRET.get(), message, b"rack-to-region", salt
            )
            return succeed({"digest": digest, "salt": salt})

        callRemote = self.mocker.patch.object(
            client, "callRemote", autospec=True
        )
        callRemote.side_effect = respond_as_region

        d = client.authenticateRegion()
        assert extract_result(d)

    def test_authenticateRegion_rejects_cross_role_digest(self):
        MAAS_SECRET.set(factory.make_bytes())
        client = self.make_running_client()

        def respond_with_cluster_digest(_, message):
            return succeed(Cluster().authenticate(message))

        callRemote = self.mocker.patch.object(
            client, "callRemote", autospec=True
        )
        callRemote.side_effect = respond_with_cluster_digest

        d = client.authenticateRegion()
        assert not extract_result(d)

    def test_authenticateRegion_rejects_non_matching_digests(self):
        MAAS_SECRET.set(factory.make_bytes())
        client = self.make_running_client()

        def respond_with_invalid_digest(_, message):
            response = {
                "digest": factory.make_bytes(),
                "salt": factory.make_bytes(),
            }
            return succeed(response)

        callRemote = self.mocker.patch.object(
            client, "callRemote", autospec=True
        )
        callRemote.side_effect = respond_with_invalid_digest

        d = client.authenticateRegion()
        assert not extract_result(d)

    def test_authenticateRegion_propagates_errors(self):
        client = self.make_running_client()
        exception_type = factory.make_exception_type()

        callRemote = self.mocker.patch.object(
            client, "callRemote", autospec=True
        )
        callRemote.return_value = fail(exception_type())

        d = client.authenticateRegion()
        with pytest.raises(exception_type):
            extract_result(d)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_authenticateRegion_end_to_end(self, request):
        fixture = MockLiveClusterToRegionRPCFixture()
        shutdown = [lambda: succeed(None)]
        _register_rpc_fixture_cleanup(request, fixture, shutdown)
        yield fixture.setUp()
        protocol, connecting = fixture.makeEventLoop()
        shutdown[0] = yield connecting
        yield getRegionClient()
        protocol.Authenticate.assert_called_once_with(protocol, message=ANY)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_registerRackWithRegion_returns_True_when_accepted(self):
        logger = TwistedLoggerFixture()
        logger.setUp()
        self.request.addfinalizer(logger.cleanUp)
        client = self.make_running_client()

        callRemote = self.mocker.patch.object(
            client, "callRemote", autospec=True
        )
        callRemote.side_effect = always_succeed_with({"system_id": "..."})

        result = yield client.registerRackWithRegion()
        assert result

        assert (
            f"Rack controller '{client.localIdent}' registered (via eventloop:pid=12345) with MAAS version 2.2 or below."
            in logger.dump()
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_registerRackWithRegion_logs_version_if_supplied(self):
        client = self.make_running_client()

        callRemote = self.mocker.patch.object(
            client, "callRemote", autospec=True
        )
        callRemote.side_effect = always_succeed_with(
            {"system_id": "...", "version": "2.3.0"}
        )

        logger = TwistedLoggerFixture()
        logger.setUp()
        self.request.addfinalizer(logger.cleanUp)

        result = yield client.registerRackWithRegion()
        assert result

        assert (
            "Rack controller '...' registered (via eventloop:pid=12345) with MAAS version 2.3.0."
            in logger.output
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_registerRackWithRegion_logs_unknown_version_if_empty(self):
        client = self.make_running_client()

        callRemote = self.mocker.patch.object(
            client, "callRemote", autospec=True
        )
        callRemote.side_effect = always_succeed_with(
            {"system_id": "...", "version": ""}
        )

        logger = TwistedLoggerFixture()
        logger.setUp()
        self.request.addfinalizer(logger.cleanUp)

        result = yield client.registerRackWithRegion()
        assert result

        assert (
            "Rack controller '...' registered (via eventloop:pid=12345) with unknown MAAS version."
            in logger.output
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_registerRackWithRegion_sets_localIdent(self):
        client = self.make_running_client()

        system_id = factory.make_name("id")
        callRemote = self.mocker.patch.object(
            client, "callRemote", autospec=True
        )
        callRemote.side_effect = always_succeed_with({"system_id": system_id})

        result = yield client.registerRackWithRegion()
        assert result
        assert system_id == client.localIdent

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_registerRackWithRegion_calls_set_maas_id(self):
        def set_id(maas_id):
            self.maas_id = maas_id

        set_id_mock = self.mocker.patch.object(clusterservice.MAAS_ID, "set")
        set_id_mock.side_effect = set_id

        client = self.make_running_client()

        system_id = factory.make_name("id")
        callRemote = self.mocker.patch.object(
            client, "callRemote", autospec=True
        )
        callRemote.side_effect = always_succeed_with({"system_id": system_id})

        result = yield client.registerRackWithRegion()
        assert result
        set_id_mock.assert_called_once_with(system_id)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_registerRackWithRegion_sets_global_labels(self):
        mock_set_global_labels = self.mocker.patch.object(
            clusterservice, "set_global_labels"
        )
        client = self.make_running_client()

        system_id = factory.make_name("id")
        callRemote = self.mocker.patch.object(
            client, "callRemote", autospec=True
        )
        callRemote.side_effect = always_succeed_with(
            {"system_id": system_id, "uuid": "a-b-c"}
        )

        result = yield client.registerRackWithRegion()
        assert result
        mock_set_global_labels.assert_called_once_with(maas_uuid="a-b-c")

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_registerRackWithRegion_sets_uuid(self):
        maas_uuid = factory.make_name("uuid")
        client = self.make_running_client()

        system_id = factory.make_name("id")
        callRemote = self.mocker.patch.object(
            client, "callRemote", autospec=True
        )
        callRemote.side_effect = always_succeed_with(
            {"system_id": system_id, "uuid": maas_uuid}
        )

        result = yield client.registerRackWithRegion()
        assert result
        assert MAAS_UUID.get() == maas_uuid

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_registerRackWithRegion_returns_False_when_rejected(self):
        client = self.make_running_client()

        callRemote = self.mocker.patch.object(
            client, "callRemote", autospec=True
        )
        callRemote.return_value = fail(
            exceptions.CannotRegisterRackController()
        )

        logger = TwistedLoggerFixture()
        logger.setUp()
        self.request.addfinalizer(logger.cleanUp)

        result = yield client.registerRackWithRegion()
        assert not result

        assert logger.output == (
            "Rack controller REJECTED by the region (via eventloop:pid=12345)."
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_registerRackWithRegion_propagates_errors(self):
        client = self.make_running_client()
        exception_type = factory.make_exception_type()

        callRemote = self.mocker.patch.object(
            client, "callRemote", autospec=True
        )
        callRemote.return_value = fail(exception_type())

        with pytest.raises(exception_type):
            yield client.registerRackWithRegion()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_registerRackWithRegion_end_to_end(self):
        system_id = factory.make_name("id")
        MAAS_ID.set(system_id)
        maas_url = factory.make_simple_http_url()
        hostname = "rackcontrol.example.com"
        self.mocker.patch.object(
            clusterservice, "gethostname", autospec=True
        ).return_value = hostname
        config_fixture = ClusterConfigurationFixture()
        config_fixture.setUp()
        self.request.addfinalizer(config_fixture.cleanUp)
        fixture = MockLiveClusterToRegionRPCFixture(maas_url)
        shutdown = [lambda: succeed(None)]
        _register_rpc_fixture_cleanup(self.request, fixture, shutdown)
        yield fixture.setUp()
        protocol, connecting = fixture.makeEventLoop()
        shutdown[0] = yield connecting
        yield getRegionClient()
        protocol.RegisterRackController.assert_called_once_with(
            protocol,
            system_id=system_id,
            hostname=hostname,
            interfaces={},
            url=urlparse(maas_url),
            beacon_support=True,
            version=str(get_running_version()),
            rack_controller_uuid=None,
        )


@pytest.mark.rack_reactor_guard
class TestClusterClientCheckerService:
    def make_client(self):
        client = Mock()
        client.return_value = succeed(None)
        return client

    def test_init_sets_up_timer_correctly(self):
        service = ClusterClientCheckerService(
            sentinel.client_service, sentinel.clock
        )
        assert service.call == (service.tryLoop, (), {})
        assert service.step == 30
        assert service.client_service is sentinel.client_service
        assert service.clock is sentinel.clock

    def test_tryLoop_calls_loop(self, mocker):
        service = ClusterClientCheckerService(
            sentinel.client_service, sentinel.clock
        )
        mock_loop = mocker.patch.object(
            service, "loop", return_value=succeed(None)
        )
        service.tryLoop()
        mock_loop.assert_called_once_with()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_loop_does_nothing_with_no_clients(self):
        mock_client_service = MagicMock()
        mock_client_service.getAllClients.return_value = []
        service = ClusterClientCheckerService(mock_client_service, reactor)
        # Test will timeout if this blocks longer than 5 seconds.
        yield service.loop()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_loop_calls_ping_for_each_client(self):
        clients = [self.make_client() for _ in range(3)]
        mock_client_service = MagicMock()
        mock_client_service.getAllClients.return_value = clients
        service = ClusterClientCheckerService(mock_client_service, reactor)
        yield service.loop()
        for client in clients:
            client.assert_called_once_with(common.Ping, _timeout=10)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_ping_calls_loseConnection_on_failure(self):
        client = MagicMock()
        client.return_value = fail(factory.make_exception())
        mock_client_service = MagicMock()
        service = ClusterClientCheckerService(mock_client_service, reactor)
        yield service._ping(client)
        client._conn.transport.loseConnection.assert_called_once_with()


@pytest.mark.rack_reactor_guard
class TestClusterProtocol_PowerQuery:
    def test_is_registered(self):
        protocol = Cluster()
        responder = protocol.locateResponder(cluster.PowerQuery.commandName)
        assert responder is not None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_returns_power_state(self, mocker):
        state = random.choice(["on", "off"])
        perform_power_driver_query = mocker.patch.object(
            power_module, "perform_power_driver_query"
        )
        perform_power_driver_query.return_value = state
        power_driver = random.choice(
            [driver for _, driver in PowerDriverRegistry if driver.queryable]
        )
        arguments = {
            "system_id": factory.make_name("system"),
            "hostname": factory.make_name("hostname"),
            "power_type": power_driver.name,
            "context": factory.make_name("context"),
        }

        # Make sure power driver doesn't check for installed packages.
        mocker.patch.object(
            power_driver, "detect_missing_packages"
        ).return_value = []

        observed = yield call_responder(
            Cluster(), cluster.PowerQuery, arguments
        )
        assert {"state": state, "error_msg": None} == observed
        perform_power_driver_query.assert_called_once_with(
            arguments["system_id"],
            arguments["hostname"],
            arguments["power_type"],
            arguments["context"],
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_returns_power_error(self, mocker):
        perform_power_driver_query = mocker.patch.object(
            power_module, "perform_power_driver_query"
        )
        perform_power_driver_query.side_effect = PowerError("Error message")
        power_driver = random.choice(
            [driver for _, driver in PowerDriverRegistry if driver.queryable]
        )
        arguments = {
            "system_id": factory.make_name("system"),
            "hostname": factory.make_name("hostname"),
            "power_type": power_driver.name,
            "context": factory.make_name("context"),
        }

        # Make sure power driver doesn't check for installed packages.
        mocker.patch.object(
            power_driver, "detect_missing_packages"
        ).return_value = []

        observed = yield call_responder(
            Cluster(), cluster.PowerQuery, arguments
        )
        assert {
            "state": "error",
            "error_msg": "Error message",
        } == observed
        perform_power_driver_query.assert_called_once_with(
            arguments["system_id"],
            arguments["hostname"],
            arguments["power_type"],
            arguments["context"],
        )


@pytest.mark.rack_reactor_guard
class TestClusterProtocol_ScanNetworks:
    @pytest.fixture(autouse=True)
    def wait_for_deferred_threads(self, mocker, request):
        deferreds = []
        original_defer_to_thread = clusterservice.deferToThread

        def defer_to_thread(function, *args, **kwargs):
            deferred = original_defer_to_thread(function, *args, **kwargs)
            deferreds.append(deferred)
            return deferred

        mocker.patch.object(clusterservice, "deferToThread", defer_to_thread)

        @wait_for(timeout=TIMEOUT)
        @inlineCallbacks
        def wait_for_deferreds():
            for deferred in deferreds:
                yield deferred

        request.addfinalizer(wait_for_deferreds)

    def test_is_registered(self):
        protocol = Cluster()
        responder = protocol.locateResponder(cluster.ScanNetworks.commandName)
        assert responder is not None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_raises_refresh_already_in_progress_when_locked(self):
        with NamedLock("scan-networks"):
            with pytest.raises(exceptions.ScanNetworksAlreadyInProgress):
                yield call_responder(
                    Cluster(), cluster.ScanNetworks, {"scan_all": True}
                )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_acquires_lock_when_scanning_releases_when_done(self, mocker):
        def mock_scan(*args, **kwargs):
            lock = NamedLock("scan-networks")
            assert lock.is_locked()

        mocker.patch.object(
            clusterservice, "executeScanNetworksSubprocess", mock_scan
        )

        yield call_responder(
            Cluster(), cluster.ScanNetworks, {"scan_all": True}
        )

        lock = NamedLock("scan-networks")
        assert not lock.is_locked()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_releases_on_error(self, mocker):
        exception = factory.make_exception()
        mock_scan = mocker.patch.object(
            clusterservice, "executeScanNetworksSubprocess"
        )
        mock_scan.side_effect = exception

        with TwistedLoggerFixture() as logger:
            yield call_responder(
                Cluster(), cluster.ScanNetworks, {"scan_all": True}
            )

        # The failure is logged
        assert "Failed to scan all networks." in {
            err["why"] for err in logger.errors
        }

        # The lock is released
        lock = NamedLock("scan-networks")
        assert not lock.is_locked()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_wraps_subprocess_scan_in_maybeDeferred(self, mocker):
        mock_maybeDeferred = mocker.patch.object(
            clusterservice, "maybeDeferred", autospec=True
        )
        mock_maybeDeferred.side_effect = (succeed(None),)

        yield call_responder(
            Cluster(), cluster.ScanNetworks, {"scan_all": True}
        )

        mock_maybeDeferred.assert_called_once_with(
            clusterservice.executeScanNetworksSubprocess,
            cidrs=None,
            force_ping=None,
            interface=None,
            scan_all=True,
            slow=None,
            threads=None,
        )

    def test_get_scan_all_networks_args_asserts_for_invalid_config(self):
        with pytest.raises(AssertionError, match="Invalid scan parameters.*"):
            get_scan_all_networks_args()

    def test_get_scan_all_networks_args_returns_expected_binary_args(self):
        args = get_scan_all_networks_args(scan_all=True)
        assert args == [
            get_maas_common_command().encode("utf-8"),
            b"scan-network",
        ]

    def test_get_scan_all_networks_args_returns_supplied_cidrs(self):
        args = get_scan_all_networks_args(
            cidrs=[IPNetwork("192.168.0.0/24"), IPNetwork("192.168.1.0/24")]
        )
        assert args == [
            get_maas_common_command().encode("utf-8"),
            b"scan-network",
            b"192.168.0.0/24",
            b"192.168.1.0/24",
        ]

    def test_get_scan_all_networks_args_returns_supplied_interface(self):
        args = get_scan_all_networks_args(interface="eth0")
        assert args == [
            get_maas_common_command().encode("utf-8"),
            b"scan-network",
            b"eth0",
        ]

    def test_get_scan_all_networks_with_all_optional_arguments(self):
        threads = random.randint(1, 10)
        args = get_scan_all_networks_args(
            scan_all=False,
            slow=True,
            threads=threads,
            force_ping=True,
            interface="eth0",
            cidrs=[IPNetwork("192.168.0.0/24"), IPNetwork("192.168.1.0/24")],
        )
        assert args == [
            get_maas_common_command().encode("utf-8"),
            b"scan-network",
            b"--threads",
            str(threads).encode("utf-8"),
            b"--ping",
            b"--slow",
            b"eth0",
            b"192.168.0.0/24",
            b"192.168.1.0/24",
        ]

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_spawnProcessAndNullifyStdout_nullifies_stdout(self):
        done, protocol = makeDeferredWithProcessProtocol()
        args = [b"/bin/bash", b"-c", b"echo foo"]
        outReceived = Mock()
        protocol.outReceived = outReceived
        spawnProcessAndNullifyStdout(protocol, args)
        yield done
        outReceived.assert_not_called()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_spawnProcessAndNullifyStdout_captures_stderr(self):
        done, protocol = makeDeferredWithProcessProtocol()
        args = [b"/bin/bash", b"-c", b"echo foo >&2"]
        errReceived = Mock()
        protocol.errReceived = errReceived
        spawnProcessAndNullifyStdout(protocol, args)
        yield done
        errReceived.assert_called_once_with(b"foo\n")

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_executeScanNetworksSubprocess(self, mocker):
        mock_scan_args = mocker.patch.object(
            clusterservice, "get_scan_all_networks_args"
        )
        mock_scan_args.return_value = [b"/bin/bash", b"-c", b"echo -n foo >&2"]
        mock_log_msg = mocker.patch.object(clusterservice.log, "msg")
        d = executeScanNetworksSubprocess()
        yield d
        mock_log_msg.assert_called_once_with("Scan all networks: foo")


@pytest.mark.rack_reactor_guard
class TestClusterProtocol_AddChassis:
    @pytest.fixture(autouse=True)
    def wait_for_deferred_threads(self, mocker, request):
        deferreds = []
        original_defer_to_thread = clusterservice.deferToThread

        def defer_to_thread(function, *args, **kwargs):
            deferred = original_defer_to_thread(function, *args, **kwargs)
            deferreds.append(deferred)
            return deferred

        mocker.patch.object(clusterservice, "deferToThread", defer_to_thread)

        @wait_for(timeout=TIMEOUT)
        @inlineCallbacks
        def wait_for_deferreds():
            for deferred in deferreds:
                yield deferred

        request.addfinalizer(wait_for_deferreds)

    def test_is_registered(self):
        protocol = Cluster()
        responder = protocol.locateResponder(cluster.AddChassis.commandName)
        assert responder is not None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_chassis_type_virsh_calls_probe_virsh_and_enlist(self, mocker):
        mock_deferToThread = mocker.patch.object(
            clusterservice, "deferToThread", autospec=True
        )
        user = factory.make_name("user")
        hostname = factory.make_hostname()
        password = factory.make_name("password")
        accept_all = factory.pick_bool()
        domain = factory.make_name("domain")
        prefix_filter = factory.make_name("prefix_filter")
        yield call_responder(
            Cluster(),
            cluster.AddChassis,
            {
                "user": user,
                "chassis_type": "virsh",
                "hostname": hostname,
                "password": password,
                "accept_all": accept_all,
                "domain": domain,
                "prefix_filter": prefix_filter,
            },
        )
        mock_deferToThread.assert_called_once_with(
            clusterservice.probe_virsh_and_enlist,
            user,
            hostname,
            password,
            prefix_filter,
            accept_all,
            domain,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_chassis_type_powerkvm_calls_probe_virsh_and_enlist(self, mocker):
        mock_deferToThread = mocker.patch.object(
            clusterservice, "deferToThread", autospec=True
        )
        user = factory.make_name("user")
        hostname = factory.make_hostname()
        password = factory.make_name("password")
        accept_all = factory.pick_bool()
        domain = factory.make_name("domain")
        prefix_filter = factory.make_name("prefix_filter")
        yield call_responder(
            Cluster(),
            cluster.AddChassis,
            {
                "user": user,
                "chassis_type": "powerkvm",
                "hostname": hostname,
                "password": password,
                "accept_all": accept_all,
                "domain": domain,
                "prefix_filter": prefix_filter,
            },
        )
        mock_deferToThread.assert_called_once_with(
            clusterservice.probe_virsh_and_enlist,
            user,
            hostname,
            password,
            prefix_filter,
            accept_all,
            domain,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_chassis_type_virsh_logs_error_to_maaslog(self, mocker):
        fake_error = factory.make_name("error")
        mocker.patch.object(clusterservice, "maaslog")
        mock_deferToThread = mocker.patch.object(
            clusterservice, "deferToThread", autospec=True
        )
        mock_deferToThread.return_value = fail(Exception(fake_error))
        user = factory.make_name("user")
        hostname = factory.make_hostname()
        password = factory.make_name("password")
        accept_all = factory.pick_bool()
        domain = factory.make_name("domain")
        prefix_filter = factory.make_name("prefix_filter")
        yield call_responder(
            Cluster(),
            cluster.AddChassis,
            {
                "user": user,
                "chassis_type": "powerkvm",
                "hostname": hostname,
                "password": password,
                "accept_all": accept_all,
                "domain": domain,
                "prefix_filter": prefix_filter,
            },
        )
        clusterservice.maaslog.error.assert_any_call(
            "Failed to probe and enlist %s nodes: %s", "virsh", fake_error
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_chassis_type_proxmox_calls_probe_proxmoxand_enlist(self, mocker):
        mock_proxmox = mocker.patch.object(
            clusterservice, "probe_proxmox_and_enlist", autospec=True
        )
        user = factory.make_name("user")
        hostname = factory.make_hostname()
        username = factory.make_name("username")
        password = factory.make_name("password")
        token_name = factory.make_name("token_name")
        token_secret = factory.make_name("token_secret")
        verify_ssl = factory.pick_bool()
        accept_all = factory.pick_bool()
        domain = factory.make_name("domain")
        prefix_filter = factory.make_name("prefix_filter")
        yield call_responder(
            Cluster(),
            cluster.AddChassis,
            {
                "user": user,
                "chassis_type": "proxmox",
                "hostname": hostname,
                "username": username,
                "password": password,
                "token_name": token_name,
                "token_secret": token_secret,
                "verify_ssl": verify_ssl,
                "accept_all": accept_all,
                "domain": domain,
                "prefix_filter": prefix_filter,
            },
        )
        mock_proxmox.assert_called_once_with(
            user,
            hostname,
            username,
            password,
            token_name,
            token_secret,
            verify_ssl,
            accept_all,
            domain,
            prefix_filter,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_chassis_type_proxmox_logs_error_to_maaslog(self, mocker):
        fake_error = factory.make_name("error")
        mocker.patch.object(clusterservice, "maaslog")
        mock_proxmox = mocker.patch.object(
            clusterservice, "probe_proxmox_and_enlist", autospec=True
        )
        mock_proxmox.return_value = fail(Exception(fake_error))
        user = factory.make_name("user")
        hostname = factory.make_hostname()
        username = factory.make_name("username")
        password = factory.make_name("password")
        token_name = factory.make_name("token_name")
        token_secret = factory.make_name("token_secret")
        verify_ssl = factory.pick_bool()
        accept_all = factory.pick_bool()
        domain = factory.make_name("domain")
        prefix_filter = factory.make_name("prefix_filter")
        yield call_responder(
            Cluster(),
            cluster.AddChassis,
            {
                "user": user,
                "chassis_type": "proxmox",
                "hostname": hostname,
                "username": username,
                "password": password,
                "token_name": token_name,
                "token_secret": token_secret,
                "verify_ssl": verify_ssl,
                "accept_all": accept_all,
                "domain": domain,
                "prefix_filter": prefix_filter,
            },
        )
        clusterservice.maaslog.error.assert_any_call(
            "Failed to probe and enlist %s nodes: %s",
            "proxmox",
            fake_error,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_chassis_type_hmcz_calls_probe_hmcz_and_enlist(self, mocker):
        mock_probe_hmcz_and_enlist = mocker.patch.object(
            clusterservice, "probe_hmcz_and_enlist", autospec=True
        )
        user = factory.make_name("user")
        hostname = factory.make_hostname()
        username = factory.make_name("username")
        password = factory.make_name("password")
        accept_all = factory.pick_bool()
        domain = factory.make_name("domain")
        prefix_filter = factory.make_name("prefix_filter")
        yield call_responder(
            Cluster(),
            cluster.AddChassis,
            {
                "user": user,
                "chassis_type": "hmcz",
                "hostname": hostname,
                "username": username,
                "password": password,
                "accept_all": accept_all,
                "domain": domain,
                "prefix_filter": prefix_filter,
            },
        )
        mock_probe_hmcz_and_enlist.assert_called_once_with(
            user,
            hostname,
            username,
            password,
            accept_all,
            domain,
            prefix_filter,
            None,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_chassis_type_hmcz_logs_error_to_maaslog(self, mocker):
        fake_error = factory.make_name("error")
        mocker.patch.object(clusterservice, "maaslog")
        mock_probe_hmcz_and_enlist = mocker.patch.object(
            clusterservice, "probe_hmcz_and_enlist", autospec=True
        )
        mock_probe_hmcz_and_enlist.return_value = fail(Exception(fake_error))
        user = factory.make_name("user")
        hostname = factory.make_hostname()
        username = factory.make_name("username")
        password = factory.make_name("password")
        accept_all = factory.pick_bool()
        domain = factory.make_name("domain")
        prefix_filter = factory.make_name("prefix_filter")
        yield call_responder(
            Cluster(),
            cluster.AddChassis,
            {
                "user": user,
                "chassis_type": "hmcz",
                "hostname": hostname,
                "username": username,
                "password": password,
                "accept_all": accept_all,
                "domain": domain,
                "prefix_filter": prefix_filter,
            },
        )
        clusterservice.maaslog.error.assert_any_call(
            "Failed to probe and enlist %s nodes: %s", "hmcz", fake_error
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_chassis_type_vmware_calls_probe_vmware_and_enlist(self, mocker):
        mock_deferToThread = mocker.patch.object(
            clusterservice, "deferToThread", autospec=True
        )
        user = factory.make_name("user")
        hostname = factory.make_hostname()
        username = factory.make_name("username")
        password = factory.make_name("password")
        accept_all = factory.pick_bool()
        domain = factory.make_name("domain")
        prefix_filter = factory.make_name("prefix_filter")
        port = random.choice([80, 443, 8080, 8443])
        protocol = random.choice(["http", "https"])
        yield call_responder(
            Cluster(),
            cluster.AddChassis,
            {
                "user": user,
                "chassis_type": "vmware",
                "hostname": hostname,
                "username": username,
                "password": password,
                "accept_all": accept_all,
                "domain": domain,
                "prefix_filter": prefix_filter,
                "port": port,
                "protocol": protocol,
            },
        )
        mock_deferToThread.assert_called_once_with(
            clusterservice.probe_vmware_and_enlist,
            user,
            hostname,
            username,
            password,
            port,
            protocol,
            prefix_filter,
            accept_all,
            domain,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_chassis_type_vmware_logs_error_to_maaslog(self, mocker):
        fake_error = factory.make_name("error")
        mocker.patch.object(clusterservice, "maaslog")
        mock_deferToThread = mocker.patch.object(
            clusterservice, "deferToThread", autospec=True
        )
        mock_deferToThread.return_value = fail(Exception(fake_error))
        user = factory.make_name("user")
        hostname = factory.make_hostname()
        username = factory.make_name("username")
        password = factory.make_name("password")
        accept_all = factory.pick_bool()
        domain = factory.make_name("domain")
        prefix_filter = factory.make_name("prefix_filter")
        port = random.choice([80, 443, 8080, 8443])
        protocol = random.choice(["http", "https"])
        yield call_responder(
            Cluster(),
            cluster.AddChassis,
            {
                "user": user,
                "chassis_type": "vmware",
                "hostname": hostname,
                "username": username,
                "password": password,
                "accept_all": accept_all,
                "domain": domain,
                "prefix_filter": prefix_filter,
                "port": port,
                "protocol": protocol,
            },
        )
        clusterservice.maaslog.error.assert_any_call(
            "Failed to probe and enlist %s nodes: %s", "VMware", fake_error
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_chassis_type_recs_calls_probe_and_enlist_recs(self, mocker):
        mock_deferToThread = mocker.patch.object(
            clusterservice, "deferToThread", autospec=True
        )
        user = factory.make_name("user")
        hostname = factory.make_hostname()
        username = factory.make_name("username")
        password = factory.make_name("password")
        accept_all = factory.pick_bool()
        domain = factory.make_name("domain")
        port = random.randint(2000, 4000)
        yield call_responder(
            Cluster(),
            cluster.AddChassis,
            {
                "user": user,
                "chassis_type": "recs_box",
                "hostname": hostname,
                "username": username,
                "password": password,
                "accept_all": accept_all,
                "domain": domain,
                "port": port,
            },
        )
        mock_deferToThread.assert_called_once_with(
            clusterservice.probe_and_enlist_recs,
            user,
            hostname,
            port,
            username,
            password,
            accept_all,
            domain,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_chassis_type_recs_logs_error_to_maaslog(self, mocker):
        fake_error = factory.make_name("error")
        mocker.patch.object(clusterservice, "maaslog")
        mock_deferToThread = mocker.patch.object(
            clusterservice, "deferToThread", autospec=True
        )
        mock_deferToThread.return_value = fail(Exception(fake_error))
        user = factory.make_name("user")
        hostname = factory.make_hostname()
        username = factory.make_name("username")
        password = factory.make_name("password")
        accept_all = factory.pick_bool()
        domain = factory.make_name("domain")
        port = random.randint(2000, 4000)
        yield call_responder(
            Cluster(),
            cluster.AddChassis,
            {
                "user": user,
                "chassis_type": "recs_box",
                "hostname": hostname,
                "username": username,
                "password": password,
                "accept_all": accept_all,
                "domain": domain,
                "port": port,
            },
        )
        clusterservice.maaslog.error.assert_any_call(
            "Failed to probe and enlist %s nodes: %s",
            "RECS|Box",
            fake_error,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_chassis_type_seamicro15k_calls_probe_seamicro15k_and_enlist(
        self, mocker
    ):
        mock_deferToThread = mocker.patch.object(
            clusterservice, "deferToThread", autospec=True
        )
        user = factory.make_name("user")
        hostname = factory.make_hostname()
        username = factory.make_name("username")
        password = factory.make_name("password")
        accept_all = factory.pick_bool()
        domain = factory.make_name("domain")
        power_control = random.choice(["ipmi", "restapi", "restapi2"])
        yield call_responder(
            Cluster(),
            cluster.AddChassis,
            {
                "user": user,
                "chassis_type": "seamicro15k",
                "hostname": hostname,
                "username": username,
                "password": password,
                "accept_all": accept_all,
                "domain": domain,
                "power_control": power_control,
            },
        )
        mock_deferToThread.assert_called_once_with(
            clusterservice.probe_seamicro15k_and_enlist,
            user,
            hostname,
            username,
            password,
            power_control,
            accept_all,
            domain,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_chassis_type_seamicro15k_logs_error_to_maaslog(self, mocker):
        fake_error = factory.make_name("error")
        mocker.patch.object(clusterservice, "maaslog")
        mock_deferToThread = mocker.patch.object(
            clusterservice, "deferToThread", autospec=True
        )
        mock_deferToThread.return_value = fail(Exception(fake_error))
        user = factory.make_name("user")
        hostname = factory.make_hostname()
        username = factory.make_name("username")
        password = factory.make_name("password")
        accept_all = factory.pick_bool()
        domain = factory.make_name("domain")
        power_control = random.choice(["ipmi", "restapi", "restapi2"])
        yield call_responder(
            Cluster(),
            cluster.AddChassis,
            {
                "user": user,
                "chassis_type": "seamicro15k",
                "hostname": hostname,
                "username": username,
                "password": password,
                "accept_all": accept_all,
                "domain": domain,
                "power_control": power_control,
            },
        )
        clusterservice.maaslog.error.assert_any_call(
            "Failed to probe and enlist %s nodes: %s",
            "SeaMicro 15000",
            fake_error,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_removed_chassis_types_are_not_probed(self, mocker):
        mock_deferToThread = mocker.patch.object(
            clusterservice, "deferToThread", autospec=True
        )
        maaslog = mocker.patch.object(clusterservice, "maaslog")
        for chassis_type in (
            "dli",
            "eaton",
            "mscm",
            "msftocs",
            "openbmc",
            "ucsm",
        ):
            yield call_responder(
                Cluster(),
                cluster.AddChassis,
                {
                    "user": factory.make_name("user"),
                    "chassis_type": chassis_type,
                    "hostname": factory.make_hostname(),
                },
            )
            maaslog.error.assert_called_with(
                f"Unknown chassis type {chassis_type}"
            )
        mock_deferToThread.assert_not_called()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_chassis_type_unknown_logs_error_to_maaslog(self, mocker):
        maaslog = mocker.patch.object(clusterservice, "maaslog")
        user = factory.make_name("user")
        chassis_type = factory.make_name("chassis_type")
        yield call_responder(
            Cluster(),
            cluster.AddChassis,
            {
                "user": user,
                "chassis_type": chassis_type,
                "hostname": factory.make_hostname(),
            },
        )
        maaslog.error.assert_any_call(f"Unknown chassis type {chassis_type}")

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_returns_nothing(self, mocker):
        mocker.patch.object(clusterservice, "deferToThread", autospec=True)
        user = factory.make_name("user")
        response = yield call_responder(
            Cluster(),
            cluster.AddChassis,
            {
                "user": user,
                "chassis_type": "virsh",
                "hostname": factory.make_hostname(),
            },
        )
        assert response == {}


@pytest.mark.rack_reactor_guard
class TestClusterProtocol_DisableAndShutoffRackd:
    def test_is_registered(self):
        protocol = Cluster()
        responder = protocol.locateResponder(
            cluster.DisableAndShutoffRackd.commandName
        )
        assert responder is not None

    def test_remove_shared_secret(self, mocker, tmp_path):
        root_path = tmp_path
        shared_secret_path = root_path / "secret"
        mocker.patch.object(
            utils_env.MAAS_SHARED_SECRET, "_path", lambda: shared_secret_path
        )
        mocker.patch.object(clusterservice, "call_and_check")
        shared_secret_path.write_text("secret")
        response = call_responder(
            Cluster(), cluster.DisableAndShutoffRackd, {}
        )
        assert response.result == {}
        assert not shared_secret_path.exists()

    def test_issues_restart_snap(self, mocker):
        mock_call_and_check = mocker.patch.object(
            clusterservice, "call_and_check"
        )
        response = call_responder(
            Cluster(), cluster.DisableAndShutoffRackd, {}
        )
        assert {} == response.result
        mock_call_and_check.assert_called_once_with(
            ["snapctl", "restart", "maas.pebble"]
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_raises_error_on_failure_snap(self, mocker):
        mock_call_and_check = mocker.patch.object(
            clusterservice, "call_and_check"
        )
        mock_call_and_check.side_effect = ExternalProcessError(
            random.randint(1, 255), "maas", "failure"
        )
        with pytest.raises(exceptions.CannotDisableAndShutoffRackd):
            yield call_responder(Cluster(), cluster.DisableAndShutoffRackd, {})

    def test_snap_ignores_signal_error_code_on_restart(self, mocker):
        mock_call_and_check = mocker.patch.object(
            clusterservice, "call_and_check"
        )
        mock_call_and_check.side_effect = ExternalProcessError(
            -15, "maas", "failure"
        )
        response = call_responder(
            Cluster(), cluster.DisableAndShutoffRackd, {}
        )
        assert {} == response.result
        assert 1 == mock_call_and_check.call_count


@pytest.mark.rack_reactor_guard
class TestClusterProtocol_CheckIPs:
    @pytest.fixture(autouse=True)
    def wait_for_deferred_threads(self, mocker, request):
        deferreds = []
        original_defer_to_thread = clusterservice.deferToThread

        def defer_to_thread(function, *args, **kwargs):
            deferred = original_defer_to_thread(function, *args, **kwargs)
            deferreds.append(deferred)
            return deferred

        mocker.patch.object(clusterservice, "deferToThread", defer_to_thread)

        @wait_for(timeout=TIMEOUT)
        @inlineCallbacks
        def wait_for_deferreds():
            for deferred in deferreds:
                yield deferred

        request.addfinalizer(wait_for_deferreds)

    def test_is_registered(self):
        protocol = Cluster()
        responder = protocol.locateResponder(cluster.CheckIPs.commandName)
        assert responder is not None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_reports_results(self, mocker):
        ip_addresses = [
            {
                # Always exists, returns exit code of `0`.
                "ip_address": "127.0.0.1"
            },
            {
                # Broadcast that `ping` by default doesn't allow ping to
                # occur so the command returns exit code of `2`.
                "ip_address": "255.255.255.255"
            },
        ]

        # Fake `find_mac_via_arp` so its always returns a MAC address.
        fake_mac = factory.make_mac_address()
        mocker.patch.object(
            clusterservice, "find_mac_via_arp"
        ).return_value = fake_mac
        result = yield call_responder(
            Cluster(), cluster.CheckIPs, {"ip_addresses": ip_addresses}
        )

        assert result == {
            "ip_addresses": [
                {
                    "ip_address": "127.0.0.1",
                    "used": True,
                    "interface": None,
                    "mac_address": fake_mac,
                },
                {
                    "ip_address": "255.255.255.255",
                    "used": False,
                    "interface": None,
                    "mac_address": None,
                },
            ]
        }
