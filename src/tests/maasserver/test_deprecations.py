import os

from django.conf import settings
import pytest

from maasserver import deprecations
from maasserver.deprecations import (
    Deprecation,
    DEPRECATIONS,
    get_deprecations,
    log_deprecations,
    sync_deprecation_notifications,
)
from maasserver.models import Notification
from provisioningserver.logger import LegacyLogger


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestGetDeprecations:
    def test_old_postgres_version(self, mocker):
        mocker.patch.object(
            deprecations, "postgresql_major_version"
        ).return_value = 14
        assert DEPRECATIONS["POSTGRES_OLDER_THAN_16"] in get_deprecations()

    def test_wrong_database_owner(self, mocker):
        mocker.patch.object(
            deprecations, "get_database_owner"
        ).return_value = "postgres"
        assert DEPRECATIONS["WRONG_MAAS_DATABASE_OWNER"] in get_deprecations()

    def test_curtin_preseeds_included_if_custom_preseeds_exist(self, mocker):
        mocker.patch.object(
            settings,
            "PRESEED_TEMPLATE_LOCATIONS",
            ["/path/to/location1", "/path/to/location2"],
        )
        mocker.patch.object(os.path, "isdir").return_value = True
        mocker.patch.object(os, "listdir").return_value = ["curtin_userdata"]
        assert DEPRECATIONS["CURTIN_PRESEEDS"] in get_deprecations()

    def test_curtin_preseeds_not_included_if_no_custom_preseeds(self, mocker):
        mocker.patch.object(
            settings,
            "PRESEED_TEMPLATE_LOCATIONS",
            ["/path/to/location1", "/path/to/location2"],
        )
        mocker.patch.object(os.path, "isdir").return_value = True
        mocker.patch.object(os, "listdir").return_value = ["no_curtin_file"]
        assert DEPRECATIONS["CURTIN_PRESEEDS"] not in get_deprecations()


class TestLogDeprecations:
    def test_log_deprecations(self, mocker):
        mocker.patch.object(deprecations, "get_deprecations").return_value = [
            Deprecation(
                id="MD123", since="2.9", description="something is deprecated"
            )
        ]

        events = []
        logger = LegacyLogger(observer=events.append)
        log_deprecations(logger=logger)
        [event] = events
        assert (
            event["_message_0"]
            == "Deprecation MD123 (https://canonical.com/maas/deprecations/MD123): "
            "something is deprecated"
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestSyncDeprecationNotifications:
    def test_create_notifications(self, mocker):
        mocker.patch.object(deprecations, "get_deprecations").return_value = [
            Deprecation(
                id="MD123", since="2.9", description="something is deprecated"
            )
        ]

        sync_deprecation_notifications()

        notifications = Notification.objects.filter(
            ident__in=[
                "deprecation_MD123_admins",
                "deprecation_MD123_users",
            ]
        ).order_by("ident")
        notification1, notification2 = notifications
        assert notification1.ident == "deprecation_MD123_admins"
        assert notification1.category == "warning"
        assert not notification1.dismissable
        assert notification1.admins
        assert not notification1.users
        assert (
            "https://canonical.com/maas/deprecations/MD123"
            in notification1.message
        )
        assert (
            "Please contact your MAAS administrator."
            not in notification1.message
        )
        assert notification2.ident == "deprecation_MD123_users"
        assert notification2.category == "warning"
        assert not notification2.dismissable
        assert not notification2.admins
        assert notification2.users
        assert (
            "Please contact your MAAS administrator." in notification2.message
        )

    def test_remove_deprecations(self, mocker):
        Notification(
            ident="deprecation_MD1_admins", message="some text"
        ).save()
        mocker.patch.object(deprecations, "get_deprecations").return_value = []
        sync_deprecation_notifications()
        # the notification is removed since there is no active deprecation
        assert not Notification.objects.filter(
            ident="deprecation_MD1_admins"
        ).exists()
