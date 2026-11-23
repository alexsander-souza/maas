# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from collections import Counter

from django.core.exceptions import PermissionDenied, ValidationError
import pytest

from maasserver.models.space import DEFAULT_SPACE_NAME, Space
from maasserver.permissions import NodePermission
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestSpaceManagerGetSpaceOr404:
    def test_user_view_returns_space(self):
        user = factory.make_User()
        space = factory.make_Space()
        assert space == Space.objects.get_space_or_404(
            space.id, user, NodePermission.view
        )

    def test_user_edit_raises_PermissionError(self):
        user = factory.make_User()
        space = factory.make_Space()
        with pytest.raises(PermissionDenied):
            Space.objects.get_space_or_404(space.id, user, NodePermission.edit)

    def test_user_admin_raises_PermissionError(self):
        user = factory.make_User()
        space = factory.make_Space()
        with pytest.raises(PermissionDenied):
            Space.objects.get_space_or_404(
                space.id, user, NodePermission.admin
            )

    def test_admin_view_returns_space(self):
        admin = factory.make_admin()
        space = factory.make_Space()
        assert space == Space.objects.get_space_or_404(
            space.id, admin, NodePermission.view
        )

    def test_admin_edit_returns_space(self):
        admin = factory.make_admin()
        space = factory.make_Space()
        assert space == Space.objects.get_space_or_404(
            space.id, admin, NodePermission.edit
        )

    def test_admin_admin_returns_space(self):
        admin = factory.make_admin()
        space = factory.make_Space()
        assert space == Space.objects.get_space_or_404(
            space.id, admin, NodePermission.admin
        )


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestSpaceManager:
    def test_default_specifier_matches_id(self):
        factory.make_Space()
        space = factory.make_Space()
        factory.make_Space()
        id = space.id
        assert Counter(
            Space.objects.filter_by_specifiers("%s" % id)
        ) == Counter([space])

    def test_default_specifier_matches_name_with_id(self):
        factory.make_Space()
        space = factory.make_Space()
        factory.make_Space()
        id = space.id
        assert Counter(
            Space.objects.filter_by_specifiers("space-%s" % id)
        ) == Counter([space])

    def test_default_specifier_matches_name(self):
        factory.make_Space()
        space = factory.make_Space(name="infinite-improbability")
        factory.make_Space()
        assert Counter(
            Space.objects.filter_by_specifiers("infinite-improbability")
        ) == Counter([space])

    def test_name_specifier_matches_name(self):
        factory.make_Space()
        space = factory.make_Space(name="infinite-improbability")
        factory.make_Space()
        assert Counter(
            Space.objects.filter_by_specifiers("name:infinite-improbability")
        ) == Counter([space])

    def test_class_specifier_matches_attached_subnet(self):
        factory.make_Space()
        space = factory.make_Space()
        subnet = factory.make_Subnet(space=space)
        factory.make_Space()
        assert Counter(
            Space.objects.filter_by_specifiers("subnet:%s" % subnet.id)
        ) == Counter([space])


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestSpace:
    def test_creates_space(self):
        name = factory.make_name("name")
        space = Space(name=name)
        space.save()
        space_from_db = Space.objects.get(name=name)
        assert space_from_db.name == name

    def test_get_default_space_creates_default_space(self):
        default_space = Space.objects.get_default_space()
        assert 0 == default_space.id
        assert DEFAULT_SPACE_NAME == default_space.get_name()
        assert DEFAULT_SPACE_NAME == default_space.name

    def test_invalid_name_raises_exception(self):
        with pytest.raises(ValidationError):
            factory.make_Space(name="invalid*name")

    def test_reserved_name_raises_exception(self):
        with pytest.raises(ValidationError):
            factory.make_Space(name="space-1999")

    def test_undefined_name_raises_exception(self):
        with pytest.raises(ValidationError):
            factory.make_Space(name=Space.UNDEFINED)

    def test_create_sets_name(self):
        space = Space.objects.create(name=None)
        assert "space-%d" % space.id == space.name

    def test_create_does_not_override_name(self):
        name = factory.make_name()
        space = factory.make_Space(name=name)
        assert name == space.name

    def test_nonreserved_name_does_not_raise_exception(self):
        space = factory.make_Space(name="myspace-1999")
        assert "myspace-1999" == space.name

    def test_rejects_names_with_blanks(self):
        with pytest.raises(ValidationError):
            factory.make_Space(name=factory.make_name("Space "))

    def test_rejects_duplicate_names(self):
        space1 = factory.make_Space()
        with pytest.raises(ValidationError):
            factory.make_Space(name=space1.name)

    def test_get_default_space_is_idempotent(self):
        default_space = Space.objects.get_default_space()
        default_space2 = Space.objects.get_default_space()
        assert default_space.id == default_space2.id

    def test_is_default_detects_default_space(self):
        default_space = Space.objects.get_default_space()
        assert default_space.is_default()

    def test_is_default_detects_non_default_space(self):
        name = factory.make_name("name")
        space = factory.make_Space(name=name)
        assert not space.is_default()

    def test_can_be_deleted_if_does_not_contain_subnets(self):
        name = factory.make_name("name")
        space = factory.make_Space(name=name)
        space.delete()
        assert Counter([]) == Counter(Space.objects.filter(name=name))

    def test_sets_null_if_contains_vlan(self):
        space = factory.make_Space()
        subnet = factory.make_Subnet(space=space)
        space.delete()
        subnet = reload_object(subnet)
        assert subnet.vlan.space is None
