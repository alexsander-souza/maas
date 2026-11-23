# Copyright 2022-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the config-tls command."""

from contextlib import contextmanager
import tempfile

from django.core.management import call_command
import pytest

from maascommon.events import AUDIT
from maasserver.enum import ENDPOINT
from maasserver.management.commands import config_tls
from maasserver.models import Config, Event, Notification
from maasserver.regiondservices.certificate_expiration_check import (
    REGIOND_CERT_EXPIRE_NOTIFICATION_IDENT,
    REGIOND_CERT_EXPIRED_NOTIFICATION_IDENT,
)
from maasserver.secrets import SecretManager
from maasserver.testing.factory import factory
from provisioningserver.certificates import CertificateError
from provisioningserver.events import EVENT_TYPES
from provisioningserver.testing.certificates import (
    get_sample_cert,
    get_sample_cert_with_cacerts,
)


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestConfigTLSCommand:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker, request):
        self.read_input = mocker.patch.object(config_tls, "prompt_yes_no")
        self.read_input.return_value = False
        from maasserver.sqlalchemy import service_layer

        original_call_command = call_command

        def call_command_with_service_layer(*args, **kwargs):
            try:
                return original_call_command(*args, **kwargs)
            finally:
                service_layer.init()

        mocker.patch.object(
            request.module,
            "call_command",
            side_effect=call_command_with_service_layer,
        )

    @contextmanager
    def wrong_file(self):
        with tempfile.NamedTemporaryFile(mode="w+") as key_file:
            key_file.flush()
            yield key_file.name

    def _get_config(self):
        return (
            SecretManager().get_composite_secret("tls", default=None),
            Config.objects.get_config("tls_port"),
        )

    def get_notifications(self):
        notifications = Notification.objects.filter(
            ident__in=[
                REGIOND_CERT_EXPIRE_NOTIFICATION_IDENT,
                REGIOND_CERT_EXPIRED_NOTIFICATION_IDENT,
            ]
        ).order_by("ident")
        return list(notifications)

    def test_config_tls_disable(self):
        call_command("config_tls", "disable")
        assert self._get_config() == (None, None)

    def test_config_tls_enable_skip_confirm(self):
        sample_cert = get_sample_cert()
        cert_path, key_path = sample_cert.tempfiles()

        call_command(
            "config_tls", "enable", key_path, cert_path, "-p=5234", "--yes"
        )
        # the command is not interactive
        self.read_input.assert_not_called()
        assert self._get_config() == (
            {
                "key": sample_cert.private_key_pem(),
                "cert": sample_cert.certificate_pem(),
                "cacert": "",
            },
            5234,
        )

    def test_config_tls_enable(self):
        sample_cert = get_sample_cert()
        cert_path, key_path = sample_cert.tempfiles()

        self.read_input.return_value = "y"
        call_command("config_tls", "enable", key_path, cert_path, "-p=5234")
        assert self._get_config() == (
            {
                "key": sample_cert.private_key_pem(),
                "cert": sample_cert.certificate_pem(),
                "cacert": "",
            },
            5234,
        )

    def test_config_tls_enable_with_cacert(self, tmp_path):
        sample_cert = get_sample_cert_with_cacerts()
        cert_path, key_path = sample_cert.tempfiles()
        cacert_path = tmp_path / "cacerts.pem"

        cacert_path.write_text(sample_cert.ca_certificates_pem())

        call_command(
            "config_tls",
            "enable",
            key_path,
            cert_path,
            "--cacert",
            str(cacert_path),
            "-p",
            "5234",
            "--yes",
        )
        assert self._get_config() == (
            {
                "key": sample_cert.private_key_pem(),
                "cert": sample_cert.certificate_pem(),
                "cacert": sample_cert.ca_certificates_pem(),
            },
            5234,
        )

    def test_config_tls_enable_break(self):
        sample_cert = get_sample_cert()
        cert_path, key_path = sample_cert.tempfiles()

        last_config = self._get_config()

        call_command("config_tls", "enable", key_path, cert_path)
        self.read_input.return_value = "n"

        current_config = self._get_config()
        assert last_config == current_config

    def test_config_tls_enable_with_default_port(self):
        sample_cert = get_sample_cert()
        cert_path, key_path = sample_cert.tempfiles()

        self.read_input.return_value = "y"
        call_command("config_tls", "enable", key_path, cert_path)

        assert self._get_config() == (
            {
                "key": sample_cert.private_key_pem(),
                "cert": sample_cert.certificate_pem(),
                "cacert": "",
            },
            5443,
        )

    def test_config_tls_enable_with_incorrect_key(self):
        self.read_input.return_value = "y"
        with self.wrong_file() as key_path:
            sample_cert = get_sample_cert()
            cert_path, _ = sample_cert.tempfiles()

            with pytest.raises(CertificateError, match="Invalid PEM material"):
                call_command("config_tls", "enable", key_path, cert_path)

    def test_config_tls_enable_with_incorrect_cert(self):
        self.read_input.return_value = "y"
        with self.wrong_file() as cert_path:
            sample_cert = get_sample_cert()
            _, key_path = sample_cert.tempfiles()

            with pytest.raises(CertificateError, match="Invalid PEM material"):
                call_command("config_tls", "enable", key_path, cert_path)

    def test_config_tls_is_audited(self):
        sample_cert = get_sample_cert()
        cert_path, key_path = sample_cert.tempfiles()

        self.read_input.return_value = "y"
        call_command("config_tls", "enable", key_path, cert_path)

        assert self._get_config() == (
            {
                "key": sample_cert.private_key_pem(),
                "cert": sample_cert.certificate_pem(),
                "cacert": "",
            },
            5443,
        )
        [event] = Event.objects.filter(type__level=AUDIT)
        assert EVENT_TYPES.SETTINGS == event.type.name
        assert ENDPOINT.CLI == event.endpoint
        assert event.description == "Updated TLS configuration settings"

    def test_config_tls_disable_removes_tls_notifications(self):
        factory.make_Notification(
            ident=REGIOND_CERT_EXPIRE_NOTIFICATION_IDENT,
            admins=True,
            dismissable=True,
        )
        factory.make_Notification(
            ident=REGIOND_CERT_EXPIRED_NOTIFICATION_IDENT,
            admins=True,
            dismissable=True,
        )

        call_command("config_tls", "disable")

        notifications = self.get_notifications()
        assert 0 == len(notifications)

    def test_config_tls_enable_removes_tls_notifications(self):
        factory.make_Notification(
            ident=REGIOND_CERT_EXPIRE_NOTIFICATION_IDENT,
            admins=True,
            dismissable=True,
        )
        factory.make_Notification(
            ident=REGIOND_CERT_EXPIRED_NOTIFICATION_IDENT,
            admins=True,
            dismissable=True,
        )

        sample_cert = get_sample_cert()
        cert_path, key_path = sample_cert.tempfiles()

        self.read_input.return_value = "y"
        call_command("config_tls", "enable", key_path, cert_path)
        notifications = self.get_notifications()
        assert 0 == len(notifications)
