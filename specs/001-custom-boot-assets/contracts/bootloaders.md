# Contract: Boot Asset Upload Endpoints (v3 API)

**Base path**: `/MAAS/a/v3/boot_assets`
**Auth**: OAuth2 Bearer / Django sessionid / Macaroon (existing MAAS auth)

---

## POST /boot_assets/bootloaders

Upload a bootloader tarball. Creates a new `BootResource` (or a new version of an existing one identified by `name + architecture`).

### Request

**Headers** (all required unless noted):

| Header | Required | Validation | Example |
|---|---|---|---|
| `Content-Type` | Yes | Must be `application/octet-stream` | `application/octet-stream` |
| `Content-Length` | Yes | Positive integer | `4194304` |
| `x-name` | Yes | Non-empty; must not collide with Simplestreams names | `ubuntu/jammy` |
| `x-architecture` | Yes | Pattern `[a-zA-Z0-9]+/[a-zA-Z0-9.-]+`; must be a usable arch | `amd64/generic` |
| `x-sha256` | Yes | Exactly 64 hex chars | `a1b2c3...` |
| `x-primary-file` | Yes | Pattern `^[A-Za-z0-9._-]{1,64}$` (no separators) | `shimx64.efi` |

**Body**: Raw binary content of the tarball (`.tar.gz`, `.tar.xz`, or `.tar.bz2`).

**Permissions**: `CAN_EDIT_BOOT_ENTITIES` (Admin only)

### Responses

**201 Created**:
```json
{
  "kind": "BootloaderAsset",
  "id": 42,
  "name": "ubuntu/jammy",
  "architecture": "amd64",
  "sub_architecture": "generic",
  "version": "20260522",
  "primary_file": "shimx64.efi",
  "files": [
    { "filename": "shimx64.efi", "sha256": "a1b2...", "size": 1048576 }
  ],
  "_links": { "self": { "href": "/MAAS/a/v3/boot_assets/bootloaders/42" } }
}
```

**400 Bad Request** (any of):
- Missing required header
- `x-primary-file` contains path separators or invalid characters
- SHA-256 mismatch between header and received body
- Tarball contains path-traversal entries or external symlinks
- Architecture not in usable architectures list

**403 Forbidden**: Caller lacks `CAN_EDIT_BOOT_ENTITIES`

---

## GET /boot_assets/bootloaders

List all uploaded bootloader assets. Paginated.

### Request

**Query parameters**:

| Parameter | Type | Description |
|---|---|---|
| `name` | string (optional) | Exact match on asset name |
| `architecture` | string (optional) | Exact match on `arch/subarch` |
| `page` | integer (default 1) | Page number |
| `size` | integer (default 20) | Items per page |

**Permissions**: `CAN_VIEW_BOOT_ENTITIES` (any authenticated user)

### Response 200

```json
{
  "kind": "BootloaderAssetList",
  "items": [
    {
      "kind": "BootloaderAsset",
      "id": 42,
      "name": "ubuntu/jammy",
      "architecture": "amd64",
      "sub_architecture": "generic",
      "version": "20260522",
      "primary_file": "shimx64.efi",
      "_links": { "self": { "href": "/MAAS/a/v3/boot_assets/bootloaders/42" } }
    }
  ],
  "total": 1,
  "next": null
}
```

---

## GET /boot_assets/bootloaders/{id}

Get a single bootloader asset with full version history.

**Permissions**: `CAN_VIEW_BOOT_ENTITIES`

### Response 200

```json
{
  "kind": "BootloaderAsset",
  "id": 42,
  "name": "ubuntu/jammy",
  "architecture": "amd64",
  "sub_architecture": "generic",
  "latest_version": "20260522",
  "versions": ["20260520", "20260522"],
  "primary_file": "shimx64.efi",
  "files": [
    { "filename": "shimx64.efi", "sha256": "a1b2...", "size": 1048576 }
  ],
  "created_at": "2026-05-20T10:00:00Z",
  "updated_at": "2026-05-22T14:30:00Z",
  "_links": { "self": { "href": "/MAAS/a/v3/boot_assets/bootloaders/42" } }
}
```

**404 Not Found**: No bootloader asset with that ID.
