# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the removed VM host (KVM) API endpoints.

VM host support has been removed from MAAS. The endpoints are kept for
backwards compatibility but must respond with HTTP 410 Gone.
"""

import http.client

from django.urls import reverse
import pytest


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestVmHostEndpointsGone:
    @pytest.mark.parametrize(
        "uri_name,args,gone_methods",
        [
            pytest.param("pods_handler", [], ["get", "post"], id="pods"),
            pytest.param(
                "pod_handler", ["1"], ["get", "put", "delete"], id="pod"
            ),
            pytest.param(
                "vm_hosts_handler", [], ["get", "post"], id="vm_hosts"
            ),
            pytest.param(
                "vm_host_handler",
                ["1"],
                ["get", "put", "delete"],
                id="vm_host",
            ),
            pytest.param("vm_clusters_handler", [], ["get"], id="vm_clusters"),
            pytest.param(
                "vm_cluster_handler",
                ["1"],
                ["get", "put", "delete"],
                id="vm_cluster",
            ),
            pytest.param(
                "virtual_machines_handler", [], ["get"], id="virtual_machines"
            ),
            pytest.param(
                "virtual_machine_handler", ["1"], ["get"], id="virtual_machine"
            ),
        ],
    )
    def test_endpoints_return_gone(
        self, api_identity, api_client, uri_name, args, gone_methods
    ):
        uri = reverse(uri_name, args=args)
        for method in gone_methods:
            response = getattr(api_client, method)(uri)
            assert http.client.GONE == response.status_code, (
                f"{method.upper()} {uri} did not return 410 Gone"
            )
            assert b"removed" in response.content
