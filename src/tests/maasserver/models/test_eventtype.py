# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import random
import threading
import time

import pytest

from maasserver.models.eventtype import EventType, LOGGING_LEVELS
from maasserver.testing.factory import factory
from maasserver.utils.orm import transactional


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestEventType:
    def test_displays_event_type_description(self):
        event_type = factory.make_EventType()
        assert event_type.description in "%s" % event_type

    def test_level_str_returns_level_description(self):
        events_and_levels = [
            (
                level,
                factory.make_Event(type=factory.make_EventType(level=level)),
            )
            for level in LOGGING_LEVELS
        ]

        actual_levels = [
            event.type.level_str for level, event in events_and_levels
        ]
        expected_levels = [
            LOGGING_LEVELS[level] for level, event in events_and_levels
        ]
        assert actual_levels == expected_levels

    def test_register(self):
        name = factory.make_name("name")
        desc = factory.make_name("desc")
        level = random.choice(list(LOGGING_LEVELS))
        event_type = EventType.objects.register(name, desc, level)
        assert event_type.name == name
        assert event_type.description == desc
        assert event_type.level == level

    def test_register_does_not_update_existing_description_or_level(self):
        name = factory.make_name("name")
        levels = set(LOGGING_LEVELS)

        desc1 = factory.make_name("desc1")
        level1 = levels.pop()
        event_type1 = EventType.objects.register(name, desc1, level1)

        desc2 = factory.make_name("desc2")
        level2 = levels.pop()
        event_type2 = EventType.objects.register(name, desc2, level2)

        assert event_type1 == event_type2
        assert event_type2.name == name
        assert event_type2.description == desc1
        assert event_type2.level == level1


@pytest.mark.allow_transactions
@pytest.mark.usefixtures(
    "maasdb", "maas_region_test", "factory", "transactional_maasdb"
)
class TestEventTypeConcurrency:
    def test_register_is_safe_with_concurrency(self):
        name = factory.make_name("name")
        desc = factory.make_name("desc")
        level = random.choice(list(LOGGING_LEVELS))

        # A list to store the event types that are being registered, and a
        # lock to synchronise write access to it.
        event_types_lock = threading.Lock()
        event_types = []

        # Use the transactional decorator to do two things: retry when there's
        # an IntegrityError, and ensure that old connections are closed in the
        # threads we're spawning. If we don't do the latter Django gets angry.
        @transactional
        def make_event_type():
            # Create the event type then wait a short time to increase the
            # chances that transactions between threads overlap.
            etype = EventType.objects.register(name, desc, level)
            time.sleep(0.1)
            return etype

        # Only save the event type when the txn that make_event_type() runs is
        # has been committed. This is when we're likely to see errors.
        def make_event_type_in_thread():
            event_type = make_event_type()
            with event_types_lock:
                event_types.append(event_type)

        # Create a number of threads to simulate a race.
        threads = [
            threading.Thread(target=make_event_type_in_thread)
            for _ in range(5)
        ]

        # Start all the threads at the same time.
        for thread in threads:
            thread.start()
        # Now wait for them all to finish.
        for thread in threads:
            thread.join()

        # All threads return the same event type.
        assert len(threads) == len(event_types)
        for et in event_types:
            assert et.name == name
            assert et.description == desc
            assert et.level == level
