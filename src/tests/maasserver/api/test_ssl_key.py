# Copyright 2014-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the ssl key API."""

import http.client

from django.conf import settings
from django.urls import reverse
import pytest

from maascommon.events import AUDIT
from maasserver.models import Event, SSLKey
from maasserver.testing import get_data
from maasserver.testing.factory import factory
from maasserver.utils.orm import get_one


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestSSLKeyHandlers:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_sslkeys_handler_path(self):
        assert "/MAAS/api/2.0/account/prefs/sslkeys/" == reverse(
            "sslkeys_handler"
        )

    def test_sslkey_handler_path(self):
        assert "/MAAS/api/2.0/account/prefs/sslkeys/key/" == reverse(
            "sslkey_handler", args=["key"]
        )

    def test_list_works(self):
        _, keys = factory.make_user_with_ssl_keys(n_keys=2, user=self.user)
        response = self.client.get(reverse("sslkeys_handler"))
        assert http.client.OK == response.status_code, response
        parsed_result = [result["resource_uri"] for result in response.json()]
        expected_result = [
            reverse("sslkey_handler", args=[keys[0].id]),
            reverse("sslkey_handler", args=[keys[1].id]),
        ]
        assert sorted(expected_result) == sorted(parsed_result)

    def test_list_sorts_output(self):
        _, keys = factory.make_user_with_ssl_keys(n_keys=2, user=self.user)
        response = self.client.get(reverse("sslkeys_handler"))
        assert http.client.OK == response.status_code, response
        parsed_result = [result["resource_uri"] for result in response.json()]
        expected_result = [
            reverse("sslkey_handler", args=[keys[0].id]),
            reverse("sslkey_handler", args=[keys[1].id]),
        ]
        assert expected_result == parsed_result

    def test_list_only_shows_user_keys(self):
        # other user
        factory.make_user_with_ssl_keys(n_keys=2)
        _, keys = factory.make_user_with_ssl_keys(n_keys=2, user=self.user)
        response = self.client.get(reverse("sslkeys_handler"))
        assert http.client.OK == response.status_code, response
        parsed_result = [result["resource_uri"] for result in response.json()]
        expected_result = [
            reverse("sslkey_handler", args=[keys[0].id]),
            reverse("sslkey_handler", args=[keys[1].id]),
        ]
        assert sorted(expected_result) == sorted(parsed_result)

    def test_list_only_shows_user_keys_for_admin(self):
        # other user
        factory.make_user_with_ssl_keys(n_keys=2)
        _, keys = factory.make_user_with_ssl_keys(n_keys=2, user=self.user)
        self.user.is_superuser = True
        self.user.save()
        response = self.client.get(reverse("sslkeys_handler"))
        assert http.client.OK == response.status_code, response
        parsed_result = [result["resource_uri"] for result in response.json()]
        expected_result = [
            reverse("sslkey_handler", args=[keys[0].id]),
            reverse("sslkey_handler", args=[keys[1].id]),
        ]
        assert sorted(expected_result) == sorted(parsed_result)

    def test_get_by_id_works(self):
        _, keys = factory.make_user_with_ssl_keys(n_keys=1, user=self.user)
        key = keys[0]
        response = self.client.get(reverse("sslkey_handler", args=[key.id]))
        assert http.client.OK == response.status_code, response
        expected = dict(
            id=key.id,
            key=key.key,
            resource_uri=reverse("sslkey_handler", args=[key.id]),
        )
        assert expected == response.json()

    def test_get_by_id_fails_for_non_owner(self):
        _, keys = factory.make_user_with_ssl_keys(n_keys=1)
        factory.make_user_with_ssl_keys(n_keys=1, user=self.user)
        key = keys[0]
        response = self.client.get(reverse("sslkey_handler", args=[key.id]))
        assert http.client.FORBIDDEN == response.status_code, response

    def test_get_by_id_fails_for_non_owner_as_admin(self):
        _, keys = factory.make_user_with_ssl_keys(n_keys=1)
        factory.make_user_with_ssl_keys(n_keys=1, user=self.user)
        self.user.is_superuser = True
        self.user.save()
        key = keys[0]
        response = self.client.get(reverse("sslkey_handler", args=[key.id]))
        assert http.client.FORBIDDEN == response.status_code, response

    def test_delete_by_id_works_and_creates_audit_event(self):
        _, keys = factory.make_user_with_ssl_keys(n_keys=2, user=self.user)
        response = self.client.delete(
            reverse("sslkey_handler", args=[keys[0].id])
        )
        assert http.client.NO_CONTENT == response.status_code, response
        keys_after = SSLKey.objects.filter(user=self.user)
        event = Event.objects.get(type__level=AUDIT)
        assert 1 == len(keys_after)
        assert keys[1].id == keys_after[0].id
        assert event is not None
        assert "Deleted SSL key id='%s'." % keys[0].id == event.description

    def test_delete_fails_if_not_your_key(self):
        user, keys = factory.make_user_with_ssl_keys(n_keys=1)
        response = self.client.delete(
            reverse("sslkey_handler", args=[keys[0].id])
        )
        assert http.client.FORBIDDEN == response.status_code, response
        assert 1 == len(SSLKey.objects.filter(user=user))

    def test_adding_works(self):
        key_string = get_data("data/test_x509_0.pem")
        response = self.client.post(
            reverse("sslkeys_handler"), data=dict(key=key_string)
        )
        assert http.client.CREATED == response.status_code
        assert key_string == response.json()["key"]
        added_key = get_one(SSLKey.objects.filter(user=self.user))
        assert key_string == added_key.key

    def test_adding_catches_key_validation_errors(self):
        key_string = factory.make_string()
        response = self.client.post(
            reverse("sslkeys_handler"), data=dict(key=key_string)
        )
        assert http.client.BAD_REQUEST == response.status_code, response
        assert "Invalid" in response.content.decode(settings.DEFAULT_CHARSET)

    def test_adding_returns_badrequest_when_key_not_in_form(self):
        response = self.client.post(reverse("sslkeys_handler"))
        assert http.client.BAD_REQUEST == response.status_code, response
        assert {"key": ["This field is required."]} == response.json()

    def test_adding_rejects_non_fips_cert_when_fips_enabled(self, mocker):
        from OpenSSL import crypto as ossl_crypto

        from maasserver.models import sslkey

        k = ossl_crypto.PKey()
        k.generate_key(ossl_crypto.TYPE_RSA, 2048)
        cert = ossl_crypto.X509()
        cert.get_subject().CN = "test"
        cert.set_serial_number(1)
        cert.gmtime_adj_notBefore(0)
        cert.gmtime_adj_notAfter(10 * 365 * 24 * 60 * 60)
        cert.set_issuer(cert.get_subject())
        cert.set_pubkey(k)
        cert.sign(k, "sha1")  # SHA-1 signature: FIPS violation
        pem = ossl_crypto.dump_certificate(
            ossl_crypto.FILETYPE_PEM, cert
        ).decode()

        mocker.patch.object(sslkey, "is_fips_enabled", return_value=True)
        response = self.client.post(
            reverse("sslkeys_handler"), data=dict(key=pem)
        )
        assert http.client.BAD_REQUEST == response.status_code, response
        assert "FIPS" in response.content.decode(settings.DEFAULT_CHARSET)
