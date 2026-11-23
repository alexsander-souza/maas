# Copyright 2016-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import pytest

from maasserver.models import RackController, RegionRackRPCConnection, Service
from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestRegionRackRPCConnection:
    def test_calls_create_services_for_on_create(self, mocker):
        endpoint = factory.make_RegionControllerProcessEndpoint()
        rack_controller = factory.make_RackController()
        mock_create_for = mocker.patch.object(
            Service.objects, "create_services_for"
        )
        RegionRackRPCConnection.objects.create(
            endpoint=endpoint, rack_controller=rack_controller
        )
        mock_create_for.assert_called_once_with(rack_controller)

    def test_calls_update_rackd_status_on_create(self, mocker):
        endpoint = factory.make_RegionControllerProcessEndpoint()
        rack_controller = factory.make_RackController()
        mock_update_rackd_status = mocker.patch.object(
            rack_controller, "update_rackd_status"
        )
        RegionRackRPCConnection.objects.create(
            endpoint=endpoint, rack_controller=rack_controller
        )
        mock_update_rackd_status.assert_called_once_with()

    def test_calls_create_services_for_on_update(self, mocker):
        endpoint = factory.make_RegionControllerProcessEndpoint()
        rack_controller = factory.make_RackController()
        mock_create_for = mocker.patch.object(
            Service.objects, "create_services_for"
        )
        connection = RegionRackRPCConnection.objects.create(
            endpoint=endpoint, rack_controller=rack_controller
        )
        connection.save()
        mock_create_for.assert_called_with(rack_controller)

    def test_calls_update_rackd_status_on_update(self, mocker):
        endpoint = factory.make_RegionControllerProcessEndpoint()
        rack_controller = factory.make_RackController()
        mock_update_rackd_status = mocker.patch.object(
            rack_controller, "update_rackd_status"
        )
        connection = RegionRackRPCConnection.objects.create(
            endpoint=endpoint, rack_controller=rack_controller
        )
        mock_update_rackd_status.reset_mock()
        connection.save()
        mock_update_rackd_status.assert_called_once_with()

    def test_calls_create_services_for_on_delete(self, mocker):
        endpoint = factory.make_RegionControllerProcessEndpoint()
        rack_controller = factory.make_RackController()
        mock_create_for = mocker.patch.object(
            Service.objects, "create_services_for"
        )
        connection = RegionRackRPCConnection.objects.create(
            endpoint=endpoint, rack_controller=rack_controller
        )
        mock_create_for.reset_mock()
        connection.delete()
        mock_create_for.assert_called_once_with(rack_controller)

    def test_calls_update_rackd_status_on_delete(self, mocker):
        endpoint = factory.make_RegionControllerProcessEndpoint()
        rack_controller = factory.make_RackController()
        mock_update_rackd_status = mocker.patch.object(
            rack_controller, "update_rackd_status"
        )
        connection = RegionRackRPCConnection.objects.create(
            endpoint=endpoint, rack_controller=rack_controller
        )
        mock_update_rackd_status.reset_mock()
        connection.delete()
        mock_update_rackd_status.assert_called_once_with()


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestRegionControllerProcess:
    def test_calls_create_services_for_on_all_racks_on_create(self, mocker):
        rack_controllers = [factory.make_RackController() for _ in range(3)]
        mock_create_for = mocker.patch.object(
            Service.objects, "create_services_for"
        )
        factory.make_RegionControllerProcess()
        assert len(rack_controllers) + 1 == mock_create_for.call_count

    def test_calls_update_rackd_status_on_all_racks_on_create(self, mocker):
        rack_controllers = [factory.make_RackController() for _ in range(3)]
        mock_update_rackd_status = mocker.patch.object(
            RackController, "update_rackd_status"
        )
        factory.make_RegionControllerProcess()
        assert len(rack_controllers) == mock_update_rackd_status.call_count

    def test_calls_create_services_for_on_all_racks_on_delete(self, mocker):
        rack_controllers = [factory.make_RackController() for _ in range(3)]
        process = factory.make_RegionControllerProcess()
        mock_create_for = mocker.patch.object(
            Service.objects, "create_services_for"
        )
        process.delete()
        assert len(rack_controllers) == mock_create_for.call_count

    def test_calls_update_rackd_status_on_all_racks_on_delete(self, mocker):
        rack_controllers = [factory.make_RackController() for _ in range(3)]
        process = factory.make_RegionControllerProcess()
        mock_update_rackd_status = mocker.patch.object(
            RackController, "update_rackd_status"
        )
        process.delete()
        assert len(rack_controllers) == mock_update_rackd_status.call_count
