# Copyright 2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for Notification forms."""

import json
import random

import pytest

from maasserver.forms.notification import NotificationForm
from maasserver.testing.factory import factory

categories = "info", "success", "warning", "error"


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNotificationForm:
    def test_notification_can_be_created_with_just_message(self):
        notification_message = factory.make_name("message")
        form = NotificationForm({"message": notification_message})
        assert form.is_valid(), form.errors
        notification = form.save()
        assert notification.ident is None
        assert notification.message == notification_message
        assert notification.user is None
        assert not notification.users
        assert not notification.admins
        assert notification.category == "info"
        assert notification.context == {}

    def test_notification_can_be_created_with_empty_fields(self):
        notification_message = factory.make_name("message")
        form = NotificationForm(
            {
                "ident": "",
                "user": "",
                "users": "",
                "admins": "",
                "message": notification_message,
                "context": "",
                "category": "",
            }
        )
        assert form.is_valid(), form.errors
        notification = form.save()
        assert notification.ident is None
        assert notification.message == notification_message
        assert notification.user is None
        assert not notification.users
        assert not notification.admins
        assert notification.category == "info"
        assert notification.context == {}
        assert notification.dismissable

    def test_notification_can_be_created_with_all_fields(self):
        user = factory.make_User()
        data = {
            "ident": factory.make_name("ident"),
            "user": str(user.id),
            "users": random.choice(["true", "false"]),
            "admins": random.choice(["true", "false"]),
            "message": factory.make_name("message"),
            "context": json.dumps(
                {factory.make_name("key"): factory.make_name("value")}
            ),
            "category": random.choice(categories),
            "dismissable": random.choice(["true", "false"]),
        }
        form = NotificationForm(data)
        assert form.is_valid(), form.errors
        notification = form.save()
        assert notification.ident == data["ident"]
        assert notification.message == data["message"]
        assert notification.user == user
        if data["users"] == "true":
            assert notification.users
        else:
            assert not notification.users
        if data["admins"] == "true":
            assert notification.admins
        else:
            assert not notification.admins
        assert notification.context == json.loads(data["context"])
        if data["dismissable"] == "true":
            assert notification.dismissable
        else:
            assert not notification.dismissable
        assert notification.category == data["category"]

    def test_notification_can_be_created_with_username(self):
        user = factory.make_User()
        data = {
            "message": factory.make_name("message"),
            "user": user.username,
        }
        form = NotificationForm(data)
        assert form.is_valid(), form.errors
        notification = form.save()
        assert notification.user == user

    def test_notification_rejects_unknown_username(self):
        form = NotificationForm(
            {"message": factory.make_name("message"), "user": "no-such-user"}
        )
        assert not form.is_valid()
        assert ["Enter a valid user id or username."] == form.errors["user"]

    def test_notification_can_be_updated(self):
        notification = factory.make_Notification()
        user = factory.make_User()
        data = {
            "ident": factory.make_name("ident"),
            "user": str(user.id),
            "users": "false" if notification.users else "true",
            "admins": "false" if notification.admins else "true",
            "message": factory.make_name("message"),
            "context": json.dumps(
                {factory.make_name("key"): factory.make_name("value")}
            ),
            "category": random.choice(
                [c for c in categories if c != notification.category]
            ),
        }
        form = NotificationForm(instance=notification, data=data)
        assert form.is_valid(), form.errors
        notification_saved = form.save()
        assert notification == notification_saved
        assert notification_saved.ident == data["ident"]
        assert notification_saved.message == data["message"]
        assert notification_saved.user == user
        if data["users"] == "true":
            assert notification_saved.users
        else:
            assert not notification_saved.users
        if data["admins"] == "true":
            assert notification_saved.admins
        else:
            assert not notification_saved.admins
        assert notification_saved.context == json.loads(data["context"])
        assert notification_saved.category == data["category"]
