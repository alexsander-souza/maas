# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from decimal import Decimal
import importlib.util
import json
from unittest import mock

from django.core.serializers.json import DjangoJSONEncoder
from django.urls import reverse
from piston3 import emitters as piston_emitters
from piston3.handler import typemapper
from piston3.utils import Mimer
import pytest

from maasserver.api.machines import MachinesHandler
from maasserver.api.support import method_fields_reserved_fields_patch
from maasserver.api.zones import ZoneHandler
from maasserver.models import Zone
from maasserver.testing.factory import factory
from maastesting.http import make_HttpRequest
from tests.maasserver.api.test_nodes import RenderedNodesMixin


def load_piston_emitter():
    """Load Piston's `Emitter` as MAAS uses it, but with its `construct`."""
    spec = importlib.util.spec_from_file_location(
        "piston3.pristine_emitters", piston_emitters.__file__
    )
    module = importlib.util.module_from_spec(spec)
    with mock.patch.object(Mimer, "register"):
        spec.loader.exec_module(module)

    class PistonEmitter(module.Emitter):
        method_fields = method_fields_reserved_fields_patch

    return PistonEmitter


PistonEmitter = load_piston_emitter()


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestConstruct(RenderedNodesMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, admin, admin_api_client, mocker):
        self.user = admin
        self.client = admin_api_client
        reverse("machines_handler")
        self.setup_rendered_nodes(mocker)

    def assert_constructed_like_piston(self, data, handler, fields):
        expected = PistonEmitter(
            data, typemapper, handler, fields, False
        ).construct()
        observed = piston_emitters.Emitter(
            data, typemapper, handler, fields, False
        ).construct()
        assert json.dumps(
            observed, cls=DjangoJSONEncoder, indent=1
        ) == json.dumps(expected, cls=DjangoJSONEncoder, indent=1)

    def test_machines_listing(self):
        parent = self.make_rich_machine()
        self.make_machine_with_fallbacks(parent)
        factory.make_Machine()
        handler = MachinesHandler()
        request = make_HttpRequest()
        request.user = self.user

        self.assert_constructed_like_piston(
            handler.read(request), handler, handler.fields
        )

    def test_explicit_field_specs(self):
        machine = self.make_rich_machine()
        handler = MachinesHandler()
        fields = (
            "hostname",
            "id",
            "fqdn",
            "tags",
            "unknown_attribute",
            "resource_uri",
            ("zone", ("name", "description")),
            ("current_config", ("name",)),
            ("tags", ("name", "comment")),
            ("blockdevice_set", ("name", "size")),
        )

        self.assert_constructed_like_piston([machine], handler, fields)

    def test_mixed_payload(self):
        machine = self.make_rich_machine()
        handler = MachinesHandler()
        payload = {
            "decimal": Decimal("1.50"),
            "created": machine.created,
            "primitives": [1, 2.5, "text", None, True, b"bytes"],
            "containers": ({"set": {1}}, [[], {}], ()),
            "machines": [machine, machine.zone],
        }

        self.assert_constructed_like_piston(payload, handler, None)

    def test_handlers_registered_while_emitting(self):
        zone = factory.make_Zone()
        zone_handler = typemapper[ZoneHandler]

        def construct(emitter_class):
            handlers = {
                handler: types
                for handler, types in typemapper.items()
                if types[0] is not Zone
            }

            def register_zone_handler():
                handlers[ZoneHandler] = zone_handler

            return emitter_class(
                [zone, register_zone_handler, zone],
                handlers,
                None,
                ("name",),
                False,
            ).construct()

        observed = construct(piston_emitters.Emitter)

        assert observed == construct(PistonEmitter)
        assert "resource_uri" not in observed[0]
        assert "resource_uri" in observed[2]


def test_emitter_raises_on_circular_references():
    data = {"key": []}
    data["key"].append(data)

    with pytest.raises(RuntimeError, match="Circular reference detected"):
        piston_emitters.Emitter(data, typemapper, None).construct()
