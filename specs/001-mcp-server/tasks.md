# Tasks: MAAS MCP Server

**Feature**: `001-mcp-server` | **Branch**: `6689-mcp-server`
**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)
**Generated**: 2025-07-22

---

## Format & Conventions

- `- [ ] TXXX` — task checkbox with sequential execution-order ID
- `[P]` — task is parallelisable (different file, no incomplete-task dependency)
- `[USn]` — maps to User Story n from spec.md (setup/foundational phases omit this)
- File paths are absolute from repo root
- All Python must pass `ruff format` (79 chars, double quotes) and `ruff check`

---

## Phase 1: Setup

**Purpose**: Repository skeleton and build-system wiring. Must be complete before all other
phases. No user story label — these tasks serve all stories equally.

- [X] T001 Add `mcp` scope entry to `.specify/memory/scopes.md` documenting module `src/maasmcpserver/` and conventional-commit scope `mcp`
- [X] T002 Create `src/maasmcpserver/` module skeleton: `__init__.py` (empty), `__main__.py` (stub `main()` only), `errors.py` (empty), `config.py` (empty), `logging_events.py` (empty), `client.py` (empty), `middleware.py` (empty), `server.py` (empty), `models/__init__.py` (empty), `tools/__init__.py` (empty)
- [X] T003 Register `maasmcpserver` in `pyproject.toml`: add `"maasmcpserver*"` to `packages.find.include`; add `scripts."maas-mcp-server" = "maasmcpserver.__main__:main"` to `[project.scripts]`
- [X] T004 Create test directory skeleton: `src/tests/maasmcpserver/__init__.py`, `src/tests/maasmcpserver/tool_tests/__init__.py`

---

## Phase 2: Foundational

**Purpose**: Config, errors, logging, HTTP client, and Pydantic models. All are blocking
prerequisites for every user story phase. No user story label.

**Independent test**: `python3 -c "from maasmcpserver.config import MaasServerConfig"` loads
without error; `pytest src/tests/maasmcpserver/test_config.py` passes.

- [X] T005 Implement `src/maasmcpserver/config.py` — `MaasServerConfig(BaseSettings)` with exactly these fields: `maas_url: str` (required, no default), `mcp_socket_path: str = "/run/maas/mcp.sock"`, `maas_request_timeout: int = 30`, `maas_tls_verify: bool = True`, `log_level: str = "INFO"`; the class must **not** define `mcp_host`, `mcp_port`, `tls_cert`, `tls_key`, `maas_api_key`, or any TLS listener field
- [X] T006 [P] Implement `src/maasmcpserver/errors.py` — `MAASUnreachableError(Exception)` with fields `url_pattern: str` and `failure_mode: str` (values: `"timeout"` or `"connection_refused"`); `MAASPermissionError(Exception)` with field `status_code: int`; both classes exported from module `__init__.py`
- [X] T007 [P] Implement `src/maasmcpserver/logging_events.py` — `configure_logging(log_level: str)` wiring `structlog` + `pythonjsonlogger` to `StreamHandler(sys.stdout)` producing NDJSON (one JSON object per line, terminated by `\n`); implement six emitter functions: `log_session_opened(session_id, api_key)`, `log_tool_received(session_id, tool_name, params)`, `log_maas_request(session_id, method, url_pattern)`, `log_maas_response(session_id, http_status, duration_ms, error=None)`, `log_tool_outcome(session_id, tool_name, status, error_code=None)`, `log_session_closed(session_id)`; `user_token_hash` = `hashlib.sha256(api_key.encode()).hexdigest()` — raw key must never appear in any log field; all timestamps ISO 8601 UTC (`datetime.now(timezone.utc).isoformat()`); `log_maas_response` sets `http_status=0` and `error="maas_unreachable"` on timeout/connection-refused outcomes
- [X] T008 [P] Implement `src/maasmcpserver/client.py` — `MAASClient` wrapping `httpx.AsyncClient(verify=config.maas_tls_verify)`; every request method sets `Authorization: Bearer {api_key}` header, applies `httpx.Timeout(config.maas_request_timeout)`, emits `maas.request` before the call and `maas.response` after; `httpx.TimeoutException` or `httpx.ConnectError` → emit `maas.response` with `http_status=0` then raise `MAASUnreachableError`; HTTP 401/403 → raise `MAASPermissionError`; zero retries — one attempt is the final attempt; expose `async def get(url_pattern, path_params, query_params)`, `async def post(url_pattern, path_params, body)`, `async def put(url_pattern, path_params, body)`, `async def delete(url_pattern, path_params)` in `src/maasmcpserver/client.py`
- [X] T009 [P] Implement `src/maasmcpserver/models/machines.py` — Pydantic v2 models all with `model_config = ConfigDict(extra="ignore")`: `InterfaceSummary` (id, name, type, mac_address, enabled, vlan_id: int|None, ip_addresses: list[str]); `BlockDevice` (id, name, type, size_gb: float, model: str|None, serial: str|None); `MachineSummary` (system_id, hostname, status, zone, pool, architecture, cpu_count, memory_mb, owner: str|None, power_state: str|None, tags: list[str]); `MachineDetail` extending `MachineSummary` with `interfaces: list[InterfaceSummary]`, `block_devices: list[BlockDevice]`, `bios_boot_method: str|None`, `osystem: str|None`, `distro_series: str|None`
- [X] T010 [P] Implement `src/maasmcpserver/models/diagnostics.py` — Pydantic v2 models with `model_config = ConfigDict(extra="ignore")`: `MachineEvent` (id: int, created: str, type: str, description: str, username: str|None); `ScriptResult` (id: int, name: str, status: str, exit_status: int|None, output: str|None, started: str|None, ended: str|None)
- [X] T011 [P] Implement `src/maasmcpserver/models/info.py` — Pydantic v2 models with `model_config = ConfigDict(extra="ignore")`: `RackController` (hostname: str, rack_id: str, connection_state: str); `MAASInfo` (deployment_name: str, rack_controllers: list[RackController]); the model must **not** define `instance_uuid` or `region_controllers` fields
- [X] T012 [P] Implement `src/maasmcpserver/models/network.py` — Pydantic v2 models with `model_config = ConfigDict(extra="ignore")`: `Fabric` (id: int, name: str, class_type: str|None, description: str|None); `VLAN` (id: int, vid: int, name: str|None, fabric: str, mtu: int, dhcp_on: bool); `Subnet` (id: int, name: str, cidr: str, gateway_ip: str|None, dns_servers: list[str], vlan: int, fabric: str)
- [X] T013 [P] Implement `src/maasmcpserver/models/boot_sources.py` — Pydantic v2 models with `model_config = ConfigDict(extra="ignore")`: `BootSourceSelection` (id: int, os: str|None, release: str|None, arches: list[str], subarches: list[str], labels: list[str]); `BootSource` (id: int, url: str, keyring_data: str|None, selections: list[BootSourceSelection])

---

## Phase 3: User Story 1 — Session Initialization via API Key Delegation

**Goal**: An AI client can connect to the MCP server, supply a MAAS API key, and receive a
permission-scoped session — all before any MAAS resource is queried.

**Independent test**: Start the server pointing at a real or mock MAAS URL; connect an MCP
client without providing an `Authorization` header → server returns HTTP 401; connect with a
valid bearer token → `session.opened` log event emitted with correct `user_token_hash`; two
simultaneous connections with different tokens → each session sees only its own token in the
ContextVar.

- [X] T014 [US1] Implement `src/maasmcpserver/middleware.py` — `AuthMiddleware(app)` ASGI middleware: on each new HTTP/SSE connection, extract `Authorization: Bearer <token>` from request headers; if header missing or malformed return HTTP 401 immediately and emit no `session.opened`; generate `session_id = str(uuid.uuid4())`; store token and session_id in a `contextvars.ContextVar[dict]` keyed per-request; call `log_session_opened(session_id, token)`; on connection close call `log_session_closed(session_id)` and clear ContextVar; multi-user isolation: ContextVar ensures no cross-session token leakage
- [X] T015 [US1] Implement TC-2 deferred-tool guard in `src/maasmcpserver/tools/__init__.py` — define `DEFERRED_TOOLS: frozenset[str]` listing all machine lifecycle write tool names (commission, deploy, release, abort, rescue, add_tag, remove_tag, reassign_pool, update_power_params, set_owner); define `deferred_tool(name)` decorator that, when invoked, immediately returns a structured MCP `not-implemented` error with message `"Machine lifecycle write operations are not available: API v3 does not currently expose write endpoints for machine lifecycle management (TC-2). Tool '{name}' is deferred."` and makes no MAAS API v3 call; deferred tools must be absent from the MCP tool-listing response
- [X] T016 [US1] Implement `src/maasmcpserver/server.py` — `create_app(config: MaasServerConfig) -> FastMCP`: instantiate `FastMCP("MAAS MCP Server")`; register tool modules fleet, diagnostics, info, network, boot_sources via `mcp.include_router()` or equivalent; wrap the ASGI app with `AuthMiddleware`; implement lifespan that validates `config.mcp_socket_path` parent directory exists and is writable, logging a clear error and exiting if not; expose `get_app(config)` returning the wrapped ASGI application
- [X] T017 [US1] Implement `src/maasmcpserver/__main__.py` `main()` — load `MaasServerConfig()` (raises `ValidationError` on missing `MAAS_URL`); call `configure_logging(config.log_level)`; call `create_app(config)` to get the ASGI app; call `uvicorn.run(app, uds=config.mcp_socket_path, log_config=None)` (Unix domain socket binding — `uds=` parameter, NOT `host=`/`port=`); on `ValidationError` print human-readable message to stderr and `sys.exit(1)`

---

## Phase 4: User Story 2 — Fleet Discovery via Natural Language

**Goal**: An authenticated session can list and query MAAS machines, resource pools, zones,
and power states via MCP tools — all read-only, no provisioning.

**Independent test**: With a live or mocked MAAS API v3, invoke `list_machines(status="Ready")`
via MCP client → response is a Markdown table with correct columns; invoke `get_machine` with
a valid hostname → full hardware detail returned; invoke with non-existent machine → structured
error, not exception; `list_resource_pools` and `list_zones` return paginated results.

- [ ] T018 [US2] Implement `list_machines` in `src/maasmcpserver/tools/fleet.py` — signature: `list_machines(status, zone, pool, architecture, tags, owner, power_state, page=1, page_size=50) -> str`; call `GET /MAAS/a/v3/machines` forwarding all non-None filters as query parameters plus `page` and `size`; parse response as `list[MachineSummary]`; return Markdown table with columns: hostname, system_id, status, zone, pool, architecture, CPUs, memory (GiB), owner, power_state, tags; empty result returns clear "No machines found" message, not an error; emit `tool.received` and `tool.outcome` log events
- [ ] T019 [P] [US2] Implement `get_machine` in `src/maasmcpserver/tools/fleet.py` — signature: `get_machine(identifier: str) -> str`; if identifier contains no `/` treat as hostname: call `GET /MAAS/a/v3/machines?hostname={identifier}` to resolve `system_id`, then call `GET /MAAS/a/v3/machines/{system_id}` and `GET /MAAS/a/v3/machines/{system_id}/interfaces`; parse as `MachineDetail`; return formatted full machine detail including hardware specs, OS, interfaces, block devices; on not-found return structured error message
- [ ] T020 [P] [US2] Implement `list_resource_pools` in `src/maasmcpserver/tools/fleet.py` — signature: `list_resource_pools(page=1, page_size=100) -> str`; call `GET /MAAS/a/v3/resource_pools?page={page}&size={page_size}`; return formatted list of pool names, descriptions, and machine counts
- [ ] T021 [P] [US2] Implement `list_zones` in `src/maasmcpserver/tools/fleet.py` — signature: `list_zones(page=1, page_size=100) -> str`; call `GET /MAAS/a/v3/zones?page={page}&size={page_size}`; return formatted list of availability zone names and descriptions
- [ ] T022 [P] [US2] Implement `get_machine_power_state` in `src/maasmcpserver/tools/fleet.py` — signature: `get_machine_power_state(identifier: str) -> str`; resolve hostname to system_id if needed (same pattern as `get_machine`); call `GET /MAAS/a/v3/machines/{system_id}`; extract `power_state` field from response; return formatted string: `"{hostname}: power state is {power_state}"` (on/off/unknown/error)

---

## Phase 5: User Story 3 — MAAS Instance Identification

**Goal**: An authenticated session can invoke `get_maas_info` to identify the connected MAAS
deployment by name and list its rack controllers — no UUID or region controller fields.

**Independent test**: Invoke `get_maas_info` via MCP client against a live MAAS → response
contains non-empty `deployment_name` matching the known MAAS name and a `rack_controllers`
list; response does **not** contain `instance_uuid` or `region_controllers`; point server at
an unreachable MAAS endpoint → error returned within 30 s with `error_code: "maas_unreachable"`.

- [ ] T023 [US3] Implement `get_maas_info` in `src/maasmcpserver/tools/info.py` — signature: `get_maas_info() -> str`; use `asyncio.gather` to concurrently call `GET /MAAS/a/v3/configurations/maas_name` and `GET /MAAS/a/v3/racks`; parse results into `MAASInfo(deployment_name=..., rack_controllers=[...])` where each rack entry contains hostname, rack_id, and connection_state; if either call raises `MAASUnreachableError`, propagate as MCP `maas_unreachable` error immediately; return formatted output listing deployment name and rack controller inventory; response must not include `instance_uuid` or `region_controllers` (no v3 endpoint available — do not fabricate); emit `tool.received` and `tool.outcome` log events

---

## Phase 6: User Story 4 — Hardware Troubleshooting Assistance

**Goal**: An authenticated session can retrieve machine event logs, commissioning/test script
output, and hardware detail for a specific machine via diagnostic MCP tools.

**Independent test**: Invoke `get_machine_events(identifier="node-1", since_hours=24)` via MCP
client → events returned in chronological order matching `GET /v3/events?system_id=...`; invoke
`get_script_results(identifier="node-1")` → commissioning script output returned; user without
log-view permission → authorisation error surfaced directly.

- [ ] T024 [US4] Implement `get_machine_events` in `src/maasmcpserver/tools/diagnostics.py` — signature: `get_machine_events(identifier: str, since_hours: int | None = None) -> str`; resolve identifier to system_id if hostname; call `GET /MAAS/a/v3/events?system_id={system_id}` (verify exact endpoint path against `src/tests/maasmcpserver/openapi-spec.json` or MAAS API v3 docs at implementation time — path may differ); parse as `list[MachineEvent]`; apply client-side `since_hours` filter on `created` timestamp if provided; return events in chronological order (oldest first); emit `tool.received` and `tool.outcome` log events
- [ ] T025 [P] [US4] Implement `get_script_results` in `src/maasmcpserver/tools/diagnostics.py` — signature: `get_script_results(identifier: str, script_type: str | None = None) -> str`; resolve identifier to system_id; call machine script results endpoint (verify exact API v3 path in openapi spec at implementation time — likely `GET /MAAS/a/v3/machines/{system_id}/script_results` or similar); parse as `list[ScriptResult]`; optionally filter by `script_type` (e.g. `"commissioning"`, `"testing"`); return formatted output including script name, status, exit code, and output text

---

## Phase 7: User Story 5 — Network Fabric, VLAN & Subnet Management

**Goal**: An authenticated session can list, create, update, and delete fabrics, VLANs, and
subnets through MCP tools using MAAS API v3 nested paths. All subnet ops require explicit
`fabric_id` + `vlan_id` — no flat `/subnets/` endpoint exists in API v3.

**Independent test**: `list_fabrics` returns correct fabric inventory; `create_vlan` →
`list_vlans` → `delete_vlan` round-trip: VLAN appears then disappears from MAAS; `create_subnet`
(with fabric_id + vlan_id) → `list_subnets` (same context) → `delete_subnet` round-trip:
subnet appears then disappears; delete responses include resource identity fields; user without
network-management permissions → authorisation error, no retry.

- [ ] T026 [US5] Implement network read tools in `src/maasmcpserver/tools/network.py` — `list_fabrics(page=1, page_size=100)`: `GET /MAAS/a/v3/fabrics`; `get_fabric(fabric_id: int)`: `GET /MAAS/a/v3/fabrics/{fabric_id}`; `list_vlans(fabric_id: int, page=1, page_size=100)`: `GET /MAAS/a/v3/fabrics/{fabric_id}/vlans`; `get_vlan(fabric_id: int, vlan_id: int)`: `GET /MAAS/a/v3/fabrics/{fabric_id}/vlans/{vlan_id}`; `list_subnets(fabric_id: int, vlan_id: int, page=1, page_size=100)`: `GET /MAAS/a/v3/fabrics/{fabric_id}/vlans/{vlan_id}/subnets`; `get_subnet(fabric_id: int, vlan_id: int, subnet_id: int)`: `GET /MAAS/a/v3/fabrics/{fabric_id}/vlans/{vlan_id}/subnets/{subnet_id}`; all parse into corresponding Pydantic models and return formatted output; all list tools support pagination
- [ ] T027 [P] [US5] Implement fabric write tools in `src/maasmcpserver/tools/network.py` — `create_fabric(name: str, class_type: str | None = None) -> str`: `POST /MAAS/a/v3/fabrics`; return new fabric ID and name; `update_fabric(fabric_id: int, name: str | None = None, class_type: str | None = None) -> str`: `PUT /MAAS/a/v3/fabrics/{fabric_id}`; return updated fabric; `delete_fabric(fabric_id: int) -> str`: `DELETE /MAAS/a/v3/fabrics/{fabric_id}`; execute immediately (no server-side confirmation gate); success response includes the deleted fabric's name so the AI client can verify the correct target was acted on
- [ ] T028 [P] [US5] Implement VLAN write tools in `src/maasmcpserver/tools/network.py` — `create_vlan(fabric_id: int, vid: int, name: str | None = None, mtu: int | None = None, dhcp_relay_target: int | None = None) -> str`: `POST /MAAS/a/v3/fabrics/{fabric_id}/vlans`; return new VLAN VID and name; `update_vlan(fabric_id: int, vlan_id: int, **fields) -> str`: `PUT /MAAS/a/v3/fabrics/{fabric_id}/vlans/{vlan_id}`; `delete_vlan(fabric_id: int, vlan_id: int) -> str`: `DELETE /MAAS/a/v3/fabrics/{fabric_id}/vlans/{vlan_id}`; success response includes deleted VLAN VID + name; on 404 return descriptive error message (not silent failure)
- [ ] T029 [P] [US5] Implement subnet write tools in `src/maasmcpserver/tools/network.py` — `create_subnet(fabric_id: int, vlan_id: int, cidr: str, name: str | None = None, gateway_ip: str | None = None, dns_servers: list[str] | None = None) -> str`: `POST /MAAS/a/v3/fabrics/{fabric_id}/vlans/{vlan_id}/subnets`; `fabric_id` and `vlan_id` are **mandatory** parameters (no flat `/subnets/` endpoint); return new subnet CIDR and name; `update_subnet(fabric_id: int, vlan_id: int, subnet_id: int, **fields) -> str`: `PUT /MAAS/a/v3/fabrics/{fabric_id}/vlans/{vlan_id}/subnets/{subnet_id}`; `delete_subnet(fabric_id: int, vlan_id: int, subnet_id: int) -> str`: `DELETE /MAAS/a/v3/fabrics/{fabric_id}/vlans/{vlan_id}/subnets/{subnet_id}`; success response includes deleted subnet CIDR + name + fabric + VLAN context; on 404 return descriptive error message

---

## Phase 8: User Story 6 — Boot Source Management

**Goal**: An authenticated session can list, sync, and delete MAAS boot sources through MCP
tools without knowledge of image source configuration internals.

**Independent test**: `list_boot_sources` returns boot source inventory including URL, keyring
data, and selections; `trigger_boot_source_sync(boot_source_id=1, selection_id=1)` posts to
correct endpoint and returns API v3 accepted status without polling; `delete_boot_source`
executes immediately and returns deleted source ID + URL; user without boot-source management
permissions → authorisation error surfaced directly.

- [ ] T030 [US6] Implement `list_boot_sources` in `src/maasmcpserver/tools/boot_sources.py` — signature: `list_boot_sources() -> str`; call `GET /MAAS/a/v3/boot_sources`; parse as `list[BootSource]`; return formatted output listing each source's ID, URL, keyring data (if any), and associated selections; emit `tool.received` and `tool.outcome` log events
- [ ] T031 [P] [US6] Implement `trigger_boot_source_sync` in `src/maasmcpserver/tools/boot_sources.py` — signature: `trigger_boot_source_sync(boot_source_id: int, selection_id: int) -> str`; call `POST /MAAS/a/v3/boot_sources/{boot_source_id}/selections/{selection_id}:sync`; accepts **only** `boot_source_id` and `selection_id` — no URL, source type, or credential parameters; return the API v3 response (accepted/queued status) immediately without polling; note in output that sync completion must be checked via `list_boot_sources`
- [ ] T032 [P] [US6] Implement `delete_boot_source` in `src/maasmcpserver/tools/boot_sources.py` — signature: `delete_boot_source(boot_source_id: int) -> str`; call `DELETE /MAAS/a/v3/boot_sources/{boot_source_id}`; execute immediately (no server-side confirmation gate); success response includes the deleted source's ID and URL so the AI client can verify the correct source was removed; on 404 return descriptive error message

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Unit tests, dual packaging, nginx documentation, CI integration.

### Unit Tests

- [ ] T033 [P] Write `src/tests/maasmcpserver/test_config.py` — assert `MaasServerConfig()` raises `ValidationError` when `MAAS_URL` is absent; assert `mcp_socket_path` defaults to `"/run/maas/mcp.sock"`; assert `maas_request_timeout` defaults to `30`; assert `maas_tls_verify` defaults to `True`; assert `log_level` defaults to `"INFO"`; assert the class has no `mcp_host`, `mcp_port`, `tls_cert`, `tls_key`, or `maas_api_key` attribute (getattr raises AttributeError or field absent)
- [ ] T034 [P] Write `src/tests/maasmcpserver/test_client.py` — mock `httpx.AsyncClient`; assert `Authorization: Bearer {token}` header present on every request; assert `httpx.TimeoutException` → `MAASUnreachableError` with `failure_mode="timeout"`; assert `httpx.ConnectError` → `MAASUnreachableError` with `failure_mode="connection_refused"`; assert `maas.response` log event emitted with `http_status=0` on timeout; assert HTTP 401 → `MAASPermissionError`; assert zero retries (client.get called exactly once per tool invocation even on timeout)
- [ ] T035 [P] Write `src/tests/maasmcpserver/test_middleware.py` — assert request without `Authorization` header returns HTTP 401 and emits no `session.opened`; assert malformed header (non-Bearer scheme) returns HTTP 401; assert valid Bearer header triggers `session.opened` with correct `user_token_hash` (SHA-256 hex of token); assert `session_id` is a valid UUID4 string; assert `session.closed` emitted when connection closes; assert two concurrent connections with different tokens have isolated ContextVar state (no cross-session token leakage)
- [ ] T036 [P] Write `src/tests/maasmcpserver/test_logging.py` — call each of the six emitter functions and capture stdout; assert each produces exactly one parseable JSON line terminated by `\n`; assert the raw API key string never appears in any log line; assert `user_token_hash` equals `sha256(api_key.encode()).hexdigest()`; assert all `timestamp` values parse as ISO 8601 UTC; assert `log_maas_response` with timeout sets `http_status=0` and `error="maas_unreachable"`; assert `log_tool_outcome` with error sets `error_code` field; assert `log_tool_outcome` on success omits `error_code`
- [ ] T037 [P] Write `src/tests/maasmcpserver/tool_tests/test_fleet.py` — mock `MAASClient`; assert `list_machines` calls `GET /MAAS/a/v3/machines` with correct query params; assert pagination params `page` and `size` forwarded; assert output is a Markdown table; assert `list_machines` with zero results returns non-error "No machines found" message; assert `get_machine` calls machines endpoint then interfaces endpoint sequentially; assert `get_machine_power_state` extracts `power_state` field
- [ ] T038 [P] Write `src/tests/maasmcpserver/tool_tests/test_diagnostics.py` — mock `MAASClient`; assert `get_machine_events` calls correct events endpoint with `system_id` query param; assert `since_hours` filter applied client-side; assert events returned in chronological order; assert `get_script_results` calls correct script results endpoint; assert permission errors surfaced directly
- [ ] T039 [P] Write `src/tests/maasmcpserver/tool_tests/test_info.py` — mock `MAASClient`; assert `get_maas_info` issues exactly two concurrent MAAS calls (configurations/maas_name and racks); assert response contains `deployment_name` and `rack_controllers`; assert response does **not** contain `instance_uuid` or `region_controllers`; assert `MAASUnreachableError` from either call propagates as MCP `maas_unreachable` error; assert tool completes within `MAAS_REQUEST_TIMEOUT`
- [ ] T040 [P] Write `src/tests/maasmcpserver/tool_tests/test_network.py` — mock `MAASClient`; assert `list_subnets` requires `fabric_id` and `vlan_id` (TypeError if omitted); assert `create_subnet` calls `POST /MAAS/a/v3/fabrics/{fabric_id}/vlans/{vlan_id}/subnets` — never a flat `/subnets/` path; assert `delete_fabric` success response includes fabric name; assert `delete_vlan` success response includes VID + name; assert `delete_subnet` success response includes CIDR + name + fabric + VLAN context; assert 404 response produces descriptive error, not silent failure; assert permission errors surfaced without retry
- [ ] T041 [P] Write `src/tests/maasmcpserver/tool_tests/test_boot_sources.py` — mock `MAASClient`; assert `trigger_boot_source_sync` calls `POST .../boot_sources/{id}/selections/{id}:sync` with only `boot_source_id` and `selection_id`; assert `delete_boot_source` success response includes source ID + URL; assert TC-2 deferred tool guard fires for a machine lifecycle tool name (e.g., `"deploy"`) and returns MCP `not-implemented` error with the TC-2 message without making any MAAS API call

### Debian Packaging

- [ ] T042 Create `debian/maas-mcp-server.install` — installs `src/maasmcpserver/` Python package to site-packages and the `maas-mcp-server` console script to `/usr/sbin/maas-mcp-server`
- [ ] T043 [P] Add `maas-mcp-server` package stanza to `debian/control` with `Depends: python3-mcp, python3-httpx, python3-pydantic (>= 2.0.0), python3-pydantic-settings, uvicorn, python3-structlog, python3-pythonjsonlogger`; no PyPI reference anywhere in the stanza; `Architecture: all`; `Section: net`
- [ ] T044 [P] Create `debian/maas-mcp-server.maas-mcp-server.service` — systemd unit: `User=maas`, `RuntimeDirectory=maas`, `EnvironmentFile=-/etc/maas/mcp-server.env`, `ExecStart=/usr/sbin/maas-mcp-server`, `Restart=on-failure`; service is **disabled** by default (no `[Install] WantedBy=` that auto-enables on install); following pattern of existing `maas-agent.maas-agent.service`
- [ ] T045 [P] Create `debian/maas-mcp-server.dirs` — declares `/etc/maas/` so the environment file directory is created on package install

### Snap Packaging

- [ ] T046 Create `snap/local/tree/usr/share/maas/pebble/layers/004-maas-mcp-layer.yaml` — Pebble layer defining service `mcp-server`: `override: replace`, `command: sh -c "exec systemd-cat -t maas-mcp-server $SNAP/usr/bin/run-mcp-server"`, `startup: disabled`; follow `002-maas-region-layer.yaml` pattern exactly; service must **not** appear in `snapcraft.yaml` `apps:` section
- [ ] T047 [P] Create `snap/local/tree/usr/bin/run-mcp-server` wrapper script — set `MAAS_PATH="$SNAP"`, `MAAS_ROOT="$SNAP_DATA"`, `MCP_SOCKET_PATH="$SNAP_DATA/mcp.sock"`; `[ -f "$SNAP_DATA/mcp-server.env" ] && source "$SNAP_DATA/mcp-server.env"`; `exec "$SNAP/usr/bin/maas-mcp-server"`; mark executable (`chmod +x`); follow `run-apiserver` pattern in `snap/local/tree/usr/bin/`
- [ ] T048 [P] Add `python3-mcp` to `stage-packages` list in `snap/snapcraft.yaml` (Ubuntu archive — NOT PyPI); verify `python3-httpx`, `python3-pydantic`, `python3-pydantic-settings`, `python3-uvicorn`, `python3-structlog`, `python3-pythonjsonlogger` are also declared in `stage-packages`; do NOT add `mcp-server` to `apps:` (Pebble manages the service)

### Documentation & CI

- [ ] T049 Create `docs/mcp-server-nginx.conf.example` — nginx `server` block for TCP port 5275 → Unix socket proxy: `proxy_pass http://unix:/run/maas/mcp.sock:/`; `proxy_buffering off` (required for SSE streaming); `proxy_read_timeout 3600s`; comment noting snap socket path is `$SNAP_DATA/mcp.sock`; note this fragment is for region controller operators — the MCP server package does not install or manage nginx configuration
- [ ] T050 [P] Add `maas-mcp-server` to the deb build matrix in CI (Makefile or GitHub Actions workflow); add `src/tests/maasmcpserver/` as a pytest discovery target in `tox.ini` or equivalent; add CI step that asserts `python3-mcp` is resolvable from the Ubuntu package archive (no PyPI index consulted, no pip fallback); add snap build smoke test verifying the `mcp-server` Pebble service is present and `startup: disabled` in the built snap

---

## Dependencies

```
T001 → T002 → T003 → T004           (setup chain, strictly sequential)
T004 → T005                          (skeleton before config)
T005 → T006 → T007 → T008           (config before errors, before logging, before client)
T005 → T009..T013                    (config before models — models import config for type hints)
T007, T008, T009..T013 → T014       (logging+client+models before middleware)
T014 → T015                          (middleware before TC-2 guard)
T015, T009..T013 → T016             (guard + models before server.py)
T016 → T017                          (server.py before __main__.py)

T017 → T018..T022                    (server complete before fleet tools registered)
T017 → T023                          (server complete before info tool registered)
T017 → T024..T025                    (server complete before diagnostic tools registered)
T017 → T026..T029                    (server complete before network tools registered)
T017 → T030..T032                    (server complete before boot source tools registered)

T005 → T033                          (config before config tests)
T008 → T034                          (client before client tests)
T014 → T035                          (middleware before middleware tests)
T007 → T036                          (logging before logging tests)
T018..T022 → T037                    (fleet tools before fleet tests)
T024..T025 → T038                    (diagnostic tools before diagnostic tests)
T023 → T039                          (info tool before info tests)
T026..T029 → T040                    (network tools before network tests)
T030..T032, T015 → T041             (boot source tools + TC-2 guard before boot source tests)

T003 → T042..T045                    (pyproject wired before deb packaging)
T003 → T046..T048                    (pyproject wired before snap packaging)
T042..T048 → T049..T050              (packaging before CI matrix entries)
```

**Story completion order** (by priority):

| Phase | User Story | Priority | Gate tasks |
|-------|-----------|----------|------------|
| Phase 3 | US1 Session Init | P1 | T014–T017 complete |
| Phase 4 | US2 Fleet Discovery | P2 | T018–T022 complete |
| Phase 5 | US3 MAAS Info | P2 | T023 complete |
| Phase 6 | US4 Diagnostics | P3 | T024–T025 complete |
| Phase 7 | US5 Network Mgmt | P3 | T026–T029 complete |
| Phase 8 | US6 Boot Sources | P3 | T030–T032 complete |

**Deferred** (TC-2): US7 (P4 Node Provisioning) and US8 (P5 Resource Lifecycle) — machine
lifecycle write operations unavailable in API v3. No tasks generated. TC-2 guard (T015)
handles any unexpected invocation.

---

## Parallel Execution Examples

### Phase 2 — Foundational (after T005)
```
T006  errors.py          ─┐
T007  logging_events.py  ─┤
T008  client.py          ─┤ all parallel (different files, share only config import)
T009  models/machines.py ─┤
T010  models/diagnostics ─┤
T011  models/info.py     ─┤
T012  models/network.py  ─┤
T013  models/boot_sources─┘
```

### Phase 4 — Fleet Tools (after T017)
```
T018  list_machines             (start here — other tools can parallel after T018 skeleton)
T019  get_machine          ─┐
T020  list_resource_pools  ─┤ all parallel (same file, non-overlapping functions)
T021  list_zones           ─┤
T022  get_machine_power_state─┘
```

### Phase 7 — Network Tools (after T017)
```
T026  network read tools        (start here — write tools can parallel after read skeleton)
T027  fabric write tools   ─┐
T028  VLAN write tools     ─┤ all parallel (same file, non-overlapping functions)
T029  subnet write tools   ─┘
```

### Phase 9 — Tests (all parallel after respective implementation)
```
T033  test_config.py       ─┐
T034  test_client.py       ─┤
T035  test_middleware.py   ─┤ all parallel (different test files)
T036  test_logging.py      ─┤
T037  tool_tests/fleet     ─┤
T038  tool_tests/diag      ─┤
T039  tool_tests/info      ─┤
T040  tool_tests/network   ─┤
T041  tool_tests/boot      ─┘
```

### Phase 9 — Packaging (all parallel after T003)
```
T042  deb install file     ─┐
T043  deb control stanza   ─┤
T044  systemd unit         ─┤ all parallel (different files)
T045  deb dirs file        ─┤
T046  Pebble layer 004     ─┤
T047  run-mcp-server       ─┤
T048  snapcraft.yaml       ─┘
```

---

## Implementation Strategy

### MVP Scope (Phase 1 + Phase 2 + Phase 3 only — T001–T017)

Delivers a running MCP server on a Unix socket with token-delegation auth and structured
NDJSON logging — fully verifiable without any MAAS tools implemented. Validates:
- Unix socket binding via uvicorn (`uds=`) works in the target environment
- `python3-mcp` from Ubuntu archive is importable as `FastMCP`
- AuthMiddleware correctly enforces Bearer token and emits session lifecycle logs
- TC-2 guard correctly rejects deferred tool invocations

### Increment 1: Read-Only Fleet (Phases 1–4, T001–T022)

Adds all five fleet discovery tools. Delivers immediate value: operators can query machine
inventory, pools, zones, and power states through an AI assistant with no write risk.

### Increment 2: Full Read Stack (add Phase 5 + Phase 6, T023–T025)

Adds MAAS instance identification and diagnostic tools (events, script results). The MCP
server is now a fully functional read-only MAAS interface.

### Increment 3: Write Operations (add Phases 7–8, T026–T032)

Adds network fabric/VLAN/subnet management (15 tools) and boot source management (3 tools).
These are the only API v3 write domains available (TC-2 excludes machine lifecycle writes).

### Final: Polish (Phase 9, T033–T050)

Completes unit tests, deb and snap packaging, nginx documentation, and CI wiring. Required
before any release or merge to main.

---

## Summary

| Metric | Count |
|--------|-------|
| Total tasks | 50 |
| Phase 1 (Setup) | 4 |
| Phase 2 (Foundational) | 9 |
| Phase 3 (US1 Session Auth) | 4 |
| Phase 4 (US2 Fleet Discovery) | 5 |
| Phase 5 (US3 MAAS Info) | 1 |
| Phase 6 (US4 Diagnostics) | 2 |
| Phase 7 (US5 Network Mgmt) | 4 |
| Phase 8 (US6 Boot Sources) | 3 |
| Phase 9 (Polish: tests + packaging + CI) | 18 |
| Parallelisable tasks `[P]` | 34 |
| User Story tasks `[USn]` | 19 |
| Deferred (TC-2: US7, US8) | 0 (guard in T015) |

**MCP tools implemented**: 27 across 5 files (fleet×5, diagnostics×2, info×1, network×15,
boot_sources×3). Machine lifecycle write tools (FR-6) absent from listing per TC-2.
