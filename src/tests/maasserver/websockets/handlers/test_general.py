from unittest.mock import sentinel

from distro_info import UbuntuDistroInfo
import petname
import pytest

from maasserver.enum import (
    BOND_LACP_RATE_CHOICES,
    BOND_MODE_CHOICES,
    BOND_XMIT_HASH_POLICY_CHOICES,
    BOOT_RESOURCE_TYPE,
    NODE_TYPE,
)
from maasserver.models import Config, ControllerInfo, PackageRepository
from maasserver.models.signals.testing import SignalsDisabled
from maasserver.node_action import ACTIONS_DICT
from maasserver.secrets import SecretManager
from maasserver.testing.factory import factory
from maasserver.testing.osystems import make_osystem_with_releases
from maasserver.websockets.base import DATETIME_FORMAT, dehydrate_datetime
from maasserver.websockets.handlers import general
from maasserver.websockets.handlers.general import GeneralHandler
from provisioningserver.boot import BootMethodRegistry
from provisioningserver.testing.certificates import get_sample_cert
from provisioningserver.utils.snap import SnapVersionsInfo
from provisioningserver.utils.version import MAASVersion
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


@pytest.mark.usefixtures("maasdb", "factory", "maas_region_test")
class TestGeneralHandler:
    @pytest.fixture(autouse=True)
    def _setup_handler(self, maasdb, request):
        factory.make_RegionController()
        signals_disabled = SignalsDisabled("bootsources")
        signals_disabled.setUp()
        request.addfinalizer(signals_disabled.cleanUp)

    def dehydrate_actions(self, actions, node_type=None):
        return [
            {
                "name": name,
                "title": action.display,
                "sentence": action.display_sentence,
                "type": action.action_type,
            }
            for name, action in actions.items()
            if node_type is None or node_type in action.for_type
        ]

    def make_boot_sources(self):
        kernels = []
        ubuntu = UbuntuDistroInfo()
        # LP: #1711191 - distro-info 0.16+ no longer returns dictionaries or
        # lists, and it now returns objects instead. As such, we need to
        # handle both cases for backwards compatibility.
        try:
            ubuntu_rows = ubuntu._rows
        except AttributeError:
            ubuntu_rows = [row.__dict__ for row in ubuntu._releases]
        for row in ubuntu_rows:
            release_year = int(row["version"].split(".")[0])
            if release_year < 12:
                continue
            elif release_year < 16:
                style = row["series"][0]
            else:
                style = row["version"]
            for kflavor in [
                "generic",
                "lowlatency",
                "edge",
                "lowlatency-edge",
            ]:
                if kflavor == "generic":
                    kernel = "hwe-%s" % style
                else:
                    kernel = f"hwe-{style}-{kflavor}"
                arch = factory.make_name("arch")
                architecture = f"{arch}/{kernel}"
                release = row["series"].split(" ")[0]
                factory.make_usable_boot_resource(
                    name="ubuntu/" + release,
                    kflavor=kflavor,
                    extra={"subarches": kernel},
                    architecture=architecture,
                    rtype=BOOT_RESOURCE_TYPE.SYNCED,
                )
                factory.make_BootSourceCache(
                    os="ubuntu", arch=arch, subarch=kernel, release=release
                )
                kernels.append((kernel, f"{release} ({kernel})"))
        return kernels

    def test_architectures(self):
        arches = []
        for _ in range(3):
            arch = factory.make_name("arch")
            subarch = factory.make_name("subarch")
            arches.append(f"{arch}/generic")
            arches.append(f"{arch}/{subarch}")
        for arch in arches:
            factory.make_usable_boot_resource(architecture=arch)
        handler = GeneralHandler(factory.make_User(), {}, None)
        assert sorted(arches, key=repr) == sorted(
            handler.architectures({}), key=repr
        )

    def test_known_architectures(self):
        handler = GeneralHandler(factory.make_User(), {}, None)
        assert (
            PackageRepository.objects.get_known_architectures()
            == handler.known_architectures({})
        )

    def test_pockets_to_disable(self):
        handler = GeneralHandler(factory.make_User(), {}, None)
        assert (
            PackageRepository.objects.get_pockets_to_disable()
            == handler.pockets_to_disable({})
        )

    def test_components_to_disable(self):
        handler = GeneralHandler(factory.make_User(), {}, None)
        assert (
            PackageRepository.objects.get_components_to_disable()
            == handler.components_to_disable({})
        )

    def test_hwe_kernels(self):
        expected_output = self.make_boot_sources()
        handler = GeneralHandler(factory.make_User(), {}, None)
        assert sorted(expected_output) == sorted(handler.hwe_kernels({}))

    def test_hwe_min_kernels(self):
        expected_output = self.make_boot_sources()
        handler = GeneralHandler(factory.make_User(), {}, None)
        assert sorted(expected_output) == sorted(handler.min_hwe_kernels({}))

    def test_osinfo(self, mocker):
        handler = GeneralHandler(factory.make_User(), {}, None)
        osystem, osystem_releases = make_osystem_with_releases(
            None, osystem_name="ubuntu", releases=["noble"]
        )
        releases = [
            ("{}/{}".format(osystem, release), release)
            for release in osystem_releases
        ]
        mocker.patch.object(
            general, "list_osystem_choices", return_value=[(osystem, osystem)]
        )
        mocker.patch.object(
            general, "list_release_choices", return_value=releases
        )
        expected_osinfo = {
            "osystems": [(osystem, osystem)],
            "releases": releases,
            "kernels": {
                "ubuntu": {"noble": [("hwe-24.04", "noble (hwe-24.04)")]}
            },
            "default_osystem": Config.objects.get_config("default_osystem"),
            "default_release": Config.objects.get_config(
                "default_distro_series"
            ),
        }
        assert expected_osinfo == handler.osinfo({})

    def test_machine_actions_for_admin(self):
        handler = GeneralHandler(factory.make_admin(), {}, None)
        actions_expected = self.dehydrate_actions(
            ACTIONS_DICT, NODE_TYPE.MACHINE
        )
        assert sorted(actions_expected, key=repr) == sorted(
            handler.machine_actions({}), key=repr
        )

    def test_machine_actions_for_non_admin(self):
        handler = GeneralHandler(factory.make_User(), {}, None)
        assert sorted(
            {
                "release",
                "mark-broken",
                "on",
                "deploy",
                "acquire",
                "off",
                "lock",
                "unlock",
            },
            key=repr,
        ) == sorted(
            [action["name"] for action in handler.machine_actions({})],
            key=repr,
        )

    def test_device_actions_for_admin(self):
        handler = GeneralHandler(factory.make_admin(), {}, None)
        assert sorted({"set-zone", "delete"}, key=repr) == sorted(
            [action["name"] for action in handler.device_actions({})], key=repr
        )

    def test_device_actions_for_non_admin(self):
        handler = GeneralHandler(factory.make_User(), {}, None)
        assert sorted({"set-zone", "delete"}, key=repr) == sorted(
            [action["name"] for action in handler.device_actions({})], key=repr
        )

    def test_region_controller_actions_for_admin(self):
        handler = GeneralHandler(factory.make_admin(), {}, None)
        assert sorted({"set-zone", "delete"}, key=repr) == sorted(
            [
                action["name"]
                for action in handler.region_controller_actions({})
            ],
            key=repr,
        )

    def test_region_controller_actions_for_non_admin(self):
        handler = GeneralHandler(factory.make_User(), {}, None)
        assert [] == handler.region_controller_actions({})

    def test_rack_controller_actions_for_admin(self):
        handler = GeneralHandler(factory.make_admin(), {}, None)
        assert sorted(
            [
                "delete",
                "off",
                "on",
                "set-zone",
                "test",
                "override-failed-testing",
            ],
            key=repr,
        ) == sorted(
            [action["name"] for action in handler.rack_controller_actions({})],
            key=repr,
        )

    def test_rack_controller_actions_for_non_admin(self):
        handler = GeneralHandler(factory.make_User(), {}, None)
        assert [] == handler.rack_controller_actions({})

    def test_region_and_rack_controller_actions_for_admin(self):
        handler = GeneralHandler(factory.make_admin(), {}, None)
        assert sorted(["set-zone", "delete"], key=repr) == sorted(
            [
                action["name"]
                for action in handler.region_and_rack_controller_actions({})
            ],
            key=repr,
        )

    def test_region_and_rack_controller_actions_for_non_admin(self):
        handler = GeneralHandler(factory.make_User(), {}, None)
        assert [] == handler.region_and_rack_controller_actions({})

    def test_random_hostname_checks_hostname_existence(self, mocker):
        existing_node = factory.make_Node(hostname="hostname")
        hostnames = [existing_node.hostname, "new-hostname"]
        mocker.patch.object(petname, "Generate").side_effect = hostnames
        handler = GeneralHandler(factory.make_User(), {}, None)
        assert "new-hostname" == handler.random_hostname({})

    def test_bond_options(self):
        handler = GeneralHandler(factory.make_User(), {}, None)
        assert {
            "modes": BOND_MODE_CHOICES,
            "lacp_rates": BOND_LACP_RATE_CHOICES,
            "xmit_hash_policies": BOND_XMIT_HASH_POLICY_CHOICES,
        } == handler.bond_options({})

    def test_version(self, mocker):
        handler = GeneralHandler(factory.make_User(), {}, None)
        mocker.patch.object(
            general, "get_maas_version", autospec=True
        ).return_value = MAASVersion.from_string("1.2.3~rc1")
        assert handler.version({}) == "1.2.3~rc1"

    def test_target_version(self):
        controller = factory.make_RackController()
        ControllerInfo.objects.set_versions_info(
            controller,
            SnapVersionsInfo(
                current={
                    "version": "3.0.0~beta2-123-g.asdf",
                    "revision": "1234",
                },
                update={
                    "version": "3.0.0~beta3-456-g.cafe",
                    "revision": "5678",
                },
                channel="3.0/beta",
            ),
        )
        handler = GeneralHandler(factory.make_User(), {}, None)
        result = handler.target_version({})
        assert result["version"] == "3.0.0~beta3-456-g.cafe"
        assert result["snap_channel"] == "3.0/beta"
        assert result["first_reported"] is not None

    def test_target_version_snap_cohort(self):
        controller = factory.make_RackController()
        ControllerInfo.objects.set_versions_info(
            controller,
            SnapVersionsInfo(
                current={
                    "version": "3.0.0~beta2-123-g.asdf",
                    "revision": "1234",
                },
                channel="3.0/beta",
                cohort="abc",
            ),
        )
        handler = GeneralHandler(factory.make_User(), {}, None)
        result = handler.target_version({})
        assert result["snap_cohort"] == "abc"

    def test_power_types(self, mocker):
        handler = GeneralHandler(factory.make_User(), {}, None)
        mocker.patch.object(
            general, "get_all_power_types", autospec=True
        ).return_value = sentinel.types
        assert sentinel.types == handler.power_types({})

    def test_release_options(self):
        handler = GeneralHandler(factory.make_User(), {}, None)
        erase = factory.pick_bool()
        secure_erase = factory.pick_bool()
        quick_erase = factory.pick_bool()
        Config.objects.set_config("enable_disk_erasing_on_release", erase)
        Config.objects.set_config("disk_erase_with_secure_erase", secure_erase)
        Config.objects.set_config("disk_erase_with_quick_erase", quick_erase)
        assert {
            "erase": erase,
            "secure_erase": secure_erase,
            "quick_erase": quick_erase,
        } == handler.release_options({})

    def test_known_boot_architectures(self):
        handler = GeneralHandler(factory.make_User(), {}, None)
        assert [
            {
                "name": boot_method.name,
                "bios_boot_method": boot_method.bios_boot_method,
                "bootloader_arches": "/".join(boot_method.bootloader_arches),
                "arch_octet": boot_method.arch_octet,
                "protocol": (
                    "http"
                    if boot_method.http_url or boot_method.user_class
                    else "tftp"
                ),
            }
            for _, boot_method in BootMethodRegistry
            if boot_method.arch_octet or boot_method.user_class
        ] == handler.known_boot_architectures({})

    def test_generate_certificate_no_name(self, mocker):
        Config.objects.set_config("maas_name", "mymaas")
        handler = GeneralHandler(factory.make_User(), {}, None)
        mock_generate_certificate = mocker.patch.object(
            general, "generate_certificate", autospec=True
        )
        handler.generate_client_certificate({})
        mock_generate_certificate.assert_called_once_with("mymaas")

    def test_generate_certificate_with_name(self, mocker):
        Config.objects.set_config("maas_name", "mymaas")
        handler = GeneralHandler(factory.make_User(), {}, None)
        mock_generate_certificate = mocker.patch.object(
            general, "generate_certificate", autospec=True
        )
        handler.generate_client_certificate({"object_name": "mypod"})
        mock_generate_certificate.assert_called_once_with("mypod@mymaas")

    def test_generate_certificate_metadata(self, mocker):
        cert = get_sample_cert()
        handler = GeneralHandler(factory.make_User(), {}, None)
        mocker.patch.object(
            general, "generate_certificate"
        ).return_value = cert
        result = handler.generate_client_certificate({})
        assert result["fingerprint"] == cert.cert_hash()
        assert result["expiration"] == cert.expiration().strftime(
            DATETIME_FORMAT
        )

    def test_tls_certificate(self):
        cert = get_sample_cert()
        SecretManager().set_composite_secret(
            "tls",
            {
                "key": cert.private_key_pem(),
                "cert": cert.certificate_pem(),
            },
        )
        handler = GeneralHandler(factory.make_User(), {}, None)
        result = handler.tls_certificate({})

        assert cert.cn() == result["CN"]
        assert cert.certificate_pem() == result["certificate"]
        assert dehydrate_datetime(cert.expiration()) == result["expiration"]
        assert cert.cert_hash() == result["fingerprint"]

        # ensure we don't leak anything else
        allowed_keys = ["CN", "certificate", "expiration", "fingerprint"]
        assert sorted(result.keys(), key=repr) == sorted(
            allowed_keys, key=repr
        )

    def test_tls_certificate_tls_disabled(self):
        handler = GeneralHandler(factory.make_User(), {}, None)
        result = handler.tls_certificate({})

        assert result is None

    def test_vault_enabled(self):
        Config.objects.set_config("vault_enabled", True)
        handler = GeneralHandler(factory.make_User(), {}, None)
        result = handler.vault_enabled({})
        assert result

    def test_vault_disabled(self):
        Config.objects.set_config("vault_enabled", False)
        handler = GeneralHandler(factory.make_User(), {}, None)
        result = handler.vault_enabled({})
        assert not result

    def test_vault_not_specified(self):
        handler = GeneralHandler(factory.make_User(), {}, None)
        result = handler.vault_enabled({})
        assert not result

    def test_maas_url(self):
        url = "http://maas.internal"
        Config.objects.set_config("maas_url", url)
        handler = GeneralHandler(factory.make_User(), {}, None)
        result = handler.maas_url({})
        assert url == result


@pytest.mark.usefixtures("maasdb", "factory")
class TestGeneralHandlerOpenFGAIntegration(PytestOpenFGAMockMixin):
    def test_machine_actions_for_users_that_can_edit_machines(self):
        user = factory.make_User()
        handler = GeneralHandler(user, {}, None)
        self.openfga_client.can_edit_machines.return_value = True
        actions_expected = handler.machine_actions({})
        assert sorted(
            [
                "commission",
                "acquire",
                "deploy",
                "on",
                "off",
                "release",
                "abort",
                "override-failed-testing",
                "test",
                "rescue-mode",
                "exit-rescue-mode",
                "lock",
                "unlock",
                "mark-broken",
                "mark-fixed",
                "tag",
                "untag",
                "clone",
                "set-zone",
                "set-pool",
                "delete",
            ]
        ) == sorted([action["name"] for action in actions_expected])
        self.openfga_client.can_edit_machines.assert_called_once_with(user)

    def test_machine_actions_for_users_with_no_edit_permissions(self):
        self.openfga_client.can_edit_machines.return_value = False
        user = factory.make_User()
        handler = GeneralHandler(user, {}, None)
        actions_expected = handler.machine_actions({})
        assert sorted(
            [
                "acquire",
                "deploy",
                "on",
                "off",
                "release",
                "mark-broken",
                "lock",
                "unlock",
            ]
        ) == sorted([action["name"] for action in actions_expected])
        self.openfga_client.can_edit_machines.assert_called_once_with(user)

    def test_controller_actions_for_users_that_can_edit_controllers(self):
        self.openfga_client.can_edit_controllers.return_value = True
        user = factory.make_User()
        handler = GeneralHandler(user, {}, None)
        actions_expected = handler.region_controller_actions({})
        assert sorted(["set-zone", "delete"]) == sorted(
            [action["name"] for action in actions_expected]
        )
        self.openfga_client.can_edit_controllers.assert_called_once_with(user)

    def test_controller_actions_for_users_with_no_permissions(self):
        self.openfga_client.can_edit_controllers.return_value = False
        user = factory.make_User()
        handler = GeneralHandler(user, {}, None)
        actions_expected = handler.region_controller_actions({})
        assert [] == actions_expected
        self.openfga_client.can_edit_controllers.assert_called_once_with(user)
