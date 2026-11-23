# Copyright 2014-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for log.py"""

import pathlib
import subprocess
import sys

import pytest

from maastesting.factory import factory
from provisioningserver.logger import LoggingMode
from provisioningserver.logger import testing as logger_testing_module
from provisioningserver.logger.testing import find_log_lines
from provisioningserver.utils.shell import get_env_with_locale

here = pathlib.Path(logger_testing_module.__file__).parent


def log_something(
    name: str,
    *,
    verbosity: int,
    set_verbosity: int = None,
    mode: LoggingMode,
    use_json_logging: bool,
):
    env = dict(get_env_with_locale(), PYTHONPATH=":".join(sys.path))
    script = here.joinpath("logsomething.py")
    args = [
        "--name",
        name,
        "--verbosity",
        "%d" % verbosity,
        "--mode",
        mode.name,
    ]
    if use_json_logging:
        args.append("--use_json_logging")
    if set_verbosity is not None:
        args.extend(["--set-verbosity", "%d" % set_verbosity])
    cmd = [sys.executable, str(script)] + args
    output = subprocess.check_output(cmd, env=env, stderr=subprocess.STDOUT)
    return output.decode("utf-8")


@pytest.mark.parametrize(
    "initial_only,increasing,use_json_logging",
    [
        (True, False, False),
        (True, False, True),
        (False, True, False),
        (False, True, True),
        (False, False, True),
        (False, False, False),
    ],
    ids=[
        "initial_only",
        "initial_only_with_json",
        "increasing_verbosity",
        "increasing_verbosity_with_json",
        "decreasing_verbosity",
        "decreasing_verbosity_with_json",
    ],
)
class TestLogging:
    """Test logging in MAAS as configured by `p.logger.configure`.

    The "twistd" tests reflect usage under `twistd`.

    The "command" tests reflect usage at an interactive terminal, like when
    invoking `maas-rackd`. The chief difference here is that neither stdout
    nor stderr are wrapped.
    """

    def _get_log_levels(
        self, verbosity_under_test: int, initial_only, increasing
    ):
        if initial_only:
            verbosity = verbosity_under_test
            set_verbosity = None
        elif increasing:
            verbosity = 0
            set_verbosity = verbosity_under_test
        else:
            verbosity = 3
            set_verbosity = verbosity_under_test
        return verbosity, set_verbosity

    def test_twistd_default_verbosity(
        self, initial_only, increasing, use_json_logging
    ):
        verbosity, set_verbosity = self._get_log_levels(
            2, initial_only, increasing
        )
        name = factory.make_name("log.name")
        logged = log_something(
            name,
            verbosity=verbosity,
            set_verbosity=set_verbosity,
            mode=LoggingMode.TWISTD,
            use_json_logging=use_json_logging,
        )
        observed = find_log_lines(logged, use_json_logging)
        expected = [
            (name, "info", "From `twisted.logger`."),
            (name, "warn", "From `twisted.logger`."),
            (name, "error", "From `twisted.logger`."),
            (name, "info", "From `twisted.python.log`."),
            ("logsomething", "info", "From `twisted.python.log.logfile`."),
            (name, "info", "From `logging`."),
            (name, "warn", "From `logging`."),
            (name, "error", "From `logging`."),
            ("maas." + name, "info", "From `get_maas_logger`."),
            ("maas." + name, "warn", "From `get_maas_logger`."),
            ("maas." + name, "error", "From `get_maas_logger`."),
            ("stdout", "info", "Printing to stdout."),
            ("stderr", "error", "Printing to stderr."),
            ("-", "warn", "UserWarning: This is a warning!"),
        ]
        assert expected == observed

    def test_twistd_high_verbosity(
        self, initial_only, increasing, use_json_logging
    ):
        verbosity, set_verbosity = self._get_log_levels(
            3, initial_only, increasing
        )
        name = factory.make_name("log.name")
        logged = log_something(
            name,
            verbosity=verbosity,
            set_verbosity=set_verbosity,
            mode=LoggingMode.TWISTD,
            use_json_logging=use_json_logging,
        )
        observed = find_log_lines(logged, use_json_logging)
        expected = [
            (name, "debug", "From `twisted.logger`."),
            (name, "info", "From `twisted.logger`."),
            (name, "warn", "From `twisted.logger`."),
            (name, "error", "From `twisted.logger`."),
            (name, "info", "From `twisted.python.log`."),
            ("logsomething", "info", "From `twisted.python.log.logfile`."),
            (name, "debug", "From `logging`."),
            (name, "info", "From `logging`."),
            (name, "warn", "From `logging`."),
            (name, "error", "From `logging`."),
            ("maas." + name, "debug", "From `get_maas_logger`."),
            ("maas." + name, "info", "From `get_maas_logger`."),
            ("maas." + name, "warn", "From `get_maas_logger`."),
            ("maas." + name, "error", "From `get_maas_logger`."),
            ("stdout", "info", "Printing to stdout."),
            ("stderr", "error", "Printing to stderr."),
            ("-", "warn", "UserWarning: This is a warning!"),
        ]
        assert expected == observed

    def test_twistd_low_verbosity(
        self, initial_only, increasing, use_json_logging
    ):
        verbosity, set_verbosity = self._get_log_levels(
            1, initial_only, increasing
        )
        name = factory.make_name("log.name")
        logged = log_something(
            name,
            verbosity=verbosity,
            set_verbosity=set_verbosity,
            mode=LoggingMode.TWISTD,
            use_json_logging=use_json_logging,
        )
        observed = find_log_lines(logged, use_json_logging)
        expected = [
            (name, "warn", "From `twisted.logger`."),
            (name, "error", "From `twisted.logger`."),
            (name, "warn", "From `logging`."),
            (name, "error", "From `logging`."),
            ("maas." + name, "warn", "From `get_maas_logger`."),
            ("maas." + name, "error", "From `get_maas_logger`."),
            ("stderr", "error", "Printing to stderr."),
            ("-", "warn", "UserWarning: This is a warning!"),
        ]
        assert expected == observed

    def test_twistd_lowest_verbosity(
        self, initial_only, increasing, use_json_logging
    ):
        verbosity, set_verbosity = self._get_log_levels(
            0, initial_only, increasing
        )
        name = factory.make_name("log.name")
        logged = log_something(
            name,
            verbosity=verbosity,
            set_verbosity=set_verbosity,
            mode=LoggingMode.TWISTD,
            use_json_logging=use_json_logging,
        )
        observed = find_log_lines(logged, use_json_logging)
        expected = [
            (name, "error", "From `twisted.logger`."),
            (name, "error", "From `logging`."),
            ("maas." + name, "error", "From `get_maas_logger`."),
            ("stderr", "error", "Printing to stderr."),
        ]
        assert expected == observed

    def test_command_default_verbosity(
        self, initial_only, increasing, use_json_logging
    ):
        verbosity, set_verbosity = self._get_log_levels(
            2, initial_only, increasing
        )
        name = factory.make_name("log.name")
        logged = log_something(
            name,
            verbosity=verbosity,
            set_verbosity=set_verbosity,
            mode=LoggingMode.COMMAND,
            use_json_logging=use_json_logging,
        )
        observed = find_log_lines(logged, use_json_logging)
        expected = [
            (name, "info", "From `twisted.logger`."),
            (name, "warn", "From `twisted.logger`."),
            (name, "error", "From `twisted.logger`."),
            (name, "info", "From `twisted.python.log`."),
            ("logsomething", "info", "From `twisted.python.log.logfile`."),
            (name, "info", "From `logging`."),
            (name, "warn", "From `logging`."),
            (name, "error", "From `logging`."),
            ("maas." + name, "info", "From `get_maas_logger`."),
            ("maas." + name, "warn", "From `get_maas_logger`."),
            ("maas." + name, "error", "From `get_maas_logger`."),
        ]
        assert expected == observed
        for needle in [
            "Printing to stdout.",
            "Printing to stderr.",
            "This is a warning",
        ]:
            assert needle in logged

    def test_command_high_verbosity(
        self, initial_only, increasing, use_json_logging
    ):
        verbosity, set_verbosity = self._get_log_levels(
            3, initial_only, increasing
        )
        name = factory.make_name("log.name")
        logged = log_something(
            name,
            verbosity=verbosity,
            set_verbosity=set_verbosity,
            mode=LoggingMode.COMMAND,
            use_json_logging=use_json_logging,
        )
        observed = find_log_lines(logged, use_json_logging)
        expected = [
            (name, "debug", "From `twisted.logger`."),
            (name, "info", "From `twisted.logger`."),
            (name, "warn", "From `twisted.logger`."),
            (name, "error", "From `twisted.logger`."),
            (name, "info", "From `twisted.python.log`."),
            ("logsomething", "info", "From `twisted.python.log.logfile`."),
            (name, "debug", "From `logging`."),
            (name, "info", "From `logging`."),
            (name, "warn", "From `logging`."),
            (name, "error", "From `logging`."),
            ("maas." + name, "debug", "From `get_maas_logger`."),
            ("maas." + name, "info", "From `get_maas_logger`."),
            ("maas." + name, "warn", "From `get_maas_logger`."),
            ("maas." + name, "error", "From `get_maas_logger`."),
        ]
        assert expected == observed
        for needle in [
            "Printing to stdout.",
            "Printing to stderr.",
            "This is a warning",
        ]:
            assert needle in logged

    def test_command_low_verbosity(
        self, initial_only, increasing, use_json_logging
    ):
        verbosity, set_verbosity = self._get_log_levels(
            1, initial_only, increasing
        )
        name = factory.make_name("log.name")
        logged = log_something(
            name,
            verbosity=verbosity,
            set_verbosity=set_verbosity,
            mode=LoggingMode.COMMAND,
            use_json_logging=use_json_logging,
        )
        observed = find_log_lines(logged, use_json_logging)
        expected = [
            (name, "warn", "From `twisted.logger`."),
            (name, "error", "From `twisted.logger`."),
            (name, "warn", "From `logging`."),
            (name, "error", "From `logging`."),
            ("maas." + name, "warn", "From `get_maas_logger`."),
            ("maas." + name, "error", "From `get_maas_logger`."),
        ]
        assert expected == observed
        for needle in [
            "Printing to stdout.",
            "Printing to stderr.",
            "This is a warning",
        ]:
            assert needle in logged

    def test_command_lowest_verbosity(
        self, initial_only, increasing, use_json_logging
    ):
        verbosity, set_verbosity = self._get_log_levels(
            0, initial_only, increasing
        )
        name = factory.make_name("log.name")
        logged = log_something(
            name,
            verbosity=verbosity,
            set_verbosity=set_verbosity,
            mode=LoggingMode.COMMAND,
            use_json_logging=use_json_logging,
        )
        observed = find_log_lines(logged, use_json_logging)
        expected = [
            (name, "error", "From `twisted.logger`."),
            (name, "error", "From `logging`."),
            ("maas." + name, "error", "From `get_maas_logger`."),
        ]
        assert expected == observed
        for needle in [
            "Printing to stdout.",
            "Printing to stderr.",
            "This is a warning",
        ]:
            assert needle in logged
