# Copyright 2014-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for converters utilities."""

from textwrap import dedent

import pytest

from maasserver.utils.converters import (
    machine_readable_bytes,
    round_size_to_nearest_block,
    systemd_interval_to_calendar,
    XMLToYAML,
)


class TestXMLToYAML:
    def test_xml_to_yaml_converts_xml(self):
        # This test is similar to the test above but this one
        # checks that tags with colons works as expected.
        xml = """
        <list xmlns:lldp="lldp" xmlns:lshw="lshw">
         <lldp:lldp label="LLDP neighbors"/>
         <lshw:list>Some Content</lshw:list>
        </list>
        """
        expected_result = dedent(
            """\
        - list:
          - lldp:lldp:
            label: LLDP neighbors
          - lshw:list:
            Some Content
        """
        )
        yml = XMLToYAML(xml)
        assert yml.convert() == expected_result


class TestMachineReadableBytes:
    """Testing the human->machine byte count converter"""

    def test_suffixes(self):
        assert machine_readable_bytes("987") == 987
        assert machine_readable_bytes("987K") == 987000
        assert machine_readable_bytes("987M") == 987000000
        assert machine_readable_bytes("987G") == 987000000000
        assert machine_readable_bytes("987T") == 987000000000000
        assert machine_readable_bytes("987P") == 987000000000000000
        assert machine_readable_bytes("987E") == 987000000000000000000
        assert machine_readable_bytes("987k") == 987000
        assert machine_readable_bytes("987m") == 987000000
        assert machine_readable_bytes("987g") == 987000000000
        assert machine_readable_bytes("987t") == 987000000000000
        assert machine_readable_bytes("987p") == 987000000000000000
        assert machine_readable_bytes("987e") == 987000000000000000000

        with pytest.raises(ValueError):
            machine_readable_bytes("987Z")


class TestRoundSizeToNearestBlock:
    def test_round_up_adds_extra_block(self):
        block_size = 4096
        size = block_size + 1
        assert (
            round_size_to_nearest_block(size, block_size, True)
            == 2 * block_size
        ), "Should add an extra block to the size."

    def test_round_up_doesnt_add_extra_block(self):
        block_size = 4096
        size = block_size
        assert round_size_to_nearest_block(size, block_size, True) == size, (
            "Shouldn't add an extra block to the size."
        )

    def test_round_down_removes_block(self):
        block_size = 4096
        size = block_size + 1
        assert (
            round_size_to_nearest_block(size, block_size, False)
            == 1 * block_size
        ), "Should remove block from the size."

    def test_round_down_doesnt_remove_block(self):
        block_size = 4096
        size = block_size * 2
        assert round_size_to_nearest_block(size, block_size, False) == size, (
            "Shouldn't remove a block from the size."
        )


class TestSystemdIntervalToCalendar:
    def test_every_2_hours(self):
        interval = "2h"
        assert systemd_interval_to_calendar(interval) == "*-*-* 00/2:00:00"

    def test_every_hour(self):
        interval = "1h"
        assert systemd_interval_to_calendar(interval) == "*-*-* *:00:00"

    def test_every_hour_and_a_half(self):
        interval = "1h 30m"
        assert systemd_interval_to_calendar(interval) == "*-*-* *:00/30:00"

    def test_every_30_minutes(self):
        interval = "30m"
        assert systemd_interval_to_calendar(interval) == "*-*-* *:00/30:00"

    def test_every_30_minutes_5_seconds(self):
        interval = "30m 5s"
        assert systemd_interval_to_calendar(interval) == "*-*-* *:00/30:00/5"

    def test_every_15_seconds(self):
        interval = "15s"
        assert systemd_interval_to_calendar(interval) == "*-*-* *:*:00/15"
