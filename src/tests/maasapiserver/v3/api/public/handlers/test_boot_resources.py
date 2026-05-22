# Copyright 2025-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import hashlib
from io import BytesIO
from typing import Callable
from unittest.mock import MagicMock, Mock, patch

from httpx import AsyncClient
import pytest

from maasapiserver.common.api.models.responses.errors import ErrorBodyResponse
from maasapiserver.v3.api.public.models.responses.boot_images_common import (
    ImageListResponse,
    ImageResponse,
    ImageStatisticListResponse,
    ImageStatisticResponse,
    ImageStatusListResponse,
)
from maasapiserver.v3.api.public.models.responses.boot_resources import (
    BootAssetFileInfo,
    BootloaderAssetListResponse,
    BootloaderDetailResponse,
    BootloaderListResponse,
    BootloaderResponse,
    KernelAssetListResponse,
    KernelDetailResponse,
)
from maasapiserver.v3.constants import V3_API_PREFIX
from maascommon.enums.boot_resources import (
    BootResourceFileType,
    BootResourceType,
    ImageStatus,
)
from maascommon.openfga.base import MAASResourceEntitlement
from maasservicelayer.builders.bootresources import BootResourceBuilder
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
from maasservicelayer.exceptions.catalog import (
    BadRequestException,
    BaseExceptionDetail,
    InsufficientStorageException,
    NotFoundException,
    PreconditionFailedException,
    ValidationException,
)
from maasservicelayer.exceptions.constants import (
    ETAG_PRECONDITION_VIOLATION_TYPE,
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
from maasservicelayer.services import (
    BootSourceCacheService,
    ServiceCollectionV3,
)
from maasservicelayer.services.bootresourcefiles import (
    BootResourceFilesService,
)
from maasservicelayer.services.bootresourcefilesync import (
    BootResourceFileSyncService,
)
from maasservicelayer.services.bootresources import BootResourceService
from maasservicelayer.services.bootresourcesets import BootResourceSetsService
from maasservicelayer.services.nodes import NodesService
from maasservicelayer.services.temporal import TemporalService
from maasservicelayer.utils.date import utcnow
from maastesting.factory import factory
from tests.maasapiserver.v3.api.public.handlers.base import (
    ApiCommonTests,
    Endpoint,
)

TEST_BOOT_RESOURCE_1 = BootResource(
    id=1,
    created=utcnow(),
    updated=utcnow(),
    rtype=BootResourceType.UPLOADED,
    name="custom/noble-image",
    architecture="amd64/generic",
    rolling=False,
    base_image="",
    extra={},
)

TEST_BOOTLOADER_RESOURCE = BootResource(
    id=2,
    created=utcnow(),
    updated=utcnow(),
    rtype=BootResourceType.UPLOADED,
    name="bootloader/shim",
    architecture="amd64/generic",
    rolling=False,
    base_image="",
    extra={},
    bootloader_type="uefi",
)

TEST_KERNEL_RESOURCE = BootResource(
    id=3,
    created=utcnow(),
    updated=utcnow(),
    rtype=BootResourceType.UPLOADED,
    name="kernel/linux-custom",
    architecture="amd64/generic",
    rolling=False,
    base_image="",
    extra={},
    kflavor="lowlatency",
    bootloader_type=None,
)

TEST_BOOT_RESOURCE_2 = BootResource(
    id=1,
    created=utcnow(),
    updated=utcnow(),
    rtype=BootResourceType.SYNCED,
    name="ubuntu/noble",
    architecture="amd64/generic",
    extra={},
    kflavor=None,
    bootloader_type=None,
    rolling=False,
    base_image="ubuntu/noble",
    alias=None,
    last_deployed=None,
)

TEST_BOOT_RESOURCE_SET = BootResourceSet(
    id=1,
    created=utcnow(),
    updated=utcnow(),
    version="20250829",
    label="uploaded",
    resource_id=1,
)

TEST_BOOT_RESOURCE_FILE = BootResourceFile(
    id=1,
    created=utcnow(),
    updated=utcnow(),
    filename="test.bin",
    filetype=BootResourceFileType.ROOT_TGZ,
    extra={},
    sha256="",
    size=1024,
    filename_on_disk="test.bin",
    resource_set_id=1,
)


class MockTemporaryFile:
    def __init__(self, name: str = "test-tmp-file.txt"):
        self._written_data = b""
        self._name = name

    async def write(self, chunk) -> int:
        self._written_data += chunk
        return len(chunk)

    async def tell(self) -> int:
        return len(self._written_data)

    @property
    def name(self) -> str:
        return self._name

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class TestCustomImagesApi(ApiCommonTests):
    BASE_PATH = f"{V3_API_PREFIX}/custom_images"

    @pytest.fixture
    def endpoints_with_authorization(self) -> list[Endpoint]:
        return [
            Endpoint(
                method="GET",
                path=self.BASE_PATH,
                permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
            ),
            Endpoint(
                method="GET",
                path=f"{self.BASE_PATH}/1",
                permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
            ),
            Endpoint(
                method="POST",
                path=self.BASE_PATH,
                permission=MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
            ),
            Endpoint(
                method="DELETE",
                path=f"{self.BASE_PATH}?id=1",
                permission=MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
            ),
            Endpoint(
                method="DELETE",
                path=f"{self.BASE_PATH}/1",
                permission=MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
            ),
        ]

    def create_dummy_binary_upload_file(
        self,
        name: str | None = "test_upload_file.bin",
        size_in_bytes: int = 1024,
    ) -> BytesIO:
        assert size_in_bytes >= 0, "Size of dummy file must be positive"
        file_bytes = BytesIO()
        file_bytes.name = name
        file_bytes.write(b"0" * size_in_bytes)
        file_bytes.seek(0)
        return file_bytes

    @patch(
        "maasapiserver.v3.api.public.handlers.boot_resources.BootResourceCreateRequest.to_builder"
    )
    async def test_upload_custom_image(
        self,
        request_to_builder_mock: MagicMock,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )
        file_size = 1024
        file_data = self.create_dummy_binary_upload_file(
            name="test.bin", size_in_bytes=file_size
        )

        sha256 = hashlib.sha256()
        sha256.update(file_data.read())
        sha256_str = sha256.hexdigest()
        file_data.seek(0)

        request_to_builder_mock.return_value = None

        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.create.return_value = TEST_BOOT_RESOURCE_1
        services_mock.boot_resources.get_next_version_name.return_value = (
            TEST_BOOT_RESOURCE_SET.version
        )
        services_mock.boot_resources.upload_binary.return_value = (
            TEST_BOOT_RESOURCE_FILE
        )

        services_mock.boot_resource_sets = Mock(BootResourceSetsService)
        services_mock.boot_resource_sets.create.return_value = (
            TEST_BOOT_RESOURCE_SET
        )
        services_mock.boot_resource_files = Mock(BootResourceFilesService)
        services_mock.boot_resource_file_sync = Mock(
            BootResourceFileSyncService
        )
        services_mock.nodes = Mock(NodesService)
        services_mock.temporal = Mock(TemporalService)

        headers = {
            "name": "my-image",
            "sha256": sha256_str,
            "architecture": "amd64/generic",
            "Content-Type": "application/octet-stream",
        }

        response = await client.post(
            url=f"{self.BASE_PATH}",
            headers=headers,
            content=file_data.read(),
        )

        assert response.status_code == 201

        boot_resource_response = ImageResponse(**response.json())

        assert (
            boot_resource_response.os
            == TEST_BOOT_RESOURCE_1.name.split("/")[0]
        )
        assert (
            boot_resource_response.release
            == TEST_BOOT_RESOURCE_1.name.split("/")[1]
        )
        assert (
            boot_resource_response.architecture
            == TEST_BOOT_RESOURCE_1.split_arch()[0]
        )

        services_mock.boot_resources.upload_binary.assert_awaited_once()
        upload_kwargs = (
            services_mock.boot_resources.upload_binary.await_args.kwargs
        )
        assert upload_kwargs["sha256"] == sha256_str
        assert upload_kwargs["size"] == file_size
        assert upload_kwargs["resource_set_id"] == TEST_BOOT_RESOURCE_SET.id
        assert upload_kwargs["filetype"] == BootResourceFileType.ROOT_TGZ
        assert upload_kwargs["filename"] == "root.tgz"
        assert (
            upload_kwargs["boot_resource_files_service"]
            is services_mock.boot_resource_files
        )
        assert (
            upload_kwargs["boot_resource_file_sync_service"]
            is services_mock.boot_resource_file_sync
        )
        assert upload_kwargs["nodes_service"] is services_mock.nodes
        assert upload_kwargs["temporal_service"] is services_mock.temporal

    @patch(
        "maasapiserver.v3.api.public.handlers.boot_resources.BootResourceCreateRequest.to_builder"
    )
    async def test_upload_custom_image_400_sha_does_not_match(
        self,
        request_to_builder_mock: MagicMock,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )
        file_data = self.create_dummy_binary_upload_file(
            name="test.bin", size_in_bytes=1024
        )

        request_to_builder_mock.return_value = None

        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.create.return_value = TEST_BOOT_RESOURCE_1
        services_mock.boot_resources.get_next_version_name.return_value = (
            TEST_BOOT_RESOURCE_SET.version
        )
        services_mock.boot_resources.upload_binary.side_effect = BadRequestException(
            details=[
                BaseExceptionDetail(
                    type=INVALID_ARGUMENT_VIOLATION_TYPE,
                    message="Provided SHA256 does not match calculated one.",
                )
            ]
        )

        services_mock.boot_resource_sets = Mock(BootResourceSetsService)
        services_mock.boot_resource_sets.create.return_value = (
            TEST_BOOT_RESOURCE_SET
        )
        services_mock.boot_resource_files = Mock(BootResourceFilesService)
        services_mock.boot_resource_file_sync = Mock(
            BootResourceFileSyncService
        )
        services_mock.nodes = Mock(NodesService)
        services_mock.temporal = Mock(TemporalService)

        headers = {
            "name": "my-image",
            "sha256": factory.make_hex_string(size=16),
            "architecture": "amd64/generic",
            "Content-Type": "application/octet-stream",
        }

        response = await client.post(
            url=f"{self.BASE_PATH}",
            headers=headers,
            content=file_data.read(),
        )

        assert response.status_code == 400

        error_response = ErrorBodyResponse(**response.json())

        assert error_response.code == 400
        assert error_response.kind == "Error"
        assert (
            error_response.details[0].type == INVALID_ARGUMENT_VIOLATION_TYPE  # pyright: ignore[reportOptionalSubscript]
        )
        assert "SHA256" in error_response.details[0].message  # pyright: ignore[reportOptionalSubscript]

    @patch(
        "maasapiserver.v3.api.public.handlers.boot_resources.BootResourceCreateRequest.to_builder"
    )
    async def test_upload_custom_image_507_insufficient_disk_space(
        self,
        request_to_builder_mock: MagicMock,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )
        request_to_builder_mock.return_value = None

        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.create.return_value = TEST_BOOT_RESOURCE_1
        services_mock.boot_resources.get_next_version_name.return_value = (
            TEST_BOOT_RESOURCE_SET.version
        )
        services_mock.boot_resources.upload_binary.side_effect = (
            InsufficientStorageException()
        )

        services_mock.boot_resource_sets = Mock(BootResourceSetsService)
        services_mock.boot_resource_sets.create.return_value = (
            TEST_BOOT_RESOURCE_SET
        )
        services_mock.boot_resource_files = Mock(BootResourceFilesService)
        services_mock.boot_resource_file_sync = Mock(
            BootResourceFileSyncService
        )
        services_mock.nodes = Mock(NodesService)
        services_mock.temporal = Mock(TemporalService)

        content = b"a" * 100

        headers = {
            "name": "my-image",
            "sha256": str(hashlib.sha256(content).hexdigest()),
            "architecture": "amd64/generic",
            "Content-Type": "application/octet-stream",
        }

        response = await client.post(
            url=f"{self.BASE_PATH}",
            headers=headers,
            content=content,
        )

        assert response.status_code == 507

        error_response = ErrorBodyResponse(**response.json())

        assert error_response.code == 507
        assert error_response.kind == "Error"

    async def test_list_custom_images_200_no_other_page(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.list.return_value = ListResult[
            BootResource
        ](items=[TEST_BOOT_RESOURCE_1], total=1)

        response = await client.get(f"{self.BASE_PATH}?size=1")

        assert response.status_code == 200

        boot_sources_response = ImageListResponse(**response.json())

        assert len(boot_sources_response.items) == 1
        assert boot_sources_response.total == 1
        assert boot_sources_response.next is None

    async def test_list_custom_images_200_other_page(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.list.return_value = ListResult[
            BootResource
        ](items=[TEST_BOOT_RESOURCE_1, TEST_BOOT_RESOURCE_2], total=2)

        response = await client.get(f"{self.BASE_PATH}?size=1")

        assert response.status_code == 200

        boot_resources_response = ImageListResponse(**response.json())

        assert len(boot_resources_response.items) == 2
        assert boot_resources_response.total == 2
        assert (
            boot_resources_response.next == f"{self.BASE_PATH}?page=2&size=1"
        )

    async def test_list_custom_images_filter_by_file_type(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.list.return_value = ListResult[
            BootResource
        ](items=[TEST_BOOT_RESOURCE_1], total=1)

        response = await client.get(
            f"{self.BASE_PATH}?file_type=self-extracting"
        )

        assert response.status_code == 200

        boot_resources_response = ImageListResponse(**response.json())

        assert len(boot_resources_response.items) == 1
        assert boot_resources_response.total == 1
        assert boot_resources_response.next is None

        services_mock.boot_resources.list.assert_called_once()
        call_args = services_mock.boot_resources.list.call_args
        query_spec = call_args.kwargs["query"]
        assert query_spec is not None
        assert query_spec.where is not None

    async def test_list_custom_images_filter_combined(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.list.return_value = ListResult[
            BootResource
        ](items=[TEST_KERNEL_RESOURCE], total=2)

        response = await client.get(
            f"{self.BASE_PATH}?size=1&id=1&id=2&file_type=self-extracting"
            "&type=kernel&name=kernel/linux-custom"
            "&architecture=amd64/generic&kflavor=lowlatency"
        )

        assert response.status_code == 200

        boot_resources_response = ImageListResponse(**response.json())

        assert len(boot_resources_response.items) == 1
        assert boot_resources_response.total == 2
        assert boot_resources_response.next is not None
        assert (
            boot_resources_response.next
            == f"{self.BASE_PATH}?page=2&size=1&id=1&id=2"
            "&file_type=self-extracting&type=kernel"
            "&name=kernel/linux-custom&architecture=amd64/generic"
            "&kflavor=lowlatency"
        )

    async def test_list_custom_images_filter_by_type_bootloader(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.list.return_value = ListResult[
            BootResource
        ](items=[TEST_BOOTLOADER_RESOURCE], total=1)

        response = await client.get(f"{self.BASE_PATH}?type=bootloader")

        assert response.status_code == 200

        boot_resources_response = ImageListResponse(**response.json())

        assert [item.type for item in boot_resources_response.items] == [
            "bootloader"
        ]

    async def test_list_custom_images_filter_by_type_kernel(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.list.return_value = ListResult[
            BootResource
        ](items=[TEST_KERNEL_RESOURCE], total=1)

        response = await client.get(
            f"{self.BASE_PATH}?type=kernel&kflavor=lowlatency"
        )

        assert response.status_code == 200

        boot_resources_response = ImageListResponse(**response.json())

        assert [item.type for item in boot_resources_response.items] == [
            "kernel"
        ]

    async def test_list_custom_images_without_type_returns_all_assets(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.list.return_value = ListResult[
            BootResource
        ](
            items=[
                TEST_BOOT_RESOURCE_1,
                TEST_BOOTLOADER_RESOURCE,
                TEST_KERNEL_RESOURCE,
            ],
            total=3,
        )

        response = await client.get(self.BASE_PATH)

        assert response.status_code == 200

        boot_resources_response = ImageListResponse(**response.json())

        assert [item.type for item in boot_resources_response.items] == [
            "image",
            "bootloader",
            "kernel",
        ]

    async def test_list_custom_images_filter_by_name_and_architecture(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.list.return_value = ListResult[
            BootResource
        ](items=[TEST_BOOT_RESOURCE_1], total=1)

        response = await client.get(
            f"{self.BASE_PATH}?name=custom/noble-image"
            "&architecture=amd64/generic"
        )

        assert response.status_code == 200

        boot_resources_response = ImageListResponse(**response.json())

        assert len(boot_resources_response.items) == 1
        assert boot_resources_response.items[0].type == "image"

    async def test_get_custom_image_by_id_200(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.get_one.return_value = (
            TEST_BOOT_RESOURCE_1
        )

        response = await client.get(f"{self.BASE_PATH}/1")

        assert response.status_code == 200
        assert "ETag" in response.headers

        boot_resource_response = ImageResponse(**response.json())

        assert boot_resource_response.id == 1

    async def test_get_custom_image_by_id_404(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.get_one.return_value = None

        response = await client.get(f"{self.BASE_PATH}/3")

        assert response.status_code == 404
        assert "ETag" not in response.headers

        error_response = ErrorBodyResponse(**response.json())
        assert error_response.kind == "Error"
        assert error_response.code == 404

    async def test_delete_custom_images_204(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.delete_one.return_value = (
            TEST_BOOT_RESOURCE_2
        )

        response = await client.delete(f"{self.BASE_PATH}/1")

        assert response.status_code == 204

        services_mock.boot_resources.delete_one.assert_called_once_with(
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(
                    [
                        BootResourceClauseFactory.with_id(1),
                        BootResourceClauseFactory.with_rtype(
                            BootResourceType.UPLOADED
                        ),
                    ]
                )
            ),
            etag_if_match=None,
        )

    async def test_delete_custom_images_204_by_etag(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )
        correct_etag = "correct_etag"

        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.delete_one.return_value = (
            TEST_BOOT_RESOURCE_2
        )

        response = await client.delete(
            f"{self.BASE_PATH}/1",
            headers={"if-match": correct_etag},
        )

        assert response.status_code == 204

        services_mock.boot_resources.delete_one.assert_called_once_with(
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(
                    [
                        BootResourceClauseFactory.with_id(1),
                        BootResourceClauseFactory.with_rtype(
                            BootResourceType.UPLOADED
                        ),
                    ]
                )
            ),
            etag_if_match=correct_etag,
        )

    async def test_delete_custom_images_404(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.delete_one.side_effect = (
            NotFoundException()
        )

        response = await client.delete(f"{self.BASE_PATH}/2")

        assert response.status_code == 404
        assert "ETag" not in response.headers

        error_response = ErrorBodyResponse(**response.json())

        assert error_response.kind == "Error"
        assert error_response.code == 404

        services_mock.boot_resources.delete_one.assert_called_once_with(
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(
                    [
                        BootResourceClauseFactory.with_id(2),
                        BootResourceClauseFactory.with_rtype(
                            BootResourceType.UPLOADED
                        ),
                    ]
                )
            ),
            etag_if_match=None,
        )

    async def test_delete_custom_images_412_wrong_etag(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )
        wrong_etag = "wrong_etag"
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.delete_one.side_effect = PreconditionFailedException(
            details=[
                BaseExceptionDetail(
                    type=ETAG_PRECONDITION_VIOLATION_TYPE,
                    message=f"The resource etag '{wrong_etag}' did not match 'my_etag'.",
                )
            ]
        )

        response = await client.delete(
            f"{self.BASE_PATH}/2",
            headers={"if-match": wrong_etag},
        )

        assert response.status_code == 412

        error_response = ErrorBodyResponse(**response.json())

        assert error_response.code == 412
        assert error_response.message == "A precondition has failed."
        assert (
            error_response.details[0].type == ETAG_PRECONDITION_VIOLATION_TYPE  # pyright: ignore[reportOptionalSubscript]
        )

        services_mock.boot_resources.delete_one.assert_called_once_with(
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(
                    [
                        BootResourceClauseFactory.with_id(2),
                        BootResourceClauseFactory.with_rtype(
                            BootResourceType.UPLOADED
                        ),
                    ]
                )
            ),
            etag_if_match=wrong_etag,
        )

    async def test_bulk_delete_custom_images(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.delete_many.return_value = None

        response = await client.delete(f"{self.BASE_PATH}?id=1&id=2")
        assert response.status_code == 204
        services_mock.boot_resources.delete_many.assert_awaited_once_with(
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(
                    [
                        BootResourceClauseFactory.with_ids([1, 2]),
                        BootResourceClauseFactory.with_rtype(
                            BootResourceType.UPLOADED
                        ),
                    ]
                )
            )
        )


class TestCustomImageStatusApi(ApiCommonTests):
    BASE_PATH = f"{V3_API_PREFIX}/custom_images/statuses"

    @pytest.fixture
    def endpoints_with_authorization(self) -> list[Endpoint]:
        return [
            Endpoint(
                method="GET",
                path=self.BASE_PATH,
                permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
            ),
            Endpoint(
                method="GET",
                path=f"{self.BASE_PATH}/1",
                permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
            ),
        ]

    async def test_list_custom_images_status_other_page(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.list_custom_images_status.return_value = (
            ListResult[CustomBootResourceStatus](
                items=[
                    CustomBootResourceStatus(
                        id=1,
                        sync_percentage=100.0,
                        status=ImageStatus.READY,
                    )
                ],
                total=2,
            )
        )

        response = await client.get(f"{self.BASE_PATH}?size=1")

        assert response.status_code == 200

        custom_images_status_response = ImageStatusListResponse(
            **response.json()
        )

        assert custom_images_status_response.total == 2
        assert len(custom_images_status_response.items) == 1
        assert (
            custom_images_status_response.next
            == f"{self.BASE_PATH}?page=2&size=1"
        )

    async def test_list_custom_images_status_no_other_page(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.list_custom_images_status.return_value = (
            ListResult[CustomBootResourceStatus](
                items=[
                    CustomBootResourceStatus(
                        id=1,
                        sync_percentage=100.0,
                        status=ImageStatus.READY,
                    )
                ],
                total=1,
            )
        )

        response = await client.get(f"{self.BASE_PATH}?size=1")

        assert response.status_code == 200

        custom_images_status_response = ImageStatusListResponse(
            **response.json()
        )

        assert custom_images_status_response.total == 1
        assert len(custom_images_status_response.items) == 1
        assert custom_images_status_response.next is None


class TestCustomImageStatisticsApi(ApiCommonTests):
    BASE_PATH = f"{V3_API_PREFIX}/custom_images/statistics"

    @pytest.fixture
    def endpoints_with_authorization(self) -> list[Endpoint]:
        return [
            Endpoint(
                method="GET",
                path=self.BASE_PATH,
                permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
            ),
            Endpoint(
                method="GET",
                path=f"{self.BASE_PATH}/1",
                permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
            ),
        ]

    async def test_list_custom_images_statistics_other_page(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.list_custom_images_statistics.return_value = ListResult[
            CustomBootResourceStatistic
        ](
            items=[
                CustomBootResourceStatistic(
                    id=1,
                    last_updated=utcnow(),
                    last_deployed=None,
                    size=1024,
                    deploy_to_memory=True,
                    node_count=2,
                )
            ],
            total=2,
        )

        response = await client.get(f"{self.BASE_PATH}?size=1")

        assert response.status_code == 200

        custom_images_statistics_response = ImageStatisticListResponse(
            **response.json()
        )

        assert custom_images_statistics_response.total == 2
        assert len(custom_images_statistics_response.items) == 1
        assert (
            custom_images_statistics_response.next
            == f"{self.BASE_PATH}?page=2&size=1"
        )

    async def test_list_custom_images_statistics_no_other_page(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.list_custom_images_statistics.return_value = ListResult[
            CustomBootResourceStatistic
        ](
            items=[
                CustomBootResourceStatistic(
                    id=1,
                    last_updated=utcnow(),
                    last_deployed=None,
                    size=1024,
                    deploy_to_memory=True,
                    node_count=2,
                )
            ],
            total=1,
        )

        response = await client.get(f"{self.BASE_PATH}?size=1")

        assert response.status_code == 200

        custom_images_statistics_response = ImageStatisticListResponse(
            **response.json()
        )

        assert custom_images_statistics_response.total == 1
        assert len(custom_images_statistics_response.items) == 1
        assert custom_images_statistics_response.next is None

    async def test_list_custom_images_statistics_filters(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.list_custom_images_statistics.return_value = ListResult[
            CustomBootResourceStatistic
        ](
            items=[
                CustomBootResourceStatistic(
                    id=1,
                    last_updated=utcnow(),
                    last_deployed=None,
                    size=1024,
                    deploy_to_memory=True,
                    node_count=2,
                )
            ],
            total=2,
        )

        response = await client.get(f"{self.BASE_PATH}?size=1&id=1&id=2")
        assert response.status_code == 200

        custom_images_statistics_response = ImageStatisticListResponse(
            **response.json()
        )

        assert custom_images_statistics_response.total == 2
        assert len(custom_images_statistics_response.items) == 1
        assert custom_images_statistics_response.next is not None
        assert (
            custom_images_statistics_response.next
            == f"{self.BASE_PATH}?page=2&size=1&id=1&id=2"
        )

    async def test_get_custom_image_statistic_200(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.get_custom_image_statistic_by_id.return_value = CustomBootResourceStatistic(
            id=1,
            last_updated=utcnow(),
            last_deployed=None,
            size=1024,
            deploy_to_memory=True,
            node_count=2,
        )

        response = await client.get(f"{self.BASE_PATH}/1")

        assert response.status_code == 200
        stat_response = ImageStatisticResponse(**response.json())
        assert stat_response.id == 1

    async def test_get_custom_image_statistic_404(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.get_custom_image_statistic_by_id.return_value = None

        response = await client.get(f"{self.BASE_PATH}/1")

        assert response.status_code == 404
        error_response = ErrorBodyResponse(**response.json())
        assert error_response.kind == "Error"
        assert error_response.code == 404


class TestBootloadersApi(ApiCommonTests):
    BASE_PATH = f"{V3_API_PREFIX}/bootloaders"

    @pytest.fixture
    def endpoints_with_authorization(self) -> list[Endpoint]:
        return [
            Endpoint(
                method="GET",
                path=self.BASE_PATH,
                permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
            ),
            Endpoint(
                method="GET",
                path=f"{self.BASE_PATH}/1",
                permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
            ),
        ]

    @pytest.fixture
    def bootloader(self) -> BootResource:
        now = utcnow()
        return BootResource(
            id=1,
            created=now,
            updated=now,
            name="grub-efi/uefi",
            architecture="amd64/generic",
            extra={},
            rtype=BootResourceType.UPLOADED,
            rolling=False,
            base_image="",
            kflavor=None,
            bootloader_type="uefi",
            alias=None,
            last_deployed=None,
        )

    async def test_list_bootloaders_other_page(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
        bootloader: BootResource,
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.list.return_value = ListResult[
            BootResource
        ](
            items=[bootloader],
            total=2,
        )

        response = await client.get(f"{self.BASE_PATH}?size=1")

        assert response.status_code == 200

        bootloaders_response = BootloaderListResponse(**response.json())

        assert bootloaders_response.total == 2
        assert len(bootloaders_response.items) == 1
        assert bootloaders_response.next == f"{self.BASE_PATH}?page=2&size=1"

        services_mock.boot_resources.list.assert_awaited_once_with(
            page=1,
            size=1,
            query=QuerySpec(
                where=BootResourceClauseFactory.not_clause(
                    BootResourceClauseFactory.with_bootloader_type(None)
                )
            ),
        )

    async def test_list_bootloaders_no_other_page(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
        bootloader: BootResource,
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.list.return_value = ListResult[
            BootResource
        ](
            items=[bootloader],
            total=1,
        )

        response = await client.get(f"{self.BASE_PATH}?size=1")

        assert response.status_code == 200

        bootloaders_response = BootloaderListResponse(**response.json())

        assert bootloaders_response.total == 1
        assert len(bootloaders_response.items) == 1
        assert bootloaders_response.next is None

    async def test_get_bootloader_200(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
        bootloader: BootResource,
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.get_one.return_value = bootloader

        response = await client.get(f"{self.BASE_PATH}/1")

        assert response.status_code == 200
        stat_response = BootloaderResponse(**response.json())
        assert stat_response.id == 1
        services_mock.boot_resources.get_one.assert_awaited_once_with(
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(
                    [
                        BootResourceClauseFactory.not_clause(
                            BootResourceClauseFactory.with_bootloader_type(
                                None
                            )
                        ),
                        BootResourceClauseFactory.with_id(1),
                    ]
                )
            )
        )

    async def test_get_bootloader_404(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.get_one.return_value = None

        response = await client.get(f"{self.BASE_PATH}/1")

        assert response.status_code == 404
        error_response = ErrorBodyResponse(**response.json())
        assert error_response.kind == "Error"
        assert error_response.code == 404


class TestBootAssetsApi(ApiCommonTests):
    BASE_PATH = f"{V3_API_PREFIX}/boot_assets/bootloaders"

    @pytest.fixture
    def endpoints_with_authorization(self) -> list[Endpoint]:
        return [
            Endpoint(
                method="GET",
                path=self.BASE_PATH,
                permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
            ),
            Endpoint(
                method="GET",
                path=f"{self.BASE_PATH}/1",
                permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
            ),
            Endpoint(
                method="POST",
                path=self.BASE_PATH,
                permission=MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
            ),
        ]

    @pytest.fixture
    def bootloader_asset(self) -> BootResource:
        now = utcnow()
        return BootResource(
            id=42,
            created=now,
            updated=now,
            rtype=BootResourceType.UPLOADED,
            name="ubuntu/jammy",
            architecture="amd64/generic",
            rolling=False,
            base_image="",
            extra={"primary_file": "shimx64.efi"},
            kflavor=None,
            bootloader_type="uefi",
            alias=None,
            last_deployed=None,
        )

    @pytest.fixture
    def bootloader_asset_set(self) -> BootResourceSet:
        return BootResourceSet(
            id=7,
            created=utcnow(),
            updated=utcnow(),
            version="20260522",
            label="uploaded",
            resource_id=42,
        )

    @pytest.fixture
    def bootloader_asset_file(self) -> BootResourceFile:
        return BootResourceFile(
            id=9,
            created=utcnow(),
            updated=utcnow(),
            filename="shimx64.efi",
            filetype=BootResourceFileType.ARCHIVE_TAR_XZ,
            extra={},
            sha256="a" * 64,
            size=1024,
            filename_on_disk="uploaded-file",
            resource_set_id=7,
        )

    async def test_upload_bootloader(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
        bootloader_asset: BootResource,
        bootloader_asset_set: BootResourceSet,
        bootloader_asset_file: BootResourceFile,
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.create_or_version_bootloader.return_value = (
            bootloader_asset,
            bootloader_asset_set,
            bootloader_asset_file,
        )
        services_mock.boot_resource_files = Mock(BootResourceFilesService)
        services_mock.boot_resource_file_sync = Mock(
            BootResourceFileSyncService
        )
        services_mock.nodes = Mock(NodesService)
        services_mock.temporal = Mock(TemporalService)

        payload = b"bootloader-tarball"
        response = await client.post(
            self.BASE_PATH,
            headers={
                "x-name": bootloader_asset.name,
                "x-architecture": bootloader_asset.architecture,
                "x-sha256": hashlib.sha256(payload).hexdigest(),
                "x-primary-file": "shimx64.efi",
                "Content-Type": "application/octet-stream",
            },
            content=payload,
        )

        assert response.status_code == 201
        bootloader_response = BootloaderDetailResponse(**response.json())
        assert bootloader_response.id == bootloader_asset.id
        assert bootloader_response.version == bootloader_asset_set.version
        assert bootloader_response.primary_file == "shimx64.efi"
        assert bootloader_response.files == [
            BootAssetFileInfo(
                filename="shimx64.efi",
                sha256="a" * 64,
                size=1024,
            )
        ]
        services_mock.boot_resources.create_or_version_bootloader.assert_awaited_once()

    async def test_upload_bootloader_400_sha_mismatch(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.create_or_version_bootloader.side_effect = BadRequestException(
            details=[
                BaseExceptionDetail(
                    type=INVALID_ARGUMENT_VIOLATION_TYPE,
                    message="Provided SHA256 does not match calculated one.",
                )
            ]
        )
        services_mock.boot_resource_files = Mock(BootResourceFilesService)
        services_mock.boot_resource_file_sync = Mock(
            BootResourceFileSyncService
        )
        services_mock.nodes = Mock(NodesService)
        services_mock.temporal = Mock(TemporalService)

        response = await client.post(
            self.BASE_PATH,
            headers={
                "x-name": "ubuntu/jammy",
                "x-architecture": "amd64/generic",
                "x-sha256": "a" * 64,
                "x-primary-file": "shimx64.efi",
                "Content-Type": "application/octet-stream",
            },
            content=b"bad-tarball",
        )

        assert response.status_code == 400
        error_response = ErrorBodyResponse(**response.json())
        assert error_response.code == 400

    async def test_upload_bootloader_422_missing_primary_file(
        self,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )

        response = await client.post(
            self.BASE_PATH,
            headers={
                "x-name": "ubuntu/jammy",
                "x-architecture": "amd64/generic",
                "x-sha256": "a" * 64,
                "Content-Type": "application/octet-stream",
            },
            content=b"bootloader-tarball",
        )

        assert response.status_code == 422

    async def test_upload_bootloader_422_invalid_primary_file(
        self,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )

        response = await client.post(
            self.BASE_PATH,
            headers={
                "x-name": "ubuntu/jammy",
                "x-architecture": "amd64/generic",
                "x-sha256": "a" * 64,
                "x-primary-file": "../shimx64.efi",
                "Content-Type": "application/octet-stream",
            },
            content=b"bootloader-tarball",
        )

        assert response.status_code == 422

    async def test_list_boot_asset_bootloaders(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
        bootloader_asset: BootResource,
        bootloader_asset_set: BootResourceSet,
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resource_sets = Mock(BootResourceSetsService)
        services_mock.boot_resources.list.return_value = ListResult[
            BootResource
        ](
            items=[bootloader_asset],
            total=2,
        )
        services_mock.boot_resource_sets.get_latest_complete_set_for_boot_resource.return_value = bootloader_asset_set

        response = await client.get(
            f"{self.BASE_PATH}?size=1&name=ubuntu/jammy&architecture=amd64/generic"
        )

        assert response.status_code == 200
        bootloaders_response = BootloaderAssetListResponse(**response.json())
        assert bootloaders_response.total == 2
        assert len(bootloaders_response.items) == 1
        assert (
            bootloaders_response.next
            == f"{self.BASE_PATH}?page=2&size=1&name=ubuntu/jammy&architecture=amd64/generic"
        )
        services_mock.boot_resources.list.assert_awaited_once_with(
            page=1,
            size=1,
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(
                    [
                        BootResourceClauseFactory.with_custom_bootloader_type(),
                        BootResourceClauseFactory.with_name("ubuntu/jammy"),
                        BootResourceClauseFactory.with_architecture(
                            "amd64/generic"
                        ),
                    ]
                )
            ),
        )

    async def test_get_boot_asset_bootloader(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
        bootloader_asset: BootResource,
        bootloader_asset_set: BootResourceSet,
        bootloader_asset_file: BootResourceFile,
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resource_sets = Mock(BootResourceSetsService)
        services_mock.boot_resource_files = Mock(BootResourceFilesService)
        services_mock.boot_resources.get_one.return_value = bootloader_asset
        services_mock.boot_resource_sets.get_many.return_value = [
            BootResourceSet(
                id=6,
                created=utcnow(),
                updated=utcnow(),
                version="20260520",
                label="uploaded",
                resource_id=42,
            ),
            bootloader_asset_set,
        ]
        services_mock.boot_resource_sets.get_latest_for_boot_resource.return_value = bootloader_asset_set
        services_mock.boot_resource_files.get_many.return_value = [
            bootloader_asset_file
        ]

        response = await client.get(f"{self.BASE_PATH}/42")

        assert response.status_code == 200
        bootloader_response = BootloaderDetailResponse(**response.json())
        assert bootloader_response.latest_version == "20260522"
        assert bootloader_response.versions == ["20260520", "20260522"]
        assert bootloader_response.files[0].filename == "shimx64.efi"
        services_mock.boot_resources.get_one.assert_awaited_once_with(
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(
                    [
                        BootResourceClauseFactory.with_id(42),
                        BootResourceClauseFactory.with_custom_bootloader_type(),
                    ]
                )
            )
        )
        services_mock.boot_resource_sets.get_many.assert_awaited_once_with(
            query=QuerySpec(
                where=BootResourceSetClauseFactory.with_resource_id(42)
            )
        )
        services_mock.boot_resource_files.get_many.assert_awaited_once_with(
            query=QuerySpec(
                where=BootResourceFileClauseFactory.with_resource_set_id(
                    bootloader_asset_set.id
                )
            )
        )


class TestBootKernelsHandler(ApiCommonTests):
    BASE_PATH = f"{V3_API_PREFIX}/boot_assets/kernels"

    @pytest.fixture
    def endpoints_with_authorization(self) -> list[Endpoint]:
        return [
            Endpoint(
                method="GET",
                path=self.BASE_PATH,
                permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
            ),
            Endpoint(
                method="GET",
                path=f"{self.BASE_PATH}/42",
                permission=MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
            ),
            Endpoint(
                method="POST",
                path=self.BASE_PATH,
                permission=MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
            ),
            Endpoint(
                method="POST",
                path=f"{self.BASE_PATH}/42/initrd",
                permission=MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
            ),
        ]

    @pytest.fixture
    def kernel_asset(self) -> BootResource:
        now = utcnow()
        return BootResource(
            id=42,
            created=now,
            updated=now,
            rtype=BootResourceType.UPLOADED,
            name="ubuntu/noble",
            architecture="amd64/generic",
            rolling=False,
            base_image="",
            extra={"subarches": "generic"},
            kflavor="generic",
            bootloader_type=None,
            alias=None,
            last_deployed=None,
        )

    @pytest.fixture
    def kernel_asset_set(self) -> BootResourceSet:
        return BootResourceSet(
            id=11,
            created=utcnow(),
            updated=utcnow(),
            version="20260522",
            label="uploaded",
            resource_id=42,
        )

    @pytest.fixture
    def kernel_file(self) -> BootResourceFile:
        return BootResourceFile(
            id=12,
            created=utcnow(),
            updated=utcnow(),
            filename="kernel",
            filetype=BootResourceFileType.BOOT_KERNEL,
            extra={},
            sha256="a" * 64,
            size=1024,
            filename_on_disk="kernel-file",
            resource_set_id=11,
        )

    @pytest.fixture
    def initrd_file(self) -> BootResourceFile:
        return BootResourceFile(
            id=13,
            created=utcnow(),
            updated=utcnow(),
            filename="initrd",
            filetype=BootResourceFileType.BOOT_INITRD,
            extra={},
            sha256="b" * 64,
            size=2048,
            filename_on_disk="initrd-file",
            resource_set_id=11,
        )

    async def test_upload_kernel(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
        kernel_asset: BootResource,
        kernel_asset_set: BootResourceSet,
        kernel_file: BootResourceFile,
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.start_kernel_upload.return_value = (
            kernel_asset,
            kernel_asset_set,
            kernel_file,
        )
        services_mock.boot_resource_files = Mock(BootResourceFilesService)
        services_mock.boot_resource_file_sync = Mock(
            BootResourceFileSyncService
        )
        services_mock.nodes = Mock(NodesService)
        services_mock.temporal = Mock(TemporalService)

        payload = b"kernel-binary"
        response = await client.post(
            self.BASE_PATH,
            headers={
                "x-name": kernel_asset.name,
                "x-architecture": kernel_asset.architecture,
                "x-kflavor": "generic",
                "x-sha256": hashlib.sha256(payload).hexdigest(),
                "Content-Type": "application/octet-stream",
            },
            content=payload,
        )

        assert response.status_code == 201
        kernel_response = KernelDetailResponse(**response.json())
        assert kernel_response.id == kernel_asset.id
        assert kernel_response.complete is False
        assert kernel_response.version == kernel_asset_set.version
        assert kernel_response.files == [
            BootAssetFileInfo(
                filename="kernel",
                sha256="a" * 64,
                size=1024,
            )
        ]
        assert kernel_response.hal_links is not None
        assert kernel_response.hal_links.initrd is not None
        assert (
            kernel_response.hal_links.initrd.href
            == f"{self.BASE_PATH}/{kernel_asset.id}/initrd"
        )
        services_mock.boot_resources.start_kernel_upload.assert_awaited_once()

    async def test_upload_kernel_400_sha_mismatch(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.start_kernel_upload.side_effect = BadRequestException(
            details=[
                BaseExceptionDetail(
                    type=INVALID_ARGUMENT_VIOLATION_TYPE,
                    message="Provided SHA256 does not match calculated one.",
                )
            ]
        )
        services_mock.boot_resource_files = Mock(BootResourceFilesService)
        services_mock.boot_resource_file_sync = Mock(
            BootResourceFileSyncService
        )
        services_mock.nodes = Mock(NodesService)
        services_mock.temporal = Mock(TemporalService)

        response = await client.post(
            self.BASE_PATH,
            headers={
                "x-name": "ubuntu/noble",
                "x-architecture": "amd64/generic",
                "x-kflavor": "generic",
                "x-sha256": "a" * 64,
                "Content-Type": "application/octet-stream",
            },
            content=b"bad-kernel",
        )

        assert response.status_code == 400
        error_response = ErrorBodyResponse(**response.json())
        assert error_response.code == 400

    async def test_attach_kernel_initrd(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
        kernel_asset: BootResource,
        kernel_asset_set: BootResourceSet,
        kernel_file: BootResourceFile,
        initrd_file: BootResourceFile,
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.attach_initrd.return_value = (
            kernel_asset,
            kernel_asset_set,
            initrd_file,
            True,
        )
        services_mock.boot_resource_files = Mock(BootResourceFilesService)
        services_mock.boot_resource_files.get_many.return_value = [
            kernel_file,
            initrd_file,
        ]
        services_mock.boot_resource_file_sync = Mock(
            BootResourceFileSyncService
        )
        services_mock.nodes = Mock(NodesService)
        services_mock.temporal = Mock(TemporalService)

        payload = b"initrd-binary"
        response = await client.post(
            f"{self.BASE_PATH}/42/initrd",
            headers={
                "x-sha256": hashlib.sha256(payload).hexdigest(),
                "Content-Type": "application/octet-stream",
            },
            content=payload,
        )

        assert response.status_code == 200
        kernel_response = KernelDetailResponse(**response.json())
        assert kernel_response.complete is True
        assert [file.filename for file in kernel_response.files] == [
            "kernel",
            "initrd",
        ]

    async def test_attach_kernel_initrd_400_sha_mismatch(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.attach_initrd.side_effect = BadRequestException(
            details=[
                BaseExceptionDetail(
                    type=INVALID_ARGUMENT_VIOLATION_TYPE,
                    message="Provided SHA256 does not match calculated one.",
                )
            ]
        )
        services_mock.boot_resource_files = Mock(BootResourceFilesService)
        services_mock.boot_resource_file_sync = Mock(
            BootResourceFileSyncService
        )
        services_mock.nodes = Mock(NodesService)
        services_mock.temporal = Mock(TemporalService)

        response = await client.post(
            f"{self.BASE_PATH}/42/initrd",
            headers={
                "x-sha256": "b" * 64,
                "Content-Type": "application/octet-stream",
            },
            content=b"bad-initrd",
        )

        assert response.status_code == 400

    async def test_attach_kernel_initrd_404_unknown_resource(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.attach_initrd.side_effect = (
            NotFoundException()
        )
        services_mock.boot_resource_files = Mock(BootResourceFilesService)
        services_mock.boot_resource_file_sync = Mock(
            BootResourceFileSyncService
        )
        services_mock.nodes = Mock(NodesService)
        services_mock.temporal = Mock(TemporalService)

        response = await client.post(
            f"{self.BASE_PATH}/404/initrd",
            headers={
                "x-sha256": "b" * 64,
                "Content-Type": "application/octet-stream",
            },
            content=b"missing-resource",
        )

        assert response.status_code == 404

    async def test_attach_kernel_initrd_400_already_complete(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.attach_initrd.side_effect = BadRequestException(
            details=[
                BaseExceptionDetail(
                    type=INVALID_ARGUMENT_VIOLATION_TYPE,
                    message="This kernel asset already has an initrd attached.",
                )
            ]
        )
        services_mock.boot_resource_files = Mock(BootResourceFilesService)
        services_mock.boot_resource_file_sync = Mock(
            BootResourceFileSyncService
        )
        services_mock.nodes = Mock(NodesService)
        services_mock.temporal = Mock(TemporalService)

        response = await client.post(
            f"{self.BASE_PATH}/42/initrd",
            headers={
                "x-sha256": "b" * 64,
                "Content-Type": "application/octet-stream",
            },
            content=b"duplicate-initrd",
        )

        assert response.status_code == 400

    async def test_list_boot_asset_kernels_with_kflavor_filter(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
        kernel_asset: BootResource,
        kernel_asset_set: BootResourceSet,
        kernel_file: BootResourceFile,
        initrd_file: BootResourceFile,
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resource_sets = Mock(BootResourceSetsService)
        services_mock.boot_resource_files = Mock(BootResourceFilesService)
        services_mock.boot_resources.list.return_value = ListResult[
            BootResource
        ](
            items=[kernel_asset],
            total=2,
        )
        services_mock.boot_resource_sets.get_latest_for_boot_resource.return_value = kernel_asset_set
        services_mock.boot_resource_files.get_many.return_value = [
            kernel_file,
            initrd_file,
        ]

        response = await client.get(
            f"{self.BASE_PATH}?size=1&name=ubuntu/noble&architecture=amd64/generic&kflavor=generic"
        )

        assert response.status_code == 200
        kernels_response = KernelAssetListResponse(**response.json())
        assert kernels_response.total == 2
        assert len(kernels_response.items) == 1
        assert kernels_response.items[0].complete is True
        assert (
            kernels_response.next
            == f"{self.BASE_PATH}?page=2&size=1&name=ubuntu/noble&architecture=amd64/generic&kflavor=generic"
        )
        services_mock.boot_resources.list.assert_awaited_once_with(
            page=1,
            size=1,
            query=QuerySpec(
                where=BootResourceClauseFactory.and_clauses(
                    [
                        BootResourceClauseFactory.with_custom_kernel_type(),
                        BootResourceClauseFactory.with_name("ubuntu/noble"),
                        BootResourceClauseFactory.with_architecture(
                            "amd64/generic"
                        ),
                        BootResourceClauseFactory.with_kflavor("generic"),
                    ]
                )
            ),
        )

    async def test_get_boot_asset_kernel(
        self,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
        kernel_asset: BootResource,
        kernel_asset_set: BootResourceSet,
        kernel_file: BootResourceFile,
        initrd_file: BootResourceFile,
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_VIEW_BOOT_ENTITIES,
        )
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resource_sets = Mock(BootResourceSetsService)
        services_mock.boot_resource_files = Mock(BootResourceFilesService)
        services_mock.boot_resources.get_one.return_value = kernel_asset
        services_mock.boot_resource_sets.get_many.return_value = [
            BootResourceSet(
                id=10,
                created=utcnow(),
                updated=utcnow(),
                version="20260521",
                label="uploaded",
                resource_id=42,
            ),
            kernel_asset_set,
        ]
        services_mock.boot_resource_sets.get_latest_for_boot_resource.return_value = kernel_asset_set
        services_mock.boot_resource_files.get_many.return_value = [
            kernel_file,
            initrd_file,
        ]

        response = await client.get(f"{self.BASE_PATH}/42")

        assert response.status_code == 200
        kernel_response = KernelDetailResponse(**response.json())
        assert kernel_response.latest_version == "20260522"
        assert kernel_response.versions == ["20260521", "20260522"]
        assert kernel_response.complete is True
        assert [file.filename for file in kernel_response.files] == [
            "kernel",
            "initrd",
        ]


class TestONIEImageUpload(ApiCommonTests):
    BASE_PATH = f"{V3_API_PREFIX}/custom_images"

    @pytest.fixture
    def endpoints_with_authorization(self) -> list[Endpoint]:
        return [
            Endpoint(
                method="POST",
                path=self.BASE_PATH,
                permission=MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
            ),
        ]

    @staticmethod
    def create_onie_installer_binary(size_in_bytes: int = 1024) -> bytes:
        return b"ONIE_INSTALLER_MOCK_DATA" * (size_in_bytes // 24)

    @patch(
        "maasapiserver.v3.api.public.handlers.boot_resources.BootResourceCreateRequest.to_builder"
    )
    async def test_upload_onie_image_success(
        self,
        to_builder_mock: MagicMock,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )
        file_data = self.create_onie_installer_binary(size_in_bytes=102400)
        sha256_hash = hashlib.sha256(file_data).hexdigest()

        onie_boot_resource = BootResource(
            id=1,
            rtype=BootResourceType.UPLOADED,
            name="onie/mellanox-3.8.0",
            architecture="amd64/generic",
            extra={"title": "Mellanox ONIE 3.8.0", "subarches": "generic"},
            rolling=False,
            base_image="",
        )

        to_builder_mock.return_value = BootResourceBuilder(
            name="onie/mellanox-3.8.0",
            architecture="amd64/generic",
            base_image="",
            rtype=BootResourceType.UPLOADED,
            extra={"title": "Mellanox ONIE 3.8.0", "subarches": "generic"},
            alias="",
            bootloader_type=None,
            kflavor=None,
            rolling=False,
            last_deployed=None,
            created=utcnow(),
            updated=utcnow(),
        )

        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.create.return_value = onie_boot_resource
        services_mock.boot_resources.get_next_version_name.return_value = "1"
        services_mock.boot_resources.upload_binary.return_value = (
            TEST_BOOT_RESOURCE_FILE
        )

        services_mock.boot_resource_sets = Mock(BootResourceSetsService)
        services_mock.boot_resource_sets.create.return_value = Mock(
            id=1, version="1"
        )

        services_mock.boot_resource_files = Mock(BootResourceFilesService)
        services_mock.boot_resource_file_sync = Mock(
            BootResourceFileSyncService
        )
        services_mock.temporal = Mock(TemporalService)
        services_mock.nodes = Mock(NodesService)

        headers = {
            "name": "onie/mellanox-3.8.0",
            "sha256": sha256_hash,
            "architecture": "amd64/generic",
            "file_type": "tgz",
            "title": "Mellanox ONIE 3.8.0",
            "Content-Type": "application/octet-stream",
        }

        response = await client.post(
            self.BASE_PATH,
            headers=headers,
            content=file_data,
        )

        assert response.status_code == 201
        image = ImageResponse(**response.json())
        assert image.os == "onie"
        assert image.release == "mellanox-3.8.0"
        assert image.title == "Mellanox ONIE 3.8.0"
        assert image.architecture == "amd64"

        upload_kwargs = (
            services_mock.boot_resources.upload_binary.await_args.kwargs
        )
        assert upload_kwargs["sha256"] == sha256_hash
        assert upload_kwargs["size"] == len(file_data)
        assert upload_kwargs["filetype"] == BootResourceFileType.ROOT_TGZ
        assert upload_kwargs["filename"] == "root.tgz"

    @patch(
        "maasapiserver.v3.api.public.handlers.boot_resources.BootResourceCreateRequest.to_builder"
    )
    async def test_upload_onie_image_invalid_name(
        self,
        to_builder_mock: MagicMock,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )
        file_data = self.create_onie_installer_binary(size_in_bytes=1024)
        sha256_hash = hashlib.sha256(file_data).hexdigest()

        services_mock.boot_source_cache = Mock(BootSourceCacheService)
        services_mock.boot_source_cache.get_unique_os_releases.return_value = []
        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.get_usable_architectures.return_value = [
            "amd64/generic"
        ]

        to_builder_mock.side_effect = ValidationException.build_for_field(
            field="name",
            message="Invalid ONIE image name format",
            location="header",
        )

        headers = {
            "name": "onie/invalid_format",
            "sha256": sha256_hash,
            "architecture": "amd64/generic",
            "Content-Type": "application/octet-stream",
        }

        response = await client.post(
            self.BASE_PATH,
            headers=headers,
            content=file_data,
        )

        assert response.status_code == 422
        error_response = ErrorBodyResponse(**response.json())
        assert "name" in str(error_response.details[0].field)

    @patch(
        "maasapiserver.v3.api.public.handlers.boot_resources.BootResourceCreateRequest.to_builder"
    )
    async def test_upload_onie_image_with_self_extracting_type(
        self,
        to_builder_mock: MagicMock,
        services_mock: ServiceCollectionV3,
        mocked_api_client_user_with_permissions: Callable[..., AsyncClient],
    ) -> None:
        """Test uploading an ONIE image with self-extracting file type."""
        client = mocked_api_client_user_with_permissions(
            MAASResourceEntitlement.CAN_EDIT_BOOT_ENTITIES,
        )

        file_data = self.create_onie_installer_binary(size_in_bytes=102400)
        sha256_hash = hashlib.sha256(file_data).hexdigest()

        onie_boot_resource = BootResource(
            id=1,
            rtype=BootResourceType.UPLOADED,
            name="onie/mellanox-3.8.0",
            architecture="amd64/generic",
            extra={"title": "Mellanox ONIE 3.8.0", "subarches": "generic"},
            rolling=False,
            base_image="",
        )

        to_builder_mock.return_value = BootResourceBuilder(
            name="onie/mellanox-3.8.0",
            architecture="amd64/generic",
            base_image="",
            rtype=BootResourceType.UPLOADED,
            extra={"title": "Mellanox ONIE 3.8.0", "subarches": "generic"},
            alias="",
            bootloader_type=None,
            kflavor=None,
            rolling=False,
            last_deployed=None,
            created=utcnow(),
            updated=utcnow(),
        )

        services_mock.boot_resources = Mock(BootResourceService)
        services_mock.boot_resources.create.return_value = onie_boot_resource
        services_mock.boot_resources.get_next_version_name.return_value = "1"
        services_mock.boot_resources.upload_binary.return_value = (
            TEST_BOOT_RESOURCE_FILE
        )

        services_mock.boot_resource_sets = Mock(BootResourceSetsService)
        services_mock.boot_resource_sets.create.return_value = Mock(
            id=1, version="1"
        )

        services_mock.boot_resource_files = Mock(BootResourceFilesService)
        services_mock.boot_resource_file_sync = Mock(
            BootResourceFileSyncService
        )
        services_mock.temporal = Mock(TemporalService)
        services_mock.nodes = Mock(NodesService)

        headers = {
            "name": "onie/mellanox-3.8.0",
            "sha256": sha256_hash,
            "architecture": "amd64/generic",
            "file-type": "self-extracting",
            "Content-Type": "application/octet-stream",
        }

        response = await client.post(
            self.BASE_PATH,
            headers=headers,
            content=file_data,
        )

        assert response.status_code == 201
        upload_kwargs = (
            services_mock.boot_resources.upload_binary.await_args.kwargs
        )
        assert upload_kwargs["sha256"] == sha256_hash
        assert upload_kwargs["size"] == len(file_data)
        assert (
            upload_kwargs["filetype"] == BootResourceFileType.SELF_EXTRACTING
        )
        assert upload_kwargs["filename"] == "installer.bin"
