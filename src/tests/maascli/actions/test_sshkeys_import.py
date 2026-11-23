# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test for sshkeys import action."""

import random
from unittest.mock import Mock

import pytest

from apiclient.testing.credentials import make_api_credentials
from maascli.actions.sshkeys_import import SSHKeysImportAction
from maascli.command import CommandError
from maasserver.enum import KEYS_PROTOCOL_TYPE
from maastesting.factory import factory


class TestSSHKeysImportAction:
    """Tests for `SSHKeysImportAction`."""

    def make_sshkeys_import_action(self, capsys):
        action_bases = (SSHKeysImportAction,)
        action_ns = {
            "action": {"method": "POST"},
            "handler": {"uri": b"/MAAS/api/2.0/sshkeys/", "params": []},
            "profile": {"credentials": make_api_credentials()},
        }
        action_class = type("import", action_bases, action_ns)
        action = action_class(Mock())
        return action

    def test_name_value_pair_returns_sshkey_creds_tuple(self, capsys):
        action = self.make_sshkeys_import_action(capsys)
        ks = "{}:{}".format(
            random.choice([KEYS_PROTOCOL_TYPE.LP, KEYS_PROTOCOL_TYPE.GH]),
            factory.make_name("user-id"),
        )
        expected_data = ("keysource", ks)
        data = action.name_value_pair(ks)
        assert data == expected_data

    def test_name_value_pair_returns_sshkey_creds_tuple_for_no_protocol(
        self, capsys
    ):
        action = self.make_sshkeys_import_action(capsys)
        ks = factory.make_name("user-id")
        expected_data = ("keysource", ks)
        data = action.name_value_pair(ks)
        assert data == expected_data

    def test_name_value_pair_returns_sshkey_creds_tuple_for_no_input(
        self, capsys
    ):
        action = self.make_sshkeys_import_action(capsys)
        with pytest.raises(CommandError):
            action.name_value_pair("")
