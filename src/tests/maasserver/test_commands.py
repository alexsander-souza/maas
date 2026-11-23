# Copyright 2012-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test custom commands, as found in src/maasserver/management/commands."""

import io
from io import StringIO
import random
from unittest.mock import AsyncMock

from aiohttp import ClientError
from django.contrib.auth.models import User
from django.core.management import call_command, load_command_class
from django.core.management.base import CommandError
import pytest

from apiclient.creds import convert_tuple_to_string
import maascommon.hardening as H
from maasserver.enum import KEYS_PROTOCOL_TYPE
from maasserver.management.commands import changepasswords, createadmin
from maasserver.models.sshkey import SSHKey
from maasserver.models.user import get_creds_tuple
from maasserver.testing import get_data
from maasserver.testing.factory import factory
from maasserver.utils.orm import get_one, reload_object
import maasservicelayer.services.sshkeys as servicelayer_sshkeys


def assertCommandErrors(command, *args, **kwargs):
    """Assert that the given django command fails and return its error text."""
    with pytest.raises(CommandError) as exception:
        call_command(command, *args, **kwargs)
    return str(exception.value)


def set_hardening(monkeypatch, active):
    """Toggle the process-wide hardening state for the duration of a test."""
    monkeypatch.setattr(H, "_hardening_active", active)
    monkeypatch.setattr(H, "_hardening_configured", True)


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestCommands:
    """Happy-path integration testing for custom commands.

    Detailed testing does not belong here.  If there's any complexity at all
    in a command's code, it should be extracted and unit-tested separately.
    """

    def test_generate_api_doc(self):
        stdout = StringIO()
        call_command("generate_api_doc", stdout=stdout)
        result = stdout.getvalue()
        # Just check that the documentation looks all right.
        assert "POST /MAAS/api/2.0/account/" in result
        assert "MAAS API" in result
        assert result[:20].startswith(".. _maas-api:")
        # It also contains a ReST title (not indented).
        assert "===" in result[:20]

    def test_createadmin_prompts_for_password_if_not_given(self, mocker):
        stderr = StringIO()
        stdout = StringIO()
        username = factory.make_name("user")
        password = factory.make_string()
        ssh_import = "{}:{}".format(
            random.choice([KEYS_PROTOCOL_TYPE.LP, KEYS_PROTOCOL_TYPE.GH]),
            factory.make_name("user-id"),
        )
        email = factory.make_email_address()
        mocker.patch.object(
            createadmin, "prompt_for_password", return_value=password
        )
        mocker.patch.object(SSHKey.objects, "from_keysource")

        call_command(
            "createadmin",
            username=username,
            email=email,
            ssh_import=ssh_import,
            stdout=stdout,
            stderr=stderr,
        )
        user = User.objects.get(username=username)

        assert stderr.getvalue().strip() == ""
        assert stdout.getvalue().strip() == ""
        assert user.check_password(password)

    def test_createadmin_prompts_for_username_if_not_given(self, mocker):
        stderr = StringIO()
        stdout = StringIO()
        username = factory.make_name("user")
        password = factory.make_string()
        email = factory.make_email_address()
        ssh_import = "{}:{}".format(
            random.choice([KEYS_PROTOCOL_TYPE.LP, KEYS_PROTOCOL_TYPE.GH]),
            factory.make_name("user-id"),
        )
        mocker.patch.object(
            createadmin, "prompt_for_username", return_value=username
        )
        mocker.patch.object(SSHKey.objects, "from_keysource")

        call_command(
            "createadmin",
            password=password,
            email=email,
            ssh_import=ssh_import,
            stdout=stdout,
            stderr=stderr,
        )
        user = User.objects.get(username=username)

        assert stderr.getvalue().strip() == ""
        assert stdout.getvalue().strip() == ""
        assert user.check_password(password)

    def test_createadmin_prompts_for_email_if_not_given(self, mocker):
        stderr = StringIO()
        stdout = StringIO()
        username = factory.make_name("user")
        password = factory.make_string()
        email = factory.make_email_address()
        ssh_import = "{}:{}".format(
            random.choice([KEYS_PROTOCOL_TYPE.LP, KEYS_PROTOCOL_TYPE.GH]),
            factory.make_name("user-id"),
        )
        mocker.patch.object(
            createadmin, "prompt_for_email", return_value=email
        )
        mocker.patch.object(SSHKey.objects, "from_keysource")

        call_command(
            "createadmin",
            username=username,
            password=password,
            ssh_import=ssh_import,
            stdout=stdout,
            stderr=stderr,
        )
        user = User.objects.get(username=username)

        assert stderr.getvalue().strip() == ""
        assert stdout.getvalue().strip() == ""

        assert user.check_password(password)

    def test_createadmin_not_prompt_for_ssh_import_if_other_params_given(self):
        stderr = StringIO()
        stdout = StringIO()
        username = factory.make_name("user")
        password = factory.make_string()
        email = factory.make_email_address()

        call_command(
            "createadmin",
            username=username,
            password=password,
            email=email,
            stdout=stdout,
            stderr=stderr,
        )

        assert stderr.getvalue().strip() == ""
        assert stdout.getvalue().strip() == ""

    def test_createadmin_prompts_for_ssh_import_if_not_given(self, mocker):
        stderr = StringIO()
        stdout = StringIO()
        username = factory.make_name("user")
        password = factory.make_string()
        email = factory.make_email_address()
        ssh_import = "{}:{}".format(
            random.choice([KEYS_PROTOCOL_TYPE.LP, KEYS_PROTOCOL_TYPE.GH]),
            factory.make_name("user-id"),
        )
        mocker.patch.object(
            createadmin, "prompt_for_ssh_import", return_value=ssh_import
        )
        mocker.patch.object(SSHKey.objects, "from_keysource")

        call_command(
            "createadmin",
            username=username,
            password=password,
            email=email,
            stdout=stdout,
            stderr=stderr,
        )
        user = User.objects.get(username=username)

        assert stderr.getvalue().strip() == ""
        assert stdout.getvalue().strip() == ""

        assert user.check_password(password)

    def test_createadmin_creates_admin_and_ssh_key(self, mocker):
        stderr = StringIO()
        stdout = StringIO()
        username = factory.make_string()
        password = factory.make_string()
        email = "%s@example.com" % factory.make_string()
        protocol = random.choice(
            [KEYS_PROTOCOL_TYPE.LP, KEYS_PROTOCOL_TYPE.GH]
        )
        user_id = factory.make_name("user-id")
        ssh_import = f"{protocol}:{user_id}"
        key_string = get_data("data/test_rsa0.pub")
        if protocol == KEYS_PROTOCOL_TYPE.LP:
            mock_get_ssh_key = mocker.patch.object(
                servicelayer_sshkeys.SshKeysService,
                "_get_ssh_key_from_launchpad",
                new_callable=AsyncMock,
            )
        else:
            mock_get_ssh_key = mocker.patch.object(
                servicelayer_sshkeys.SshKeysService,
                "_get_ssh_key_from_github",
                new_callable=AsyncMock,
            )
        mock_get_ssh_key.return_value = [key_string]
        call_command(
            "createadmin",
            username=username,
            password=password,
            email=email,
            ssh_import=ssh_import,
            stderr=stderr,
            stdout=stdout,
        )
        user = get_one(User.objects.filter(username=username))
        sshkey = get_one(SSHKey.objects.filter(user=user))
        assert stderr.getvalue().strip() == ""
        assert stdout.getvalue().strip() == ""

        assert user.check_password(password)
        assert user.is_superuser
        assert email == user.email
        assert key_string == sshkey.key

    def test_createadmin_raises_ssh_key_error(self, mocker):
        stderr = StringIO()
        stdout = StringIO()
        username = factory.make_string()
        password = factory.make_string()
        email = "%s@example.com" % factory.make_string()
        ssh_import = "{}:{}".format(
            random.choice([KEYS_PROTOCOL_TYPE.LP, KEYS_PROTOCOL_TYPE.GH]),
            factory.make_name("user-id"),
        )
        mocker.patch.object(
            SSHKey.objects, "from_keysource", side_effect=ClientError("error")
        )
        with pytest.raises(createadmin.SSHKeysError):
            call_command(
                "createadmin",
                username=username,
                password=password,
                email=email,
                ssh_import=ssh_import,
                stderr=stderr,
                stdout=stdout,
            )
        assert len(User.objects.filter(username=username)) == 0

    def test_createadmin_user_already_exists(self):
        stderr = StringIO()
        stdout = StringIO()
        username = factory.make_string()
        password = factory.make_string()
        email = "%s@example.com" % factory.make_string()
        call_command(
            "createadmin",
            username=username,
            password=password,
            email=email,
            stderr=stderr,
            stdout=stdout,
        )
        assert len(User.objects.filter(username=username)) == 1

        with pytest.raises(createadmin.AlreadyExistingUser):
            call_command(
                "createadmin",
                username=username,
                password=password,
                email=email,
                stderr=stderr,
                stdout=stdout,
            )

    def test_prompt_for_password_returns_selected_password(self, mocker):
        password = factory.make_string()
        mocker.patch.object(createadmin, "getpass", return_value=password)

        assert password == createadmin.prompt_for_password()

    def test_prompt_for_password_checks_for_consistent_password(self, mocker):
        mocker.patch.object(
            createadmin, "getpass", side_effect=lambda x: factory.make_string()
        )

        with pytest.raises(createadmin.InconsistentPassword):
            createadmin.prompt_for_password()

    def test_prompt_for_username_returns_selected_username(self, mocker):
        username = factory.make_name("user")
        mocker.patch.object(createadmin, "read_input", return_value=username)

        assert username == createadmin.prompt_for_username()

    def test_prompt_for_username_checks_for_empty_username(self, mocker):
        mocker.patch.object(createadmin, "read_input", return_value="")

        with pytest.raises(createadmin.EmptyUsername):
            createadmin.prompt_for_username()

    def test_prompt_for_email_returns_selected_email(self, mocker):
        email = factory.make_email_address()
        mocker.patch.object(createadmin, "read_input", return_value=email)

        assert email == createadmin.prompt_for_email()

    def test_prompt_for_email_checks_for_empty_email(self, mocker):
        mocker.patch.object(createadmin, "read_input", return_value="")

        with pytest.raises(createadmin.EmptyEmail):
            createadmin.prompt_for_email()

    def test_prompt_for_ssh_import_returns_selected_creds(self, mocker):
        ssh_import = "{}:{}".format(
            random.choice([KEYS_PROTOCOL_TYPE.LP, KEYS_PROTOCOL_TYPE.GH]),
            factory.make_name("user-id"),
        )
        mocker.patch.object(createadmin, "read_input", return_value=ssh_import)

        assert ssh_import == createadmin.prompt_for_ssh_import()

    def test_prompt_for_ssh_import_returns_None_for_no_user_id(self, mocker):
        mocker.patch.object(createadmin, "read_input", return_value="")
        assert "" == createadmin.prompt_for_ssh_import()

    def test_validate_ssh_import_validates_protocol_and_user_id(self):
        protocol = random.choice(
            [KEYS_PROTOCOL_TYPE.LP, KEYS_PROTOCOL_TYPE.GH]
        )
        user_id = factory.make_name("user-id")
        ssh_import = f"{protocol}:{user_id}"
        assert (protocol, user_id) == createadmin.validate_ssh_import(
            ssh_import
        )

    def test_validate_ssh_import_validates_user_id_with_no_protocol(self):
        user_id = factory.make_name("user-id")
        assert (
            KEYS_PROTOCOL_TYPE.LP,
            user_id,
        ) == createadmin.validate_ssh_import(user_id)

    def test_validate_ssh_import_errors_on_incorrect_protocol(self):
        with pytest.raises(createadmin.SSHKeysError):
            createadmin.validate_ssh_import("rubbish:good")

    def test_validate_ssh_import_errors_on_incorrect_user_id(self):
        with pytest.raises(createadmin.SSHKeysError):
            createadmin.validate_ssh_import("lp:rubbish:here")

    def test_createadmin_rejects_weak_password_when_hardening_active(
        self, monkeypatch
    ):
        set_hardening(monkeypatch, True)
        username = factory.make_name("user")
        email = factory.make_email_address()
        with pytest.raises(CommandError):
            call_command(
                "createadmin",
                username=username,
                password="secret",
                email=email,
                stdout=StringIO(),
                stderr=StringIO(),
            )
        assert 0 == User.objects.filter(username=username).count()

    def test_createadmin_accepts_compliant_password_when_hardening_active(
        self, monkeypatch
    ):
        set_hardening(monkeypatch, True)
        username = factory.make_name("user")
        password = "Sup3rSecret!pw"
        email = factory.make_email_address()
        call_command(
            "createadmin",
            username=username,
            password=password,
            email=email,
            stdout=StringIO(),
            stderr=StringIO(),
        )
        user = User.objects.get(username=username)
        assert user.check_password(password)

    def test_createadmin_allows_weak_password_when_hardening_inactive(
        self, monkeypatch
    ):
        set_hardening(monkeypatch, False)
        username = factory.make_name("user")
        password = "secret"
        email = factory.make_email_address()
        call_command(
            "createadmin",
            username=username,
            password=password,
            email=email,
            stdout=StringIO(),
            stderr=StringIO(),
        )
        user = User.objects.get(username=username)
        assert user.check_password(password)


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestChangePasswords:
    def test_bad_input(self, mocker):
        stdin = io.StringIO("nobody")
        mocker.patch.object(changepasswords, "fileinput", return_value=stdin)
        error_text = assertCommandErrors("changepasswords")
        assert (
            "Invalid input provided. "
            "Format is 'username:password', one per line."
        ) in error_text

    def test_nonexistent_user(self, mocker):
        stdin = io.StringIO("nobody:nopass")
        mocker.patch.object(changepasswords, "fileinput", return_value=stdin)
        error_text = assertCommandErrors("changepasswords")
        assert "User 'nobody' does not exist." in error_text

    def test_changes_one_password(self, mocker):
        username = factory.make_username()
        password = factory.make_string(size=16, spaces=True, prefix="password")
        user = factory.make_User(username=username, password=password)
        assert user.check_password(password)
        newpass = factory.make_string(size=16, spaces=True, prefix="newpass")
        stdin = io.StringIO(f"{username}:{newpass}")
        mocker.patch.object(changepasswords, "fileinput", return_value=stdin)
        call_command("changepasswords")
        assert reload_object(user).check_password(newpass)

    def test_changes_ten_passwords(self, mocker):
        users_passwords = []
        stringio = io.StringIO()
        for _ in range(10):
            username = factory.make_username()
            user = factory.make_User(username=username)
            newpass = factory.make_string(spaces=True, prefix="newpass")
            users_passwords.append((user, newpass))
            stringio.write(f"{username}:{newpass}\n")
        stringio.seek(0)
        mocker.patch.object(
            changepasswords, "fileinput", return_value=stringio
        )
        call_command("changepasswords")
        for user, newpass in users_passwords:
            assert reload_object(user).check_password(newpass)

    def test_rejects_weak_password_when_hardening_active(
        self, mocker, monkeypatch
    ):
        set_hardening(monkeypatch, True)
        username = factory.make_username()
        original = "Sup3rSecret!pw"
        user = factory.make_User(username=username, password=original)
        assert user.check_password(original)
        stdin = io.StringIO(f"{username}:secret")
        mocker.patch.object(changepasswords, "fileinput", return_value=stdin)
        error_text = assertCommandErrors("changepasswords")
        assert "is not compliant" in error_text
        # The weak password was rejected before hashing; the stored password
        # is unchanged.
        assert reload_object(user).check_password(original)
        assert not reload_object(user).check_password("secret")

    def test_allows_weak_password_when_hardening_inactive(
        self, mocker, monkeypatch
    ):
        set_hardening(monkeypatch, False)
        username = factory.make_username()
        user = factory.make_User(username=username)
        newpass = "secret"
        stdin = io.StringIO(f"{username}:{newpass}")
        mocker.patch.object(changepasswords, "fileinput", return_value=stdin)
        call_command("changepasswords")
        assert reload_object(user).check_password(newpass)

    def test_accepts_compliant_password_when_hardening_active(
        self, mocker, monkeypatch
    ):
        set_hardening(monkeypatch, True)
        username = factory.make_username()
        user = factory.make_User(username=username)
        newpass = "Sup3rSecret!pw"
        stdin = io.StringIO(f"{username}:{newpass}")
        mocker.patch.object(changepasswords, "fileinput", return_value=stdin)
        call_command("changepasswords")
        assert reload_object(user).check_password(newpass)


def run_changepassword(mocker, username, passwords, **options):
    import getpass as getpass_mod

    calls = iter(passwords)
    mocker.patch.object(
        getpass_mod, "getpass", side_effect=lambda prompt="": next(calls)
    )
    call_command(
        load_command_class("maasserver", "changepassword"),
        username=username,
        **options,
    )


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestChangePassword:
    def test_changes_password(self, mocker):
        username = factory.make_username()
        user = factory.make_User(username=username, password="oldpass")
        newpass = "Sup3rSecret!pw"
        run_changepassword(
            mocker,
            username,
            [newpass, newpass],
            stdout=StringIO(),
            stderr=StringIO(),
        )
        assert reload_object(user).check_password(newpass)

    def test_rejects_weak_password_when_hardening_active(
        self, mocker, monkeypatch
    ):
        set_hardening(monkeypatch, True)
        username = factory.make_username()
        original = "Sup3rSecret!pw"
        user = factory.make_User(username=username, password=original)
        weak = "secret"
        with pytest.raises(CommandError):
            run_changepassword(
                mocker,
                username,
                [weak, weak, weak, weak, weak, weak],
                stdout=StringIO(),
                stderr=StringIO(),
            )
        assert reload_object(user).check_password(original)
        assert not reload_object(user).check_password(weak)

    def test_accepts_compliant_password_when_hardening_active(
        self, mocker, monkeypatch
    ):
        set_hardening(monkeypatch, True)
        username = factory.make_username()
        user = factory.make_User(username=username)
        newpass = "Sup3rSecret!pw"
        run_changepassword(
            mocker,
            username,
            [newpass, newpass],
            stdout=StringIO(),
            stderr=StringIO(),
        )
        assert reload_object(user).check_password(newpass)

    def test_allows_weak_password_when_hardening_inactive(
        self, mocker, monkeypatch
    ):
        set_hardening(monkeypatch, False)
        username = factory.make_username()
        user = factory.make_User(username=username)
        newpass = "secret"
        run_changepassword(
            mocker,
            username,
            [newpass, newpass],
            stdout=StringIO(),
            stderr=StringIO(),
        )
        assert reload_object(user).check_password(newpass)


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestApikeyCommand:
    def test_apikey_requires_username(self):
        error_text = assertCommandErrors("apikey")
        assert "You must provide a username with --username." in error_text

    def test_apikey_gets_keys(self):
        stderr = StringIO()
        stdout = StringIO()
        user = factory.make_User()
        call_command(
            "apikey", username=user.username, stderr=stderr, stdout=stdout
        )
        assert stderr.getvalue().strip() == ""

        expected_token = get_one(user.userprofile.get_authorisation_tokens())
        expected_string = (
            convert_tuple_to_string(get_creds_tuple(expected_token)) + "\n"
        )
        assert expected_string == stdout.getvalue()

    def test_apikey_generates_key(self):
        stderr = StringIO()
        stdout = StringIO()
        user = factory.make_User()
        num_keys = len(user.userprofile.get_authorisation_tokens())
        call_command(
            "apikey",
            username=user.username,
            generate=True,
            stderr=stderr,
            stdout=stdout,
        )
        assert stderr.getvalue().strip() == ""

        keys_after = user.userprofile.get_authorisation_tokens()
        expected_num_keys = num_keys + 1
        assert expected_num_keys == len(keys_after)
        expected_token = user.userprofile.get_authorisation_tokens()[1]
        expected_string = (
            convert_tuple_to_string(get_creds_tuple(expected_token)) + "\n"
        )
        assert expected_string == stdout.getvalue()

    def test_apikey_deletes_key(self):
        stderr = StringIO()
        stdout = StringIO()
        user = factory.make_User()
        existing_token = get_one(user.userprofile.get_authorisation_tokens())
        token_string = convert_tuple_to_string(get_creds_tuple(existing_token))
        call_command(
            "apikey",
            username=user.username,
            delete=token_string,
            stderr=stderr,
            stdout=stdout,
        )
        assert stderr.getvalue().strip() == ""

        keys_after = user.userprofile.get_authorisation_tokens()
        assert 0 == len(keys_after)

    def test_apikey_rejects_mutually_exclusive_options(self):
        user = factory.make_User()
        error_text = assertCommandErrors(
            "apikey", username=user.username, generate=True, delete="foo"
        )
        assert "Specify one of --generate or --delete" in error_text

    def test_apikey_rejects_deletion_of_bad_key(self):
        user = factory.make_User()
        error_text = assertCommandErrors(
            "apikey", username=user.username, delete="foo"
        )
        assert "Malformed credentials string" in error_text

    def test_api_key_rejects_deletion_of_nonexistent_key(self):
        stderr = StringIO()
        user = factory.make_User()
        existing_token = get_one(user.userprofile.get_authorisation_tokens())
        token_string = convert_tuple_to_string(get_creds_tuple(existing_token))
        call_command(
            "apikey",
            username=user.username,
            delete=token_string,
            stderr=stderr,
        )
        assert stderr.getvalue().strip() == ""

        # Delete it again. Check that there's a sensible rejection.
        error_text = assertCommandErrors(
            "apikey", username=user.username, delete=token_string
        )
        assert "No matching api key found" in error_text

    def test_success_modify_apikey_name(self):
        stderr = StringIO()
        stdout = StringIO()
        fake_api_key_name = "Test Key Name"
        user = factory.make_User()
        existing_token = get_one(user.userprofile.get_authorisation_tokens())
        token_string = convert_tuple_to_string(get_creds_tuple(existing_token))
        call_command(
            "apikey",
            username=user.username,
            update=token_string,
            api_key_name=fake_api_key_name,
            stderr=stderr,
            stdout=stdout,
        )
        assert stderr.getvalue().strip() == ""

    def test_api_key_rejects_update_of_nonexistent_key(self):
        stderr = StringIO()
        user = factory.make_User()
        fake_api_key_name = "Test Key Name"
        existing_token = get_one(user.userprofile.get_authorisation_tokens())
        token_string = convert_tuple_to_string(get_creds_tuple(existing_token))
        call_command(
            "apikey",
            username=user.username,
            delete=token_string,
            stderr=stderr,
        )
        assert stderr.getvalue().strip() == ""

        # Try to update the deleted token.
        error_text = assertCommandErrors(
            "apikey",
            username=user.username,
            update=token_string,
            api_key_name=fake_api_key_name,
        )
        assert "No matching api key found" in error_text

    def test_api_key_rejects_update_without_key_name(self):
        user = factory.make_User()
        existing_token = get_one(user.userprofile.get_authorisation_tokens())
        token_string = convert_tuple_to_string(get_creds_tuple(existing_token))
        error_text = assertCommandErrors(
            "apikey", username=user.username, update=token_string
        )
        assert "Should specify new name" in error_text

    def test_api_key_update_and_generate_mutually_exclusive_options(self):
        user = factory.make_User()
        fake_api_key_name = "Test Key Name"
        existing_token = get_one(user.userprofile.get_authorisation_tokens())
        token_string = convert_tuple_to_string(get_creds_tuple(existing_token))
        error_text = assertCommandErrors(
            "apikey",
            username=user.username,
            generate=True,
            api_key_name=fake_api_key_name,
            update=token_string,
        )
        assert "Specify one of --generate or --update." in error_text
