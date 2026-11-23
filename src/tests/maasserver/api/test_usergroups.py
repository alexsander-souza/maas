# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `UserGroup` API."""

import http.client
import json

from django.conf import settings
from django.urls import reverse
import pytest

from maasserver.sqlalchemy import service_layer
from maasserver.testing.factory import factory
from maasservicelayer.db.filters import QuerySpec
from maasservicelayer.db.repositories.openfga_tuples import (
    OpenFGATuplesClauseFactory,
)
from maasservicelayer.models.openfga_tuple import OpenFGATuple
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


def _parse(response):
    return json.loads(response.content.decode(settings.DEFAULT_CHARSET))


def _create_group(client, name, description=None):
    """Helper to create a group and return the parsed response dict."""
    data = {"name": name}
    if description is not None:
        data["description"] = description
    resp = client.post(reverse("usergroups_handler"), data)
    return _parse(resp), resp


def get_openfga_tuple(
    user: str, relation: str, object_type: str, object_id: str
) -> OpenFGATuple | None:
    tuples = service_layer.services.openfga_tuples.get_many(
        QuerySpec(
            where=OpenFGATuplesClauseFactory.and_clauses(
                [
                    OpenFGATuplesClauseFactory.with_user(user),
                    OpenFGATuplesClauseFactory.with_relation(relation),
                    OpenFGATuplesClauseFactory.with_object_type(object_type),
                    OpenFGATuplesClauseFactory.with_object_id(object_id),
                ]
            )
        )
    )
    assert len(tuples) <= 1, "Expected at most one matching OpenFGA tuple"
    if tuples:
        return tuples[0]
    return None


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
class TestUserGroupsAPI:
    """Tests for the UserGroups collection endpoint."""

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_handler_path(self):
        assert "/MAAS/api/2.0/groups/" == reverse("usergroups_handler")

    def test_list_default_groups(self):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.get(reverse("usergroups_handler"))
        assert sorted(
            [
                {
                    "description": "Default administrators group",
                    "id": 1,
                    "name": "Administrators",
                    "resource_uri": "/MAAS/api/2.0/groups/1/",
                },
                {
                    "description": "Default users group",
                    "id": 2,
                    "name": "Users",
                    "resource_uri": "/MAAS/api/2.0/groups/2/",
                },
            ],
            key=lambda group: group["id"],
        ) == sorted(_parse(response), key=lambda group: group["id"])

    def test_list_returns_groups(self):
        self.user.is_superuser = True
        self.user.save()
        _create_group(self.client, "group-a", "Group A")
        _create_group(self.client, "group-b", "Group B")
        response = self.client.get(reverse("usergroups_handler"))
        assert http.client.OK == response.status_code, response.content
        parsed = _parse(response)
        names = {g["name"] for g in parsed}
        assert "group-a" in names
        assert "group-b" in names

    def test_list_includes_resource_uri(self):
        self.user.is_superuser = True
        self.user.save()
        created, _ = _create_group(self.client, "uri-group")
        response = self.client.get(reverse("usergroups_handler"))
        parsed = _parse(response)
        group = [g for g in parsed if g["name"] == "uri-group"][0]
        assert (
            f"/MAAS/api/2.0/groups/{created['id']}/" == group["resource_uri"]
        )

    def test_create_requires_admin(self):
        response = self.client.post(
            reverse("usergroups_handler"),
            {"name": "test-group"},
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_create(self):
        self.user.is_superuser = True
        self.user.save()
        created, response = _create_group(
            self.client, "new-group", "A new group"
        )
        assert http.client.OK == response.status_code, response.content
        assert "new-group" == created["name"]
        assert "A new group" == created["description"]
        assert "id" in created
        assert "resource_uri" in created

    def test_create_without_description(self):
        self.user.is_superuser = True
        self.user.save()
        created, response = _create_group(self.client, "no-desc-group")
        assert http.client.OK == response.status_code, response.content
        assert "no-desc-group" == created["name"]
        assert "" == created["description"]

    def test_create_requires_name(self):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.post(
            reverse("usergroups_handler"),
            {"description": "no name"},
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
class TestUserGroupAPI:
    """Tests for the UserGroup single-resource endpoint."""

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def test_handler_path(self):
        assert "/MAAS/api/2.0/groups/1/" == reverse(
            "usergroup_handler", args=[1]
        )

    def test_read(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()

        response = self.client.get(
            reverse("usergroup_handler", args=[group.id])
        )
        assert http.client.OK == response.status_code, response.content
        parsed = _parse(response)
        assert group.name == parsed["name"]
        assert group.description == parsed["description"]
        assert f"/MAAS/api/2.0/groups/{group.id}/" == parsed["resource_uri"]

    def test_read_404(self):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.get(reverse("usergroup_handler", args=[99999]))
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_update_requires_admin(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()

        self.user.is_superuser = False
        self.user.save()

        response = self.client.put(
            reverse("usergroup_handler", args=[group.id]),
            {"name": "new-name"},
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_update(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()

        response = self.client.put(
            reverse("usergroup_handler", args=[group.id]),
            {"name": "new-name", "description": "new desc"},
        )
        assert http.client.OK == response.status_code, response.content
        parsed = _parse(response)
        assert "new-name" == parsed["name"]
        assert "new desc" == parsed["description"]

    def test_update_name_only(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()

        response = self.client.put(
            reverse("usergroup_handler", args=[group.id]),
            {"name": "changed-name"},
        )
        assert http.client.OK == response.status_code, response.content
        parsed = _parse(response)
        assert "changed-name" == parsed["name"]
        assert group.description == parsed["description"]

    def test_update_description_only(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()

        response = self.client.put(
            reverse("usergroup_handler", args=[group.id]),
            {"description": "updated"},
        )
        assert http.client.OK == response.status_code, response.content
        parsed = _parse(response)
        assert group.name == parsed["name"]
        assert "updated" == parsed["description"]

    def test_update_404(self):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.put(
            reverse("usergroup_handler", args=[99999]),
            {"name": "nope"},
        )
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_delete_requires_admin(self):
        group = factory.make_Usergroup()

        response = self.client.delete(
            reverse("usergroup_handler", args=[group.id])
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_delete(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()

        response = self.client.delete(
            reverse("usergroup_handler", args=[group.id])
        )
        assert http.client.NO_CONTENT == response.status_code, response.content

        # Verify it's gone
        response = self.client.get(
            reverse("usergroup_handler", args=[group.id])
        )
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_delete_404(self):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.delete(
            reverse("usergroup_handler", args=[99999])
        )
        assert http.client.NOT_FOUND == response.status_code, response.content

    # Membership endpoints
    def test_list_members_requires_admin(self):
        group = factory.make_Usergroup()

        response = self.client.get(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "list_members"},
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_list_members_empty(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()

        response = self.client.get(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "list_members"},
        )
        assert http.client.OK == response.status_code, response.content
        assert [] == _parse(response)

    def test_list_members_404(self):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.get(
            reverse("usergroup_handler", args=[99999]),
            {"op": "list_members"},
        )
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_list_members_returns_added_members(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()
        member = factory.make_User()

        self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "add_member", "username": member.username},
        )

        response = self.client.get(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "list_members"},
        )
        assert http.client.OK == response.status_code, response.content
        parsed = _parse(response)
        usernames = {m["username"] for m in parsed}
        assert member.username in usernames

    def test_add_member_requires_admin(self):
        group = factory.make_Usergroup()

        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "add_member", "username": "someone"},
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_add_member(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()
        member = factory.make_User()

        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "add_member", "username": member.username},
        )
        assert http.client.OK == response.status_code, response.content
        assert (
            get_openfga_tuple(
                f"user:{member.id}",
                "member",
                "group",
                str(group.id),
            )
            is not None
        )

    def test_add_member_requires_username(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()

        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "add_member"},
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )

    def test_add_member_user_not_found(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()

        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "add_member", "username": "nonexistent-user"},
        )
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_add_member_group_not_found(self):
        self.user.is_superuser = True
        self.user.save()
        member = factory.make_User()

        response = self.client.post(
            reverse("usergroup_handler", args=[99999]),
            {"op": "add_member", "username": member.username},
        )
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_add_member_already_in_group(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()
        member = factory.make_User()

        self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "add_member", "username": member.username},
        )
        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "add_member", "username": member.username},
        )
        assert http.client.CONFLICT == response.status_code, response.content
        assert (
            get_openfga_tuple(
                f"user:{member.id}",
                "member",
                "group",
                str(group.id),
            )
            is not None
        )

    def test_remove_member_requires_admin(self):
        group = factory.make_Usergroup()

        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "remove_member", "username": "someone"},
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_remove_member(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()
        member = factory.make_User()

        self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "add_member", "username": member.username},
        )
        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "remove_member", "username": member.username},
        )
        assert http.client.NO_CONTENT == response.status_code, response.content
        assert (
            get_openfga_tuple(
                f"user:{member.id}",
                "member",
                "group",
                str(group.id),
            )
            is None
        )

    def test_remove_member_requires_username(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()

        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "remove_member"},
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )

    def test_remove_member_group_not_found(self):
        self.user.is_superuser = True
        self.user.save()
        user = factory.make_User()

        response = self.client.post(
            reverse("usergroup_handler", args=[9999]),
            {"op": "remove_member", "username": user.username},
        )
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_remove_member_user_not_found(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()

        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "remove_member", "username": "nonexistent-user"},
        )
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_remove_member_not_in_group_after_removal(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()
        member = factory.make_User()

        self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "add_member", "username": member.username},
        )
        self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "remove_member", "username": member.username},
        )

        response = self.client.get(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "list_members"},
        )
        assert http.client.OK == response.status_code, response.content
        parsed = _parse(response)
        usernames = {m["username"] for m in parsed}
        assert member.username not in usernames

    # Entitlement endpoints
    def test_list_entitlements_requires_admin(self):
        group = factory.make_Usergroup()

        response = self.client.get(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "list_entitlements"},
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_list_entitlements_empty(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()

        response = self.client.get(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "list_entitlements"},
        )
        assert http.client.OK == response.status_code, response.content
        assert [] == _parse(response)

    def test_list_entitlements_404(self):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.get(
            reverse("usergroup_handler", args=[99999]),
            {"op": "list_entitlements"},
        )
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_list_entitlements_returns_added_entitlements(self):
        self.user.is_superuser = True
        self.user.save()

        group = factory.make_Usergroup()
        entitlement = factory.make_Entitlement(
            group=group,
            resource_type="maas",
            entitlement="can_edit_machines",
        )

        another_group = factory.make_Usergroup()
        factory.make_Entitlement(
            group=another_group,
            resource_type="maas",
            entitlement="can_view_machines",
        )

        response = self.client.get(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "list_entitlements"},
        )
        assert http.client.OK == response.status_code, response.content
        parsed = _parse(response)
        assert len(parsed) == 1
        assert parsed[0]["resource_type"] == entitlement.object_type
        assert parsed[0]["resource_id"] == int(entitlement.object_id)
        assert parsed[0]["entitlement"] == entitlement.relation

    # add_entitlement
    def test_add_entitlement_requires_admin(self):
        group = factory.make_Usergroup()

        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {
                "op": "add_entitlement",
                "resource_type": "maas",
                "resource_id": 0,
                "entitlement": "can_edit_machines",
            },
        )
        assert http.client.FORBIDDEN == response.status_code, response.content
        assert (
            get_openfga_tuple(
                f"group:{group.id}#member", "can_edit_machines", "maas", "0"
            )
            is None
        )

    def test_add_entitlement_maas(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()

        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {
                "op": "add_entitlement",
                "resource_type": "maas",
                "resource_id": 0,
                "entitlement": "can_edit_machines",
            },
        )
        assert http.client.OK == response.status_code, response.content
        assert (
            get_openfga_tuple(
                f"group:{group.id}#member",
                "can_edit_machines",
                "maas",
                "0",
            )
            is not None
        )

    def test_add_entitlement_pool(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()
        pool = factory.make_ResourcePool()

        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {
                "op": "add_entitlement",
                "resource_type": "pool",
                "resource_id": pool.id,
                "entitlement": "can_edit_machines",
            },
        )
        assert http.client.OK == response.status_code, response.content
        assert (
            get_openfga_tuple(
                f"group:{group.id}#member",
                "can_edit_machines",
                "pool",
                str(pool.id),
            )
            is not None
        )

    def test_add_entitlement_group_not_found(self):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.post(
            reverse("usergroup_handler", args=[99999]),
            {
                "op": "add_entitlement",
                "resource_type": "maas",
                "resource_id": 0,
                "entitlement": "can_edit_machines",
            },
        )
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_add_entitlement_invalid_resource_type(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()

        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {
                "op": "add_entitlement",
                "resource_type": "invalid",
                "resource_id": 0,
                "entitlement": "can_edit_machines",
            },
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )

    def test_add_entitlement_pool_not_found(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()

        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {
                "op": "add_entitlement",
                "resource_type": "pool",
                "resource_id": 99999,
                "entitlement": "can_edit_machines",
            },
        )
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_add_entitlement_maas_invalid(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()

        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {
                "op": "add_entitlement",
                "resource_type": "maas",
                "resource_id": -1,  # must be 0 for maas
                "entitlement": "can_edit_machines",
            },
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )

    def test_add_entitlement_invalid_entitlement_name(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()

        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {
                "op": "add_entitlement",
                "resource_type": "maas",
                "resource_id": 0,
                "entitlement": "nonexistent",
            },
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )

    def test_remove_entitlement_requires_admin(self):
        group = factory.make_Usergroup()

        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {
                "op": "remove_entitlement",
                "resource_type": "maas",
                "resource_id": "0",
                "entitlement": "can_edit_machines",
            },
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_remove_entitlement(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()
        entitlement = factory.make_Entitlement(group=group)

        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {
                "op": "remove_entitlement",
                "resource_type": entitlement.object_type,
                "resource_id": entitlement.object_id,
                "entitlement": entitlement.relation,
            },
        )
        assert http.client.NO_CONTENT == response.status_code, response.content
        assert (
            get_openfga_tuple(
                f"group:{group.id}#member",
                entitlement.relation,
                entitlement.object_type,
                entitlement.object_id,
            )
            is None
        )

    def test_remove_entitlement_group_not_found(self):
        self.user.is_superuser = True
        self.user.save()
        response = self.client.post(
            reverse("usergroup_handler", args=[99999]),
            {
                "op": "remove_entitlement",
                "resource_type": "maas",
                "resource_id": 0,
                "entitlement": "can_edit_machines",
            },
        )
        assert http.client.NOT_FOUND == response.status_code, response.content

    def test_remove_entitlement_invalid_entitlement(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()

        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {
                "op": "remove_entitlement",
                "resource_type": "maas",
                "resource_id": 0,
                "entitlement": "invalid",
            },
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )

    def test_remove_entitlement_invalid_resource_type(self):
        self.user.is_superuser = True
        self.user.save()
        group = factory.make_Usergroup()

        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {
                "op": "remove_entitlement",
                "resource_type": "invalid",
                "resource_id": 0,
                "entitlement": "can_edit_machines",
            },
        )
        assert http.client.BAD_REQUEST == response.status_code, (
            response.content
        )


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
@pytest.mark.parametrize("api_identity", ["user=user,client=oauth"])
class TestUserGroupsOpenFGAIntegration(PytestOpenFGAMockMixin):
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def _create_group_as_admin(self, name, description="test"):
        """Create a group using edit permission, then return its id."""
        self.openfga_client.can_edit_identities.return_value = True
        created, resp = _create_group(self.client, name, description)
        assert http.client.OK == resp.status_code, resp.content
        self.openfga_client.reset_mock()
        return created["id"]

    def test_list_requires_can_view_identities(self):
        self.openfga_client.can_view_identities.return_value = True
        response = self.client.get(reverse("usergroups_handler"))
        assert http.client.OK == response.status_code, response.content
        self.openfga_client.can_view_identities.assert_called_once_with(
            self.user
        )

    def test_list_denied_without_view_permission(self):
        self.openfga_client.can_view_identities.return_value = False
        response = self.client.get(reverse("usergroups_handler"))
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_create_requires_can_edit_identities(self):
        self.openfga_client.can_edit_identities.return_value = True
        _, response = _create_group(self.client, "openfga-group", "test")
        assert http.client.OK == response.status_code, response.content
        self.openfga_client.can_edit_identities.assert_called_once_with(
            self.user
        )

    def test_create_denied_without_edit_permission(self):
        self.openfga_client.can_edit_identities.return_value = False
        response = self.client.post(
            reverse("usergroups_handler"),
            {"name": "denied-group"},
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_read_requires_can_view_identities(self):
        group_id = self._create_group_as_admin("view-group")
        self.openfga_client.can_view_identities.return_value = True
        response = self.client.get(
            reverse("usergroup_handler", args=[group_id])
        )
        assert http.client.OK == response.status_code, response.content
        self.openfga_client.can_view_identities.assert_called_once_with(
            self.user
        )

    def test_read_denied_without_view_permission(self):
        group_id = self._create_group_as_admin("no-view-group")
        self.openfga_client.can_view_identities.return_value = False
        response = self.client.get(
            reverse("usergroup_handler", args=[group_id])
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_update_requires_can_edit_identities(self):
        group_id = self._create_group_as_admin("edit-group")
        self.openfga_client.can_edit_identities.return_value = True
        response = self.client.put(
            reverse("usergroup_handler", args=[group_id]),
            {"name": "edited"},
        )
        assert http.client.OK == response.status_code, response.content
        self.openfga_client.can_edit_identities.assert_called_once_with(
            self.user
        )

    def test_update_denied_without_edit_permission(self):
        group_id = self._create_group_as_admin("no-edit-group")
        self.openfga_client.can_edit_identities.return_value = False
        response = self.client.put(
            reverse("usergroup_handler", args=[group_id]),
            {"name": "nope"},
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_delete_requires_can_edit_identities(self):
        group_id = self._create_group_as_admin("del-group")
        self.openfga_client.can_edit_identities.return_value = True
        response = self.client.delete(
            reverse("usergroup_handler", args=[group_id])
        )
        assert http.client.NO_CONTENT == response.status_code, response.content
        self.openfga_client.can_edit_identities.assert_called_once_with(
            self.user
        )

    def test_delete_denied_without_edit_permission(self):
        group_id = self._create_group_as_admin("no-del-group")
        self.openfga_client.can_edit_identities.return_value = False
        response = self.client.delete(
            reverse("usergroup_handler", args=[group_id])
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_list_members_requires_can_view_identities(self):
        group = factory.make_Usergroup()
        self.openfga_client.can_view_identities.return_value = True
        response = self.client.get(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "list_members"},
        )
        assert http.client.OK == response.status_code, response.content
        self.openfga_client.can_view_identities.assert_called_once_with(
            self.user
        )

    def test_list_members_denied_without_view_permission(self):
        group = factory.make_Usergroup()
        self.openfga_client.can_view_identities.return_value = False
        response = self.client.get(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "list_members"},
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_add_member_requires_can_edit_identities(self):
        group = factory.make_Usergroup()
        self.openfga_client.can_edit_identities.return_value = True
        member = factory.make_User()
        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "add_member", "username": member.username},
        )
        assert http.client.OK == response.status_code, response.content
        self.openfga_client.can_edit_identities.assert_called_once_with(
            self.user
        )

    def test_add_member_denied_without_edit_permission(self):
        group = factory.make_Usergroup()
        self.openfga_client.can_edit_identities.return_value = False
        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "add_member", "username": "someone"},
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_remove_member_requires_can_edit_identities(self):
        group = factory.make_Usergroup()
        self.openfga_client.can_edit_identities.return_value = True
        member = factory.make_User()

        self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "add_member", "username": member.username},
        )
        self.openfga_client.reset_mock()
        self.openfga_client.can_edit_identities.return_value = True
        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "remove_member", "username": member.username},
        )
        assert http.client.NO_CONTENT == response.status_code, response.content
        self.openfga_client.can_edit_identities.assert_called_once_with(
            self.user
        )

    def test_remove_member_denied_without_edit_permission(self):
        group = factory.make_Usergroup()
        self.openfga_client.can_edit_identities.return_value = False
        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "remove_member", "username": "someone"},
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_add_entitlement_requires_can_edit_identities(self):
        group = factory.make_Usergroup()
        self.openfga_client.can_edit_identities.return_value = True
        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {
                "op": "add_entitlement",
                "resource_type": "maas",
                "resource_id": 0,
                "entitlement": "can_edit_machines",
            },
        )
        assert http.client.OK == response.status_code, response.content

    def test_add_entitlement_denied_without_can_edit_permission(self):
        group = factory.make_Usergroup()
        self.openfga_client.can_edit_identities.return_value = False
        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {
                "op": "add_entitlement",
                "resource_type": "maas",
                "resource_id": 0,
                "entitlement": "can_edit_machines",
            },
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_remove_entitlement_requires_can_edit_identities(self):
        group = factory.make_Usergroup()
        entitlement = factory.make_Entitlement(group=group)
        self.openfga_client.can_edit_identities.return_value = True
        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {
                "op": "remove_entitlement",
                "resource_type": entitlement.object_type,
                "resource_id": entitlement.object_id,
                "entitlement": entitlement.relation,
            },
        )
        assert http.client.NO_CONTENT == response.status_code, response.content

    def test_remove_entitlement_denied_without_can_edit_permission(self):
        group = factory.make_Usergroup()
        entitlement = factory.make_Entitlement(group=group)
        self.openfga_client.can_edit_identities.return_value = False
        response = self.client.post(
            reverse("usergroup_handler", args=[group.id]),
            {
                "op": "remove_entitlement",
                "resource_type": entitlement.object_type,
                "resource_id": entitlement.object_id,
                "entitlement": entitlement.relation,
            },
        )
        assert http.client.FORBIDDEN == response.status_code, response.content

    def test_list_entitlements_requires_can_view_identities(self):
        group = factory.make_Usergroup()
        self.openfga_client.can_view_identities.return_value = True
        response = self.client.get(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "list_entitlements"},
        )
        assert http.client.OK == response.status_code, response.content

    def test_list_entitlements_denied_without_view_permission(self):
        group = factory.make_Usergroup()
        self.openfga_client.can_view_identities.return_value = False
        response = self.client.get(
            reverse("usergroup_handler", args=[group.id]),
            {"op": "list_entitlements"},
        )
        assert http.client.FORBIDDEN == response.status_code, response.content
