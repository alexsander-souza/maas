# Data Model: MAAS MCP Server

**Feature**: 001-mcp-server | **Branch**: `6689-mcp-server`

> **No Database**: The MCP server has no database, no ORM, and no migrations. This document
> defines **in-memory Pydantic response models** used to structure data flowing from MAAS API
> v3 responses to MCP tool outputs. There are no table definitions, no Alembic migration
> files, and no SQLAlchemy constructs anywhere in `src/maasmcpserver/`.

---

## Session Context (In-Memory, Connection-Scoped)

Not a Pydantic model — managed by ASGI middleware via a `contextvars.ContextVar`.

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | `str` | UUID4 generated at connection time; included in all log events |
| `api_key` | `str` | Raw MAAS JWT Bearer token; never logged, never persisted |
| `api_key_hash` | `str` | `sha256(api_key).hexdigest()`; emitted in `session.opened` log only |

**Lifetime**: Exists for exactly the duration of the HTTP/SSE connection. Cleared on
disconnect. Never written to disk or any external store.

---

## Machine Models (`models/machines.py`)

### `MachineSummary`

Returned by `list_machines`. Subset of the full machine record.

| Field | Type | Nullable | API v3 source field |
|-------|------|----------|---------------------|
| `system_id` | `str` | No | `system_id` |
| `hostname` | `str` | No | `hostname` |
| `status` | `str` | No | `status` |
| `zone` | `str` | No | `zone.name` |
| `pool` | `str` | No | `pool.name` |
| `architecture` | `str` | No | `architecture` |
| `cpu_count` | `int` | No | `cpu_count` |
| `memory_mb` | `int` | No | `memory` (MiB) |
| `owner` | `str \| None` | Yes | `owner` |
| `power_state` | `str \| None` | Yes | `power_state` |
| `tags` | `list[str]` | No | `tag_names` |

### `InterfaceSummary`

Embedded in `MachineDetail.interfaces`.

| Field | Type | Nullable | API v3 source field |
|-------|------|----------|---------------------|
| `id` | `int` | No | `id` |
| `name` | `str` | No | `name` |
| `type` | `str` | No | `type` (physical/bond/vlan/bridge) |
| `mac_address` | `str` | No | `mac_address` |
| `enabled` | `bool` | No | `enabled` |
| `vlan_id` | `int \| None` | Yes | `vlan.id` |
| `ip_addresses` | `list[str]` | No | `links[].ip_address` |

### `BlockDevice`

Embedded in `MachineDetail.block_devices`.

| Field | Type | Nullable | API v3 source field |
|-------|------|----------|---------------------|
| `id` | `int` | No | `id` |
| `name` | `str` | No | `name` |
| `type` | `str` | No | `type` (physical/virtual) |
| `size_gb` | `float` | No | `size` bytes ÷ 1,073,741,824 |
| `model` | `str \| None` | Yes | `model` |
| `serial` | `str \| None` | Yes | `serial` |

### `MachineDetail`

Returned by `get_machine`. Extends `MachineSummary`.

| Field | Type | Nullable | API v3 source field |
|-------|------|----------|---------------------|
| *(all `MachineSummary` fields)* | | | |
| `fqdn` | `str` | No | `fqdn` |
| `osystem` | `str` | No | `osystem` |
| `distro_series` | `str` | No | `distro_series` |
| `interfaces` | `list[InterfaceSummary]` | No | `GET …/interfaces` |
| `block_devices` | `list[BlockDevice]` | No | `blockdevice_set` |

---

## Diagnostic Models (`models/diagnostics.py`)

### `MachineEvent`

Returned by `get_machine_events`.

| Field | Type | Nullable | API v3 source field |
|-------|------|----------|---------------------|
| `id` | `int` | No | `id` |
| `event_type` | `str` | No | `type.name` |
| `description` | `str` | No | `description` |
| `created` | `str` | No | `created` (ISO 8601) |
| `level` | `str` | No | `type.level` |

### `ScriptResult`

Returned by `get_script_results`.

| Field | Type | Nullable | API v3 source field |
|-------|------|----------|---------------------|
| `id` | `int` | No | `id` |
| `name` | `str` | No | `name` |
| `status` | `str` | No | `status` |
| `exit_status` | `int \| None` | Yes | `exit_status` |
| `output` | `str \| None` | Yes | `output` (stdout + stderr) |
| `started` | `str \| None` | Yes | `started` (ISO 8601) |
| `ended` | `str \| None` | Yes | `ended` (ISO 8601) |

---

## MAAS Info Models (`models/info.py`)

### `RackController`

Embedded in `MAASInfo.rack_controllers`.

| Field | Type | Nullable | API v3 source field |
|-------|------|----------|---------------------|
| `rack_id` | `str` | No | `system_id` |
| `hostname` | `str` | No | `hostname` |
| `connection_state` | `str` | No | `connection_state` |

### `MAASInfo`

Returned by `get_maas_info`.

| Field | Type | Nullable | Notes |
|-------|------|----------|-------|
| `deployment_name` | `str` | No | From `GET /MAAS/a/v3/configurations/maas_name` |
| `rack_controllers` | `list[RackController]` | No | From `GET /MAAS/a/v3/racks`; may be empty |

**Absent fields** (`instance_uuid`, `region_controllers`): Not available in API v3. Must not
be fabricated. See FR-12.

---

## Network Models (`models/network.py`)

### `Fabric`

| Field | Type | Nullable | API v3 source field |
|-------|------|----------|---------------------|
| `id` | `int` | No | `id` |
| `name` | `str` | No | `name` |
| `description` | `str` | No | `description` |
| `class_type` | `str \| None` | Yes | `class_type` |

### `VLAN`

| Field | Type | Nullable | API v3 source field |
|-------|------|----------|---------------------|
| `id` | `int` | No | `id` |
| `fabric_id` | `int` | No | `fabric` (parent fabric ID) |
| `vid` | `int` | No | `vid` |
| `name` | `str \| None` | Yes | `name` |
| `mtu` | `int` | No | `mtu` |
| `dhcp_on` | `bool` | No | `dhcp_on` |

### `Subnet`

> **API v3 nesting**: Subnets are nested under VLANs. All subnet operations require
> `fabric_id` + `vlan_id`. A flat `/subnets/` endpoint does not exist in API v3.

| Field | Type | Nullable | API v3 source field |
|-------|------|----------|---------------------|
| `id` | `int` | No | `id` |
| `fabric_id` | `int` | No | path param (parent context) |
| `vlan_id` | `int` | No | path param (parent context) |
| `name` | `str` | No | `name` |
| `cidr` | `str` | No | `cidr` |
| `gateway_ip` | `str \| None` | Yes | `gateway_ip` |
| `dns_servers` | `list[str]` | No | `dns_servers` |
| `active_discovery` | `bool` | No | `active_discovery` |

---

## Boot Source Models (`models/boot_sources.py`)

### `BootSource`

Returned by `list_boot_sources`.

| Field | Type | Nullable | API v3 source field |
|-------|------|----------|---------------------|
| `id` | `int` | No | `id` |
| `url` | `str` | No | `url` |
| `keyring_filename` | `str \| None` | Yes | `keyring_filename` |
| `keyring_data` | `str \| None` | Yes | `keyring_data` |

### `BootSourceSelection`

Embedded in a boot source's selections list.

| Field | Type | Nullable | API v3 source field |
|-------|------|----------|---------------------|
| `id` | `int` | No | `id` |
| `boot_source_id` | `int` | No | parent context |
| `os` | `str` | No | `os` |
| `release` | `str` | No | `release` |
| `arches` | `list[str]` | No | `arches` |
| `subarches` | `list[str]` | No | `subarches` |
| `labels` | `list[str]` | No | `labels` |

---

## Error Models (`errors.py`)

Not Pydantic models — Python exceptions used internally.

### `MAASUnreachableError`

Raised by `MAASClient` on timeout (`httpx.TimeoutException`) or connection refused
(`httpx.ConnectError`). Carries:
- `url_pattern: str` — path template (e.g. `/MAAS/a/v3/machines/{id}`)
- `failure_mode: str` — `"timeout"` or `"connection_refused"`

Tool handlers catch this and return a structured MCP error with
`error_code: "maas_unreachable"`.

### `MAASPermissionError`

Raised by `MAASClient` on HTTP 401 or 403. Carries the raw API v3 error body. Tool handlers
surface this directly to the AI client without masking (FR-7).

---

## State Transitions (Reference)

The MCP server does not drive machine state transitions in v1 (TC-2). The following is
provided for context only:

```
New → Commissioning → Ready → Allocated → Deploying → Deployed → Releasing → Ready
                            ↘ Failed Commissioning
                                         ↘ Failed Deployment
```

All read-only tools (fleet, diagnostics) correctly handle any status value returned by
API v3 — no status enumeration is hard-coded; status is passed through as a plain string.
