# Copyright 2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
import datetime
import random
from unittest.mock import AsyncMock, Mock, patch

import pytest

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
from maasservicelayer.context import Context
from maasservicelayer.db.filters import QuerySpec
from maasservicelayer.db.repositories.bootresources import (
    BootResourceClauseFactory,
    BootResourcesRepository,
)
from maasservicelayer.db.repositories.bootresourcesets import (
    BootResourceSetClauseFactory,
)
from maasservicelayer.exceptions.catalog import (
    BadRequestException,
    InsufficientStorageException,
)
from maasservicelayer.models.bootresourcefiles import BootResourceFile
from maasservicelayer.models.bootresources import BootResource
from maasservicelayer.models.bootresourcesets import BootResourceSet
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
from maasservicelayer.utils.image_local_files import (
    LocalStoreAllocationFail,
    LocalStoreInvalidHash,
)
from maastesting.factory import factory
from tests.fixtures import AsyncContextManagerMock, AsyncIteratorMock
from tests.fixtures.factories.bootresourcefiles import (
    create_test_bootresourcefile_entry,
)
from tests.fixtures.factories.bootresources import (
    create_test_bootresource_entry,
)
from tests.fixtures.factories.bootresourcesets import (
    create_test_bootresourceset_entry,
)
from tests.maasapiserver.fixtures.db import Fixture
from tests.maasservicelayer.services.base import ServiceCommonTests

TEST_BOOT_RESOURCE = BootResource(
    id=1,
    created=utcnow(),
    updated=utcnow(),
    rtype=BootResourceType.SYNCED,
    name="ubuntu/noble",
    architecture="amd64/generic",
    rolling=False,
    base_image="",
    extra={},
)


class TestCommonBootResourceService(ServiceCommonTests):
    @pytest.fixture
    def service_instance(self) -> BootResourceService:
        return BootResourceService(
            context=Context(),
            repository=Mock(BootResourcesRepository),
            boot_resource_sets_service=Mock(BootResourceSetsService),
        )

    @pytest.fixture
    def test_instance(self) -> BootResource:
        return TEST_BOOT_RESOURCE


class TestBootResourceService:
    @pytest.fixture
    def mock_repository(self) -> Mock:
        return Mock(BootResourcesRepository)

    @pytest.fixture
    def mock_boot_resource_sets_service(self) -> Mock:
        return Mock(BootResourceSetsService)

    @pytest.fixture
    def service(
        self, mock_repository: Mock, mock_boot_resource_sets_service: Mock
    ) -> BootResourceService:
        return BootResourceService(
            context=Context(),
            repository=mock_repository,
            boot_resource_sets_service=mock_boot_resource_sets_service,
        )

    async def make_incomplete_boot_resource(
        self,
        architecture: str,
        fixture: Fixture,
    ) -> None:
        await create_test_bootresource_entry(
            fixture=fixture,
            rtype=BootResourceType.UPLOADED,
            name="",
            architecture=architecture,
        )

    async def make_usable_boot_resource(
        self,
        architecture: str,
        fixture: Fixture,
        version: str = "",
        label: str = "",
        image_filetype: BootResourceFileType = BootResourceFileType.SQUASHFS_IMAGE,
    ) -> tuple[BootResource, BootResourceSet]:
        boot_resource = await create_test_bootresource_entry(
            fixture=fixture,
            rtype=BootResourceType.UPLOADED,
            name="test-name",
            architecture=architecture,
        )

        boot_resource_set = await create_test_bootresourceset_entry(
            fixture=fixture,
            version=version,
            label=label,
            resource_id=boot_resource.id,
        )

        filetypes = {
            BootResourceFileType.BOOT_KERNEL,
            BootResourceFileType.BOOT_INITRD,
        }
        filetypes.add(image_filetype)

        for filetype in filetypes:
            await self.make_boot_resource_file_with_content(
                fixture=fixture,
                resource_set=boot_resource_set,
                filetype=filetype,
            )

        return (boot_resource, boot_resource_set)

    async def make_boot_resource_file_with_content(
        self,
        fixture: Fixture,
        resource_set: BootResourceSet,
        filetype: BootResourceFileType,
    ) -> None:
        await create_test_bootresourcefile_entry(
            fixture=fixture,
            filename=factory.make_name(),
            filename_on_disk=factory.make_name(),
            filetype=filetype,
            sha256=factory.make_hex_string(size=16),
            size=random.randint(100, 1024),
            resource_set_id=resource_set.id,
        )

    async def test_pre_delete_hook(
        self,
        mock_repository: Mock,
        mock_boot_resource_sets_service: Mock,
        service: BootResourceService,
    ) -> None:
        mock_repository.get_by_id.return_value = TEST_BOOT_RESOURCE
        await service.delete_by_id(TEST_BOOT_RESOURCE.id)
        mock_boot_resource_sets_service.delete_many.assert_awaited_once_with(
            query=QuerySpec(
                where=BootResourceSetClauseFactory.with_resource_id(
                    TEST_BOOT_RESOURCE.id
                )
            )
        )

    async def test_pre_delete_many_hook(
        self,
        mock_repository: Mock,
        mock_boot_resource_sets_service: Mock,
        service: BootResourceService,
    ) -> None:
        mock_repository.get_many.return_value = [TEST_BOOT_RESOURCE]
        await service.delete_many(query=QuerySpec())
        mock_boot_resource_sets_service.delete_many.assert_awaited_once_with(
            query=QuerySpec(
                where=BootResourceSetClauseFactory.with_resource_ids(
                    [TEST_BOOT_RESOURCE.id]
                )
            )
        )

    async def test_delete_all_without_sets(
        self,
        mock_repository: Mock,
        mock_boot_resource_sets_service: Mock,
        service: BootResourceService,
    ) -> None:
        mock_boot_resource_sets_service.get_many.return_value = [
            BootResourceSet(
                id=1,
                created=utcnow(),
                updated=utcnow(),
                version="20250618",
                label="stable",
                resource_id=TEST_BOOT_RESOURCE.id,
            ),
        ]

        await service.delete_all_without_sets(query=QuerySpec())

        mock_repository.delete_many.assert_awaited_once_with(
            query=QuerySpec(where=BootResourceClauseFactory.with_ids(set()))
        )

    async def test_delete_all_without_sets_delete_all_boot_resources(
        self,
        mock_repository: Mock,
        mock_boot_resource_sets_service: Mock,
        service: BootResourceService,
    ) -> None:
        mock_repository.get_many.return_value = [TEST_BOOT_RESOURCE]
        mock_boot_resource_sets_service.get_many.return_value = []

        await service.delete_all_without_sets(query=QuerySpec())

        mock_repository.delete_many.assert_awaited_once_with(
            query=QuerySpec(
                where=BootResourceClauseFactory.with_ids(
                    {TEST_BOOT_RESOURCE.id}
                )
            )
        )

    async def test_get_usable_architectures(
        self,
        service: BootResourceService,
        mock_repository: Mock,
        mock_boot_resource_sets_service: Mock,
    ) -> None:
        num_archs = 3
        architectures = []
        for _ in range(1, num_archs + 1):
            architectures.append(
                f"{factory.make_name('arch')}/{factory.make_name('subarch')}"
            )

        # Create several usable resources
        resources = []
        complete_sets = []
        for i in range(1, num_archs + 1):
            resources.append(
                BootResource(
                    id=i,
                    created=utcnow(),
                    updated=utcnow(),
                    rtype=BootResourceType.UPLOADED,
                    name=f"ubuntu/{factory.make_name()}",
                    architecture=architectures[i - 1],
                    rolling=False,
                    base_image="",
                    extra={},
                )
            )
            complete_sets.append(
                BootResourceSet(
                    id=i,
                    resource_id=i,
                    version=str(random.randint(20200618, 20250827)),
                    label=factory.make_name(),
                )
            )
        # ...and an incomplete one
        resources.append(
            BootResource(
                id=num_archs + 1,
                created=utcnow(),
                updated=utcnow(),
                rtype=BootResourceType.UPLOADED,
                name=f"ubuntu/{factory.make_name()}",
                architecture=architectures[-1],
                rolling=False,
                base_image="",
                extra={},
            ),
        )
        complete_sets.append(
            None,
        )

        mock_repository.get_many.return_value = resources
        mock_boot_resource_sets_service.get_latest_complete_set_for_boot_resource.side_effects = complete_sets
        mock_boot_resource_sets_service.is_usable.return_value = True
        mock_boot_resource_sets_service.is_xinstallable.return_value = True

        usable_architectures = await service.get_usable_architectures()

        assert len(usable_architectures) == num_archs

    async def test_get_usable_architectures_combines_subarches(
        self,
        service: BootResourceService,
        mock_repository: Mock,
        mock_boot_resource_sets_service: Mock,
    ) -> None:
        resources = []
        complete_sets = []

        num_archs = 3
        architectures = []
        for i in range(1, num_archs + 1):
            arch = factory.make_name("arch")
            subarches = [factory.make_name("subarch") for _ in range(3)]
            architecture = f"{arch}/{subarches[0]}"
            for subarch in subarches:
                architectures.append(f"{arch}/{subarch}")

            resources.append(
                BootResource(
                    id=i,
                    created=utcnow(),
                    updated=utcnow(),
                    rtype=BootResourceType.UPLOADED,
                    name=f"ubuntu/{factory.make_name()}",
                    architecture=architecture,
                    rolling=False,
                    base_image="",
                    extra={"subarches": ",".join(subarches)},
                )
            )
            complete_sets.append(
                BootResourceSet(
                    id=i,
                    resource_id=i,
                    version=str(random.randint(20200618, 20250827)),
                    label=factory.make_name(),
                )
            )

        mock_repository.get_many.return_value = resources
        mock_boot_resource_sets_service.get_latest_complete_set_for_boot_resource.side_effects = complete_sets
        mock_boot_resource_sets_service.is_usable.return_value = True
        mock_boot_resource_sets_service.is_xinstallable.return_value = True

        usable_architectures = await service.get_usable_architectures()

        assert len(usable_architectures) == len(architectures)

    async def test_get_usable_architectures_combines_platforms(
        self,
        service: BootResourceService,
        mock_repository: Mock,
        mock_boot_resource_sets_service: Mock,
    ) -> None:
        resources = []
        complete_sets = []

        num_archs = 3
        architectures = []
        for i in range(1, num_archs + 1):
            arch = factory.make_name("arch")
            platforms = [factory.make_name("platform") for _ in range(3)]
            for i, platform in enumerate(platforms):
                architectures.append(f"{arch}/{platform}")
                architectures.append(f"{arch}/{platform}-supported")
                architectures.append(f"{arch}/{platform}-also-supported")

                resources.append(
                    BootResource(
                        id=i,
                        created=utcnow(),
                        updated=utcnow(),
                        rtype=BootResourceType.UPLOADED,
                        name=f"ubuntu/{factory.make_name()}",
                        architecture=f"{arch}/hwe-{i}",
                        rolling=False,
                        base_image="",
                        extra={
                            "platform": platform,
                            "supported_platforms": f"{platform}-supported,{platform}-also-supported",
                        },
                    )
                )
                complete_sets.append(
                    BootResourceSet(
                        id=i,
                        resource_id=i,
                        version=str(random.randint(20200618, 20250827)),
                        label=factory.make_name(),
                    )
                )

        mock_repository.get_many.return_value = resources
        mock_boot_resource_sets_service.get_latest_complete_set_for_boot_resource.side_effects = complete_sets
        mock_boot_resource_sets_service.is_usable.return_value = True
        mock_boot_resource_sets_service.is_xinstallable.return_value = True

        usable_architectures = await service.get_usable_architectures()

        assert len(usable_architectures) == len(architectures)

    async def test_get_next_version_name_returns_current_date(
        self,
        mock_boot_resource_sets_service: Mock,
        service: BootResourceService,
    ) -> None:
        boot_resource_id = 42

        mock_boot_resource_sets_service.get_many.return_value = []

        version_name = await service.get_next_version_name(boot_resource_id)

        expected_version_name = datetime.datetime.today().strftime("%Y%m%d")

        assert version_name == expected_version_name

    async def test_get_next_version_name_returns_first_revision(
        self,
        mock_boot_resource_sets_service: Mock,
        service: BootResourceService,
    ) -> None:
        boot_resource_id = 42

        mock_boot_resource_sets_service.get_many.return_value = [
            BootResourceSet(
                id=0,
                version="",
                label="",
                resource_id=boot_resource_id,
            )
        ]

        version_name = await service.get_next_version_name(boot_resource_id)

        current_date_string = datetime.datetime.today().strftime("%Y%m%d")
        expected_version_name = f"{current_date_string}.1"

        assert version_name == expected_version_name

    async def test_get_next_version_name_returns_latest_revision(
        self,
        mock_boot_resource_sets_service: Mock,
        service: BootResourceService,
    ) -> None:
        boot_resource_id = 42
        current_date_string = datetime.datetime.today().strftime("%Y%m%d")

        set_count = random.randint(2, 4)
        test_sets_to_return = []
        for set_id in range(set_count):
            version_str = current_date_string
            if set_id > 0:
                version_str = f"{current_date_string}.{set_id}"
            test_sets_to_return.append(
                BootResourceSet(
                    id=set_id,
                    version=version_str,
                    label="",
                    resource_id=boot_resource_id,
                )
            )
        mock_boot_resource_sets_service.get_many.return_value = (
            test_sets_to_return
        )

        version_name = await service.get_next_version_name(boot_resource_id)

        expected_version_name = f"{current_date_string}.{set_count}"

        assert version_name == expected_version_name

    @patch("maasservicelayer.services.bootresources.MAAS_ID")
    @patch(
        "maasservicelayer.services.bootresources.AsyncLocalBootResourceFile"
    )
    async def test_upload_binary(
        self,
        async_local_file_mock: Mock,
        maas_id_mock: Mock,
        service: BootResourceService,
    ) -> None:
        store = Mock()
        store.write = AsyncMock()
        async_local_file_mock.return_value.store.return_value = (
            AsyncContextManagerMock(store)
        )

        boot_resource_files_service = Mock(BootResourceFilesService)
        boot_resource_files_service.calculate_filename_on_disk.return_value = (
            "file.bin"
        )

        resource_file = Mock()
        resource_file.id = 1
        resource_file.sha256 = "abcd1234"
        resource_file.filename_on_disk = "file.bin"
        resource_file.size = 3
        boot_resource_files_service.create.return_value = resource_file

        boot_resource_file_sync_service = Mock(BootResourceFileSyncService)
        nodes_service = Mock(NodesService)
        nodes_service.get_one.return_value = Mock(id=9)
        temporal_service = Mock(TemporalService)

        maas_id_mock.get.return_value = "region-1"

        uploaded_file = await service.upload_binary(
            stream=AsyncIteratorMock([b"a", b"bc"]),
            sha256="abcd1234",
            size=3,
            resource_set_id=7,
            filetype=BootResourceFileType.ROOT_TGZ,
            filename="root.tgz",
            boot_resource_files_service=boot_resource_files_service,
            boot_resource_file_sync_service=boot_resource_file_sync_service,
            nodes_service=nodes_service,
            temporal_service=temporal_service,
        )

        assert uploaded_file is resource_file
        async_local_file_mock.assert_called_once_with(
            sha256="abcd1234",
            filename_on_disk="file.bin",
            total_size=3,
        )
        store.write.assert_awaited_once_with(bytearray(b"abc"))

        resource_file_builder = (
            boot_resource_files_service.create.await_args.args[0]
        )
        assert resource_file_builder.filename == "root.tgz"
        assert resource_file_builder.filename_on_disk == "file.bin"
        assert resource_file_builder.filetype == BootResourceFileType.ROOT_TGZ
        assert resource_file_builder.sha256 == "abcd1234"
        assert resource_file_builder.size == 3
        assert resource_file_builder.resource_set_id == 7

        sync_builder = (
            boot_resource_file_sync_service.get_or_create.await_args.kwargs[
                "builder"
            ]
        )
        assert sync_builder.file_id == resource_file.id
        assert sync_builder.size == 3
        assert sync_builder.region_id == 9

        temporal_service.register_or_update_workflow_call.assert_called_once_with(
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
            workflow_id=f"sync-bootresources:{short_sha(resource_file.sha256)}",
            wait=False,
        )

    @patch(
        "maasservicelayer.services.bootresources.AsyncLocalBootResourceFile"
    )
    async def test_upload_binary_raises_bad_request_on_hash_mismatch(
        self,
        async_local_file_mock: Mock,
        service: BootResourceService,
    ) -> None:
        async_local_file_mock.return_value.store.side_effect = (
            LocalStoreInvalidHash()
        )
        boot_resource_files_service = Mock(BootResourceFilesService)
        boot_resource_files_service.calculate_filename_on_disk.return_value = (
            "file.bin"
        )

        with pytest.raises(BadRequestException):
            await service.upload_binary(
                stream=AsyncIteratorMock([b"abc"]),
                sha256="abcd1234",
                size=3,
                resource_set_id=7,
                filetype=BootResourceFileType.ROOT_TGZ,
                filename="root.tgz",
                boot_resource_files_service=boot_resource_files_service,
                boot_resource_file_sync_service=Mock(
                    BootResourceFileSyncService
                ),
                nodes_service=Mock(NodesService),
                temporal_service=Mock(TemporalService),
            )

        boot_resource_files_service.create.assert_not_awaited()

    @patch(
        "maasservicelayer.services.bootresources.AsyncLocalBootResourceFile"
    )
    async def test_upload_binary_raises_insufficient_storage(
        self,
        async_local_file_mock: Mock,
        service: BootResourceService,
    ) -> None:
        async_local_file_mock.return_value.store.side_effect = (
            LocalStoreAllocationFail()
        )
        boot_resource_files_service = Mock(BootResourceFilesService)
        boot_resource_files_service.calculate_filename_on_disk.return_value = (
            "file.bin"
        )

        with pytest.raises(InsufficientStorageException):
            await service.upload_binary(
                stream=AsyncIteratorMock([b"abc"]),
                sha256="abcd1234",
                size=3,
                resource_set_id=7,
                filetype=BootResourceFileType.ROOT_TGZ,
                filename="root.tgz",
                boot_resource_files_service=boot_resource_files_service,
                boot_resource_file_sync_service=Mock(
                    BootResourceFileSyncService
                ),
                nodes_service=Mock(NodesService),
                temporal_service=Mock(TemporalService),
            )

        boot_resource_files_service.create.assert_not_awaited()

    async def test_get_custom_image_status_by_id(
        self,
        mock_repository: Mock,
        service: BootResourceService,
    ) -> None:
        mock_repository.get_custom_image_status_by_id.return_value = None

        await service.get_custom_image_status_by_id(1)

        mock_repository.get_custom_image_status_by_id.assert_awaited_once()

    async def test_list_custom_images_status(
        self,
        mock_repository: Mock,
        service: BootResourceService,
    ) -> None:
        mock_repository.list_custom_images_status.return_value = []

        await service.list_custom_images_status(page=1, size=10)

        mock_repository.list_custom_images_status.assert_awaited_once()

    async def test_get_custom_image_statistic_by_id(
        self,
        mock_repository: Mock,
        service: BootResourceService,
    ) -> None:
        await service.get_custom_image_statistic_by_id(1)
        mock_repository.get_custom_image_statistic_by_id.assert_awaited_once_with(
            1
        )

    async def test_list_custom_images_statistic(
        self,
        mock_repository: Mock,
        service: BootResourceService,
    ) -> None:
        await service.list_custom_images_statistics(page=1, size=10)
        mock_repository.list_custom_images_statistics.assert_awaited_once_with(
            page=1, size=10, query=None
        )


class TestKernelUploadService:
    @pytest.fixture
    def mock_repository(self) -> Mock:
        return Mock(BootResourcesRepository)

    @pytest.fixture
    def mock_boot_resource_sets_service(self) -> Mock:
        return Mock(BootResourceSetsService)

    @pytest.fixture
    def service(
        self, mock_repository: Mock, mock_boot_resource_sets_service: Mock
    ) -> BootResourceService:
        return BootResourceService(
            context=Context(),
            repository=mock_repository,
            boot_resource_sets_service=mock_boot_resource_sets_service,
        )

    def make_kernel_resource(
        self,
        *,
        id: int,
        kflavor: str = "generic",
    ) -> BootResource:
        now = utcnow()
        return BootResource(
            id=id,
            created=now,
            updated=now,
            rtype=BootResourceType.UPLOADED,
            name="ubuntu/noble",
            architecture="amd64/generic",
            rolling=False,
            base_image="",
            extra={"subarches": "generic"},
            kflavor=kflavor,
            bootloader_type=None,
            alias="",
            last_deployed=None,
        )

    def make_uploaded_file(
        self,
        resource_set_id: int,
        filetype: BootResourceFileType,
        filename: str,
    ) -> BootResourceFile:
        return BootResourceFile(
            id=random.randint(1, 1000),
            created=utcnow(),
            updated=utcnow(),
            filename=filename,
            filetype=filetype,
            extra={},
            sha256=factory.make_hex_string(size=32),
            size=128,
            filename_on_disk=factory.make_name("uploaded"),
            resource_set_id=resource_set_id,
        )

    async def test_start_kernel_upload_creates_new_resource(
        self,
        service: BootResourceService,
        mock_repository: Mock,
        mock_boot_resource_sets_service: Mock,
    ) -> None:
        created_resource = self.make_kernel_resource(id=1)
        created_set = BootResourceSet(
            id=7,
            created=utcnow(),
            updated=utcnow(),
            version=datetime.datetime.today().strftime("%Y%m%d"),
            label="uploaded",
            resource_id=created_resource.id,
        )
        kernel_file = self.make_uploaded_file(
            created_set.id,
            BootResourceFileType.BOOT_KERNEL,
            "kernel",
        )
        mock_repository.get_one.return_value = None
        mock_repository.create.return_value = created_resource
        mock_boot_resource_sets_service.get_many.return_value = []
        mock_boot_resource_sets_service.create.return_value = created_set
        service.upload_binary = AsyncMock(return_value=kernel_file)

        (
            boot_resource,
            resource_set,
            resource_file,
        ) = await service.start_kernel_upload(
            name="ubuntu/noble",
            architecture="amd64/generic",
            kflavor="generic",
            stream=AsyncIteratorMock([b"kernel"]),
            sha256="a" * 64,
            size=128,
            boot_resource_files_service=Mock(BootResourceFilesService),
            boot_resource_file_sync_service=Mock(BootResourceFileSyncService),
            nodes_service=Mock(NodesService),
            temporal_service=Mock(TemporalService),
        )

        assert boot_resource == created_resource
        assert resource_set == created_set
        assert resource_file == kernel_file
        create_builder = mock_repository.create.await_args.kwargs["builder"]
        assert create_builder.kflavor == "generic"
        assert create_builder.bootloader_type is None
        assert create_builder.extra["subarches"] == "generic"
        upload_kwargs = service.upload_binary.await_args.kwargs
        assert upload_kwargs["filetype"] == BootResourceFileType.BOOT_KERNEL
        assert upload_kwargs["filename"] == "kernel"

    async def test_start_kernel_upload_second_upload_creates_new_version(
        self,
        service: BootResourceService,
        mock_repository: Mock,
        mock_boot_resource_sets_service: Mock,
    ) -> None:
        existing = self.make_kernel_resource(id=1)
        new_set = BootResourceSet(
            id=8,
            created=utcnow(),
            updated=utcnow(),
            version=f"{datetime.datetime.today().strftime('%Y%m%d')}.1",
            label="uploaded",
            resource_id=existing.id,
        )
        mock_repository.get_one.return_value = existing
        mock_boot_resource_sets_service.get_many.return_value = [
            BootResourceSet(
                id=7,
                created=utcnow(),
                updated=utcnow(),
                version=datetime.datetime.today().strftime("%Y%m%d"),
                label="uploaded",
                resource_id=existing.id,
            )
        ]
        mock_boot_resource_sets_service.create.return_value = new_set
        service.upload_binary = AsyncMock(
            return_value=self.make_uploaded_file(
                new_set.id,
                BootResourceFileType.BOOT_KERNEL,
                "kernel",
            )
        )

        boot_resource, resource_set, _ = await service.start_kernel_upload(
            name="ubuntu/noble",
            architecture="amd64/generic",
            kflavor="generic",
            stream=AsyncIteratorMock([b"kernel-v2"]),
            sha256="b" * 64,
            size=128,
            boot_resource_files_service=Mock(BootResourceFilesService),
            boot_resource_file_sync_service=Mock(BootResourceFileSyncService),
            nodes_service=Mock(NodesService),
            temporal_service=Mock(TemporalService),
        )

        assert boot_resource == existing
        assert resource_set == new_set
        assert resource_set.version.endswith(".1")
        mock_repository.create.assert_not_awaited()

    async def test_start_kernel_upload_rolls_back_on_sha_mismatch(
        self,
        service: BootResourceService,
        mock_repository: Mock,
        mock_boot_resource_sets_service: Mock,
    ) -> None:
        created_resource = self.make_kernel_resource(id=1)
        created_set = BootResourceSet(
            id=7,
            created=utcnow(),
            updated=utcnow(),
            version=datetime.datetime.today().strftime("%Y%m%d"),
            label="uploaded",
            resource_id=created_resource.id,
        )
        mock_repository.get_one.return_value = None
        mock_repository.create.return_value = created_resource
        mock_repository.get_by_id.return_value = created_resource
        mock_repository.delete_by_id.return_value = created_resource
        mock_boot_resource_sets_service.get_many.return_value = []
        mock_boot_resource_sets_service.create.return_value = created_set
        service.upload_binary = AsyncMock(
            side_effect=BadRequestException(details=[])
        )

        with pytest.raises(BadRequestException):
            await service.start_kernel_upload(
                name="ubuntu/noble",
                architecture="amd64/generic",
                kflavor="generic",
                stream=AsyncIteratorMock([b"kernel"]),
                sha256="a" * 64,
                size=128,
                boot_resource_files_service=Mock(BootResourceFilesService),
                boot_resource_file_sync_service=Mock(
                    BootResourceFileSyncService
                ),
                nodes_service=Mock(NodesService),
                temporal_service=Mock(TemporalService),
            )

        mock_boot_resource_sets_service.delete_by_id.assert_awaited_once_with(
            created_set.id, force=True
        )
        mock_repository.delete_by_id.assert_awaited_once_with(
            id=created_resource.id
        )

    async def test_attach_initrd_returns_complete(
        self,
        service: BootResourceService,
        mock_repository: Mock,
        mock_boot_resource_sets_service: Mock,
    ) -> None:
        kernel_resource = self.make_kernel_resource(id=1)
        kernel_set = BootResourceSet(
            id=7,
            created=utcnow(),
            updated=utcnow(),
            version=datetime.datetime.today().strftime("%Y%m%d"),
            label="uploaded",
            resource_id=kernel_resource.id,
        )
        kernel_file = self.make_uploaded_file(
            kernel_set.id,
            BootResourceFileType.BOOT_KERNEL,
            "kernel",
        )
        initrd_file = self.make_uploaded_file(
            kernel_set.id,
            BootResourceFileType.BOOT_INITRD,
            "initrd",
        )
        boot_resource_files_service = Mock(BootResourceFilesService)
        boot_resource_files_service.get_many.side_effect = [
            [kernel_file],
            [kernel_file, initrd_file],
        ]
        mock_repository.get_one.return_value = kernel_resource
        mock_boot_resource_sets_service.get_latest_for_boot_resource.return_value = kernel_set
        service.upload_binary = AsyncMock(return_value=initrd_file)

        (
            boot_resource,
            resource_set,
            resource_file,
            complete,
        ) = await service.attach_initrd(
            resource_id=kernel_resource.id,
            stream=AsyncIteratorMock([b"initrd"]),
            sha256="b" * 64,
            size=128,
            boot_resource_files_service=boot_resource_files_service,
            boot_resource_file_sync_service=Mock(BootResourceFileSyncService),
            nodes_service=Mock(NodesService),
            temporal_service=Mock(TemporalService),
        )

        assert boot_resource == kernel_resource
        assert resource_set == kernel_set
        assert resource_file == initrd_file
        assert complete is True
        upload_kwargs = service.upload_binary.await_args.kwargs
        assert upload_kwargs["filetype"] == BootResourceFileType.BOOT_INITRD
        assert upload_kwargs["filename"] == "initrd"

    async def test_attach_initrd_rejects_complete_asset(
        self,
        service: BootResourceService,
        mock_repository: Mock,
        mock_boot_resource_sets_service: Mock,
    ) -> None:
        kernel_resource = self.make_kernel_resource(id=1)
        kernel_set = BootResourceSet(
            id=7,
            created=utcnow(),
            updated=utcnow(),
            version=datetime.datetime.today().strftime("%Y%m%d"),
            label="uploaded",
            resource_id=kernel_resource.id,
        )
        kernel_file = self.make_uploaded_file(
            kernel_set.id,
            BootResourceFileType.BOOT_KERNEL,
            "kernel",
        )
        initrd_file = self.make_uploaded_file(
            kernel_set.id,
            BootResourceFileType.BOOT_INITRD,
            "initrd",
        )
        boot_resource_files_service = Mock(BootResourceFilesService)
        boot_resource_files_service.get_many.return_value = [
            kernel_file,
            initrd_file,
        ]
        mock_repository.get_one.return_value = kernel_resource
        mock_boot_resource_sets_service.get_latest_for_boot_resource.return_value = kernel_set
        service.upload_binary = AsyncMock()

        with pytest.raises(BadRequestException):
            await service.attach_initrd(
                resource_id=kernel_resource.id,
                stream=AsyncIteratorMock([b"initrd"]),
                sha256="b" * 64,
                size=128,
                boot_resource_files_service=boot_resource_files_service,
                boot_resource_file_sync_service=Mock(
                    BootResourceFileSyncService
                ),
                nodes_service=Mock(NodesService),
                temporal_service=Mock(TemporalService),
            )

        service.upload_binary.assert_not_awaited()


class TestCreateOrVersionBootloaderService:
    @pytest.fixture
    def mock_repository(self) -> Mock:
        return Mock(BootResourcesRepository)

    @pytest.fixture
    def mock_boot_resource_sets_service(self) -> Mock:
        return Mock(BootResourceSetsService)

    @pytest.fixture
    def service(
        self, mock_repository: Mock, mock_boot_resource_sets_service: Mock
    ) -> BootResourceService:
        return BootResourceService(
            context=Context(),
            repository=mock_repository,
            boot_resource_sets_service=mock_boot_resource_sets_service,
        )

    def make_boot_resource(
        self,
        *,
        id: int,
        primary_file: str,
        updated: datetime.datetime | None = None,
    ) -> BootResource:
        now = updated or utcnow()
        return BootResource(
            id=id,
            created=now,
            updated=now,
            rtype=BootResourceType.UPLOADED,
            name="ubuntu/jammy",
            architecture="amd64/generic",
            rolling=False,
            base_image="",
            extra={
                "primary_file": primary_file,
                "subarches": "generic",
            },
            kflavor=None,
            bootloader_type="uefi",
            alias="",
            last_deployed=None,
        )

    def make_uploaded_file(self, resource_set_id: int) -> BootResourceFile:
        return BootResourceFile(
            id=random.randint(1, 1000),
            created=utcnow(),
            updated=utcnow(),
            filename="shimx64.efi",
            filetype=BootResourceFileType.ARCHIVE_TAR_XZ,
            extra={},
            sha256="a" * 64,
            size=128,
            filename_on_disk=factory.make_name("uploaded"),
            resource_set_id=resource_set_id,
        )

    async def test_create_or_version_bootloader_creates_new_resource(
        self,
        service: BootResourceService,
        mock_repository: Mock,
        mock_boot_resource_sets_service: Mock,
    ) -> None:
        created_resource = self.make_boot_resource(
            id=1, primary_file="shimx64.efi"
        )
        created_set = BootResourceSet(
            id=7,
            created=utcnow(),
            updated=utcnow(),
            version=datetime.datetime.today().strftime("%Y%m%d"),
            label="uploaded",
            resource_id=created_resource.id,
        )
        mock_repository.get_one.return_value = None
        mock_repository.create.return_value = created_resource
        mock_boot_resource_sets_service.get_many.return_value = []
        mock_boot_resource_sets_service.create.return_value = created_set
        service.upload_binary = AsyncMock(
            return_value=self.make_uploaded_file(created_set.id)
        )

        (
            boot_resource,
            resource_set,
            resource_file,
        ) = await service.create_or_version_bootloader(
            name="ubuntu/jammy",
            architecture="amd64/generic",
            primary_file="shimx64.efi",
            stream=AsyncIteratorMock([b"bootloader"]),
            sha256="a" * 64,
            size=128,
            boot_resource_files_service=Mock(BootResourceFilesService),
            boot_resource_file_sync_service=Mock(BootResourceFileSyncService),
            nodes_service=Mock(NodesService),
            temporal_service=Mock(TemporalService),
        )

        assert boot_resource == created_resource
        assert resource_set == created_set
        assert resource_file.resource_set_id == created_set.id
        create_builder = mock_repository.create.await_args.kwargs["builder"]
        assert create_builder.bootloader_type == "uefi"
        assert create_builder.extra["primary_file"] == "shimx64.efi"
        assert create_builder.extra["subarches"] == "generic"

    async def test_create_or_version_bootloader_second_upload_creates_new_version(
        self,
        service: BootResourceService,
        mock_repository: Mock,
        mock_boot_resource_sets_service: Mock,
    ) -> None:
        existing = self.make_boot_resource(id=1, primary_file="old.efi")
        updated = self.make_boot_resource(id=1, primary_file="shimx64.efi")
        new_set = BootResourceSet(
            id=8,
            created=utcnow(),
            updated=utcnow(),
            version=f"{datetime.datetime.today().strftime('%Y%m%d')}.1",
            label="uploaded",
            resource_id=existing.id,
        )
        mock_repository.get_one.side_effect = [existing, existing]
        mock_repository.update_by_id.return_value = updated
        mock_boot_resource_sets_service.get_many.return_value = [
            BootResourceSet(
                id=7,
                created=utcnow(),
                updated=utcnow(),
                version=datetime.datetime.today().strftime("%Y%m%d"),
                label="uploaded",
                resource_id=existing.id,
            )
        ]
        mock_boot_resource_sets_service.create.return_value = new_set
        service.upload_binary = AsyncMock(
            return_value=self.make_uploaded_file(8)
        )

        (
            boot_resource,
            resource_set,
            _,
        ) = await service.create_or_version_bootloader(
            name="ubuntu/jammy",
            architecture="amd64/generic",
            primary_file="shimx64.efi",
            stream=AsyncIteratorMock([b"bootloader-v2"]),
            sha256="b" * 64,
            size=128,
            boot_resource_files_service=Mock(BootResourceFilesService),
            boot_resource_file_sync_service=Mock(BootResourceFileSyncService),
            nodes_service=Mock(NodesService),
            temporal_service=Mock(TemporalService),
        )

        assert boot_resource == updated
        assert resource_set == new_set
        assert resource_set.version.endswith(".1")
        update_builder = mock_repository.update_by_id.await_args.kwargs[
            "builder"
        ]
        assert update_builder.extra["primary_file"] == "shimx64.efi"

    async def test_create_or_version_bootloader_rejects_invalid_primary_file(
        self,
        service: BootResourceService,
        mock_repository: Mock,
    ) -> None:
        with pytest.raises(BadRequestException):
            await service.create_or_version_bootloader(
                name="ubuntu/jammy",
                architecture="amd64/generic",
                primary_file="efi/shimx64.efi",
                stream=AsyncIteratorMock([b"bootloader"]),
                sha256="a" * 64,
                size=128,
                boot_resource_files_service=Mock(BootResourceFilesService),
                boot_resource_file_sync_service=Mock(
                    BootResourceFileSyncService
                ),
                nodes_service=Mock(NodesService),
                temporal_service=Mock(TemporalService),
            )

        mock_repository.get_one.assert_not_awaited()

    async def test_create_or_version_bootloader_rolls_back_on_sha_mismatch(
        self,
        service: BootResourceService,
        mock_repository: Mock,
        mock_boot_resource_sets_service: Mock,
    ) -> None:
        created_resource = self.make_boot_resource(
            id=1, primary_file="shimx64.efi"
        )
        created_set = BootResourceSet(
            id=7,
            created=utcnow(),
            updated=utcnow(),
            version=datetime.datetime.today().strftime("%Y%m%d"),
            label="uploaded",
            resource_id=created_resource.id,
        )
        mock_repository.get_one.return_value = None
        mock_repository.create.return_value = created_resource
        mock_repository.get_by_id.return_value = created_resource
        mock_repository.delete_by_id.return_value = created_resource
        mock_boot_resource_sets_service.get_many.return_value = []
        mock_boot_resource_sets_service.create.return_value = created_set
        service.upload_binary = AsyncMock(
            side_effect=BadRequestException(details=[])
        )

        with pytest.raises(BadRequestException):
            await service.create_or_version_bootloader(
                name="ubuntu/jammy",
                architecture="amd64/generic",
                primary_file="shimx64.efi",
                stream=AsyncIteratorMock([b"bootloader"]),
                sha256="a" * 64,
                size=128,
                boot_resource_files_service=Mock(BootResourceFilesService),
                boot_resource_file_sync_service=Mock(
                    BootResourceFileSyncService
                ),
                nodes_service=Mock(NodesService),
                temporal_service=Mock(TemporalService),
            )

        mock_boot_resource_sets_service.delete_by_id.assert_awaited_once_with(
            created_set.id, force=True
        )
        mock_repository.delete_by_id.assert_awaited_once_with(
            id=created_resource.id
        )
