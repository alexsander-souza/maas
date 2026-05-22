# Contract: Kernel Upload Endpoints (v3 API)

**Base path**: `/MAAS/a/v3/boot_assets/kernels`
**Auth**: OAuth2 Bearer / Django sessionid / Macaroon

---

## POST /boot_assets/kernels  (Step 1 — kernel binary)

Upload the kernel binary. Returns a `resource_id` for step 2. Asset is `complete: false` until the initrd is attached.

### Request

**Headers**:

| Header | Required | Validation | Example |
|---|---|---|---|
| `Content-Type` | Yes | `application/octet-stream` | |
| `Content-Length` | Yes | Positive integer | `8388608` |
| `x-name` | Yes | Non-empty; no Simplestreams collision | `ubuntu/noble` |
| `x-architecture` | Yes | Pattern `[a-zA-Z0-9]+/[a-zA-Z0-9.-]+` | `arm64/generic` |
| `x-kflavor` | Yes | One of: `generic`, `lowlatency`, `hwe`, or custom string ≤ 32 chars | `generic` |
| `x-sha256` | Yes | 64 hex chars | |

**Body**: Raw kernel binary.

**Permissions**: `CAN_EDIT_BOOT_ENTITIES` (Admin only)

### Response 201

```json
{
  "kind": "KernelAsset",
  "id": 17,
  "name": "ubuntu/noble",
  "architecture": "arm64",
  "sub_architecture": "generic",
  "kflavor": "generic",
  "version": "20260522",
  "complete": false,
  "_links": {
    "self":  { "href": "/MAAS/a/v3/boot_assets/kernels/17" },
    "initrd": { "href": "/MAAS/a/v3/boot_assets/kernels/17/initrd" }
  }
}
```

**400 Bad Request**: Missing header, SHA-256 mismatch, or architecture not usable.
**403 Forbidden**: Insufficient permissions.

---

## POST /boot_assets/kernels/{resource_id}/initrd  (Step 2 — initrd)

Attach the initrd to an existing (incomplete) kernel asset. After this call the asset becomes `complete: true` and is selectable for deployment.

### Request

**Headers**:

| Header | Required | Validation |
|---|---|---|
| `Content-Type` | Yes | `application/octet-stream` |
| `Content-Length` | Yes | Positive integer |
| `x-sha256` | Yes | 64 hex chars |

**Body**: Raw initrd binary.

**Permissions**: `CAN_EDIT_BOOT_ENTITIES`

### Response 200

```json
{
  "kind": "KernelAsset",
  "id": 17,
  "name": "ubuntu/noble",
  "architecture": "arm64",
  "sub_architecture": "generic",
  "kflavor": "generic",
  "version": "20260522",
  "complete": true,
  "files": [
    { "filename": "kernel",  "sha256": "...", "size": 8388608 },
    { "filename": "initrd",  "sha256": "...", "size": 4194304 }
  ],
  "_links": { "self": { "href": "/MAAS/a/v3/boot_assets/kernels/17" } }
}
```

**400 Bad Request**: SHA-256 mismatch; asset already complete (initrd already attached).
**404 Not Found**: No kernel asset with that `resource_id`, or asset already deleted.
**403 Forbidden**: Insufficient permissions.

---

## GET /boot_assets/kernels

List all uploaded kernel assets. Paginated.

### Query parameters

| Parameter | Type | Description |
|---|---|---|
| `name` | string (optional) | Exact match |
| `architecture` | string (optional) | Exact match |
| `kflavor` | string (optional) | Exact match |
| `page` | integer (default 1) | |
| `size` | integer (default 20) | |

**Permissions**: `CAN_VIEW_BOOT_ENTITIES`

### Response 200

```json
{
  "kind": "KernelAssetList",
  "items": [
    {
      "kind": "KernelAsset",
      "id": 17,
      "name": "ubuntu/noble",
      "architecture": "arm64",
      "sub_architecture": "generic",
      "kflavor": "generic",
      "version": "20260522",
      "complete": true,
      "_links": { "self": { "href": "/MAAS/a/v3/boot_assets/kernels/17" } }
    }
  ],
  "total": 1,
  "next": null
}
```

---

## GET /boot_assets/kernels/{id}

Get a single kernel asset with version history.

**Permissions**: `CAN_VIEW_BOOT_ENTITIES`

### Response 200

```json
{
  "kind": "KernelAsset",
  "id": 17,
  "name": "ubuntu/noble",
  "architecture": "arm64",
  "sub_architecture": "generic",
  "kflavor": "generic",
  "latest_version": "20260522",
  "versions": ["20260521", "20260522"],
  "complete": true,
  "files": [
    { "filename": "kernel", "sha256": "...", "size": 8388608 },
    { "filename": "initrd", "sha256": "...", "size": 4194304 }
  ],
  "created_at": "2026-05-21T08:00:00Z",
  "updated_at": "2026-05-22T14:00:00Z",
  "_links": { "self": { "href": "/MAAS/a/v3/boot_assets/kernels/17" } }
}
```

**404 Not Found**: No kernel asset with that ID.
