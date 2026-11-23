# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from collections import defaultdict
import http.client
import json
import random

from django.urls import reverse
import pytest

from maasserver.models import Config
from maasserver.prometheus.service import (
    PrometheusDiscoveryResource,
    RACK_PROMETHEUS_PORT,
    REGION_PROMETHEUS_PORT,
)
from maasserver.testing.factory import factory
from maasserver.testing.testclient import MAASSensibleClient


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestPrometheusDiscoveryResource:
    @pytest.fixture(autouse=True)
    def _setup_client(self):
        self.client = MAASSensibleClient()

    def test_prometheus_discover_not_found_when_disabled(self):
        Config.objects.set_config("prometheus_enabled", False)
        response = self.client.get(reverse("metrics_endpoints"))
        assert response["Content-Type"] == "text/html; charset=utf-8"
        assert response.status_code == http.client.NOT_FOUND

    def test_prometheus_discovery_separate_controllers(self):
        Config.objects.set_config("prometheus_enabled", True)
        subnet = factory.make_Subnet()
        region_controller = self._make_controller(
            factory.make_RegionController
        )
        factory.make_Interface(
            node=region_controller,
            subnet=subnet,
            ip=subnet.get_next_ip_for_allocation()[0],
        )
        rack_controller = self._make_controller(factory.make_RackController)
        factory.make_Interface(
            node=rack_controller,
            subnet=subnet,
            ip=subnet.get_next_ip_for_allocation()[0],
        )
        discovery_response = self.client.get(reverse("metrics_endpoints"))
        discovered = json.loads(discovery_response.content)
        expected = [
            {
                "targets": [
                    ip + ":" + str(REGION_PROMETHEUS_PORT)
                    for ip in region_controller.ip_addresses()
                ],
                "labels": {
                    "__meta_prometheus_job": "maas",
                    "maas_az": region_controller.zone.name,
                    "maas_region": "True",
                    "maas_rack": "False",
                },
            },
            {
                "targets": [
                    ip + ":" + str(RACK_PROMETHEUS_PORT)
                    for ip in rack_controller.ip_addresses()
                ],
                "labels": {
                    "__meta_prometheus_job": "maas",
                    "maas_az": rack_controller.zone.name,
                    "maas_region": "False",
                    "maas_rack": "True",
                },
            },
        ]
        assert sorted(
            json.dumps(item, sort_keys=True) for item in expected
        ) == sorted(json.dumps(item, sort_keys=True) for item in discovered)

    def test_prometheus_discovery_region_rack_controller(self):
        Config.objects.set_config("prometheus_enabled", True)
        subnet = factory.make_Subnet()
        region_rack_controller = self._make_controller(
            factory.make_RegionRackController
        )
        factory.make_Interface(
            node=region_rack_controller,
            subnet=subnet,
            ip=subnet.get_next_ip_for_allocation()[0],
        )
        rack_controller = self._make_controller(factory.make_RackController)
        factory.make_Interface(
            node=rack_controller,
            subnet=subnet,
            ip=subnet.get_next_ip_for_allocation()[0],
        )
        discovery_response = self.client.get(reverse("metrics_endpoints"))
        discovered = json.loads(discovery_response.content)
        expected = [
            {
                "targets": [
                    ip + ":" + str(REGION_PROMETHEUS_PORT)
                    for ip in region_rack_controller.ip_addresses()
                ],
                "labels": {
                    "__meta_prometheus_job": "maas",
                    "maas_az": region_rack_controller.zone.name,
                    "maas_region": "True",
                    "maas_rack": "True",
                },
            },
            {
                "targets": [
                    ip + ":" + str(RACK_PROMETHEUS_PORT)
                    for ip in rack_controller.ip_addresses()
                ],
                "labels": {
                    "__meta_prometheus_job": "maas",
                    "maas_az": rack_controller.zone.name,
                    "maas_region": "False",
                    "maas_rack": "True",
                },
            },
        ]
        assert sorted(
            json.dumps(item, sort_keys=True) for item in expected
        ) == sorted(json.dumps(item, sort_keys=True) for item in discovered)

    def _make_controller(self, controller_factory, **kwargs):
        power_parameters = {
            "power_address": (
                f"qemu+ssh://user@{factory.make_ipv4_address()}/system"
            )
        }
        return controller_factory(
            owner=factory.make_User(),
            power_type="virsh",
            power_parameters=power_parameters,
            **kwargs,
        )

    def _test_format(self, controller_factory, is_region, is_rack):
        expected = []
        bucketed_controllers = defaultdict(set)
        discovery_resource = PrometheusDiscoveryResource()
        for _ in range(3):
            zone = factory.make_Zone()
            subnet = factory.make_Subnet()
            for _ in range(3):
                controller = self._make_controller(controller_factory)
                factory.make_Interface(
                    node=controller,
                    subnet=subnet,
                    ip=subnet.get_next_ip_for_allocation()[0],
                )
                bucketed_controllers[
                    (
                        zone.name,
                        controller.is_region_controller,
                        controller.is_rack_controller,
                    )
                ].add(controller)
            instances = [
                ip
                + ":"
                + str(
                    REGION_PROMETHEUS_PORT
                    if is_region
                    else RACK_PROMETHEUS_PORT
                )
                for controller in bucketed_controllers[
                    (
                        zone.name,
                        controller.is_region_controller,
                        controller.is_rack_controller,
                    )
                ]
                for ip in controller.ip_addresses()
            ]
            if instances:
                expected.append(
                    {
                        "targets": instances,
                        "labels": {
                            "__meta_prometheus_job": "maas",
                            "maas_az": zone.name,
                            "maas_region": str(is_region),
                            "maas_rack": str(is_rack),
                        },
                    }
                )
        formated = discovery_resource._format(bucketed_controllers)
        assert sorted(
            json.dumps(item, sort_keys=True) for item in expected
        ) == sorted(json.dumps(item, sort_keys=True) for item in formated)

    def test_format_region_controllers(self):
        self._test_format(factory.make_RegionController, True, False)

    def test_format_rack_controllers(self):
        self._test_format(factory.make_RackController, False, True)

    def test_format_region_rack_controllers(self):
        self._test_format(factory.make_RegionRackController, True, True)

    def test_group_controllers_by_az(self):
        zones = [factory.make_Zone() for _ in range(3)]
        controllers = []
        expected = defaultdict(set)
        for zone in zones:
            for _ in range(3):
                fact = random.choice(
                    [
                        factory.make_RegionController,
                        factory.make_RackController,
                        factory.make_RegionRackController,
                    ]
                )
                controller = self._make_controller(fact, zone=zone)
                expected[
                    (
                        zone.name,
                        controller.is_region_controller,
                        controller.is_rack_controller,
                    )
                ].add(controller)
                controllers.append(controller)
        discovery_resource = PrometheusDiscoveryResource()
        buckets = discovery_resource._group_controllers_by_az(controllers)
        assert expected == buckets
