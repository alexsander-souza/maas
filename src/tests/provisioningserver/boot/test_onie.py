#  Copyright 2026 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the ONIE boot method."""

import pytest

from provisioningserver.boot import BootMethodRegistry


class TestONIEBootMethod:
    """Tests for the ONIE boot method properties."""

    def test_name(self):
        method = self._get_onie_method()
        assert method.name == "onie"

    def test_bios_boot_method(self):
        method = self._get_onie_method()
        assert method.bios_boot_method == "onie"

    def test_bootloader_path(self):
        method = self._get_onie_method()
        assert method.bootloader_path == "MAAS/a/v3/nos-installer"

    def test_template_subdir(self):
        method = self._get_onie_method()
        assert method.template_subdir == "onie"

    def test_arch_octet(self):
        method = self._get_onie_method()
        assert method.arch_octet is None

    def test_user_class(self):
        """ONIE should use 'onie_dhcp_user_class' as its user class."""
        method = self._get_onie_method()
        assert method.user_class == "onie_dhcp_user_class"

    def test_bootloader_arches(self):
        method = self._get_onie_method()
        assert method.bootloader_arches == []

    def test_path_prefix_http(self):
        method = self._get_onie_method()
        assert method.path_prefix_http

    def test_absolute_url_as_filename(self):
        method = self._get_onie_method()
        assert method.absolute_url_as_filename

    def _get_onie_method(self):
        """Get the ONIE boot method from the registry."""
        for name, method in BootMethodRegistry:
            if name == "onie":
                return method
        pytest.fail("ONIE boot method not found in registry")
