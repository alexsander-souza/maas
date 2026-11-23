# Copyright 2014-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
from typing import Optional

from django import forms
from django.http import HttpRequest
import pytest

from maasserver.enum import ENDPOINT_CHOICES
from maasserver.forms import ConfigForm
from maasserver.models import Config
from maasserver.testing.factory import factory
import maasservicelayer.models.configurations as maascommon_configuration
import maasservicelayer.services.configurations as servicelayer_config_module


class OptionForm(ConfigForm):
    field1 = forms.CharField(label="Field 1", max_length=10)
    field2 = forms.BooleanField(label="Field 2", required=False)


class ValidOptionForm(ConfigForm):
    maas_name = forms.CharField(label="Field 1", max_length=10)


class CompositeForm(ConfigForm):
    config_fields = ["maas_name"]

    maas_name = forms.CharField(label="Field 1", max_length=10)
    non_config_field = forms.CharField(label="Field 2", max_length=10)


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestConfigForm:
    def _get_config_stub(self, config_name, default_value):
        class Field1Stub(maascommon_configuration.Config[Optional[str]]):
            name = config_name
            default = default_value

        return Field1Stub

    def _get_factory_config_stub(self, config_name, default_value):
        class ConfigFactoryStub(maascommon_configuration.ConfigFactory):
            @classmethod
            def get_config_model(cls, name):
                if name == config_name:
                    return self._get_config_stub(config_name, default_value)
                else:
                    raise ValueError("Unkwnown config.")

        return ConfigFactoryStub

    def test_form_valid_saves_into_db(self):
        endpoint = factory.pick_choice(ENDPOINT_CHOICES)
        request = HttpRequest()
        request.user = factory.make_User()
        value = factory.make_string(10)
        form = ValidOptionForm({"maas_name": value})
        result = form.save(endpoint, request)

        assert result, form._errors
        assert Config.objects.get_config("maas_name") == value

    def test_form_rejects_unknown_settings(self):
        value = factory.make_string(10)
        value2 = factory.make_string(10)
        form = OptionForm({"field1": value, "field2": value2})
        valid = form.is_valid()

        assert not valid, form._errors
        assert "field1" in form._errors
        assert "field2" in form._errors

    def test_form_invalid_does_not_save_into_db(self):
        endpoint = factory.pick_choice(ENDPOINT_CHOICES)
        request = HttpRequest()
        request.user = factory.make_User()
        value_too_long = factory.make_string(20)
        form = OptionForm({"field1": value_too_long, "field2": False})
        result = form.save(endpoint, request)

        assert not result, form._errors
        assert "field1" in form._errors
        assert Config.objects.get_config("field1") is None
        assert Config.objects.get_config("field2") is None

    def test_form_loads_initial_values(self):
        value = factory.make_string()
        Config.objects.set_config("field1", value)
        form = OptionForm()

        assert form.initial == {"field1": value}

    def test_form_loads_initial_values_from_default_value(self, mocker):
        value = factory.make_string()
        mocker.patch.object(
            servicelayer_config_module,
            "ConfigFactory",
            self._get_factory_config_stub("field1", value),
        )
        form = OptionForm()
        assert form.initial == {"field1": value}

    def test_validates_composite_form(self):
        endpoint = factory.pick_choice(ENDPOINT_CHOICES)
        request = HttpRequest()
        request.user = factory.make_User()
        value1 = factory.make_string(5)
        value2 = factory.make_string(5)
        form = CompositeForm({"maas_name": value1, "non_config_field": value2})
        result = form.save(endpoint, request)

        assert result, form._errors
        assert Config.objects.get_config("maas_name") == value1
