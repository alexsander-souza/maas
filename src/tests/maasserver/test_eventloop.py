# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maasserver.eventloop`."""

from unittest.mock import ANY, call, Mock, sentinel

from django.db import connections
import pytest
from twisted.internet import defer
from twisted.internet.defer import inlineCallbacks
from twisted.python.threadable import isInIOThread

from maasserver import (
    bootresources,
    eventloop,
    ipc,
    nonces_cleanup,
    region_controller,
    stats,
    status_monitor,
    webapp,
    workers,
)
from maasserver.eventloop import MAASServices
from maasserver.prometheus.service import REGION_PROMETHEUS_PORT
from maasserver.prometheus.stats import PrometheusService
from maasserver.regiondservices import ntp, service_monitor_service, syslog
from maasserver.regiondservices.certificate_expiration_check import (
    CertificateExpirationCheckService,
)
from maasserver.regiondservices.vault_secrets_cleanup import (
    VaultSecretsCleanupService,
)
from maasserver.regiondservices.version_update_check import (
    RegionVersionUpdateCheckService,
)
from maasserver.rpc import regionservice
from maasserver.testing.eventloop import RegionEventLoopFixture
from maasserver.testing.listener import FakePostgresListenerService
from maasserver.utils import dbtasks
from maasserver.utils.orm import DisabledDatabaseConnection, transactional
from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.factory import factory
from metadataserver import api_twisted
from provisioningserver.utils.twisted import asynchronous

TIMEOUT = get_testing_timeout()
wait_for_reactor = wait_for()


class TestMAASServices:
    @wait_for_reactor
    @inlineCallbacks
    def test_calls_prepare(self):
        fake_eventloop = Mock()
        calls = Mock()
        fake_eventloop.prepare = calls
        fake_services = [Mock(), Mock()]
        services = MAASServices(fake_eventloop)
        for service in fake_services:
            service.startService = Mock()
            services.addService(service)
        yield services.startService()
        calls.assert_called_once_with()
        assert 1 == services.running

    @wait_for_reactor
    @inlineCallbacks
    def test_starts_each_service(self):
        fake_eventloop = Mock()
        fake_eventloop.prepare = Mock()
        calls = Mock()
        fake_services = [Mock(), Mock()]
        services = MAASServices(fake_eventloop)
        for service in fake_services:
            service.startService = calls
            services.addService(service)
        yield services.startService()
        calls.assert_has_calls((call(), call()))
        assert 1 == services.running

    @wait_for_reactor
    @inlineCallbacks
    def test_sets_global_labels(self, mocker):
        mock_set_global_labels = mocker.patch.object(
            eventloop, "set_global_labels"
        )
        fake_eventloop = Mock()
        services = MAASServices(fake_eventloop)
        yield services.startService()
        mock_set_global_labels.assert_called_once_with(maas_uuid=ANY)


class TestRegionEventLoop:
    def test_name(self, mocker):
        mocker.patch.object(eventloop, "gethostname", return_value="foo")
        mocker.patch.object(eventloop.os, "getpid", return_value=12345)
        assert "foo:pid=12345" == eventloop.loop.name

    def test_populateService_prevent_worker_service_on_master(self, mocker):
        mocker.patch.object(eventloop.services, "getServiceNamed")
        an_eventloop = eventloop.RegionEventLoop()

        @asynchronous
        def tryPopulate(*args, **kwargs):
            with pytest.raises(ValueError):
                an_eventloop.populateService(*args, **kwargs)

        tryPopulate("web", master=True).wait(TIMEOUT)

    def test_populateService_prevent_master_service_on_worker(self, mocker):
        mocker.patch.object(eventloop.services, "getServiceNamed")
        an_eventloop = eventloop.RegionEventLoop()

        @asynchronous
        def tryPopulate(*args, **kwargs):
            with pytest.raises(ValueError):
                an_eventloop.populateService(*args, **kwargs)

        tryPopulate("workers", master=False).wait(TIMEOUT)

    def test_populateService_prevent_service_on_all_in_one(self, mocker):
        mocker.patch.object(eventloop.services, "getServiceNamed")
        an_eventloop = eventloop.RegionEventLoop()

        @asynchronous
        def tryPopulate(*args, **kwargs):
            with pytest.raises(ValueError):
                an_eventloop.populateService(*args, **kwargs)

        tryPopulate("workers", master=True, all_in_one=True).wait(TIMEOUT)

    def test_populate_on_worker_without_import_services(self, mocker):
        mocker.patch.object(eventloop.services, "getServiceNamed")
        an_eventloop = eventloop.RegionEventLoop()
        # At first there are no services.
        assert set() == {service.name for service in an_eventloop.services}
        # populate() creates a service with each factory.
        an_eventloop.populate(master=False).wait(TIMEOUT)
        assert {
            name
            for name, item in an_eventloop.factories.items()
            if item["only_on_master"] is False
            and (item.get("import_service", False) is False)
        } == {svc.name for svc in an_eventloop.services}
        # The services are not started.
        assert {
            name: False
            for name, item in an_eventloop.factories.items()
            if item["only_on_master"] is False
            and (item.get("import_service", False) is False)
        } == {svc.name: svc.running for svc in an_eventloop.services}

    def test_populate_on_worker_with_import_services(self, mocker):
        mocker.patch.object(eventloop.services, "getServiceNamed")
        an_eventloop = eventloop.RegionEventLoop()
        # At first there are no services.
        assert set() == {service.name for service in an_eventloop.services}
        # populate() creates a service with each factory.
        an_eventloop.populate(master=False, import_services=True).wait(TIMEOUT)
        assert {
            name
            for name, item in an_eventloop.factories.items()
            if item["only_on_master"] is False
        } == {svc.name for svc in an_eventloop.services}
        # The services are not started.
        assert {
            name: False
            for name, item in an_eventloop.factories.items()
            if item["only_on_master"] is False
        } == {svc.name: svc.running for svc in an_eventloop.services}

    def test_populate_on_master(self, mocker):
        mocker.patch.object(eventloop.services, "getServiceNamed")
        an_eventloop = eventloop.RegionEventLoop()
        # At first there are no services.
        assert set() == {service.name for service in an_eventloop.services}
        # populate() creates a service with each factory.
        an_eventloop.populate(master=True).wait(TIMEOUT)
        assert {
            name
            for name, item in an_eventloop.factories.items()
            if item["only_on_master"] is True
        } == {svc.name for svc in an_eventloop.services}
        # The services are not started.
        assert {
            name: False
            for name, item in an_eventloop.factories.items()
            if item["only_on_master"] is True
        } == {svc.name: svc.running for svc in an_eventloop.services}

    def test_populate_on_all_in_one(self, mocker):
        mocker.patch.object(eventloop.services, "getServiceNamed")
        an_eventloop = eventloop.RegionEventLoop()
        # At first there are no services.
        assert set() == {service.name for service in an_eventloop.services}
        # populate() creates a service with each factory.
        an_eventloop.populate(
            master=True, all_in_one=True, import_services=True
        ).wait(TIMEOUT)
        assert {
            name
            for name, item in an_eventloop.factories.items()
            if item.get("not_all_in_one", False) is False
        } == {svc.name for svc in an_eventloop.services}
        # The services are not started.
        assert {
            name: False
            for name, item in an_eventloop.factories.items()
            if item.get("not_all_in_one", False) is False
        } == {svc.name: svc.running for svc in an_eventloop.services}

    def test_start_and_stop(self, mocker):
        # Replace the factories in RegionEventLoop with non-functional
        # dummies to avoid bringing up real services here, and ensure
        # that the services list is empty.
        with RegionEventLoopFixture():
            # At the outset, the eventloop's services are dorment.
            assert not eventloop.loop.services.running
            # RegionEventLoop.running is an alias for .services.running.
            assert not eventloop.loop.running
            assert set(eventloop.loop.services) == set()
            # Patch prepare so it's not actually run.
            mocker.patch.object(
                eventloop.loop, "prepare", return_value=defer.succeed(None)
            )
            # After starting the loop, the services list is populated, and
            # the services are started too.
            eventloop.loop.start().wait(TIMEOUT)
            try:
                assert eventloop.loop.services.running
                assert eventloop.loop.running
                assert {
                    service.name for service in eventloop.loop.services
                } == {name for name in eventloop.loop.factories.keys()}
                # A shutdown hook is registered with the reactor.
                stopService = eventloop.loop.services.stopService
                assert ("shutdown", ("before", stopService, (), {})) == (
                    eventloop.loop.handle
                )
                # After stopping the loop, the services list remains
                # populated, but the services are all stopped.
                eventloop.loop.stop().wait(TIMEOUT)
                assert not eventloop.loop.services.running
                assert not eventloop.loop.running
                assert {
                    service.name for service in eventloop.loop.services
                } == {name for name in eventloop.loop.factories.keys()}
            finally:
                eventloop.loop.reset().wait(TIMEOUT)
            # The hook has been cleared.
            assert eventloop.loop.handle is None

    def test_reset(self, mocker):
        # Replace the factories in RegionEventLoop with non-functional
        # dummies to avoid bringing up real services here, and ensure
        # that the services list is empty.
        with RegionEventLoopFixture():
            # Patch prepare so it's not actually run.
            mocker.patch.object(
                eventloop.loop, "prepare", return_value=defer.succeed(None)
            )
            eventloop.loop.start().wait(TIMEOUT)
            eventloop.loop.reset().wait(TIMEOUT)
            # After stopping the loop, the services list is also emptied.
            assert not eventloop.loop.services.running
            assert not eventloop.loop.running
            assert set(eventloop.loop.services) == set()
            # The hook has also been cleared.
            assert eventloop.loop.handle is None

    def test_reset_clears_factories(self):
        eventloop.loop.factories = ((factory.make_name("service"), None),)
        eventloop.loop.reset().wait(TIMEOUT)
        # The loop's factories are also reset.
        assert eventloop.loop.__class__.factories == eventloop.loop.factories

    def test_restart(self, mocker):
        # Replace the factories in RegionEventLoop with non-functional
        # dummies to avoid bringing up real services here, and ensure
        # that the services list is empty.
        # The reset mock delegates to the real reset so that the services
        # started here are disowned again (the legacy unittest-based test
        # relied on its cleanup ordering to do this with the real reset).
        real_reset = eventloop.loop.reset
        with RegionEventLoopFixture():
            # Patch prepare so it's not actually run.
            mocker.patch.object(
                eventloop.loop, "prepare", return_value=defer.succeed(None)
            )
            reset_mock = mocker.patch.object(
                eventloop.loop, "reset", side_effect=real_reset
            )

            eventloop.loop.start().wait(TIMEOUT)
            start_mock = mocker.patch.object(
                eventloop.loop,
                "start",
                return_value=defer.succeed(None),
            )
            eventloop.loop.restart().wait(TIMEOUT)

            reset_mock.assert_called_once()
            start_mock.assert_called_once_with(
                master=eventloop.loop.master,
                all_in_one=eventloop.loop.all_in_one,
            )
            eventloop.loop.stop().wait(TIMEOUT)

    def test_module_globals(self):
        # Several module globals are references to a shared RegionEventLoop.
        assert eventloop.services is eventloop.loop.services
        # Must compare by equality here; these methods are decorated.
        assert eventloop.reset == eventloop.loop.reset
        assert eventloop.start == eventloop.loop.start
        assert eventloop.stop == eventloop.loop.stop
        assert eventloop.restart == eventloop.loop.restart


class TestFactories:
    def test_make_DatabaseTaskService(self):
        service = eventloop.make_DatabaseTaskService()
        assert isinstance(service, dbtasks.DatabaseTasksService)
        # It is registered as a factory in RegionEventLoop.
        assert (
            eventloop.make_DatabaseTaskService
            is eventloop.loop.factories["database-tasks"]["factory"]
        )
        assert not eventloop.loop.factories["database-tasks"]["only_on_master"]

    def test_make_MasterDatabaseTaskService(self):
        service = eventloop.make_DatabaseTaskService()
        assert isinstance(service, dbtasks.DatabaseTasksService)
        # It is registered as a factory in RegionEventLoop.
        assert (
            eventloop.make_DatabaseTaskService
            is eventloop.loop.factories["database-tasks-master"]["factory"]
        )
        assert eventloop.loop.factories["database-tasks-master"][
            "only_on_master"
        ]

    def test_make_RegionControllerService(self):
        service = eventloop.make_RegionControllerService(
            sentinel.postgresListener, sentinel.dbtasks
        )
        assert isinstance(service, region_controller.RegionControllerService)
        # It is registered as a factory in RegionEventLoop.
        assert (
            eventloop.make_RegionControllerService
            is eventloop.loop.factories["region-controller"]["factory"]
        )
        assert eventloop.loop.factories["region-controller"]["only_on_master"]

    def test_make_RegionService(self):
        service = eventloop.make_RegionService(sentinel.ipcWorker)
        assert isinstance(service, regionservice.RegionService)
        # It is registered as a factory in RegionEventLoop.
        assert (
            eventloop.make_RegionService
            is eventloop.loop.factories["rpc"]["factory"]
        )
        assert not eventloop.loop.factories["rpc"]["only_on_master"]
        assert ["ipc-worker"] == eventloop.loop.factories["rpc"]["requires"]

    def test_make_RegionService_unset_outside_hardening_binds_any(
        self, mocker
    ):
        # Outside hardening, an unset rpc_bind binds every interface,
        # regardless of whether maas_url resolves to a local address --
        # the same rule every other hardened service follows.
        from maasserver.config import RegionConfiguration
        import provisioningserver.utils.network as network_module

        mock_open = mocker.patch.object(RegionConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.rpc_bind = []
        mock_cfg.maas_url = "http://10.0.0.9:5240/MAAS"
        mock_open.return_value.__exit__.return_value = False
        mocker.patch.object(
            network_module,
            "get_source_address_for_url",
            return_value="10.0.0.9",
        )

        service = eventloop.make_RegionService(sentinel.ipcWorker)

        assert service.endpoints[0][0]._interface == ""

    def test_make_RegionService_unset_under_hardening_derives_from_maas_url(
        self, mocker
    ):
        # Under hardening, an unset rpc_bind derives a specific address
        # from maas_url -- the same address rack controllers already use
        # to reach the region -- instead of a bare wildcard bind.
        import maascommon.hardening as hardening_module
        from maasserver.config import RegionConfiguration
        import provisioningserver.utils.network as network_module

        mock_open = mocker.patch.object(RegionConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.rpc_bind = []
        mock_cfg.maas_url = "http://10.0.0.9:5240/MAAS"
        mock_open.return_value.__exit__.return_value = False
        mocker.patch.object(
            network_module,
            "get_source_address_for_url",
            return_value="10.0.0.9",
        )
        mocker.patch.object(
            hardening_module, "is_hardening_enabled", return_value=True
        )

        service = eventloop.make_RegionService(sentinel.ipcWorker)

        assert service.endpoints[0][0]._interface == "10.0.0.9"

    def test_make_RegionService_unresolvable_under_hardening_binds_loopback(
        self, mocker
    ):
        # Under hardening, an unresolvable maas_url falls back to loopback
        # rather than every interface: a wildcard bind is not allowed.
        import maascommon.hardening as hardening_module
        from maasserver.config import RegionConfiguration
        import provisioningserver.utils.network as network_module

        mock_open = mocker.patch.object(RegionConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.rpc_bind = []
        mock_cfg.maas_url = "http://unreachable.invalid:5240/MAAS"
        mock_open.return_value.__exit__.return_value = False
        mocker.patch.object(
            network_module, "get_source_address_for_url", return_value=None
        )
        mocker.patch.object(
            hardening_module, "is_hardening_enabled", return_value=True
        )

        service = eventloop.make_RegionService(sentinel.ipcWorker)

        assert service.endpoints[0][0]._interface == "127.0.0.1"

    def test_make_RegionService_explicit_bind(self, mocker):
        from maasserver.config import RegionConfiguration

        mock_open = mocker.patch.object(RegionConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.rpc_bind = ["10.0.0.1"]
        mock_open.return_value.__exit__.return_value = False

        service = eventloop.make_RegionService(sentinel.ipcWorker)

        assert service.endpoints[0][0]._interface == "10.0.0.1"

    def test_make_RegionService_multiple_explicit_binds(self, mocker):
        from maasserver.config import RegionConfiguration

        mock_open = mocker.patch.object(RegionConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.rpc_bind = ["10.0.0.1", "10.0.0.2"]
        mock_open.return_value.__exit__.return_value = False

        service = eventloop.make_RegionService(sentinel.ipcWorker)

        assert ["10.0.0.1", "10.0.0.2"] == [
            endpoint._interface for endpoint in service.endpoints[0]
        ]

    def test_make_NonceCleanupService(self):
        service = eventloop.make_NonceCleanupService()
        assert isinstance(service, nonces_cleanup.NonceCleanupService)
        # It is registered as a factory in RegionEventLoop.
        assert (
            eventloop.make_NonceCleanupService
            is eventloop.loop.factories["nonce-cleanup"]["factory"]
        )
        assert eventloop.loop.factories["nonce-cleanup"]["only_on_master"]

    def test_make_StatusMonitorService(self):
        service = eventloop.make_StatusMonitorService()
        assert isinstance(service, status_monitor.StatusMonitorService)
        # It is registered as a factory in RegionEventLoop.
        assert (
            eventloop.make_StatusMonitorService
            is eventloop.loop.factories["status-monitor"]["factory"]
        )
        assert eventloop.loop.factories["status-monitor"]["only_on_master"]

    def test_make_StatsService(self):
        service = eventloop.make_StatsService()
        assert isinstance(service, stats.StatsService)
        # It is registered as a factory in RegionEventLoop.
        assert (
            eventloop.make_StatsService
            is eventloop.loop.factories["stats"]["factory"]
        )
        assert eventloop.loop.factories["stats"]["only_on_master"]

    def test_make_PrometheusService(self):
        service = eventloop.make_PrometheusService()
        assert isinstance(service, PrometheusService)
        # It is registered as a factory in RegionEventLoop.
        assert (
            eventloop.make_PrometheusService
            is eventloop.loop.factories["prometheus"]["factory"]
        )
        assert eventloop.loop.factories["prometheus"]["only_on_master"]

    def test_make_ImportResourcesProgressService(self):
        service = eventloop.make_ImportResourcesProgressService()
        assert isinstance(
            service, bootresources.ImportResourcesProgressService
        )
        # It is registered as a factory in RegionEventLoop.
        factories = eventloop.loop.factories
        assert (
            eventloop.make_ImportResourcesProgressService
            is factories["import-resources-progress"]["factory"]
        )
        assert not factories["import-resources-progress"]["only_on_master"]
        assert factories["import-resources-progress"]["import_service"]

    def test_make_WebApplicationService(self):
        service = eventloop.make_WebApplicationService(
            FakePostgresListenerService(), sentinel.status_worker
        )
        assert isinstance(service, webapp.WebApplicationService)
        # It is registered as a factory in RegionEventLoop.
        assert (
            eventloop.make_WebApplicationService
            is eventloop.loop.factories["web"]["factory"]
        )
        # Has a dependency of postgres-listener.
        assert [
            "postgres-listener-worker",
            "status-worker",
        ] == eventloop.loop.factories["web"]["requires"]
        assert not eventloop.loop.factories["web"]["only_on_master"]

    def test_make_VersionUpdateCheckService(self):
        service = eventloop.make_VersionUpdateCheckService()
        assert isinstance(service, RegionVersionUpdateCheckService)
        assert (
            eventloop.loop.factories["version-check"]["factory"]
            is eventloop.make_VersionUpdateCheckService
        )

    def test_make_ServiceMonitorService(self):
        service = eventloop.make_ServiceMonitorService()
        assert isinstance(
            service, service_monitor_service.ServiceMonitorService
        )
        # It is registered as a factory in RegionEventLoop.
        assert (
            eventloop.make_ServiceMonitorService
            is eventloop.loop.factories["service-monitor"]["factory"]
        )
        assert [] == eventloop.loop.factories["service-monitor"]["requires"]
        assert eventloop.loop.factories["service-monitor"]["only_on_master"]

    def test_make_StatusWorkerService(self):
        service = eventloop.make_StatusWorkerService(sentinel.dbtasks)
        assert isinstance(service, api_twisted.StatusWorkerService)
        # It is registered as a factory in RegionEventLoop.
        assert (
            eventloop.make_StatusWorkerService
            is eventloop.loop.factories["status-worker"]["factory"]
        )
        # Has a dependency of database-tasks.
        assert ["database-tasks"] == eventloop.loop.factories["status-worker"][
            "requires"
        ]
        assert not eventloop.loop.factories["status-worker"]["only_on_master"]

    def test_make_NetworkTimeProtocolService(self):
        service = eventloop.make_NetworkTimeProtocolService()
        assert isinstance(service, ntp.RegionNetworkTimeProtocolService)
        # It is registered as a factory in RegionEventLoop.
        assert (
            eventloop.make_NetworkTimeProtocolService
            is eventloop.loop.factories["ntp"]["factory"]
        )
        # Has a no dependencies.
        assert [] == eventloop.loop.factories["ntp"]["requires"]
        assert eventloop.loop.factories["ntp"]["only_on_master"]

    def test_make_SyslogService(self):
        service = eventloop.make_SyslogService()
        assert isinstance(service, syslog.RegionSyslogService)
        # It is registered as a factory in RegionEventLoop.
        assert (
            eventloop.make_SyslogService
            is eventloop.loop.factories["syslog"]["factory"]
        )
        # Has a no dependencies.
        assert [] == eventloop.loop.factories["syslog"]["requires"]
        assert eventloop.loop.factories["syslog"]["only_on_master"]

    def test_make_WorkersService(self):
        service = eventloop.make_WorkersService()
        assert isinstance(service, workers.WorkersService)
        # It is registered as a factory in RegionEventLoop.
        assert (
            eventloop.make_WorkersService
            is eventloop.loop.factories["workers"]["factory"]
        )
        # Has a no dependencies.
        assert [] == eventloop.loop.factories["workers"]["requires"]
        assert eventloop.loop.factories["workers"]["only_on_master"]
        assert eventloop.loop.factories["workers"]["not_all_in_one"]

    def test_make_IPCMasterService(self):
        service = eventloop.make_IPCMasterService()
        assert isinstance(service, ipc.IPCMasterService)
        # It is registered as a factory in RegionEventLoop.
        assert (
            eventloop.make_IPCMasterService
            is eventloop.loop.factories["ipc-master"]["factory"]
        )
        # Has a no dependencies.
        assert [] == eventloop.loop.factories["ipc-master"]["requires"]
        # Has an optional dependency on workers.
        assert ["workers"] == eventloop.loop.factories["ipc-master"][
            "optional"
        ]
        assert eventloop.loop.factories["ipc-master"]["only_on_master"]

    def test_make_IPCWorkerService(self):
        service = eventloop.make_IPCWorkerService()
        assert isinstance(service, ipc.IPCWorkerService)
        # It is registered as a factory in RegionEventLoop.
        assert (
            eventloop.make_IPCWorkerService
            is eventloop.loop.factories["ipc-worker"]["factory"]
        )
        # Has a no dependencies.
        assert [] == eventloop.loop.factories["ipc-worker"]["requires"]
        assert not eventloop.loop.factories["ipc-worker"]["only_on_master"]

    def test_make_PrometheusExporterService(self):
        from maasserver.prometheus.service import PrometheusExporterService

        service = eventloop.make_PrometheusExporterService()
        assert isinstance(service, PrometheusExporterService)
        assert service._port == REGION_PROMETHEUS_PORT
        # It is registered as a factory in RegionEventLoop.
        assert (
            eventloop.make_PrometheusExporterService
            is eventloop.loop.factories["prometheus-exporter"]["factory"]
        )
        assert eventloop.loop.factories["prometheus-exporter"][
            "only_on_master"
        ]

    def test_make_PrometheusExporterService_binds_all_by_default(self, mocker):
        import maascommon.hardening as hardening_module

        mocker.patch.object(
            hardening_module, "is_hardening_enabled", return_value=False
        )

        service = eventloop.make_PrometheusExporterService()

        assert service._resolve_bind_address() == ""

    def test_make_PrometheusExporterService_binds_loopback_under_hardening(
        self, mocker
    ):
        import maascommon.hardening as hardening_module

        mocker.patch.object(
            hardening_module, "is_hardening_enabled", return_value=True
        )

        service = eventloop.make_PrometheusExporterService()

        assert service._resolve_bind_address() == "127.0.0.1"

    def test_make_PrometheusExporterService_explicit_bind_overrides(
        self, mocker
    ):
        from maasserver.config import RegionConfiguration

        mock_open = mocker.patch.object(RegionConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.prometheus_bind = "10.0.0.5"
        mock_open.return_value.__exit__.return_value = False

        service = eventloop.make_PrometheusExporterService()

        assert service._resolve_bind_address() == "10.0.0.5"

    def test_make_PrometheusExporterService_bind_resolved_lazily(self, mocker):
        # Regression test for the populate()/configure_hardening() race:
        # the bind address must be computed when the service actually
        # starts, not baked in at construction time (`populate()` builds
        # every factory before `start_up()` calls `configure_hardening()`).
        import maascommon.hardening as hardening_module

        mock_enabled = mocker.patch.object(
            hardening_module, "is_hardening_enabled", return_value=False
        )
        service = eventloop.make_PrometheusExporterService()
        # Hardening becomes active only after construction, mirroring
        # configure_hardening() running after populate().
        mock_enabled.return_value = True
        assert service._resolve_bind_address() == "127.0.0.1"

    def test_make_CertificateExpirationCheckService(self):
        service = eventloop.make_CertificateExpirationCheckService()
        assert isinstance(service, CertificateExpirationCheckService)
        assert (
            eventloop.loop.factories["certificate-expiration-check"]["factory"]
            is eventloop.make_CertificateExpirationCheckService
        )

    def test_make_VaultSecretsCleanupService(self):
        service = eventloop.make_VaultSecretsCleanupService()
        assert isinstance(service, VaultSecretsCleanupService)
        assert (
            eventloop.loop.factories["vault-secrets-cleanup"]["factory"]
            is eventloop.make_VaultSecretsCleanupService
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestDisablingDatabaseConnections:
    @wait_for_reactor
    def test_connections_are_all_stubs_in_the_event_loop(self):
        assert isInIOThread()
        for alias in connections:
            connection = connections[alias]
            # isinstance() fails because it references __bases__, so
            # compare types here.
            assert type(connection) is DisabledDatabaseConnection

    @transactional
    def test_connections_are_all_usable_outside_the_event_loop(self):
        assert not isInIOThread()
        for alias in connections:
            connection = connections[alias]
            assert connection.is_usable()
