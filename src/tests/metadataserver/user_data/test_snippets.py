# Copyright 2013-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the snippets-related support routines for commissioning user data."""

from maastesting.factory import factory
from metadataserver.user_data.snippets import (
    get_snippet_context,
    is_snippet,
    list_snippets,
    read_snippet,
    strip_name,
)


class TestSnippets:
    def test_read_snippet_reads_snippet_file(self, tmp_path):
        contents = factory.make_string()
        snippets_dir = tmp_path / "snippets"
        snippets_dir.mkdir()
        snippet = snippets_dir / "snippet"
        snippet.write_text(contents)
        assert contents == read_snippet(str(snippet.parent), snippet.name)

    def test_strip_name_leaves_simple_names_intact(self):
        simple_name = factory.make_string()
        assert simple_name == strip_name(simple_name)

    def test_strip_name_replaces_dots(self):
        assert "_x_y_" == strip_name(".x.y.")

    def test_is_snippet(self):
        are_snippets = {
            "snippet": True,
            "with-dash": True,
            "module.py": True,
            ".backup": False,
            "backup~": False,
            "module.pyc": False,
            "__init__.pyc": False,
            "tests": False,
        }
        assert are_snippets == {
            name: is_snippet(name) for name in are_snippets
        }

    def test_list_snippets(self, tmp_path):
        snippets_dir = tmp_path / "snippets"
        snippets_dir.mkdir()
        factory.make_file(str(snippets_dir), "snippet")
        factory.make_file(str(snippets_dir), ".backup.pyc")
        assert ["snippet"] == list_snippets(str(snippets_dir))

    def test_get_snippet_context(self, tmp_path):
        contents = factory.make_string()
        snippets_dir = tmp_path / "snippets"
        snippets_dir.mkdir()
        factory.make_file(str(snippets_dir), "snippet.py", contents=contents)
        snippets = get_snippet_context(snippets_dir=str(snippets_dir))
        assert {"base_user_data_sh", "snippet_py"} == snippets.keys()
        assert contents == snippets["snippet_py"]

    def test_get_snippet_always_contains_base_user_data(self, tmp_path):
        snippets_dir = tmp_path / "snippets"
        snippets_dir.mkdir()
        assert {"base_user_data_sh"} == get_snippet_context(
            snippets_dir=str(snippets_dir)
        ).keys()
