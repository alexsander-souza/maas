# Copyright 2016-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maasserver.websockets.handlers.service`"""

import pytest

from maasserver.models.service import Service
from maasserver.testing.factory import factory
from maasserver.websockets.base import dehydrate_datetime
from maasserver.websockets.handlers.service import ServiceHandler


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestServiceHandler:
    def dehydrate_service(self, service, for_list=False):
        data = {
            "id": service.id,
            "node": service.node.id,
            "name": service.name,
            "status": service.status,
            "status_info": service.status_info,
            "updated": dehydrate_datetime(service.updated),
            "created": dehydrate_datetime(service.created),
        }
        if for_list:
            del data["node"]
            del data["updated"]
            del data["created"]
        return data

    def test_get(self):
        user = factory.make_User()
        handler = ServiceHandler(user, {}, None)
        node = factory.make_RackController()
        service = factory.make_Service(node)
        assert self.dehydrate_service(service) == handler.get(
            {"id": service.id}
        )

    def test_list(self):
        user = factory.make_User()
        handler = ServiceHandler(user, {}, None)
        node = factory.make_RackController()
        factory.make_Service(node)
        expected_services = [
            self.dehydrate_service(service, for_list=True)
            for service in Service.objects.all()
        ]
        assert len(expected_services) > 0
        assert sorted(expected_services, key=repr) == sorted(
            handler.list({}), key=repr
        )
