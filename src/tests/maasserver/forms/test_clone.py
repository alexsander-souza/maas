# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for Clone form."""

import random

import pytest

from maasserver.enum import NODE_STATUS
from maasserver.forms.clone import CloneForm
from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestCloneForm:
    def test_empty_errors(self):
        user = factory.make_admin()
        form = CloneForm(user, data={})
        assert not form.is_valid()
        assert form.errors == {
            "source": ["This field is required."],
            "destinations": ["This field is required."],
            "__all__": ["Either storage or interfaces must be true."],
        }

    def test_source_destination_match_error(self):
        user = factory.make_admin()
        source = factory.make_Machine(
            status=random.choice(
                [NODE_STATUS.READY, NODE_STATUS.FAILED_TESTING]
            )
        )
        form = CloneForm(
            user,
            data={
                "source": source.system_id,
                "destinations": [source.system_id],
                "storage": True,
            },
        )
        assert not form.is_valid()
        assert form.errors == {
            "destinations": [
                f"Source machine {source} cannot be a destination machine."
            ]
        }

    def test_destination_smaller_storage(self):
        user = factory.make_admin()
        source = factory.make_Machine(with_boot_disk=False)
        factory.make_PhysicalBlockDevice(
            node=source, size=8 * 1024**3, name="sda"
        )
        destination = factory.make_Machine(
            status=random.choice(
                [NODE_STATUS.READY, NODE_STATUS.FAILED_TESTING]
            ),
            with_boot_disk=False,
        )
        factory.make_PhysicalBlockDevice(
            node=destination, size=4 * 1024**3, name="sda"
        )
        form = CloneForm(
            user,
            data={
                "source": source.system_id,
                "destinations": [destination.system_id],
                "storage": True,
            },
        )
        assert not form.is_valid()
        assert form.errors == {
            "destinations": [
                f"{destination} is invalid: "
                "destination boot disk(sda) is smaller than "
                "source boot disk(sda)"
            ]
        }

    def test_multiple_errors(self):
        user = factory.make_admin()
        source = factory.make_Machine(
            status=NODE_STATUS.READY, with_boot_disk=False
        )
        factory.make_PhysicalBlockDevice(
            node=source, size=8 * 1024**3, name="sda"
        )
        destination = factory.make_Machine(
            status=NODE_STATUS.READY, with_boot_disk=False
        )
        factory.make_PhysicalBlockDevice(
            node=destination, size=4 * 1024**3, name="sda"
        )
        form = CloneForm(
            user,
            data={
                "source": source.system_id,
                "destinations": [source.system_id, destination.system_id],
                "storage": True,
            },
        )
        assert not form.is_valid()
        assert form.errors == {
            "destinations": [
                f"Source machine {source} cannot be a destination machine.",
                f"{destination} is invalid: "
                "destination boot disk(sda) is smaller than "
                "source boot disk(sda)",
            ]
        }

    def test_destination_missing_nic(self):
        user = factory.make_admin()
        source = factory.make_Machine(with_boot_disk=False)
        factory.make_Interface(node=source, name="eth0")
        destination = factory.make_Machine(
            status=random.choice(
                [NODE_STATUS.READY, NODE_STATUS.FAILED_TESTING]
            ),
            with_boot_disk=False,
        )
        factory.make_Interface(node=destination, name="eth1")
        form = CloneForm(
            user,
            data={
                "source": source.system_id,
                "destinations": [destination.system_id],
                "interfaces": True,
            },
        )
        assert not form.is_valid()
        assert form.errors == {
            "destinations": [
                f"{destination} is invalid: "
                "destination node physical interfaces do not match "
                "the source nodes physical interfaces: eth0"
            ]
        }

    def test_permission_errors(self):
        user = factory.make_User()
        source = factory.make_Machine(with_boot_disk=False)
        factory.make_PhysicalBlockDevice(
            node=source, size=8 * 1024**3, name="sda"
        )
        factory.make_Interface(node=source, name="eth0")
        destination = factory.make_Machine(
            status=random.choice(
                [NODE_STATUS.READY, NODE_STATUS.FAILED_TESTING]
            ),
            with_boot_disk=False,
        )
        factory.make_PhysicalBlockDevice(
            node=destination, size=8 * 1024**3, name="sda"
        )
        factory.make_Interface(node=destination, name="eth0")
        form = CloneForm(
            user,
            data={
                "source": source.system_id,
                "destinations": [destination.system_id],
                "storage": True,
                "interfaces": True,
            },
        )
        assert not form.is_valid()
        assert form.errors == {
            "destinations": [
                f"Machine 1 is invalid: Select a valid choice. {destination.system_id} is not one of the available choices."
            ]
        }

    def test_performs_clone(self):
        user = factory.make_admin()
        source = factory.make_Machine(with_boot_disk=False)
        factory.make_PhysicalBlockDevice(
            node=source, size=8 * 1024**3, name="sda"
        )
        factory.make_Interface(node=source, name="eth0")
        destination1 = factory.make_Machine(
            status=random.choice(
                [NODE_STATUS.READY, NODE_STATUS.FAILED_TESTING]
            ),
            with_boot_disk=False,
        )
        factory.make_PhysicalBlockDevice(
            node=destination1, size=8 * 1024**3, name="sda"
        )
        factory.make_Interface(node=destination1, name="eth0")
        destination2 = factory.make_Machine(
            status=random.choice(
                [NODE_STATUS.READY, NODE_STATUS.FAILED_TESTING]
            ),
            with_boot_disk=False,
        )
        factory.make_PhysicalBlockDevice(
            node=destination2, size=8 * 1024**3, name="sda"
        )
        factory.make_Interface(node=destination2, name="eth0")
        form = CloneForm(
            user,
            data={
                "source": source.system_id,
                "destinations": [
                    destination1.system_id,
                    destination2.system_id,
                ],
                "storage": True,
                "interfaces": True,
            },
        )
        assert form.is_valid(), form.errors
        # An exception here will cause the test to fail.
        form.save()
