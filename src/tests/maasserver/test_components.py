# Copyright 2012-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import random

import pytest

from maasserver.components import (
    discard_persistent_error,
    get_persistent_errors,
    register_persistent_error,
)
from maasserver.enum import COMPONENT
from maasserver.models import Notification
from maasserver.testing.factory import factory
from provisioningserver.utils.enum import map_enum


def get_random_component():
    return random.choice(list(map_enum(COMPONENT).values()))


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestPersistentErrorsUtilities:
    def test_register_persistent_error_registers_error(self):
        error_message = factory.make_string()
        component = get_random_component()
        register_persistent_error(component, error_message)
        assert [error_message] == get_persistent_errors()

    def test_register_persistent_error_stores_last_error(self):
        error_message = factory.make_string()
        error_message2 = factory.make_string()
        component = get_random_component()
        register_persistent_error(component, error_message)
        register_persistent_error(component, error_message2)
        assert [error_message2] == get_persistent_errors()

    def test_discard_persistent_error_discards_error(self):
        error_message = factory.make_string()
        component = get_random_component()
        register_persistent_error(component, error_message)
        discard_persistent_error(component)
        assert [] == get_persistent_errors()

    def test_discard_persistent_error_can_be_called_many_times(self):
        error_message = factory.make_string()
        component = get_random_component()
        register_persistent_error(component, error_message)
        discard_persistent_error(component)
        discard_persistent_error(component)
        assert [] == get_persistent_errors()

    def get_persistent_errors_returns_text_for_error_codes(self):
        errors, components = [], []
        for _ in range(3):
            error_message = factory.make_string()
            component = get_random_component()
            register_persistent_error(component, error_message)
            errors.append(error_message)
            components.append(component)
        assert errors == get_persistent_errors()

    def test_register_persistent_error_reuses_component_errors(self):
        """When registering a persistent error that already has an error
        recorded for that component, reuse the error instead of deleting and
        recreating it."""
        component = factory.make_name("component")
        error1 = factory.make_name("error")
        error2 = factory.make_name("error")
        register_persistent_error(component, error1)
        notification = Notification.objects.get(ident=component)
        assert notification.render() == error1
        notification_id = notification.id
        register_persistent_error(component, error2)
        notification = Notification.objects.get(ident=component)
        # The message is updated.
        assert notification.render() == error2
        # The same notification row is used.
        assert notification.id == notification_id
