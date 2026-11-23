# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from datetime import timedelta

import pytest
from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks

from maasserver.models.config import Config
from maasserver.models.notification import Notification
from maasserver.regiondservices.certificate_expiration_check import (
    CertificateExpirationCheckService,
    REGIOND_CERT_EXPIRE_NOTIFICATION_IDENT,
    REGIOND_CERT_EXPIRED_NOTIFICATION_IDENT,
)
from maasserver.secrets import SecretManager
from maasserver.testing.factory import factory
from maasserver.utils.threads import deferToDatabase
from maastesting.crochet import wait_for
from provisioningserver.testing.certificates import get_sample_cert

wait_for_reactor = wait_for()


@pytest.mark.allow_transactions
@pytest.mark.usefixtures(
    "maasdb", "transactional_maasdb", "maas_region_test", "factory"
)
class TestCertificateExpirationCheckService:
    def set_config(self, cert, enabled=True, interval=10):
        SecretManager().set_composite_secret(
            "tls",
            {
                "key": cert.private_key_pem(),
                "cert": cert.certificate_pem(),
            },
        )
        Config.objects.set_config(
            "tls_cert_expiration_notification_enabled", enabled
        )
        Config.objects.set_config(
            "tls_cert_expiration_notification_interval", interval
        )

    def get_notifications(self):
        notifications = Notification.objects.filter(
            ident__in=[
                REGIOND_CERT_EXPIRE_NOTIFICATION_IDENT,
                REGIOND_CERT_EXPIRED_NOTIFICATION_IDENT,
            ]
        ).order_by("ident")
        return list(notifications)

    @wait_for_reactor
    @inlineCallbacks
    def test_no_notifications_when_not_enabled(self):
        yield deferToDatabase(
            Config.objects.set_config,
            "tls_cert_expiration_notification_enabled",
            False,
        )
        yield deferToDatabase(
            factory.make_Notification,
            ident=REGIOND_CERT_EXPIRE_NOTIFICATION_IDENT,
            admins=True,
            dismissable=True,
        )

        service = CertificateExpirationCheckService(reactor)
        yield service.startService()
        yield service.stopService()

        notifications = yield deferToDatabase(self.get_notifications)
        assert len(notifications) == 0

    @wait_for_reactor
    @inlineCallbacks
    def test_notify_when_certificate_will_expire(self):
        sample_cert = get_sample_cert(validity=timedelta(days=5))
        yield deferToDatabase(self.set_config, cert=sample_cert)

        service = CertificateExpirationCheckService(reactor)
        yield service.startService()
        yield service.stopService()

        notifications = yield deferToDatabase(self.get_notifications)
        assert len(notifications) == 1
        notification = notifications[0]
        assert notification is not None
        assert notification.category == "info"
        assert notification.dismissable
        assert notification.admins
        assert not notification.users
        assert notification.context["days"] == 4

    @wait_for_reactor
    @inlineCallbacks
    def test_notify_when_certificate_will_expire_update(self):
        sample_cert = get_sample_cert(validity=timedelta(days=5))
        yield deferToDatabase(self.set_config, cert=sample_cert)
        yield deferToDatabase(
            factory.make_Notification,
            ident=REGIOND_CERT_EXPIRE_NOTIFICATION_IDENT,
            category="info",
            admins=True,
            dismissable=True,
            context={"days": 10},
        )
        service = CertificateExpirationCheckService(reactor)
        yield service.startService()
        yield service.stopService()

        notifications = yield deferToDatabase(self.get_notifications)
        assert len(notifications) == 1
        notification = notifications[0]
        assert notification is not None
        assert notification.category == "info"
        assert notification.dismissable
        assert notification.admins
        assert not notification.users
        assert notification.context["days"] == 4

    @wait_for_reactor
    @inlineCallbacks
    def test_notify_when_certificate_expired(self):
        sample_cert = get_sample_cert(validity=timedelta(days=0))
        yield deferToDatabase(self.set_config, cert=sample_cert)
        yield deferToDatabase(
            factory.make_Notification,
            ident=REGIOND_CERT_EXPIRE_NOTIFICATION_IDENT,
            admins=True,
            dismissable=True,
        )
        service = CertificateExpirationCheckService(reactor)
        yield service.startService()
        yield service.stopService()

        notifications = yield deferToDatabase(self.get_notifications)
        assert len(notifications) == 1
        notification = notifications[0]
        assert notification is not None
        assert notification.category == "warning"
        assert notification.dismissable
        assert notification.admins
        assert not notification.users
        assert notification.ident == REGIOND_CERT_EXPIRED_NOTIFICATION_IDENT

    @wait_for_reactor
    @inlineCallbacks
    def test_notify_when_certificate_renewed_after_expired(self):
        sample_cert = get_sample_cert(validity=timedelta(days=30))
        yield deferToDatabase(self.set_config, cert=sample_cert)
        yield deferToDatabase(
            factory.make_Notification,
            ident=REGIOND_CERT_EXPIRED_NOTIFICATION_IDENT,
            admins=True,
            dismissable=True,
        )
        service = CertificateExpirationCheckService(reactor)
        yield service.startService()
        yield service.stopService()

        notifications = yield deferToDatabase(self.get_notifications)
        assert len(notifications) == 0

    @wait_for_reactor
    @inlineCallbacks
    def test_notify_when_certificate_renewed_before_expired(self):
        sample_cert = get_sample_cert(validity=timedelta(days=30))
        yield deferToDatabase(self.set_config, cert=sample_cert)
        yield deferToDatabase(
            factory.make_Notification,
            ident=REGIOND_CERT_EXPIRE_NOTIFICATION_IDENT,
            admins=True,
            dismissable=True,
        )
        service = CertificateExpirationCheckService(reactor)
        yield service.startService()
        yield service.stopService()

        notifications = yield deferToDatabase(self.get_notifications)
        assert len(notifications) == 0
