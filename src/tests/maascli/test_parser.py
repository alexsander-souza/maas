# Copyright 2012-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import sys

import pytest

from maascli.parser import (
    ArgumentParser,
    get_deepest_subparser,
    prepare_parser,
)
from maastesting.factory import factory


class TestArgumentParser:
    """Tests for `ArgumentParser`."""

    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HOME", str(tmp_path))

    def test_add_subparsers_single_only(self):
        parser = ArgumentParser()
        parser.add_subparsers()
        with pytest.raises(AssertionError):
            parser.add_subparsers()

    def test_add_subparsers_returns_subparsers(self):
        parser = ArgumentParser()
        added_subparsers = parser.add_subparsers()
        assert added_subparsers is parser.subparsers

    def test_subparsers_property(self):
        parser = ArgumentParser()
        # argparse.ArgumentParser.add_subparsers populates a _subparsers
        # attribute when called. Its contents are not the same as the return
        # value from add_subparsers, so we just use it an indicator here.
        assert parser._subparsers is None
        # Reference the subparsers property.
        subparsers = parser.subparsers
        # _subparsers is populated, meaning add_subparsers has been called on
        # the superclass.
        assert parser._subparsers is not None
        # The subparsers property, once populated, always returns the same
        # object.
        assert subparsers is parser.subparsers

    def test_bad_arguments_prints_help_to_stderr(self, mocker):
        argv = ["maas", factory.make_name(prefix="profile"), "nodes"]
        parser = prepare_parser(argv)
        mock_print_help = mocker.patch.object(ArgumentParser, "print_help")
        mocker.patch.object(sys, "exit")
        mocker.patch.object(ArgumentParser, "_print_error")
        # We need to catch this TypeError, because after our overridden error()
        # method is called, argparse expects the system to exit. Without
        # catching it, when we mock sys.exit() it will continue unexpectedly
        # and crash with the TypeError later.
        try:
            parser.parse_args(argv[1:])
        except TypeError:
            pass
        mock_print_help.assert_called_with(sys.stderr)

    def test_bad_arguments_calls_sys_exit_2(self, mocker):
        argv = ["maas", factory.make_name(prefix="profile"), "nodes"]
        parser = prepare_parser(argv)
        mocker.patch.object(ArgumentParser, "print_help")
        mock_exit = mocker.patch.object(sys, "exit")
        mocker.patch.object(ArgumentParser, "_print_error")
        # We need to catch this TypeError, because after our overridden error()
        # method is called, argparse expects the system to exit. Without
        # catching it, when we mock sys.exit() it will continue unexpectedly
        # and crash with the TypeError later.
        try:
            parser.parse_args(argv[1:])
        except TypeError:
            pass
        mock_exit.assert_called_with(2)


class TestGetDeepestSubparser:
    def test_no_argv(self):
        parser = ArgumentParser()
        assert get_deepest_subparser(parser, []) is parser

    def test_single_subparser(self):
        top_parser = ArgumentParser()
        foo = top_parser.subparsers.add_parser("foo", help="foo help")

        assert get_deepest_subparser(top_parser, ["foo"]) is foo

    def test_nested_subparser(self):
        top_parser = ArgumentParser()
        foo = top_parser.subparsers.add_parser("foo", help="foo help")
        bar = foo.subparsers.add_parser("bar", help="bar help")

        assert get_deepest_subparser(top_parser, ["foo", "bar"]) is bar

    def test_not_a_subparser(self):
        top_parser = ArgumentParser()
        foo = top_parser.subparsers.add_parser("foo", help="foo help")
        bar = foo.subparsers.add_parser("bar", help="bar help")

        assert (
            get_deepest_subparser(top_parser, ["foo", "bar", "--help"]) is bar
        )
        assert get_deepest_subparser(top_parser, ["--random"]) is top_parser
