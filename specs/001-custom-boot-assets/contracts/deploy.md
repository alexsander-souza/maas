# Contract: Updated Deploy Endpoint (v2 API)

**Endpoint**: `POST /api/2.0/machines/{system_id}/op-deploy`

Three optional `multipart/form-data` parameters are added. All existing parameters are unchanged.

---

## New Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `custom_bootloader` | string | — (omit to use default) | Name of the uploaded bootloader asset to use (e.g. `ubuntu/jammy`). Architecture is matched automatically to the machine's architecture. |
| `custom_kernel` | string | — (omit to use default) | Name and optional kflavor of the uploaded kernel asset, in the form `name` or `name:kflavor` (e.g. `ubuntu/noble` or `ubuntu/noble:lowlatency`). kflavor defaults to `generic` when omitted. Architecture is matched automatically. |

> **Note — why not reuse `hwe_kernel`?**
> `hwe_kernel` selects a Simplestreams kernel *version* (e.g. `hwe-22.04`) and is stored on the Node as the Simplestreams `subarch`. When `custom_kernel` is set the Simplestreams lookup is bypassed entirely, making `hwe_kernel` irrelevant in that code path. Reusing it to carry kflavor would overload the field with two incompatible meanings depending on runtime context. The `name:kflavor` encoding keeps the deploy API to two new parameters with no ambiguity.

---

## Validation (applied before deployment starts)

When `custom_bootloader` is provided:
1. Look up `BootResource` where `name = custom_bootloader`, `architecture = machine.architecture`, `rtype = UPLOADED`, `bootloader_type IS NOT NULL`.
2. If not found → **HTTP 400** `custom_bootloader "{name}" not found for architecture "{arch}"`.
3. If architecture mismatch → **HTTP 400** `custom_bootloader architecture does not match machine architecture`.
4. Store `machine.custom_bootloader = custom_bootloader`.
5. Trigger DHCP config update on the Rack Controller serving this machine.
6. Await DHCP update completion before powering on the machine.

When `custom_kernel` is provided:
1. Parse `name:kflavor` — if no `:` separator, kflavor defaults to `generic`.
2. Look up `BootResource` where `name = parsed_name`, `architecture = machine.architecture`, `rtype = UPLOADED`, `kflavor = parsed_kflavor`, `bootloader_type IS NULL`.
3. If not found → **HTTP 400** `custom_kernel "{name}:{kflavor}" not found`.
4. Resolve latest complete `BootResourceSet`. If incomplete → **HTTP 400** `custom_kernel asset is incomplete (missing initrd)`.
5. Store `machine.custom_kernel = name`, `machine.custom_kernel_kflavor = kflavor`.

---

## Response

Unchanged from existing deploy endpoint:

| Code | Meaning |
|---|---|
| `200 OK` | Deployment started successfully |
| `400 Bad Request` | Named asset not found, architecture mismatch, incomplete kernel, or existing validation error |
| `403 Forbidden` | Caller lacks deployment permission on the target machine |
| `404 Not Found` | Machine not found |

---

## PXE Boot Behaviour (downstream of this endpoint)

After a successful deploy call with custom assets:

- **Custom bootloader**: At PXE boot time, DHCP option 67 for this machine's MAC address will contain `custom-bootloaders/<sha256[:8]>/<primary_file>`. The Rack Controller serves the file on demand from the Region.
- **Custom kernel**: At PXE boot time, `get_boot_config` returns `kernel` and `initrd` paths from the custom asset instead of the Simplestreams paths.
- **Both absent**: Standard Simplestreams paths are used; no behaviour change.
