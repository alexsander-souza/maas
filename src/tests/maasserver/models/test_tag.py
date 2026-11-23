# Copyright 2012-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from unittest.mock import ANY, Mock

from django.core.exceptions import ValidationError
import pytest

from maasserver import populate_tags
from maasserver.models import tag as tag_module
from maasserver.models.tag import Tag
from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestTag:
    def test_factory_make_Tag(self):
        """The generated system_id looks good."""
        tag = factory.make_Tag("tag-name", "//node[@id=display]")
        assert tag.name == "tag-name"
        assert tag.definition == "//node[@id=display]"
        assert tag.comment == ""
        assert tag.kernel_opts == ""
        assert tag.updated is not None
        assert tag.created is not None

    def test_factory_make_Tag_with_hardware_details(self):
        tag = factory.make_Tag("a-tag", "true", kernel_opts="console=ttyS0")
        assert tag.name == "a-tag"
        assert tag.definition == "true"
        assert tag.comment == ""
        assert tag.kernel_opts == "console=ttyS0"
        assert tag.updated is not None
        assert tag.created is not None

    def test_add_tag_to_node(self):
        node = factory.make_Node()
        tag = factory.make_Tag()
        tag.save()
        node.tags.add(tag)
        assert [t.id for t in node.tags.all()] == [tag.id]
        assert [n.id for n in tag.node_set.all()] == [node.id]

    def test_valid_tag_names(self):
        for valid in ["valid-dash", "under_score", "long" * 50]:
            tag = factory.make_Tag(name=valid)
            assert tag.name == valid

    def test_validate_traps_invalid_tag_name(self):
        for invalid in [
            "invalid:name",
            "no spaces",
            "no\ttabs",
            "no&ampersand",
            "no!shouting",
            "",
            "too-long" * 33,
            "\xb5",
        ]:
            with pytest.raises(ValidationError):
                factory.make_Tag(name=invalid)

    def test_validate_traps_invalid_tag_definitions(self):
        with pytest.raises(ValidationError):
            factory.make_Tag(definition="invalid::definition")

    def test_applies_tags_to_nodes_on_save(self, mocker):
        populate_nodes = mocker.patch.object(
            Tag, "populate_nodes", autospec=True
        )
        tag = Tag(name=factory.make_name("tag"), definition="//node/child")
        populate_nodes.assert_not_called()
        tag.save()
        populate_nodes.assert_called_once_with(tag)

    def test_will_not_save_invalid_xpath(self):
        tag = factory.make_Tag(definition="//node/foo")
        tag.definition = "invalid::tag"
        with pytest.raises(ValidationError):
            tag.save()


@pytest.mark.parametrize(
    "definition,expected",
    [("", False), ("   \t\n ", False), ("//node", True)],
    ids=["empty", "whitespace", "defined"],
)
@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestTagIsDefined:
    """Tests for the `Tag.is_defined` property."""

    def test_is_defined(self, definition, expected):
        tag = Tag(name="tag", definition=definition)
        assert tag.is_defined is expected


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestTagPopulateNodesLater:
    def test_tag_is_populated_when_tag_is_defined(self, mocker):
        mock_reactor = mocker.patch.object(tag_module, "reactor")
        mock_reactor.callLater = Mock()
        tag_1 = Tag(name=factory.make_name("tag_1"), definition="//foo")
        tag_2 = Tag(name=factory.make_name("tag_2"), definition="//foo")

        # when tag is saved with populate=False, and the tag is defined (not
        # empty or different in case of updating the tag)
        tag_1.save(populate=False)
        # then the tag evaluation does get triggered
        mock_reactor.callLater.assert_not_called()

        # when tag is saved with populate=True, and the tag is defined (not
        # empty or different in case of updating the tag)
        tag_2.save()
        # then the tag evaluation gets triggered
        assert tag_2.is_defined
        mock_reactor.callLater.assert_called_once()

    def test_does_nothing_if_tag_is_not_defined(self, mocker):
        mock_reactor = mocker.patch.object(tag_module, "reactor")
        mock_reactor.callLater = Mock()
        tag = Tag(name=factory.make_name("tag"), definition="")

        # when tag is saved with populate=False, and the tag is not defined
        # (empty or the same definition in case of updating the tag)
        tag.save(populate=False)

        # then the tag evaluation does not get triggered
        assert not tag.is_defined
        mock_reactor.callLater.assert_not_called()
        tag._populate_nodes_later()
        mock_reactor.callLater.assert_not_called()

    def test_does_not_clear_node_set_before_populating(self, mocker):
        mock_reactor = mocker.patch.object(tag_module, "reactor")
        mock_reactor.callLater = Mock()
        tag = Tag(name=factory.make_name("tag"), definition="//foo")

        tag.save(populate=False)

        nodes = [factory.make_Node() for _ in range(3)]
        tag.node_set.add(*nodes)
        tag._populate_nodes_later()
        assert set(nodes) == set(tag.node_set.all())
        mock_reactor.callLater.assert_called_once()

    def test_later_is_the_default(self, mocker):
        tag = Tag(name=factory.make_name("tag"))
        mocker.patch.object(tag, "_populate_nodes_later")
        tag._populate_nodes_later.assert_not_called()
        tag.save()
        tag._populate_nodes_later.assert_called_once_with()


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestTagPopulateNodesNow:
    def test_populates_if_tag_is_defined(self, mocker):
        populate_multiple = mocker.patch.object(
            populate_tags, "populate_tag_for_multiple_nodes", autospec=True
        )

        tag = Tag(name=factory.make_name("tag"), definition="//foo")
        tag.save(populate=False)

        assert tag.is_defined
        populate_multiple.assert_not_called()
        tag._populate_nodes_now()
        populate_multiple.assert_called_once_with(tag, ANY)

    def test_does_nothing_if_tag_is_not_defined(self, mocker):
        populate_multiple = mocker.patch.object(
            populate_tags, "populate_tag_for_multiple_nodes", autospec=True
        )

        tag = Tag(name=factory.make_name("tag"), definition="")
        tag.save(populate=False)

        assert not tag.is_defined
        populate_multiple.assert_not_called()
        tag._populate_nodes_now()
        populate_multiple.assert_not_called()

    def test_clears_node_set_before_populating(self):
        tag = Tag(name=factory.make_name("tag"), definition="//foo")
        tag.save(populate=False)

        nodes = [factory.make_Node() for _ in range(3)]
        tag.node_set.add(*nodes)
        tag._populate_nodes_now()
        assert not list(tag.node_set.all())
