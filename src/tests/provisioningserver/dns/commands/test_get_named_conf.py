# Copyright 2012-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the get-named-conf command."""

from argparse import ArgumentParser
import io

import pytest

from provisioningserver.dns.commands.get_named_conf import add_arguments, run


class TestGetNamedConfCommand:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        self.output = io.StringIO()
        self.error_output = io.StringIO()
        self.parser = ArgumentParser()
        add_arguments(self.parser)
        self.tmp_path = tmp_path

    def run_command(self, *args):
        parsed_args = self.parser.parse_args([*args])
        return run(parsed_args, stdout=self.output, stderr=self.error_output)

    def test_get_named_conf_returns_snippet(self):
        self.run_command()
        result = self.output.getvalue()
        # Just check that the returned snippet looks all right.
        assert 'include "' in result

    def test_get_named_conf_appends_to_config_file(self):
        file_path = str(self.tmp_path / "named.conf")
        # Create an empty config file so --edit can append to it.
        open(file_path, "w").close()
        self.run_command("--edit", "--config-path", file_path)
        with open(file_path, "r") as fh:
            contents = fh.read()

        assert 'include "' in contents
