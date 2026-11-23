# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for utilities to execute external commands."""

import os
import random
from subprocess import CalledProcessError
from tempfile import NamedTemporaryFile
from textwrap import dedent

from fixtures import EnvironmentVariable
import pytest

from maastesting.factory import factory
import provisioningserver.utils.shell as shell_module
from provisioningserver.utils.shell import (
    call_and_check,
    ExternalProcessError,
    get_env_with_bytes_locale,
    get_env_with_locale,
    has_command_available,
    run_command,
)


class TestCallAndCheck:
    """Tests `call_and_check`."""

    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        self.mocker = mocker

    def patch_popen(self, returncode=0, stderr=""):
        """Replace `subprocess.Popen` with a mock."""
        popen = self.mocker.patch.object(shell_module, "Popen")
        process = popen.return_value
        process.communicate.return_value = (None, stderr)
        process.returncode = returncode
        return process

    def test_returns_standard_output(self):
        output = factory.make_string().encode("ascii")
        assert output == call_and_check(["/bin/echo", "-n", output])

    def test_raises_ExternalProcessError_on_failure(self):
        command = factory.make_name("command")
        message = factory.make_string()
        self.patch_popen(returncode=1, stderr=message)
        with pytest.raises(ExternalProcessError) as exc_info:
            call_and_check(command)
        assert 1 == exc_info.value.returncode
        assert command == exc_info.value.cmd
        assert message == exc_info.value.output

    def test_passes_timeout_to_communicate(self):
        command = factory.make_name("command")
        process = self.patch_popen()
        timeout = random.randint(1, 10)
        call_and_check(command, timeout=timeout)
        process.communicate.assert_called_once_with(timeout=timeout)

    def test_reports_stderr_on_failure(self, tmp_path):
        nonfile = os.path.join(str(tmp_path), factory.make_name("nonesuch"))
        with pytest.raises(ExternalProcessError) as exc_info:
            call_and_check(
                ["/bin/cat", nonfile],
                env={"LC_ALL": "C"},
            )
        assert (
            b"cat: %s: No such file or directory" % nonfile.encode("ascii")
            in exc_info.value.output
        )


class TestExternalProcessError:
    """Tests for the ExternalProcessError class."""

    def test_upgrade_upgrades_CalledProcessError(self):
        error = factory.make_CalledProcessError()
        assert not isinstance(error, ExternalProcessError)
        ExternalProcessError.upgrade(error)
        assert isinstance(error, ExternalProcessError)

    def test_upgrade_does_not_change_CalledProcessError_subclasses(self):
        error_type = factory.make_exception_type(bases=(CalledProcessError,))
        error = factory.make_CalledProcessError()
        error.__class__ = error_type  # Change the class.
        assert not isinstance(error, ExternalProcessError)
        ExternalProcessError.upgrade(error)
        assert not isinstance(error, ExternalProcessError)
        assert error.__class__ is error_type

    def test_upgrade_does_not_change_other_errors(self):
        error_type = factory.make_exception_type()
        error = error_type()
        assert not isinstance(error, ExternalProcessError)
        ExternalProcessError.upgrade(error)
        assert not isinstance(error, ExternalProcessError)
        assert error.__class__ is error_type

    def test_upgrade_returns_None(self):
        assert None is ExternalProcessError.upgrade(factory.make_exception())

    def test_to_unicode_decodes_to_unicode(self):
        # Byte strings are decoded as ASCII by _to_unicode(), replacing
        # all non-ASCII characters with U+FFFD REPLACEMENT CHARACTERs.
        byte_string = b"This string will be converted. \xe5\xb2\x81\xe5."
        expected_unicode_string = (
            "This string will be converted. \ufffd\ufffd\ufffd\ufffd."
        )
        converted_string = ExternalProcessError._to_unicode(byte_string)
        assert isinstance(converted_string, str)
        assert expected_unicode_string == converted_string

    def test_to_unicode_defers_to_unicode_constructor(self):
        # Unicode strings and non-byte strings are handed to unicode()
        # to undergo Python's normal coercion strategy. (For unicode
        # strings this is actually a no-op, but it's cheaper to do this
        # than special-case unicode strings.)
        assert str(self) == ExternalProcessError._to_unicode(self)

    def test_to_ascii_encodes_to_bytes(self):
        # Yes, this is how you really spell "smorgasbord."  Look it up.
        unicode_string = "Sm\xf6rg\xe5sbord"
        expected_byte_string = b"Sm?rg?sbord"
        converted_string = ExternalProcessError._to_ascii(unicode_string)
        assert isinstance(converted_string, bytes)
        assert expected_byte_string == converted_string

    def test_to_ascii_defers_to_bytes(self):
        # Byte strings and non-unicode strings are handed to bytes() to
        # undergo Python's normal coercion strategy. (For byte strings
        # this is actually a no-op, but it's cheaper to do this than
        # special-case byte strings.)
        assert str(self).encode("ascii") == ExternalProcessError._to_ascii(
            self
        )

    def test_to_ascii_removes_non_printable_chars(self):
        # After conversion to a byte string, all non-printable and
        # non-ASCII characters are replaced with question marks.
        byte_string = b"*How* many roads\x01\x02\xb2\xfe"
        expected_byte_string = b"*How* many roads????"
        converted_string = ExternalProcessError._to_ascii(byte_string)
        assert isinstance(converted_string, bytes)
        assert expected_byte_string == converted_string

    def test_str__returns_unicode(self):
        error = ExternalProcessError(returncode=-1, cmd="foo-bar")
        assert isinstance(error.__str__(), str)

    def test_str__contains_output(self):
        output = b"Mot\xf6rhead"
        unicode_output = "Mot\ufffdrhead"
        error = ExternalProcessError(
            returncode=-1, cmd="foo-bar", output=output
        )
        assert unicode_output in error.__str__()

    def test_output_as_ascii(self):
        output = b"Joyeux No\xebl"
        ascii_output = b"Joyeux No?l"
        error = ExternalProcessError(
            returncode=-1, cmd="foo-bar", output=output
        )
        assert ascii_output == error.output_as_ascii

    def test_output_as_unicode(self):
        output = b"Mot\xf6rhead"
        unicode_output = "Mot\ufffdrhead"
        error = ExternalProcessError(
            returncode=-1, cmd="foo-bar", output=output
        )
        assert unicode_output == error.output_as_unicode


class TestHasCommandAvailable:
    def test_returns_False_when_not_found_raised(self, mocker):
        mocker.patch.object(shell_module.shutil, "which").return_value = None
        assert not has_command_available(factory.make_name("cmd"))

    def test_returns_True_when_ExternalProcessError_not_raised(self, mocker):
        command = factory.make_name("cmd")
        mocker.patch.object(
            shell_module.shutil, "which"
        ).return_value = f"/bin/{command}"
        assert has_command_available(command)


# Taken from locale(7).
LC_VAR_NAMES = {
    "LC_ADDRESS",
    "LC_COLLATE",
    "LC_CTYPE",
    "LC_IDENTIFICATION",
    "LC_MONETARY",
    "LC_MESSAGES",
    "LC_MEASUREMENT",
    "LC_NAME",
    "LC_NUMERIC",
    "LC_PAPER",
    "LC_TELEPHONE",
    "LC_TIME",
}


class TestGetEnvWithLocale:
    """Tests for `get_env_with_locale`."""

    def test_sets_LANG_and_LC_ALL(self):
        assert get_env_with_locale({}) == {
            "LANG": "C.UTF-8",
            "LANGUAGE": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }

    def test_overwrites_LANG(self):
        assert get_env_with_locale({"LANG": factory.make_name("LANG")}) == {
            "LANG": "C.UTF-8",
            "LANGUAGE": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }

    def test_overwrites_LANGUAGE(self):
        assert get_env_with_locale(
            {"LANGUAGE": factory.make_name("LANGUAGE")}
        ) == {
            "LANG": "C.UTF-8",
            "LANGUAGE": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }

    def test_removes_other_LC_variables(self):
        assert get_env_with_locale(
            {name: factory.make_name(name) for name in LC_VAR_NAMES}
        ) == {
            "LANG": "C.UTF-8",
            "LANGUAGE": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
        }

    def test_passes_other_variables_through(self):
        basis = {
            factory.make_name("name"): factory.make_name("value")
            for _ in range(5)
        }
        expected = basis.copy()
        expected["LANG"] = expected["LC_ALL"] = expected["LANGUAGE"] = (
            "C.UTF-8"
        )
        observed = get_env_with_locale(basis)
        assert expected == observed

    def test_defaults_to_process_environment(self):
        name = factory.make_name("name")
        value = factory.make_name("value")
        with EnvironmentVariable(name, value):
            assert get_env_with_locale().get(name) == value


class TestGetEnvWithBytesLocale:
    """Tests for `get_env_with_bytes_locale`."""

    def test_sets_LANG_and_LC_ALL(self):
        assert get_env_with_bytes_locale({}) == {
            b"LANG": b"C.UTF-8",
            b"LANGUAGE": b"C.UTF-8",
            b"LC_ALL": b"C.UTF-8",
        }

    def test_overwrites_LANG(self):
        assert get_env_with_bytes_locale(
            {b"LANG": factory.make_name("LANG").encode("ascii")}
        ) == {
            b"LANG": b"C.UTF-8",
            b"LANGUAGE": b"C.UTF-8",
            b"LC_ALL": b"C.UTF-8",
        }

    def test_overwrites_LANGUAGE(self):
        assert get_env_with_bytes_locale(
            {b"LANGUAGE": factory.make_name("LANGUAGE").encode("ascii")}
        ) == {
            b"LANG": b"C.UTF-8",
            b"LANGUAGE": b"C.UTF-8",
            b"LC_ALL": b"C.UTF-8",
        }

    def test_removes_other_LC_variables(self):
        assert get_env_with_bytes_locale(
            {
                name.encode("ascii"): factory.make_name(name).encode("ascii")
                for name in LC_VAR_NAMES
            }
        ) == {
            b"LANG": b"C.UTF-8",
            b"LANGUAGE": b"C.UTF-8",
            b"LC_ALL": b"C.UTF-8",
        }

    def test_passes_other_variables_through(self):
        basis = {
            factory.make_name("name").encode("ascii"): (
                factory.make_name("value").encode("ascii")
            )
            for _ in range(5)
        }
        expected = basis.copy()
        expected[b"LANG"] = expected[b"LC_ALL"] = expected[b"LANGUAGE"] = (
            b"C.UTF-8"
        )
        observed = get_env_with_bytes_locale(basis)
        assert expected == observed

    def test_defaults_to_process_environment(self):
        name = factory.make_name("name")
        value = factory.make_name("value")
        with EnvironmentVariable(name, value):
            assert get_env_with_bytes_locale().get(
                name.encode("ascii")
            ) == value.encode("Ascii")


class TestRunCommand:
    def test_stdout_stderr(self):
        with NamedTemporaryFile(
            "w", encoding="utf-8", delete=False
        ) as executable:
            executable.write(
                dedent(
                    """\
                    #!/bin/sh
                    echo "$@"
                    echo stderr >&2
                    return 3
                    """
                )
            )
            executable.close()
            os.chmod(executable.name, 0o755)
            result = run_command(executable.name, "some", "args")
        assert result.stdout == "some args"
        assert result.stderr == "stderr"
        assert result.returncode == 3

    def test_no_decode(self):
        with NamedTemporaryFile(
            "w", encoding="utf-8", delete=False
        ) as executable:
            executable.write(
                dedent(
                    """\
                    #!/bin/sh
                    echo "$@"
                    echo stderr >&2
                    """
                )
            )
            executable.close()
            os.chmod(executable.name, 0o755)
            result = run_command(executable.name, "some", "args", decode=False)
        assert result.stdout == b"some args"
        assert result.stderr == b"stderr"

    def test_environ(self):
        result = run_command("env", extra_environ={"FOO": "bar"})
        assert "FOO=bar" in result.stdout

    def test_stdin(self):
        # The timeout here is to prevent hanging of the test suite
        # should it fail (since failure scenario is inheriting stdin
        # from parent process, i.e. this one!)
        result = run_command("cat", stdin=b"foo", decode=False, timeout=0.2)
        assert result.stdout == b"foo"
