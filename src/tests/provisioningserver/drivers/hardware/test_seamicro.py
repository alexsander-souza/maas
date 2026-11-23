# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `provisioningserver.drivers.hardware.seamicro`."""

import json
from unittest.mock import call, Mock
import urllib.parse

import pytest
from twisted.internet.defer import inlineCallbacks
from twisted.internet.threads import deferToThread

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.factory import factory
from provisioningserver.drivers.hardware import seamicro
from provisioningserver.drivers.hardware.seamicro import (
    find_seamicro15k_servers,
    power_control_seamicro15k_v09,
    power_control_seamicro15k_v2,
    power_query_seamicro15k_v2,
    POWER_STATUS,
    probe_seamicro15k_and_enlist,
    SeaMicroAPIV09,
    SeaMicroAPIV09Error,
    SeaMicroError,
    select_seamicro15k_api_version,
)
from provisioningserver.utils.twisted import asynchronous


class FakeResponse:
    def __init__(self, response_code, response, is_json=False):
        self.response_code = response_code
        if is_json:
            response = json.dumps(response)
        self.response = response

    def getcode(self):
        return self.response_code

    def read(self):
        return self.response

    def close(self):
        pass


class FakeServer:
    def __init__(self, id):
        self.id = id
        self.nic = {}
        self.active = False

    def add_fake_nic(self, id):
        self.nic[id] = {"macAddr": factory.make_mac_address()}

    def get_fake_macs(self):
        return [nic["macAddr"] for nic in self.nic.values()]


class FakeSeaMicroServerManager:
    def __init__(self):
        self.servers = []

    def get(self, server_id):
        for server in self.servers:
            if server_id == server.id:
                return server
        return None

    def list(self):
        return self.servers


class FakeSeaMicroClient:
    pass


class TestSeaMicroAPIV09:
    """Tests for SeaMicroAPIV09."""

    def test_build_url(self):
        url = factory.make_string()
        api = SeaMicroAPIV09("http://%s/" % url)
        location = factory.make_string()
        params = [factory.make_string() for _ in range(3)]
        output = api.build_url(location, params)
        parsed = urllib.parse.urlparse(output)
        assert url == parsed.netloc
        assert location == parsed.path.split("/")[1]
        assert params == parsed.query.split("&")

    def test_invalid_reponse_code(self):
        url = "http://%s/" % factory.make_string()
        api = SeaMicroAPIV09(url)
        response = FakeResponse(401, "Unauthorized")
        with pytest.raises(SeaMicroAPIV09Error):
            api.parse_response(url, response)

    def test_invalid_json_response(self):
        url = "http://%s/" % factory.make_string()
        api = SeaMicroAPIV09(url)
        response = FakeResponse(200, factory.make_string())
        with pytest.raises(SeaMicroAPIV09Error):
            api.parse_response(url, response)

    def test_json_error_response(self):
        url = "http://%s/" % factory.make_string()
        api = SeaMicroAPIV09(url)
        data = {"error": {"code": 401}}
        response = FakeResponse(200, data, is_json=True)
        with pytest.raises(SeaMicroAPIV09Error):
            api.parse_response(url, response)

    def test_json_valid_response(self):
        url = "http://%s/" % factory.make_string()
        api = SeaMicroAPIV09(url)
        output = factory.make_string()
        data = {"error": {"code": 200}, "result": {"data": output}}
        response = FakeResponse(200, data, is_json=True)
        result = api.parse_response(url, response)
        assert output == result["result"]["data"]

    def configure_get_result(self, mocker, result=None):
        mocker.patch.object(SeaMicroAPIV09, "get", Mock(return_value=result))

    def test_login_and_logout(self, mocker):
        token = factory.make_string()
        self.configure_get_result(mocker, token)
        url = "http://%s/" % factory.make_string()
        api = SeaMicroAPIV09(url)
        api.login("username", "password")
        assert token == api.token
        api.logout()
        assert api.token is None

    def test_get_server_index(self, mocker):
        result = {"serverId": {0: "0/0", 1: "1/0", 2: "2/0"}}
        self.configure_get_result(mocker, result)
        url = "http://%s/" % factory.make_string()
        api = SeaMicroAPIV09(url)
        assert 0 == api.server_index("0/0")
        assert 1 == api.server_index("1/0")
        assert 2 == api.server_index("2/0")
        assert api.server_index("3/0") is None

    def configure_put_server_power(self, mocker, token=None):
        result = {"serverId": {0: "0/0"}}
        self.configure_get_result(mocker, result)
        mock = mocker.patch.object(SeaMicroAPIV09, "put")
        url = "http://%s/" % factory.make_string()
        api = SeaMicroAPIV09(url)
        api.token = token
        return mock, api

    def assert_put_power_called(self, mock, idx, new_status, *params):
        location = "servers/%d" % idx
        params = ["action=%s" % new_status] + list(params)
        mock.assert_called_once_with(location, params=params)

    def test_put_server_power_on_using_pxe(self, mocker):
        token = factory.make_string()
        mock, api = self.configure_put_server_power(mocker, token)
        api.power_on("0/0", do_pxe=True)
        self.assert_put_power_called(
            mock, 0, POWER_STATUS.ON, "using-pxe=true", token
        )

    def test_put_server_power_on_not_using_pxe(self, mocker):
        token = factory.make_string()
        mock, api = self.configure_put_server_power(mocker, token)
        api.power_on("0/0", do_pxe=False)
        self.assert_put_power_called(
            mock, 0, POWER_STATUS.ON, "using-pxe=false", token
        )

    def test_put_server_power_reset_using_pxe(self, mocker):
        token = factory.make_string()
        mock, api = self.configure_put_server_power(mocker, token)
        api.reset("0/0", do_pxe=True)
        self.assert_put_power_called(
            mock, 0, POWER_STATUS.RESET, "using-pxe=true", token
        )

    def test_put_server_power_reset_not_using_pxe(self, mocker):
        token = factory.make_string()
        mock, api = self.configure_put_server_power(mocker, token)
        api.reset("0/0", do_pxe=False)
        self.assert_put_power_called(
            mock, 0, POWER_STATUS.RESET, "using-pxe=false", token
        )

    def test_put_server_power_off(self, mocker):
        token = factory.make_string()
        mock, api = self.configure_put_server_power(mocker, token)
        api.power_off("0/0", force=False)
        self.assert_put_power_called(
            mock, 0, POWER_STATUS.OFF, "force=false", token
        )

    def test_put_server_power_off_force(self, mocker):
        token = factory.make_string()
        mock, api = self.configure_put_server_power(mocker, token)
        api.power_off("0/0", force=True)
        self.assert_put_power_called(
            mock, 0, POWER_STATUS.OFF, "force=true", token
        )


@pytest.mark.rack_reactor_guard
class TestSeaMicro:
    """Tests for SeaMicro custom hardware."""

    def test_select_seamicro15k_api_version_ipmi(self):
        versions = select_seamicro15k_api_version("ipmi")
        assert ["v2.0", "v0.9"] == versions

    def test_select_seamicro15k_api_version_restapi(self):
        versions = select_seamicro15k_api_version("restapi")
        assert ["v0.9"] == versions

    def test_select_seamicro15k_api_version_restapi2(self):
        versions = select_seamicro15k_api_version("restapi2")
        assert ["v2.0"] == versions

    def configure_get_seamicro15k_api(self, mocker, return_value=None):
        ip = factory.make_ipv4_address()
        username = factory.make_string()
        password = factory.make_string()
        mock = mocker.patch.object(seamicro, "get_seamicro15k_api")
        mock.return_value = return_value
        return mock, ip, username, password

    def test_find_seamicro15k_servers_impi(self, mocker):
        mock, ip, username, password = self.configure_get_seamicro15k_api(
            mocker
        )
        with pytest.raises(SeaMicroError):
            find_seamicro15k_servers(ip, username, password, "ipmi")
        mock.assert_has_calls(
            [
                call("v2.0", ip, username, password),
                call("v0.9", ip, username, password),
            ]
        )

    def test_find_seamicro15k_servers_restapi(self, mocker):
        mock, ip, username, password = self.configure_get_seamicro15k_api(
            mocker
        )
        with pytest.raises(SeaMicroError):
            find_seamicro15k_servers(ip, username, password, "restapi")
        mock.assert_called_once_with("v0.9", ip, username, password)

    def test_find_seamicro15k_servers_restapi2(self, mocker):
        mock, ip, username, password = self.configure_get_seamicro15k_api(
            mocker
        )
        with pytest.raises(SeaMicroError):
            find_seamicro15k_servers(ip, username, password, "restapi2")
        mock.assert_called_once_with("v2.0", ip, username, password)

    def configure_api_v09_login(self, mocker, token=None):
        token = token or factory.make_string()
        mock = mocker.patch.object(SeaMicroAPIV09, "login")
        mock.return_value = token
        return mock

    @wait_for(timeout=get_testing_timeout())
    @inlineCallbacks
    def test_probe_seamicro15k_and_enlist_v09(self, mocker):
        self.configure_api_v09_login(mocker)
        user = factory.make_name("user")
        ip = factory.make_ipv4_address()
        username = factory.make_name("username")
        password = factory.make_name("password")
        system_id = factory.make_name("system_id")
        domain = factory.make_name("domain")
        result = {
            0: {
                "serverId": "0/0",
                "serverNIC": "0",
                "serverMacAddr": factory.make_mac_address(),
            },
            1: {
                "serverId": "1/0",
                "serverNIC": "0",
                "serverMacAddr": factory.make_mac_address(),
            },
            2: {
                "serverId": "2/0",
                "serverNIC": "0",
                "serverMacAddr": factory.make_mac_address(),
            },
            3: {
                "serverId": "3/1",
                "serverNIC": "1",
                "serverMacAddr": factory.make_mac_address(),
            },
        }
        mocker.patch.object(SeaMicroAPIV09, "get", Mock(return_value=result))
        mock_create_node = mocker.patch.object(seamicro, "create_node")
        mock_create_node.side_effect = asynchronous(lambda *_, **__: system_id)
        mock_commission_node = mocker.patch.object(seamicro, "commission_node")

        yield deferToThread(
            probe_seamicro15k_and_enlist,
            user,
            ip,
            username,
            password,
            power_control="restapi",
            accept_all=True,
            domain=domain,
        )
        assert 3 == mock_create_node.call_count

        last = result[2]
        power_params = {
            "power_control": "restapi",
            "system_id": last["serverId"].split("/")[0],
            "power_address": ip,
            "power_pass": password,
            "power_user": username,
        }
        mock_create_node.assert_called_with(
            last["serverMacAddr"],
            "amd64",
            "sm15k",
            power_params,
            domain=domain,
        )
        mock_commission_node.assert_called_with(system_id, user)

    def test_power_control_seamicro15k_v09(self, mocker):
        self.configure_api_v09_login(mocker)
        ip = factory.make_ipv4_address()
        username = factory.make_string()
        password = factory.make_string()
        mock = mocker.patch.object(SeaMicroAPIV09, "power_server")

        power_control_seamicro15k_v09(ip, username, password, "25", "on")
        mock.assert_called_once_with("25/0", POWER_STATUS.ON, do_pxe=True)

    def test_power_control_seamicro15k_v09_retry_failure(self, mocker):
        self.configure_api_v09_login(mocker)
        ip = factory.make_ipv4_address()
        username = factory.make_string()
        password = factory.make_string()
        mock = mocker.patch.object(SeaMicroAPIV09, "power_server")
        mock.side_effect = SeaMicroAPIV09Error("mock error", response_code=401)

        power_control_seamicro15k_v09(
            ip, username, password, "25", "on", retry_count=5, retry_wait=0
        )
        assert 5 == mock.call_count

    def test_power_control_seamicro15k_v09_exception_failure(self, mocker):
        self.configure_api_v09_login(mocker)
        ip = factory.make_ipv4_address()
        username = factory.make_string()
        password = factory.make_string()
        mock = mocker.patch.object(SeaMicroAPIV09, "power_server")
        mock.side_effect = SeaMicroAPIV09Error("mock error")

        with pytest.raises(SeaMicroAPIV09Error):
            power_control_seamicro15k_v09(ip, username, password, "25", "on")

    @wait_for(timeout=get_testing_timeout())
    @inlineCallbacks
    def test_probe_seamicro15k_and_enlist_v2(self, mocker):
        user = factory.make_name("user")
        ip = factory.make_ipv4_address()
        username = factory.make_name("username")
        password = factory.make_name("password")
        system_id = factory.make_name("system_id")

        fake_server_0 = FakeServer("0/0")
        fake_server_0.add_fake_nic("0")
        fake_server_0.add_fake_nic("1")
        fake_server_1 = FakeServer("1/0")
        fake_server_1.add_fake_nic("0")
        fake_server_1.add_fake_nic("1")
        fake_client = FakeSeaMicroClient()
        fake_client.servers = FakeSeaMicroServerManager()
        fake_client.servers.servers.append(fake_server_0)
        fake_client.servers.servers.append(fake_server_1)
        mock_get_api = mocker.patch.object(seamicro, "get_seamicro15k_api")
        mock_get_api.return_value = fake_client
        mock_create_node = mocker.patch.object(seamicro, "create_node")
        mock_create_node.side_effect = asynchronous(lambda *_, **__: system_id)
        mock_commission_node = mocker.patch.object(seamicro, "commission_node")

        yield deferToThread(
            probe_seamicro15k_and_enlist,
            user,
            ip,
            username,
            password,
            power_control="restapi2",
            accept_all=True,
        )
        assert 2 == mock_create_node.call_count

        mock_create_node.assert_has_calls(
            [
                call(
                    fake_server_0.get_fake_macs(),
                    "amd64",
                    "sm15k",
                    {
                        "power_control": "restapi2",
                        "system_id": "0",
                        "power_address": ip,
                        "power_pass": password,
                        "power_user": username,
                    },
                    domain=None,
                ),
                call(
                    fake_server_1.get_fake_macs(),
                    "amd64",
                    "sm15k",
                    {
                        "power_control": "restapi2",
                        "system_id": "1",
                        "power_address": ip,
                        "power_pass": password,
                        "power_user": username,
                    },
                    domain=None,
                ),
            ]
        )
        mock_commission_node.assert_called_with(system_id, user)

    def test_power_control_seamicro15k_v2(self, mocker):
        ip = factory.make_ipv4_address()
        username = factory.make_string()
        password = factory.make_string()

        fake_server = FakeServer("0/0")
        fake_client = FakeSeaMicroClient()
        fake_client.servers = FakeSeaMicroServerManager()
        fake_client.servers.servers.append(fake_server)
        mock_power_on = mocker.patch.object(
            fake_server, "power_on", create=True
        )

        mock_get_api = mocker.patch.object(seamicro, "get_seamicro15k_api")
        mock_get_api.return_value = fake_client

        power_control_seamicro15k_v2(ip, username, password, "0", "on")
        mock_power_on.assert_called_once_with(using_pxe=True)

    def test_power_control_seamicro15k_v2_raises_error_when_api_None(
        self, mocker
    ):
        ip = factory.make_ipv4_address()
        username = factory.make_string()
        password = factory.make_string()

        mock_get_api = mocker.patch.object(seamicro, "get_seamicro15k_api")
        mock_get_api.return_value = None

        with pytest.raises(SeaMicroError):
            power_control_seamicro15k_v2(ip, username, password, "0", "on")

    def test_power_query_seamicro15k_v2_power_on(self, mocker):
        ip = factory.make_ipv4_address()
        username = factory.make_string()
        password = factory.make_string()

        fake_server = FakeServer("0/0")
        mocker.patch.object(fake_server, "active", True)
        fake_client = FakeSeaMicroClient()
        fake_client.servers = FakeSeaMicroServerManager()
        fake_client.servers.servers.append(fake_server)

        mock_get_api = mocker.patch.object(seamicro, "get_seamicro15k_api")
        mock_get_api.return_value = fake_client

        assert "on" == power_query_seamicro15k_v2(ip, username, password, "0")

    def test_power_query_seamicro15k_v2_power_off(self, mocker):
        ip = factory.make_ipv4_address()
        username = factory.make_string()
        password = factory.make_string()

        fake_server = FakeServer("0/0")
        mocker.patch.object(fake_server, "active", False)
        fake_client = FakeSeaMicroClient()
        fake_client.servers = FakeSeaMicroServerManager()
        fake_client.servers.servers.append(fake_server)

        mock_get_api = mocker.patch.object(seamicro, "get_seamicro15k_api")
        mock_get_api.return_value = fake_client

        assert "off" == power_query_seamicro15k_v2(ip, username, password, "0")

    def test_power_query_seamicro15k_v2_raises_error_when_api_None(
        self, mocker
    ):
        ip = factory.make_ipv4_address()
        username = factory.make_string()
        password = factory.make_string()

        mock_get_api = mocker.patch.object(seamicro, "get_seamicro15k_api")
        mock_get_api.return_value = None

        with pytest.raises(SeaMicroError):
            power_query_seamicro15k_v2(ip, username, password, "0")
