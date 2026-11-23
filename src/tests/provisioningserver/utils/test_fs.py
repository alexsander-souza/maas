# Copyright 2014-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for filesystem-related utilities."""

import glob
import io
import os
import os.path
from pathlib import Path
import random
import re
import stat
import tempfile
import tokenize
import types
from unittest.mock import ANY, call, create_autospec, Mock, sentinel

import pytest
from twisted import internet
from twisted.internet.task import Clock
from twisted.python import lockfile

from maastesting import dev_root
from maastesting.factory import factory
from maastesting.fixtures import CaptureStandardIO
from maastesting.utils import age_file
import provisioningserver.config
from provisioningserver.path import get_tentative_data_path
import provisioningserver.utils.fs as fs_module
from provisioningserver.utils.fs import (
    atomic_copy,
    atomic_delete,
    atomic_symlink,
    atomic_write,
    FileLock,
    FilesystemLock,
    get_maas_common_command,
    get_root_path,
    NamedLock,
    read_text_file,
    RunLock,
    SystemLock,
    write_text_file,
)


def _make_file(tmp_path, name=None, contents=None):
    """Create a file under tmp_path and return its path."""
    if name is None:
        name = factory.make_string()
    path = os.path.join(str(tmp_path), name)
    if contents is None:
        contents = factory.make_bytes()
    if isinstance(contents, str):
        with open(path, "w") as f:
            f.write(contents)
    else:
        with open(path, "wb") as f:
            f.write(contents)
    return path


class TestGetRootPath:
    """Test get_root_path()."""

    def test_snap(self, mocker):
        mocker.patch.object(os, "environ", {"SNAP": "/snap/maas/123"})
        assert get_root_path() == Path("/snap/maas/123")

    def test_no_snap(self, mocker):
        mocker.patch.object(os, "environ", {})
        assert get_root_path() == Path("/")


class TestFilesystemLock:
    """Test `FilesystemLock.lock`."""

    def test_removes_lock_file_on_permission_error_before_retry(
        self, mocker, tmp_path
    ):
        target_dir = tmp_path
        name = factory.make_name("link")
        sym_link_path = os.path.join(str(target_dir), name)
        # Create a lock file.  Twisted's FilesystemLock creates
        # a symlink lock file for the current PID.
        fs_lock = FilesystemLock(sym_link_path)
        locked = fs_lock.lock()
        assert locked
        # Now that we have a lock file for the current PID, if we try to
        # lock the file again and we mock the readlink method, this will
        # cause kill to raise a PermissionError identitical to the error
        # seen with this bug. To verify this, run this unittest without
        # the fix.
        mocker.patch.object(lockfile, "readlink")
        locked = fs_lock.lock()
        assert locked


class TestAtomicWrite:
    """Test `atomic_write`."""

    def assert_file_contains(self, filename, content):
        with open(filename, "rb") as fh:
            file_content = fh.read()
        assert file_content == content

    def test_atomic_write_overwrites_dest_file(self, tmp_path):
        content = factory.make_bytes()
        filename = _make_file(tmp_path, contents=factory.make_string())
        atomic_write(content, filename)
        self.assert_file_contains(filename, content)

    def test_atomic_write_does_not_overwrite_file_if_overwrite_false(
        self, tmp_path
    ):
        content = factory.make_bytes()
        random_content = factory.make_bytes()
        filename = _make_file(tmp_path, contents=random_content)
        atomic_write(content, filename, overwrite=False)
        self.assert_file_contains(filename, random_content)

    def test_atomic_write_writes_file_if_no_file_present(self, tmp_path):
        filename = os.path.join(str(tmp_path), factory.make_string())
        content = factory.make_bytes()
        atomic_write(content, filename, overwrite=False)
        self.assert_file_contains(filename, content)

    def test_atomic_write_does_not_leak_temp_file_when_not_overwriting(
        self, tmp_path
    ):
        # If the file is not written because it already exists and
        # overwriting was disabled, atomic_write does not leak its
        # temporary file.
        parent = str(tmp_path / factory.make_name("dir"))
        os.makedirs(parent)
        filename = os.path.join(parent, factory.make_name("file"))
        with open(filename, "wb") as f:
            f.write(factory.make_bytes())
        atomic_write(factory.make_bytes(), filename, overwrite=False)
        assert [os.path.basename(filename)] == os.listdir(parent)

    def test_atomic_write_does_not_leak_temp_file_on_failure(
        self, mocker, tmp_path
    ):
        # If the overwrite fails, atomic_write does not leak its
        # temporary file.
        mocker.patch.object(fs_module, "rename", Mock(side_effect=OSError()))
        parent = str(tmp_path / factory.make_name("dir"))
        os.makedirs(parent)
        filename = os.path.join(parent, factory.make_name("file"))
        with open(filename, "wb") as f:
            f.write(factory.make_bytes())
        with pytest.raises(OSError):
            atomic_write(factory.make_bytes(), filename)
        assert [os.path.basename(filename)] == os.listdir(parent)

    def test_atomic_wrtie_does_not_leak_temp_file_set_permission_failure(
        self, mocker, tmp_path
    ):
        # Make os.chown() raise PermissionError and verify the temporary file
        # was removed.
        mocker.patch.object(
            fs_module, "chown", Mock(side_effect=PermissionError())
        )
        filename = _make_file(tmp_path)
        with pytest.raises(PermissionError):
            atomic_write(factory.make_bytes(), filename)

        pattern = os.path.join(
            os.path.dirname(filename),
            ".%s.*" % os.path.basename(filename),
        )
        matched_files = glob.glob(pattern)
        assert matched_files == []

    def test_atomic_write_sets_permissions(self, tmp_path):
        atomic_file = _make_file(tmp_path)
        # Pick an unusual mode that is also likely to fall outside our
        # umask.  We want this mode set, not treated as advice that may
        # be tightened up by umask later.
        mode = 0o323
        atomic_write(factory.make_bytes(), atomic_file, mode=mode)
        assert mode == stat.S_IMODE(os.stat(atomic_file).st_mode)

    def test_atomic_write_sets_permissions_before_moving_into_place(
        self, mocker, tmp_path
    ):
        recorded_modes = []

        def record_mode(source, dest):
            """Stub for os.rename: get source file's access mode."""
            recorded_modes.append(os.stat(source).st_mode)

        mocker.patch.object(fs_module, "rename", Mock(side_effect=record_mode))
        playground = tmp_path
        atomic_file = os.path.join(
            str(playground), factory.make_name("atomic")
        )
        mode = 0o323
        atomic_write(factory.make_bytes(), atomic_file, mode=mode)
        [recorded_mode] = recorded_modes
        assert mode == stat.S_IMODE(recorded_mode)

    def test_atomic_write_preserves_ownership_before_moving_into_place(
        self, mocker, tmp_path
    ):
        atomic_file = _make_file(tmp_path, name="atomic")

        mocker.patch.object(fs_module, "chown")
        mocker.patch.object(fs_module, "rename")
        mocker.patch.object(fs_module, "stat")

        ret_stat = fs_module.stat.return_value
        ret_stat.st_uid = sentinel.uid
        ret_stat.st_gid = sentinel.gid
        ret_stat.st_mode = stat.S_IFREG

        atomic_write(factory.make_bytes(), atomic_file)

        fs_module.stat.assert_called_once_with(atomic_file)
        fs_module.chown.assert_called_once_with(
            ANY, sentinel.uid, sentinel.gid
        )

    def test_atomic_write_sets_OSError_filename_if_undefined(self, mocker):
        # When the filename attribute of an OSError is undefined when
        # attempting to create a temporary file, atomic_write fills it in with
        # a representative filename, similar to the specification required by
        # mktemp(1).
        mock_mkstemp = mocker.patch.object(tempfile, "mkstemp")
        mock_mkstemp.side_effect = OSError()
        filename = os.path.join("directory", "basename")
        with pytest.raises(OSError) as excinfo:
            atomic_write(b"content", filename)
        assert excinfo.value.filename == os.path.join(
            "directory", ".basename.XXXXXX.tmp"
        )

    def test_atomic_write_does_not_set_OSError_filename_if_defined(
        self, mocker
    ):
        # When the filename attribute of an OSError is defined when attempting
        # to create a temporary file, atomic_write leaves it alone.
        mock_mkstemp = mocker.patch.object(tempfile, "mkstemp")
        mock_mkstemp.side_effect = OSError()
        mock_mkstemp.side_effect.filename = factory.make_name("filename")
        filename = os.path.join("directory", "basename")
        with pytest.raises(OSError) as excinfo:
            atomic_write(b"content", filename)
        assert mock_mkstemp.side_effect.filename == excinfo.value.filename

    def test_atomic_write_rejects_non_bytes_contents(self):
        with pytest.raises(TypeError):
            atomic_write(factory.make_string(), factory.make_string())


class TestAtomicCopy:
    def assert_file_contains(self, filename, content):
        with open(filename, "rb") as fh:
            file_content = fh.read()
        assert file_content == content

    def test_integration(self, tmp_path):
        loader_contents = factory.make_bytes()
        loader = _make_file(tmp_path, contents=loader_contents)
        destination = _make_file(tmp_path)
        atomic_copy(loader, destination)
        self.assert_file_contains(destination, loader_contents)

    def test_installs_new_bootloader(self, tmp_path):
        contents = factory.make_bytes()
        loader = _make_file(tmp_path, contents=contents)
        install_dir = tmp_path
        dest = os.path.join(str(install_dir), factory.make_name("loader"))
        atomic_copy(loader, dest)
        self.assert_file_contains(dest, contents)

    def test_replaces_file_if_changed(self, tmp_path):
        contents = factory.make_bytes()
        loader = _make_file(tmp_path, contents=contents)
        dest = _make_file(tmp_path, contents="Old contents")
        atomic_copy(loader, dest)
        self.assert_file_contains(dest, contents)

    def test_skips_if_unchanged(self, tmp_path):
        contents = factory.make_bytes()
        dest = _make_file(tmp_path, contents=contents)
        age_file(dest, 100)
        original_write_time = os.stat(dest).st_mtime
        loader = _make_file(tmp_path, contents=contents)
        atomic_copy(loader, dest)
        self.assert_file_contains(dest, contents)
        assert original_write_time == os.stat(dest).st_mtime

    def test_sweeps_aside_dot_new_if_any(self, tmp_path):
        contents = factory.make_bytes()
        loader = _make_file(tmp_path, contents=contents)
        dest = _make_file(tmp_path, contents="Old contents")
        temp_file = "%s.new" % dest
        factory.make_file(
            os.path.dirname(temp_file), name=os.path.basename(temp_file)
        )
        atomic_copy(loader, dest)
        self.assert_file_contains(dest, contents)


class TestAtomicDelete:
    """Test `atomic_delete`."""

    def test_atomic_delete_deletes_file(self, tmp_path):
        filename = _make_file(tmp_path)
        atomic_delete(filename)
        assert not os.path.exists(filename)

    def test_renames_file_before_deleting(self, mocker, tmp_path):
        # Intercept calls to os.remove.
        os_remove = mocker.patch.object(fs_module.os, "remove")

        filedir = str(tmp_path / factory.make_name("dir"))
        os.makedirs(filedir)
        contents = factory.make_name("contents").encode("ascii")
        filepath = os.path.join(filedir, factory.make_name("file"))
        with open(filepath, "wb") as f:
            f.write(contents)

        atomic_delete(filepath)

        listing = os.listdir(filedir)
        assert len(listing) == 1
        [deletedname] = listing
        assert re.search(r"^[.][^.]+[.]deleted$", deletedname)
        deletedpath = os.path.join(filedir, deletedname)
        os_remove.assert_called_once_with(deletedpath)
        with open(deletedpath, "rb") as fh:
            assert fh.read() == contents

    def test_leaves_nothing_behind_on_error(self, tmp_path):
        dirname = str(tmp_path / factory.make_name("dir"))
        os.makedirs(dirname)
        filename = os.path.join(dirname, "does-not-exist")
        with pytest.raises(FileNotFoundError):
            atomic_delete(filename)
        assert os.listdir(dirname) == []


class TestAtomicSymlink:
    """Test `atomic_symlink`."""

    def test_atomic_symlink_creates_symlink(self, tmp_path):
        filename = _make_file(tmp_path, contents=factory.make_string())
        target_dir = tmp_path
        link_name = factory.make_name("link")
        target = os.path.join(str(target_dir), link_name)
        atomic_symlink(filename, target)
        assert os.path.islink(target), "atomic_symlink didn't create a symlink"
        assert os.path.abspath(os.path.realpath(target)) == os.path.abspath(
            os.path.realpath(filename)
        )

    def test_atomic_symlink_overwrites_dest_file(self, tmp_path):
        filename = _make_file(tmp_path, contents=factory.make_string())
        target_dir = tmp_path
        link_name = factory.make_name("link")
        # Create a file that will be overwritten.
        factory.make_file(location=str(target_dir), name=link_name)
        target = os.path.join(str(target_dir), link_name)
        atomic_symlink(filename, target)
        assert os.path.islink(target), "atomic_symlink didn't create a symlink"
        assert os.path.abspath(os.path.realpath(target)) == os.path.abspath(
            os.path.realpath(filename)
        )

    def test_atomic_symlink_does_not_leak_temp_file_if_failure(
        self, mocker, tmp_path
    ):
        # In the face of failure, no temp file is leaked.
        mocker.patch.object(os, "rename", Mock(side_effect=OSError()))
        target_dir = str(tmp_path / factory.make_name("target"))
        os.makedirs(target_dir)
        filename = _make_file(tmp_path)
        link_name = factory.make_name("link")
        target = os.path.join(target_dir, link_name)
        with pytest.raises(OSError):
            atomic_symlink(filename, target)
        assert os.listdir(target_dir) == []

    def test_atomic_symlink_uses_relative_path(self, tmp_path):
        filename = _make_file(tmp_path, contents=factory.make_string())
        link_name = factory.make_name("link")
        target = os.path.join(os.path.dirname(filename), link_name)
        atomic_symlink(filename, target)
        assert os.path.basename(filename) == os.readlink(target)
        assert os.path.samefile(filename, target)

    def test_atomic_symlink_uses_relative_path_for_directory(self, tmp_path):
        target_path = str(tmp_path / factory.make_name("dir"))
        os.makedirs(target_path)  # The target is a directory.
        parent_dir = tmp_path / factory.make_name("parent")
        os.makedirs(str(parent_dir))
        link_path = os.path.join(str(parent_dir), factory.make_name("sub"))
        atomic_symlink(target_path, link_path)
        assert os.path.relpath(
            target_path, os.path.dirname(link_path)
        ) == os.readlink(link_path)
        assert os.path.samefile(target_path, link_path)


class TestGetMAASProvisionCommand:
    def test_returns_maas_rack_for_snap(self, mocker):
        mocker.patch.object(provisioningserver.config, "is_dev_environment")
        provisioningserver.config.is_dev_environment.return_value = False
        mocker.patch.object(os, "environ", {"SNAP": "/snap/maas/10"})
        assert get_maas_common_command() == "/snap/maas/10/usr/bin/maas-rack"

    def test_returns_full_path_for_development(self, mocker):
        mocker.patch.object(provisioningserver.config, "is_dev_environment")
        provisioningserver.config.is_dev_environment.return_value = True
        assert dev_root.rstrip("/") + "/usr/bin/maas-common" == (
            get_maas_common_command()
        )


def load_script(filename):
    """Load the Python script at `filename` into a new module."""
    modname = os.path.relpath(filename, dev_root).replace(os.sep, ".")
    module = types.ModuleType(modname)
    with tokenize.open(filename) as fd:
        code = compile(fd.read(), filename, "exec", dont_inherit=True)
        exec(code, module.__dict__, module.__dict__)
    return module


class TestSudoWriteFileScript:
    """Tests for `scripts/maas-write-file`."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.script_path = os.path.join(
            dev_root, "package-files/usr/lib/maas/maas-write-file"
        )
        self.script = load_script(self.script_path)
        self.script.atomic_write = create_autospec(self.script.atomic_write)

    def test_allowed_list_is_a_non_empty_set_of_file_names(self):
        assert isinstance(self.script.WRITABLE_FILES, set)
        assert len(self.script.WRITABLE_FILES) > 0
        for filename in self.script.WRITABLE_FILES:
            assert isinstance(filename, str)

    def test_accepts_file_names_on_allowed_list(self):
        calls_expected = []
        for filename in self.script.WRITABLE_FILES:
            content = factory.make_bytes()  # It's binary safe.
            mode = random.randint(0o000, 0o777)  # Inclusive of endpoints.
            args = self.script.arg_parser.parse_args([filename, oct(mode)])
            self.script.main(args, io.BytesIO(content))
            calls_expected.append(
                call(content, filename, overwrite=True, mode=mode)
            )
        self.script.atomic_write.assert_has_calls(calls_expected)

    def test_rejects_file_name_not_on_allowed_list(self):
        filename = factory.make_name("/some/where", sep="/")
        mode = random.randint(0o000, 0o777)  # Inclusive of endpoints.
        args = self.script.arg_parser.parse_args([filename, oct(mode)])
        with CaptureStandardIO() as stdio:
            with pytest.raises(SystemExit) as excinfo:
                self.script.main(args, io.BytesIO())
        assert excinfo.value.code > 0
        self.script.atomic_write.assert_not_called()
        assert "" == stdio.getOutput()
        assert re.search(
            r"(?s)^usage: .* Given filename .* is not in the allowed list. Choose from: ",
            stdio.getError(),
        )

    def test_rejects_file_mode_with_high_bits_set(self):
        filename = random.choice(list(self.script.WRITABLE_FILES))
        mode = random.randint(0o1000, 0o7777)  # Inclusive of endpoints.
        args = self.script.arg_parser.parse_args([filename, oct(mode)])
        with CaptureStandardIO() as stdio:
            with pytest.raises(SystemExit) as excinfo:
                self.script.main(args, io.BytesIO())
        assert excinfo.value.code > 0
        self.script.atomic_write.assert_not_called()
        assert "" == stdio.getOutput()
        assert re.search(
            rf"(?s)^usage: .* Given file mode {oct(mode)} is not permitted; only permission bits may be set",
            stdio.getError(),
        )


class TestSudoDeleteFileScript:
    """Tests for `scripts/maas-delete-file`."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.script_path = os.path.join(
            dev_root, "package-files/usr/lib/maas/maas-delete-file"
        )
        self.script = load_script(self.script_path)
        self.script.atomic_delete = create_autospec(self.script.atomic_delete)

    def test_allowed_list_is_a_non_empty_set_of_file_names(self):
        assert isinstance(self.script.DELETABLE_FILES, set)
        assert len(self.script.DELETABLE_FILES) > 0
        for filename in self.script.DELETABLE_FILES:
            assert isinstance(filename, str)

    def test_accepts_file_names_on_allowed_list(self):
        calls_expected = []
        for filename in self.script.DELETABLE_FILES:
            args = self.script.arg_parser.parse_args([filename])
            self.script.main(args)
            calls_expected.append(call(filename))
        self.script.atomic_delete.assert_has_calls(calls_expected)

    def test_is_okay_when_the_file_does_not_exist(self):
        filename = random.choice(list(self.script.DELETABLE_FILES))
        args = self.script.arg_parser.parse_args([filename])
        self.script.atomic_delete.side_effect = FileNotFoundError
        self.script.main(args)
        self.script.atomic_delete.assert_called_once_with(filename)

    def test_rejects_file_name_not_on_allowed_list(self):
        filename = factory.make_name("/some/where", sep="/")
        args = self.script.arg_parser.parse_args([filename])
        with CaptureStandardIO() as stdio:
            with pytest.raises(SystemExit) as excinfo:
                self.script.main(args)
        assert excinfo.value.code > 0
        self.script.atomic_delete.assert_not_called()
        assert "" == stdio.getOutput()
        assert re.search(
            rf"(?s)usage: .* Given filename {filename} is not in the allowed list. Choose from: .*",
            stdio.getError(),
        )


class TestReadTextFile:
    def test_reads_file(self, tmp_path):
        text = factory.make_string()
        assert text == read_text_file(_make_file(tmp_path, contents=text))

    def test_defaults_to_utf8(self, tmp_path):
        # Test input: "registered trademark" (ringed R) symbol.
        text = "\xae"
        assert text == read_text_file(
            _make_file(tmp_path, contents=text.encode("utf-8"))
        )

    def test_uses_given_encoding(self, tmp_path):
        # Test input: "registered trademark" (ringed R) symbol.
        text = "\xae"
        assert text == read_text_file(
            _make_file(tmp_path, contents=text.encode("utf-16")),
            encoding="utf-16",
        )


class TestWriteTextFile:
    def test_creates_file(self, tmp_path):
        path = os.path.join(str(tmp_path), factory.make_name("text"))
        text = factory.make_string()
        write_text_file(path, text)
        with open(path, "rb") as fh:
            assert fh.read().decode("ascii") == text

    def test_overwrites_file(self, tmp_path):
        path = _make_file(tmp_path, contents="original text")
        text = factory.make_string()
        write_text_file(path, text)
        with open(path, "rb") as fh:
            assert fh.read().decode("ascii") == text

    def test_defaults_to_utf8(self, tmp_path):
        path = _make_file(tmp_path)
        # Test input: "registered trademark" (ringed R) symbol.
        text = "\xae"
        write_text_file(path, text)
        with open(path, encoding="utf-8") as fd:
            assert text == fd.read()

    def test_uses_given_encoding(self, tmp_path):
        path = _make_file(tmp_path)
        # Test input: "registered trademark" (ringed R) symbol.
        text = "\xae"
        write_text_file(path, text, encoding="utf-16")
        with open(path, encoding="utf-16") as fd:
            assert text == fd.read()


@pytest.mark.parametrize(
    "locktype",
    [FileLock, RunLock, SystemLock, NamedLock],
    ids=["FileLock", "RunLock", "SystemLock", "NamedLock"],
)
class TestSystemLocks:
    """Tests for `SystemLock` and its children."""

    @pytest.fixture(autouse=True)
    def _setup(self, mocker, tmp_path):
        self.mocker = mocker
        self.tmp_path = tmp_path

    def make_lock(self, locktype):
        if locktype is NamedLock:
            lockname = factory.make_name("lock")
            return locktype(lockname)
        else:
            lockdir = self.tmp_path
            lockpath = os.path.join(
                str(lockdir), factory.make_name("lockfile")
            )
            return locktype(lockpath)

    def ensure_global_lock_held_when_locking_and_unlocking(
        self, lock, locktype
    ):
        # Patch the lock to check that PROCESS_LOCK is held when doing IO.

        def do_lock():
            assert locktype.PROCESS_LOCK.locked()
            return True

        self.mocker.patch.object(lock._fslock, "lock").side_effect = do_lock

        def do_unlock():
            assert locktype.PROCESS_LOCK.locked()

        self.mocker.patch.object(
            lock._fslock, "unlock"
        ).side_effect = do_unlock

    def test_path_is_read_only(self, locktype):
        lock = self.make_lock(locktype)
        with pytest.raises(AttributeError):
            lock.path = factory.make_name()

    def test_holds_file_system_lock(self, locktype):
        lock = self.make_lock(locktype)
        assert not lockfile.isLocked(lock.path)
        with lock:
            assert lockfile.isLocked(lock.path)
        assert not lockfile.isLocked(lock.path)

    def test_is_locked_reports_accurately(self, locktype):
        lock = self.make_lock(locktype)
        assert not lock.is_locked()
        with lock:
            assert lock.is_locked()
        assert not lock.is_locked()

    def test_is_locked_holds_global_lock(self, locktype):
        lock = self.make_lock(locktype)
        PROCESS_LOCK = self.mocker.patch.object(locktype, "PROCESS_LOCK")
        assert not lock.is_locked()
        PROCESS_LOCK.__enter__.assert_called_once_with()
        PROCESS_LOCK.__exit__.assert_called_once_with(None, None, None)

    def test_cannot_be_acquired_twice(self, locktype):
        """
        `SystemLock` and its kin do not suffer from a bug that afflicts
        ``lockfile`` (https://pypi.python.org/pypi/lockfile):

          >>> from lockfile import FileLock
          >>> with FileLock('foo'):
          ...     with FileLock('foo'):
          ...         print("Hello!")
          ...
          Hello!
          Traceback (most recent call last):
            File "<stdin>", line 3, in <module>
            File ".../dist-packages/lockfile.py", line 230, in __exit__
              self.release()
            File ".../dist-packages/lockfile.py", line 271, in release
              raise NotLocked
          lockfile.NotLocked

        """
        lock = self.make_lock(locktype)
        with lock:
            with pytest.raises(locktype.NotAvailable, match=lock.path):
                with lock:
                    pass

    def test_locks_and_unlocks_while_holding_global_lock(self, locktype):
        lock = self.make_lock(locktype)
        self.ensure_global_lock_held_when_locking_and_unlocking(lock, locktype)

        with lock:
            assert not locktype.PROCESS_LOCK.locked()

        lock._fslock.lock.assert_called_once_with()
        lock._fslock.unlock.assert_called_once_with()

    def test_wait_waits_until_lock_can_be_acquired(self, locktype):
        clock = self.mocker.patch.object(internet, "reactor", Clock())
        sleep = self.mocker.patch.object(fs_module, "sleep")
        sleep.side_effect = clock.advance

        lock = self.make_lock(locktype)
        do_lock = self.mocker.patch.object(lock._fslock, "lock")
        do_unlock = self.mocker.patch.object(lock._fslock, "unlock")

        do_lock.side_effect = [False, False, True]

        with lock.wait(10):
            do_lock.assert_has_calls([call(), call(), call()])
            sleep.assert_has_calls([call(1.0), call(1.0)])
            do_unlock.assert_not_called()

        do_unlock.assert_called_once_with()

    def test_wait_raises_exception_when_time_has_run_out(self, locktype):
        clock = self.mocker.patch.object(internet, "reactor", Clock())
        sleep = self.mocker.patch.object(fs_module, "sleep")
        sleep.side_effect = clock.advance

        lock = self.make_lock(locktype)
        do_lock = self.mocker.patch.object(lock._fslock, "lock")
        do_unlock = self.mocker.patch.object(lock._fslock, "unlock")

        do_lock.return_value = False

        with pytest.raises(locktype.NotAvailable, match=lock.path):
            with lock.wait(0.2):
                pass

        do_lock.assert_has_calls([call(), call(), call()])
        sleep.assert_has_calls([call(0.1), call(0.1)])
        do_unlock.assert_not_called()

    def test_wait_locks_and_unlocks_while_holding_global_lock(self, locktype):
        lock = self.make_lock(locktype)
        self.ensure_global_lock_held_when_locking_and_unlocking(lock, locktype)

        with lock.wait(10):
            assert not locktype.PROCESS_LOCK.locked()

        lock._fslock.lock.assert_called_once_with()
        lock._fslock.unlock.assert_called_once_with()

    def test_context_is_implemented_using_acquire_and_release(self, locktype):
        # Thus implying that all the earlier tests are valid for both.
        lock = self.make_lock(locktype)
        acquire = self.mocker.patch.object(lock, "acquire")
        release = self.mocker.patch.object(lock, "release")

        acquire.assert_not_called()
        release.assert_not_called()
        # Not locked at first, naturally.
        assert not lock.is_locked()
        lock.acquire()
        try:
            acquire.assert_called_once_with()
            release.assert_not_called()
            # The lock is not locked because — ah ha! — we've patched out the
            # method that does the locking.
            assert not lock.is_locked()
        finally:
            lock.release()
        acquire.assert_called_once_with()
        release.assert_called_once_with()
        # Still not locked, without surprise.
        assert not lock.is_locked()


class TestSystemLock:
    """Tests specific to `SystemLock`."""

    def test_path(self, tmp_path):
        filename = _make_file(tmp_path)
        observed = SystemLock(filename).path
        assert filename == observed


class TestFileLock:
    """Tests specific to `FileLock`."""

    def test_path(self, tmp_path):
        filename = _make_file(tmp_path)
        expected = filename + ".lock"
        observed = FileLock(filename).path
        assert expected == observed


class TestRunLock:
    """Tests specific to `RunLock`."""

    def test_string_path(self):
        filename = "/foo/bar/123:456.txt"
        expected = get_tentative_data_path(
            "/run/lock/maas@foo:bar:123::456.txt"
        )
        observed = RunLock(filename).path
        assert expected == observed

    def test_byte_path(self):
        filename = b"/foo/bar/123:456.txt"
        expected = get_tentative_data_path(
            "/run/lock/maas@foo:bar:123::456.txt"
        )
        observed = RunLock(filename).path
        assert expected == observed


class TestNamedLock:
    """Tests specific to `NamedLock`."""

    def test_string_name(self):
        name = factory.make_name("lock")
        expected = get_tentative_data_path("/run/lock/maas:" + name)
        observed = NamedLock(name).path
        assert expected == observed

    def test_byte_name_is_rejected(self):
        name = factory.make_name("lock").encode("ascii")
        with pytest.raises(TypeError) as excinfo:
            NamedLock(name)
        assert "Lock name must be str, not bytes" == str(excinfo.value)

    def test_name_rejects_unacceptable_characters(self):
        # This demonstrates that validation is performed, but it is not an
        # exhaustive test by any means.
        with pytest.raises(ValueError):
            NamedLock("foo:bar")
        with pytest.raises(ValueError):
            NamedLock("foo^bar")
        with pytest.raises(ValueError):
            NamedLock("(foobar)")
        with pytest.raises(ValueError):
            NamedLock("foo*bar")
        with pytest.raises(ValueError):
            NamedLock("foo/bar")
        with pytest.raises(ValueError):
            NamedLock("foo=bar")
        # The error message contains all of the unacceptable characters.
        with pytest.raises(ValueError) as excinfo:
            NamedLock("[foo;bar]")
        assert "Lock name contains illegal characters: ;[]" == str(
            excinfo.value
        )
