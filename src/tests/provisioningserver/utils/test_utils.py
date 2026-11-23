# Copyright 2012-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test `provisioningserver.utils`."""

from collections.abc import Iterator
from copy import deepcopy
import os
from unittest.mock import sentinel

from fixtures import EnvironmentVariableFixture
import pytest

from maastesting.factory import factory
from provisioningserver import utils as utils_module
from provisioningserver.utils import (
    CircularDependency,
    classify,
    flatten,
    is_instance_or_subclass,
    locate_config,
    locate_template,
    sorttop,
)


def get_run_path(*path):
    """Locate a file or directory relative to ``MAAS_ROOT``."""
    maas_root = os.environ["MAAS_ROOT"]
    return os.path.abspath(os.path.join(maas_root, *path))


class TestLocateConfig:
    """Tests for `locate_config`."""

    def test_returns_branch_etc_maas(self):
        config_path = locate_config()
        assert get_run_path("etc/maas") == config_path
        assert os.path.isdir(config_path)

    def test_defaults_to_global_etc_maas_if_variable_is_unset(self):
        with EnvironmentVariableFixture("MAAS_ROOT", None):
            assert "/etc/maas" == locate_config()

    def test_defaults_to_global_etc_maas_if_variable_is_empty(self):
        with EnvironmentVariableFixture("MAAS_ROOT", ""):
            assert "/etc/maas" == locate_config()

    def test_returns_absolute_path(self):
        with EnvironmentVariableFixture("MAAS_ROOT", "."):
            assert os.path.isabs(locate_config())

    def test_locates_config_file(self):
        filename = factory.make_string()
        assert get_run_path("etc/maas/", filename) == locate_config(filename)

    def test_locates_full_path(self):
        path = [factory.make_string() for counter in range(3)]
        assert get_run_path("etc/maas/", *path) == locate_config(*path)

    def test_normalizes_path(self):
        assert get_run_path("etc/maas/bar/szot") == locate_config(
            "foo/.././bar///szot"
        )


class TestLocateTemplate:
    """Tests for `locate_template`."""

    def test_returns_test_path(self):
        assert os.path.abspath(
            os.path.join(
                os.path.dirname(utils_module.__file__),
                "..",
                "templates",
            )
        ) == locate_template("")


class TestClassify:
    def test_no_subjects(self):
        assert ([], []) == classify(sentinel.func, [])

    def test_subjects(self):
        subjects = [("one", 1), ("two", 2), ("three", 3)]

        def is_even(subject):
            return subject % 2 == 0

        assert (["two"], ["one", "three"]) == classify(is_even, subjects)


class TestFlatten:
    def test_returns_iterator(self):
        assert isinstance(flatten(()), Iterator)

    def test_returns_empty_when_nothing_provided(self):
        assert [] == list(flatten([]))
        assert [] == list(flatten(()))
        assert [] == list(flatten({}))
        assert [] == list(flatten(set()))
        assert [] == list(flatten(([], (), {}, set())))
        assert [] == list(flatten(([[]], ((),))))

    def test_flattens_list(self):
        assert [1, 2, 3, "abc"] == list(flatten([1, 2, 3, "abc"]))

    def test_flattens_nested_lists(self):
        assert [1, 2, 3, "abc"] == list(flatten([[[1, 2, 3, "abc"]]]))

    def test_flattens_arbitrarily_nested_lists(self):
        assert [1, "two", "three", 4, 5, 6] == list(
            flatten([[1], ["two", "three"], [4], [5, 6]])
        )

    def test_flattens_other_iterables(self):
        assert [1, 2, 3.3, 4, 5, 6] == list(flatten([1, 2, {3.3, 4, (5, 6)}]))

    def test_treats_string_like_objects_as_leaves(self):
        # Strings are iterable, but we know they cannot be flattened further.
        assert ["abcdef"] == list(flatten("abcdef"))

    def test_takes_star_args(self):
        assert ["a", "b", "c", "d", "e", "f"] == list(
            flatten("a", "b", "c", "d", "e", "f")
        )


EMPTY = frozenset()


class TestSortTop:
    """Tests for `sorttop`."""

    def assertSort(self, data, *batches):
        assert batches == tuple(sorttop(data))

    def test_empty_yields_no_batches(self):
        self.assertSort({})

    def test_single_thing_without_dep_yields_single_batch(self):
        self.assertSort({7: EMPTY}, {7})

    def test_single_thing_referring_to_self_yields_single_batch(self):
        self.assertSort({7: {7}}, {7})

    def test_multiple_things_without_dep_yields_single_batch(self):
        self.assertSort({4: EMPTY, 5: EMPTY}, {4, 5})

    def test_multiple_things_with_deps_yields_multiple_batches(self):
        self.assertSort({1: {2}, 2: {3}, 3: EMPTY}, {3}, {2}, {1})

    def test_ghost_dependencies_appear_in_first_batch(self):
        # A "ghost" is a dependency that doesn't appear as a "thing", i.e. as
        # a key in the dict passed in to sorttop.
        self.assertSort({1: {2}, 3: EMPTY}, {2, 3}, {1})

    def test_circular_dependency_results_in_an_exception(self):
        with pytest.raises(CircularDependency):
            list(sorttop({1: {2}, 2: {1}}))

    def test_input_not_modified(self):
        data = {1: {2, 5}, 2: {3, 4, 5}, 6: {2}}
        orig = deepcopy(data)
        self.assertSort(data, {3, 4, 5}, {2}, {1, 6})
        assert orig == data

    def test_can_sort_non_numeric_things_too(self):
        computers = object()
        books = object()
        paper = object()
        silicon = object()
        data = {
            "alice": {"bob", "carol"},
            "bob": {"carol", "dave"},
            "carol": {computers, books},
            "dave": {books},
            books: {paper},
            computers: {books, silicon},
            True: {False},
        }
        self.assertSort(
            data,
            {silicon, paper, False},
            {books, True},
            {computers, "dave"},
            {"carol"},
            {"bob"},
            {"alice"},
        )


# Classes for testing `is_instance_or_type()`.
class Foo:
    pass


class Bar:
    pass


class Baz(Bar):
    pass


@pytest.mark.parametrize(
    "foo,bar,baz",
    [
        (Foo(), Bar(), Baz()),
        (Foo, Bar, Baz),
    ],
    ids=["instances", "types"],
)
class TestIsInstanceOrSubclass:
    """Tests for `is_instance_or_subclass`."""

    def test_accepts_correct_type(self, foo, bar, baz):
        assert is_instance_or_subclass(foo, Foo)
        assert is_instance_or_subclass(bar, Bar)
        assert is_instance_or_subclass(baz, Baz)

    def test_returns_false_if_object_is_not_relevant(self, foo, bar, baz):
        assert not is_instance_or_subclass("Bar", Bar)

    def test_accept_subclass(self, foo, bar, baz):
        assert is_instance_or_subclass(baz, Bar)

    def test_rejects_incorrect_type(self, foo, bar, baz):
        assert not is_instance_or_subclass(foo, Bar)
        assert not is_instance_or_subclass(bar, Baz)
        assert not is_instance_or_subclass(baz, Foo)

    def test_accepts_tuple_or_list(self, foo, bar, baz):
        assert is_instance_or_subclass(foo, (Baz, Foo, Bar))
        assert not is_instance_or_subclass(bar, (Baz, Foo))
        assert is_instance_or_subclass(baz, [Bar, Foo])

    def test_accepts_variable_args(self, foo, bar, baz):
        assert is_instance_or_subclass(foo, Baz, Foo, Bar)
        assert not is_instance_or_subclass(foo, Baz, Bar)

    def test_accepts_non_flat_list(self, foo, bar, baz):
        assert is_instance_or_subclass(foo, (Baz, (Bar, (Foo,))))
        assert is_instance_or_subclass(bar, *[Baz, [Bar, [Foo]]])
