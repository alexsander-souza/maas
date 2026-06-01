# API FIPS Impact Reference

**Document ID**: FR-027
**Version**: 1.0
**Feature**: FIPS-Compliant MAAS
**Branch**: `fips_compliance`
**Date**: 2026-05-27
**Status**: Draft — Requires review and approval before MVP release

---

## Purpose

This document enumerates every MAAS REST API endpoint whose behaviour, available options, or accepted inputs **differ when FIPS mode is active** (i.e., when `/proc/sys/crypto/fips_enabled == 1`). It serves as the authoritative contract between the MAAS API layer and:

- **UI team**: Implement FIPS-aware UI adaptations independently (hide/disable non-FIPS options)
- **Third-party API clients**: Update integrations to handle FIPS-restricted responses
- **Compliance auditors**: Verify all API-exposed options are FIPS-compliant when active

**Scope**: Only endpoints with changed behaviour are listed. Endpoints not listed behave identically under FIPS and non-FIPS modes.

---

## FIPS Mode Indicator

All MAAS API responses include the host's FIPS state in the system status endpoint. Clients should query this endpoint first to determine whether FIPS restrictions are active.

---

## Affected Endpoints

### 1. System Status — FIPS State Exposed

**Endpoint**: `GET /api/v3/`
**Method**: GET
**Authentication**: None required (public endpoint)

#### Behaviour Under FIPS Mode

A new field `fips_active` (boolean) is added to the response body. This field reflects the value read from `/proc/sys/crypto/fips_enabled` at MAAS startup.

**Standard mode response** (no change from baseline):
```json
{
  "fips_active": false
}
```

**FIPS-active response**:
```json
{
  "fips_active": true
}
```

#### UI Guidance
- When `fips_active: true`, UI should:
  - Display a FIPS badge/indicator in the system status section.
  - Suppress or grey out UI controls that would trigger non-FIPS operations (see affected endpoints below).
  - Show informational text: "MAAS is operating in FIPS 140-2/140-3 compliant mode."

#### Notes
- `fips_active` reflects the **host OS FIPS state**, not a MAAS configuration setting. It cannot be changed via API.
- There is no `+fips` version tag in the MAAS version string (single package). `fips_active` is the canonical FIPS indicator.

---

### 2. Power Driver Configuration — IPMI Cipher Suite Restriction

**Endpoint**: `PUT /api/v3/machines/{system_id}/power_parameters`
**Related Endpoint**: `GET /api/v3/machines/{system_id}/power_parameters`
**Method**: PUT (set), GET (read)
**Driver**: IPMI (`ipmi`)

#### Behaviour Under FIPS Mode

**Cipher suite options available**:

| Cipher Suite | Non-FIPS | FIPS Mode |
|---|---|---|
| `17` — HMAC-SHA256::HMAC_SHA256_128::AES-CBC-128 | ✅ Available | ✅ **Required / Only option** |
| `3` — HMAC-SHA1::HMAC-SHA1-96::AES-CBC-128 | ✅ Available | ❌ Rejected |
| `8` — HMAC-MD5::HMAC-MD5-128::AES-CBC-128 | ✅ Available | ❌ Rejected |
| `12` — HMAC-MD5::MD5-128::AES-CBC-128 | ✅ Available | ❌ Rejected |

**GET response under FIPS**: The `cipher_suite_id_choices` field returns only `["17"]`.

**PUT request under FIPS**: If `cipher_suite_id` is set to `3`, `8`, or `12`, the API returns:
```json
{
  "error": "cipher_suite_id '3' is not permitted under FIPS mode. Only cipher suite 17 (HMAC-SHA256::HMAC_SHA256_128::AES-CBC-128) is FIPS-compliant.",
  "fips_violation": true,
  "allowed_values": ["17"]
}
```
HTTP status: `422 Unprocessable Entity`

#### UI Guidance
- When `fips_active: true`, the cipher suite dropdown for IPMI power drivers must:
  - Show only **Suite 17**.
  - Remove or disable Suite 3, Suite 8, Suite 12.
  - Display tooltip: "Only IPMI Cipher Suite 17 is FIPS-compliant."

---

### 3. Power Driver Selection — UNSUPPORTED-IN-FIPS Drivers

**Endpoint**: `PUT /api/v3/machines/{system_id}/power_parameters`
**Related Endpoint**: `GET /api/v3/power-types`
**Method**: PUT (set), GET (list available types)

#### Behaviour Under FIPS Mode

The following power drivers are **unavailable** when FIPS mode is active:

| Driver | Reason |
|--------|--------|
| `apc` | SNMPv1 — unencrypted, no FIPS-approved authentication |
| `eaton` | SNMPv1 — unencrypted, no FIPS-approved authentication |
| `raritan` | SNMPv2c — unencrypted, community string auth only |
| `dli` | Plain HTTP basic auth — no encryption |
| `msftocs` | Plain HTTP basic auth — no encryption |
| `recs` | Plain HTTP — no TLS |
| `seamicro` | Plain HTTP — no TLS |
| `ucsm` | HTTP XML API — no TLS |
| `moonshot` | IPMI without Cipher Suite 17 support (protocol-level incompatibility) |

**GET `/api/v3/power-types` under FIPS**:
```json
{
  "power_types": [
    {
      "name": "apc",
      "description": "APC PDU",
      "fips_supported": false,
      "fips_unsupported_reason": "SNMPv1 is not FIPS-compliant. Use a Redfish-capable PDU or SNMPv3 alternative."
    },
    {
      "name": "ipmi",
      "description": "IPMI",
      "fips_supported": true
    },
    ...
  ]
}
```

**PUT request with UNSUPPORTED-IN-FIPS driver under FIPS**: API returns:
```json
{
  "error": "Power driver 'apc' is not supported when MAAS is running on a FIPS-enabled host. SNMPv1 is incompatible with FIPS 140-2/140-3 requirements.",
  "fips_violation": true,
  "fips_supported_alternatives": ["ipmi (cipher suite 17)", "redfish", "openbmc", "webhook (HTTPS with cert verification)"]
}
```
HTTP status: `422 Unprocessable Entity`

#### UI Guidance
- When `fips_active: true`:
  - In the power type selector, grey out (disable) all UNSUPPORTED-IN-FIPS drivers.
  - Show tooltip: "Not supported in FIPS mode. [driver-specific reason]"
  - Do not hide drivers (they must remain visible so users understand the limitation).
  - Show informational banner: "9 power drivers are not supported in FIPS mode."

---

### 4. SSH Keys — Algorithm Restrictions

**Endpoint**: `POST /api/v3/users/{username}/sshkeys`
**Related Endpoint**: `GET /api/v3/users/{username}/sshkeys`
**Method**: POST (import key)

#### Behaviour Under FIPS Mode

**Rejected key types under FIPS**:

| Key Type | Non-FIPS | FIPS Mode |
|----------|----------|-----------|
| `ecdsa-sha2-nistp256` | ✅ Accepted | ✅ Accepted |
| `ecdsa-sha2-nistp384` | ✅ Accepted | ✅ Accepted |
| `ecdsa-sha2-nistp521` | ✅ Accepted | ✅ Accepted |
| `rsa` (≥2048-bit) | ✅ Accepted | ✅ Accepted |
| `rsa` (<2048-bit) | ✅ Accepted | ❌ Rejected |
| `ssh-dss` (DSA) | ✅ Accepted | ❌ Rejected |
| `ssh-ed25519` | ✅ Accepted | ❌ Rejected (EdDSA/Curve25519 not in FIPS 140-2 approved algorithms) |
| `sk-ssh-ed25519@openssh.com` | ✅ Accepted | ❌ Rejected |

**POST response under FIPS with rejected key**:
```json
{
  "error": "SSH key algorithm 'ssh-dss' (DSA) is not permitted under FIPS mode. Accepted algorithms: ecdsa-sha2-nistp256, ecdsa-sha2-nistp384, ecdsa-sha2-nistp521, rsa (≥2048-bit).",
  "fips_violation": true,
  "accepted_algorithms": [
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "rsa (minimum 2048-bit)"
  ]
}
```
HTTP status: `422 Unprocessable Entity`

#### UI Guidance
- When `fips_active: true`:
  - Show info banner on SSH key import: "FIPS mode is active. Accepted key types: ECDSA (P-256/384/521), RSA ≥2048-bit. DSA and Ed25519 keys are not FIPS-compliant."
  - Display inline validation when a rejected key type is pasted.

---

### 5. SSL Keys — Certificate Algorithm Restrictions

**Endpoint**: `POST /api/v3/sslkeys`
**Method**: POST (import TLS certificate)

#### Behaviour Under FIPS Mode

**Rejected certificate properties under FIPS**:

| Property | Non-FIPS | FIPS Mode |
|----------|----------|-----------|
| SHA-256 or stronger signature | ✅ Accepted | ✅ Accepted |
| RSA ≥2048-bit key | ✅ Accepted | ✅ Accepted |
| ECDSA P-256/384/521 key | ✅ Accepted | ✅ Accepted |
| SHA-1 signature | ✅ Accepted | ❌ Rejected |
| MD5 signature | ✅ Accepted | ❌ Rejected |
| RSA <2048-bit key | ✅ Accepted | ❌ Rejected |
| DSA key | ✅ Accepted | ❌ Rejected |

**POST response under FIPS with rejected certificate**:
```json
{
  "error": "TLS certificate uses SHA-1 signature algorithm, which is not permitted under FIPS mode. Re-issue the certificate with SHA-256 or stronger.",
  "fips_violation": true,
  "cert_subject": "CN=example.com",
  "signature_algorithm": "sha1WithRSAEncryption"
}
```
HTTP status: `422 Unprocessable Entity`

#### UI Guidance
- When `fips_active: true`:
  - Show info banner on certificate import: "FIPS mode requires certificates signed with SHA-256 or stronger. SHA-1 and MD5 certificates will be rejected."

---

### 6. Configuration — Password Hasher Validation (Internal, Not Directly Exposed)

**Endpoint**: System startup validation (not a REST API endpoint)
**Affected configuration**: Django `PASSWORD_HASHERS` setting

#### Behaviour Under FIPS Mode

At MAAS startup, when FIPS mode is detected, MAAS validates that `MD5PasswordHasher` is not included in the active `PASSWORD_HASHERS` list. If it is:
- MAAS logs a `FIPS_crypto_error` event at ERROR level.
- MAAS raises a `FIPSConfigurationError` and refuses to start.
- Service journal shows: `"MD5PasswordHasher is not permitted under FIPS mode. Remove it from PASSWORD_HASHERS in Django settings."`

**This is not an API endpoint** — it is a startup configuration gate. The UI is not affected directly, but administrators must resolve this before MAAS will start.

---

### 7. Machine Provisioning — Image Checksum Validation

**Endpoint**: (Internal provisioning workflow — triggered by machine commissioning/deployment)
**Directly triggered by**: `POST /api/v3/machines/{system_id}/commission`, `POST /api/v3/machines/{system_id}/deploy`

#### Behaviour Under FIPS Mode

MAAS validates image checksums using the algorithm provided by the image source. Under FIPS mode:

| Algorithm | Non-FIPS | FIPS Mode |
|-----------|----------|-----------|
| SHA-256 | ✅ Accepted | ✅ Accepted |
| SHA-512 | ✅ Accepted | ✅ Accepted |
| MD5 | ✅ Accepted | ❌ Rejected |

If an image source provides only MD5 checksums:
- MAAS logs a `FIPS_crypto_error` at ERROR level.
- Machine commissioning/deployment fails with:
  ```json
  {
    "error": "Image source provides only MD5 checksums, which are not permitted under FIPS mode. Configure the image source to provide SHA-256 or SHA-512 checksums.",
    "fips_violation": true
  }
  ```

#### UI Guidance
- When `fips_active: true`:
  - Show informational warning on boot source configuration: "FIPS mode requires SHA-256 or SHA-512 image checksums. Boot sources providing only MD5 checksums cannot be used."

---

### 8. Webhook Power Driver — TLS Certificate Verification

**Endpoint**: `PUT /api/v3/machines/{system_id}/power_parameters` (driver: `webhook`)
**Field**: `power_verify_ssl` (boolean)

#### Behaviour Under FIPS Mode

| Setting | Non-FIPS | FIPS Mode |
|---------|----------|-----------|
| `power_verify_ssl: true` | ✅ Accepted | ✅ Required |
| `power_verify_ssl: false` | ✅ Accepted (allows self-signed) | ❌ Rejected |

**PUT response under FIPS with `power_verify_ssl: false`**:
```json
{
  "error": "TLS certificate verification cannot be disabled in FIPS mode. Set power_verify_ssl to true and ensure the webhook endpoint uses a valid FIPS-compliant certificate.",
  "fips_violation": true
}
```
HTTP status: `422 Unprocessable Entity`

Same restriction applies to `proxmox` and `hmcz` drivers that have a `verify_ssl`/`power_verify_ssl` parameter.

#### UI Guidance
- When `fips_active: true`:
  - For webhook, proxmox, and hmcz drivers: disable the "Skip SSL verification" checkbox.
  - Show tooltip: "SSL verification cannot be disabled in FIPS mode."

---

## Non-Affected Endpoints (Unchanged Behaviour)

The following API areas have **identical behaviour** under FIPS and non-FIPS modes:

- Machine CRUD operations (create, list, update, delete)
- Network configuration (subnets, VLANs, fabrics, IP ranges, DHCP)
- User and group management (except SSH key import — see §4)
- Boot resource management (image download — MD5 restriction applies internally, §7)
- Event log queries
- DNS configuration
- Storage configuration
- Tags and annotations
- Zones and resource pools
- Service status (other than `fips_active` addition — see §1)

---

## Error Response Schema (FIPS Violations)

All FIPS-related API errors follow this schema:

```json
{
  "error": "<human-readable description of the FIPS violation>",
  "fips_violation": true,
  "allowed_values": ["<value1>", "<value2>"],           // optional: for enumerated choices
  "fips_supported_alternatives": ["<alt1>", "<alt2>"]  // optional: for driver substitutions
}
```

HTTP Status: `422 Unprocessable Entity` for all FIPS validation failures.

---

## Review and Approval

| Role | Name | Approved | Date |
|------|------|----------|------|
| MAAS API Team Lead | TBD | ☐ | — |
| UI Team Lead | TBD | ☐ | — |
| Compliance Reviewer | TBD | ☐ | — |

**Review required before MVP release** (per FR-027 and SC-010).
