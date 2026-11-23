# Copyright 2012-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the BIND fixture."""

import os
from subprocess import check_output
from types import SimpleNamespace

import pytest

from provisioningserver.testing.bindfixture import (
    BINDServer,
    BINDServerResources,
    BINDServerRunner,
)
from provisioningserver.utils.shell import get_env_with_locale


def dig_call(port=53, server="localhost", commands=None):
    """Call `dig` with the given command.

    Note that calling dig without a command will perform an NS
    query for "." (the root) which is useful to check if there
    is a running server.

    :param port: Port of the queried DNS server (defaults to 53).
    :param server: IP address of the queried DNS server (defaults
        to '127.0.0.1').
    :param commands: List of dig commands to run (defaults to None
        which will perform an NS query for "." (the root)).
    :return: The output as a string.
    :rtype: str
    """
    # The time and tries below are high so that tests pass in environments
    # that are much slower than the average developer's machine, so beware
    # before lowering. Many Bothans died to discover these parameters.
    cmd = ["dig", "+time=10", "+tries=5", f"@{server}", "-p", str(port)]
    if commands is not None:
        cmd.extend(commands)
    output = check_output(cmd, env=get_env_with_locale())
    return output.decode("utf-8").strip()


class TestBINDFixture:
    def test_start_check_shutdown(self):
        # The fixture correctly starts and stops BIND.
        config = BINDServerResources(timeout_deadline=10, timeout_interval=0.5)
        with BINDServer(config) as fixture:
            result = dig_call(fixture.config.port)
            assert "Got answer" in result
        assert not fixture.runner.is_running()

    def test_config(self):
        # The configuration can be passed in.
        config = BINDServerResources(timeout_deadline=10, timeout_interval=0.5)
        with BINDServer(config) as fixture:
            assert config is fixture.config

    def test_start_timeout_includes_server_log(self, tmp_path, mocker):
        log_file = tmp_path / "named.log"
        log_file.write_text("named failed to start")
        config = SimpleNamespace(
            timeout_deadline=1,
            timeout_interval=0,
            log_file=str(log_file),
        )
        runner = BINDServerRunner(config)
        mocker.patch.object(runner, "_spawn")
        mocker.patch(
            "provisioningserver.testing.bindfixture.time.time",
            side_effect=[0, 2],
        )
        mocker.patch.object(runner, "is_running", return_value=False)

        with pytest.raises(RuntimeError, match="named failed to start"):
            runner._start()


class TestBINDServerResources:
    def test_defaults(self):
        with BINDServerResources() as resources:
            assert isinstance(resources.port, int)
            assert isinstance(resources.rndc_port, int)
            assert isinstance(resources.homedir, str)
            assert isinstance(resources.log_file, str)
            assert resources.include_in_options is None
            assert isinstance(resources.named_file, str)
            assert isinstance(resources.conf_file, str)
            assert isinstance(resources.rndcconf_file, str)
            assert resources.timeout_deadline == 15
            assert resources.timeout_interval == 0.01

    def test_setUp_copies_executable(self):
        with BINDServerResources() as resources:
            assert os.path.isfile(resources.named_file)

    def test_setUp_creates_config_files(self):
        with BINDServerResources() as resources:
            with open(resources.conf_file, "r") as fh:
                conf_contents = fh.read()
            with open(resources.rndcconf_file, "r") as fh:
                rndcconf_contents = fh.read()
        assert f"listen-on port {resources.port}" in conf_contents
        assert f"default-port {resources.rndc_port}" in rndcconf_contents
        # This should ideally be in its own test but it's here to cut
        # test run time. See test_setUp_honours_include_in_options()
        # as its counterpart.
        assert "forwarders" not in conf_contents

    def test_setUp_honours_include_in_options(self):
        forwarders = "forwarders { 1.2.3.4; };"
        with BINDServerResources(include_in_options=forwarders) as resources:
            with open(resources.conf_file, "r") as fh:
                conf_contents = fh.read()

        assert resources.homedir + "/" + forwarders in conf_contents

    def test_defaults_reallocated_after_teardown(self):
        seen_homedirs = set()
        resources = BINDServerResources()
        for _ in range(2):
            with resources:
                assert os.path.exists(resources.homedir)
                assert resources.homedir not in seen_homedirs
                seen_homedirs.add(resources.homedir)
