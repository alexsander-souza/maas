# Copyright 2016-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


import os
from pathlib import Path

import pytest
import yaml

from provisioningserver.utils import snap
from provisioningserver.utils.shell import ProcessResult
from provisioningserver.utils.snap import (
    get_snap_mode,
    get_snap_version,
    get_snap_versions_info,
    SnapChannel,
    SnapPaths,
    SnapVersion,
    SnapVersionsInfo,
)


class TestSnapPaths:
    def test_from_environ_no_env(self):
        paths = SnapPaths.from_environ(environ={})
        assert paths.snap is None
        assert paths.common is None
        assert paths.data is None

    def test_from_environ(self):
        paths = SnapPaths.from_environ(
            environ={
                "SNAP": "/snap/base",
                "SNAP_COMMON": "/snap/common",
                "SNAP_DATA": "/snap/data",
            }
        )
        assert paths.snap == Path("/snap/base")
        assert paths.common == Path("/snap/common")
        assert paths.data == Path("/snap/data")


class TestSnapChannel:
    def test_str_default(self):
        assert str(SnapChannel(track="latest")) == "latest/stable"

    def test_str_no_branch(self):
        assert str(SnapChannel(track="2.0", risk="beta")) == "2.0/beta"

    def test_str_with_branch(self):
        assert (
            str(SnapChannel(track="2.0", risk="beta", branch="test"))
            == "2.0/beta/test"
        )

    def test_from_string_no_branch(self):
        assert SnapChannel.from_string("2.0/beta") == SnapChannel(
            track="2.0", risk="beta"
        )

    def test_from_string_with_branch(self):
        assert SnapChannel.from_string("2.0/beta/test") == SnapChannel(
            track="2.0", risk="beta", branch="test"
        )

    def test_is_release_branch(self):
        assert not SnapChannel.from_string("2.0/beta").is_release_branch()
        assert not SnapChannel.from_string(
            "2.0/beta/branch"
        ).is_release_branch()
        assert not SnapChannel.from_string(
            "2.0/beta/ubuntu-20.04.4"
        ).is_release_branch()
        assert not SnapChannel.from_string(
            "2.0/beta/myubuntu-20.04"
        ).is_release_branch()
        assert SnapChannel.from_string(
            "2.0/beta/ubuntu-20.04"
        ).is_release_branch()

    def test_equal(self):
        assert SnapChannel.from_string("2.0/beta") == SnapChannel.from_string(
            "2.0/beta"
        )
        assert SnapChannel.from_string(
            "2.0/beta/ubuntu-20.04"
        ) == SnapChannel.from_string("2.0/beta/ubuntu-20.04")

    def test_not_equal(self):
        assert SnapChannel.from_string(
            "3.0/stable"
        ) != SnapChannel.from_string("3.1/stable")
        assert SnapChannel.from_string(
            "2.0/stable"
        ) != SnapChannel.from_string("2.0/beta")
        assert SnapChannel.from_string(
            "2.0/stable"
        ) != SnapChannel.from_string("2.0/stable/branch")
        assert SnapChannel.from_string(
            "2.0/beta/ubuntu-18.04"
        ) != SnapChannel.from_string("2.0/beta/ubuntu-20.04")
        assert SnapChannel.from_string(
            "2.0/beta/ubuntu-20.04"
        ) != SnapChannel.from_string("2.0/beta/mybranch")

    def test_less(self):
        assert SnapChannel.from_string("3.0/stable") < SnapChannel.from_string(
            "latest/stable"
        )
        assert SnapChannel.from_string("3.0/stable") < SnapChannel.from_string(
            "3.1/stable"
        )
        assert SnapChannel.from_string("3.0/stable") < SnapChannel.from_string(
            "3.0/beta"
        )
        assert SnapChannel.from_string("3.0/stable") < SnapChannel.from_string(
            "3.0/stable/branch"
        )
        assert SnapChannel.from_string("3.0/stable") < SnapChannel.from_string(
            "3.1/stable/ubuntu-20.04"
        )
        assert SnapChannel.from_string(
            "2.0/beta/ubuntu-18.04"
        ) < SnapChannel.from_string("2.0/beta/ubuntu-20.04")
        assert SnapChannel.from_string(
            "2.0/beta/mybranch"
        ) < SnapChannel.from_string("2.0/beta/ubuntu-20.04")


class TestGetSnapVersion:
    def test_get_snap_version_None_when_no_snap(self):
        assert get_snap_version(environ={}) is None

    def test_get_snap_version(self):
        environ = {
            "SNAP_VERSION": "3.0.0-456-g.deadbeef",
            "SNAP_REVISION": "1234",
        }
        assert get_snap_version(environ=environ) == SnapVersion(
            version="3.0.0-456-g.deadbeef",
            revision="1234",
        )


class TestGetSnapMode:
    def _write_snap_mode(self, mode, tmp_path):
        snap_common_path = tmp_path
        snap_mode_path = snap_common_path.joinpath("snap_mode")
        if mode is not None:
            snap_mode_path.write_text(mode, "utf-8")
        return snap_common_path

    def test_get_snap_mode_no_mode(self, tmp_path, monkeypatch):
        snap_common_path = self._write_snap_mode(None, tmp_path)
        monkeypatch.setenv("SNAP_COMMON", str(snap_common_path))
        assert get_snap_mode() is None

    def test_get_snap_mode_mode_none(self, tmp_path, monkeypatch):
        snap_common_path = self._write_snap_mode("none", tmp_path)
        monkeypatch.setenv("SNAP_COMMON", str(snap_common_path))
        assert get_snap_mode() is None

    def test_get_snap_mode_mode_other(self, tmp_path, monkeypatch):
        snap_common_path = self._write_snap_mode("rack+region", tmp_path)
        monkeypatch.setenv("SNAP_COMMON", str(snap_common_path))
        assert get_snap_mode() == "rack+region"


class TestSnapVersionsInfo:
    def test_deserialize(self):
        info = SnapVersionsInfo(
            current={
                "revision": "1234",
                "version": "3.0.0~alpha1-111-g.deadbeef",
            },
            channel={"track": "3.0", "risk": "stable"},
            update={
                "revision": "5678",
                "version": "3.0.0~alpha2-222-g.cafecafe",
            },
        )
        assert info.current == SnapVersion(
            revision="1234", version="3.0.0~alpha1-111-g.deadbeef"
        )
        assert info.channel == SnapChannel(track="3.0")
        assert info.update == SnapVersion(
            revision="5678", version="3.0.0~alpha2-222-g.cafecafe"
        )


class TestGetSnapVersionsInfo:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker, monkeypatch):
        monkeypatch.setattr(
            os,
            "environ",
            {
                "SNAP": "/snap/maas/1234",
                "SNAP_REVISION": "1234",
                "SNAP_VERSION": "3.0.0~alpha1-111-g.deadbeef",
            },
        )
        self.mocker = mocker

    def mock_snapctl_info(self, data=None, returncode=0):
        mock_snapctl = self.mocker.patch.object(snap, "run_command")
        mock_snapctl.return_value = ProcessResult(
            stdout=yaml.dump(data) if data else "",
            stderr="",
            returncode=returncode,
        )

    def test_get_snap_versions_failed_command(self):
        self.mock_snapctl_info(returncode=1)
        versions = get_snap_versions_info()
        assert versions == SnapVersionsInfo(
            current=SnapVersion(
                revision="1234", version="3.0.0~alpha1-111-g.deadbeef"
            ),
            channel=None,
            update=None,
            cohort="",
        )

    def test_get_snap_versions_info(self):
        self.mock_snapctl_info(
            data={
                "channel": "3.0/edge/fix-9991",
                "revision": 5678,
                "version": "3.0.0~alpha2-222-g.cafecafe",
            }
        )
        versions = get_snap_versions_info()
        assert versions == SnapVersionsInfo(
            current=SnapVersion(
                revision="1234", version="3.0.0~alpha1-111-g.deadbeef"
            ),
            channel=SnapChannel(track="3.0", risk="edge", branch="fix-9991"),
            update=SnapVersion(
                revision="5678", version="3.0.0~alpha2-222-g.cafecafe"
            ),
            cohort="",
        )

    def test_get_snap_versions_info_with_cohort(self):
        self.mock_snapctl_info(
            data={
                "channel": "3.0/stable",
                "cohort": "abcdef",
            }
        )
        versions = get_snap_versions_info()
        assert versions.cohort == "abcdef"

    def test_get_snap_version_info_no_update(self):
        self.mock_snapctl_info(data={"channel": "3.0/edge/fix-9991"})
        versions = get_snap_versions_info()
        assert versions == SnapVersionsInfo(
            current=SnapVersion(
                revision="1234", version="3.0.0~alpha1-111-g.deadbeef"
            ),
            channel=SnapChannel(track="3.0", risk="edge", branch="fix-9991"),
            update=None,
            cohort="",
        )
