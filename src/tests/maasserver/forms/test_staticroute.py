# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for static route forms."""

import random

import pytest

from maasserver.forms.staticroute import StaticRouteForm
from maasserver.testing.factory import factory


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestStaticRouteForm:
    def test_requires_source_destination_gateway_ip(self):
        form = StaticRouteForm({})
        assert not form.is_valid(), form.errors
        assert form.errors == {
            "source": ["This field is required."],
            "destination": ["This field is required."],
            "gateway_ip": ["This field is required."],
        }

    def test_creates_staticroute(self):
        source = factory.make_Subnet()
        version = source.get_ipnetwork().version
        dest = factory.make_Subnet(version=version)
        gateway_ip = factory.pick_ip_in_Subnet(source)
        form = StaticRouteForm(
            {
                "source": source.id,
                "destination": dest.id,
                "gateway_ip": gateway_ip,
            }
        )
        assert form.is_valid(), form.errors
        staticroute = form.save()
        assert staticroute.source == source
        assert staticroute.destination == dest
        assert staticroute.gateway_ip == gateway_ip
        assert staticroute.metric == 0

    def test_doest_require_any_fields_on_update(self):
        static_route = factory.make_StaticRoute()
        form = StaticRouteForm(instance=static_route, data={})
        assert form.is_valid(), form.errors

    def test_updates_staticroute(self):
        static_route = factory.make_StaticRoute()
        new_source = factory.make_Subnet()
        version = new_source.get_ipnetwork().version
        new_dest = factory.make_Subnet(version=version)
        new_gateway_ip = factory.pick_ip_in_Subnet(new_source)
        new_metric = random.randint(0, 500)
        form = StaticRouteForm(
            instance=static_route,
            data={
                "source": new_source.id,
                "destination": new_dest.id,
                "gateway_ip": new_gateway_ip,
                "metric": new_metric,
            },
        )
        assert form.is_valid(), form.errors
        staticroute = form.save()
        assert staticroute.source == new_source
        assert staticroute.destination == new_dest
        assert staticroute.gateway_ip == new_gateway_ip
        assert staticroute.metric == new_metric
