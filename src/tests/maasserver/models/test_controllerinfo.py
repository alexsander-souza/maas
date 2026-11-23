# Copyright 2017-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


import pytest

from maasserver.models import ControllerInfo, Notification
from maasserver.models.controllerinfo import (
    get_maas_version,
    get_target_version,
    TargetVersion,
    UPGRADE_ISSUE_NOTIFICATION_IDENT,
    UPGRADE_STATUS_NOTIFICATION_IDENT,
    VERSION_ISSUES,
)
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object
from provisioningserver.utils.snap import SnapChannel, SnapVersionsInfo
from provisioningserver.utils.version import MAASVersion


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestControllerInfo:
    def test_str(self):
        controller = factory.make_RackController(hostname="foobar")
        info, _ = ControllerInfo.objects.update_or_create(node=controller)
        assert "ControllerInfo (foobar)" == str(info)

    def test_set_version(self):
        controller = factory.make_RackController()
        ControllerInfo.objects.set_version(controller, "2.3.0")
        assert controller.version == "2.3.0"

    def test_set_versions_info_snap(self):
        controller = factory.make_RackController()
        versions = SnapVersionsInfo(
            current={
                "revision": "1234",
                "version": "3.0.0~alpha1-111-g.deadbeef",
            },
            channel={"track": "3.0", "risk": "stable"},
            update={
                "revision": "5678",
                "version": "3.0.0~alpha2-222-g.cafecafe",
            },
            cohort="abc123",
        )
        ControllerInfo.objects.set_versions_info(controller, versions)
        controller_info = controller.controllerinfo
        assert controller_info.version == "3.0.0~alpha1-111-g.deadbeef"
        assert controller_info.update_version == "3.0.0~alpha2-222-g.cafecafe"
        assert controller_info.update_origin == "3.0/stable"
        assert controller_info.snap_revision == "1234"
        assert controller_info.snap_update_revision == "5678"
        assert controller_info.snap_cohort == "abc123"
        assert controller_info.update_first_reported is not None

    def test_set_versions_info_snap_no_update(self):
        controller = factory.make_RackController()
        versions = SnapVersionsInfo(
            current={
                "revision": "1234",
                "version": "3.0.0~alpha1-111-g.deadbeef",
            },
            channel={"track": "3.0", "risk": "stable"},
        )
        ControllerInfo.objects.set_versions_info(controller, versions)
        controller_info = controller.controllerinfo
        assert controller_info.update_origin == "3.0/stable"
        assert controller_info.snap_update_revision == ""
        assert controller_info.snap_cohort == ""
        assert controller_info.update_first_reported is None

    def test_set_versions_update_first_reported_update_same_update(self):
        controller = factory.make_RackController()
        versions = SnapVersionsInfo(
            current={
                "revision": "1234",
                "version": "3.0.0~alpha1-111-g.deadbeef",
            },
            update={
                "revision": "5678",
                "version": "3.0.0~alpha2-222-g.cafecafe",
            },
        )
        ControllerInfo.objects.set_versions_info(controller, versions)
        update_first_reported = controller.controllerinfo.update_first_reported
        versions = SnapVersionsInfo(
            current={
                "revision": "1234",
                "version": "3.0.0~alpha1-111-g.deadbeef",
            },
            update={
                "revision": "5678",
                "version": "3.0.0~alpha2-222-g.cafecafe",
            },
        )
        controller_info = reload_object(controller).controllerinfo
        assert controller_info.update_first_reported == update_first_reported

    def test_set_versions_update_first_reported_update_different_update(self):
        controller = factory.make_RackController()
        versions = SnapVersionsInfo(
            current={
                "revision": "1234",
                "version": "3.0.0~alpha1-111-g.deadbeef",
            },
            update={
                "revision": "5678",
                "version": "3.0.0~alpha2-222-g.cafecafe",
            },
        )
        ControllerInfo.objects.set_versions_info(controller, versions)
        update_first_reported = controller.controllerinfo.update_first_reported
        versions = SnapVersionsInfo(
            current={
                "revision": "1234",
                "version": "3.0.0~alpha1-111-g.deadbeef",
            },
            update={
                "revision": "5678",
                "version": "3.0.0~alpha3-333-g.adadadad",
            },
        )
        ControllerInfo.objects.set_versions_info(controller, versions)
        controller_info = reload_object(controller).controllerinfo
        assert controller_info.update_first_reported > update_first_reported

    def test_set_versions_update_first_reported_no_update(self):
        controller = factory.make_RackController()
        versions = SnapVersionsInfo(
            current={
                "revision": "1234",
                "version": "3.0.0~alpha1-111-g.deadbeef",
            },
            update={
                "revision": "5678",
                "version": "3.0.0~alpha2-222-g.cafecafe",
            },
        )
        ControllerInfo.objects.set_versions_info(controller, versions)
        versions = SnapVersionsInfo(
            current={
                "revision": "5678",
                "version": "3.0.0~alpha2-222-g.cafecafe",
            },
        )
        ControllerInfo.objects.set_versions_info(controller, versions)
        controller_info = reload_object(controller).controllerinfo
        assert controller_info.update_first_reported is None

    def test_is_up_to_date(self):
        version = "3.0.0~alpha1-111-g.deadbeef"
        target_version = TargetVersion(
            version=MAASVersion.from_string(version),
            snap_channel="3.0/stable",
        )
        controller = factory.make_RackController()
        ControllerInfo.objects.set_versions_info(
            controller,
            SnapVersionsInfo(
                current={
                    "revision": "1234",
                    "version": version,
                },
            ),
        )
        assert controller.info.is_up_to_date(target_version)

    def test_is_up_to_date_with_update(self):
        version = "3.0.0~alpha1-111-g.deadbeef"
        target_version = TargetVersion(
            version=MAASVersion.from_string(version),
            snap_channel="3.0/stable",
        )
        controller = factory.make_RackController()
        ControllerInfo.objects.set_versions_info(
            controller,
            SnapVersionsInfo(
                current={
                    "revision": "1234",
                    "version": version,
                },
                update={
                    "revision": "5678",
                    "version": "3.0.0-222-g.cafecafe",
                },
            ),
        )
        assert not controller.info.is_up_to_date(target_version)

    def test_is_up_to_date_with_different_version(self):
        target_version = TargetVersion(
            version=MAASVersion.from_string("3.0.0-222-g.cafecafe"),
            snap_channel="3.0/stable",
        )
        controller = factory.make_RackController()
        ControllerInfo.objects.set_versions_info(
            controller,
            SnapVersionsInfo(
                current={
                    "revision": "1234",
                    "version": "3.0.0~alpha1-111-g.deadbeef",
                },
            ),
        )
        assert not controller.info.is_up_to_date(target_version)

    def test_get_version_issues(self):
        target_version = TargetVersion(
            version=MAASVersion.from_string("3.0.0-222-g.cafecafe"),
            snap_channel="3.0/stable",
        )
        controller = factory.make_RackController()
        ControllerInfo.objects.set_versions_info(
            controller,
            SnapVersionsInfo(
                current={
                    "revision": "1234",
                    "version": "3.0.0~alpha1-111-g.deadbeef",
                },
                channel="3.0/beta",
                cohort="abc",
            ),
        )
        assert controller.info.get_version_issues(target_version) == [
            VERSION_ISSUES.DIFFERENT_CHANNEL.value,
            VERSION_ISSUES.DIFFERENT_COHORT.value,
        ]

    def test_get_version_issue_flags_missing_channel(self):
        target_version = TargetVersion(
            version=MAASVersion.from_string("3.1.0-222-g.cafecafe"),
            snap_channel=SnapChannel.from_string("3.1/stable"),
        )
        controller = factory.make_RegionRackController()
        ControllerInfo.objects.set_versions_info(
            controller,
            SnapVersionsInfo(
                current={
                    "revision": "1234",
                    "version": "3.1.0-222-g.cafecafe",
                },
            ),
        )
        assert controller.info.get_version_issues(target_version) == [
            VERSION_ISSUES.MISSING_CHANNEL.value,
        ]


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestGetTargetVersion:
    def test_empty(self):
        factory.make_RackController()
        assert get_target_version() is None

    def test_return_highest_version(self):
        c1 = factory.make_RackController()
        c2 = factory.make_RackController()
        c3 = factory.make_RackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0~alpha1-111-g.aaa", "revision": "1"}
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c2,
            SnapVersionsInfo(
                current={"version": "3.0.0~beta1-222-g.bbb", "revision": "1"}
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c3,
            SnapVersionsInfo(
                current={"version": "3.0.0-333-g.ccc", "revision": "1"}
            ),
        )
        target_version = get_target_version()
        assert target_version.version == MAASVersion.from_string(
            "3.0.0-333-g.ccc"
        )

    def test_return_highest_update(self):
        c1 = factory.make_RackController()
        c2 = factory.make_RackController()
        c3 = factory.make_RackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "2.9.0-001-g.zzz", "revision": "1"},
                update={"version": "3.0.0~alpha1-111-g.aaa", "revision": "1"},
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c2,
            SnapVersionsInfo(
                current={"version": "2.9.0-001-g.zzz", "revision": "1"},
                update={"version": "3.0.0~beta1-222-g.bbb", "revision": "1"},
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c3,
            SnapVersionsInfo(
                current={"version": "2.9.0-001-g.zzz", "revision": "1"},
                update={"version": "3.0.0-333-g.ccc", "revision": "1"},
            ),
        )
        target_version = get_target_version()
        assert target_version.version == MAASVersion.from_string(
            "3.0.0-333-g.ccc"
        )

        assert target_version.first_reported == c3.info.update_first_reported

    def test_update_return_earliest_reported(self):
        c1 = factory.make_RackController()
        c2 = factory.make_RackController()
        c3 = factory.make_RackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "2.9.0-001-g.zzz", "revision": "1"},
                update={"version": "3.0.0~alpha1-111-g.aaa", "revision": "1"},
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c2,
            SnapVersionsInfo(
                current={"version": "2.9.0-001-g.zzz", "revision": "1"},
                update={"version": "3.0.0-333-g.ccc", "revision": "1"},
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c3,
            SnapVersionsInfo(
                current={"version": "2.9.0-001-g.zzz", "revision": "1"},
                update={"version": "3.0.0-333-g.ccc", "revision": "1"},
            ),
        )
        target_version = get_target_version()
        assert target_version.version == MAASVersion.from_string(
            "3.0.0-333-g.ccc"
        )
        assert target_version.first_reported == c2.info.update_first_reported

    def test_update_older_than_installed(self):
        c1 = factory.make_RackController()
        c2 = factory.make_RackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1"},
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c2,
            SnapVersionsInfo(
                current={"version": "2.9.0-001-g.zzz", "revision": "1"},
                update={"version": "2.9.1-010-g.bbb", "revision": "1"},
            ),
        )
        target_version = get_target_version()
        assert target_version.version == MAASVersion.from_string(
            "3.0.0-111-g.aaa"
        )

    def test_snap_channel(self):
        c1 = factory.make_RackController()
        c2 = factory.make_RackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1234"},
                channel={"track": "3.0", "risk": "stable"},
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c2,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1234"},
                channel={"track": "3.0", "risk": "beta"},
            ),
        )
        target_version = get_target_version()
        # the most stable channel is returned
        assert target_version.snap_channel == SnapChannel("3.0", "stable")

    def test_snap_channel_no_branch(self):
        controller = factory.make_RackController()
        ControllerInfo.objects.set_versions_info(
            controller,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1234"},
                channel={"track": "3.0", "risk": "beta", "branch": "mybranch"},
            ),
        )
        target_version = get_target_version()
        assert target_version.snap_channel == SnapChannel("3.0", "beta")

    def test_snap_channel_keep_release_branch(self):
        controller = factory.make_RackController()
        ControllerInfo.objects.set_versions_info(
            controller,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1234"},
                channel={
                    "track": "3.0",
                    "risk": "beta",
                    "branch": "ubuntu-20.04",
                },
            ),
        )
        target_version = get_target_version()
        assert target_version.snap_channel == SnapChannel(
            "3.0", "beta", branch="ubuntu-20.04"
        )

    def test_snap_channel_from_version(self):
        c1 = factory.make_RackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0~rc1-111-g.aaa", "revision": "1"},
            ),
        )
        target_version = get_target_version()
        assert target_version.snap_channel == SnapChannel("3.0", "candidate")

    def test_snap_cohort_from_target_version(self):
        c1 = factory.make_RackController()
        c2 = factory.make_RackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1234"},
                cohort="abc",
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c2,
            SnapVersionsInfo(
                current={"version": "3.0.1-222-g.bbb", "revision": "5678"},
                cohort="xyz",
            ),
        )
        target_version = get_target_version()
        assert target_version.snap_cohort == "xyz"

    def test_snap_cohort_from_update(self):
        c1 = factory.make_RackController()
        c2 = factory.make_RackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1234"},
                cohort="abc",
                update={"version": "3.0.2-333-g.ccc", "revision": "7890"},
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c2,
            SnapVersionsInfo(
                current={"version": "3.0.1-222-g.bbb", "revision": "5678"},
                cohort="xyz",
            ),
        )
        target_version = get_target_version()
        assert target_version.snap_cohort == "abc"

    def test_snap_cohort_multiple_cohorts_target_version(self):
        c1 = factory.make_RackController()
        c2 = factory.make_RackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1234"},
                cohort="abc",
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c2,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1234"},
                cohort="xyz",
            ),
        )
        target_version = get_target_version()
        assert target_version.snap_cohort == ""


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestGetMAASVersion:
    def test_no_versions(self):
        factory.make_RegionRackController()
        factory.make_RegionRackController()
        assert get_maas_version() is None

    def test_version_with_highest_count(self):
        c1 = factory.make_RegionRackController()
        ControllerInfo.objects.set_version(c1, "3.0.0")
        c2 = factory.make_RegionRackController()
        ControllerInfo.objects.set_version(c2, "3.0.0")
        c3 = factory.make_RegionRackController()
        ControllerInfo.objects.set_version(c3, "3.1.0")
        assert get_maas_version() == MAASVersion.from_string("3.0.0")

    def test_highest_version_same_count(self):
        c1 = factory.make_RegionRackController()
        ControllerInfo.objects.set_version(c1, "3.0.0")
        c2 = factory.make_RegionRackController()
        ControllerInfo.objects.set_version(c2, "3.1.0")
        assert get_maas_version() == MAASVersion.from_string("3.1.0")

    def test_combine_versions_up_to_qualifier(self):
        c1 = factory.make_RegionRackController()
        ControllerInfo.objects.set_version(c1, "3.0.0~beta1-123-g.asdf")
        c2 = factory.make_RegionRackController()
        ControllerInfo.objects.set_version(c2, "3.0.0~beta2-456-g.cafe")
        c2 = factory.make_RegionRackController()
        ControllerInfo.objects.set_version(c2, "3.0.0~beta2-789-g.abcd")
        c3 = factory.make_RegionRackController()
        ControllerInfo.objects.set_version(c3, "3.1.0")
        assert get_maas_version() == MAASVersion.from_string("3.0.0~beta2")


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestUpdateVersionNotifications:
    def test_same_upgrade(self):
        c1 = factory.make_RegionRackController()
        c2 = factory.make_RegionRackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1"},
                update={"version": "3.0.1-222-g.bbb", "revision": "1"},
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c2,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1"},
                update={"version": "3.0.1-222-g.bbb", "revision": "1"},
            ),
        )
        assert not Notification.objects.filter(
            ident=UPGRADE_ISSUE_NOTIFICATION_IDENT
        ).exists()

    def test_different_versions(self):
        c1 = factory.make_RegionRackController()
        c2 = factory.make_RegionRackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1"},
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c2,
            SnapVersionsInfo(
                current={"version": "3.0.1-222-g.bbb", "revision": "1"},
            ),
        )
        notification = Notification.objects.filter(
            ident=UPGRADE_ISSUE_NOTIFICATION_IDENT
        ).first()
        assert "Controllers have different versions." in notification.message

    def test_different_upgrades(self):
        c1 = factory.make_RegionRackController()
        c2 = factory.make_RegionRackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1"},
                update={"version": "3.0.1-222-g.bbb", "revision": "1"},
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c2,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1"},
                update={"version": "3.0.2-333-g.ccc", "revision": "1"},
            ),
        )
        notification = Notification.objects.filter(
            ident=UPGRADE_ISSUE_NOTIFICATION_IDENT
        ).first()
        assert (
            "Controllers report different upgrade versions."
            in notification.message
        )

    def test_different_origins(self):
        c1 = factory.make_RegionRackController()
        c2 = factory.make_RegionRackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1234"},
                channel={"track": "3.0", "risk": "stable"},
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c2,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1234"},
                channel={"track": "3.0", "risk": "beta"},
            ),
        )
        notification = Notification.objects.filter(
            ident=UPGRADE_ISSUE_NOTIFICATION_IDENT
        ).first()
        assert (
            "Controllers have different installation sources."
            in notification.message
        )

    def test_different_snap_cohorts(self):
        c1 = factory.make_RegionRackController()
        c2 = factory.make_RegionRackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1234"},
                cohort="abc",
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c2,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1234"},
                cohort="xyz",
            ),
        )
        notification = Notification.objects.filter(
            ident=UPGRADE_ISSUE_NOTIFICATION_IDENT
        ).first()
        assert (
            "Controllers have different installation sources."
            in notification.message
        )

    def test_issue_resolved_removes_notification(self):
        c1 = factory.make_RegionRackController()
        c2 = factory.make_RegionRackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1234"},
                cohort="abc",
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c2,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1234"},
            ),
        )
        assert Notification.objects.filter(
            ident=UPGRADE_ISSUE_NOTIFICATION_IDENT
        ).exists()
        # remove the cohort
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1234"},
            ),
        )
        assert not Notification.objects.filter(
            ident=UPGRADE_ISSUE_NOTIFICATION_IDENT
        ).exists()

    def test_different_issue_new_notification(self):
        c1 = factory.make_RegionRackController()
        c2 = factory.make_RegionRackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1234"},
                channel={"track": "3.0", "risk": "stable"},
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c2,
            SnapVersionsInfo(
                current={"version": "3.0.0-111-g.aaa", "revision": "1234"},
                channel={"track": "3.0", "risk": "beta"},
            ),
        )
        notification1 = Notification.objects.filter(
            ident=UPGRADE_ISSUE_NOTIFICATION_IDENT
        ).first()
        assert (
            "Controllers have different installation sources."
            in notification1.message
        )
        ControllerInfo.objects.set_versions_info(
            c2,
            SnapVersionsInfo(
                current={"version": "3.0.2-222-g.bbb", "revision": "5678"},
                channel={"track": "3.0", "risk": "stable"},
            ),
        )
        notification2 = Notification.objects.filter(
            ident=UPGRADE_ISSUE_NOTIFICATION_IDENT
        ).first()
        assert "Controllers have different versions." in notification2.message
        assert notification1.id != notification2.id

    def test_update_status_update_available(self):
        c1 = factory.make_RegionRackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111.aaa", "revision": "1"},
                update={"version": "3.0.1-222-g.bbb", "revision": "1"},
            ),
        )
        notification = Notification.objects.filter(
            ident=UPGRADE_STATUS_NOTIFICATION_IDENT,
        ).first()
        assert notification.category == "info"
        assert (
            notification.render()
            == "MAAS 3.0.1 is available, controllers will upgrade soon."
        )
        assert notification.context == {
            "status": "inprogress",
            "version": "3.0.1",
        }

    def test_update_status_update_same_version(self):
        c1 = factory.make_RegionRackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111.aaa", "revision": "1"},
                update={"version": "3.0.1-222-g.bbb", "revision": "1"},
            ),
        )
        notification1 = Notification.objects.filter(
            ident=UPGRADE_STATUS_NOTIFICATION_IDENT,
        ).first()
        assert (
            notification1.render()
            == "MAAS 3.0.1 is available, controllers will upgrade soon."
        )
        # report again, same version
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111.aaa", "revision": "1"},
                update={"version": "3.0.1-222-g.bbb", "revision": "1"},
            ),
        )
        notification2 = Notification.objects.filter(
            ident=UPGRADE_STATUS_NOTIFICATION_IDENT,
        ).first()
        assert (
            notification2.render()
            == "MAAS 3.0.1 is available, controllers will upgrade soon."
        )
        assert notification2.context == {
            "status": "inprogress",
            "version": "3.0.1",
        }
        assert notification1.id == notification2.id

    def test_update_status_update_new_version(self):
        c1 = factory.make_RegionRackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111.aaa", "revision": "1"},
                update={"version": "3.0.1-222-g.bbb", "revision": "1"},
            ),
        )
        notification1 = Notification.objects.filter(
            ident=UPGRADE_STATUS_NOTIFICATION_IDENT,
        ).first()
        assert (
            notification1.render()
            == "MAAS 3.0.1 is available, controllers will upgrade soon."
        )
        # report again, but new upgrade version
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111.aaa", "revision": "1"},
                update={"version": "3.0.2-333-g.ccc", "revision": "1"},
            ),
        )
        notification2 = Notification.objects.filter(
            ident=UPGRADE_STATUS_NOTIFICATION_IDENT,
        ).first()
        assert (
            notification2.render()
            == "MAAS 3.0.2 is available, controllers will upgrade soon."
        )
        assert notification2.context == {
            "status": "inprogress",
            "version": "3.0.2",
        }
        assert notification1.id != notification2.id

    def test_update_status_update_completed(self):
        c1 = factory.make_RegionRackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111.aaa", "revision": "1"},
                update={"version": "3.0.1-222-g.bbb", "revision": "1"},
            ),
        )
        notification1 = Notification.objects.filter(
            ident=UPGRADE_STATUS_NOTIFICATION_IDENT,
        ).first()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.1-222-g.bbb", "revision": "1"},
            ),
        )
        notification2 = Notification.objects.filter(
            ident=UPGRADE_STATUS_NOTIFICATION_IDENT,
        ).first()
        assert notification2.category == "success"
        assert (
            notification2.render() == "MAAS has been updated to version 3.0.1."
        )
        assert notification2.context == {
            "status": "completed",
            "version": "3.0.1",
        }
        assert notification1.id != notification2.id

    def test_update_status_update_already_completed(self):
        c1 = factory.make_RegionRackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111.aaa", "revision": "1"},
                update={"version": "3.0.1-222-g.bbb", "revision": "1"},
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.1-222-g.bbb", "revision": "1"},
            ),
        )
        notification1 = Notification.objects.filter(
            ident=UPGRADE_STATUS_NOTIFICATION_IDENT,
        ).first()
        # report again, but with no change
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.1-222-g.bbb", "revision": "1"},
            ),
        )
        notification2 = Notification.objects.filter(
            ident=UPGRADE_STATUS_NOTIFICATION_IDENT,
        ).first()
        assert (
            notification2.render() == "MAAS has been updated to version 3.0.1."
        )
        assert notification2.context == {
            "status": "completed",
            "version": "3.0.1",
        }
        assert notification1.id == notification2.id

    def test_update_status_new_update_already_completed(self):
        c1 = factory.make_RegionRackController()
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.0-111.aaa", "revision": "1"},
                update={"version": "3.0.1-222-g.bbb", "revision": "1"},
            ),
        )
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.1-222-g.bbb", "revision": "1"},
            ),
        )
        notification1 = Notification.objects.filter(
            ident=UPGRADE_STATUS_NOTIFICATION_IDENT,
        ).first()
        # a new update is available
        ControllerInfo.objects.set_versions_info(
            c1,
            SnapVersionsInfo(
                current={"version": "3.0.1-222-g.bbb", "revision": "1"},
                update={"version": "3.0.2-333-g.ccc", "revision": "1"},
            ),
        )
        notification2 = Notification.objects.filter(
            ident=UPGRADE_STATUS_NOTIFICATION_IDENT,
        ).first()
        assert (
            notification2.render()
            == "MAAS 3.0.2 is available, controllers will upgrade soon."
        )
        assert notification2.context == {
            "status": "inprogress",
            "version": "3.0.2",
        }
        assert notification1.id != notification2.id
