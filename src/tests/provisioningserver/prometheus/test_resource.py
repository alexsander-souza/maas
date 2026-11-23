from unittest.mock import MagicMock

import prometheus_client
import pytest
from twisted.web.server import Request
from twisted.web.test.test_web import DummyChannel

from provisioningserver.prometheus.utils import (
    create_metrics,
    MetricDefinition,
)
from provisioningserver.rackdservices import http


class TestPrometheusMetricsResource:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.metrics_definitions = [
            MetricDefinition(
                "Histogram", "sample_histogram", "Sample histogram", []
            ),
            MetricDefinition(
                "Counter", "sample_counter", "Sample counter", []
            ),
        ]

    def test_metrics(self):
        prometheus_metrics = create_metrics(
            self.metrics_definitions,
            registry=prometheus_client.CollectorRegistry(),
        )
        resource = http.PrometheusMetricsResource(prometheus_metrics)
        request = Request(DummyChannel(), False)
        content = resource.render_GET(request).decode("utf-8")
        assert request.code == 200
        assert "TYPE sample_histogram histogram" in content
        assert "TYPE sample_counter_total counter" in content

    def test_metrics_disabled(self):
        prometheus_metrics = create_metrics(
            None, registry=prometheus_client.CollectorRegistry()
        )
        resource = http.PrometheusMetricsResource(prometheus_metrics)
        request = Request(DummyChannel(), False)
        content = resource.render_GET(request).decode("utf-8")
        assert request.code == 404
        assert content == ""

    def test_content_type(self):
        prometheus_metrics = create_metrics(
            None, registry=prometheus_client.CollectorRegistry()
        )
        resource = http.PrometheusMetricsResource(prometheus_metrics)
        request = MagicMock()
        resource.render_GET(request)
        request.setHeader.assert_called_with(b"Content-Type", b"text/plain")
