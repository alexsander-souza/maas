# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the top-level region RPC API."""

from unittest.mock import sentinel

import pytest
from twisted.internet.defer import inlineCallbacks

from maasserver import eventloop, rpc
from maastesting.crochet import wait_for
from provisioningserver.rpc import exceptions

wait_for_reactor = wait_for()


class TestFunctions:
    @wait_for_reactor
    @inlineCallbacks
    def test_getClientFor_service_not_running(self):
        with pytest.raises(
            exceptions.NoConnectionsAvailable,
            match="sentinel.uuid; no connections available",
        ):
            yield rpc.getClientFor(sentinel.uuid)

    @wait_for_reactor
    def test_getClientFor(self, mocker):
        getServiceNamed = mocker.patch.object(
            eventloop.services, "getServiceNamed"
        )
        getClientFor = getServiceNamed.return_value.getClientFor
        getClientFor.return_value = sentinel.client
        assert getClientFor(sentinel.uuid) is sentinel.client
        getClientFor.assert_called_once_with(sentinel.uuid)

    @wait_for_reactor
    def test_getAllClients_service_not_running(self):
        assert [] == rpc.getAllClients()

    @wait_for_reactor
    def test_getAllClients(self, mocker):
        getServiceNamed = mocker.patch.object(
            eventloop.services, "getServiceNamed"
        )
        getAllClients = getServiceNamed.return_value.getAllClients
        getAllClients.return_value = sentinel.clients
        assert getAllClients() is sentinel.clients
        getAllClients.assert_called_once_with()
