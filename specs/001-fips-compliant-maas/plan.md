# Implementation Plan: FIPS-Compliant MAAS

**Branch**: `fips_compliance` | **Date**: 2026-06-01 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/001-fips-compliant-maas/spec.md`

## Summary

Make MAAS fully operational on Ubuntu hosts with FIPS mode enabled (`/proc/sys/crypto/fips_enabled == 1`). The standard MAAS snap is the only distribution artifact — no separate FIPS build. MAAS detects FIPS at runtime and adapts cryptographic operations: replace MD5/SHA-1/weak ciphers with FIPS-approved algorithms, enforce TLS 1.2 minimum, configure Paramiko SSH for FIPS-compliant ciphers, replace RPC Fernet encryption with AES-256-GCM, replace PostgreSQL MD5 index with `sha256(bytea)`, activate Go FIPS via `GODEBUG=fips140=on`, and expose FIPS status via logs and API.

## Technical Context

**Language/Version**: Python 3.14 (Pyright strict), Go 1.24.4

**Primary Dependencies**:
- Python: FastAPI, SQLAlchemy Core, Pydantic, Twisted, paramiko, `cryptography` (pyOpenSSL 26.0), Django (legacy)
- Go: microcluster, Temporal SDK
- PostgreSQL (built-in `sha256(bytea)` function — no extension required)

**Storage**: PostgreSQL (existing schema; no new tables — FIPS state is ephemeral, read from `/proc/sys/crypto/fips_enabled`)

**Testing**: pytest (Python), `go test` (Go), FIPS-enabled Ubuntu 24.04 LTS VM for integration tests

**Target Platform**: Linux server (Ubuntu 24.04 LTS with FIPS kernel modules), strict-confinement snap (`core26`)

**Project Type**: Web service + CLI + Go microservices (monorepo)

**Performance Goals**: No measurable performance regression on non-FIPS hosts; FIPS detection adds <1ms at startup

**Constraints**:
- Strict snap confinement (no host filesystem access beyond `/proc/sys/crypto/fips_enabled` read)
- 79-char line length, double-quotes only (Python)
- Must not modify `pg_hba.conf` automatically
- Must not break non-FIPS hosts (zero regression)
- All changes to BIND9 rndc key, OMAPI key, RPC encryption, TLS minimum version, SHA-1 `usedforsecurity=False`, X.509 serial generation apply **unconditionally** on all hosts (FIPS and non-FIPS)

**Scale/Scope**: All MAAS deployment scenarios; ~100+ files touched across Python and Go codebases

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Gate | Status | Notes |
|------|--------|-------|
| Three-tier v3 API architecture | PASS | New API endpoints (FIPS status) follow FastAPI → Service → Repository pattern |
| SQLAlchemy Core for repositories | PASS | No ORM usage; existing table definitions in `src/maasservicelayer/db/tables.py` |
| Pydantic builders for create/update | N/A | No new entities with create/update flows; FIPSStatus is read-only response model |
| Async/await (v3 API) | PASS | All new handlers are `async`; legacy uses `deferToDatabase()` |
| Conventional Commits with scopes | PASS | Scopes: `legacy`, `provisioning`, `agent`, `api`, `common`, `db`, `cli` |
| Code quality & linting | PASS | Ruff + Pyright strict (Python), golangci-lint (Go) |
| Database migrations with Alembic | PASS | No new tables; PostgreSQL index change uses raw SQL in Alembic migration |
| Testing pyramid | PASS | Repository tests (real DB), service tests (mocked repos), API tests (mocked services) |
| Three-module governance | PASS | Changes span legacy, provisioning, agent, API, common modules per constitution |
| Backward compatibility | PASS | All unconditional changes are defence-in-depth hardening; FIPS-gated changes only activate when `/proc/sys/crypto/fips_enabled == 1` |

## Project Structure

### Documentation (this feature)

```text
specs/001-fips-compliant-maas/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 — 11 research topics resolved
├── data-model.md        # Phase 1 — FIPSStatus Pydantic model
├── quickstart.md        # Phase 1 — Dev/test guide for FIPS mode
├── contracts/           # Phase 1 — API FIPS impact reference
└── tasks.md             # Phase 2 — Implementation task breakdown
```

### Source Code (repository root)

```text
src/maascommon/
├── fips.py                          # FIPS detection utility (shared Python/Go concept)
└── ...

src/maasserver/                      # Legacy Django region controller
├── models/node.py                   # SHA-1 usedforsecurity=False fix
├── api/doc.py                       # SHA-1 usedforsecurity=False fix (ETag)
└── ...

src/provisioningserver/              # Rack controller
├── rpc/utils.py                     # Replace Fernet with AES-256-GCM
├── certificates.py                  # X.509 serial number generation (secrets.randbits)
├── drivers/power/utils.py           # TLS context — enforce TLS 1.2 minimum
├── drivers/hardware/__init__.py     # BIND9 rndc key: hmac-sha256
└── ...

src/maasapiserver/                   # v3 FastAPI API
├── ...                              # FIPS status endpoint (if added to v3)

src/maasagent/                       # Go agent
├── cmd/                             # Wrapper script entry point for GODEBUG
└── ...

snap/
└── snapcraft.yaml                   # Wrapper script for Go services (GODEBUG=fips140=on)

src/maasservicelayer/db/
├── alembic/versions/                # Migration: replace MD5 index with sha256(bytea)
└── tables.py                        # (no changes — existing table definitions)

src/tests/                           # Integration tests
├── test_fips_detection.py           # Unit tests for FIPS detection
├── test_fips_ssh_config.py          # Paramiko FIPS cipher config tests
├── test_fips_rpc_encryption.py      # AES-256-GCM RPC tests
└── ...
```

**Structure Decision**: Single monorepo project. Changes span multiple existing modules per the constitution's three-module governance model. No new modules created. FIPS detection utility lives in `src/maascommon/` for cross-module reuse. Go FIPS activation is handled via snap wrapper scripts (no source changes to third-party binaries).

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Unconditional cryptographic upgrades (BIND9, OMAPI, RPC, TLS min version) | Defence-in-depth; eliminates FIPS uncertainty across all hosts | Gating on FIPS mode would leave non-FIPS hosts with weak crypto; these are all approved algorithm upgrades with no downside |
| PostgreSQL index change (unconditional) | `md5()` is blocked under FIPS; `sha256(bytea)` works on all hosts | Conditional index would require dual code paths and migration complexity |
| Snap wrapper script for Go services | Strict confinement prevents direct env var injection; source changes not possible for third-party binaries (Temporal) | Static systemd `Environment=` entries would set `GODEBUG=fips140=on` unconditionally, impacting non-FIPS performance |
