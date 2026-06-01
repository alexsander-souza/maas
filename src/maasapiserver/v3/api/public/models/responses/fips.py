#  Copyright 2026 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).

"""Shared FIPS violation error response schema.

Used by all API handlers that enforce FIPS algorithm restrictions at
import boundaries (SSH keys, TLS certificates, etc.).

All FIPS rejection responses return HTTP 422 with a body that includes
`fips_violation: true` so callers can distinguish FIPS rejections from
ordinary validation errors.
"""

from starlette import status

from maasapiserver.common.api.models.responses.errors import ErrorBodyResponse


class FIPSViolationBodyResponse(ErrorBodyResponse):
    """422 Unprocessable Content response for FIPS algorithm violations.

    Returned by any endpoint that rejects a submitted key, certificate, or
    configuration value because it uses an algorithm not approved by
    FIPS 140-2/140-3.

    Fields
    ------
    fips_violation:
        Always ``True`` — identifies this response as a FIPS rejection.
    allowed_values:
        Optional list of algorithm identifiers that *are* accepted in FIPS
        mode (e.g. ``["ecdsa-sha2-nistp256", "rsa-sha2-256"]``).
    """

    code: int = status.HTTP_422_UNPROCESSABLE_CONTENT
    message: str = "FIPS violation: algorithm not permitted in FIPS mode."
    fips_violation: bool = True
    allowed_values: list[str] | None = None
