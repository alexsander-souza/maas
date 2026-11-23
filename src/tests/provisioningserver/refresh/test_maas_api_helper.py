# Copyright 2016-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


from collections import OrderedDict
from email.utils import formatdate
from io import StringIO
import json
import random
import re
from subprocess import PIPE, Popen, TimeoutExpired
import time
from unittest.mock import ANY, MagicMock
import urllib

from lxml import etree
import pytest

from maastesting.factory import factory
from provisioningserver.refresh import maas_api_helper


class TestCredentials:
    def test_defaults(self):
        creds = maas_api_helper.Credentials()
        assert creds.consumer_key == ""
        assert creds.token_key == ""
        assert creds.token_secret == ""
        assert creds.consumer_secret == ""

    def test_with_args(self):
        creds = maas_api_helper.Credentials(
            token_key="token_key", consumer_secret="consumer_secret"
        )
        assert creds.consumer_key == ""
        assert creds.token_key == "token_key"
        assert creds.token_secret == ""
        assert creds.consumer_secret == "consumer_secret"

    def test_eq(self):
        creds = maas_api_helper.Credentials(
            token_key="token_key", consumer_secret="consumer_secret"
        )
        assert creds == maas_api_helper.Credentials(
            token_key="token_key", consumer_secret="consumer_secret"
        )
        assert creds != maas_api_helper.Credentials(
            token_key="token_key2", consumer_key="consumer_key"
        )

    def test_bool(self):
        assert maas_api_helper.Credentials(
            token_key="token_key", consumer_key="consumer_key"
        )
        assert not maas_api_helper.Credentials()

    def test_from_stringempty(self):
        assert (
            maas_api_helper.Credentials.from_string("")
            == maas_api_helper.Credentials()
        )
        assert (
            maas_api_helper.Credentials.from_string(None)
            == maas_api_helper.Credentials()
        )

    def test_all(self):
        creds = maas_api_helper.Credentials.from_string("ck:tk:ts:cs")
        assert creds == maas_api_helper.Credentials(
            consumer_key="ck",
            token_key="tk",
            token_secret="ts",
            consumer_secret="cs",
        )

    def test_no_consumer_secret(self):
        creds = maas_api_helper.Credentials.from_string("ck:tk:ts")
        assert creds == maas_api_helper.Credentials(
            consumer_key="ck",
            token_key="tk",
            token_secret="ts",
            consumer_secret="",
        )

    def test_wrong_format(self):
        with pytest.raises(maas_api_helper.InvalidCredentialsFormat):
            maas_api_helper.Credentials.from_string("wrong:format")

    def test_update(self):
        creds = maas_api_helper.Credentials()
        consumer_key = factory.make_name("consumer_key")
        token_key = factory.make_name("token_key")
        token_secret = factory.make_name("token_secret")
        consumer_secret = factory.make_name("consumer_secret")
        creds.update(
            {
                "consumer_key": consumer_key,
                "token_key": token_key,
                "token_secret": token_secret,
                "consumer_secret": consumer_secret,
            }
        )
        assert creds.consumer_key == consumer_key
        assert creds.token_key == token_key
        assert creds.token_secret == token_secret
        assert creds.consumer_secret == consumer_secret

    def test_update_no_update_already_set(self):
        creds = maas_api_helper.Credentials()
        consumer_key = factory.make_name("consumer_key")
        token_key = factory.make_name("token_key")
        token_secret = factory.make_name("token_secret")
        consumer_secret = factory.make_name("consumer_secret")
        creds.update(
            {
                "consumer_key": consumer_key,
                "token_key": token_key,
                "token_secret": token_secret,
                "consumer_secret": consumer_secret,
            }
        )
        creds.update(
            {
                "consumer_key": factory.make_name(),
                "token_key": factory.make_name(),
                "token_secret": factory.make_name(),
                "consumer_secret": factory.make_name(),
            }
        )
        assert creds.consumer_key == consumer_key
        assert creds.token_key == token_key
        assert creds.token_secret == token_secret
        assert creds.consumer_secret == consumer_secret

    def test_oauth_headers(self):
        now = time.time()

        url = factory.make_name("url")
        consumer_key = factory.make_name("consumer_key")
        token_key = factory.make_name("token_key")
        token_secret = factory.make_name("token_secret")
        consumer_secret = factory.make_name("consumer_secret")
        credentials = maas_api_helper.Credentials()
        credentials.update(
            {
                "consumer_key": consumer_key,
                "token_key": token_key,
                "token_secret": token_secret,
                "consumer_secret": consumer_secret,
            }
        )
        headers = credentials.oauth_headers(url)
        authorization = headers["Authorization"]
        assert re.search(r"^OAuth .*", authorization)
        authorization = authorization.replace("OAuth ", "")
        oauth_arguments = {}
        for argument in authorization.split(", "):
            key, value = argument.split("=")
            oauth_arguments[key] = value.replace('"', "")

        assert "oauth_nonce" in oauth_arguments
        oauth_arguments.pop("oauth_nonce", None)

        assert int(oauth_arguments.get("oauth_timestamp", 0)) == pytest.approx(
            now, abs=3
        )
        assert oauth_arguments.get("oauth_version") == "1.0"
        assert oauth_arguments.get("oauth_signature_method") == "PLAINTEXT"
        assert oauth_arguments.get("oauth_consumer_key") == consumer_key
        assert oauth_arguments.get("oauth_token") == token_key
        assert (
            oauth_arguments.get("oauth_signature")
            == f"{consumer_secret}%26{token_secret}"
        )

    def test_oauth_headers_empty(self):
        creds = maas_api_helper.Credentials()
        assert creds.oauth_headers("http://example.com") == {}


class MAASMockHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        if "broken_with_date" in req.get_full_url():
            code = random.choice([401, 403])
            headers = {"date": formatdate()}
        elif "broken" in req.get_full_url():
            code = 400
            headers = {}
        else:
            code = 200
            headers = {}
        resp = urllib.request.addinfourl(
            StringIO("mock response"), headers, req.get_full_url(), code
        )
        resp.msg = "OK"
        return resp


class TestGetBase:
    def test_get_base_url(self):
        assert (
            maas_api_helper.get_base_url(
                "http://example.com:1234/some/path?and=query"
            )
            == "http://example.com:1234"
        )

    def test_get_base_url_no_port(self):
        assert (
            maas_api_helper.get_base_url(
                "http://example.com/some/path?and=query"
            )
            == "http://example.com"
        )


class TestGetUrl:
    @pytest.fixture(autouse=True)
    def _setup(self):
        opener = urllib.request.build_opener(MAASMockHTTPHandler)
        urllib.request.install_opener(opener)

    def test_geturl_sends_request(self):
        assert (
            "mock response"
            == maas_api_helper.geturl(
                "http://%s" % factory.make_hostname(),
            ).read()
        )

    def test_geturl_raises_exception_on_failure(self, mocker):
        sleep = mocker.patch.object(maas_api_helper.time, "sleep")
        warn = mocker.patch.object(maas_api_helper, "warn")
        with pytest.raises(urllib.error.HTTPError):
            maas_api_helper.geturl(
                "http://%s-broken" % factory.make_hostname(),
            )
        assert sleep.call_count == 8
        warn.assert_any_call("date field not in 400 headers")

    def test_geturl_increments_skew(self, mocker):
        sleep = mocker.patch.object(maas_api_helper.time, "sleep")
        warn = mocker.patch.object(maas_api_helper, "warn")
        with pytest.raises(urllib.error.HTTPError):
            maas_api_helper.geturl(
                "http://%s-broken_with_date" % factory.make_hostname(),
            )
        assert sleep.call_count == 8
        clock_skew_updates = [
            call
            for call in warn.call_args_list
            if call[0][0].startswith("updated clock skew to")
        ]
        assert len(clock_skew_updates) == 8

    def test_geturl_posts_data(self, mocker):
        mock_urlopen = mocker.patch.object(
            maas_api_helper.urllib.request, "urlopen"
        )
        post_data = {factory.make_name("key"): factory.make_name("value")}
        maas_api_helper.geturl(
            "http://%s" % factory.make_hostname(), post_data=post_data
        )
        mock_urlopen.assert_called_once_with(
            ANY, data=urllib.parse.urlencode(post_data).encode("ascii")
        )

    def test_geturl_no_retry(self, mocker):
        mock_urlopen = mocker.patch.object(
            maas_api_helper.urllib.request, "urlopen"
        )
        maas_api_helper.geturl("http://example.com", retry=False)
        mock_urlopen.assert_called_once()


class TestEncode:
    def test_encode_blank(self):
        data, headers = maas_api_helper.encode_multipart_data({}, {})
        m = re.search("boundary=([a-zA-Z]+)", headers["Content-Type"])
        boundary = m.group(1)
        assert headers == {
            "Content-Type": "multipart/form-data; boundary=%s" % boundary,
            "Content-Length": str(len(data)),
        }
        assert isinstance(data, bytes)
        assert data.decode("utf-8") == "--%s--\r\n" % boundary

    def test_encode_data(self):
        key = factory.make_name("key")
        value = factory.make_name("value")
        params = {key.encode("utf-8"): value.encode("utf-8")}
        data, headers = maas_api_helper.encode_multipart_data(params, {})
        m = re.search("boundary=([a-zA-Z]+)", headers["Content-Type"])
        boundary = m.group(1)
        assert headers == {
            "Content-Type": "multipart/form-data; boundary=%s" % boundary,
            "Content-Length": str(len(data)),
        }
        assert isinstance(data, bytes)
        assert data.decode("utf-8") == (
            '--%s\r\nContent-Disposition: form-data; name="%s"'
            "\r\n\r\n%s\r\n--%s--\r\n" % (boundary, key, value, boundary)
        )

    def test_encode_file(self):
        file = factory.make_name("file")
        content = factory.make_name("content")
        files = {file: content.encode("utf-8")}
        data, headers = maas_api_helper.encode_multipart_data({}, files)
        m = re.search("boundary=([a-zA-Z]+)", headers["Content-Type"])
        boundary = m.group(1)
        assert headers == {
            "Content-Type": "multipart/form-data; boundary=%s" % boundary,
            "Content-Length": str(len(data)),
        }
        assert isinstance(data, bytes)
        assert data.decode("utf-8") == (
            '--%s\r\nContent-Disposition: form-data; name="%s"; filename="%s"'
            "\r\nContent-Type: application/octet-stream\r\n\r\n%s\r\n--%s--"
            "\r\n" % (boundary, file, file, content, boundary)
        )


class TestSignal:
    def test_signal_formats_basic_params(self, mocker):
        mock_encode_multipart_data = mocker.patch.object(
            maas_api_helper, "encode_multipart_data"
        )
        mock_encode_multipart_data.return_value = None, None
        mock_geturl = mocker.patch.object(maas_api_helper, "geturl")
        mm = MagicMock()
        mm.status = 200
        mm.read.return_value = b"OK"
        mock_geturl.return_value = mm

        status = factory.make_name("status")

        # None used for url and creds as we're not actually sending data.
        maas_api_helper.signal(None, None, status)

        mock_encode_multipart_data.assert_called_with(
            {b"op": b"signal", b"status": status.encode("utf-8")},
            files=None,
        )
        mock_geturl.assert_called_once()

    def test_signal_formats_params_with_error(self, mocker):
        mock_encode_multipart_data = mocker.patch.object(
            maas_api_helper, "encode_multipart_data"
        )
        mock_encode_multipart_data.return_value = None, None
        mock_geturl = mocker.patch.object(maas_api_helper, "geturl")
        mm = MagicMock()
        mm.status = 200
        mm.read.return_value = b"OK"
        mock_geturl.return_value = mm

        status = factory.make_name("status")
        error = factory.make_name("error")

        # None used for url and creds as we're not actually sending data.
        maas_api_helper.signal(None, None, status, error=error)

        mock_encode_multipart_data.assert_called_with(
            {
                b"op": b"signal",
                b"status": status.encode("utf-8"),
                b"error": error.encode("utf-8"),
            },
            files=None,
        )
        mock_geturl.assert_called_once()

    def test_signal_formats_params_with_script_result_id(self, mocker):
        mock_encode_multipart_data = mocker.patch.object(
            maas_api_helper, "encode_multipart_data"
        )
        mock_encode_multipart_data.return_value = None, None
        mock_geturl = mocker.patch.object(maas_api_helper, "geturl")
        mm = MagicMock()
        mm.status = 200
        mm.read.return_value = b"OK"
        mock_geturl.return_value = mm

        status = factory.make_name("status")
        script_result_id = random.randint(1, 1000)

        # None used for url and creds as we're not actually sending data.
        maas_api_helper.signal(
            None, None, status, script_result_id=script_result_id
        )

        mock_encode_multipart_data.assert_called_with(
            {
                b"op": b"signal",
                b"status": status.encode("utf-8"),
                b"script_result_id": str(script_result_id).encode("utf-8"),
            },
            files=None,
        )
        mock_geturl.assert_called_once()

    def test_signal_formats_params_with_exit_status(self, mocker):
        mock_encode_multipart_data = mocker.patch.object(
            maas_api_helper, "encode_multipart_data"
        )
        mock_encode_multipart_data.return_value = None, None
        mock_geturl = mocker.patch.object(maas_api_helper, "geturl")
        mm = MagicMock()
        mm.status = 200
        mm.read.return_value = b"OK"
        mock_geturl.return_value = mm

        status = factory.make_name("status")
        exit_status = random.randint(0, 255)

        # None used for url and creds as we're not actually sending data.
        maas_api_helper.signal(None, None, status, exit_status=exit_status)

        mock_encode_multipart_data.assert_called_with(
            {
                b"op": b"signal",
                b"status": status.encode("utf-8"),
                b"exit_status": str(exit_status).encode("utf-8"),
            },
            files=None,
        )
        mock_geturl.assert_called_once()

    def test_signal_formats_params_with_script_name(self, mocker):
        mock_encode_multipart_data = mocker.patch.object(
            maas_api_helper, "encode_multipart_data"
        )
        mock_encode_multipart_data.return_value = None, None
        mock_geturl = mocker.patch.object(maas_api_helper, "geturl")
        mm = MagicMock()
        mm.status = 200
        mm.read.return_value = b"OK"
        mock_geturl.return_value = mm

        status = factory.make_name("status")
        script_name = factory.make_name("script_name")

        # None used for url and creds as we're not actually sending data.
        maas_api_helper.signal(None, None, status, script_name=script_name)

        mock_encode_multipart_data.assert_called_with(
            {
                b"op": b"signal",
                b"status": status.encode("utf-8"),
                b"name": str(script_name).encode("utf-8"),
            },
            files=None,
        )
        mock_geturl.assert_called_once()

    def test_signal_formats_params_with_script_version_id(self, mocker):
        mock_encode_multipart_data = mocker.patch.object(
            maas_api_helper, "encode_multipart_data"
        )
        mock_encode_multipart_data.return_value = None, None
        mock_geturl = mocker.patch.object(maas_api_helper, "geturl")
        mm = MagicMock()
        mm.status = 200
        mm.read.return_value = b"OK"
        mock_geturl.return_value = mm

        status = factory.make_name("status")
        script_version_id = random.randint(1, 1000)

        # None used for url and creds as we're not actually sending data.
        maas_api_helper.signal(
            None, None, status, script_version_id=script_version_id
        )

        mock_encode_multipart_data.assert_called_with(
            {
                b"op": b"signal",
                b"status": status.encode("utf-8"),
                b"script_version_id": str(script_version_id).encode("utf-8"),
            },
            files=None,
        )
        mock_geturl.assert_called_once()

    def test_signal_formats_params_with_runtime(self, mocker):
        mock_encode_multipart_data = mocker.patch.object(
            maas_api_helper, "encode_multipart_data"
        )
        mock_encode_multipart_data.return_value = None, None
        mock_geturl = mocker.patch.object(maas_api_helper, "geturl")
        mm = MagicMock()
        mm.status = 200
        mm.read.return_value = b"OK"
        mock_geturl.return_value = mm

        status = factory.make_name("status")
        script_name = factory.make_name("script_name")
        runtime = random.randint(1000, 9999) / 100

        # None used for url and creds as we're not actually sending data.
        maas_api_helper.signal(
            None, None, status, script_name=script_name, runtime=runtime
        )

        mock_encode_multipart_data.assert_called_with(
            {
                b"op": b"signal",
                b"status": status.encode("utf-8"),
                b"name": str(script_name).encode("utf-8"),
                b"runtime": str(runtime).encode("utf-8"),
            },
            files=None,
        )
        mock_geturl.assert_called_once()

    def test_signal_formats_params_with_power_params(self, mocker):
        mock_encode_multipart_data = mocker.patch.object(
            maas_api_helper, "encode_multipart_data"
        )
        mock_encode_multipart_data.return_value = None, None
        mock_geturl = mocker.patch.object(maas_api_helper, "geturl")
        mm = MagicMock()
        mm.status = 200
        mm.read.return_value = b"OK"
        mock_geturl.return_value = mm

        status = factory.make_name("status")
        power_type = factory.make_name("power_type")
        power_params = OrderedDict(
            [
                ("power_user", factory.make_name("power_user")),
                ("power_pass", factory.make_name("power_pass")),
                ("power_address", factory.make_url()),
                ("power_driver", factory.make_name("power_driver")),
                ("power_boot_type", factory.make_name("power_boot_type")),
            ]
        )

        # None used for url and creds as we're not actually sending data.
        maas_api_helper.signal(
            None,
            None,
            status,
            power_type=power_type,
            power_params=",".join([value for value in power_params.values()]),
        )

        mock_encode_multipart_data.assert_called_with(
            {
                b"op": b"signal",
                b"status": status.encode("utf-8"),
                b"power_type": power_type.encode("utf-8"),
                b"power_parameters": json.dumps(power_params).encode(),
            },
            files=None,
        )
        mock_geturl.assert_called_once()

    def test_signal_formats_params_with_moonshot_power_params(self, mocker):
        mock_encode_multipart_data = mocker.patch.object(
            maas_api_helper, "encode_multipart_data"
        )
        mock_encode_multipart_data.return_value = None, None
        mock_geturl = mocker.patch.object(maas_api_helper, "geturl")
        mm = MagicMock()
        mm.status = 200
        mm.read.return_value = b"OK"
        mock_geturl.return_value = mm

        status = factory.make_name("status")
        power_type = "moonshot"
        power_params = OrderedDict(
            [
                ("power_user", factory.make_name("power_user")),
                ("power_pass", factory.make_name("power_pass")),
                ("power_address", factory.make_url()),
                ("power_hwaddress", factory.make_name("power_hwaddress")),
            ]
        )

        # None used for url and creds as we're not actually sending data.
        maas_api_helper.signal(
            None,
            None,
            status,
            power_type=power_type,
            power_params=",".join([value for value in power_params.values()]),
        )

        mock_encode_multipart_data.assert_called_with(
            {
                b"op": b"signal",
                b"status": status.encode("utf-8"),
                b"power_type": power_type.encode("utf-8"),
                b"power_parameters": json.dumps(power_params).encode(),
            },
            files=None,
        )
        mock_geturl.assert_called_once()

    def test_signal_formats_files(self, mocker):
        mock_encode_multipart_data = mocker.patch.object(
            maas_api_helper, "encode_multipart_data"
        )
        mock_encode_multipart_data.return_value = None, None
        mock_geturl = mocker.patch.object(maas_api_helper, "geturl")
        mm = MagicMock()
        mm.status = 200
        mm.read.return_value = b"OK"
        mock_geturl.return_value = mm

        status = factory.make_name("status")
        files = {factory.make_name(): factory.make_bytes()}

        # None used for url and creds as we're not actually sending data.
        maas_api_helper.signal(None, None, status, files=files)

        mock_encode_multipart_data.assert_called_with(
            {
                b"op": b"signal",
                b"status": status.encode("utf-8"),
            },
            files=files,
        )
        mock_geturl.assert_called_once()

    def test_signal_raises_exception_if_not_ok(self, mocker):
        mock_encode_multipart_data = mocker.patch.object(
            maas_api_helper, "encode_multipart_data"
        )
        mock_encode_multipart_data.return_value = None, None
        mock_geturl = mocker.patch.object(maas_api_helper, "geturl")
        mm = MagicMock()
        mm.status = 400
        mm.read.return_value = b"bad_ret"
        mock_geturl.return_value = mm

        status = factory.make_name("status")

        # None used for url and creds as we're not actually sending data.
        with pytest.raises(maas_api_helper.SignalException):
            maas_api_helper.signal(None, None, status)

    def test_signal_raises_exception_on_httperror(self, mocker):
        mock_encode_multipart_data = mocker.patch.object(
            maas_api_helper, "encode_multipart_data"
        )
        mock_encode_multipart_data.return_value = None, None
        mock_geturl = mocker.patch.object(maas_api_helper, "geturl")
        mock_geturl.side_effect = maas_api_helper.urllib.error.HTTPError(
            None, None, None, None, None
        )

        status = factory.make_name("status")

        # None used for url and creds as we're not actually sending data.
        with pytest.raises(maas_api_helper.SignalException):
            maas_api_helper.signal(None, None, status)

    def test_signal_raises_exception_on_urlerror(self, mocker):
        mock_encode_multipart_data = mocker.patch.object(
            maas_api_helper, "encode_multipart_data"
        )
        mock_encode_multipart_data.return_value = None, None
        mock_geturl = mocker.patch.object(maas_api_helper, "geturl")
        mock_geturl.side_effect = maas_api_helper.urllib.error.URLError(None)

        status = factory.make_name("status")

        # None used for url and creds as we're not actually sending data.
        with pytest.raises(maas_api_helper.SignalException):
            maas_api_helper.signal(None, None, status)

    def test_signal_raises_exception_on_socket_timeout(self, mocker):
        mock_encode_multipart_data = mocker.patch.object(
            maas_api_helper, "encode_multipart_data"
        )
        mock_encode_multipart_data.return_value = None, None
        mock_geturl = mocker.patch.object(maas_api_helper, "geturl")
        mock_geturl.side_effect = maas_api_helper.socket.timeout()

        status = factory.make_name("status")

        # None used for url and creds as we're not actually sending data.
        with pytest.raises(maas_api_helper.SignalException):
            maas_api_helper.signal(None, None, status)

    def test_signal_raises_exception_on_typeerror(self, mocker):
        mock_encode_multipart_data = mocker.patch.object(
            maas_api_helper, "encode_multipart_data"
        )
        mock_encode_multipart_data.return_value = None, None
        mock_geturl = mocker.patch.object(maas_api_helper, "geturl")
        mock_geturl.side_effect = TypeError()

        status = factory.make_name("status")

        # None used for url and creds as we're not actually sending data.
        with pytest.raises(maas_api_helper.SignalException):
            maas_api_helper.signal(None, None, status)

    def test_signal_raises_exception_on_unknown_exception(self, mocker):
        mock_encode_multipart_data = mocker.patch.object(
            maas_api_helper, "encode_multipart_data"
        )
        mock_encode_multipart_data.return_value = None, None
        mock_geturl = mocker.patch.object(maas_api_helper, "geturl")
        mock_geturl.side_effect = Exception()

        status = factory.make_name("status")

        # None used for url and creds as we're not actually sending data.
        with pytest.raises(maas_api_helper.SignalException):
            maas_api_helper.signal(None, None, status)


class TestCaptureScriptOutput:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker, tmp_path):
        self.tmp_path = tmp_path
        self.mocker = mocker
        # Make sure output isn't shown when running tests through a console
        self.isatty = mocker.patch.object(maas_api_helper.sys.stdout, "isatty")
        self.isatty.return_value = False

    def capture(self, proc, timeout=None, console_output=None):
        scripts_dir = self.tmp_path
        combined_path = scripts_dir.joinpath("combined")
        stdout_path = scripts_dir.joinpath("stdout")
        stderr_path = scripts_dir.joinpath("stderr")

        returncode = maas_api_helper.capture_script_output(
            proc,
            str(combined_path),
            str(stdout_path),
            str(stderr_path),
            timeout_seconds=timeout,
            console_output=console_output,
        )

        return (
            returncode,
            stdout_path.read_text(),
            stderr_path.read_text(),
            combined_path.read_text(),
        )

    def test_captures_script_output(self):
        proc = Popen(
            'echo "stdout"; echo "stderr" 1>&2',
            stdout=PIPE,
            stderr=PIPE,
            shell=True,
        )
        ret_code, stdout, stderr, combined = self.capture(proc)
        assert ret_code == 0
        assert stdout == "stdout\n"
        assert stderr == "stderr\n"
        # The writes to stdout and stderr occur so close in time that
        # they may be received in any order.

        assert sorted(combined.splitlines()) == sorted(["stderr", "stdout"])

    def test_forwards_to_console(self):
        stdout = self.mocker.patch.object(maas_api_helper.sys.stdout, "write")
        stderr = self.mocker.patch.object(maas_api_helper.sys.stderr, "write")
        stdout_flush = self.mocker.patch.object(
            maas_api_helper.sys.stdout, "flush"
        )
        stderr_flush = self.mocker.patch.object(
            maas_api_helper.sys.stderr, "flush"
        )
        self.isatty.return_value = True
        proc = Popen(
            'echo "stdout"; echo "stderr" 1>&2',
            stdout=PIPE,
            stderr=PIPE,
            shell=True,
        )
        self.capture(proc)
        stdout.assert_called_once_with("stdout\n")
        stderr.assert_called_once_with("stderr\n")
        stdout_flush.assert_called_once()
        stderr_flush.assert_called_once()

    def test_no_forwards_to_console_with_false(self):
        stdout = self.mocker.patch.object(maas_api_helper.sys.stdout, "write")
        stderr = self.mocker.patch.object(maas_api_helper.sys.stderr, "write")
        self.mocker.patch.object(maas_api_helper.sys.stdout, "flush")
        self.mocker.patch.object(maas_api_helper.sys.stderr, "flush")
        self.isatty.return_value = True
        proc = Popen(
            'echo "stdout"; echo "stderr" 1>&2',
            stdout=PIPE,
            stderr=PIPE,
            shell=True,
        )
        self.capture(proc, console_output=False)
        stdout.assert_not_called()
        stderr.assert_not_called()

    def test_forwards_to_console_with_true_no_tty(self):
        stdout = self.mocker.patch.object(maas_api_helper.sys.stdout, "write")
        stderr = self.mocker.patch.object(maas_api_helper.sys.stderr, "write")
        self.mocker.patch.object(maas_api_helper.sys.stdout, "flush")
        self.mocker.patch.object(maas_api_helper.sys.stderr, "flush")
        self.isatty.return_value = False
        proc = Popen(
            'echo "stdout"; echo "stderr" 1>&2',
            stdout=PIPE,
            stderr=PIPE,
            shell=True,
        )
        self.capture(proc, console_output=True)
        stdout.assert_called_once_with("stdout\n")
        stderr.assert_called_once_with("stderr\n")

    def test_does_not_wait_for_forked_process(self):
        start_time = time.time()
        proc = Popen("sleep 6 &", stdout=PIPE, stderr=PIPE, shell=True)
        ret_code, stdout, stderr, combined = self.capture(proc)
        assert ret_code == 0
        assert stdout == ""
        assert stderr == ""
        assert combined == ""
        # A forked process should continue running after capture_script_output
        # returns. capture_script_output should not block on the forked call.
        assert time.time() - start_time < 3

    def test_captures_output_from_completed_process(self):
        # Write to both stdout and stderr.
        proc = Popen(
            "echo -n foo >&1 && echo -n bar >&2",
            stdout=PIPE,
            stderr=PIPE,
            shell=True,
        )
        ret_code, stdout, stderr, combined = self.capture(proc)
        # Wait for it to finish before capturing.
        assert 0 == proc.wait()
        # Capturing now still gets foo and bar.
        assert ret_code == 0
        assert stdout == "foo"
        assert stderr == "bar"
        # The writes to stdout and stderr occur so close in time that
        # they may be received in any order.
        assert combined in ("foobar", "barfoo")

    def test_captures_stderr_after_stdout_closes(self):
        # Write to stdout, close stdout, then write to stderr.
        proc = Popen(
            "echo -n foo >&1 && exec 1>&- && echo -n bar >&2",
            stdout=PIPE,
            stderr=PIPE,
            shell=True,
        )
        ret_code, stdout, stderr, combined = self.capture(proc)
        # Capturing gets the bar even after stdout is closed.
        assert ret_code == 0
        assert stdout == "foo"
        assert stderr == "bar"
        # The writes to stdout and stderr occur so close in time that
        # they may be received in any order.
        assert combined in ("foobar", "barfoo")

    def test_captures_stdout_after_stderr_closes(self):
        # Write to stderr, close stderr, then write to stdout.
        proc = Popen(
            "echo -n bar >&2 && exec 2>&- && echo -n foo >&1",
            stdout=PIPE,
            stderr=PIPE,
            shell=True,
        )
        ret_code, stdout, stderr, combined = self.capture(proc)
        # Capturing gets the foo even after stderr is closed.
        assert ret_code == 0
        assert stdout == "foo"
        assert stderr == "bar"
        # The writes to stdout and stderr occur so close in time that
        # they may be received in any order.
        assert combined in ("foobar", "barfoo")

    def test_captures_all_output(self):
        proc = Popen(("lshw", "-xml"), stdout=PIPE, stderr=PIPE)
        ret_code, stdout, stderr, combined = self.capture(proc)
        assert ret_code == 0
        # This is a complete XML document that can be parsed; we've captured
        # all output.
        assert etree.fromstring(stdout) is not None

    def test_interprets_backslash(self):
        proc = Popen(
            'bash -c "echo -en \bmas\bas"',
            stdout=PIPE,
            stderr=PIPE,
            shell=True,
        )
        ret_code, stdout, stderr, combined = self.capture(proc)
        assert ret_code == 0
        assert stdout == "maas"
        assert stderr == ""
        assert combined == "maas"

    def test_interprets_carriage_return(self):
        proc = Popen(
            'bash -c "echo -en foo\rmaas"',
            stdout=PIPE,
            stderr=PIPE,
            shell=True,
        )
        ret_code, stdout, stderr, combined = self.capture(proc)
        assert ret_code == 0
        assert stdout == "maas"
        assert stderr == ""
        assert combined == "maas"

    def test_timeout(self):
        self.mocker.patch.object(
            maas_api_helper.time, "monotonic"
        ).side_effect = (
            0,
            60 * 6,
            60 * 6,
            60 * 6,
        )
        proc = Popen('echo "test"', stdout=PIPE, stderr=PIPE, shell=True)
        with pytest.raises(TimeoutExpired):
            self.capture(proc, random.randint(1, 5))
