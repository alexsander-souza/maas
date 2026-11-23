# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the workflow module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from temporalio.service import RPCError, RPCStatusCode

from maasserver import workflow as workflow_module


class TestStopWorkflow:
    """Tests for stop_workflow function."""

    def test_stops_workflow_successfully(self, mocker):
        """Test that stop_workflow succeeds when workflow exists."""
        mock_client = MagicMock()
        mock_handle = MagicMock()
        mock_handle.cancel = AsyncMock()
        mock_client.get_workflow_handle = MagicMock(return_value=mock_handle)

        mocker.patch.object(
            workflow_module,
            "get_client_async",
            AsyncMock(return_value=mock_client),
        )

        # Should not raise any exception
        asyncio.run(workflow_module.stop_workflow("deploy:test-id"))

        mock_handle.cancel.assert_called_once()

    def test_handles_workflow_not_found(self, mocker):
        """Test that stop_workflow handles NOT_FOUND status gracefully."""
        mock_client = MagicMock()
        mock_handle = MagicMock()
        mock_handle.cancel = AsyncMock(
            side_effect=RPCError(
                "workflow not found for ID: deploy:test-id",
                RPCStatusCode.NOT_FOUND,
                b"",
            )
        )
        mock_client.get_workflow_handle = MagicMock(return_value=mock_handle)

        mocker.patch.object(
            workflow_module,
            "get_client_async",
            AsyncMock(return_value=mock_client),
        )

        # Should not raise - workflow already gone
        asyncio.run(workflow_module.stop_workflow("deploy:test-id"))

        mock_handle.cancel.assert_called_once()

    def test_propagates_other_rpc_errors(self, mocker):
        """Test that stop_workflow re-raises other RPCErrors."""
        mock_client = MagicMock()
        mock_handle = MagicMock()
        mock_handle.cancel = AsyncMock(
            side_effect=RPCError(
                "connection refused", RPCStatusCode.UNAVAILABLE, b""
            )
        )
        mock_client.get_workflow_handle = MagicMock(return_value=mock_handle)

        mocker.patch.object(
            workflow_module,
            "get_client_async",
            AsyncMock(return_value=mock_client),
        )

        with pytest.raises(RPCError) as cm:
            asyncio.run(workflow_module.stop_workflow("deploy:test-id"))

        assert "connection refused" in str(cm.value)
        mock_handle.cancel.assert_called_once()
