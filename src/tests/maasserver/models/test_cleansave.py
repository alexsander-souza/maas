# Copyright 2018-2022 Canonical Ltd. This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from django.db.models import Model
import pytest

from maasserver.tests.models import CleanSaveTestModel


@pytest.mark.usefixtures("maasdb", "maas_region_test")
class TestCleanSave:
    def test_save_doesnt_clean_pk_and_related_fields_when_new(self, mocker):
        obj = CleanSaveTestModel()
        mock_full_clean = mocker.patch.object(obj, "full_clean")
        obj.save()
        if hasattr(obj, "validate_constraints"):
            mock_full_clean.assert_called_once_with(
                exclude={"id", "related"},
                validate_unique=False,
                validate_constraints=False,
            )
        else:
            # FIXME Remove this once Django3 support is dropped
            mock_full_clean.assert_called_once_with(
                exclude={"id", "related"}, validate_unique=False
            )

    def test_save_validates_unique_except_for_pk_when_new(self, mocker):
        obj = CleanSaveTestModel()
        mock_validate_unique = mocker.patch.object(obj, "validate_unique")
        obj.save()
        mock_validate_unique.assert_called_once_with(exclude={"id"})

    def test_save_performed_with_force_update(self, mocker):
        obj = CleanSaveTestModel.objects.create()
        mock_save = mocker.patch.object(Model, "save")
        obj.save(force_update=True)
        mock_save.assert_called_once_with(force_update=True)

    def test_save_performed_when_id_reset(self, mocker):
        obj = CleanSaveTestModel.objects.create()
        obj.id = None
        mock_save = mocker.patch.object(Model, "save")
        obj.save()
        mock_save.assert_called_once_with()

    def test_save_performed_when_state_forced(self, mocker):
        obj = CleanSaveTestModel.objects.create()
        obj._state.adding = True
        mock_save = mocker.patch.object(Model, "save")
        obj.save()
        mock_save.assert_called_once_with()

    def test_save_performed_with_force_insert(self, mocker):
        obj = CleanSaveTestModel.objects.create()
        mock_save = mocker.patch.object(Model, "save")
        obj.save(force_insert=True)
        mock_save.assert_called_once_with(force_insert=True)
