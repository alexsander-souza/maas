# Copyright 2015-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


from collections import Counter
import http.client
from itertools import chain, combinations
import logging
import random
from random import randint
from urllib.parse import parse_qsl, urlparse

from django.conf import settings
from django.urls import reverse
import pytest

from maascommon.events import AUDIT
from maasserver.api import events as events_module
from maasserver.api.events import DATETIME_FORMAT, event_to_dict
from maasserver.enum import NODE_TYPE
from maasserver.testing.factory import factory
from maasserver.utils.converters import json_load_bytes
from maasserver.utils.orm import reload_object
from maastesting.querycounter import count_queries
from tests.maasserver.api.test_nodes import RequestFixture


def make_events(count=None, **kwargs):
    """Make `count` events using the factory."""
    return [
        factory.make_Event(**kwargs)
        for _ in range(randint(2, 7) if count is None else count)
    ]


def extract_event_ids(parsed_result):
    """List the system_ids of the nodes in `parsed_result`'s events."""
    return [event["id"] for event in parsed_result["events"]]


def shuffled(things):
    things = list(things)
    random.shuffle(things)
    return things


@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestEventToDict:
    """Test for `event_to_dict` function."""

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_node_not_None(self):
        event = factory.make_Event()
        event_dict = event_to_dict(event)
        assert event_dict["username"] == event.owner
        assert event_dict["node"] == event.node.system_id
        assert event_dict["hostname"] == event.hostname
        assert event_dict["id"] == event.id
        assert event_dict["level"] == event.type.level_str
        assert event_dict["created"] == event.created.strftime(DATETIME_FORMAT)
        assert event_dict["type"] == event.type.description
        assert event_dict["description"] == event.description

    def test_node_and_user_is_None(self):
        user = factory.make_User()
        node = factory.make_Node()
        event = factory.make_Event(node=node, user=user)
        node.delete()
        user.delete()
        event = reload_object(event)
        event_dict = event_to_dict(event)
        assert event_dict["username"] == event.owner
        assert event_dict["node"] is None
        assert event_dict["hostname"] == event.hostname
        assert event_dict["id"] == event.id
        assert event_dict["level"] == event.type.level_str
        assert event_dict["created"] == event.created.strftime(DATETIME_FORMAT)
        assert event_dict["type"] == event.type.description
        assert event_dict["description"] == event.description

    def test_type_level_AUDIT(self):
        event = factory.make_Event()
        event_dict = event_to_dict(event)
        assert event_dict["username"] == event.owner
        assert event_dict["node"] == event.node.system_id
        assert event_dict["hostname"] == event.hostname
        assert event_dict["id"] == event.id
        assert event_dict["level"] == event.type.level_str
        assert event_dict["created"] == event.created.strftime(DATETIME_FORMAT)
        assert event_dict["type"] == event.type.description
        assert event_dict["description"] == event.render_audit_description


@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestEventsAPI:
    """Tests for /api/2.0/events/."""

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    log_levels = (
        ("CRITICAL", logging.CRITICAL),
        ("ERROR", logging.ERROR),
        ("WARNING", logging.WARNING),
        ("INFO", logging.INFO),
        ("DEBUG", logging.DEBUG),
    )

    def test_handler_path(self):
        assert "/MAAS/api/2.0/events/" == reverse("events_handler")

    def test_GET_query_without_events_returns_empty_list(self):
        # If there are no nodes to list, the "query" op returns an empty list.
        response = self.client.get(reverse("events_handler"), {"op": "query"})
        assert response.status_code == http.client.OK
        response_dict = json_load_bytes(response.content)
        assert response_dict.get("count") == 0
        assert response_dict.get("events") == []

    def test_GET_query_returns_events_in_order_newest_first(self):
        node = factory.make_Node()
        events = make_events(node=node)
        response = self.client.get(
            reverse("events_handler"), {"op": "query", "level": "DEBUG"}
        )
        parsed_result = json_load_bytes(response.content)
        assert [event.id for event in reversed(events)] == extract_event_ids(
            parsed_result
        )
        assert len(events) == parsed_result["count"]

    def test_GET_query_with_id_returns_matching_nodes(self):
        # The "list" operation takes optional "id" parameters.  Only
        # events from nodes with matching ids will be returned.
        nodes = [factory.make_Node() for _ in range(3)]
        events = [factory.make_Event(node=node) for node in nodes]
        first_node = nodes[0]
        first_event = events[0]  # Pertains to the first node.
        response = self.client.get(
            reverse("events_handler"),
            {"op": "query", "id": [first_node.system_id], "level": "DEBUG"},
        )
        parsed_result = json_load_bytes(response.content)
        assert [first_event.id] == extract_event_ids(parsed_result)
        assert 1 == parsed_result["count"]

    def test_GET_query_with_nonexistent_id_returns_empty_list(self):
        # Trying to list events for a nonexistent node id returns a list
        # containing no nodes -- even if other (non-matching) nodes exist.
        node = factory.make_Node()
        make_events(node=node)
        existing_id = node.system_id
        nonexistent_id = existing_id + factory.make_string()
        response = self.client.get(
            reverse("events_handler"), {"op": "query", "id": [nonexistent_id]}
        )
        response_dict = json_load_bytes(response.content)
        assert response_dict.get("count") == 0
        assert response_dict.get("events") == []

    def test_GET_query_with_ids_orders_by_id_reverse(self):
        # Even when node ids are passed to "list," events for nodes are
        # returned in event id order, not necessarily in the order of the
        # node id arguments.
        self.user.is_superuser = True
        self.user.save()
        nodes = [factory.make_Node() for _ in range(3)]
        events = [factory.make_Event(node=node) for node in nodes]
        response = self.client.get(
            reverse("events_handler"),
            {
                "op": "query",
                "id": shuffled(node.system_id for node in nodes),
                "level": "DEBUG",
            },
        )
        parsed_result = json_load_bytes(response.content)
        assert [event.id for event in reversed(events)] == extract_event_ids(
            parsed_result
        )
        assert len(events) == parsed_result["count"]

    def test_GET_query_with_some_matching_ids_returns_matching_nodes(self):
        # If some nodes match the requested ids and some don't, only the
        # events matching nodes specified are returned.
        existing_node = factory.make_Node()
        existing_id = existing_node.system_id
        existing_events = make_events(node=existing_node)
        nonexistent_id = existing_id + factory.make_string()
        make_events()  # Some non-matching events.
        response = self.client.get(
            reverse("events_handler"),
            {
                "op": "query",
                "id": [existing_id, nonexistent_id],
                "level": "DEBUG",
            },
        )
        parsed_result = json_load_bytes(response.content)
        assert Counter([event.id for event in existing_events]) == Counter(
            extract_event_ids(parsed_result)
        )
        assert len(existing_events) == parsed_result["count"]

    def test_GET_query_with_hostname_returns_matching_nodes(self):
        # The list operation takes optional "hostname" parameters. Only events
        # for nodes with matching hostnames will be returned.
        nodes = [factory.make_Node() for _ in range(3)]
        events = [factory.make_Event(node=node) for node in nodes]
        first_node = nodes[0]
        first_event = events[0]  # Pertains to the first node.
        response = self.client.get(
            reverse("events_handler"),
            {
                "op": "query",
                "hostname": [first_node.hostname],
                "level": "DEBUG",
            },
        )
        parsed_result = json_load_bytes(response.content)
        assert [first_event.id] == extract_event_ids(parsed_result)
        assert 1 == parsed_result["count"]

    def test_GET_query_with_macs_returns_matching_nodes(self):
        # The "list" operation takes optional "mac_address" parameters. Only
        # events for nodes with matching MAC addresses will be returned.
        nodes = [
            factory.make_Node_with_Interface_on_Subnet() for _ in range(3)
        ]
        events = [factory.make_Event(node=node) for node in nodes]
        first_node = nodes[0]
        first_node_mac = first_node.get_boot_interface().mac_address
        first_event = events[0]  # Pertains to the first node.
        response = self.client.get(
            reverse("events_handler"),
            {"op": "query", "mac_address": [first_node_mac], "level": "DEBUG"},
        )
        parsed_result = json_load_bytes(response.content)
        assert [first_event.id] == extract_event_ids(parsed_result)
        assert 1 == parsed_result["count"]

    def test_GET_query_with_invalid_macs_returns_sensible_error(self):
        # If specifying an invalid MAC, make sure the error that's
        # returned is not a crazy stack trace, but something nice to
        # humans.
        bad_mac1 = "00:E0:81:DD:D1:ZZ"  # ZZ is bad.
        bad_mac2 = "00:E0:81:DD:D1:XX"  # XX is bad.
        node = factory.make_Node_with_Interface_on_Subnet()
        ok_mac = node.get_boot_interface().mac_address
        make_events(node=node)
        response = self.client.get(
            reverse("events_handler"),
            {
                "op": "query",
                "mac_address": [bad_mac1, bad_mac2, ok_mac],
                "level": "DEBUG",
            },
        )
        assert response.status_code == http.client.BAD_REQUEST
        assert (
            b"Invalid MAC address(es): 00:E0:81:DD:D1:ZZ, 00:E0:81:DD:D1:XX"
            in response.content
        )

    def test_GET_query_with_agent_name_filters_by_agent_name(self):
        agent_name1 = factory.make_name("agent-name")
        node1 = factory.make_Node(agent_name=agent_name1)
        node1_events = make_events(node=node1)

        agent_name2 = factory.make_name("agent-name")
        node2 = factory.make_Node(agent_name=agent_name2)
        make_events(node=node2)

        # Request events relating to node1's agent.
        response = self.client.get(
            reverse("events_handler"),
            {"op": "query", "agent_name": agent_name1, "level": "DEBUG"},
        )

        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)

        # Only events pertaining to node1 are returned.
        assert [
            event.id for event in reversed(node1_events)
        ] == extract_event_ids(parsed_result)
        assert parsed_result["count"] == len(node1_events)

    def test_GET_query_with_agent_name_filters_with_empty_string(self):
        node1 = factory.make_Node(agent_name="")
        node1_events = make_events(node=node1)

        node2 = factory.make_Node(agent_name=factory.make_name("agent-name"))
        make_events(node=node2)

        # Request events relating to node1's agent, the empty string.
        response = self.client.get(
            reverse("events_handler"),
            {"op": "query", "agent_name": "", "level": "DEBUG"},
        )

        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)

        # Only events pertaining to node1 are returned.
        assert [
            event.id for event in reversed(node1_events)
        ] == extract_event_ids(parsed_result)
        assert parsed_result["count"] == len(node1_events)

    def test_GET_query_without_agent_name_does_not_filter(self):
        nodes = [
            factory.make_Node(agent_name=factory.make_name("agent-name"))
            for _ in range(3)
        ]
        events = [factory.make_Event(node=node) for node in nodes]
        response = self.client.get(
            reverse("events_handler"), {"op": "query", "level": "DEBUG"}
        )
        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        assert [event.id for event in reversed(events)] == extract_event_ids(
            parsed_result
        )
        assert parsed_result["count"] == len(events)

    def test_GET_query_doesnt_list_devices(self):
        self.user.is_superuser = True
        self.user.save()
        machines = [
            factory.make_Node(
                agent_name=factory.make_name("agent-name"),
                node_type=NODE_TYPE.MACHINE,
            )
            for _ in range(3)
        ]
        for machine in machines:
            factory.make_Event(node=machine)

        # Create devices.
        devices = [factory.make_Device() for _ in range(3)]
        for device in devices:
            factory.make_Event(node=device)

        # Create rack controllers.
        rack_controllers = [
            factory.make_Node(
                agent_name=factory.make_name("agent-name"),
                node_type=NODE_TYPE.RACK_CONTROLLER,
            )
            for _ in range(3)
        ]
        for rack_controller in rack_controllers:
            factory.make_Event(node=rack_controller)

        response = self.client.get(
            reverse("events_handler"), {"op": "query", "level": "DEBUG"}
        )

        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        system_ids = {event["node"] for event in parsed_result["events"]}
        assert (
            system_ids.intersection(device.system_id for device in devices)
            == set()
        )
        assert len(machines) + len(rack_controllers) == parsed_result["count"]

    def test_GET_query_with_zone_filters_by_zone(self):
        zone1 = factory.make_Zone(name="zone1")
        node1 = factory.make_Node(zone=zone1)
        node1_events = make_events(node=node1)

        zone2 = factory.make_Zone(name="zone2")
        node2 = factory.make_Node(zone=zone2)
        make_events(node=node2)

        response = self.client.get(
            reverse("events_handler"),
            {"op": "query", "zone": zone1.name, "level": "DEBUG"},
        )
        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        assert [
            event.id for event in reversed(node1_events)
        ] == extract_event_ids(parsed_result)
        assert len(node1_events) == parsed_result["count"]

    def test_GET_query_with_limit_limits_with_most_recent_events(self):
        test_limit = randint(4, 8)
        events = make_events(test_limit + 1)
        response = self.client.get(
            reverse("events_handler"),
            {"op": "query", "limit": str(test_limit), "level": "DEBUG"},
        )
        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        assert [event.id for event in reversed(events)][
            :test_limit
        ] == extract_event_ids(parsed_result)
        assert test_limit == parsed_result["count"]

    def test_GET_query_with_limit_over_hard_limit_raises_error_with_msg(
        self, mocker
    ):
        artificial_limit = randint(4, 8)
        mocker.patch.object(
            events_module, "MAX_EVENT_LOG_COUNT", artificial_limit
        )
        test_limit = artificial_limit + 1
        make_events(test_limit)
        response = self.client.get(
            reverse("events_handler"),
            {"op": "query", "limit": str(test_limit)},
        )
        assert response.status_code == http.client.BAD_REQUEST
        assert (
            f"Requested number of events {test_limit} is greater than limit: "
            f"{artificial_limit}"
        ) in response.content.decode("utf-8")

    def test_GET_query_with_without_limit_limits_to_default_newest(
        self, mocker
    ):
        artificial_limit = randint(4, 8)
        mocker.patch.object(
            events_module, "DEFAULT_EVENT_LOG_LIMIT", artificial_limit
        )
        test_limit = artificial_limit + 1
        events = make_events(test_limit)
        response = self.client.get(
            reverse("events_handler"), {"op": "query", "level": "DEBUG"}
        )
        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        assert [event.id for event in reversed(events)][
            :artificial_limit
        ] == extract_event_ids(parsed_result)
        assert artificial_limit == parsed_result["count"]

    def test_GET_query_with_after_event_id_with_limit(self):
        events = make_events(5)
        response = self.client.get(
            reverse("events_handler"),
            {
                "op": "query",
                "after": str(events[1].id),
                "limit": "2",
                "level": "DEBUG",
            },
        )
        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        # Two events created AFTER events[1] are returned, newest first.
        assert [events[3].id, events[2].id] == extract_event_ids(parsed_result)
        assert 2 == parsed_result["count"]

    def test_GET_query_with_after_event_id_without_limit(self):
        events = make_events(6)
        response = self.client.get(
            reverse("events_handler"),
            {"op": "query", "after": str(events[2].id), "level": "DEBUG"},
        )
        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        # Three events created AFTER events[2] are returned, newest first.
        assert [
            event.id for event in reversed(events[3:])
        ] == extract_event_ids(parsed_result)
        assert 3 == parsed_result["count"]

    def test_GET_query_with_before_event_id_with_limit(self):
        events = make_events(5)
        response = self.client.get(
            reverse("events_handler"),
            {
                "op": "query",
                "before": str(events[3].id),
                "limit": "2",
                "level": "DEBUG",
            },
        )
        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        # Two events created BEFORE events[3] are returned, newest first.
        assert [events[2].id, events[1].id] == extract_event_ids(parsed_result)
        assert 2 == parsed_result["count"]

    def test_GET_query_with_before_event_id_without_limit(self):
        events = make_events(6)
        response = self.client.get(
            reverse("events_handler"),
            {"op": "query", "before": str(events[3].id), "level": "DEBUG"},
        )
        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        # Three events created BEFORE events[3] are returned, newest first.
        assert [events[2].id, events[1].id, events[0].id] == extract_event_ids(
            parsed_result
        )
        assert 3 == parsed_result["count"]

    def test_GET_query_with_invalid_log_level_raises_error_with_msg(self):
        make_events()
        invalid_level = factory.make_name("invalid_log_level")
        response = self.client.get(
            reverse("events_handler"), {"op": "query", "level": invalid_level}
        )
        assert response.status_code == http.client.BAD_REQUEST
        assert (
            f"Unrecognised log level: {invalid_level}"
            in response.content.decode("utf-8")
        )

    def test_GET_query_with_log_level_returns_that_level_and_greater(self):
        events = [
            make_events(type=factory.make_EventType(level=level))
            for level_name, level in self.log_levels
        ]

        for idx, (level_name, level) in enumerate(self.log_levels):  # noqa: B007
            response = self.client.get(
                reverse("events_handler"), {"op": "query", "level": level_name}
            )
            assert http.client.OK == response.status_code
            parsed_result = json_load_bytes(response.content)
            # Events of the same or higher level are returned.
            assert Counter(
                [event.id for event in chain.from_iterable(events[: idx + 1])]
            ) == Counter(extract_event_ids(parsed_result))

    def test_GET_query_with_default_log_level_is_info(self):
        for level_name, level in self.log_levels:  # noqa: B007
            make_events(type=factory.make_EventType(level=level))

        info_response = self.client.get(
            reverse("events_handler"), {"op": "query", "level": "INFO"}
        )
        assert http.client.OK == info_response.status_code
        info_result = json_load_bytes(info_response.content)

        default_response = self.client.get(
            reverse("events_handler"), {"op": "query"}
        )
        assert http.client.OK == default_response.status_code
        default_result = json_load_bytes(default_response.content)

        assert default_result["events"] == info_result["events"]

    def test_GET_query_with_log_level_AUDIT_returns_only_that_level(self):
        user = factory.make_User()
        node = factory.make_Node(owner=user)
        audit_description = "Testing audit events for '%(username)s'."
        generic_description = factory.make_name("desc")
        event1 = factory.make_Event(
            type=factory.make_EventType(level=AUDIT),
            user=user,
            description=audit_description,
        )
        factory.make_Event(
            type=factory.make_EventType(level=logging.DEBUG),
            node=node,
            user=user,
            description=generic_description,
        )

        response = self.client.get(
            reverse("events_handler"), {"op": "query", "level": "AUDIT"}
        )
        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)
        assert [event1.id] == extract_event_ids(parsed_result)

    def test_audit_query_filters_nodes(self):
        nodes = [factory.make_Node() for _ in range(3)]
        events = [
            factory.make_Event(
                node=node, type=factory.make_EventType(level=AUDIT)
            )
            for node in nodes
        ]
        first_node = nodes[0]
        first_event = events[0]  # Pertains to the first node.
        response = self.client.get(
            reverse("events_handler"),
            {
                "op": "query",
                "hostname": [first_node.hostname],
                "level": "AUDIT",
            },
        )
        parsed_result = json_load_bytes(response.content)
        assert [first_event.id] == extract_event_ids(parsed_result)
        assert 1 == parsed_result["count"]

    def test_GET_query_with_owner_returns_matching_events(self):
        # Only events for user will be returned
        user1 = factory.make_User()
        user2 = factory.make_User()
        nodes = [factory.make_Node(owner=user1) for _ in range(2)]
        events = [factory.make_Event(node=node, user=user1) for node in nodes]
        expected_event = factory.make_Event(user=user2)
        events.append(expected_event)
        response = self.client.get(
            reverse("events_handler"),
            {"op": "query", "level": "DEBUG", "owner": user2.username},
        )
        parsed_result = json_load_bytes(response.content)
        assert [expected_event.id] == extract_event_ids(parsed_result)
        assert 1 == parsed_result["count"]

    def test_GET_query_with_owner_after_delete_returns_matching_events(self):
        # Only events for user will be returned
        user1 = factory.make_User()
        user2 = factory.make_User()
        nodes = [factory.make_Node(owner=user1) for _ in range(2)]
        events = [factory.make_Event(node=node, user=user1) for node in nodes]
        expected_event = factory.make_Event(user=user2)
        user2_username = user2.username
        user2.delete()
        expected_event = reload_object(expected_event)
        events.append(expected_event)
        response = self.client.get(
            reverse("events_handler"),
            {"op": "query", "level": "DEBUG", "owner": user2_username},
        )
        parsed_result = json_load_bytes(response.content)
        assert [expected_event.id] == extract_event_ids(parsed_result)
        assert 1 == parsed_result["count"]

    def make_nodes_in_group_with_events(self, number_nodes=2, number_events=2):
        """Make `number_events` events for `number_nodes` nodes."""
        for _ in range(number_nodes):
            node = factory.make_Node(interface=True)
            make_events(number_events, node=node)

    def test_query_num_queries_is_independent_of_num_nodes_and_events(self):
        expected_queries = 1
        events_per_node = 5
        num_nodes_per_group = 5
        events_per_group = num_nodes_per_group * events_per_node

        self.make_nodes_in_group_with_events(
            num_nodes_per_group, events_per_node
        )

        handler = events_module.EventsHandler()

        query_1_count, query_1_result = count_queries(
            handler.query,
            RequestFixture({"op": "query", "level": "DEBUG"}, ["op", "level"]),
        )

        self.make_nodes_in_group_with_events(
            num_nodes_per_group, events_per_node
        )

        query_2_count, query_2_result = count_queries(
            handler.query,
            RequestFixture({"op": "query", "level": "DEBUG"}, ["op", "level"]),
        )

        # This check is to notify the developer that a change was made that
        # affects the number of queries performed when doing an event listing.
        # If this happens, consider your prefetching and adjust accordingly.
        assert events_per_group == int(query_1_result["count"])
        assert expected_queries == query_1_count, (
            "Number of queries has changed; make sure this is expected."
        )

        assert events_per_group * 2 == int(query_2_result["count"])
        assert query_1_count == query_2_count, (
            "Number of queries is not independent of the number of nodes."
        )


@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestEventsURIs:
    """Tests for next_uri and prev_uri in responses from /api/2.0/events/.

    These test a few specific combinations of arguments to test
    windowing/paging behaviour.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def check_uris(self, query, before, after):
        response = self.client.get(reverse("events_handler"), query)
        assert http.client.OK == response.status_code, response.content.decode(
            settings.DEFAULT_CHARSET
        )
        parsed_result = json_load_bytes(response.content)

        prev_uri = urlparse(parsed_result["prev_uri"])
        prev_uri_params = dict(parse_qsl(prev_uri.query))
        assert "before" in prev_uri_params
        assert str(before) == prev_uri_params["before"]
        assert "after" not in prev_uri_params

        next_uri = urlparse(parsed_result["next_uri"])
        next_uri_params = dict(parse_qsl(next_uri.query))
        assert "after" in next_uri_params
        assert str(after) == next_uri_params["after"]
        assert "before" not in next_uri_params

        return prev_uri_params, next_uri_params

    def test_GET_query_provides_prev_and_next_uris(self):
        event1, event2, event3 = make_events(3)
        query = {"op": "query", "level": "DEBUG"}
        self.check_uris(query, event1.id, event3.id)

    def test_GET_query_with_after_provides_prev_and_next_uris(self):
        event1, event2, event3 = make_events(3)
        query = {"op": "query", "after": str(event2.id), "level": "DEBUG"}
        self.check_uris(query, event3.id, event3.id)

    def test_GET_query_with_before_provides_prev_and_next_uris(self):
        event1, event2, event3 = make_events(3)
        query = {"op": "query", "before": str(event2.id), "level": "DEBUG"}
        self.check_uris(query, event1.id, event1.id)

    def test_GET_query_with_before_and_after_is_forbidden(self):
        query = {"op": "query", "before": "3", "after": "1"}
        response = self.client.get(reverse("events_handler"), query)
        assert http.client.BAD_REQUEST == response.status_code
        assert response.content.decode("utf-8") == (
            "There is undetermined behaviour when both `after` and `before` "
            "are specified."
        )

    def test_GET_prev_and_next_uris_contain_search_parameters(self):
        machine = factory.make_Machine(
            domain=factory.make_Domain(), zone=factory.make_Zone()
        )
        interface = factory.make_Interface(node=machine)
        machine.agent_name = factory.make_name("agent")
        machine.save()
        query = {
            "op": "query",
            "level": "DEBUG",
            # Node filtering parameters.
            "agent_name": machine.agent_name,
            "domain": machine.domain.name,
            "hostname": machine.hostname,
            "id": machine.system_id,
            "mac_address": interface.mac_address,
            "zone": machine.zone.name,
        }
        event = factory.make_Event(node=machine)
        prev_params, next_params = self.check_uris(query, event.id, event.id)
        assert prev_params.items() > query.items()
        assert next_params.items() > query.items()


# Parameters used in queries, excluding "op", which
# is a detail of MAAS's Web API machinery.
parameters = sorted(events_module.EventsHandler.all_params)
parameters.remove("op")


scenarios = tuple(
    ("-".join(params) or "no-params", params)
    for count in range(len(parameters) + 1)
    for params in combinations(parameters, count)
)


@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
@pytest.mark.parametrize(
    "params",
    [pytest.param(params, id=name) for name, params in scenarios],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestEventsURIsWithoutEvents:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_GET_query_prev_next_URIs_preserve_query_params(self, params):
        expected_uri_path = reverse("events_handler")

        # Build a query dict for the given combination of params.
        factories = {
            "after": lambda: str(randint(1, 6)),
            "agent_name": factory.make_string,
            "domain": factory.make_string,
            "hostname": factory.make_string,
            "id": factory.make_string,
            "level": lambda: random.choice(
                ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")
            ),
            "limit": lambda: str(randint(1, 6)),
            "mac_address": factory.make_mac_address,
            "zone": factory.make_string,
            "owner": factory.make_string,
        }
        request_params = {param: factories[param]() for param in params}

        # Ensure that op is always included.
        request_params["op"] = "query"

        response = self.client.get(reverse("events_handler"), request_params)

        assert http.client.OK == response.status_code, response.content.decode(
            settings.DEFAULT_CHARSET
        )

        parsed_result = json_load_bytes(response.content)

        # next_uri is always set because new matching events may be
        # logged at a later date.
        next_uri = urlparse(parsed_result["next_uri"])
        assert next_uri.scheme == ""
        assert next_uri.netloc == ""
        assert next_uri.params == ""
        assert next_uri.path == expected_uri_path
        assert next_uri.fragment == ""

        next_uri_params = dict(
            parse_qsl(next_uri.query, keep_blank_values=True)
        )
        if "before" in request_params:
            # The window was limited in the request by the presence of a
            # `before` argument, so the next_uri omits the `before` argument
            # and substitutes a related `after` argument.
            expected_params = request_params.copy()
            before = expected_params.pop("before")
            expected_params["after"] = str(int(before) - 1)
            assert expected_params == next_uri_params
        else:
            # Because we have not created any actual events in the database,
            # the next_uri has the same parameters as we already requested.
            assert request_params == next_uri_params

        # prev_uri is set when there MAY be older matching events, but
        # sometimes we can know there aren't any.
        if "after" in request_params:
            prev_uri = urlparse(parsed_result["prev_uri"])
            assert prev_uri.scheme == ""
            assert prev_uri.netloc == ""
            assert prev_uri.params == ""
            assert prev_uri.path == expected_uri_path
            assert prev_uri.fragment == ""
            prev_uri_params = dict(
                parse_qsl(prev_uri.query, keep_blank_values=True)
            )
            if "after" in request_params:
                # The window was limited in the request by the presence of an
                # `after` argument, so the prev_uri omits the `after` argument
                # and substitutes a related `before` argument.
                expected_params = request_params.copy()
                after = expected_params.pop("after")
                expected_params["before"] = str(int(after) + 1)
                assert expected_params == prev_uri_params
            else:
                # Because we have not created any actual test events, the
                # prev_uri has the same parameters as we already requested.
                assert request_params == prev_uri_params
        else:
            # Because we have not created any actual test events AND the
            # search window was not limited by `after`, we can be certain that
            # no older matching events exist, hence prev_uri is not provided.
            assert parsed_result["prev_uri"] is None
