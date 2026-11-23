# Copyright 2014-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test `api.auth` module."""

from itertools import product
from typing import Any, Optional
from unittest import mock

from django.contrib.auth.models import AnonymousUser
from piston3 import oauth
import pytest

from maasserver.api import auth as api_auth
from maasserver.api.auth import (
    MAASAPIAuthentication,
    OAuthBadRequest,
    OAuthUnauthorized,
    RequestValidityReport,
)
from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestMAASAPIAuthentication:
    def make_request(
        self,
        user=None,
        method: str = "GET",
        data: Optional[dict[str, str]] = None,
        headers: Optional[dict[str, Any]] = None,
    ):
        request = factory.make_fake_request(
            "/",
            method=method,
            data=data,
            headers=headers,
        )
        request.user = user or AnonymousUser()
        return request

    def test_is_authenticated(self):
        user = factory.make_User()
        request = self.make_request(user=user)
        auth = MAASAPIAuthentication()
        assert auth.is_authenticated(request)

    def test_is_authenticated_oidc_user_active(self, mocker):
        mock_service_layer = mocker.patch.object(api_auth, "service_layer")
        mock_service_layer.services.external_oauth.is_active_oidc_user.return_value = True

        auth = MAASAPIAuthentication()
        user = factory.make_User()
        user.userprofile.is_local = False
        user.userprofile.save()
        mock_token = mock.Mock(user=user)
        request = self.make_request()
        auth.check_validity = lambda request: RequestValidityReport({}, {}, {})
        auth.validate_token = lambda request: (mock.Mock(), mock_token, None)

        assert auth.is_authenticated(request)
        mock_service_layer.services.external_oauth.is_active_oidc_user.assert_called_once_with(
            user.username
        )

    def test_is_authenticated_oidc_user_inactive(self, mocker):
        mock_service_layer = mocker.patch.object(api_auth, "service_layer")
        mock_service_layer.services.external_oauth.is_active_oidc_user.return_value = False

        auth = MAASAPIAuthentication()
        user = factory.make_User()
        user.userprofile.is_local = False
        user.userprofile.save()
        mock_token = mock.Mock(user=user)
        request = self.make_request()
        auth.check_validity = lambda request: RequestValidityReport({}, {}, {})
        auth.validate_token = lambda request: (mock.Mock(), mock_token, None)

        assert not auth.is_authenticated(request)
        mock_service_layer.services.external_oauth.is_active_oidc_user.assert_called_once_with(
            user.username
        )

    def test_is_authenticated_local_user_skips_oidc_check(self, mocker):
        mock_service_layer = mocker.patch.object(api_auth, "service_layer")

        auth = MAASAPIAuthentication()
        user = factory.make_User()
        user.userprofile.is_local = True
        user.userprofile.save()
        mock_token = mock.Mock(user=user)
        request = self.make_request()
        auth.check_validity = lambda request: RequestValidityReport({}, {}, {})
        auth.validate_token = lambda request: (mock.Mock(), mock_token, None)

        assert auth.is_authenticated(request)
        mock_service_layer.services.external_oauth.is_active_oidc_user.assert_not_called()

    def test_validity_report(self):
        params = product(["AUTH_HEADER", "GET", "POST"], [True, False])
        valid_auth_headers = {
            "Authorization": 'OAuth oauth_timestamp="1764850000", oauth_consumer_key="_", oauth_token="_", oauth_signature="_", oauth_signature_method="_", oauth_nonce="_"'
        }
        invalid_auth_headers = {
            "Authorization": 'OAuth oauth_timestamp="", oauth_consumer_key="_", oauth_token="_", oauth_signature="_", oauth_signature_method="_", oauth_nonce="_"'
        }

        valid_request_params = {
            "oauth_timestamp": "1764850000",
            "oauth_consumer_key": "_",
            "oauth_token": "_",
            "oauth_signature": "_",
            "oauth_signature_method": "_",
            "oauth_nonce": "_",
        }
        invalid_request_params = {
            "oauth_timestamp": "",
            "oauth_consumer_key": "_",
            "oauth_token": "_",
            "oauth_signature": "_",
            "oauth_signature_method": "_",
            "oauth_nonce": "_",
        }
        for method, is_valid in params:
            if method == "AUTH" and is_valid:
                request = self.make_request(headers=valid_auth_headers)
                validity_report = MAASAPIAuthentication.check_validity(request)
                assert validity_report.represents_valid_request()
            elif method == "AUTH" and not is_valid:
                request = self.make_request(headers=invalid_auth_headers)
                validity_report = MAASAPIAuthentication.check_validity(request)
                assert not validity_report.represents_valid_request()
            elif is_valid:
                request = self.make_request(
                    method=method, data=valid_request_params
                )
                validity_report = MAASAPIAuthentication.check_validity(request)
                assert validity_report.represents_valid_request()
            else:
                request = self.make_request(
                    method=method, data=invalid_request_params
                )
                validity_report = MAASAPIAuthentication.check_validity(request)
                assert not validity_report.represents_valid_request()

    def test_error_message_when_failing_oauth_validation(self):
        request = self.make_request(
            headers={
                "Authorization": 'OAuth oauth_timestamp="", oauth_consumer_key="_", oauth_token="_", oauth_signature="_", oauth_signature_method="_", oauth_nonce="_"'
            },
        )
        report = MAASAPIAuthentication.check_validity(request)

        assert "oauth_timestamp" in report.generate_error_message()
        assert "oauth_consumer_key" not in report.generate_error_message()


class TestOAuthUnauthorized:
    def test_exception_unicode_includes_original_failure_message(self):
        error_msg = factory.make_name("error-message")
        original_exception = oauth.OAuthError(error_msg)
        maas_exception = OAuthUnauthorized(original_exception)
        assert ("Authorization Error: %r" % error_msg) in str(maas_exception)

    def test_exception_unicode_includes_user_friendly_message(self):
        # When the error is an authentication error, the message is more
        # user-friendly than the default 'Invalid consumer.'.
        original_exception = oauth.OAuthError("Invalid consumer.")
        maas_exception = OAuthUnauthorized(original_exception)
        assert "Authorization Error: Invalid API key." in str(maas_exception)


class TestOAuthBadRequest:
    def test_exception_unicode_includes_original_failure_message(self):
        error_msg = factory.make_name("error-message")
        original_exception = oauth.OAuthMissingParam(error_msg)
        maas_exception = OAuthBadRequest(original_exception)
        assert f"Bad Request: {error_msg}" in str(maas_exception)
