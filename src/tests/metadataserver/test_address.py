# Copyright 2012-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test server-address-guessing logic."""

from metadataserver import address


def parse_locale_lines(output):
    """Parse lines of output from /bin/locale into a dict."""
    return {
        key: value.strip('"')
        for key, value in [line.split("=") for line in output]
    }


class TestAddress:
    def test_get_command_output_executes_command(self):
        assert address.get_command_output("echo", "Hello") == ["Hello"]

    def test_get_command_output_does_not_expand_arguments(self):
        assert address.get_command_output("echo", "$*") == ["$*"]

    def test_get_command_output_returns_sequence_of_lines(self):
        assert address.get_command_output("echo", "1\n2") == ["1", "2"]

    def test_get_command_output_uses_C_locale(self):
        locale = parse_locale_lines(address.get_command_output("locale"))
        assert locale["LC_CTYPE"] == "C.UTF-8"
        assert locale["LC_MESSAGES"] == "C.UTF-8"
        assert locale["LANG"] == "C.UTF-8"
