#  Copyright 2026 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `provisioningserver.drivers.power.fips`."""

from provisioningserver.drivers.power.fips import (
    DRIVER_FIPS_REGISTRY,
    DriverFIPSStatus,
    get_fips_compliant_alternatives,
    get_fips_status_for_driver,
)


class TestDriverFIPSRegistry:
    def test_known_compliant_driver_returns_true_no_reason(self):
        supported, reason = get_fips_status_for_driver("ipmi")
        assert supported
        assert reason is None

    def test_known_unsupported_driver_returns_false_with_reason(self):
        supported, reason = get_fips_status_for_driver("apc")
        assert not supported
        assert reason is not None
        assert "FIPS" in reason

    def test_unknown_driver_defaults_to_non_compliant(self):
        # Drivers not in the registry are assumed non-compliant (closed-world).
        supported, reason = get_fips_status_for_driver("unknown_driver")
        assert not supported
        assert reason is not None

    def test_all_registry_entries_have_reason_iff_unsupported(self):
        for name, (status, reason) in DRIVER_FIPS_REGISTRY.items():
            if status == DriverFIPSStatus.UNSUPPORTED:
                assert reason is not None, (
                    f"driver {name!r} is UNSUPPORTED but has no reason"
                )
            else:
                assert reason is None, (
                    f"driver {name!r} is COMPLIANT but has a reason set"
                )

    def test_unsupported_drivers_include_known_non_fips(self):
        for driver in ("apc", "raritan", "recs_box"):
            supported, _ = get_fips_status_for_driver(driver)
            assert not supported, f"expected {driver!r} to be FIPS-unsupported"

    def test_every_registry_key_matches_a_registered_driver_name(self):
        # A key that does not correspond to a real power driver `name`
        # (e.g. "seamicro" instead of "sm15k") would silently fall through
        # to the COMPLIANT default and fail to block an unsupported driver.
        from provisioningserver.drivers.power.registry import (
            PowerDriverRegistry,
        )

        driver_names = {name for name, _ in PowerDriverRegistry}
        for key in DRIVER_FIPS_REGISTRY:
            assert key in driver_names, (
                f"registry key {key!r} does not match any power driver name"
            )


class TestGetFipsCompliantAlternatives:
    def test_returns_only_compliant_drivers(self):
        alternatives = get_fips_compliant_alternatives()
        for name in alternatives:
            status, _ = DRIVER_FIPS_REGISTRY.get(
                name, (DriverFIPSStatus.COMPLIANT, None)
            )
            assert status == DriverFIPSStatus.COMPLIANT, (
                f"alternative {name!r} is not COMPLIANT in registry"
            )

    def test_does_not_include_unsupported_drivers(self):
        alternatives = get_fips_compliant_alternatives()
        for name, (status, _) in DRIVER_FIPS_REGISTRY.items():
            if status == DriverFIPSStatus.UNSUPPORTED:
                assert name not in alternatives, (
                    f"unsupported driver {name!r} should not appear in alternatives"
                )

    def test_returns_nonempty_list(self):
        assert len(get_fips_compliant_alternatives()) > 0
