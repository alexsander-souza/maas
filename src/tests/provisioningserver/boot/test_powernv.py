# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `provisioningserver.boot.powernv`."""

import os
import re
from unittest.mock import Mock

from twisted.python.filepath import FilePath

from maastesting.factory import factory
from provisioningserver.boot import BytesReader
from provisioningserver.boot import powernv as powernv_module
from provisioningserver.boot.powernv import (
    ARP_HTYPE,
    format_bootif,
    PowerNVBootMethod,
    re_config_file,
)
from provisioningserver.boot.testing import TFTPPathAndComponents
from provisioningserver.config import ClusterConfiguration
from provisioningserver.utils.network import convert_host_to_uri_str
from tests.provisioningserver.boot.test_pxe import parse_pxe_config
from tests.provisioningserver.test_kernel_opts import make_kernel_parameters


def compose_config_path(mac: str) -> bytes:
    """Compose the TFTP path for a PowerNV PXE configuration file.

    The path returned is relative to the TFTP root, as it would be
    identified by clients on the network.

    :param mac: A MAC address, in IEEE 802 hyphen-separated form,
        corresponding to the machine for which this configuration is
        relevant. This relates to PXELINUX's lookup protocol.
    :return: Path for the corresponding PXE config file as exposed over
        TFTP, as a byte string.
    """
    # Not using os.path.join: this is a TFTP path, not a native path. Yes, in
    # practice for us they're the same. We always assume that the ARP HTYPE
    # (hardware type) that PXELINUX sends is Ethernet.
    return "ppc64el/pxelinux.cfg/{htype:02x}-{mac}".format(
        htype=ARP_HTYPE.ETHERNET, mac=mac
    ).encode("ascii")


def get_example_path_and_components() -> TFTPPathAndComponents:
    """Return a plausible path and its components.

    The path is intended to match `re_config_file`, and the components are
    the expected groups from a match.
    """
    mac = factory.make_mac_address("-")
    return compose_config_path(mac), {"mac": mac.encode("ascii")}


class TestPowerNVBootMethod:
    def make_tftp_root(self, tmp_path, monkeypatch):
        """Set, and return, a temporary TFTP root directory."""
        tftproot = tmp_path / "tftp"
        tftproot.mkdir()
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        config_path = os.path.join(
            str(config_dir),
            os.path.basename(ClusterConfiguration.DEFAULT_FILENAME),
        )
        with ClusterConfiguration.open_for_update(config_path) as config:
            config.tftp_root = str(tftproot)
        monkeypatch.setenv("MAAS_CLUSTER_CONFIG", config_path)
        return FilePath(str(tftproot))

    def test_compose_config_path_follows_maas_pxe_directory_layout(self):
        mac = factory.make_mac_address("-")
        assert (
            f"ppc64el/pxelinux.cfg/{ARP_HTYPE.ETHERNET:02x}-{mac}"
            == compose_config_path(mac).decode("ascii")
        )

    def test_compose_config_path_does_not_include_tftp_root(
        self, tmp_path, monkeypatch
    ):
        tftproot = self.make_tftp_root(tmp_path, monkeypatch).asBytesMode()
        mac = factory.make_mac_address("-")
        config_path = compose_config_path(mac)
        assert not config_path.startswith(tftproot.path)

    def test_bootloader_path(self):
        method = PowerNVBootMethod()
        assert "pxelinux.0" == method.bootloader_path

    def test_bootloader_path_does_not_include_tftp_root(
        self, tmp_path, monkeypatch
    ):
        tftproot = self.make_tftp_root(tmp_path, monkeypatch)
        method = PowerNVBootMethod()
        assert not method.bootloader_path.startswith(tftproot.path)

    def test_name(self):
        method = PowerNVBootMethod()
        assert "powernv" == method.name

    def test_template_subdir(self):
        method = PowerNVBootMethod()
        assert "pxe" == method.template_subdir

    def test_arch_octet(self):
        method = PowerNVBootMethod()
        assert "00:0E" == method.arch_octet

    def test_path_prefix(self):
        method = PowerNVBootMethod()
        assert "ppc64el/" == method.path_prefix


class TestPowerNVBootMethodMatchPath:
    """Tests for
    `provisioningserver.boot.powernv.PowerNVBootMethod.match_path`.
    """

    def test_match_path_pxe_config_with_mac(self):
        method = PowerNVBootMethod()
        config_path, args = get_example_path_and_components()
        params = method.match_path(None, config_path)
        expected = {"arch": "ppc64el", "mac": args["mac"].decode("ascii")}
        assert expected == params

    def test_match_path_pxe_config_without_mac(self, mocker):
        method = PowerNVBootMethod()
        fake_mac = factory.make_mac_address("-")
        mocker.patch.object(
            powernv_module, "get_remote_mac"
        ).return_value = fake_mac
        config_path = b"ppc64el/pxelinux.cfg/default"
        params = method.match_path(None, config_path)
        expected = {"arch": "ppc64el", "mac": fake_mac}
        assert expected == params

    def test_match_path_pxe_prefix_request(self, mocker):
        method = PowerNVBootMethod()
        fake_mac = factory.make_mac_address("-")
        mocker.patch.object(
            powernv_module, "get_remote_mac"
        ).return_value = fake_mac
        file_path = b"ppc64el/file"
        params = method.match_path(None, file_path)
        expected = {
            "arch": "ppc64el",
            "mac": fake_mac,
            # The "ppc64el/" prefix has been removed from the path.
            "path": file_path.decode("utf-8")[8:],
        }
        assert expected == params


class TestPowerNVBootMethodRenderConfig:
    """Tests for
    `provisioningserver.boot.powernv.PowerNVBootMethod.get_reader`
    """

    def test_get_reader_install(self):
        # Given the right configuration options, the PXE configuration is
        # correctly rendered.
        method = PowerNVBootMethod()
        params = make_kernel_parameters(arch="ppc64el", purpose="xinstall")
        fs_host = re.escape(
            f"http://{convert_host_to_uri_str(params.fs_host)}:5248/images"
        )
        output = method.get_reader(backend=None, kernel_params=params)
        # The output is a BytesReader.
        assert isinstance(output, BytesReader)
        output = output.read(10000).decode("utf-8")
        # The template has rendered without error. PXELINUX configurations
        # typically start with a DEFAULT line.
        assert output.startswith("DEFAULT ")
        # The PXE parameters are all set according to the options.
        for regex in [
            rf"(?ms).*^\s+KERNEL {fs_host}/{params.kernel}$",
            rf"(?ms).*^\s+INITRD {fs_host}/{params.initrd}$",
            r"(?ms).*^\s+APPEND .+?$",
        ]:
            assert re.search(regex, output)

    def test_get_reader_with_extra_arguments_does_not_affect_output(self):
        # get_reader() allows any keyword arguments as a safety valve.
        method = PowerNVBootMethod()
        options = {
            "backend": None,
            "kernel_params": make_kernel_parameters(
                arch="ppc64el", purpose="install"
            ),
        }
        # Capture the output before sprinking in some random options.
        output_before = method.get_reader(**options).read(10000)
        # Sprinkle some magic in.
        options.update(
            (factory.make_name("name"), factory.make_name("value"))
            for _ in range(10)
        )
        # Capture the output after sprinking in some random options.
        output_after = method.get_reader(**options).read(10000)
        # The generated template is the same.
        assert output_before == output_after

    def test_get_reader_with_local_purpose(self):
        # If purpose is "local", output should be empty string.
        method = PowerNVBootMethod()
        options = {
            "backend": None,
            "kernel_params": make_kernel_parameters(
                arch="ppc64el", purpose="local"
            ),
        }
        output = method.get_reader(**options).read(10000).decode("utf-8")
        assert "" in output

    def test_get_reader_appends_bootif(self):
        method = PowerNVBootMethod()
        fake_mac = factory.make_mac_address("-")
        params = make_kernel_parameters(purpose="install")
        output = method.get_reader(
            backend=None, kernel_params=params, arch="ppc64el", mac=fake_mac
        )
        output = output.read(10000).decode("utf-8")
        config = parse_pxe_config(output)
        expected = "BOOTIF=%s" % format_bootif(fake_mac)
        assert expected in config["execute"]["APPEND"]

    def test_format_bootif_replaces_colon(self):
        fake_mac = factory.make_mac_address("-")
        assert "01-%s" % fake_mac.replace(":", "-").lower() == format_bootif(
            fake_mac
        )

    def test_format_bootif_makes_mac_address_lower(self):
        fake_mac = factory.make_mac_address("-")
        fake_mac = fake_mac.upper()
        assert "01-%s" % fake_mac.replace(":", "-").lower() == format_bootif(
            fake_mac
        )


class TestPowerNVBootMethodPathPrefix:
    """Tests for `provisioningserver.boot.powernv.PowerNVBootMethod`."""

    def test_path_prefix_removed(self, tmp_path, request):
        temp_dir = FilePath(str(tmp_path))
        backend = Mock(base=temp_dir)  # A `TFTPBackend`.

        # Create a file in the backend's base directory.
        data = factory.make_string().encode("ascii")
        temp_file = temp_dir.child("example")
        temp_file.setContent(data)

        method = PowerNVBootMethod()
        params = method.get_params(backend, b"ppc64el/example")
        assert {"path": "example"} == params
        reader = method.get_reader(backend, make_kernel_parameters(), **params)
        request.addfinalizer(reader.finish)
        assert len(data) == reader.size
        assert data == reader.read(len(data))
        assert b"" == reader.read(1)

    def test_path_prefix_only_first_occurrence_removed(
        self, tmp_path, request
    ):
        temp_dir = FilePath(str(tmp_path))
        backend = Mock(base=temp_dir)  # A `TFTPBackend`.

        # Create a file nested within a "ppc64el" directory.
        data = factory.make_string().encode("ascii")
        temp_subdir = temp_dir.child("ppc64el")
        temp_subdir.createDirectory()
        temp_file = temp_subdir.child("example")
        temp_file.setContent(data)

        method = PowerNVBootMethod()
        params = method.get_params(backend, b"ppc64el/ppc64el/example")
        assert {"path": "ppc64el/example"} == params
        reader = method.get_reader(backend, make_kernel_parameters(), **params)
        request.addfinalizer(reader.finish)
        assert len(data) == reader.size
        assert data == reader.read(len(data))
        assert b"" == reader.read(1)


class TestPowerNVBootMethodRegex:
    """Tests for
    `provisioningserver.boot.powernv.PowerNVBootMethod.re_config_file`.
    """

    def test_re_config_file_is_compatible_with_config_path_generator(self):
        # The regular expression for extracting components of the file path is
        # compatible with the PXE config path generator.
        for iteration in range(10):  # noqa: B007
            config_path, args = get_example_path_and_components()
            match = re_config_file.match(config_path)
            assert match is not None, config_path
            assert args == match.groupdict()

    def test_re_config_file_with_leading_slash(self):
        # The regular expression for extracting components of the file path
        # doesn't care if there's a leading forward slash; the TFTP server is
        # easy on this point, so it makes sense to be also.
        config_path, args = get_example_path_and_components()
        # Ensure there's a leading slash.
        config_path = b"/" + config_path.lstrip(b"/")
        match = re_config_file.match(config_path)
        assert match is not None, config_path
        assert args == match.groupdict()

    def test_re_config_file_without_leading_slash(self):
        # The regular expression for extracting components of the file path
        # doesn't care if there's no leading forward slash; the TFTP server is
        # easy on this point, so it makes sense to be also.
        config_path, args = get_example_path_and_components()
        # Ensure there's no leading slash.
        config_path = config_path.lstrip(b"/")
        match = re_config_file.match(config_path)
        assert match is not None, config_path
        assert args == match.groupdict()

    def test_re_config_file_matches_classic_pxelinux_cfg(self):
        # The default config path is simply "pxelinux.cfg" (without
        # leading slash).  The regex matches this.
        mac = factory.make_mac_address("-").encode("ascii")
        match = re_config_file.match(b"ppc64el/pxelinux.cfg/01-%s" % mac)
        assert match is not None
        assert {"mac": mac} == match.groupdict()

    def test_re_config_file_matches_pxelinux_cfg_with_leading_slash(self):
        mac = factory.make_mac_address("-").encode("ascii")
        match = re_config_file.match(b"/ppc64el/pxelinux.cfg/01-%s" % mac)
        assert match is not None
        assert {"mac": mac} == match.groupdict()

    def test_re_config_file_does_not_match_non_config_file(self):
        assert re_config_file.match(b"ppc64el/pxelinux.cfg/kernel") is None

    def test_re_config_file_does_not_match_file_in_root(self):
        assert re_config_file.match(b"01-aa-bb-cc-dd-ee-ff") is None

    def test_re_config_file_does_not_match_file_not_in_pxelinux_cfg(self):
        assert re_config_file.match(b"foo/01-aa-bb-cc-dd-ee-ff") is None

    def test_re_config_file_with_default(self):
        match = re_config_file.match(b"ppc64el/pxelinux.cfg/default")
        assert match is not None
        assert {"mac": None} == match.groupdict()
