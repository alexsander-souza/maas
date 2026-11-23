# Copyright 2013-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the utilities of the per-tenant file storage work."""

from django.urls import reverse
import pytest

from maasserver.support.pertenant.utils import (
    extract_bootstrap_node_system_id,
    get_bootstrap_node_owner,
    PROVIDER_STATE_FILENAME,
)
from maasserver.testing.factory import factory
from maastesting.utils import sample_binary_data


def make_provider_state_file(node=None):
    """Create a 'provider-state' file with a reference (zookeeper-instances)
    to a node.
    """
    if node is None:
        node = factory.make_Node()
    node_link = reverse("node_handler", args=[node.system_id])
    content = "zookeeper-instances: [%s]\n" % node_link
    content_data = content.encode("ascii")
    return factory.make_FileStorage(
        filename=PROVIDER_STATE_FILENAME, content=content_data, owner=None
    )


@pytest.mark.usefixtures(
    "maasdb",
    "maas_region_test",
    "factory",
    "mock_openfga",
    "mock_start_workflows",
)
class TestExtractBootstrapNodeSystemId:
    def test_parses_valid_provider_state_file(self):
        node = factory.make_Node()
        provider_state_file = make_provider_state_file(node=node)
        system_id = extract_bootstrap_node_system_id(
            provider_state_file.content
        )
        assert system_id == node.system_id

    def test_returns_None_if_parsing_fails(self):
        invalid_contents = [
            "%",  # invalid yaml
            sample_binary_data,  # binary content (invalid yaml)
            "invalid content",  # invalid provider-state content
            "zookeeper-instances: []",  # no instances listed
        ]
        for invalid_content in invalid_contents:
            assert extract_bootstrap_node_system_id(invalid_content) is None


@pytest.mark.usefixtures(
    "maasdb",
    "maas_region_test",
    "factory",
    "mock_openfga",
    "mock_start_workflows",
)
class TestGetBootstrapNodeOwner:
    def test_returns_None_if_no_provider_state_file(self):
        assert get_bootstrap_node_owner() is None

    def test_returns_owner_if_node_found(self):
        node = factory.make_Node(owner=factory.make_User())
        make_provider_state_file(node=node)
        assert node.owner == get_bootstrap_node_owner()

    def test_returns_None_if_node_does_not_exist(self):
        node = factory.make_Node(owner=factory.make_User())
        make_provider_state_file(node=node)
        node.delete()
        assert get_bootstrap_node_owner() is None

    def test_returns_None_if_invalid_yaml(self):
        invalid_content = b"%"
        factory.make_FileStorage(
            filename=PROVIDER_STATE_FILENAME, content=invalid_content
        )
        assert get_bootstrap_node_owner() is None
