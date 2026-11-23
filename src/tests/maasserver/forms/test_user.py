# Copyright 2014-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for user-creation forms."""

import re

from django.contrib.auth.models import User
import pytest

from maasserver.forms import EditUserForm, NewUserCreationForm, ProfileForm
from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestUniqueEmailForms:
    def assert_form_fails_validation_because_email_not_unique(self, form):
        assert not form.is_valid()
        assert "email" in form._errors
        assert len(form._errors["email"]) == 1
        # Cope with 'Email' and 'E-mail' in error message.
        assert re.search(
            r"User with this E-{0,1}mail address already exists.",
            form._errors["email"][0],
        )

    def test_ProfileForm_fails_validation_if_email_taken(self):
        another_email = "%s@example.com" % factory.make_string()
        factory.make_User(email=another_email)
        email = "%s@example.com" % factory.make_string()
        user = factory.make_User(email=email)
        form = ProfileForm(instance=user, data={"email": another_email})
        self.assert_form_fails_validation_because_email_not_unique(form)

    def test_ProfileForm_validates_if_email_unchanged(self):
        email = "%s@example.com" % factory.make_string()
        user = factory.make_User(email=email)
        form = ProfileForm(instance=user, data={"email": email})
        assert form.is_valid(), form.errors

    def test_NewUserCreationForm_fails_validation_if_email_taken(self):
        email = "%s@example.com" % factory.make_string()
        username = factory.make_string()
        password = factory.make_string()
        factory.make_User(email=email)
        form = NewUserCreationForm(
            {
                "email": email,
                "username": username,
                "password1": password,
                "password2": password,
            }
        )
        self.assert_form_fails_validation_because_email_not_unique(form)

    def test_EditUserForm_fails_validation_if_email_taken(self):
        another_email = "%s@example.com" % factory.make_string()
        factory.make_User(email=another_email)
        email = "%s@example.com" % factory.make_string()
        user = factory.make_User(email=email)
        form = EditUserForm(instance=user, data={"email": another_email})
        self.assert_form_fails_validation_because_email_not_unique(form)

    def test_EditUserForm_validates_if_email_unchanged(self):
        email = "%s@example.com" % factory.make_string()
        user = factory.make_User(email=email)
        form = EditUserForm(
            instance=user,
            data={"email": email, "username": factory.make_string()},
        )
        assert form.is_valid(), form.errors


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNewUserCreationForm:
    def test_saves_to_db_by_default(self):
        password = factory.make_name("password")
        params = {
            "email": "%s@example.com" % factory.make_string(),
            "username": factory.make_name("user"),
            "password1": password,
            "password2": password,
        }
        form = NewUserCreationForm(params)
        form.save()
        assert User.objects.get(username=params["username"]) is not None

    def test_email_is_required(self):
        password = factory.make_name("password")
        params = {
            "email": "",
            "username": factory.make_name("user"),
            "password1": password,
            "password2": password,
        }
        form = NewUserCreationForm(params)
        assert not form.is_valid()
        assert {"email": ["This field is required."]} == form._errors

        password = factory.make_name("password")
        params = {
            "email": "%s@example.com" % factory.make_string(),
            "username": factory.make_name("user"),
            "password1": password,
            "password2": password,
        }
        form = NewUserCreationForm(params)
        form.save(commit=False)
        assert not User.objects.filter(username=params["username"]).exists()

    def test_fields_order(self):
        form = NewUserCreationForm()

        assert [
            "username",
            "last_name",
            "email",
            "password1",
            "password2",
            "is_superuser",
        ] == list(form.fields)
