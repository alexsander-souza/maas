# Copyright 2014-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import logging
import random

from django.db import IntegrityError
import pytest

from maasserver.models import Event, EventType
from maasserver.models import event as event_module
from maasserver.testing.factory import factory
from provisioningserver.events import EVENT_TYPES


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestEvent:
    def test_displays_event_node(self):
        event = factory.make_Event()
        assert "%s" % event.node in "%s" % event

    def test_register_event_and_event_type_registers_event(self):
        # EvenType exists
        node = factory.make_Node()
        event_type = factory.make_EventType()
        Event.objects.register_event_and_event_type(
            system_id=node.system_id, type_name=event_type.name
        )
        assert Event.objects.get(node=node) is not None

    def test_register_event_and_event_type_registers_event_with_datetime(self):
        # EvenType exists
        node = factory.make_Node()
        event_type = factory.make_EventType()
        created = factory.make_date()
        event = Event.objects.register_event_and_event_type(
            system_id=node.system_id,
            type_name=event_type.name,
            created=created,
        )
        assert created == event.created

    def test_register_event_and_event_type_registers_event_for_new_type(self):
        # EventType does not exist
        node = factory.make_Node()
        type_name = factory.make_name("type_name")
        description = factory.make_name("description")
        action = factory.make_name("action")

        Event.objects.register_event_and_event_type(
            system_id=node.system_id,
            type_name=type_name,
            type_description=description,
            type_level=random.choice(
                [logging.ERROR, logging.WARNING, logging.INFO]
            ),
            event_action=action,
            event_description=description,
        )

        # Since this is a new node, it can have only this one event.
        event = Event.objects.get(node=node)

        # Check if all parameters were correctly saved.
        assert node == event.node
        assert type_name == event.type.name
        assert description == event.description
        assert action == event.action

    def test_register_event_and_event_type_registers_event_type(self):
        # EventType does not exist
        node = factory.make_Node()
        type_name = factory.make_name("type_name")
        description = factory.make_name("description")
        action = factory.make_name("action")

        Event.objects.register_event_and_event_type(
            system_id=node.system_id,
            type_name=type_name,
            type_description=description,
            type_level=random.choice(
                [logging.ERROR, logging.WARNING, logging.INFO]
            ),
            event_action=action,
            event_description=description,
        )

        # Check whether we created the event type.
        assert EventType.objects.get(name=type_name) is not None

    def test_register_event_and_event_type_registers_event_with_user(self):
        # EventType does not exist
        node = factory.make_Node()
        type_name = factory.make_name("type_name")
        description = factory.make_name("description")
        action = factory.make_name("action")

        Event.objects.register_event_and_event_type(
            system_id=node.system_id,
            type_name=type_name,
            type_description=description,
            type_level=random.choice(
                [logging.ERROR, logging.WARNING, logging.INFO]
            ),
            event_action=action,
            event_description=description,
            user=node.owner,
        )

        # Check whether we created the event type.
        assert EventType.objects.get(name=type_name) is not None
        assert Event.objects.get(node_system_id=node.system_id) is not None

    def test_create_node_event_creates_event(self):
        # EventTypes that are currently being used for
        # create_node_event
        node = factory.make_Node()
        event_type = random.choice([EVENT_TYPES.NODE_PXE_REQUEST])
        Event.objects.create_node_event(
            system_id=node.system_id, event_type=event_type, user=node.owner
        )
        assert EventType.objects.get(name=event_type) is not None
        assert Event.objects.get(node=node) is not None

    def test_create_region_event_creates_region_event(self, mocker):
        region = factory.make_RegionRackController()
        mocker.patch.object(
            event_module.MAAS_ID, "get", return_value=region.system_id
        )
        Event.objects.create_region_event(
            event_type=EVENT_TYPES.REGION_IMPORT_ERROR, user=region.owner
        )
        assert (
            EventType.objects.get(name=EVENT_TYPES.REGION_IMPORT_ERROR)
            is not None
        )
        assert Event.objects.get(node=region) is not None

    def test_register_event_and_event_type_handles_integrity_errors(
        self, mocker
    ):
        # It's possible that two calls to
        # register_event_and_event_type() could arrive at more-or-less
        # the same time. If that happens, we could end up with an
        # IntegrityError getting raised. register_event_and_event_type()
        # will handle that correctly rather than allowing it to blow up.
        node = factory.make_Node()
        type_name = factory.make_name("type_name")
        description = factory.make_name("description")
        action = factory.make_name("action")

        Event.objects.register_event_and_event_type(
            system_id=node.system_id,
            type_name=type_name,
            type_description=description,
            type_level=random.choice(
                [logging.ERROR, logging.WARNING, logging.INFO]
            ),
            event_action=action,
            event_description=description,
        )

        mocker.patch.object(
            EventType.objects, "create", side_effect=IntegrityError
        )
        Event.objects.register_event_and_event_type(
            system_id=node.system_id,
            type_name=type_name,
            type_description=description,
            type_level=random.choice(
                [logging.ERROR, logging.WARNING, logging.INFO]
            ),
            event_action=action,
            event_description=description,
        )

        # If we get this far then we have the event type and the
        # events, and more importantly no errors got raised.
        event_type = EventType.objects.get(name=type_name)
        assert event_type is not None
        assert 2 == Event.objects.filter(node=node).count()
