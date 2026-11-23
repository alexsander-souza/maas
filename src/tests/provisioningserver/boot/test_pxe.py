# Copyright 2012-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the pxe boot method."""

from collections import OrderedDict
import re

import pytest
from twisted.python.filepath import FilePath

from maastesting.factory import factory
from provisioningserver import kernel_opts
from provisioningserver.boot import BytesReader
from provisioningserver.boot.pxe import (
    ARP_HTYPE,
    PXEBootMethod,
    re_config_file,
)
from provisioningserver.boot.testing import TFTPPath, TFTPPathAndComponents
from provisioningserver.testing.config import ClusterConfigurationFixture
from provisioningserver.utils.network import convert_host_to_uri_str
from tests.provisioningserver.test_kernel_opts import make_kernel_parameters


def compose_config_path(mac: str) -> TFTPPath:
    """Compose the TFTP path for a PXE configuration file.

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
    return "pxelinux.cfg/{htype:02x}-{mac}".format(
        htype=ARP_HTYPE.ETHERNET, mac=mac
    ).encode("ascii")


class TestPXEBootMethod:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        tftproot = tmp_path / "tftp"
        tftproot.mkdir()
        self._tftp_root = FilePath(str(tftproot))
        self._config_fixture = ClusterConfigurationFixture(
            tftp_root=str(tftproot)
        )
        self._config_fixture.setUp()
        yield
        self._config_fixture.cleanUp()

    def make_tftp_root(self):
        """Return the TFTP root directory set up by _setup."""
        return self._tftp_root

    def make_dummy_bootloader_sources(self, destination, loader_names):
        """install_bootloader requires real files to exist, this method
        creates them in the requested location.

        :return: list of created filenames
        """
        created = []
        for loader in loader_names:
            name = factory.make_file(destination, loader)
            created.append(name)
        return created

    def test_compose_config_path_follows_maas_pxe_directory_layout(self):
        mac = factory.make_mac_address("-")
        assert (
            f"pxelinux.cfg/{ARP_HTYPE.ETHERNET:02x}-{mac}"
            == compose_config_path(mac).decode("ascii")
        )

    def test_compose_config_path_does_not_include_tftp_root(self):
        tftproot = self.make_tftp_root().asBytesMode()
        mac = factory.make_mac_address("-")
        config_path = compose_config_path(mac)
        assert not config_path.startswith(tftproot.path)

    def test_bootloader_path(self):
        method = PXEBootMethod()
        assert "lpxelinux.0" == method.bootloader_path

    def test_bootloader_path_does_not_include_tftp_root(self):
        tftproot = self.make_tftp_root()
        method = PXEBootMethod()
        assert not method.bootloader_path.startswith(tftproot.path)

    def test_name(self):
        method = PXEBootMethod()
        assert "pxe" == method.name

    def test_template_subdir(self):
        method = PXEBootMethod()
        assert "pxe" == method.template_subdir

    def test_arch_octet(self):
        method = PXEBootMethod()
        assert "00:00" == method.arch_octet


def parse_pxe_config(text):
    """Parse a PXE config file.

    Returns a structure like the following, defining the sections::

      {"section_label": {"KERNEL": "...", "INITRD": "...", ...}, ...}

    Additionally, the returned dict - which is actually an `OrderedDict`, as
    are all mappings returned from this function - has a `header` attribute.
    This is an `OrderedDict` of the settings in the top part of the PXE config
    file, the part before any labelled sections.
    """
    result = OrderedDict()
    sections = re.split("^LABEL ", text, flags=re.MULTILINE)
    for index, section in enumerate(sections):
        elements = [
            line.split(None, 1)
            for line in section.splitlines()
            if line and not line.isspace()
        ]
        if index == 0:
            result.header = OrderedDict(elements)
        else:
            [label] = elements.pop(0)
            if label in result:
                raise AssertionError("Section %r already defined" % label)
            result[label] = OrderedDict(elements)
    return result


class TestParsePXEConfig:
    """Tests for `parse_pxe_config`."""

    def test_parse_with_no_header(self):
        config = parse_pxe_config("LABEL foo\nOPTION setting")
        assert {"foo": {"OPTION": "setting"}} == config
        assert {} == config.header

    def test_parse_with_no_labels(self):
        config = parse_pxe_config("OPTION setting")
        assert {"OPTION": "setting"} == config.header
        assert {} == config


class TestPXEBootMethodRender:
    """Tests for `provisioningserver.boot.pxe.PXEBootMethod.render`."""

    def test_get_reader_install(self):
        # Given the right configuration options, the PXE configuration is
        # correctly rendered.
        method = PXEBootMethod()
        params = make_kernel_parameters(purpose="xinstall")
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

    def test_get_reader_install_mustang_dtb(self):
        # Architecture specific test.
        # Given the right configuration options, the PXE configuration is
        # correctly rendered for Mustang.
        method = PXEBootMethod()
        params = make_kernel_parameters(
            osystem="ubuntu",
            arch="arm64",
            subarch="xgene-uboot-mustang",
            purpose="xinstall",
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
            rf"(?ms).*^\s+KERNEL {params.kernel}$",
            rf"(?ms).*^\s+INITRD {params.initrd}$",
            rf"(?ms).*^\s+FDT {params.boot_dtb}$",
            r"(?ms).*^\s+APPEND .+?$",
        ]:
            assert re.search(regex, output)

    def test_get_reader_xinstall_mustang_dtb(self):
        # Architecture specific test.
        # Given the right configuration options, the PXE configuration is
        # correctly rendered for Mustang.
        method = PXEBootMethod()
        params = make_kernel_parameters(
            osystem="ubuntu",
            arch="arm64",
            subarch="xgene-uboot-mustang",
            purpose="xinstall",
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
            rf"(?ms).*^\s+KERNEL {params.kernel}$",
            rf"(?ms).*^\s+INITRD {params.initrd}$",
            rf"(?ms).*^\s+FDT {params.boot_dtb}$",
            r"(?ms).*^\s+APPEND .+?$",
        ]:
            assert re.search(regex, output)

    def test_get_reader_with_extra_arguments_does_not_affect_output(self):
        # get_reader() allows any keyword arguments as a safety valve.
        method = PXEBootMethod()
        options = {
            "backend": None,
            "kernel_params": make_kernel_parameters(purpose="install"),
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
        # If purpose is "local", the config.localboot.template should be
        # used.
        method = PXEBootMethod()
        options = {
            "backend": None,
            "kernel_params": make_kernel_parameters(purpose="local"),
        }
        output = method.get_reader(**options).read(10000)
        assert b"LOCALBOOT 0" in output

    def test_get_reader_with_local_purpose_i386_arch(self):
        # Intel i386 is a special case and needs to use the chain.c32
        # loader as the LOCALBOOT PXE directive is unreliable.
        method = PXEBootMethod()
        options = {
            "backend": None,
            "kernel_params": make_kernel_parameters(
                arch="i386", purpose="local"
            ),
        }
        output = method.get_reader(**options).read(10000)
        assert b"chain.c32" in output
        assert b"LOCALBOOT" not in output

    def test_get_reader_with_local_purpose_amd64_arch(self):
        # Intel amd64 is a special case and needs to use the chain.c32
        # loader as the LOCALBOOT PXE directive is unreliable.
        method = PXEBootMethod()
        options = {
            "backend": None,
            "kernel_params": make_kernel_parameters(
                arch="amd64", purpose="local"
            ),
        }
        output = method.get_reader(**options).read(10000)
        assert b"chain.c32" in output
        assert b"LOCALBOOT" not in output


class TestPXEBootMethodRenderConfigScenarios:
    """Tests for `provisioningserver.boot.pxe.PXEBootMethod.render_config`."""

    @pytest.mark.parametrize(
        "purpose",
        ["commissioning", "xinstall"],
        ids=["commissioning", "xinstall"],
    )
    def test_get_reader_scenarios(self, purpose, mocker):
        method = PXEBootMethod()
        get_ephemeral_name = mocker.patch(
            "provisioningserver.kernel_opts.get_ephemeral_name",
            create=True,
        )
        get_ephemeral_name.return_value = factory.make_name("ephemeral")
        osystem = factory.make_name("osystem")
        arch = factory.make_name("arch")
        subarch = factory.make_name("subarch")
        options = {
            "backend": None,
            "kernel_params": make_kernel_parameters(
                osystem=osystem,
                kernel_osystem=osystem,
                subarch=subarch,
                arch=arch,
                purpose=purpose,
            ),
        }
        fs_host = f"http://{convert_host_to_uri_str(options['kernel_params'].fs_host)}:5248/images"
        output = method.get_reader(**options).read(10000).decode("utf-8")
        config = parse_pxe_config(output)
        # The default section is defined.
        default_section_label = config.header["DEFAULT"]
        assert default_section_label in config
        default_section = dict(config[default_section_label])

        assert (
            f"{fs_host}/{options['kernel_params'].kernel}"
            == default_section["KERNEL"]
        )
        assert (
            f"{fs_host}/{options['kernel_params'].initrd}"
            == default_section["INITRD"]
        )
        assert "2" == default_section["IPAPPEND"]


class TestPXEBootMethodRenderConfigScenariosEnlist:
    def test_get_reader_scenarios(self, mocker):
        # The commissioning config uses an extra PXELINUX module to auto
        # select between i386 and amd64.
        method = PXEBootMethod()
        get_ephemeral_name = mocker.patch.object(
            kernel_opts, "get_ephemeral_name", create=True
        )
        get_ephemeral_name.return_value = factory.make_name("ephemeral")
        osystem = factory.make_name("osystem")
        release = factory.make_name("release")
        label = factory.make_name("label")
        options = {
            "backend": None,
            "kernel_params": make_kernel_parameters(
                osystem=osystem,
                release=release,
                label=label,
                kernel_osystem=osystem,
                kernel_release=release,
                kernel_label=label,
                subarch="generic",
                purpose="enlist",
            ),
        }
        fs_host = f"http://{convert_host_to_uri_str(options['kernel_params'].fs_host)}:5248/images"
        output = method.get_reader(**options).read(10000).decode("utf-8")
        config = parse_pxe_config(output)
        # The default section is defined.
        default_section_label = config.header["DEFAULT"]
        assert default_section_label in config
        default_section = config[default_section_label]
        # The default section uses the ifcpu64 module, branching to the "i386"
        # or "amd64" labels accordingly.
        assert "ifcpu64.c32" == default_section["KERNEL"]
        assert ["amd64", "--", "i386"] == default_section["APPEND"].split()
        # Both "i386" and "amd64" sections exist.
        assert "i386" in config
        assert "amd64" in config

        # Each section defines KERNEL, INITRD, and APPEND settings.  The
        # KERNEL and INITRD ones contain paths referring to their
        # architectures.
        for section_label in ("i386", "amd64"):
            section = config[section_label]
            assert section.keys() >= {"KERNEL", "INITRD", "APPEND"}
            assert (
                f"{fs_host}/{options['kernel_params'].kernel}"
                == section["KERNEL"]
            )
            assert (
                f"{fs_host}/{options['kernel_params'].initrd}"
                == section["INITRD"]
            )
            assert "APPEND" in section


class TestPXEBootMethodRegex:
    """Tests for `provisioningserver.boot.pxe.PXEBootMethod.re_config_file`."""

    @staticmethod
    def get_example_path_and_components() -> TFTPPathAndComponents:
        """Return a plausible path and its components.

        The path is intended to match `re_config_file`, and the components are
        the expected groups from a match.
        """
        mac = factory.make_mac_address("-")
        components = {
            "mac": mac.encode("ascii"),
            "hardware_uuid": None,
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

    def test_re_config_file_matches_classic_pxelinux_cfg(self):
        # The default config path is simply "pxelinux.cfg" (without
        # leading slash).  The regex matches this.
        mac = b"aa-bb-cc-dd-ee-ff"
        match = re_config_file.match(b"pxelinux.cfg/01-%s" % mac)
        assert match is not None
        assert {
            "mac": mac,
            "hardware_uuid": None,
            "arch": None,
            "subarch": None,
        } == match.groupdict()

    def test_re_config_file_matches_pxelinux_cfg_with_leading_slash(self):
        mac = b"aa-bb-cc-dd-ee-ff"
        match = re_config_file.match(b"/pxelinux.cfg/01-%s" % mac)
        assert match is not None
        assert {
            "mac": mac,
            "hardware_uuid": None,
            "arch": None,
            "subarch": None,
        } == match.groupdict()

    def test_re_config_file_matches_pxelinux_cfg_with_hardware_uuid(self):
        hardware_uuid = factory.make_UUID().encode()
        match = re_config_file.match(b"pxelinux.cfg/%s" % hardware_uuid)
        assert match is not None
        assert {
            "mac": None,
            "hardware_uuid": hardware_uuid,
            "arch": None,
            "subarch": None,
        } == match.groupdict()

    def test_re_config_file_does_not_match_non_config_file(self):
        assert re_config_file.match(b"pxelinux.cfg/kernel") is None

    def test_re_config_file_does_not_match_file_in_root(self):
        assert re_config_file.match(b"01-aa-bb-cc-dd-ee-ff") is None

    def test_re_config_file_does_not_match_file_not_in_pxelinux_cfg(self):
        assert re_config_file.match(b"foo/01-aa-bb-cc-dd-ee-ff") is None

    def test_re_config_file_with_default(self):
        match = re_config_file.match(b"pxelinux.cfg/default")
        assert match is not None
        assert {
            "mac": None,
            "hardware_uuid": None,
            "arch": None,
            "subarch": None,
        } == match.groupdict()

    def test_re_config_file_with_default_arch(self):
        arch = factory.make_name("arch", sep="").encode("ascii")
        match = re_config_file.match(b"pxelinux.cfg/default.%s" % arch)
        assert match is not None
        assert {
            "mac": None,
            "hardware_uuid": None,
            "arch": arch,
            "subarch": None,
        } == match.groupdict()

    def test_re_config_file_with_default_arch_and_subarch(self):
        arch = factory.make_name("arch", sep="").encode("ascii")
        subarch = factory.make_name("subarch", sep="").encode("ascii")
        match = re_config_file.match(
            b"pxelinux.cfg/default.%s-%s" % (arch, subarch)
        )
        assert match is not None
        assert {
            "mac": None,
            "hardware_uuid": None,
            "arch": arch,
            "subarch": subarch,
        } == match.groupdict()
