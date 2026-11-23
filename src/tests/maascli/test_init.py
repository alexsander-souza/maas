# Copyright 2012-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maascli.init`."""

import sys

import pytest

from maascli import init
from maascli.parser import ArgumentParser


class TestCreateAdminOptions:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.parser = ArgumentParser()
        init.add_create_admin_options(self.parser)

    def test_create_admin_options_empty(self):
        options = self.parser.parse_args([])
        assert options.admin_username is None
        assert options.admin_password is None
        assert options.admin_email is None
        assert options.admin_ssh_import is None

    def test_create_admin_options_username(self):
        options = self.parser.parse_args(["--admin-username", "my-username"])
        assert "my-username" == options.admin_username

    def test_create_admin_options_password(self):
        options = self.parser.parse_args(["--admin-password", "my-password"])
        assert "my-password" == options.admin_password

    def test_create_admin_options_email(self):
        options = self.parser.parse_args(["--admin-email", "my@example.com"])
        assert "my@example.com" == options.admin_email

    def test_create_admin_options_ssh_import(self):
        options = self.parser.parse_args(["--admin-ssh-import", "lp:me"])
        assert "lp:me" == options.admin_ssh_import


class TestPrintMsg:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        self.mock_print = mocker.patch.object(init, "print")

    def test_print_msg_empty_message(self):
        init.print_msg()
        self.mock_print.assert_called_with(
            "", end="\n", file=sys.stdout, flush=True
        )
