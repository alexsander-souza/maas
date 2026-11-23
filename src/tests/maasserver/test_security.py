# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


import binascii
from datetime import datetime

import pytest
from pytz import UTC

from maasserver import security
from maasserver.secrets import SecretManager


class TestGetSerial:
    def test_serial_generated(self, mocker):
        nowish = datetime(2014, 0o3, 24, 16, 0o7, tzinfo=UTC)
        security_datetime = mocker.patch.object(security, "datetime")
        # Make security.datetime() work like regular datetime.
        security_datetime.side_effect = datetime
        # Make security.timezone.now() return a fixed value.
        security_datetime.now.return_value = nowish
        assert security.get_serial() == 69005220


@pytest.mark.allow_transactions
@pytest.mark.usefixtures(
    "maasdb", "maas_region_test", "factory", "transactional_maasdb"
)
class TestGetSharedSecret:
    def test_generates_new_secret_when_unset(self):
        secret = security.get_shared_secret()
        assert isinstance(secret, bytes)
        assert len(secret) >= 16

    def test_same_secret_is_returned_on_subsequent_calls(self):
        assert security.get_shared_secret() == security.get_shared_secret()

    def test_errors_when_database_value_cannot_be_decoded(self):
        SecretManager().set_simple_secret("rpc-shared", "_")
        with pytest.raises(binascii.Error):
            security.get_shared_secret()
