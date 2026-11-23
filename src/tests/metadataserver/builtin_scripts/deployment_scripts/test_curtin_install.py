# Copyright 2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import io
import os
import time
import uuid

import pytest
import yaml

import metadataserver.builtin_scripts.deployment_scripts.curtin_install as ci

VALID_CFG = {
    "datasource": {
        "MAAS": {
            "consumer_key": "ck",
            "token_key": "tk",
            "token_secret": "ts",
            "metadata_url": "http://maas/MAAS/metadata/curtin",
        }
    }
}


class TestCurtinInstall:
    def test_extract_maas_config_success(self):
        maas = ci.extract_maas_config(VALID_CFG)
        assert maas["consumer_key"] == "ck"
        assert maas["token_key"] == "tk"
        assert maas["token_secret"] == "ts"

    def test_extract_maas_config_failure(self):
        with pytest.raises(ci.CurtinInstallError):
            ci.extract_maas_config({})

    def test_build_maas_url(self):
        url = ci.get_maas_base_url("http://x/MAAS/metadata/curtin")
        assert url == "http://x"

    def test_build_auth_header_deterministic(self, mocker):
        mocker.patch.object(time, "time", return_value=123)
        mocker.patch.object(
            uuid, "uuid4", return_value="00000000-0000-0000-0000-000000000000"
        )
        header = ci.build_auth_header(
            "ck",
            "tk",
            "ts",
        )
        assert "oauth_consumer_key=ck" in header
        assert "oauth_token=tk" in header
        assert "oauth_signature=&ts" in header
        assert "oauth_timestamp=123" in header
        assert "oauth_nonce=00000000-0000-0000-0000-000000000000" in header

    def test_download_installer_success(self, tmp_path, mocker):
        fake_resp = io.BytesIO(b"binarydata")
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = lambda *a: None

        urlopen_mock = mocker.patch.object(ci, "urlopen")
        urlopen_mock.return_value = fake_resp

        out = os.path.join(tmp_path, "installer")
        ci.download_installer("http://x", "auth", out)

        with open(out, "rb") as f:
            assert f.read() == b"binarydata"

    def test_download_installer_empty(self, tmp_path, mocker):
        fake_resp = io.BytesIO(b"")
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = lambda *a: None

        urlopen_mock = mocker.patch.object(ci, "urlopen")
        urlopen_mock.return_value = fake_resp

        out = os.path.join(tmp_path, "installer")
        with pytest.raises(ci.CurtinInstallError):
            ci.download_installer("http://x", "auth", out)

    def test_run_installer_success(self, mocker):
        subprocess_mock = mocker.patch.object(ci.subprocess, "run")
        subprocess_mock.return_value = None
        ci.run_installer("./installer")
        subprocess_mock.assert_called_once_with(["./installer"], check=True)

    def test_run_installer_failure(self, mocker):
        subprocess_mock = mocker.patch.object(ci.subprocess, "run")
        subprocess_mock.side_effect = Exception("boom")
        with pytest.raises(ci.CurtinInstallError):
            ci.run_installer("./installer")

    def test_script_flow(self, tmp_path, mocker):
        tmpfile = tmp_path / "config.yaml"
        tmpfile.write_text(yaml.dump(VALID_CFG))

        fake_installer_data = b"#!/bin/sh\necho curtin\n"

        fake_resp = io.BytesIO(fake_installer_data)
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = lambda *a: None

        mocker.patch.object(ci, "CFG_FILE", str(tmpfile))

        urlopen_mock = mocker.patch.object(ci, "urlopen")
        urlopen_mock.return_value = fake_resp

        subprocess_run_mock = mocker.patch.object(ci, "subprocess")
        subprocess_run_mock.run.return_value = None

        installer_path = "./curtin-installer"
        try:
            ci.main()
        finally:
            if os.path.exists(installer_path):
                os.remove(installer_path)

        urlopen_mock.assert_called_once()

        subprocess_run_mock.run.assert_called_once_with(
            [installer_path],
            check=True,
        )
