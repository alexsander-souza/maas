# Copyright 2012-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from argparse import Namespace
import http.client
import json
import sys
from unittest.mock import sentinel

import httplib2
import pytest

from apiclient.creds import convert_string_to_tuple, convert_tuple_to_string
from maascli import auth
from maastesting.factory import factory


def make_credentials():
    return (
        factory.make_name("consumer_key"),
        factory.make_name("token_key"),
        factory.make_name("secret_key"),
    )


def make_options():
    credentials = ":".join(make_credentials())
    url = "http://example.com/api/2.0/"
    options = Namespace(
        credentials=credentials,
        execute=None,
        insecure=False,
        profile_name="test",
        url=url,
        cacerts=None,
    )
    return options


class TestAuth:
    def test_try_getpass(self, mocker):
        getpass = mocker.patch.object(auth, "getpass")
        getpass.return_value = sentinel.credentials
        assert auth.try_getpass(sentinel.prompt) is sentinel.credentials
        getpass.assert_called_once_with(sentinel.prompt)

    def test_try_getpass_eof(self, mocker):
        getpass = mocker.patch.object(auth, "getpass")
        getpass.side_effect = EOFError
        assert auth.try_getpass(sentinel.prompt) is None
        getpass.assert_called_once_with(sentinel.prompt)

    def test_obtain_credentials_from_stdin(self, mocker):
        # When "-" is passed to obtain_credentials, it reads credentials from
        # stdin, trims whitespace, and converts it into a 3-tuple of creds.
        credentials = make_credentials()
        stdin = mocker.patch.object(sys, "stdin")
        stdin.readline.return_value = (
            convert_tuple_to_string(credentials) + "\n"
        )
        assert (
            auth.obtain_credentials("http://example.com/", "-") == credentials
        )
        stdin.readline.assert_called_once_with()

    def test_obtain_credentials_via_getpass(self, mocker):
        # When None is passed to obtain_credentials, it attempts to obtain
        # credentials via getpass, then converts it into a 3-tuple of creds.
        credentials = make_credentials()
        getpass = mocker.patch.object(auth, "getpass")
        getpass.return_value = convert_tuple_to_string(credentials)
        assert (
            auth.obtain_credentials("http://example.com/", None) == credentials
        )
        getpass.assert_called_once()

    def test_obtain_credentials_empty(self, mocker):
        # If the entered credentials are empty or only whitespace,
        # obtain_credentials returns None.
        getpass = mocker.patch.object(auth, "getpass")
        getpass.return_value = None
        assert auth.obtain_credentials("http://example.com/", None) is None
        getpass.assert_called_once()

    def test_check_valid_apikey_passes_valid_key(self, mocker):
        options = make_options()
        content = factory.make_name("content")
        mock_request = mocker.patch.object(httplib2.Http, "request")
        response = httplib2.Response({})
        response["status"] = http.client.OK
        mock_request.return_value = response, json.dumps(content)
        assert auth.check_valid_apikey(
            options.url,
            convert_string_to_tuple(options.credentials),
            options.insecure,
        )

    def test_check_valid_apikey_catches_invalid_key(self, mocker):
        options = make_options()
        content = factory.make_name("content")
        mock_request = mocker.patch.object(httplib2.Http, "request")
        response = httplib2.Response({})
        response["status"] = http.client.UNAUTHORIZED
        mock_request.return_value = response, json.dumps(content)
        assert not auth.check_valid_apikey(
            options.url,
            convert_string_to_tuple(options.credentials),
            options.insecure,
        )

    def test_check_valid_apikey_raises_if_unexpected_response(self, mocker):
        options = make_options()
        content = factory.make_name("content")
        mock_request = mocker.patch.object(httplib2.Http, "request")
        response = httplib2.Response({})
        response["status"] = http.client.GONE
        mock_request.return_value = response, json.dumps(content)
        with pytest.raises(auth.UnexpectedResponse):
            auth.check_valid_apikey(
                options.url,
                convert_string_to_tuple(options.credentials),
                options.insecure,
            )
