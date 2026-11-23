# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


import os
from subprocess import Popen

import crochet
from django.db import connections
from django.db.backends.base.base import BaseDatabaseWrapper
import pytest
from twisted.application.service import MultiService
from twisted.internet import reactor

from maasserver import eventloop
from maasserver.plugin import (
    Options,
    RegionAllInOneServiceMaker,
    RegionMasterServiceMaker,
    RegionWorkerServiceMaker,
)
from maasserver.utils.orm import (
    disable_all_database_connections,
    DisabledDatabaseConnection,
    enable_all_database_connections,
)
from provisioningserver import logger
from provisioningserver.utils.twisted import asynchronous, ThreadPool


def import_websocket_handlers():
    # Import the websocket handlers for their side-effects: merely defining
    # DeviceHandler, e.g., causes a database access, which will crash if it
    # happens inside the reactor thread where database access is forbidden and
    # prevented. The most sensible solution to this might be to disallow
    # database access at import time.
    import maasserver.websockets.handlers  # noqa


class TestOptions:
    """Tests for `maasserver.plugin.Options`."""

    def test_defaults(self):
        options = Options()
        assert options.defaults == {}

    def test_parse_minimal_options(self):
        options = Options()
        # The minimal set of options that must be provided.
        arguments = []
        options.parseOptions(arguments)  # No error.


class TestServiceMaker:
    """Mixin with helpers for all the service marker tests."""

    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        mocker.patch.object(eventloop.loop, "services", MultiService())
        # Prevent setting the pdeathsig in tests.
        mocker.patch.object(
            RegionWorkerServiceMaker, "_set_pdeathsig", autospec=True
        )
        mocker.patch.object(crochet, "no_setup", autospec=True)
        mocker.patch.object(logger, "configure", autospec=True)
        # Enable database access in the reactor just for these tests.
        asynchronous(enable_all_database_connections, timeout=60)()
        import_websocket_handlers()
        yield
        # Disable database access in the reactor again.
        asynchronous(disable_all_database_connections, timeout=60)()

    def assertConnectionsEnabled(self):
        for alias in connections:
            assert isinstance(connections[alias], BaseDatabaseWrapper)

    def assertConnectionsDisabled(self):
        for alias in connections:
            assert type(connections[alias]) is DisabledDatabaseConnection


class TestRegionWorkerServiceMaker(TestServiceMaker):
    """Tests for `maasserver.plugin.RegionWorkerServiceMaker`."""

    def test_init(self):
        service_maker = RegionWorkerServiceMaker("Harry", "Hill")
        assert service_maker.tapname == "Harry"
        assert service_maker.description == "Hill"

    @asynchronous(timeout=60)
    def test_makeService_configures_pserv_debug(self, mocker):
        options = Options()
        service_maker = RegionWorkerServiceMaker("Harry", "Hill")
        mock_pserv = mocker.patch.object(
            service_maker, "_configurePservSettings"
        )
        # Disable _configureThreads() as it's too invasive right now.
        mocker.patch.object(service_maker, "_configureThreads", autospec=True)
        service_maker.makeService(options)
        mock_pserv.assert_called_once_with()

    @asynchronous(timeout=60)
    def test_makeService_without_import_services(self, mocker):
        options = Options()
        service_maker = RegionWorkerServiceMaker("Harry", "Hill")
        # Disable _configureThreads() as it's too invasive right now.
        mocker.patch.object(service_maker, "_configureThreads", autospec=True)
        service = service_maker.makeService(options)
        assert isinstance(service, MultiService)
        expected_services = {
            "database-tasks",
            "postgres-listener-worker",
            "rpc",
            "status-worker",
            "web",
            "ipc-worker",
        }
        assert service.namedServices.keys() == expected_services
        assert len(service.namedServices) == len(service.services), (
            "Not all services are named."
        )
        logger.configure.assert_called_once_with(
            options["verbosity"], logger.LoggingMode.TWISTD
        )
        crochet.no_setup.assert_called_once_with()

    @asynchronous(timeout=60)
    def test_makeService_with_import_services(self, mocker, monkeypatch):
        options = Options()
        service_maker = RegionWorkerServiceMaker("Harry", "Hill")
        # Disable _configureThreads() as it's too invasive right now.
        mocker.patch.object(service_maker, "_configureThreads", autospec=True)
        # Set the environment variable to create the import services.
        monkeypatch.setenv("MAAS_REGIOND_RUN_IMPORTER_SERVICE", "true")
        service = service_maker.makeService(options)
        assert isinstance(service, MultiService)
        expected_services = {
            "database-tasks",
            "postgres-listener-worker",
            "rpc",
            "status-worker",
            "web",
            "ipc-worker",
            "import-resources-progress",
            "active-discovery",
        }
        assert service.namedServices.keys() == expected_services
        assert len(service.namedServices) == len(service.services), (
            "Not all services are named."
        )
        logger.configure.assert_called_once_with(
            options["verbosity"], logger.LoggingMode.TWISTD
        )

        crochet.no_setup.assert_called_once_with()

    @asynchronous(timeout=60)
    def test_configures_thread_pool(self, monkeypatch):
        # Patch and restore where it's visible because patching a running
        # reactor is potentially fairly harmful.
        monkeypatch.setattr(reactor, "threadpool", None)
        monkeypatch.setattr(reactor, "threadpoolForDatabase", None)
        service_maker = RegionWorkerServiceMaker("Harry", "Hill")
        service_maker.makeService(Options())
        threadpool = reactor.getThreadPool()
        assert isinstance(threadpool, ThreadPool)

    @asynchronous(timeout=60)
    def test_disables_database_connections_in_reactor(self, mocker):
        self.assertConnectionsEnabled()
        service_maker = RegionWorkerServiceMaker("Harry", "Hill")
        # Disable _configureThreads() as it's too invasive right now.
        mocker.patch.object(service_maker, "_configureThreads", autospec=True)
        service_maker.makeService(Options())
        self.assertConnectionsDisabled()


class TestRegionMasterServiceMaker(TestServiceMaker):
    """Tests for `maasserver.plugin.RegionMasterServiceMaker`."""

    def get_unused_pid(self):
        """Return a PID for a process that has just finished running."""
        proc = Popen(["/bin/true"])
        proc.wait()
        return proc.pid

    def test_init(self):
        service_maker = RegionMasterServiceMaker("Harry", "Hill")
        assert service_maker.tapname == "Harry"
        assert service_maker.description == "Hill"

    @asynchronous(timeout=60)
    def test_makeService_configures_pserv_debug(self, mocker):
        options = Options()
        service_maker = RegionMasterServiceMaker("Harry", "Hill")
        mock_pserv = mocker.patch.object(
            service_maker, "_configurePservSettings"
        )
        # Disable _ensureConnection() its not allowed in the reactor.
        mocker.patch.object(service_maker, "_ensureConnection", autospec=True)
        # Disable _configureThreads() as it's too invasive right now.
        mocker.patch.object(service_maker, "_configureThreads", autospec=True)
        service_maker.makeService(options)
        mock_pserv.assert_called_once_with()

    @asynchronous(timeout=60)
    def test_makeService(self, mocker):
        options = Options()
        service_maker = RegionMasterServiceMaker("Harry", "Hill")
        # Disable _ensureConnection() its not allowed in the reactor.
        mocker.patch.object(service_maker, "_ensureConnection", autospec=True)
        # Disable _configureThreads() as it's too invasive right now.
        mocker.patch.object(service_maker, "_configureThreads", autospec=True)
        service = service_maker.makeService(options)
        assert isinstance(service, MultiService)
        expected_services = {
            "database-tasks-master",
            "region-controller",
            "nonce-cleanup",
            "dns-publication-cleanup",
            "service-monitor",
            "status-monitor",
            "stats",
            "prometheus",
            "prometheus-exporter",
            "postgres-listener-master",
            "networks-monitor",
            "reverse-dns",
            "reverse-proxy",
            "certificate-expiration-check",
            "ntp",
            "syslog",
            "version-check",
            "workers",
            "ipc-master",
            "vault-secrets-cleanup",
            "temporal",
            "dns-reload",
        }
        assert service.namedServices.keys() == expected_services
        assert len(service.namedServices) == len(service.services), (
            "Not all services are named."
        )
        logger.configure.assert_called_once_with(
            options["verbosity"], logger.LoggingMode.TWISTD
        )
        crochet.no_setup.assert_called_once_with()

    @asynchronous(timeout=60)
    def test_makeService_cleanup_prometheus_dir(
        self, mocker, monkeypatch, tmp_path
    ):
        tmpdir = tmp_path
        monkeypatch.setenv("prometheus_multiproc_dir", str(tmpdir))
        pid = os.getpid()
        file1 = tmpdir / f"histogram_{pid}.db"
        file1.touch()
        file2 = tmpdir / f"histogram_{self.get_unused_pid()}.db"
        file2.touch()

        service_maker = RegionMasterServiceMaker("Harry", "Hill")
        # Disable _ensureConnection() its not allowed in the reactor.
        mocker.patch.object(service_maker, "_ensureConnection", autospec=True)
        # Disable _configureThreads() as it's too invasive right now.
        mocker.patch.object(service_maker, "_configureThreads", autospec=True)
        service_maker.makeService(Options())
        assert file1.exists()
        assert not file2.exists()

    @asynchronous(timeout=60)
    def test_configures_thread_pool(self, mocker, monkeypatch):
        # Patch and restore where it's visible because patching a running
        # reactor is potentially fairly harmful.
        monkeypatch.setattr(reactor, "threadpool", None)
        monkeypatch.setattr(reactor, "threadpoolForDatabase", None)
        service_maker = RegionMasterServiceMaker("Harry", "Hill")
        # Disable _ensureConnection() its not allowed in the reactor.
        mocker.patch.object(service_maker, "_ensureConnection", autospec=True)
        service_maker.makeService(Options())
        threadpool = reactor.getThreadPool()
        assert isinstance(threadpool, ThreadPool)

    @asynchronous(timeout=60)
    def test_disables_database_connections_in_reactor(self, mocker):
        self.assertConnectionsEnabled()
        service_maker = RegionMasterServiceMaker("Harry", "Hill")
        # Disable _ensureConnection() its not allowed in the reactor.
        mocker.patch.object(service_maker, "_ensureConnection", autospec=True)
        # Disable _configureThreads() as it's too invasive right now.
        mocker.patch.object(service_maker, "_configureThreads", autospec=True)
        service_maker.makeService(Options())
        self.assertConnectionsDisabled()


class TestRegionAllInOneServiceMaker(TestServiceMaker):
    """Tests for `maasserver.plugin.RegionAllInOneServiceMaker`."""

    def test_init(self):
        service_maker = RegionAllInOneServiceMaker("Harry", "Hill")
        assert service_maker.tapname == "Harry"
        assert service_maker.description == "Hill"

    @asynchronous(timeout=60)
    def test_makeService_configures_pserv_debug(self, mocker):
        options = Options()
        service_maker = RegionAllInOneServiceMaker("Harry", "Hill")
        mock_pserv = mocker.patch.object(
            service_maker, "_configurePservSettings"
        )
        # Disable _ensureConnection() its not allowed in the reactor.
        mocker.patch.object(service_maker, "_ensureConnection", autospec=True)
        # Disable _configureThreads() as it's too invasive right now.
        mocker.patch.object(service_maker, "_configureThreads", autospec=True)
        service_maker.makeService(options)
        mock_pserv.assert_called_once_with()

    @asynchronous(timeout=60)
    def test_makeService(self, mocker):
        options = Options()
        service_maker = RegionAllInOneServiceMaker("Harry", "Hill")
        # Disable _ensureConnection() its not allowed in the reactor.
        mocker.patch.object(service_maker, "_ensureConnection", autospec=True)
        # Disable _configureThreads() as it's too invasive right now.
        mocker.patch.object(service_maker, "_configureThreads", autospec=True)
        service = service_maker.makeService(options)
        assert isinstance(service, MultiService)
        expected_services = {
            # Worker services.
            "database-tasks",
            "postgres-listener-worker",
            "rpc",
            "service-monitor",
            "status-worker",
            "version-check",
            "web",
            "ipc-worker",
            # Master services.
            "database-tasks-master",
            "region-controller",
            "nonce-cleanup",
            "dns-publication-cleanup",
            "status-monitor",
            "stats",
            "prometheus",
            "prometheus-exporter",
            "import-resources-progress",
            "postgres-listener-master",
            "networks-monitor",
            "active-discovery",
            "reverse-dns",
            "reverse-proxy",
            "vault-secrets-cleanup",
            "certificate-expiration-check",
            "ntp",
            "syslog",
            # "workers",  Prevented in all-in-one.
            "ipc-master",
            "temporal",
            "dns-reload",
        }
        assert service.namedServices.keys() == expected_services
        assert len(service.namedServices) == len(service.services), (
            "Not all services are named."
        )
        logger.configure.assert_called_once_with(
            options["verbosity"], logger.LoggingMode.TWISTD
        )
        crochet.no_setup.assert_called_once_with()

    @asynchronous(timeout=60)
    def test_configures_thread_pool(self, mocker, monkeypatch):
        # Patch and restore where it's visible because patching a running
        # reactor is potentially fairly harmful.
        monkeypatch.setattr(reactor, "threadpool", None)
        monkeypatch.setattr(reactor, "threadpoolForDatabase", None)
        service_maker = RegionAllInOneServiceMaker("Harry", "Hill")
        # Disable _ensureConnection() its not allowed in the reactor.
        mocker.patch.object(service_maker, "_ensureConnection", autospec=True)
        service_maker.makeService(Options())
        threadpool = reactor.getThreadPool()
        assert isinstance(threadpool, ThreadPool)

    @asynchronous(timeout=60)
    def test_disables_database_connections_in_reactor(self, mocker):
        self.assertConnectionsEnabled()
        service_maker = RegionAllInOneServiceMaker("Harry", "Hill")
        # Disable _ensureConnection() its not allowed in the reactor.
        mocker.patch.object(service_maker, "_ensureConnection", autospec=True)
        # Disable _configureThreads() as it's too invasive right now.
        mocker.patch.object(service_maker, "_configureThreads", autospec=True)
        service_maker.makeService(Options())
        self.assertConnectionsDisabled()
