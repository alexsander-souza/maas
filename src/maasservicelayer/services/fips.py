#  Copyright 2026 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).

import structlog

from maascommon.fips import FIPS_ENABLED_PATH, FIPSStatus, is_fips_enabled
from maascommon.logging.security import FIPS_MODE_DETECTED
from maasservicelayer.services.base import Service

logger = structlog.getLogger()


class FIPSService(Service):
    """Service providing FIPS mode status for the running host."""

    async def get_fips_status(self) -> FIPSStatus:
        """Return the FIPS mode status as detected from the host OS."""
        return FIPSStatus(
            fips_enabled=is_fips_enabled(),
            source="/proc/sys/crypto/fips_enabled",
        )

    async def emit_startup_log(self) -> None:
        """Emit FIPS_MODE_DETECTED structured log event at regiond startup.

        Logs at INFO level with fips_mode and source fields.  Falls back to
        WARNING if detection raises an unexpected exception.
        """
        try:
            status = await self.get_fips_status()
            logger.info(
                FIPS_MODE_DETECTED,
                fips_mode=status.fips_enabled,
                source=status.source,
            )
        except Exception as exc:
            logger.warning(
                FIPS_MODE_DETECTED,
                fips_mode=None,
                source=FIPS_ENABLED_PATH,
                error=str(exc),
            )
