
| Index | MA295 |  |  |
| :---- | :---- | :---- | :---- |
| Title | FIPS-Compliant MAAS |  |  |
| **Type** | **Author(s)** | **Status** | **Created** |
| Implementation | MAAS Team | Draft | 2026-04-23 |
|  | **Reviewer(s)** | **Status** | **Date** |
|  | Pending assignment | Pending Review | — |

# Abstract

MAAS cannot currently run on a Ubuntu host with FIPS 140-2/140-3 mode active. FIPS mode enforces kernel-level restrictions on cryptographic algorithms, causing MAAS to fail at startup or during operation due to prohibited uses of MD5, RC4, DSA, and weak TLS in its SSH clients, DHCP/DNS subsystems, and power drivers. This specification defines the changes required to make MAAS operate correctly on a FIPS-enabled Ubuntu 24.04 LTS host using the standard snap package, with no separate FIPS build artifact, by detecting FIPS mode at runtime and enforcing FIPS-approved algorithms across all components. The `.deb` package delivery path is deferred to a later release.

# Rationale

Enterprise and government organizations subject to FIPS 140-2/140-3 compliance requirements must run all infrastructure management software on FIPS-enabled hosts. MAAS is untested and unsupported on FIPS hosts. Without this feature, MAAS cannot be adopted in regulated sectors, which blocks a significant class of enterprise deployments.

The specific pain points are:

- MAAS services crash or log algorithm-not-permitted errors on a FIPS host because of MD5 use in DHCP OMAPI (Object Management API) authentication, HMAC-MD5 in BIND9 rndc (Remote Name Daemon Control) key configuration, weak SSH cipher defaults in paramiko, and legacy SSL contexts in power drivers.  
- There is no mechanism for an administrator or compliance auditor to confirm that MAAS is operating in FIPS-compliant mode without inspecting individual cryptographic operations.  
- Nine power drivers use protocols that are fundamentally incompatible with FIPS (SNMPv1, plain HTTP) and have no documented status, leaving operators with no guidance.

# Specification

## Key Design Decisions

- **Fernet backward compatibility**: The AES-256-GCM replacement in `provisioningserver/security.py` includes a backward-compatibility path that auto-detects and decrypts legacy Fernet tokens (identified by the `0x80` version byte prefix). This works on both FIPS and non-FIPS hosts because the legacy Fernet decryption uses the same PBKDF2-derived key material — no DB migration or secret re-encryption is needed since tokens are ephemeral RPC payloads, not stored at rest.
- **Single package, runtime detection**: A separate FIPS snap would require a parallel build and distribution channel. Runtime detection via `/proc/sys/crypto/fips_enabled` achieves the same result with a single artifact, consistent with how Ubuntu Pro FIPS is designed to work. The snap package is the primary delivery mechanism for the FIPS-compliant MVP; `.deb` packaging is deferred.
- **`core` snap baseline**: A FIPS-enabled `core26` snap (`fips-updates/stable` channel) is not yet available (ETA early 2027). For the MVP, MAAS will ship with the standard `core26` snap and rely on the host's FIPS kernel modules at the OS level. Once a FIPS-enabled `core26` becomes available, the installation guide will document the channel switch as a manual prerequisite step.
- **HMAC-SHA256 upgrade applied unconditionally**: Applying the OMAPI and rndc algorithm changes only in FIPS mode would leave non-FIPS hosts using HMAC-MD5 indefinitely. HMAC-SHA256 is a safe, non-breaking upgrade on all hosts, so the change is applied unconditionally.

## User Stories

### **\[1\] As an infrastructure administrator, I want to install and run MAAS on a FIPS-enabled Ubuntu host using the standard package, so that I can manage bare-metal infrastructure without violating my organization's FIPS compliance requirements.**

An administrator at a government or regulated-enterprise organization installs MAAS on an Ubuntu 24.04 LTS host that has FIPS mode enabled via Ubuntu Pro. They use the standard `snap install maas` workflow with the regular `core26` snap — the host OS FIPS kernel modules provide the cryptographic enforcement layer. A dedicated FIPS-enabled `core26` snap is not yet available (ETA early 2027). MAAS detects FIPS mode at startup and adapts its cryptographic behavior automatically. All services start successfully and remain operational.

#### Acceptance criteria

- Given a FIPS-enabled Ubuntu 24.04 LTS host, when the administrator runs `snap install maas` with the standard `core26` snap and MAAS services start, then regiond, rackd, and maas-agent all reach a running state with no FIPS-violation errors in the service journal.
- Given MAAS is running on a FIPS-enabled host, when it performs cryptographic operations, then no `algorithm not permitted` kernel errors occur.  
- Given MAAS is running on a FIPS-enabled host, when the administrator performs provisioning, image download, and machine management via the API, then all operations complete successfully with no cryptographic failures.  
- Given MAAS is installed on a non-FIPS host, when the administrator installs and operates the standard snap package, then MAAS behavior is identical to the pre-feature baseline with no regressions.

#### Work Items

- Implement FIPS mode detection utilities (requirements 1, 2): Python utility in `maascommon`, Go module in `maasagent`.  
- Implement power driver classification and FIPS-conditional enforcement (requirements 12, 13): IPMI cipher suite enforcement, SSL verification requirements, and unsupported driver rejection.
- Apply SSH and TLS algorithm hardening (requirements 3, 8): enforce FIPS-approved algorithms across all paramiko clients and TLS context construction sites.
- Upgrade DHCP/DNS HMAC algorithms and key generation (requirements 4, 5, 6, 11): replace HMAC-MD5 with HMAC-SHA256, enforce RSA/ECDSA key constraints, use CSPRNG for certificate serial numbers, and replace the PostgreSQL BMC index MD5 hash.
- Apply unconditional hardening changes (requirements 7, 9): Fernet→AES-256-GCM migration, SHA-1→SHA-256 for display uses.
- Implement FIPS-conditional startup gates (requirement 14): Go FIPS activation.
- Document the `core` snap situation: MVP uses standard `core26` with host OS FIPS kernel modules; provide guidance for switching to the `fips-updates/stable` channel once a FIPS-enabled `core26` ships (ETA early 2027).

### **\[2\] As an infrastructure administrator, I want MAAS to expose its detected FIPS state via the API and startup logs, so that I can confirm FIPS-compliant operation without inspecting cryptographic operations directly or accessing the build pipeline.**

After installation, the administrator needs a simple, authoritative signal that MAAS is running in FIPS mode. They check the MAAS API system status endpoint and the service journal. Both must confirm FIPS mode without requiring access to source code, CI/CD metadata, or a separate FIPS package identifier.

#### Acceptance criteria

- Given MAAS is installed on a FIPS-enabled host, when MAAS services start, then the service journal contains a structured JSON entry `{"event": "fips_mode_detected", "fips_mode": true, "source": "/proc/sys/crypto/fips_enabled"}` at INFO level.  
- Given MAAS is running on a FIPS-enabled host, when the administrator queries `GET /MAAS/a/v3/`, then the response includes `"fips_active": true`.  
- Given MAAS is installed on a non-FIPS host, when MAAS starts, then the journal entry contains `"fips_mode": false` and `GET /MAAS/a/v3/` returns `"fips_active": false`.  
- Given `/proc/sys/crypto/fips_enabled` cannot be read at startup (OSError), when MAAS starts, then a WARNING is logged, MAAS defaults to standard mode, and the administrator is directed to verify host FIPS configuration. An absent file is not an error — it is the normal state on a non-FIPS host.

#### Work Items

- Add `fips_active: bool` field to the `RootGetResponse` Pydantic model, populated by `FIPSService` injected via FastAPI dependency injection.  
- Implement `FIPSService` in the service layer to wrap `is_fips_enabled()` and emit the `fips_mode_detected` structured log event at startup.  
- Add `fips_supported: bool` and `fips_unsupported_reason: str | None` fields to the power-types list API response, derived from the `DriverFIPSStatus` registry.

### **\[3\] As a compliance auditor, I want MAAS to produce structured, machine-parsable audit logs of cryptographic events and enforce FIPS algorithm restrictions at API boundaries, so that I can verify FIPS-compliant operation from log evidence alone.**

A compliance auditor reviewing a regulated MAAS deployment needs to confirm that all cryptographic operations use approved algorithms. They use standard log analysis tools to query structured JSON log output. They also need the API to reject non-compliant SSH keys and TLS certificates at import time, producing clear evidence of enforcement.

#### Acceptance criteria

- Given MAAS is running on a FIPS-enabled host, when any outbound TLS connection is made, then the journal contains a `fips_tls_handshake` event with fields `cipher_suite`, `protocol_version`, `peer`, `cert_issuer`, and `cert_valid`.  
- Given MAAS is running on a FIPS-enabled host, when a paramiko SSH session is established, then the journal contains a `fips_ssh_authentication` event with fields `key_type`, `kex`, `cipher`, `mac`, `peer`, and `result`.
- Given MAAS is running on a FIPS-enabled host, when a FIPS violation is detected (algorithm rejected, driver unsupported), then the journal contains a `fips_crypto_error` or `fips_driver_rejected` event with fields identifying the operation, algorithm, and peer.  
- Given FIPS mode is active, when a user submits a `POST /MAAS/a/v3/users/{username}/sshkeys` request with a DSA or Ed25519 key, or an RSA key under 2,048 bits, then the API returns HTTP 422 with `"fips_violation": true` in the response body.  
- Given FIPS mode is active, when a user submits a `POST /MAAS/a/v3/sslkeys` request with a SHA-1 or MD5-signed certificate, then the API returns HTTP 422 with `"fips_violation": true` in the response body.  
- Given a compliance auditor runs `sslscan` against all MAAS TLS endpoints on a FIPS host, then only TLS 1.2 and TLS 1.3 connections with FIPS-approved cipher suites are offered.

#### Work Items

- Emit `fips_tls_handshake` structured log events at all outbound Twisted/pyOpenSSL TLS connection sites.  
- Emit `fips_ssh_authentication` structured log events after each paramiko SSH session negotiation in hmc, mscm, and wedge drivers.
- Emit `fips_crypto_error` and `fips_driver_rejected` structured log events at every FIPS rejection site.  
- Add FIPS SSH key algorithm validation to the SSH keys API handler; return a shared FIPS violation error response on rejection.  
- Add FIPS TLS certificate algorithm validation to the SSL keys API handler; return a shared FIPS violation error response on rejection.  
- Implement a shared FIPS violation error response Pydantic model for consistent 422 responses across all rejection paths.  
- Add log event name constants to `maascommon/logging/security.py`.

### **\[4\] As an infrastructure administrator, I want MAAS-initiated SSH sessions to managed machines to use only FIPS-approved algorithms, so that SSH connections do not violate FIPS mode even when the managed machine's SSH server advertises non-compliant options.**

When MAAS connects to a managed machine via SSH (for power control, commissioning, or deployment), the algorithm negotiation must be controlled by MAAS, not by the managed machine's default configuration. If the remote server cannot negotiate a FIPS-approved algorithm set, MAAS must reject the connection with a clear error rather than silently falling back to a prohibited algorithm.

#### Acceptance criteria

- Given MAAS on a FIPS host initiates an SSH connection, when the session is negotiated, then only the approved ciphers (aes128-ctr, aes192-ctr, aes256-ctr, aes128-gcm@openssh.com, aes256-gcm@openssh.com), key exchange methods (diffie-hellman-group14-sha256, ecdh-sha2-nistp256, ecdh-sha2-nistp384), and MACs (hmac-sha2-256, hmac-sha2-512) are used.  
- Given MAAS on a FIPS host generates SSH host keys, when keys are generated, then they use ecdsa-sha2-nistp256 or RSA ≥ 2,048-bit; DSA and RSA \< 2,048-bit keys are never generated.  
- Given a remote SSH server that only advertises `hmac-md5`, when MAAS attempts a connection in FIPS mode, then MAAS rejects the connection and logs a `fips_crypto_error` event; it does not fall back to a non-compliant algorithm.  
- Given FIPS mode is active and an IPMI power driver operation is requested with cipher suite 3, 8, or 12, when the request is processed, then MAAS returns a user-facing error and logs a `fips_crypto_error` event; only cipher suite 17 is used.

#### Work Items

- Apply the `FIPSSSHConfig` allow-lists to all paramiko SSH clients in hmc, mscm, and wedge drivers.  
- Enforce FIPS-conditional SSH key generation in `provisioningserver/security.py`; reject DSA and RSA \< 2,048-bit when FIPS is active.  
- Enforce IPMI cipher suite 17 in the ipmitool invocation in FIPS mode; reject suites 3, 8, and 12\.  
- Validate Temporal TLS configuration in maas-agent uses `MinVersion: tls.VersionTLS12` and only FIPS-approved cipher suites.

### **\[5\] As an infrastructure administrator, I want every MAAS release to be automatically validated against a FIPS-enabled Ubuntu host in CI/CD, so that FIPS regressions are caught before a release reaches production.**

Currently there is no automated FIPS validation in the MAAS CI/CD pipeline. A regression in FIPS-compliant behavior would only be discovered by operators in production. A per-release FIPS integration test job must run the standard MAAS package on a FIPS-enabled host and gate publication on the result.

#### Acceptance criteria

- Given a standard MAAS release is triggered, when the CI/CD pipeline runs, then a dedicated FIPS integration test job installs the standard snap on a FIPS-enabled Ubuntu 24.04 LTS runner and executes the FIPS integration test suite.
- Given the FIPS integration test job completes with failures, when the pipeline evaluates the result, then artifact publication is blocked.  
- Given the FIPS integration tests run, when they execute, then they verify startup log FIPS detection, `fips_active` API field, SSH algorithm negotiation, TLS cipher suites, IPMI cipher rejection, image download without FIPS errors, Go agent FIPS log entry, and zero algorithm-not-permitted errors over ten minutes of normal operation.  
- Given a published MAAS artifact, when a release auditor reviews CI/CD metadata, then they can confirm FIPS integration tests passed for that release on a FIPS-enabled Ubuntu host.

#### Work Items

- Write the FIPS integration test suite covering the eight verification scenarios listed in the Testing section.  
- Add `--fips-host`, `--maas-url`, and `--maas-api-key` pytest CLI options and corresponding `fips_enabled` / `fips_disabled` fixtures to `tests/conftest.py`.  
- Add a `fips-integration` CI/CD job to the GitHub Actions workflow that installs the standard MAAS snap on an Ubuntu 24.04 FIPS runner and gates release publication on the result.

### **\[6\] As an infrastructure administrator, I want all MAAS snap-bundled dependencies to operate without FIPS violations on a FIPS-enabled host, so that third-party components distributed within the MAAS snap do not break compliance.**

MAAS ships Temporal server (Go binary), Temporal Python SDK, Curtin, and pylxd within the MAAS snap. On a FIPS host, any of these may use prohibited algorithms and cause audit failures or crashes. MAAS-owned components must be validated and rebuilt if needed; upstream-owned components must be audited and their compliance status documented. The `.deb` PPA delivery path for these dependencies is deferred.

#### Acceptance criteria

- Given the Temporal server is running on a FIPS-enabled host, when it processes gRPC/TLS and internal workflow operations, then no FIPS-violation errors appear in Temporal logs or system audit events.  
- Given the Temporal Python SDK communicates with the Temporal server over gRPC/TLS, when connections are established, then only FIPS-approved cipher suites are negotiated and no bundled non-FIPS native crypto is used.  
- Given Curtin and pylxd are operating on a FIPS-enabled host, when they perform their normal functions, then upstream owners have confirmed FIPS-compatible operation or the MAAS team has documented the compliance status and any mitigations.  
- Given a FIPS-incompatible snap-bundled dependency cannot be remediated in time, when the MAAS team evaluates options, then the compliance gap is documented with a formal risk assessment and mitigation plan.

#### Work Items

- Audit the Temporal Go binary for FIPS compliance; set `GODEBUG=fips140=on` in the Temporal service unit within the snap; rebuild and bundle a FIPS-validated binary in the MAAS snap.
- Audit the Temporal Python SDK for bundled non-FIPS native crypto; open an upstream issue if a violation is found; document findings internally.  
- Engage Curtin and pylxd upstream owners; document confirmed-compliant, needs-mitigation, or risk-accepted status with a formal risk assessment.

## Functional Requirements

This section catalogs the technical requirements that implement the user stories above. Each requirement has a sequential number referenced from Work Items and Testing.

Requirements are classified as **Unconditional** (applied to all MAAS deployments) or **FIPS-conditional** (activated only when `/proc/sys/crypto/fips_enabled == 1`).

### **Detection**

#### 1\. FIPS mode detection utility (FIPS-conditional)

Implement a FIPS mode detection utility in `maascommon` that reads `/proc/sys/crypto/fips_enabled`. A missing file is treated as non-FIPS (normal on standard hosts). An OSError (file present but unreadable) is an unexpected condition logged at WARNING level. The result is cached in a module-level singleton for the process lifetime.

#### 2\. Go FIPS detection module (FIPS-conditional)

Implement a Go FIPS detection module (`fips.IsEnabled()`) in maas-agent that reads the same proc file and emits a structured startup log entry.

### **Cryptographic Hardening**

#### 3\. SSH algorithm allow-lists (FIPS-conditional)

Enforce FIPS-approved SSH algorithm allow-lists for all paramiko clients in power drivers (hmc, mscm, wedge): 

* ciphers `aes128-ctr`, `aes192-ctr`, `aes256-ctr`, `aes128-gcm@openssh.com`, `aes256-gcm@openssh.com`;   
* key exchange `ecdh-sha2-nistp256`, `ecdh-sha2-nistp384`, `diffie-hellman-group14-sha256`;   
* MACs `hmac-sha2-256`, `hmac-sha2-512`;   
* key types `ecdsa-sha2-nistp256`, `rsa-sha2-256`, `rsa-sha2-512`.   
* Replace `AutoAddPolicy` with `RejectPolicy`.

#### 4\. OMAPI HMAC-SHA256 (Unconditional)

Replace HMAC-MD5 with HMAC-SHA256 in OMAPI authentication (dhcpd templates and `authenticator.go`).

#### 5\. rndc HMAC-SHA256 (Unconditional)

Add `-a hmac-sha256` to the `rndc-confgen` invocation in `generate_rndc()`.

#### 6\. Certificate and key generation constraints (FIPS-conditional)

Enforce RSA ≥ 2,048-bit and ECDSA P-256+ in certificate and key generation; reject DSA.

#### 7\. Fernet to AES-256-GCM migration (Unconditional)

Replace Fernet with AES-256-GCM in `provisioningserver/security.py` for region↔rack RPC encryption using `cryptography.hazmat.primitives.ciphers.aead.AESGCM` with a 256-bit key (`os.urandom(32)`) and a 96-bit nonce (`os.urandom(12)`) per encryption operation. Legacy Fernet tokens (detected by the base64-encoded `0x80` version byte prefix) are automatically decrypted via a backward-compatibility path (`_is_fernet_token` + `_fernet_decrypt`); no DB migration is needed because tokens are ephemeral RPC payloads, not stored at rest.

#### 8\. TLS 1.2 minimum version (Unconditional)

Enforce TLS 1.2 as the minimum protocol version in code at every `ssl.SSLContext` (Python: `ctx.minimum_version = ssl.TLSVersion.TLSv1_2`) and `tls.Config` (Go: `MinVersion: tls.VersionTLS12`) construction site.

#### 9\. SHA-1 display uses with `usedforsecurity=False` (Unconditional)

Flag all SHA-1 invocations used for display or non-security purposes with `hashlib.sha1(..., usedforsecurity=False)` in `maasserver/models/node.py` (certificate fingerprint display) and `maasserver/api/doc.py` (API documentation ETag). This satisfies FIPS mode, which permits SHA-1 only when explicitly marked as non-security use.

#### 10\. X.509 serial number CSPRNG (Unconditional)

Replace `random.randint` with `secrets.randbits(64)` for X.509 certificate serial number generation in `provisioningserver/certificates.py`.

#### 11\. PostgreSQL BMC index MD5 replacement (Unconditional)

Replace `md5(power_parameters::text)` with `sha256(power_parameters::text::bytea)` in the `maasserver_bmc_power_type_parameters_idx` unique index. Uses PostgreSQL built-in `sha256(bytea)` function — no `pgcrypto` extension required. Applied unconditionally on all hosts.

### **Power Drivers**

#### 12\. Power driver FIPS enforcement (FIPS-conditional)

Enforce IPMI cipher suite 17 in FIPS mode; reject suites 3, 8, and 12\. Remediate the VMware driver's legacy SSL context (`ssl.PROTOCOL_SSLv23` / `ssl.CERT_NONE`) to use a modern TLS context. Enforce HTTPS and TLS certificate verification for the AMT driver; reject plain HTTP on port 16992\. Enforce `verify_ssl=True` for hmcz, proxmox, and webhook drivers.

#### 13\. Unsupported power driver rejection (FIPS-conditional)

Classify and reject the nine UNSUPPORTED-IN-FIPS drivers (apc, eaton, raritan, dli, msftocs, recs, seamicro, ucsm, moonshot) at call time when FIPS is active, returning a 422 response with `fips_supported_alternatives`.

### **Startup Gates**

#### 14\. Go services FIPS activation (FIPS-conditional)

Set `GODEBUG=fips140=on` before any cryptographic operations in Go services when FIPS mode is detected, using a wrapper script within the snap that reads `/proc/sys/crypto/fips_enabled` at runtime and exports the variable before exec-ing the Go binary. This applies to both third-party binaries (Temporal server) and MAAS-owned Go binaries (maas-agent).

## Data Model

No database schema changes are required. FIPS state is ephemeral — read from `/proc/sys/crypto/fips_enabled` at process startup and held in a module-level singleton for the lifetime of the process. No Alembic migration is needed.

The following Pydantic models are introduced as runtime state holders and API response fragments. They are not database-backed.

| Model: FIPSStatus |  |  |
| :---- | :---- | :---- |
| **Field** | **Description** | **Type** |
| fips\_enabled | True if FIPS mode is active on the host | bool |
| detection\_source | Always `/proc/sys/crypto/fips_enabled` | str |
| detection\_error | Error message if detection failed; None on success | str | None |

`fips_enabled` defaults to `False` when `detection_error` is set. The value is immutable after process startup.

| Model: FIPSSSHConfig (frozen dataclass) |  |  |
| :---- | :---- | :---- |
| **Field** | **Description** | **Type** |
| ciphers | FIPS-approved SSH ciphers for paramiko clients | tuple\[str, ...\] |
| kex | FIPS-approved key exchange algorithms | tuple\[str, ...\] |
| macs | FIPS-approved MAC algorithms | tuple\[str, ...\] |
| key\_types | FIPS-approved SSH host key types | tuple\[str, ...\] |

| Enum: DriverFIPSStatus |  |
| :---- | :---- |
| **Value** | **Meaning** |
| COMPLIANT | Driver uses only FIPS-approved cryptographic operations |
| NON\_COMPLIANT\_REMEDIABLE | FIPS violations can be remediated in software |
| UNSUPPORTED\_IN\_FIPS | Protocol-level incompatibility; cannot be fixed without hardware or firmware changes |

The `DriverFIPSStatus` registry maps all 21 power drivers to their classification. See the Power Driver Classification table in the API Changes section for the full mapping.

## API Changes

### **v3 API**

**`GET /MAAS/a/v3/`** — System status

A new field is added to the existing response body. No breaking change.

```
GET /MAAS/a/v3/
summary: System status
responses:
  200:
    description: OK
    content:
      application/json:
        schema:
          properties:
            fips_active:
              type: boolean
              description: >
                True if MAAS detected FIPS mode active on this host
                (from /proc/sys/crypto/fips_enabled). Reflects host OS
                state; cannot be changed via API.
```

**`GET /MAAS/a/v3/power-types`** — Power type list

Each entry in the response gains two new fields.

```
GET /MAAS/a/v3/power-types
summary: List available power types
responses:
  200:
    description: OK
    content:
      application/json:
        schema:
          properties:
            power_types:
              type: array
              items:
                properties:
                  fips_supported:
                    type: boolean
                  fips_unsupported_reason:
                    type: string
                    nullable: true
```

**`PUT /MAAS/a/v3/machines/{system_id}/power_parameters`** — Power parameters

Additional validation applies when `fips_active` is true.

```
PUT /MAAS/a/v3/machines/{system_id}/power_parameters
summary: Set machine power parameters
responses:
  200:
    description: Parameters accepted
  422:
    description: FIPS validation failure
    content:
      application/json:
        schema:
          properties:
            error:
              type: string
            fips_violation:
              type: boolean
              enum: [true]
            allowed_values:
              type: array
              items:
                type: string
            fips_supported_alternatives:
              type: array
              items:
                type: string
```

FIPS validation rules for this endpoint:

| Driver / field | Non-FIPS | FIPS mode |
| :---- | :---- | :---- |
| IPMI `cipher_suite_id` 17 | Accepted | Accepted (required) |
| IPMI `cipher_suite_id` 3, 8, or 12 | Accepted | Rejected — 422 |
| apc, eaton, raritan, dli, msftocs, recs, seamicro, ucsm, moonshot | Accepted | Rejected — 422 |
| webhook / proxmox / hmcz `power_verify_ssl: false` | Accepted | Rejected — 422 |

**`POST /MAAS/a/v3/users/{username}/sshkeys`** — SSH key import

```
POST /MAAS/a/v3/users/{username}/sshkeys
summary: Import SSH public key
responses:
  201:
    description: Key imported
  422:
    description: FIPS key algorithm validation failure
```

Rejected key types under FIPS: `ssh-dss`, `ssh-ed25519`, RSA \< 2,048-bit. Accepted: `ecdsa-sha2-nistp256`, `ecdsa-sha2-nistp384`, `ecdsa-sha2-nistp521`, RSA ≥ 2,048-bit.

**`POST /MAAS/a/v3/sslkeys`** — TLS certificate import

```
POST /MAAS/a/v3/sslkeys
summary: Import TLS certificate
responses:
  201:
    description: Certificate imported
  422:
    description: FIPS certificate validation failure
```

Rejected certificate properties under FIPS: SHA-1 or MD5 signatures, RSA \< 2,048-bit, DSA keys.

All 422 FIPS error responses share the schema defined in the power parameters endpoint above.

**Power Driver FIPS Classification**

| Driver | Target classification | Required change |
| :---- | :---- | :---- |
| redfish | COMPLIANT | — |
| openbmc | COMPLIANT | — |
| manual | COMPLIANT | — |
| ipmi | COMPLIANT | Enforce cipher suite 17 only in FIPS mode |
| vmware | COMPLIANT | Replace `ssl.PROTOCOL_SSLv23` / `ssl.CERT_NONE` |
| amt | COMPLIANT | Enforce HTTPS; reject plain HTTP in FIPS mode |
| hmc | COMPLIANT | Apply FIPS SSH cipher list; replace `AutoAddPolicy` |
| mscm | COMPLIANT | Apply FIPS SSH cipher list; replace `AutoAddPolicy` |
| wedge | COMPLIANT | Apply FIPS SSH cipher list; replace `AutoAddPolicy` |
| hmcz | COMPLIANT | Reject `verify_ssl=False` in FIPS mode |
| proxmox | COMPLIANT | Reject `verify_ssl=False` in FIPS mode |
| webhook | COMPLIANT | Reject `power_verify_ssl=false` in FIPS mode |
| apc | UNSUPPORTED\_IN\_FIPS | SNMPv1 — no FIPS-approved authentication |
| eaton | UNSUPPORTED\_IN\_FIPS | SNMPv1 — no FIPS-approved authentication |
| raritan | UNSUPPORTED\_IN\_FIPS | SNMPv2c — community string authentication only |
| dli | UNSUPPORTED\_IN\_FIPS | Plain HTTP basic auth |
| msftocs | UNSUPPORTED\_IN\_FIPS | Plain HTTP basic auth |
| recs | UNSUPPORTED\_IN\_FIPS | Plain HTTP — no TLS |
| seamicro | UNSUPPORTED\_IN\_FIPS | Plain HTTP — no TLS |
| ucsm | UNSUPPORTED\_IN\_FIPS | HTTP XML API — no TLS |
| moonshot | UNSUPPORTED\_IN\_FIPS | IPMI without Cipher Suite 17 support |

## UI/UX Changes

All UI adaptations are conditional on `fips_active: true` returned by `GET /MAAS/a/v3/`. The UI team must query this endpoint once at session start and propagate the flag to all affected views.

**Open issue:** No Figma designs exist yet for the FIPS badge or the power driver disabled states. The UI team should produce designs before implementation begins.

### **Global — FIPS status indicator**

When `fips_active: true`, display a persistent FIPS badge in the system status section with the text "MAAS is operating in FIPS 140-2/140-3 compliant mode." This indicator is read-only and cannot be toggled from the UI.

### **Power driver selector**

| Context | Behaviour when `fips_active: true` |
| :---- | :---- |
| Power type dropdown | Grey out (disable) all nine UNSUPPORTED-IN-FIPS drivers. Do not hide them — users must see which drivers are unavailable and why. |
| Disabled driver tooltip | "Not supported in FIPS mode. \[driver-specific reason from `fips_unsupported_reason`\]" |
| IPMI cipher suite dropdown | Show Suite 17 only; remove Suites 3, 8, and 12\. Tooltip: "Only IPMI Cipher Suite 17 is FIPS-compliant." |
| Webhook / proxmox / hmcz — Skip SSL verification checkbox | Disabled. Tooltip: "SSL verification cannot be disabled in FIPS mode." |

### **SSH key import**

Display an info banner above the import field: "FIPS mode is active. Accepted key types: ECDSA (P-256/384/521), RSA ≥ 2,048-bit. DSA and Ed25519 keys are not FIPS-compliant." Provide inline validation when a rejected key type is pasted, before the form is submitted.

### **TLS certificate import**

Display an info banner above the import field: "FIPS mode requires certificates signed with SHA-256 or stronger. SHA-1 and MD5 certificates will be rejected."

### **Boot source configuration**

No UI changes required.

## Security

**Authentication and authorization**: No new authentication mechanisms are introduced. The `fips_active` field on `GET /MAAS/a/v3/` is a read-only public field on the existing unauthenticated status endpoint. All other FIPS-gated endpoints (power parameters, SSH key import, SSL key import) use existing MAAS authentication and authorization; no new roles or permissions are added.

**Data sensitivity**: No new sensitive data is stored. The FIPS runtime state (`fips_enabled`) is derived from `/proc/sys/crypto/fips_enabled` and held in memory; it is not written to the database. The `omapi-key` secret bytes are preserved on upgrade — only the algorithm string changes. No secrets are logged.

**Attack surface**: The feature reduces attack surface by replacing weak algorithms (HMAC-MD5, HMAC-SHA1, RC4) with FIPS-approved alternatives, enforcing TLS certificate verification where it was previously optional, and rejecting UNSUPPORTED-IN-FIPS drivers at the API boundary before they can attempt a connection.

**Unconditional hardening**: Requirements 4, 5, 7, 8, 9, and 10 apply security improvements to all MAAS deployments regardless of FIPS mode.

**Cryptographic choices**:

- OMAPI and rndc: HMAC-SHA256 (FIPS 140-2 approved)  
- SSH: AES-CTR/GCM ciphers, ECDH/DH-group14-SHA256 key exchange, HMAC-SHA2-256/512 MACs  
- TLS: minimum 1.2, ECDHE suites with AES-GCM and SHA-384  
- Password hashing: PBKDF2-HMAC-SHA256 (NIST SP 800-132 approved); bcrypt excluded (Blowfish not FIPS-approved)  
- Key generation: RSA ≥ 2,048-bit, ECDSA P-256/P-384/P-521, SHA-256/384/512

**Failure mode safety**: An absent `/proc/sys/crypto/fips_enabled` file is treated as non-FIPS (normal state). Only an OSError (file present but unreadable) triggers a WARNING. MAAS never assumes FIPS is active when the state is ambiguous, preventing operational failures on standard hosts.

## Events and logs

All FIPS-relevant events are emitted via structlog as structured JSON, compatible with `journalctl -o json` and compliance log collection tools.

| Event | Level | Trigger | Required fields |
| :---- | :---- | :---- | :---- |
| `fips_mode_detected` | INFO | Process startup — FIPS active or inactive | `fips_mode` (bool), `source` (str) |
| `fips_mode_unreadable` | WARNING | OSError reading proc file (file present but unreadable) | `fips_mode: false`, `detection_error` (str) |
| `fips_tls_handshake` | INFO | Outbound TLS connection established | `cipher_suite`, `protocol_version`, `peer`, `cert_issuer`, `cert_valid` |
| `fips_ssh_authentication` | INFO | Paramiko SSH session negotiated | `key_type`, `kex`, `cipher`, `mac`, `peer`, `result` |
| `fips_crypto_error` | ERROR | FIPS violation detected | `operation`, `error`, `algorithm`, `peer` |
| `fips_driver_rejected` | ERROR | UNSUPPORTED-IN-FIPS driver called | `driver`, `reason` |

Event name constants are defined in `src/maascommon/logging/security.py`. Event names use snake\_case to match the existing MAAS security log convention.

## Testing

Testing will occur at three levels:

**Unit tests** will verify FIPS detection logic, algorithm enforcement, and cryptographic operations across all affected components (power drivers, SSH clients, TLS contexts, API handlers). These tests will mock FIPS mode detection and run on standard developer machines without requiring a FIPS-enabled kernel.

**Integration tests** will exercise the boundaries between components, particularly the API handler, FIPS service, and detection utility, to ensure end-to-end correctness without mocking.

**End-to-end tests** will run on a FIPS-enabled Ubuntu 24.04 LTS VM and verify:

- FIPS mode detection at startup  
- API exposure of FIPS status  
- SSH and TLS algorithm negotiation  
- Power driver enforcement and rejection  
- Absence of cryptographic errors during normal operation

This test suite requires a dedicated FIPS CI/CD runner and cannot be substituted by mocking.

**Existing tests** that exercise DHCP OMAPI authentication, rndc key generation, RPC encryption, or TLS context construction will be updated to reflect the new algorithms and minimum protocol versions.

**Manual verification** will be required for Temporal server and Python SDK FIPS compliance, and for Curtin and pylxd dependency status.

# Further Information

**Related documents**

- [MAAS project on GitHub](https://github.com/canonical/maas)  
- [Ubuntu Pro FIPS documentation](https://ubuntu.com/security/certifications/docs/fips)  
- [NIST SP 800-132 — Password-Based Key Derivation](https://csrc.nist.gov/publications/detail/sp/800-132/final)  
- [FIPS 140-2 Approved Security Functions](https://csrc.nist.gov/publications/detail/fips/140/2/final)

# Spec History and Changelog

Please be thorough when recording changes and progress with the spec itself and the work resulting from it. Record every meeting, attendees and conclusions from the meeting.

| Author(s) | Status | Date | Comment |
| :---- | :---- | :---- | :---- |
| [Alexsander Silva de Souza](mailto:alexsander.souza@canonical.com) | Drafting | May 26, 2026 | Initial draft |
| [Alexsander Silva de Souza](mailto:alexsander.souza@canonical.com) | Drafting | May 29, 2026 | Transitioned from `.deb` to snap as primary MVP delivery mechanism; `.deb` packaging deferred |
| Person | Drafting | Date | Initial review, comments |
| Person | Approved | Date |  |
|  |  |  |  |
