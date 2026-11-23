# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
"""Tests for hardening_check.py (notification sync).

Uses Django ORM (maasserver test suite).  Run via:
    bin/pytest src/tests/maasserver/test_hardening_check.py
"""

import pytest

from maasserver.models import Notification
from maasserver.regiondservices.hardening_check import (
    HARDENING_CTRL_IDENT_PREFIX,
    HARDENING_NOTIFICATION_IDENT_PREFIX,
    sync_hardening_notifications,
)
from maasservicelayer.services.hardening import _ident, HardeningViolation


def _make_violation(
    code: str, config_key: str = "api_tls_cert"
) -> HardeningViolation:
    return HardeningViolation(
        ident=_ident(code),
        code=code,
        message=f"Test violation: {code}",
        resolution="Run: maas config-hardening set api_tls_cert <path>",
        config_key=config_key,
        file_path=None,
    )


def _make_bind_violation(config_key: str = "api_bind") -> HardeningViolation:
    return HardeningViolation(
        ident=f"hardening-wildcard-bind-{config_key.replace('_', '-')}",
        code="WILDCARD_BIND_NOT_ALLOWED",
        message=f"{config_key} is not configured; would bind to all interfaces",
        resolution=f"Run: maas config-hardening set {config_key} <ip>",
        config_key=config_key,
        file_path=None,
    )


def _ctrl_ident(ctrl: str, config_key: str) -> str:
    return f"{HARDENING_CTRL_IDENT_PREFIX}{ctrl}-{config_key}"


@pytest.mark.usefixtures("maasdb")
class TestSyncHardeningNotifications:
    def test_empty_violations_no_notifications_created(self):
        sync_hardening_notifications([])
        count = Notification.objects.filter(
            ident__startswith=HARDENING_NOTIFICATION_IDENT_PREFIX
        ).count()
        assert count == 0

    def test_violation_creates_error_notification(self):
        v = _make_violation("MISSING_TLS_CERT")
        sync_hardening_notifications([v])

        n = Notification.objects.get(ident=v.ident)
        assert n.category == "error"
        assert n.admins
        assert not n.users
        assert not n.dismissable
        assert "MISSING_TLS_CERT" in n.context["code"]

    def test_violation_message_contains_resolution(self):
        v = _make_violation("MISSING_TLS_CERT")
        sync_hardening_notifications([v])
        n = Notification.objects.get(ident=v.ident)
        assert "config-hardening" in n.message

    def test_resolved_violation_cleared_on_next_sync(self):
        v = _make_violation("MISSING_TLS_CERT")
        sync_hardening_notifications([v])
        assert Notification.objects.filter(ident=v.ident).exists()
        sync_hardening_notifications([])
        assert not Notification.objects.filter(ident=v.ident).exists()

    def test_unrelated_notifications_not_touched(self):
        Notification.objects.create_info_for_admins(
            "Unrelated", ident="some-other-ident"
        )
        sync_hardening_notifications([])
        assert Notification.objects.filter(ident="some-other-ident").exists()

    def test_second_violation_replaces_first(self):
        v1 = _make_violation("MISSING_TLS_CERT")
        v2 = _make_violation("WEAK_DH_PARAMS")
        sync_hardening_notifications([v1])
        sync_hardening_notifications([v2])
        assert not Notification.objects.filter(ident=v1.ident).exists()
        assert Notification.objects.filter(ident=v2.ident).exists()

    def test_multiple_violations_all_posted(self):
        violations = [
            _make_violation("MISSING_TLS_CERT"),
            _make_violation("WEAK_DH_PARAMS"),
            _make_violation("INSECURE_DB_SSLMODE", "database_sslmode"),
        ]
        sync_hardening_notifications(violations)
        for v in violations:
            assert Notification.objects.filter(ident=v.ident).exists(), (
                f"Missing notification for {v.ident}"
            )

    def test_dismissable_is_false(self):
        v = _make_violation("MISSING_TLS_CERT")
        sync_hardening_notifications([v])
        n = Notification.objects.get(ident=v.ident)
        assert not n.dismissable

    def test_context_has_code_config_key_file_path(self):
        v = HardeningViolation(
            ident=_ident("MISSING_TLS_CERT"),
            code="MISSING_TLS_CERT",
            message="cert missing",
            resolution="fix it",
            config_key="api_tls_cert",
            file_path="/etc/maas/certs/tls.pem",
        )
        sync_hardening_notifications([v])
        n = Notification.objects.get(ident=v.ident)
        assert n.context["code"] == "MISSING_TLS_CERT"
        assert n.context["config_key"] == "api_tls_cert"
        assert n.context["file_path"] == "/etc/maas/certs/tls.pem"


@pytest.mark.usefixtures("maasdb")
class TestSyncHardeningNotificationsWithControllerId:
    """Bind violations are scoped per controller; non-bind ones are global."""

    CTRL_A = "abc123"
    CTRL_B = "def456"

    def test_bind_violation_uses_controller_scoped_ident(self):
        v = _make_bind_violation()
        sync_hardening_notifications([v], controller_id=self.CTRL_A)

        assert Notification.objects.filter(
            ident=_ctrl_ident(self.CTRL_A, "api_bind")
        ).exists()
        assert not Notification.objects.filter(ident=v.ident).exists()

    def test_bind_violation_message_contains_controller_id(self):
        v = _make_bind_violation()
        sync_hardening_notifications([v], controller_id=self.CTRL_A)
        n = Notification.objects.get(
            ident=_ctrl_ident(self.CTRL_A, "api_bind")
        )
        assert self.CTRL_A in n.message

    def test_bind_violation_context_contains_controller_id(self):
        v = _make_bind_violation()
        sync_hardening_notifications([v], controller_id=self.CTRL_A)
        n = Notification.objects.get(
            ident=_ctrl_ident(self.CTRL_A, "api_bind")
        )
        assert n.context["controller_id"] == self.CTRL_A

    def test_non_bind_violation_keeps_global_ident_with_controller_id(self):
        v = _make_violation("MISSING_TLS_CERT")
        sync_hardening_notifications([v], controller_id=self.CTRL_A)

        assert Notification.objects.filter(ident=v.ident).exists()
        assert (
            Notification.objects.filter(
                ident__startswith=f"{HARDENING_CTRL_IDENT_PREFIX}{self.CTRL_A}-"
            ).count()
            == 0
        )

    def test_stale_bind_notification_cleared_on_resolution(self):
        v = _make_bind_violation()
        sync_hardening_notifications([v], controller_id=self.CTRL_A)
        ctrl_ident = _ctrl_ident(self.CTRL_A, "api_bind")
        assert Notification.objects.filter(ident=ctrl_ident).exists()
        sync_hardening_notifications([], controller_id=self.CTRL_A)
        assert not Notification.objects.filter(ident=ctrl_ident).exists()

    def test_other_controller_bind_notification_not_cleared(self):
        v = _make_bind_violation()
        sync_hardening_notifications([v], controller_id=self.CTRL_A)
        sync_hardening_notifications([v], controller_id=self.CTRL_B)

        ctrl_b_ident = _ctrl_ident(self.CTRL_B, "api_bind")
        assert Notification.objects.filter(ident=ctrl_b_ident).exists()
        sync_hardening_notifications([], controller_id=self.CTRL_A)
        assert Notification.objects.filter(ident=ctrl_b_ident).exists()

    def test_multiple_bind_violations_all_scoped(self):
        violations = [
            _make_bind_violation(config_key="api_bind"),
            _make_bind_violation(config_key="rack_ctrl_api_bind"),
        ]
        sync_hardening_notifications(violations, controller_id=self.CTRL_A)
        for config_key in ("api_bind", "rack_ctrl_api_bind"):
            ident = _ctrl_ident(self.CTRL_A, config_key)
            assert Notification.objects.filter(ident=ident).exists(), (
                f"Missing scoped notification: {ident}"
            )


@pytest.mark.usefixtures("maasdb")
class TestHardeningIdentLength:
    """Controller-scoped idents must stay within Notification.ident max_length=40."""

    # All bind config_keys produced by HardeningValidator.__init__'s
    # self._binds (including api_int_bind, which has no maas_url-derived
    # fallback, and dns_bind, which is snap-only).
    BIND_CONFIG_KEYS = (
        "api_bind",
        "api_int_bind",
        "prometheus_bind",
        "temporal_bind",
        "rpc_bind",
        "rack_ctrl_api_bind",
        "syslog_bind",
        "http_proxy_bind",
        "dns_bind",
    )

    def test_all_bind_idents_within_40_chars(self):
        """Every (system_id, config_key) pair produces an ident <= 40 chars."""
        # system_id is a base-24 znums string; empirically 6 chars for the
        # full 24^6 space.  Use the 6-char maximum to confirm the invariant.
        system_id = "abc123"  # representative 6-char system_id
        for config_key in self.BIND_CONFIG_KEYS:
            ident = _ctrl_ident(system_id, config_key)
            assert len(ident) <= 40, (
                f"ident {ident!r} is {len(ident)} chars — exceeds "
                f"Notification.ident max_length=40"
            )

    def test_scoped_ident_can_be_stored_and_retrieved(self):
        """An ident at the expected maximum length round-trips through the DB."""
        # rack_ctrl_api_bind is the longest key (18 chars) and produces an
        # ident of exactly 40 chars; verify it persists.
        system_id = "abc123"
        config_key = "rack_ctrl_api_bind"
        ident = _ctrl_ident(system_id, config_key)
        v = _make_bind_violation(config_key=config_key)
        sync_hardening_notifications([v], controller_id=system_id)
        assert Notification.objects.filter(ident=ident).exists(), (
            f"Notification with ident {ident!r} was not created"
        )
