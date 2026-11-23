# Copyright 2012-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the setup-dns command."""

from argparse import ArgumentParser
import io
import os

import pytest

from maastesting.factory import factory
from provisioningserver.dns.commands.setup_dns import add_arguments, run
from provisioningserver.dns.config import (
    MAAS_NAMED_CONF_NAME,
    MAAS_RNDC_CONF_NAME,
)


class TestSetupCommand:
    """Tests for the setup-dns command."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.output = io.StringIO()
        self.error_output = io.StringIO()
        self.parser = ArgumentParser()
        add_arguments(self.parser)

    def run_command(self, *args):
        parsed_args = self.parser.parse_args([*args])
        return run(parsed_args, stdout=self.output, stderr=self.error_output)

    def test_writes_configuration(self, tmp_path, monkeypatch):
        dns_conf_dir = tmp_path / "dns"
        dns_conf_dir.mkdir()
        monkeypatch.setenv("MAAS_DNS_CONFIG_DIR", str(dns_conf_dir))
        monkeypatch.setenv("MAAS_BIND_CONFIG_DIR", str(dns_conf_dir))
        monkeypatch.setenv("MAAS_ZONE_FILE_CONFIG_DIR", str(dns_conf_dir))
        self.run_command()
        named_config = os.path.join(dns_conf_dir, MAAS_NAMED_CONF_NAME)
        rndc_conf_path = os.path.join(dns_conf_dir, MAAS_RNDC_CONF_NAME)
        assert os.path.exists(rndc_conf_path)
        assert os.path.exists(named_config)

    def test_does_not_overwrite_config(self, tmp_path, monkeypatch):
        dns_conf_dir = tmp_path / "dns"
        dns_conf_dir.mkdir()
        zone_file_dir = tmp_path / "zone"
        zone_file_dir.mkdir()
        monkeypatch.setenv("MAAS_DNS_CONFIG_DIR", str(dns_conf_dir))
        monkeypatch.setenv("MAAS_BIND_CONFIG_DIR", str(dns_conf_dir))
        monkeypatch.setenv("MAAS_ZONE_FILE_CONFIG_DIR", str(zone_file_dir))
        random_content = factory.make_string()
        (dns_conf_dir / MAAS_NAMED_CONF_NAME).write_text(random_content)
        self.run_command("--no-clobber")
        contents = (dns_conf_dir / MAAS_NAMED_CONF_NAME).read_text()
        assert random_content in contents
