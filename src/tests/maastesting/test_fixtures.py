# Copyright 2012-2016 Canonical Ltd. This software is licensed under the GNU
# Affero General Public License version 3 (see the file LICENSE).

import builtins
from itertools import repeat
import os
import sys
from unittest.mock import call

from fixtures import EnvironmentVariable
import pytest

from maastesting import dev_root
from maastesting.factory import factory
from maastesting.fixtures import (
    CaptureStandardIO,
    ImportErrorFixture,
    MAASRootFixture,
    ProxiesDisabledFixture,
    TempDirectory,
    TempWDFixture,
)
from maastesting.utils import sample_binary_data


class TestImportErrorFixture:
    """Tests for :class:`TestImportErrorFixture`."""

    def test_import_non_targeted_module_successfull(self):
        with ImportErrorFixture("maastesting", "dev_root"):
            from maastesting import bindir  # noqa

    def test_import_targeted_module_unsuccessfull(self):
        with ImportErrorFixture("maastesting", "dev_root"):
            with pytest.raises(
                ImportError,
                match=r"ImportErrorFixture raising ImportError exception on targeted import: maastesting\.dev_root",
            ):
                from maastesting import dev_root  # noqa

    def test_import_restores_original__import__(self):
        __real_import = builtins.__import__
        with ImportErrorFixture("maastesting", "dev_root"):
            assert __real_import is not builtins.__import__, (
                "ImportErrorFixture did not properly "
                "patch __builtin__.__import__"
            )
        assert __real_import is builtins.__import__, (
            "ImportErrorFixture did not properly restore "
            "the original __builtin__.__import__ upon cleanup"
        )


class TestProxiedDisabledFixture:
    """Tests for :class:`ProxiesDisabledFixture`."""

    def test_removes_http_proxy_from_environment(self):
        http_proxy = factory.make_name("http-proxy")
        with EnvironmentVariable("http_proxy", http_proxy):
            # On entry, http_proxy is removed from the environment.
            with ProxiesDisabledFixture():
                assert "http_proxy" not in os.environ
            # On exit, http_proxy is restored.
            assert http_proxy == os.environ.get("http_proxy")

    def test_removes_https_proxy_from_environment(self):
        https_proxy = factory.make_name("https-proxy")
        with EnvironmentVariable("https_proxy", https_proxy):
            # On entry, https_proxy is removed from the environment.
            with ProxiesDisabledFixture():
                assert "https_proxy" not in os.environ
            # On exit, http_proxy is restored.
            assert https_proxy == os.environ.get("https_proxy")


class TestTempDirectory:
    def test_path_is_unicode(self):
        with TempDirectory() as fixture:
            assert isinstance(fixture.path, str)

    def test_path_is_decoded_using_filesystem_encoding(self):
        with TempDirectory() as outer:
            # Create a nested temporary directory from a BYTE path.
            with TempDirectory(outer.path.encode("ascii")) as inner:
                assert isinstance(inner.path, str)


class TestTempWDFixture:
    def test_changes_dir_and_cleans_up(self):
        orig_cwd = os.getcwd()
        with TempWDFixture() as temp_wd:
            new_cwd = os.getcwd()
            assert os.path.isdir(temp_wd.path)
            assert orig_cwd != new_cwd
            assert new_cwd == temp_wd.path
        final_cwd = os.getcwd()
        assert orig_cwd == final_cwd
        assert not os.path.isdir(new_cwd)


class TestCaptureStandardIO:
    """Test `CaptureStandardIO`."""

    def test_captures_stdin(self):
        stdin_before = sys.stdin
        with CaptureStandardIO():
            stdin_during = sys.stdin
        stdin_after = sys.stdin

        assert stdin_during is not stdin_before
        assert stdin_during is not stdin_after
        assert stdin_after is stdin_before

    def test_captures_stdout(self):
        stdout_before = sys.stdout
        with CaptureStandardIO():
            stdout_during = sys.stdout
        stdout_after = sys.stdout

        assert stdout_during is not stdout_before
        assert stdout_during is not stdout_after
        assert stdout_after is stdout_before

    def test_captures_stderr(self):
        stderr_before = sys.stderr
        with CaptureStandardIO():
            stderr_during = sys.stderr
        stderr_after = sys.stderr

        assert stderr_during is not stderr_before
        assert stderr_during is not stderr_after
        assert stderr_after is stderr_before

    def test_addInput_feeds_stdin(self):
        text = factory.make_name("text")
        with CaptureStandardIO() as stdio:
            stdio.addInput(text + "111")
            assert sys.stdin.read(2) == text[:2]
            stdio.addInput(text + "222")
            assert sys.stdin.read() == text[2:] + "111" + text + "222"

    def test_getInput_returns_data_waiting_to_be_read(self):
        stdio = CaptureStandardIO()
        stdio.addInput("one\ntwo\n")
        with stdio:
            assert sys.stdin.readline() == "one\n"
            assert stdio.getInput() == "two\n"

    def test_getOutput_returns_data_written_to_stdout(self, mocker):
        self.assert_getter_returns_data_written_to_stream(
            CaptureStandardIO.getOutput, "stdout", mocker
        )

    def test_getError_returns_data_written_to_stderr(self, mocker):
        self.assert_getter_returns_data_written_to_stream(
            CaptureStandardIO.getError, "stderr", mocker
        )

    def assert_getter_returns_data_written_to_stream(
        self, getter, name, mocker
    ):
        stream = mocker.patch.object(sys, name)

        before = factory.make_name("before")
        during = factory.make_name("during")
        after = factory.make_name("after")
        end = factory.make_name("end")

        print(before, file=getattr(sys, name), end=end)
        with CaptureStandardIO() as stdio:
            print(during, file=getattr(sys, name), end=end)
        print(after, file=getattr(sys, name), end=end)

        assert getter(stdio) == during + end
        stream.write.assert_has_calls(
            [call(before), call(end), call(after), call(end)]
        )

    def test_clearInput_clears_input(self):
        text = factory.make_name("text")
        with CaptureStandardIO() as stdio:
            stdio.addInput(text + "111")
            sys.stdin.read(2)
            stdio.clearInput()
            assert sys.stdin.read(2) == ""

    def test_clearOutput_clears_output(self):
        text = factory.make_name("text")
        with CaptureStandardIO() as stdio:
            sys.stdout.write(text)
            assert stdio.getOutput() == text
            stdio.clearOutput()
            assert stdio.getOutput() == ""

    def test_clearError_clears_error(self):
        text = factory.make_name("text")
        with CaptureStandardIO() as stdio:
            sys.stderr.write(text)
            assert stdio.getError() == text
            stdio.clearError()
            assert stdio.getError() == ""

    def test_clearAll_clears_input_output_and_error(self):
        text = factory.make_name("text")
        with CaptureStandardIO() as stdio:
            stdio.addInput(text)
            sys.stdout.write(text)
            sys.stderr.write(text)
            stdio.clearAll()
            assert stdio.getInput() == ""
            assert stdio.getOutput() == ""
            assert stdio.getError() == ""

    def test_non_text_strings_are_rejected_on_stdout(self):
        with CaptureStandardIO():
            with pytest.raises(TypeError) as error:
                sys.stdout.write(sample_binary_data)
        assert "write() argument must be str, not bytes" in str(error.value)

    def test_non_text_strings_are_rejected_on_stderr(self):
        with CaptureStandardIO():
            with pytest.raises(TypeError) as error:
                sys.stderr.write(sample_binary_data)
        assert "write() argument must be str, not bytes" in str(error.value)


def listdirs(start):
    """Recursively generate paths for all directories and files in `start`.

    Paths generated are relative to `start`. Symbolic links are followed.
    """
    for dirpath, dirnames, filenames in os.walk(start, followlinks=True):
        dirpath = os.path.relpath(dirpath, start)
        yield from map(os.path.join, repeat(dirpath), dirnames)
        yield from map(os.path.join, repeat(dirpath), filenames)


class TestMAASRootFixture:
    """Tests for `MAASRootFixture`."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.skel = os.path.join(dev_root, "run-skel")
        self.package_files = os.path.join(dev_root, "package-files")
        with EnvironmentVariable("MAAS_ROOT", "/"):
            yield

    def test_creates_populates_and_removes_new_directory(self):
        fixture = MAASRootFixture()
        with fixture:
            assert os.path.exists(fixture.path)
            assert fixture.path != self.skel
            files_expected = set(listdirs(self.skel)) | set(
                listdirs(self.package_files)
            )
            files_observed = set(listdirs(fixture.path))
            assert files_expected == files_observed
        assert not os.path.exists(fixture.path)

    def test_updates_MAAS_ROOT_in_the_environment(self):
        assert os.environ["MAAS_ROOT"] != self.skel
        with MAASRootFixture() as fixture:
            assert os.environ["MAAS_ROOT"] == fixture.path
        assert os.environ["MAAS_ROOT"] != self.skel
