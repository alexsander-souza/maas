# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import pytest
from twisted.internet.defer import Deferred

from maasserver.models import Config, signals
from maasserver.utils.orm import post_commit_hooks
from tests.fixtures import assert_no_post_commit_hooks


@pytest.mark.usefixtures("maasdb", "maas_region_test")
def test_region_fixture_preserves_base_setup(request):
    from django.db import connection

    assert Config.objects.get_config("completed_intro") is True
    assert signals.events.STATE_TRANSITION_EVENT_CONNECT is False
    with connection.cursor() as cursor:
        cursor.execute("SHOW application_name")
        (application_name,) = cursor.fetchone()
    assert application_name == request.node.nodeid[:63]


@pytest.mark.usefixtures("maasdb")
def test_maasdb_rejects_manual_commit():
    from django.db import transaction
    from django.db.transaction import TransactionManagementError

    with pytest.raises(TransactionManagementError):
        transaction.commit()


def test_post_commit_hook_leak_check_reports_and_resets_hooks():
    post_commit_hooks.add(Deferred())

    with pytest.raises(AssertionError, match="leaked before test setup"):
        assert_no_post_commit_hooks("before test setup")

    assert not post_commit_hooks.hooks
