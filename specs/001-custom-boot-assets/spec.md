# Feature Specification: Custom Boot Assets

**Feature Branch**: `custom-boot-assets`

**Jira**: MAASENG-5494

**Created**: 2026-05-22

**Status**: Draft

**Input**: Upload, manage, and select operator-supplied bootloaders and kernels as first-class MAAS assets, replacing out-of-band TFTP injection with a versioned, lifecycle-managed alternative.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Upload Custom Bootloader (Priority: P1)

An infrastructure operator has a vendor-specific UEFI bootloader (e.g. a custom POWER shim or a patched EFI binary) that must be used in place of the default Ubuntu Simplestreams bootloader. The operator uploads a tarball containing the bootloader binaries to MAAS. MAAS validates the tarball, extracts the files safely, versions the asset, and makes it immediately available for deployment selection. Uploading to the same `name + architecture` identity creates a new version; previous versions are retained. New deployments always use the latest version.

**Why this priority**: Without the ability to upload a bootloader, none of the downstream stories (deploy selection, caching) can be validated end to end. This is the foundational upload path.

**Independent Test**: Can be tested by uploading a bootloader tarball via the API and verifying the asset appears in the list endpoint with the correct name, architecture, version, and stored files.

**Acceptance Scenarios**:

1. **Given** a valid tarball with a new `name + architecture`, **When** the operator uploads it, **Then** the asset is created with a version string and appears in the bootloaders list.
2. **Given** a tarball for an existing `name + architecture`, **When** uploaded, **Then** a new version is created and the previous version is retained.
3. **Given** a tarball where the supplied SHA-256 does not match the received body, **When** uploaded, **Then** the request is rejected with a 400 error and no record is created.
4. **Given** a tarball containing a path-traversal entry (e.g. `../../../etc/passwd`), **When** uploaded, **Then** the request is rejected with a 400 error.
5. **Given** an upload request without a bootloader filename, **When** submitted, **Then** the request is rejected with a 400 error.
6. **Given** a valid bootloader upload, **When** the machine PXE boots with that bootloader assigned, **Then** DHCP option 67 returns a value whose total length (extraction path + filename) does not exceed 128 bytes.
7. **Given** a successful upload, **When** the operator queries the custom images list with `type=bootloader`, **Then** the new asset appears in the response.

---

### User Story 2 - Upload Custom Kernel and Initrd (Priority: P1)

An infrastructure operator wants machines to commission and deploy with a custom kernel. Kernels require both a kernel binary and an initrd file to boot. The operator uploads the kernel binary in a first request, receives a resource identifier, then attaches the initrd in a second request. Until the initrd is attached, the asset is marked incomplete and cannot be selected for deployment.

A kernel asset is identified by `name + architecture + kflavor`. The `kflavor` field (e.g. `generic`, `lowlatency`, `hwe`) is mandatory and forms part of the identity key.

**Why this priority**: Custom kernel support is a primary use case, and the two-step upload flow is novel; it must be validated independently of the bootloader path.

**Independent Test**: Can be tested by completing both upload steps, then verifying `complete: true` in the kernel detail response, and verifying that an asset after only step 1 shows `complete: false`.

**Acceptance Scenarios**:

1. **Given** a completed two-step upload (kernel then initrd), **When** the operator retrieves the kernel asset, **Then** the response includes `complete: true` and the asset is selectable for deployment.
2. **Given** only step 1 completed (no initrd attached), **When** the operator retrieves the asset, **Then** the response includes `complete: false` and the asset is rejected if selected for deployment.
3. **Given** a SHA-256 mismatch on either upload step, **When** the upload request is submitted, **Then** the request is rejected with a 400 error and no partial record is committed.
4. **Given** multiple kernel uploads for the same `name + architecture + kflavor`, **When** each upload completes, **Then** each produces a new version.
5. **Given** a completed kernel asset, **When** a machine is deployed with it, **Then** the asset is usable for both commissioning and disk deployment environments.
6. **Given** a machine with a custom kernel stored, **When** the machine PXE boots and the Rack Controller requests boot parameters from the Region, **Then** the Region returns the custom kernel and initrd file paths instead of the standard Simplestreams kernel paths.

---

### User Story 3 - List and Filter Custom Boot Assets (Priority: P2)

An infrastructure operator manages many uploaded assets across different architectures and kernel flavours. They need to find the right asset for a given machine configuration quickly. The existing custom images endpoint gains filter parameters for type, name, architecture, and kernel flavour. Typed endpoints return enriched responses including version history and completion state.

**Why this priority**: Discoverability is required before deployment selection; without filtering, operators in large deployments cannot reliably identify the correct asset.

**Independent Test**: Can be tested by uploading assets of different types and verifying that each filter parameter independently narrows the result set as expected.

**Acceptance Scenarios**:

1. **Given** assets of multiple types, **When** filtering by `type=bootloader`, **Then** only bootloader assets are returned.
2. **Given** assets of multiple types, **When** no `type` filter is applied, **Then** all uploaded assets are returned.
3. **Given** assets with different names, **When** filtering by `name=ubuntu/jammy`, **Then** only assets with that exact name are returned regardless of type.
4. **Given** assets for different architectures, **When** filtering by `architecture=amd64/generic`, **Then** only assets for that architecture are returned.
5. **Given** kernel assets with different flavours, **When** filtering by `type=kernel&kflavor=lowlatency`, **Then** only lowlatency kernel assets are returned.
6. **Given** a bootloader asset ID, **When** the operator requests that asset by ID, **Then** the response includes `versions`, `latest_version`, `primary_file`, `files`, `created_at`, and `updated_at`.
7. **Given** a kernel asset ID, **When** the operator requests that asset by ID, **Then** the response includes `versions`, `latest_version`, `complete`, `created_at`, and `updated_at`.

---

### User Story 4 - Select Custom Boot Asset at Deploy Time (Priority: P2)

A user with deployment permissions wants a machine to use a specific custom bootloader or kernel at deploy time instead of the Simplestreams default. Asset selection is explicit: if no custom asset is selected, the system uses the official Ubuntu asset. The system always resolves to the latest version of the selected asset identity; version pinning is not supported.

When a custom bootloader is selected, MAAS updates the Rack Controller's DHCP configuration to deliver that bootloader to the target machine via DHCP option 67, matched by MAC address. The DHCP update must complete before the machine is powered on.

**Why this priority**: Deploy-time selection is the primary consumer value. Without it, uploaded assets have no effect on machine provisioning.

**Independent Test**: Can be tested by deploying a machine with a custom bootloader parameter and verifying the Rack Controller DHCP configuration is updated with the correct per-host boot filename before machine power-on.

**Acceptance Scenarios**:

1. **Given** a valid `custom_bootloader` name on a deploy request, **When** the deploy is triggered, **Then** the Rack Controller DHCP config is updated with a per-host `filename` directive before the machine powers on.
2. **Given** no `custom_bootloader` parameter, **When** the deploy is triggered, **Then** the machine receives the default Simplestreams bootloader.
3. **Given** a `custom_bootloader` whose architecture does not match the machine's architecture, **When** the deploy is triggered, **Then** the request is rejected with a 400 error.
4. **Given** a non-existent `custom_bootloader` name, **When** the deploy is triggered, **Then** the request is rejected with a 400 error.
5. **Given** a `custom_kernel` value with an optional `:kflavor` suffix on the deploy request (e.g. `ubuntu/noble` or `ubuntu/noble:lowlatency`), **When** the deploy is triggered, **Then** the machine boots with that kernel+initrd pair (latest version).
6. **Given** a user without deployment permission on the target machine, **When** the deploy is triggered with a custom asset, **Then** the request is rejected with a 403 error.
7. **Given** a machine already deployed with version N, **When** version N+1 is uploaded, **Then** the running machine is unaffected and new deployments use version N+1.
8. **Given** a deploy request with an incomplete kernel asset (missing initrd), **When** submitted, **Then** the request is rejected with a 400 error.

---

### User Story 5 - Rack Controller Caching of Custom Boot Assets (Priority: P3)

An infrastructure operator wants machines to receive boot files at network speed. Rack Controllers serve boot assets on demand: on a cache miss the Rack fetches the file from the Region Controller and caches it locally. Subsequent requests are served from the local cache. Custom assets must flow through this existing on-demand fetch path without requiring a new caching mechanism.

**Why this priority**: Caching is a non-functional correctness requirement. Without it, large deployments would saturate the Region Controller's network interface on every PXE boot.

**Independent Test**: Can be manually verified by observing that the first machine request for a custom asset causes a Rack-to-Region fetch, while subsequent requests are served locally.

**Acceptance Scenarios**:

1. **Given** a custom asset on the Region not yet cached on the Rack, **When** a machine requests it via the Rack, **Then** the Rack fetches it from the Region and caches it locally.
2. **Given** a cached asset on the Rack, **When** subsequent machine requests arrive, **Then** they are served from the Rack's local cache without contacting the Region.
3. **Given** a new version uploaded to the Region, **When** a machine requests it, **Then** the new version is fetched on the next cache miss.

---

### Edge Cases

- What happens when a tarball upload is interrupted mid-stream? The partial record must not be committed; the operation must be atomic.
- What happens when an operator deletes a bootloader that is actively assigned to deployed machines? The deletion proceeds (admin only); machines currently deployed retain their cached files but MAAS has no record of the asset. This risk is accepted for this iteration.
- What happens when a bootloader upload succeeds but distribution to a remote Region fails? The asset remains available on the originating Region and Rack Controllers served by that Region; other Regions and their Racks will not have the asset until the distribution is retried.
- What happens when the primary EFI filename submitted at upload time contains path separators or shell metacharacters? The value must be rejected at upload time before storage, to prevent DHCP config injection.
- What happens if the combined DHCP option 67 value (extraction path + bootloader filename) would exceed 128 bytes? The system must enforce a short, fixed-depth extraction path at upload time, ensuring the constraint is always met without per-upload validation.
- The `custom_kernel` deploy parameter accepts an optional `:kflavor` suffix (e.g. `ubuntu/noble:lowlatency`). When the suffix is absent, kflavor defaults to `generic`. A separate `custom_kernel_kflavor` parameter is NOT added — the `hwe_kernel` parameter is also not reused, as it selects a Simplestreams kernel version (used as `subarch` in Simplestreams lookup) and is entirely bypassed when `custom_kernel` is set; overloading it would conflate two incompatible meanings on `Node.hwe_kernel`.
- What happens when the Region is asked for boot parameters for a machine whose stored custom kernel asset has been deleted since deployment? The Region must detect the missing asset and fall back to the standard Simplestreams kernel, logging a warning.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST allow admin users to upload a bootloader tarball (`.tar.gz`, `.tar.xz`, `.tar.bz2`) via a dedicated upload endpoint, identified by `name + architecture`. The operator MUST supply the bootloader filename at upload time — this is the entry point binary within the tarball (e.g. `shimx64.efi`) that DHCP option 67 will return to PXE clients. This field is mandatory; the upload MUST be rejected if it is absent.
- **FR-002**: The system MUST validate the SHA-256 digest of every uploaded binary against the value supplied by the caller, rejecting mismatches before any record is committed.
- **FR-003**: The system MUST reject tarball uploads containing path-traversal entries or symlinks that resolve outside the extraction directory.
- **FR-004**: The system MUST version bootloader assets: uploading to an existing `name + architecture` identity creates a new version while retaining previous versions.
- **FR-005**: The system MUST allow admin users to upload a custom kernel binary (step 1) and attach an initrd (step 2) via sequential requests, identified by `name + architecture + kflavor`.
- **FR-006**: The system MUST track kernel asset completeness: an asset without an attached initrd MUST have `complete: false` and MUST NOT be selectable for deployment.
- **FR-007**: The system MUST expose filterable list endpoints for custom boot assets, supporting filters for `type`, `name`, `architecture`, and `kflavor`.
- **FR-008**: The system MUST expose detail endpoints for individual bootloader and kernel assets, returning version history, completion state, and primary file metadata.
- **FR-009**: The system MUST allow users with deployment permission to select a custom bootloader or kernel at machine deploy time using the v2 deploy endpoint.
- **FR-010**: The system MUST validate that the selected custom asset's architecture matches the target machine's architecture, rejecting mismatches at deploy time.
- **FR-011**: When a custom bootloader is selected for deployment, the system MUST update the Rack Controller's DHCP configuration with a per-host boot filename directive (DHCP option 67) before the machine is powered on.
- **FR-012**: The system MUST resolve custom asset selection to the latest version of the given asset identity; version pinning is not supported.
- **FR-013**: Custom boot assets MUST be accessible through the Rack Controller's existing on-demand fetch and local cache path, with no new caching mechanism required.
- **FR-014**: The bootloader filename supplied at upload time MUST be validated to contain only safe characters (no path separators or shell metacharacters) before storage. This value is later rendered verbatim into DHCP option 67 and served to PXE clients; it must not allow injection into the DHCP configuration.
- **FR-015**: The tarball extraction path on disk MUST be kept short. DHCP option 67 delivers the full path to the PXE client; the combined length of the extraction base path and the bootloader filename MUST NOT cause the option 67 value to exceed the DHCP protocol limit (128 bytes for the standard BOOTP file field).
- **FR-016**: The existing `/custom_images` list endpoint MUST be extended with a `type` discriminator field on each response item (`bootloader`, `kernel`, or `image`).
- **FR-017**: The binary upload pipeline — encompassing file streaming, SHA-256 verification, storage, and resource record creation (boot resource, resource set, resource file, and file-sync entries) — MUST be implemented in the service layer and shared across all upload paths (bootloader, kernel, and custom OS image). Handlers MUST be responsible only for request parsing, permission enforcement, and response formatting. This requires refactoring the existing `upload_custom_image` handler before or alongside the new upload endpoints.
- **FR-018**: When the Region Controller renders boot parameters for a PXE-booting machine, it MUST check whether a custom kernel is stored on the machine. If one is present, the response MUST include the custom kernel and initrd file paths from the latest complete version of that asset, in place of the standard Simplestreams kernel paths. If no custom kernel is stored, the standard kernel resolution path is used unchanged.

### Key Entities

- **Boot Asset (Bootloader)**: A versioned collection of bootloader binaries identified by `name + architecture`. Carries a primary EFI filename used as the DHCP option 67 value. Multiple versions co-exist; new deployments always use the latest.
- **Boot Asset (Kernel)**: A versioned kernel+initrd pair identified by `name + architecture + kflavor`. Has a `complete` flag that is `true` only when both files are present. Multiple versions co-exist.
- **Asset Version**: A point-in-time snapshot of a boot asset's files. Versions are immutable after creation.
- **Custom Image**: The umbrella category for all operator-uploaded boot resources, including bootloaders, kernels, and plain OS images. Exposed via `/custom_images` with a `type` discriminator.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator can upload a bootloader tarball and have it available for deployment selection within 60 seconds of upload completion.
- **SC-002**: An operator can complete a two-step kernel upload (kernel then initrd) and have the asset marked complete and selectable within 60 seconds of the final step.
- **SC-003**: A machine deployed with a custom bootloader receives the correct bootloader via DHCP option 67 on its first PXE request, with no manual TFTP configuration required.
- **SC-004**: A machine deployed with a custom kernel boots using the correct kernel and initrd, with no manual intervention on the Rack Controller.
- **SC-005**: Filtering the custom images list by any supported filter parameter returns only matching assets, with zero false positives.
- **SC-006**: All upload and deploy operations enforce permissions such that non-admin users cannot upload assets and users without deploy permission cannot select assets.
- **SC-007**: A Rack Controller serves a custom asset from its local cache on the second and subsequent machine requests, without a Region Controller round-trip.
- **SC-008**: Uploading a new version of an existing asset does not affect machines currently deployed with the previous version.
- **SC-009**: The bootloader, kernel, and custom OS image upload paths share a single upload pipeline implementation in the service layer, with no duplication of file streaming, SHA-256 verification, or record-creation logic across handlers.

## Assumptions

- The existing `BootResource` storage model (four-tier chain: `BootResource → BootResourceSet → BootResourceFile → BootResourceFileSync`) supports custom assets without new tables.
- Rack Controllers do not receive assets via a push or sync workflow. They pull assets on demand from the Region Controller on a cache miss and serve subsequent requests from local cache. No new distribution mechanism is required for custom assets.
- The v2 deploy endpoint (`POST /api/2.0/machines/{system_id}/op-deploy`) is the appropriate integration point for deploy-time asset selection, as no v3 deploy endpoint exists at the time of writing.
- Upload endpoints may receive large binary payloads; the reverse proxy body size limit for the `/boot_assets` location must be increased to accommodate typical bootloader and kernel file sizes.
- Operators are responsible for Secure Boot compliance and binary signing; MAAS does not verify cryptographic signatures on uploaded binaries.
- Version pinning (deploying a specific historical version rather than the latest) is explicitly out of scope for this iteration.
- Per-machine version tracking and garbage collection of old asset versions are out of scope for this iteration.
- The UI/UX design for surfacing custom asset selection in the deploy form is a follow-on deliverable outside this spec's scope.
- The MAAS Site Manager changes needed to surface the new Simplestreams multi-bootloader index are out of scope; only the index format specification is in scope.

## Clarifications

### Session 2026-05-22

- Q: How do Rack Controllers receive custom boot assets? → A: There is no Temporal (or other) sync workflow pushing assets to Racks. Rack Controllers pull assets on demand from the Region Controller on a cache miss and serve subsequent requests from local cache.
- Q: How should the upload logic be shared across bootloader, kernel, and custom image upload paths? → A: The binary upload pipeline (file streaming, SHA-256 verification, storage, resource/set/file/sync record creation) must be extracted to the service layer and shared. The existing `upload_custom_image` handler must be refactored as part of this feature. Handlers remain thin: request parsing, permission enforcement, and response formatting only.
- Q: How does a custom kernel selection reach the Rack Controller at PXE boot time? → A: The custom kernel selection is stored on the machine at deploy time. When the machine PXE boots, the Rack calls the Region's `get_boot_config` RPC endpoint. The Region checks whether a custom kernel is stored on the machine and, if so, resolves the custom asset's latest complete version and returns its kernel and initrd file paths in the boot parameter response, bypassing the standard Simplestreams `get_boot_filenames()` lookup. If the stored asset has been deleted, the Region falls back to the standard kernel and logs a warning.
- Q: How is the DHCP option 67 value constructed for custom bootloaders, and what constrains it? → A: The operator supplies the bootloader entry-point filename (e.g. `shimx64.efi`) as a mandatory field at upload time. This is the file returned to PXE clients. The tarball is extracted to a deliberately short, fixed base path so that the full option 67 value (base path + `/` + filename) does not exceed the 128-byte BOOTP file field limit. The filename is validated for safe characters at upload time to prevent DHCP config injection.
