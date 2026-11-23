# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the subcommand utilities."""

from argparse import ArgumentParser, Namespace
from random import randint
from subprocess import CalledProcessError
import types

import pytest

from maastesting.factory import factory
from provisioningserver.utils import script as script_module
from provisioningserver.utils.script import ActionScript, ActionScriptError


class TestActionScript:
    """Test `ActionScript`."""

    factory = ActionScript

    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        # ActionScript.setup() is not safe to run in the test suite.
        mocker.patch.object(ActionScript, "setup", lambda self: None)
        self.mocker = mocker

    def test_init(self):
        description = factory.make_string()
        script = self.factory(description)
        assert isinstance(script.parser, ArgumentParser)
        assert description == script.parser.description

    def test_register(self):
        handler = types.ModuleType("handler")
        handler.add_arguments = lambda parser: (
            isinstance(parser, ArgumentParser)
        )
        handler.run = lambda args: isinstance(args, int)
        script = self.factory("Description")
        script.register("slay", handler)
        assert "slay" in script.subparsers.choices
        action_parser = script.subparsers.choices["slay"]
        assert isinstance(action_parser, ArgumentParser)

    def test_register_without_add_arguments(self):
        # ActionScript.register will crash if the handler has no
        # add_arguments() callable.
        handler = types.ModuleType("handler")
        handler.run = lambda args: None
        script = self.factory("Description")
        with pytest.raises(AttributeError) as exc_info:
            script.register("decapitate", handler)
        assert "'add_arguments'" in "%s" % exc_info.value

    def test_register_without_run(self):
        # ActionScript.register will crash if the handler has no run()
        # callable.
        handler = types.ModuleType("handler")
        handler.add_arguments = lambda parser: None
        script = self.factory("Description")
        with pytest.raises(AttributeError) as exc_info:
            script.register("decapitate", handler)
        assert "'run'" in "%s" % exc_info.value

    def test_call(self):
        handler_calls = []
        handler = types.ModuleType("handler")
        handler.add_arguments = lambda parser: None
        handler.run = handler_calls.append
        script = self.factory("Description")
        script.register("amputate", handler)
        with pytest.raises(SystemExit) as exc_info:
            script(["amputate"])
        assert 0 == exc_info.value.code
        assert 1 == len(handler_calls)
        assert isinstance(handler_calls[0], Namespace)

    def test_call_invalid_choice(self, capsys):
        script = self.factory("Description")
        with pytest.raises(SystemExit):
            script(["disembowel"])
        stderr = capsys.readouterr().err
        assert "invalid choice" in stderr

    def test_call_with_exception(self):
        # Most exceptions from run() are propagated.
        handler = types.ModuleType("handler")
        handler.add_arguments = lambda parser: None
        handler.run = lambda args: 0 / 0
        script = self.factory("Description")
        script.register("eviscerate", handler)
        with pytest.raises(ZeroDivisionError):
            script(["eviscerate"])

    def test_call_with_process_exception(self):
        # CalledProcessError is converted into SystemExit.
        exception = CalledProcessError(
            randint(0, 256),
            [factory.make_string()],
            factory.make_string().encode("ascii"),
        )

        def raise_exception():
            raise exception

        handler = types.ModuleType("handler")
        handler.add_arguments = lambda parser: None
        handler.run = lambda args: raise_exception()
        script = self.factory("Description")
        script.register("sever", handler)
        with pytest.raises(SystemExit) as exc_info:
            script(["sever"])
        assert exception.returncode == exc_info.value.code

    def test_call_with_keyboard_interrupt(self):
        # KeyboardInterrupt is silently converted into SystemExit, with an
        # exit code of 1.

        def raise_exception():
            raise KeyboardInterrupt()

        handler = types.ModuleType("handler")
        handler.add_arguments = lambda parser: None
        handler.run = lambda args: raise_exception()
        script = self.factory("Description")
        script.register("smash", handler)
        with pytest.raises(SystemExit) as exc_info:
            script(["smash"])
        assert 1 == exc_info.value.code

    def test_call_with_actionscripterror(self, capsys):
        # ActionScriptError is converted into SystemExit, with  the
        # specified exit code. (And the message is printed to stderr.)

        def raise_exception():
            raise ActionScriptError("Towel.", returncode=42)

        handler = types.ModuleType("handler")
        handler.add_arguments = lambda parser: None
        handler.run = lambda args: raise_exception()
        script = self.factory("Description")
        script.register("smash", handler)
        with pytest.raises(SystemExit, match="42"):
            # This needs to be a no-op.
            self.mocker.patch.object(script_module.ActionScript, "setup")
            script(["smash"])
        stderr = capsys.readouterr().err
        assert "Towel.\n" == stderr
