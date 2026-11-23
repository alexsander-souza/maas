# Copyright 2014-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `provisioningserver.boot`."""

import errno
import os
from unittest import mock

import pytest
import tempita
from twisted.internet.defer import inlineCallbacks
from twisted.python import context

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.factory import factory
from provisioningserver import boot
from provisioningserver.boot import (
    BootMethod,
    BootMethodRegistry,
    BytesReader,
    gen_template_filenames,
    get_remote_mac,
)
from provisioningserver.kernel_opts import compose_kernel_command_line
from provisioningserver.testing.config import ClusterConfigurationFixture
from tests.provisioningserver.test_kernel_opts import make_kernel_parameters

TIMEOUT = get_testing_timeout()


class FakeBootMethod(BootMethod):
    name = factory.make_name("name")
    bios_boot_method = factory.make_name("bios_boot_method")
    template_subdir = factory.make_name("template_subdir")
    bootloader_arches = [factory.make_name("arch") for _ in range(2)]
    bootloader_path = factory.make_name("bootloader_path")
    bootloader_files = [factory.make_name("bootloader_file") for _ in range(3)]
    arch_octet = "00:00"
    user_class = None

    def match_path(self, backend, path):
        return {}

    def get_reader(backend, kernel_params, **extra):
        return BytesReader("")


@pytest.mark.rack_reactor_guard
class TestBootMethod:
    """Test for `BootMethod` in `provisioningserver.boot`."""

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_get_remote_mac(self, mocker):
        remote_host = factory.make_ipv4_address()
        call_context = {
            "local": (factory.make_ipv4_address(), factory.pick_port()),
            "remote": (remote_host, factory.pick_port()),
        }
        mock_find = mocker.patch.object(boot, "find_mac_via_arp")
        yield context.call(call_context, get_remote_mac)
        mock_find.assert_called_once_with(remote_host)

    def test_gen_template_filenames(self):
        purpose = factory.make_name("purpose")
        arch, subarch = factory.make_names("arch", "subarch")
        expected = [
            f"config.{purpose}.{arch}.{subarch}.template",
            f"config.{purpose}.{arch}.template",
            f"config.{purpose}.template",
            "config.template",
        ]
        observed = gen_template_filenames(purpose, arch, subarch)
        assert expected == list(observed)

    def test_get_pxe_template(self, mocker):
        method = FakeBootMethod()
        purpose = factory.make_name("purpose")
        arch, subarch = factory.make_names("arch", "subarch")
        filename = factory.make_name("filename")
        gen_filenames = mocker.patch.object(boot, "gen_template_filenames")
        gen_filenames.return_value = [filename]
        from_filename = mocker.patch.object(tempita.Template, "from_filename")
        from_filename.return_value = mock.sentinel.template
        template = method.get_template(purpose, arch, subarch)
        assert mock.sentinel.template == template
        gen_filenames.assert_called_once_with(purpose, arch, subarch)
        from_filename.assert_called_once_with(
            os.path.join(method.get_template_dir(), filename), encoding="UTF-8"
        )

    def test_get_template_gets_default_if_available(self, tmp_path):
        templates_dir = str(tmp_path)
        method = FakeBootMethod()
        method.get_template_dir = lambda: templates_dir
        generic_template = factory.make_file(templates_dir, "config.template")
        purpose = factory.make_name("purpose")
        arch, subarch = factory.make_names("arch", "subarch")
        assert (
            generic_template
            == method.get_template(purpose, arch, subarch).name
        )

    def test_get_template_not_found(self, tmp_path, mocker):
        mock_try_send_rack_event = mocker.patch.object(
            boot, "try_send_rack_event"
        )
        method = FakeBootMethod()
        method.get_template_dir = lambda: str(tmp_path)
        with pytest.raises(AssertionError):
            method.get_template(
                *factory.make_names("purpose", "arch", "subarch")
            )
        mock_try_send_rack_event.assert_called_once()

    def test_get_templates_only_suppresses_ENOENT(self, mocker):
        method = FakeBootMethod()
        from_filename = mocker.patch.object(tempita.Template, "from_filename")
        from_filename.side_effect = IOError()
        from_filename.side_effect.errno = errno.EACCES
        with pytest.raises(IOError):
            method.get_template(
                *factory.make_names("purpose", "arch", "subarch")
            )

    def test_compose_template_namespace(self):
        kernel_params = make_kernel_parameters()
        method = FakeBootMethod()
        template_namespace = method.compose_template_namespace(kernel_params)
        assert kernel_params.initrd == template_namespace["initrd_path"](
            kernel_params
        )
        assert compose_kernel_command_line(
            kernel_params
        ) == template_namespace["kernel_command"](kernel_params)
        assert kernel_params == template_namespace["kernel_params"]
        assert kernel_params.kernel == template_namespace["kernel_path"](
            kernel_params
        )
        assert template_namespace["dtb_path"](kernel_params) is None

    def test_compose_template_namespace_returns_filetype_when_missing(self):
        kernel_params = make_kernel_parameters(
            subarch="xgene-uboot-mustang",
            kernel=None,
            initrd=None,
            boot_dtb=None,
        )
        method = FakeBootMethod()
        template_namespace = method.compose_template_namespace(kernel_params)
        assert "boot-initrd" == template_namespace["initrd_path"](
            kernel_params
        )
        assert compose_kernel_command_line(
            kernel_params
        ) == template_namespace["kernel_command"](kernel_params)
        assert kernel_params == template_namespace["kernel_params"]
        assert "boot-kernel" == template_namespace["kernel_path"](
            kernel_params
        )
        assert "boot-dtb" == template_namespace["dtb_path"](kernel_params)

    def test_compose_template_namespace_returns_dtb_file_when_arm(self):
        kernel_params = make_kernel_parameters(subarch="xgene-uboot-mustang")
        method = FakeBootMethod()
        template_namespace = method.compose_template_namespace(kernel_params)
        assert kernel_params.initrd == template_namespace["initrd_path"](
            kernel_params
        )
        assert compose_kernel_command_line(
            kernel_params
        ) == template_namespace["kernel_command"](kernel_params)
        assert kernel_params == template_namespace["kernel_params"]
        assert kernel_params.kernel == template_namespace["kernel_path"](
            kernel_params
        )
        assert kernel_params.boot_dtb == template_namespace["dtb_path"](
            kernel_params
        )

    def test_compose_template_namespace_include_debug(self, request):
        debug = factory.pick_bool()
        boot.debug_enabled.cache_clear()
        request.addfinalizer(boot.debug_enabled.cache_clear)
        config_fixture = ClusterConfigurationFixture(debug=debug)
        config_fixture.setUp()
        request.addfinalizer(config_fixture.cleanUp)
        kernel_params = make_kernel_parameters()
        method = FakeBootMethod()
        template_namespace = method.compose_template_namespace(kernel_params)
        assert debug == template_namespace["debug"]

    def test_consistent_names(self):
        # MAAS stores the boot method name on the Subnet model to indicate it
        # is disabled. This test ensures the name doesn't change.
        assert [
            ("ipxe", None),
            ("onie", None),
            ("pxe", "00:00"),
            ("uefi_amd64_tftp", "00:07"),
            ("uefi_amd64_http", "00:10"),
            ("uefi_ebc_tftp", "00:09"),
            ("uefi_arm64_tftp", "00:0B"),
            ("uefi_arm64_http", "00:13"),
            ("uefi_riscv64_tftp", "00:1B"),
            ("open-firmware_ppc64el", "00:0C"),
            ("powernv", "00:0E"),
            ("windows", None),
            ("s390x", "00:1F"),
            ("s390x_partition", "00:20"),
        ] == [
            (boot_method.name, boot_method.arch_octet)
            for _, boot_method in BootMethodRegistry
        ]
