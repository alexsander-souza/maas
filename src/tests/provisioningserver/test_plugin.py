# Copyright 2012-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the ``maasrackd`` TAP."""

from itertools import count
import os
from subprocess import Popen

import crochet
import pytest
from twisted.application.internet import StreamServerEndpointService
from twisted.application.service import MultiService
from twisted.internet.task import Clock

from maastesting.factory import factory
import provisioningserver
from provisioningserver import logger, settings
from provisioningserver import plugin as plugin_module
from provisioningserver.config import ClusterConfiguration
from provisioningserver.plugin import Options, ProvisioningServiceMaker
from provisioningserver.rackdservices.dhcp_probe_service import (
    DHCPProbeService,
)
from provisioningserver.rackdservices.external import RackExternalService
from provisioningserver.rackdservices.networks_monitoring_service import (
    RackNetworksMonitoringService,
)
from provisioningserver.rackdservices.node_power_monitor_service import (
    NodePowerMonitorService,
)
from provisioningserver.rackdservices.service_monitor_service import (
    ServiceMonitorService,
)
from provisioningserver.rackdservices.tftp import TFTPBackend, TFTPService
from provisioningserver.rackdservices.version_update_check import (
    VersionUpdateCheckService,
)
from provisioningserver.rpc.clusterservice import ClusterClientCheckerService
from provisioningserver.security import to_hex
from provisioningserver.testing.config import ClusterConfigurationFixture
from provisioningserver.utils.env import MAAS_SHARED_SECRET


class TestOptions:
    """Tests for `provisioningserver.plugin.Options`."""

    def test_defaults(self):
        options = Options()
        assert {} == options.defaults

    def test_parse_minimal_options(self):
        options = Options()
        # The minimal set of options that must be provided.
        arguments = []
        options.parseOptions(arguments)  # No error.


@pytest.mark.rack_reactor_guard
class TestProvisioningServiceMaker:
    """Tests for `provisioningserver.plugin.ProvisioningServiceMaker`."""

    @pytest.fixture(autouse=True)
    def _setup(self, mocker, monkeypatch, tmp_path, request):
        tftp_root = tmp_path / "tftp"
        tftp_root.mkdir()
        config_fixture = ClusterConfigurationFixture(tftp_root=str(tftp_root))
        config_fixture.setUp()
        request.addfinalizer(config_fixture.cleanUp)
        mocker.patch.object(provisioningserver, "services", MultiService())
        mocker.patch.object(crochet, "no_setup", autospec=True)
        mocker.patch.object(logger, "configure", autospec=True)
        monkeypatch.setattr(
            MAAS_SHARED_SECRET, "_path", lambda: tmp_path / "secret"
        )
        # by default, define a shared secret so that sevices are populated
        MAAS_SHARED_SECRET.set(to_hex(factory.make_bytes()))

    def get_unused_pid(self):
        """Return a PID for a process that has just finished running."""
        proc = Popen(["/bin/true"])
        proc.wait()
        return proc.pid

    def test_init(self):
        service_maker = ProvisioningServiceMaker("Harry", "Hill")
        assert service_maker.tapname == "Harry"
        assert service_maker.description == "Hill"

    def test_makeService_no_shared_secret(self, mocker):
        MAAS_SHARED_SECRET.set(None)
        service_maker = ProvisioningServiceMaker("foo", "bar")
        mocker.patch.object(service_maker, "_loadSettings")
        clock = Clock()

        attempts = count()

        def advance(seconds):
            next(attempts)
            clock.advance(seconds)

        service = service_maker.makeService(
            Options(), clock=clock, sleep=advance
        )
        assert isinstance(service, MultiService)
        assert service.namedServices == {}
        # All 300 attempts (e.g. 5 minutes) fail, next is 301
        assert next(attempts) == 301

    def test_makeService_eventual_shared_secret(self, mocker):
        # First two attempts will find the secret unset, third one will find it
        MAAS_SHARED_SECRET.set(None)
        secret_values = [None, to_hex(factory.make_bytes())]
        service_maker = ProvisioningServiceMaker("foo", "bar")
        mocker.patch.object(service_maker, "_loadSettings")
        clock = Clock()

        attempts = count(1)

        def advance(seconds):
            secret = secret_values.pop(0)
            MAAS_SHARED_SECRET.set(secret)
            next(attempts)
            clock.advance(60)

        service = service_maker.makeService(
            Options(), clock=clock, sleep=advance
        )
        assert isinstance(service, MultiService)
        assert service.namedServices != {}
        # First two fail, the third one succeeds
        assert next(attempts) == 3

    def test_makeService_not_in_debug(self, mocker):
        """
        Only the site service is created when no options are given.
        """
        mocker.patch.object(settings, "DEBUG", False)
        options = Options()
        service_maker = ProvisioningServiceMaker("Harry", "Hill")
        mocker.patch.object(service_maker, "_loadSettings")
        service = service_maker.makeService(options, clock=None)
        assert isinstance(service, MultiService)
        expected_services = {
            "dhcp_probe",
            "networks_monitor",
            "node_monitor",
            "external",
            "rpc",
            "rpc-ping",
            "http",
            "http_service",
            "tftp",
            "service_monitor",
            "version_update_check",
        }
        assert service.namedServices.keys() == expected_services
        assert len(service.namedServices) == len(service.services), (
            "Not all services are named."
        )
        assert service == provisioningserver.services
        crochet.no_setup.assert_called_once_with()
        logger.configure.assert_called_once_with(
            options["verbosity"], logger.LoggingMode.TWISTD
        )

    def test_makeService_in_debug(self, mocker):
        """
        Only the site service is created when no options are given.
        """
        mocker.patch.object(settings, "DEBUG", True)
        options = Options()
        service_maker = ProvisioningServiceMaker("Harry", "Hill")
        mocker.patch.object(service_maker, "_loadSettings")
        service = service_maker.makeService(options, clock=None)
        assert isinstance(service, MultiService)
        expected_services = {
            "dhcp_probe",
            "networks_monitor",
            "node_monitor",
            "external",
            "rpc",
            "rpc-ping",
            "http",
            "http_service",
            "tftp",
            "service_monitor",
            "version_update_check",
        }
        assert service.namedServices.keys() == expected_services
        assert len(service.namedServices) == len(service.services), (
            "Not all services are named."
        )
        assert service == provisioningserver.services
        crochet.no_setup.assert_called_once_with()
        logger.configure.assert_called_once_with(3, logger.LoggingMode.TWISTD)

    def test_makeService_patches_tftp_service(self, mocker):
        mock_tftp_patch = mocker.patch.object(
            plugin_module, "add_patches_to_txtftp"
        )
        options = Options()
        service_maker = ProvisioningServiceMaker("Harry", "Hill")
        service_maker.makeService(options, clock=None)
        mock_tftp_patch.assert_called_once_with()

    def test_makeService_cleanup_prometheus_dir(self, tmp_path, monkeypatch):
        tmpdir = tmp_path
        monkeypatch.setenv("prometheus_multiproc_dir", str(tmpdir))
        pid = os.getpid()
        file1 = tmpdir / f"histogram_{pid}.db"
        file1.touch()
        file2 = tmpdir / f"histogram_{self.get_unused_pid()}.db"
        file2.touch()

        service_maker = ProvisioningServiceMaker("Harry", "Hill")
        service_maker.makeService(Options(), clock=None)
        assert file1.exists()
        assert not file2.exists()

    def test_node_monitor_service(self):
        options = Options()
        service_maker = ProvisioningServiceMaker("Harry", "Hill")
        service = service_maker.makeService(options, clock=None)
        node_monitor = service.getServiceNamed("node_monitor")
        assert isinstance(node_monitor, NodePowerMonitorService)

    def test_networks_monitor_service(self):
        options = Options()
        service_maker = ProvisioningServiceMaker("Spike", "Milligan")
        service = service_maker.makeService(options, clock=None)
        networks_monitor = service.getServiceNamed("networks_monitor")
        assert isinstance(networks_monitor, RackNetworksMonitoringService)

    def test_dhcp_probe_service(self):
        options = Options()
        service_maker = ProvisioningServiceMaker("Spike", "Milligan")
        service = service_maker.makeService(options, clock=None)
        dhcp_probe = service.getServiceNamed("dhcp_probe")
        assert isinstance(dhcp_probe, DHCPProbeService)

    def test_service_monitor_service(self):
        options = Options()
        service_maker = ProvisioningServiceMaker("Harry", "Hill")
        service = service_maker.makeService(options, clock=None)
        service_monitor = service.getServiceNamed("service_monitor")
        assert isinstance(service_monitor, ServiceMonitorService)

    def test_rpc_ping_service(self):
        options = Options()
        service_maker = ProvisioningServiceMaker("Harry", "Hill")
        service = service_maker.makeService(options, clock=None)
        rpc_ping = service.getServiceNamed("rpc-ping")
        assert isinstance(rpc_ping, ClusterClientCheckerService)

    def test_external_service(self):
        options = Options()
        service_maker = ProvisioningServiceMaker("Harry", "Hill")
        service = service_maker.makeService(options, clock=None)
        external_service = service.getServiceNamed("external")
        assert isinstance(external_service, RackExternalService)

    def test_version_update_service(self):
        options = Options()
        service_maker = ProvisioningServiceMaker("Harry", "Hill")
        service = service_maker.makeService(options, clock=None)
        version_check_service = service.getServiceNamed("version_update_check")
        assert isinstance(version_check_service, VersionUpdateCheckService)

    def test_http_service(self):
        options = Options()
        service_maker = ProvisioningServiceMaker("Harry", "Hill")
        service = service_maker.makeService(options, clock=None)
        http_service = service.getServiceNamed("http_service")
        assert isinstance(http_service, StreamServerEndpointService)

    def test_tftp_service(self):
        """A TFTP service is configured and added to the top-level service."""
        options = Options()
        service_maker = ProvisioningServiceMaker("Harry", "Hill")
        service = service_maker.makeService(options, clock=None)
        tftp_service = service.getServiceNamed("tftp")
        assert isinstance(tftp_service, TFTPService)

        with ClusterConfiguration.open() as config:
            tftp_root = config.tftp_root
            tftp_port = config.tftp_port
            tftp_max_blksize = config.tftp_max_blksize

        assert tftp_service.port == tftp_port
        assert isinstance(tftp_service.backend, TFTPBackend)
        assert tftp_service.backend.base.path == tftp_root
        assert tftp_service.max_blksize == tftp_max_blksize
        assert os.path.exists(tftp_root)
