# Copyright 2015-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maasserver.websockets.handlers.fabric`"""

import pytest

from maasserver import openfga
from maasserver.models.fabric import Fabric
from maasserver.testing.factory import factory
from maasserver.websockets.base import (
    dehydrate_datetime,
    HandlerPermissionError,
)
from maasserver.websockets.handlers.fabric import FabricHandler
from maastesting.querycounter import count_queries


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestFabricHandler:
    def dehydrate_fabric(self, fabric):
        data = {
            "id": fabric.id,
            "name": fabric.get_name(),
            "description": fabric.description,
            "class_type": fabric.class_type,
            "updated": dehydrate_datetime(fabric.updated),
            "created": dehydrate_datetime(fabric.created),
            "vlan_ids": sorted(vlan.id for vlan in fabric.vlan_set.all()),
        }
        data["default_vlan_id"] = data["vlan_ids"][0]
        return data

    def test_get(self):
        user = factory.make_User()
        handler = FabricHandler(user, {}, None)
        fabric = factory.make_Fabric()
        vlan = fabric.get_default_vlan()
        for _ in range(3):
            node = factory.make_Node(interface=True)
            interface = node.get_boot_interface()
            interface.vlan = vlan
            interface.save()
        assert self.dehydrate_fabric(fabric) == handler.get({"id": fabric.id})

    def test_get_default_vlan_is_first(self):
        user = factory.make_User()
        handler = FabricHandler(user, {}, None)
        fabric = factory.make_Fabric()
        default_vlan = fabric.get_default_vlan()
        tagged_vlan_ids = [
            factory.make_VLAN(fabric=fabric).id for _ in range(3)
        ]
        observed = handler.get({"id": fabric.id})
        assert [default_vlan.id] + tagged_vlan_ids == observed["vlan_ids"]

    def test_list(self):
        user = factory.make_User()
        handler = FabricHandler(user, {}, None)
        factory.make_Fabric()
        expected_fabrics = [
            self.dehydrate_fabric(fabric) for fabric in Fabric.objects.all()
        ]
        assert sorted(
            expected_fabrics, key=lambda fabric: fabric["id"]
        ) == sorted(handler.list({}), key=lambda fabric: fabric["id"])

    def test_list_constant_queries(self):
        user = factory.make_User()
        handler = FabricHandler(user, {}, None)
        for _ in range(10):
            fabric = factory.make_Fabric()
            vlan = fabric.get_default_vlan()
            for _ in range(3):
                node = factory.make_Node(interface=True)
                interface = node.get_boot_interface()
                interface.vlan = vlan
                interface.save()

        queries_one, _ = count_queries(handler.list, {"limit": 1})
        queries_multiple, _ = count_queries(handler.list, {})

        assert queries_one == queries_multiple


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestFabricHandlerViewPermission:
    def deny_global_view(self, mocker):
        mocker.patch.object(
            openfga.get_openfga_client(),
            "can_view_global_entities",
            return_value=False,
        )

    def test_list_requires_view_permission(self, mocker):
        self.deny_global_view(mocker)
        handler = FabricHandler(factory.make_User(), {}, None)
        factory.make_Fabric()
        with pytest.raises(HandlerPermissionError):
            handler.list({})

    def test_get_requires_view_permission(self, mocker):
        self.deny_global_view(mocker)
        fabric = factory.make_Fabric()
        handler = FabricHandler(factory.make_User(), {}, None)
        with pytest.raises(HandlerPermissionError):
            handler.get({"id": fabric.id})


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestFabricHandlerEditPermission:
    def deny_global_edit(self, mocker):
        mocker.patch.object(
            openfga.get_openfga_client(),
            "can_edit_global_entities",
            return_value=False,
        )

    def test_create_requires_edit_permission(self, mocker):
        self.deny_global_edit(mocker)
        handler = FabricHandler(factory.make_User(), {}, None)
        with pytest.raises(HandlerPermissionError):
            handler.create({})

    def test_update_requires_edit_permission(self, mocker):
        self.deny_global_edit(mocker)
        fabric = factory.make_Fabric()
        handler = FabricHandler(factory.make_User(), {}, None)
        with pytest.raises(HandlerPermissionError):
            handler.update({"id": fabric.id})
