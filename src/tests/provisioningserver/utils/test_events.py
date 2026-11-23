# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for event-related helpers."""

from unittest.mock import MagicMock, sentinel

from maastesting.factory import factory
from provisioningserver.utils.events import Event, EventGroup


class TestEvent:
    """Tests for `Event`."""

    def test_registerHandler(self):
        event = Event()
        event.registerHandler(sentinel.handler)
        assert {sentinel.handler} == event.handlers

    def test_registerHandler_during_fire(self):
        event = Event()
        event.registerHandler(event.registerHandler)
        event.fire(sentinel.otherHandler)
        assert {event.registerHandler, sentinel.otherHandler} == event.handlers

    def test_unregisterHandler(self):
        event = Event()
        event.registerHandler(sentinel.handler)
        event.unregisterHandler(sentinel.handler)
        assert set() == event.handlers

    def test_unregisterHandler_during_fire(self):
        event = Event()
        event.registerHandler(event.unregisterHandler)
        event.fire(event.unregisterHandler)
        assert set() == event.handlers

    def test_fire_calls_all_handlers(self, mocker):
        event = Event()
        handler_one = MagicMock()
        handler_two = MagicMock()
        event.registerHandler(handler_one)
        event.registerHandler(handler_two)
        args = [factory.make_name("arg") for _ in range(3)]
        kwargs = {
            factory.make_name("key"): factory.make_name("value")
            for _ in range(3)
        }
        event.fire(*args, **kwargs)
        handler_one.assert_called_once_with(*args, **kwargs)
        handler_two.assert_called_once_with(*args, **kwargs)


class TestEventGroup:
    """Tests for `EventGroup`."""

    def test_makes_events_as_properties(self):
        events = [factory.make_name("event") for _ in range(3)]
        group = EventGroup(*events)
        for event in events:
            assert isinstance(getattr(group, event), Event)
