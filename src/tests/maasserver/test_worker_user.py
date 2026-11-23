# Copyright 2012-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test for the system user that represents node-group workers."""

from django.contrib.auth.models import User
import pytest

from maascommon.constants import MAAS_USER_USERNAME
from maasserver.models import UserProfile
from maasserver.models.user import SYSTEM_USERS
from maasserver.worker_user import get_worker_user


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNodeGroupUser:
    """Test the special "user" that workers use to access the API."""

    def test_get_worker_user_always_returns_same_user(self):
        assert get_worker_user().id == get_worker_user().id

    def test_get_worker_user_holds_the_worker_user(self):
        worker_user = get_worker_user()
        assert isinstance(worker_user, User)
        assert worker_user.username == MAAS_USER_USERNAME

    def test_worker_user_is_system_user(self):
        worker_user = get_worker_user()
        assert worker_user.username in SYSTEM_USERS

        def get_user_profile():
            return worker_user.userprofile

        with pytest.raises(UserProfile.DoesNotExist):
            get_user_profile()
