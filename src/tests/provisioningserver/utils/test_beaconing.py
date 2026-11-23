# Copyright 2016-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for ``provisioningserver.utils.beaconing``."""

from argparse import ArgumentParser
from collections import OrderedDict
from gzip import compress
import io
import random
import struct
import subprocess
from tempfile import NamedTemporaryFile
import time
from unittest.mock import Mock

import pytest

from maastesting.factory import factory
from provisioningserver.security import fernet_encrypt_psk, MissingSharedSecret
from provisioningserver.utils import beaconing as beaconing_module
from provisioningserver.utils.beaconing import (
    add_arguments,
    age_out_ulid_queue,
    BEACON_HEADER_FORMAT_V1,
    beacon_to_json,
    BEACON_TYPES,
    BeaconingPacket,
    BeaconPayload,
    create_beacon_payload,
    InvalidBeaconingPacket,
    read_beacon_payload,
    run,
    ulid_to_timestamp,
)
from provisioningserver.utils.env import MAAS_SECRET
from provisioningserver.utils.script import ActionScriptError
from tests.provisioningserver.test_security import SharedSecretTestCase


class TestULIDToTimestamp:
    def test_round_trip_preserves_timestamp(self):
        from ulid import ULID

        before = time.time()
        ulid_str = str(ULID())
        after = time.time()
        extracted = ulid_to_timestamp(ulid_str)
        # ULID timestamp must be bracketed by the before/after wall-clock values.
        assert extracted >= before - 0.001
        assert extracted <= after + 0.001


class TestBeaconToJSON:
    """Tests for `beacon_to_json()` function."""

    def test_preserves_version_type_and_payload__discards_bytes(self):
        test_bytes = factory.make_bytes()
        test_version = factory.make_string()
        test_type = factory.make_string()
        test_payload = {factory.make_string(): factory.make_string()}
        beacon = BeaconPayload(
            test_bytes, test_version, test_type, test_payload
        )
        beacon_json = beacon_to_json(beacon)
        assert test_version == beacon_json["version"]
        assert test_type == beacon_json["type"]
        assert test_payload == beacon_json["payload"]
        assert "bytes" not in beacon_json
        assert len(beacon_json) == 3


class TestCreateBeaconPayload(SharedSecretTestCase):
    _maas_secret_set = False

    @pytest.fixture(autouse=True)
    def _setup(self):
        MAAS_SECRET.set(factory.make_bytes())
        yield

    def test_requires_maas_shared_secret_for_inner_data_payload(self):
        MAAS_SECRET.set(None)
        with pytest.raises(
            MissingSharedSecret, match=".*shared secret not found.*"
        ):
            create_beacon_payload("solicitation", payload={})

    def test_returns_beaconpayload_namedtuple(self):
        beacon = create_beacon_payload("solicitation")
        assert isinstance(beacon.bytes, bytes)
        assert beacon.payload is None
        assert "solicitation" == beacon.type
        assert beacon.version == 2

    def test_succeeds_when_shared_secret_present(self):
        beacon = create_beacon_payload("solicitation", payload={})
        assert "solicitation" == beacon.type
        assert BEACON_TYPES["solicitation"] == beacon.payload["type"]

    def test_supplements_data_and_returns_complete_data(self):
        random_type = random.choice(list(BEACON_TYPES.keys()))
        random_key = factory.make_string(prefix="_")
        random_value = factory.make_string()
        beacon = create_beacon_payload(
            random_type, payload={random_key: random_value}
        )
        # Ensure a valid ULID was added.
        ulid_str = beacon.payload["ulid"]
        assert len(ulid_str) == 26
        assert all(c in "0123456789ABCDEFGHJKMNPQRSTVWXYZ" for c in ulid_str)
        assert random_type == beacon.type
        # The type is replicated here for authentication purposes.
        assert BEACON_TYPES[random_type] == beacon.payload["type"]
        assert random_value == beacon.payload[random_key]

    def test_creates_packet_that_can_decode(self):
        random_type = random.choice(list(BEACON_TYPES.keys()))
        random_key = factory.make_string(prefix="_")
        random_value = factory.make_string()
        packet_bytes, _, _, _ = create_beacon_payload(
            random_type, payload={random_key: random_value}
        )
        decrypted = read_beacon_payload(packet_bytes)
        assert random_type == decrypted.type
        assert random_value == decrypted.payload[random_key]


def _make_beacon_payload(version=1, type_code=1, length=None, payload=None):
    if payload is None:
        payload = b""
    if length is None:
        length = len(payload)
    packet = struct.pack(BEACON_HEADER_FORMAT_V1, version, type_code, length)
    return packet + payload


class TestReadBeaconPayload(SharedSecretTestCase):
    _maas_secret_set = False

    @pytest.fixture(autouse=True)
    def _setup(self):
        MAAS_SECRET.set(factory.make_bytes())
        yield

    def test_raises_if_packet_too_small(self):
        with pytest.raises(
            InvalidBeaconingPacket, match=".*packet must be at least 4 bytes.*"
        ):
            read_beacon_payload(b"")

    def test_raises_if_payload_too_small(self):
        packet = _make_beacon_payload(payload=b"1234")[:6]
        with pytest.raises(
            InvalidBeaconingPacket, match=".*expected 4 bytes, got 2 bytes.*"
        ):
            read_beacon_payload(packet)

    def test_raises_when_version_incorrect(self):
        packet = _make_beacon_payload(version=0xFE)
        with pytest.raises(
            InvalidBeaconingPacket, match=".*Unknown beacon version.*"
        ):
            read_beacon_payload(packet)

    def test_raises_when_inner_payload_does_not_decrypt(self):
        packet = _make_beacon_payload(payload=b"\xfe")
        with pytest.raises(
            InvalidBeaconingPacket, match=".*Failed to decrypt.*"
        ):
            read_beacon_payload(packet)

    def test_raises_when_inner_encapsulation_does_not_decompress(self):
        packet = _make_beacon_payload(
            payload=fernet_encrypt_psk("\n\n", raw=True)
        )
        with pytest.raises(
            InvalidBeaconingPacket, match=".*Failed to decompress.*"
        ):
            read_beacon_payload(packet)

    def test_raises_when_inner_encapsulation_is_not_bson(self):
        payload = fernet_encrypt_psk(compress(b"\n\n"), raw=True)
        packet = _make_beacon_payload(payload=payload)
        with pytest.raises(
            InvalidBeaconingPacket, match=".*beacon payload is not BSON.*"
        ):
            read_beacon_payload(packet)


class TestReadBeaconPayloadVersions(SharedSecretTestCase):
    _maas_secret_set = False

    @pytest.fixture(autouse=True)
    def _setup(self):
        MAAS_SECRET.set(factory.make_bytes())
        yield

    def test_accepts_version_1_packet(self):
        # v1 is decoded cleanly — dropping is the caller's responsibility.
        beacon = create_beacon_payload("solicitation", payload={}, version=1)
        result = read_beacon_payload(beacon.bytes)
        assert result.version == 1

    def test_accepts_version_2_packet(self):
        beacon = create_beacon_payload("solicitation", payload={})
        assert beacon.version == 2
        result = read_beacon_payload(beacon.bytes)
        assert result.version == 2

    def test_raises_for_unknown_version(self):
        packet = _make_beacon_payload(version=0xFE)
        with pytest.raises(
            InvalidBeaconingPacket, match=".*Unknown beacon version.*"
        ):
            read_beacon_payload(packet)


class TestBeaconingPacket:
    def test_is_valid__succeeds_for_valid_payload(self):
        beacon = create_beacon_payload("solicitation")
        beacon_packet = BeaconingPacket(beacon.bytes)
        assert beacon_packet.valid

    def test_is_valid__fails_for_invalid_payload(self):
        beacon = BeaconingPacket(b"\n\n\n\n")
        assert not beacon.valid


BEACON_PCAP = (
    b"\xd4\xc3\xb2\xa1\x02\x00\x04\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00@\x00\x00\x01\x00\x00\x00v\xe19Y\xadF\x08\x00^\x00\x00\x00^\x00\x00"
    b"\x00\x01\x00^\x00\x00v\x00\x16>\x91zz\x08\x00E\x00\x00P\xe2E@\x00\x01"
    b"\x11\xe0\xce\xac\x10*\x02\xe0\x00\x00v\xda\xc2\x14x\x00<h(4\x00\x00\x00"
    b"\x02uuid\x00%\x00\x00\x0000000000-0000-0000-0000-000000000000\x00\x00"
)


class TestObserveBeaconsCommand:
    """Tests for `maas-rack observe-beacons`."""

    def test_requires_input_file(self):
        parser = ArgumentParser()
        add_arguments(parser)
        args = parser.parse_args([])
        with pytest.raises(
            ActionScriptError, match=".*Required argument: interface.*"
        ):
            run(args)

    def test_calls_subprocess_for_interface(self, mocker):
        parser = ArgumentParser()
        add_arguments(parser)
        args = parser.parse_args(["eth0"])
        popen = mocker.patch.object(beaconing_module.subprocess, "Popen")
        popen.return_value.poll = Mock()
        popen.return_value.poll.return_value = None
        popen.return_value.stdout = io.BytesIO(BEACON_PCAP)
        output = io.StringIO()
        run(args, output=output)
        popen.assert_called_once_with(
            ["/usr/lib/maas/beacon-monitor", "eth0"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
        )

    def test_checks_for_pipe(self, mocker):
        parser = ArgumentParser()
        add_arguments(parser)
        args = parser.parse_args(["--input-file", "-"])
        output = io.StringIO()
        stdin = Mock()
        fstat = mocker.patch.object(beaconing_module.os, "fstat")
        fstat.return_value.st_mode = None
        stat = mocker.patch.object(beaconing_module.stat, "S_ISFIFO")
        stat.return_value = False
        with pytest.raises(
            ActionScriptError, match="Expected stdin to be a pipe"
        ):
            run(args, output=output, stdin=stdin)

    def test_allows_pipe_input(self, mocker):
        parser = ArgumentParser()
        add_arguments(parser)
        args = parser.parse_args(["--input-file", "-"])
        output = io.StringIO()
        stdin = Mock()
        fstat = mocker.patch.object(beaconing_module.os, "fstat")
        fstat.return_value.st_mode = None
        stat = mocker.patch.object(beaconing_module.stat, "S_ISFIFO")
        stat.return_value = True
        stdin_buffer = io.BytesIO(BEACON_PCAP)
        run(args, output=output, stdin=stdin, stdin_buffer=stdin_buffer)

    def test_allows_file_input(self):
        with NamedTemporaryFile("wb") as f:
            parser = ArgumentParser()
            add_arguments(parser)
            f.write(BEACON_PCAP)
            f.flush()
            args = parser.parse_args(["--input-file", f.name])
            output = io.StringIO()
            run(args, output=output)

    def test_raises_systemexit_observe_beaconing_return_code(self, mocker):
        parser = ArgumentParser()
        add_arguments(parser)
        args = parser.parse_args(["eth0"])
        popen = mocker.patch.object(beaconing_module.subprocess, "Popen")
        popen.return_value.poll = Mock()
        popen.return_value.poll.return_value = None
        popen.return_value.stdout = io.BytesIO(BEACON_PCAP)
        output = io.StringIO()
        observe_beaconing_packets = mocker.patch.object(
            beaconing_module, "observe_beaconing_packets"
        )
        observe_beaconing_packets.return_value = 37
        with pytest.raises(SystemExit, match=".*37.*"):
            run(args, output=output)

    def test_raises_systemexit_poll_result(self, mocker):
        parser = ArgumentParser()
        add_arguments(parser)
        args = parser.parse_args(["eth0"])
        popen = mocker.patch.object(beaconing_module.subprocess, "Popen")
        popen.return_value.poll = Mock()
        popen.return_value.poll.return_value = None
        popen.return_value.stdout = io.BytesIO(BEACON_PCAP)
        output = io.StringIO()
        observe_beaconing_packets = mocker.patch.object(
            beaconing_module, "observe_beaconing_packets"
        )
        observe_beaconing_packets.return_value = None
        popen.return_value.poll = Mock()
        popen.return_value.poll.return_value = 42
        with pytest.raises(SystemExit, match=".*42.*"):
            run(args, output=output)

    def test_sets_self_as_process_group_leader(self, mocker):
        exception_type = factory.make_exception_type()
        os = mocker.patch.object(beaconing_module, "os")
        os.setpgrp.side_effect = exception_type
        with pytest.raises(exception_type):
            run([])
        os.setpgrp.assert_called_once_with()


class TestAgeOutULIDQueue:
    """Tests for `age_out_ulid_queue()` function."""

    def test_does_not_remove_fresh_entries(self):
        ulid_now = factory.make_ULID_with_timestamp(time.time())
        queue = OrderedDict()
        queue[ulid_now] = {}
        assert len(queue) == 1
        age_out_ulid_queue(queue)
        assert len(queue) == 1

    def test_keeps_entries_from_the_reasonable_past(self):
        ulid = factory.make_ULID_with_timestamp(time.time() - 60.0)
        queue = OrderedDict()
        queue[ulid] = {}
        age_out_ulid_queue(queue)
        assert len(queue) == 1

    def test_removes_entries_from_the_past(self):
        ulid = factory.make_ULID_with_timestamp(time.time() - 123.0)
        queue = OrderedDict()
        queue[ulid] = {}
        age_out_ulid_queue(queue)
        assert queue == {}

    def test_removes_entries_from_the_future(self):
        ulid = factory.make_ULID_with_timestamp(time.time() + 123.0)
        queue = OrderedDict()
        queue[ulid] = {}
        age_out_ulid_queue(queue)
        assert queue == {}
