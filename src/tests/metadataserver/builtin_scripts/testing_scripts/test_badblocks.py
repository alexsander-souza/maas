# Copyright 2017-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test badblocks functions."""

import io
import os
import random
from subprocess import PIPE, STDOUT
from textwrap import dedent
from unittest.mock import ANY

import pytest
import yaml

from maastesting.factory import factory
from metadataserver.builtin_scripts.testing_scripts import badblocks

BADBLOCKS = random.randint(0, 1000)
READ_ERRORS = random.randint(0, 1000)
WRITE_ERRORS = random.randint(0, 1000)
COMPARISON_ERRORS = random.randint(0, 1000)
BADBLOCKS_OUTPUT = dedent(
    """
    Checking for bad blocks in non-destructive read-write mode
    From block 0 to 5242879
    Testing with random pattern:
    Pass completed, %s bad blocks found. (%s/%s/%s errors)
    """
    % (BADBLOCKS, READ_ERRORS, WRITE_ERRORS, COMPARISON_ERRORS)
)


class TestRunBadBlocks:
    def test_get_block_size(self, mocker):
        mock_check_output = mocker.patch.object(badblocks, "check_output")
        mocker.patch.object(badblocks, "print")
        block_size = random.randint(512, 4096)
        mock_check_output.return_value = ("%s\n" % block_size).encode()
        assert block_size == badblocks.get_block_size(
            factory.make_name("storage")
        )

    def test_get_parallel_blocks(self, mocker):
        # Most systems will have more than enough memory to test 50000
        # blocks at a time. This test mocks system memory values and
        # lsblk output to verify the function returns the expected value.
        mock_check_output = mocker.patch.object(badblocks, "check_output")
        mocker.patch.object(badblocks, "print")

        def open_side_effect(path, *args, **kwargs):
            if path == "/proc/sys/vm/min_free_kbytes":
                return io.StringIO("110000\n")
            elif path == "/proc/meminfo":
                return io.StringIO(
                    "MemTotal:        8000000 kB\n"
                    "MemFree:         7000000 kB\n"
                )
            else:
                pytest.fail(f"Unexpected file open: {path}")

        mock_open = mocker.patch.object(badblocks, "open")
        mock_open.side_effect = open_side_effect
        # Mock lsblk output with 1 storage device
        mock_check_output.return_value = (
            b"NAME=sda MODEL=TestDisk SERIAL=12345\n"
        )

        assert 50000 == badblocks.get_parallel_blocks(1)

    def test_get_parallel_blocks_limited(self, mocker):
        # Systems with a large amount of disks and not much RAM need to
        # throttle the amount of blocks tested at once. This test verifies
        # the function respects the 50000 block limit when needed.
        mock_check_output = mocker.patch.object(badblocks, "check_output")
        mocker.patch.object(badblocks, "print")

        def open_side_effect(path, *args, **kwargs):
            if path == "/proc/sys/vm/min_free_kbytes":
                return io.StringIO("110000\n")
            elif path == "/proc/meminfo":
                return io.StringIO(
                    "MemTotal:        8000000 kB\n"
                    "MemFree:         7000000 kB\n"
                )
            else:
                pytest.fail(f"Unexpected file open: {path}")

        mock_open = mocker.patch.object(badblocks, "open")
        mock_open.side_effect = open_side_effect
        # Mock lsblk output with 1000 storage devices (many devices)
        mock_check_output.return_value = (
            b"NAME=sda MODEL=TestDisk SERIAL=12345\n" * 1000
        )

        assert 50000 >= badblocks.get_parallel_blocks(1000)

    def test_run_badblocks_nondestructive_and_writes_results_file(
        self, mocker
    ):
        storage = factory.make_name("storage")
        blocksize = random.randint(512, 4096)
        mocker.patch.object(
            badblocks, "get_block_size"
        ).return_value = blocksize
        parallel_blocks = random.randint(1, 50000)
        mocker.patch.object(
            badblocks, "get_parallel_blocks"
        ).return_value = parallel_blocks
        mocker.patch.dict(os.environ, {"RESULT_PATH": factory.make_name()})
        cmd = [
            "sudo",
            "-n",
            "badblocks",
            "-b",
            str(blocksize),
            "-c",
            str(parallel_blocks),
            "-v",
            "-f",
            "-s",
            "-n",
            storage,
        ]
        mock_popen = mocker.patch.object(badblocks, "Popen")
        proc = mock_popen.return_value
        proc.communicate.return_value = (
            BADBLOCKS_OUTPUT.encode("utf-8"),
            None,
        )
        proc.returncode = 0
        mock_open = mocker.patch.object(badblocks, "open")
        mock_open.return_value = io.StringIO()
        mock_yaml_safe_dump = mocker.patch.object(yaml, "safe_dump")
        results = {
            "results": {
                "badblocks": BADBLOCKS,
                "read_errors": READ_ERRORS,
                "write_errors": WRITE_ERRORS,
                "comparison_errors": COMPARISON_ERRORS,
            }
        }

        assert 1 == badblocks.run_badblocks(storage)
        mock_popen.assert_called_once_with(cmd, stdout=PIPE, stderr=STDOUT)
        mock_open.assert_called_once_with(ANY, "w")
        mock_yaml_safe_dump.assert_called_once_with(
            results, mock_open.return_value
        )

    def test_run_badblocks_destructive(self, mocker):
        storage = factory.make_name("storage")
        blocksize = random.randint(512, 4096)
        mocker.patch.object(
            badblocks, "get_block_size"
        ).return_value = blocksize
        parallel_blocks = random.randint(1, 50000)
        mocker.patch.object(
            badblocks, "get_parallel_blocks"
        ).return_value = parallel_blocks
        cmd = [
            "sudo",
            "-n",
            "badblocks",
            "-b",
            str(blocksize),
            "-c",
            str(parallel_blocks),
            "-v",
            "-f",
            "-s",
            "-w",
            storage,
        ]
        mock_popen = mocker.patch.object(badblocks, "Popen")
        proc = mock_popen.return_value
        proc.communicate.return_value = (
            BADBLOCKS_OUTPUT.encode("utf-8"),
            None,
        )
        proc.returncode = 0

        assert 1 == badblocks.run_badblocks(storage, destructive=True)
        mock_popen.assert_called_once_with(cmd, stdout=PIPE, stderr=STDOUT)
