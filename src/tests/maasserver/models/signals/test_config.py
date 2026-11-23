# Copyright 2016-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the behaviour of config signals."""

import pytest

from maasserver.models import domain as domain_module
from maasserver.models.config import Config


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestConfigSignals:
    def test_changing_kms_host_triggers_update(self, mocker):
        dns_kms_setting_changed = mocker.patch.object(
            domain_module, "dns_kms_setting_changed", autospec=True
        )
        Config.objects.set_config("windows_kms_host", "8.8.8.8")
        dns_kms_setting_changed.assert_called_once_with()
