# Data Model: FIPS-Compliant MAAS

**Phase**: 1 — Design & Contracts
**Feature**: FIPS-Compliant MAAS
**Branch**: `fips_compliance`
**Date**: 2026-05-27

---

## Overview

FIPS compliance is primarily a **runtime behavioural change** in MAAS, not a data-model change. FIPS state is ephemeral — read from `/proc/sys/crypto/fips_enabled` at process startup — and is **not persisted** to the database. No new database tables or Alembic migrations are required.

The data entities described here are **Pydantic models** (response models and internal state holders), not database-backed entities.

---

## Entities

### 1. `FIPSStatus` — Runtime FIPS State

**Purpose**: Canonical representation of the FIPS runtime state as detected by MAAS at startup.

**Location**: `src/maascommon/fips.py`

```python
from pydantic import BaseModel, Field


class FIPSStatus(BaseModel):
    """Canonical runtime FIPS state detected from host OS."""

    fips_enabled: bool = Field(
        description="True if FIPS mode is active (read from /proc/sys/crypto/fips_enabled)."
    )
    detection_source: str = Field(
        default="/proc/sys/crypto/fips_enabled",
        description="The source used to detect FIPS mode.",
    )
    detection_error: str | None = Field(
        default=None,
        description="Error message if FIPS detection failed; None if detection succeeded.",
    )
```

**State Transitions**:
```
[process start]
    ↓
detect_fips_mode() reads /proc/sys/crypto/fips_enabled
    ↓ value == "1"                    ↓ value == "0" or file absent     ↓ OSError
FIPSStatus(fips_enabled=True)   FIPSStatus(fips_enabled=False)    FIPSStatus(fips_enabled=False, detection_error=str(e))
                                                                   log WARNING
    ↓
cached as module-level singleton (_FIPS_ENABLED)
    ↓
is_fips_enabled() returns cached value for lifetime of process
```

**Validation Rules**:
- `fips_enabled` is immutable after startup (process restart required to change FIPS mode).
- `detection_error` is set only when the proc file could not be read; in that case `fips_enabled` defaults to `False` (non-FIPS).

---

### 2. `FIPSSystemStatus` — API Response Fragment

**Purpose**: FIPS state as exposed in the MAAS v3 REST API system status endpoint.

**Location**: `src/maasapiserver/v3/api/public/handlers/root.py`

```python
from pydantic import BaseModel


class FIPSSystemStatus(BaseModel):
    """FIPS runtime state fragment included in system status API response."""

    fips_active: bool
    """True if MAAS detected FIPS mode active on this host (from /proc/sys/crypto/fips_enabled)."""
```

This is embedded in the existing `RootGetResponse` (or a new `SystemStatusResponse`):

```python
class RootGetResponse(BaseModel):
    """Root handler response — extended with FIPS state."""

    fips_active: bool
    """FIPS mode active on this MAAS host."""
```

**Field Semantics**:
- `fips_active: true` — MAAS detected `/proc/sys/crypto/fips_enabled == 1`; MAAS is operating in FIPS-compliant mode with all algorithm restrictions active.
- `fips_active: false` — MAAS detected `/proc/sys/crypto/fips_enabled == 0`, or the file is absent (normal on a non-FIPS host); MAAS operates in standard mode.

---

### 3. `FIPSSSHConfig` — SSH Algorithm Allow-Lists

**Purpose**: FIPS-compliant SSH algorithm configuration applied to all paramiko clients.

**Location**: `src/maascommon/fips.py`

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class FIPSSSHConfig:
    """FIPS-compliant SSH algorithm allow-lists for paramiko clients."""

    ciphers: tuple[str, ...] = (
        "aes128-ctr",
        "aes192-ctr",
        "aes256-ctr",
        "aes128-gcm@openssh.com",
        "aes256-gcm@openssh.com",
    )
    kex: tuple[str, ...] = (
        "ecdh-sha2-nistp256",
        "ecdh-sha2-nistp384",
        "diffie-hellman-group14-sha256",
    )
    macs: tuple[str, ...] = (
        "hmac-sha2-256",
        "hmac-sha2-512",
    )
    key_types: tuple[str, ...] = (
        "ecdsa-sha2-nistp256",
        "ecdsa-sha2-nistp384",
        "rsa-sha2-256",
        "rsa-sha2-512",
    )


FIPS_SSH_CONFIG = FIPSSSHConfig()
```

**Usage Rule**: Applied to all paramiko `Transport.get_security_options()` when `is_fips_enabled()` is `True`.

---

### 4. `PowerDriverFIPSStatus` — Driver FIPS Classification

**Purpose**: Machine-readable FIPS compliance classification for each power driver.

**Location**: `src/provisioningserver/drivers/power/registry.py` (or a new `src/provisioningserver/drivers/power/fips.py`)

```python
from enum import Enum


class DriverFIPSStatus(str, Enum):
    """FIPS compliance classification for a power driver."""

    COMPLIANT = "compliant"
    """Driver uses only FIPS-approved cryptographic operations."""

    NON_COMPLIANT_REMEDIABLE = "non_compliant_remediable"
    """Driver has FIPS violations but can be remediated in software."""

    UNSUPPORTED_IN_FIPS = "unsupported_in_fips"
    """Driver uses cryptographic operations that are incompatible at the
    protocol level (e.g., SNMPv1, HMAC-MD5 IPMI cipher suites, plain HTTP).
    Cannot be remediated without hardware/firmware changes."""
```

**Driver Classification Registry**:

| Driver Name | `DriverFIPSStatus` |
|-------------|---------------------|
| `redfish` | `COMPLIANT` |
| `openbmc` | `COMPLIANT` |
| `manual` | `COMPLIANT` |
| `ipmi` | `COMPLIANT` (after enforcement of suite 17 only) |
| `vmware` | `COMPLIANT` (after TLS context fix) |
| `amt` | `COMPLIANT` (after HTTPS enforcement) |
| `hmc` | `COMPLIANT` (after SSH cipher pinning) |
| `mscm` | `COMPLIANT` (after SSH cipher pinning) |
| `wedge` | `COMPLIANT` (after SSH cipher pinning) |
| `hmcz` | `COMPLIANT` (after verify_ssl enforcement) |
| `proxmox` | `COMPLIANT` (after verify_ssl enforcement) |
| `webhook` | `COMPLIANT` (after TLS verification enforcement) |
| `apc` | `UNSUPPORTED_IN_FIPS` (SNMPv1) |
| `eaton` | `UNSUPPORTED_IN_FIPS` (SNMPv1) |
| `raritan` | `UNSUPPORTED_IN_FIPS` (SNMPv2c) |
| `dli` | `UNSUPPORTED_IN_FIPS` (plain HTTP) |
| `msftocs` | `UNSUPPORTED_IN_FIPS` (plain HTTP) |
| `recs` | `UNSUPPORTED_IN_FIPS` (plain HTTP) |
| `seamicro` | `UNSUPPORTED_IN_FIPS` (plain HTTP) |
| `ucsm` | `UNSUPPORTED_IN_FIPS` (plain HTTP XML API) |
| `moonshot` | `UNSUPPORTED_IN_FIPS` (IPMI without suite 17 support) |

---

### 5. `FIPSCryptoLogEvent` — Audit Log Event (Structured)

**Purpose**: Structured log event for FIPS-relevant cryptographic operations. Emitted by structlog for compliance audit trails.

**Location**: `src/maascommon/logging/security.py` (extend existing security log constants)

```python
# FIPS security log event names (add to existing constants)
FIPS_MODE_DETECTED = "FIPS_mode_detected"
FIPS_TLS_HANDSHAKE = "FIPS_tls_handshake"
FIPS_SSH_AUTH = "FIPS_ssh_authentication"
FIPS_CRYPTO_ERROR = "FIPS_crypto_error"
FIPS_DRIVER_REJECTED = "FIPS_driver_rejected"
```

**Structured log event fields** (structlog JSON):

```python
# FIPS mode startup event
{
    "event": "FIPS_mode_detected",
    "fips_mode": True,                   # bool
    "source": "/proc/sys/crypto/fips_enabled",
    "level": "info",
    "timestamp": "2026-05-27T10:00:00Z"
}

# TLS handshake event
{
    "event": "FIPS_tls_handshake",
    "cipher_suite": "ECDHE-RSA-AES256-GCM-SHA384",
    "protocol_version": "TLSv1.3",
    "peer": "10.0.0.1:443",
    "cert_issuer": "CN=MAAS-CA",
    "cert_valid": True,
    "level": "info"
}

# SSH authentication event
{
    "event": "FIPS_ssh_authentication",
    "key_type": "ecdsa-sha2-nistp256",
    "kex": "ecdh-sha2-nistp256",
    "cipher": "aes256-ctr",
    "mac": "hmac-sha2-256",
    "peer": "192.168.1.50",
    "result": "success",
    "level": "info"
}

# Crypto error / FIPS violation
{
    "event": "FIPS_crypto_error",
    "operation": "tls_handshake",
    "error": "Algorithm not permitted under FIPS mode",
    "algorithm": "RC4",
    "peer": "192.168.1.100:443",
    "level": "error"
}

# Driver rejected (FIPS unsupported)
{
    "event": "FIPS_driver_rejected",
    "driver": "apc",
    "reason": "SNMPv1 is not FIPS-compliant",
    "level": "error"
}
```

---

### 6. `FIPSService` — Service Layer FIPS Provider

**Purpose**: Canonical service-layer provider of FIPS runtime state, following MAAS 3-tier architecture.

**Location**: `src/maasservicelayer/services/fips.py`

```python
from maascommon.fips import is_fips_enabled, FIPSStatus
from maasservicelayer.services.base import Service


class FIPSService(Service):
    """
    Service providing FIPS runtime state to the API layer and other services.

    Wraps the maascommon.fips detection utility. Returns cached state;
    no database access or repository needed.
    """

    async def get_fips_status(self) -> FIPSStatus:
        """Return the FIPS runtime status detected at startup."""
        enabled = is_fips_enabled()
        return FIPSStatus(fips_enabled=enabled)
```

**Architecture compliance**:
- No repository needed (no DB persistence).
- Injected into API handlers via dependency injection (FastAPI `Depends`).
- Service is mocked in API-layer tests (`mocked_api_client` fixtures).

---

## State Machine: FIPS Mode Lifecycle

```
┌──────────────────────────────────────────────────────────────────────┐
│                        MAAS Process Lifecycle                        │
├──────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  [Process Start]                                                     │
│       │                                                              │
│       ▼                                                              │
│  detect_fips_mode()                                                  │
│  reads /proc/sys/crypto/fips_enabled                                 │
│       │                                                              │
│       ├─── value == "1" ──→ [FIPS_ACTIVE]                           │
│       │                          │                                   │
│       │                          ▼                                   │
│       │                    All crypto operations use                 │
│       │                    FIPS-approved algorithms only             │
│       │                    • SSH: FIPS cipher list                   │
│       │                    • TLS: min TLS 1.2, approved suites      │
│       │                    • Keys: RSA≥2048 or ECDSA P-256+         │
│       │                    • Hashing: PBKDF2-SHA256 only            │
│       │                    • Go: GOFIPS=1 + boringcrypto             │
│       │                    • UNSUPPORTED-IN-FIPS drivers: rejected   │
│       │                                                              │
│       ├─── value == "0" ──→ [STANDARD_MODE]                         │
│       │                          │                                   │
│       │                          ▼                                   │
│       │                    Standard MAAS behaviour                   │
│       │                    (no restrictions; baseline unchanged)     │
│       │                                                              │
│       └─── OSError ────────→ [FIPS_UNKNOWN → STANDARD_MODE]         │
│                                   │                                  │
│                                   ▼                                  │
│                             Log WARNING                              │
│                             Default to non-FIPS mode                │
│                             Direct admin to verify host config       │
│                                                                      │
│  [Process Running]                                                   │
│       │                                                              │
│       ▼                                                              │
│  is_fips_enabled() returns cached value (immutable)                  │
│  (FIPS mode cannot change without process restart)                   │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

---

## Database Schema Impact

**None.** FIPS runtime state is not persisted. No new tables, columns, or Alembic migrations are needed. The only data-layer change is:

- `src/maasservicelayer/db/tables.py`: No changes.
- `src/maasservicelayer/db/alembic/`: No new migration files.

---

## Validation Rules (Cross-Entity)

| Rule | Entity | Condition | Behaviour |
|------|--------|-----------|-----------|
| RSA key minimum size | `FIPSStatus` (FIPS active) | RSA key size < 2048 | Reject; log `FIPS_crypto_error` |
| SSH cipher allow-list | `FIPSSSHConfig` | Cipher not in FIPS list | Reject connection; log `FIPS_crypto_error` |
| TLS minimum version | All TLS contexts | Protocol < TLS 1.2 | Reject; OpenSSL raises |
| SHA-1 certificate | TLS certificate validation | SHA-1 signature algorithm | Reject; log `FIPS_crypto_error` |
| IPMI cipher suite | IPMI power driver | Suite != 17 when FIPS active | Reject; return user error + log |
| SNMPv1/v2c driver | UNSUPPORTED-IN-FIPS drivers | FIPS mode active | Reject; return `FIPS_driver_rejected` error |
| MD5 password hasher | Django settings | FIPS active + MD5PasswordHasher present | Raise `FIPSConfigurationError` at startup |
| Go HMAC-MD5 (OMAPI) | maas-agent OMAPI | FIPS mode active | Replace with HMAC-SHA256 |
