# Copyright 2012-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test cases for dns.config"""

import errno
import os.path
import random
from textwrap import dedent
from unittest.mock import Mock, sentinel

from netaddr import IPNetwork
import pytest
from twisted.python.filepath import FilePath

from maastesting.factory import factory
from provisioningserver.dns import config
from provisioningserver.dns.config import (
    _rndc_conf_uses_approved_algorithm,
    clean_old_zone_files,
    compose_config_path,
    DNSConfig,
    DNSConfigDirectoryMissing,
    DNSConfigFail,
    execute_rndc_command,
    extract_suggested_named_conf,
    generate_rndc,
    MAAS_NAMED_CONF_NAME,
    MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME,
    MAAS_NAMED_RNDC_CONF_NAME,
    MAAS_RNDC_CONF_NAME,
    NAMED_CONF_OPTIONS,
    render_dns_template,
    report_missing_config_dir,
    set_up_options_conf,
    set_up_rndc,
    uncomment_named_conf,
)
from provisioningserver.dns.zoneconfig import (
    DNSForwardZoneConfig,
    DNSReverseZoneConfig,
)
from provisioningserver.utils import locate_config
from provisioningserver.utils.isc import parse_isc_string, read_isc_file

NAMED_CONF_OPTIONS_CONTENTS = dedent(
    """\
    options {
        forwarders {
            8.8.8.8;
            8.8.4.4;
        };
        dnssec-validation auto;
        allow-query { any; };
        allow-recursion { trusted; };
        allow-query-cache { trusted; };
        auth-nxdomain no;
        listen-on-v6 { any; };
    };
    """
)

NAMED_CONF_OPTIONS_WITH_ALLOW_QUERY_CONTENTS = dedent(
    """\
    options {
        forwarders {
            8.8.8.8;
            8.8.4.4;
        };
        dnssec-validation auto;
        allow-query { any; };
        auth-nxdomain no;
        listen-on-v6 { any; };
    };
    """
)

NAMED_CONF_OPTIONS_NO_ALLOW_CONTENTS = dedent(
    """\
    options {
        forwarders {
            8.8.8.8;
            8.8.4.4;
        };
        dnssec-validation auto;
        auth-nxdomain no;
        listen-on-v6 { any; };
    };
    """
)


def _patch_dns_config_path(tmp_path, monkeypatch):
    """Set the DNS config dir to a temporary directory, and return its path."""
    dns_dir = str(tmp_path / "dns")
    os.makedirs(dns_dir, exist_ok=True)
    monkeypatch.setenv("MAAS_DNS_CONFIG_DIR", dns_dir)
    monkeypatch.setenv("MAAS_BIND_CONFIG_DIR", dns_dir)
    return dns_dir


def _patch_zone_file_config_path(tmp_path, monkeypatch):
    """Set the zone file config dir to a temporary directory, and return its
    path."""
    zone_dir = str(tmp_path / "zones")
    os.makedirs(zone_dir, exist_ok=True)
    monkeypatch.setenv("MAAS_ZONE_FILE_CONFIG_DIR", zone_dir)
    return zone_dir


class TestHelpers:
    def test_get_dns_config_dir_defaults_to_etc_bind_maas(self, monkeypatch):
        monkeypatch.delenv("MAAS_DNS_CONFIG_DIR", raising=False)
        config_dir = config.get_dns_config_dir()
        assert isinstance(config_dir, str)
        assert config_dir == locate_config("../bind/maas")

    def test_get_dns_config_dir_checks_environ_first(
        self, tmp_path, monkeypatch
    ):
        directory = str(tmp_path)
        monkeypatch.setenv("MAAS_DNS_CONFIG_DIR", directory)
        config_dir = config.get_dns_config_dir()
        assert isinstance(config_dir, str)
        assert config_dir == directory

    def test_get_bind_config_dir_defaults_to_etc_bind_maas(self, monkeypatch):
        monkeypatch.delenv("MAAS_BIND_CONFIG_DIR", raising=False)
        config_dir = config.get_bind_config_dir()
        assert isinstance(config_dir, str)
        assert config_dir == locate_config("../bind")

    def test_get_bind_config_dir_checks_environ_first(
        self, tmp_path, monkeypatch
    ):
        directory = str(tmp_path)
        monkeypatch.setenv("MAAS_BIND_CONFIG_DIR", directory)
        config_dir = config.get_bind_config_dir()
        assert isinstance(config_dir, str)
        assert config_dir == directory

    def test_get_dns_root_port_defaults_to_954(self, monkeypatch):
        monkeypatch.delenv("MAAS_DNS_RNDC_PORT", raising=False)
        assert 954 == config.get_dns_rndc_port()

    def test_get_dns_root_port_checks_environ_first(self, monkeypatch):
        port = factory.pick_port()
        monkeypatch.setenv("MAAS_DNS_RNDC_PORT", "%d" % port)
        assert port == config.get_dns_rndc_port()

    def test_get_zone_file_config_dir_defaults_to_var_lib_bind_maas(
        self, monkeypatch
    ):
        monkeypatch.delenv("MAAS_ZONE_FILE_CONFIG_DIR", raising=False)
        assert str(config.get_zone_file_config_dir()) == "/var/lib/bind/maas"

    def test_get_zone_file_config_dir_check_environ_first(
        self, tmp_path, monkeypatch
    ):
        directory = str(tmp_path)
        monkeypatch.setenv("MAAS_ZONE_FILE_CONFIG_DIR", directory)
        assert str(config.get_zone_file_config_dir()) == directory


class TestRNDCUtilities:
    def test_generate_rndc_returns_configurations(self):
        rndc_content, named_content = generate_rndc()
        # rndc_content and named_content look right.
        assert "# Start of rndc.conf" in rndc_content
        assert "controls {" in named_content
        # named_content does not include any comment.
        assert "\n#" not in named_content

    def test_set_up_rndc_writes_configurations(self, tmp_path, monkeypatch):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_rndc()
        expected = (
            (MAAS_RNDC_CONF_NAME, "# Start of rndc.conf"),
            (MAAS_NAMED_RNDC_CONF_NAME, "controls {"),
        )
        for filename, content in expected:
            filepath = os.path.join(dns_conf_dir, filename)
            with open(filepath, encoding="ascii") as stream:
                conf_content = stream.read()
                assert content in conf_content

    def test_set_up_rndc_generates_sha256_key(self, tmp_path, monkeypatch):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_rndc()
        rndc_file = os.path.join(dns_conf_dir, MAAS_RNDC_CONF_NAME)
        with open(rndc_file, encoding="ascii") as stream:
            content = stream.read()
        assert "algorithm hmac-sha256" in content

    def test_set_up_rndc_idempotent_when_already_sha256(
        self, tmp_path, monkeypatch
    ):
        # A rndc.conf already using hmac-sha256 is left unchanged; the helper
        # must not regenerate the key (idempotency requirement).
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        # Write an initial rndc.conf with a known secret and hmac-sha256.
        initial_secret = "aGFyZGVuaW5nLXRlc3Qtc2VjcmV0LWtleQ=="
        rndc_file = os.path.join(dns_conf_dir, MAAS_RNDC_CONF_NAME)
        named_file = os.path.join(dns_conf_dir, MAAS_NAMED_RNDC_CONF_NAME)
        rndc_content = (
            "# Start of rndc.conf\n"
            'key "rndc-maas-key" {\n'
            "    algorithm hmac-sha256;\n"
            f'    secret "{initial_secret}";\n'
            "};\n"
        )
        with open(rndc_file, "w", encoding="ascii") as fh:
            fh.write(rndc_content)
        with open(named_file, "w", encoding="ascii") as fh:
            fh.write("# placeholder named conf\n")
        # Capture mtime before calling set_up_rndc.
        mtime_before = os.path.getmtime(rndc_file)
        set_up_rndc()
        # File must not have been rewritten.
        mtime_after = os.path.getmtime(rndc_file)
        assert mtime_before == mtime_after
        with open(rndc_file, encoding="ascii") as fh:
            assert initial_secret in fh.read()

    def test_set_up_rndc_rotates_non_approved_algorithm(
        self, tmp_path, monkeypatch
    ):
        # A rndc.conf using a non-approved algorithm (e.g. hmac-md5 from a
        # pre-3.7 installation) must be regenerated with hmac-sha256 on the
        # next service restart (key rotation).
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        old_secret = "b2xkLW1kNS1zZWNyZXQ="
        rndc_file = os.path.join(dns_conf_dir, MAAS_RNDC_CONF_NAME)
        # Write a stale rndc.conf with hmac-md5.
        old_content = (
            "# Start of rndc.conf\n"
            'key "rndc-maas-key" {\n'
            "    algorithm hmac-md5;\n"
            f'    secret "{old_secret}";\n'
            "};\n"
        )
        with open(rndc_file, "w", encoding="ascii") as fh:
            fh.write(old_content)
        set_up_rndc()
        with open(rndc_file, encoding="ascii") as fh:
            new_content = fh.read()
        assert "algorithm hmac-sha256" in new_content
        assert old_secret not in new_content

    def test_rndc_conf_uses_approved_algorithm_returns_true_for_sha256(
        self, tmp_path, monkeypatch
    ):
        # Helper returns True for an existing rndc.conf with hmac-sha256.
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        rndc_file = os.path.join(dns_conf_dir, MAAS_RNDC_CONF_NAME)
        with open(rndc_file, "w", encoding="ascii") as fh:
            fh.write(
                "# Start of rndc.conf\n"
                'key "rndc-maas-key" {\n'
                "    algorithm hmac-sha256;\n"
                '    secret "dGVzdA==";\n'
                "};\n"
            )
        assert _rndc_conf_uses_approved_algorithm(rndc_file)

    def test_rndc_conf_uses_approved_algorithm_returns_false_for_md5(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        rndc_file = os.path.join(dns_conf_dir, MAAS_RNDC_CONF_NAME)
        with open(rndc_file, "w", encoding="ascii") as fh:
            fh.write(
                "# Start of rndc.conf\n"
                'key "rndc-maas-key" {\n'
                "    algorithm hmac-md5;\n"
                '    secret "dGVzdA==";\n'
                "};\n"
            )
        assert not _rndc_conf_uses_approved_algorithm(rndc_file)

    def test_rndc_conf_uses_approved_algorithm_returns_false_when_missing(
        self,
    ):
        # Missing file → False (triggers regeneration).
        assert not _rndc_conf_uses_approved_algorithm("/nonexistent/rndc.conf")

    def test_set_up_options_conf_writes_configuration(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        fake_dns = [factory.make_ipv4_address(), factory.make_ipv4_address()]
        set_up_options_conf(upstream_dns=fake_dns)
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        with open(target_file, "r") as fh:
            contents = fh.read()

        for address in fake_dns:
            assert address in contents

    def test_set_up_options_conf_write_config_assumes_no_overrides(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_options_conf()
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        target = read_isc_file(target_file)
        assert target["allow-query"]["any"]
        assert target["allow-recursion"]["trusted"]
        assert target["allow-query-cache"]["trusted"]

    def test_set_up_options_conf_write_config_allows_overrides(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        factory.make_file(
            location=dns_conf_dir,
            name=NAMED_CONF_OPTIONS,
            contents=NAMED_CONF_OPTIONS_CONTENTS,
        )
        set_up_options_conf()
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        target = read_isc_file(target_file)
        assert target.get("allow-query") is None
        assert target.get("allow-recursion") is None
        assert target.get("allow-query-cache") is None

    def test_set_up_options_conf_write_config_allows_zero_overrides(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        factory.make_file(
            location=dns_conf_dir,
            name=NAMED_CONF_OPTIONS,
            contents=NAMED_CONF_OPTIONS_NO_ALLOW_CONTENTS,
        )
        set_up_options_conf()
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        target = read_isc_file(target_file)
        assert target["allow-query"]["any"]
        assert target["allow-recursion"]["trusted"]
        assert target["allow-query-cache"]["trusted"]

    def test_set_up_options_conf_write_config_allows_single_override(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        factory.make_file(
            location=dns_conf_dir,
            name=NAMED_CONF_OPTIONS,
            contents=NAMED_CONF_OPTIONS_WITH_ALLOW_QUERY_CONTENTS,
        )
        set_up_options_conf()
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        target = read_isc_file(target_file)
        assert target.get("allow-query") is None

    def test_set_up_options_conf_handles_no_upstream_dns(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_options_conf()
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        assert os.path.exists(target_file)

    def test_set_up_options_conf_without_hardening(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_options_conf(hardening=False)
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        with open(target_file, "r") as fh:
            contents = fh.read()
        assert 'version "not disclosed"' not in contents
        assert "allow-transfer" not in contents
        assert "fetches-per-zone" not in contents
        assert "fetches-per-server" not in contents

    def test_set_up_options_conf_with_hardening(self, tmp_path, monkeypatch):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_options_conf(hardening=True)
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        with open(target_file, "r") as fh:
            contents = fh.read()
        assert 'version "not disclosed"' in contents
        assert "allow-transfer { none; }" in contents
        assert "fetches-per-zone 100" in contents
        assert "fetches-per-server 100" in contents

    def test_set_up_options_conf_with_hardening_and_dns_bind(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_options_conf(hardening=True, dns_bind=["10.0.0.1"])
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        with open(target_file, "r") as fh:
            contents = fh.read()
        assert "listen-on { 10.0.0.1; 127.0.0.1; }" in contents
        assert "listen-on-v6" not in contents

    def test_set_up_options_conf_with_hardening_and_mixed_dns_bind(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_options_conf(hardening=True, dns_bind=["10.0.0.1", "fd00::1"])
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        with open(target_file, "r") as fh:
            contents = fh.read()
        assert "listen-on { 10.0.0.1; 127.0.0.1; }" in contents
        assert "listen-on-v6 { fd00::1; ::1; }" in contents

    def test_set_up_options_conf_with_hardening_and_ipv6_only_dns_bind(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_options_conf(hardening=True, dns_bind=["fd00::1"])
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        with open(target_file, "r") as fh:
            contents = fh.read()
        assert "listen-on-v6 { fd00::1; ::1; }" in contents
        assert "listen-on {" not in contents

    def test_set_up_options_conf_with_hardening_no_dns_bind(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_options_conf(hardening=True, dns_bind=[])
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        with open(target_file, "r") as fh:
            contents = fh.read()
        assert "listen-on" not in contents

    def test_set_up_options_conf_without_hardening_with_dns_bind(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_options_conf(hardening=False, dns_bind=["10.0.0.1", "fd00::1"])
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        with open(target_file, "r") as fh:
            contents = fh.read()
        assert "listen-on { 10.0.0.1; 127.0.0.1; }" in contents
        assert "listen-on-v6 { fd00::1; ::1; }" in contents

    def test_set_up_options_conf_with_multiple_dns_bind(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_options_conf(
            hardening=True,
            dns_bind=[
                "10.0.0.1",
                "10.0.0.2",
                "fd00::1",
                "fd00::2",
            ],
        )
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        with open(target_file, "r") as fh:
            contents = fh.read()
        assert "listen-on { 10.0.0.1; 10.0.0.2; 127.0.0.1; }" in contents
        assert "listen-on-v6 { fd00::1; fd00::2; ::1; }" in contents

    def test_set_up_options_conf_without_hardening_no_dns_bind(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_options_conf(hardening=False, dns_bind=[])
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        with open(target_file, "r") as fh:
            contents = fh.read()
        assert "listen-on" not in contents

    def test_set_up_options_conf_explicit_allow_transfer(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_options_conf(hardening=False, dns_allow_transfer="trusted")
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        with open(target_file, "r") as fh:
            contents = fh.read()
        assert "allow-transfer { trusted; }" in contents

    def test_set_up_options_conf_allow_transfer_overrides_hardening_default(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_options_conf(hardening=True, dns_allow_transfer="trusted")
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        with open(target_file, "r") as fh:
            contents = fh.read()
        assert "allow-transfer { trusted; }" in contents
        assert "allow-transfer { none; }" not in contents

    def test_set_up_options_conf_allow_transfer_suppressed_when_empty_no_hardening(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_options_conf(hardening=False, dns_allow_transfer="")
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        with open(target_file, "r") as fh:
            contents = fh.read()
        assert "allow-transfer" not in contents

    def test_set_up_options_conf_explicit_fetch_limits(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_options_conf(
            hardening=False,
            dns_fetches_per_zone=50,
            dns_fetches_per_server=75,
        )
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        with open(target_file, "r") as fh:
            contents = fh.read()
        assert "fetches-per-zone 50" in contents
        assert "fetches-per-server 75" in contents

    def test_set_up_options_conf_fetch_limits_override_hardening_defaults(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_options_conf(
            hardening=True,
            dns_fetches_per_zone=200,
            dns_fetches_per_server=300,
        )
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        with open(target_file, "r") as fh:
            contents = fh.read()
        assert "fetches-per-zone 200" in contents
        assert "fetches-per-server 300" in contents
        assert "fetches-per-zone 100" not in contents
        assert "fetches-per-server 100" not in contents

    def test_set_up_options_conf_fetch_limits_suppressed_when_zero_no_hardening(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_options_conf(
            hardening=False,
            dns_fetches_per_zone=0,
            dns_fetches_per_server=0,
        )
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        with open(target_file, "r") as fh:
            contents = fh.read()
        assert "fetches-per-zone" not in contents
        assert "fetches-per-server" not in contents

    def test_set_up_options_conf_allow_transfer_default_applies_when_explicit_empty_string_and_hardening(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_options_conf(hardening=True, dns_allow_transfer="")
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        with open(target_file, "r") as fh:
            contents = fh.read()
        assert "allow-transfer { none; }" in contents

    def test_set_up_options_conf_fetch_limits_default_applies_when_explicit_zero_and_hardening(
        self, tmp_path, monkeypatch
    ):
        dns_conf_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        set_up_options_conf(
            hardening=True,
            dns_fetches_per_zone=0,
            dns_fetches_per_server=0,
        )
        target_file = os.path.join(
            dns_conf_dir, MAAS_NAMED_CONF_OPTIONS_INSIDE_NAME
        )
        with open(target_file, "r") as fh:
            contents = fh.read()
        assert "fetches-per-zone 100" in contents
        assert "fetches-per-server 100" in contents

    def test_clean_old_zone_files(self, tmp_path, monkeypatch):
        zone_file_dir = _patch_zone_file_config_path(tmp_path, monkeypatch)

        zonefiles = [
            os.path.join(zone_file_dir, f"zone.{i}")
            for i, _ in enumerate(range(2))
        ]
        for zonefile in zonefiles:
            with open(zonefile, "w+"):
                pass

        clean_old_zone_files()
        for zonefile in zonefiles:
            with pytest.raises(FileNotFoundError):
                os.stat(zonefile)

    def test_clean_old_zone_files_only_deletes_files(
        self, tmp_path, monkeypatch
    ):
        zone_file_dir = _patch_zone_file_config_path(tmp_path, monkeypatch)

        zonefiles = [
            os.path.join(zone_file_dir, f"zone.{i}")
            for i, _ in enumerate(range(2))
        ]
        for zonefile in zonefiles:
            with open(zonefile, "w+"):
                pass

        child_dir = os.path.join(zone_file_dir, "test_dir")
        os.mkdir(child_dir)

        clean_old_zone_files()
        assert os.stat(child_dir) is not None

    def test_execute_rndc_command_executes_command(
        self, tmp_path, monkeypatch, mocker
    ):
        fake_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        mock_call_and_check = mocker.patch.object(config, "call_and_check")
        command = factory.make_string()
        execute_rndc_command([command], timeout=sentinel.timeout)
        rndc_conf_path = os.path.join(fake_dir, MAAS_RNDC_CONF_NAME)
        expected_command = ["rndc", "-c", rndc_conf_path, command]
        mock_call_and_check.assert_called_once_with(
            expected_command, timeout=sentinel.timeout
        )

    def test_extract_suggested_named_conf_extracts_section(self):
        named_part = factory.make_string()
        # Actual rndc-confgen output, mildly mangled for testing purposes.
        # Note the awkward line break.  The code works by matching that exact
        # line, so there's no leeway with the spacing.
        rndc_config = dedent(
            """\
            # Start of rndc.conf
            %(rndc_part)s
            # End of rndc.conf

            # %(start_marker)s
            %(named_part)s
            # End of named.conf
        """
        ) % {
            "start_marker": (
                "Use with the following in named.conf, "
                "adjusting the allow list as needed:"
            ),
            "rndc_part": factory.make_string(),
            "named_part": named_part,
        }
        # What you get is just the suggested named.conf that's embedded in
        # the rndc-confgen output, not including its header and footer.
        assert named_part + "\n" == extract_suggested_named_conf(rndc_config)

    def test_extract_suggested_named_conf_notices_missing_boundary(self):
        # extract_suggested_named_conf raises an exception if it does not
        # find the expected boundary between the rndc and named parts of the
        # generated configuration.
        rndc_config = dedent(
            """\
            # Start of rndc.conf
            %s

            %s
            # End of named.conf
        """
        ) % (factory.make_string(), factory.make_string())
        with pytest.raises(ValueError):
            extract_suggested_named_conf(rndc_config)

    def test_uncomment_named_conf_uncomments(self):
        rndc_conf = 'key "rndc_key" {}'
        assert rndc_conf == uncomment_named_conf("# %s" % rndc_conf)

    def test_uncomment_named_conf_uncomments_multiple_lines(self):
        # named.conf section, extracted from actual rndc-confgen output.
        # Note the weird %s: the config has a line ending in a space.
        named_comment = (
            dedent(
                """\
            # key "rndc-key" {
            # \talgorithm hmac-sha256;
            # \tsecret "FuvtYZbYYLLJQKtn3zembg==";
            # };
            # %s
            # controls {
            # \tinet 127.0.0.1 port 953
            # \t\tallow { 127.0.0.1; } keys { "rndc-key"; };
            # };
            """
            )
            % ""
        )

        assert (
            'key "rndc-key" {\n\talgorithm hmac-sha256;\n'
            in uncomment_named_conf(named_comment)
        )


class TestComposeConfigPath:
    """Tests for `compose_config_path`."""

    def test_returns_filename_in_dns_config_dir(self, tmp_path, monkeypatch):
        dns_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        filename = factory.make_name("config")
        assert os.path.join(dns_dir, filename) == compose_config_path(filename)


class TestRenderDNSTemplate:
    """Tests for `render_dns_template`."""

    def test_renders_template(self, tmp_path):
        template_text = "X %d Y" % random.randint(1, 10000)
        template_file = tmp_path / "template"
        template_file.write_text(template_text)
        assert template_text == render_dns_template(str(template_file))

    def test_interpolates_parameters(self, tmp_path):
        param_name = factory.make_name("param", sep="_")
        param_value = factory.make_string()
        template_file = tmp_path / "template"
        template_file.write_text("X {{%s}} Y" % param_name)
        assert "X %s Y" % param_value == render_dns_template(
            str(template_file), {param_name: param_value}
        )

    def test_combines_parameter_dicts(self, tmp_path):
        template_file = tmp_path / "template"
        template_file.write_text("{{one}} {{two}}")
        assert "aaa bbb" == render_dns_template(
            str(template_file), {"one": "aaa"}, {"two": "bbb"}
        )

    def test_takes_latest_value_of_redefined_parameter(self, tmp_path):
        template_file = tmp_path / "template"
        template_file.write_text("{{var}}")
        assert "last" == render_dns_template(
            str(template_file),
            {"var": "first"},
            {"var": "middle"},
            {"var": "last"},
        )

    def test_reports_missing_parameters(self, tmp_path):
        template_file = tmp_path / "template"
        template_file.write_text("{{x}}")
        with pytest.raises(DNSConfigFail) as excinfo:
            render_dns_template(str(template_file), {"y": "?"})
        assert "'x' is not defined" in str(excinfo.value)


class TestReportMissingConfigDir:
    """Tests for the `report_missing_config_dir` context manager."""

    def test_specially_reports_missing_config_dir(self, tmp_path):
        with pytest.raises(DNSConfigDirectoryMissing):
            with report_missing_config_dir():
                open(os.path.join(str(tmp_path), "nonexistent-file.txt"))

    def test_succeeds_if_no_exceptions(self):
        with report_missing_config_dir():
            pass
        # The real test is that we get here without error.

    def test_passes_on_other_similar_errors(self):
        with pytest.raises(PermissionError):
            with report_missing_config_dir():
                # OSError(EACCESS) is transmogrified, by Python itself, into
                # PermissionError. It's a subclass of OSError.
                raise OSError(errno.EACCES, "Deliberate error for testing.")

    def test_passes_on_dissimilar_errors(self):
        class DeliberateError(Exception):
            """Deliberately induced error for testing."""

        with pytest.raises(DeliberateError):
            with report_missing_config_dir():
                raise DeliberateError("This exception propagates unchanged.")


class TestDNSConfig:
    """Tests for DNSConfig."""

    def test_write_config_DNSConfigDirectoryMissing_if_dir_missing(
        self, tmp_path, monkeypatch
    ):
        dnsconfig = DNSConfig()
        dir_name = _patch_dns_config_path(tmp_path, monkeypatch)
        os.rmdir(dir_name)
        with pytest.raises(DNSConfigDirectoryMissing):
            dnsconfig.write_config()

    def test_write_config_errors_if_unexpected_exception(
        self, tmp_path, monkeypatch, mocker
    ):
        dnsconfig = DNSConfig()
        exception = IOError(errno.EBUSY, factory.make_string())
        mocker.patch.object(
            config, "atomic_write", Mock(side_effect=exception)
        )
        with pytest.raises(IOError):
            dnsconfig.write_config()

    def test_write_config_skips_writing_if_overwrite_false(
        self, tmp_path, monkeypatch
    ):
        # If DNSConfig is created with overwrite=False, it won't
        # overwrite an existing config file.
        target_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        random_content = factory.make_string()
        factory.make_file(
            location=target_dir,
            name=MAAS_NAMED_CONF_NAME,
            contents=random_content,
        )
        dnsconfig = DNSConfig()
        dnsconfig.write_config(overwrite=False)
        named_conf = os.path.join(target_dir, MAAS_NAMED_CONF_NAME)
        with open(named_conf, "r") as fh:
            contents = fh.read()
        assert contents == random_content

    def test_write_config_writes_config_if_no_existing_file(
        self, tmp_path, monkeypatch
    ):
        # If DNSConfig is created with overwrite=False, the config file
        # will be written if no config file exists.
        target_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        dnsconfig = DNSConfig()
        dnsconfig.write_config(overwrite=False)
        assert os.path.exists(os.path.join(target_dir, MAAS_NAMED_CONF_NAME))

    def test_write_config_writes_config(self, tmp_path, monkeypatch):
        target_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        domain = factory.make_string()
        network = IPNetwork("192.168.0.3/24")
        ip = factory.pick_ip_in_network(network)
        forward_zone = DNSForwardZoneConfig(
            domain, mapping={factory.make_string(): ip}
        )
        reverse_zone = DNSReverseZoneConfig(domain, network=network)
        dnsconfig = DNSConfig((forward_zone, reverse_zone))
        dnsconfig.write_config()
        with open(os.path.join(target_dir, MAAS_NAMED_CONF_NAME)) as fh:
            contents = fh.read()
        for needle in (
            f"zone.{domain}",
            "zone.0.168.192.in-addr.arpa",
            MAAS_NAMED_RNDC_CONF_NAME,
        ):
            assert needle in contents

    def test_write_config_with_forwarded_zones(self, tmp_path, monkeypatch):
        name = factory.make_name("domain")
        ip = factory.make_ip_address()
        forwarded_zones = [(name, [(ip, None)])]
        target_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        DNSConfig(forwarded_zones=forwarded_zones).write_config()
        config_path = os.path.join(target_dir, MAAS_NAMED_CONF_NAME)
        expected_content = dedent(
            f"""
        zone "{name}" {{
            type forward;
            forward only;
            forwarders {{
                {ip} port 53;
            }};
        }};
        """
        )
        config = read_isc_file(config_path)
        expected = parse_isc_string(expected_content)
        assert expected[f'zone "{name}"'] == config[f'zone "{name}"']

    def test_write_config_with_forwarded_zones_with_custom_port(
        self, tmp_path, monkeypatch
    ):
        name = factory.make_name("domain")
        ip = factory.make_ip_address()
        port = 5353
        forwarded_zones = [(name, [(ip, port)])]
        target_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        DNSConfig(forwarded_zones=forwarded_zones).write_config()
        config_path = os.path.join(target_dir, MAAS_NAMED_CONF_NAME)
        expected_content = dedent(
            f"""
        zone "{name}" {{
            type forward;
            forward only;
            forwarders {{
                {ip} port {port};
            }};
        }};
        """
        )
        config = read_isc_file(config_path)
        print(config)
        expected = parse_isc_string(expected_content)
        assert expected[f'zone "{name}"'] == config[f'zone "{name}"']

    def test_write_config_makes_config_world_readable(
        self, tmp_path, monkeypatch
    ):
        target_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        DNSConfig().write_config()
        config_file = FilePath(os.path.join(target_dir, MAAS_NAMED_CONF_NAME))
        assert config_file.getPermissions().other.read

    def test_get_include_snippet_returns_snippet(self, tmp_path, monkeypatch):
        target_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        snippet = DNSConfig.get_include_snippet()
        config_dir = config.get_dns_config_dir()
        assert not snippet.startswith("\n")
        assert snippet.endswith("\n")
        assert target_dir in snippet
        assert (
            f'include "{config_dir}/{DNSConfig.target_file_name}"' in snippet
        )

    def test_write_config_with_authoritive_zones(self, tmp_path, monkeypatch):
        domain = factory.make_name("domain")
        network = IPNetwork("192.168.0.3/24")

        reverse_zone = DNSReverseZoneConfig(domain, network=network)
        reverse_zone.zone_info = [
            type(
                "ZoneInfo",
                (),
                {"zone_name": domain, "target_path": f"zone.{domain}"},
            )()
        ]
        target_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        DNSConfig(zones=[reverse_zone]).write_config(
            allow_only_trusted_transfers=True
        )

        config_path = os.path.join(target_dir, MAAS_NAMED_CONF_NAME)
        expected_content = dedent(
            f"""
        zone "{domain}" {{
            type master;
            # Disable forwarding for authoritative zones, lp:2118833
            forwarders {{ }};
            file "zone.{domain}";
            allow-transfer {{
                trusted;
            }};
        }};
        """
        )
        config = read_isc_file(config_path)
        expected = parse_isc_string(expected_content)

        assert expected[f'zone "{domain}"'] == config[f'zone "{domain}"']

    def test_write_config_without_trusted_transfers(
        self, tmp_path, monkeypatch
    ):
        domain = factory.make_name("domain")
        network = IPNetwork("192.168.0.3/24")

        reverse_zone = DNSReverseZoneConfig(domain, network=network)
        reverse_zone.zone_info = [
            type(
                "ZoneInfo",
                (),
                {"zone_name": domain, "target_path": f"zone.{domain}"},
            )()
        ]
        target_dir = _patch_dns_config_path(tmp_path, monkeypatch)
        DNSConfig(zones=[reverse_zone]).write_config(
            allow_only_trusted_transfers=False
        )

        config_path = os.path.join(target_dir, MAAS_NAMED_CONF_NAME)
        expected_content = dedent(
            f"""
            zone "{domain}" {{
                type master;
                # Disable forwarding for authoritative zones, lp:2118833
                forwarders {{ }};
                file "zone.{domain}";
            }};
            """
        )
        config = read_isc_file(config_path)
        expected = parse_isc_string(expected_content)

        assert expected[f'zone "{domain}"'] == config[f'zone "{domain}"']
