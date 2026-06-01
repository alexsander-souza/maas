# Feature Specification: FIPS-Compliant MAAS

**Feature Branch**: `002-fips-ubuntu-support`

**Created**: 2026-04-23

**Updated**: 2026-05-28

**Status**: Draft

---

## Clarifications

### Session 2026-05-28

- Q1 - Snap confinement mode: Strict confinement (existing mode). -> A: Strict confinement, keeping current snap mode.
- Q2 - FIPS detection under strict confinement: How to read fips_enabled? -> A: Reading fips_enabled is allowed by default under strict confinement.
- Q3 - Snap base image FIPS support: Where does FIPS OpenSSL come from? -> A: Base image provides FIPS-capable OpenSSL; activated at runtime only.
- Q4 - MVP distribution scope: Snap vs DEB priority? -> A: Snap-only for MVP; DEB deferred entirely to post-MVP.
- Q5 - Go FIPS activation in strict confinement: How to inject env vars? -> A: Wrapper script reads fips_enabled, exports vars, then execs binary.
- Q6 - Temporal server packaging: How to package Temporal in the snap? -> A: Bundled inside MAAS snap, same wrapper script handles FIPS activation (current approach).

## Overview

Organizations operating under compliance requirements (Federal Information Processing Standards — FIPS 140-2/140-3) need MAAS to operate correctly when installed on Ubuntu hosts with FIPS mode enabled. FIPS mode enforces restrictions on cryptographic algorithms and operations, disabling weak ciphers and non-approved algorithms. MAAS must work seamlessly in this restricted cryptographic environment without errors, degraded functionality, or silent fallback to non-compliant operations.

**Scope clarification**: This feature is about running MAAS infrastructure components (region controller, rack controller, agent) on Ubuntu hosts that have FIPS mode enabled. It is **not** about MAAS deploying or provisioning FIPS-enabled Ubuntu nodes to managed machines. Managed machines provisioned by MAAS are out of scope for FIPS configuration.

### User Need

- Enterprise and government organizations require FIPS compliance for their MAAS infrastructure hosts.
- Only Ubuntu LTS releases support FIPS mode via Canonical's FIPS-compliant modules (Ubuntu 24.04 LTS and newer).
- MAAS is a critical component in these environments but is not currently tested or guaranteed to work when installed on a FIPS-enabled host.
- Compliance audits require that all infrastructure management components — including MAAS — run in a FIPS-compliant manner on their hosts.

### Key Architecture Decisions

The following decisions are final and reflected throughout this document. They supersede any earlier drafts or discussion notes.

- **Single standard snap**: There is no separate FIPS build artifact or FIPS-specific package. The standard MAAS snap is the only package for the MVP release. When installed on a FIPS-enabled Ubuntu host, MAAS automatically detects and adapts to FIPS mode at runtime. DEB packaging is deferred to post-MVP.
- **Runtime detection via `/proc/sys/crypto/fips_enabled`**: This is the sole mechanism MAAS uses to determine FIPS state. No build-marker environment variable (e.g., `MAAS_FIPS_BUILD=1`) is used or required. No dual-check or mismatch-warning logic exists.
- **No baked-in FIPS environment variables at build time**: `GODEBUG=fips140=on` is set at runtime when `/proc/sys/crypto/fips_enabled == 1` — not packaged as build-time activators. It may be set in Go service startup code or in startup scripts (e.g., wrapper scripts); the latter is the preferred approach for third-party binaries such as the Temporal server where source changes are not possible (see FR-033).
- **No separate FIPS distribution channel**: MAAS is distributed as a single standard snap for both FIPS and non-FIPS hosts. No FIPS-only channel is produced. DEB packaging is deferred to post-MVP.
- **Snap is the MVP distribution channel**: MAAS is packaged as a strict-confinement snap (`confinement: strict`, `base: core26`) for the MVP release. Reading `/proc/sys/crypto/fips_enabled` is allowed by default under strict confinement, so the FIPS detection mechanism introduced by this feature works without modification. The base image provides FIPS-capable OpenSSL, activated at runtime only. DEB packaging is deferred to post-MVP.
- **FIPS mode is host-OS-controlled**: An operator who wants to enable or disable FIPS does so at the Ubuntu host OS level. MAAS respects whatever `/proc/sys/crypto/fips_enabled` reports. No MAAS reinstallation is required when toggling FIPS at the OS level.
- **UI adaptation is out of scope**: The MAAS UI team independently implements FIPS-aware UI changes, guided by the "API FIPS Impact Reference" document (FR-027) produced by this feature.
- **All power drivers must be audited**: Every driver in `src/provisioningserver/drivers/power/` must be verified for FIPS compliance. Drivers that are fundamentally incompatible at the protocol level are documented as unsupported in FIPS mode and are not removed from the codebase.

---

## Implementation Notes

This section records precise, component-level decisions that are too narrow for the architecture overview but must be documented to guide implementation correctly.

### BIND9 / rndc Key

- Add `-a hmac-sha256` to the `rndc-confgen` call in `generate_rndc()`; retain the existing `-b 256` key-size flag unchanged.
- Leave the nsupdate TSIG key untouched — it already uses HMAC-SHA512.
- Apply unconditionally: this change is not gated on FIPS mode.

### OMAPI Key (ISC DHCP)

- Change the algorithm identifier from `hmac-md5` to `hmac-sha256` in `dhcpd.conf.template`, `dhcpd6.conf.template`, and `authenticator.go`. Key size stays at 512 bits.
- The correct wire-format name for ISC DHCP is `"hmac-sha256"` (the DST internal form). The `.SIG-ALG.REG.INT.` suffix is HMAC-MD5-specific (RFC 2845) and does not apply to SHA-256.
- On upgrade, if an omapi-key secret already exists in `dhcpd.conf`, reuse the existing key bytes and update only the algorithm string. Do not force secret regeneration.
- Apply unconditionally: this change is not gated on FIPS mode.

### PostgreSQL Authentication

On FIPS-enabled hosts, PostgreSQL client authentication MUST use `scram-sha-256`. The FIPS kernel module blocks MD5 at the OS level, preventing database connectivity if `pg_hba.conf` still uses `md5`. At startup, MAAS MUST query the active PostgreSQL authentication method for its database and refuse to start if MD5 is configured, emitting: `"PostgreSQL is configured to use MD5 authentication, which is prohibited under FIPS mode. Update pg_hba.conf to use scram-sha-256 for the MAAS database entry and restart MAAS."` MAAS does not modify `pg_hba.conf` automatically. The MAAS installation guide must document this as a prerequisite for FIPS deployments.

### PostgreSQL MD5 Index Functions

The `maasserver_bmc_power_type_parameters_idx` unique index uses `md5(power_parameters::text)` to hash JSONB content for uniqueness enforcement. The `md5()` PostgreSQL function is blocked under FIPS mode. The index MUST be replaced to use `sha256(power_parameters::text::bytea)`, which produces a SHA-256 hash as a hex string using PostgreSQL's built-in `sha256(bytea)` function (no extension required). This change applies unconditionally on all hosts.

### Region↔Rack RPC Encryption

The Fernet symmetric encryption used in `src/provisioningserver/rpc/utils.py` for RPC shared secrets MUST be replaced with AES-256-GCM (`cryptography.hazmat.primitives.ciphers.aead.AESGCM` with a 256-bit key). This replacement applies unconditionally on all hosts — FIPS and non-FIPS — to eliminate FIPS uncertainty around AES-128-CBC and upgrade RPC secret encryption to authenticated encryption (AEAD). Key generation must use `os.urandom(32)`. Nonce generation must use `os.urandom(12)` per encryption operation. Existing Fernet-encrypted secrets stored at rest must be re-encrypted with AES-256-GCM on first startup after upgrade.

### Go Services FIPS Activation

Every Go service managed by MAAS (including maas-agent) MUST have `GODEBUG=fips140=on` set before any cryptographic operations, conditioned on `/proc/sys/crypto/fips_enabled == 1`.

The activation mechanism is a conditional wrapper script within the snap that reads `/proc/sys/crypto/fips_enabled` and exports the variables before exec-ing the Go binary. This approach applies to all Go services (both MAAS-owned and third-party, such as the Temporal server) and is the required approach under strict snap confinement.

Static, unconditional `Environment=` entries in systemd unit files are NOT acceptable — the variables must be set conditionally based on the runtime FIPS state.

### TLS Minimum Version Enforcement

MAAS MUST enforce a minimum TLS version of TLS 1.2 in code at all TLS context construction sites, unconditionally on all hosts (FIPS and non-FIPS). In Python: set `ctx.minimum_version = ssl.TLSVersion.TLSv1_2` on all `ssl.SSLContext` objects. In Go: set `MinVersion: tls.VersionTLS12` in all `tls.Config` structs. This is a defence-in-depth hardening measure independent of FIPS mode; it must not be gated on FIPS detection.

### SHA-1 Display Usage (`usedforsecurity=False`)

All SHA-1 invocations used for display or non-security purposes MUST be flagged with `hashlib.sha1(..., usedforsecurity=False)`, unconditionally: (a) Certificate fingerprint display in `src/maasserver/models/node.py` (and related model/view code). (b) The API documentation ETag in `src/maasserver/api/doc.py`. These are not security-critical uses, and FIPS mode permits SHA-1 when explicitly marked as non-security via `usedforsecurity=False`.

### X.509 Serial Number Generation

X.509 certificate serial numbers in `src/provisioningserver/certificates.py` MUST be generated using a cryptographically secure source: `secrets.randbits(64)` or `int.from_bytes(os.urandom(8), 'big')`. The current `random.randint` call is not cryptographically secure and FIPS mode may reject it. This change applies unconditionally.

---

## User Scenarios & Testing

### User Story 1 — FIPS Infrastructure Admin: Install and Operate MAAS on a FIPS Host (Priority: P1)

An infrastructure administrator at a government or regulated-enterprise organization needs to run MAAS on Ubuntu 24.04 LTS hosts that have FIPS mode enabled. They install the standard MAAS package on the FIPS-enabled host and expect MAAS services (region controller, rack controller, agent) to detect FIPS mode automatically via `/proc/sys/crypto/fips_enabled`, start successfully, remain operational, and perform all management functions without any FIPS-violation errors.

**Why this priority**: This is the core user need. If MAAS cannot run on a FIPS host without errors, the entire feature has failed.

**Independent Test**: Install the standard MAAS package on a fresh FIPS-enabled Ubuntu 24.04 LTS VM; start all MAAS services; confirm MAAS detects FIPS mode from `/proc/sys/crypto/fips_enabled`; run normal API and provisioning operations for 7 days; confirm zero "algorithm not permitted" errors in logs.

**Acceptance Scenarios**:

1. **Given** a fresh Ubuntu 24.04 LTS host with FIPS mode enabled, **When** the administrator runs `snap install maas` (standard snap with `core26`) and starts MAAS services, **Then** MAAS detects FIPS mode via `/proc/sys/crypto/fips_enabled`, logs its FIPS status at startup, and all MAAS services (regiond, rackd, maas-agent) start successfully with no FIPS-violation errors.
2. **Given** MAAS is running on a FIPS-enabled host, **When** MAAS performs any internal cryptographic operation (TLS handshake, SSH connection, key generation, password hashing), **Then** only FIPS-approved algorithms are used and no "algorithm not permitted" kernel errors occur.
3. **Given** MAAS is running on a FIPS-enabled host, **When** the administrator uses the MAAS API or UI to perform provisioning, image download, and machine management tasks, **Then** all operations complete successfully with no cryptographic failures.
4. **Given** MAAS is running on a non-FIPS host, **When** the administrator installs and operates the standard MAAS package, **Then** MAAS behaviour is unchanged from the pre-feature baseline (no regression).

---

### User Story 2 — FIPS Infrastructure Admin: Verify FIPS Mode is Active After Installation (Priority: P1)

An administrator who has installed the standard MAAS package on a FIPS-enabled Ubuntu host needs to confirm that MAAS has detected FIPS mode and is operating compliantly — without requiring access to a separate FIPS artifact, build pipeline, or special package identifier.

**Why this priority**: Without a clear runtime signal that MAAS is operating in FIPS mode, administrators and auditors cannot confirm compliance without detailed inspection of cryptographic operations.

**Independent Test**: Install the standard MAAS package on a FIPS-enabled Ubuntu 24.04 LTS host; check MAAS startup logs for a structured FIPS status entry; verify that MAAS log and API expose the active FIPS state as detected from the host OS.

**Acceptance Scenarios**:

1. **Given** MAAS is installed on a FIPS-enabled Ubuntu host, **When** MAAS services start, **Then** the startup log contains a structured entry confirming FIPS mode is active (e.g., `fips_mode: true` sourced from `/proc/sys/crypto/fips_enabled`).
2. **Given** MAAS is running on a FIPS-enabled host, **When** the administrator queries the MAAS REST API system status endpoint, **Then** the response includes `fips_active: true` reflecting the detected host OS state.
3. **Given** MAAS is installed on a non-FIPS host, **When** MAAS services start, **Then** the startup log confirms FIPS mode is inactive (`fips_mode: false`) and MAAS operates in standard mode with no behavioural difference from the pre-feature baseline.
4. **Given** a compliance auditor reviewing an installed MAAS instance on a FIPS host, **When** they review startup logs or query the API, **Then** they can confirm FIPS mode is active without requiring access to CI/CD pipelines, source repositories, or a separate package channel.

---

### User Story 3 — Compliance Auditor: Verify FIPS-Compliant Operation (Priority: P2)

A compliance auditor must confirm that MAAS running on a FIPS host uses only FIPS-approved cryptographic algorithms across all connection types (SSH, TLS, API, inter-service), generates only FIPS-approved keys and certificates, and produces audit-ready logs of cryptographic operations.

**Why this priority**: Compliance audit passage is a success criterion. Auditors need verifiable evidence of FIPS-compliant operation, not just administrator assertions.

**Independent Test**: Use network inspection tools (e.g., sslscan, SSH verbose logging) to enumerate cipher suites on all MAAS connection types; verify 100% FIPS-approved algorithms; review structured audit logs for cryptographic event records.

**Acceptance Scenarios**:

1. **Given** MAAS is running on a FIPS-enabled host, **When** a compliance auditor inspects all inbound and outbound network connections (MAAS API, region↔rack, MAAS↔Temporal, MAAS↔managed machines), **Then** 100% of connections use FIPS-approved cipher suites and no prohibited algorithms (MD5, RC4, DES, SSLv2/3, TLS 1.0/1.1) are negotiated.
2. **Given** MAAS generates SSH keys or TLS certificates, **When** those keys or certificates are inspected, **Then** they use RSA ≥2048-bit or ECDSA P-256/P-384/P-521 with SHA-256 or stronger signatures; no DSA keys or MD5 signatures are present.
3. **Given** MAAS is operating on a FIPS-enabled host, **When** the auditor reviews MAAS logs, **Then** the logs contain structured, machine-parsable entries for TLS handshake details, SSH authentication events, cryptographic errors (if any), and FIPS mode status.
4. **Given** an external compliance audit of a MAAS FIPS installation, **When** the auditor evaluates MAAS against FIPS requirements, **Then** the audit result is a pass with documented approved algorithms and no non-compliant operations recorded.

---

### User Story 4 — FIPS Infrastructure Admin: SSH Operations on Managed Machines (Priority: P2)

When MAAS (running on a FIPS host) initiates SSH connections to managed machines or uses SSH for inter-component communication, the SSH sessions must exclusively use FIPS-approved key exchange, encryption, and MAC algorithms — enforced by MAAS's SSH configuration, not relying on the managed machine's configuration.

**Why this priority**: SSH is MAAS's primary communication channel for machine management; non-compliant SSH would invalidate FIPS posture even if TLS connections are compliant.

**Independent Test**: Enable SSH verbose logging on MAAS services; initiate SSH connections; confirm only FIPS-approved ciphers, key exchange methods, and MACs appear in logs.

**Acceptance Scenarios**:

1. **Given** MAAS running on a FIPS-enabled host initiates an SSH connection, **When** the SSH session is negotiated, **Then** only FIPS-approved ciphers (aes128-ctr, aes192-ctr, aes256-ctr, aes128-gcm@openssh.com, aes256-gcm@openssh.com), key exchange methods (diffie-hellman-group14-sha256, ecdh-sha2-nistp256, ecdh-sha2-nistp384), and MACs (hmac-sha2-256, hmac-sha2-512) are used.
2. **Given** MAAS needs to generate SSH host keys, **When** keys are generated on a FIPS-enabled host, **Then** keys use ecdsa-sha2-nistp256 or RSA ≥2048-bit; no DSA or RSA <2048-bit keys are generated.
3. **Given** an SSH connection attempt would require a non-FIPS algorithm (e.g., the remote only supports hmac-md5), **When** MAAS attempts the connection, **Then** MAAS rejects the connection and logs a clear error ("Algorithm not permitted under FIPS mode") rather than silently falling back to a non-compliant algorithm.

---

### User Story 5 — FIPS Infrastructure Admin: CI/CD Validates FIPS Compliance Per Release (Priority: P2)

For each standard MAAS release, the existing CI/CD pipeline must include FIPS-specific integration tests that run the standard MAAS package on a FIPS-enabled Ubuntu host and confirm all FIPS compliance requirements are met. No separate FIPS build job or FIPS artifact publication is required — the standard package is validated for FIPS-host operation.

**Why this priority**: Without automated FIPS validation in CI/CD, regressions in FIPS-compliant behaviour would only be detected by operators in production.

**Independent Test**: Trigger a MAAS release cycle; confirm FIPS integration tests execute against the standard package on a FIPS-enabled Ubuntu 24.04 LTS host and pass before release publication.

**Acceptance Scenarios**:

1. **Given** a standard MAAS release is triggered, **When** the CI/CD pipeline runs, **Then** a FIPS integration test job executes the standard MAAS package on a FIPS-enabled Ubuntu 24.04 LTS host and validates FIPS-compliant operation.
2. **Given** the FIPS integration test job has completed, **When** tests pass, **Then** the standard MAAS artifact is cleared for publication; if tests fail, the release is blocked.
3. **Given** FIPS integration tests run, **When** they execute, **Then** they verify: MAAS detects `/proc/sys/crypto/fips_enabled` correctly, logs FIPS status at startup, uses only FIPS-approved algorithms for all connection types, and produces no FIPS-violation errors.
4. **Given** a published standard MAAS artifact, **When** an auditor reviews release notes or CI/CD metadata, **Then** the metadata confirms FIPS integration tests passed for this release on a FIPS-enabled Ubuntu host.

---

### User Story 6 — FIPS Infrastructure Admin: Snap-Bundled Dependency FIPS Compliance (Priority: P3)

MAAS depends on third-party and Canonical-maintained components bundled within the MAAS snap (Temporal server, Temporal Python SDK, Curtin, pylxd). On a FIPS-enabled host, all these dependencies must also operate without FIPS violations. The MAAS team must either enforce FIPS compliance for MAAS-owned components or engage upstream owners for externally-maintained components. The `.deb` PPA delivery path for these dependencies is deferred.

**Why this priority**: Snap-bundled dependencies are a significant compliance risk but are partially outside direct MAAS team control (upstream-owned components). MAAS-owned components (Temporal) are highest priority.

**Independent Test**: Run MAAS (including Temporal, Curtin, pylxd) on a FIPS-enabled Ubuntu 24.04 LTS host; run `auditd` FIPS audit event monitoring; confirm no FIPS-violation events for any snap-bundled dependency.

**Acceptance Scenarios**:

1. **Given** the Temporal server (Go binary) is running on a FIPS-enabled host, **When** it processes gRPC/TLS and internal workflow operations, **Then** no FIPS-violation errors appear in Temporal logs or system audit events.
2. **Given** the Temporal Python SDK is communicating with the Temporal server over gRPC/TLS, **When** connections are established, **Then** only FIPS-approved cipher suites are negotiated and no bundled non-FIPS crypto is used.
3. **Given** Curtin and pylxd are operating on a FIPS-enabled host, **When** they perform their normal functions, **Then** upstream owners have confirmed FIPS-compatible operation or MAAS team has documented compliance status and mitigations.
4. **Given** a FIPS-incompatible snap-bundled dependency cannot be remediated in time, **When** the MAAS team evaluates options, **Then** the compliance gap is explicitly documented with a formal risk assessment and mitigation plan.

---

### Edge Cases

- **MAAS on a FIPS-enabled host**: MAAS reads `/proc/sys/crypto/fips_enabled` at startup, logs `fips_mode: true`, and operates in FIPS-compliant mode — using only FIPS-approved algorithms for all cryptographic operations. This is the expected production path.
- **MAAS on a non-FIPS host**: MAAS reads `/proc/sys/crypto/fips_enabled` at startup, logs `fips_mode: false`, and operates in standard mode. No behavioural change from the pre-feature baseline.
- **What happens if a managed machine's SSH daemon only advertises non-FIPS algorithms?** MAAS must refuse the connection and report a FIPS-compliance error rather than downgrading.
- **What happens when a TLS certificate presented to MAAS uses a SHA-1 signature (still valid for some legacy CAs)?** MAAS must reject it as non-FIPS-compliant and log the rejection reason.
- **What happens when a snap-bundled dependency (e.g., Temporal) attempts a non-FIPS cryptographic operation?** The OS FIPS kernel module must block it; MAAS must surface the resulting error clearly rather than crashing silently.
- **What happens when password hashing is requested with a prohibited algorithm (e.g., MD5-crypt)?** The system must refuse and use a FIPS-approved alternative (bcrypt, PBKDF2-HMAC-SHA-256).
- **What happens if `/proc/sys/crypto/fips_enabled` is not readable at startup?** MAAS must log a warning that FIPS status could not be determined and default to non-FIPS behaviour; it must not crash. Administrators must be directed to verify host FIPS configuration.

---

## Requirements

### Functional Requirements

#### Core Cryptographic Compatibility

- **FR-001**: MAAS MUST NOT use cryptographic algorithms prohibited under FIPS mode. Prohibited algorithms include: DES, MD5, MD4, MD2, RC4, and export-grade encryption. Allowed algorithms include: AES (128, 192, 256), RSA, ECDSA, SHA-256, SHA-384, SHA-512, and HMAC-SHA2 variants.
- **FR-002**: All SSH connections initiated by MAAS MUST negotiate exclusively FIPS-approved algorithms: key exchange (diffie-hellman-group14-sha256, ecdh-sha2-nistp256, ecdh-sha2-nistp384), encryption (aes128-ctr, aes192-ctr, aes256-ctr, aes128-gcm@openssh.com, aes256-gcm@openssh.com), and MAC (hmac-sha2-256, hmac-sha2-512 — no hmac-md5 variants).
- **FR-003**: All TLS/HTTPS connections MUST use FIPS-compliant cipher suites with a minimum protocol version of TLS 1.2. Approved cipher suites include ECDHE-ECDSA-AES256-GCM-SHA384, ECDHE-RSA-AES256-GCM-SHA384, and ECDHE-RSA-AES128-GCM-SHA256. SSLv2, SSLv3, TLS 1.0, and TLS 1.1 are prohibited. MAAS MUST enforce this minimum version in code at all TLS context construction sites unconditionally — Python: `ctx.minimum_version = ssl.TLSVersion.TLSv1_2`; Go: `MinVersion: tls.VersionTLS12`. This requirement is not gated on FIPS mode; it applies on all hosts.
- **FR-004**: All cryptographic key generation by MAAS MUST use FIPS-approved algorithms and parameter sizes: RSA minimum 2048-bit (4096-bit recommended for certificates), ECDSA using NIST P-256, P-384, or P-521 curves only, and hash functions SHA-256, SHA-384, or SHA-512 (no MD5 or SHA-1).

#### SSH Configuration

- **FR-005**: MAAS MUST configure SSH clients and servers with FIPS-compliant settings. Default SSH key types used by MAAS must be ecdsa-sha2-nistp256, rsa-sha2-256, or rsa-sha2-512 (no ssh-rsa with SHA-1). SSH client configuration for outbound connections must use approved ciphers and key exchange methods.
- **FR-006**: On FIPS-enabled hosts, SSH keys generated by MAAS MUST use FIPS-approved algorithms. Any existing keys using weak algorithms (DSA, RSA <2048-bit) that would be encountered during a fresh installation must not be used; MAAS must generate replacement keys using FIPS-approved algorithms.

#### TLS/HTTPS Configuration

- **FR-007**: MAAS MUST enforce FIPS-compliant TLS across ALL connections — inbound and outbound, internal and external — with no exceptions. This includes: MAAS API endpoints (HTTPS inbound from clients), region controller ↔ rack controller communication, MAAS ↔ Temporal server, MAAS ↔ database, and MAAS ↔ managed machines (SSH, HTTP, HTTPS). No mixed-mode or partial FIPS networking is permitted.
- **FR-008**: Certificate generation and validation by MAAS MUST use FIPS-approved algorithms. Self-signed certificates must use RSA (≥2048-bit) or ECDSA (P-256 minimum). Certificate signing requests must use SHA-256 or stronger. Certificate validation must use FIPS-approved signature verification.

#### Package and Repository Access

- **FR-009**: MAAS host package management (apt) MUST function correctly under FIPS mode on the MAAS host. APT must correctly validate repository GPG signatures using FIPS-approved algorithms. HTTPS access to Ubuntu package repositories must use FIPS-compliant cipher suites. MAAS snap installation on a FIPS host must not trigger FIPS violations.
- **FR-010**: Image downloads and checksum verification performed by MAAS MUST use FIPS-approved hash algorithms (SHA-256, SHA-512). MD5 and MD4 checksums in MAAS image download or verification workflows are prohibited.

#### Password and Authentication Hashing

- **FR-011**: Password storage and authentication operations in MAAS MUST use FIPS-approved algorithms: bcrypt, scrypt, or PBKDF2 with HMAC-SHA-256/SHA-512. MD5-based crypt is prohibited. MAAS database credentials and user authentication must use FIPS-approved hash functions.

#### Logging and Compliance

- **FR-012**: MAAS MUST log cryptographic operations for compliance auditing. Log entries must include: TLS handshake details (cipher suite, protocol version, certificate verification result), SSH authentication details (key type, algorithm, result), and cryptographic errors (algorithm not permitted, FIPS mode violation). Log format must be structured and machine-parsable (JSON recommended) for compatibility with compliance tools.
- **FR-013**: MAAS configuration and documentation MUST document FIPS compliance status and restrictions. Configuration documentation must list FIPS mode status and approved algorithms. MAAS installation scripts must support FIPS mode detection and validation.

#### Error Handling and Graceful Degradation

- **FR-014**: MAAS MUST detect and clearly communicate FIPS-related failures. Error messages must distinguish FIPS-compliance errors from other failures (e.g., "Algorithm not permitted under FIPS mode" vs. "Connection refused"). Fallback behaviour must not silently disable FIPS or allow non-compliant operations. Administrators must be alerted to FIPS violations or configuration mismatches.
- **FR-015**: MAAS installations on non-FIPS hosts MUST continue to operate as before. A MAAS installation on a non-FIPS host is unaffected by this feature. Within a FIPS-enabled MAAS deployment, all connections use FIPS-approved crypto exclusively — no relaxed or mixed-mode cipher suites are permitted.
- **FR-026**: At startup, MAAS MUST read `/proc/sys/crypto/fips_enabled` as the sole FIPS detection mechanism and log a structured FIPS status entry (e.g., `fips_mode: true/false`) at INFO level, visible in the service journal. If `/proc/sys/crypto/fips_enabled` == 1, MAAS operates in FIPS-compliant mode — activating all FIPS algorithm restrictions. If `/proc/sys/crypto/fips_enabled` == 0 (or the file is absent), MAAS operates in standard mode. No secondary build-marker mechanism is consulted. If the file cannot be read at startup, MAAS MUST log a WARNING, default to standard mode, and direct the administrator to verify host FIPS configuration. MAAS must never silently assume FIPS state.

#### Compatibility and Supported Versions

- **FR-016**: MAAS MUST support FIPS mode on Ubuntu 24.04 LTS and all newer Ubuntu LTS releases. FIPS packages required: ubuntu-fips and fips-updates (Ubuntu 24.04+). Only LTS releases of Ubuntu have FIPS modules available. Testing and validation is required for each supported LTS release. The minimum kernel version supporting FIPS must be documented.
- **FR-017**: MAAS MUST be compatible with the FIPS cryptographic implementations provided by Ubuntu on FIPS-enabled hosts. The Go-based maas-agent must be validated to correctly inherit FIPS mode from the host OS automatically (this is a validation requirement, not an implementation task). FIPS inheritance behaviour (GODEBUG/FIPS mode) must be confirmed as part of agent validation. Go FIPS mode activation: when `/proc/sys/crypto/fips_enabled == 1`, MAAS MUST ensure `GODEBUG=fips140=on` is set before any crypto operations, via startup script or service startup code as appropriate (see FR-033).

#### Snap-Bundled Dependency FIPS Compliance

- **FR-018** *(MAAS-Owned — Highest Risk)*: The Temporal server (Go binary) bundled in the MAAS snap MUST execute without FIPS violations when running on a FIPS-enabled Ubuntu host. The MAAS team MUST validate that the Temporal server binary correctly inherits FIPS mode from the host OS (via the Ubuntu Pro FIPS kernel and OpenSSL FIPS provider). When `/proc/sys/crypto/fips_enabled == 1`, MAAS MUST set `GODEBUG=fips140=on` in the Temporal service unit within the snap before any cryptographic operations — the condition is evaluated at runtime. OS-level crypto (OpenSSL, kernel FIPS module) is provided by Ubuntu Pro FIPS packages installed on the host — a host prerequisite. The Temporal binary is bundled in the MAAS snap; no separate FIPS variant is produced. Risk level: HIGH.
- **FR-019** *(MAAS-Owned)*: The Temporal Python SDK bundled in the MAAS snap MUST use only FIPS-approved cryptographic operations when executing on a FIPS-enabled Ubuntu host. The MAAS team MUST validate that the Temporal Python SDK relies on the host system's FIPS-compliant OpenSSL provided by Ubuntu Pro FIPS packages — no bundled non-FIPS native crypto extensions are permitted. Risk level: MEDIUM.
- **FR-020** *(Upstream-Owned)*: The Curtin and pylxd components bundled in the MAAS snap MUST provide FIPS-compliant builds or verified FIPS-compatible operation on Ubuntu FIPS hosts. Ubuntu Pro FIPS packages installed on the host provide OS-level FIPS crypto (OpenSSL, kernel FIPS module); these upstream-owned components must not bundle their own non-FIPS crypto implementations and should rely on host-provided FIPS crypto instead. The MAAS team must engage respective upstream owners and document compliance status. If upstream cooperation is not obtained within an acceptable timeframe, the MAAS team must formally declare these as out-of-scope risks with documented mitigations. Risk level: MEDIUM (contingent on upstream cooperation).

#### FIPS Build, Packaging, and Distribution

- **FR-021**: MAAS MUST be distributed as a single standard snap — there is no separate FIPS build artifact or FIPS-specific package. When installed on a FIPS-enabled Ubuntu host (where `/proc/sys/crypto/fips_enabled` == 1), MAAS automatically detects FIPS mode at startup via `/proc/sys/crypto/fips_enabled` (FR-026) and activates FIPS-compliant behaviour. The snap uses strict confinement (`confinement: strict`, `base: core26`). Reading `/proc/sys/crypto/fips_enabled` is allowed by default under strict confinement. The base image provides FIPS-capable OpenSSL, activated at runtime only. No environment variables are packaged as build-time FIPS activators, and no MAAS-specific build marker exists. The standard MAAS snap is installable on both FIPS and non-FIPS Ubuntu hosts; behaviour adapts to the host OS state. DEB packaging is deferred to post-MVP.
- **FR-022**: MAAS MUST be distributed as a snap for the MVP release. DEB packaging via the MAAS PPA is deferred to post-MVP. No separate FIPS-only distribution channel is required. The standard MAAS installation guide must document FIPS mode operation: that MAAS installed on a FIPS-enabled Ubuntu host will automatically operate in FIPS-compliant mode.
- **FR-023**: MAAS release version numbers MUST be consistent and clearly documented. Each MAAS release that has been validated for FIPS-host operation must be noted in release documentation. No separate FIPS PPA naming convention is required.
- **FR-024**: CI/CD pipelines MUST include FIPS integration test jobs that validate the standard MAAS snap on a FIPS-enabled Ubuntu host before each release. No separate FIPS build job or FIPS artifact publication pipeline is required. FIPS integration tests must pass before the standard MAAS snap is published for any given release. DEB integration testing is deferred to post-MVP.
- **FR-025**: MAAS MUST expose its detected FIPS runtime state to administrators and auditors. At startup, MAAS logs a structured FIPS status entry (e.g., `fips_mode: true/false`) reflecting the value read from `/proc/sys/crypto/fips_enabled`. The MAAS REST API system status endpoint MUST include a `fips_active` field (boolean) reflecting the detected host OS FIPS state. This information must be available without requiring access to the build pipeline or source repository. Note: there is no `+fips` version tag since there is only one standard package — the runtime-detected `fips_active` field is the canonical indicator.

#### API FIPS Impact Reference Documentation

- **FR-027**: MAAS MUST produce and maintain an "API FIPS Impact Reference" document enumerating every API endpoint whose behaviour, available options, or accepted inputs differ when FIPS mode is active (i.e., when `/proc/sys/crypto/fips_enabled` == 1). For each affected endpoint the document must specify: (a) the endpoint path and HTTP method, (b) how behaviour changes under FIPS mode (e.g., restricted cipher options returned, inputs rejected, response values differ), and (c) which non-FIPS options are suppressed or rejected. This document serves as the authoritative contract between the MAAS API layer and the UI team (and any other API consumers), enabling the UI team to implement appropriate FIPS-aware UI adaptations independently. The document must be reviewed and approved before MVP release.

#### Power Driver FIPS Compliance

- **FR-028**: All MAAS power drivers (located in `src/provisioningserver/drivers/power/`) MUST be audited for FIPS compliance. The audit must cover each driver's cryptographic operations — including authentication mechanisms, transport encryption, and certificate handling (e.g., BMC/IPMI cipher suites, Redfish/HTTPS configuration, iDRAC/iLO TLS settings, VMware SSL context). Each driver must be verified to use only FIPS-approved algorithms when `/proc/sys/crypto/fips_enabled` is active. Known non-compliant areas already identified include: Gap 8 (IPMI Cipher Suites 8 and 12 using HMAC-MD5) and Gap 7 (Legacy SSL context in VMware driver). Non-compliant drivers must either be remediated to use FIPS-approved operations or explicitly documented as unsupported in FIPS mode with a clear user-facing notice. Drivers that are fundamentally incompatible at the protocol level (e.g., those only supporting HMAC-MD5 cipher suites such as IPMI cipher suite 3) will be documented as unsupported in FIPS mode rather than removed from the codebase.
- **FR-029**: MAAS MUST replace HMAC-MD5 with HMAC-SHA256 in DHCP/DNS subsystems **unconditionally** — this change applies on all hosts regardless of whether FIPS mode is active. Specifically: (a) **OMAPI authentication** — the algorithm identifier in `dhcpd.conf.template`, `dhcpd6.conf.template`, and `src/maasagent/internal/dhcpd/omapi/authenticator.go` MUST be changed from `hmac-md5` / `hmac-md5.SIG-ALG.REG.INT.` to `hmac-sha256` / `"hmac-sha256"` (ISC DHCP wire-format name; the `.SIG-ALG.REG.INT.` suffix is RFC 2845-specific to HMAC-MD5 and has no SHA equivalent). Key size (512 bits) MUST remain unchanged. On upgrade, MAAS MUST silently reuse existing `omapi-key` bytes — changing only the algorithm string — with no forced secret regeneration on either FIPS or non-FIPS hosts. (b) **rndc key** — `generate_rndc()` in `src/provisioningserver/dns/config.py` MUST pass `-a hmac-sha256` to `rndc-confgen` unconditionally; the existing `-b 256` key-size flag MUST NOT be altered (256 bits is the correct maximum for HMAC-SHA256). Adding `-a hmac-sha256` is the sole change to the `rndc-confgen` invocation. (c) **nsupdate TSIG key** is explicitly out of scope — it already uses HMAC-SHA512 and requires no change.

#### Cryptographic Hardening

**Unconditional** (applied to all MAAS deployments regardless of FIPS mode):

- **FR-030**: MAAS nginx configuration MUST proxy all WebSocket upgrade requests on all MAAS deployments, handling the RFC 6455 SHA-1 handshake computation at the nginx layer. No FIPS-gating of the Django WebSocket handler is required.
- **FR-032**: The Fernet encryption in `src/provisioningserver/rpc/utils.py` MUST be replaced with AES-256-GCM unconditionally on all hosts. Key: 256-bit (`os.urandom(32)`). Nonce: 96-bit per operation (`os.urandom(12)`). Existing Fernet-encrypted secrets must be re-encrypted with AES-256-GCM on first startup after upgrade.
- **FR-034**: MAAS MUST enforce TLS 1.2 as the minimum protocol version in code at all TLS context construction sites, unconditionally on all hosts. Python: `ctx.minimum_version = ssl.TLSVersion.TLSv1_2`. Go: `MinVersion: tls.VersionTLS12`.
- **FR-035**: All uses of SHA-1 in MAAS for display or caching purposes MUST be flagged with `hashlib.sha1(..., usedforsecurity=False)` unconditionally: (a) certificate fingerprint display (`src/maasserver/models/node.py`), (b) API documentation ETag (`src/maasserver/api/doc.py`).
- **FR-036**: X.509 certificate serial numbers MUST be generated using `secrets.randbits(64)` or `int.from_bytes(os.urandom(8), 'big')` in `src/provisioningserver/certificates.py`. `random.randint` MUST NOT be used for serial number generation.
- **FR-037**: The `maasserver_bmc_power_type_parameters_idx` unique index MUST use `sha256(power_parameters::text::bytea)` instead of `md5(power_parameters::text)`. This uses PostgreSQL's built-in `sha256(bytea)` function (no extension required). This change applies unconditionally on all hosts.

**FIPS-conditional** (activated only when `/proc/sys/crypto/fips_enabled == 1`):

- **FR-031**: On FIPS-enabled hosts, MAAS MUST verify at startup that PostgreSQL authentication for the MAAS database uses `scram-sha-256`. If MD5 authentication is detected, MAAS MUST refuse to start and emit a clear, actionable error message directing the operator to update `pg_hba.conf`. MAAS MUST NOT modify `pg_hba.conf` automatically. The MAAS installation guide must document `scram-sha-256` as a FIPS deployment prerequisite.
- **FR-033**: Every Go service managed by MAAS MUST have `GODEBUG=fips140=on` set when `/proc/sys/crypto/fips_enabled == 1`, before any cryptographic operations. The activation mechanism is a conditional wrapper script that reads `/proc/sys/crypto/fips_enabled` and exports the variables before exec-ing the Go binary. This applies to all Go services (MAAS-owned and third-party, such as the Temporal server) and is the required approach under strict snap confinement. Static, unconditional `Environment=` entries in systemd unit files are NOT acceptable — the condition MUST be evaluated at runtime against `/proc/sys/crypto/fips_enabled`.

---

### Key Entities

#### Configuration Entities

1. **FIPS Mode Status**
   - Active flag: Boolean (FIPS mode enabled/disabled on the host)
   - Source: Single check at MAAS startup — OS kernel state via `/proc/sys/crypto/fips_enabled`. This is the sole authoritative source; no secondary build-marker env var is consulted.

2. **Cryptographic Algorithm Registry**
   - Approved algorithms by category: key exchange, encryption, hashing, authentication
   - Configuration source: FIPS module or hardcoded FIPS specification

3. **SSH Configuration**
   - Ciphers: List of approved SSH ciphers used by MAAS
   - Key exchange methods: Approved key exchange algorithms
   - Host key types: Approved SSH key types
   - Scope: Applies to MAAS-initiated SSH connections (outbound) and MAAS SSH daemons (inbound)

4. **TLS Configuration**
   - Cipher suites: Approved TLS cipher suites for all MAAS connections
   - Minimum TLS version: TLS 1.2 or higher
   - Certificate validation: FIPS-approved signature algorithms required

#### Operational Entities

1. **SSH Session Log**
   - Timestamp, cipher suite, key exchange method, authentication method, result
   - Purpose: Audit trail for compliance

2. **TLS Session Log**
   - Timestamp, cipher suite, protocol version, certificate details, verification result
   - Purpose: Audit trail and performance monitoring

3. **Cryptographic Error Event**
   - Timestamp, operation type (SSH/TLS/key generation/hashing), error message, FIPS violation indicator
   - Purpose: Alerting, troubleshooting, and compliance evidence

4. **FIPS Runtime Status**
   - Runtime FIPS state exposed at startup and via the API (`fips_mode` log entry, `fips_active` API field)
   - Purpose: Allow administrators and auditors to confirm whether MAAS is operating in FIPS mode on the current host

#### Compliance Audit Artifacts

5. **API FIPS Impact Reference**
   - A maintained document listing every MAAS API endpoint whose behaviour, available options, or accepted inputs differ under FIPS mode
   - Consumers: UI team (for FIPS-aware UI adaptation), auditors, third-party API clients
   - Lifecycle: Produced as part of this feature; updated whenever a new endpoint is affected by FIPS; reviewed and approved before MVP release

6. **Power Drivers**
   - Scope: All drivers in `src/provisioningserver/drivers/power/` (BMC, IPMI, Redfish, iDRAC, iLO, VMware, etc.)
   - Audit requirement: Each driver's cryptographic operations (authentication, transport encryption, certificate handling) must be verified for FIPS compliance when `/proc/sys/crypto/fips_enabled` is active
   - Compliance outcomes: Classified as FIPS-compliant (after remediation if needed) or documented as unsupported in FIPS mode
   - Known gaps: Gap 7 (VMware legacy SSL context), Gap 8 (IPMI Cipher Suites 8 and 12 using HMAC-MD5)

---

## Success Criteria

### Measurable Outcomes

- **SC-001 — Zero FIPS-Related Cryptographic Errors**: MAAS services (regiond, rackd, maas-agent) run on a FIPS-enabled Ubuntu host and remain operational without encountering algorithm-not-permitted or FIPS-violation errors for at least 7 days of normal operation. *(Target: Error count = 0)*

- **SC-002 — All SSH Connections FIPS-Compliant**: 100% of SSH connections initiated by MAAS (running on a FIPS-enabled host) use FIPS-approved cipher suites and algorithms, verified via SSH debug logs or network analysis. *(Target: 100% compliance)*

- **SC-003 — All MAAS Connections FIPS-Compliant**: 100% of all network connections made by any MAAS component on a FIPS-enabled host use FIPS-approved cipher suites and algorithms — including region controller ↔ rack controller, MAAS ↔ Temporal server, MAAS ↔ database, MAAS API (HTTPS) inbound from clients, and MAAS ↔ managed machines (SSH, HTTP, HTTPS). Verified via network analysis and TLS/SSH inspection. *(Target: 100% cipher suite compliance across all connection types)*

- **SC-004 — MAAS Provisioning Workflows Succeed on FIPS Host**: MAAS provisioning workflows (image download, checksum verification, repository access, agent communication) complete without cryptographic errors in 100% of test runs when MAAS is running on a FIPS-enabled host. *(Target: 100% workflow success)*

- **SC-005 — Key Generation Uses Approved Algorithms**: All SSH keys and TLS certificates generated by MAAS use RSA (≥2048-bit), ECDSA (P-256+), and SHA-256+ signatures; no DSA keys or MD5 signatures. *(Target: 100% approved algorithm usage)*

- **SC-006 — Compliance Audit Pass**: External compliance audit confirms MAAS operates in FIPS-compliant mode on a FIPS-enabled Ubuntu host, with documented approved algorithms and no non-compliant operations recorded. *(Target: Audit status = pass)*

- **SC-007 — Performance Impact <5%**: MAAS API response times on FIPS-enabled hosts are within 5% of non-FIPS baselines (e.g., <525ms vs. <500ms for p95 API latency). *(Target: Latency delta <5%)*

- **SC-008 — FIPS Runtime State is Observable**: MAAS running on a FIPS-enabled host exposes its detected FIPS state via the MAAS API system status endpoint (`fips_active: true`) and a structured startup log entry, verifiable without access to the build pipeline or source repository. *(Target: fips_active field present and correct = true)*

- **SC-009 — FIPS CI/CD Validation Passes Per Release**: FIPS integration tests (running the standard MAAS package on a FIPS-enabled Ubuntu host) pass in the CI/CD pipeline for each standard MAAS release before publication. *(Target: FIPS integration test pass rate = 100% per release)*

- **SC-010 — API FIPS Impact Reference Document Exists and Reviewed**: The "API FIPS Impact Reference" document enumerating all MAAS API endpoints whose behaviour, available options, or accepted inputs differ when FIPS mode is active is produced, reviewed, and approved before MVP release. *(Target: Document exists, reviewed, and approved = true before MVP)*

- **SC-011 — All Power Drivers Audited for FIPS Compliance**: All power drivers in `src/provisioningserver/drivers/power/` have been audited for FIPS compliance. Drivers that are non-compliant but remediable have been fixed to use FIPS-approved algorithms. Drivers that are fundamentally incompatible at the protocol level (e.g., those only supporting HMAC-MD5) are explicitly documented as unsupported in FIPS mode with a user-facing notice. *(Target: Audit complete = 100% of drivers; zero unclassified drivers remaining)*

---

## Scope

### In Scope

- **MAAS Core Services on FIPS Hosts**: Ensure MAAS region controller, rack controller, and agent work correctly when installed on a FIPS-enabled Ubuntu 24.04 LTS (or newer LTS) host.
- **SSH Configuration**: Configure SSH clients/servers used by MAAS for FIPS compliance (ciphers, key types, algorithms).
- **TLS/HTTPS Configuration**: Enforce FIPS-compliant TLS for MAAS API endpoints and all inter-service communication.
- **Cryptographic Libraries**: Validate and configure Python cryptography libraries (paramiko, cryptography, Twisted) and Go crypto libraries for FIPS mode.
- **Key and Certificate Management**: Ensure SSH keys and TLS certificates generated by MAAS use FIPS-approved algorithms.
- **Password Hashing**: Verify user authentication and database credentials use FIPS-approved hashing (bcrypt, PBKDF2).
- **MAAS Host Package and Image Operations**: Ensure MAAS's own APT operations and image downloads on the FIPS-enabled MAAS host complete without FIPS violations.
- **Ubuntu 24.04 LTS and Newer LTS Releases**: Support on all LTS releases (24.04, 26.04, 28.04, etc.); only LTS releases have FIPS module availability.
- **Testing and Validation**: Create a test suite for FIPS compliance scenarios on MAAS hosts; includes validation that maas-agent inherits FIPS mode from the host OS.
- **Documentation**: Provide installation and configuration guidance for running MAAS on FIPS-enabled Ubuntu hosts, including confirming FIPS mode is automatically detected from the host OS.
- **PPA Dependency FIPS Compliance (MAAS-Owned)**: Validate and enforce FIPS compliance for MAAS-owned PPA packages — specifically Temporal server (Go binary) and Temporal Python SDK — including rebuilding with FIPS-approved crypto or patching as needed.
- **PPA Dependency FIPS Engagement (Upstream-Owned)**: Engage upstream project owners for Curtin and pylxd to request FIPS-compliant builds or confirmed FIPS-compatible operation; document compliance status and track resolution.
- **FIPS CI/CD Validation**: Add FIPS integration test jobs to the existing CI/CD pipeline that validate the standard MAAS package on a FIPS-enabled Ubuntu host before each release.
- **FIPS Runtime State Observability**: Expose the MAAS-detected FIPS state (`fips_active`) via the API system status endpoint and structured startup log so administrators and auditors can confirm FIPS mode without build pipeline access.
- **API FIPS Impact Reference Document**: Produce and maintain a document enumerating every MAAS API endpoint whose behaviour, available options, or accepted inputs differ when FIPS mode is active; serves as the authoritative contract between the MAAS API layer and the UI team for FIPS-aware UI adaptation.
- **Power Driver FIPS Compliance Audit**: Systematically audit all power drivers in `src/provisioningserver/drivers/power/` (BMC, IPMI, Redfish, iDRAC, iLO, VMware, etc.) for FIPS compliance; remediate non-compliant drivers or document them as unsupported in FIPS mode.

### Out of Scope

- **Deploying FIPS-Enabled Ubuntu Nodes to Managed Machines**: MAAS will not configure or enforce FIPS mode on machines it provisions. Teaching managed machines to be FIPS-compliant is explicitly out of scope.
- **FIPS Mode Enablement on the Host**: This feature assumes FIPS is already enabled externally on the Ubuntu MAAS host via official packages (ubuntu-fips). MAAS does not enable FIPS.
- **Custom Cryptographic Implementations**: MAAS uses standard libraries; custom crypto implementations are out of scope.
- **Legacy Non-FIPS Components**: Components already marked for deprecation are not retrofitted for FIPS compliance.
- **Third-Party Integrations**: External systems (e.g., monitoring, logging platforms) may have their own FIPS requirements; these are out of scope.
- **Performance Optimization**: While FIPS compliance may have performance costs, optimization beyond the <5% threshold is secondary to correctness.
- **FIPS Validation Certification**: MAAS itself will not be FIPS-validated (CMVP); instead, MAAS operations are FIPS-compliant when running on a FIPS-enabled host.
- **Migration from Non-FIPS to FIPS Deployments**: There is no supported migration path from an existing non-FIPS MAAS installation to a FIPS one. FIPS deployments are always green-field.
- **Automatic Upgrade Between FIPS and Non-FIPS Configurations**: Since there is only one MAAS package, switching between FIPS and non-FIPS modes is controlled at the host OS level (enabling/disabling Ubuntu FIPS). No MAAS reinstallation is required when toggling FIPS at the OS level.
- **Separate FIPS Package or FIPS-Specific CI/CD Pipeline**: A dedicated FIPS-specific MAAS package, FIPS PPA, or separate FIPS-specific CI/CD pipeline is explicitly out of scope. The standard MAAS snap is the only package for MVP; FIPS-compliant behaviour is achieved at runtime by detecting the host OS state via `/proc/sys/crypto/fips_enabled`.
- **Snap Packaging (MVP — Primary Distribution)**: MAAS snap artifacts for FIPS-enabled hosts are the primary distribution channel for the MVP release. The snap uses strict confinement (`confinement: strict`, `base: core26`). Reading `/proc/sys/crypto/fips_enabled` is allowed by default under strict confinement. The base image provides FIPS-capable OpenSSL, activated at runtime only. DEB packaging is deferred to post-MVP.
- **FIPS Snap Distribution (MVP — Primary Channel)**: MAAS is distributed as a snap for the MVP release. DEB packaging via the MAAS PPA is deferred to post-MVP. No separate FIPS snap channel or track is needed.
- **UI/UX FIPS Adaptation**: Implementing MAAS UI changes that reflect FIPS mode and restrict UI controls that would trigger non-FIPS-compliant operations is out of scope for this spec. The UI team owns UI-level FIPS adaptation; they will consume the "API FIPS Impact Reference" document (FR-027) produced by this feature to implement appropriate UI changes independently.
- **DEB Packaging (Deferred to Post-MVP)**: MAAS DEB packaging for FIPS-enabled hosts is not in scope for the MVP release. DEB distribution via the MAAS PPA is deferred to post-MVP.

---

## Assumptions

1. **FIPS is Externally Enabled on the MAAS Host**: MAAS assumes FIPS is already enabled on the Ubuntu host running MAAS via official packages (ubuntu-fips); MAAS does not enable FIPS. MAAS does not configure or deploy FIPS on managed machines.

2. **Standard Cryptographic Libraries**: MAAS uses standard Python/Go libraries (cryptography, paramiko, Twisted, Go crypto); no custom crypto implementations exist that would require special handling.

3. **Green-Field Installations Preferred for Initial Validation**: Initial FIPS validation focuses on green-field installations on an already-FIPS-enabled Ubuntu 24.04+ LTS host. Existing MAAS deployments may be revalidated after host OS FIPS reconfiguration, but no legacy key migration tooling or compatibility shims are required.

4. **Performance Trade-off Acceptable**: FIPS mode may impose minor performance overhead (typically <5%); this is acceptable for compliance.

5. **FIPS-Enabled OpenSSL Available on Host**: A FIPS-enabled OpenSSL (1.1.1+ or 3.x) is available and configured on the FIPS Ubuntu host via the ubuntu-fips package stack.

6. **No Custom Protocol Extensions**: MAAS does not implement proprietary cryptographic protocols; all communication uses standard SSH/TLS.

7. **Audit Logging Infrastructure Exists**: The organization has infrastructure to collect and analyze MAAS logs for compliance audits.

8. **Database FIPS Connection Support**: MAAS and managed systems use PostgreSQL; FIPS-compliant TLS connections to PostgreSQL are supported and required on FIPS-enabled hosts.

9. **Curtin and pylxd FIPS Compliance is Contingent on Upstream Cooperation**: FIPS-compliant operation of Curtin and pylxd — bundled in the MAAS snap — depends on upstream project owners providing FIPS-compatible builds or confirmed FIPS-compatible behaviour. The MAAS team will engage these upstreams but cannot guarantee delivery timelines. If upstream cooperation is not obtained, the MAAS team must assess risk and either patch the snap-bundled components directly or treat these dependencies as outstanding compliance gaps with documented mitigations.

10. **Temporal Upstream Will Not Self-Prioritize FIPS**: The Temporal project (server and Python SDK) is unlikely to independently prioritize FIPS compliance for Ubuntu. The MAAS team assumes full ownership of validating and enforcing FIPS compliance for Temporal components bundled in the MAAS snap, including validating that the Temporal server binary correctly inherits FIPS mode from the host OS (via `GODEBUG=fips140=on`) and that the Temporal Python SDK relies on host-provided FIPS OpenSSL without bundling non-FIPS crypto.

11. **FIPS Mode is Controlled at the Host OS Level**: Switching MAAS between FIPS and non-FIPS operation is done by enabling or disabling FIPS at the Ubuntu host OS level. Since there is only one MAAS package, no reinstallation is required to change FIPS mode — only a host OS reconfiguration (and service restart) is needed.

12. **DEB Packaging is Deferred to Post-MVP**: MAAS DEB packaging for FIPS-enabled hosts is not in scope for the MVP release. The snap is the primary and only distribution channel for MVP. DEB distribution via the MAAS PPA is deferred to post-MVP.

13. **Snap Base Image Provides FIPS Crypto**: The snap base image (`core26`) provides FIPS-capable OpenSSL, activated at runtime only. No FIPS-specific build-time toolchain modifications are required for the MAAS CI/CD pipeline. The MAAS team is responsible for validating that MAAS snap-specific dependencies (Temporal server, Temporal Python SDK) correctly inherit FIPS mode from the host OS without bundling non-FIPS crypto. Reading `/proc/sys/crypto/fips_enabled` is allowed by default under strict snap confinement.

14. **UI Team Consumes API FIPS Impact Reference**: The MAAS UI team will independently implement UI-level FIPS adaptations (e.g., hiding or disabling UI controls that would trigger non-FIPS-compliant operations) based on the "API FIPS Impact Reference" document produced by this feature (FR-027). UI adaptation work is tracked and owned by the UI team; it is not part of this spec.

15. **Some Power Drivers May Be Fundamentally Incompatible with FIPS**: Certain power drivers may use protocols that are intrinsically non-FIPS-compliant at the hardware or protocol level (e.g., IPMI cipher suite 3, which only supports HMAC-MD5 for authentication). Such drivers cannot be remediated through software changes alone. These drivers will be explicitly documented as unsupported in FIPS mode and surfaced to administrators as a known limitation; they will not be removed from the codebase.

---

## Dependencies and Related Features

- **Ubuntu FIPS Packages**: Assumes ubuntu-fips and fips-updates packages are installed and enabled on target hosts.
- **Python 3.11+**: Required for FIPS-compliant cryptography library support.
- **OpenSSL 3.x**: FIPS module availability and configuration on the host.
- **PostgreSQL 13+**: FIPS-compatible TLS connection support.
- **Temporal Server** *(MAAS snap — MAAS-owned, HIGH risk)*: Go-based workflow server; MAAS team MUST validate FIPS-compliant operation on FIPS-enabled Ubuntu hosts; when `/proc/sys/crypto/fips_enabled == 1`, MAAS MUST set `GODEBUG=fips140=on` in the Temporal service unit within the snap before any cryptographic operations (see FR-033 and `### Go Services FIPS Activation`); OS-level crypto provided by Ubuntu Pro FIPS packages on the host (host prerequisite); bundled in the MAAS snap.
- **Temporal Python SDK** *(MAAS snap — MAAS-owned, MEDIUM risk)*: Python SDK for Temporal; MAAS team MUST validate FIPS-compliant operation on FIPS-enabled Ubuntu hosts; must rely on host-provided FIPS-compliant OpenSSL (Ubuntu Pro FIPS packages) with no bundled non-FIPS native extensions; bundled in the MAAS snap.
- **Curtin** *(MAAS snap — upstream-owned, MEDIUM risk)*: Ubuntu's curtin installer dependency; MAAS team to engage Curtin upstream (Canonical) to confirm FIPS-compatible operation.
- **pylxd** *(MAAS snap — upstream-owned, MEDIUM risk)*: Python LXD client library; MAAS team to engage pylxd upstream to validate FIPS-compliant crypto usage.
- **FIPS CI/CD Integration Tests**: FIPS integration test jobs added to the existing MAAS CI/CD pipeline; run the standard MAAS package on a FIPS-enabled Ubuntu 24.04 LTS host to validate FIPS-compliant operation before each release.

---

## Open Questions *(Resolved)*

- [x] **Q1 — FIPS Enforcement Level** *(Resolved 2026-04-23)*: ALL connections in and out of MAAS must be FIPS-compliant with no exceptions — no mixed-mode or partial FIPS networking.

- [x] **Q2 — Existing Non-FIPS Keys Handling** *(Resolved 2026-04-23)*: FIPS deployments are always green-field. No migration from non-FIPS to FIPS is supported. No legacy key migration tooling required.

- [x] **Q3 — Go Agent FIPS Support** *(Resolved 2026-04-23)*: The Go runtime on a FIPS-enabled Ubuntu host automatically inherits FIPS mode — no MAAS-specific configuration needed. The requirement is to validate (not implement) correct inheritance.

- [x] **Q4 — Single Package, Runtime-Adaptive FIPS** *(Resolved 2026-05-26)*: There is no separate FIPS build artifact. The standard MAAS snap is the only package for the MVP. When installed on a FIPS-enabled Ubuntu host (where `/proc/sys/crypto/fips_enabled` == 1), MAAS automatically detects FIPS mode at startup and operates in FIPS-compliant mode. No environment variables are packaged as build-time FIPS activators. `GODEBUG=fips140=on` is set at runtime by MAAS after detecting `/proc/sys/crypto/fips_enabled`. No separate FIPS-only distribution channel is needed. DEB packaging is deferred to post-MVP.

- [x] **Q5 — FIPS Distribution Channel Strategy** *(Resolved 2026-05-26)*: MAAS is distributed as a snap for the MVP — no separate FIPS-only distribution channel is needed. The standard snap adapts behaviour based on the host OS FIPS state detected at runtime via `/proc/sys/crypto/fips_enabled`. DEB packaging via the MAAS PPA is deferred to post-MVP.

---

**Next Step**: Run `/speckit.plan` to generate detailed implementation design.
