# Research: FIPS-Compliant MAAS

**Phase**: 0 — Research & Unknowns Resolution
**Feature**: FIPS-Compliant MAAS
**Branch**: `fips_compliance`
**Date**: 2026-05-27

---

## 1. Python Cryptographic Library Behavior on FIPS Hosts

### Decision
The `cryptography` library (pyOpenSSL 26.0) automatically inherits OpenSSL's FIPS restrictions when running on a FIPS-enabled Ubuntu host. No explicit FIPS activation code is needed for `cryptography`-backed operations — the host OS FIPS kernel module gates all operations.

### Rationale
- `cryptography` links directly to the system OpenSSL backend. On Ubuntu 24.04 LTS with `ubuntu-fips` packages installed, OpenSSL operates in FIPS mode and rejects prohibited algorithms at the library level.
- MAAS already uses `cryptography` in `src/provisioningserver/certificates.py` and `src/provisioningserver/security.py`. These paths will automatically fail with `ValueError`/`OpenSSLError` if a FIPS-prohibited algorithm (e.g., MD5, DSA, RSA <2048) is requested.
- Twisted TLS (`OpenSSLCertificateOptions`, `TLSMemoryBIOProtocol`) also inherits this — `src/provisioningserver/drivers/power/utils.py` uses `WebClientContextFactory()` which is FIPS-inherited.

### What MAAS Needs to Do
- Audit `certificates.py` to ensure default key sizes are RSA ≥2048 (ECDSA P-256 preferred).
- Verify no MD5 or SHA-1 is hardcoded for certificate signing.
- Add a startup check that reads `/proc/sys/crypto/fips_enabled` and logs status.
- When FIPS is active, reject non-compliant operations proactively (before OpenSSL raises).

### Alternatives Considered
- **FIPS-specific Python build**: Not required because Ubuntu Pro FIPS provides a FIPS-compliant OpenSSL that Python's `cryptography` picks up automatically.
- **Manual algorithm allow-list in `cryptography`**: Not needed at the library level; OpenSSL FIPS mode enforces it. Needed at the application level (paramiko SSH cipher config).

---

## 2. Paramiko SSH: FIPS-Compliant Configuration

### Decision
Paramiko SSH clients in MAAS (power drivers, provisioningserver) must be explicitly configured with FIPS-approved algorithms at connection time. Paramiko 4.x uses its own algorithm negotiation; the host OpenSSL FIPS mode does **not** automatically restrict paramiko's cipher list.

### Rationale
- MAAS currently uses default Paramiko settings with no cipher pinning in `hmc.py`, `wedge.py`, and `mscm.py`.
- Paramiko 4.x includes weak algorithms (hmac-md5, diffie-hellman-group1-sha1) in its defaults.
- The `Transport.security_options` API allows specifying explicit allow-lists for ciphers, digests, and key types.

### Implementation Pattern

```python
# In maascommon/fips.py (or a shared SSH helper)
FIPS_SSH_CIPHERS = [
    "aes128-ctr", "aes192-ctr", "aes256-ctr",
    "aes128-gcm@openssh.com", "aes256-gcm@openssh.com",
]
FIPS_SSH_KEXES = [
    "ecdh-sha2-nistp256", "ecdh-sha2-nistp384",
    "diffie-hellman-group14-sha256",
]
FIPS_SSH_MACS = ["hmac-sha2-256", "hmac-sha2-512"]
FIPS_SSH_KEYS = ["ecdsa-sha2-nistp256", "rsa-sha2-256", "rsa-sha2-512"]


def configure_fips_ssh(client: paramiko.SSHClient) -> None:
    """Configure SSH client for FIPS-compliant algorithm negotiation."""
    transport = client.get_transport()
    if transport is None:
        return
    opts = transport.get_security_options()
    opts.ciphers = FIPS_SSH_CIPHERS
    opts.digests = FIPS_SSH_MACS
    opts.kex = FIPS_SSH_KEXES
    opts.key_types = FIPS_SSH_KEYS
```

This function is called after `client.connect()` but before any commands are sent, or configured pre-connect via subclassing where needed.

### Alternatives Considered
- **System SSH config (`/etc/ssh/ssh_config`)**: Can be set by Ubuntu FIPS packages, but MAAS cannot rely on system config being present in all deployment scenarios.
- **asyncssh**: Would require replacing paramiko entirely — too high a risk for this MVP scope.

---

## 3. Password Hashing: FIPS-Approved Algorithms

### Decision
Use **PBKDF2-HMAC-SHA256** for all MAAS password hashing in FIPS mode. MAAS already uses Django's `PBKDF2PasswordHasher` as the primary hasher. The development-only `MD5PasswordHasher` must be removed or gated from FIPS hosts.

### Rationale
- **bcrypt is NOT FIPS-approved** (uses Blowfish cipher, not in FIPS 140-2/140-3 approved list).
- **PBKDF2 with HMAC-SHA256 is FIPS-approved** (per NIST SP 800-132).
- MAAS already uses `PBKDF2PasswordHasher` as the Django default, so no user password migration is required for fresh FIPS installs.
- `MD5PasswordHasher` in `djangosettings/development.py` must be blocked or removed in FIPS mode.
- `src/maasservicelayer/models/users.py` uses PBKDF2 — this is correct.

### What MAAS Needs to Do
- Ensure `PASSWORD_HASHERS` in Django settings excludes `MD5PasswordHasher` in FIPS mode.
- The `FIPSService` startup check enforces this (raises `FIPSConfigurationError` if MD5 hasher present in FIPS mode).
- No database migration needed — PBKDF2 is already the default.

### Alternatives Considered
- **bcrypt**: Not FIPS-approved; would need to be replaced.
- **Argon2**: FIPS-approved algorithm but not standard FIPS CMVP module; not available in Ubuntu FIPS OpenSSL. Excluded.
- **scrypt**: Not in FIPS 140-2 approved list for Ubuntu's FIPS module.

---

## 4. FIPS Mode Detection at Startup

### Decision
Read `/proc/sys/crypto/fips_enabled` **once** at process startup (before async event loops start) and cache the result. Log a structured INFO entry (`fips_mode: true/false`). If the file is unreadable, log a WARNING and default to non-FIPS mode.

### Rationale
- This is the sole FIPS detection mechanism per the spec (FR-026).
- `/proc/sys/crypto/fips_enabled` returns `"1"` when the kernel FIPS module is active, `"0"` otherwise.
- Reading at startup avoids repeated I/O on every cryptographic operation.
- Structlog's JSON output format is already used in MAAS and is compliance-tool compatible.

### Implementation

```python
# src/maascommon/fips.py

import os
import structlog

log = structlog.getLogger()
_FIPS_PROC_PATH = "/proc/sys/crypto/fips_enabled"

def detect_fips_mode() -> bool:
    """
    Read FIPS mode from the kernel proc interface.

    Returns True if FIPS mode is active, False otherwise.
    Logs a WARNING if the proc file cannot be read; defaults to False (non-FIPS).
    """
    try:
        with open(_FIPS_PROC_PATH, "r") as f:
            value = f.read().strip()
        enabled = value == "1"
        log.info(
            "fips_mode_detected",
            fips_mode=enabled,
            source=_FIPS_PROC_PATH,
        )
        return enabled
    except OSError as e:
        log.warning(
            "fips_mode_detection_failed",
            error=str(e),
            default="non_fips",
            action="Verify host FIPS configuration manually.",
        )
        return False


# Cached at module import time (called from service startup)
_FIPS_ENABLED: bool | None = None


def is_fips_enabled() -> bool:
    """Return cached FIPS mode status."""
    global _FIPS_ENABLED
    if _FIPS_ENABLED is None:
        _FIPS_ENABLED = detect_fips_mode()
    return _FIPS_ENABLED
```

### FIPS Detection in Go (maas-agent)

```go
// internal/fips/fips.go

package fips

import (
    "os"
    "strings"
    "go.uber.org/zap"
)

const fipsProc = "/proc/sys/crypto/fips_enabled"

// IsEnabled reads the kernel FIPS proc file.
// Returns true if FIPS mode is active; false otherwise.
// Logs the result; on error, defaults to false and logs a warning.
func IsEnabled(log *zap.Logger) bool {
    data, err := os.ReadFile(fipsProc)
    if err != nil {
        log.Warn("fips_mode_detection_failed",
            zap.Error(err),
            zap.String("default", "non_fips"),
        )
        return false
    }
    enabled := strings.TrimSpace(string(data)) == "1"
    log.Info("fips_mode_detected", zap.Bool("fips_mode", enabled))
    return enabled
}
```

---

## 5. Twisted TLS on FIPS Hosts

### Decision
Twisted TLS (via pyOpenSSL) inherits FIPS restrictions from the system OpenSSL automatically — no Twisted-specific FIPS configuration is required. MAAS must ensure `WebClientContextFactory()` is used with certificate verification enabled (no `CERT_NONE`).

### Rationale
- `OpenSSLCertificateOptions` in `provisioningserver/drivers/power/utils.py` uses pyOpenSSL, which links to system OpenSSL.
- FIPS-enabled OpenSSL rejects prohibited algorithms during TLS handshake at the C library level.
- The existing `contextFactory` in `utils.py` enables certificate verification by default — this is correct.

### What MAAS Needs to Do
- Ensure `ssl.PROTOCOL_SSLv23` (deprecated) is replaced with modern TLS context in `vmware.py` / `hardware/vmware.py`.
- Ensure `CERT_NONE` / `CERT_OPTIONAL` is not used in any driver in FIPS mode.
- Set minimum TLS version to TLS 1.2 explicitly in contexts that permit configuration.

---

## 6. Go Agent FIPS Compliance

### Decision
The `maas-agent` and the Temporal server (Go binary) must be built with the **`boringcrypto` build tag** (`go build -tags boringcrypto`) for FIPS-capable Go crypto. At runtime, `GOFIPS=1` (or `GODEBUG=fips140=on` for older Go) must be set when `/proc/sys/crypto/fips_enabled` == 1.

### Rationale
- Go does NOT automatically use the host OpenSSL FIPS module. Standard Go crypto is a pure-Go implementation; FIPS only happens with `boringcrypto` + `GOFIPS=1`.
- BoringCrypto build tag links Go's `crypto/tls`, `crypto/rsa`, etc. to BoringSSL FIPS-validated crypto primitives.
- `GOFIPS=1` (Go 1.21+ unified flag) activates FIPS-only mode at runtime; without it, BoringCrypto does not restrict to FIPS-only algorithms.
- maas-agent (`internal/dhcpd/omapi/authenticator.go`) currently uses `crypto/md5` for HMAC-MD5 — this is **FIPS-prohibited** and must be replaced with HMAC-SHA256 **unconditionally** (not gated on FIPS detection).

### What MAAS Needs to Do
1. **Build**: Add `-tags boringcrypto` to the maas-agent and Temporal server Go build commands in the Makefile / CI pipeline.
2. **Runtime detection**: maas-agent reads `/proc/sys/crypto/fips_enabled` at startup; if active, sets `GOFIPS=1` in environment (or validates it was set by the host) and logs FIPS status.
3. **OMAPI authenticator fix**: Replace HMAC-MD5 with HMAC-SHA256 **unconditionally** (regardless of FIPS mode) in `authenticator.go`. Wire-format algorithm name: `"hmac-sha256"`. Key size (512 bits) unchanged.
4. **Temporal server validation**: Build Temporal server binary in MAAS PPA with `-tags boringcrypto`; set `GOFIPS=1` at runtime when FIPS detected. The Temporal server binary is distributed via the standard MAAS PPA (no separate FIPS PPA needed).

### Alternatives Considered
- **GODEBUG=fips140=on without boringcrypto**: Not sufficient — `GODEBUG=fips140=on` is only meaningful when the binary was built with BoringCrypto. Without the build tag, there is no FIPS-validated crypto path to activate.
- **CGO with host OpenSSL**: Complex, not the standard Go FIPS approach on Ubuntu. BoringCrypto + GOFIPS=1 is the validated Ubuntu approach.

---

## 7. Power Driver FIPS Audit Results

### Summary

Full audit of all 21 power drivers in `src/provisioningserver/drivers/power/`.

| Driver | Transport | Key Crypto Issues | FIPS Status | Action |
|--------|-----------|-------------------|-------------|--------|
| `ipmi.py` | IPMI (ipmitool) | Cipher suites 3 (HMAC-SHA1), 8/12 (HMAC-MD5) accepted; only 17 is FIPS-compliant | **NON-COMPLIANT — Remediable** | Enforce suite 17 only in FIPS mode; reject 3/8/12 with clear error |
| `vmware.py` | HTTPS | `ssl.PROTOCOL_SSLv23` + `CERT_NONE` for "unverified" mode | **NON-COMPLIANT — Remediable** | Replace with modern `ssl.create_default_context()` + cert verification required |
| `amt.py` | WS-MAN HTTP/HTTPS | `--noverifypeer` + `--noverifyhost`; HTTP on port 16992 | **NON-COMPLIANT — Remediable** | Require HTTPS (port 16993) + cert verification in FIPS mode |
| `hmc.py` | SSH (paramiko) | `AutoAddPolicy()` + no cipher pinning | **NON-COMPLIANT — Remediable** | Replace AutoAddPolicy; pin FIPS SSH algos |
| `mscm.py` | SSH (paramiko) | `AutoAddPolicy()` + no cipher pinning | **NON-COMPLIANT — Remediable** | Replace AutoAddPolicy; pin FIPS SSH algos |
| `wedge.py` | SSH (paramiko) | `AutoAddPolicy()` + no cipher pinning | **NON-COMPLIANT — Remediable** | Replace AutoAddPolicy; pin FIPS SSH algos |
| `hmcz.py` | HTTPS | Optional `verify_ssl=False` | **NON-COMPLIANT — Remediable** | Disallow `verify_ssl=False` in FIPS mode |
| `proxmox.py` | HTTPS | Optional `verify_ssl=False` | **NON-COMPLIANT — Remediable** | Disallow `verify_ssl=False` in FIPS mode |
| `webhook.py` | HTTP/HTTPS | Optional insecure TLS; no cert enforcement | **NON-COMPLIANT — Remediable** | Require verified TLS in FIPS mode |
| `redfish.py` | Redfish/HTTPS | Uses `WebClientContextFactory()` (verified by default) | **COMPLIANT** | No change |
| `openbmc.py` | HTTPS REST | Uses `WebClientContextFactory()` | **COMPLIANT** | No change |
| `manual.py` | None | No crypto | **COMPLIANT** | No change |
| `apc.py` | SNMPv1 | Community string auth, no encryption | **UNSUPPORTED-IN-FIPS** | Document as unsupported; show user-facing notice |
| `eaton.py` | SNMPv1 | Community string auth, no encryption | **UNSUPPORTED-IN-FIPS** | Document as unsupported; show user-facing notice |
| `raritan.py` | SNMPv2c | Community string auth, no encryption | **UNSUPPORTED-IN-FIPS** | Document as unsupported; show user-facing notice |
| `dli.py` | HTTP | Plain HTTP basic auth in URL | **UNSUPPORTED-IN-FIPS** | Document as unsupported; show user-facing notice |
| `msftocs.py` | HTTP | Plain HTTP basic auth | **UNSUPPORTED-IN-FIPS** | Document as unsupported; show user-facing notice |
| `recs.py` | HTTP | Plain HTTP basic auth | **UNSUPPORTED-IN-FIPS** | Document as unsupported; show user-facing notice |
| `seamicro.py` | HTTP | Plain HTTP; no TLS | **UNSUPPORTED-IN-FIPS** | Document as unsupported; show user-facing notice |
| `ucsm.py` | HTTP XML API | Plain HTTP (`urlopen`) | **UNSUPPORTED-IN-FIPS** | Document as unsupported; show user-facing notice |
| `moonshot.py` | IPMI (ipmitool) | No cipher suite pinned; ipmitool defaults may include non-FIPS suites | **UNSUPPORTED-IN-FIPS** | Document as unsupported unless ipmitool suite 17 can be enforced |

**IPMI Detail**: Only IPMI Cipher Suite 17 (HMAC-SHA256::HMAC_SHA256_128::AES-CBC-128) is FIPS-compliant. Suite 3 (HMAC-SHA1) and suites 8/12 (HMAC-MD5) are prohibited. IPMI cipher suite 0 (no auth) is also prohibited. In FIPS mode, `ipmi.py` must reject any cipher suite other than 17.

### User-Facing Notice for Unsupported Drivers
When a user attempts to use an UNSUPPORTED-IN-FIPS driver while FIPS mode is active, MAAS must return:
```
This power driver (<driver_name>) uses cryptographic operations that are
incompatible with FIPS 140-2/140-3 mode. This driver is not supported when
MAAS is running on a FIPS-enabled host. To manage this hardware in a FIPS
environment, use a FIPS-compatible management interface (e.g., Redfish over
HTTPS, or IPMI with Cipher Suite 17).
```

---

## 8. Temporal Server and Python SDK FIPS Compliance

### Decision
- **Temporal Server (Go binary)**: Build with `-tags boringcrypto`; validate that `GOFIPS=1` enables FIPS-only mode. Distributed via standard MAAS PPA (no separate FIPS PPA). Risk: HIGH — MAAS team owns this.
- **Temporal Python SDK**: Validate it uses host-provided FIPS OpenSSL (via grpc and cryptography libraries) and does not bundle non-FIPS native crypto. Risk: MEDIUM — validate in integration testing.

### Rationale
- Temporal server uses gRPC/TLS for all inter-service communication; this must use FIPS-approved cipher suites.
- The Python Temporal SDK (gRPC) uses the `grpcio` package, which links to the system's BoringSSL or OpenSSL. On a FIPS Ubuntu host, grpcio should inherit FIPS restrictions — this must be validated.
- Neither Temporal upstream nor grpcio upstream will independently prioritize Ubuntu FIPS compliance; the MAAS team must own validation and (if needed) patching.

### Validation Steps
1. Run Temporal server on FIPS Ubuntu 24.04 VM with `GOFIPS=1` set.
2. Inspect Temporal gRPC cipher negotiation with `openssl s_client` or `wireshark`.
3. Confirm only FIPS-approved cipher suites (TLS_AES_256_GCM_SHA384, ECDHE-RSA-AES256-GCM-SHA384, etc.).
4. For Python SDK: run `strace`/`ltrace` or `auditd` to confirm no non-FIPS algorithm invocations.

### Alternatives Considered
- **Patching Temporal directly**: Fallback if BoringCrypto + GOFIPS=1 is insufficient. Unlikely needed since BoringCrypto is the standard FIPS Go approach.
- **Separate FIPS Temporal package**: Explicitly excluded by spec (no separate PPA).

---

## 9. PPA Dependency Engagement: Curtin and pylxd

### Decision
Engage Curtin (Canonical-maintained) and pylxd upstream owners to confirm FIPS-compatible operation. Both are expected to rely on host-provided OpenSSL FIPS crypto (no bundled non-FIPS native extensions). Risk: MEDIUM — contingent on upstream cooperation.

### Status
- **Curtin**: Written in Python; uses standard libraries (requests, apt). Expected to inherit host OpenSSL FIPS automatically. Canonical team engagement recommended within first sprint.
- **pylxd**: Python LXD client; uses `requests` + `websocket-client`. Both link to system OpenSSL. Expected FIPS-compatible — validate in integration tests.
- If upstream cooperation is not obtained within the MVP timeline, the MAAS team will formally document these as outstanding compliance gaps with risk assessment and mitigations (documented in release notes).

---

## 10. CI/CD FIPS Integration Tests

### Decision
Add a dedicated FIPS integration test job to the MAAS CI/CD pipeline (`.github/workflows/`) that runs the **standard MAAS package** on a FIPS-enabled Ubuntu 24.04 LTS VM and validates all FIPS compliance requirements. No separate FIPS build job; no separate FIPS artifact.

### Test Scope
1. MAAS detects `/proc/sys/crypto/fips_enabled` correctly and logs `fips_mode: true`.
2. API system status returns `fips_active: true`.
3. All SSH connections use only FIPS-approved cipher suites (validated via SSH debug logs).
4. All TLS connections use TLS 1.2+ and approved cipher suites (validated via `sslscan`/`openssl s_client`).
5. No `algorithm not permitted` errors in MAAS logs over 7-day soak test (abbreviated in CI).
6. Provisioning workflow: image download + checksum verification completes without FIPS errors.

### Tooling
- `sslscan 2.x` for TLS cipher inspection
- `ssh -v` debug logging for SSH cipher negotiation
- `auditd` (Linux Audit Daemon) for FIPS violation events
- `journalctl -u maas-regiond` for startup FIPS log entry

---

## 11. API FIPS Impact Reference (FR-027)

### Decision
Produce `contracts/api-fips-impact-reference.md` as the authoritative document listing all MAAS API endpoints whose behaviour changes under FIPS mode. See `contracts/api-fips-impact-reference.md` for full details.

### Key Affected Endpoints (summary)
- `GET /api/v3/` (or system status): Returns `fips_active: true/false`
- `POST /api/v3/machines/{id}/power_params` (IPMI): Cipher suite 17 only in FIPS mode; other suites rejected
- Power driver configuration endpoints: UNSUPPORTED-IN-FIPS drivers return error when FIPS active
- SSH key import: DSA keys and RSA <2048-bit keys rejected in FIPS mode
- SSL key management: SHA-1 signed certificates rejected in FIPS mode

---

## Open Items (Resolved)

| Item | Resolution |
|------|-----------|
| Is bcrypt FIPS-approved? | No — use PBKDF2-HMAC-SHA256 (already default) |
| Does Python cryptography library need explicit FIPS config? | No — inherits OpenSSL FIPS automatically |
| Does Go crypto need special configuration? | Yes — boringcrypto build tag + GOFIPS=1 at runtime |
| Does paramiko need explicit cipher pinning? | Yes — FIPS mode does not restrict paramiko automatically |
| Which IPMI cipher suite is FIPS-compliant? | Only Cipher Suite 17 (HMAC-SHA256::HMAC_SHA256_128::AES-CBC-128) |
| Is maas-agent OMAPI authenticator FIPS-compliant? | No — uses HMAC-MD5; replaced unconditionally with HMAC-SHA256 (wire name: `"hmac-sha256"`) regardless of FIPS mode |
| Should snap be supported for MVP? | No — deferred to post-MVP per spec decision |
| Is there a separate FIPS MAAS package? | No — single standard package; runtime detection only |
