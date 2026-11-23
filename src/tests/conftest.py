# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import pytest

pytest_plugins = ("tests.fixtures",)


@pytest.fixture
def transactional_maasdb(maasdb):
    """Use real top-level transactions for commit-dependent DB tests."""
    from django.db import transaction

    transaction.rollback()
    transaction.set_autocommit(True)
    yield
