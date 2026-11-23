#  Copyright 2026 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for NGINX template hardening conditionals (rack).

The rack HTTP server never requires TLS: rack clients (enlisting/commissioning
machines, bootloaders) cannot be assumed to support it. Hardening only adds
security response headers, rate limiting is applied regardless of hardening,
and binding is driven by the merged api_bind key.
"""

import tempita

from provisioningserver.rackdservices.http import compose_listen_addresses
from provisioningserver.utils import locate_template


def _render(extra: dict | None = None) -> str:
    """Render the rackd.nginx.conf template with base vars plus extras."""
    base = {
        "upstream_http": [],
        "machine_resources": "/usr/share/maas",
        "maas_rack_controller_httpproxy_socket_path": "/run/maas/httpproxy.sock",
        "maas_rack_controller_http_socket_path": "/run/maas/rack-controller-http.sock",
        "boot_resources_dir": "/var/lib/maas/image-storage",
        "hardening": False,
        "api_upstream_port": 5240,
        "api_rate_limit_rate": "10r/s",
        "api_rate_limit_burst": 20,
        "api_conn_limit": 100,
    }
    if extra:
        base.update(extra)
    api_bind = base.pop("api_bind", [])
    if isinstance(api_bind, str):
        api_bind = [api_bind] if api_bind else []
    base["api_listen"] = compose_listen_addresses(5248, api_bind)
    tpl = tempita.Template.from_filename(
        locate_template("http", "rackd.nginx.conf.template"),
        encoding="UTF-8",
    )
    return tpl.substitute(base)


HARDENING_VARS = {
    "hardening": True,
    "api_bind": "10.0.0.5",
    "api_rate_limit_rate": "10r/s",
    "api_rate_limit_burst": 20,
    "api_conn_limit": 100,
}

# Same as HARDENING_VARS but with wildcard binding (empty api_bind),
# producing listen [::]:5248 + listen 5248 instead of a specific address.
HARDENING_VARS_WILDCARD = {**HARDENING_VARS, "api_bind": ""}


class TestNginxTemplateNeverTLS:
    """The rack server is plain HTTP on 5248 in every mode."""

    def test_listen_on_5248_without_hardening(self):
        rendered = _render()
        assert "listen [::]:5248;" in rendered
        assert "listen 5248;" in rendered

    def test_no_ssl_directives_without_hardening(self):
        rendered = _render()
        assert "ssl_protocols" not in rendered
        assert "ssl_certificate" not in rendered

    def test_no_ssl_directives_with_hardening(self):
        rendered = _render(HARDENING_VARS)
        assert "ssl_protocols" not in rendered
        assert "ssl_certificate" not in rendered
        assert " ssl;" not in rendered
        assert "Strict-Transport-Security" not in rendered


class TestNginxTemplateBinding:
    """Binding is driven by the merged api_bind key."""

    def test_wildcard_when_no_bind(self):
        rendered = _render({"api_bind": ""})
        assert "listen [::]:5248;" in rendered
        assert "listen 5248;" in rendered

    def test_ipv4_bind_only(self):
        rendered = _render({"api_bind": "10.0.0.5"})
        assert "listen 10.0.0.5:5248;" in rendered
        assert "listen 5248;" not in rendered
        assert "listen [::]:5248;" not in rendered

    def test_ipv6_bind_only(self):
        rendered = _render({"api_bind": "fd00::5"})
        assert "listen [fd00::5]:5248;" in rendered
        assert "listen 5248;" not in rendered
        assert "listen [::]:5248;" not in rendered

    def test_dual_stack_bind(self):
        rendered = _render({"api_bind": ["10.0.0.5", "fd00::5"]})
        assert "listen 10.0.0.5:5248;" in rendered
        assert "listen [fd00::5]:5248;" in rendered


class TestNginxTemplateUpstreamPort:
    """The upstream region API port is configurable, default 5240."""

    def test_default_upstream_port(self):
        rendered = _render({"upstream_http": ["10.0.0.1"]})
        assert "server 10.0.0.1:5240;" in rendered

    def test_custom_upstream_port(self):
        rendered = _render(
            {"upstream_http": ["10.0.0.1"], "api_upstream_port": 6240}
        )
        assert "server 10.0.0.1:6240;" in rendered


class TestNginxTemplateRateLimiting:
    """Rate/burst/conn limits apply with defaults regardless of hardening."""

    def test_rate_limit_zone_present_without_hardening(self):
        rendered = _render(
            {
                "api_rate_limit_rate": "5r/s",
                "api_rate_limit_burst": 10,
                "api_conn_limit": 50,
            }
        )
        assert (
            "limit_req_zone $binary_remote_addr zone=api_rate:10m rate=5r/s;"
            in rendered
        )
        assert (
            "limit_conn_zone $binary_remote_addr zone=api_conn:10m;"
            in rendered
        )

    def test_rate_limit_applied_with_and_without_hardening(self):
        for extra in (None, HARDENING_VARS):
            rendered = _render(extra)
            assert "limit_req zone=api_rate burst=20 nodelay;" in rendered

            assert "limit_conn api_conn 100;" in rendered

    def test_no_rate_limit_zone_when_rate_empty(self):
        # api_rate_limit_burst and api_conn_limit are only interpolated inside
        # the {{if api_rate_limit_rate}} block, so they are not required here.
        rendered = _render({"api_rate_limit_rate": ""})
        assert "limit_req_zone" not in rendered
        assert "limit_conn_zone" not in rendered


class TestNginxTemplateSecurityHeaders:
    """Security headers are added only when hardening is active."""

    def test_no_security_headers_without_hardening(self):
        rendered = _render()
        assert "X-Frame-Options" not in rendered
        assert "Content-Security-Policy" not in rendered
        assert "server_tokens off;" not in rendered

    def test_security_headers_with_hardening(self):
        rendered = _render(HARDENING_VARS)
        assert "server_tokens off;" in rendered
        assert 'add_header X-Frame-Options "DENY" always;' in rendered
        assert (
            'add_header X-Content-Type-Options "nosniff" always;' in rendered
        )
        assert (
            'add_header Referrer-Policy "strict-origin-when-cross-origin" always;'
            in rendered
        )
        assert (
            'add_header X-XSS-Protection "1; mode=block" always;' in rendered
        )

    def test_content_security_policy_with_hardening(self):
        rendered = _render(HARDENING_VARS)
        assert (
            "add_header Content-Security-Policy"
            " \"default-src 'none'; frame-ancestors 'none'\" always;"
            in rendered
        )

    def test_trace_and_options_blocked_with_444(self):
        rendered = _render(HARDENING_VARS)
        assert "return 444;" in rendered
        assert "TRACE" in rendered
        assert "OPTIONS" in rendered

    def test_no_trace_block_without_hardening(self):
        rendered = _render()
        assert "return 444;" not in rendered


class TestNginxTemplateLocations:
    """Location blocks are unaffected by hardening."""

    def test_location_blocks_present_regardless_of_hardening(self):
        for extra in (None, HARDENING_VARS):
            rendered = _render(extra)
            assert "location /machine-resources/" in rendered
            # The rackd metadata/boot HTTP service (port 5249) binds to
            # ::1 only (see `ProvisioningServiceMaker._makeHTTPService`),
            # so nginx must dial it there rather than via "localhost".
            assert "proxy_pass http://[::1]:5249/boot/;" in rendered
