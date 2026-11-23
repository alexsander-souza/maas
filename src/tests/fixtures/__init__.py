# Copyright 2025-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from contextlib import contextmanager
from pathlib import Path
import typing
from unittest.mock import Mock

import pytest

from maasserver.testing.openfga import OpenFGAClientMock
from maasservicelayer.services import ServiceCollectionV3


def get_test_data_file(filename: str) -> str:
    test_data_path = Path(__file__).parent / "test_data" / filename
    with open(test_data_path, "r") as f:
        return f.read()


class ContextManagerMock:
    def __init__(self, mock):
        self.mock = mock

    def __enter__(self):
        return self.mock

    def __exit__(self, exc_type, exc, tb):
        pass


class AsyncContextManagerMock:
    """Mock for async context managers with nested mocking capabilities."""

    def __init__(self, mock):
        """Initialize with a mock that will be returned from __aenter__."""
        self.mock = mock

    async def __aenter__(self):
        """Enter async context manager."""
        return self.mock

    async def __aexit__(self, exc_type, exc, tb):
        """Exit async context manager."""
        pass

    def request(self, *args, **kwargs):
        """Return mock to support chaining."""
        return self.mock


class AsyncIteratorMock:
    """Mock for async iterators."""

    def __init__(self, iterable) -> None:
        self.iterable = iterable

    def __aiter__(self):
        return self

    async def __anext__(self):
        if len(self.iterable) > 0:
            return self.iterable.pop(0)
        else:
            raise StopAsyncIteration


def create_services_mock() -> Mock:
    services_mock = Mock(ServiceCollectionV3)
    for (
        service_name,
        service_class,
    ) in typing.get_type_hints(ServiceCollectionV3).items():
        setattr(services_mock, service_name, Mock(spec_set=service_class))
    return services_mock


@pytest.fixture
def services_mock():
    yield create_services_mock()


@pytest.fixture
def mock_openfga(mocker):
    openfga_mock = OpenFGAClientMock()
    mocker.patch("maasserver.openfga._get_client", return_value=openfga_mock)
    yield


def _patch_start_workflows(mocker):
    for module_name in (
        "maasserver.models.node",
        "maasserver.models.interface",
        "maasserver.models.signals.vlan",
        "maasserver.models.signals.subnet",
        "maasserver.models.iprange",
        "maasserver.models.staticipaddress",
    ):
        mocker.patch(f"{module_name}.start_workflow")
    mocker.patch("maasserver.bootsources.post_commit_do")


@pytest.fixture
def mock_start_workflows(mocker):
    _patch_start_workflows(mocker)
    yield


def assert_no_post_commit_hooks(stage):
    from maasserver.utils.orm import (
        gen_description_of_hooks,
        post_commit_hooks,
    )

    description = "\n".join(gen_description_of_hooks(post_commit_hooks.hooks))
    try:
        assert not post_commit_hooks.hooks, (
            f"Post-commit hooks leaked {stage}:\n" + description
        )
    finally:
        post_commit_hooks.reset()


@contextmanager
def legacy_maas_server_setup(mocker, patch_workflows=False):
    from maasserver.models import signals
    from maasserver.openfga import get_openfga_client
    from maasserver.testing.fixtures import IntroCompletedFixture

    get_openfga_client.cache_clear()
    mocker.patch.object(
        signals.events, "STATE_TRANSITION_EVENT_CONNECT", False
    )
    if patch_workflows:
        _patch_start_workflows(mocker)
    try:
        with IntroCompletedFixture():
            yield
    finally:
        get_openfga_client.cache_clear()


@pytest.fixture
def maas_region_test(
    maasdb, mocker, request, mock_openfga, mock_start_workflows
):
    """Apply shared region setup not already provided by pytest fixtures."""
    import os
    from pathlib import Path

    from django.db import connection, reset_queries

    assert_no_post_commit_hooks("into test setup")
    reset_queries()
    with connection.cursor() as cursor:
        cursor.execute("SET application_name = %s", (request.node.nodeid,))
    for env_name, dirname in (
        ("MAAS_DATA", "image-storage"),
        ("MAAS_ROOT", "certificates"),
    ):
        root = os.environ.get(env_name)
        if root:
            Path(root, dirname).mkdir(exist_ok=True)
    try:
        with legacy_maas_server_setup(mocker):
            yield
    finally:
        assert_no_post_commit_hooks("from test teardown")
        reset_queries()
