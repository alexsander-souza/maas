# Copyright 2017-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test generation of commissioning user data."""

import base64
import email
import re

import pytest

from maasserver.enum import NODE_STATUS
from maasserver.testing.factory import factory
from metadataserver.user_data import (
    generate_user_data_for_poweroff,
    generate_user_data_for_status,
)
from tests.fixtures import mock_openfga, mock_start_workflows  # noqa: F401

CLOUD_INIT_CONTENT_TYPE = 'text/x-shellscript; charset="utf-8"'
CLOUD_INIT_TRANSFER_ENCODING = "base64"
CLOUD_INIT_DISPOSITION = 'attachment; filename="user_data.sh"'


def parse_user_data(user_data):
    parsed_data = email.message_from_string(user_data.decode("utf-8"))
    assert parsed_data.is_multipart()
    user_data_script = parsed_data.get_payload()[0]
    assert user_data_script["Content-Type"] == CLOUD_INIT_CONTENT_TYPE
    assert (
        user_data_script["Content-Transfer-Encoding"]
        == CLOUD_INIT_TRANSFER_ENCODING
    )
    assert user_data_script["Content-Disposition"] == CLOUD_INIT_DISPOSITION
    return base64.b64decode(user_data_script.get_payload())


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
class TestGenerateUserData:
    def test_generate_user_data_produces_enlist_script(self):
        # generate_user_data produces a commissioning script which contains
        # both definitions and use of various commands in python.
        rack = factory.make_RackController()
        user_data = generate_user_data_for_status(
            None,
            NODE_STATUS.NEW,
            rack_controller=rack,
            extra_content={"enlist_commissioning": True},
        )
        decoded = parse_user_data(user_data)
        for needle in (
            b"find_creds_cfg()",
            b"main()",
            b"# maas-run-remote-scripts -",
        ):
            assert needle in decoded

    def test_generate_user_data_produces_commissioning_script(self):
        # generate_user_data produces a commissioning script which contains
        # both definitions and use of various commands in python.
        node = factory.make_Node()
        user_data = generate_user_data_for_status(
            node, status=NODE_STATUS.COMMISSIONING
        )
        decoded = parse_user_data(user_data)
        for needle in (
            b"find_creds_cfg()",
            b"main()",
            b"# maas-run-remote-scripts -",
        ):
            assert needle in decoded

    def test_generate_user_data_produces_testing_script(self):
        node = factory.make_Node()
        user_data = generate_user_data_for_status(
            node, status=NODE_STATUS.TESTING
        )
        decoded = parse_user_data(user_data)
        for needle in (
            b"export DEBIAN_FRONTEND=noninteractive",
            b"maas-run-remote-scripts",
            b"def signal",
            b"def download_and_extract_tar",
        ):
            assert needle in decoded

    def test_generate_user_data_produces_rescue_mode_script(self):
        node = factory.make_Node()
        user_data = generate_user_data_for_status(
            node, status=NODE_STATUS.RESCUE_MODE
        )
        decoded = parse_user_data(user_data)
        for needle in (
            b"export DEBIAN_FRONTEND=noninteractive",
            b"maas-run-remote-scripts",
            b"def signal",
            b"def download_and_extract_tar",
        ):
            assert needle in decoded

    def test_generate_user_data_produces_poweroff_script(self):
        node = factory.make_Node()
        user_data = generate_user_data_for_poweroff(node)
        decoded = parse_user_data(user_data)
        assert b"Powering node off." in decoded


@pytest.mark.usefixtures("maasdb", "mock_openfga", "mock_start_workflows")
@pytest.mark.parametrize(
    "extra_content,maas_wipe",
    [
        pytest.param(
            {"secure_erase": True, "quick_erase": True},
            rb"(?ms)^\s*maas-wipe\s--secure-erase\s--quick-erase$\s*signal\sOK",
            id="secure_and_quick",
        ),
        pytest.param(
            {"secure_erase": True, "quick_erase": False},
            rb"(?ms)^\s*maas-wipe\s--secure-erase\s$\s*signal\sOK",
            id="secure_not_quick",
        ),
        pytest.param(
            {"secure_erase": False, "quick_erase": True},
            rb"(?ms)^\s*maas-wipe\s\s--quick-erase$\s*signal\sOK",
            id="quick_not_secure",
        ),
        pytest.param(
            {"secure_erase": False, "quick_erase": False},
            rb"(?ms)^\s*maas-wipe\s\s$\s*signal\sOK",
            id="not_quick_not_secure",
        ),
    ],
)
class TestDiskErasingUserData:
    def test_generate_user_data_produces_disk_erase_script(
        self, extra_content, maas_wipe
    ):
        node = factory.make_Node()
        user_data = generate_user_data_for_status(
            node,
            status=NODE_STATUS.DISK_ERASING,
            extra_content=extra_content,
        )
        payload = parse_user_data(user_data)
        for needle in (
            b"export DEBIAN_FRONTEND=noninteractive",
            b"maas-wipe",
            b"def signal",
            b"VALID_STATUS =",
            b"class WipeError",
        ):
            assert needle in payload
        assert re.search(maas_wipe, payload)
