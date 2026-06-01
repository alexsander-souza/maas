#  Copyright 2026 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).

"""Unit tests for the fips_active field on GET /api/v3/."""

from unittest.mock import AsyncMock, Mock

from httpx import AsyncClient
import pytest

from maasapiserver.v3.constants import V3_API_PREFIX
from maascommon.fips import FIPSStatus
from maasservicelayer.services import ServiceCollectionV3
from maasservicelayer.services.fips import FIPSService


@pytest.mark.asyncio
class TestRootFIPSApi:
    """Tests for fips_active field in GET /api/v3/."""

    async def test_get_fips_active_true(
        self,
        mocked_api_client: AsyncClient,
        services_mock: ServiceCollectionV3,
    ) -> None:
        """Root endpoint returns fips_active: true when host FIPS is active."""
        services_mock.fips = Mock(FIPSService)
        services_mock.fips.get_fips_status = AsyncMock(
            return_value=FIPSStatus(
                fips_enabled=True,
                source="/proc/sys/crypto/fips_enabled",
            )
        )

        response = await mocked_api_client.get(f"{V3_API_PREFIX}/")

        assert response.status_code == 200
        body = response.json()
        assert body["fips_active"] is True

    async def test_get_fips_active_false(
        self,
        mocked_api_client: AsyncClient,
        services_mock: ServiceCollectionV3,
    ) -> None:
        """Root endpoint returns fips_active: false on a non-FIPS host."""
        services_mock.fips = Mock(FIPSService)
        services_mock.fips.get_fips_status = AsyncMock(
            return_value=FIPSStatus(
                fips_enabled=False,
                source="/proc/sys/crypto/fips_enabled",
            )
        )

        response = await mocked_api_client.get(f"{V3_API_PREFIX}/")

        assert response.status_code == 200
        body = response.json()
        assert body["fips_active"] is False

    async def test_get_fips_active_field_present(
        self,
        mocked_api_client: AsyncClient,
        services_mock: ServiceCollectionV3,
    ) -> None:
        """Root endpoint always includes fips_active in the response body."""
        services_mock.fips = Mock(FIPSService)
        services_mock.fips.get_fips_status = AsyncMock(
            return_value=FIPSStatus(
                fips_enabled=False,
                source="/proc/sys/crypto/fips_enabled",
            )
        )

        response = await mocked_api_client.get(f"{V3_API_PREFIX}/")

        assert response.status_code == 200
        assert "fips_active" in response.json()
