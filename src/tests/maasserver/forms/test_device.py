# Copyright 2015-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from django.http import HttpRequest
from django.http.request import QueryDict
import pytest

from maasserver.forms import DeviceForm, DeviceWithMACsForm
from maasserver.models import Device, Interface
from maasserver.testing.factory import factory
from maasserver.utils.forms import get_QueryDict
from maasserver.utils.orm import get_one, post_commit_hooks, reload_object


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestDeviceForm:
    def test_contains_limited_set_of_fields(self):
        form = DeviceForm()

        assert {
            "hostname",
            "description",
            "domain",
            "parent",
            "disable_ipv4",
            "swap_size",
            "zone",
        } == form.fields.keys()

    def test_changes_device_parent(self):
        device = factory.make_Device()
        parent = factory.make_Node()

        form = DeviceForm(data={"parent": parent.system_id}, instance=device)
        form.save()
        reload_object(device)
        reload_object(parent)

        assert parent == device.parent


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestDeviceWithMACsForm:
    def make_request(self):
        """Return a :class:`HttpRequest` with the given parameters."""
        request = HttpRequest()
        request.user = factory.make_User()
        return request

    def test_contains_mac_addresses_field_and_converts_non_querydict(self):
        form = DeviceWithMACsForm(data={})
        assert "mac_addresses" in form.fields
        assert isinstance(form.data, QueryDict)

    def test_creates_device_with_mac(self):
        hostname = factory.make_name("device")
        mac = factory.make_mac_address()
        form = DeviceWithMACsForm(
            data=get_QueryDict({"hostname": hostname, "mac_addresses": mac}),
            request=self.make_request(),
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            form.save()
        device = get_one(Device.objects.filter(hostname=hostname))
        assert hostname == device.hostname
        iface = get_one(Interface.objects.filter(mac_address=mac))
        assert iface.node_config.node == device

    def test_creates_device_with_macs(self):
        hostname = factory.make_name("device")
        mac1 = factory.make_mac_address()
        mac2 = factory.make_mac_address()
        form = DeviceWithMACsForm(
            data=get_QueryDict(
                {"hostname": hostname, "mac_addresses": [mac1, mac2]}
            ),
            request=self.make_request(),
        )
        assert form.is_valid(), dict(form.errors)

        with post_commit_hooks:
            form.save()
        device = get_one(Device.objects.filter(hostname=hostname))
        assert hostname == device.hostname
        iface = get_one(Interface.objects.filter(mac_address=mac1))
        assert iface.node_config.node == device
        iface = get_one(Interface.objects.filter(mac_address=mac2))
        assert iface.node_config.node == device

    def test_creates_device_with_parent_inherits_parents_domain(self):
        parent = factory.make_Node()
        hostname = factory.make_name("device")
        mac1 = factory.make_mac_address()
        mac2 = factory.make_mac_address()
        form = DeviceWithMACsForm(
            data=get_QueryDict(
                {
                    "hostname": hostname,
                    "mac_addresses": [mac1, mac2],
                    "parent": parent.system_id,
                }
            ),
            request=self.make_request(),
        )
        assert form.is_valid(), dict(form.errors)
        with post_commit_hooks:
            form.save()
        device = get_one(Device.objects.filter(hostname=hostname))
        assert hostname == device.hostname
        assert parent.domain == device.domain
        iface = get_one(Interface.objects.filter(mac_address=mac1))
        assert iface.node_config.node == device
        iface = get_one(Interface.objects.filter(mac_address=mac2))
        assert iface.node_config.node == device

    def test_creates_device_with_domain_and_parent(self):
        parent = factory.make_Node()
        hostname = factory.make_name("device")
        mac1 = factory.make_mac_address()
        mac2 = factory.make_mac_address()
        domain = factory.make_Domain()
        form = DeviceWithMACsForm(
            data=get_QueryDict(
                {
                    "hostname": hostname,
                    "mac_addresses": [mac1, mac2],
                    "parent": parent.system_id,
                    "domain": domain.name,
                }
            ),
            request=self.make_request(),
        )
        assert form.is_valid(), dict(form.errors)
        with post_commit_hooks:
            form.save()
        device = get_one(Device.objects.filter(hostname=hostname))
        assert hostname == device.hostname
        assert domain == device.domain
        iface = get_one(Interface.objects.filter(mac_address=mac1))
        assert iface.node_config.node == device
        iface = get_one(Interface.objects.filter(mac_address=mac2))
        assert iface.node_config.node == device
