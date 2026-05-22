# Copyright 2025-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from typing import Annotated

from fastapi import Depends, Header, Query, Request, Response
from pydantic import Field
from starlette import status
import structlog

from maasapiserver.common.api.base import Handler, handler
from maasapiserver.common.api.models.responses.errors import (
    BadRequestBodyResponse,
    NotFoundBodyResponse,
    PreconditionFailedBodyResponse,
)
from maasapiserver.v3.api import services
from maasapiserver.v3.api.public.models.requests.boot_resources import (
    BootloaderUploadRequest,
    BootResourceCreateRequest,
    BootResourceFileTypeChoice,
    CustomImageFilterParams,
    InitrdUploadRequest,
    KernelUploadRequest,
)
from maasapiserver.v3.api.public.models.requests.query import PaginationParams
from maasapiserver.v3.api.public.models.responses.base import (
    BaseHal,
    BaseHref,
    OPENAPI_ETAG_HEADER,
)
from maasapiserver.v3.api.public.models.responses.boot_images_common import (
    ImageListResponse,
    ImageResponse,
    ImageStatisticListResponse,
    ImageStatisticResponse,
    ImageStatusListResponse,
    ImageStatusResponse,
)
from maasapiserver.v3.api.public.models.responses.boot_resources import (
    BootAssetFileInfo,
    BootloaderAssetListResponse,
    BootloaderDetailResponse,
    BootloaderListResponse,
    BootloaderResponse,
    KernelAssetHal,
    KernelAssetListResponse,
    KernelDetailResponse,
    KernelResponse,
)
from maasapiserver.v3.auth.base import check_permissions
from maasapiserver.v3.constants import V3_API_PREFIX
from maascommon.enums.boot_resources import (
    BootResourceFileType,
    BootResourceType,
)
from maascommon.openfga.base import MAASResourceEntitlement
from maasservicelayer.builders.bootresourcesets import BootResourceSetBuilder
from maasservicelayer.db.filters import QuerySpec
from maasservicelayer.db.repositories.bootresourcefiles import (
    BootResourceFileClauseFactory,
)
from maasservicelayer.db.repositories.bootresources import (
    BootResourceClauseFactory,
)
from maasservicelayer.db.repositories.bootresourcesets import (
    BootResourceSetClauseFactory,
)
from maasservicelayer.exceptions.catalog import NotFoundException
from maasservicelayer.models.fields import UniqueList
from maasservicelayer.services import ServiceCollectionV3
from maasservicelayer.utils.date import utcnow

logger = structlog.get_logger()


class CustomImagesHandler(Handler):
    """CustomImages API handler."""

    TAGS = ["CustomImages"]

    def get_handlers(self):
        return [
            "list_custom_images_status",
            "get_custom_image_status",
            "list_custom_images_statistic",
            "get_custom_image_statistic",
            "upload_custom_image",
            "list_custom_images",
            "get_custom_image_by_id",
            "bulk_delete_custom_images",
            "delete_custom_image_by_id",
        ]

    def _get_uploaded_filename(self, filetype: BootResourceFileType) -> str:
        # Root tarball images need to have a proper extension to work for
        # ephemeral deployments.
        filetype_filename = {
            BootResourceFileType.ROOT_TGZ: "root.tgz",
            BootResourceFileType.ROOT_TBZ: "root.tbz",
            BootResourceFileType.ROOT_TXZ: "root.txz",
            BootResourceFileType.SELF_EXTRACTING: "installer.bin",
        }
        return filetype_filename.get(filetype, filetype)

    @handler(
        path="/custom_images",
        methods=["POST"],
        tags=TAGS,
        responses={
            201: {
                "model": ImageResponse,
                "headers": {"ETag": OPENAPI_ETAG_HEADER},
            },
            400: {"model": BadRequestBodyResponse},
        },
        response_model_exclude_none=True,
        status_code=201,
        dependencies=[
            Depends(
                check_permissions(
                    openfga_permission=MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES
                )
            )
        ],
        openapi_extra={
            "requestBody": {
                "description": "Image content, presented as an `application/octet-stream` file upload.",
                "required": True,
                "content": {
                    "application/octet-stream": {
                        "schema": {
                            "type": "string",
                            "format": "binary",
                        },
                    },
                },
            }
        },
    )
    async def upload_custom_image(
        self,
        create_request: Annotated[BootResourceCreateRequest, Header()],
        request: Request,
        response: Response,
        services: Annotated[ServiceCollectionV3, Depends(services)],
    ) -> ImageResponse:
        now = utcnow()

        # The body is the file, so we can gather the file size from the Content-Length header.
        # We don't need it as a parameter since the file is already validated through the SHA
        file_size = int(request.headers["content-length"])

        boot_resource = await services.boot_resources.create(
            await create_request.to_builder(services=services)
        )

        version = await services.boot_resources.get_next_version_name(
            boot_resource.id
        )
        resource_set_builder = BootResourceSetBuilder(
            label="uploaded",
            version=version,
            resource_id=boot_resource.id,
            created=now,
            updated=now,
        )

        resource_set = await services.boot_resource_sets.create(
            resource_set_builder
        )

        resource_filetype = BootResourceFileTypeChoice.get_resource_filetype(
            create_request.file_type
        )

        await services.boot_resources.upload_binary(
            stream=request.stream(),
            sha256=create_request.sha256,
            size=file_size,
            resource_set_id=resource_set.id,
            filetype=resource_filetype,
            filename=self._get_uploaded_filename(resource_filetype),
            boot_resource_files_service=services.boot_resource_files,
            boot_resource_file_sync_service=services.boot_resource_file_sync,
            nodes_service=services.nodes,
            temporal_service=services.temporal,
        )

        logger.info(f"Completed upload of file {create_request.name}.")

        response.headers["ETag"] = boot_resource.etag()
        return ImageResponse.from_boot_resource(
            boot_resource=boot_resource,
            self_base_hyperlink=f"{V3_API_PREFIX}/custom_images",
        )

    @handler(
        path="/custom_images",
        methods=["GET"],
        tags=TAGS,
        responses={
            200: {
                "model": ImageListResponse,
            },
        },
        response_model_exclude_none=True,
        status_code=200,
        dependencies=[
            Depends(
                check_permissions(
                    openfga_permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES
                )
            )
        ],
    )
    async def list_custom_images(
        self,
        filters: CustomImageFilterParams = Depends(),  # noqa: B008
        pagination_params: PaginationParams = Depends(),  # noqa: B008
        services: ServiceCollectionV3 = Depends(services),  # noqa: B008
    ) -> ImageListResponse:
        clauses = [
            BootResourceClauseFactory.with_rtype(BootResourceType.UPLOADED)
        ]
        if filter_clause := filters.to_clause():
            clauses.append(filter_clause)
        where_clause = BootResourceClauseFactory.and_clauses(clauses)

        boot_resources = await services.boot_resources.list(
            page=pagination_params.page,
            size=pagination_params.size,
            query=QuerySpec(where=where_clause),
        )

        next_link = None
        if boot_resources.has_next(
            pagination_params.page, pagination_params.size
        ):
            next_link = (
                f"{V3_API_PREFIX}/custom_images?"
                f"{pagination_params.to_next_href_format()}"
            )
            if query_filters := filters.to_href_format():
                next_link += f"&{query_filters}"

        return ImageListResponse(
            items=[
                ImageResponse.from_boot_resource(
                    boot_resource=boot_resource,
                    self_base_hyperlink=f"{V3_API_PREFIX}/custom_images",
                )
                for boot_resource in boot_resources.items
            ],
            total=boot_resources.total,
            next=next_link,
        )

    @handler(
        path="/custom_images/{boot_resource_id}",
        methods=["GET"],
        tags=TAGS,
        responses={
            200: {
                "model": ImageResponse,
                "headers": {"ETag": OPENAPI_ETAG_HEADER},
            },
            404: {"model": NotFoundBodyResponse},
        },
        response_model_exclude_none=True,
        status_code=200,
        dependencies=[
            Depends(
                check_permissions(
                    openfga_permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES
                )
            )
        ],
    )
    async def get_custom_image_by_id(
        self,
        boot_resource_id: int,
        response: Response,
        services: ServiceCollectionV3 = Depends(services),  # noqa: B008
    ) -> ImageResponse:
        boot_resource = await services.boot_resources.get_one(
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(
                    [
                        BootResourceClauseFactory.with_id(boot_resource_id),
                        BootResourceClauseFactory.with_rtype(
                            BootResourceType.UPLOADED
                        ),
                    ]
                )
            ),
        )
        if boot_resource is None:
            raise NotFoundException()
        response.headers["ETag"] = boot_resource.etag()
        return ImageResponse.from_boot_resource(
            boot_resource=boot_resource,
            self_base_hyperlink=f"{V3_API_PREFIX}/custom_images",
        )

    @handler(
        path="/custom_images/{boot_resource_id}",
        methods=["DELETE"],
        tags=TAGS,
        responses={
            204: {},
            404: {"model": NotFoundBodyResponse},
            412: {"model": PreconditionFailedBodyResponse},
        },
        response_model_exclude_none=True,
        status_code=204,
        dependencies=[
            Depends(
                check_permissions(
                    openfga_permission=MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES
                )
            )
        ],
    )
    async def delete_custom_image_by_id(
        self,
        boot_resource_id: int,
        etag_if_match: str | None = Header(alias="if-match", default=None),
        services: ServiceCollectionV3 = Depends(services),  # noqa: B008
    ) -> Response:
        await services.boot_resources.delete_one(
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(
                    [
                        BootResourceClauseFactory.with_id(boot_resource_id),
                        BootResourceClauseFactory.with_rtype(
                            BootResourceType.UPLOADED
                        ),
                    ]
                )
            ),
            etag_if_match=etag_if_match,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @handler(
        path="/custom_images",
        methods=["DELETE"],
        tags=TAGS,
        responses={
            204: {},
            404: {"model": NotFoundBodyResponse},
            412: {"model": PreconditionFailedBodyResponse},
        },
        response_model_exclude_none=True,
        status_code=204,
        dependencies=[
            Depends(
                check_permissions(
                    openfga_permission=MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES
                )
            )
        ],
    )
    async def bulk_delete_custom_images(
        self,
        ids: Annotated[
            UniqueList[int],
            Field(min_length=1),
        ] = Query(  # noqa: B008
            description="ids of custom images to delete", alias="id"
        ),
        services: ServiceCollectionV3 = Depends(services),  # noqa: B008
    ) -> Response:
        await services.boot_resources.delete_many(
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(
                    [
                        BootResourceClauseFactory.with_ids(ids),
                        BootResourceClauseFactory.with_rtype(
                            BootResourceType.UPLOADED
                        ),
                    ]
                )
            ),
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @handler(
        path="/custom_images/statuses",
        methods=["GET"],
        tags=TAGS,
        responses={
            200: {
                "model": ImageStatusListResponse,
            },
        },
        response_model_exclude_none=True,
        status_code=200,
        dependencies=[
            Depends(
                check_permissions(
                    openfga_permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES
                )
            )
        ],
    )
    async def list_custom_images_status(
        self,
        filters: CustomImageFilterParams = Depends(),  # noqa: B008
        pagination_params: PaginationParams = Depends(),  # noqa: B008
        services: ServiceCollectionV3 = Depends(services),  # noqa: B008
    ) -> ImageStatusListResponse:
        statuses = await services.boot_resources.list_custom_images_status(
            page=pagination_params.page,
            size=pagination_params.size,
            query=QuerySpec(where=filters.to_clause()),
        )

        next_link = None
        if statuses.has_next(pagination_params.page, pagination_params.size):
            next_link = (
                f"{V3_API_PREFIX}/custom_images/statuses?"
                f"{pagination_params.to_next_href_format()}"
            )
            if query_filters := filters.to_href_format():
                next_link += f"&{query_filters}"

        return ImageStatusListResponse(
            items=[
                ImageStatusResponse.from_model(status)
                for status in statuses.items
            ],
            next=next_link,
            total=statuses.total,
        )

    @handler(
        path="/custom_images/statuses/{id}",
        methods=["GET"],
        tags=TAGS,
        responses={
            200: {
                "model": ImageStatusResponse,
            },
        },
        response_model_exclude_none=True,
        status_code=200,
        dependencies=[
            Depends(
                check_permissions(
                    openfga_permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES
                )
            )
        ],
    )
    async def get_custom_image_status(
        self,
        id: int,
        services: ServiceCollectionV3 = Depends(services),  # noqa: B008
    ) -> ImageStatusResponse:
        status = await services.boot_resources.get_custom_image_status_by_id(
            id
        )
        if not status:
            raise NotFoundException()

        return ImageStatusResponse.from_model(status)

    @handler(
        path="/custom_images/statistics",
        methods=["GET"],
        tags=TAGS,
        responses={
            200: {
                "model": ImageStatisticListResponse,
            },
        },
        response_model_exclude_none=True,
        status_code=200,
        dependencies=[
            Depends(
                check_permissions(
                    openfga_permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES
                )
            )
        ],
    )
    async def list_custom_images_statistic(
        self,
        filters: CustomImageFilterParams = Depends(),  # noqa: B008
        pagination_params: PaginationParams = Depends(),  # noqa: B008
        services: ServiceCollectionV3 = Depends(services),  # noqa: B008
    ) -> ImageStatisticListResponse:
        statistics = (
            await services.boot_resources.list_custom_images_statistics(
                page=pagination_params.page,
                size=pagination_params.size,
                query=QuerySpec(where=filters.to_clause()),
            )
        )

        next_link = None
        if statistics.has_next(pagination_params.page, pagination_params.size):
            next_link = (
                f"{V3_API_PREFIX}/custom_images/statistics?"
                f"{pagination_params.to_next_href_format()}"
            )
            if query_filters := filters.to_href_format():
                next_link += f"&{query_filters}"

        return ImageStatisticListResponse(
            items=[
                ImageStatisticResponse.from_model(statistic)
                for statistic in statistics.items
            ],
            next=next_link,
            total=statistics.total,
        )

    @handler(
        path="/custom_images/statistics/{id}",
        methods=["GET"],
        tags=TAGS,
        responses={
            200: {
                "model": ImageStatisticResponse,
            },
        },
        response_model_exclude_none=True,
        status_code=200,
        dependencies=[
            Depends(
                check_permissions(
                    openfga_permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES
                )
            )
        ],
    )
    async def get_custom_image_statistic(
        self,
        id: int,
        services: ServiceCollectionV3 = Depends(services),  # noqa: B008
    ) -> ImageStatisticResponse:
        statistic = (
            await services.boot_resources.get_custom_image_statistic_by_id(id)
        )
        if not statistic:
            raise NotFoundException()

        return ImageStatisticResponse.from_model(statistic)


class BootAssetsHandler(Handler):
    """Boot Assets upload API handler for custom bootloaders."""

    TAGS = ["BootAssets"]

    def get_handlers(self):
        return [
            "upload_bootloader",
            "list_boot_asset_bootloaders",
            "get_boot_asset_bootloader",
        ]

    def _bootloader_href(self, bootloader_id: int) -> str:
        return f"{V3_API_PREFIX}/boot_assets/bootloaders/{bootloader_id}"

    @handler(
        path="/boot_assets/bootloaders",
        methods=["POST"],
        tags=TAGS,
        responses={
            201: {"model": BootloaderDetailResponse},
            400: {"model": BadRequestBodyResponse},
        },
        response_model_exclude_none=True,
        status_code=201,
        dependencies=[
            Depends(
                check_permissions(
                    openfga_permission=MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES
                )
            )
        ],
        openapi_extra={
            "requestBody": {
                "description": "Bootloader tarball content (application/octet-stream).",
                "required": True,
                "content": {
                    "application/octet-stream": {
                        "schema": {
                            "type": "string",
                            "format": "binary",
                        }
                    }
                },
            }
        },
    )
    async def upload_bootloader(
        self,
        upload_request: Annotated[BootloaderUploadRequest, Header()],
        request: Request,
        response: Response,
        services: Annotated[ServiceCollectionV3, Depends(services)],
    ) -> BootloaderDetailResponse:
        file_size = int(request.headers["content-length"])

        (
            boot_resource,
            resource_set,
            resource_file,
        ) = await services.boot_resources.create_or_version_bootloader(
            name=upload_request.x_name,
            architecture=upload_request.x_architecture,
            primary_file=upload_request.x_primary_file,
            stream=request.stream(),
            sha256=upload_request.x_sha256,
            size=file_size,
            boot_resource_files_service=services.boot_resource_files,
            boot_resource_file_sync_service=services.boot_resource_file_sync,
            nodes_service=services.nodes,
            temporal_service=services.temporal,
        )

        arch, subarch = boot_resource.split_arch()
        response.status_code = 201
        return BootloaderDetailResponse(
            id=boot_resource.id,
            name=boot_resource.name,
            architecture=arch,
            sub_architecture=subarch,
            version=resource_set.version,
            primary_file=boot_resource.extra.get("primary_file"),
            files=[
                BootAssetFileInfo(
                    filename=resource_file.filename,
                    sha256=resource_file.sha256,
                    size=resource_file.size,
                )
            ],
            created_at=boot_resource.created,
            updated_at=boot_resource.updated,
            hal_links=BaseHal(  # pyright: ignore [reportCallIssue]
                self=BaseHref(href=self._bootloader_href(boot_resource.id))
            ),
        )

    @handler(
        path="/boot_assets/bootloaders",
        methods=["GET"],
        tags=TAGS,
        responses={200: {"model": BootloaderAssetListResponse}},
        response_model_exclude_none=True,
        status_code=200,
        dependencies=[
            Depends(
                check_permissions(
                    openfga_permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES
                )
            )
        ],
    )
    async def list_boot_asset_bootloaders(
        self,
        pagination_params: PaginationParams = Depends(),  # noqa: B008
        name: str | None = Query(default=None),
        architecture: str | None = Query(default=None),
        services: ServiceCollectionV3 = Depends(services),  # noqa: B008
    ) -> BootloaderAssetListResponse:
        clauses = [BootResourceClauseFactory.with_custom_bootloader_type()]
        if name:
            clauses.append(BootResourceClauseFactory.with_name(name))
        if architecture:
            clauses.append(
                BootResourceClauseFactory.with_architecture(architecture)
            )

        boot_resources = await services.boot_resources.list(
            page=pagination_params.page,
            size=pagination_params.size,
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(clauses)
            ),
        )

        items = []
        for boot_resource in boot_resources.items:
            arch, subarch = boot_resource.split_arch()
            latest_set = await services.boot_resource_sets.get_latest_complete_set_for_boot_resource(
                boot_resource.id
            )
            items.append(
                BootloaderDetailResponse(
                    id=boot_resource.id,
                    name=boot_resource.name,
                    architecture=arch,
                    sub_architecture=subarch,
                    version=latest_set.version if latest_set else None,
                    primary_file=boot_resource.extra.get("primary_file"),
                    hal_links=BaseHal(  # pyright: ignore [reportCallIssue]
                        self=BaseHref(
                            href=self._bootloader_href(boot_resource.id)
                        )
                    ),
                )
            )

        next_link = None
        if boot_resources.has_next(
            pagination_params.page, pagination_params.size
        ):
            next_link = (
                f"{V3_API_PREFIX}/boot_assets/bootloaders?"
                f"{pagination_params.to_next_href_format()}"
            )
            extra_filters = []
            if name:
                extra_filters.append(f"name={name}")
            if architecture:
                extra_filters.append(f"architecture={architecture}")
            if extra_filters:
                next_link = f"{next_link}&{'&'.join(extra_filters)}"

        return BootloaderAssetListResponse(
            items=items,
            total=boot_resources.total,
            next=next_link,
        )

    @handler(
        path="/boot_assets/bootloaders/{bootloader_id}",
        methods=["GET"],
        tags=TAGS,
        responses={
            200: {"model": BootloaderDetailResponse},
            404: {"model": NotFoundBodyResponse},
        },
        response_model_exclude_none=True,
        status_code=200,
        dependencies=[
            Depends(
                check_permissions(
                    openfga_permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES
                )
            )
        ],
    )
    async def get_boot_asset_bootloader(
        self,
        bootloader_id: int,
        services: ServiceCollectionV3 = Depends(services),  # noqa: B008
    ) -> BootloaderDetailResponse:
        boot_resource = await services.boot_resources.get_one(
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(
                    [
                        BootResourceClauseFactory.with_id(bootloader_id),
                        BootResourceClauseFactory.with_custom_bootloader_type(),
                    ]
                )
            )
        )
        if boot_resource is None:
            raise NotFoundException()

        resource_sets = await services.boot_resource_sets.get_many(
            query=QuerySpec(
                where=BootResourceSetClauseFactory.with_resource_id(
                    boot_resource.id
                )
            )
        )
        latest_set = (
            await services.boot_resource_sets.get_latest_for_boot_resource(
                boot_resource.id
            )
        )

        files = []
        if latest_set is not None:
            latest_files = await services.boot_resource_files.get_many(
                query=QuerySpec(
                    where=BootResourceFileClauseFactory.with_resource_set_id(
                        latest_set.id
                    )
                )
            )
            files = [
                BootAssetFileInfo(
                    filename=resource_file.filename,
                    sha256=resource_file.sha256,
                    size=resource_file.size,
                )
                for resource_file in latest_files
            ]

        arch, subarch = boot_resource.split_arch()
        return BootloaderDetailResponse(
            id=boot_resource.id,
            name=boot_resource.name,
            architecture=arch,
            sub_architecture=subarch,
            latest_version=latest_set.version if latest_set else None,
            versions=sorted(
                [resource_set.version for resource_set in resource_sets]
            ),
            primary_file=boot_resource.extra.get("primary_file"),
            files=files,
            created_at=boot_resource.created,
            updated_at=boot_resource.updated,
            hal_links=BaseHal(  # pyright: ignore [reportCallIssue]
                self=BaseHref(href=self._bootloader_href(boot_resource.id))
            ),
        )


class BootKernelsHandler(Handler):
    """Boot kernels upload API handler for custom kernels."""

    TAGS = ["BootAssets"]

    def get_handlers(self):
        return [
            "upload_kernel",
            "attach_kernel_initrd",
            "list_boot_asset_kernels",
            "get_boot_asset_kernel",
        ]

    def _kernel_href(self, kernel_id: int) -> str:
        return f"{V3_API_PREFIX}/boot_assets/kernels/{kernel_id}"

    def _kernel_initrd_href(self, kernel_id: int) -> str:
        return f"{self._kernel_href(kernel_id)}/initrd"

    def _kernel_files_to_info(
        self, resource_files: list
    ) -> list[BootAssetFileInfo]:
        return [
            BootAssetFileInfo(
                filename=resource_file.filename,
                sha256=resource_file.sha256,
                size=resource_file.size,
            )
            for resource_file in resource_files
        ]

    def _kernel_complete(self, resource_files: list) -> bool:
        filetypes = {
            resource_file.filetype for resource_file in resource_files
        }
        return {
            BootResourceFileType.BOOT_KERNEL,
            BootResourceFileType.BOOT_INITRD,
        }.issubset(filetypes)

    @handler(
        path="/boot_assets/kernels",
        methods=["POST"],
        tags=TAGS,
        responses={
            201: {"model": KernelDetailResponse},
            400: {"model": BadRequestBodyResponse},
        },
        response_model_exclude_none=True,
        status_code=201,
        dependencies=[
            Depends(
                check_permissions(
                    openfga_permission=MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES
                )
            )
        ],
        openapi_extra={
            "requestBody": {
                "description": "Kernel binary content (application/octet-stream).",
                "required": True,
                "content": {
                    "application/octet-stream": {
                        "schema": {"type": "string", "format": "binary"}
                    }
                },
            }
        },
    )
    async def upload_kernel(
        self,
        upload_request: Annotated[KernelUploadRequest, Header()],
        request: Request,
        response: Response,
        services: Annotated[ServiceCollectionV3, Depends(services)],
    ) -> KernelDetailResponse:
        file_size = int(request.headers["content-length"])
        (
            boot_resource,
            resource_set,
            resource_file,
        ) = await services.boot_resources.start_kernel_upload(
            name=upload_request.x_name,
            architecture=upload_request.x_architecture,
            kflavor=upload_request.x_kflavor,
            stream=request.stream(),
            sha256=upload_request.x_sha256,
            size=file_size,
            boot_resource_files_service=services.boot_resource_files,
            boot_resource_file_sync_service=services.boot_resource_file_sync,
            nodes_service=services.nodes,
            temporal_service=services.temporal,
        )

        arch, subarch = boot_resource.split_arch()
        response.status_code = 201
        return KernelDetailResponse(
            id=boot_resource.id,
            name=boot_resource.name,
            architecture=arch,
            sub_architecture=subarch,
            kflavor=boot_resource.kflavor,
            version=resource_set.version,
            complete=False,
            files=self._kernel_files_to_info([resource_file]),
            created_at=boot_resource.created,
            updated_at=boot_resource.updated,
            hal_links=KernelAssetHal(  # pyright: ignore [reportCallIssue]
                self=BaseHref(href=self._kernel_href(boot_resource.id)),
                initrd=BaseHref(
                    href=self._kernel_initrd_href(boot_resource.id)
                ),
            ),
        )

    @handler(
        path="/boot_assets/kernels/{resource_id}/initrd",
        methods=["POST"],
        tags=TAGS,
        responses={
            200: {"model": KernelDetailResponse},
            400: {"model": BadRequestBodyResponse},
            404: {"model": NotFoundBodyResponse},
        },
        response_model_exclude_none=True,
        status_code=200,
        dependencies=[
            Depends(
                check_permissions(
                    openfga_permission=MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES
                )
            )
        ],
        openapi_extra={
            "requestBody": {
                "description": "Initrd binary content (application/octet-stream).",
                "required": True,
                "content": {
                    "application/octet-stream": {
                        "schema": {"type": "string", "format": "binary"}
                    }
                },
            }
        },
    )
    async def attach_kernel_initrd(
        self,
        resource_id: int,
        upload_request: Annotated[InitrdUploadRequest, Header()],
        request: Request,
        services: Annotated[ServiceCollectionV3, Depends(services)],
    ) -> KernelDetailResponse:
        file_size = int(request.headers["content-length"])
        (
            boot_resource,
            resource_set,
            _,
            complete,
        ) = await services.boot_resources.attach_initrd(
            resource_id=resource_id,
            stream=request.stream(),
            sha256=upload_request.x_sha256,
            size=file_size,
            boot_resource_files_service=services.boot_resource_files,
            boot_resource_file_sync_service=services.boot_resource_file_sync,
            nodes_service=services.nodes,
            temporal_service=services.temporal,
        )

        all_files = await services.boot_resource_files.get_many(
            query=QuerySpec(
                where=BootResourceFileClauseFactory.with_resource_set_id(
                    resource_set.id
                )
            )
        )
        arch, subarch = boot_resource.split_arch()
        return KernelDetailResponse(
            id=boot_resource.id,
            name=boot_resource.name,
            architecture=arch,
            sub_architecture=subarch,
            kflavor=boot_resource.kflavor,
            version=resource_set.version,
            complete=complete,
            files=self._kernel_files_to_info(all_files),
            hal_links=KernelAssetHal(  # pyright: ignore [reportCallIssue]
                self=BaseHref(href=self._kernel_href(boot_resource.id))
            ),
        )

    @handler(
        path="/boot_assets/kernels",
        methods=["GET"],
        tags=TAGS,
        responses={200: {"model": KernelAssetListResponse}},
        response_model_exclude_none=True,
        status_code=200,
        dependencies=[
            Depends(
                check_permissions(
                    openfga_permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES
                )
            )
        ],
    )
    async def list_boot_asset_kernels(
        self,
        pagination_params: PaginationParams = Depends(),  # noqa: B008
        name: str | None = Query(default=None),
        architecture: str | None = Query(default=None),
        kflavor: str | None = Query(default=None),
        services: ServiceCollectionV3 = Depends(services),  # noqa: B008
    ) -> KernelAssetListResponse:
        clauses = [BootResourceClauseFactory.with_custom_kernel_type()]
        if name:
            clauses.append(BootResourceClauseFactory.with_name(name))
        if architecture:
            clauses.append(
                BootResourceClauseFactory.with_architecture(architecture)
            )
        if kflavor:
            clauses.append(BootResourceClauseFactory.with_kflavor(kflavor))

        boot_resources = await services.boot_resources.list(
            page=pagination_params.page,
            size=pagination_params.size,
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(clauses)
            ),
        )

        items = []
        for boot_resource in boot_resources.items:
            latest_set = (
                await services.boot_resource_sets.get_latest_for_boot_resource(
                    boot_resource.id
                )
            )
            files = []
            if latest_set is not None:
                files = await services.boot_resource_files.get_many(
                    query=QuerySpec(
                        where=BootResourceFileClauseFactory.with_resource_set_id(
                            latest_set.id
                        )
                    )
                )
            arch, subarch = boot_resource.split_arch()
            items.append(
                KernelResponse(
                    id=boot_resource.id,
                    name=boot_resource.name,
                    architecture=arch,
                    sub_architecture=subarch,
                    kflavor=boot_resource.kflavor,
                    version=latest_set.version if latest_set else None,
                    complete=self._kernel_complete(files),
                    hal_links=KernelAssetHal(  # pyright: ignore [reportCallIssue]
                        self=BaseHref(href=self._kernel_href(boot_resource.id))
                    ),
                )
            )

        next_link = None
        if boot_resources.has_next(
            pagination_params.page, pagination_params.size
        ):
            next_link = (
                f"{V3_API_PREFIX}/boot_assets/kernels?"
                f"{pagination_params.to_next_href_format()}"
            )
            extra_filters = []
            if name:
                extra_filters.append(f"name={name}")
            if architecture:
                extra_filters.append(f"architecture={architecture}")
            if kflavor:
                extra_filters.append(f"kflavor={kflavor}")
            if extra_filters:
                next_link = f"{next_link}&{'&'.join(extra_filters)}"

        return KernelAssetListResponse(
            items=items,
            total=boot_resources.total,
            next=next_link,
        )

    @handler(
        path="/boot_assets/kernels/{kernel_id}",
        methods=["GET"],
        tags=TAGS,
        responses={
            200: {"model": KernelDetailResponse},
            404: {"model": NotFoundBodyResponse},
        },
        response_model_exclude_none=True,
        status_code=200,
        dependencies=[
            Depends(
                check_permissions(
                    openfga_permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES
                )
            )
        ],
    )
    async def get_boot_asset_kernel(
        self,
        kernel_id: int,
        services: ServiceCollectionV3 = Depends(services),  # noqa: B008
    ) -> KernelDetailResponse:
        boot_resource = await services.boot_resources.get_one(
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(
                    [
                        BootResourceClauseFactory.with_id(kernel_id),
                        BootResourceClauseFactory.with_custom_kernel_type(),
                    ]
                )
            )
        )
        if boot_resource is None:
            raise NotFoundException()

        resource_sets = await services.boot_resource_sets.get_many(
            query=QuerySpec(
                where=BootResourceSetClauseFactory.with_resource_id(
                    boot_resource.id
                )
            )
        )
        latest_set = (
            await services.boot_resource_sets.get_latest_for_boot_resource(
                boot_resource.id
            )
        )

        files = []
        if latest_set is not None:
            files = await services.boot_resource_files.get_many(
                query=QuerySpec(
                    where=BootResourceFileClauseFactory.with_resource_set_id(
                        latest_set.id
                    )
                )
            )

        arch, subarch = boot_resource.split_arch()
        return KernelDetailResponse(
            id=boot_resource.id,
            name=boot_resource.name,
            architecture=arch,
            sub_architecture=subarch,
            kflavor=boot_resource.kflavor,
            latest_version=latest_set.version if latest_set else None,
            versions=sorted(
                [resource_set.version for resource_set in resource_sets]
            ),
            complete=self._kernel_complete(files),
            files=self._kernel_files_to_info(files),
            created_at=boot_resource.created,
            updated_at=boot_resource.updated,
            hal_links=KernelAssetHal(  # pyright: ignore [reportCallIssue]
                self=BaseHref(href=self._kernel_href(boot_resource.id))
            ),
        )


class BootloadersHandler(Handler):
    """Bootloaders API handler."""

    TAGS = ["Bootloaders"]

    @handler(
        path="/bootloaders",
        methods=["GET"],
        tags=TAGS,
        responses={
            200: {
                "model": BootloaderListResponse,
            }
        },
        response_model_exclude_none=True,
        status_code=200,
        dependencies=[
            Depends(
                check_permissions(
                    openfga_permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES
                )
            )
        ],
    )
    async def list_bootloaders(
        self,
        pagination_params: PaginationParams = Depends(),  # noqa: B008
        services: ServiceCollectionV3 = Depends(services),  # noqa: B008
    ) -> BootloaderListResponse:
        bootloaders = await services.boot_resources.list(
            page=pagination_params.page,
            size=pagination_params.size,
            query=QuerySpec(
                where=BootResourceClauseFactory.not_clause(
                    BootResourceClauseFactory.with_bootloader_type(None)
                )
            ),
        )
        return BootloaderListResponse(
            items=[
                BootloaderResponse.from_model(
                    boot_resource=bootloader,
                    self_base_hyperlink=f"{V3_API_PREFIX}/bootloaders",
                )
                for bootloader in bootloaders.items
            ],
            total=bootloaders.total,
            next=(
                f"{V3_API_PREFIX}/bootloaders?"
                f"{pagination_params.to_next_href_format()}"
                if bootloaders.has_next(
                    pagination_params.page, pagination_params.size
                )
                else None
            ),
        )

    @handler(
        path="/bootloaders/{bootloader_id}",
        methods=["GET"],
        tags=TAGS,
        responses={
            200: {
                "model": BootloaderResponse,
                "headers": {"ETag": OPENAPI_ETAG_HEADER},
            },
            404: {"model": NotFoundBodyResponse},
        },
        response_model_exclude_none=True,
        status_code=200,
        dependencies=[
            Depends(
                check_permissions(
                    openfga_permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES
                )
            )
        ],
    )
    async def get_bootloader(
        self,
        bootloader_id: int,
        response: Response,
        services: ServiceCollectionV3 = Depends(services),  # noqa: B008
    ) -> BootloaderResponse:
        bootloader = await services.boot_resources.get_one(
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(
                    [
                        BootResourceClauseFactory.not_clause(
                            BootResourceClauseFactory.with_bootloader_type(
                                None
                            )
                        ),
                        BootResourceClauseFactory.with_id(bootloader_id),
                    ]
                )
            )
        )
        if bootloader is None:
            raise NotFoundException()
        response.headers["ETag"] = bootloader.etag()
        return BootloaderResponse.from_model(
            boot_resource=bootloader,
            self_base_hyperlink=f"{V3_API_PREFIX}/bootloaders",
        )
