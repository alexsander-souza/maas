# Configuration Contract

**Feature**: 001-mcp-server | **Branch**: `6689-mcp-server`

---

## Environment Variables (`config.py` — `MaasServerConfig`)

All configuration is via environment variables (or `.env` file for development, loaded by
Pydantic `BaseSettings`). No source-code editing is required for any supported configuration
scenario.

| Variable | Type | Default | Required | Description |
|----------|------|---------|----------|-------------|
| `MAAS_URL` | `str` | — | **Yes** | Base URL of the MAAS API v3 endpoint (e.g. `http://maas.example.com:5240`). Must not include a trailing slash. |
| `MCP_SOCKET_PATH` | `str` | `/run/maas/mcp.sock` | No | Filesystem path of the Unix domain socket the MCP server binds. The parent directory must be writable by the `maas` user at startup. |
| `MAAS_REQUEST_TIMEOUT` | `int` | `30` | No | Seconds to wait for each MAAS API v3 HTTP response. Enforced unconditionally per-request; no override path exists. |
| `MAAS_TLS_VERIFY` | `bool` | `true` | No | Verify the TLS certificate presented by the MAAS API v3 endpoint. Set `false` only in development with self-signed certs. |
| `LOG_LEVEL` | `str` | `INFO` | No | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |

### Deliberately Absent Variables

| Variable | Reason absent |
|----------|--------------|
| `MCP_HOST` | TC-3 violation — the MCP server binds a Unix socket, not a TCP address. |
| `MCP_PORT` | TC-3 violation — TCP port binding belongs to nginx (port 5275), not the MCP server. |
| `MAAS_API_KEY` / any app-level key | FR-2 violation — API keys are per-session via HTTP `Authorization` header; no centralized service account. |
| `MAAS_MCP_TRANSPORT` | TC-3 violation — transport is always `streamable-http` over the Unix socket; it is not configurable. |
| `TLS_CERT`, `TLS_KEY`, `TLS_CA` | TC-4 violation — the MCP listener never provides native TLS. TLS termination is nginx's responsibility. |
| `DATABASE_URL` / `DB_DSN` | The MCP server has no database; all data is sourced from MAAS API v3. |

---

## Pydantic Settings Schema (`src/maasmcpserver/config.py`)

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class MaasServerConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    maas_url: str                                    # Required
    mcp_socket_path: str = "/run/maas/mcp.sock"     # Unix socket path
    maas_request_timeout: int = 30
    maas_tls_verify: bool = True
    log_level: str = "INFO"
```

---

## Systemd Unit (`debian/maas-mcp-server.maas-mcp-server.service`) — deb

```ini
[Unit]
Description=MAAS MCP Server
Documentation=https://maas.io/docs
Requires=network-online.target
After=network-online.target
ConditionPathExists=/etc/maas/mcp-server.env

[Service]
User=maas
Group=maas
Restart=on-failure
RestartSec=10s
KillMode=mixed
RuntimeDirectory=maas
RuntimeDirectoryMode=0755
EnvironmentFile=/etc/maas/mcp-server.env
ExecStart=/usr/sbin/maas-mcp-server

[Install]
WantedBy=multi-user.target
```

Notes:
- `RuntimeDirectory=maas` creates `/run/maas/` on startup (owned by `maas:maas`), ensuring
  the Unix socket path `/run/maas/mcp.sock` is writable.
- Service is **disabled by default**. Operator must `sudo systemctl enable maas-mcp-server`
  and then `sudo systemctl start maas-mcp-server`.
- `ConditionPathExists=/etc/maas/mcp-server.env` prevents startup without a `MAAS_URL`.

---

## Systemd Environment File Template (`/etc/maas/mcp-server.env`) — deb

Installed by the `maas-mcp-server` package as a template (mode `640`, owner `root:maas`):

```bash
# REQUIRED: URL of your MAAS API v3 endpoint
MAAS_URL=http://maas.example.com:5240

# OPTIONAL (defaults shown)
# MCP_SOCKET_PATH=/run/maas/mcp.sock
# MAAS_REQUEST_TIMEOUT=30
# MAAS_TLS_VERIFY=true
# LOG_LEVEL=INFO
```

---

## Pebble Layer File (`snap/local/tree/usr/share/maas/pebble/layers/004-maas-mcp-layer.yaml`) — snap

```yaml
summary: MAAS MCP Server layer

description: |
  Optional MCP (Model Context Protocol) server for AI-assisted MAAS operations.
  Binds a Unix domain socket fronted by nginx on TCP port 5275.
  Disabled by default; enable with: sudo snap start maas.mcp-server

services:
  mcp-server:
    override: replace
    command: sh -c "exec systemd-cat -t maas-mcp-server $SNAP/usr/bin/run-mcp-server"
    startup: disabled
```

Notes:
- `startup: disabled` matches the pattern for optional services (`temporal`,
  `temporal-worker`, `bind9`, etc.).
- NOT registered in `snapcraft.yaml` `apps:` — all snap service management is via Pebble.
- Operator lifecycle: `sudo snap start maas.mcp-server` / `sudo snap stop maas.mcp-server`.

---

## Snap Wrapper Script (`snap/local/tree/usr/bin/run-mcp-server`) — snap

```bash
#!/bin/bash -e
# Copyright 2025 Canonical Ltd. This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# Override paths to work in the snap environment
export MAAS_PATH="$SNAP"
export MAAS_ROOT="$SNAP_DATA"

# Unix socket lives under $SNAP_DATA (writable by the snap at runtime)
export MCP_SOCKET_PATH="$SNAP_DATA/mcp.sock"

# Source operator-supplied config if present (missing file is not an error).
# MAAS_URL must be set here or the Python process will exit with a clear message.
if [ -f "$SNAP_DATA/mcp-server.env" ]; then
    # shellcheck disable=SC1091
    source "$SNAP_DATA/mcp-server.env"
fi

exec "$SNAP/usr/bin/maas-mcp-server"
```

Notes:
- Follows the exact pattern of `run-apiserver`, `run-regiond`, etc.
- `MCP_SOCKET_PATH` is explicitly set to `$SNAP_DATA/mcp.sock` so it is inside the snap's
  writable data directory (snap confinement would block `/run/maas/` by default).
- If `MAAS_URL` is absent after sourcing the env file, the Python process exits immediately
  with a Pydantic validation error — a clear operator signal.

---

## Snap Configuration File (`$SNAP_DATA/mcp-server.env`) — snap

Operators create this file before starting the service:

```bash
# Create snap config
sudo tee /var/snap/maas/current/mcp-server.env > /dev/null <<'EOF'
MAAS_URL=http://maas.example.com:5240
# MAAS_REQUEST_TIMEOUT=30
# MAAS_TLS_VERIFY=true
# LOG_LEVEL=INFO
EOF

# Enable and start
sudo snap start maas.mcp-server
sudo snap logs maas.mcp-server
```

---

## nginx Proxy Configuration (Region Controller Concern — NOT MCP Server)

> **Important**: The MCP server does **not** configure nginx. The following is provided as
> documentation for region controller maintainers. Port 5275 is the external-facing TCP port
> that nginx binds; the MCP server itself only knows about the Unix socket.

The MAAS region nginx config should include a `server` block like:

```nginx
server {
    listen 5275;
    # listen [::]:5275;  # IPv6 if needed

    location / {
        proxy_pass http://unix:/run/maas/mcp.sock;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header Connection "";

        # SSE-specific: disable buffering for event streams
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
    }
}
```

For snap deployments, the Unix socket path is `$SNAP_DATA/mcp.sock`
(`/var/snap/maas/current/mcp.sock`).

---

## Deployment Matrix

| Aspect | deb (`maas-mcp-server`) | snap (`maas`) |
|--------|------------------------|----------------|
| SDK source | `python3-mcp` via `Depends:` | `python3-mcp` via `stage-packages:` |
| Service manager | systemd | Pebble (`004-maas-mcp-layer.yaml`) |
| Service name | `maas-mcp-server.service` | `mcp-server` (Pebble) / `maas.mcp-server` (snap surface) |
| Default state | disabled | `startup: disabled` |
| Entry point | `/usr/sbin/maas-mcp-server` | `run-mcp-server` wrapper → `/usr/bin/maas-mcp-server` |
| Unix socket | `/run/maas/mcp.sock` | `$SNAP_DATA/mcp.sock` |
| Config file | `/etc/maas/mcp-server.env` | `$SNAP_DATA/mcp-server.env` |
| Enable | `systemctl enable maas-mcp-server` | `snap start maas.mcp-server` |
| Logs | `journalctl -u maas-mcp-server` | `snap logs maas.mcp-server` |
| External TCP port | 5275 (nginx fronts Unix socket) | 5275 (nginx fronts Unix socket) |
