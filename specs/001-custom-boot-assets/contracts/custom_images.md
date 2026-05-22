# Contract: Updated Custom Images Endpoint (v3 API)

**Endpoint**: `GET /MAAS/a/v3/custom_images`

This endpoint is extended with new filter parameters and a `type` discriminator field on each response item. Existing behaviour is unchanged when the new parameters are omitted.

---

## New Query Parameters

| Parameter | Type | Values | Description |
|---|---|---|---|
| `type` | string (optional) | `bootloader`, `kernel`, `image` | Filter by asset type. Omit to return all uploaded resources. |
| `name` | string (optional) | any | Exact match on `BootResource.name` |
| `architecture` | string (optional) | any | Exact match on `BootResource.architecture` |
| `kflavor` | string (optional) | any | Exact match on `BootResource.kflavor`. Only meaningful with `type=kernel`. |

**Type discrimination logic** (server-side, derived from DB columns):

| `bootloader_type` | `kflavor` | Returned `type` |
|---|---|---|
| set (non-null) | null | `"bootloader"` |
| null | set (non-null) | `"kernel"` |
| null | null | `"image"` |

---

## Updated Response Schema

Each item in `items` now carries a `type` field:

```json
{
  "kind": "ImageList",
  "items": [
    {
      "kind": "Image",
      "id": 42,
      "name": "ubuntu/jammy",
      "architecture": "amd64",
      "sub_architecture": "generic",
      "type": "bootloader",
      "_links": { "self": { "href": "/MAAS/a/v3/custom_images/42" } }
    },
    {
      "kind": "Image",
      "id": 17,
      "name": "ubuntu/noble",
      "architecture": "arm64",
      "sub_architecture": "generic",
      "type": "kernel",
      "_links": { "self": { "href": "/MAAS/a/v3/custom_images/17" } }
    },
    {
      "kind": "Image",
      "id": 5,
      "name": "custom/myimage",
      "architecture": "amd64",
      "sub_architecture": "generic",
      "type": "image",
      "_links": { "self": { "href": "/MAAS/a/v3/custom_images/5" } }
    }
  ],
  "total": 3,
  "next": null
}
```

---

## Unchanged Endpoints

The following endpoints are unmodified by this feature:

| Method | Path | Notes |
|---|---|---|
| `GET` | `/custom_images/{id}` | Detail view; no type discriminator added in this iteration |
| `DELETE` | `/custom_images/{id}` | Deletes all versions of the asset identity |
| `DELETE` | `/custom_images` | Bulk delete by `id` list |
