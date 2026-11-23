# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the top-level cluster RPC API."""

import pytest

import provisioningserver
from provisioningserver.rpc.exceptions import NoConnectionsAvailable


class TestUtilities:
    def test_get_rpc_client_returns_client(self, mocker):
        services = mocker.patch.object(provisioningserver, "services")

        client = provisioningserver.rpc.getRegionClient()
        assert services.getServiceNamed("rpc").getClient() == client

    def test_error_when_cluster_services_are_down(self, mocker):
        services = mocker.patch.object(provisioningserver, "services")
        services.getServiceNamed.side_effect = KeyError
        with pytest.raises(NoConnectionsAvailable):
            provisioningserver.rpc.getRegionClient()
