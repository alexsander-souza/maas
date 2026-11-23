# Copyright 2014-2016 Canonical Ltd.
# Copyright 2014 Cloudbase Solutions SRL.
# This software is licensed under the GNU Affero General Public License
# version 3 (see the file LICENSE).

"""Tests for `provisioningserver.boot.windows`."""

import io
import os
import shutil
from unittest import mock
from unittest.mock import ANY, sentinel

import pytest
from tftp.backend import FilesystemReader
from twisted.internet.defer import inlineCallbacks

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.deferred import extract_result
from maastesting.factory import factory
from maastesting.twisted import always_fail_with, always_succeed_with
from provisioningserver.boot import BootMethodError, BytesReader
from provisioningserver.boot import windows as windows_module
from provisioningserver.boot.windows import Bcd, WindowsPXEBootMethod
from provisioningserver.rpc.exceptions import NoSuchNode
from provisioningserver.rpc.region import RequestNodeInfoByMACAddress
from provisioningserver.testing.config import ClusterConfigurationFixture
from tests.provisioningserver.test_kernel_opts import make_kernel_parameters

TIMEOUT = get_testing_timeout()


class TestBcd:
    def configure_hivex(self, mocker):
        mock_hivex = mock.MagicMock()
        mocker.patch.object(
            windows_module, "load_hivex"
        ).return_value = mock_hivex
        mock_hivex.node_name.side_effect = [
            "Objects",
            Bcd.GUID_WINDOWS_BOOTMGR,
            Bcd.BOOT_MGR_DISPLAY_ORDER,
        ]
        mock_hivex.node_children.side_effect = [
            [factory.make_name("objects")],
            [factory.make_name("object")],
            ["value0", factory.make_UUID()],
            [factory.make_name("element")],
        ]
        mock_hivex.node_values.return_value = [factory.make_name("val")]

    def configure_bcd(self, mocker, uids=None):
        self.configure_hivex(mocker)
        filename = factory.make_name("filename")
        bcd = Bcd(filename)
        bcd.uids = mock.MagicMock(spec=dict)
        if uids is None:
            uids = [factory.make_name("uid"), factory.make_name("uid")]
        bcd.uids.__getitem__.return_value = uids
        bcd.hive = mock.MagicMock()
        return bcd

    def test_get_loader(self, mocker):
        bcd = self.configure_bcd(mocker)
        mock_elem = factory.make_name("elem")
        bootmgr_elems = mock.MagicMock(spec=dict)
        bootmgr_elems.__getitem__.return_value = mock_elem
        mock_node_value = factory.make_name("node_value")
        bcd.hive.node_values.return_value = [mock_node_value]
        mock_string = factory.make_name("strings")
        bcd.hive.value_multiple_strings.return_value = [mock_string]
        response = bcd._get_loader(bootmgr_elems)
        bcd.hive.node_values.assert_called_once_with(mock_elem)
        bcd.hive.value_multiple_strings.assert_called_once_with(
            mock_node_value
        )
        assert mock_string == response

    def test_get_loader_elems(self, mocker):
        mock_uid_0 = factory.make_name("uid")
        mock_uid_1 = factory.make_name("uid")
        bcd = self.configure_bcd(mocker, uids=[mock_uid_0, mock_uid_1])
        mock_child = factory.make_name("child")
        bcd.hive.node_children.side_effect = [[mock_child]]
        mock_name = factory.make_name("name")
        bcd.hive.node_name.return_value = mock_name
        response = bcd._get_loader_elems()
        bcd.hive.node_children.assert_called_once_with(mock_uid_1)
        bcd.hive.node_name.assert_called_once_with(mock_child)
        assert response == {mock_name: mock_child}

    def test_get_load_options_key(self, mocker):
        bcd = self.configure_bcd(mocker)
        fake_load_elem = factory.make_name("load_elem")
        mock_load_elem = mock.MagicMock()
        mock_load_elem.get.return_value = fake_load_elem
        mock_get_loader_elems = mocker.patch.object(Bcd, "_get_loader_elems")
        mock_get_loader_elems.return_value = mock_load_elem
        response = bcd._get_load_options_key()
        mock_get_loader_elems.assert_called_once_with()
        mock_load_elem.get.assert_called_once_with(bcd.LOAD_OPTIONS, None)
        assert response == fake_load_elem

    def test_set_load_options(self, mocker):
        mock_uid_0 = factory.make_name("uid")
        mock_uid_1 = factory.make_name("uid")
        bcd = self.configure_bcd(mocker, uids=[mock_uid_0, mock_uid_1])
        fake_value = factory.make_name("value").encode("ascii")
        mock_get_load_options_key = mocker.patch.object(
            Bcd, "_get_load_options_key"
        )
        mock_get_load_options_key.return_value = None
        fake_child = factory.make_name("child")
        bcd.hive.node_add_child.return_value = fake_child
        bcd.set_load_options(value=fake_value)
        compare = {
            "t": 1,
            "key": "Element",
            "value": fake_value.decode("utf-8").encode("utf-16le"),
        }
        mock_get_load_options_key.assert_called_once_with()
        bcd.hive.node_add_child.assert_called_once_with(
            mock_uid_1, bcd.LOAD_OPTIONS
        )
        bcd.hive.node_set_value.assert_called_once_with(fake_child, compare)
        bcd.hive.commit.assert_called_once_with(None)


@pytest.mark.rack_reactor_guard
class TestRequestNodeInfoByMACAddress:
    @wait_for(timeout=TIMEOUT)
    def test_returns_None_when_MAC_is_None(self):
        d = windows_module.request_node_info_by_mac_address(None)
        assert extract_result(d) is None

    @wait_for(timeout=TIMEOUT)
    def test_returns_None_when_node_not_found(self, mocker):
        client = mocker.patch.object(
            windows_module, "getRegionClient"
        ).return_value
        client.side_effect = always_fail_with(NoSuchNode())
        mac = factory.make_mac_address()
        d = windows_module.request_node_info_by_mac_address(mac)
        assert extract_result(d) is None

    @wait_for(timeout=TIMEOUT)
    def test_returns_output_from_RequestNodeInfoByMACAddress(self, mocker):
        client = mocker.patch.object(
            windows_module, "getRegionClient"
        ).return_value
        client.side_effect = always_succeed_with(sentinel.node_info)
        d = windows_module.request_node_info_by_mac_address(sentinel.mac)
        assert extract_result(d) is sentinel.node_info
        client.assert_called_once_with(
            RequestNodeInfoByMACAddress, mac_address=sentinel.mac
        )


@pytest.mark.rack_reactor_guard
class TestWindowsPXEBootMethod:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        mocker.patch.object(windows_module, "get_hivex_module")

    def test_clean_path(self):
        method = WindowsPXEBootMethod()
        parts = [factory.make_string() for _ in range(3)]
        dirty_path = "\\".join(parts)
        valid_path = dirty_path.lower().replace("\\", "/")
        clean_path = method.clean_path(dirty_path)
        assert valid_path == clean_path

    def test_clean_path_strip_boot(self):
        method = WindowsPXEBootMethod()
        dirty_path = "\\Boot\\BCD"
        clean_path = method.clean_path(dirty_path)
        assert "bcd" == clean_path

    def test_get_node_info(self, mocker):
        method = WindowsPXEBootMethod()
        mac = factory.make_mac_address()
        mocker.patch.object(
            windows_module, "get_remote_mac"
        ).return_value = mac
        mock_request_node_info = mocker.patch.object(
            windows_module, "request_node_info_by_mac_address"
        )
        method.get_node_info()
        mock_request_node_info.assert_called_once_with(mac)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_match_path_pxelinux(self, mocker):
        method = WindowsPXEBootMethod()
        method.remote_path = factory.make_string()
        mock_mac = factory.make_mac_address()
        mock_get_node_info = mocker.patch.object(method, "get_node_info")
        mock_get_node_info.return_value = {
            "purpose": "install",
            "osystem": "windows",
            "mac": mock_mac,
        }
        params = yield method.match_path(None, "pxelinux.0")
        assert mock_mac == params["mac"]
        assert method.bootloader_path == params["path"]

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_match_path_pxelinux_only_on_install(self, mocker):
        method = WindowsPXEBootMethod()
        method.remote_path = factory.make_string()
        mock_mac = factory.make_mac_address()
        mock_get_node_info = mocker.patch.object(method, "get_node_info")
        mock_get_node_info.return_value = {
            "purpose": factory.make_string(),
            "osystem": "windows",
            "mac": mock_mac,
        }
        params = yield method.match_path(None, "pxelinux.0")
        assert params is None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_match_path_pxelinux_missing_hivex(self, mocker):
        method = WindowsPXEBootMethod()
        method.remote_path = factory.make_string()
        mock_mac = factory.make_mac_address()
        mock_get_node_info = mocker.patch.object(method, "get_node_info")
        mock_get_node_info.return_value = {
            "purpose": factory.make_string(),
            "osystem": "windows",
            "mac": mock_mac,
        }
        mocker.patch.object(
            windows_module, "get_hivex_module", return_value=None
        )
        params = yield method.match_path(None, "pxelinux.0")
        assert params is None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_match_path_pxelinux_only_on_windows(self, mocker):
        method = WindowsPXEBootMethod()
        method.remote_path = factory.make_string()
        mock_mac = factory.make_mac_address()
        mock_get_node_info = mocker.patch.object(method, "get_node_info")
        mock_get_node_info.return_value = {
            "purpose": "install",
            "osystem": factory.make_string(),
            "mac": mock_mac,
        }
        params = yield method.match_path(None, "pxelinux.0")
        assert params is None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_match_path_pxelinux_get_node_info_None(self, mocker):
        method = WindowsPXEBootMethod()
        method.remote_path = factory.make_string()
        mock_get_node_info = mocker.patch.object(method, "get_node_info")
        mock_get_node_info.return_value = None
        params = yield method.match_path(None, "pxelinux.0")
        assert params is None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_match_path_lpxelinux(self, mocker):
        method = WindowsPXEBootMethod()
        method.remote_path = factory.make_string()
        mock_mac = factory.make_mac_address()
        mock_get_node_info = mocker.patch.object(method, "get_node_info")
        mock_get_node_info.return_value = {
            "purpose": "install",
            "osystem": "windows",
            "mac": mock_mac,
        }
        params = yield method.match_path(None, "lpxelinux.0")
        assert mock_mac == params["mac"]
        assert method.bootloader_path == params["path"]

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_match_path_lpxelinux_only_on_install(self, mocker):
        method = WindowsPXEBootMethod()
        method.remote_path = factory.make_string()
        mock_mac = factory.make_mac_address()
        mock_get_node_info = mocker.patch.object(method, "get_node_info")
        mock_get_node_info.return_value = {
            "purpose": factory.make_string(),
            "osystem": "windows",
            "mac": mock_mac,
        }
        params = yield method.match_path(None, "lpxelinux.0")
        assert params is None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_match_path_lpxelinux_missing_hivex(self, mocker):
        method = WindowsPXEBootMethod()
        method.remote_path = factory.make_string()
        mock_mac = factory.make_mac_address()
        mock_get_node_info = mocker.patch.object(method, "get_node_info")
        mock_get_node_info.return_value = {
            "purpose": factory.make_string(),
            "osystem": "windows",
            "mac": mock_mac,
        }
        mocker.patch.object(
            windows_module, "get_hivex_module", return_value=None
        )
        params = yield method.match_path(None, "lpxelinux.0")
        assert params is None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_match_path_lpxelinux_only_on_windows(self, mocker):
        method = WindowsPXEBootMethod()
        method.remote_path = factory.make_string()
        mock_mac = factory.make_mac_address()
        mock_get_node_info = mocker.patch.object(method, "get_node_info")
        mock_get_node_info.return_value = {
            "purpose": "install",
            "osystem": factory.make_string(),
            "mac": mock_mac,
        }
        params = yield method.match_path(None, "lpxelinux.0")
        assert params is None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_match_path_lpxelinux_get_node_info_None(self, mocker):
        method = WindowsPXEBootMethod()
        method.remote_path = factory.make_string()
        mock_get_node_info = mocker.patch.object(method, "get_node_info")
        mock_get_node_info.return_value = None
        params = yield method.match_path(None, "lpxelinux.0")
        assert params is None

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_match_path_static_file(self, mocker):
        method = WindowsPXEBootMethod()
        mock_mac = factory.make_mac_address()
        mock_get_node_info = mocker.patch.object(
            windows_module, "get_remote_mac"
        )
        mock_get_node_info.return_value = mock_mac
        params = yield method.match_path(None, "bootmgr.exe")
        assert mock_mac == params["mac"]
        assert "bootmgr.exe" == params["path"]

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_match_path_static_file_clean_path(self, mocker):
        method = WindowsPXEBootMethod()
        mock_mac = factory.make_mac_address()
        mock_get_node_info = mocker.patch.object(
            windows_module, "get_remote_mac"
        )
        mock_get_node_info.return_value = mock_mac
        params = yield method.match_path(None, "\\Boot\\BCD")
        assert mock_mac == params["mac"]
        assert "bcd" == params["path"]

    def test_get_reader_bcd(self, mocker):
        method = WindowsPXEBootMethod()
        mock_compose_bcd = mocker.patch.object(method, "compose_bcd")
        local_host = factory.make_ipv4_address()
        kernel_params = make_kernel_parameters(osystem="windows")
        method.get_reader(
            None, kernel_params, path="bcd", local_host=local_host
        )
        mock_compose_bcd.assert_called_once_with(kernel_params, local_host)

    def test_get_reader_static_file(self, mocker):
        method = WindowsPXEBootMethod()
        mock_path = factory.make_name("path")
        mock_output_static = mocker.patch.object(method, "output_static")
        kernel_params = make_kernel_parameters(osystem="windows")
        method.get_reader(None, kernel_params, path=mock_path)
        mock_output_static.assert_called_once_with(kernel_params, mock_path)

    def test_compose_preseed_url(self):
        url = "http://localhost/MAAS"
        expected = "http:\\\\localhost\\^M^A^A^S"
        method = WindowsPXEBootMethod()
        output = method.compose_preseed_url(url)
        assert expected == output

    def test_compose_bcd(self, mocker):
        method = WindowsPXEBootMethod()
        local_host = factory.make_ipv4_address()
        kernel_params = make_kernel_parameters()
        fake_output = factory.make_string().encode("utf-8")
        mocker.patch.object(os.path, "isfile").return_value = True
        mocker.patch.object(shutil, "copyfile")
        mocker.patch.object(windows_module, "Bcd")
        mocker.patch.object(windows_module, "open")
        windows_module.open.return_value = io.BytesIO(fake_output)
        output = method.compose_bcd(kernel_params, local_host)
        windows_module.open.assert_called_once_with(ANY, "rb")
        assert isinstance(output, BytesReader)
        assert fake_output == output.read(-1)

    def test_compose_bcd_missing_template(self, mocker):
        method = WindowsPXEBootMethod()
        mocker.patch.object(method, "get_resource_path").return_value = ""
        local_host = factory.make_ipv4_address()
        kernel_params = make_kernel_parameters()
        with pytest.raises(BootMethodError):
            method.compose_bcd(kernel_params, local_host)

    def test_get_resouce_path(self, tmp_path, request):
        fake_tftproot = str(tmp_path)
        config_fixture = ClusterConfigurationFixture(tftp_root=fake_tftproot)
        config_fixture.setUp()
        request.addfinalizer(config_fixture.cleanUp)
        method = WindowsPXEBootMethod()
        fake_path = factory.make_name("path")
        fake_kernelparams = make_kernel_parameters()
        result = method.get_resource_path(fake_kernelparams, fake_path)
        expected = os.path.join(
            fake_tftproot,
            "windows",
            fake_kernelparams.arch,
            fake_kernelparams.subarch,
            fake_kernelparams.release,
            fake_kernelparams.label,
            fake_path,
        )
        assert expected == result

    def test_output_static(self, tmp_path, mocker):
        method = WindowsPXEBootMethod()
        contents = factory.make_bytes()
        filename = factory.make_file(
            str(tmp_path), "resource", contents=contents
        )
        mocker.patch.object(
            method, "get_resource_path"
        ).return_value = filename
        result = method.output_static(None, None)
        assert isinstance(result, FilesystemReader)
        assert contents == result.read(10000)
