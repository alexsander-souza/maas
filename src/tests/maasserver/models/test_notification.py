# Copyright 2015-2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `Notification`."""

from collections import Counter
import itertools
import random

from django.core.exceptions import ValidationError
from django.db.models.query import QuerySet
import pytest

from maasserver.models.notification import (
    Notification,
    NotificationNotDismissable,
)
from maasserver.testing.factory import factory


@pytest.mark.parametrize(
    "category,target_name,method_name",
    [
        pytest.param(
            category,
            target_name,
            f"create_{category.lower()}_for_{target_name}",
            id=f"create_{category.lower()}_for_{target_name}",
        )
        for category, target_name in itertools.product(
            ("error", "warning", "success", "info"),
            ("user", "users", "admins"),
        )
    ],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test")
class TestNotificationManagerCreateMethods:
    """Tests for the `NotificationManager`'s create methods."""

    def make_notification(
        self, method_name, target_name, *, ident=None, context=None
    ):
        method = getattr(Notification.objects, method_name)
        message = factory.make_name("message")

        if target_name == "user":
            return method(
                message, factory.make_User(), context=context, ident=ident
            )
        return method(message, context=context, ident=ident)

    def check_notification(
        self, notification, *, ident, category, target_name
    ):
        assert notification.users is (target_name == "users")
        assert notification.admins is (target_name in {"users", "admins"})
        if target_name == "user":
            assert notification.user is not None
        else:
            assert notification.user is None
        if ident is None:
            assert notification.ident is None
        else:
            assert notification.ident == ident
        assert notification.category == category

    def test_create_new_notification_without_context(
        self, category, target_name, method_name
    ):
        notification = self.make_notification(method_name, target_name)
        self.check_notification(
            notification,
            ident=None,
            category=category,
            target_name=target_name,
        )
        assert notification.context == {}

    def test_create_new_notification_with_context(
        self, category, target_name, method_name
    ):
        context = {factory.make_name("key"): factory.make_name("value")}
        notification = self.make_notification(
            method_name, target_name, context=context
        )
        self.check_notification(
            notification,
            ident=None,
            category=category,
            target_name=target_name,
        )
        assert notification.context == context

    def test_create_new_notification_with_ident(
        self, category, target_name, method_name
    ):
        ident = factory.make_name("ident")
        notification = self.make_notification(
            method_name, target_name, ident=ident
        )
        self.check_notification(
            notification,
            ident=ident,
            category=category,
            target_name=target_name,
        )

    def test_create_new_notification_with_reused_ident(
        self, category, target_name, method_name
    ):
        # A new notification is created, and the ident is moved.
        ident = factory.make_name("ident")
        n1 = self.make_notification(method_name, target_name, ident=ident)
        n2 = self.make_notification(method_name, target_name, ident=ident)
        n1.refresh_from_db()  # Get current value of `ident`.
        assert n1 != n2
        self.check_notification(
            n1, ident=None, category=category, target_name=target_name
        )
        self.check_notification(
            n2, ident=ident, category=category, target_name=target_name
        )
        assert Notification.objects.filter(ident=ident).count() == 1


@pytest.mark.usefixtures("maasdb", "maas_region_test")
class TestFindingAndDismissingNotifications:
    """Tests for finding and dismissing notifications."""

    def notify(self, user):
        message = factory.make_name("message")
        return (
            Notification.objects.create_error_for_user(message, user),
            Notification.objects.create_error_for_users(message),
            Notification.objects.create_error_for_admins(message),
        )

    def check_notifications(self, user, notifications):
        notification = Notification.objects.find_for_user(user)
        assert isinstance(notification, QuerySet)  # Not RawQuerySet
        assert Counter(notification) == Counter(notifications)

    def test_find_and_dismiss_notifications_for_user(self):
        user = factory.make_User()
        n_for_user, n_for_users, n_for_admins = self.notify(user)
        self.check_notifications(user, [n_for_user, n_for_users])
        n_for_user.dismiss(user)
        self.check_notifications(user, [n_for_users])
        n_for_users.dismiss(user)
        self.check_notifications(user, [])

    def test_find_and_dismiss_notifications_for_users(self):
        user = factory.make_User("user")
        user2 = factory.make_User("user2")
        n_for_user, n_for_users, n_for_admins = self.notify(user)
        self.check_notifications(user, [n_for_user, n_for_users])
        self.check_notifications(user2, [n_for_users])
        n_for_users.dismiss(user2)
        self.check_notifications(user, [n_for_user, n_for_users])
        self.check_notifications(user2, [])

    def test_find_and_dismiss_notifications_for_admins(self):
        user = factory.make_User("user")
        admin = factory.make_admin("admin")
        n_for_user, n_for_users, n_for_admins = self.notify(user)
        self.check_notifications(user, [n_for_user, n_for_users])
        self.check_notifications(admin, [n_for_users, n_for_admins])
        n_for_users.dismiss(admin)
        self.check_notifications(user, [n_for_user, n_for_users])
        self.check_notifications(admin, [n_for_admins])
        n_for_admins.dismiss(admin)
        self.check_notifications(user, [n_for_user, n_for_users])
        self.check_notifications(admin, [])

    def test_not_dismissable(self):
        notification = Notification(
            message="Some notification", dismissable=False
        )
        with pytest.raises(NotificationNotDismissable):
            notification.dismiss(factory.make_User())


@pytest.mark.usefixtures("maasdb", "maas_region_test")
class TestNotification:
    """Tests for the `Notification`."""

    def test_render_combines_message_with_context(self):
        thing_a = factory.make_name("a")
        thing_b = random.randrange(1000)
        message = "There are {b:d} of {a} in my suitcase."
        context = {"a": thing_a, "b": thing_b}
        notification = Notification(message=message, context=context)
        assert notification.render() == (
            "There are " + str(thing_b) + " of " + thing_a + " in my suitcase."
        )

    def test_render_allows_markup_in_message_but_escapes_context(self):
        message = "<foo>{bar}</foo>"
        context = {"bar": "<BAR>"}
        notification = Notification(message=message, context=context)
        assert notification.render() == "<foo>&lt;BAR&gt;</foo>"

    def test_save_checks_that_rendering_works(self):
        message = "Dude, where's my {thing}?"
        notification = Notification(message=message)
        with pytest.raises(ValidationError) as error:
            notification.save()
        assert error.value.message_dict == {
            "__all__": ["Notification cannot be rendered."]
        }
        assert notification.id is None
        assert not Notification.objects.all().exists()

    def test_is_relevant_to_user(self):
        make_notification = factory.make_Notification

        user = factory.make_User()
        user2 = factory.make_User()
        admin = factory.make_admin()

        def check_relevance(notification, user, should_be_relevant: bool):
            # Ensure that is_relevant_to and find_for_user agree, i.e. if
            # is_relevant_to returns True, the notification is in the set
            # returned by find_for_user. Likewise, if is_relevant_to returns
            # False, the notification is not in the find_for_user set.
            assert notification.is_relevant_to(user) == should_be_relevant
            assert (
                Notification.objects.find_for_user(user)
                .filter(id=notification.id)
                .exists()
            ) == should_be_relevant

        notification_to_user = make_notification(user=user)
        check_relevance(notification_to_user, None, False)
        check_relevance(notification_to_user, user, True)
        check_relevance(notification_to_user, user2, False)
        check_relevance(notification_to_user, admin, False)

        notification_to_users = make_notification(users=True)
        check_relevance(notification_to_users, None, False)
        check_relevance(notification_to_users, user, True)
        check_relevance(notification_to_users, user2, True)
        check_relevance(notification_to_users, admin, False)

        notification_to_admins = make_notification(admins=True)
        check_relevance(notification_to_admins, None, False)
        check_relevance(notification_to_admins, user, False)
        check_relevance(notification_to_admins, user2, False)
        check_relevance(notification_to_admins, admin, True)

        notification_to_all = make_notification(users=True, admins=True)
        check_relevance(notification_to_all, None, False)
        check_relevance(notification_to_all, user, True)
        check_relevance(notification_to_all, user2, True)
        check_relevance(notification_to_all, admin, True)


@pytest.mark.parametrize(
    "category",
    ("error", "warning", "success", "info"),
    ids=("error", "warning", "success", "info"),
)
@pytest.mark.usefixtures("maasdb", "maas_region_test")
class TestNotificationRepresentation:
    """Tests for the `Notification` representation."""

    def test_for_user(self, category):
        notification = Notification(
            user=factory.make_User("foobar"),
            message="The cat in the {place}",
            context=dict(place="bear trap"),
            category=category,
        )
        assert repr(notification) == (
            f"<Notification {category.upper()} user='foobar' users=False admins=False "
            "'The cat in the bear trap'>"
        )

    def test_for_users(self, category):
        notification = Notification(
            users=True,
            message="The cat in the {place}",
            context=dict(place="blender"),
            category=category,
        )
        assert repr(notification) == (
            f"<Notification {category.upper()} user=None users=True admins=False "
            "'The cat in the blender'>"
        )

    def test_for_admins(self, category):
        notification = Notification(
            admins=True,
            message="The cat in the {place}",
            context=dict(place="lava pit"),
            category=category,
        )
        assert repr(notification) == (
            f"<Notification {category.upper()} user=None users=False admins=True "
            "'The cat in the lava pit'>"
        )
