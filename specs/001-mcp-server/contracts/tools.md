# MCP Tool Contracts

**Feature**: 001-mcp-server | **Branch**: `6689-mcp-server`

All tools return `str` (formatted text) on success or raise/return a structured MCP error on
failure. Parameters are passed as keyword arguments by MCP clients. All tools enforce
`MAAS_REQUEST_TIMEOUT` on every outbound MAAS API v3 request; timeout and connection errors
produce `error_code: "maas_unreachable"`. Permission errors from API v3 are surfaced directly
(FR-7). No tool retries a failed MAAS request (FR-11).

---

## Fleet Discovery Tools (`tools/fleet.py`) — FR-4, US2

### `list_machines`

```python
list_machines(
    status: str | None = None,          # e.g. "Ready", "Allocated", "Deployed"
    zone: str | None = None,            # Availability zone name
    pool: str | None = None,            # Resource pool name
    architecture: str | None = None,    # e.g. "amd64/generic"
    tags: str | None = None,            # Comma-separated tag names
    owner: str | None = None,           # MAAS username
    power_state: str | None = None,     # e.g. "on", "off", "unknown"
    page: int = 1,
    page_size: int = 50,
) -> str
```

MAAS API: `GET /MAAS/a/v3/machines` (filters as query parameters, pagination via `page` +
`size`).

Success output: Markdown table — hostname, system_id, status, zone, pool, architecture,
CPUs, memory (GiB), owner, power_state, tags.

---

### `get_machine`

```python
get_machine(
    identifier: str,    # Machine hostname or system_id
) -> str
```

MAAS API calls (sequential):
1. `GET /MAAS/a/v3/machines/{system_id}` — full machine record
2. `GET /MAAS/a/v3/machines/{system_id}/interfaces` — network interfaces

If `identifier` looks like a hostname (no `/`), the client first resolves it to a
`system_id` via `GET /MAAS/a/v3/machines?hostname={identifier}` then fetches the detail.

Success output: Full machine detail — hardware specs, OS, network interfaces, block devices.

---

### `list_resource_pools`

```python
list_resource_pools(
    page: int = 1,
    page_size: int = 100,
) -> str
```

MAAS API: `GET /MAAS/a/v3/resource_pools?page={page}&size={page_size}`

Success output: List of pool names, descriptions, and machine counts.

---

### `list_zones`

```python
list_zones(
    page: int = 1,
    page_size: int = 100,
) -> str
```

MAAS API: `GET /MAAS/a/v3/zones?page={page}&size={page_size}`

Success output: List of availability zone names and descriptions.

---

### `get_machine_power_state`

```python
get_machine_power_state(
    identifier: str,    # Hostname or system_id
) -> str
```

MAAS API: `GET /MAAS/a/v3/machines/{system_id}` (extracts `power_state` field).

Success output: Machine hostname + current power state (on / off / unknown / error).

---

## Diagnostic Tools (`tools/diagnostics.py`) — FR-5, US4

### `get_machine_events`

```python
get_machine_events(
    identifier: str,          # Hostname or system_id
    since_hours: int = 24,    # Return events from the last N hours
    page: int = 1,
    page_size: int = 100,
) -> str
```

MAAS API: `GET /MAAS/a/v3/events?system_id={system_id}&page={page}&size={page_size}`

Client-side filters the response by `created` timestamp using `since_hours`. Events are
returned in chronological order (oldest first).

Success output: Chronological list — event type, level, description, timestamp.

---

### `get_script_results`

```python
get_script_results(
    identifier: str,                        # Hostname or system_id
    script_type: str = "commissioning",     # "commissioning" or "testing"
) -> str
```

MAAS API: Script results endpoint under the machine resource (verify exact path against
`openapi-spec.json` during implementation; expected:
`GET /MAAS/a/v3/machines/{system_id}/results?script_type={script_type}`).

Success output: Per-script name, exit status, runtime, truncated stdout/stderr output.

---

## MAAS Info Tool (`tools/info.py`) — FR-12, US3

### `get_maas_info`

```python
get_maas_info() -> str
```

MAAS API calls (concurrent via `asyncio.gather`):
1. `GET /MAAS/a/v3/configurations/maas_name` → `deployment_name`
2. `GET /MAAS/a/v3/racks` → `rack_controllers[]`

Success output: Deployment name + rack controller list (hostname, rack_id,
connection_state). List may be empty if no racks are registered.

**Absent from response**: `instance_uuid`, `region_controllers` — these fields are not
exposed by API v3 and must not be fabricated or sourced from any non-v3 path (FR-12).

Error output (any API v3 call times out):
`error_code: "maas_unreachable"`, human-readable description with URL pattern and failure
mode.

---

## Network Management Tools (`tools/network.py`) — FR-13, US5

> **API v3 Subnet Nesting**: Subnets are nested under VLANs in API v3. All subnet tools
> require `fabric_id` + `vlan_id`. A flat `/subnets/` endpoint does not exist.

### Read Tools

```python
list_fabrics(page: int = 1, page_size: int = 100) -> str
```
MAAS API: `GET /MAAS/a/v3/fabrics?page={page}&size={page_size}`

```python
get_fabric(fabric_id: int) -> str
```
MAAS API: `GET /MAAS/a/v3/fabrics/{fabric_id}`

```python
list_vlans(fabric_id: int, page: int = 1, page_size: int = 100) -> str
```
MAAS API: `GET /MAAS/a/v3/fabrics/{fabric_id}/vlans?page={page}&size={page_size}`

```python
get_vlan(fabric_id: int, vlan_id: int) -> str
```
MAAS API: `GET /MAAS/a/v3/fabrics/{fabric_id}/vlans/{vlan_id}`

```python
list_subnets(fabric_id: int, vlan_id: int, page: int = 1, page_size: int = 100) -> str
```
MAAS API: `GET /MAAS/a/v3/fabrics/{fabric_id}/vlans/{vlan_id}/subnets?page={page}&size={page_size}`

```python
get_subnet(fabric_id: int, vlan_id: int, subnet_id: int) -> str
```
MAAS API: `GET /MAAS/a/v3/fabrics/{fabric_id}/vlans/{vlan_id}/subnets/{subnet_id}`

### Write Tools — Fabrics

```python
create_fabric(name: str, description: str = "", class_type: str | None = None) -> str
```
MAAS API: `POST /MAAS/a/v3/fabrics`

```python
update_fabric(fabric_id: int, name: str | None = None, description: str | None = None) -> str
```
MAAS API: `PUT /MAAS/a/v3/fabrics/{fabric_id}`

```python
delete_fabric(fabric_id: int) -> str
```
MAAS API: `DELETE /MAAS/a/v3/fabrics/{fabric_id}`

Executes immediately — no server-side confirmation gate. Success response always includes
the deleted fabric's **name** so the AI client can verify the correct target was acted on.

### Write Tools — VLANs

```python
create_vlan(
    fabric_id: int,
    vid: int,
    name: str = "",
    mtu: int = 1500,
    dhcp_relay_target: int | None = None,
) -> str
```
MAAS API: `POST /MAAS/a/v3/fabrics/{fabric_id}/vlans`

```python
update_vlan(
    fabric_id: int,
    vlan_id: int,
    vid: int | None = None,
    name: str | None = None,
    mtu: int | None = None,
) -> str
```
MAAS API: `PUT /MAAS/a/v3/fabrics/{fabric_id}/vlans/{vlan_id}`

```python
delete_vlan(fabric_id: int, vlan_id: int) -> str
```
MAAS API: `DELETE /MAAS/a/v3/fabrics/{fabric_id}/vlans/{vlan_id}`

Executes immediately — no server-side confirmation gate. Success response always includes
the deleted VLAN's **VID + name** so the AI client can verify the correct target.

### Write Tools — Subnets

```python
create_subnet(
    fabric_id: int,
    vlan_id: int,
    cidr: str,
    name: str = "",
    gateway_ip: str | None = None,
    dns_servers: list[str] | None = None,
) -> str
```
MAAS API: `POST /MAAS/a/v3/fabrics/{fabric_id}/vlans/{vlan_id}/subnets`

```python
update_subnet(
    fabric_id: int,
    vlan_id: int,
    subnet_id: int,
    name: str | None = None,
    cidr: str | None = None,
    gateway_ip: str | None = None,
    dns_servers: list[str] | None = None,
) -> str
```
MAAS API: `PUT /MAAS/a/v3/fabrics/{fabric_id}/vlans/{vlan_id}/subnets/{subnet_id}`

```python
delete_subnet(fabric_id: int, vlan_id: int, subnet_id: int) -> str
```
MAAS API: `DELETE /MAAS/a/v3/fabrics/{fabric_id}/vlans/{vlan_id}/subnets/{subnet_id}`

Executes immediately — no server-side confirmation gate. Success response always includes
the deleted subnet's **CIDR + name** (with fabric + VLAN context) so the AI client can
verify the correct target.

---

## Boot Source Management Tools (`tools/boot_sources.py`) — FR-14, US6

### `list_boot_sources`

```python
list_boot_sources() -> str
```

MAAS API: `GET /MAAS/a/v3/boot_sources`

Success output: Each boot source's ID, URL, keyring filename, keyring data, and associated
selections (OS, release, arches).

---

### `trigger_boot_source_sync`

```python
trigger_boot_source_sync(
    boot_source_id: int,
    selection_id: int,
) -> str
```

MAAS API: `POST /MAAS/a/v3/boot_sources/{boot_source_id}/selections/{selection_id}:sync`

Triggers MAAS to sync the specified boot image selection. The tool returns the API v3
response (accepted/queued status) immediately — it does not poll for completion. The AI
client or operator is responsible for polling `list_boot_sources` or checking selections to
confirm sync completion.

The tool accepts only `boot_source_id` and `selection_id`. It does not accept source URL,
source type, or credential parameters — it delegates entirely to MAAS's pre-configured
sources (FR-14).

---

### `delete_boot_source`

```python
delete_boot_source(boot_source_id: int) -> str
```

MAAS API: `DELETE /MAAS/a/v3/boot_sources/{boot_source_id}`

Executes immediately — no server-side confirmation gate. Success response always includes
the deleted boot source's **ID + URL** so the AI client can verify the correct source was
removed.

---

## Deferred Tools (TC-2 — Machine Lifecycle Writes)

The following tool groups are **not implemented** and **not listed** in the MCP
tool-listing response while TC-2 is in force:

| Tool | Deferred reason |
|------|----------------|
| `commission_machine` | API v3 write endpoint unavailable (TC-2) |
| `release_machine` | API v3 write endpoint unavailable (TC-2) |
| `abort_machine` | API v3 write endpoint unavailable (TC-2) |
| `rescue_machine` | API v3 write endpoint unavailable (TC-2) |
| `deploy_machine` | API v3 write endpoint unavailable (TC-2) |
| `add_tag` / `remove_tag` | API v3 write endpoint unavailable (TC-2) |
| `reassign_pool` | API v3 write endpoint unavailable (TC-2) |
| `update_power_params` | API v3 write endpoint unavailable (TC-2) |
| `update_ownership` | API v3 write endpoint unavailable (TC-2) |

**Runtime guard**: If an invocation for any deferred tool is received (e.g., from a client
with a stale tool list), the server returns a structured MCP `not-implemented` error
immediately with the message:

```
"Machine lifecycle write operations are not available: API v3 does not currently
expose write endpoints for machine lifecycle management (TC-2). Tool '<name>' is
deferred until API v3 gains these endpoints."
```

No MAAS API v3 request is made. No partial state change occurs.

---

## MAAS HTTP Client (`client.py`)

### `MAASClient`

Thin async wrapper around `httpx.AsyncClient`.

```python
class MAASClient:
    def __init__(self, config: MaasServerConfig, api_key: str) -> None: ...
    async def get(self, path: str, **params) -> dict: ...
    async def post(self, path: str, body: dict) -> dict: ...
    async def put(self, path: str, body: dict) -> dict: ...
    async def delete(self, path: str) -> dict: ...
```

All methods:
- Set `Authorization: Bearer {api_key}` on every request.
- Apply `httpx.Timeout(timeout=config.maas_request_timeout)` unconditionally.
- Emit `maas.request` log event before the call and `maas.response` event after.
- Raise `MAASUnreachableError` on `httpx.TimeoutException` or `httpx.ConnectError`.
  `maas.response` is emitted with `http_status: 0` and `error: "maas_unreachable"` in
  these cases.
- Raise `MAASPermissionError` on HTTP 401 or 403.
- Raise `httpx.HTTPStatusError` for other 4xx/5xx responses (tool handlers format the
  message for the AI client).
- Do **not** retry on any error (FR-11).

The `url_pattern` logged in `maas.request` is the path template (e.g.
`/MAAS/a/v3/machines/{id}`) — never the resolved URL with substituted IDs or query
strings that could carry credential-adjacent data.
