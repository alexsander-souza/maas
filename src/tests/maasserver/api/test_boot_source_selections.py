# Copyright 2014-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the `Boot Source Selections` API."""

import http.client

from django.urls import reverse
import pytest

from maasserver.api.boot_source_selections import (
    DISPLAYED_BOOTSOURCESELECTION_FIELDS,
)
from maasserver.audit import Event
from maasserver.models import BootSourceSelection
import maasserver.models.bootsourceselection as bootsourceselection_module
from maasserver.models.signals import bootsources
from maasserver.testing.factory import factory
from maasserver.utils.converters import json_load_bytes
from maasserver.utils.orm import reload_object
from provisioningserver.events import EVENT_TYPES
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


def get_boot_source_selection_uri(boot_source_selection):
    """Return a boot source's URI on the API."""
    boot_source = boot_source_selection.boot_source
    return reverse(
        "boot_source_selection_handler",
        args=[boot_source.id, boot_source_selection.id],
    )


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
class TestBootSourceSelectionAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client
        bootsources.signals.disable()
        yield
        bootsources.signals.enable()

    def test_handler_path(self):
        assert "/MAAS/api/2.0/boot-sources/3/selections/4/" == reverse(
            "boot_source_selection_handler", args=["3", "4"]
        )

    def test_GET_returns_boot_source(self):
        self.user.is_superuser = True
        self.user.save()
        boot_source_selection = factory.make_BootSourceSelection()
        response = self.client.get(
            get_boot_source_selection_uri(boot_source_selection)
        )
        assert http.client.OK == response.status_code
        returned_boot_source_selection = json_load_bytes(response.content)
        boot_source = boot_source_selection.boot_source
        # The returned object contains a 'resource_uri' field.
        assert (
            reverse(
                "boot_source_selection_handler",
                args=[boot_source.id, boot_source_selection.id],
            )
            == returned_boot_source_selection["resource_uri"]
        )
        # The other fields are the boot source selection's fields.
        del returned_boot_source_selection["resource_uri"]
        # All the fields are present.
        assert set(DISPLAYED_BOOTSOURCESELECTION_FIELDS) == (
            returned_boot_source_selection.keys()
        )
        assert (
            vars(boot_source_selection).items()
            > returned_boot_source_selection.items()
        )

    def test_DELETE_deletes_boot_source_selection(self, mocker):
        mocker.patch.object(bootsourceselection_module, "stop_workflow")
        self.user.is_superuser = True
        self.user.save()
        boot_source_selection = factory.make_BootSourceSelection()
        response = self.client.delete(
            get_boot_source_selection_uri(boot_source_selection)
        )
        assert http.client.NO_CONTENT == response.status_code
        assert reload_object(boot_source_selection) is None

    def test_DELETE_create_audit_event(self, mocker):
        mocker.patch.object(bootsourceselection_module, "stop_workflow")
        self.user.is_superuser = True
        self.user.save()
        boot_source_selection = factory.make_BootSourceSelection()
        response = self.client.delete(
            get_boot_source_selection_uri(boot_source_selection)
        )
        assert http.client.NO_CONTENT == response.status_code
        events = Event.objects.filter(
            type__name=EVENT_TYPES.BOOT_SOURCE_SELECTION
        )
        assert len(events) == 1
        assert (
            events[0].description
            == f"Deleted boot source selection for {boot_source_selection.os}/{boot_source_selection.release} arches={boot_source_selection.arches}"
        )

    def test_DELETE_requires_admin(self):
        boot_source_selection = factory.make_BootSourceSelection()
        response = self.client.delete(
            get_boot_source_selection_uri(boot_source_selection)
        )
        assert http.client.FORBIDDEN == response.status_code

    def test_PUT_updates_boot_source_selection(self):
        self.user.is_superuser = True
        self.user.save()
        boot_source_selection = factory.make_BootSourceSelection()
        new_os = factory.make_name("os")
        new_release = factory.make_name("release")
        boot_source_caches = factory.make_many_BootSourceCaches(
            2,
            boot_source=boot_source_selection.boot_source,
            os=new_os,
            release=new_release,
        )
        new_values = {
            "os": new_os,
            "release": new_release,
            "arches": [boot_source_caches[0].arch, boot_source_caches[1].arch],
            "subarches": [
                boot_source_caches[0].subarch,
                boot_source_caches[1].subarch,
            ],
            "labels": [boot_source_caches[0].label],
        }
        response = self.client.put(
            get_boot_source_selection_uri(boot_source_selection), new_values
        )
        assert http.client.OK == response.status_code, response.content
        boot_source_selection = reload_object(boot_source_selection)
        assert boot_source_selection.os == new_os
        assert boot_source_selection.release == new_release
        assert boot_source_selection.arches == [
            boot_source_caches[0].arch,
            boot_source_caches[1].arch,
        ]
        assert boot_source_selection.subarches == [
            boot_source_caches[0].subarch,
            boot_source_caches[1].subarch,
        ]
        assert boot_source_selection.labels == [boot_source_caches[0].label]

    def test_PUT_create_audit_event(self):
        self.user.is_superuser = True
        self.user.save()
        boot_source_selection = factory.make_BootSourceSelection()
        new_os = factory.make_name("os")
        new_release = factory.make_name("release")
        boot_source_caches = factory.make_many_BootSourceCaches(
            2,
            boot_source=boot_source_selection.boot_source,
            os=new_os,
            release=new_release,
        )
        new_arches = [boot_source_caches[0].arch, boot_source_caches[1].arch]
        new_values = {
            "os": new_os,
            "release": new_release,
            "arches": new_arches,
            "subarches": [
                boot_source_caches[0].subarch,
                boot_source_caches[1].subarch,
            ],
            "labels": [boot_source_caches[0].label],
        }
        response = self.client.put(
            get_boot_source_selection_uri(boot_source_selection), new_values
        )
        assert http.client.OK == response.status_code, response.content
        events = Event.objects.filter(
            type__name=EVENT_TYPES.BOOT_SOURCE_SELECTION
        )
        assert len(events) == 1
        assert (
            events[0].description
            == f"Updated boot source selection for {new_os}/{new_release} arches={new_arches}: {boot_source_selection.boot_source.url}"
        )

    def test_PUT_requires_admin(self):
        boot_source_selection = factory.make_BootSourceSelection()
        new_values = {"release": factory.make_name("release")}
        response = self.client.put(
            get_boot_source_selection_uri(boot_source_selection), new_values
        )
        assert http.client.FORBIDDEN == response.status_code


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
class TestBootSourceSelectionsAPI:
    """Test the the boot source selections API."""

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client
        bootsources.signals.disable()
        yield
        bootsources.signals.enable()

    def test_handler_path(self):
        assert "/MAAS/api/2.0/boot-sources/3/selections/" == reverse(
            "boot_source_selections_handler", args=["3"]
        )

    def test_GET_returns_boot_source_selection_list(self):
        self.user.is_superuser = True
        self.user.save()
        boot_source = factory.make_BootSource()
        selections = [
            factory.make_BootSourceSelection(boot_source=boot_source)
            for _ in range(3)
        ]
        # Create boot source selections in another boot source.
        [factory.make_BootSourceSelection() for _ in range(3)]
        response = self.client.get(
            reverse("boot_source_selections_handler", args=[boot_source.id])
        )
        assert http.client.OK == response.status_code, response.content
        parsed_result = json_load_bytes(response.content)
        assert sorted(selection.id for selection in selections) == sorted(
            selection.get("id") for selection in parsed_result
        )

    def test_POST_creates_boot_source_selection(self):
        self.user.is_superuser = True
        self.user.save()
        boot_source = factory.make_BootSource()
        new_release = factory.make_name("release")
        boot_source_caches = factory.make_many_BootSourceCaches(
            2, boot_source=boot_source, release=new_release
        )
        params = {
            "release": new_release,
            "arches": [boot_source_caches[0].arch, boot_source_caches[1].arch],
            "subarches": [
                boot_source_caches[0].subarch,
                boot_source_caches[1].subarch,
            ],
            "labels": [boot_source_caches[0].label],
        }
        response = self.client.post(
            reverse("boot_source_selections_handler", args=[boot_source.id]),
            params,
        )
        assert http.client.OK == response.status_code
        parsed_result = json_load_bytes(response.content)

        boot_source_selection = BootSourceSelection.objects.get(
            id=parsed_result["id"]
        )
        assert boot_source_selection.release == new_release
        assert boot_source_selection.arches == [
            boot_source_caches[0].arch,
            boot_source_caches[1].arch,
        ]
        assert boot_source_selection.subarches == [
            boot_source_caches[0].subarch,
            boot_source_caches[1].subarch,
        ]
        assert boot_source_selection.labels == [boot_source_caches[0].label]

    def test_POST_create_audit_event(self):
        self.user.is_superuser = True
        self.user.save()
        boot_source = factory.make_BootSource()
        os = factory.make_name("os")
        new_release = factory.make_name("release")
        boot_source_caches = factory.make_many_BootSourceCaches(
            2, boot_source=boot_source, os=os, release=new_release
        )
        arches = [boot_source_caches[0].arch, boot_source_caches[1].arch]
        params = {
            "os": os,
            "release": new_release,
            "arches": arches,
            "subarches": ["*"],
            "labels": ["*"],
        }
        response = self.client.post(
            reverse("boot_source_selections_handler", args=[boot_source.id]),
            params,
        )
        assert http.client.OK == response.status_code
        events = Event.objects.filter(
            type__name=EVENT_TYPES.BOOT_SOURCE_SELECTION
        )
        assert len(events) == 1
        assert (
            events[0].description
            == f"Created boot source selection for {os}/{new_release} arches={[boot_source_caches[0].arch, boot_source_caches[1].arch]}: {boot_source.url}"
        )

    def test_POST_requires_admin(self):
        boot_source = factory.make_BootSource()
        new_release = factory.make_name("release")
        params = {
            "release": new_release,
            "arches": [factory.make_name("arch"), factory.make_name("arch")],
            "subarches": [
                factory.make_name("subarch"),
                factory.make_name("subarch"),
            ],
            "labels": [factory.make_name("label")],
        }
        response = self.client.post(
            reverse("boot_source_selections_handler", args=[boot_source.id]),
            params,
        )
        assert http.client.FORBIDDEN == response.status_code


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
class TestBootSourceSelectionOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_GET_requires_can_view_boot_entities(self):
        self.openfga_client.can_view_boot_entities.return_value = True
        boot_source_selection = factory.make_BootSourceSelection()
        response = self.client.get(
            get_boot_source_selection_uri(boot_source_selection)
        )
        assert http.client.OK == response.status_code
        self.openfga_client.can_view_boot_entities.assert_called_once_with(
            self.user
        )

    def test_PUT_requires_can_view_boot_entities(self):
        self.openfga_client.can_edit_boot_entities.return_value = True
        boot_source_selection = factory.make_BootSourceSelection()
        new_values = {"release": factory.make_name("release")}
        response = self.client.put(
            get_boot_source_selection_uri(boot_source_selection), new_values
        )
        assert http.client.FORBIDDEN != response.status_code
        self.openfga_client.can_edit_boot_entities.assert_called_once_with(
            self.user
        )

    def test_DELETE_requires_can_view_boot_entities(self, mocker):
        mocker.patch.object(bootsourceselection_module, "stop_workflow")
        self.openfga_client.can_edit_boot_entities.return_value = True
        boot_source_selection = factory.make_BootSourceSelection()
        response = self.client.delete(
            get_boot_source_selection_uri(boot_source_selection)
        )
        assert http.client.NO_CONTENT == response.status_code
        self.openfga_client.can_edit_boot_entities.assert_called_once_with(
            self.user
        )


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
class TestBootSourceSelectionsOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_GET_requires_can_view_boot_entities(self):
        self.openfga_client.can_view_boot_entities.return_value = True
        boot_source = factory.make_BootSource()
        response = self.client.get(
            reverse("boot_source_selections_handler", args=[boot_source.id])
        )
        assert http.client.OK == response.status_code
        self.openfga_client.can_view_boot_entities.assert_called_once_with(
            self.user
        )

    def test_POST_requires_can_edit_boot_entities(self):
        self.openfga_client.can_edit_boot_entities.return_value = True
        boot_source = factory.make_BootSource()
        response = self.client.post(
            reverse("boot_source_selections_handler", args=[boot_source.id]),
            {},
        )
        assert http.client.FORBIDDEN != response.status_code
        self.openfga_client.can_edit_boot_entities.assert_called_once_with(
            self.user
        )
