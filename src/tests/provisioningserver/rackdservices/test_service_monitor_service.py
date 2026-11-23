# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for
:py:module:`~provisioningserver.rackdservices.service_monitor_service`."""

import random
from unittest.mock import Mock, sentinel

import pytest
from twisted.internet import defer
from twisted.internet.defer import inlineCallbacks
from twisted.internet.task import Clock

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.factory import factory
from maastesting.twisted import TwistedLoggerFixture
from provisioningserver.rackdservices import service_monitor_service as sms
from provisioningserver.rpc import clusterservice, getRegionClient, region
from provisioningserver.rpc.testing import MockLiveClusterToRegionRPCFixture
from provisioningserver.service_monitor import service_monitor
from provisioningserver.utils.service_monitor import (
    AlwaysOnService,
    SERVICE_STATE,
    ServiceState,
    ToggleableService,
)

TIMEOUT = get_testing_timeout()


def _cleanup_rpc_fixture(fixture, shutdown):
    @inlineCallbacks
    def cleanup():
        try:
            yield shutdown()
        finally:
            yield fixture.cleanUp()

    return cleanup()


@pytest.mark.rack_reactor_guard
class TestServiceMonitorService:
    @pytest.fixture(autouse=True)
    def _set_up(self, mocker):
        # Reset the all the toggleable services to off.
        for service in service_monitor._services.values():
            if isinstance(service, ToggleableService):
                service.off()
        mocker.patch.object(
            clusterservice, "get_all_interfaces_definition", return_value={}
        )

    def pick_service(self):
        return random.choice(list(service_monitor._services.values()))

    def test_init_sets_up_timer_correctly(self):
        monitor_service = sms.ServiceMonitorService(
            sentinel.client_service, sentinel.clock
        )
        assert monitor_service.call == (
            monitor_service.monitorServices,
            (),
            {},
        )
        assert monitor_service.step == 30
        assert monitor_service.client_service == sentinel.client_service
        assert monitor_service.clock == sentinel.clock

    def test_monitorServices_does_not_do_anything_in_dev_environment(
        self, mocker
    ):
        # Belt-n-braces make sure we're in a development environment.
        assert sms.is_dev_environment()

        monitor_service = sms.ServiceMonitorService(
            sentinel.client_service, Clock()
        )
        mock_ensureServices = mocker.patch.object(
            service_monitor, "ensureServices"
        )
        with TwistedLoggerFixture() as logger:
            monitor_service.monitorServices()
        mock_ensureServices.assert_not_called()
        assert (
            "Skipping check of services; they're not running under the supervision of systemd."
            in logger.messages
        )

    def test_monitorServices_calls_ensureServices(self, mocker):
        # Pretend we're in a production environment.
        mocker.patch.object(sms, "is_dev_environment", return_value=False)

        monitor_service = sms.ServiceMonitorService(
            sentinel.client_service, Clock()
        )
        mock_client = Mock()
        mocker.patch.object(
            monitor_service,
            "_getConnection",
            return_value=defer.succeed(mock_client),
        )
        mock_ensureServices = mocker.patch.object(
            service_monitor, "ensureServices"
        )
        monitor_service.monitorServices()
        mock_ensureServices.assert_called_once_with()

    def test_monitorServices_handles_failure(self, mocker):
        # Pretend we're in a production environment.
        mocker.patch.object(sms, "is_dev_environment", return_value=False)

        monitor_service = sms.ServiceMonitorService(
            sentinel.client_service, Clock()
        )
        mock_get_connection = mocker.patch.object(
            monitor_service, "_getConnection"
        )
        mock_get_connection.return_value = defer.fail(factory.make_exception())
        with TwistedLoggerFixture() as logger:
            monitor_service.monitorServices()
        assert (
            "Failed to monitor services and update region." in logger.messages
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_reports_services_to_region_on_start(self, mocker, request):
        # Pretend we're in a production environment.
        mocker.patch.object(sms, "is_dev_environment", return_value=False)
        fixture = MockLiveClusterToRegionRPCFixture()
        shutdown = [lambda: defer.succeed(None)]
        request.addfinalizer(
            lambda: wait_for(timeout=TIMEOUT)(_cleanup_rpc_fixture)(
                fixture, shutdown[0]
            )
        )
        yield fixture.setUp()
        protocol, connecting = fixture.makeEventLoop(region.UpdateServices)
        shutdown[0] = yield connecting

        class ExampleService(AlwaysOnService):
            name = service_name = snap_service_name = factory.make_name(
                "service"
            )

        service = ExampleService()
        # Inveigle this new service into the service monitor.
        request.addfinalizer(
            lambda: service_monitor._services.pop(service.name)
        )
        service_monitor._services[service.name] = service

        state = ServiceState(SERVICE_STATE.ON, "running")
        mocker.patch.object(
            service_monitor,
            "ensureServices",
            return_value=defer.succeed({service.name: state}),
        )

        client = getRegionClient()
        rpc_service = Mock()
        rpc_service.getClientNow.return_value = defer.succeed(client)
        monitor_service = sms.ServiceMonitorService(rpc_service, Clock())
        yield monitor_service.startService()
        yield monitor_service.stopService()

        expected_services = list(monitor_service.ALWAYS_RUNNING_SERVICES)
        expected_services.append(
            {"name": service.name, "status": "running", "status_info": ""}
        )
        protocol.UpdateServices.assert_called_once_with(
            protocol,
            system_id=client.localIdent,
            services=expected_services,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_reports_services_to_region(self, mocker, request):
        # Pretend we're in a production environment.
        mocker.patch.object(sms, "is_dev_environment", return_value=False)

        fixture = MockLiveClusterToRegionRPCFixture()
        shutdown = [lambda: defer.succeed(None)]
        request.addfinalizer(
            lambda: wait_for(timeout=TIMEOUT)(_cleanup_rpc_fixture)(
                fixture, shutdown[0]
            )
        )
        yield fixture.setUp()
        protocol, connecting = fixture.makeEventLoop(region.UpdateServices)
        shutdown[0] = yield connecting

        class ExampleService(AlwaysOnService):
            name = service_name = snap_service_name = factory.make_name(
                "service"
            )

        service = ExampleService()
        # Inveigle this new service into the service monitor.
        request.addfinalizer(
            lambda: service_monitor._services.pop(service.name)
        )
        service_monitor._services[service.name] = service

        state = ServiceState(SERVICE_STATE.ON, "running")
        mocker.patch.object(
            service_monitor,
            "ensureServices",
            return_value=defer.succeed({service.name: state}),
        )

        client = getRegionClient()
        rpc_service = Mock()
        rpc_service.getClientNow.return_value = defer.succeed(client)
        monitor_service = sms.ServiceMonitorService(rpc_service, Clock())

        yield monitor_service.startService()
        yield monitor_service.stopService()

        expected_services = list(monitor_service.ALWAYS_RUNNING_SERVICES)
        expected_services.append(
            {"name": service.name, "status": "running", "status_info": ""}
        )
        protocol.UpdateServices.assert_called_once_with(
            protocol,
            system_id=client.localIdent,
            services=expected_services,
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_buildServices_includes_always_running_services(self):
        monitor_service = sms.ServiceMonitorService(
            sentinel.client_service, Clock()
        )
        observed_services = yield monitor_service._buildServices({})
        assert monitor_service.ALWAYS_RUNNING_SERVICES == observed_services

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_buildServices_adds_services_to_always_running_services(self):
        monitor_service = sms.ServiceMonitorService(
            sentinel.client_service, Clock()
        )
        service = self.pick_service()
        state = ServiceState(SERVICE_STATE.ON, "running")
        observed_services = yield monitor_service._buildServices(
            {service.name: state}
        )
        expected_services = list(monitor_service.ALWAYS_RUNNING_SERVICES)
        expected_services.append(
            {"name": service.name, "status": "running", "status_info": ""}
        )
        assert expected_services == observed_services
