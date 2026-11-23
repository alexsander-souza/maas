# Copyright 2021-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE)

import dataclasses
from unittest.mock import sentinel

import pytest
from twisted.internet import defer
from twisted.internet.defer import inlineCallbacks

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from provisioningserver import services
from provisioningserver.rackdservices import version_update_check
from provisioningserver.rackdservices.version_update_check import (
    RackVersionUpdateCheckService,
    VersionUpdateCheckService,
)
from provisioningserver.rpc import clusterservice
from provisioningserver.rpc.region import UpdateControllerState
from provisioningserver.rpc.testing import MockLiveClusterToRegionRPCFixture
from provisioningserver.utils.snap import (
    SnapChannel,
    SnapVersion,
    SnapVersionsInfo,
)

TIMEOUT = get_testing_timeout()


@inlineCallbacks
def _cleanup_rpc_fixture(fixture, shutdown):
    try:
        yield shutdown()
    finally:
        yield fixture.cleanUp()


class SampleVersionUpdateCheckService(VersionUpdateCheckService):
    def __init__(self, clock=None):
        super().__init__(clock=clock)
        self.calls = []

    @inlineCallbacks
    def process_versions_info(self, versions_info):
        self.calls.append(versions_info)
        yield


@pytest.mark.rack_reactor_guard
class TestVersionUpdateCheckService:
    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_process_version_info_not_called_without_versions(self, mocker):
        service = SampleVersionUpdateCheckService()
        mocker.patch.object(
            version_update_check, "get_versions_info"
        ).return_value = None
        yield service.do_action()
        assert service.calls == []

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_process_version_called_with_versions(self, mocker):
        service = SampleVersionUpdateCheckService()
        mocker.patch.object(
            version_update_check, "get_versions_info"
        ).return_value = sentinel.versions_info
        yield service.do_action()
        assert service.calls == [sentinel.versions_info]


@pytest.mark.rack_reactor_guard
class TestRackVersionUpdateCheckService:
    @inlineCallbacks
    def create_fake_rpc_service(self, request, mocker):
        fixture = MockLiveClusterToRegionRPCFixture()
        shutdown = [lambda: defer.succeed(None)]
        request.addfinalizer(
            lambda: wait_for(timeout=TIMEOUT)(_cleanup_rpc_fixture)(
                fixture, shutdown[0]
            )
        )
        yield fixture.setUp()
        mocker.patch.object(
            clusterservice, "get_all_interfaces_definition"
        ).return_value = {}
        protocol, connecting = fixture.makeEventLoop(UpdateControllerState)
        shutdown[0] = yield connecting
        return protocol

    def test_get_versions_state_in_snap(self):
        service = RackVersionUpdateCheckService(None)
        versions_info = SnapVersionsInfo(
            current=SnapVersion(
                revision="1234", version="3.0.0~alpha1-111-g.deadbeef"
            ),
            channel=SnapChannel(track="3.0"),
            update=SnapVersion(
                revision="5678", version="3.0.0~alpha2-222-g.cafecafe"
            ),
        )
        assert service._get_state(versions_info) == {
            "snap": dataclasses.asdict(versions_info),
        }

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_sends_version_state_update(self, request, mocker):
        protocol = yield self.create_fake_rpc_service(request, mocker)
        rpc_service = services.getServiceNamed("rpc")
        service = RackVersionUpdateCheckService(rpc_service)
        versions_info = SnapVersionsInfo(
            current=SnapVersion(
                revision="1234", version="3.0.0~alpha1-111-g.deadbeef"
            ),
            channel=SnapChannel(track="3.0"),
            update=SnapVersion(
                revision="5678", version="3.0.0~alpha2-222-g.cafecafe"
            ),
        )
        mocker.patch.object(
            version_update_check, "get_versions_info"
        ).return_value = versions_info
        service.startService()
        yield service.stopService()
        protocol.UpdateControllerState.assert_called_once_with(
            protocol,
            system_id=rpc_service.getClient().localIdent,
            scope="versions",
            state={
                "snap": dataclasses.asdict(versions_info),
            },
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_process_version_info_not_called_without_client(
        self, request, mocker
    ):
        protocol = yield self.create_fake_rpc_service(request, mocker)
        rpc_service = services.getServiceNamed("rpc")
        service = RackVersionUpdateCheckService(rpc_service)
        mocker.patch.object(
            version_update_check, "get_versions_info"
        ).return_value = sentinel.version_info

        mocker.patch.object(service, "_getRPCClient").return_value = None
        service.startService()
        yield service.stopService()
        protocol.UpdateControllerState.assert_not_called()
