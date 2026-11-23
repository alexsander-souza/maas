# Copyright 2018-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
"""Tests for `maasserver.ipc`"""

from datetime import timedelta
import os
import random
from unittest.mock import MagicMock
import uuid

import pytest
from twisted.internet import reactor
from twisted.internet.defer import DeferredList, inlineCallbacks, succeed

from maasserver import ipc, workers
from maasserver.enum import SERVICE_STATUS
from maasserver.ipc import (
    get_ipc_socket_path,
    IPCMasterService,
    IPCWorkerService,
)
from maasserver.models import timestampedmodel
from maasserver.models.node import RegionController
from maasserver.models.regioncontrollerprocess import RegionControllerProcess
from maasserver.models.regioncontrollerprocessendpoint import (
    RegionControllerProcessEndpoint,
)
from maasserver.models.regionrackrpcconnection import RegionRackRPCConnection
from maasserver.models.service import Service
from maasserver.models.timestampedmodel import now
from maasserver.rpc.regionservice import RegionService
from maasserver.testing.factory import factory
from maasserver.testing.orm import reload_objects
from maasserver.utils.orm import reload_object
from maasserver.utils.threads import deferToDatabase
import maasserver.workers as workers_module
from maastesting.crochet import wait_for
from metadataserver.builtin_scripts import load_builtin_scripts
from provisioningserver.utils import ipaddr
from provisioningserver.utils.testing import MAASIDFixture
from provisioningserver.utils.twisted import callOut, DeferredValue

wait_for_reactor = wait_for()


class TestGetIPCSocketPath:
    def test_returns_ipc_socket_env(self, mocker):
        path = factory.make_name("path")
        mocker.patch.dict(os.environ, {"MAAS_IPC_SOCKET_PATH": path})
        assert get_ipc_socket_path() == path

    def test_returns_ipc_from_maas_data(self, mocker):
        path = factory.make_name("path")
        mocker.patch.dict(os.environ, {"MAAS_DATA": path})
        assert os.path.join(path, "maas-regiond.sock") == get_ipc_socket_path()

    def test_returns_ipc_at_default_location(self, mocker):
        mocker.patch.dict(os.environ, {}, clear=True)
        assert get_ipc_socket_path() == "/var/lib/maas/maas-regiond.sock"


class TestIPCMasterServiceGetListenAddresses:
    """`_getListenAddresses` mirrors `eventloop.resolve_rpc_bind_addresses`,
    the same resolution `RegionService` uses to bind, so what's advertised
    to rack controllers always matches what's actually listening."""

    def test_prefers_configured_rpc_bind(self, mocker, tmp_path):
        from maasserver.config import RegionConfiguration

        master = IPCMasterService(
            reactor, socket_path=str(tmp_path / "ipc.sock")
        )
        mock_open = mocker.patch.object(RegionConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.rpc_bind = ["10.0.0.1", "10.0.0.2"]
        mock_open.return_value.__exit__.return_value = False

        assert master._getListenAddresses(5250) == {
            ("10.0.0.1", 5250),
            ("10.0.0.2", 5250),
        }

    def test_derives_from_maas_url_under_hardening_when_unset(
        self, mocker, tmp_path
    ):
        import maascommon.hardening as hardening_module
        from maasserver.config import RegionConfiguration
        import provisioningserver.utils.network as network_module

        master = IPCMasterService(
            reactor, socket_path=str(tmp_path / "ipc.sock")
        )
        mock_open = mocker.patch.object(RegionConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.rpc_bind = []
        mock_cfg.maas_url = "http://10.0.0.9:5240/MAAS"
        mock_open.return_value.__exit__.return_value = False
        mocker.patch.object(
            network_module, "get_source_address_for_url"
        ).return_value = "10.0.0.9"
        mocker.patch.object(
            hardening_module, "is_hardening_enabled"
        ).return_value = True

        assert master._getListenAddresses(5250) == {("10.0.0.9", 5250)}

    def test_falls_back_to_discovery_when_hardening_inactive_and_unset(
        self, mocker, tmp_path
    ):
        # Outside hardening, `resolve_rpc_bind_addresses` returns an empty
        # list for an unset `rpc_bind` without even attempting to derive
        # from `maas_url` (the RPC listener itself binds every interface
        # in that case); `_getListenAddresses` still needs *some* concrete
        # address to advertise to racks, so it falls back to interface
        # discovery.
        from maasserver.config import RegionConfiguration

        master = IPCMasterService(
            reactor, socket_path=str(tmp_path / "ipc.sock")
        )
        mock_open = mocker.patch.object(RegionConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.rpc_bind = []
        mock_cfg.maas_url = "http://10.0.0.9:5240/MAAS"
        mock_open.return_value.__exit__.return_value = False
        mocker.patch.object(
            ipc, "get_all_interface_source_addresses"
        ).return_value = {"10.0.0.9"}

        assert master._getListenAddresses(5250) == {("10.0.0.9", 5250)}

    def test_falls_back_to_discovery_when_maas_url_unresolvable(
        self, mocker, tmp_path
    ):
        from maasserver.config import RegionConfiguration
        import provisioningserver.utils.network as network_module

        master = IPCMasterService(
            reactor, socket_path=str(tmp_path / "ipc.sock")
        )
        mock_open = mocker.patch.object(RegionConfiguration, "open")
        mock_cfg = mock_open.return_value.__enter__.return_value
        mock_cfg.rpc_bind = []
        mock_cfg.maas_url = "http://unreachable.invalid:5240/MAAS"
        mock_open.return_value.__exit__.return_value = False
        mocker.patch.object(
            network_module, "get_source_address_for_url"
        ).return_value = None
        mocker.patch.object(
            ipc, "get_all_interface_source_addresses"
        ).return_value = {"10.0.0.9"}

        assert master._getListenAddresses(5250) == {("10.0.0.9", 5250)}


@pytest.mark.allow_transactions
@pytest.mark.usefixtures("transactional_maasdb", "maas_region_test", "factory")
class TestIPCCommunication:
    @pytest.fixture(autouse=True)
    def _setup(
        self,
        mocker,
        tmp_path,
        request,
        transactional_maasdb,
        maas_region_test,
        factory,
    ):
        self.ipc_path = str(tmp_path / "maas-regiond.sock")
        mocker.patch.object(ipaddr, "get_ip_addr", return_value={})
        mocker.patch.object(ipc, "get_all_interface_addresses")
        mocker.patch.object(ipc, "get_all_interface_source_addresses")
        running_region = factory.make_RegionController()
        maas_id_fixture = MAASIDFixture(running_region.system_id)
        maas_id_fixture.setUp()
        request.addfinalizer(maas_id_fixture.cleanUp)

    def make_IPCMasterService(self, workers=None, run_loop=False):
        master = IPCMasterService(
            reactor, workers=workers, socket_path=self.ipc_path
        )

        if not run_loop:
            # Prevent the update loop from running.
            loop = MagicMock()
            loop.start.return_value = succeed(None)
            loop.running = True
            master.updateLoop = loop

        return master

    def wrap_async_method(self, mocker, obj, method_name):
        dv = DeferredValue()
        original_method = getattr(obj, method_name)

        def mock_method(*args, **kwargs):
            d = original_method(*args, **kwargs)
            d.addCallback(callOut, dv.set, None)
            return d

        new_method = mocker.patch.object(obj, method_name)
        new_method.side_effect = mock_method
        return dv

    def make_IPCMasterService_with_wrap(
        self, mocker, workers=None, run_loop=False
    ):
        master = self.make_IPCMasterService(workers=workers, run_loop=run_loop)

        dv_connected = self.wrap_async_method(mocker, master, "registerWorker")
        dv_disconnected = self.wrap_async_method(
            mocker, master, "unregisterWorker"
        )

        return master, dv_connected, dv_disconnected

    def getRegiondService(self):
        region = RegionController.objects.get_running_controller()
        return Service.objects.get(node=region, name="regiond")

    @wait_for_reactor
    @inlineCallbacks
    def test_worker_registers_and_deregisters(self, mocker):
        yield deferToDatabase(load_builtin_scripts)
        pid = random.randint(1, 512)
        mocker.patch.object(os, "getpid").return_value = pid
        (
            master,
            connected,
            disconnected,
        ) = self.make_IPCMasterService_with_wrap(mocker)
        yield master.startService()
        worker = IPCWorkerService(reactor, socket_path=self.ipc_path)
        yield worker.startService()

        yield connected.get(timeout=2)
        assert pid in master.connections

        def getProcessFromDB():
            region = RegionController.objects.get_running_controller()
            return RegionControllerProcess.objects.get(region=region, pid=pid)

        process = yield deferToDatabase(getProcessFromDB)
        assert master.connections[pid]["process_id"] == process.id

        worker_procId = yield worker.processId.get(timeout=2)
        assert worker_procId == process.id

        yield worker.stopService()

        yield disconnected.get(timeout=2)
        assert master.connections == {}

        process = yield deferToDatabase(reload_object, process)
        assert process is None

        yield master.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_master_calls_killWorker_on_deregister(self, mocker):
        yield deferToDatabase(load_builtin_scripts)
        pid = random.randint(1, 512)
        mocker.patch.object(os, "getpid").return_value = pid
        workers = MagicMock()
        master, connected, disconnected = self.make_IPCMasterService_with_wrap(
            mocker, workers=workers
        )
        yield master.startService()
        worker = IPCWorkerService(reactor, socket_path=self.ipc_path)
        yield worker.startService()

        yield connected.get(timeout=2)
        yield worker.stopService()
        yield disconnected.get(timeout=2)
        yield master.stopService()

        workers.killWorker.assert_called_once_with(pid)

    @wait_for_reactor
    @inlineCallbacks
    def test_worker_registers_rpc_endpoints(self, mocker):
        yield deferToDatabase(load_builtin_scripts)
        pid = random.randint(1, 512)
        mocker.patch.object(os, "getpid").return_value = pid
        (
            master,
            connected,
            disconnected,
        ) = self.make_IPCMasterService_with_wrap(mocker)
        rpc_started = self.wrap_async_method(
            mocker, master, "registerWorkerRPC"
        )
        yield master.startService()

        worker = IPCWorkerService(reactor, socket_path=self.ipc_path)
        rpc = RegionService(worker)
        yield worker.startService()
        yield rpc.startService()

        yield connected.get(timeout=2)
        yield rpc_started.get(timeout=2)

        def getEndpoints():
            region = RegionController.objects.get_running_controller()
            process = RegionControllerProcess.objects.get(
                region=region, pid=pid
            )
            return {
                (endpoint.address, endpoint.port)
                for endpoint in (
                    RegionControllerProcessEndpoint.objects.filter(
                        process=process
                    )
                )
            }

        endpoints = yield deferToDatabase(getEndpoints)
        assert endpoints == master._getListenAddresses(
            master.connections[pid]["rpc"]["port"]
        )

        yield rpc.stopService()
        yield worker.stopService()
        yield disconnected.get(timeout=2)
        yield master.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_registerWorker_sets_regiond_degraded_with_less_than_workers(
        self, mocker
    ):
        # In case you run the test suite on a VM with 1 core, the MAX_WORKERS_COUNT is set to 1 so we have to patch it in order to test this scenario.
        mocker.patch.object(workers_module, "MAX_WORKERS_COUNT", 4)
        yield deferToDatabase(load_builtin_scripts)
        master = self.make_IPCMasterService()
        yield master.startService()
        pid = random.randint(1, 512)
        yield master.registerWorker(pid, MagicMock())

        regiond_service = yield deferToDatabase(self.getRegiondService)

        assert SERVICE_STATUS.DEGRADED == regiond_service.status
        assert (
            f"1 process running but {workers.MAX_WORKERS_COUNT} were expected."
            == regiond_service.status_info
        )
        yield master.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_worker_registers_and_unregister_rpc_connection(self, mocker):
        yield deferToDatabase(load_builtin_scripts)
        pid = random.randint(1, 512)
        mocker.patch.object(os, "getpid").return_value = pid
        (
            master,
            connected,
            disconnected,
        ) = self.make_IPCMasterService_with_wrap(mocker)
        rpc_started = self.wrap_async_method(
            mocker, master, "registerWorkerRPC"
        )
        yield master.startService()

        worker = IPCWorkerService(reactor, socket_path=self.ipc_path)
        rpc = RegionService(worker)
        yield worker.startService()
        yield rpc.startService()

        yield connected.get(timeout=2)
        yield rpc_started.get(timeout=2)

        rackd = yield deferToDatabase(factory.make_RackController)
        connid = str(uuid.uuid4())
        address = factory.make_ipv4_address()
        port = random.randint(1000, 5000)
        yield worker.rpcRegisterConnection(
            connid, rackd.system_id, address, port
        )

        def getConnection():
            region = RegionController.objects.get_running_controller()
            process = RegionControllerProcess.objects.get(
                region=region, pid=pid
            )
            endpoint = RegionControllerProcessEndpoint.objects.get(
                process=process, address=address, port=port
            )
            return RegionRackRPCConnection.objects.filter(
                endpoint=endpoint, rack_controller=rackd
            ).first()

        connection = yield deferToDatabase(getConnection)
        assert connection is not None
        assert master.connections[pid]["rpc"]["connections"] == {
            connid: (rackd.system_id, address, port)
        }

        yield worker.rpcUnregisterConnection(connid)
        connection = yield deferToDatabase(getConnection)
        assert connection is None

        yield rpc.stopService()
        yield worker.stopService()
        yield disconnected.get(timeout=2)
        yield master.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_update_creates_process_when_removed(self):
        yield deferToDatabase(load_builtin_scripts)
        master = self.make_IPCMasterService()
        yield master.startService()

        pids = {random.randint(1, 512) for _ in range(3)}
        for pid in pids:
            yield master.registerWorker(pid, MagicMock())

        def delete_all():
            region = RegionController.objects.get_running_controller()
            region.processes.all().delete()

        yield deferToDatabase(delete_all)

        yield master.update()

        for pid, data in master.connections.items():
            process = yield deferToDatabase(
                RegionControllerProcess.objects.get, id=data["process_id"]
            )
            assert process.pid == pid

        yield master.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_update_removes_old_processes(self):
        yield deferToDatabase(load_builtin_scripts)
        master = self.make_IPCMasterService()
        yield master.startService()

        def make_old_processes():
            old_time = now() - timedelta(seconds=90)
            region = RegionController.objects.get_running_controller()
            other_region = factory.make_RegionController()
            old_region_process = RegionControllerProcess.objects.create(
                region=region,
                pid=random.randint(1, 1000),
                created=old_time,
                updated=old_time,
            )
            old_other_region_process = RegionControllerProcess.objects.create(
                region=other_region,
                pid=random.randint(1000, 2000),
                created=old_time,
                updated=old_time,
            )
            return old_region_process, old_other_region_process

        old_region_process, old_other_region_process = yield deferToDatabase(
            make_old_processes
        )

        yield master.update()

        old_region_process = yield deferToDatabase(
            reload_object, old_region_process
        )
        old_other_region_process = yield deferToDatabase(
            reload_object, old_other_region_process
        )
        assert old_region_process is None
        assert old_other_region_process is None

        yield master.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_update_updates_updated_time_on_processes(self, mocker):
        yield deferToDatabase(load_builtin_scripts)
        current_time = now()
        mocker.patch.object(
            timestampedmodel, "now"
        ).return_value = current_time

        master = self.make_IPCMasterService()
        yield master.startService()

        pid = random.randint(1, 512)
        yield master.registerWorker(pid, MagicMock())

        def set_to_old_time(procId):
            old_time = current_time - timedelta(seconds=90)
            region_process = RegionControllerProcess.objects.get(id=procId)
            region_process.created = region_process.updated = old_time
            region_process.save()
            return region_process

        region_process = yield deferToDatabase(
            set_to_old_time, master.connections[pid]["process_id"]
        )

        yield master.update()

        region_process = yield deferToDatabase(reload_object, region_process)
        assert region_process.updated == current_time

        yield master.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_update_sets_regiond_running_with_all_workers(self):
        yield deferToDatabase(load_builtin_scripts)
        master = self.make_IPCMasterService()
        yield master.startService()

        pids = set()
        while len(pids) < workers.MAX_WORKERS_COUNT:
            pids.add(random.randint(1, 512))
        for pid in pids:
            yield master.registerWorker(pid, MagicMock())

        # The service status for the region should now be running.
        regiond_service = yield deferToDatabase(self.getRegiondService)
        assert SERVICE_STATUS.RUNNING == regiond_service.status
        assert "" == regiond_service.status_info

        # Delete all the processes and an update should re-create them
        # and the service status should still be running.
        def delete_all():
            region = RegionController.objects.get_running_controller()
            region.processes.all().delete()

        yield deferToDatabase(delete_all)

        yield master.update()
        regiond_service = yield deferToDatabase(self.getRegiondService)
        assert SERVICE_STATUS.RUNNING == regiond_service.status
        assert "" == regiond_service.status_info

        yield master.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_update_calls_mark_dead_on_regions_without_processes(self, mocker):
        yield deferToDatabase(load_builtin_scripts)
        master = self.make_IPCMasterService()
        yield master.startService()

        mock_mark_dead = mocker.patch.object(Service.objects, "mark_dead")

        pid = random.randint(1, 512)
        other_region = yield deferToDatabase(factory.make_RegionController)
        yield master.registerWorker(pid, MagicMock())
        yield master.update()

        mock_mark_dead.assert_called_once_with(other_region, dead_region=True)

        yield master.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_update_removes_all_rpc_connections_when_none(self):
        yield deferToDatabase(load_builtin_scripts)
        master = self.make_IPCMasterService()
        yield master.startService()

        pid = random.randint(1, 512)
        port = random.randint(1, 512)
        yield master.registerWorker(pid, MagicMock())
        yield master.registerWorkerRPC(pid, port)

        def make_connections(procId):
            region = RegionController.objects.get_running_controller()
            process = region.processes.get(id=procId)
            endpoints = process.endpoints.all()
            return [
                factory.make_RegionRackRPCConnection(endpoint=endpoint)
                for endpoint in endpoints
                for _ in range(3)
            ]

        rpc_connections = yield deferToDatabase(
            make_connections, master.connections[pid]["process_id"]
        )

        yield master.update()

        def reload_connections(objects):
            return list(reload_objects(RegionRackRPCConnection, objects))

        rpc_connections = yield deferToDatabase(
            reload_connections, rpc_connections
        )
        assert [] == rpc_connections

        yield master.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_update_allows_new_connections_while_updating_connections_in_db(
        self,
    ):
        yield deferToDatabase(load_builtin_scripts)
        master = self.make_IPCMasterService()
        yield master.startService()

        pid = random.randint(1, 512)
        port = random.randint(1, 512)
        ip = factory.make_ip_address()
        yield master.registerWorker(pid, MagicMock())
        yield master.registerWorkerRPC(pid, port)

        rack_controller = yield deferToDatabase(factory.make_RackController)

        for i in range(2):
            master.registerWorkerRPCConnection(
                pid,
                i,
                rack_controller.system_id,
                ip,
                random.randint(1, 512),
            )

        defers = DeferredList(
            [
                master.update(),
                master.registerWorkerRPCConnection(
                    pid,
                    3,
                    rack_controller.system_id,
                    ip,
                    random.randint(1, 512),
                ),
            ]
        )

        yield defers

        def _get_conn_count():
            return RegionRackRPCConnection.objects.filter(
                rack_controller=rack_controller
            ).count()

        count = yield deferToDatabase(_get_conn_count)

        assert (
            len(master.connections[pid]["rpc"]["connections"].values())
            == count
        )

        yield master.stopService()

    @wait_for_reactor
    @inlineCallbacks
    def test_updateConnections(self):
        yield deferToDatabase(load_builtin_scripts)
        master = self.make_IPCMasterService()
        yield master.startService()

        pid = random.randint(1, 512)
        port = random.randint(1, 512)
        ip = factory.make_ip_address()
        yield master.registerWorker(pid, MagicMock())
        yield master.registerWorkerRPC(pid, port)

        rack_controller = yield deferToDatabase(factory.make_RackController)

        for connid in range(2):
            connid_str = f"conn-{connid}"
            yield master.registerWorkerRPCConnection(
                pid,
                connid_str,
                rack_controller.system_id,
                ip,
                connid + 1,
            )

        for worker_pid, conn in master.connections.items():
            process = yield deferToDatabase(
                master._getProcessObjFor, worker_pid
            )
            rpc_conns = conn["rpc"]["connections"].copy()
            rpc_conns.pop(random.choice(list(rpc_conns.keys())))
            yield deferToDatabase(
                master._updateConnections, process, rpc_conns
            )

        def _get_conn_count():
            return RegionRackRPCConnection.objects.filter(
                rack_controller=rack_controller
            ).count()

        count = yield deferToDatabase(_get_conn_count)
        assert 1 == count

        yield master.stopService()
