from io import BytesIO
import json
import os
from pathlib import Path
from unittest.mock import ANY, call, MagicMock
from urllib.error import HTTPError

import yaml

from provisioningserver.refresh.maas_api_helper import Credentials
from snippets import maas_run_scripts
from snippets.maas_run_scripts import (
    get_config,
    main,
    parse_args,
    Script,
    ScriptRunResult,
    ScriptsPaths,
    write_token,
)


class TestScriptsPaths:
    def test_paths(self, tmp_path):
        base_path = tmp_path
        scripts_paths = ScriptsPaths(base_path=base_path)
        assert scripts_paths.scripts == base_path / "scripts"
        assert scripts_paths.out == base_path / "out"
        assert scripts_paths.downloads == base_path / "downloads"
        assert scripts_paths.resources_file == base_path / "resources.json"

    def test_ensure(self, tmp_path):
        base_path = tmp_path
        scripts_paths = ScriptsPaths(base_path=base_path)
        scripts_paths.ensure()
        assert scripts_paths.scripts.exists()
        assert scripts_paths.out.exists()
        assert scripts_paths.downloads.exists()
        assert scripts_paths.resources_file.exists()

    def test_ensure_clears_existing_content(self, tmp_path):
        base_path = tmp_path
        scripts_paths = ScriptsPaths(base_path=base_path)
        scripts_paths.scripts.mkdir()
        a_file = scripts_paths.scripts / "a-file"
        a_file.touch()
        scripts_paths.ensure()
        assert not a_file.exists()


class TestScript:
    def test_properties(self):
        info = {
            "name": "myscript",
            "path": "commissioning-scripts/myscript",
        }
        paths = ScriptsPaths(base_path=Path("/base"))
        script = Script(info, "http://maas.example.com", paths)
        assert script.name == "myscript"
        assert script.command == [
            str(paths.scripts / "commissioning-scripts/myscript")
        ]
        assert script.stdout_path == paths.out / "myscript.out"
        assert script.stderr_path == paths.out / "myscript.err"
        assert script.combined_path == paths.out / "myscript"
        assert script.result_path == paths.out / "myscript.yaml"

    def test_environ(self):
        info = {
            "name": "myscript",
            "path": "commissioning-scripts/myscript",
            "timeout_seconds": 100,
            "bmc_config_path": "/bmc-config",
        }
        paths = ScriptsPaths(base_path=Path("/base"))
        script = Script(info, "http://maas.example.com", paths)
        assert script.environ["MAAS_BASE_URL"] == "http://maas.example.com"
        assert script.environ["MAAS_RESOURCES_FILE"] == "/base/resources.json"
        assert script.environ["RUNTIME"] == "100"
        assert script.environ["BMC_CONFIG_PATH"] == "/bmc-config"
        assert script.environ["HAS_STARTED"] == "False"
        # vars from the original environ are preserved
        assert script.environ["PATH"] == os.environ["PATH"]

    def test_should_run(self):
        infos = [
            {
                "name": "myscript",
                "path": "commissioning-scripts/myscript",
                "default": True,
                "tags": ["node", "deploy-info"],
            },
            {
                "name": "myscript",
                "path": "commissioning-scripts/myscript",
                "default": False,
                "tags": ["node", "deploy-info"],
            },
            {
                "name": "myscript",
                "path": "commissioning-scripts/myscript",
                "default": True,
                "tags": ["node"],
            },
            {
                "name": "myscript",
                "path": "commissioning-scripts/myscript",
                "default": False,
                "tags": ["node"],
            },
        ]
        should_run = [
            Script(info, "http://maas.example.com", None).should_run()
            for info in infos
        ]
        assert should_run == [True, False, False, False]

    def test_run(self, mocker):
        fake_process = mocker.patch.object(
            maas_run_scripts.subprocess, "Popen"
        ).return_value
        mock_capture_script_output = mocker.patch.object(
            maas_run_scripts, "capture_script_output"
        )
        info = {
            "name": "myscript",
            "path": "commissioning-scripts/myscript",
            "timeout_seconds": 100,
        }
        paths = ScriptsPaths(base_path=Path("/base"))
        script = Script(info, "http://maas.example.com", paths)
        result = script.run()
        assert result.exit_status == 0
        assert result.status == "WORKING"
        assert result.error is None
        assert result.runtime > 0.0
        mock_capture_script_output.assert_called_once_with(
            fake_process,
            script.combined_path,
            script.stdout_path,
            script.stderr_path,
            timeout_seconds=100,
            console_output=False,
        )

    def test_run_failed(self, mocker):
        mocker.patch.object(maas_run_scripts.subprocess, "Popen")
        error = OSError("Fail!")
        error.errno = 10
        mocker.patch.object(
            maas_run_scripts, "capture_script_output"
        ).side_effect = error
        info = {
            "name": "myscript",
            "path": "commissioning-scripts/myscript",
            "timeout_seconds": 100,
        }
        paths = ScriptsPaths(base_path=Path("/base"))
        script = Script(info, "http://maas.example.com", paths)
        result = script.run()
        assert result.exit_status == 10
        assert result.status == "FAILED"
        assert result.error == "Failed to execute myscript: 10"

    def test_run_timedout(self, mocker):
        mocker.patch.object(maas_run_scripts.subprocess, "Popen")
        error = OSError("Timeout!")
        error.errno = 124
        mocker.patch.object(
            maas_run_scripts, "capture_script_output"
        ).side_effect = error
        info = {
            "name": "myscript",
            "path": "commissioning-scripts/myscript",
            "timeout_seconds": 100,
        }
        paths = ScriptsPaths(base_path=Path("/base"))
        script = Script(info, "http://maas.example.com", paths)
        result = script.run()
        assert result.exit_status == 124
        assert result.status == "TIMEDOUT"
        assert result.error == "Timeout(0:01:40) expired on myscript"


class TestGetConfig:
    def test_read_from_config(self, tmp_path):
        conf = {
            "reporting": {
                "maas": {
                    "token_key": "token-key",
                    "token_secret": "token-secret",
                    "consumer_key": "consumer-key",
                    "consumer_secret": "consumer-secret",
                    "endpoint": "http://example.com",
                }
            }
        }
        config_file = tmp_path / "conf.yaml"
        with config_file.open("w") as fd:
            yaml.dump(conf, fd)
        ns = parse_args(["report-results", "--config", str(config_file)])
        config = get_config(ns)
        assert config.credentials.token_key == "token-key"
        assert config.credentials.token_secret == "token-secret"
        assert config.credentials.consumer_key == "consumer-key"
        assert config.credentials.consumer_secret == "consumer-secret"
        assert config.metadata_url == "http://example.com"

    def test_override_config(self, tmp_path):
        conf = {
            "reporting": {
                "maas": {
                    "token_key": "token-key",
                    "token_secret": "token-secret",
                    "consumer_key": "consumer-key",
                    "consumer_secret": "consumer-secret",
                    "endpoint": "http://example.com",
                }
            }
        }
        config_file = tmp_path / "conf.yaml"
        with config_file.open("w") as fd:
            yaml.dump(conf, fd)
        ns = parse_args(
            [
                "report-results",
                "--config",
                str(config_file),
                "--machine-token",
                "new-consumer-key:new-token-key:new-token-secret:new-consumer-secret",
                "--metadata-url",
                "http://new.example.com",
            ]
        )
        config = get_config(ns)
        assert config.credentials.token_key == "new-token-key"
        assert config.credentials.token_secret == "new-token-secret"
        assert config.credentials.consumer_key == "new-consumer-key"
        assert config.credentials.consumer_secret == "new-consumer-secret"
        assert config.metadata_url == "http://new.example.com"


def mock_geturl(mocker, results):
    mocked = mocker.patch.object(maas_run_scripts, "geturl")
    # fake returning a json result from the API call
    mock_result = MagicMock()
    mock_result.read.return_value.decode.side_effect = [
        json.dumps(result) for result in results
    ]
    mocked.return_value = mock_result
    return mocked


def make_http_error(code, reason, details):
    return HTTPError(
        "http://example.com",
        code,
        reason,
        {},
        BytesIO(details.encode("utf8")),
    )


class TestMain:
    def test_run_report_results(self, mocker, tmp_path):
        mocker.patch.object(maas_run_scripts, "print")
        conf = {
            "reporting": {
                "maas": {
                    "token_key": "token-key",
                    "token_secret": "token-secret",
                    "consumer_key": "consumer-key",
                    "consumer_secret": "consumer-secret",
                    "endpoint": "http://maas",
                }
            }
        }
        config_file = tmp_path / "conf.yaml"
        with config_file.open("w") as fd:
            yaml.dump(conf, fd)
        scripts_info = [
            {
                "name": "myscript1",
                "path": "commissioning-scripts/myscript1",
                "script_result_id": 1,
                "script_version_id": 10,
                "default": True,
                "tags": ["node", "deploy-info"],
            },
            {
                "name": "myscript2",
                "path": "commissioning-scripts/myscript2",
                "script_result_id": 2,
                "script_version_id": 20,
                "default": True,
                "tags": ["node", "deploy-info"],
            },
            {
                "name": "myscript3",
                "path": "commissioning-scripts/myscript3",
                "script_result_id": 3,
                "script_version_id": 30,
                "default": False,
                "tags": ["node", "deploy-info"],
            },
            {
                "name": "myscript4",
                "path": "commissioning-scripts/myscript4",
                "script_result_id": 4,
                "script_version_id": 40,
                "default": True,
                "tags": ["node"],
            },
        ]
        mocker.patch.object(maas_run_scripts, "fetch_scripts").return_value = [
            Script(info, "http://maas", None) for info in scripts_info
        ]
        mocker.patch.object(maas_run_scripts, "signal")

        ran_scripts = []

        def run_script(script, console_output=False):
            ran_scripts.append(script.name)
            return ScriptRunResult(0, "WORKING", None, 10, {})

        mocker.patch.object(maas_run_scripts.Script, "run", run_script)

        main(["report-results", "--config", str(config_file)])
        # only default scripts tagged as "deploy-info" are run
        assert ran_scripts == ["myscript1", "myscript2"]

    def test_register_machine(self, mocker, tmp_path):
        token_info = {
            "token_key": "tk",
            "token_secret": "ts",
            "consumer_key": "ck",
        }
        mocked_geturl = mock_geturl(
            mocker, [{"system_id": "abcde"}, token_info]
        )
        mock_node = mocker.patch.object(maas_run_scripts.platform, "node")
        mock_node.return_value = "myhost"
        tempdir = str(tmp_path)

        main(
            [
                "register-machine",
                "--base-dir",
                tempdir,
                "http://mymaas.example.com:5240/MAAS",
                "foo:bar:baz",
            ]
        )
        mocked_geturl.assert_has_calls(
            [
                call(
                    "http://mymaas.example.com:5240/MAAS/api/2.0/machines/",
                    credentials=Credentials.from_string("foo:bar:baz"),
                    data=ANY,
                    headers=ANY,
                    retry=False,
                ),
                call(
                    "http://mymaas.example.com:5240/MAAS/api/2.0/machines/abcde/?op=get_token",
                    credentials=Credentials.from_string("foo:bar:baz"),
                    retry=False,
                ),
            ],
            any_order=True,
        )
        mock_node.assert_called_once()
        creds_yaml = yaml.safe_load(
            (Path(tempdir) / "myhost-creds.yaml").read_text()
        )
        info = creds_yaml["reporting"]["maas"]
        assert "tk" == info["token_key"]
        assert "ts" == info["token_secret"]
        assert "ck" == info["consumer_key"]
        assert (
            "http://mymaas.example.com:5240/MAAS/metadata/status/abcde"
            == info["endpoint"]
        )

    def test_register_machine_with_hostname(self, mocker, tmp_path):
        token_info = {
            "token_key": "tk",
            "token_secret": "ts",
            "consumer_key": "ck",
        }
        mocked_geturl = mock_geturl(
            mocker, [{"system_id": "abcde"}, token_info]
        )
        mock_node = mocker.patch.object(maas_run_scripts.platform, "node")
        mock_write_token = mocker.patch.object(maas_run_scripts, "write_token")

        main(
            [
                "register-machine",
                "http://mymaas.example.com:5240/MAAS",
                "foo:bar:baz",
                "--hostname",
                "myhost",
            ]
        )
        mocked_geturl.assert_has_calls(
            [
                call(
                    "http://mymaas.example.com:5240/MAAS/api/2.0/machines/",
                    credentials=Credentials.from_string("foo:bar:baz"),
                    data=ANY,
                    headers=ANY,
                    retry=False,
                ),
                call(
                    "http://mymaas.example.com:5240/MAAS/api/2.0/machines/abcde/?op=get_token",
                    credentials=Credentials.from_string("foo:bar:baz"),
                    retry=False,
                ),
            ],
            any_order=True,
        )
        mock_node.assert_not_called()
        token = {
            "endpoint": "http://mymaas.example.com:5240/MAAS/metadata/status/abcde",
            **token_info,
        }
        mock_write_token.assert_called_once_with(
            token, path=Path("myhost-creds.yaml")
        )

    def test_get_machine_token(self, mocker, tmp_path):
        tempdir = str(tmp_path)
        token_info = {
            "token_key": "tk",
            "token_secret": "ts",
            "consumer_key": "ck",
        }
        mock_write_token = mocker.patch.object(maas_run_scripts, "write_token")
        mocked_geturl = mock_geturl(mocker, [token_info])
        main(
            [
                "get-machine-token",
                "http://mymaas.example.com:5240/MAAS",
                "foo:bar:baz",
                "abcde",
                f"{tempdir}/creds.yaml",
            ]
        )
        mocked_geturl.assert_called_with(
            "http://mymaas.example.com:5240/MAAS/api/2.0/machines/abcde/?op=get_token",
            credentials=Credentials.from_string("foo:bar:baz"),
            retry=False,
        )
        token = {
            "endpoint": "http://mymaas.example.com:5240/MAAS/metadata/status/abcde",
            **token_info,
        }
        mock_write_token.assert_called_once_with(
            token, path=Path(f"{tempdir}/creds.yaml")
        )

    def test_get_machine_token_machine_not_found(self, mocker, tmp_path):
        tempdir = str(tmp_path)
        mock_exit = mocker.patch.object(maas_run_scripts.sys, "exit")
        mocker.patch.object(
            maas_run_scripts, "geturl"
        ).side_effect = make_http_error(
            404,
            "Not found",
            "Machine not found",
        )
        main(
            [
                "get-machine-token",
                "http://mymaas.example.com:5240/MAAS",
                "foo:bar:baz",
                "abcde",
                f"{tempdir}/creds.yaml",
            ]
        )
        mock_exit.assert_called_with(
            "Failed getting machine credentials: Not found: Machine not found"
        )

    def test_get_machine_token_token_not_found(self, mocker, tmp_path):
        tempdir = str(tmp_path)
        mock_exit = mocker.patch.object(maas_run_scripts.sys, "exit")
        mock_geturl(mocker, [None])
        main(
            [
                "get-machine-token",
                "http://mymaas.example.com:5240/MAAS",
                "foo:bar:baz",
                "abcde",
                f"{tempdir}creds.yaml",
            ]
        )
        mock_exit.assert_called_with(
            "Failed getting machine credentials: Credentials not found"
        )


class TestWriteToken:
    def writes_file(self, tmp_path):
        token_info = {
            "token_key": "tk",
            "token_secret": "ts",
            "consumer_key": "ck",
        }
        path = write_token("myhost", token_info, basedir=tmp_path)
        assert yaml.safe_load(path) == {"reporting": {"maas": token_info}}
