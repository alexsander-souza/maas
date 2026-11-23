# Copyright 2015-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


import pytest

from provisioningserver.utils import snap, version
from provisioningserver.utils.version import (
    get_running_version,
    get_versions_info,
    MAASVersion,
)


@pytest.mark.parametrize(
    "version,maas_version,str_version,short_version,extended_info,qualifier_type_order,main_version",
    [
        (
            "1.2.3",
            MAASVersion(
                major=1,
                minor=2,
                point=3,
                qualifier_type=None,
                qualifier_version=0,
                revno=0,
                git_rev="",
            ),
            "1.2.3",
            "1.2.3",
            "",
            0,
            MAASVersion(
                major=1,
                minor=2,
                point=3,
                qualifier_type=None,
                qualifier_version=0,
            ),
        ),
        (
            "11.22.33~rc3",
            MAASVersion(
                major=11,
                minor=22,
                point=33,
                qualifier_type="rc",
                qualifier_version=3,
                revno=0,
                git_rev="",
            ),
            "11.22.33~rc3",
            "11.22.33~rc3",
            "",
            -1,
            MAASVersion(
                major=11,
                minor=22,
                point=33,
                qualifier_type="rc",
                qualifier_version=3,
            ),
        ),
        (
            "2.3.0~alpha3-6202-g54f83de-0ubuntu1~16.04.1",
            MAASVersion(
                major=2,
                minor=3,
                point=0,
                qualifier_type="alpha",
                qualifier_version=3,
                revno=6202,
                git_rev="54f83de",
            ),
            "2.3.0~alpha3-6202-g.54f83de",
            "2.3.0~alpha3",
            "6202-g.54f83de",
            -3,
            MAASVersion(
                major=2,
                minor=3,
                point=0,
                qualifier_type="alpha",
                qualifier_version=3,
            ),
        ),
        (
            "2.3.0~alpha3-6202-g54f83de-0ubuntu1~16.04.1-snap",
            MAASVersion(
                major=2,
                minor=3,
                point=0,
                qualifier_type="alpha",
                qualifier_version=3,
                revno=6202,
                git_rev="54f83de",
            ),
            "2.3.0~alpha3-6202-g.54f83de",
            "2.3.0~alpha3",
            "6202-g.54f83de",
            -3,
            MAASVersion(
                major=2,
                minor=3,
                point=0,
                qualifier_type="alpha",
                qualifier_version=3,
            ),
        ),
        (
            "2.3.0~alpha3-6202-g.54f83de-0ubuntu1~16.04.1",
            MAASVersion(
                major=2,
                minor=3,
                point=0,
                qualifier_type="alpha",
                qualifier_version=3,
                revno=6202,
                git_rev="54f83de",
            ),
            "2.3.0~alpha3-6202-g.54f83de",
            "2.3.0~alpha3",
            "6202-g.54f83de",
            -3,
            MAASVersion(
                major=2,
                minor=3,
                point=0,
                qualifier_type="alpha",
                qualifier_version=3,
            ),
        ),
    ],
    ids=[
        "version only",
        "version with qualifier",
        "full version",
        "full version with snap suffix",
        "full version with dotted git hash prefix",
    ],
)
class TestMAASVersionScenarios:
    def test_parse(
        self,
        version,
        maas_version,
        str_version,
        short_version,
        extended_info,
        qualifier_type_order,
        main_version,
    ):
        result = MAASVersion.from_string(version)
        assert result == maas_version
        assert result.short_version == short_version
        assert result.extended_info == extended_info
        assert result._qualifier_type_order == qualifier_type_order

    def test_string(
        self,
        version,
        maas_version,
        str_version,
        short_version,
        extended_info,
        qualifier_type_order,
        main_version,
    ):
        assert str(MAASVersion.from_string(version)) == str_version

    def test_short_version(
        self,
        version,
        maas_version,
        str_version,
        short_version,
        extended_info,
        qualifier_type_order,
        main_version,
    ):
        result = MAASVersion.from_string(version)
        assert result.main_version == main_version


class TestMAASVersion:
    def test_extended_info_no_git_hash_ignore_count(self):
        version = MAASVersion(
            major=2,
            minor=3,
            point=2,
            qualifier_type="alpha",
            qualifier_version=3,
            git_rev="54f83de",
        )
        assert version.extended_info == "g.54f83de"


class TestVersionTestCase:
    """MAASTestCase that resets the cache used by utility methods."""

    @pytest.fixture(autouse=True)
    def _clear_caches(self):
        for attribute in vars(version).values():
            if hasattr(attribute, "cache_clear"):
                attribute.cache_clear()


class TestGetRunningVersion(TestVersionTestCase):
    def test_uses_snap_get_snap_version(self, mocker):
        mocker.patch.object(
            snap, "get_snap_version"
        ).return_value = snap.SnapVersion(
            version="2.10.0-456-g.deadbeef",
            revision="1234",
        )
        maas_version = get_running_version()
        assert maas_version.short_version == "2.10.0"
        assert maas_version.extended_info == "456-g.deadbeef"

    def test_falls_back_to_distribution_version_when_not_in_snap(self, mocker):
        mocker.patch.object(snap, "get_snap_version").return_value = None
        distribution = mocker.patch.object(version, "DISTRIBUTION")
        distribution.version = "3.6.0-1-g.deadbeef"
        maas_version = get_running_version()
        assert maas_version.short_version == "3.6.0"
        assert maas_version.extended_info == "1-g.deadbeef"

    def test_method_is_cached(self, mocker):
        mock_get_snap_versions = mocker.patch.object(snap, "get_snap_version")
        mock_get_snap_versions.return_value = snap.SnapVersion(
            version="2.10.0-456-g.deadbeef",
            revision="1234",
        )
        version.get_running_version.cache_clear()

        first_return_value = version.get_running_version()
        second_return_value = version.get_running_version()
        # The return value is not empty (full unit tests have been performed
        # earlier).
        assert first_return_value not in [b"", "", None]
        assert first_return_value == second_return_value
        mock_get_snap_versions.assert_called_once()


class TestGetVersionsInfo:
    def test_get_versions_info_empty(self, mocker):
        mocker.patch.object(snap, "get_snap_versions_info").return_value = None
        assert get_versions_info() is None

    def test_get_versions_info_snap(self, mocker):
        versions_info = snap.SnapVersionsInfo(
            current=snap.SnapVersion(
                revision="1234", version="3.0.0~alpha1-111-g.deadbeef"
            ),
        )
        mock_get_snap_versions = mocker.patch.object(
            snap, "get_snap_versions_info"
        )
        mock_get_snap_versions.return_value = versions_info
        assert get_versions_info() == versions_info
        mock_get_snap_versions.assert_called_once()
