# Copyright 2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import pytest
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks
from twisted.internet.task import Clock

from maasserver.models import Config, DNSPublication
from maasserver.regiondservices import dns
from maasserver.utils.threads import deferToDatabase
from maastesting.crochet import wait_for

wait_for_reactor = wait_for()


MAAS_INTERNAL_ZONE = """
; Zone file modified: 2025-10-23 21:30:14.556173.
 $TTL 15
@   IN    SOA maas-internal. nobody.example.com. (
              0000000004 ; serial
              600 ; Refresh
              1800 ; Retry
              604800 ; Expire
              15 ; NXTTL
              )

@   15 IN NS maas.
10-0-1-0--24 15 IN A 10.0.1.29
10-0-2-0--24 15 IN A 10.0.2.247
"""


class TestDNSReloadService_Basic:
    """Basic tests for `DNSReloadService`."""

    def test_service_uses__tryUpdate_as_periodic_function(self):
        service = dns.DNSReloadService(reactor)
        assert (service._tryUpdate, (), {}) == service.call

    def test_service_iterates_every_60_seconds(self):
        service = dns.DNSReloadService(reactor)
        assert service.step == 60.0


@pytest.mark.allow_transactions
@pytest.mark.usefixtures(
    "maasdb", "transactional_maasdb", "maas_region_test", "factory"
)
class TestDNSReloadService:
    """Tests for `DNSReloadService`."""

    @wait_for_reactor
    @inlineCallbacks
    def test_tryUpdate_skips_execution_if_already_running(self, mocker):
        service = dns.DNSReloadService(Clock())
        service.update_running = True
        _run_mock = mocker.patch.object(service, "_run")
        yield service._tryUpdate()
        assert _run_mock.call_count == 0

    @wait_for_reactor
    @inlineCallbacks
    def test_tryUpdate_sets_and_release_running_flag(self, mocker):
        service = dns.DNSReloadService(Clock())
        interceptor = {}

        def _run_patch():
            interceptor["update_running"] = service.update_running

        _run_mock = mocker.patch.object(service, "_run")
        _run_mock.side_effect = _run_patch
        yield service._tryUpdate()
        assert _run_mock.call_count == 1
        assert interceptor["update_running"] is True
        assert service.update_running is False

    @wait_for_reactor
    @inlineCallbacks
    def test_tryUpdate_releases_flag_if_run_crashes(self, mocker):
        service = dns.DNSReloadService(Clock())
        _run_mock = mocker.patch.object(service, "_run")
        _run_mock.side_effect = Exception
        yield service._tryUpdate()
        assert _run_mock.call_count == 1
        assert service.update_running is False

    @wait_for_reactor
    @inlineCallbacks
    def test_tryUpdate_calls_dns_update_all_zones_when_no_zones_are_available(
        self, mocker
    ):
        service = dns.DNSReloadService(Clock())
        dns_update_all_zones_mock = mocker.patch.object(
            dns, "dns_update_all_zones"
        )
        yield service._tryUpdate()
        dns_update_all_zones_mock.assert_called_once_with()

    @wait_for_reactor
    @inlineCallbacks
    def test_tryUpdate_calls_dns_update_all_zones_when_serial_mismatch(
        self, tmp_path, monkeypatch, mocker
    ):
        service = dns.DNSReloadService(Clock())
        zone_file_dir = str(tmp_path)
        monkeypatch.setenv("MAAS_ZONE_FILE_CONFIG_DIR", zone_file_dir)
        yield deferToDatabase(
            Config.objects.set_config, "maas_internal_domain", "maas-internal"
        )
        yield deferToDatabase(DNSPublication.objects.create, serial=5)
        with open(zone_file_dir + "/zone.maas-internal", "w") as f:
            f.write(MAAS_INTERNAL_ZONE)

        dns_update_all_zones_mock = mocker.patch.object(
            dns, "dns_update_all_zones"
        )
        yield service._tryUpdate()
        dns_update_all_zones_mock.assert_called_once_with(serial="0000000005")

    @wait_for_reactor
    @inlineCallbacks
    def test_tryUpdate_skips_dns_update_all_zones_when_serial_is_up_to_date(
        self, tmp_path, monkeypatch, mocker
    ):
        service = dns.DNSReloadService(Clock())
        zone_file_dir = str(tmp_path)
        monkeypatch.setenv("MAAS_ZONE_FILE_CONFIG_DIR", zone_file_dir)
        yield deferToDatabase(
            Config.objects.set_config, "maas_internal_domain", "maas-internal"
        )
        yield deferToDatabase(DNSPublication.objects.create, serial=4)
        with open(zone_file_dir + "/zone.maas-internal", "w") as f:
            f.write(MAAS_INTERNAL_ZONE)

        dns_update_all_zones_mock = mocker.patch.object(
            dns, "dns_update_all_zones"
        )
        yield service._tryUpdate()
        dns_update_all_zones_mock.assert_not_called()

    @wait_for_reactor
    @inlineCallbacks
    def test_tryUpdate_calls_dns_update_when_no_serial_is_found(
        self, tmp_path, monkeypatch, mocker
    ):
        service = dns.DNSReloadService(Clock())
        zone_file_dir = str(tmp_path)
        monkeypatch.setenv("MAAS_ZONE_FILE_CONFIG_DIR", zone_file_dir)
        yield deferToDatabase(
            Config.objects.set_config, "maas_internal_domain", "maas-internal"
        )
        with open(zone_file_dir + "/zone.maas-internal", "w") as f:
            f.write("definitely not a valid zone")

        dns_update_all_zones_mock = mocker.patch.object(
            dns, "dns_update_all_zones"
        )
        yield service._tryUpdate()
        dns_update_all_zones_mock.assert_called_once_with()
