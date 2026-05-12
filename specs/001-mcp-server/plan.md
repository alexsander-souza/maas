# Implementation Plan: MAAS MCP Server

**Branch**: `6689-mcp-server` | **Date**: 2025-07-22 | **Spec**: [spec.md](spec.md)

---

## Summary

A new standalone Python module `src/maasmcpserver/` that implements a Model Context Protocol
(MCP) server bridging AI assistants to MAAS bare-metal infrastructure. The server communicates
exclusively with MAAS HTTP API v3 via per-session JWT Bearer token delegation. Transport is
HTTP/SSE (`streamable-http`) only, bound to a **Unix domain socket** fronted by the MAAS
region **nginx** on TCP port 5275. The module has no database dependency — all data flows
through MAAS API v3. Machine lifecycle write operations are fully deferred (TC-2); network
management (fabric/VLAN/subnet) and boot-source operations are in scope.

### Hard Constraints (Non-Negotiable)

| # | Constraint | Effect on plan |
|---|-----------|----------------|
| TC-1 | `python3-mcp` from Ubuntu archive only — never PyPI | Declared in `debian/control` `Depends:` + `snapcraft.yaml` `stage-packages:` |
| TC-2 | Machine lifecycle writes unavailable in API v3 | All FR-6 tools deferred; runtime `not-implemented` guard required |
| TC-3 | Unix domain socket listener only — no TCP bind on MCP server | `MCP_SOCKET_PATH` env var; no `MCP_HOST`/`MCP_PORT`; nginx owns port 5275 |
| TC-4 | No native TLS on MCP listener | No TLS config vars; naturally satisfied by Unix socket behind nginx |
| TC-5 | Dual deb + snap packaging | systemd unit (deb) **and** Pebble layer `004-maas-mcp-layer.yaml` (snap) |

---

## Technical Context

**Language/Version**: Python 3.14

**Deployment targets**:

| Format | Package | Service manager | Service name | Default state |
|--------|---------|-----------------|--------------|---------------|
| deb | `maas-mcp-server` | systemd | `maas-mcp-server.service` | disabled |
| snap | `maas` | Pebble (`004-maas-mcp-layer.yaml`) | `mcp-server` | `startup: disabled` |

**Network binding**:

- The MCP server binds a **Unix domain socket** (default: `/run/maas/mcp.sock` for deb;
  `$SNAP_DATA/mcp.sock` for snap). It does NOT bind a TCP address or port.
- The MAAS region **nginx** reverse proxy fronts the Unix socket and exposes the service
  externally on **TCP port 5275**. The MCP server is never aware of port 5275.
- nginx configuration for port 5275 is a region controller concern — the MCP server does
  not configure or manage nginx.
- `MCP_HOST` and `MCP_PORT` environment variables must **not** be implemented. The correct
  variable is `MCP_SOCKET_PATH`.

**Primary dependencies**:

| Package | Source | Notes |
|---------|--------|-------|
| `python3-mcp` | **Ubuntu archive only** (TC-1) | MCP Python SDK (`FastMCP`) — NOT PyPI |
| `python3-httpx` | Ubuntu archive | Async HTTP client for MAAS API v3 |
| `python3-pydantic` ≥ 2.0.0 | Ubuntu archive | Response models and settings |
| `python3-pydantic-settings` | Ubuntu archive | `BaseSettings` for env-var config |
| `python3-uvicorn` | Ubuntu archive | ASGI server for `streamable-http` transport over Unix socket |
| `python3-structlog` | Ubuntu archive | Structured logging (FR-10) |
| `python3-pythonjsonlogger` | Ubuntu archive | NDJSON formatter |

**Database**: **None** — no SQLAlchemy, no Alembic, no `db_connection` fixture in tests.

**Testing**: `pytest` + `pytest-asyncio` + `httpx` (`AsyncMock`) — standard async unit
tests. No database fixture. Integration tests against a live MAAS endpoint are optional CI
jobs.

**Target component**: `src/maasmcpserver/` — new standalone module. NOT part of
`maasapiserver` or `maasservicelayer`.

**Architecture pattern**: Documented exception to the 3-tier constitution rule. This module
is a thin adapter: MCP protocol ↔ MAAS HTTP API v3. No service layer, no repository layer,
no database.

**Import boundary (hard constraint)**: `maasmcpserver` may only import from `maascommon`.
Imports from `maasservicelayer`, `maasapiserver`, `maasserver`, or any other MAAS component
are **not permitted**.

**Scale/scope**: 1 standalone module, 27 MCP tools across 5 tool-group files, 1 async HTTP
client, 1 ASGI auth middleware, `structlog`-based NDJSON logging, 1 Pydantic config.

---

## Constitution Check

*Gate: Verify compliance before Phase 1 research.*

- ✅ **Architecture exception documented**: `maasmcpserver` is a new standalone module, not
  a MAAS v3 API feature. The 3-tier architecture (API → Service → Repository) does not
  apply. No database, no ORM, no SQLAlchemy, no service/repository layers.
  **Rationale**: The MCP server is a protocol adapter; its "data layer" is the external
  MAAS HTTP API v3.
- ✅ **No database migrations required**: No schema changes; no Alembic migration. The MCP
  server is stateless (no persistent storage of any kind).
- ✅ **Testing strategy**: `pytest` + `pytest-asyncio`; tool tests mock `httpx.AsyncClient`;
  no `db_connection` fixture.
- ✅ **Conventional Commits scope**: New scope `mcp` maps to `src/maasmcpserver/`. **Action
  required before first commit**: add `mcp` to `.specify/memory/scopes.md`.
- ✅ **Ruff formatting**: 79 chars, double quotes — enforced per constitution.
- ✅ **No ORM in repositories**: N/A — no repositories, no SQLAlchemy at all.
- ✅ **TC-3 / Unix socket**: Plan correctly uses `MCP_SOCKET_PATH` throughout; no `MCP_HOST`
  or `MCP_PORT`; nginx owns TCP port 5275 exclusively.
- ✅ **TC-4 / No native TLS**: Naturally satisfied — Unix socket behind nginx never faces
  external traffic directly; no TLS config vars implemented.
- ✅ **TC-5 / Dual packaging**: Plan specifies both systemd unit (deb) and Pebble layer 004
  (snap); `run-mcp-server` wrapper follows existing `run-apiserver` pattern exactly.
- ✅ **TC-1 / Ubuntu archive only**: `python3-mcp` declared in both `debian/control`
  `Depends:` and `snapcraft.yaml` `stage-packages:`; no PyPI reference anywhere.

---

## Module Layout (`src/maasmcpserver/`)

```
src/maasmcpserver/
├── __init__.py
├── __main__.py           # python3 -m maasmcpserver entry point
├── config.py             # MaasServerConfig (Pydantic BaseSettings)
├── server.py             # FastMCP app factory, lifespan, Unix socket bind
├── middleware.py         # ASGI auth middleware: extracts JWT from Authorization header
├── client.py             # MAASClient (httpx.AsyncClient wrapper)
├── logging_events.py     # configure_logging(), structured NDJSON event emitters
├── errors.py             # MAASUnreachableError, MAASPermissionError
├── models/
│   ├── __init__.py
│   ├── machines.py       # MachineSummary, MachineDetail, InterfaceSummary, BlockDevice
│   ├── diagnostics.py    # MachineEvent, ScriptResult
│   ├── info.py           # MAASInfo, RackController
│   ├── network.py        # Fabric, VLAN, Subnet
│   └── boot_sources.py   # BootSource, BootSourceSelection
└── tools/
    ├── __init__.py
    ├── fleet.py          # FR-4: list_machines, get_machine, list_resource_pools,
    │                     #       list_zones, get_machine_power_state
    ├── diagnostics.py    # FR-5: get_machine_events, get_script_results
    ├── info.py           # FR-12: get_maas_info
    ├── network.py        # FR-13: list/get/create/update/delete fabrics, VLANs, subnets
    └── boot_sources.py   # FR-14: list_boot_sources, trigger_boot_source_sync,
                          #        delete_boot_source
```

---

## Phase 0: Research Findings

*(Research complete — see [research.md](research.md) for full decision log.)*

### Key Architectural Decisions

1. **Unix socket only** — `MCP_SOCKET_PATH` (not `MCP_HOST`/`MCP_PORT`). nginx owns port
   5275. MCP server is never aware of the external port.
2. **`streamable-http` transport** over the Unix socket, via uvicorn. No stdio.
3. **JWT Bearer token forwarded verbatim** from the MCP client's `Authorization` header to
   every MAAS API v3 request. ASGI middleware extracts it into a `ContextVar`.
4. **`MAASClient`** wraps `httpx.AsyncClient`. Per-request `httpx.Timeout(30)`. No retries.
   Raises `MAASUnreachableError` on timeout/connection refused.
5. **Structured logging** — local `configure_logging()` following `maasservicelayer` pattern;
   `structlog` + `pythonjsonlogger` → NDJSON stdout. Six mandatory event types (FR-10).
6. **`MaasServerConfig`** via Pydantic `BaseSettings`. Variables: `MAAS_URL` (required),
   `MCP_SOCKET_PATH` (default `/run/maas/mcp.sock`), `MAAS_REQUEST_TIMEOUT` (default 30),
   `MAAS_TLS_VERIFY` (default `true`), `LOG_LEVEL` (default `INFO`). No TCP vars, no TLS
   vars, no app-level API key.
7. **27 tools** across 5 files. TC-2 deferred tools are absent from tool listing; runtime
   guard returns `not-implemented` if a deferred tool is invoked.
8. **Dual packaging**: systemd unit + `/etc/maas/mcp-server.env` (deb); Pebble layer 004 +
   `run-mcp-server` wrapper sourcing `$SNAP_DATA/mcp-server.env` (snap).

---

## Phase 1: Design & Contracts

*(Artifacts complete.)*

- **Data model**: [data-model.md](data-model.md) — in-memory Pydantic models; no DB tables.
- **Configuration contract**: [contracts/config.md](contracts/config.md) — env vars, systemd
  unit, Pebble layer 004, `run-mcp-server` wrapper, nginx fragment.
- **Tool contracts**: [contracts/tools.md](contracts/tools.md) — all 27 tool signatures,
  MAAS API v3 endpoint mappings, error behaviour, deferred tool list.
- **Quickstart**: [quickstart.md](quickstart.md) — install, configure, start, connect,
  troubleshoot for both deb and snap.

---

## Implementation Work Items

The following ordered work items cover the full implementation from skeleton to CI. Each
maps to one or more `tasks.md` entries.

### WI-1: Repository Skeleton

- Create `src/maasmcpserver/__init__.py`, `__main__.py`, `config.py`, `errors.py`.
- Add `mcp` scope to `.specify/memory/scopes.md`.
- Wire `maasmcpserver` into `setup.py` / `pyproject.toml` as a discovered package.
- Add entry point: `maas-mcp-server = maasmcpserver.__main__:main` (console_scripts).

### WI-2: Configuration (`config.py`)

Implement `MaasServerConfig(BaseSettings)`:
- `maas_url: str` (required)
- `mcp_socket_path: str = "/run/maas/mcp.sock"`
- `maas_request_timeout: int = 30`
- `maas_tls_verify: bool = True`
- `log_level: str = "INFO"`

**Must not** include `mcp_host`, `mcp_port`, `tls_cert`, `tls_key`, or `maas_api_key`.

### WI-3: Structured Logging (`logging_events.py`)

Implement `configure_logging(log_level: str)` following `maasservicelayer` pattern:
- `structlog` + `pythonjsonlogger` → `StreamHandler(sys.stdout)`.
- Implement six emitter functions: `log_session_opened`, `log_tool_received`,
  `log_maas_request`, `log_maas_response`, `log_tool_outcome`, `log_session_closed`.
- `user_token_hash`: `hashlib.sha256(api_key.encode()).hexdigest()`.
- `url_pattern`: path template form only (e.g. `/MAAS/a/v3/machines/{id}`).
- `maas.response` on timeout/connection-refused: `http_status=0`, `error="maas_unreachable"`.
- All timestamps: ISO 8601 UTC (`datetime.now(UTC).isoformat()`).

### WI-4: ASGI Auth Middleware (`middleware.py`)

Implement `AuthMiddleware(app)`:
- Extract `Authorization: Bearer <token>` from HTTP headers on each new connection.
- On missing or malformed header: return HTTP 401 immediately, emit no `session.opened`.
- Store token in `contextvars.ContextVar[str]` keyed by session UUID.
- Generate `session_id` (UUID4) at connection time.
- Emit `session.opened` (with `user_token_hash`) and `session.closed` events.

### WI-5: MAAS HTTP Client (`client.py`)

Implement `MAASClient`:
- Constructor accepts `MaasServerConfig` + `api_key`.
- `httpx.AsyncClient` with `verify=config.maas_tls_verify`.
- Every method: set `Authorization: Bearer {api_key}`, apply
  `httpx.Timeout(config.maas_request_timeout)`, emit `maas.request` + `maas.response`.
- `httpx.TimeoutException` / `httpx.ConnectError` → raise `MAASUnreachableError`.
- HTTP 401/403 → raise `MAASPermissionError`.
- No retries.

### WI-6: Domain Models (`models/`)

Implement Pydantic v2 models per `data-model.md`:
- `models/machines.py`: `MachineSummary`, `MachineDetail`, `InterfaceSummary`, `BlockDevice`
- `models/diagnostics.py`: `MachineEvent`, `ScriptResult`
- `models/info.py`: `MAASInfo`, `RackController`
- `models/network.py`: `Fabric`, `VLAN`, `Subnet`
- `models/boot_sources.py`: `BootSource`, `BootSourceSelection`

All models use `model_config = ConfigDict(extra="ignore")` to tolerate API v3 schema drift.

### WI-7: Fleet Discovery Tools (`tools/fleet.py`)

Implement per tool contract (`contracts/tools.md`):
- `list_machines` — `GET /MAAS/a/v3/machines` with optional query filters + pagination.
- `get_machine` — `GET /MAAS/a/v3/machines/{id}` + `GET …/interfaces`.
- `list_resource_pools` — `GET /MAAS/a/v3/resource_pools`.
- `list_zones` — `GET /MAAS/a/v3/zones`.
- `get_machine_power_state` — `GET /MAAS/a/v3/machines/{id}` (extract `power_state`).

### WI-8: Diagnostic Tools (`tools/diagnostics.py`)

- `get_machine_events` — `GET /MAAS/a/v3/events?system_id=…` with client-side `since_hours`
  filter. Verify exact endpoint path against `openapi-spec.json` at implementation time.
- `get_script_results` — machine script results endpoint (verify path in openapi spec).

### WI-9: MAAS Info Tool (`tools/info.py`)

- `get_maas_info` — two concurrent calls via `asyncio.gather`:
  1. `GET /MAAS/a/v3/configurations/maas_name`
  2. `GET /MAAS/a/v3/racks`
- Response **must not** include `instance_uuid` or `region_controllers`.
- If either call raises `MAASUnreachableError`, propagate as `maas_unreachable` error.

### WI-10: Network Management Tools (`tools/network.py`)

Implement all 15 tools per tool contract:
- Read: `list_fabrics`, `get_fabric`, `list_vlans`, `get_vlan`, `list_subnets`, `get_subnet`
- Write (fabric): `create_fabric`, `update_fabric`, `delete_fabric`
- Write (VLAN): `create_vlan`, `update_vlan`, `delete_vlan`
- Write (subnet): `create_subnet`, `update_subnet`, `delete_subnet`

Delete tools: execute immediately, success response includes deleted resource identity.
Subnet tools always require `fabric_id` + `vlan_id` (no flat `/subnets/` endpoint).

### WI-11: Boot Source Tools (`tools/boot_sources.py`)

- `list_boot_sources` — `GET /MAAS/a/v3/boot_sources`
- `trigger_boot_source_sync` — `POST .../boot_sources/{id}/selections/{id}:sync`
  (returns immediately; no polling)
- `delete_boot_source` — `DELETE .../boot_sources/{id}`, success response includes ID + URL.

### WI-12: MCP Server Entry Point (`server.py`, `__main__.py`)

- `server.py`: Create `FastMCP` app, register all tool modules, wrap with `AuthMiddleware`,
  bind uvicorn to the Unix socket (`MCP_SOCKET_PATH`).
- `__main__.py`: `main()` — load config, call `configure_logging()`, start uvicorn.
- **Unix socket binding pattern**:
  ```python
  import uvicorn
  uvicorn.run(app, uds=config.mcp_socket_path, ...)
  ```
- Ensure the Unix socket's parent directory exists and is writable at startup; exit with a
  clear error if not.

### WI-13: TC-2 Runtime Guard

Add a guard in the tool dispatcher (or as a decorator on the deferred tool stubs) that:
- Intercepts any invocation of a machine lifecycle write tool (commission, deploy, release,
  abort, rescue, tag mutation, pool reassignment, power param update, ownership change).
- Returns a structured MCP `not-implemented` error immediately with the message:
  `"Machine lifecycle write operations are not available: API v3 does not currently expose
  write endpoints for machine lifecycle management (TC-2). Tool '<name>' is deferred."`
- Makes no MAAS API v3 call.
- The deferred tools are **absent from the tool-listing response**.

### WI-14: Unit Tests

- `tests/maasmcpserver/test_config.py` — validate required/optional fields; assert
  `mcp_host`, `mcp_port`, and TLS vars are rejected or absent.
- `tests/maasmcpserver/test_client.py` — mock `httpx.AsyncClient`; assert timeout raises
  `MAASUnreachableError`; assert Bearer header forwarded; assert no retries.
- `tests/maasmcpserver/test_middleware.py` — valid/missing/malformed auth header; session
  lifecycle log events.
- `tests/maasmcpserver/test_logging.py` — assert all six event types produce parseable NDJSON;
  assert raw API key never appears in output.
- `tests/maasmcpserver/tool_tests/` — one test file per tool group; mock `MAASClient`;
  assert correct MAAS API path called; assert deferred tool guard fires.

### WI-15: Debian Packaging

New package `maas-mcp-server`:
- `debian/maas-mcp-server.install` — installs `src/maasmcpserver/` to Python site-packages
  and `/usr/sbin/maas-mcp-server`.
- `debian/control` — `Depends: python3-mcp, python3-httpx, python3-pydantic (>= 2.0.0),
  python3-pydantic-settings, uvicorn, python3-structlog, python3-pythonjsonlogger`
- `debian/maas-mcp-server.maas-mcp-server.service` — systemd unit with
  `RuntimeDirectory=maas`, `EnvironmentFile=/etc/maas/mcp-server.env`,
  `User=maas`, disabled by default.
- `debian/maas-mcp-server.dirs` — `/etc/maas/` (for env file template).
- No `python3-mcp` from PyPI at any point in the build.

### WI-16: Snap Packaging

- **Pebble layer**: `snap/local/tree/usr/share/maas/pebble/layers/004-maas-mcp-layer.yaml`
  — service `mcp-server`, `startup: disabled`, command via `run-mcp-server` wrapper,
  `systemd-cat` tagging following `002-maas-region-layer.yaml` pattern.
- **Wrapper script**: `snap/local/tree/usr/bin/run-mcp-server` — sets `MAAS_PATH`,
  `MAAS_ROOT`, `MCP_SOCKET_PATH=$SNAP_DATA/mcp.sock`, sources
  `$SNAP_DATA/mcp-server.env` if present, execs `/usr/bin/maas-mcp-server`.
- **`snapcraft.yaml`**: add `python3-mcp` to `stage-packages` (Ubuntu archive). Do NOT add
  to `apps:` — service managed by Pebble only.
- **Not** registered in `snapcraft.yaml` `apps:` section.

### WI-17: nginx Configuration Fragment (Region Controller)

- Document the nginx `server` block for port 5275 → Unix socket proxy in
  `docs/mcp-server-nginx.conf.example` (or equivalent documentation location).
- Include `proxy_buffering off` for SSE compatibility, `proxy_read_timeout 3600s`.
- Note that for snap deployments the socket path is `$SNAP_DATA/mcp.sock`.
- This fragment is for region controller maintainers; the MCP server package itself does not
  install or manage nginx configuration.

### WI-18: CI Integration

- Add `maas-mcp-server` to the deb build matrix.
- Add snap build smoke test for `mcp-server` Pebble service.
- `tox` / `pytest` target for `tests/maasmcpserver/`.
- Confirm `python3-mcp` is resolvable from the Ubuntu archive in CI (no PyPI fallback).

---

## Logging Event Reference

Every deployed instance must produce parseable NDJSON lines for these six event types on a
single tool call end-to-end:

```jsonc
// session.opened (on HTTP/SSE connection established)
{"event": "session.opened", "session_id": "...", "user_token_hash": "<sha256-hex>", "timestamp": "2026-05-12T10:00:00.000Z"}

// tool.received (on each tool invocation)
{"event": "tool.received", "session_id": "...", "tool_name": "list_machines", "params": {"status": "Ready"}, "timestamp": "..."}

// maas.request (before each outbound MAAS API v3 call)
{"event": "maas.request", "session_id": "...", "method": "GET", "url_pattern": "/MAAS/a/v3/machines", "timestamp": "..."}

// maas.response (after each outbound MAAS API v3 call)
{"event": "maas.response", "session_id": "...", "http_status": 200, "duration_ms": 42, "timestamp": "..."}

// tool.outcome (after tool returns)
{"event": "tool.outcome", "session_id": "...", "tool_name": "list_machines", "status": "ok", "timestamp": "..."}
// on error: {"event": "tool.outcome", ..., "status": "error", "error_code": "maas_unreachable", "timestamp": "..."}

// session.closed (on HTTP/SSE connection closed)
{"event": "session.closed", "session_id": "...", "timestamp": "..."}
```

Validation: capture stdout during a single tool call and assert (a) exactly 6 lines in
correct sequence, (b) each line parses as valid JSON, (c) each line contains its mandatory
fields, (d) no line contains the raw API key string.

---

## Success Criteria Traceability

| Criterion | WI(s) | Notes |
|-----------|-------|-------|
| Fleet queries < 3 s for ≤ 1,000 machines | WI-7 | Pagination; no blocking calls |
| Auth enforced end-to-end | WI-4, WI-5 | Bearer token forwarded; MAAS audit logs confirm |
| Permission model faithfully reflected | WI-5 | 401/403 surfaced directly (FR-7) |
| MAAS system unaffected | WI-1, WI-12, WI-16 | Standalone process; operational independence (FR-8) |
| Machine lifecycle writes remain deferred | WI-13 | TC-2 guard; tools absent from listing |
| Multi-user isolation | WI-4 | Per-session `ContextVar`; no cross-session state |
| Structured NDJSON logging | WI-3 | Six mandatory event types; no raw key in logs |
| Low-friction adoption | WI-15, WI-16, quickstart.md | ≤ 15 min install |
| Deterministic timeout | WI-5 | `MAAS_REQUEST_TIMEOUT=30`; no retry; ≤ 30 s error response |
| MAAS instance identifiable | WI-9 | `get_maas_info` returns deployment_name + rack_controllers |
| Network management writes succeed | WI-10 | create→list→delete round-trips pass |
