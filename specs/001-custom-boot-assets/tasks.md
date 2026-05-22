---
description: "Task list for Custom Boot Assets (MAASENG-5494)"
---

# Tasks: Custom Boot Assets

**Feature**: MAASENG-5494 — Operator-supplied bootloaders and kernels as first-class MAAS assets
**Branch**: `custom-boot-assets`
**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Data Model**: [data-model.md](data-model.md)

**Tech Stack**: Python 3.14, FastAPI + Pydantic (v3 API), SQLAlchemy Core (repositories), Django + Twisted (legacy region), Alembic (migrations), Tempita (DHCP templates)

**Test commands**:
- `make test-py` — service layer + v3 API handler tests
- `bin/test.region <test_path>` — legacy region tests (boot RPC, DHCP, deploy endpoint)
- `bin/pytest <test_path>` — repository layer tests (requires DB)
- `cd src && alembic -c maasservicelayer/db/alembic/alembic.ini upgrade head` — apply migrations

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[US1–US5]**: Maps to user story (from spec.md)

---

## Phase 1: Setup (Schema & Infrastructure)

**Purpose**: Apply DB schema changes and proxy configuration that every user story depends on.

- [X] T001 Create Alembic migration `0022_custom_boot_asset_indexes.py` adding two partial unique indexes on `maasserver_bootresource` (`uq_bootresource_bootloader_identity` and `uq_bootresource_kernel_identity`) per data-model.md in `src/maasservicelayer/db/alembic/versions/0022_custom_boot_asset_indexes.py`
- [X] T002 Create Alembic migration `0023_node_custom_boot_fields.py` adding nullable columns `custom_bootloader` (String 255), `custom_kernel` (String 255), and `custom_kernel_kflavor` (String 32, server_default `"generic"`) to `maasserver_node` per data-model.md in `src/maasservicelayer/db/alembic/versions/0023_node_custom_boot_fields.py`
- [X] T003 [P] Increase nginx/reverse proxy body size limit for the `/MAAS/a/v3/boot_assets` location to accommodate bootloader tarballs and kernel binaries (update the relevant nginx config template or Snap/package config for the Region Controller)

**Checkpoint**: `alembic upgrade head` applies cleanly; both indexes and Node columns exist in the DB; proxy accepts large uploads to `/boot_assets`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core service-layer and repository infrastructure that ALL upload user stories require. No user story work can begin until this phase is complete.

**⚠️ CRITICAL**: Phase 3 (US1) and Phase 4 (US2) both depend on T004 and T005. T006 is required by Phase 6 (US4).

- [X] T004 Refactor `upload_custom_image` handler to extract the binary upload pipeline (file streaming, SHA-256 verification, disk storage via `AsyncLocalBootResourceFile`, `BootResourceSet` creation, `BootResourceFile` record creation, originating-region `BootResourceFileSync` creation, and `SYNC_BOOTRESOURCES_WORKFLOW_NAME` Temporal workflow trigger) into `BootResourceService.upload_binary(stream, sha256, size, resource_id, filetype, filename)` in `src/maasservicelayer/services/bootresources.py`; update the existing `upload_custom_image` handler in `src/maasapiserver/v3/api/public/handlers/boot_resources.py` to call `upload_binary()` instead of inline logic
- [X] T005 [P] Add `bootloader_type IS NOT NULL` and `kflavor IS NOT NULL` / `bootloader_type IS NULL` discriminator `ClauseFactory` filter methods to `BootResourceRepository` in `src/maasservicelayer/db/repositories/bootresources.py` to enable typed queries used by list and detail endpoints
- [X] T006 [P] Add `custom_bootloader`, `custom_kernel`, and `custom_kernel_kflavor` Django `CharField` fields to `Node` model in `src/maasserver/models/node.py` (nullable, blank=True; `custom_kernel_kflavor` default `"generic"`) to match the Alembic migration in T002

**Checkpoint**: `upload_custom_image` continues to work via the refactored service method; repository discriminator filters can be exercised in unit tests; Node model fields are accessible from the ORM.

---

## Phase 3: User Story 1 — Upload Custom Bootloader (Priority: P1) 🎯 MVP

**Goal**: Admin users can upload a bootloader tarball (`.tar.gz`, `.tar.xz`, `.tar.bz2`) via `POST /boot_assets/bootloaders`. MAAS validates the SHA-256, checks for path-traversal entries, extracts the tarball to a short deterministic path, versions the asset, and exposes it via GET endpoints.

**Independent Test**: Upload a tarball via `POST /boot_assets/bootloaders` with correct headers; verify `201 Created` response with `id`, `version`, and `primary_file`; verify the asset appears in `GET /boot_assets/bootloaders` with the correct name and architecture; verify re-upload to the same identity creates a new version. See quickstart.md §1 for curl commands.

### Implementation for User Story 1

- [X] T007 [P] [US1] Add `BootloaderUploadRequest` Pydantic model parsing `x-name`, `x-architecture`, `x-sha256`, and `x-primary-file` headers with validation rules (`x-primary-file` must match `^[A-Za-z0-9._-]{1,64}$`) per contracts/bootloaders.md in `src/maasapiserver/v3/api/public/models/requests/boot_resources.py`
- [X] T008 [P] [US1] Add `BootloaderDetailResponse` and `BootloaderAssetListResponse` Pydantic response models (fields: `kind`, `id`, `name`, `architecture`, `sub_architecture`, `version`/`latest_version`, `versions`, `primary_file`, `files`, `created_at`, `updated_at`, `_links`) per contracts/bootloaders.md in `src/maasapiserver/v3/api/public/models/responses/boot_resources.py`
- [X] T009 [US1] Implement `BootResourceService.create_or_version_bootloader(name, architecture, primary_file, stream, sha256, size)` in `src/maasservicelayer/services/bootresources.py`: validate `primary_file` pattern; call `get_next_version_name()`; create/version the `BootResource`; call `upload_binary()` (from T004) which handles tarball streaming with SHA-256 verification; extract tarball to `<image-storage>/custom-bootloaders/<sha256[:8]>/` enforcing path-traversal safety (reject absolute paths, `..` components, symlinks resolving outside extraction dir); store `primary_file` in `BootResource.extra["primary_file"]`
- [X] T010 [US1] Implement `BootAssetsHandler` bootloader routes — `POST /boot_assets/bootloaders` (calls `create_or_version_bootloader`, returns 201), `GET /boot_assets/bootloaders` (paginated list with `name`/`architecture` filter params), and `GET /boot_assets/bootloaders/{id}` (full detail with version history) — in `src/maasapiserver/v3/api/public/handlers/boot_resources.py`; enforce `CAN_EDIT_BOOT_ENTITIES` on POST and `CAN_VIEW_BOOT_ENTITIES` on GET via `check_permissions`
- [X] T011 [US1] Register `BootAssetsHandler` bootloader routes (`/boot_assets/bootloaders`, `/boot_assets/bootloaders/{id}`) in the v3 API public router (the file that wires handlers to FastAPI routes)
- [X] T012 [P] [US1] Write handler tests covering: bootloader upload returns 201 with correct body; SHA-256 mismatch returns 400; path-traversal tarball entry returns 400; missing `x-primary-file` returns 400; missing `CAN_EDIT_BOOT_ENTITIES` returns 403; list endpoint returns paginated results; detail endpoint returns version history in `src/tests/maasapiserver/v3/api/public/handlers/test_boot_resources.py`
- [X] T013 [P] [US1] Write service tests for `create_or_version_bootloader()` covering: new asset creation; second upload to same identity increments version; path-traversal symlink rejected before any DB write; `primary_file` with path separator rejected; SHA-256 mismatch causes rollback in `src/tests/maasservicelayer/services/test_bootresources.py`
- [X] T014 [P] [US1] Write repository tests asserting the `uq_bootresource_bootloader_identity` partial unique index raises `IntegrityError` on duplicate `(name, architecture)` for `rtype=UPLOADED, bootloader_type IS NOT NULL`, and does NOT raise for Simplestreams resources with the same `name`/`architecture` in `src/tests/maasservicelayer/db/repositories/test_bootresources.py`

**Checkpoint**: `POST /boot_assets/bootloaders` + `GET /boot_assets/bootloaders` + `GET /boot_assets/bootloaders/{id}` all functional. Run `make test-py` and confirm Phase 3 tests pass.

---

## Phase 4: User Story 2 — Upload Custom Kernel and Initrd (Priority: P1)

**Goal**: Admin users upload a kernel binary (step 1, returns `resource_id`, `complete: false`) and then attach an initrd (step 2, returns `complete: true`). Asset is not selectable for deployment until both steps complete. Kernel assets are versioned by `name + architecture + kflavor`.

**Independent Test**: Complete the two-step upload via quickstart.md §2 curl commands; after step 1 verify `complete: false`; after step 2 verify `complete: true`; verify uploading the same identity again creates a new version. Test SHA-256 mismatch on each step independently.

> **Note**: T015–T022 can proceed in parallel with T007–T014 once T004 and T005 are complete (all operate on different files or additive sections of the same files).

### Implementation for User Story 2

- [x] T015 [P] [US2] Add `KernelUploadRequest` Pydantic model parsing `x-name`, `x-architecture`, `x-kflavor` (≤ 32 chars), and `x-sha256` headers per contracts/kernels.md in `src/maasapiserver/v3/api/public/models/requests/boot_resources.py`
- [x] T016 [P] [US2] Add `KernelResponse` (for list items and step-1 response) and `KernelDetailResponse` (with `versions`, `latest_version`, `complete`, `files`, `created_at`, `updated_at`, `_links.initrd`) Pydantic response models per contracts/kernels.md in `src/maasapiserver/v3/api/public/models/responses/boot_resources.py`
- [x] T017 [US2] Implement `BootResourceService.start_kernel_upload(name, architecture, kflavor, stream, sha256, size)` and `BootResourceService.attach_initrd(resource_id, stream, sha256, size)` in `src/maasservicelayer/services/bootresources.py`: `start_kernel_upload` creates/versions `BootResource` (kflavor set, bootloader_type null) and calls `upload_binary()` for the `BOOT_KERNEL` file; `attach_initrd` validates the asset exists and is incomplete (rejects if `is_usable()` already true), calls `upload_binary()` for the `BOOT_INITRD` file, then derives `complete` from `BootResourceSetsService.is_usable()`
- [x] T018 [US2] Implement kernel routes in `BootAssetsHandler` — `POST /boot_assets/kernels` (step 1, returns 201), `POST /boot_assets/kernels/{resource_id}/initrd` (step 2, returns 200 with `complete: true`), `GET /boot_assets/kernels` (paginated list with `name`/`architecture`/`kflavor` filter params), `GET /boot_assets/kernels/{id}` (full detail with version history) — in `src/maasapiserver/v3/api/public/handlers/boot_resources.py`; enforce `CAN_EDIT_BOOT_ENTITIES` on POST, `CAN_VIEW_BOOT_ENTITIES` on GET
- [x] T019 [US2] Register kernel routes (`/boot_assets/kernels`, `/boot_assets/kernels/{resource_id}/initrd`, `/boot_assets/kernels/{id}`) in the v3 API public router
- [x] T020 [P] [US2] Write handler tests covering: step-1 returns 201 with `complete: false`; step-2 returns 200 with `complete: true`; SHA-256 mismatch on either step returns 400; step-2 on unknown `resource_id` returns 404; step-2 on already-complete asset returns 400; list returns paginated results; `kflavor` filter narrows results; detail returns version history in `src/tests/maasapiserver/v3/api/public/handlers/test_boot_resources.py`
- [x] T021 [P] [US2] Write service tests for `start_kernel_upload()` and `attach_initrd()` covering: completeness transitions (`false` → `true`); SHA-256 mismatch causes rollback; duplicate upload to same `(name, architecture, kflavor)` creates new version; `attach_initrd` on already-usable set is rejected in `src/tests/maasservicelayer/services/test_bootresources.py`
- [x] T022 [P] [US2] Write repository tests asserting the `uq_bootresource_kernel_identity` partial unique index raises `IntegrityError` on duplicate `(name, architecture, kflavor)` for `rtype=UPLOADED, kflavor IS NOT NULL, bootloader_type IS NULL`, and does NOT raise for Simplestreams resources in `src/tests/maasservicelayer/db/repositories/test_bootresources.py`

**Checkpoint**: Both upload steps work; `GET /boot_assets/kernels/{id}` shows correct `complete` flag. Run `make test-py` and confirm Phase 4 tests pass.

---

## Phase 5: User Story 3 — List and Filter Custom Boot Assets (Priority: P2)

**Goal**: The existing `GET /custom_images` endpoint gains a `type` discriminator field on each response item and four new filter query parameters (`type`, `name`, `architecture`, `kflavor`) so operators can quickly identify the right asset for a given machine configuration.

**Independent Test**: Upload at least one bootloader, one kernel, and one plain custom image; verify `GET /custom_images?type=bootloader` returns only bootloaders; `GET /custom_images?type=kernel` returns only kernels; `GET /custom_images` (no filter) returns all; `GET /custom_images?kflavor=lowlatency` returns only lowlatency kernel assets.

> **Dependency**: Requires T005 (repo discriminator filters). Can start in parallel with Phase 6 once T005 is done.

### Implementation for User Story 3

- [X] T023 [US3] Extend the `GET /custom_images` handler with optional query parameters `type` (`bootloader`/`kernel`/`image`), `name`, `architecture`, and `kflavor`; pass filter values to the repository list method; return existing paginated response shape (per contracts/custom_images.md)
- [X] T024 [US3] Add `type` discriminator field to the custom images list response item model: derive `"bootloader"` when `bootloader_type IS NOT NULL`, `"kernel"` when `kflavor IS NOT NULL AND bootloader_type IS NULL`, and `"image"` otherwise; update the response Pydantic model in `src/maasapiserver/v3/api/public/models/responses/boot_resources.py` (or the appropriate custom_images response file)
- [X] T025 [US3] Extend the `BootResourceRepository` list query used by `/custom_images` with `WHERE` clauses for `type` (using the discriminator filters from T005), `name`, `architecture`, and `kflavor` filter parameters in `src/maasservicelayer/db/repositories/bootresources.py`
- [X] T026 [P] [US3] Write handler tests for `GET /custom_images` covering: `type=bootloader` returns only bootloaders with correct `type` field; `type=kernel` returns only kernels; no `type` returns all; `name` filter exact-matches; `architecture` filter exact-matches; `kflavor` filter with `type=kernel` returns only matching flavours; response items all carry a `type` field in `src/tests/maasapiserver/v3/api/public/handlers/test_boot_resources.py`

**Checkpoint**: All four filter parameters work independently and in combination. Run `make test-py` and confirm Phase 5 tests pass.

---

## Phase 6: User Story 4 — Select Custom Boot Asset at Deploy Time (Priority: P2)

**Goal**: The v2 deploy endpoint accepts optional `custom_bootloader` and `custom_kernel` (with optional `:kflavor` suffix) parameters. MAAS validates the asset exists, matches the machine's architecture, and is complete (kernel only); stores the selection on the Node; triggers a DHCP config update (bootloader only) before powering on. At PXE boot time, `get_boot_config` returns custom kernel paths; DHCP renders a per-host `filename` directive for custom bootloaders.

**Independent Test**: Deploy a machine with `custom_bootloader=ubuntu/jammy` via the v2 API; confirm `Node.custom_bootloader` is set and the Rack DHCP config contains `filename "custom-bootloaders/<sha256[:8]>/shimx64.efi";` for the machine's MAC before power-on. See quickstart.md §4 for CLI commands.

> **Dependency**: Requires T006 (Django Node fields from Phase 2). Can start after T006 completes.

### Implementation for User Story 4

- [X] T027 [US4] Extend `MachineHandler.deploy()` in `src/maasserver/api/machines.py` to accept `custom_bootloader` (string, optional) and `custom_kernel` (string `name[:kflavor]`, optional) POST parameters; for each supplied value: (1) validate asset existence and architecture match against machine architecture (HTTP 400 on mismatch/not-found); (2) for `custom_kernel`, resolve latest `BootResourceSet` and reject if not `is_usable()` (HTTP 400); (3) parse `name:kflavor` splitting on `:`, defaulting kflavor to `"generic"`; (4) store `machine.custom_bootloader`, `machine.custom_kernel`, `machine.custom_kernel_kflavor` on the Node; (5) for `custom_bootloader`, trigger DHCP config update and await completion before calling the power-on action
- [X] T028 [US4] In `make_hosts_for_subnets()` in `src/maasserver/dhcp.py`, add a `boot_filename` key to the per-host dict when `node.custom_bootloader` is set: resolve the `BootResource` for the stored name + machine architecture, read `BootResource.extra["primary_file"]` and the latest set's `BootResourceFile.filename_on_disk` SHA-256 prefix, and compute `boot_filename = f"custom-bootloaders/{sha256[:8]}/{primary_file}"`
- [X] T029 [US4] Render the per-host `filename` DHCP directive in the DHCP host block Tempita template in `src/maasserver/dhcpd/config.py`: emit `filename "{{host.boot_filename}}";` when `host.boot_filename` is present; leave the host block unchanged when absent
- [X] T030 [US4] Add custom kernel resolution block to `get_boot_config()` in `src/maasserver/rpc/boot.py`: after loading the machine, if `machine.custom_kernel` is set, look up the `BootResource` by `(name, architecture=f"{arch}/{machine.custom_kernel_kflavor}", rtype=UPLOADED, kflavor__isnull=False)`; if found and latest set `is_usable()`, return `kernel` and `initrd` paths from the latest complete set's `BootResourceFile.filename_on_disk` values; if the asset is missing or its latest set is incomplete, log a warning and fall through to the standard `get_boot_filenames()` call
- [X] T031 [P] [US4] Write deploy endpoint tests covering: valid `custom_bootloader` stores on Node and triggers DHCP; architecture mismatch returns 400; asset not found returns 400; valid `custom_kernel` stores name and kflavor on Node; incomplete kernel (missing initrd) returns 400; no custom params leaves Node fields null; missing deploy permission returns 403 — use `bin/test.region` on the relevant test file (e.g. `src/maasserver/tests/test_api_machines.py`)
- [X] T032 [P] [US4] Write DHCP config tests asserting that `make_hosts_for_subnets()` includes `boot_filename` in the host dict when `node.custom_bootloader` is set, and that the Tempita template renders `filename "custom-bootloaders/<sha256[:8]>/<primary_file>";` in the host block; assert the directive is absent when `node.custom_bootloader` is null — run with `bin/test.region src/maasserver/dhcpd/tests/test_config.py`
- [X] T033 [P] [US4] Write RPC boot tests for `get_boot_config()` covering: custom kernel found → returns custom kernel and initrd paths instead of Simplestreams paths; stored custom kernel asset deleted since deploy → falls back to standard `get_boot_filenames()` with a logged warning; stored custom kernel has incomplete latest set → falls back with warning — run with `bin/test.region src/maasserver/rpc/tests/test_boot.py`

**Checkpoint**: Deploy with `custom_bootloader` produces the correct per-host `filename` directive in `dhcpd.conf` before machine power-on. Deploy with `custom_kernel` stores the selection; PXE boot returns the custom kernel paths. Run all Phase 6 tests.

---

## Phase 7: User Story 5 — Rack Controller Caching of Custom Boot Assets (Priority: P3)

**Goal**: Custom boot assets flow through the Rack Controller's existing on-demand fetch and local cache path with no new caching mechanism. Verify that `upload_binary()` (T004) correctly triggers `SYNC_BOOTRESOURCES_WORKFLOW_NAME` and creates the originating-region `BootResourceFileSync` record so the Rack can discover and pull the file.

**Independent Test**: After a bootloader upload, observe that the first machine PXE request to the Rack causes a Region → Rack fetch (visible in Region logs), and subsequent requests are served from the Rack's local cache without contacting the Region (see quickstart.md §Debugging Tips).

> **Dependency**: Requires T004 (upload_binary service method). No new source files — these tasks are verification and test tasks only.

### Implementation for User Story 5

- [X] T034 [US5] Confirm that `BootResourceService.upload_binary()` (implemented in T004) triggers `SYNC_BOOTRESOURCES_WORKFLOW_NAME` via the existing Temporal client call at the end of each upload, covering all three upload paths (bootloader, kernel/initrd, and the refactored custom image path); add an explicit assertion in the service test suite if the Temporal call is not already covered in T013/T021 in `src/tests/maasservicelayer/services/test_bootresources.py`
- [X] T035 [P] [US5] Confirm that `upload_binary()` creates a `BootResourceFileSync` record for the originating region (via `MAAS_ID` → `NodeClauseFactory.with_system_id` lookup) immediately after the `BootResourceFile` record is committed; add an explicit service test assertion if not already covered by T013/T021 in `src/tests/maasservicelayer/services/test_bootresources.py`

**Checkpoint**: `BootResourceFileSync` record exists for the originating region after every upload; Temporal sync workflow is triggered for bootloader, kernel, and custom image uploads.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: End-to-end validation, documentation, and cleanup.

- [ ] T036 [P] Apply all Alembic migrations end-to-end (`cd src && alembic -c maasservicelayer/db/alembic/alembic.ini upgrade head`) and verify both the partial unique indexes and the Node custom boot columns exist in the schema; confirm downgrade (`alembic downgrade -1`) is clean for both migrations
- [ ] T037 [P] Run the quickstart.md bootloader upload and deploy flow end-to-end in a local dev environment: upload tarball, verify 201; list with `type=bootloader`, verify asset present; deploy machine with `custom_bootloader`; verify DHCP config contains per-host `filename` directive before power-on
- [ ] T038 [P] Run the quickstart.md kernel upload and deploy flow end-to-end: upload kernel (step 1, `complete: false`), attach initrd (step 2, `complete: true`); deploy machine with `custom_kernel=ubuntu/noble:generic`; verify `Node.custom_kernel` is set; verify PXE boot returns custom kernel paths

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1: Setup (T001, T002, T003)
    │ No dependencies — start immediately
    ▼
Phase 2: Foundational (T004, T005, T006)
    │ Depends on Phase 1 migration files existing (T001, T002)
    ├──────────────────────────────────────────────────────────┐
    ▼                                                          ▼
Phase 3: US1 Bootloader Upload (T007–T014)         Phase 4: US2 Kernel Upload (T015–T022)
    │ Requires T004, T005                              │ Requires T004, T005
    │ (parallel with Phase 4)                          │ (parallel with Phase 3)
    └─────────────────────────┬────────────────────────┘
                              ▼
              Phase 5: US3 List & Filter (T023–T026)
                  │ Requires T005 (repo filters)
                  │ (can overlap with Phase 6)
                  ▼
              Phase 6: US4 Deploy Selection (T027–T033)
                  │ Requires T006 (Node model fields)
                  ▼
              Phase 7: US5 Rack Caching (T034–T035)
                  │ Requires T004 (upload_binary)
                  ▼
              Phase 8: Polish (T036–T038)
                  │ Requires all phases complete
```

### User Story Dependencies

| Story | Depends On | Can Parallelize With |
|---|---|---|
| US1 — Bootloader Upload (P1) | Phase 2 (T004, T005) | US2 (T015–T022) |
| US2 — Kernel Upload (P1) | Phase 2 (T004, T005) | US1 (T007–T014) |
| US3 — List & Filter (P2) | T005 (repo filters) | US4 once T006 done |
| US4 — Deploy Selection (P2) | T006 (Node fields) | US3 |
| US5 — Rack Caching (P3) | T004 (upload_binary) | Polish |

### Within Each User Story

- Request models [P] → Response models [P] → Service implementation → Handler → Router registration
- Tests [P] can be written alongside or after the implementation they cover
- Repository tests [P] (constraint tests) are independent of service/handler tests

---

## Parallel Execution Examples

### Phases 3 + 4 in parallel (after Phase 2 completes)

```
# Developer A — User Story 1 (bootloader)
Task T007: Add BootloaderUploadRequest model
Task T008: Add BootloaderDetailResponse model
Task T009: Implement create_or_version_bootloader() service method
Task T010: Implement BootAssetsHandler bootloader routes
Task T011: Register bootloader routes in router

# Developer B — User Story 2 (kernel) — simultaneously
Task T015: Add KernelUploadRequest model
Task T016: Add KernelResponse / KernelDetailResponse models
Task T017: Implement start_kernel_upload() and attach_initrd()
Task T018: Implement kernel routes in BootAssetsHandler
Task T019: Register kernel routes in router
```

### Parallel tests within US1

```
# After T009 and T010 are complete, launch all US1 tests together:
Task T012: Handler tests for bootloader upload/list/detail
Task T013: Service tests for create_or_version_bootloader()
Task T014: Repository constraint tests for bootloader unique index
```

### Parallel tasks within Phase 2

```
Task T004: Refactor upload_binary() (service layer)
Task T005: Add discriminator ClauseFactory filters (repository)  ← independent file
Task T006: Add Django Node model fields (legacy models)          ← independent file
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2 Only — both P1)

1. Complete **Phase 1**: Apply Alembic migrations
2. Complete **Phase 2**: Foundational (upload_binary refactor, repo filters, Node fields)
3. Complete **Phase 3** + **Phase 4** in parallel: Upload endpoints for bootloaders and kernels
4. **STOP and VALIDATE**: Operators can upload bootloaders and kernels; assets are versioned and listed
5. Ship as MVP — US3, US4, US5 are additive

### Incremental Delivery

1. Phase 1 + Phase 2 → Foundation ready
2. Phase 3 + Phase 4 → Upload endpoints live (MVP) ✅
3. Phase 5 → Filtering and discovery live ✅
4. Phase 6 → Deploy-time selection live (full end-to-end value) ✅
5. Phase 7 + Phase 8 → Verified caching + polished ✅

### Parallel Team Strategy (3 developers)

After Phase 1 + Phase 2 complete:
- **Developer A**: Phase 3 (US1 — bootloader upload)
- **Developer B**: Phase 4 (US2 — kernel upload)
- **Developer C**: Phase 6 (US4 — deploy selection, starts with T027 on Node fields T006 already done)

Then converge for Phase 5 (US3), Phase 7 (US5), and Phase 8 (Polish).

---

## Notes

- **[P]** tasks operate on different files or independent sections — safe to run concurrently
- **Alembic migrations are immutable**: hard-code the `UPLOADED` rtype integer value (read from `BootResourceType.UPLOADED` at migration authoring time) in `0022_custom_boot_asset_indexes.py`
- **DHCP 128-byte constraint**: enforced structurally by the short extraction path `custom-bootloaders/<8-char-sha256>/`; no per-upload runtime check needed
- **`primary_file` injection safety**: validated at request parse time (`^[A-Za-z0-9._-]{1,64}$`) before any storage or DHCP rendering
- **Django migrations are frozen**: all schema changes go through Alembic only (T001, T002)
- **`hwe_kernel` is not reused**: the `custom_kernel` deploy parameter uses `name:kflavor` encoding to avoid overloading `hwe_kernel` with two incompatible meanings
- Each phase checkpoint should be independently validated before progressing
- Commit after each task or logical group using conventional commits scoped to `api`, `service`, `repo`, `db`, or `legacy` as appropriate
