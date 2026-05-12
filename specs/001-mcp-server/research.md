# Research: MAAS MCP Server

**Feature**: 001-mcp-server | **Branch**: `6689-mcp-server` | **Date**: 2025-07-22 (refreshed)

---

## Decision 1: Module Architecture — Standalone Adapter, No Database

**Decision**: `src/maasmcpserver/` is a new standalone Python module. It is a pure
MCP-protocol ↔ MAAS-HTTP-API-v3 adapter. It has **no database**, no SQLAlchemy, no Alembic
migrations, no service layer, and no repository layer.

**Rationale**: The MCP server's only data source is MAAS HTTP API v3. Introducing a local
database would add operational complexity with zero benefit — all state is authoritative in
MAAS. The constitution's 3-tier rule targets MAAS feature modules that own persisted data;
this module is an explicitly documented exception. Import boundary: `maasmcpserver` may only
import from `maascommon`. All other MAAS packages (`maasservicelayer`, `maasapiserver`,
`maasserver`, etc.) are forbidden.

**Alternatives considered**:
- *Caching layer (Redis/SQLite)*: Rejected. Caching MAAS state introduces stale-data risk and
  violates FR-3 (MAAS API v3 is sole source of truth).
- *Embedding in `maasapiserver`*: Rejected. MCP protocol is independent from the MAAS REST
  API; embedding couples unrelated concerns and violates FR-8 (operational independence).

---

## Decision 2: Network Binding — Unix Domain Socket, NOT TCP

**Decision**: The MCP server binds its HTTP/SSE listener to a **Unix domain socket** (default:
`/run/maas/mcp.sock`). It does not bind to a TCP address or port. The socket path is
configurable via `MCP_SOCKET_PATH`. Variables `MCP_HOST` and `MCP_PORT` must **not** be
implemented — they imply TCP binding and would contradict TC-3 and FR-9.

The MAAS region **nginx** reverse proxy fronts the Unix socket and exposes the service on
**TCP port 5275**. The MCP server is never aware of the external port number. nginx
configuration for port 5275 is the region controller's concern, not the MCP server's.

**Rationale**: TC-3 (hard constraint) mandates that the MCP server bind to a Unix domain
socket, not a TCP port. This architecture naturally satisfies TC-4 (no native TLS) because the
socket is always behind nginx and never directly reachable from external networks. The Unix
socket path must be inside a directory writable by the `maas` user at runtime — `/run/maas/`
for deb deployments, `$SNAP_DATA/` for snap deployments.

**Alternatives considered**:
- *TCP bind on 5275*: Rejected. TC-3 explicitly prohibits the MCP server from binding to a TCP
  port. nginx owns the TCP listener; the MCP server owns the Unix socket.
- *TCP bind on a private port with forwarding*: Also rejected for the same reason. The spec
  is unambiguous: Unix socket only.

---

## Decision 3: MCP Transport — Streamable-HTTP / SSE Only, No stdio

**Decision**: The server uses `streamable-http` as its sole MCP transport. It is mounted on a
Unix domain socket listener (uvicorn or equivalent ASGI server). stdio transport is not
supported and must not be implemented — no code path, no configuration flag, no deployment
mode may activate stdio.

**Rationale**: TC-3 is a hard constraint. stdio transport is explicitly prohibited. HTTP/SSE is
the correct transport for a persistent, multi-user network service. The MCP Python SDK's
`streamable-http` transport covers both SSE streaming and standard JSON responses.

**Alternatives considered**:
- *stdio + HTTP*: Rejected. TC-3 prohibits stdio with no exceptions.
- *SSE-only (no StreamableHTTP)*: The SDK's `streamable-http` covers both; it is the
  recommended production transport.

---

## Decision 4: Per-Session MAAS API Key — HTTP Authorization Header

**Decision**: The MAAS API key (a JWT Bearer token) is passed by the MCP client as an HTTP
`Authorization: Bearer <jwt-token>` header on the initial connection request. An ASGI
middleware layer (`middleware.py`) extracts the token, stores it in a `contextvars.ContextVar`
keyed by session ID, and makes it available to all tool handlers throughout the session.

The API key is:
- Never stored on disk.
- Never logged in raw form — only its SHA-256 hex digest (`user_token_hash`) appears in logs
  (`session.opened` event).
- Held only for the lifetime of the HTTP/SSE connection.
- Forwarded verbatim in the `Authorization: Bearer` header of every outbound MAAS API v3
  request.

**Session lifetime**: Connection-scoped (FR-11). When the HTTP/SSE connection closes, the
`ContextVar` is cleared and any in-flight MAAS request is cancelled.

**Rationale**: HTTP headers are the standard transport-level mechanism for per-connection
credentials. Bearer token forwarding is trivial: no signing, no OAuth handshake, no additional
Ubuntu archive dependency. MAAS API v3 authenticates via JWT Bearer; the MCP server forwards
the token as-is. MAAS is the authority on token validity.

**Alternatives considered**:
- *MCP `initialize` params*: More complex (SDK-level hooks), less standard than HTTP headers.
- *Dedicated `initialize_session` tool*: Poor UX; requires a mandatory first tool call.
- *App-level config key*: Explicitly forbidden by FR-2 — no centralized service accounts.

---

## Decision 5: MAAS HTTP Client — `httpx.AsyncClient`

**Decision**: All MAAS API v3 HTTP calls go through `MAASClient`, a thin async wrapper around
`httpx.AsyncClient`. Per-request timeout is enforced unconditionally via
`httpx.Timeout(timeout=MAAS_REQUEST_TIMEOUT)`. On `httpx.TimeoutException` or
`httpx.ConnectError`, the client raises `MAASUnreachableError` immediately — no retry.

**Rationale**: `httpx` is available in the Ubuntu archive (`python3-httpx`). The no-retry
policy is a hard spec requirement (FR-11). Sync HTTP (`requests`) would block the async event
loop.

**Alternatives considered**:
- *`aiohttp`*: Functionally equivalent; `httpx` preferred for cleaner API and Ubuntu archive
  availability.
- *`requests` (sync)*: Rejected. Blocks the async event loop.

---

## Decision 6: Structured Logging — Local `configure_logging()` Following `maasservicelayer` Pattern

**Decision**: The MCP server implements its own `configure_logging()` in `logging_events.py`,
following the identical pattern used by `maasservicelayer.logging.configure` — `structlog` +
`pythonjsonlogger` (`CustomJsonFormatter`) writing NDJSON to `StreamHandler(sys.stdout)`.
It cannot import from `maasservicelayer` (only `maascommon` imports are permitted), so the
~40-line setup is replicated locally.

For `user_token_hash` in `session.opened` events, `hashlib.sha256(token.encode()).hexdigest()`
is used inline — no external helper needed.

**Six mandatory event types** and their required fields (verbatim from FR-10):

| Event | Required fields |
|-------|----------------|
| `session.opened` | `event`, `session_id`, `user_token_hash`, `timestamp` |
| `tool.received` | `event`, `session_id`, `tool_name`, `params` (sanitised), `timestamp` |
| `maas.request` | `event`, `session_id`, `method`, `url_pattern`, `timestamp` |
| `maas.response` | `event`, `session_id`, `http_status`, `duration_ms`, `timestamp` |
| `tool.outcome` | `event`, `session_id`, `tool_name`, `status`, `error_code` (on error), `timestamp` |
| `session.closed` | `event`, `session_id`, `timestamp` |

All `timestamp` values are ISO 8601 UTC. `url_pattern` is the path template form
(e.g. `/MAAS/a/v3/machines/{id}`) — never the resolved URL (to avoid leaking IDs or
credentials). On timeout/connection-refused, `maas.response` emits `http_status: 0` (or
`null`) plus `error: "maas_unreachable"`.

**Rationale**: `maasservicelayer` is out of bounds. Replicating the logging setup locally is
correct — it keeps the NDJSON format consistent with the MAAS observability stack.

**Alternatives considered**:
- *Import from `maasservicelayer`*: Violates the import boundary.
- *Plain `logging` module without structlog*: Inconsistent with MAAS codebase convention.

---

## Decision 7: Configuration — Unix Socket Path, No TCP Variables

**Decision**: Configuration via Pydantic `BaseSettings` + environment variables (`.env` file
supported for development). The canonical configuration variables are:

| Variable | Type | Default | Notes |
|----------|------|---------|-------|
| `MAAS_URL` | `str` | — (required) | Base URL of MAAS API v3 endpoint |
| `MCP_SOCKET_PATH` | `str` | `/run/maas/mcp.sock` | Unix socket the server binds to |
| `MAAS_REQUEST_TIMEOUT` | `int` | `30` | Seconds; enforced per-request, no override |
| `MAAS_TLS_VERIFY` | `bool` | `true` | TLS cert verification for MAAS endpoint |
| `LOG_LEVEL` | `str` | `INFO` | Python log level |

**Deliberately absent variables**:
- `MCP_HOST` / `MCP_PORT`: TCP binding — prohibited by TC-3.
- `TLS_CERT` / `TLS_KEY` / `TLS_CA`: Native TLS on MCP listener — prohibited by TC-4.
- `MAAS_API_KEY`: App-level key — prohibited by FR-2 (per-session delegation only).
- `DATABASE_URL`: No database — MCP server is stateless.
- `MAAS_MCP_TRANSPORT`: Transport is always `streamable-http`, not configurable.

**Snap path**: In snap deployments, `MCP_SOCKET_PATH` defaults to `$SNAP_DATA/mcp.sock`
(overridden in the `run-mcp-server` wrapper). Config file at
`$SNAP_DATA/mcp-server.env` (optional; missing is not an error).

**Rationale**: `MCP_HOST`/`MCP_PORT` would incorrectly imply TCP binding. Using
`MCP_SOCKET_PATH` correctly captures the Unix socket requirement and makes the socket path
configurable for both deb (standard path under `/run/maas/`) and snap (under `$SNAP_DATA/`).

---

## Decision 8: Dual Packaging — deb and snap

### deb (`maas-mcp-server`)

- **Package name**: `maas-mcp-server`
- **Entry point binary**: `/usr/sbin/maas-mcp-server` (invokes `python3 -m maasmcpserver`)
- **`Depends:`** includes `python3-mcp` (Ubuntu archive), `python3-httpx`,
  `python3-pydantic` (≥ 2.0.0), `python3-structlog`, `python3-pythonjsonlogger`, `uvicorn`
- **Systemd unit**: `maas-mcp-server.service` — `User=maas`, `Group=maas`,
  `RuntimeDirectory=maas` (creates `/run/maas/`), `EnvironmentFile=/etc/maas/mcp-server.env`,
  service is **disabled by default** (operator must `systemctl enable maas-mcp-server`).
- **Config template**: `/etc/maas/mcp-server.env` (owned `root:root 640`).

### snap (Pebble layer `004-maas-mcp-layer.yaml`)

- **Location**: `snap/local/tree/usr/share/maas/pebble/layers/004-maas-mcp-layer.yaml`
- **Service name**: `mcp-server`
- **`startup: disabled`** — operator runs `sudo snap start maas.mcp-server` to enable.
- **`command`**: `sh -c "exec systemd-cat -t maas-mcp-server $SNAP/usr/bin/run-mcp-server"`
  — follows the exact pattern used by `apiserver`, `regiond`, and all other Pebble services.
- **Wrapper script**: `snap/local/tree/usr/bin/run-mcp-server` — sets `MAAS_PATH`, `MAAS_ROOT`,
  overrides `MCP_SOCKET_PATH` to `$SNAP_DATA/mcp.sock`, sources `$SNAP_DATA/mcp-server.env`
  if present, then `exec "$SNAP/usr/bin/maas-mcp-server"`.
- **`snapcraft.yaml`**: `python3-mcp` declared in `stage-packages` (Ubuntu archive). Never
  fetched from PyPI.
- **NOT** registered in `snapcraft.yaml` `apps:` section — all service management is via
  Pebble, not snapd.

**Rationale**: TC-5 requires both formats. Within the snap, MAAS uses Pebble for all service
management — adding the MCP server as a `snapd` app daemon instead of a Pebble layer would
be inconsistent with every other MAAS snap service and would bypass Pebble's dependency/
ordering model.

---

## Decision 9: Machine Lifecycle Writes — Deferred, Runtime Guard Required

**Decision**: All FR-6 tools (commission, release, abort, rescue, deploy, tag mutations, pool
reassignment, power parameter updates, ownership changes) are fully deferred — TC-2 is a hard
constraint. They are **not listed** in the MCP tool-listing response. If a call is received
for a deferred tool, the server returns a structured MCP `not-implemented` error immediately
with a human-readable message; no MAAS API v3 call is made.

Network management (FR-13) and boot-source management (FR-14) write operations ARE in scope
(API v3 exposes those endpoints).

**Rationale**: MAAS API v3 does not expose machine lifecycle write endpoints. There is no
workaround; the constraint is architectural.

---

## Decision 10: Tool Inventory — 27 Tools Across 5 Groups

| Group file | Tools | FR |
|------------|-------|-----|
| `tools/fleet.py` | `list_machines`, `get_machine`, `list_resource_pools`, `list_zones`, `get_machine_power_state` | FR-4 |
| `tools/diagnostics.py` | `get_machine_events`, `get_script_results` | FR-5 |
| `tools/info.py` | `get_maas_info` | FR-12 |
| `tools/network.py` | `list_fabrics`, `get_fabric`, `create_fabric`, `update_fabric`, `delete_fabric`, `list_vlans`, `get_vlan`, `create_vlan`, `update_vlan`, `delete_vlan`, `list_subnets`, `get_subnet`, `create_subnet`, `update_subnet`, `delete_subnet` | FR-13 |
| `tools/boot_sources.py` | `list_boot_sources`, `trigger_boot_source_sync`, `delete_boot_source` | FR-14 |

All delete tools execute immediately (no server-side confirmation gate). Success responses
always include the deleted resource's identity so the AI client can verify the correct target.

---

## Decision 11: `get_maas_info` — Two Concurrent API Calls, No UUID/Region Fields

**Decision**: `get_maas_info` makes two concurrent API v3 calls:
1. `GET /MAAS/a/v3/configurations/maas_name` → `deployment_name`
2. `GET /MAAS/a/v3/racks` → `rack_controllers[]`

The response does **not** include `instance_uuid` or `region_controllers` — these fields are
not available in API v3 and must not be fabricated or sourced from any non-v3 path.

**Rationale**: FR-12 explicitly documents this constraint. The tool is always listed (not
subject to TC-2).
