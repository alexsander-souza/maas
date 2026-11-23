# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from collections import defaultdict
from datetime import timedelta
from functools import partial
import json
from pathlib import Path
import random
import socket
import threading
from unittest.mock import ANY, call, Mock

import pytest
from twisted.application.service import MultiService
from twisted.internet import reactor
from twisted.internet.defer import (
    Deferred,
    DeferredQueue,
    fail,
    inlineCallbacks,
    succeed,
)
from twisted.internet.error import (
    ProcessDone,
    ProcessExitedAlready,
    ProcessTerminated,
)
from twisted.internet.task import Clock
from twisted.logger import formatEvent, LogLevel
from twisted.python import threadable
from twisted.python.failure import Failure
from ulid import ULID

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.factory import factory
from maastesting.twisted import TwistedLoggerFixture
from provisioningserver import refresh as refresh_module
from provisioningserver import security
from provisioningserver.refresh.maas_api_helper import SignalException
from provisioningserver.refresh.node_info_scripts import (
    COMMISSIONING_OUTPUT_NAME,
)
from provisioningserver.utils import services
from provisioningserver.utils.beaconing import (
    BeaconPayload,
    create_beacon_payload,
    TopologyHint,
)
from provisioningserver.utils.env import MAAS_SECRET
from provisioningserver.utils.services import (
    BeaconingService,
    BeaconingSocketProtocol,
    JSONPerLineProtocol,
    MDNSResolverService,
    NeighbourDiscoveryService,
    NetworksMonitoringLock,
    NetworksMonitoringService,
    ProcessProtocolService,
    ProtocolForObserveARP,
    ProtocolForObserveBeacons,
    SingleInstanceService,
)

TIMEOUT = get_testing_timeout()


def use_logger(request):
    logger = TwistedLoggerFixture()
    logger.setUp()
    request.addfinalizer(logger.cleanUp)
    return logger


class FakeScriptRun:
    """Information about a script run.

    The output of the script run be found in the `out`, `err` and
    `combined` attributes.
    """

    out = None
    err = None
    combined = None

    def __init__(self):
        self.status = "running"


class FakePOpen:
    def __init__(self, *args, **kwargs):
        self.returncode = None


class FakeRefresher:
    """A better replacement for simply mocking out the "refresh()" function.

    It hooks into the refresh code and allow to inspect which scripts
    were being run and what output was sent to the metadata server.

    In addition, it ensures that the credentials were being passed
    correct, and it keeps track of the metadata URL that was being used.

    The script_runs dict has the metadata URL as key, and the scripts
    results that were being sent as the value. Normally there should be
    exactly one key.

    You may control the output of the scripts by using the
    stdout_content and stderr_contents. The script name is the key, and
    the content is the value in bytes.

    It only deals with successful runs. If you need to test failed test
    runs, you'll have to amend this class to cope with it.
    """

    def __init__(self, mocker, credentials):
        self.mock_signal = mocker.patch.object(refresh_module, "signal")
        self.mock_signal.side_effect = self.fake_signal
        self.mock_proc = mocker.patch.object(refresh_module, "Popen")
        self.mock_proc.side_effect = self.fake_popen
        self.mock_capture_script_output = mocker.patch.object(
            refresh_module, "capture_script_output"
        )
        self.mock_capture_script_output.side_effect = (
            self.fake_capture_script_output
        )
        self.credentials = {"consumer_secret": ""}
        self.credentials.update(credentials)
        self.reset()

    def reset(self):
        self.stdout_content = defaultdict(lambda: b"{}")
        self.stderr_content = defaultdict(bytes)
        self.script_runs = defaultdict(dict)

    def fake_popen(self, *args, **kwargs):
        return FakePOpen(*args, **kwargs)

    def fake_capture_script_output(
        self, proc, combined_path, stdout_path, stderr_path, timeout
    ):
        script_name = Path(combined_path).stem
        stdout = self.stdout_content[script_name]
        stderr = self.stderr_content[script_name]
        combined = stderr + stdout

        for content, path in [
            (stdout, stdout_path),
            (stderr, stderr_path),
            (combined, combined_path),
        ]:
            Path(path).write_bytes(content)
        proc.returncode = 0

    def fake_signal(
        self,
        url,
        creds,
        status,
        error=None,
        files=None,
        exit_status=None,
        retry=True,
    ):
        assert self.credentials["token_key"] == creds.token_key
        assert self.credentials["token_secret"] == creds.token_secret
        assert self.credentials["consumer_key"] == creds.consumer_key
        assert self.credentials["consumer_secret"] == creds.consumer_secret
        script_runs = self.script_runs[url]
        if status == "WORKING":
            if error.startswith("Starting"):
                script_name = error.split(" ")[1]
                assert script_name not in self.script_runs
                script_runs[script_name] = FakeScriptRun()
            elif error.startswith("Finished"):
                script_name = error.split(" ")[1]
                script_runs[script_name].status = "finished"
                script_runs[script_name].out = files[f"{script_name}.out"]
                script_runs[script_name].err = files[f"{script_name}.err"]
                script_runs[script_name].combined = files[script_name]


class SampleSingleInstanceService(SingleInstanceService):
    SERVICE_NAME = "sample"
    LOCK_NAME = "sample-lock"
    INTERVAL = timedelta(minutes=1)

    def __init__(self, clock=None):
        super().__init__(clock=clock)
        self.action_times = []

    @inlineCallbacks
    def do_action(self):
        self.action_times.append(self.clock.seconds())
        yield


@pytest.mark.rack_reactor_guard
class TestSingleInstanceService:
    def test_init(self):
        clock = Clock()
        service = SampleSingleInstanceService(clock=clock)
        assert service._lock.path.endswith("maas:sample-lock")
        assert service._timer_service.step == 60
        assert service._timer_service.parent is service
        assert service._timer_service.clock is clock

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_is_responsible(self):
        clock = Clock()
        service = SampleSingleInstanceService(clock=clock)
        yield service.startService()
        assert service.is_responsible

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_is_responsible_false_after_stop(self):
        clock = Clock()
        service = SampleSingleInstanceService(clock=clock)
        yield service.startService()
        yield service.stopService()
        assert not service.is_responsible

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_call_action(self):
        clock = Clock()
        service = SampleSingleInstanceService(clock=clock)
        yield service.startService()
        # simulate time elapsed for a single run
        clock.advance(40)
        assert service.action_times == [0.0]
        yield service.stopService()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_call_action_multiple_times(self):
        clock = Clock()
        service = SampleSingleInstanceService(clock=clock)
        yield service.startService()
        clock.advance(60)
        assert service.action_times == [0.0, 60.0]
        yield service.stopService()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_no_action_if_not_running(self):
        clock = Clock()
        service = SampleSingleInstanceService(clock=clock)
        yield service._do_action()
        clock.advance(0)
        assert service.action_times == []

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_no_run_if_not_responsible(self):
        clock = Clock()
        service1 = SampleSingleInstanceService(clock=clock)
        service2 = SampleSingleInstanceService(clock=clock)
        yield service1.startService()
        clock.advance(10)
        assert service1.is_responsible
        yield service2.startService()
        clock.advance(10)
        assert not service2.is_responsible
        assert service1.action_times == [0.0]
        assert service2.action_times == []


class StubNetworksMonitoringService(NetworksMonitoringService):
    """Concrete subclass for testing."""

    def __init__(
        self,
        enable_monitoring=False,
        enable_beaconing=False,
        system_id=None,
        maas_url="http://localhost:5240/MAAS",
        credentials=None,
        *args,
        **kwargs,
    ):
        super().__init__(
            *args,
            enable_monitoring=enable_monitoring,
            enable_beaconing=enable_beaconing,
            **kwargs,
        )
        self.iterations = DeferredQueue()
        self.interfaces = []
        self.update_interface__calls = 0
        if system_id is None:
            system_id = factory.make_string()
        self.system_id = system_id
        self.maas_url = maas_url
        if credentials is None:
            credentials = {
                "consumer_key": factory.make_string(),
                "token_key": factory.make_string(),
                "token_secret": factory.make_string(),
            }
        self.credentials = credentials

    def getDiscoveryState(self):
        return {}

    def getRefreshDetails(self):
        """Record the interfaces information."""
        return succeed((self.maas_url, self.system_id, self.credentials))

    def _do_action(self):
        self.update_interface__calls += 1
        d = super()._do_action()
        d.addBoth(self.iterations.put)
        return d

    def _interfacesRecorded(self, interfaces):
        super()._interfacesRecorded(interfaces)
        self.interfaces.append(interfaces)

    def reportNeighbours(self, neighbours):
        pass

    def reportMDNSEntries(self, neighbours):
        pass


@pytest.mark.rack_reactor_guard
class TestNetworksMonitoringService:
    @pytest.fixture(autouse=True)
    def _set_up(self, mocker, request):
        self.mocker = mocker
        self.request = request
        self.all_interfaces_mock = mocker.patch.object(
            services, "get_all_interfaces_definition", return_value={}
        )
        self.metadata_credentials = {
            "consumer_key": factory.make_string(),
            "token_key": factory.make_string(),
            "token_secret": factory.make_string(),
        }
        self.fake_refresher = FakeRefresher(mocker, self.metadata_credentials)

    def makeService(self, *args, **kwargs):
        service = StubNetworksMonitoringService(*args, clock=Clock(), **kwargs)
        service.credentials = self.metadata_credentials.copy()
        self.request.addfinalizer(service._release_sole_responsibility)
        return service

    def test_init(self, request):
        service = self.makeService()
        assert isinstance(service, MultiService)
        assert service._timer_service.step == service.INTERVAL.total_seconds()
        assert (service._do_action, (), {}) == service._timer_service.call

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_get_all_interfaces_definition_is_called_in_thread(self):
        def record_thread():
            threads.append(threading.current_thread())
            return {}

        threads = []
        service = self.makeService()
        service.running = 1
        self.all_interfaces_mock.side_effect = record_thread
        yield service._do_action()
        assert 1 == len(service.interfaces)
        [thread] = threads
        assert isinstance(thread, threading.Thread)
        assert thread != threadable.ioThread

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_getInterfaces_called_to_get_configuration(self, mocker):
        service = self.makeService()
        service.running = 1
        getInterfaces = mocker.patch.object(service, "getInterfaces")
        my_interfaces = {
            "eth0": {"type": "physical", "parents": [], "enabled": True},
        }
        getInterfaces.return_value = succeed(my_interfaces)
        yield service._do_action()
        assert service.interfaces == [my_interfaces]

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_logs_errors(self, mocker):
        service = self.makeService()
        service.running = 1
        with TwistedLoggerFixture() as logger:
            error_message = factory.make_string()
            get_interfaces = mocker.patch.object(
                services, "get_all_interfaces_definition"
            )
            get_interfaces.side_effect = Exception(error_message)
            yield service._do_action()
        assert logger.output.startswith(
            "Failed to update and/or record network interface configuration"
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_starting_service_triggers_interface_update(self):
        service = self.makeService()
        yield service.startService()
        service.clock.advance(0)
        assert 1 == service.update_interface__calls
        yield service.stopService()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_runs_refresh_and_annotates_commissioning_with_hints(self, mocker):
        # Don't actually wait for beaconing to complete.
        mocker.patch.object(services, "pause")
        service = self.makeService(enable_beaconing=True)
        service.maas_url = "http://my.example.com/MAAS"
        service.system_id = "my-system"
        service.credentials = {
            "consumer_key": "my-consumer",
            "token_key": "my-key",
            "token_secret": "my-secret",
        }
        self.fake_refresher.credentials.update(service.credentials)
        base_lxd_data = {factory.make_string(): factory.make_string()}
        base_lxd_output = json.dumps(base_lxd_data)
        self.fake_refresher.stdout_content[COMMISSIONING_OUTPUT_NAME] = (
            base_lxd_output.encode("utf-8")
        )
        network_extra = {
            "interfaces": {
                "eth0": {"type": "physical", "parents": [], "enabled": True},
                "eth1": {"type": "physical", "parents": [], "enabled": False},
            },
            "monitored-interfaces": ["eth0"],
            "hints": {"my-hint": "foo"},
        }
        self.all_interfaces_mock.return_value = network_extra["interfaces"]
        mocker.patch.object(
            service, "_get_topology_hints"
        ).return_value = network_extra["hints"]

        yield service.startService()
        service.clock.advance(0)
        yield service.stopService()

        metadata_url = service.maas_url + "/metadata/2012-03-01/"
        script_runs = self.fake_refresher.script_runs[metadata_url]
        assert "finished" == script_runs[COMMISSIONING_OUTPUT_NAME].status
        commissioning_data_out = json.loads(
            script_runs[COMMISSIONING_OUTPUT_NAME].out.decode("utf-8")
        )
        commissioning_data_combined = json.loads(
            script_runs[COMMISSIONING_OUTPUT_NAME].combined.decode("utf-8")
        )
        expected_commisioning_data = base_lxd_data.copy()
        expected_commisioning_data.update({"network-extra": network_extra})
        assert expected_commisioning_data == commissioning_data_out
        assert expected_commisioning_data == commissioning_data_combined

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_runs_refresh_and_annotates_commissioning_without_hints(self):
        service = self.makeService()
        service.maas_url = "http://my.example.com/MAAS"
        service.system_id = "my-system"
        service.credentials = {
            "consumer_key": "my-consumer",
            "token_key": "my-key",
            "token_secret": "my-secret",
        }
        self.fake_refresher.credentials.update(service.credentials)
        base_lxd_data = {factory.make_string(): factory.make_string()}
        base_lxd_output = json.dumps(base_lxd_data)
        self.fake_refresher.stdout_content[COMMISSIONING_OUTPUT_NAME] = (
            base_lxd_output.encode("utf-8")
        )
        network_extra = {
            "interfaces": {
                "eth0": {"type": "physical", "parents": [], "enabled": True},
                "eth1": {"type": "physical", "parents": [], "enabled": False},
            },
            "monitored-interfaces": ["eth0"],
            "hints": None,
        }
        self.all_interfaces_mock.return_value = network_extra["interfaces"]

        yield service.startService()
        service.clock.advance(0)
        yield service.stopService()

        metadata_url = service.maas_url + "/metadata/2012-03-01/"
        script_runs = self.fake_refresher.script_runs[metadata_url]
        assert "finished" == script_runs[COMMISSIONING_OUTPUT_NAME].status
        commissioning_data_out = json.loads(
            script_runs[COMMISSIONING_OUTPUT_NAME].out.decode("utf-8")
        )
        commissioning_data_combined = json.loads(
            script_runs[COMMISSIONING_OUTPUT_NAME].combined.decode("utf-8")
        )
        expected_commisioning_data = base_lxd_data.copy()
        expected_commisioning_data.update({"network-extra": network_extra})
        assert expected_commisioning_data == commissioning_data_out
        assert expected_commisioning_data == commissioning_data_combined

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_recordInterfaces_called_when_interfaces_changed(self, mocker):
        get_interfaces = mocker.patch.object(
            services, "get_all_interfaces_definition"
        )
        # Configuration changes between the first and second call.
        my_interfaces1 = {"foo": {"parents": [], "enabled": True}}
        my_interfaces2 = {"bar": {"parents": [], "enabled": True}}
        get_interfaces.side_effect = [my_interfaces1, my_interfaces2]

        service = self.makeService()
        service.running = 1
        assert service.interfaces == []
        yield service._do_action()
        assert service.interfaces == [my_interfaces1]
        self.fake_refresher.reset()
        yield service._do_action()
        assert service.interfaces == [my_interfaces1, my_interfaces2]

        get_interfaces.assert_has_calls(calls=[call(), call()])

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_recordInterfaces_not_called_after_signal_error(self, mocker):
        get_interfaces = mocker.patch.object(
            services, "get_all_interfaces_definition"
        )
        my_interfaces = {"foo": {"parents": [], "enabled": True}}
        get_interfaces.return_value = my_interfaces

        service = self.makeService()
        service.running = 1
        assert service.interfaces == []

        with TwistedLoggerFixture() as logger:
            self.fake_refresher.mock_signal.side_effect = SignalException(
                "boom"
            )
            yield service._do_action()
            assert service.interfaces == []
            assert ["Couldn't report test results: boom"] == [
                formatEvent(event)
                for event in logger.events
                if event.get("log_level") == LogLevel.warn
            ]

        # The next time it's run, and no signal error occurs, the interfaces get recorded.
        self.fake_refresher.reset()
        self.fake_refresher.mock_signal.side_effect = (
            self.fake_refresher.fake_signal
        )
        yield service._do_action()
        assert service.interfaces == [my_interfaces]

        get_interfaces.assert_has_calls(calls=[call(), call()])

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_recordInterfaces_not_called_when_interfaces_not_changed(
        self, mocker
    ):
        get_interfaces = mocker.patch.object(
            services, "get_all_interfaces_definition"
        )
        # Configuration does NOT change between the first and second call.
        get_interfaces.side_effect = [{}, {}]

        service = self.makeService()
        service.running = 1
        assert service.interfaces == []
        yield service._do_action()
        assert service.interfaces == [{}]
        yield service._do_action()
        assert service.interfaces == [{}]

        get_interfaces.assert_has_calls(calls=[call(), call()])

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_recordInterfaces_called_after_unexpected_failure(self, mocker):
        get_interfaces = mocker.patch.object(
            services, "get_all_interfaces_definition"
        )
        get_interfaces.return_value = {}

        service = self.makeService()
        service.running = 1
        run_refresh = mocker.patch.object(service, "_run_refresh")
        run_refresh.side_effect = [
            fail(Exception()),
            succeed(None),
            succeed(None),
        ]

        # Using the logger fixture prevents the test case from failing due
        # to the logged exception.
        with TwistedLoggerFixture():
            # _run_refresh is called the first time, as expected.
            run_refresh.reset_mock()
            yield service._do_action()
            assert 1 == run_refresh.call_count

            # _run_refresh is called the second time too; the service noted
            # that it crashed last time and knew to run it again.
            run_refresh.reset_mock()
            yield service._do_action()
            assert 1 == run_refresh.call_count

            # _run_refresh is NOT called the third time; the service noted
            # that the configuration had not changed.
            run_refresh.reset_mock()
            assert 0 == run_refresh.call_count
            yield service._do_action()
            assert 0 == run_refresh.call_count

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_assumes_sole_responsibility_before_updating(self):
        # A filesystem lock is used to prevent multiple network monitors from
        # running on each host machine.
        service = self.makeService()

        # Not locked after instantiating the service.
        lock = service._lock
        assert not lock.is_locked()

        # It's locked when the service is started and has begun iterating.
        service.startService()
        try:
            # It's locked once the first iteration is done.
            yield service.iterations.get()
            assert lock.is_locked()

            # It remains locked as the service iterates.
            yield service._do_action()
            assert lock.is_locked()

        finally:
            yield service.stopService()

        # It's unlocked now that the service is stopped.
        assert not lock.is_locked()

        # Interfaces were recorded.
        assert service.interfaces != []

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_does_not_update_if_cannot_assume_sole_responsibility(self):
        # A filesystem lock is used to prevent multiple network monitors from
        # running on each host machine.
        lock = NetworksMonitoringLock()

        with lock:
            service = self.makeService()
            service.running = 1
            # Iterate a few times.
            yield service._do_action()
            yield service._do_action()
            yield service._do_action()

        # Interfaces were NOT recorded.
        assert service.interfaces == []

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_attempts_to_assume_sole_responsibility_on_each_iteration(self):
        # A filesystem lock is used to prevent multiple network monitors from
        # running on each host machine.
        lock = NetworksMonitoringLock()

        with lock:
            service = self.makeService()
            service.running = 1
            # Iterate one time.
            yield service._do_action()

        # Interfaces have not been recorded yet.
        assert service.interfaces == []
        # Iterate once more and ...
        yield service._do_action()
        # ... interfaces ARE recorded.
        assert service.interfaces != []


@pytest.mark.rack_reactor_guard
class TestJSONPerLineProtocol:
    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_propagates_exit_errors(self):
        proto = JSONPerLineProtocol(callback=lambda json: None)
        reactor.spawnProcess(proto, b"false", (b"false",))
        with pytest.raises(ProcessTerminated, match=" exit code 1"):
            yield proto.done

    def test_parses_only_full_lines(self):
        callback = Mock()
        proto = JSONPerLineProtocol(callback=callback)
        proto.connectionMade()
        # Send an empty JSON dictionary using 3 separate writes.
        proto.outReceived(b"{")
        # No callback yet...
        callback.assert_not_called()
        proto.outReceived(b"}")
        # Still no callback...
        callback.assert_not_called()
        proto.outReceived(b"\n")
        # After a newline, we expect the JSON to be parsed and the callback
        # to receive an empty Python dictionary (which corresponds to the JSON
        # that was sent.)
        callback.assert_called_once_with([{}])

    def test_ignores_interspersed_zero_length_writes(self):
        callback = Mock()
        proto = JSONPerLineProtocol(callback=callback)
        proto.connectionMade()
        proto.outReceived(b"")
        callback.assert_not_called()
        proto.outReceived(b"{}\n")
        callback.assert_called_once_with([{}])
        proto.outReceived(b"")
        callback.assert_called_once_with([{}])
        proto.outReceived(b"{}\n")
        callback.assert_has_calls(calls=[call([{}]), call([{}])])

    def test_logs_non_json_output(self):
        callback = Mock()
        proto = JSONPerLineProtocol(callback=callback)
        proto.connectionMade()
        with TwistedLoggerFixture() as logger:
            proto.outReceived(b"{\n")
        assert logger.output.startswith("Failed to parse JSON: ")

    def test_logs_stderr(self):
        message = factory.make_name("message")
        callback = Mock()
        proto = JSONPerLineProtocol(callback=callback)
        proto.connectionMade()
        with TwistedLoggerFixture() as logger:
            proto.errReceived((message + "\n").encode("ascii"))
        assert logger.output == message

    def test_logs_only_full_lines_from_stderr(self):
        message = factory.make_name("message")
        callback = Mock()
        proto = JSONPerLineProtocol(callback=callback)
        proto.connectionMade()
        with TwistedLoggerFixture() as logger:
            proto.errReceived(message.encode("ascii"))
        assert logger.output == ""

    def test_logs_stderr_at_process_end(self):
        message = factory.make_name("message")
        callback = Mock()
        proto = JSONPerLineProtocol(callback=callback)
        proto.connectionMade()
        with TwistedLoggerFixture() as logger:
            proto.errReceived(message.encode("ascii"))
            assert logger.output == ""
            proto.processEnded(Failure(ProcessDone(0)))
        assert logger.output == message

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_propagates_errors_from_command(self):
        proto = JSONPerLineProtocol(callback=lambda obj: None)
        proto.connectionMade()
        reason = Failure(ProcessTerminated(1))
        proto.processEnded(reason)
        with pytest.raises(ProcessTerminated, match=r"exit code 1\."):
            yield proto.done


@pytest.mark.rack_reactor_guard
class TestProtocolForObserveARP:
    def test_adds_interface(self):
        callback = Mock()
        ifname = factory.make_name("eth")
        proto = ProtocolForObserveARP(ifname, callback=callback)
        proto.makeConnection(Mock(pid=None))
        proto.outReceived(b"{}\n")
        callback.assert_called_once_with([{"interface": ifname}])


@pytest.mark.rack_reactor_guard
class TestProtocolForObserveBeacons:
    def test_adds_interface(self):
        callback = Mock()
        ifname = factory.make_name("eth")
        proto = ProtocolForObserveBeacons(ifname, callback=callback)
        proto.makeConnection(Mock(pid=None))
        proto.outReceived(b"{}\n")
        callback.assert_called_once_with([{"interface": ifname}])


class MockProcessProtocolService(ProcessProtocolService):
    def __init__(self):
        super().__init__()
        self._callback = Mock()

    def getDescription(self):
        return self.__class__.__name__

    def createProcessProtocol(self):
        return JSONPerLineProtocol(callback=self._callback)


class TrueProcessProtocolService(MockProcessProtocolService):
    def getProcessParameters(self):
        return [b"/bin/true"]


class FalseProcessProtocolService(MockProcessProtocolService):
    def getProcessParameters(self):
        return [b"/bin/false"]


class ForeverProcessProtocolService(MockProcessProtocolService):
    def getProcessParameters(self):
        return [b"/bin/cat"]


class EchoProcessProtocolService(MockProcessProtocolService):
    def getProcessParameters(self):
        return [b"/bin/echo", b"{}\n"]


@pytest.mark.rack_reactor_guard
class TestProcessProtocolService:
    @pytest.fixture(autouse=True)
    def _set_up(self, mocker):
        self.mocker = mocker
        # Alter timings of terminateProcess so we don't have to wait so long.
        mocker.patch.object(
            services,
            "terminateProcess",
            partial(services.terminateProcess, quit_after=0.2, kill_after=0.4),
        )

    def test_base_class_cannot_be_used(self):
        pytest.raises(TypeError, ProcessProtocolService)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_starts_and_stops_process(self):
        service = ForeverProcessProtocolService()
        with TwistedLoggerFixture() as logger:
            service.startService()
            assert isinstance(service._protocol.done, Deferred)
            assert not service._protocol.done.called
            yield service.stopService()
            result = yield service._protocol.done
            assert result is None
        assert logger.messages[0] == "ForeverProcessProtocolService started."
        assert (
            logger.messages[-1]
            == "ForeverProcessProtocolService was terminated."
        )
        pytest.raises(
            ProcessExitedAlready, service._process.signalProcess, "INT"
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_handles_normal_process_exit(self):
        # If the spawned process exits with an exit code of zero this is
        # logged as "ended normally".
        service = TrueProcessProtocolService()
        with TwistedLoggerFixture() as logger:
            service.startService()
            yield service._protocol.done
            yield service.stopService()
        assert logger.output == (
            "TrueProcessProtocolService started.\n"
            "---\n"
            "TrueProcessProtocolService ended normally."
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_handles_terminated_process_exit(self):
        # During service stop the spawned process can be terminated with a
        # signal. This is logged with a slightly different error message.
        service = ForeverProcessProtocolService()
        with TwistedLoggerFixture() as logger:
            service.startService()
            yield service.stopService()
        assert logger.messages[0] == "ForeverProcessProtocolService started."
        assert (
            logger.messages[-1]
            == "ForeverProcessProtocolService was terminated."
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_handles_abnormal_process_exit(self):
        # If the spawned process exits with a non-zero exit code this is
        # logged as "a probable error".
        service = FalseProcessProtocolService()
        with TwistedLoggerFixture() as logger:
            service.startService()
            result = yield service._protocol.done
            assert result is None
            yield service.stopService()
        assert logger.output == (
            "FalseProcessProtocolService started.\n"
            "---\n"
            "FalseProcessProtocolService failed.\n"
            "Traceback (most recent call last):\n"
            "Failure: twisted.internet.error.ProcessTerminated: A process has ended with a probable error "
            "condition: process ended with exit code 1.\n"
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_calls_protocol_callback(self):
        service = EchoProcessProtocolService()
        service.startService()
        # Wait for the protocol to finish. (the echo process will stop)
        result = yield service._protocol.done
        service._callback.assert_called_once_with([{}])
        yield service.stopService()
        assert result is None


@pytest.mark.rack_reactor_guard
class TestNeighbourDiscoveryService:
    def test_returns_expected_arguments(self):
        ifname = factory.make_name("eth")
        service = NeighbourDiscoveryService(ifname, Mock())
        args = service.getProcessParameters()
        assert len(args) == 3
        assert args[0].endswith(b"maas-common")
        assert args[1] == b"observe-arp"
        assert args[2] == ifname.encode("utf-8")

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_restarts_process_after_finishing(self, mocker):
        ifname = factory.make_name("eth")
        service = NeighbourDiscoveryService(ifname, Mock())
        mock_process_params = mocker.patch.object(
            service, "getProcessParameters"
        )
        mock_process_params.return_value = [b"/bin/echo", b"{}"]
        service.clock = Clock()
        service.startService()
        # Wait for the protocol to finish
        service.clock.advance(0.0)
        yield service._protocol.done
        # Advance the clock (should start the service again)
        interval = service.step
        service.clock.advance(interval)
        # The Deferred should have been recreated.
        assert isinstance(service._protocol.done, Deferred)
        assert not service._protocol.done.called
        yield service._protocol.done
        service.stopService()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_protocol_logs_stderr(self, request):
        logger = use_logger(request)
        ifname = factory.make_name("eth")
        service = NeighbourDiscoveryService(ifname, lambda _: None)
        protocol = service.createProcessProtocol()
        reactor.spawnProcess(protocol, b"sh", (b"sh", b"-c", b"exec cat >&2"))
        protocol.transport.write(
            b"Lines written to stderr are logged\n"
            b"with a prefix, with no exceptions.\n"
        )
        protocol.transport.closeStdin()
        yield protocol.done
        assert logger.output == (
            f"observe-arp[{ifname}]: Lines written to stderr are logged\n"
            "---\n"
            f"observe-arp[{ifname}]: with a prefix, with no exceptions."
        )


@pytest.mark.rack_reactor_guard
class TestBeaconingService:
    def test_returns_expected_arguments(self):
        ifname = factory.make_name("eth")
        service = BeaconingService(ifname, Mock())
        args = service.getProcessParameters()
        assert len(args) == 3
        assert args[0].endswith(b"maas-common")
        assert args[1] == b"observe-beacons"
        assert args[2] == ifname.encode("utf-8")

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_restarts_process_after_finishing(self, mocker):
        ifname = factory.make_name("eth")
        service = BeaconingService(ifname, Mock())
        mock_process_params = mocker.patch.object(
            service, "getProcessParameters"
        )
        mock_process_params.return_value = [b"/bin/echo", b"{}"]
        service.clock = Clock()
        service.startService()
        # Wait for the protocol to finish
        service.clock.advance(0.0)
        yield service._protocol.done
        # Advance the clock (should start the service again)
        interval = service.step
        service.clock.advance(interval)
        # The Deferred should have been recreated.
        assert isinstance(service._protocol.done, Deferred)
        assert not service._protocol.done.called
        yield service._protocol.done
        service.stopService()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_protocol_logs_stderr(self, request):
        logger = use_logger(request)
        ifname = factory.make_name("eth")
        service = BeaconingService(ifname, lambda _: None)
        protocol = service.createProcessProtocol()
        reactor.spawnProcess(protocol, b"sh", (b"sh", b"-c", b"exec cat >&2"))
        protocol.transport.write(
            b"Lines written to stderr are logged\n"
            b"with a prefix, with no exceptions.\n"
        )
        protocol.transport.closeStdin()
        yield protocol.done
        assert logger.output == (
            f"observe-beacons[{ifname}]: Lines written to stderr are logged\n"
            "---\n"
            f"observe-beacons[{ifname}]: with a prefix, with no exceptions."
        )


@pytest.mark.rack_reactor_guard
class TestMDNSResolverService:
    def test_returns_expected_arguments(self):
        service = MDNSResolverService(Mock())
        args = service.getProcessParameters()
        assert len(args) == 2
        assert args[0].endswith(b"maas-common")
        assert args[1] == b"observe-mdns"

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_protocol_selectively_logs_stderr(self, request):
        logger = use_logger(request)
        service = MDNSResolverService(lambda _: None)
        protocol = service.createProcessProtocol()
        reactor.spawnProcess(protocol, b"sh", (b"sh", b"-c", b"exec cat >&2"))
        protocol.transport.write(
            b"Lines written to stderr are logged\n"
            b"with a prefix, with one exception:\n"
            b"Got SIGFAKE, quitting.\n"
        )
        protocol.transport.closeStdin()
        yield protocol.done
        assert logger.output == (
            "observe-mdns: Lines written to stderr are logged\n"
            "---\n"
            "observe-mdns: with a prefix, with one exception:"
        )


def wait_for_rx_packets(beacon_protocol, count, deferred=None):
    """Waits for a BeaconingSocketProtocol to transmit `count` packets."""
    if deferred is None:
        deferred = Deferred()
    if len(beacon_protocol.rx_queue) >= count:
        deferred.callback(None)
    else:
        reactor.callLater(
            0.001,
            wait_for_rx_packets,
            beacon_protocol,
            count,
            deferred=deferred,
        )
    return deferred


class FakeBeaconPayload(BeaconPayload):
    def __new__(
        cls,
        ulid,
        payload=None,
        ifname="eth0",
        mac=None,
        vid=None,
        version=2,
        beacon_type="solicitation",
    ):
        if payload is None:
            remote = {"name": ifname}
            if mac is not None:
                remote["mac_address"] = mac
            if vid is not None:
                remote["vid"] = vid
            payload = {"ulid": ulid, "remote": remote}
        return super().__new__(cls, b"", version, beacon_type, payload)


@pytest.mark.rack_reactor_guard
class TestBeaconingSocketProtocol:
    """Tests for `BeaconingSocketProtocol`."""

    @pytest.fixture(autouse=True)
    def _set_up_shared_secret(self, mocker):
        self.mocker = mocker
        original_secret = MAAS_SECRET.get()
        original_iteration_count = security.DEFAULT_ITERATION_COUNT
        MAAS_SECRET.set(None)
        mocker.patch.object(security, "_aesgcm_key", None)
        security.DEFAULT_ITERATION_COUNT = 2
        yield
        MAAS_SECRET.set(original_secret)
        security.DEFAULT_ITERATION_COUNT = original_iteration_count

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_creates_listen_port_when_run_with_IReactorMulticast(self):
        # Note: Always use a random port for testing. (port=0)
        protocol = BeaconingSocketProtocol(reactor, port=0)
        assert protocol.listen_port is not None
        # This tests that the post gets closed properly; otherwise the test
        # suite will complain about things left in the reactor.
        yield protocol.stopProtocol()

    def test_skips_creating_listen_port_when_run_with_fake_reactor(self):
        # Note: Always use a random port for testing. (port=0)
        protocol = BeaconingSocketProtocol(Clock(), port=0)
        assert protocol.listen_port is None
        # No listen port, so stopProtocol() shouldn't return a Deferred.
        result = protocol.stopProtocol()
        assert result is None

    def test_beaconReceived_drops_v1_packet(self):
        """beaconReceived() must silently return for version-1 (UUID-based) packets."""
        protocol = BeaconingSocketProtocol(Clock(), port=0)
        beacon_json = {
            "version": 1,
            "type": "solicitation",
            "payload": {"uuid": factory.make_string(), "type": 1},
            "source_ip": "10.0.0.1",
            "source_port": 5240,
        }
        # Must return None without raising and without adding to rx_queue
        result = protocol.beaconReceived(beacon_json)
        assert result is None
        assert len(protocol.rx_queue) == 0

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_sends_and_receives_unicast_beacons(self, request):
        logger = use_logger(request)
        protocol = BeaconingSocketProtocol(
            reactor,
            port=0,
            process_incoming=True,
            loopback=True,
            interface="::",
            debug=True,
        )
        assert protocol.listen_port is not None
        listen_port = protocol.listen_port._realPortNumber
        MAAS_SECRET.set(factory.make_bytes())
        beacon = create_beacon_payload("solicitation", {})
        rx_ulid = beacon.payload["ulid"]
        destination = random.choice(["::ffff:127.0.0.1", "::1"])
        protocol.send_beacon(beacon, (destination, listen_port))
        # Pretend we didn't send this packet. Otherwise we won't reply to it.
        # We have to do this now, before the reactor runs again.
        transmitted = protocol.tx_queue.pop(rx_ulid, None)
        # Since we've instructed the protocol to loop back packets for testing,
        # it should have sent a multicast solicitation, received it back, sent
        # an advertisement, then received it back. So we'll wait for two
        # packets to be sent.
        yield wait_for_rx_packets(protocol, 2)
        # Grab the beacon we know we transmitted and then received.
        received = protocol.rx_queue.pop(rx_ulid, None)
        assert transmitted == beacon
        assert received[0].json["payload"]["ulid"] == rx_ulid
        # Grab the subsequent packets from the queues.
        transmitted = protocol.tx_queue.popitem()[1]
        received = protocol.rx_queue.popitem()[1]
        # We should have received a second packet to ack the first beacon.
        assert received[0].json["payload"]["acks"] == rx_ulid
        # We should have transmitted an advertisement in response to the
        # solicitation.
        assert transmitted.type == "advertisement"
        # This tests that the post gets closed properly; otherwise the test
        # suite will complain about things left in the reactor.
        yield protocol.stopProtocol()
        # In debug mode, the logger should have printed each packet.
        assert "Beacon received:" in logger.output
        assert "Own beacon received:" in logger.output

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_send_multicast_beacon_sets_ipv4_source(self):
        # Note: Always use a random port for testing. (port=0)
        protocol = BeaconingSocketProtocol(
            reactor,
            port=0,
            process_incoming=True,
            loopback=True,
            interface="::",
            debug=False,
        )
        assert protocol.listen_port is not None
        listen_port = protocol.listen_port._realPortNumber
        MAAS_SECRET.set(factory.make_bytes())
        beacon = create_beacon_payload("advertisement", {})
        protocol.send_multicast_beacon("127.0.0.1", beacon, port=listen_port)
        # Verify that we received the packet.
        yield wait_for_rx_packets(protocol, 1)
        yield protocol.stopProtocol()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_send_multicast_beacon_sets_ipv6_source(self):
        pytest.skip("IPv6 loopback multicast isn't working")
        protocol = BeaconingSocketProtocol(
            reactor,
            port=0,
            process_incoming=True,
            loopback=True,
            interface="::",
            debug=False,
        )
        assert protocol.listen_port is not None
        listen_port = protocol.listen_port._realPortNumber
        MAAS_SECRET.set(factory.make_bytes())
        beacon = create_beacon_payload("advertisement", {})
        # The loopback interface ifindex should always be 1; this is saying
        # to send an IPv6 multicast on ifIndex == 1.
        protocol.send_multicast_beacon(1, beacon, port=listen_port)
        yield wait_for_rx_packets(protocol, 1)
        yield protocol.stopProtocol()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_hints_for_own_beacon_received_on_another_interface(self):
        # Note: Always use a random port for testing. (port=0)
        protocol = BeaconingSocketProtocol(
            reactor,
            port=0,
            process_incoming=False,
            loopback=True,
            interface="::",
            debug=True,
        )
        # Need to generate a real ULID with the current time, so it doesn't
        # get aged out.
        ulid = str(ULID())
        # Make the protocol think we sent a beacon with this ULID already.
        fake_tx_beacon = FakeBeaconPayload(ulid, ifname="eth0")
        protocol.tx_queue[ulid] = fake_tx_beacon
        fake_rx_beacon = {
            "source_ip": "127.0.0.1",
            "source_port": 5240,
            "destination_ip": "224.0.0.118",
            # Note the different receive interface.
            "interface": "eth1",
            "version": 2,
            "type": "solicitation",
            "payload": fake_tx_beacon.payload,
        }
        protocol.beaconReceived(fake_rx_beacon)
        # Should only have created one hint.
        hint = protocol.topology_hints[ulid].pop()
        assert hint.hint == "rx_own_beacon_on_other_interface"
        yield protocol.stopProtocol()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_hints_for_own_beacon_received_on_same_interface(self):
        # Note: Always use a random port for testing. (port=0)
        protocol = BeaconingSocketProtocol(
            reactor,
            port=0,
            process_incoming=False,
            loopback=True,
            interface="::",
            debug=True,
        )
        # Need to generate a real ULID with the current time, so it doesn't
        # get aged out.
        ulid = str(ULID())
        # Make the protocol think we sent a beacon with this ULID already.
        fake_tx_beacon = FakeBeaconPayload(ulid, ifname="eth0")
        protocol.tx_queue[ulid] = fake_tx_beacon
        fake_rx_beacon = {
            "source_ip": "127.0.0.1",
            "source_port": 5240,
            "destination_ip": "224.0.0.118",
            "interface": "eth0",
            "version": 2,
            "type": "solicitation",
            "payload": fake_tx_beacon.payload,
        }
        protocol.beaconReceived(fake_rx_beacon)
        # Should only have created one hint.
        hint = protocol.topology_hints[ulid].pop()
        assert hint.hint == "rx_own_beacon_on_tx_interface"
        yield protocol.stopProtocol()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_hints_for_same_beacon_seen_on_multiple_interfaces(self):
        # Note: Always use a random port for testing. (port=0)
        protocol = BeaconingSocketProtocol(
            reactor,
            port=0,
            process_incoming=False,
            loopback=True,
            interface="::",
            debug=True,
        )
        # Don't try to send out any replies.
        self.mocker.patch.object(services, "create_beacon_payload")
        self.mocker.patch.object(protocol, "send_beacon")
        # Need to generate a real ULID with the current time, so it doesn't
        # get aged out.
        ulid = str(ULID())
        # Make the protocol think we sent a beacon with this ULID already.
        fake_tx_beacon = FakeBeaconPayload(ulid, ifname="eth0")
        fake_rx_beacon_eth0 = {
            "source_ip": "127.0.0.1",
            "source_port": 5240,
            "destination_ip": "224.0.0.118",
            "interface": "eth0",
            "version": 2,
            "type": "solicitation",
            "payload": fake_tx_beacon.payload,
        }
        fake_rx_beacon_eth1 = {
            "source_ip": "127.0.0.1",
            "source_port": 5240,
            "destination_ip": "224.0.0.118",
            "interface": "eth1",
            "vid": 100,
            "version": 2,
            "type": "solicitation",
            "payload": fake_tx_beacon.payload,
        }
        protocol.beaconReceived(fake_rx_beacon_eth0)
        protocol.beaconReceived(fake_rx_beacon_eth1)
        hints = protocol.topology_hints[ulid]
        expected_hints = {
            TopologyHint(
                ifname="eth0",
                vid=None,
                hint="same_local_fabric_as",
                related_ifname="eth1",
                related_vid=100,
                related_mac=None,
            ),
            TopologyHint(
                ifname="eth1",
                vid=100,
                hint="same_local_fabric_as",
                related_ifname="eth0",
                related_vid=None,
                related_mac=None,
            ),
        }
        assert hints == expected_hints
        yield protocol.stopProtocol()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_hints_for_remote_unicast(self):
        # Note: Always use a random port for testing. (port=0)
        protocol = BeaconingSocketProtocol(
            reactor,
            port=0,
            process_incoming=False,
            loopback=True,
            interface="::",
            debug=True,
        )
        # Don't try to send out any replies.
        self.mocker.patch.object(services, "create_beacon_payload")
        self.mocker.patch.object(protocol, "send_beacon")
        # Need to generate a real ULID with the current time, so it doesn't
        # get aged out.
        ulid = str(ULID())
        # Make the protocol think we sent a beacon with this ULID already.
        tx_mac = factory.make_mac_address()
        fake_tx_beacon = FakeBeaconPayload(
            ulid, ifname="eth1", mac=tx_mac, vid=100
        )
        fake_rx_beacon = {
            "source_ip": "127.0.0.1",
            "source_port": 5240,
            "destination_ip": "127.0.0.1",
            "interface": "eth0",
            "version": 2,
            "type": "solicitation",
            "payload": fake_tx_beacon.payload,
        }
        protocol.beaconReceived(fake_rx_beacon)
        hints = protocol.topology_hints[ulid]
        expected_hints = {
            TopologyHint(
                ifname="eth0",
                vid=None,
                hint="routable_to",
                related_ifname="eth1",
                related_vid=100,
                related_mac=tx_mac,
            )
        }
        assert hints == expected_hints
        yield protocol.stopProtocol()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_hints_for_remote_multicast(self):
        # Note: Always use a random port for testing. (port=0)
        protocol = BeaconingSocketProtocol(
            reactor,
            port=0,
            process_incoming=False,
            loopback=True,
            interface="::",
            debug=True,
        )
        # Don't try to send out any replies.
        self.mocker.patch.object(services, "create_beacon_payload")
        self.mocker.patch.object(protocol, "send_beacon")
        # Need to generate a real ULID with the current time, so it doesn't
        # get aged out.
        ulid = str(ULID())
        # Make the protocol think we sent a beacon with this ULID already.
        tx_mac = factory.make_mac_address()
        fake_tx_beacon = FakeBeaconPayload(
            ulid, ifname="eth1", mac=tx_mac, vid=100
        )
        fake_rx_beacon = {
            "source_ip": "127.0.0.1",
            "source_port": 5240,
            "destination_ip": "224.0.0.118",
            "interface": "eth0",
            "vid": 200,
            "version": 2,
            "type": "solicitation",
            "payload": fake_tx_beacon.payload,
        }
        protocol.beaconReceived(fake_rx_beacon)
        hints = protocol.topology_hints[ulid]
        expected_hints = {
            TopologyHint(
                ifname="eth0",
                vid=200,
                hint="on_remote_network",
                related_ifname="eth1",
                related_vid=100,
                related_mac=tx_mac,
            )
        }
        assert hints == expected_hints
        yield protocol.stopProtocol()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_queues_multicast_beacon_soliciations_upon_request(self):
        # Note: Always use a random port for testing. (port=0)
        clock = Clock()
        protocol = BeaconingSocketProtocol(
            clock,
            port=0,
            process_incoming=False,
            loopback=True,
            interface="::",
            debug=True,
        )
        # Don't try to send out any replies.
        self.mocker.patch.object(services, "create_beacon_payload")
        send_mcast_mock = self.mocker.patch.object(
            protocol, "send_multicast_beacons"
        )
        self.mocker.patch.object(protocol, "send_beacon")
        yield protocol.queueMulticastBeaconing(solicitation=True)
        clock.advance(0)
        send_mcast_mock.assert_called_once_with({}, "solicitation")

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_multicasts_at_most_once_per_five_seconds(self):
        # Note: Always use a random port for testing. (port=0)
        clock = Clock()
        protocol = BeaconingSocketProtocol(
            clock,
            port=0,
            process_incoming=False,
            loopback=True,
            interface="::",
            debug=True,
        )
        # Don't try to send out any replies.
        self.mocker.patch.object(services, "create_beacon_payload")
        monotonic_mock = self.mocker.patch.object(services.time, "monotonic")
        send_mcast_mock = self.mocker.patch.object(
            protocol, "send_multicast_beacons"
        )
        self.mocker.patch.object(protocol, "send_beacon")
        monotonic_mock.side_effect = [
            # Initial queue
            6,
            # Initial dequeue
            6,
            # Second queue (hasn't yet been 5 seconds)
            10,
            # Third queue
            11,
            # Second dequeue
            11,
        ]
        yield protocol.queueMulticastBeaconing()
        clock.advance(0)
        send_mcast_mock.assert_called_once_with({}, "advertisement")
        send_mcast_mock.reset_mock()
        yield protocol.queueMulticastBeaconing()
        yield protocol.queueMulticastBeaconing(solicitation=True)
        clock.advance(4.9)
        send_mcast_mock.assert_not_called()
        clock.advance(0.1)
        send_mcast_mock.assert_called_once_with({}, "solicitation")

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_multiple_beacon_requests_coalesced(self):
        # Note: Always use a random port for testing. (port=0)
        clock = Clock()
        protocol = BeaconingSocketProtocol(
            clock,
            port=0,
            process_incoming=False,
            loopback=True,
            interface="::",
            debug=True,
        )
        # Don't try to send out any replies.
        self.mocker.patch.object(services, "create_beacon_payload")
        send_mcast_mock = self.mocker.patch.object(
            protocol, "send_multicast_beacons"
        )
        self.mocker.patch.object(protocol, "send_beacon")
        yield protocol.queueMulticastBeaconing()
        yield protocol.queueMulticastBeaconing()
        clock.advance(5)
        send_mcast_mock.assert_called_once_with({}, "advertisement")

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_solicitation_wins_when_multiple_requests_queued(self):
        # Note: Always use a random port for testing. (port=0)
        clock = Clock()
        protocol = BeaconingSocketProtocol(
            clock,
            port=0,
            process_incoming=False,
            loopback=True,
            interface="::",
            debug=True,
        )
        # Don't try to send out any replies.
        self.mocker.patch.object(services, "create_beacon_payload")
        send_mcast_mock = self.mocker.patch.object(
            protocol, "send_multicast_beacons"
        )
        self.mocker.patch.object(protocol, "send_beacon")
        yield protocol.queueMulticastBeaconing()
        yield protocol.queueMulticastBeaconing(solicitation=True)
        clock.advance(5)
        send_mcast_mock.assert_called_once_with({}, "solicitation")

    def test_send_multicast_beacons(self):
        interfaces = {
            "eth0": {"enabled": True, "links": []},
            "eth1": {"enabled": True, "links": []},
            "eth2": {"enabled": True, "links": []},
        }
        self.mocker.patch.object(
            socket, "if_nametoindex", lambda name: int(name[3:])
        )
        protocol = BeaconingSocketProtocol(
            Clock(),
            port=0,
            process_incoming=False,
            loopback=True,
            interface="::",
            debug=True,
        )
        self.mocker.patch.object(services, "create_beacon_payload")
        send_mcast_mock = self.mocker.patch.object(
            protocol, "send_multicast_beacon"
        )
        protocol.send_multicast_beacons(interfaces)
        # beaconing is sent for each interface ID
        assert send_mcast_mock.mock_calls == [
            call(0, ANY),
            call(1, ANY),
            call(2, ANY),
        ]
