# Research: Custom Boot Assets (MAASENG-5494)

**Phase 0 findings** — all NEEDS CLARIFICATION resolved before Phase 1 design.

---

## 1. Boot Resource Storage Model

**Decision**: Reuse `BootResource → BootResourceSet → BootResourceFile → BootResourceFileSync` without new tables.

**Rationale**: The existing four-tier chain already handles identity (`BootResource`), versioning (`BootResourceSet`), file storage (`BootResourceFile`), and per-region sync tracking (`BootResourceFileSync`). Custom asset type is distinguished by existing nullable columns:

| Asset type | Distinguishing columns |
|---|---|
| Bootloader | `bootloader_type` is set; `kflavor` is null |
| Kernel | `kflavor` is set; `bootloader_type` is null |
| Custom OS image | Both null |

The `extra` JSONB column on `BootResource` stores the operator-supplied bootloader entry-point filename (`primary_file`) without a schema change.

**Alternatives considered**: New `CustomBootloaderAsset` and `CustomKernelAsset` tables — rejected because they would duplicate identity, versioning, and sync infrastructure and require separate handling in the Temporal file sync workflow.

---

## 2. Identity Uniqueness Enforcement

**Decision**: Two new partial unique indexes on `maasserver_bootresource`:

```sql
-- Bootloader identity: one lineage per (name, architecture) for uploaded bootloaders
CREATE UNIQUE INDEX uq_bootresource_bootloader_identity
  ON maasserver_bootresource (name, architecture)
  WHERE rtype = 1 AND bootloader_type IS NOT NULL;

-- Kernel identity: one lineage per (name, architecture, kflavor) for uploaded kernels
CREATE UNIQUE INDEX uq_bootresource_kernel_identity
  ON maasserver_bootresource (name, architecture, kflavor)
  WHERE rtype = 1 AND kflavor IS NOT NULL AND bootloader_type IS NULL;
```

(`rtype = 1` = `UPLOADED`; the exact integer must be confirmed from `BootResourceType` enum at implementation time.)

**Rationale**: Partial indexes scope the constraint to uploaded custom assets only, leaving Simplestreams-synced resources (`rtype != 1`) unaffected. The existing table-level unique constraint `(name, architecture, alias)` is not a conflict because `alias` is nullable and Simplestreams resources use it.

**Alternatives considered**: Application-level uniqueness check in the service — rejected because it introduces a TOCTOU race under concurrent uploads.

---

## 3. Upload Pipeline Extraction

**Decision**: Extract the upload pipeline from `upload_custom_image` (handler) into a new `BootResourceService.upload_binary()` method. All three upload paths (custom image, bootloader, kernel) call this shared method.

**Current handler responsibilities (to be moved to service)**:
1. Call `services.boot_resources.get_next_version_name()`
2. Create `BootResourceSet` via `services.boot_resource_sets.create()`
3. Calculate `filename_on_disk` via `services.boot_resource_files.calculate_filename_on_disk()`
4. Stream body to `AsyncLocalBootResourceFile` with SHA-256 verification
5. Create `BootResourceFile` record
6. Look up current region node (`MAAS_ID` → `NodeClauseFactory.with_system_id`)
7. `get_or_create` `BootResourceFileSync` record
8. Register Temporal `SYNC_BOOTRESOURCES_WORKFLOW_NAME` call

**Handler responsibilities remaining**:
- Parse request headers into `BootloaderUploadRequest` / `KernelUploadRequest`
- Enforce permissions via `check_permissions`
- Call service method
- Build and return the response model

**New service API sketch**:
```python
async def upload_binary(
    self,
    stream: AsyncIterator[bytes],
    sha256: str,
    size: int,
    resource_id: int,
    filetype: BootResourceFileType,
    filename: str,
) -> BootResourceFile: ...

async def create_or_version_bootloader(
    self,
    name: str,
    architecture: str,
    primary_file: str,
) -> BootResource: ...

async def start_kernel_upload(
    self,
    name: str,
    architecture: str,
    kflavor: str,
) -> BootResource: ...
```

---

## 4. Bootloader Tarball Extraction and DHCP Option 67 Path

**Decision**: Extract bootloader tarballs into `image-storage/custom-bootloaders/<sha256[:8]>/` to keep the DHCP option 67 value short. The full option 67 value is `custom-bootloaders/<sha256[:8]>/<primary_file>`, which is well under 128 bytes for any reasonable filename.

**Rationale**: DHCP option 67 (the BOOTP `file` field) is limited to 128 bytes. The image-storage base path is stripped from the TFTP-served path by the Rack Controller. Using a short, deterministic prefix based on SHA-256 of the tarball body means the extraction path is stable across re-uploads of the same tarball.

**Path-traversal safety**: Before extraction, every tarball entry must be checked for:
- Absolute paths (`/` prefix)
- `..` components
- Symlinks resolving outside the extraction directory

Entries failing these checks cause the upload to be rejected with HTTP 400 before any files are written.

**`primary_file` validation**: The operator-supplied bootloader entry-point filename must match `^[A-Za-z0-9._-]{1,64}$` (no path separators, no shell metacharacters, max 64 chars). This is enforced at request parsing time.

**Alternatives considered**: Using the full SHA-256 as the extraction directory — rejected because that alone is 64 chars, leaving only 63 chars for the DHCP base path prefix and filename.

---

## 5. Kernel Completeness Flag

**Decision**: Use `BootResourceSet` completeness semantics: a set is "complete" when it has both a `BOOT_KERNEL` file and a `BOOT_INITRD` file. The existing `BootResourceSetsService.is_usable()` method checks this. The API response's `complete` field is derived from this check at read time rather than stored explicitly.

**Two-step upload flow**:
1. `POST /boot_assets/kernels` → creates `BootResource` + `BootResourceSet` + `BootResourceFile` (kernel only) → returns `resource_id`
2. `POST /boot_assets/kernels/{resource_id}/initrd` → creates second `BootResourceFile` (initrd) on same set → asset becomes complete

**Rationale**: Deriving `complete` at read time avoids a separate boolean column that could go stale. The `resource_id` returned in step 1 is the `BootResource.id`.

---

## 6. Custom Kernel Selection at PXE Boot Time

**Decision**: Add `custom_kernel` (str, nullable) and `custom_kernel_kflavor` (str, default `"generic"`) to the Django `Node` model. In `get_boot_config` (RPC), check these fields before calling `get_boot_filenames()`.

**Resolution logic**:
```python
if machine.custom_kernel:
    resource = BootResource.objects.get_one(
        name=machine.custom_kernel,
        architecture=f"{arch}/{machine.custom_kernel_kflavor}",
        rtype=UPLOADED, kflavor__isnull=False
    )
    if resource:
        latest_set = resource.get_latest_complete_set()
        if latest_set:
            kernel = latest_set.get_file(BOOT_KERNEL).filename_on_disk
            initrd = latest_set.get_file(BOOT_INITRD).filename_on_disk
            # return custom paths
    # else fall through to standard get_boot_filenames()
```

If the stored asset has been deleted or its latest set is incomplete, the code falls back to the standard Simplestreams lookup and logs a warning.

**Alternatives considered**: Storing `boot_resource_id` FK on Node — rejected for this iteration (version tracking FK is out of scope per spec). Name-based lookup is sufficient.

---

## 7. DHCP Per-Host Bootloader Filename Override

**Decision**: Add a `boot_filename` key to the host dict produced by `make_hosts_for_subnets()`. Update the DHCP host block Tempita template to render `filename "{{host.boot_filename}}";` when the key is present. The value is derived from the machine's `custom_bootloader` field resolved to the `BootResource.extra["primary_file"]` and short extraction path.

**Value format**: `custom-bootloaders/<sha256[:8]>/<primary_file>` (e.g. `custom-bootloaders/ab12cd34/shimx64.efi`)

**Integration point**: `make_hosts_for_subnets()` already queries `Node` objects via `StaticIPAddress`. A check for `node.custom_bootloader` is added per-interface. The DHCP update (triggering Temporal DHCP config regen) must complete before machine power-on — this is enforced in the deploy flow by awaiting the DHCP update before calling the power-on action.

**Alternatives considered**: Using `dhcp_snippets` to inject `filename "...";` — rejected because snippets are user-defined and mixing them with system-generated directives would complicate auditing and testing.

---

## 8. Deploy-Time Asset Selection (v2 Endpoint)

**Decision**: Add three optional `POST` parameters to `MachineHandler.deploy()`:
- `custom_bootloader` (str): name of bootloader asset (`ubuntu/jammy`)
- `custom_kernel` (str): name of kernel asset
- `custom_kernel_kflavor` (str, default `"generic"`): kernel flavour

**Validation at deploy time**:
1. Resolve bootloader: `BootResource` with matching `name` + machine `architecture` + `rtype=UPLOADED` + `bootloader_type IS NOT NULL`
2. Architecture mismatch → HTTP 400
3. Asset not found → HTTP 400
4. Kernel asset incomplete (latest set not usable) → HTTP 400
5. Store selection on `Node.custom_bootloader` / `Node.custom_kernel` / `Node.custom_kernel_kflavor`
6. Trigger DHCP update (if custom bootloader)
7. Power on machine

---

## 9. File Sync Between Regions

**Decision**: Reuse the existing `SYNC_BOOTRESOURCES_WORKFLOW_NAME` Temporal workflow, already triggered at the end of the upload pipeline. No changes needed to the sync workflow itself.

**Rack distribution**: Racks pull on demand from the Region via the existing boot resource HTTP endpoint. No new caching mechanism required. Custom assets are accessible through the same path as Simplestreams assets.
