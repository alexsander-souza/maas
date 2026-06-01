#  Copyright 2026 Canonical Ltd.  This software is licensed under the GNU Affero General Public License version 3 (see the file LICENSE).

from unittest.mock import mock_open, patch

import maascommon.fips as fips_module


class TestFIPS:
    @patch("builtins.open", new_callable=mock_open, read_data="1\n")
    def test_detect_fips_mode_enabled(self, _mock_open):
        assert fips_module.detect_fips_mode() is True

    @patch("builtins.open", new_callable=mock_open, read_data="0\n")
    def test_detect_fips_mode_disabled(self, _mock_open):
        assert fips_module.detect_fips_mode() is False

    @patch("builtins.open", side_effect=OSError)
    def test_detect_fips_mode_missing_file(self, _mock_open):
        assert fips_module.detect_fips_mode() is False

    @patch("builtins.open", side_effect=OSError)
    def test_detect_fips_mode_oserror_logs_warning(self, _mock_open):
        with patch.object(fips_module.logger, "warning") as mock_warning:
            assert fips_module.detect_fips_mode() is False

        mock_warning.assert_called_once()

    def test_is_fips_enabled_returns_cached(self):
        with (
            patch.object(fips_module, "_fips_checked", True),
            patch.object(fips_module, "_fips_value", True),
        ):
            assert fips_module.is_fips_enabled() is True

    def test_fips_status_model(self):
        status = fips_module.FIPSStatus(
            fips_enabled=True,
            detection_source="/proc/sys/crypto/fips_enabled",
        )

        assert status.fips_enabled is True
        assert status.detection_source == "/proc/sys/crypto/fips_enabled"

    def test_get_fips_ssh_config_returns_allow_lists(self):
        result = fips_module.get_fips_ssh_config()

        # The function returns explicit allow-lists, not disabled sets.
        assert "hmac-md5" not in result["macs"]
        assert "3des-cbc" not in result["ciphers"]
        assert "hmac-sha2-256" in result["macs"]
        assert "aes128-ctr" in result["ciphers"]

    def test_fips_ssh_config_singleton(self):
        assert isinstance(
            fips_module.FIPS_SSH_CONFIG,
            fips_module.FIPSSSHConfig,
        )
        assert fips_module.FIPS_SSH_CONFIG.ciphers == (
            "aes128-ctr",
            "aes192-ctr",
            "aes256-ctr",
            "aes128-gcm@openssh.com",
            "aes256-gcm@openssh.com",
        )
