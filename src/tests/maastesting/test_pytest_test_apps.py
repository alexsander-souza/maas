# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from django.apps import apps
from django.conf import settings
from django.db import connection
import pytest

from maasserver.djangosettings import development
from maasserver.djangosettings import settings as production_settings
from maasserver.tests.models import GenericTestModel
from metadataserver.fields import Bin
from metadataserver.tests.models import BinaryFieldModel


def test_test_apps_are_registered_only_in_pytest_settings():
    assert apps.get_app_config("maasserver_tests").name == "maasserver.tests"
    assert (
        apps.get_app_config("metadataserver_tests").name
        == "metadataserver.tests"
    )
    assert settings.MIGRATION_MODULES["maasserver_tests"] is None
    assert settings.MIGRATION_MODULES["metadataserver_tests"] is None
    assert "maasserver.tests" not in production_settings.INSTALLED_APPS
    assert "metadataserver.tests" not in production_settings.INSTALLED_APPS
    assert "maasserver_tests" not in production_settings.MIGRATION_MODULES
    assert "metadataserver_tests" not in production_settings.MIGRATION_MODULES
    assert "maasserver.tests" not in development.INSTALLED_APPS
    assert "metadataserver.tests" not in development.INSTALLED_APPS
    assert "maasserver_tests" not in development.MIGRATION_MODULES
    assert "metadataserver_tests" not in development.MIGRATION_MODULES


@pytest.mark.recreate_db
def test_test_app_tables_exist_in_worker_database(maasdb, worker_id):
    assert connection.settings_dict["NAME"] == f"maas_test_{worker_id}"

    region_model = GenericTestModel.objects.create(field="ordinary pytest")
    metadata_model = BinaryFieldModel.objects.create(
        data=Bin(b"test-only table")
    )

    assert GenericTestModel.objects.get(pk=region_model.pk).field == (
        "ordinary pytest"
    )
    assert BinaryFieldModel.objects.get(pk=metadata_model.pk).data == (
        b"test-only table"
    )
