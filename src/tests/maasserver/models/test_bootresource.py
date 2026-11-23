# Copyright 2014-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `BootResource`."""

from collections.abc import Iterable
import random

from django.core.exceptions import ValidationError
from django.utils import timezone
import pytest

from maascommon.osystem import OperatingSystemRegistry
from maasserver.enum import (
    BOOT_RESOURCE_FILE_TYPE,
    BOOT_RESOURCE_TYPE,
    BOOT_RESOURCE_TYPE_CHOICES_DICT,
)
from maasserver.models import bootresource
from maasserver.models.bootresource import BootResource
from maasserver.models.config import Config
from maasserver.models.signals import bootsources
from maasserver.testing.factory import factory
from provisioningserver.testing.os import FakeOS


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestBootResourceManager:
    """Tests for the `BootResource` model manager."""

    @pytest.fixture(autouse=True)
    def _setup(self, maasdb):
        self.region = factory.make_RegionController()

    def make_boot_resource(self, rtype, name):
        arch = factory.make_name("arch")
        subarch = factory.make_name("subarch")
        architecture = f"{arch}/{subarch}"
        resource = factory.make_BootResource(
            rtype=rtype, name=name, architecture=architecture
        )
        return resource, (arch, subarch)

    def make_synced_boot_resource(self):
        os = factory.make_name("os")
        series = factory.make_name("series")
        name = f"{os}/{series}"
        resource, (arch, subarch) = self.make_boot_resource(
            BOOT_RESOURCE_TYPE.SYNCED, name=name
        )
        return resource, (os, arch, subarch, series)

    def make_uploaded_boot_resource(self):
        name = factory.make_name("name")
        resource, (arch, subarch) = self.make_boot_resource(
            BOOT_RESOURCE_TYPE.UPLOADED, name=name
        )
        return resource, (name, arch, subarch)

    def test_get_kernels_doesnt_include_all_subarches(self):
        factory.make_usable_boot_resource(
            architecture="amd64/hwe-16.04",
            extra={"subarches": "hwe-p,hwe-t,hwe-16.04,hwe-16.10"},
        )
        assert BootResource.objects.get_kernels() == ["hwe-16.04"]

    def test_get_supported_kernel_compatibility_levels_includes_all_subarches(
        self,
    ):
        factory.make_usable_boot_resource(
            architecture="amd64/hwe-16.04",
            extra={"subarches": "hwe-p,hwe-t,hwe-16.04,hwe-16.10"},
        )
        assert (
            BootResource.objects.get_supported_kernel_compatibility_levels()
            == ["hwe-p", "hwe-t", "hwe-16.04", "hwe-16.10"]
        )

    def test_get_commissionable_resource_returns_iterable(self):
        os = factory.make_name("os")
        series = factory.make_name("series")
        name = f"{os}/{series}"
        factory.make_usable_boot_resource(
            rtype=BOOT_RESOURCE_TYPE.SYNCED, name=name
        )
        commissionables = BootResource.objects.get_commissionable_resource(
            os, series
        )
        assert isinstance(commissionables, Iterable)

    def test_get_commissionable_resource_returns_only_commissionable(self):
        os = factory.make_name("os")
        series = factory.make_name("series")
        name = f"{os}/{series}"
        resource = factory.make_usable_boot_resource(
            rtype=BOOT_RESOURCE_TYPE.SYNCED, name=name
        )
        factory.make_incomplete_boot_resource(
            rtype=BOOT_RESOURCE_TYPE.SYNCED, name=name
        )
        not_commissionable = factory.make_BootResource(
            rtype=BOOT_RESOURCE_TYPE.SYNCED, name=name
        )
        factory.make_BootResourceSet(not_commissionable)
        commissionables = BootResource.objects.get_commissionable_resource(
            os, series
        )
        assert list(commissionables) == [resource]

    def test_get_commissionable_resource_returns_only_for_os_series(self):
        os = factory.make_name("os")
        series = factory.make_name("series")
        name = f"{os}/{series}"
        resource = factory.make_usable_boot_resource(
            rtype=BOOT_RESOURCE_TYPE.SYNCED, name=name
        )
        factory.make_usable_boot_resource()
        commissionables = BootResource.objects.get_commissionable_resource(
            os, series
        )
        assert list(commissionables) == [resource]

    def test_get_commissionable_resource_returns_sorted_by_architecture(self):
        os = factory.make_name("os")
        series = factory.make_name("series")
        name = f"{os}/{series}"
        resource_b = factory.make_usable_boot_resource(
            rtype=BOOT_RESOURCE_TYPE.SYNCED,
            name=name,
            architecture="b/generic",
        )
        resource_a = factory.make_usable_boot_resource(
            rtype=BOOT_RESOURCE_TYPE.SYNCED,
            name=name,
            architecture="a/generic",
        )
        resource_c = factory.make_usable_boot_resource(
            rtype=BOOT_RESOURCE_TYPE.SYNCED,
            name=name,
            architecture="c/generic",
        )
        commissionables = BootResource.objects.get_commissionable_resource(
            os, series
        )
        assert list(commissionables) == [resource_a, resource_b, resource_c]

    def test_get_default_commissioning_resource_returns_i386_first(self):
        os = factory.make_name("os")
        series = factory.make_name("series")
        name = f"{os}/{series}"
        arches = ["i386/generic", "amd64/generic", "arm64/generic"]
        for arch in arches:
            factory.make_usable_boot_resource(
                rtype=BOOT_RESOURCE_TYPE.SYNCED,
                name=name,
                architecture=arch,
            )
        assert (
            BootResource.objects.get_default_commissioning_resource(
                os, series
            ).architecture
            == "i386/generic"
        )

    def test_get_default_commissioning_resource_returns_amd64_second(self):
        os = factory.make_name("os")
        series = factory.make_name("series")
        name = f"{os}/{series}"
        arches = ["amd64/generic", "arm64/generic"]
        for arch in arches:
            factory.make_usable_boot_resource(
                rtype=BOOT_RESOURCE_TYPE.SYNCED,
                name=name,
                architecture=arch,
            )
        assert (
            BootResource.objects.get_default_commissioning_resource(
                os, series
            ).architecture
            == "amd64/generic"
        )

    def test_get_default_commissioning_resource_returns_first_arch(self):
        os = factory.make_name("os")
        series = factory.make_name("series")
        name = f"{os}/{series}"
        arches = ["ppc64el/generic", "arm64/generic"]
        for arch in arches:
            factory.make_usable_boot_resource(
                rtype=BOOT_RESOURCE_TYPE.SYNCED,
                name=name,
                architecture=arch,
            )
        assert (
            BootResource.objects.get_default_commissioning_resource(
                os, series
            ).architecture
            == "arm64/generic"
        )

    def test_get_resource_for_returns_matching_resource(self):
        resources = [
            factory.make_BootResource(rtype=BOOT_RESOURCE_TYPE.SYNCED)
            for _ in range(3)
        ]
        resource = resources.pop()
        subarches = [factory.make_name("subarch") for _ in range(3)]
        subarch = random.choice(subarches)
        extra = resource.extra.copy()
        extra["subarches"] = ",".join(subarches)
        resource.extra = extra
        resource.save()
        osystem, series = resource.name.split("/")
        arch, _ = resource.split_arch()
        assert (
            BootResource.objects.get_resource_for(
                osystem, arch, subarch, series
            )
            == resource
        )

    def test_get_resource_for_returns_custom_resource(self):
        factory.make_BootResource(rtype=BOOT_RESOURCE_TYPE.SYNCED)
        factory.make_BootResource(rtype=BOOT_RESOURCE_TYPE.SYNCED)
        custom = factory.make_BootResource(
            rtype=BOOT_RESOURCE_TYPE.UPLOADED,
            name=factory.make_name(),
            base_image=factory.make_name("ubuntu", "/"),
        )
        subarches = [factory.make_name("subarch") for _ in range(3)]
        subarch = random.choice(subarches)
        extra = custom.extra.copy()
        extra["subarches"] = ",".join(subarches)
        custom.extra = extra
        custom.save()
        osystem = "custom"
        series = custom.name
        arch, _ = custom.split_arch()
        assert (
            BootResource.objects.get_resource_for(
                osystem, arch, subarch, series
            )
            == custom
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestGetAvailableCommissioningResources:
    @pytest.fixture(autouse=True)
    def _setup(self, maasdb):
        self.region = factory.make_RegionController()
        # Disable boot source cache signals.
        bootsources.signals.disable()
        yield
        bootsources.signals.enable()

    def test_returns_empty_if_no_cache(self):
        release = factory.make_name("release")
        name = "ubuntu/%s" % release
        factory.make_usable_boot_resource(
            rtype=BOOT_RESOURCE_TYPE.SYNCED, name=name
        )
        assert (
            BootResource.objects.get_available_commissioning_resources() == []
        )

    def test_returns_empty_if_no_lts(self):
        release = factory.make_name("release")
        name = "ubuntu/%s" % release
        support_eol = factory.make_date().strftime("%Y-%m-%d")
        factory.make_usable_boot_resource(
            rtype=BOOT_RESOURCE_TYPE.SYNCED, name=name
        )
        factory.make_BootSourceCache(
            os="ubuntu",
            release=release,
            release_title=release,
            support_eol=support_eol,
        )
        assert (
            BootResource.objects.get_available_commissioning_resources() == []
        )

    def test_returns_only_lts(self):
        release = factory.make_name("release")
        name = "ubuntu/%s" % release
        support_eol = factory.make_date().strftime("%Y-%m-%d")
        release_title = "%s LTS" % release
        resource = factory.make_usable_boot_resource(
            rtype=BOOT_RESOURCE_TYPE.SYNCED, name=name
        )
        factory.make_BootSourceCache(
            os="ubuntu",
            release=release,
            release_title=release_title,
            support_eol=support_eol,
        )
        other_release = factory.make_name("release")
        other_name = "ubuntu/%s" % other_release
        other_support_eol = factory.make_date().strftime("%Y-%m-%d")
        factory.make_usable_boot_resource(
            rtype=BOOT_RESOURCE_TYPE.SYNCED, name=other_name
        )
        factory.make_BootSourceCache(
            os="ubuntu",
            release=other_release,
            release_title=other_release,
            support_eol=other_support_eol,
        )
        assert (
            BootResource.objects.get_available_commissioning_resources()
            == [resource]
        )

    def test_returns_longest_remaining_supported_lts_first(self):
        trusty_resource = factory.make_usable_boot_resource(
            rtype=BOOT_RESOURCE_TYPE.SYNCED, name="ubuntu/trusty"
        )
        factory.make_BootSourceCache(
            os="ubuntu",
            release="trusty",
            release_title="14.04 LTS",
            support_eol="2019-04-17",
        )
        xenial_resource = factory.make_usable_boot_resource(
            rtype=BOOT_RESOURCE_TYPE.SYNCED, name="ubuntu/xenial"
        )
        factory.make_BootSourceCache(
            os="ubuntu",
            release="xenial",
            release_title="16.04 LTS",
            support_eol="2021-04-17",
        )
        assert (
            BootResource.objects.get_available_commissioning_resources()
            == [xenial_resource, trusty_resource]
        )


@pytest.mark.parametrize(
    "name,arch,subarch,kernels",
    [
        (
            "ubuntu/trusty",
            "amd64",
            "generic",
            ["hwe-t", "hwe-u", "hwe-v", "hwe-rolling"],
        ),
        ("ubuntu/vivid", "i386", "generic", ["hwe-v", "hwe-rolling"]),
        (
            "ubuntu/precise",
            "armfh",
            "generic",
            ["hwe-p", "hwe-t", "hwe-v", "hwe-rolling"],
        ),
        ("ubuntu/wily", "armfh", "hardbank", []),
        (
            "ubuntu/xenial",
            "amd64",
            "generic",
            [
                "hwe-16.04",
                "hwe-16.04-lowlatency",
                "hwe-rolling",
                "hwe-rolling-lowlatency",
            ],
        ),
    ],
    ids=[
        "ubuntu/trusty",
        "ubuntu/vivid",
        "ubuntu/precise",
        "ubuntu/wily",
        "ubuntu/xenial",
    ],
)
@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestGetKernels:
    """Tests for `get_kernels`."""

    @pytest.fixture(autouse=True)
    def _setup(self, maasdb):
        self.region = factory.make_RegionController()

    def test_returns_usable_kernels(self, name, arch, subarch, kernels):
        if subarch == "generic":
            generic_kernels = []
            for i in kernels:
                kernel_parts = i.split("-")
                if len(kernel_parts) > 2:
                    kflavor = kernel_parts[2]
                else:
                    kflavor = "generic"
                    generic_kernels.append(i)
                factory.make_usable_boot_resource(
                    name=name,
                    rtype=BOOT_RESOURCE_TYPE.SYNCED,
                    architecture=f"{arch}/{i}",
                    kflavor=kflavor,
                    rolling=True,
                    platform=None,
                    supported_platforms=None,
                )
                factory.make_incomplete_boot_resource(
                    name=name,
                    rtype=BOOT_RESOURCE_TYPE.SYNCED,
                    architecture="%s/%s"
                    % (arch, factory.make_name("incomplete")),
                    kflavor=kflavor,
                )
        else:
            generic_kernels = kernels
            factory.make_usable_boot_resource(
                name=name,
                rtype=BOOT_RESOURCE_TYPE.SYNCED,
                architecture=f"{arch}/{subarch}",
                rolling=True,
                platform=None,
                supported_platforms=None,
            )
        assert set(BootResource.objects.get_kernels(name, arch)) == set(
            kernels
        ), "%s should return %s as its usable kernel" % (
            name,
            kernels,
        )
        assert (
            BootResource.objects.get_kernels(
                name=name,
                architecture=arch,
                platform=None,
                kflavor="generic",
            )
            == generic_kernels
        ), "%s should return %s as its usable kernel" % (
            name,
            generic_kernels,
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestGetKpackageForNode:
    """Tests for `get_kpackage_for_node`."""

    @pytest.fixture(autouse=True)
    def _setup(self, maasdb):
        self.region = factory.make_RegionController()

    def test_returns_kpackage(self):
        resource = factory.make_BootResource(
            name="ubuntu/trusty",
            architecture="amd64/hwe-t",
            rtype=BOOT_RESOURCE_TYPE.SYNCED,
        )
        resource_set = factory.make_BootResourceSet(resource)
        factory.make_boot_resource_file_with_content(
            resource_set,
            filename="boot-kernel",
            filetype="boot-kernel",
            extra={"kpackage": "linux-image-generic-lts-trusty"},
            synced=[(self.region, -1)],
        )
        node = factory.make_Node(
            interface=True,
            power_type="manual",
            osystem="ubuntu",
            distro_series="trusty",
            architecture="amd64/generic",
            hwe_kernel="hwe-t",
        )
        assert (
            BootResource.objects.get_kpackage_for_node(node)
            == "linux-image-generic-lts-trusty"
        )

    def test_returns_hwe_rolling(self):
        node = factory.make_Node()
        for hwe_kernel, kpackage in (
            ["hwe-rolling", "linux-generic-hwe-rolling"],
            ["hwe-rolling-lowlatency", "linux-lowlatency-hwe-rolling"],
            ["hwe-rolling-edge", "linux-generic-hwe-rolling-edge"],
            [
                "hwe-rolling-lowlatency-edge",
                "linux-lowlatency-hwe-rolling-edge",
            ],
        ):
            node.hwe_kernel = hwe_kernel
            assert BootResource.objects.get_kpackage_for_node(node) == kpackage

    def test_returns_none(self):
        node = factory.make_Node()
        assert BootResource.objects.get_kpackage_for_node(node) is None


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestGetKparamsForNode:
    """Tests for `get_kparams_for_node`."""

    @pytest.fixture(autouse=True)
    def _setup(self, maasdb):
        self.region = factory.make_RegionController()

    def test_returns_kpackage(self):
        resource = factory.make_BootResource(
            name="ubuntu/trusty",
            architecture="amd64/hwe-t",
            rtype=BOOT_RESOURCE_TYPE.SYNCED,
        )
        resource_set = factory.make_BootResourceSet(resource)
        factory.make_boot_resource_file_with_content(
            resource_set,
            filename="boot-kernel",
            filetype="boot-kernel",
            extra={
                "kpackage": "linux-image-generic-lts-trusty",
                "kparams": "a=b",
            },
            synced=[(self.region, -1)],
        )
        node = factory.make_Node(
            interface=True,
            power_type="manual",
            osystem="ubuntu",
            distro_series="trusty",
            architecture="amd64/generic",
            hwe_kernel="hwe-t",
        )
        assert BootResource.objects.get_kparams_for_node(node) == "a=b"

    def test_returns_none(self):
        node = factory.make_Node()
        assert BootResource.objects.get_kparams_for_node(node) is None


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestBootResource:
    """Tests for the `BootResource` model."""

    @pytest.fixture(autouse=True)
    def _setup(self, maasdb):
        self.region = factory.make_RegionController()

    def make_complete_boot_resource_set(self, resource):
        resource_set = factory.make_BootResourceSet(resource)
        filename = factory.make_name("name")
        filetype = factory.pick_enum(BOOT_RESOURCE_FILE_TYPE)
        factory.make_boot_resource_file_with_content(
            resource_set,
            filename=filename,
            filetype=filetype,
            synced=[(self.region, -1)],
        )
        return resource_set

    def test_validation_raises_error_on_missing_subarch(self):
        arch = factory.make_name("arch")
        with pytest.raises(ValidationError):
            factory.make_BootResource(architecture=arch)

    def test_validation_raises_error_on_invalid_name_for_synced(self):
        name = factory.make_name("name")
        arch = "{}/{}".format(
            factory.make_name("arch"),
            factory.make_name("subarch"),
        )
        resource = BootResource(
            rtype=BOOT_RESOURCE_TYPE.SYNCED, name=name, architecture=arch
        )
        with pytest.raises(ValidationError):
            resource.save()

    def test_validation_raises_error_on_invalid_name_for_uploaded(self):
        name = "{}/{}".format(
            factory.make_name("os"), factory.make_name("series")
        )
        arch = "{}/{}".format(
            factory.make_name("arch"),
            factory.make_name("subarch"),
        )
        resource = BootResource(
            rtype=BOOT_RESOURCE_TYPE.UPLOADED, name=name, architecture=arch
        )
        with pytest.raises(ValidationError):
            resource.save()

    def test_validation_allows_any_uploaded_name_slash_with_supported_os(
        self, request
    ):
        osystem = factory.make_name("osystem")
        fake = FakeOS(osystem)
        OperatingSystemRegistry.register_item(fake.name, fake)
        request.addfinalizer(
            lambda: OperatingSystemRegistry.unregister_item(osystem)
        )
        name = "{}/{}".format(osystem, factory.make_name("release"))
        arch = "{}/{}".format(
            factory.make_name("arch"),
            factory.make_name("subarch"),
        )
        resource = BootResource(
            rtype=BOOT_RESOURCE_TYPE.UPLOADED, name=name, architecture=arch
        )
        resource.save()

    def test_validation_allows_any_uploaded_name_without_slash(self):
        name = factory.make_name("name")
        arch = "{}/{}".format(
            factory.make_name("arch"),
            factory.make_name("subarch"),
        )
        resource = BootResource(
            rtype=BOOT_RESOURCE_TYPE.UPLOADED, name=name, architecture=arch
        )
        resource.save()

    def test_create_raises_error_on_not_unique(self):
        name = "{}/{}".format(
            factory.make_name("os"), factory.make_name("series")
        )
        arch = "{}/{}".format(
            factory.make_name("arch"),
            factory.make_name("subarch"),
        )
        factory.make_BootResource(
            rtype=BOOT_RESOURCE_TYPE.SYNCED, name=name, architecture=arch
        )
        with pytest.raises(ValidationError):
            factory.make_BootResource(
                rtype=BOOT_RESOURCE_TYPE.UPLOADED,
                name=name,
                architecture=arch,
            )

    def test_display_rtype(self):
        for key, value in BOOT_RESOURCE_TYPE_CHOICES_DICT.items():
            resource = BootResource(rtype=key)
            assert resource.display_rtype == value

    def test_split_arch(self):
        arch = factory.make_name("arch")
        subarch = factory.make_name("subarch")
        architecture = f"{arch}/{subarch}"
        resource = factory.make_BootResource(architecture=architecture)
        assert resource.split_arch() == (arch, subarch)

    def test_get_latest_set(self):
        resource = factory.make_BootResource()
        factory.make_BootResourceSet(resource)
        latest_two = factory.make_BootResourceSet(resource)
        assert resource.get_latest_set() == latest_two

    def test_get_latest_complete_set(self):
        resource = factory.make_BootResource()
        factory.make_BootResourceSet(resource)
        self.make_complete_boot_resource_set(resource)
        latest_complete = self.make_complete_boot_resource_set(resource)
        factory.make_BootResourceSet(resource)
        assert resource.get_latest_complete_set() == latest_complete

    def configure_now(self, mocker):
        now = timezone.now()
        mocker.patch.object(bootresource, "now").return_value = now
        return now.strftime("%Y%m%d")

    def test_get_next_version_name_returns_current_date(self, mocker):
        expected_version = self.configure_now(mocker)
        resource = factory.make_BootResource()
        assert resource.get_next_version_name() == expected_version

    def test_get_next_version_name_returns_first_revision(self, mocker):
        expected_version = "%s.1" % self.configure_now(mocker)
        resource = factory.make_BootResource()
        factory.make_BootResourceSet(
            resource, version=resource.get_next_version_name()
        )
        assert resource.get_next_version_name() == expected_version

    def test_get_next_version_name_returns_later_revision(self, mocker):
        expected_version = self.configure_now(mocker)
        set_count = random.randint(2, 4)
        resource = factory.make_BootResource()
        for _ in range(set_count):
            factory.make_BootResourceSet(
                resource, version=resource.get_next_version_name()
            )
        assert resource.get_next_version_name() == "%s.%d" % (
            expected_version,
            set_count,
        )

    def test_supports_subarch_returns_True_if_subarch_in_name_matches(self):
        arch = factory.make_name("arch")
        subarch = factory.make_name("subarch")
        architecture = f"{arch}/{subarch}"
        resource = factory.make_BootResource(architecture=architecture)
        assert resource.supports_subarch(subarch)

    def test_supports_subarch_returns_False_if_subarches_is_missing(self):
        resource = factory.make_BootResource()
        assert not resource.supports_subarch(factory.make_name("subarch"))

    def test_supports_subarch_returns_True_if_subarch_in_subarches(self):
        subarches = [factory.make_name("subarch") for _ in range(3)]
        subarch = random.choice(subarches)
        resource = factory.make_BootResource(
            extra={"subarches": ",".join(subarches)}
        )
        assert resource.supports_subarch(subarch)

    def test_supports_subarch_returns_False_if_subarch_not_in_subarches(self):
        subarches = [factory.make_name("subarch") for _ in range(3)]
        resource = factory.make_BootResource(
            extra={"subarches": ",".join(subarches)}
        )
        assert not resource.supports_subarch(factory.make_name("subarch"))

    def test_split_base_image_handles_no_base_image(self):
        resource = factory.make_BootResource()
        resource.base_image = None
        cfg = Config.objects.get_configs(
            ["commissioning_osystem", "commissioning_distro_series"]
        )
        assert set(resource.split_base_image()) == set(
            (cfg["commissioning_osystem"], cfg["commissioning_distro_series"])
        )
