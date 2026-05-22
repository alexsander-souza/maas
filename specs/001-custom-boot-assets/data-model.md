# Data Model: Custom Boot Assets (MAASENG-5494)

No new tables. All changes are additive: two partial unique indexes, two nullable columns on `Node`, and use of the existing `extra` JSONB field on `BootResource`.

---

## Existing Tables (unchanged schema, new constraints)

### `maasserver_bootresource`

Existing columns used by this feature (no new columns):

| Column | Type | Purpose |
|---|---|---|
| `rtype` | `Integer` | `1` = UPLOADED; filters custom assets |
| `name` | `String(255)` | Asset name, e.g. `ubuntu/jammy` |
| `architecture` | `String(255)` | `{arch}/{subarch}`, e.g. `amd64/generic` |
| `kflavor` | `String(32)` nullable | Set for kernel assets; null for bootloaders |
| `bootloader_type` | `String(32)` nullable | Set for bootloader assets; null for kernels |
| `extra` | `JSONB` | Stores `primary_file` for bootloaders (see below) |

**`extra` JSONB schema for bootloaders**:
```json
{
  "primary_file": "shimx64.efi",
  "subarches": "generic"
}
```
`primary_file` is the operator-supplied entry-point filename used as the DHCP option 67 leaf filename. It is validated to match `^[A-Za-z0-9._-]{1,64}$` before storage.

**New partial unique indexes** (Alembic migration `0022_custom_boot_asset_indexes.py`):

```sql
-- Bootloader identity: one upload lineage per (name, architecture)
CREATE UNIQUE INDEX uq_bootresource_bootloader_identity
  ON maasserver_bootresource (name, architecture)
  WHERE rtype = <UPLOADED_INT> AND bootloader_type IS NOT NULL;

-- Kernel identity: one upload lineage per (name, architecture, kflavor)
CREATE UNIQUE INDEX uq_bootresource_kernel_identity
  ON maasserver_bootresource (name, architecture, kflavor)
  WHERE rtype = <UPLOADED_INT> AND kflavor IS NOT NULL AND bootloader_type IS NULL;
```

> The `UPLOADED_INT` value must be read from `BootResourceType.UPLOADED` at migration time and hard-coded in the migration file (Alembic migrations are immutable).

These indexes do not affect Simplestreams-synced resources (`rtype != UPLOADED`) or plain custom OS images (both `kflavor` and `bootloader_type` null).

---

### `maasserver_bootresourceset`

No changes. Existing columns:

| Column | Purpose for this feature |
|---|---|
| `version` | Date-stamped version string, e.g. `20260522` |
| `label` | Always `"uploaded"` for custom assets |
| `resource_id` | FK to `BootResource` |

**Completeness** is derived at read time by checking whether the set has both a `BOOT_KERNEL` and a `BOOT_INITRD` file (using the existing `BootResourceSetsService.is_usable()` logic).

---

### `maasserver_bootresourcefile`

No changes. Key columns:

| Column | Purpose for this feature |
|---|---|
| `filename` | Logical filename within set (e.g. `kernel`, `initrd`, `shimx64.efi`) |
| `filetype` | `BOOT_KERNEL`, `BOOT_INITRD`, or a bootloader-specific type |
| `filename_on_disk` | SHA-256-derived path under `image-storage/` (64 chars max) |
| `sha256` | Verified against operator-supplied value before record is committed |
| `size` | Byte length of the uploaded binary |

---

### `maasserver_bootresourcefilesync`

No changes. One record per `(file_id, region_id)` pair. Created immediately after upload to mark the originating region as having the file.

---

## Node Model Changes (`maasserver_node` table)

Three nullable columns added to the `maasserver_node` table via **Alembic migration** (Django migrations are legacy; Alembic is the sole migration tool).

| Column | SQLAlchemy type | Django field (ORM access) | Purpose |
|---|---|---|---|
| `custom_bootloader` | `String(255), nullable` | `CharField(max_length=255, blank=True, null=True)` | Asset name stored at deploy time, e.g. `ubuntu/jammy`. Null = use Simplestreams default. |
| `custom_kernel` | `String(255), nullable` | `CharField(max_length=255, blank=True, null=True)` | Kernel asset name, e.g. `ubuntu/noble`. Null = use Simplestreams default. |
| `custom_kernel_kflavor` | `String(32), server_default="generic"` | `CharField(max_length=32, blank=True, default="generic")` | Kernel flavour parsed from the `name:kflavor` deploy parameter, defaults to `generic`. Stored separately to avoid re-parsing at PXE boot time. |

> **Design note**: the `hwe_kernel` Node field was considered as a kflavor carrier but rejected: `hwe_kernel` maps to the Simplestreams `subarch` string and is bypassed entirely when `custom_kernel` is set. Reusing it would create a field whose meaning changes based on runtime context.

These fields are:
- Set by `MachineHandler.deploy()` when `custom_bootloader` / `custom_kernel` parameters are supplied
- Read by `get_boot_config()` (RPC) to resolve custom kernel paths at PXE boot time
- Read by `make_hosts_for_subnets()` (DHCP) to inject per-host `filename` directive

---

## Bootloader File Extraction Path

Bootloader tarballs are extracted to:
```
<image-storage>/custom-bootloaders/<sha256[:8]>/
```

The full DHCP option 67 value delivered to PXE clients is:
```
custom-bootloaders/<sha256[:8]>/<primary_file>
```

Example: `custom-bootloaders/ab12cd34/shimx64.efi` (37 chars — well within 128-byte limit).

The SHA-256 prefix is the first 8 hex characters of the SHA-256 of the uploaded tarball body, giving a collision-resistant, short, deterministic directory name.

---

## Entity Relationships (updated)

```
BootResource (rtype=UPLOADED, bootloader_type set)   ← Bootloader asset
BootResource (rtype=UPLOADED, kflavor set)           ← Kernel asset
    │
    └── BootResourceSet (version=YYYYMMDD[.N], label="uploaded")
            │
            └── BootResourceFile (filetype=BOOT_KERNEL or BOOT_INITRD or bootloader type)
                    │
                    └── BootResourceFileSync (file_id, region_id)

Node
├── custom_bootloader → resolves to BootResource at deploy/DHCP time
├── custom_kernel     → resolves to BootResource at PXE boot time (get_boot_config)
└── custom_kernel_kflavor
```

---

## State Transitions

### Bootloader Asset
```
[upload request received]
       │
       ▼
SHA-256 verify + tarball path-traversal check
       │ fail → HTTP 400, nothing written
       │ pass
       ▼
BootResource created/versioned → BootResourceSet created → tarball extracted
       │
       ▼
BootResourceFile created → BootResourceFileSync created
       │
       ▼
[available for deploy selection]
```

### Kernel Asset
```
Step 1: POST /boot_assets/kernels
    SHA-256 verify kernel binary
    BootResource created → BootResourceSet created → BootResourceFile (BOOT_KERNEL)
    Returns resource_id, complete=false

Step 2: POST /boot_assets/kernels/{resource_id}/initrd
    SHA-256 verify initrd binary
    BootResourceFile (BOOT_INITRD) added to same set
    complete=true → available for deploy selection
```

### Version Lifecycle
```
Upload to existing (name, architecture[, kflavor])
    → get_next_version_name() returns YYYYMMDD[.N]
    → new BootResourceSet created, previous sets retained
    → new deployments use latest complete set
    → running machines unaffected (their Rack has cached previous version)
```
