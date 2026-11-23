# Copyright 2016-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maasserver.websockets.handlers.staticrange`"""

import random

import pytest

from maasserver.models.staticroute import StaticRoute
from maasserver.testing.factory import factory
from maasserver.utils.orm import get_one
from maasserver.websockets.base import (
    dehydrate_datetime,
    HandlerPermissionError,
)
from maasserver.websockets.handlers.staticroute import StaticRouteHandler
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestStaticRouteHandler:
    def dehydrate_staticroute(self, staticroute, for_list=False):
        data = {
            "id": staticroute.id,
            "created": dehydrate_datetime(staticroute.created),
            "updated": dehydrate_datetime(staticroute.updated),
            "source": staticroute.source_id,
            "destination": staticroute.destination_id,
            "gateway_ip": staticroute.gateway_ip,
            "metric": staticroute.metric,
        }
        return data

    def test_get(self):
        user = factory.make_User()
        handler = StaticRouteHandler(user, {}, None)
        staticroute = factory.make_StaticRoute()
        assert self.dehydrate_staticroute(staticroute) == handler.get(
            {"id": staticroute.id}
        )

    def test_list(self):
        user = factory.make_User()
        handler = StaticRouteHandler(user, {}, None)
        for _ in range(3):
            factory.make_StaticRoute()
        expected_staticroutes = [
            self.dehydrate_staticroute(staticroute, for_list=True)
            for staticroute in StaticRoute.objects.all()
        ]
        assert sorted(expected_staticroutes, key=repr) == sorted(
            handler.list({}), key=repr
        )

    def test_create(self):
        user = factory.make_admin()
        source = factory.make_Subnet()
        destination = factory.make_Subnet(
            version=source.get_ipnetwork().version
        )
        gateway_ip = factory.pick_ip_in_Subnet(source)
        metric = random.randint(0, 500)
        handler = StaticRouteHandler(user, {}, None)
        response = handler.create(
            {
                "source": source.id,
                "destination": destination.id,
                "gateway_ip": gateway_ip,
                "metric": metric,
            }
        )

        staticroute = StaticRoute.objects.get(id=response["id"])
        assert staticroute.source == source
        assert staticroute.destination == destination
        assert staticroute.gateway_ip == gateway_ip
        assert staticroute.metric == metric

    def test_create_admin_only(self):
        user = factory.make_User()
        source = factory.make_Subnet()
        destination = factory.make_Subnet(
            version=source.get_ipnetwork().version
        )
        gateway_ip = factory.pick_ip_in_Subnet(source)
        metric = random.randint(0, 500)
        handler = StaticRouteHandler(user, {}, None)
        pytest.raises(
            HandlerPermissionError,
            handler.create,
            {
                "source": source.id,
                "destination": destination.id,
                "gateway_ip": gateway_ip,
                "metric": metric,
            },
        )

    def test_update(self):
        user = factory.make_admin()
        staticroute = factory.make_StaticRoute()
        handler = StaticRouteHandler(user, {}, None)
        data = self.dehydrate_staticroute(staticroute)
        data["metric"] = random.randint(0, 500)
        handler.update(data)
        a_staticroute = StaticRoute.objects.get(id=data["id"])
        assert a_staticroute.source == staticroute.source
        assert a_staticroute.destination == staticroute.destination
        assert a_staticroute.gateway_ip == staticroute.gateway_ip
        assert a_staticroute.metric == data["metric"]

    def test_update_admin_only(self):
        user = factory.make_User()
        staticroute = factory.make_StaticRoute()
        handler = StaticRouteHandler(user, {}, None)
        data = self.dehydrate_staticroute(staticroute)
        data["metric"] = random.randint(0, 500)
        pytest.raises(HandlerPermissionError, handler.update, data)

    def test_delete(self):
        user = factory.make_admin()
        staticroute = factory.make_StaticRoute()
        handler = StaticRouteHandler(user, {}, None)
        handler.delete({"id": staticroute.id})
        assert get_one(StaticRoute.objects.filter(id=staticroute.id)) is None

    def test_delete_admin_only(self):
        user = factory.make_User()
        staticroute = factory.make_StaticRoute()
        handler = StaticRouteHandler(user, {}, None)
        pytest.raises(
            HandlerPermissionError, handler.delete, {"id": staticroute.id}
        )


@pytest.mark.usefixtures("maasdb", "factory")
class TestStaticRouteHandlerOpenFGAIntegration(PytestOpenFGAMockMixin):
    def test_create_requires_can_edit_global_entities(self):
        self.openfga_client.can_edit_global_entities.return_value = True
        user = factory.make_User()
        source = factory.make_Subnet()
        destination = factory.make_Subnet(
            version=source.get_ipnetwork().version
        )
        gateway_ip = factory.pick_ip_in_Subnet(source)
        metric = random.randint(0, 500)
        handler = StaticRouteHandler(user, {}, None)
        handler.create(
            {
                "source": source.id,
                "destination": destination.id,
                "gateway_ip": gateway_ip,
                "metric": metric,
            }
        )
        self.openfga_client.can_edit_global_entities.assert_called_once_with(
            user
        )

    def test_update_requires_can_edit_global_entities(self):
        self.openfga_client.can_edit_global_entities.return_value = True
        user = factory.make_User()
        staticroute = factory.make_StaticRoute()
        handler = StaticRouteHandler(user, {}, None)
        handler.update({"id": staticroute.id})
        self.openfga_client.can_edit_global_entities.assert_called_once_with(
            user
        )

    def test_delete_requires_can_edit_global_entities(self):
        self.openfga_client.can_edit_global_entities.return_value = True
        user = factory.make_User()
        staticroute = factory.make_StaticRoute()
        handler = StaticRouteHandler(user, {}, None)
        handler.delete({"id": staticroute.id})
        self.openfga_client.can_edit_global_entities.assert_called_once_with(
            user
        )

    def test_list_requires_can_view_global_entities(self):
        self.openfga_client.can_view_global_entities.return_value = False
        user = factory.make_User()
        factory.make_StaticRoute()
        handler = StaticRouteHandler(user, {}, None)
        pytest.raises(HandlerPermissionError, handler.list, {})

    def test_get_requires_can_view_global_entities(self):
        self.openfga_client.can_view_global_entities.return_value = False
        user = factory.make_User()
        staticroute = factory.make_StaticRoute()
        handler = StaticRouteHandler(user, {}, None)
        pytest.raises(
            HandlerPermissionError, handler.get, {"id": staticroute.id}
        )
