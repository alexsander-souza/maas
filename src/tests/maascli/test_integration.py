# Copyright 2012-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Integration-test the `maascli` command."""

import os.path
import random
from subprocess import CalledProcessError, check_output, STDOUT

import pytest

from maascli import main
from maascli.config import ProfileConfig
from maascli.testing.config import make_configs
from maascli.utils import handler_command_name
from maastesting import dev_root


def locate_maascli():
    return os.path.join(dev_root, "bin", "maas")


class TestMAASCli:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        new_home = str(tmp_path / "home")
        (tmp_path / "home").mkdir(parents=True, exist_ok=True)
        monkeypatch.setenv("HOME", new_home)

    def run_command(self, *args):
        check_output([locate_maascli()] + list(args), stderr=STDOUT)

    def test_run_without_args_fails(self):
        with pytest.raises(CalledProcessError):
            self.run_command()

    def test_run_without_args_shows_help_reminder(self):
        with pytest.raises(CalledProcessError) as exc_info:
            self.run_command()
        assert exc_info.value.output.decode("utf-8").startswith(
            "usage: maas [-h] COMMAND"
        )

    def test_help_option_succeeds(self):
        try:
            self.run_command("-h")
        except CalledProcessError as error:
            pytest.fail(error.output.decode("ascii"))
        else:
            # The test is that we get here without error.
            pass

    def test_list_command_succeeds(self):
        try:
            self.run_command("list")
        except CalledProcessError as error:
            pytest.fail(error.output.decode("ascii"))
        else:
            # The test is that we get here without error.
            pass


class TestMain:
    """Tests of `maascli.main` directly."""

    def fake_profile(self, mocker):
        """Fake a profile."""
        configs = make_configs()  # Instance of FakeConfig.
        mocker.patch.object(ProfileConfig, "open").return_value = configs
        return configs

    def test_complains_about_too_few_arguments(self, mocker, capsys):
        configs = self.fake_profile(mocker)
        [profile_name] = configs
        resources = configs[profile_name]["description"]["resources"]
        resource_name = random.choice(resources)["name"]
        handler_name = handler_command_name(resource_name)
        command = "maas", profile_name, handler_name

        with pytest.raises(SystemExit) as exc_info:
            main(command)

        assert exc_info.value.code == 2
        out, err = capsys.readouterr()
        assert (
            f"usage: maas {profile_name} {handler_name} [-h] COMMAND ..."
            in err
        )
        assert "too few arguments" in err
