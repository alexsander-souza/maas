# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `provisioningserver.drivers.power.hmcz`."""

from dataclasses import dataclass
import json
import random
import typing
from unittest.mock import call, Mock

import pytest
from twisted.internet import defer
from twisted.internet.defer import inlineCallbacks, succeed
from zhmcclient import HTTPError, StatusTimeout
from zhmcclient_mock import FakedSession

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.factory import factory
from provisioningserver.drivers.power import hmcz as hmcz_module
from provisioningserver.drivers.power import PowerActionError, PowerError
from provisioningserver.rpc import clusterservice, region
from provisioningserver.rpc.testing import MockLiveClusterToRegionRPCFixture

TIMEOUT = get_testing_timeout()


@pytest.mark.rack_reactor_guard
class TestHMCZPowerDriver:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        self.mocker = mocker
        self.power_address = factory.make_ip_address()
        self.fake_session = FakedSession(
            self.power_address,
            factory.make_name("hmc_name"),
            # The version and API version below were taken from
            # the test environment given by IBM.
            "2.14.1",
            "2.40",
        )
        mocker.patch.object(
            hmcz_module, "Session"
        ).return_value = self.fake_session
        self.hmcz = hmcz_module.HMCZPowerDriver()

    def make_context(self, power_partition_name=None):
        if power_partition_name is None:
            power_partition_name = factory.make_name("power_partition_name")
        return {
            "power_address": self.power_address,
            "power_user": factory.make_name("power_user"),
            "power_pass": factory.make_name("power_pass"),
            "power_partition_name": power_partition_name,
        }

    def test_detect_missing_packages(self):
        hmcz_module.no_zhmcclient = False
        assert [] == self.hmcz.detect_missing_packages()

    def test_detect_missing_packages_missing(self):
        hmcz_module.no_zhmcclient = True
        assert ["python3-zhmcclient"] == self.hmcz.detect_missing_packages()

    def test_get_partition(self):
        power_partition_name = factory.make_name("power_partition_name")
        cpc = self.fake_session.hmc.cpcs.add(
            {
                "name": factory.make_name("cpc"),
                "dpm-enabled": True,
            }
        )
        cpc.partitions.add({"name": power_partition_name})

        assert power_partition_name == self.hmcz._get_partition(
            self.make_context(power_partition_name)
        ).get_property("name")

    def test_get_partition_ignores_cpcs_with_no_dpm(self):
        mock_logger = self.mocker.patch.object(hmcz_module.maaslog, "warning")
        power_partition_name = factory.make_name("power_partition_name")
        self.fake_session.hmc.cpcs.add(
            {
                "name": factory.make_name("cpc"),
                "dpm-enabled": False,
            }
        )
        cpc = self.fake_session.hmc.cpcs.add({"dpm-enabled": True})
        cpc.partitions.add({"name": power_partition_name})

        assert power_partition_name == self.hmcz._get_partition(
            self.make_context(power_partition_name)
        ).get_property("name")
        mock_logger.assert_called_once()

    def test_get_partition_doesnt_find_partition(self):
        cpc = self.fake_session.hmc.cpcs.add(
            {
                "name": factory.make_name("cpc"),
                "dpm-enabled": True,
            }
        )
        cpc.partitions.add({"name": factory.make_name("power_partition_name")})

        with pytest.raises(PowerActionError):
            self.hmcz._get_partition(self.make_context())

    def test_get_partition_logs_off_session_when_not_found(self):
        cpc = self.fake_session.hmc.cpcs.add(
            {
                "name": factory.make_name("cpc"),
                "dpm-enabled": True,
            }
        )
        cpc.partitions.add({"name": factory.make_name("power_partition_name")})

        with pytest.raises(PowerActionError):
            self.hmcz._get_partition(self.make_context())
        assert not self.fake_session.is_logon()

    # zhmcclient_mock doesn't currently support async so MagicMock
    # must be used for power on/off

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_on(self):
        mock_get_partition = self.mocker.patch.object(
            self.hmcz, "_get_partition"
        )
        yield self.hmcz.power_on(None, self.make_context())
        mock_get_partition.return_value.stop.assert_not_called()
        mock_get_partition.return_value.start.assert_called_once_with(
            wait_for_completion=False
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_on_logs_off_session(self):
        mock_get_partition = self.mocker.patch.object(
            self.hmcz, "_get_partition"
        )
        partition = mock_get_partition.return_value
        yield self.hmcz.power_on(None, self.make_context())
        partition.manager.session.logoff.assert_called_once()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_on_succeeds_even_if_session_logoff_fails(self):
        mock_get_partition = self.mocker.patch.object(
            self.hmcz, "_get_partition"
        )
        partition = mock_get_partition.return_value
        partition.manager.session.logoff.side_effect = ConnectionError()
        # Should not raise, despite logoff() failing.
        yield self.hmcz.power_on(None, self.make_context())
        partition.start.assert_called_once_with(wait_for_completion=False)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_on_stops_in_a_paused_state(self):
        mock_get_partition = self.mocker.patch.object(
            self.hmcz, "_get_partition"
        )
        mock_get_partition.return_value.get_property.return_value = "paused"
        yield self.hmcz.power_on(None, self.make_context())
        mock_get_partition.return_value.stop.assert_called_once_with(
            wait_for_completion=True
        )
        mock_get_partition.return_value.start.assert_called_once_with(
            wait_for_completion=False
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_on_stops_in_a_terminated_state(self):
        mock_get_partition = self.mocker.patch.object(
            self.hmcz, "_get_partition"
        )
        mock_get_partition.return_value.get_property.return_value = (
            "terminated"
        )
        yield self.hmcz.power_on(None, self.make_context())
        mock_get_partition.return_value.stop.assert_called_once_with(
            wait_for_completion=True
        )
        mock_get_partition.return_value.start.assert_called_once_with(
            wait_for_completion=False
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_on_waits_for_stopping_state(self):
        mock_get_partition = self.mocker.patch.object(
            self.hmcz, "_get_partition"
        )
        mock_get_partition.return_value.get_property.return_value = "stopping"
        yield self.hmcz.power_on(None, self.make_context())
        mock_get_partition.return_value.wait_for_status.assert_called_once_with(
            "stopped", 120
        )
        mock_get_partition.return_value.start.assert_called_once_with(
            wait_for_completion=False
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_on_times_out_waiting_for_stopping_state(self):
        mock_get_partition = self.mocker.patch.object(
            self.hmcz, "_get_partition"
        )
        mock_get_partition.return_value.get_property.return_value = "stopping"
        mock_get_partition.return_value.wait_for_status.side_effect = (
            StatusTimeout(None, None, None, None)
        )
        with pytest.raises(PowerError):
            yield self.hmcz.power_on(None, self.make_context())

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_off(self):
        mock_get_partition = self.mocker.patch.object(
            self.hmcz, "_get_partition"
        )
        yield self.hmcz.power_off(None, self.make_context())
        mock_get_partition.return_value.stop.assert_called_once_with(
            wait_for_completion=False
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_off_logs_off_session(self):
        mock_get_partition = self.mocker.patch.object(
            self.hmcz, "_get_partition"
        )
        partition = mock_get_partition.return_value
        yield self.hmcz.power_off(None, self.make_context())
        partition.manager.session.logoff.assert_called_once()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_off_waits_for_starting_state(self):
        mock_get_partition = self.mocker.patch.object(
            self.hmcz, "_get_partition"
        )
        mock_get_partition.return_value.get_property.return_value = "starting"
        yield self.hmcz.power_off(None, self.make_context())
        mock_get_partition.return_value.wait_for_status.assert_called_once_with(
            "active", 120
        )
        mock_get_partition.return_value.stop.assert_called_once_with(
            wait_for_completion=False
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_off_timesout_waiting_for_stopping_state(self):
        mock_get_partition = self.mocker.patch.object(
            self.hmcz, "_get_partition"
        )
        mock_get_partition.return_value.get_property.return_value = "starting"
        mock_get_partition.return_value.wait_for_status.side_effect = (
            StatusTimeout(None, None, None, None)
        )
        with pytest.raises(PowerError):
            yield self.hmcz.power_off(None, self.make_context())

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_query_starting(self):
        power_partition_name = factory.make_name("power_partition_name")
        cpc = self.fake_session.hmc.cpcs.add(
            {
                "name": factory.make_name("cpc"),
                "dpm-enabled": True,
            }
        )
        cpc.partitions.add(
            {
                "name": power_partition_name,
                "status": "starting",
            }
        )

        status = yield self.hmcz.power_query(
            None, self.make_context(power_partition_name)
        )

        assert "on" == status

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_query_active(self):
        power_partition_name = factory.make_name("power_partition_name")
        cpc = self.fake_session.hmc.cpcs.add(
            {
                "name": factory.make_name("cpc"),
                "dpm-enabled": True,
            }
        )
        cpc.partitions.add(
            {
                "name": power_partition_name,
                "status": "active",
            }
        )

        status = yield self.hmcz.power_query(
            None, self.make_context(power_partition_name)
        )

        assert "on" == status

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_query_logs_off_session(self):
        power_partition_name = factory.make_name("power_partition_name")
        cpc = self.fake_session.hmc.cpcs.add(
            {
                "name": factory.make_name("cpc"),
                "dpm-enabled": True,
            }
        )
        cpc.partitions.add(
            {
                "name": power_partition_name,
                "status": "active",
            }
        )

        yield self.hmcz.power_query(
            None, self.make_context(power_partition_name)
        )

        assert not self.fake_session.is_logon()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_query_result_not_masked_by_session_logoff_failure(self):
        mock_get_partition = self.mocker.patch.object(
            self.hmcz, "_get_partition"
        )
        partition = mock_get_partition.return_value
        partition.get_property.return_value = "active"
        partition.manager.session.logoff.side_effect = ConnectionError()

        status = yield self.hmcz.power_query(None, self.make_context())

        # The result is still returned, despite logoff() failing.
        assert "on" == status

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_query_degraded(self):
        power_partition_name = factory.make_name("power_partition_name")
        cpc = self.fake_session.hmc.cpcs.add(
            {
                "name": factory.make_name("cpc"),
                "dpm-enabled": True,
            }
        )
        cpc.partitions.add(
            {
                "name": power_partition_name,
                "status": "degraded",
            }
        )

        status = yield self.hmcz.power_query(
            None, self.make_context(power_partition_name)
        )

        assert "on" == status

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_query_stopping(self):
        power_partition_name = factory.make_name("power_partition_name")
        cpc = self.fake_session.hmc.cpcs.add(
            {
                "name": factory.make_name("cpc"),
                "dpm-enabled": True,
            }
        )
        cpc.partitions.add(
            {
                "name": power_partition_name,
                "status": "stopping",
            }
        )

        status = yield self.hmcz.power_query(
            None, self.make_context(power_partition_name)
        )

        assert "off" == status

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_query_stopped(self):
        power_partition_name = factory.make_name("power_partition_name")
        cpc = self.fake_session.hmc.cpcs.add(
            {
                "name": factory.make_name("cpc"),
                "dpm-enabled": True,
            }
        )
        cpc.partitions.add(
            {
                "name": power_partition_name,
                "status": "stopped",
            }
        )

        status = yield self.hmcz.power_query(
            None, self.make_context(power_partition_name)
        )

        assert "off" == status

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_query_paused(self):
        power_partition_name = factory.make_name("power_partition_name")
        cpc = self.fake_session.hmc.cpcs.add(
            {
                "name": factory.make_name("cpc"),
                "dpm-enabled": True,
            }
        )
        cpc.partitions.add(
            {
                "name": power_partition_name,
                "status": "paused",
            }
        )

        status = yield self.hmcz.power_query(
            None, self.make_context(power_partition_name)
        )

        assert "off" == status

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_query_terminated(self):
        power_partition_name = factory.make_name("power_partition_name")
        cpc = self.fake_session.hmc.cpcs.add(
            {
                "name": factory.make_name("cpc"),
                "dpm-enabled": True,
            }
        )
        cpc.partitions.add(
            {
                "name": power_partition_name,
                "status": "terminated",
            }
        )

        status = yield self.hmcz.power_query(
            None, self.make_context(power_partition_name)
        )

        assert "off" == status

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_power_query_other(self):
        power_partition_name = factory.make_name("power_partition_name")
        cpc = self.fake_session.hmc.cpcs.add(
            {
                "name": factory.make_name("cpc"),
                "dpm-enabled": True,
            }
        )
        cpc.partitions.add(
            {
                "name": power_partition_name,
                "status": factory.make_name("status"),
            }
        )

        status = yield self.hmcz.power_query(
            None, self.make_context(power_partition_name)
        )

        assert "unknown" == status

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_set_boot_order_network(self):
        power_partition_name = factory.make_name("power_partition_name")
        mac_address = factory.make_mac_address()
        cpc = self.fake_session.hmc.cpcs.add(
            {
                "name": factory.make_name("cpc"),
                "dpm-enabled": True,
            }
        )
        partition = cpc.partitions.add(
            {
                "name": power_partition_name,
                "status": "terminated",
            }
        )
        partition.nics.add({"mac-address": factory.make_mac_address()})
        nic = partition.nics.add({"mac-address": mac_address})

        yield self.hmcz.set_boot_order(
            None,
            self.make_context(power_partition_name),
            [
                {
                    "id": random.randint(0, 100),
                    "name": factory.make_name("name"),
                    "mac_address": mac_address,
                    "vendor": factory.make_name("vendor"),
                    "product": factory.make_name("product"),
                }
            ]
            + [
                {
                    factory.make_name("key"): factory.make_name("value")
                    for _ in range(5)
                }
                for _ in range(5)
            ],
        )

        assert "network-adapter" == partition.properties["boot-device"]
        assert nic.uri == partition.properties["boot-network-device"]

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_set_boot_order_logs_off_session(self):
        power_partition_name = factory.make_name("power_partition_name")
        mac_address = factory.make_mac_address()
        cpc = self.fake_session.hmc.cpcs.add(
            {
                "name": factory.make_name("cpc"),
                "dpm-enabled": True,
            }
        )
        partition = cpc.partitions.add(
            {
                "name": power_partition_name,
                "status": "terminated",
            }
        )
        partition.nics.add({"mac-address": mac_address})

        yield self.hmcz.set_boot_order(
            None,
            self.make_context(power_partition_name),
            [{"mac_address": mac_address}],
        )

        assert not self.fake_session.is_logon()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_set_boot_order_storage_volume(self):
        # zhmcclient_mock doesn't support storage groups.
        serial = "PHAX852069487P8CGN "
        uuid = "600507681081001D4800000000000083"
        uri = factory.make_UUID()

        mock_storage_volume = Mock()
        mock_storage_volume.properties = {
            "serial-number": serial,
        }
        mock_storage_volume.uri = uri
        mock_storage_group = Mock()
        mock_storage_group.storage_volumes.list.return_value = [
            mock_storage_volume
        ]
        mock_partition = Mock()
        mock_partition.list_attached_storage_groups.return_value = [
            mock_storage_group,
        ]
        mock_get_partition = self.mocker.patch.object(
            self.hmcz, "_get_partition"
        )
        mock_get_partition.return_value = mock_partition

        yield self.hmcz.set_boot_order(
            None,
            self.make_context(),
            [
                {
                    "id": random.randint(0, 100),
                    "name": factory.make_name("name"),
                    "id_path": factory.make_name("id_path"),
                    "model": factory.make_name("model"),
                    "serial": serial.strip().lower(),
                }
            ]
            + [
                {
                    factory.make_name("key"): factory.make_name("value")
                    for _ in range(5)
                }
                for _ in range(5)
            ],
        )

        mock_storage_volume.properties = {
            "uuid": uuid,
        }
        yield self.hmcz.set_boot_order(
            None,
            self.make_context(),
            [
                {
                    "id": random.randint(0, 100),
                    "name": factory.make_name("name"),
                    "id_path": factory.make_name("id_path"),
                    "model": factory.make_name("model"),
                    "serial": uuid.strip().lower(),
                }
            ]
            + [
                {
                    factory.make_name("key"): factory.make_name("value")
                    for _ in range(5)
                }
                for _ in range(5)
            ],
        )

        mock_partition.update_properties.assert_has_calls(
            [
                call(
                    {
                        "boot-device": "storage-volume",
                        "boot-storage-volume": uri,
                    }
                ),
                call(
                    {
                        "boot-device": "storage-volume",
                        "boot-storage-volume": uri,
                    }
                ),
            ]
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_set_boot_order_storage_volume_no_storage(self):
        # zhmcclient_mock doesn't support storage groups.
        mock_storage_volume = Mock()
        mock_storage_volume.properties = {
            "serial-number": "PHAX852069487P8CGN ",
        }
        mock_storage_group = Mock()
        mock_storage_group.storage_volumes.list.return_value = [
            mock_storage_volume
        ]
        mock_partition = Mock()
        mock_partition.list_attached_storage_groups.return_value = [
            mock_storage_group,
        ]
        mock_get_partition = self.mocker.patch.object(
            self.hmcz, "_get_partition"
        )
        mock_get_partition.return_value = mock_partition

        with pytest.raises(PowerError):
            yield self.hmcz.set_boot_order(
                None,
                self.make_context(),
                [
                    {
                        "id": random.randint(0, 100),
                        "name": factory.make_name("name"),
                        "id_path": factory.make_name("id_path"),
                        "model": factory.make_name("model"),
                        "serial": "serial-not-in-hmcz",
                    }
                ]
                + [
                    {
                        factory.make_name("key"): factory.make_name("value")
                        for _ in range(5)
                    }
                    for _ in range(5)
                ],
            )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_set_boot_order_waits_for_starting_state(self):
        # Mock must be used as partition.wait_for_status() hangs when not
        # connected to a real HMC
        mock_get_partition = self.mocker.patch.object(
            self.hmcz, "_get_partition"
        )
        mock_get_partition.return_value.get_property.return_value = "starting"

        yield self.hmcz.set_boot_order(
            None,
            self.make_context(),
            [{"mac_address": factory.make_mac_address()}],
        )

        mock_get_partition.return_value.wait_for_status.assert_called_once_with(
            ["stopped", "active", "degraded", "paused", "terminated"], 120
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_set_boot_order_waits_for_stopping_state(self):
        # Mock must be used as partition.wait_for_status() hangs when not
        # connected to a real HMC
        mock_get_partition = self.mocker.patch.object(
            self.hmcz, "_get_partition"
        )
        mock_get_partition.return_value.get_property.return_value = "stopping"

        yield self.hmcz.set_boot_order(
            None,
            self.make_context(),
            [{"mac_address": factory.make_mac_address()}],
        )

        mock_get_partition.return_value.wait_for_status.assert_called_once_with(
            ["stopped", "active", "degraded", "paused", "terminated"], 120
        )


class TestRetryOnBusy:
    """Tests for `hmcz._retry_on_busy`."""

    def make_busy_error(self):
        return HTTPError(
            {
                "http-status": 409,
                "reason": 2,
                "message": "object is busy with another operation",
                "request-method": "POST",
                "request-uri": "/api/partitions/abc",
            }
        )

    def make_not_valid_state_error(self):
        return HTTPError(
            {
                "http-status": 409,
                "reason": 1,
                "message": "partition is not in a valid state",
                "request-method": "POST",
                "request-uri": "/api/partitions/abc",
            }
        )

    def test_returns_result_without_retrying_on_success(self, mocker):
        mock_sleep = mocker.patch.object(hmcz_module.time, "sleep")
        func = Mock(return_value="ok")

        result = hmcz_module._retry_on_busy(
            func, "arg", op_desc="op", system_id="sys", kw=1
        )

        assert result == "ok"
        func.assert_called_once_with("arg", kw=1)
        mock_sleep.assert_not_called()

    def test_retries_while_409_2_busy_then_succeeds(self, mocker):
        mock_sleep = mocker.patch.object(hmcz_module.time, "sleep")
        func = Mock(
            side_effect=[
                self.make_busy_error(),
                self.make_busy_error(),
                "ok",
            ]
        )

        result = hmcz_module._retry_on_busy(
            func, op_desc="op", system_id="sys", retry_delay=5
        )

        assert result == "ok"
        assert func.call_count == 3
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(5)

    def test_retries_while_409_1_not_valid_state_then_succeeds(self, mocker):
        mock_sleep = mocker.patch.object(hmcz_module.time, "sleep")
        func = Mock(
            side_effect=[
                self.make_not_valid_state_error(),
                self.make_not_valid_state_error(),
                "ok",
            ]
        )

        result = hmcz_module._retry_on_busy(
            func, op_desc="op", system_id="sys", retry_delay=5
        )

        assert result == "ok"
        assert func.call_count == 3
        assert mock_sleep.call_count == 2
        mock_sleep.assert_called_with(5)

    def test_retries_across_mixed_409_1_and_409_2_then_succeeds(self, mocker):
        mock_sleep = mocker.patch.object(hmcz_module.time, "sleep")
        func = Mock(
            side_effect=[
                self.make_busy_error(),
                self.make_not_valid_state_error(),
                "ok",
            ]
        )

        result = hmcz_module._retry_on_busy(
            func, op_desc="op", system_id="sys"
        )

        assert result == "ok"
        assert func.call_count == 3
        assert mock_sleep.call_count == 2

    def test_reraises_other_http_errors_immediately(self, mocker):
        mock_sleep = mocker.patch.object(hmcz_module.time, "sleep")
        other = HTTPError({"http-status": 500, "reason": 1})
        func = Mock(side_effect=other)

        with pytest.raises(HTTPError):
            hmcz_module._retry_on_busy(
                func,
                op_desc="op",
                system_id="sys",
            )
        func.assert_called_once()
        mock_sleep.assert_not_called()

    def test_reraises_409_with_other_reason_immediately(self, mocker):
        mock_sleep = mocker.patch.object(hmcz_module.time, "sleep")
        other = HTTPError({"http-status": 409, "reason": 3})
        func = Mock(side_effect=other)

        with pytest.raises(HTTPError):
            hmcz_module._retry_on_busy(
                func,
                op_desc="op",
                system_id="sys",
            )
        func.assert_called_once()
        mock_sleep.assert_not_called()

    def test_gives_up_and_reraises_after_max_attempts(self, mocker):
        mock_sleep = mocker.patch.object(hmcz_module.time, "sleep")
        func = Mock(side_effect=self.make_busy_error())

        with pytest.raises(HTTPError):
            hmcz_module._retry_on_busy(
                func,
                op_desc="op",
                system_id="sys",
                max_attempts=3,
            )
        assert func.call_count == 3
        # No sleep after the final (failing) attempt.
        assert mock_sleep.call_count == 2

    def test_gives_up_and_reraises_after_max_attempts_409_1(self, mocker):
        mock_sleep = mocker.patch.object(hmcz_module.time, "sleep")
        func = Mock(side_effect=self.make_not_valid_state_error())

        with pytest.raises(HTTPError):
            hmcz_module._retry_on_busy(
                func,
                op_desc="op",
                system_id="sys",
                max_attempts=3,
            )
        assert func.call_count == 3
        # No sleep after the final (failing) attempt.
        assert mock_sleep.call_count == 2


@dataclass
class FakeNode:
    architecture: str
    power_type: str
    power_parameters: dict
    mac_addresses: typing.List[str]
    domain: str
    hostname: str
    status: str
    owner: str


@wait_for(timeout=TIMEOUT)
@inlineCallbacks
def _cleanup_rpc_fixture(fixture, shutdown):
    try:
        yield shutdown()
    finally:
        yield fixture.cleanUp()


class FakeRPCService:
    def __init__(self):
        self.nodes = {}

    @inlineCallbacks
    def set_up(self, request):
        fixture = MockLiveClusterToRegionRPCFixture()
        shutdown = [lambda: defer.succeed(None)]
        request.addfinalizer(
            lambda: _cleanup_rpc_fixture(fixture, shutdown[0])
        )
        yield fixture.setUp()
        self.protocol, connecting = fixture.makeEventLoop(
            region.CreateNode, region.CommissionNode
        )
        shutdown[0] = yield connecting
        self.protocol.CreateNode.side_effect = self.create_node
        self.protocol.CommissionNode.side_effect = self.commission_node

    def create_node(
        self,
        protocol,
        architecture,
        power_type,
        power_parameters,
        mac_addresses,
        domain=None,
        hostname=None,
    ):
        system_id = factory.make_name("system_id")
        self.nodes[system_id] = FakeNode(
            architecture,
            power_type,
            json.loads(power_parameters),
            mac_addresses,
            domain,
            hostname,
            "new",
            None,
        )
        return succeed({"system_id": system_id})

    @region.CommissionNode.responder
    def commission_node(
        self,
        protocol,
        system_id,
        user,
    ):
        self.nodes[system_id].status = "commissioning"
        self.nodes[system_id].owner = user
        return succeed({})


@pytest.mark.rack_reactor_guard
class TestProbeHMCZAndEnlist:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        self.mocker = mocker
        mocker.patch.object(
            clusterservice, "get_all_interfaces_definition"
        ).return_value = {}
        self.user = factory.make_name("user")
        self.hostname = factory.make_ip_address()
        self.username = factory.make_name("username")
        self.password = factory.make_name("password")
        self.domain = factory.make_name("domain")
        self.fake_session = FakedSession(
            self.hostname,
            factory.make_name("hmc_name"),
            # The version and API version below were taken from
            # the test environment given by IBM.
            "2.14.1",
            "2.40",
        )
        mocker.patch.object(
            hmcz_module, "Session"
        ).return_value = self.fake_session

        # Add a CPC which does not have dpm enabled to verify its ignored.
        cpc = self.fake_session.hmc.cpcs.add(
            {
                "name": factory.make_name("cpc"),
                "dpm-enabled": False,
            }
        )
        cpc.partitions.add(
            {
                "name": factory.make_name("partition"),
                "status": "stopped",
            }
        )

        cpc = self.fake_session.hmc.cpcs.add(
            {
                "name": factory.make_name("cpc"),
                "dpm-enabled": True,
            }
        )
        self.partitions = {}
        for i in range(3):
            partition_name = f"partition_{i}"
            partition = cpc.partitions.add(
                {
                    "name": partition_name,
                    "status": "stopped",
                }
            )
            macs = [factory.make_mac_address() for _ in range(2)]
            for mac in macs:
                partition.nics.add({"mac-address": mac})
            self.partitions[partition_name] = macs

    @inlineCallbacks
    def create_fake_rpc_service(self, request):
        rpc = FakeRPCService()
        yield rpc.set_up(request)
        return rpc

    def assert_rpc(self, rpc, status, partition_names=None):
        if partition_names:
            partitions_len = len(partition_names)
        else:
            partitions_len = len(self.partitions)
        assert partitions_len == len(rpc.nodes)
        for partition_name, macs in self.partitions.items():
            if partition_names and partition_name not in partition_names:
                continue
            [node] = [
                node
                for node in rpc.nodes.values()
                if node.power_parameters["power_partition_name"]
                == partition_name
            ]
            assert sorted(macs) == sorted(node.mac_addresses)
            assert node.status == status

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_probe_hmcz_and_enlist(self, request):
        rpc = yield self.create_fake_rpc_service(request)
        yield hmcz_module.probe_hmcz_and_enlist(
            self.user,
            self.hostname,
            self.username,
            self.password,
            accept_all=False,
            domain=self.domain,
        )
        self.assert_rpc(rpc, "new")

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_probe_hmcz_and_enlist_filters(self, request):
        rpc = yield self.create_fake_rpc_service(request)
        partition_name = random.choice(list(self.partitions.keys()))
        yield hmcz_module.probe_hmcz_and_enlist(
            self.user,
            self.hostname,
            self.username,
            self.password,
            accept_all=False,
            domain=self.domain,
            prefix_filter=partition_name,
        )
        self.assert_rpc(rpc, "new", [partition_name])

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_probe_hmcz_and_enlist_commissions(self, request):
        rpc = yield self.create_fake_rpc_service(request)
        yield hmcz_module.probe_hmcz_and_enlist(
            self.user,
            self.hostname,
            self.username,
            self.password,
            accept_all=True,
            domain=self.domain,
        )
        self.assert_rpc(rpc, "commissioning")

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_probe_hmcz_and_enlist_logs_off_session(self, request):
        yield self.create_fake_rpc_service(request)
        yield hmcz_module.probe_hmcz_and_enlist(
            self.user,
            self.hostname,
            self.username,
            self.password,
            accept_all=False,
            domain=self.domain,
        )
        assert not self.fake_session.is_logon()
