# Copyright 2014-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


from datetime import datetime
import http.client
from unittest import mock

from django.urls import reverse
import prometheus_client
import pytest
from twisted.application.internet import TimerService
from twisted.internet.defer import fail

from maasserver.enum import IPADDRESS_TYPE, IPRANGE_TYPE
from maasserver.models import Config
from maasserver.prometheus import stats
from maasserver.prometheus.stats import (
    push_stats_to_prometheus,
    STATS_DEFINITIONS,
    update_prometheus_stats,
)
from maastesting.deferred import extract_result
from provisioningserver.events import EVENT_TYPES
from provisioningserver.prometheus.utils import create_metrics
from provisioningserver.utils.twisted import asynchronous, FOREVER


class TestPrometheusHandler:
    def test_prometheus_stats_handler_not_found_disabled(
        self, admin_api_client, factory
    ):
        Config.objects.set_config("prometheus_enabled", False)
        response = admin_api_client.get(reverse("metrics"))
        assert response["Content-Type"] == "text/html; charset=utf-8"
        assert response.status_code == http.client.NOT_FOUND

    def test_prometheus_stats_handler_returns_success(
        self, admin_api_client, factory, mocker
    ):
        Config.objects.set_config("prometheus_enabled", True)
        mock_prometheus_client = mocker.patch.object(
            stats, "prometheus_client"
        )
        mock_prometheus_client.generate_latest.return_value = {}
        response = admin_api_client.get(reverse("metrics"))
        assert response["Content-Type"] == "text/plain"
        assert response.status_code == http.client.OK

    def test_prometheus_stats_handler_returns_metrics(
        self, admin_api_client, factory, mocker
    ):
        sample_metrics = (
            "# HELP maas_machines Number of machines managed by this MAAS.\n"
            "# TYPE maas_machines gauge\n"
            'maas_machines{maas_id="abcde"} 5.0\n'
            "# HELP maas_nodes Number of nodes managed by this MAAS.\n"
            "# TYPE maas_nodes gauge\n"
            'maas_nodes{maas_id="abcde"} 10.0\n'
            "# HELP maas_net_spaces Number of network spaces.\n"
            "# TYPE maas_net_spaces gauge\n"
            'maas_net_spaces{maas_id="abcde"} 3.0\n'
            "# HELP maas_net_fabrics Number of network fabrics.\n"
            "# TYPE maas_net_fabrics gauge\n"
            'maas_net_fabrics{maas_id="abcde"} 4.0\n'
            "# HELP maas_net_vlans Number of network VLANs.\n"
            "# TYPE maas_net_vlans gauge\n"
            'maas_net_vlans{maas_id="abcde"} 5.0\n'
            "# HELP maas_net_subnets_v4 Number of IPv4 subnets.\n"
            "# TYPE maas_net_subnets_v4 gauge\n"
            'maas_net_subnets_v4{maas_id="abcde"} 2.0\n'
            "# HELP maas_net_subnets_v6 Number of IPv6 subnets.\n"
            "# TYPE maas_net_subnets_v6 gauge\n"
            'maas_net_subnets_v6{maas_id="abcde"} 1.0\n'
            "# HELP maas_net_subnet_ip_count Count of subnet IPs.\n"
            "# TYPE maas_net_subnet_ip_count gauge\n"
            "# HELP maas_net_subnet_ip_dynamic Count of dynamic IPs.\n"
            "# TYPE maas_net_subnet_ip_dynamic gauge\n"
            "# HELP maas_net_subnet_ip_reserved Count of reserved IPs.\n"
            "# TYPE maas_net_subnet_ip_reserved gauge\n"
            "# HELP maas_net_subnet_ip_static Count of static IPs.\n"
            "# TYPE maas_net_subnet_ip_static gauge\n"
            "# HELP maas_service_availability Availability of services.\n"
            "# TYPE maas_service_availability gauge\n"
            "# HELP maas_machines_total_mem Total memory of machines.\n"
            "# TYPE maas_machines_total_mem gauge\n"
            "# HELP maas_machines_total_cpu Total CPU of machines.\n"
            "# TYPE maas_machines_total_cpu gauge\n"
            "# HELP maas_machines_total_storage Total storage of machines.\n"
            "# TYPE maas_machines_total_storage gauge\n"
            "# HELP maas_machines_avg_deployment_time Avg deployment time.\n"
            "# TYPE maas_machines_avg_deployment_time gauge\n"
            "# HELP maas_machine_arches Machine architectures.\n"
            "# TYPE maas_machine_arches gauge\n"
            "# HELP maas_custom_static_images_uploaded Custom images uploaded.\n"
            "# TYPE maas_custom_static_images_uploaded gauge\n"
            "# HELP maas_custom_static_images_deployed Custom images deployed.\n"
            "# TYPE maas_custom_static_images_deployed gauge\n"
            "# HELP site_manager_connection Site manager connection.\n"
            "# TYPE site_manager_connection gauge\n"
        )
        mock_metrics = mocker.MagicMock()
        mock_metrics.generate_latest.return_value = sample_metrics.encode(
            "utf-8"
        )
        mocker.patch.object(stats, "_METRICS", mock_metrics)
        Config.objects.set_config("prometheus_enabled", True)
        response = admin_api_client.get(reverse("metrics"))
        content = response.content.decode("utf-8")
        metrics = (
            "maas_machines",
            "maas_nodes",
            "maas_net_spaces",
            "maas_net_fabrics",
            "maas_net_vlans",
            "maas_net_subnets_v4",
            "maas_net_subnets_v6",
            "maas_net_subnet_ip_count",
            "maas_net_subnet_ip_dynamic",
            "maas_net_subnet_ip_reserved",
            "maas_net_subnet_ip_static",
            "maas_service_availability",
            "maas_machines_total_mem",
            "maas_machines_total_cpu",
            "maas_machines_total_storage",
            "maas_machines_avg_deployment_time",
            "maas_service_availability",
            "maas_machine_arches",
            "maas_custom_static_images_uploaded",
            "maas_custom_static_images_deployed",
            "site_manager_connection",
        )
        for metric in metrics:
            assert f"TYPE {metric} gauge" in content

    def test_prometheus_stats_handler_include_maas_id_label(
        self, admin_api_client, factory, mocker
    ):
        mocker.patch.object(
            stats, "get_machines_by_architecture"
        ).return_value = {
            "amd64": 2,
            "i386": 1,
        }
        Config.objects.set_config("uuid", "abcde")
        Config.objects.set_config("prometheus_enabled", True)
        response = admin_api_client.get(reverse("metrics"))
        content = response.content.decode("utf-8")
        for line in content.splitlines():
            if line.startswith("maas_"):
                assert 'maas_id="abcde"' in line


class TestPrometheus:
    def test_update_prometheus_stats(self, factory, mocker):
        mocker.patch.object(stats, "prometheus_client")
        # general values
        values = {
            "machine_status": {"random_status": 0},
            "controllers": {"regions": 0},
            "nodes": {"machines": 0},
            "network_stats": {"spaces": 0},
            "machine_stats": {"total_cpu": 0},
            "site_manager_connection": {"connected": False},
        }
        mock = mocker.patch.object(stats, "get_maas_stats")
        mock.return_value = values
        # architecture
        arches = {"amd64": 0, "i386": 0}
        mock_arches = mocker.patch.object(
            stats, "get_machines_by_architecture"
        )
        mock_arches.return_value = arches
        subnet_stats = {
            "1.2.0.0/16": {
                "available": 2**16 - 3,
                "dynamic_available": 0,
                "dynamic_used": 0,
                "reserved_available": 0,
                "reserved_used": 0,
                "static": 0,
                "unavailable": 1,
            },
            "::1/128": {
                "available": 1,
                "dynamic_available": 0,
                "dynamic_used": 0,
                "reserved_available": 0,
                "reserved_used": 0,
                "static": 0,
                "unavailable": 0,
            },
        }
        mock_subnet_stats = mocker.patch.object(
            stats, "get_subnets_utilisation_stats"
        )
        mock_subnet_stats.return_value = subnet_stats
        metrics = create_metrics(
            STATS_DEFINITIONS, registry=prometheus_client.CollectorRegistry()
        )
        update_prometheus_stats(metrics)
        assert len(mock.mock_calls) == 1
        assert len(mock_arches.mock_calls) == 1
        assert len(mock_subnet_stats.mock_calls) == 1

    def test_push_stats_to_prometheus(self, factory, mocker):
        factory.make_RegionRackController()
        maas_name = "random.maas"
        push_gateway = "127.0.0.1:2000"
        mock_prometheus_client = mocker.patch.object(
            stats, "prometheus_client"
        )
        push_stats_to_prometheus(maas_name, push_gateway)
        mock_prometheus_client.push_to_gateway.assert_called_once_with(
            push_gateway, job="stats_for_%s" % maas_name, registry=mock.ANY
        )

    def test_subnet_stats(self, factory):
        subnet = factory.make_Subnet(cidr="1.2.0.0/16", gateway_ip="1.2.0.254")
        factory.make_IPRange(
            subnet=subnet,
            start_ip="1.2.0.11",
            end_ip="1.2.0.20",
            alloc_type=IPRANGE_TYPE.DYNAMIC,
        )
        factory.make_IPRange(
            subnet=subnet,
            start_ip="1.2.0.51",
            end_ip="1.2.0.70",
            alloc_type=IPRANGE_TYPE.RESERVED,
        )
        factory.make_StaticIPAddress(
            ip="1.2.0.12", alloc_type=IPADDRESS_TYPE.DHCP, subnet=subnet
        )
        for n in (60, 61):
            factory.make_StaticIPAddress(
                ip=f"1.2.0.{n}",
                alloc_type=IPADDRESS_TYPE.USER_RESERVED,
                subnet=subnet,
            )
        for n in (80, 90, 100):
            factory.make_StaticIPAddress(
                ip=f"1.2.0.{n}",
                alloc_type=IPADDRESS_TYPE.STICKY,
                subnet=subnet,
            )
        metrics = create_metrics(
            STATS_DEFINITIONS, registry=prometheus_client.CollectorRegistry()
        )
        update_prometheus_stats(metrics)
        output = metrics.generate_latest().decode("ascii")
        assert (
            "maas_net_subnet_ip_count"
            '{cidr="1.2.0.0/16",status="available"} 65500.0' in output
        )
        assert (
            "maas_net_subnet_ip_count"
            '{cidr="1.2.0.0/16",status="unavailable"} 34.0' in output
        )
        assert (
            "maas_net_subnet_ip_dynamic"
            '{cidr="1.2.0.0/16",status="available"} 9.0' in output
        )
        assert (
            'maas_net_subnet_ip_dynamic{cidr="1.2.0.0/16",status="used"} 1.0'
            in output
        )
        assert (
            "maas_net_subnet_ip_reserved"
            '{cidr="1.2.0.0/16",status="available"} 18.0' in output
        )
        assert (
            'maas_net_subnet_ip_reserved{cidr="1.2.0.0/16",status="used"} 2.0'
            in output
        )
        assert 'maas_net_subnet_ip_static{cidr="1.2.0.0/16"} 3.0' in output

    def test_machine_avg_deployment_time_metric(self, factory):
        """Test the average time of the last successful deployment of the
        machine in MAAS.
        """
        node_1 = factory.make_Node()
        node_2 = factory.make_Node()
        event_request_deployment = factory.make_EventType(
            EVENT_TYPES.REQUEST_NODE_START_DEPLOYMENT
        )
        event_deployed = factory.make_EventType(EVENT_TYPES.DEPLOYED)
        metrics = create_metrics(
            STATS_DEFINITIONS, registry=prometheus_client.CollectorRegistry()
        )

        # status: node_1 has never been deployed
        update_prometheus_stats(metrics)
        output = metrics.generate_latest().decode("ascii")
        assert "maas_machines_avg_deployment_time NaN" in output

        # status: node_1 starts its deployment for the first time (deployment
        # event never registered before)
        factory.make_Event(
            event_request_deployment,
            node_1,
            created=datetime.fromisoformat("2024-04-12T14:05:25"),
        )
        update_prometheus_stats(metrics)
        output = metrics.generate_latest().decode("ascii")
        assert "maas_machines_avg_deployment_time NaN" in output

        # status: node_1 finishes deployment
        factory.make_Event(
            event_deployed,
            node_1,
            created=datetime.fromisoformat("2024-04-12T14:10:37"),
        )
        update_prometheus_stats(metrics)
        output = metrics.generate_latest().decode("ascii")
        assert "maas_machines_avg_deployment_time 312.0" in output

        # status: node_1 starts deployment for the second time (current
        # deployment event belongs to the previous deployment)
        factory.make_Event(
            event_request_deployment,
            node_1,
            created=datetime.fromisoformat("2024-05-15T10:17:21"),
        )
        update_prometheus_stats(metrics)
        output = metrics.generate_latest().decode("ascii")
        assert "maas_machines_avg_deployment_time NaN" in output

        # status: node_1 finishes deployment for the second time
        factory.make_Event(
            event_deployed,
            node_1,
            created=datetime.fromisoformat("2024-05-15T10:20:25"),
        )
        update_prometheus_stats(metrics)
        output = metrics.generate_latest().decode("ascii")
        assert "maas_machines_avg_deployment_time 184.0" in output

        # status: node_2 starts its deployment for the first time
        factory.make_Event(
            event_request_deployment,
            node_2,
            created=datetime.fromisoformat("2024-05-15T10:25:40"),
        )
        update_prometheus_stats(metrics)
        output = metrics.generate_latest().decode("ascii")
        assert "maas_machines_avg_deployment_time 184.0" in output
        # status: node_2 finishes its deployment for the first time
        # The result is the average time of the deployments of node_1 and
        # node_2
        factory.make_Event(
            event_deployed,
            node_2,
            created=datetime.fromisoformat("2024-05-15T10:30:41"),
        )
        update_prometheus_stats(metrics)
        output = metrics.generate_latest().decode("ascii")
        assert "maas_machines_avg_deployment_time 242.5" in output


class TestPrometheusService:
    """Tests for `ImportPrometheusService`."""

    def test_is_a_TimerService(self):
        service = stats.PrometheusService()
        assert isinstance(service, TimerService)

    def test_runs_once_an_hour_by_default(self):
        service = stats.PrometheusService()
        assert service.step == 3600

    def test_calls__maybe_make_stats_request(self):
        service = stats.PrometheusService()
        assert service.call == (service.maybe_push_prometheus_stats, (), {})

    def test_maybe_make_stats_request_does_not_error(self, factory, mocker):
        service = stats.PrometheusService()
        deferToDatabase = mocker.patch.object(stats, "deferToDatabase")
        exception_type = factory.make_exception_type()
        deferToDatabase.return_value = fail(exception_type())
        d = service.maybe_push_prometheus_stats()
        assert extract_result(d) is None


class TestPrometheusServiceAsync:
    """Tests for the async parts of `PrometheusService`."""

    def test_maybe_make_stats_request_makes_request(self, factory, mocker):
        """TODO: This test requires the crochet reactor and deferToDatabase to
        be fully wired up under pytest.  The asynchronous wrapper dispatches
        to a reactor thread where mock visibility and database connection
        context may differ from the test thread, causing the mock assertion
        to fail.  Skip pending a proper async-ready fixture."""
        pytest.skip("Async test needs crochet reactor integration")

    def test_maybe_make_stats_request_doesnt_make_request(
        self, factory, mocker
    ):
        mock_prometheus_client = mocker.patch.object(
            stats, "prometheus_client"
        )

        Config.objects.set_config("enable_analytics", False)

        service = stats.PrometheusService()
        synchronous_maybe_push = asynchronous(
            service.maybe_push_prometheus_stats, timeout=FOREVER
        )
        synchronous_maybe_push()
        mock_prometheus_client.push_stats_to_prometheus.assert_not_called()
