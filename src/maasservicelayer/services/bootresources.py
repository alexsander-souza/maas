# Copyright 2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
import asyncio
from collections.abc import AsyncIterable
import re
from typing import TYPE_CHECKING

from maascommon.enums.boot_resources import (
    BootResourceFileType,
    BootResourceType,
)
from maascommon.workflows.bootresource import (
    ResourceDownloadParam,
    short_sha,
    SYNC_BOOTRESOURCES_WORKFLOW_NAME,
    SyncRequestParam,
)
from maasservicelayer.builders.bootresourcefiles import BootResourceFileBuilder
from maasservicelayer.builders.bootresourcefilesync import (
    BootResourceFileSyncBuilder,
)
from maasservicelayer.builders.bootresources import BootResourceBuilder
from maasservicelayer.builders.bootresourcesets import BootResourceSetBuilder
from maasservicelayer.context import Context
from maasservicelayer.db.filters import Clause, QuerySpec
from maasservicelayer.db.repositories.bootresourcefiles import (
    BootResourceFileClauseFactory,
)
from maasservicelayer.db.repositories.bootresourcefilesync import (
    BootResourceFileSyncClauseFactory,
)
from maasservicelayer.db.repositories.bootresources import (
    BootResourceClauseFactory,
    BootResourcesRepository,
)
from maasservicelayer.db.repositories.bootresourcesets import (
    BootResourceSetClauseFactory,
)
from maasservicelayer.db.repositories.nodes import NodeClauseFactory
from maasservicelayer.db.tables import BootResourceTable
from maasservicelayer.exceptions.catalog import (
    BadRequestException,
    BaseExceptionDetail,
    InsufficientStorageException,
    NotFoundException,
)
from maasservicelayer.exceptions.constants import (
    INVALID_ARGUMENT_VIOLATION_TYPE,
)
from maasservicelayer.models.base import ListResult
from maasservicelayer.models.bootresourcefiles import BootResourceFile
from maasservicelayer.models.bootresources import (
    BootResource,
    CustomBootResourceStatistic,
    CustomBootResourceStatus,
)
from maasservicelayer.models.bootresourcesets import BootResourceSet
from maasservicelayer.services.base import BaseService, ServiceCache
from maasservicelayer.services.bootresourcesets import BootResourceSetsService
from maasservicelayer.utils.buffer import ChunkBuffer
from maasservicelayer.utils.date import utcnow
from maasservicelayer.utils.image_local_files import (
    AsyncLocalBootResourceFile,
    LocalStoreAllocationFail,
    LocalStoreInvalidHash,
)
from provisioningserver.utils.env import MAAS_ID

if TYPE_CHECKING:
    from maasservicelayer.services.bootresourcefiles import (
        BootResourceFilesService,
    )
    from maasservicelayer.services.bootresourcefilesync import (
        BootResourceFileSyncService,
    )
    from maasservicelayer.services.nodes import NodesService
    from maasservicelayer.services.temporal import TemporalService


class BootResourceService(
    BaseService[BootResource, BootResourcesRepository, BootResourceBuilder]
):
    resource_logging_name = "bootresources"

    def __init__(
        self,
        context: Context,
        repository: BootResourcesRepository,
        boot_resource_sets_service: BootResourceSetsService,
        cache: ServiceCache | None = None,
    ):
        super().__init__(context, repository, cache)
        self.boot_resource_sets_service = boot_resource_sets_service

    async def pre_delete_hook(
        self, resource_to_be_deleted: BootResource
    ) -> None:
        await self.boot_resource_sets_service.delete_many(
            query=QuerySpec(
                where=BootResourceSetClauseFactory.with_resource_id(
                    resource_to_be_deleted.id
                )
            )
        )

    async def pre_delete_many_hook(
        self, resources: list[BootResource]
    ) -> None:
        await self.boot_resource_sets_service.delete_many(
            query=QuerySpec(
                where=BootResourceSetClauseFactory.with_resource_ids(
                    [r.id for r in resources]
                )
            )
        )

    async def delete_all_without_sets(
        self, query: QuerySpec
    ) -> list[BootResource]:
        """Delete all the boot resources that don't have an associated resource set."""
        boot_resources = await self.get_many(query=query)
        boot_resources_ids = {b.id for b in boot_resources}
        all_resource_sets = await self.boot_resource_sets_service.get_many(
            query=QuerySpec(
                where=BootResourceSetClauseFactory.with_resource_ids(
                    list(boot_resources_ids)
                )
            )
        )
        boot_resource_ids_with_sets = {
            rset.resource_id for rset in all_resource_sets
        }
        boot_resource_ids_without_sets = (
            boot_resources_ids - boot_resource_ids_with_sets
        )

        return await self.delete_many(
            query=QuerySpec(
                where=BootResourceClauseFactory.with_ids(
                    boot_resource_ids_without_sets
                )
            )
        )

    async def get_usable_architectures(self) -> list[str]:
        """Return the set of usable architectures.

        Return the architectures for which the resource has at least one
        commissioning image and at least one install image.
        """
        architectures: set[str] = set()

        all_boot_resources = await self.get_many(query=QuerySpec())
        for boot_resource in all_boot_resources:
            latest_resource_set = await self.boot_resource_sets_service.get_latest_complete_set_for_boot_resource(
                boot_resource.id
            )
            if not latest_resource_set:
                continue

            is_usable = await self.boot_resource_sets_service.is_usable(
                latest_resource_set.id
            )
            is_xinstallable = (
                await self.boot_resource_sets_service.is_xinstallable(
                    latest_resource_set.id
                )
            )
            if latest_resource_set and is_usable and is_xinstallable:
                if (
                    "hwe-" not in boot_resource.architecture
                    and "ga-" not in boot_resource.architecture
                ):
                    architectures.add(boot_resource.architecture)

                arch, _ = boot_resource.split_arch()

                if "subarches" in boot_resource.extra:
                    for subarch in boot_resource.extra["subarches"].split(","):
                        if "hwe-" not in subarch and "ga-" not in subarch:
                            architectures.add(f"{arch}/{subarch.strip()}")
                if "platform" in boot_resource.extra:
                    architectures.add(
                        f"{arch}/{boot_resource.extra['platform']}"
                    )
                if "supported_platforms" in boot_resource.extra:
                    for platform in boot_resource.extra[
                        "supported_platforms"
                    ].split(","):
                        architectures.add(f"{arch}/{platform}")

        return sorted(architectures)

    async def get_next_version_name(self, boot_resource_id: int) -> str:
        version_name = utcnow().strftime("%Y%m%d")

        sets_for_boot_resource = (
            await self.boot_resource_sets_service.get_many(
                query=QuerySpec(
                    where=BootResourceSetClauseFactory.and_clauses(
                        [
                            BootResourceSetClauseFactory.with_resource_id(
                                boot_resource_id
                            ),
                            BootResourceSetClauseFactory.with_version_prefix(
                                version_name
                            ),
                        ]
                    )
                ),
            )
        )
        if not sets_for_boot_resource:
            return version_name

        max_idx = 0
        for resource_set in sets_for_boot_resource:
            if "." in resource_set.version:
                _, set_idx = resource_set.version.split(".")
                set_idx = int(set_idx)
                if set_idx > max_idx:
                    max_idx = set_idx

        return "%s.%d" % (version_name, max_idx + 1)

    async def upload_binary(
        self,
        stream: AsyncIterable[bytes],
        sha256: str,
        size: int,
        resource_set_id: int,
        filetype: BootResourceFileType,
        filename: str,
        boot_resource_files_service: "BootResourceFilesService",
        boot_resource_file_sync_service: "BootResourceFileSyncService",
        nodes_service: "NodesService",
        temporal_service: "TemporalService",
    ) -> BootResourceFile:
        filename_on_disk = (
            await boot_resource_files_service.calculate_filename_on_disk(
                sha256
            )
        )
        lfile = AsyncLocalBootResourceFile(
            sha256=sha256,
            filename_on_disk=filename_on_disk,
            total_size=size,
        )

        try:
            async with lfile.store() as store:
                chunk_buffer = ChunkBuffer(4 * 1024 * 1024)
                async for chunk in stream:
                    if chunk_buffer.append_and_check(chunk):
                        await store.write(chunk_buffer.get_and_reset())

                if not chunk_buffer.is_empty():
                    await store.write(chunk_buffer.get_and_reset())
        except LocalStoreAllocationFail as e:
            raise InsufficientStorageException() from e
        except LocalStoreInvalidHash as e:
            raise BadRequestException(
                details=[
                    BaseExceptionDetail(
                        type=INVALID_ARGUMENT_VIOLATION_TYPE,
                        message=(
                            "Provided SHA256 does not match calculated "
                            "one. Make sure the file uploaded has the "
                            f"SHA256 equal to '{sha256}'"
                        ),
                    )
                ]
            ) from e

        now = utcnow()
        resource_file = await boot_resource_files_service.create(
            BootResourceFileBuilder(
                extra={},
                filename=filename,
                filename_on_disk=filename_on_disk,
                filetype=filetype,
                sha256=sha256,
                size=size,
                largefile_id=None,
                resource_set_id=resource_set_id,
                created=now,
                updated=now,
            )
        )

        maas_system_id = await asyncio.to_thread(lambda: MAAS_ID.get())
        assert maas_system_id is not None

        region_info = await nodes_service.get_one(
            query=QuerySpec(
                where=NodeClauseFactory.with_system_id(maas_system_id)
            )
        )
        assert region_info is not None

        await boot_resource_file_sync_service.get_or_create(
            query=QuerySpec(
                where=BootResourceFileSyncClauseFactory.with_file_id(
                    resource_file.id
                )
            ),
            builder=BootResourceFileSyncBuilder(
                created=now,
                updated=now,
                file_id=resource_file.id,
                size=size,
                region_id=region_info.id,
            ),
        )

        temporal_service.register_or_update_workflow_call(
            SYNC_BOOTRESOURCES_WORKFLOW_NAME,
            SyncRequestParam(
                resource=ResourceDownloadParam(
                    rfile_ids=[resource_file.id],
                    source_list=[],
                    sha256=resource_file.sha256,
                    filename_on_disk=resource_file.filename_on_disk,
                    total_size=resource_file.size,
                )
            ),
            workflow_id=(
                f"sync-bootresources:{short_sha(resource_file.sha256)}"
            ),
            wait=False,
        )

        return resource_file

    async def create_or_version_bootloader(
        self,
        name: str,
        architecture: str,
        primary_file: str,
        stream: AsyncIterable[bytes],
        sha256: str,
        size: int,
        boot_resource_files_service: "BootResourceFilesService",
        boot_resource_file_sync_service: "BootResourceFileSyncService",
        nodes_service: "NodesService",
        temporal_service: "TemporalService",
    ) -> tuple[BootResource, BootResourceSet, BootResourceFile]:
        """Create a new bootloader asset or a new version of an existing one."""
        now = utcnow()

        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", primary_file):
            raise BadRequestException(
                details=[
                    BaseExceptionDetail(
                        type=INVALID_ARGUMENT_VIOLATION_TYPE,
                        message=(
                            "primary_file must match ^[A-Za-z0-9._-]{1,64}$"
                        ),
                    )
                ]
            )

        existing = await self.get_one(
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(
                    [
                        BootResourceClauseFactory.with_name(name),
                        BootResourceClauseFactory.with_architecture(
                            architecture
                        ),
                        BootResourceClauseFactory.with_rtype(
                            BootResourceType.UPLOADED
                        ),
                        Clause(
                            condition=BootResourceTable.c.bootloader_type.isnot(
                                None
                            )
                        ),
                    ]
                )
            )
        )

        created_boot_resource = False
        updated_existing = False
        resource_set: BootResourceSet | None = None
        previous_extra = dict(existing.extra) if existing else None

        if existing is None:
            boot_resource = await self.create(
                BootResourceBuilder(
                    alias="",
                    architecture=architecture,
                    base_image="",
                    bootloader_type="uefi",
                    extra={
                        "primary_file": primary_file,
                        "subarches": architecture.split("/", 1)[1],
                    },
                    kflavor=None,
                    name=name,
                    rolling=False,
                    rtype=BootResourceType.UPLOADED,
                    last_deployed=None,
                    created=now,
                    updated=now,
                )
            )
            created_boot_resource = True
        else:
            updated_extra = dict(existing.extra)
            updated_extra["primary_file"] = primary_file
            boot_resource = await self.update_one(
                query=QuerySpec(
                    where=BootResourceClauseFactory.with_id(existing.id)
                ),
                builder=BootResourceBuilder(extra=updated_extra, updated=now),
            )
            updated_existing = True

        try:
            version = await self.get_next_version_name(boot_resource.id)
            resource_set = await self.boot_resource_sets_service.create(
                BootResourceSetBuilder(
                    label="uploaded",
                    version=version,
                    resource_id=boot_resource.id,
                    created=now,
                    updated=now,
                )
            )

            resource_file = await self.upload_binary(
                stream=stream,
                sha256=sha256,
                size=size,
                resource_set_id=resource_set.id,
                filetype=BootResourceFileType.ARCHIVE_TAR_XZ,
                filename=primary_file,
                boot_resource_files_service=boot_resource_files_service,
                boot_resource_file_sync_service=(
                    boot_resource_file_sync_service
                ),
                nodes_service=nodes_service,
                temporal_service=temporal_service,
            )
        except Exception:
            if resource_set is not None:
                await self.boot_resource_sets_service.delete_by_id(
                    resource_set.id, force=True
                )
            if created_boot_resource:
                await self.delete_by_id(boot_resource.id, force=True)
            elif updated_existing and previous_extra is not None:
                await self.update_one(
                    query=QuerySpec(
                        where=BootResourceClauseFactory.with_id(
                            boot_resource.id
                        )
                    ),
                    builder=BootResourceBuilder(
                        extra=previous_extra,
                        updated=utcnow(),
                    ),
                )
            raise

        return boot_resource, resource_set, resource_file

    async def start_kernel_upload(
        self,
        name: str,
        architecture: str,
        kflavor: str,
        stream: AsyncIterable[bytes],
        sha256: str,
        size: int,
        boot_resource_files_service: "BootResourceFilesService",
        boot_resource_file_sync_service: "BootResourceFileSyncService",
        nodes_service: "NodesService",
        temporal_service: "TemporalService",
    ) -> tuple[BootResource, BootResourceSet, BootResourceFile]:
        """Create a new kernel asset or a new version of an existing one."""
        now = utcnow()
        existing = await self.get_one(
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(
                    [
                        BootResourceClauseFactory.with_name(name),
                        BootResourceClauseFactory.with_architecture(
                            architecture
                        ),
                        BootResourceClauseFactory.with_custom_kernel_type(),
                        BootResourceClauseFactory.with_kflavor(kflavor),
                    ]
                )
            )
        )

        resource_set: BootResourceSet | None = None
        created_boot_resource = False
        if existing is None:
            boot_resource = await self.create(
                BootResourceBuilder(
                    alias="",
                    architecture=architecture,
                    base_image="",
                    bootloader_type=None,
                    extra={"subarches": architecture.split("/", 1)[1]},
                    kflavor=kflavor,
                    name=name,
                    rolling=False,
                    rtype=BootResourceType.UPLOADED,
                    last_deployed=None,
                    created=now,
                    updated=now,
                )
            )
            created_boot_resource = True
        else:
            boot_resource = existing

        try:
            version = await self.get_next_version_name(boot_resource.id)
            resource_set = await self.boot_resource_sets_service.create(
                BootResourceSetBuilder(
                    label="uploaded",
                    version=version,
                    resource_id=boot_resource.id,
                    created=now,
                    updated=now,
                )
            )
            resource_file = await self.upload_binary(
                stream=stream,
                sha256=sha256,
                size=size,
                resource_set_id=resource_set.id,
                filetype=BootResourceFileType.BOOT_KERNEL,
                filename="kernel",
                boot_resource_files_service=boot_resource_files_service,
                boot_resource_file_sync_service=(
                    boot_resource_file_sync_service
                ),
                nodes_service=nodes_service,
                temporal_service=temporal_service,
            )
        except Exception:
            if resource_set is not None:
                await self.boot_resource_sets_service.delete_by_id(
                    resource_set.id, force=True
                )
            if created_boot_resource:
                await self.delete_by_id(boot_resource.id, force=True)
            raise

        return boot_resource, resource_set, resource_file

    async def attach_initrd(
        self,
        resource_id: int,
        stream: AsyncIterable[bytes],
        sha256: str,
        size: int,
        boot_resource_files_service: "BootResourceFilesService",
        boot_resource_file_sync_service: "BootResourceFileSyncService",
        nodes_service: "NodesService",
        temporal_service: "TemporalService",
    ) -> tuple[BootResource, BootResourceSet, BootResourceFile, bool]:
        """Attach an initrd to the latest version of a kernel asset."""
        boot_resource = await self.get_one(
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(
                    [
                        BootResourceClauseFactory.with_id(resource_id),
                        BootResourceClauseFactory.with_custom_kernel_type(),
                    ]
                )
            )
        )
        if boot_resource is None:
            raise NotFoundException()

        latest_set = (
            await self.boot_resource_sets_service.get_latest_for_boot_resource(
                resource_id
            )
        )
        if latest_set is None:
            raise NotFoundException()

        existing_files = await boot_resource_files_service.get_many(
            query=QuerySpec(
                where=BootResourceFileClauseFactory.with_resource_set_id(
                    latest_set.id
                )
            )
        )
        existing_types = {
            resource_file.filetype for resource_file in existing_files
        }
        if BootResourceFileType.BOOT_INITRD in existing_types:
            raise BadRequestException(
                details=[
                    BaseExceptionDetail(
                        type=INVALID_ARGUMENT_VIOLATION_TYPE,
                        message=(
                            "This kernel asset already has an initrd "
                            "attached (asset is already complete)."
                        ),
                    )
                ]
            )

        resource_file = await self.upload_binary(
            stream=stream,
            sha256=sha256,
            size=size,
            resource_set_id=latest_set.id,
            filetype=BootResourceFileType.BOOT_INITRD,
            filename="initrd",
            boot_resource_files_service=boot_resource_files_service,
            boot_resource_file_sync_service=boot_resource_file_sync_service,
            nodes_service=nodes_service,
            temporal_service=temporal_service,
        )

        current_files = await boot_resource_files_service.get_many(
            query=QuerySpec(
                where=BootResourceFileClauseFactory.with_resource_set_id(
                    latest_set.id
                )
            )
        )
        current_types = {
            resource_file.filetype for resource_file in current_files
        }
        complete = {
            BootResourceFileType.BOOT_KERNEL,
            BootResourceFileType.BOOT_INITRD,
        }.issubset(current_types)
        return boot_resource, latest_set, resource_file, complete

    async def get_custom_image_status_by_id(
        self, id: int
    ) -> CustomBootResourceStatus | None:
        return await self.repository.get_custom_image_status_by_id(id)

    async def list_custom_images_status(
        self, page: int, size: int, query: QuerySpec | None = None
    ) -> ListResult[CustomBootResourceStatus]:
        return await self.repository.list_custom_images_status(
            page=page, size=size, query=query
        )

    async def get_custom_image_statistic_by_id(
        self, id: int
    ) -> CustomBootResourceStatistic | None:
        return await self.repository.get_custom_image_statistic_by_id(id)

    async def list_custom_images_statistics(
        self, page: int, size: int, query: QuerySpec | None = None
    ) -> ListResult[CustomBootResourceStatistic]:
        return await self.repository.list_custom_images_statistics(
            page=page, size=size, query=query
        )
