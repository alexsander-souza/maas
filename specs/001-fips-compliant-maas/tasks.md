# Tasks: FIPS-Compliant MAAS

**Feature Branch**: `fips_compliance`
**Input**: `specs/001-fips-compliant-maas/` — plan.md, spec.md, data-model.md, research.md, contracts/api-fips-impact-reference.md, quickstart.md
**Generated**: 2026-05-28
**Updated**: 2026-05-28 — Phases 1, 2, 3, 4, 5, 6 complete (T001–T043 ✅); commits f4efba8, e61956f

## Format: `[ID] [P?] [Story?] Description with file path`

- **[P]**: Can run in parallel (different files, no incomplete-task dependencies)
- **[Story]**: Which user story this task belongs to (US1–US6)
- All file paths relative to repository root

---

## Phase 1: Setup (Audit & Infrastructure Verification)

**Purpose**: Confirm test infrastructure is runnable and identify all existing code sites that need FIPS remediation before making any changes.

- [x] T001 Audit existing cryptographic call sites across `src/` for FIPS violations (MD5, DSA, weak TLS, plain HTTP) and produce a short inline comment block summarising each file's required changes — reference `specs/001-fips-compliant-maas/research.md` for the known driver list
- [x] T002 [P] Confirm Python unit-test suite runs successfully on a standard (non-FIPS) dev host: `make test-py` or `python -m pytest tests/maascommon/ tests/maasservicelayer/ tests/maasapiserver/ -x -q`
- [x] T003 [P] Confirm Go unit-test suite runs successfully: `cd src/maasagent && go test ./... -count=1` — establishes green baseline before any agent changes

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core FIPS utilities, logging constants, and the service-layer provider that every other phase depends on. Also includes the unconditional OMAPI HMAC-SHA256 upgrade (all hosts benefit — not FIPS-gated).

**⚠️ CRITICAL**: No user-story work can begin until this phase is complete.

### Phase 2A: Cryptographic Hardening (Unconditional — All Hosts)

**Purpose**: Unconditional cryptographic improvements that benefit all MAAS deployments, not just FIPS hosts. These can run in parallel with Phase 2B.

- [x] T008 Replace HMAC-MD5 OMAPI authenticator with HMAC-SHA256 (unconditional — applies on all hosts) in `src/maasagent/internal/dhcpd/omapi/authenticator.go` — update algorithm selection, update matching unit tests in `src/maasagent/internal/dhcpd/omapi/`
- [x] T008a [P] Replace Fernet encryption with AES-256-GCM (unconditional) in `src/provisioningserver/security.py` — `encrypt_psk`/`decrypt_psk` use `AESGCM` with 256-bit key (PBKDF2-SHA256, `length=32`), 12-byte nonce (`os.urandom(12)`); backward compat via `_is_fernet_token()` + `_fernet_decrypt()` for legacy tokens; no DB migration needed (tokens are ephemeral RPC payloads, not stored); tests in `src/provisioningserver/tests/test_security.py` (`TestAESEncryption`, 7 tests)
- [x] T008b [P] Enforce TLS 1.2 minimum (unconditional) at all TLS context construction sites — Python: `ctx.minimum_version = ssl.TLSVersion.TLSv1_2`; Go: `MinVersion: tls.VersionTLS12`; 13 sites already had it set; fixed 1 remaining: `src/maascli/utils.py` (replaced `ssl.get_server_certificate` with explicit context + `wrap_socket`); no Go TLS sites exist; uvicorn TLS is terminated by nginx (already enforced in nginx config)
- [x] T008c [P] Flag SHA-1 display uses with `usedforsecurity=False` (unconditional) — API documentation ETag in `src/maasserver/api/doc.py` (reverted SHA-256 back to SHA-1 + `usedforsecurity=False`), WebSocket RFC 6455 handshake in `src/maasserver/websockets/websockets.py` (`sha1(..., usedforsecurity=False)`), SSHFP test fingerprint in `src/maasserver/testing/factory.py` (`hashlib.sha1(usedforsecurity=False)`)
- [x] T008d [P] Use `secrets.randbits(64)` for X.509 certificate serial number generation (unconditional) in `src/provisioningserver/certificates.py` — replaced `random.randint` usage
- [x] T008f [P] Replace `md5()` with `sha256()` in PostgreSQL index functions (unconditional) — updated `maasserver_bmc_power_type_parameters_idx` in `src/maasservicelayer/db/tables.py` to use `func.sha256(text("power_parameters::text::bytea"))`; created Alembic migration `src/maasservicelayer/db/alembic/versions/0022_replace_bmc_md5_index_with_sha256.py` (drop + recreate index with `sha256(power_parameters::text::bytea)`); no Django migration changes (per project rules); no test fixture changes needed (index is transparent to tests)

### Phase 2B: FIPS Detection & Utilities (FIPS-Conditional)

**Purpose**: Core FIPS detection utilities and service-layer provider that FIPS-specific features depend on.
- [x] T004 Implement `detect_fips_mode()`, `is_fips_enabled()`, `FIPSStatus` Pydantic model, and `_fips_value` module-level cached value in `src/maascommon/fips.py` — reads `/proc/sys/crypto/fips_enabled`, caches result, defaults to `False` + logs WARNING on OSError
- [x] T005 [P] Implement `FIPSSSHConfig` frozen dataclass (ciphers, kex, macs, key_types allow-lists) and `FIPS_SSH_CONFIG` singleton in `src/maascommon/fips.py` — `configure_fips_ssh(transport)` helper was refactored away; SSH configuration is applied via `get_fips_ssh_disabled_algorithms()` and `connect_ssh()` in `src/provisioningserver/drivers/power/utils.py`
- [x] T006 [P] Add FIPS structured-log event name constants (`FIPS_MODE_DETECTED`, `FIPS_TLS_HANDSHAKE`, `FIPS_SSH_AUTH`, `FIPS_CRYPTO_ERROR`, `FIPS_DRIVER_REJECTED`) to `src/maascommon/logging/security.py`
- [x] T007 Implement `FIPSService(Service)` with `async get_fips_status() -> FIPSStatus` in `src/maasservicelayer/services/fips.py` — wraps `is_fips_enabled()`, no repository, no DB access; register in service-layer `__init__.py`
- [x] T008 Replace HMAC-MD5 OMAPI authenticator with HMAC-SHA256 (unconditional — applies on all hosts) in `src/maasagent/internal/dhcpd/omapi/authenticator.go` — update algorithm selection, update matching unit tests in `src/maasagent/internal/dhcpd/omapi/`
- [x] T009 [P] Write unit tests for FIPS detection utility — 8 tests in `src/tests/maascommon/test_fips.py`: detect enabled/disabled/missing/OSError, cache verification, model field validation, SSH disabled algorithms, config singleton
- [x] T010 [P] Write unit tests for `FIPSService` — 5 async tests in `src/tests/maasservicelayer/services/test_fips.py`: get_fips_status (enabled/disabled), emit_startup_log (INFO when active, INFO when inactive, WARNING on error)

**Checkpoint** ✅: `FIPSStatus` (with `_fips_value` cache), `FIPSService`, `FIPSSSHConfig`, OMAPI HMAC-SHA256, and log constants are available — all user stories can now proceed.

---

## Phase 3: User Story 1 — Install and Operate MAAS on a FIPS Host (Priority: P1) 🎯 MVP

**Goal**: MAAS services (regiond, rackd, maas-agent) start and operate without any FIPS-violation errors on a FIPS-enabled Ubuntu 24.04 LTS host using the standard `.deb` package.

**Independent Test**: Install the standard MAAS package on a fresh FIPS-enabled Ubuntu 24.04 LTS VM; start all MAAS services; confirm MAAS reads `/proc/sys/crypto/fips_enabled`; run normal API and provisioning operations; confirm zero "algorithm not permitted" errors in `journalctl -u maas-regiond`.

### Implementation for User Story 1

- [x] T011 [US1] `MD5PasswordHasher` is controlled by MAAS settings — removed from `PASSWORD_HASHERS` in `src/djangosettings/development.py` when FIPS is active. No explicit startup gate needed since MAAS owns the hasher list.
- [x] T012 [P] [US1] Enforce RSA ≥2048 and ECDSA P-256+ only in certificate/key generation — audit and update `src/provisioningserver/certificates.py` (reject keys below minimum size, log `FIPS_CRYPTO_ERROR` on violation)
- [x] T013 [P] [US1] Add FIPS-conditional key generation enforcement in `src/provisioningserver/security.py` — when `is_fips_enabled()`, reject DSA and RSA <2048, force ECDSA P-256 or RSA 4096 as default
- [x] T014 [P] [US1] Implement `DriverFIPSStatus` enum (`COMPLIANT`, `NON_COMPLIANT_REMEDIABLE`, `UNSUPPORTED_IN_FIPS`) and the full driver classification registry in `src/provisioningserver/drivers/power/registry.py` (or new `src/provisioningserver/drivers/power/fips.py`) per data-model.md table
- [x] T015 [US1] Implement runtime rejection for UNSUPPORTED-IN-FIPS drivers (apc, eaton, raritan, dli, msftocs, recs, seamicro, ucsm, moonshot) — when `is_fips_enabled()`, raise `FIPSDriverUnsupportedError` with reason string in each driver's `power_control_*` / `detect_*` entry points under `src/provisioningserver/drivers/power/`
- [x] T016 [P] [US1] Fix VMware TLS context — replace deprecated `ssl.PROTOCOL_SSLv23` and `ssl.CERT_NONE` with `ssl.create_default_context()` (modern TLS, verified cert) in `src/provisioningserver/drivers/hardware/vmware.py`
- [x] T017 [P] [US1] Enforce HTTPS + verified TLS for AMT driver in FIPS mode — reject plain HTTP (port 16992) and self-signed bypass in `src/provisioningserver/drivers/power/amt.py`; log `FIPS_CRYPTO_ERROR` and surface user error on violation
- [x] T018 [P] [US1] Enforce `verify_ssl=True` for hmcz, proxmox, and webhook drivers in FIPS mode — reject `power_verify_ssl: false` with 422 error in `src/provisioningserver/drivers/power/hmcz.py`, `src/provisioningserver/drivers/power/proxmox.py`, and `src/provisioningserver/drivers/power/webhook.py`
- [x] T019 [P] [US1] Apply `configure_fips_ssh()` to all paramiko clients in HMC driver and replace `AutoAddPolicy` with `RejectPolicy` in FIPS mode in `src/provisioningserver/drivers/power/hmc.py`
- [x] T020 [P] [US1] Apply `configure_fips_ssh()` to all paramiko clients in MSCM driver and replace `AutoAddPolicy` with `RejectPolicy` in FIPS mode in `src/provisioningserver/drivers/power/mscm.py`
- [x] T021 [P] [US1] Apply `configure_fips_ssh()` to all paramiko clients in Wedge driver and replace `AutoAddPolicy` with `RejectPolicy` in FIPS mode in `src/provisioningserver/drivers/power/wedge.py`
- [x] T022 [US1] Implement Go FIPS detection module: `IsEnabled() bool` reading `/proc/sys/crypto/fips_enabled`, caching result in `src/maasagent/internal/fips/fips.go`; add `src/maasagent/internal/fips/fips_test.go`
- [x] T023 [US1] Integrate FIPS detection into Go agent startup — call `fips.IsEnabled()` at process start and emit structured log entry `{"event":"fips_mode_detected","fips_mode":true/false}` in `src/maasagent/internal/daemon/main.go` (or equivalent startup entrypoint)
- [x] T023a [US1] Set Go FIPS environment variable `GODEBUG=fips140=on` via wrapper scripts (`snap/bin/maas-agent-fips-wrapper.sh`, `debian/extras/maas-temporal-fips-wrapper.sh`) when `/proc/sys/crypto/fips_enabled == 1`. `GOFIPS=1` is legacy and not used.
- [x] T024 [P] [US1] MAAS and simplestreams exclusively use SHA-256 for image checksums — no MD5 code path exists in the provisioning workflow. No changes required.
- [x] T025 [P] [US1] Write unit tests for IPMI cipher suite 17 enforcement (reject suites 3, 8, 12 in FIPS mode; accept suite 17) in `tests/provisioningserver/drivers/power/test_ipmi_fips.py`
- [x] T026 [P] [US1] Write unit tests for UNSUPPORTED-IN-FIPS driver rejection (verify each of the 9 blocked drivers raises the correct error when FIPS active) in `tests/provisioningserver/drivers/power/test_fips_driver_rejection.py`

**Checkpoint** ✅: All US1 implementation is complete. User Story 1 is independently verifiable.
==== BASE ====

---

## Phase 4: User Story 2 — Verify FIPS Mode is Active After Installation (Priority: P1)

**Goal**: MAAS exposes its detected FIPS state via a structured startup log entry and via `GET /api/v3/` so administrators and auditors can confirm FIPS-compliant operation without inspecting cryptographic operations directly.

**Independent Test**: Install MAAS on a FIPS-enabled host; check `journalctl -u maas-regiond | grep fips_mode` for `"fips_mode": true`; check `curl http://localhost:5240/MAAS/api/v3/ | python3 -m json.tool | grep fips` for `"fips_active": true`.

### Implementation for User Story 2

- [X] T027 [US2] Emit `FIPS_MODE_DETECTED` structured log event at regiond startup using `FIPSService.get_fips_status()` — log `{"event":"FIPS_mode_detected","fips_mode":true/false,"source":"/proc/sys/crypto/fips_enabled"}` at INFO (or WARNING on detection error) in `src/maasservicelayer/services/fips.py` startup hook
- [X] T028 [US2] Add `fips_active: bool` field to `RootGetResponse` Pydantic model in `src/maasapiserver/v3/api/public/handlers/root.py`; populate it from `FIPSService.get_fips_status()` injected via FastAPI `Depends`
- [X] T029 [P] [US2] Add `fips_supported: bool` and `fips_unsupported_reason: str | None` fields to the power-types list API response (FR-027 §3) — update the power-types handler to read `DriverFIPSStatus` from the registry and annotate each driver in `src/maasapiserver/v3/api/public/handlers/` power-types endpoint
- [X] T030 [P] [US2] Write API handler unit tests for `fips_active: true` (FIPS mock active) and `fips_active: false` (FIPS mock inactive) on `GET /api/v3/` in `tests/maasapiserver/test_root_fips.py`
- [X] T031 [P] [US2] Write unit test confirming `FIPS_MODE_DETECTED` log event is emitted at startup with correct fields in `tests/maasservicelayer/services/test_fips.py`

**Checkpoint**: `GET /api/v3/` returns `fips_active` and startup logs contain `fips_mode_detected`. User Story 2 independently verifiable.

---

## Phase 5: User Story 3 — Compliance Auditor: Verify FIPS-Compliant Operation (Priority: P2)

**Goal**: MAAS produces structured, machine-parsable audit log entries for all FIPS-relevant cryptographic events (TLS handshake, SSH auth, crypto errors, driver rejections) and enforces FIPS algorithm restrictions at API import boundaries (SSH keys, TLS certificates).

**Independent Test**: Enable structured logging on a FIPS MAAS host; perform SSH and TLS connections; run `journalctl -u maas-regiond -o json | jq 'select(.event | startswith("FIPS_"))'` and confirm entries appear for each event type with required fields; run `sslscan localhost:5240` and confirm TLS 1.2+ with approved ciphers only.

### Implementation for User Story 3

- [x] T032 [US3] Emit `FIPS_TLS_HANDSHAKE` structured log event (cipher suite, protocol version, peer, cert_issuer, cert_valid) for outbound TLS connections managed by MAAS — locate Twisted/pyOpenSSL TLS connection paths in `src/provisioningserver/` and `src/maasservicelayer/` and add structlog call using `FIPS_TLS_HANDSHAKE` constant
- [x] T033 [P] [US3] Emit `FIPS_SSH_AUTH` structured log event (key_type, kex, cipher, mac, peer, result) after each paramiko SSH session negotiation in `src/provisioningserver/drivers/power/hmc.py`, `mscm.py`, `wedge.py` — add event emission after `configure_fips_ssh()` call
- [x] T034 [P] [US3] Emit `FIPS_CRYPTO_ERROR` structured log event (operation, error, algorithm, peer) at every FIPS rejection site added in Phase 3 (certificates.py, security.py, power drivers) — ensure all rejection paths log with `FIPS_CRYPTO_ERROR` before raising
- [x] T035 [P] [US3] Enforce FIPS SSH key algorithm restrictions at API import boundary — reject `ssh-dss`, `ssh-ed25519`, RSA <2048 when FIPS active with 422 + `fips_violation: true` JSON error in SSH keys API handler in `src/maasapiserver/v3/api/public/handlers/sshkeys.py` (or equivalent v3 handler)
- [x] T036 [P] [US3] Enforce FIPS TLS certificate algorithm restrictions at API import boundary — reject SHA-1/MD5 signatures and RSA <2048/DSA keys when FIPS active with 422 + `fips_violation: true` JSON error in SSL keys API handler in `src/maasapiserver/v3/api/public/handlers/sslkeys.py` (or equivalent v3 handler)
- [x] T037 [P] [US3] Implement shared FIPS violation error response schema (`error`, `fips_violation: true`, `allowed_values`, `fips_supported_alternatives`) as a Pydantic model/helper in `src/maasapiserver/v3/api/public/` for consistent 422 response formatting across all FIPS rejection paths
- [x] T038 [P] [US3] Write unit tests for SSH key API FIPS validation: reject `ssh-dss`, `ssh-ed25519`, RSA <1024; accept ECDSA, RSA ≥2048 — in `tests/maasapiserver/test_sshkeys_fips.py`
- [x] T039 [P] [US3] Write unit tests for TLS certificate API FIPS validation: reject SHA-1/MD5 certs; accept SHA-256+ — in `tests/maasapiserver/test_sslkeys_fips.py`

**Checkpoint** ✅: All FIPS crypto events produce structured log entries; API import endpoints enforce FIPS algorithm restrictions with correct error schema. User Story 3 is independently auditable.

---

## Phase 6: User Story 4 — SSH Operations on Managed Machines (Priority: P2)

**Goal**: All MAAS-initiated SSH sessions to managed machines use only FIPS-approved ciphers, key-exchange, and MACs (enforced by MAAS, not the managed machine's config). Non-FIPS SSH server algorithm sets are explicitly rejected with a clear error.

**Independent Test**: Enable SSH verbose logging (`-vvv`) on MAAS outbound connections; confirm only FIPS-approved algorithms appear in negotiation; attempt connection to a test SSH server that only advertises `hmac-md5` and confirm MAAS rejects the connection with `FIPS_crypto_error` in the log.

### Implementation for User Story 4

- [x] T040 [US4] Enforce IPMI cipher suite 17 only in FIPS mode — modify `ipmitool` invocation in `src/provisioningserver/drivers/power/ipmi.py` to pass `-C 17` when `is_fips_enabled()` is True; reject suites 3, 8, 12 with a user-facing error and `FIPS_CRYPTO_ERROR` log event
- [x] T041 [P] [US4] Add FIPS-conditional SSH key generation enforcement in `src/provisioningserver/security.py` — when `is_fips_enabled()` and a DSA key or RSA <2048 key generation is requested, raise `FIPSCryptoError` and log `FIPS_CRYPTO_ERROR` before delegating to `cryptography` library
- [x] T042 [P] [US4] Verify Go agent Temporal TLS configuration exclusively uses FIPS-approved cipher suites — inspect `src/maasagent/internal/temporal/` TLS config; ensure `MinVersion: tls.VersionTLS12` and no weak ciphers are present; add inline comment block confirming FIPS compliance
- [x] T043 [P] [US4] Write SSH FIPS enforcement unit tests: mock `configure_fips_ssh()` application on paramiko transport; verify allowed cipher/kex/mac lists are set; verify `RejectPolicy` replaces `AutoAddPolicy` — in `tests/provisioningserver/drivers/power/test_ssh_fips.py`

**Checkpoint**: All MAAS SSH connections exclusively use FIPS-approved algorithms. Non-compliant SSH servers receive an explicit rejection. User Story 4 independently testable.

---

## Phase 6A: PostgreSQL MD5 Detection (FIPS-Conditional)

**Goal**: MAAS detects MD5 authentication at startup on FIPS hosts and refuses to start with an actionable error, directing the operator to configure `scram-sha-256`.

**Independent Test**: Configure PostgreSQL with `md5` authentication in `pg_hba.conf`; start MAAS on a FIPS host; confirm MAAS refuses to start with the exact error message; update to `scram-sha-256`; confirm MAAS starts successfully.

### Implementation for PostgreSQL MD5 Detection

- [x] T043a [US4] Implement PostgreSQL MD5 detection at startup — when `is_fips_enabled()`, query the active PostgreSQL authentication method for the MAAS database; if MD5 is detected, emit the exact error: `"PostgreSQL is configured to use MD5 authentication, which is prohibited under FIPS mode. Update pg_hba.conf to use scram-sha-256 for the MAAS database entry and restart MAAS."` and refuse to start; implemented in `src/maasservicelayer/services/fips.py` startup hook
- [x] T043b [P] [US4] Write unit tests for PostgreSQL MD5 detection: mock `fips_enabled=True` with MD5 auth (expect refusal), mock `fips_enabled=True` with `scram-sha-256` (expect success), mock `fips_enabled=False` with MD5 (expect success) in `tests/maasservicelayer/services/test_fips.py`

**Checkpoint**: MAAS refuses to start on FIPS hosts with MD5 PostgreSQL authentication. User Story 4 complete.

---

## Phase 7: User Story 5 — CI/CD Validates FIPS Compliance Per Release (Priority: P2)

**Goal**: The standard MAAS package is automatically validated against a FIPS-enabled Ubuntu 24.04 LTS host as part of every release pipeline run. A failed FIPS integration test blocks the release.

**Independent Test**: Trigger a manual CI/CD pipeline run; confirm the FIPS integration test job executes, installs the standard MAAS package on a FIPS host, and passes/fails the release gate.

### Implementation for User Story 5

- [ ] T044 [US5] Write FIPS integration test suite covering all 8 verification scenarios from quickstart.md (startup log, API `fips_active`, SSH algorithm negotiation, TLS cipher sslscan, IPMI cipher rejection, image download, Go agent log, zero audit violations) in `tests/integration/test_fips_compliance.py`
- [ ] T045 [P] [US5] Add `--fips-host`, `--maas-url`, `--maas-api-key` pytest CLI options and `fips_enabled` / `fips_disabled` fixtures (mocking `_FIPS_ENABLED`) to `tests/conftest.py` for consistent FIPS test environment control
- [ ] T046 [US5] Add `fips-integration` CI/CD job to GitHub Actions workflow — installs standard MAAS `.deb` on Ubuntu 24.04 FIPS runner, runs `tests/integration/test_fips_compliance.py`, gates release on pass — add to `workflows/` (or equivalent CI config directory)

**Checkpoint**: FIPS compliance is validated automatically per release. A regression in any phase would be caught before publication.

---

## Phase 8: User Story 6 — PPA Dependency FIPS Compliance (Priority: P3)

**Goal**: All MAAS PPA dependencies (Temporal server, Temporal Python SDK, Curtin, pylxd) operate without FIPS violations on a FIPS-enabled Ubuntu 24.04 LTS host. MAAS-owned packages are rebuilt with FIPS-compliant settings; externally-owned packages are audited and documented.

**Independent Test**: Run MAAS with all PPA dependencies on a FIPS-enabled host with `auditd` active; run `sudo ausearch -m CRYPTO_FAILURE`; confirm zero entries after 10 minutes of normal operation.

### Implementation for User Story 6

- [ ] T047 [US6] Audit Temporal Go binary for FIPS compliance — verify it is built with `-tags boringcrypto`, validate `GOFIPS=1` is set in the Temporal service unit file, and confirm gRPC/TLS uses FIPS-approved suites; update `src/maasagent/internal/temporal/` TLS setup and `package-files/` service unit if needed
- [ ] T048 [P] [US6] Audit Temporal Python SDK for FIPS-compliant gRPC/TLS — confirm no bundled non-FIPS crypto is used; if violation found, open upstream issue and document mitigation; produce compliance note in `specs/001-fips-compliant-maas/research.md` (append §PPA section)
- [ ] T049 [P] [US6] Document FIPS compliance status for Curtin and pylxd — engage upstream owners or review source; document confirmed-compliant / needs-mitigation / risk-accepted status with formal risk assessment in `specs/001-fips-compliant-maas/research.md` (append §PPA section)
- [ ] T050 [US6] Rebuild and publish MAAS-owned Temporal PPA binary with `-tags boringcrypto`; update `required-packages/` or `package-files/` to reference the FIPS-validated Temporal version and set `GOFIPS=1` in the Temporal systemd unit

**Checkpoint**: PPA dependency FIPS compliance is either confirmed or documented with a risk-accepted mitigation plan.

---

## Final Phase: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, CI cleanup, and manual validation that span all user stories.

- [ ] T051 [P] Run the quickstart.md manual validation checklist end-to-end on a FIPS-enabled Ubuntu 24.04 LTS VM — confirm all 8 verification scenarios from `specs/001-fips-compliant-maas/quickstart.md` pass with the final implementation
- [ ] T052 [P] Update `INSTALL.txt` with FIPS prerequisites (Ubuntu Pro subscription, `ubuntu-fips` packages, reboot requirement) and supported platforms
- [ ] T053 [P] Add FIPS power-driver support matrix (compliant / unsupported / reason) to `docs/` — reference the `DriverFIPSStatus` registry for accuracy
- [ ] T054 [P] Add `fips_active` field to the MAAS `status` CLI command output so operators can verify FIPS mode without querying the API directly — update the relevant CLI handler in `src/`
- [ ] T055 Review FR-027 API FIPS Impact Reference (`specs/001-fips-compliant-maas/contracts/api-fips-impact-reference.md`) against the implementation; mark review/approval fields; confirm all FIPS API error responses match the `fips_violation` schema defined in T037

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1 (Setup)
    └── Phase 2A (Cryptographic Hardening — Unconditional) ← can run in parallel with Phase 2B
    └── Phase 2B (FIPS Detection & Utilities) ← BLOCKS ALL USER STORIES
            ├── Phase 3 (US1 — P1) ← MVP
            ├── Phase 4 (US2 — P1) ← depends on T007 (FIPSService)
            ├── Phase 5 (US3 — P2)
            ├── Phase 6 (US4 — P2) ← T040 depends on Phase 3 IPMI work
            ├── Phase 6A (PostgreSQL MD5 Detection) ← depends on T007 (FIPSService)
            ├── Phase 7 (US5 — P2) ← depends on all implementation phases
            └── Phase 8 (US6 — P3)
                    └── Final Phase (Polish)
```

### User Story Dependencies

| Story | Priority | Depends On | Blocks |
|-------|----------|------------|--------|
| US1 — Install & Operate | P1 | Phase 2A + 2B complete | Nothing (MVP) |
| US2 — Verify FIPS Active | P1 | Phase 2A + 2B complete (T007 FIPSService) | Nothing |
| US3 — Compliance Audit | P2 | Phase 2A + 2B complete; US1 rejection paths (Phase 3) for log events | Nothing |
| US4 — SSH Operations | P2 | Phase 2A + 2B complete (T005 configure_fips_ssh) | Nothing |
| PostgreSQL MD5 Detection | P1 | Phase 2B complete (T007 FIPSService) | Nothing |
| US5 — CI/CD Validation | P2 | All implementation phases (US1–US4 + PostgreSQL) complete | Nothing |
| US6 — PPA Compliance | P3 | Phase 2A + 2B complete; US1 Go agent (T022–T023) | Nothing |

### Within-Phase Task Dependencies

**Phase 2A (Unconditional)**:
- T008a–T008f can all run in parallel (different files, no dependencies)

**Phase 2B (FIPS-Conditional)**:
- T005 (`FIPSSSHConfig`) → complete T004 (`is_fips_enabled`) first (same file)
- T009, T010 → complete T004, T007 first (tests need implementations)

**Phase 3 (US1)**:
- T011 (`MD5PasswordHasher gate`) → complete T007 (`FIPSService`) first
- T015 (driver rejection) → complete T014 (`DriverFIPSStatus` registry) first
- T019–T021 (SSH cipher pinning) → complete T005 (`configure_fips_ssh`) first
- T022 (Go FIPS module) → complete before T023 (daemon startup log)

**Phase 4 (US2)**:
- T028 (API `fips_active`) → complete T007 (`FIPSService`) first
- T027 (startup log) → complete T007 first

**Phase 5 (US3)**:
- T034 (`FIPS_CRYPTO_ERROR` at rejection sites) → complete Phase 3 rejection paths (T012, T013, T015–T021) first
- T037 (error schema) → complete before T035, T036 (API import boundaries use it)

**Phase 6 (US4)**:
- T040 (IPMI cipher suite 17) → relates to T025 (Phase 3 IPMI tests); implement before writing additional tests
- T041 (SSH key generation) → complete T013 (Phase 3 `security.py`) first

**Phase 6A (PostgreSQL MD5 Detection)**:
- T043a (MD5 detection) → complete T007 (`FIPSService`) first
- T043b (tests) → complete T043a first

### Parallel Opportunities Per Phase

**Phase 2A Parallel Set** (all unconditional, can run immediately):
```
T008a Fernet→AES-256-GCM        T008b TLS 1.2 minimum
T008c SHA-1 usedforsecurity=False  T008d X.509 serial CSPRNG
```

**Phase 2B Parallel Set A** (after T004 is complete):
```
T005 configure_fips_ssh()       T006 security log constants
T009 test_fips.py unit tests    T010 test FIPSService unit tests
```

**Phase 3 Parallel Set A** (after T004, T005, T007, T014 complete):
```
T012 certificates.py            T013 security.py key gen
T016 vmware.py TLS fix          T017 amt.py HTTPS enforce
T018 hmcz/proxmox/webhook SSL   T019 hmc.py SSH cipher
T020 mscm.py SSH cipher         T021 wedge.py SSH cipher
T024 image checksum MD5 reject  T025 IPMI unit tests
T026 driver rejection tests
```

**Phase 5 Parallel Set A** (after Phase 3 rejection paths complete):
```
T033 FIPS_SSH_AUTH log events   T034 FIPS_CRYPTO_ERROR at rejection sites
T035 SSH key API FIPS gate      T036 TLS cert API FIPS gate
T038 test sshkeys FIPS          T039 test sslkeys FIPS
```

---

## Parallel Execution Examples

### Phase 3 (US1) — Parallel Start After Phase 2

```bash
# Developer A — Python provisioning (power drivers):
T012 → T013 → T015 (in sequence)
T016, T017, T018 in parallel

# Developer B — SSH drivers (independent files):
T019 (hmc.py), T020 (mscm.py), T021 (wedge.py) all in parallel

# Developer C — Go agent:
T022 (fips.go) → T023 (daemon main.go) in sequence

# Developer D — Tests:
T025 (IPMI tests), T026 (driver rejection tests) in parallel
```

### Phase 4 (US2) + Phase 5 (US3) — Can Start in Parallel with Phase 3

```bash
# Developer A (Phase 4, US2):
T027 (startup log event) → T028 (API handler) → T030, T031 tests

# Developer B (Phase 5, US3):
T037 (error schema first) → T035, T036 (API gates) → T038, T039 tests
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2 Only — Both P1)

1. ✅ Complete Phase 1: Setup (audit + confirm tests green)
2. ✅ Complete Phase 2A: Cryptographic Hardening (T008, T008a–T008f) — unconditional
3. ✅ Complete Phase 2B: FIPS Detection & Utilities (T004–T007, T009–T010) — CRITICAL GATE
4. ✅ Complete Phase 3: User Story 1 (T011–T026, T023a)
5. ✅ Complete Phase 4: User Story 2 (T027–T031)
6. ✅ Complete Phase 6A: PostgreSQL MD5 Detection (T043a–T043b)
7. **STOP and VALIDATE**: Install standard MAAS package on FIPS Ubuntu 24.04 LTS VM; run quickstart.md verification; confirm `fips_active: true` in API and zero algorithm violations in logs
8. Deploy/demo if ready — MVP is live

### Incremental Delivery Beyond MVP

1. Foundation (2A + 2B) + US1 + US2 + PostgreSQL MD5 → **MVP**: MAAS operates and self-identifies on FIPS host
2. Add US3 (Phase 5) → Compliance auditors can verify with structured logs
3. Add US4 (Phase 6) → SSH operations are explicitly FIPS-enforced end-to-end
4. Add US5 (Phase 7) → CI/CD prevents future regressions (permanent gating)
5. Add US6 (Phase 8) → PPA dependency compliance confirmed or risk-accepted
6. Polish (Final Phase) → Documentation and CLI complete

### Parallel Team Strategy (5 Developers)

| Phase | Dev A | Dev B | Dev C | Dev D | Dev E |
|-------|-------|-------|-------|-------|-------|
| Phase 2A | T008a, T008b | T008c, T008d | — | T008f (sha256 index) | — |
| Phase 2B | T004, T005 | T006, T007 | T008 (Go OMAPI) | T009 (tests) | T010 (tests) |
| Phase 3 | T011, T012, T013 | T014, T015 | T016–T018 | T019–T021 | T022–T024, T023a |
| Phase 4+5 | T027–T028 | T029–T031 | T032–T034 | T035–T037 | T038–T039 |
| Phase 6+6A | T040–T041 | T042–T043 | T043a–T043b | — | — |
| Phase 7+8 | T044–T046 | T047–T048 | T049–T050 | — | — |
| Polish | T051–T052 | T053–T054 | T055 | — | — |

---

## Notes

- Tasks marked `[P]` operate on distinct files with no dependency on incomplete sibling tasks — safe to run in parallel
- `[Story]` label maps each task to its user story for traceability (US1–US6)
- FIPS detection (`is_fips_enabled()`) is always mocked in unit tests; only integration tests (`tests/integration/test_fips_compliance.py`) require a real FIPS Ubuntu host
- **Unconditional changes** (Phase 2A): FR-029 (OMAPI HMAC-SHA256), FR-032 (Fernet→AES-256-GCM), FR-034 (TLS 1.2 minimum), FR-035 (SHA-1 `usedforsecurity=False`), FR-036 (X.509 serial CSPRNG), FR-037 (sha256 index functions) — all apply to all MAAS hosts
- **FIPS-conditional changes** (Phase 2B, 3, 4, 5, 6, 6A): FR-031 (PostgreSQL MD5 detection), FR-033 (Go FIPS activation), SSH/TLS enforcement, driver restrictions — only when `fips_enabled=True`
- VMware TLS fix (T016) is also unconditional — replacing `ssl.PROTOCOL_SSLv23` is a security improvement for all hosts
- Commit scope convention: `feat(common):`, `feat(api):`, `feat(service):`, `fix(provisioning):`, `feat(agent):`, `test(api):`, `ci:` per MAAS Conventional Commits spec
- Verify tests fail before implementing (where tests are written first — T009, T010, T025, T026, T030, T031, T038, T039, T043, T043b, T045)

---

## Implementation Status Audit (2026-05-29)

**Audit method**: 5 parallel agents inspected source code against every task in this file.

### Summary by Phase

| Phase | Complete | Partial | Not Started | Total |
|-------|----------|---------|-------------|-------|
| Phase 1 (Setup) | 3 | 0 | 0 | 3 |
| Phase 2A (Crypto Hardening) | 5 | 0 | 2 | 7 |
| Phase 2B (FIPS Detection) | 4 | 0 | 2 | 6 |
| Phase 3 (US1) | 16 | 0 | 0 | 16 |
| Phase 4 (US2) | 5 | 0 | 0 | 5 |
| Phase 5 (US3) | 8 | 0 | 0 | 8 |
| Phase 6 (US4) | 3 | 0 | 0 | 3 |
| Phase 6A (PG MD5) | 2 | 0 | 0 | 2 |
| Phase 7 (US5 CI/CD) | 0 | 0 | 3 | 3 |
| Phase 8 (US6 PPA) | 0 | 3 | 1 | 4 |
| Final (Polish) | 0 | 1 | 4 | 5 |
| **Total** | **46** | **1** | **15** | **62** |

### Remediation Plan — Priority Order

**P0 — Blocking (must complete before any user story works correctly):**

_No remaining P0 blockers._

**P1 — MVP gaps (US1 incomplete without these):**

1. **T024** — _Resolved: MAAS and simplestreams exclusively use SHA-256, no MD5 code path exists._

**P2 — Unconditional hardening (all hosts benefit):**

2. **T008a** — Implement Fernet→AES-256-GCM replacement in `src/provisioningserver/rpc/utils.py` with Alembic data migration.
3. **T008f** — Replace `md5()` with `sha256(power_parameters::text::bytea)` in the `maasserver_bmc_power_type_parameters_idx` index.

**P3 — Test coverage gaps:**

4. **T009** — Write unit tests for FIPS detection utility in `tests/maascommon/test_fips.py`.
5. **T010** — Write unit tests for `FIPSService` in `tests/maasservicelayer/services/test_fips.py`.

**P4 — Post-MVP (CI/CD, docs, PPA):**

6. **T044–T046** — FIPS integration tests, pytest fixtures, CI/CD job.
7. **T047–T050** — PPA dependency audits and Temporal rebuild.
8. **T051–T055** — Documentation, CLI status, contract review.
