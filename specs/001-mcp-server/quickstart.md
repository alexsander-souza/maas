# Quickstart: MAAS MCP Server

**Feature**: 001-mcp-server | **Branch**: `6689-mcp-server`

---

## Architecture Overview

```
AI Client (Claude Desktop, etc.)
       │  HTTP/SSE
       ▼
MAAS nginx (TCP port 5275) ──► Unix socket (/var/lib/maas/mcp.sock)
                                       │
                                MCP Server process
                              (src/maasmcpserver/)
                                       │  HTTP + Bearer token
                                       ▼
                            MAAS API v3 (TCP port 5240)
```

- The MCP server **binds a Unix domain socket**, not a TCP port.
- **nginx** (part of the MAAS region controller) fronts the socket on **TCP port 5275**.
  The MCP server is unaware of port 5275.
- The MCP server does **not** perform TLS termination — nginx handles TLS if required.
- No `stdio` transport; no direct database access; no MAAS API v2.

---

## Prerequisites

- Ubuntu 24.04 LTS (Noble) or later
- A running MAAS deployment with API v3 enabled, reachable at a known URL
- A MAAS user account with a valid API key (JWT token)
- An MCP-compatible AI client (Claude Desktop, a custom LLM host, etc.)
- MAAS region nginx must be configured to proxy TCP port 5275 → Unix socket (see the nginx
  configuration fragment in `contracts/config.md`)

---

## 1. Install

### Option A — Debian Package (deb)

```bash
sudo apt install maas-mcp-server
```

The package pulls `python3-mcp` from the Ubuntu archive (TC-1). No `pip install` is
required or permitted.

### Option B — Snap (MAAS installed via snap)

The MCP server is bundled in the `maas` snap as an optional Pebble service. No separate
package installation is needed. `python3-mcp` is included via `stage-packages`.

---

## 2. Configure

The MCP server works out of the box with no configuration needed — it defaults to
`MAAS_URL=http://localhost:5240`, which is the MAAS region API on the same host.

Override any setting via the env file:

### deb — `/etc/maas/mcp-server.env`

```bash
# All settings are optional; defaults shown.
# MAAS_URL=http://localhost:5240
# MCP_SOCKET_PATH=/var/lib/maas/mcp.sock
# MAAS_REQUEST_TIMEOUT=30
# MAAS_TLS_VERIFY=true
# LOG_LEVEL=INFO
```

**Do not set** `MCP_HOST`, `MCP_PORT`, `TLS_CERT`, `TLS_KEY`, or `MAAS_API_KEY` — these
are unsupported and contradict the architecture (see `contracts/config.md`).

### snap — `$SNAP_DATA/mcp-server.env` (optional)

```bash
# Override only if your MAAS API is not at http://localhost:5240
# MAAS_URL=http://maas.example.com:5240
# MAAS_REQUEST_TIMEOUT=30
# MAAS_TLS_VERIFY=true
# LOG_LEVEL=INFO
```

The snap wrapper sets `MCP_SOCKET_PATH` to `$SNAP_DATA/mcp.sock` automatically.

---

## 3. Start the Service

### deb

The service is **enabled and started automatically** on package install. No manual
`systemctl enable` is required.

```bash
# Verify it is running:
sudo systemctl status maas-mcp-server

# Restart after editing /etc/maas/mcp-server.env:
sudo systemctl restart maas-mcp-server
```

### snap

The Pebble service starts automatically with the snap. No manual `snap start` is
required.

---

## 4. Verify the Server Is Running

```bash
# Check the Unix socket exists (deb):
ls -l /var/lib/maas/mcp.sock

# Check the Unix socket exists (snap):
ls -l /var/snap/maas/common/maas/mcp.sock

# Confirm nginx is forwarding TCP 5275 → Unix socket:
curl -s http://localhost:5275/  # should return an MCP protocol response or 400, not connection refused
```

---

## 5. View Structured Logs

The MCP server writes NDJSON to stdout (captured by journald / systemd-cat):

```bash
# deb:
journalctl -u maas-mcp-server -f | python3 -m json.tool

# snap:
snap logs maas.mcp-server -f
```

Each line is a self-contained JSON object with an `event` field. The six mandatory event
types are `session.opened`, `tool.received`, `maas.request`, `maas.response`,
`tool.outcome`, and `session.closed`. The raw MAAS API key never appears in any log line.

---

## 6. Connect Your AI Client

Point your MCP-compatible AI client at:

```
http://<maas-region-host>:5275/
```

On connection, supply your MAAS API key as an HTTP `Authorization: Bearer <jwt-token>`
header. The MCP server validates that a non-empty Bearer token is present and uses it for
all MAAS API v3 calls within your session.

Example using Claude Desktop's MCP config:

```json
{
  "mcpServers": {
    "maas": {
      "type": "http",
      "url": "http://maas.example.com:5275/",
      "headers": {
        "Authorization": "Bearer <your-maas-api-key>"
      }
    }
  }
}
```

---

## 7. Try a Tool Call

Once connected, ask your AI assistant:

- *"List all machines in the staging resource pool"*
- *"What events were recorded for machine node-01 in the last 6 hours?"*
- *"What MAAS instance am I connected to?"*
- *"List all fabrics and their VLANs"*
- *"Create a new VLAN with VID 200 in fabric 'prod'"*
- *"List boot sources"*

The AI client will invoke the corresponding MCP tools (`list_machines`,
`get_machine_events`, `get_maas_info`, `list_fabrics`, `create_vlan`, `list_boot_sources`,
etc.) and present the results.

---

## 8. Development Install (from repo root)

```bash
# Install the maasmcpserver package in editable mode
pip install -e ".[mcp-server]"

# Create a .env file (Pydantic BaseSettings picks this up automatically)
cat > .env <<EOF
MAAS_URL=http://localhost:5240
MCP_SOCKET_PATH=/tmp/dev-mcp.sock
LOG_LEVEL=DEBUG
EOF

# Run the server
python3 -m maasmcpserver
```

For development, point a test nginx (or `socat`) at `/tmp/dev-mcp.sock` to simulate the
nginx proxy, or connect your AI client directly via `socat` TCP tunnelling.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `Connection refused` on port 5275 | nginx not proxying to Unix socket | Check nginx config; confirm the `proxy_pass unix:…` block for port 5275 is present and nginx has reloaded |
| `No such file or directory: /var/lib/maas/mcp.sock` | Service not started, or wrong socket path in nginx config | `systemctl start maas-mcp-server`; confirm `MCP_SOCKET_PATH` matches nginx config |
| `Validation error: maas_url field required` | `MAAS_URL` not set in env file | Edit `/etc/maas/mcp-server.env` and add `MAAS_URL=…`; restart service |
| `maas_unreachable` error in tool response | MAAS API v3 endpoint unreachable or slow | Check `MAAS_URL` value; verify MAAS is running; check `MAAS_TLS_VERIFY` if using self-signed cert |
| `401 Unauthorized` on tool call | Invalid or expired MAAS API key | Supply a valid, unexpired JWT token in the `Authorization: Bearer` header |
| Machine lifecycle tool returns `not-implemented` | TC-2: API v3 does not expose machine lifecycle write endpoints | This is expected in v1; commission/deploy/release tools are deferred |
| Service starts then immediately exits (snap) | `MAAS_URL` missing from `$SNAP_DATA/mcp-server.env` | Create the env file with `MAAS_URL=…` and `snap start maas.mcp-server` |
