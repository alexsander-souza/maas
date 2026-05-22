# Developer Quickstart: Custom Boot Assets (MAASENG-5494)

This guide walks through setting up a local dev environment and verifying the full upload-to-deploy flow.

---

## Prerequisites

- MAAS dev environment running (`make run` or snap install with override)
- Access to a Region Controller with at least one usable architecture (`amd64/generic`)
- MAAS CLI configured: `maas login <profile> http://localhost:5240/MAAS/api/2.0/ <api-key>`

---

## Getting a v3 Bearer Token

The v3 API uses session-based Bearer tokens. Obtain one with:

```bash
MAAS_USER="admin"
MAAS_PWD='admin'
MAAS_URL="http://172.16.1.4:5240"

TOKEN=$(curl -s -X POST "$MAAS_URL/MAAS/a/v3/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "username=$MAAS_USER" \
  --data-urlencode "password=$MAAS_PWD" | jq -r '.access_token')
```

Use `$TOKEN` in subsequent requests as `-H "Authorization: Bearer $TOKEN"`.

---

## Running Tests

```bash
# Service layer + API
make test-py

# Legacy region (boot config, DHCP)
bin/test.region src/maasserver/rpc/tests/test_boot.py
bin/test.region src/maasserver/dhcpd/tests/test_config.py

# Repository layer (requires DB)
bin/pytest src/tests/maasservicelayer/db/repositories/test_bootresources.py

# All new handler tests
bin/pytest src/tests/maasapiserver/v3/api/public/handlers/test_boot_resources.py
```

---

## Applying Migrations

Alembic is the sole migration tool. Django migrations are legacy and frozen.

```bash
cd src && alembic -c maasservicelayer/db/alembic/alembic.ini upgrade head
```

---

## Local Upload Flow

### 1. Upload a bootloader tarball

```bash
# Create a minimal tarball for testing
mkdir -p /tmp/testbl && echo "fake-efi" > /tmp/testbl/shimx64.efi
tar -czf /tmp/bootloader.tar.gz -C /tmp/testbl .
SHA=$(sha256sum /tmp/bootloader.tar.gz | cut -d' ' -f1)
SIZE=$(stat -c%s /tmp/bootloader.tar.gz)

curl -X POST http://localhost:5240/MAAS/a/v3/boot_assets/bootloaders \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/octet-stream" \
  -H "Content-Length: $SIZE" \
  -H "x-name: ubuntu/jammy" \
  -H "x-architecture: amd64/generic" \
  -H "x-sha256: $SHA" \
  -H "x-primary-file: shimx64.efi" \
  --data-binary @/tmp/bootloader.tar.gz
```

Expected: `201 Created` with JSON including `"id"` and `"version"`.

### 2. Upload a kernel + initrd

```bash
# Fake kernel binary
dd if=/dev/urandom of=/tmp/vmlinuz bs=1M count=8
KSHA=$(sha256sum /tmp/vmlinuz | cut -d' ' -f1)
KSIZE=$(stat -c%s /tmp/vmlinuz)

# Step 1: upload kernel
RESOURCE_ID=$(curl -s -X POST http://localhost:5240/MAAS/a/v3/boot_assets/kernels \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/octet-stream" \
  -H "Content-Length: $KSIZE" \
  -H "x-name: ubuntu/noble" \
  -H "x-architecture: amd64/generic" \
  -H "x-kflavor: generic" \
  -H "x-sha256: $KSHA" \
  --data-binary @/tmp/vmlinuz | jq -r '.id')

echo "resource_id=$RESOURCE_ID, complete should be false"

# Step 2: attach initrd
dd if=/dev/urandom of=/tmp/initrd.img bs=1M count=4
ISHA=$(sha256sum /tmp/initrd.img | cut -d' ' -f1)
ISIZE=$(stat -c%s /tmp/initrd.img)

curl -X POST http://localhost:5240/MAAS/a/v3/boot_assets/kernels/$RESOURCE_ID/initrd \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/octet-stream" \
  -H "Content-Length: $ISIZE" \
  -H "x-sha256: $ISHA" \
  --data-binary @/tmp/initrd.img

echo "complete should now be true"
```

### 3. List assets with type filter

```bash
curl http://localhost:5240/MAAS/a/v3/custom_images?type=bootloader \
  -H "Authorization: Bearer $TOKEN"

curl http://localhost:5240/MAAS/a/v3/custom_images?type=kernel \
  -H "Authorization: Bearer $TOKEN"
```

### 4. Deploy with custom bootloader

```bash
SYSTEM_ID=abc123

maas <profile> machine deploy $SYSTEM_ID \
  custom_bootloader=ubuntu/jammy

# Verify DHCP config on Rack (requires Rack access)
# grep shimx64.efi /var/lib/maas/dhcp/dhcpd.conf
```

### 5. Deploy with custom kernel

```bash
maas <profile> machine deploy $SYSTEM_ID \
  custom_kernel=ubuntu/noble:generic
```

---

## Key Files

| File | What to look for |
|---|---|
| `src/maasapiserver/v3/api/public/handlers/boot_resources.py` | `BootAssetsHandler` (new); refactored `upload_custom_image` |
| `src/maasservicelayer/services/bootresources.py` | `upload_binary()`, `create_or_version_bootloader()`, `start_kernel_upload()`, `attach_initrd()`, `resolve_custom_kernel()` |
| `src/maasservicelayer/db/tables.py` | Two new partial unique indexes |
| `src/maasserver/models/node.py` | `custom_bootloader`, `custom_kernel`, `custom_kernel_kflavor` fields |
| `src/maasserver/rpc/boot.py` | Custom kernel check before `get_boot_filenames()` call (~line 794) |
| `src/maasserver/dhcp.py` | `boot_filename` key added to host dict in `make_hosts_for_subnets()` |
| `src/maasserver/dhcpd/config.py` | Per-host `filename` directive rendering |

---

## Debugging Tips

- **Upload rejected with 400 / SHA mismatch**: Verify `sha256sum` of the exact bytes sent (no newline padding).
- **Custom kernel not picked up at PXE**: Check `Node.custom_kernel` is set (`maas <p> machine read $SID | jq .custom_kernel`). Check `get_boot_config` returns custom paths via RPC log.
- **DHCP option 67 not set**: Confirm DHCP config was regenerated after deploy (`journalctl -u maas-dhcpd`). Check `boot_filename` is populated for the host in the generated config.
- **Asset shows `complete: false` after initrd upload**: Check that the initrd `POST` returned `200` (not `400`). Verify the `BootResourceFile` with `filetype=BOOT_INITRD` was created via the DB.
