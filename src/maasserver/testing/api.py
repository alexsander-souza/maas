# Copyright 2013-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Helpers for API testing."""

__all__ = ["explain_unexpected_response", "make_worker_client"]


from maasserver.models.user import create_auth_token
from maasserver.testing.testclient import MAASSensibleOAuthClient
from maasserver.worker_user import get_worker_user


def make_worker_client(rack_controller):
    """Create a test client logged in as if it were `rack_controller`."""
    assert get_worker_user() == rack_controller.owner, (
        "Rack controller owner should be the MAAS worker user."
    )
    token = create_auth_token(rack_controller.owner)
    return MAASSensibleOAuthClient(rack_controller.owner, token=token)


def explain_unexpected_response(expected_status, response):
    """Return human-readable failure message: unexpected http response."""
    return "Unexpected http status (expected {}): {} - {}".format(
        expected_status,
        response.status_code,
        response.content,
    )
