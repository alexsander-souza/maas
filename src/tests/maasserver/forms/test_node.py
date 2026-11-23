# Copyright 2016-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for node forms."""

import pytest

from maasserver.forms import AdminNodeForm, NodeForm
from maasserver.testing.architecture import (
    make_usable_architecture,
    patch_usable_architectures,
)
from maasserver.testing.factory import factory
from maasserver.utils.orm import post_commit_hooks, reload_object


class _LegacyPatchAdapter:
    def __init__(self, mocker):
        self._mocker = mocker

    def patch(self, target, attribute):
        return self._mocker.patch.object(target, attribute)


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNodeForm:
    def test_contains_limited_set_of_fields(self):
        form = NodeForm()

        assert {"hostname", "domain", "disable_ipv4", "swap_size"} == (
            form.fields.keys()
        )

    def test_accepts_hostname(self, mocker):
        architecture_patcher = _LegacyPatchAdapter(mocker)
        machine = factory.make_Node()
        hostname = factory.make_string()
        patch_usable_architectures(
            architecture_patcher, [machine.architecture]
        )

        form = NodeForm(
            data={
                "hostname": hostname,
                "architecture": make_usable_architecture(architecture_patcher),
            },
            instance=machine,
        )

        with post_commit_hooks:
            form.save()

        assert hostname == machine.hostname

    def test_accepts_domain_by_name(self, mocker):
        machine = factory.make_Node()
        domain = factory.make_Domain()
        patch_usable_architectures(
            _LegacyPatchAdapter(mocker), [machine.architecture]
        )

        form = NodeForm(data={"domain": domain.name}, instance=machine)
        form.save()

        assert domain.name == machine.domain.name

    def test_accepts_domain_by_id(self, mocker):
        machine = factory.make_Node()
        domain = factory.make_Domain()
        patch_usable_architectures(
            _LegacyPatchAdapter(mocker), [machine.architecture]
        )

        form = NodeForm(data={"domain": domain.id}, instance=machine)
        form.save()

        assert domain.name == machine.domain.name

    def test_validates_domain(self, mocker):
        machine = factory.make_Node()
        patch_usable_architectures(
            _LegacyPatchAdapter(mocker), [machine.architecture]
        )

        form = NodeForm(
            data={"domain": factory.make_name("domain")}, instance=machine
        )

        assert not form.is_valid()

    def test_accepts_disable_ipv4_if_false(self, mocker):
        form = NodeForm(
            data={
                "architecture": make_usable_architecture(
                    _LegacyPatchAdapter(mocker)
                ),
                "disable_ipv4": False,
            }
        )
        form.save()
        # The field does not get to the model.

    def test_rejects_disable_ipv4_if_true(self, mocker):
        form = NodeForm(
            data={
                "architecture": make_usable_architecture(
                    _LegacyPatchAdapter(mocker)
                ),
                "disable_ipv4": True,
            }
        )
        assert not form.is_valid()


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestAdminNodeForm:
    def test_contains_limited_set_of_fields(self):
        user = factory.make_User()
        node = factory.make_Node(owner=user)
        form = AdminNodeForm(instance=node)

        assert {
            "hostname",
            "description",
            "domain",
            "disable_ipv4",
            "swap_size",
            "cpu_count",
            "memory",
            "zone",
            "pool",
        } == form.fields.keys()

    def test_initialises_zone(self):
        # The zone field uses "to_field_name", so that it can refer to a zone
        # by name instead of by ID.  A bug in Django breaks initialisation
        # from an instance: the field tries to initialise the field using a
        # zone's ID instead of its name, and ends up reverting to the default.
        # The code must work around this bug.
        zone = factory.make_Zone()
        node = factory.make_Node(zone=zone)
        # We'll create a form that makes a change, but not to the zone.
        data = {"hostname": factory.make_name("host")}
        form = AdminNodeForm(instance=node, data=data)
        # The Django bug would stop the initial field value from being set,
        # but the workaround ensures that it is initialised.
        assert zone.name == form.initial["zone"]

    def test_changes_zone(self, mocker):
        node = factory.make_Node()
        zone = factory.make_Zone()
        hostname = factory.make_string()
        form = AdminNodeForm(
            data={
                "hostname": hostname,
                "architecture": make_usable_architecture(
                    _LegacyPatchAdapter(mocker)
                ),
                "zone": zone.name,
            },
            instance=node,
        )

        with post_commit_hooks:
            form.save()

        node = reload_object(node)
        assert node.hostname == hostname
        assert node.zone == zone
