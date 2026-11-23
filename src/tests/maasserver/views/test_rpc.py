# Copyright 2014-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from collections import Counter
import json

from django.urls import reverse
import pytest
from twisted.internet.defer import inlineCallbacks

from maasserver import eventloop, ipc
from maasserver.testing.eventloop import RegionEventLoopFixture
from maasserver.testing.testclient import MAASSensibleClient
from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from metadataserver.builtin_scripts import load_builtin_scripts
from provisioningserver.utils.testing import MAASIDFixture

TIMEOUT = get_testing_timeout()


@pytest.fixture
def client(mocker, maasdb, maas_region_test):
    mocker.patch.object(
        ipc, "get_all_interface_source_addresses", return_value=set()
    )
    load_builtin_scripts()
    return MAASSensibleClient()


@pytest.mark.allow_transactions
@pytest.mark.usefixtures(
    "maasdb", "maas_region_test", "factory", "transactional_maasdb"
)
class TestRPCView:
    def test_rpc_info_empty(self, client):
        response = client.get(reverse("rpc-info"))
        assert "application/json" == response["Content-Type"]
        info = json.loads(response.content.decode("unicode_escape"))
        assert info.keys() == {"eventloops"}
        assert info["eventloops"] == {}

    def test_rpc_info_from_running_ipc_master(self, client, factory, request):
        # Run the IPC master, IPC worker, and RPC service so the endpoints
        # are updated in the database.
        region = factory.make_RegionController()
        maas_id_fixture = MAASIDFixture(region.system_id)
        maas_id_fixture.setUp()
        request.addfinalizer(maas_id_fixture.cleanUp)
        region.owner = factory.make_admin()
        region.save()
        # `workers` is only included so ipc-master will not actually get the
        # workers service because this test runs in all-in-one mode.
        event_loop_fixture = RegionEventLoopFixture(
            "ipc-master", "ipc-worker", "rpc", "workers"
        )
        event_loop_fixture.setUp()
        request.addfinalizer(event_loop_fixture.cleanUp)

        eventloop.start(master=True, all_in_one=True).wait(TIMEOUT)
        request.addfinalizer(lambda: eventloop.reset().wait(TIMEOUT))

        getServiceNamed = eventloop.services.getServiceNamed
        ipcMaster = getServiceNamed("ipc-master")

        @wait_for()
        @inlineCallbacks
        def wait_for_startup():
            # Wait for the service to complete startup.
            yield ipcMaster.starting
            yield getServiceNamed("ipc-worker").starting
            yield getServiceNamed("rpc").starting
            # Force an update, because it's very hard to track when the
            # first iteration of the ipc-master service has completed.
            yield ipcMaster.update()

        wait_for_startup()

        response = client.get(reverse("rpc-info"))

        assert "application/json" == response["Content-Type"]
        info = json.loads(response.content.decode("unicode_escape"))
        assert info.keys() == {"eventloops"}
        eventloops = info["eventloops"]
        assert eventloops.keys() == {eventloop.loop.name}
        endpoints = eventloops[eventloop.loop.name]
        ips, ports = zip(*endpoints, strict=True)
        expected_ips, _ = zip(
            *ipcMaster._getListenAddresses(5240), strict=True
        )
        # Each entry in the endpoints dict is a mapping from an event
        # loop to a list of (host, port) tuples. Each tuple is a
        # potential endpoint for connecting into that event loop.
        assert Counter(ips) == Counter(expected_ips)
        for port in ports:
            assert isinstance(port, int)
            assert port > 0
            assert port < 2**16
