# Copyright 2013-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from collections import Counter
import http.client
import json
from unittest.mock import ANY, call

from django.conf import settings
from django.urls import reverse
import pytest

from apiclient.creds import convert_tuple_to_string
from maascommon.events import AUDIT
from maasserver.enum import NODE_STATUS
from maasserver.models import Event, Node, Tag
from maasserver.models import node as node_module
from maasserver.models.node import generate_node_system_id
from maasserver.models.user import (
    create_auth_token,
    get_auth_tokens,
    get_creds_tuple,
)
from maasserver.testing.api import make_worker_client
from maasserver.testing.factory import factory
from maasserver.testing.testclient import MAASSensibleOAuthClient
from maasserver.utils.orm import reload_object
from maastesting.querycounter import count_queries
from provisioningserver.events import EVENT_TYPES
from tests.maasserver.api.test_nodes import RenderedNodesMixin
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


def get_json(client, path, params=None):
    response = client.get(path, params)
    assert response.status_code == http.client.OK, response.content
    return response.json()


def check_tagged_listing_like_details(client, tag, op):
    listing = get_json(
        client, reverse("tag_handler", args=[tag.name]), {"op": op}
    )
    assert listing != []
    for listed in listing:
        details = get_json(
            client, reverse("node_handler", args=[listed["system_id"]])
        )
        # Tags are rendered in database order, which isn't stable.
        details["tag_names"].sort()
        listed["tag_names"].sort()
        assert details == listed


def extract_system_ids(parsed_result):
    """List the system_ids of the machines in `parsed_result`."""
    return [machine.get("system_id") for machine in parsed_result]


def get_tag_uri(tag):
    """Get the API URI for `tag`."""
    return reverse("tag_handler", args=[tag.name])


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestTagAPI:
    """Tests for /api/2.0/tags/<tagname>/."""

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_handler_path(self):
        assert (
            reverse("tag_handler", args=["tag-name"])
            == "/MAAS/api/2.0/tags/tag-name/"
        )

    def test_DELETE_requires_admin(self):
        tag = factory.make_Tag()
        response = self.client.delete(get_tag_uri(tag))
        assert response.status_code == http.client.FORBIDDEN
        assert Counter([tag]) == Counter(Tag.objects.filter(id=tag.id))

    def test_DELETE_removes_tag(self):
        self.user.is_superuser = True
        self.user.save()
        tag = factory.make_Tag()
        response = self.client.delete(get_tag_uri(tag))
        assert response.status_code == http.client.NO_CONTENT
        assert not Tag.objects.filter(id=tag.id).exists()

    def test_DELETE_creates_event_log(self):
        self.user.is_superuser = True
        self.user.save()
        tag = factory.make_Tag()
        self.client.delete(get_tag_uri(tag))
        event = Event.objects.get(type__level=AUDIT)
        assert event.type.name == EVENT_TYPES.TAG
        assert event.description == f"Tag '{tag.name}' deleted."

    def test_DELETE_404(self):
        self.user.is_superuser = True
        self.user.save()
        url = reverse("tag_handler", args=["no-tag"])
        response = self.client.delete(url)
        assert response.status_code == http.client.NOT_FOUND

    def test_GET_returns_tag(self):
        # The api allows for fetching a single Node (using system_id).
        tag = factory.make_Tag("tag-name")
        url = reverse("tag_handler", args=["tag-name"])
        response = self.client.get(url)

        assert response.status_code == http.client.OK
        parsed_result = json.loads(response.content.decode("ascii"))
        assert tag.name == parsed_result["name"]
        assert tag.definition == parsed_result["definition"]
        assert tag.comment == parsed_result["comment"]

    def test_GET_refuses_to_access_nonexistent_node(self):
        # When fetching a Tag, the api returns a 'Not Found' (404) error
        # if no tag is found.
        url = reverse("tag_handler", args=["no-such-tag"])
        response = self.client.get(url)
        assert response.status_code == http.client.NOT_FOUND

    def test_PUT_refuses_non_superuser(self):
        tag = factory.make_Tag()
        response = self.client.put(
            get_tag_uri(tag), {"comment": "A special comment"}
        )
        assert response.status_code == http.client.FORBIDDEN

    def test_PUT_updates_tag(self):
        self.user.is_superuser = True
        self.user.save()
        tag = factory.make_Tag()
        # Note that 'definition' is not being sent
        response = self.client.put(
            get_tag_uri(tag),
            {"name": "new-tag-name", "comment": "A random comment"},
        )

        assert response.status_code == http.client.OK
        parsed_result = json.loads(response.content.decode("ascii"))
        assert parsed_result["name"] == "new-tag-name"
        assert parsed_result["comment"] == "A random comment"
        assert parsed_result["definition"] == tag.definition
        assert not Tag.objects.filter(name=tag.name).exists()
        assert Tag.objects.filter(name="new-tag-name").exists()

    def test_PUT_creates_event_log(self):
        self.user.is_superuser = True
        self.user.save()
        tag = factory.make_Tag()
        self.client.put(
            get_tag_uri(tag),
            {"comment": "A random comment"},
        )
        event = Event.objects.get(type__level=AUDIT)
        assert event.type.name == EVENT_TYPES.TAG
        assert event.description == f"Tag '{tag.name}' updated."

    def test_PUT_creates_event_log_rename(self):
        self.user.is_superuser = True
        self.user.save()
        tag = factory.make_Tag()
        old_name = tag.name
        new_name = factory.make_string()
        self.client.put(
            get_tag_uri(tag),
            {"name": new_name},
        )
        event = Event.objects.get(type__level=AUDIT)
        assert event.type.name == EVENT_TYPES.TAG
        assert (
            event.description == f"Tag '{old_name}' renamed to '{new_name}'."
        )

    def test_PUT_updates_node_associations(self, mocker):
        populate_nodes = mocker.patch.object(
            Tag, "populate_nodes", autospec=True
        )
        tag = Tag(name=factory.make_name("tag"), definition="//node/foo")
        tag.save()
        populate_nodes.assert_called_once_with(tag)
        self.user.is_superuser = True
        self.user.save()
        response = self.client.put(
            get_tag_uri(tag), {"definition": "//node/bar"}
        )
        assert response.status_code == http.client.OK
        assert populate_nodes.call_args_list == [call(tag), call(tag)]

    def test_GET_nodes_with_no_nodes(self):
        tag = factory.make_Tag()
        response = self.client.get(get_tag_uri(tag), {"op": "nodes"})

        assert response.status_code == http.client.OK
        parsed_result = json.loads(response.content.decode("ascii"))
        assert parsed_result == []

    def test_GET_nodes_returns_nodes(self):
        tag = factory.make_Tag()
        machine = factory.make_Node(owner=self.user)
        device = factory.make_Device(owner=self.user)
        rack = factory.make_RackController()
        region = factory.make_RegionController()
        # Create a second node that isn't tagged.
        factory.make_Node(owner=self.user)
        machine.tags.add(tag)
        device.tags.add(tag)
        rack.tags.add(tag)
        region.tags.add(tag)
        response = self.client.get(get_tag_uri(tag), {"op": "nodes"})

        assert response.status_code == http.client.OK
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert Counter([machine.system_id, device.system_id]) == Counter(
            r["system_id"] for r in parsed_result
        )

    def test_GET_nodes_query_count(self):
        tag = factory.make_Tag()

        query_counts = []
        node_counts = []

        vlan = factory.make_VLAN(space=factory.make_Space())
        machine = factory.make_Node_with_Interface_on_Subnet(vlan=vlan)
        machine.tags.add(tag)
        num_queries, response = count_queries(
            self.client.get, get_tag_uri(tag), {"op": "nodes"}
        )
        query_counts.append(num_queries)
        node_counts.append(len(response.json()))
        machine = factory.make_Node_with_Interface_on_Subnet()
        machine.tags.add(tag)
        num_queries, response = count_queries(
            self.client.get, get_tag_uri(tag), {"op": "nodes"}
        )
        query_counts.append(num_queries)
        node_counts.append(len(response.json()))
        machine = factory.make_Node_with_Interface_on_Subnet()
        machine.tags.add(tag)
        num_queries, response = count_queries(
            self.client.get, get_tag_uri(tag), {"op": "nodes"}
        )
        query_counts.append(num_queries)
        node_counts.append(len(response.json()))

        assert node_counts == [1, 2, 3]
        assert query_counts == [45, 45, 45]

    def test_GET_machines_returns_machines(self):
        tag = factory.make_Tag()
        machine = factory.make_Node()
        device = factory.make_Device()
        rack = factory.make_RackController()
        region = factory.make_RegionController()
        # Create a second node that isn't tagged.
        factory.make_Node()
        machine.tags.add(tag)
        device.tags.add(tag)
        rack.tags.add(tag)
        region.tags.add(tag)
        response = self.client.get(get_tag_uri(tag), {"op": "machines"})

        assert response.status_code == http.client.OK
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert [machine.system_id] == [r["system_id"] for r in parsed_result]

    def test_GET_machines_query_count(self):
        tag = factory.make_Tag()

        query_counts = []
        machine_counts = []

        # Pin the first machine's VLAN to a known Space. Otherwise
        # `make_Node_with_Interface_on_Subnet` randomises whether the
        # VLAN gets a Space (`make_Subnet(space=RANDOM_OR_NONE)`), and
        # the bulk VLAN/Space prefetch in `_prepare_vlans` only issues
        # its query once a Space actually needs loading, making the
        # query count depend on that coin flip.
        vlan = factory.make_VLAN(space=factory.make_Space())
        machine = factory.make_Node_with_Interface_on_Subnet(vlan=vlan)
        machine.tags.add(tag)
        num_queries, response = count_queries(
            self.client.get, get_tag_uri(tag), {"op": "machines"}
        )
        query_counts.append(num_queries)
        machine_counts.append(len(response.json()))
        machine = factory.make_Node_with_Interface_on_Subnet()
        machine.tags.add(tag)
        num_queries, response = count_queries(
            self.client.get, get_tag_uri(tag), {"op": "machines"}
        )
        query_counts.append(num_queries)
        machine_counts.append(len(response.json()))
        machine = factory.make_Node_with_Interface_on_Subnet()
        machine.tags.add(tag)
        num_queries, response = count_queries(
            self.client.get, get_tag_uri(tag), {"op": "machines"}
        )
        query_counts.append(num_queries)
        machine_counts.append(len(response.json()))

        assert machine_counts == [1, 2, 3]
        assert query_counts == [45, 45, 45]

    def test_GET_devices_returns_devices(self):
        tag = factory.make_Tag()
        machine = factory.make_Node(owner=self.user)
        device = factory.make_Device(owner=self.user)
        rack = factory.make_RackController()
        region = factory.make_RegionController()
        # Create a second node that isn't tagged.
        factory.make_Node(owner=self.user)
        machine.tags.add(tag)
        device.tags.add(tag)
        rack.tags.add(tag)
        region.tags.add(tag)
        response = self.client.get(get_tag_uri(tag), {"op": "devices"})

        assert response.status_code == http.client.OK
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert [device.system_id] == [r["system_id"] for r in parsed_result]

    def test_GET_devices_query_count(self):
        tag = factory.make_Tag()
        for _ in range(3):
            device = factory.make_Device(owner=self.user)
            device.tags.add(tag)
        num_queries1, response1 = count_queries(
            self.client.get, get_tag_uri(tag), {"op": "devices"}
        )

        for _ in range(3):
            device = factory.make_Device(owner=self.user)
            device.tags.add(tag)
        num_queries2, response2 = count_queries(
            self.client.get, get_tag_uri(tag), {"op": "devices"}
        )

        # Make sure the responses are ok as it's not useful to compare the
        # number of queries if they are not.
        parsed_result_1 = json.loads(
            response1.content.decode(settings.DEFAULT_CHARSET)
        )
        parsed_result_2 = json.loads(
            response2.content.decode(settings.DEFAULT_CHARSET)
        )
        assert [
            response1.status_code,
            response2.status_code,
            len(extract_system_ids(parsed_result_1)),
            len(extract_system_ids(parsed_result_2)),
        ] == [http.client.OK, http.client.OK, 3, 6]
        assert num_queries1 == num_queries2

    def test_GET_rack_controllers_returns_rack_controllers(self):
        self.user.is_superuser = True
        self.user.save()
        tag = factory.make_Tag()
        machine = factory.make_Node()
        device = factory.make_Device()
        rack = factory.make_RackController()
        region = factory.make_RegionController()
        # Create a second node that isn't tagged.
        factory.make_Node()
        machine.tags.add(tag)
        device.tags.add(tag)
        rack.tags.add(tag)
        region.tags.add(tag)
        response = self.client.get(
            get_tag_uri(tag), {"op": "rack_controllers"}
        )

        assert response.status_code == http.client.OK
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert [rack.system_id] == [r["system_id"] for r in parsed_result]

    @pytest.mark.skip(reason="XXX: ltrager 2019-11-29 bug=1854546")
    def test_GET_rack_controllers_query_count(self):
        self.user.is_superuser = True
        self.user.save()

        tag = factory.make_Tag()
        for _ in range(3):
            rack = factory.make_RackController()
            rack.tags.add(tag)
        num_queries1, response1 = count_queries(
            self.client.get, get_tag_uri(tag), {"op": "rack_controllers"}
        )

        for _ in range(3):
            rack = factory.make_RackController()
            rack.tags.add(tag)
        num_queries2, response2 = count_queries(
            self.client.get, get_tag_uri(tag), {"op": "rack_controllers"}
        )

        # Make sure the responses are ok as it's not useful to compare the
        # number of queries if they are not.
        parsed_result_1 = json.loads(
            response1.content.decode(settings.DEFAULT_CHARSET)
        )
        parsed_result_2 = json.loads(
            response2.content.decode(settings.DEFAULT_CHARSET)
        )
        assert [
            response1.status_code,
            response2.status_code,
            len(extract_system_ids(parsed_result_1)),
            len(extract_system_ids(parsed_result_2)),
        ] == [http.client.OK, http.client.OK, 3, 6]
        assert num_queries1 == num_queries2 - (3 * 3)

    def test_GET_rack_controllers_returns_no_rack_controllers_nonadmin(self):
        tag = factory.make_Tag()
        machine = factory.make_Node()
        device = factory.make_Device()
        rack = factory.make_RackController()
        region = factory.make_RegionController()
        # Create a second node that isn't tagged.
        factory.make_Node()
        machine.tags.add(tag)
        device.tags.add(tag)
        rack.tags.add(tag)
        region.tags.add(tag)
        response = self.client.get(
            get_tag_uri(tag), {"op": "rack_controllers"}
        )

        assert response.status_code == http.client.OK
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert parsed_result == []

    def test_GET_region_controllers_returns_region_controllers(self):
        self.user.is_superuser = True
        self.user.save()
        tag = factory.make_Tag()
        machine = factory.make_Node()
        device = factory.make_Device()
        rack = factory.make_RackController()
        region = factory.make_RegionController()
        # Create a second node that isn't tagged.
        factory.make_Node()
        machine.tags.add(tag)
        device.tags.add(tag)
        rack.tags.add(tag)
        region.tags.add(tag)
        response = self.client.get(
            get_tag_uri(tag), {"op": "region_controllers"}
        )

        assert response.status_code == http.client.OK
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert [region.system_id] == [r["system_id"] for r in parsed_result]

    def test_GET_region_controllers_query_count(self):
        self.user.is_superuser = True
        self.user.save()

        tag = factory.make_Tag()
        # Pin a Space so the VLAN/Space prefetch query always runs, see
        # `test_GET_machines_query_count`.
        vlan = factory.make_VLAN(space=factory.make_Space())
        for _ in range(3):
            region = factory.make_RegionController(vlan=vlan)
            region.tags.add(tag)
        num_queries1, response1 = count_queries(
            self.client.get,
            get_tag_uri(tag),
            {"op": "region_controllers"},
        )

        for _ in range(3):
            region = factory.make_RegionController()
            region.tags.add(tag)
        num_queries2, response2 = count_queries(
            self.client.get,
            get_tag_uri(tag),
            {"op": "region_controllers"},
        )

        # Make sure the responses are ok as it's not useful to compare the
        # number of queries if they are not.
        parsed_result_1 = json.loads(
            response1.content.decode(settings.DEFAULT_CHARSET)
        )
        parsed_result_2 = json.loads(
            response2.content.decode(settings.DEFAULT_CHARSET)
        )
        assert [
            response1.status_code,
            response2.status_code,
            len(extract_system_ids(parsed_result_1)),
            len(extract_system_ids(parsed_result_2)),
        ] == [http.client.OK, http.client.OK, 3, 6]
        assert num_queries1 == num_queries2

    def test_GET_region_controllers_returns_no_controllers_nonadmin(self):
        tag = factory.make_Tag()
        machine = factory.make_Node()
        device = factory.make_Device()
        rack = factory.make_RackController()
        region = factory.make_RegionController()
        # Create a second node that isn't tagged.
        factory.make_Node()
        machine.tags.add(tag)
        device.tags.add(tag)
        rack.tags.add(tag)
        region.tags.add(tag)
        response = self.client.get(
            get_tag_uri(tag), {"op": "region_controllers"}
        )

        assert response.status_code == http.client.OK
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert parsed_result == []

    def test_GET_nodes_hides_invisible_nodes(self):
        user2 = factory.make_User()
        node1 = factory.make_Node()
        node2 = factory.make_Node(status=NODE_STATUS.ALLOCATED, owner=user2)
        tag = factory.make_Tag()
        node1.tags.add(tag)
        node2.tags.add(tag)

        response = self.client.get(get_tag_uri(tag), {"op": "nodes"})

        assert response.status_code == http.client.OK
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert [node1.system_id] == [r["system_id"] for r in parsed_result]
        # The other user can also see his node
        client2 = MAASSensibleOAuthClient(user2)
        response = client2.get(get_tag_uri(tag), {"op": "nodes"})
        assert response.status_code == http.client.OK
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert Counter([node1.system_id, node2.system_id]) == Counter(
            r["system_id"] for r in parsed_result
        )

    def test_PUT_invalid_definition(self):
        self.user.is_superuser = True
        self.user.save()
        node = factory.make_Node()
        tag = factory.make_Tag(definition="//child")
        node.tags.add(tag)
        assert node.tag_names() == [tag.name]
        response = self.client.put(
            get_tag_uri(tag),
            {"name": "bad tag", "definition": "invalid::tag"},
        )

        assert response.status_code == http.client.BAD_REQUEST
        # The tag should not be modified
        tag = reload_object(tag)
        assert node.tag_names() == [tag.name]
        assert tag.definition == "//child"

    def test_POST_update_nodes_unknown_tag(self):
        self.user.is_superuser = True
        self.user.save()
        name = factory.make_name()
        response = self.client.post(
            reverse("tag_handler", args=[name]), {"op": "update_nodes"}
        )
        assert response.status_code == http.client.NOT_FOUND
        # check we have a verbose output
        assert (
            response.content.decode(settings.DEFAULT_CHARSET)
            == "No Tag matches the given query."
        )

    def test_POST_update_nodes_changes_associations(self):
        tag = factory.make_Tag()
        self.user.is_superuser = True
        self.user.save()
        node_first = factory.make_Node()
        node_second = factory.make_Node()
        node_first.tags.add(tag)
        assert Counter([node_first]) == Counter(tag.node_set.all())
        response = self.client.post(
            get_tag_uri(tag),
            {
                "op": "update_nodes",
                "add": [node_second.system_id],
                "remove": [node_first.system_id],
            },
        )
        assert response.status_code == http.client.OK
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert Counter([node_second]) == Counter(tag.node_set.all())
        assert parsed_result == {"added": 1, "removed": 1}

    def test_POST_update_nodes_ignores_unknown_nodes(self):
        tag = factory.make_Tag()
        self.user.is_superuser = True
        self.user.save()
        unknown_add_system_id = generate_node_system_id()
        unknown_remove_system_id = generate_node_system_id()
        assert Counter([]) == Counter(tag.node_set.all())
        response = self.client.post(
            get_tag_uri(tag),
            {
                "op": "update_nodes",
                "add": [unknown_add_system_id],
                "remove": [unknown_remove_system_id],
            },
        )
        assert response.status_code == http.client.OK
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert Counter([]) == Counter(tag.node_set.all())
        assert parsed_result == {"added": 0, "removed": 0}

    def test_POST_update_nodes_doesnt_require_add_or_remove(self):
        tag = factory.make_Tag()
        node = factory.make_Node()
        self.user.is_superuser = True
        self.user.save()
        assert Counter([]) == Counter(tag.node_set.all())
        response = self.client.post(
            get_tag_uri(tag),
            {"op": "update_nodes", "add": [node.system_id]},
        )
        assert response.status_code == http.client.OK
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert parsed_result == {"added": 1, "removed": 0}
        response = self.client.post(
            get_tag_uri(tag),
            {"op": "update_nodes", "remove": [node.system_id]},
        )
        assert response.status_code == http.client.OK
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert parsed_result == {"added": 0, "removed": 1}

    def test_POST_update_nodes_rejects_normal_user(self):
        tag = factory.make_Tag()
        node = factory.make_Node()
        response = self.client.post(
            get_tag_uri(tag),
            {"op": "update_nodes", "add": [node.system_id]},
        )
        assert response.status_code == http.client.FORBIDDEN
        assert Counter([]) == Counter(tag.node_set.all())

    def test_POST_update_nodes_allows_rack_controller(self):
        tag = factory.make_Tag()
        rack_controller = factory.make_RackController()
        node = factory.make_Node()
        client = make_worker_client(rack_controller)
        tokens = list(get_auth_tokens(rack_controller.owner))
        if len(tokens) > 0:
            # Use the latest token.
            token = tokens[-1]
        else:
            token = create_auth_token(rack_controller.owner)
        token.save()
        creds = convert_tuple_to_string(get_creds_tuple(token))
        response = client.post(
            get_tag_uri(tag),
            {
                "op": "update_nodes",
                "add": [node.system_id],
                "rack_controller": rack_controller.system_id,
                "credentials": creds,
            },
        )
        assert response.status_code == http.client.OK
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert parsed_result == {"added": 1, "removed": 0}
        assert Counter([node]) == Counter(tag.node_set.all())

    def test_POST_update_nodes_refuses_non_rack_controller(self):
        tag = factory.make_Tag()
        rack_controller = factory.make_RackController()
        node = factory.make_Node()
        token = create_auth_token(rack_controller.owner)
        token.save()
        creds = convert_tuple_to_string(get_creds_tuple(token))
        response = self.client.post(
            get_tag_uri(tag),
            {
                "op": "update_nodes",
                "add": [node.system_id],
                "rack_controller": rack_controller.system_id,
                "credentials": creds,
            },
        )
        assert response.status_code == http.client.FORBIDDEN
        assert Counter([]) == Counter(tag.node_set.all())

    def test_POST_update_nodes_refuses_no_token(self):
        tag = factory.make_Tag()
        rack_controller = factory.make_RackController()
        node = factory.make_Node()
        # create a token for a different user
        token = create_auth_token(factory.make_User())
        token.save()
        creds = convert_tuple_to_string(get_creds_tuple(token))
        response = self.client.post(
            get_tag_uri(tag),
            {
                "op": "update_nodes",
                "add": [node.system_id],
                "rack_controller": rack_controller.system_id,
                "credentials": creds,
            },
        )
        assert response.status_code == http.client.FORBIDDEN
        assert Counter([]) == Counter(tag.node_set.all())

    def test_POST_update_nodes_ignores_incorrect_definition(self):
        tag = factory.make_Tag()
        orig_def = tag.definition
        rack_controller = factory.make_RackController()
        node = factory.make_Node()
        client = make_worker_client(rack_controller)
        tag.definition = "//new/node/definition"
        tag.save(populate=False)
        response = client.post(
            get_tag_uri(tag),
            {
                "op": "update_nodes",
                "add": [node.system_id],
                "rack_controller": rack_controller.system_id,
                "definition": orig_def,
            },
        )
        assert response.status_code == http.client.CONFLICT
        assert Counter([]) == Counter(tag.node_set.all())
        assert Counter([]) == Counter(node.tags.all())

    def test_POST_rebuild_rebuilds_node_mapping(self, mocker):
        populate_nodes = mocker.patch.object(
            Tag, "populate_nodes", autospec=True
        )
        tag = Tag(name=factory.make_name("tag"), definition="//foo/bar")
        tag.save()
        self.user.is_superuser = True
        self.user.save()
        populate_nodes.assert_called_once_with(tag)
        response = self.client.post(get_tag_uri(tag), {"op": "rebuild"})
        assert response.status_code == http.client.OK
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert parsed_result == {"rebuilding": tag.name}
        assert populate_nodes.call_args_list == [call(tag), call(tag)]

    def test_POST_rebuild_leaves_manual_tags(self):
        tag = factory.make_Tag(definition="")
        node = factory.make_Node()
        node.tags.add(tag)
        assert Counter([node]) == Counter(tag.node_set.all())
        self.user.is_superuser = True
        self.user.save()
        response = self.client.post(get_tag_uri(tag), {"op": "rebuild"})
        assert response.status_code == http.client.OK
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert parsed_result == {"rebuilding": tag.name}
        assert Counter([node]) == Counter(tag.node_set.all())

    def test_POST_rebuild_unknown_404(self):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.post(
            reverse("tag_handler", args=["unknown-tag"]), {"op": "rebuild"}
        )
        assert response.status_code == http.client.NOT_FOUND

    def test_POST_rebuild_requires_admin(self):
        tag = factory.make_Tag(definition="/foo/bar")
        response = self.client.post(get_tag_uri(tag), {"op": "rebuild"})
        assert response.status_code == http.client.FORBIDDEN


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestTagsAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_handler_path(self):
        assert reverse("tags_handler") == "/MAAS/api/2.0/tags/"

    def test_GET_list_without_tags_returns_empty_list(self):
        response = self.client.get(reverse("tags_handler"))
        assert (
            json.loads(response.content.decode(settings.DEFAULT_CHARSET)) == []
        )

    def test_POST_new_refuses_non_admin(self):
        name = factory.make_string()
        response = self.client.post(
            reverse("tags_handler"),
            {
                "name": name,
                "comment": factory.make_string(),
                "definition": factory.make_string(),
            },
        )
        assert response.status_code == http.client.FORBIDDEN
        assert not Tag.objects.filter(name=name).exists()

    def test_POST_new_creates_tag(self, mocker):
        populate_nodes = mocker.patch.object(
            Tag, "populate_nodes", autospec=True
        )
        self.user.is_superuser = True
        self.user.save()
        name = factory.make_string()
        definition = "//node"
        comment = factory.make_string()
        response = self.client.post(
            reverse("tags_handler"),
            {"name": name, "comment": comment, "definition": definition},
        )
        assert response.status_code == http.client.OK
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert parsed_result["name"] == name
        assert parsed_result["comment"] == comment
        assert parsed_result["definition"] == definition
        assert Tag.objects.filter(name=name).exists()
        populate_nodes.assert_called_once_with(ANY)

    def test_POST_creates_event_log(self, mocker):
        mocker.patch.object(Tag, "populate_nodes", autospec=True)
        self.user.is_superuser = True
        self.user.save()
        name = factory.make_string()
        self.client.post(reverse("tags_handler"), {"name": name})
        event = Event.objects.get(type__level=AUDIT)
        assert event.type.name == EVENT_TYPES.TAG
        assert event.description == f"Tag '{name}' created."

    def test_POST_new_without_definition_creates_tag(self):
        self.user.is_superuser = True
        self.user.save()
        name = factory.make_string()
        comment = factory.make_string()
        response = self.client.post(
            reverse("tags_handler"), {"name": name, "comment": comment}
        )
        assert response.status_code == http.client.OK
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert parsed_result["name"] == name
        assert parsed_result["comment"] == comment
        assert parsed_result["definition"] == ""
        assert Tag.objects.filter(name=name).exists()

    def test_POST_new_invalid_tag_name(self):
        self.user.is_superuser = True
        self.user.save()
        # We do not check the full possible set of invalid names here, a more
        # thorough check is done in test_tag, we just check that we get a
        # reasonable error here.
        invalid = "invalid:name"
        definition = "//node"
        comment = factory.make_string()
        response = self.client.post(
            reverse("tags_handler"),
            {"name": invalid, "comment": comment, "definition": definition},
        )
        assert response.status_code == http.client.BAD_REQUEST, (
            "We did not get BAD_REQUEST for an invalid tag name: %r"
            % (invalid,)
        )
        assert not Tag.objects.filter(name=invalid).exists()

    def test_POST_new_kernel_opts(self, mocker):
        populate_nodes = mocker.patch.object(
            Tag, "populate_nodes", autospec=True
        )
        self.user.is_superuser = True
        self.user.save()
        name = factory.make_string()
        definition = "//node"
        comment = factory.make_string()
        extra_kernel_opts = factory.make_string()
        response = self.client.post(
            reverse("tags_handler"),
            {
                "name": name,
                "comment": comment,
                "definition": definition,
                "kernel_opts": extra_kernel_opts,
            },
        )
        assert response.status_code == http.client.OK
        parsed_result = json.loads(
            response.content.decode(settings.DEFAULT_CHARSET)
        )
        assert parsed_result["name"] == name
        assert parsed_result["comment"] == comment
        assert parsed_result["definition"] == definition
        assert parsed_result["kernel_opts"] == extra_kernel_opts
        assert (
            Tag.objects.filter(name=name)[0].kernel_opts == extra_kernel_opts
        )
        populate_nodes.assert_called_once_with(ANY)

    def test_POST_new_populates_nodes(self, mocker):
        populate_nodes = mocker.patch.object(
            Tag, "populate_nodes", autospec=True
        )
        self.user.is_superuser = True
        self.user.save()
        name = factory.make_string()
        definition = "//node/child"
        comment = factory.make_string()
        response = self.client.post(
            reverse("tags_handler"),
            {"name": name, "comment": comment, "definition": definition},
        )
        assert response.status_code == http.client.OK
        populate_nodes.assert_called_once_with(ANY)
        # The tag passed to populate_nodes() is the one created above.
        [tag], _ = populate_nodes.call_args
        assert tag.name == name
        assert tag.comment == comment
        assert tag.definition == definition


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestTagsOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_create_requires_can_edit_global_permissions(self, mocker):
        self.openfga_client.can_edit_global_entities.return_value = True
        mocker.patch.object(Tag, "populate_nodes", autospec=True)
        name = factory.make_string()
        response = self.client.post(
            reverse("tags_handler"),
            {
                "name": name,
                "comment": factory.make_string(),
                "definition": "//node/child",
            },
        )
        assert response.status_code == http.client.OK, response.content
        self.openfga_client.can_edit_global_entities.assert_called_once_with(
            self.user
        )


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestTagOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_update_requires_can_edit_global_permissions(self):
        self.openfga_client.can_edit_global_entities.return_value = True
        tag = factory.make_Tag()
        response = self.client.put(
            get_tag_uri(tag),
            {"name": "new-tag-name", "comment": "A random comment"},
        )
        assert response.status_code == http.client.OK
        self.openfga_client.can_edit_global_entities.assert_called_once_with(
            self.user
        )

    def test_rebuild_requires_can_edit_global_permissions(self):
        self.openfga_client.can_edit_global_entities.return_value = True
        tag = factory.make_Tag(definition="")
        response = self.client.post(get_tag_uri(tag), {"op": "rebuild"})
        assert response.status_code == http.client.OK
        self.openfga_client.can_edit_global_entities.assert_called_once_with(
            self.user
        )

    def test_update_nodes_requires_can_edit_global_permissions(self):
        self.openfga_client.can_edit_global_entities.return_value = True
        tag = factory.make_Tag(definition="")
        response = self.client.post(get_tag_uri(tag), {"op": "update_nodes"})
        assert response.status_code == http.client.OK
        self.openfga_client.can_edit_global_entities.assert_called_once_with(
            self.user
        )

    def test_delete_requires_can_edit_global_permissions(self):
        self.openfga_client.can_edit_global_entities.return_value = True
        tag = factory.make_Tag()
        response = self.client.delete(get_tag_uri(tag))
        assert response.status_code == http.client.NO_CONTENT
        self.openfga_client.can_edit_global_entities.assert_called_once_with(
            self.user
        )


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("admin", id="user=admin,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestTagNodesListingsMatchDetails(RenderedNodesMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, admin, admin_api_client, mocker):
        assert api_identity == "admin"
        self.user = admin
        self.client = admin_api_client
        mocker.patch.object(node_module, "stop_workflow")
        RenderedNodesMixin.setup_rendered_nodes(self, mocker)
        self.make_nodes()
        self.tag = factory.make_Tag()
        for node in Node.objects.all():
            node.tags.add(self.tag)

    def test_GET_nodes(self):
        check_tagged_listing_like_details(self.client, self.tag, "nodes")

    def test_GET_machines(self):
        check_tagged_listing_like_details(self.client, self.tag, "machines")

    def test_GET_devices(self):
        check_tagged_listing_like_details(self.client, self.tag, "devices")

    def test_GET_rack_controllers(self):
        check_tagged_listing_like_details(
            self.client, self.tag, "rack_controllers"
        )

    def test_GET_region_controllers(self):
        check_tagged_listing_like_details(
            self.client, self.tag, "region_controllers"
        )
