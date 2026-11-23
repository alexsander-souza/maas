# Copyright 2012-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from django.contrib.auth.models import User
from piston3.models import Consumer, Token
import pytest

from maascommon.constants import GENERIC_CONSUMER
from maasserver.exceptions import CannotDeleteUserException
from maasserver.models import FileStorage, UserProfile
from maasserver.models.user import get_auth_tokens, SYSTEM_USERS
from maasserver.testing.factory import factory
from maasserver.utils.orm import reload_object


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestUserProfile:
    def test_profile_creation(self):
        # A profile is created each time a user is created.
        user = factory.make_User()
        assert isinstance(user.userprofile, UserProfile)
        assert user == user.userprofile.user

    def test_consumer_creation(self):
        # A generic consumer is created each time a user is created.
        user = factory.make_User()
        consumers = Consumer.objects.filter(user=user, name=GENERIC_CONSUMER)
        assert [user] == [consumer.user for consumer in consumers]

    def test_token_creation(self):
        # A token is created each time a user is created.
        user = factory.make_User()
        [token] = get_auth_tokens(user)
        assert user == token.user

    def test_create_authorisation_token(self):
        # UserProfile.create_authorisation_token calls create_auth_token.
        user = factory.make_User()
        profile = user.userprofile
        consumer, token = profile.create_authorisation_token()
        assert user == token.user
        assert user == consumer.user

    def test_get_authorisation_tokens(self):
        # UserProfile.get_authorisation_tokens calls get_auth_tokens.
        user = factory.make_User()
        consumer, token = user.userprofile.create_authorisation_token()
        assert token in user.userprofile.get_authorisation_tokens()

    def test_delete(self):
        # Deleting a profile also deletes the related user.
        profile = factory.make_User().userprofile
        profile_id = profile.id
        user_id = profile.user.id
        assert User.objects.filter(id=user_id).exists()
        assert UserProfile.objects.filter(id=profile_id).exists()
        profile.delete()
        assert not User.objects.filter(id=user_id).exists()
        assert not UserProfile.objects.filter(id=profile_id).exists()

    def test_delete_consumers_tokens(self):
        # Deleting a profile deletes the related tokens and consumers.
        profile = factory.make_User().userprofile
        token_ids = []
        consumer_ids = []
        for _ in range(3):
            token, consumer = profile.create_authorisation_token()
            token_ids.append(token.id)
            consumer_ids.append(consumer.id)
        profile.delete()
        assert not Consumer.objects.filter(id__in=consumer_ids).exists()
        assert not Token.objects.filter(id__in=token_ids).exists()

    def test_delete_deletes_related_filestorage_objects(self):
        # Deleting a profile deletes the related filestorage objects.
        profile = factory.make_User().userprofile
        profile_id = profile.id
        filestorage = factory.make_FileStorage(owner=profile.user)
        filestorage_id = filestorage.id
        assert FileStorage.objects.filter(id=filestorage_id).exists()
        assert UserProfile.objects.filter(id=profile_id).exists()
        profile.delete()
        assert not FileStorage.objects.filter(id=filestorage_id).exists()
        assert not UserProfile.objects.filter(id=profile_id).exists()

    def test_delete_attached_nodes(self):
        # Cannot delete a user with nodes attached to it.
        profile = factory.make_User().userprofile
        factory.make_Node(owner=profile.user)
        with pytest.raises(CannotDeleteUserException) as error:
            profile.delete()
        assert "1 node(s)" in str(error.value)

    def test_delete_attached_static_ip_addresses(self):
        # Cannot delete a user with static IP address attached to it.
        profile = factory.make_User().userprofile
        factory.make_StaticIPAddress(user=profile.user)
        with pytest.raises(CannotDeleteUserException) as error:
            profile.delete()
        assert "1 static IP address(es)" in str(error.value)

    def test_delete_attached_iprange(self):
        # Cannot delete a user with an IP range attached to it.
        profile = factory.make_User().userprofile
        factory.make_IPRange(user=profile.user)
        with pytest.raises(CannotDeleteUserException) as error:
            profile.delete()
        assert "1 IP range(s)" in str(error.value)

    def test_delete_attached_multiple_resources(self):
        profile = factory.make_User().userprofile
        factory.make_Node(owner=profile.user)
        factory.make_StaticIPAddress(user=profile.user)
        with pytest.raises(CannotDeleteUserException) as error:
            profile.delete()
        assert "1 static IP address(es), 1 node(s)" in str(error.value)

    def test_transfer_resources(self):
        user = factory.make_User()
        node = factory.make_Node(owner=user)
        ipaddress = factory.make_StaticIPAddress(user=user)
        iprange = factory.make_IPRange(user=user)
        new_user = factory.make_User()
        user.userprofile.transfer_resources(new_user)
        assert reload_object(node).owner == new_user
        assert reload_object(ipaddress).user == new_user
        assert reload_object(iprange).user == new_user

    def test_manager_all_users(self):
        users = {factory.make_User() for _ in range(3)}
        all_users = set(UserProfile.objects.all_users())
        assert users == all_users

    def test_manager_all_users_no_system_user(self):
        for _ in range(3):
            factory.make_User()
        usernames = {user.username for user in UserProfile.objects.all_users()}
        assert set(SYSTEM_USERS).isdisjoint(usernames)
