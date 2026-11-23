# Copyright 2024-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for ReserveIPs API."""

import http.client

from django.urls import reverse
import pytest
from twisted.internet import defer

import maasserver.api.reservedip as reservedip_module
from maasserver.dhcp import configure_dhcp_on_agents
from maasserver.models import ReservedIP
from maasserver.models.signals import subnet as subnet_signals_module
from maasserver.testing.factory import factory
from maasserver.utils.converters import json_load_bytes
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestReservedIPsAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request, mocker):
        user_kind, client_kind = api_identity.split(",")
        self.user = request.getfixturevalue(
            {"user=user": "maas_user"}[user_kind]
        )
        self.client = request.getfixturevalue(
            {"client=oauth": "api_client"}[client_kind]
        )
        mocker.patch.object(
            reservedip_module,
            "post_commit_do",
            return_value=defer.succeed(None),
        )
        mocker.patch.object(subnet_signals_module, "start_workflow")

    def test_handler_path(self):
        assert reverse("reservedips_handler") == "/MAAS/api/2.0/reservedips/"

    def test_read(self):
        uri = reverse("reservedips_handler")
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        factory.make_ReservedIP("10.0.0.121", subnet)
        factory.make_ReservedIP("10.0.0.105", subnet)
        factory.make_ReservedIP("10.0.0.15", subnet)

        response = self.client.get(uri)

        expected_ids = [
            reserved_ip.id for reserved_ip in ReservedIP.objects.all()
        ]
        ids = [
            reserved_ip["id"]
            for reserved_ip in json_load_bytes(response.content)
        ]
        assert response.status_code == 200
        assert ids.sort() == expected_ids.sort()

    def test_read_with_no_reserved_ips(self):
        uri = reverse("reservedips_handler")
        response = self.client.get(uri)

        assert response.status_code == http.client.OK
        assert json_load_bytes(response.content) == []

    def test_create_reserved_ip(self, admin_api_client):
        uri = reverse("reservedips_handler")
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")

        response = admin_api_client.post(
            uri,
            {
                "ip": "10.0.0.70",
                "subnet": subnet.id,
                "mac_address": "00:11:22:33:44:55",
                "comment": "this is a comment",
            },
        )

        status_code = response.status_code
        content = json_load_bytes(response.content)
        assert status_code == http.client.OK
        assert content["ip"] == "10.0.0.70"
        assert content["subnet"]["id"] == subnet.id
        assert content["mac_address"] == "00:11:22:33:44:55"
        assert content["comment"] == "this is a comment"

        reservedip_module.post_commit_do.assert_called_once_with(
            configure_dhcp_on_agents, reserved_ip_ids=[content["id"]]
        )

    def test_create_requires_admin(self):
        uri = reverse("reservedips_handler")
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")

        response = self.client.post(
            uri,
            {
                "ip": "10.0.0.70",
                "subnet": subnet.id,
                "mac_address": "01:02:03:04:05:06",
            },
        )

        assert response.status_code == http.client.FORBIDDEN, response.content


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestReservedIPAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request, mocker):
        user_kind, client_kind = api_identity.split(",")
        self.user = request.getfixturevalue(
            {"user=user": "maas_user"}[user_kind]
        )
        self.client = request.getfixturevalue(
            {"client=oauth": "api_client"}[client_kind]
        )
        mocker.patch.object(
            reservedip_module,
            "post_commit_do",
            return_value=defer.succeed(None),
        )
        mocker.patch.object(subnet_signals_module, "start_workflow")

    def test_handler_path(self):
        reserved_ip = factory.make_ReservedIP()
        assert reverse("reservedip_handler", args=[reserved_ip.id]) == (
            f"/MAAS/api/2.0/reservedips/{reserved_ip.id}/"
        )

    def test_read(self):
        reserved_ip = factory.make_ReservedIP()
        uri = reverse("reservedip_handler", args=[reserved_ip.id])

        response = self.client.get(uri)

        status_code = response.status_code
        content = json_load_bytes(response.content)
        assert status_code == http.client.OK
        assert content["id"] == reserved_ip.id
        assert content["ip"] == reserved_ip.ip
        assert content["subnet"]["id"] == reserved_ip.subnet.id
        assert content["mac_address"] == reserved_ip.mac_address
        assert content["comment"] == reserved_ip.comment

    def test_read_when_no_id_matches_the_request(self):
        uri = reverse("reservedip_handler", args=[101])
        response = self.client.get(uri)

        status_code = response.status_code
        assert status_code == http.client.NOT_FOUND

    def test_update(self, admin_api_client):
        reserved_ip = factory.make_ReservedIP()
        uri = reverse("reservedip_handler", args=[reserved_ip.id])

        response = admin_api_client.put(
            uri,
            {
                "ip": reserved_ip.ip,
                "mac_address": reserved_ip.mac_address,
                "comment": "updated comment",
            },
        )

        status_code = response.status_code
        content = json_load_bytes(response.content)
        assert status_code == http.client.OK
        assert content["id"] == reserved_ip.id
        assert content["ip"] == reserved_ip.ip
        assert content["subnet"]["id"] == reserved_ip.subnet.id
        assert content["mac_address"] == reserved_ip.mac_address
        assert content["comment"] == "updated comment"

        reservedip_module.post_commit_do.assert_not_called()

    def test_update_return_400_with_ip_in_different_subnet(
        self, admin_api_client
    ):
        factory.make_Subnet(cidr="192.168.0.0/24")
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        reserved_ip = factory.make_ReservedIP(ip="10.0.0.121", subnet=subnet)
        uri = reverse("reservedip_handler", args=[reserved_ip.id])

        response = admin_api_client.put(
            uri,
            {"ip": "192.168.0.45"},
        )

        status_code = response.status_code
        assert status_code == http.client.BAD_REQUEST
        reservedip_module.post_commit_do.assert_not_called()

    def test_update_returns_404_with_invalid_id(self, admin_api_client):
        uri = reverse("reservedip_handler", args=[101])

        response = admin_api_client.put(
            uri,
            {
                "ip": "10.0.0.45",
                "mac_address": "00:11:22:33:44:55",
                "comment": "updated comment",
            },
        )

        status_code = response.status_code
        assert status_code == http.client.NOT_FOUND

    def test_update_requires_admin(self):
        reserved_ip = factory.make_ReservedIP()
        uri = reverse("reservedip_handler", args=[reserved_ip.id])

        response = self.client.put(
            uri,
            {
                "ip": reserved_ip.ip,
                "mac_address": reserved_ip.mac_address,
                "comment": "updated comment",
            },
        )

        assert response.status_code == http.client.FORBIDDEN, response.content

    def test_delete(self, admin_api_client):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        reserved_ip = factory.make_ReservedIP(ip="10.0.0.121", subnet=subnet)
        uri = reverse("reservedip_handler", args=[reserved_ip.id])

        response = admin_api_client.delete(uri)

        status_code = response.status_code
        assert status_code == http.client.NO_CONTENT
        reservedip_module.post_commit_do.assert_called_once_with(
            configure_dhcp_on_agents, subnet_ids=[reserved_ip.subnet.id]
        )

    def test_delete_return_404_when_no_id_matches_the_request(
        self, admin_api_client
    ):
        uri = reverse("reservedip_handler", args=[101])
        response = admin_api_client.delete(uri)

        status_code = response.status_code
        assert status_code == http.client.NOT_FOUND
        reservedip_module.post_commit_do.assert_not_called()

    def test_delete_requires_admin(self):
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")
        reserved_ip = factory.make_ReservedIP(ip="10.0.0.121", subnet=subnet)
        uri = reverse("reservedip_handler", args=[reserved_ip.id])

        response = self.client.delete(uri)

        assert response.status_code == http.client.FORBIDDEN, response.content


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestReservedIPsOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request, mocker):
        user_kind, client_kind = api_identity.split(",")
        self.user = request.getfixturevalue(
            {"user=user": "maas_user"}[user_kind]
        )
        self.client = request.getfixturevalue(
            {"client=oauth": "api_client"}[client_kind]
        )
        mocker.patch.object(
            reservedip_module,
            "post_commit_do",
            return_value=defer.succeed(None),
        )
        mocker.patch.object(subnet_signals_module, "start_workflow")

    def test_create_requires_can_edit_global_entities(self):
        self.openfga_client.can_edit_global_entities.return_value = True
        uri = reverse("reservedips_handler")
        subnet = factory.make_Subnet(cidr="10.0.0.0/24")

        response = self.client.post(
            uri,
            {
                "ip": "10.0.0.70",
                "subnet": subnet.id,
                "mac_address": "01:02:03:04:05:06",
            },
        )

        assert response.status_code == http.client.OK, response.content
        self.openfga_client.can_edit_global_entities.assert_called_once_with(
            self.user
        )


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestReservedIPOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, request, mocker):
        user_kind, client_kind = api_identity.split(",")
        self.user = request.getfixturevalue(
            {"user=user": "maas_user"}[user_kind]
        )
        self.client = request.getfixturevalue(
            {"client=oauth": "api_client"}[client_kind]
        )
        mocker.patch.object(
            reservedip_module,
            "post_commit_do",
            return_value=defer.succeed(None),
        )
        mocker.patch.object(subnet_signals_module, "start_workflow")

    def test_update_requires_can_edit_global_entities(self):
        self.openfga_client.can_edit_global_entities.return_value = True
        reserved_ip = factory.make_ReservedIP()
        uri = reverse("reservedip_handler", args=[reserved_ip.id])

        response = self.client.put(
            uri,
            {
                "ip": reserved_ip.ip,
                "mac_address": reserved_ip.mac_address,
                "comment": "updated comment",
            },
        )

        assert response.status_code == http.client.OK, response.content
        self.openfga_client.can_edit_global_entities.assert_called_once_with(
            self.user
        )

    def test_delete_requires_can_edit_global_entities(self):
        self.openfga_client.can_edit_global_entities.return_value = True
        reserved_ip = factory.make_ReservedIP()
        uri = reverse("reservedip_handler", args=[reserved_ip.id])

        response = self.client.delete(uri)

        assert response.status_code == http.client.NO_CONTENT, response.content
        self.openfga_client.can_edit_global_entities.assert_called_once_with(
            self.user
        )
