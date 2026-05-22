#  Copyright 2025 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).
from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field

from maasapiserver.v3.api.public.models.responses.base import (
    BaseHal,
    BaseHref,
    HalResponse,
    PaginatedResponse,
)
from maasservicelayer.models.bootresources import BootResource


class BootResourceResponse(HalResponse[BaseHal]):
    kind: str = Field(default="BootResource")
    id: int
    os: str
    release: str
    architecture: str
    sub_architecture: str

    @classmethod
    def from_model(
        cls, boot_resource: BootResource, self_base_hyperlink: str
    ) -> Self:
        os, release = boot_resource.split_name()
        arch, subarch = boot_resource.split_arch()
        return cls(
            id=boot_resource.id,
            os=os,
            release=release,
            architecture=arch,
            sub_architecture=subarch,
            hal_links=BaseHal(  # pyright: ignore [reportCallIssue]
                self=BaseHref(
                    href=f"{self_base_hyperlink.rstrip('/')}/{boot_resource.id}"
                )
            ),
        )


class BootResourceListResponse(PaginatedResponse[BootResourceResponse]):
    kind: str = Field(default="BootResourceList")


class BootloaderResponse(HalResponse[BaseHal]):
    kind: str = Field(default="Bootloader")
    id: int
    name: str
    architecture: str
    bootloader_type: str

    @classmethod
    def from_model(
        cls, boot_resource: BootResource, self_base_hyperlink: str
    ) -> Self:
        name, _ = boot_resource.split_name()
        arch, _ = boot_resource.split_arch()
        return cls(
            id=boot_resource.id,
            name=name,
            architecture=arch,
            bootloader_type=boot_resource.bootloader_type,
            hal_links=BaseHal(  # pyright: ignore [reportCallIssue]
                self=BaseHref(
                    href=f"{self_base_hyperlink.rstrip('/')}/{boot_resource.id}"
                )
            ),
        )


class BootloaderListResponse(PaginatedResponse[BootloaderResponse]):
    kind: str = Field(default="BootloaderList")


class BootAssetFileInfo(BaseModel):
    filename: str
    sha256: str
    size: int


class KernelAssetHal(BaseHal):
    initrd: BaseHref | None = None


class KernelResponse(HalResponse[KernelAssetHal]):
    kind: str = Field(default="KernelAsset")
    id: int
    name: str
    architecture: str
    sub_architecture: str
    kflavor: str | None = None
    version: str | None = None
    complete: bool = False


class KernelDetailResponse(HalResponse[KernelAssetHal]):
    kind: str = Field(default="KernelAsset")
    id: int
    name: str
    architecture: str
    sub_architecture: str
    kflavor: str | None = None
    version: str | None = None
    latest_version: str | None = None
    versions: list[str] = Field(default_factory=list)
    complete: bool = False
    files: list[BootAssetFileInfo] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class KernelAssetListResponse(PaginatedResponse[KernelResponse]):
    kind: str = Field(default="KernelAssetList")


class BootloaderDetailResponse(HalResponse[BaseHal]):
    kind: str = Field(default="BootloaderAsset")
    id: int
    name: str
    architecture: str
    sub_architecture: str
    version: str | None = None
    latest_version: str | None = None
    versions: list[str] = Field(default_factory=list)
    primary_file: str | None = None
    files: list[BootAssetFileInfo] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class BootloaderAssetListResponse(PaginatedResponse[BootloaderDetailResponse]):
    kind: str = Field(default="BootloaderAssetList")
