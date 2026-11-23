# Copyright 2019-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the ipxe boot method."""

import re

from twisted.python.filepath import FilePath

from maastesting.factory import factory
from provisioningserver.boot import BytesReader
from provisioningserver.boot.ipxe import IPXEBootMethod, re_config_file
from provisioningserver.boot.testing import TFTPPath, TFTPPathAndComponents
from provisioningserver.config import ClusterConfiguration
from provisioningserver.drivers import Architecture, ArchitectureRegistry
from provisioningserver.utils.network import convert_host_to_uri_str
from tests.provisioningserver.test_kernel_opts import make_kernel_parameters


def compose_config_path(mac: str) -> TFTPPath:
    """Compose the TFTP/HTTP path for a iPXE configuration file.

    The path returned is relative to root, as it would be
    identified by clients on the network.

    :param mac: A MAC address.
    :return: Path for the corresponding iPXE config file as exposed over
        TFTP/HTTP, as a byte string.
    """
    return f"ipxe.cfg-{mac}".encode("ascii")


class TestIPXEBootMethod:
    def make_tftp_root(self, tmp_path, monkeypatch):
        """Set, and return, a temporary TFTP root directory."""
        tftproot = tmp_path / "tftproot"
        tftproot.mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_path = config_dir / "cluster.yaml"
        with ClusterConfiguration.open_for_update(str(config_path)) as config:
            config.tftp_root = str(tftproot)
        monkeypatch.setenv("MAAS_CLUSTER_CONFIG", str(config_path))
        return FilePath(str(tftproot))

    def test_compose_config_path_follows_maas_pxe_directory_layout(self):
        mac = factory.make_mac_address()
        assert "ipxe.cfg-%s" % mac == compose_config_path(mac).decode("ascii")

    def test_compose_config_path_does_not_include_tftp_root(
        self, tmp_path, monkeypatch
    ):
        tftproot = self.make_tftp_root(tmp_path, monkeypatch).asBytesMode()
        mac = factory.make_mac_address()
        config_path = compose_config_path(mac)
        assert not config_path.startswith(tftproot.path)

    def test_bootloader_path(self):
        method = IPXEBootMethod()
        assert "ipxe.cfg" == method.bootloader_path

    def test_bootloader_path_does_not_include_tftp_root(
        self, tmp_path, monkeypatch
    ):
        tftproot = self.make_tftp_root(tmp_path, monkeypatch)
        method = IPXEBootMethod()
        assert not method.bootloader_path.startswith(tftproot.path)

    def test_name(self):
        method = IPXEBootMethod()
        assert "ipxe" == method.name

    def test_template_subdir(self):
        method = IPXEBootMethod()
        assert "ipxe" == method.template_subdir

    def test_arch_octet(self):
        method = IPXEBootMethod()
        assert method.arch_octet is None

    def test_user_class(self):
        method = IPXEBootMethod()
        assert "iPXE" == method.user_class


class TestIPXEBootMethodRender:
    """Tests for `provisioningserver.boot.ipxe.IPXEBootMethod.render`."""

    def test_get_reader_install(self):
        # Given the right configuration options, the PXE configuration is
        # correctly rendered.
        method = IPXEBootMethod()
        params = make_kernel_parameters(purpose="xinstall")
        name = f"{params.arch}/{params.subarch}"
        registered = False
        if name not in ArchitectureRegistry:
            resource = Architecture(name, name)
            ArchitectureRegistry.register_item(name, resource)
            registered = True
        try:
            fs_host = re.escape(
                f"http://{convert_host_to_uri_str(params.fs_host)}:5248/images"
            )
            output = method.get_reader(backend=None, kernel_params=params)
            # The output is a BytesReader.
            assert isinstance(output, BytesReader)
            output = output.read(10000).decode("utf-8")
            # The template has rendered without error. iPXE configurations
            # start with #ipxe.
            assert output.startswith("#!ipxe")
            # The iPXE parameters are all set according to the options.
            for regex in [
                rf"(?ms).*^\s*kernel {fs_host}/{params.kernel}$",
                rf"(?ms).*^\s*initrd {fs_host}/{params.initrd}$",
                r"(?ms).*^\s*imgargs .+?$",
            ]:
                assert re.search(regex, output)
        finally:
            if registered:
                ArchitectureRegistry.unregister_item(name)

    def test_get_reader_with_local_purpose(self):
        # If purpose is "local", the config.localboot.template should be
        # used.
        method = IPXEBootMethod()
        options = {
            "backend": None,
            "kernel_params": make_kernel_parameters(purpose="local"),
        }
        output = method.get_reader(**options).read(10000)
        assert b"sanboot --no-describe --drive 0x80" in output


class TestIPXEBootMethodRegex:
    "Tests for `provisioningserver.boot.ipxe.IPXEBootMethod.re_config_file`."

    @staticmethod
    def get_example_path_and_components() -> TFTPPathAndComponents:
        """Return a plausible path and its components.

        The path is intended to match `re_config_file`, and the components are
        the expected groups from a match.
        """
        mac = factory.make_mac_address()
        components = {
            "mac": mac.encode("ascii"),
            "arch": None,
            "subarch": None,
        }
        config_path = compose_config_path(mac)
        return config_path, components

    def test_re_config_file_is_compatible_with_config_path_generator(self):
        # The regular expression for extracting components of the file path is
        # compatible with the PXE config path generator.
        for iteration in range(10):  # noqa: B007
            config_path, args = self.get_example_path_and_components()
            match = re_config_file.match(config_path)
            assert match is not None, config_path
            assert args == match.groupdict()

    def test_re_config_file_with_leading_slash(self):
        # The regular expression for extracting components of the file path
        # doesn't care if there's a leading forward slash; the TFTP server is
        # easy on this point, so it makes sense to be also.
        config_path, args = self.get_example_path_and_components()
        # Ensure there's a leading slash.
        config_path = b"/" + config_path.lstrip(b"/")
        match = re_config_file.match(config_path)
        assert match is not None, config_path
        assert args == match.groupdict()

    def test_re_config_file_without_leading_slash(self):
        # The regular expression for extracting components of the file path
        # doesn't care if there's no leading forward slash; the TFTP server is
        # easy on this point, so it makes sense to be also.
        config_path, args = self.get_example_path_and_components()
        # Ensure there's no leading slash.
        config_path = config_path.lstrip(b"/")
        match = re_config_file.match(config_path)
        assert match is not None, config_path
        assert args == match.groupdict()

    def test_re_config_file_matches_ipxe_cfg(self):
        # The default config path is simply "ipxe.cfg" (without
        # leading slash).  The regex matches this.
        mac = b"aa:bb:cc:dd:ee:ff"
        match = re_config_file.match(b"ipxe.cfg-%s" % mac)
        assert match is not None
        assert {
            "mac": mac,
            "arch": None,
            "subarch": None,
        } == match.groupdict()

    def test_re_config_file_matches_ipxe_cfg_with_leading_slash(self):
        mac = b"aa:bb:cc:dd:ee:ff"
        match = re_config_file.match(b"/ipxe.cfg-%s" % mac)
        assert match is not None
        assert {
            "mac": mac,
            "arch": None,
            "subarch": None,
        } == match.groupdict()

    def test_re_config_file_does_not_match_non_config_file(self):
        assert re_config_file.match(b"ipxe.cfg-kernel") is None

    def test_re_config_file_does_not_match_file_in_root(self):
        assert re_config_file.match(b"aa:bb:cc:dd:ee:ff") is None

    def test_re_config_file_with_default_arch(self):
        arch = factory.make_name("arch", sep="").encode("ascii")
        match = re_config_file.match(b"ipxe.cfg-default-%s" % arch)
        assert match is not None
        assert {
            "mac": None,
            "arch": arch,
            "subarch": None,
        } == match.groupdict()

    def test_re_config_file_with_default_arch_and_subarch(self):
        arch = factory.make_name("arch", sep="").encode("ascii")
        subarch = factory.make_name("subarch", sep="").encode("ascii")
        match = re_config_file.match(
            b"ipxe.cfg-default-%s-%s" % (arch, subarch)
        )
        assert match is not None
        assert {
            "mac": None,
            "arch": arch,
            "subarch": subarch,
        } == match.groupdict()
