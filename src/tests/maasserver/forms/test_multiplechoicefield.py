# Copyright 2014-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for multiple-choice fields."""

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
import pytest

from maasserver.forms import (
    UnconstrainedMultipleChoiceField,
    ValidatorMultipleChoiceField,
)


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestUnconstrainedMultipleChoiceField:
    def test_accepts_list(self):
        value = ["a", "b"]
        instance = UnconstrainedMultipleChoiceField()
        assert value == instance.clean(value)


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestValidatorMultipleChoiceField:
    def test_field_validates_valid_data(self):
        value = ["test@example.com", "me@example.com"]
        field = ValidatorMultipleChoiceField(validator=validate_email)
        assert value == field.clean(value)

    def test_field_uses_validator(self):
        value = ["test@example.com", "invalid-email"]
        field = ValidatorMultipleChoiceField(validator=validate_email)
        with pytest.raises(ValidationError) as error:
            field.clean(value)
        assert ["Enter a valid email address."] == error.value.messages
