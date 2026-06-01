# Quickstart: FIPS-Compliant MAAS Development & Testing Guide

**Feature**: FIPS-Compliant MAAS
**Branch**: `fips_compliance`
**Date**: 2026-05-27

---

## Overview

This guide covers how to set up a development environment to work on FIPS compliance features in MAAS, and how to run FIPS compliance tests.

---

## Prerequisites

### Non-FIPS Development (Standard Host)

Most code changes can be developed on a standard (non-FIPS) Ubuntu 22.04/24.04 developer host. FIPS-specific code paths are gated behind `is_fips_enabled()`, so they can be unit-tested by mocking the return value.

```bash
# Standard dev environment
make install-dependencies
make build
make test-py
```

### FIPS Integration Testing (Requires FIPS Host)

FIPS integration tests must run on a **FIPS-enabled Ubuntu 24.04 LTS host** with Ubuntu Pro subscription.

```bash
# On the FIPS host: verify FIPS mode is active
cat /proc/sys/crypto/fips_enabled
# Expected output: 1

# Install ubuntu-fips packages (requires Ubuntu Pro)
sudo apt install ubuntu-fips ubuntu-fips-cloudimg-updates
sudo reboot  # Required to activate FIPS kernel
```

---

## Development Setup

### 1. Clone the Feature Branch

```bash
git clone https://github.com/alexsander-souza/maas.git
cd maas
git checkout fips_compliance
```

### 2. Install Python Dependencies

```bash
make install-dependencies
# or
pip install -e ".[dev]"
```

### 3. Running Unit Tests (Non-FIPS Host)

All unit tests mock the FIPS detection function:

```python
# In your test:
from unittest.mock import patch

@patch("maascommon.fips.is_fips_enabled", return_value=True)
def test_fips_behavior(mock_fips):
    # Test FIPS-active code paths
    ...
```

Run the full unit test suite:

```bash
make test-py
# Or specific FIPS tests:
python -m pytest tests/maascommon/test_fips.py -v
python -m pytest tests/maasservicelayer/services/test_fips.py -v
python -m pytest tests/maasapiserver/test_root_fips.py -v
python -m pytest tests/provisioningserver/drivers/power/test_ipmi_fips.py -v
```

### 4. Running Go Tests

```bash
cd src/maasagent
make test
# Or specifically for FIPS-related Go code:
go test ./internal/fips/... -v
go test ./internal/dhcpd/omapi/... -v
```

---

## Key Files to Understand

### FIPS Detection Utility
- `src/maascommon/fips.py` — Core FIPS detection; `is_fips_enabled()`, `FIPSSSHConfig`, algorithm constants

### Service Layer
- `src/maasservicelayer/services/fips.py` — `FIPSService`; wraps detection for API layer

### API Handler
- `src/maasapiserver/v3/api/public/handlers/root.py` — `fips_active` field in system status response

### SSH Configuration (Paramiko)
- `src/provisioningserver/drivers/power/hmc.py` — SSH paramiko with FIPS cipher pinning
- `src/provisioningserver/drivers/power/wedge.py` — SSH paramiko with FIPS cipher pinning
- `src/provisioningserver/drivers/power/mscm.py` — SSH paramiko with FIPS cipher pinning

### IPMI Cipher Enforcement
- `src/provisioningserver/drivers/power/ipmi.py` — FIPS cipher suite 17 enforcement

### TLS Context Fix
- `src/provisioningserver/drivers/hardware/vmware.py` — Modern TLS context (replaces `ssl.PROTOCOL_SSLv23`)

### Go Agent FIPS
- `src/maasagent/internal/fips/fips.go` — Go FIPS detection
- `src/maasagent/internal/dhcpd/omapi/authenticator.go` — HMAC-SHA256 replacement for HMAC-MD5

### Logging
- `src/maascommon/logging/security.py` — FIPS security log event constants

### Data Model
- `specs/001-fips-compliant-maas/data-model.md` — Entity definitions

---

## Local FIPS Testing Without a FIPS Kernel

For unit testing, mock `is_fips_enabled()`:

```python
# conftest.py or individual test
import pytest
from unittest.mock import patch

@pytest.fixture
def fips_enabled():
    with patch("maascommon.fips._FIPS_ENABLED", True):
        yield True

@pytest.fixture
def fips_disabled():
    with patch("maascommon.fips._FIPS_ENABLED", False):
        yield False
```

---

## Running FIPS Integration Tests

### Setup: FIPS VM

```bash
# 1. Launch a fresh Ubuntu 24.04 LTS VM (cloud or KVM)
# 2. Attach Ubuntu Pro subscription
sudo pro attach <token>

# 3. Enable FIPS
sudo pro enable fips-updates
sudo reboot

# 4. Verify FIPS mode
cat /proc/sys/crypto/fips_enabled   # Should output: 1
openssl version                     # Should show FIPS in build flags
```

### Install MAAS (Standard Package)

```bash
sudo add-apt-repository ppa:maas/latest
sudo apt update
sudo apt install maas

# Initialise MAAS
sudo maas init region+rack --database-uri "postgres://maas:maas@localhost/maas"
```

### Run FIPS Integration Tests

```bash
python -m pytest tests/integration/test_fips_compliance.py -v \
    --fips-host=true \
    --maas-url=http://localhost:5240/MAAS \
    --maas-api-key=<admin-api-key>
```

### Integration Test Coverage

The integration test suite (`tests/integration/test_fips_compliance.py`) verifies:

1. **Startup**: MAAS logs `fips_mode: true` in service journal
2. **API**: `GET /api/v3/` returns `fips_active: true`
3. **SSH**: All SSH connections negotiated with FIPS cipher suites (checked via debug logs)
4. **TLS**: All MAAS TLS endpoints use TLS 1.2+ and FIPS-approved ciphers (checked via `sslscan`)
5. **IPMI**: Cipher suite selection rejects non-17 suites in FIPS mode
6. **Image download**: Provisioning workflow completes without FIPS errors
7. **Go agent**: maas-agent starts with `fips_mode: true` logged
8. **No violations**: Zero `algorithm not permitted` errors in logs after 10 minutes of normal operation

---

## Verifying FIPS Compliance Manually

### Check MAAS Startup Log

```bash
journalctl -u maas-regiond | grep fips_mode
# Expected: {"event": "fips_mode_detected", "fips_mode": true, ...}
```

### Check API System Status

```bash
curl -s http://localhost:5240/MAAS/api/v3/ | python3 -m json.tool | grep fips
# Expected: "fips_active": true
```

### Inspect TLS Cipher Suites

```bash
sslscan localhost:5240
# Should show only TLS 1.2/1.3 with FIPS-approved ciphers
# No RC4, DES, EXPORT, MD5-signed certs
```

### Inspect SSH Algorithm Negotiation

```bash
ssh -vvv maas@<rack-controller-ip> 2>&1 | grep -E "cipher|kex|mac|host key"
# Should show only FIPS-approved algorithms (aes256-ctr, hmac-sha2-256, ecdh-sha2-nistp256)
```

### Check for FIPS Audit Events

```bash
# If auditd is installed:
sudo ausearch -m CRYPTO_FAILURE 2>/dev/null
# Expected: no output (no FIPS violations)
```

---

## Commit Guidelines

Follow the MAAS Conventional Commits spec with scopes:

```bash
# FIPS detection utility (maascommon)
git commit -m "feat(common): add FIPS mode detection utility from /proc/sys/crypto/fips_enabled"

# API layer change
git commit -m "feat(api): expose fips_active field in system status endpoint"

# Service layer
git commit -m "feat(service): add FIPSService for FIPS runtime state management"

# Power driver fix
git commit -m "fix(provisioning): enforce IPMI cipher suite 17 in FIPS mode"

# Go agent
git commit -m "feat(agent): add FIPS mode detection and HMAC-SHA256 OMAPI authenticator"

# Tests
git commit -m "test(api): add test coverage for fips_active in root handler"

# CI
git commit -m "ci: add FIPS integration test job for standard MAAS package on FIPS Ubuntu host"
```

---

## Troubleshooting

### "Algorithm not permitted" errors in MAAS logs

- **Cause**: A library is attempting a non-FIPS algorithm.
- **Check**: `journalctl -u maas-regiond | grep -i "algorithm\|fips\|crypto"`.
- **Fix**: Identify the call site; add FIPS-conditional algorithm selection.

### paramiko handshake fails on FIPS host

- **Cause**: Remote SSH server only advertises non-FIPS algorithms.
- **Expected behaviour**: MAAS should log `FIPS_crypto_error` and reject the connection.
- **Resolution for testing**: Use an SSH server that supports FIPS-approved algorithms.

### MAAS refuses to start with FIPSConfigurationError

- **Cause**: `MD5PasswordHasher` is in `PASSWORD_HASHERS` in Django settings.
- **Fix**: Remove `MD5PasswordHasher` from `djangosettings/development.py` (or active settings).

### Go agent: OMAPI authentication fails

- **Cause**: HMAC-MD5 path is being used; GOFIPS=1 is blocking MD5.
- **Fix**: Ensure the FIPS-conditional HMAC-SHA256 path is active (`fips.IsEnabled()` returns true).

### Temporal server TLS errors on FIPS host

- **Cause**: Temporal binary was not built with `-tags boringcrypto`, or `GOFIPS=1` is not set.
- **Fix**: Rebuild Temporal binary with `go build -tags boringcrypto`; set `GOFIPS=1` in the service unit file.

---

## Architecture Reference

See also:
- `specs/001-fips-compliant-maas/plan.md` — Implementation plan
- `specs/001-fips-compliant-maas/research.md` — Detailed technical research findings
- `specs/001-fips-compliant-maas/data-model.md` — Entity definitions and state model
- `specs/001-fips-compliant-maas/contracts/api-fips-impact-reference.md` — API behaviour changes under FIPS
- `.specify/memory/constitution.md` — MAAS project architecture principles
- `AGENTS.md` — Agent module boundaries
