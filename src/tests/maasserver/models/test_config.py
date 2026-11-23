# Copyright 2012-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the `Config` class and friends."""

from django.db import IntegrityError, transaction
from django.http import HttpRequest
import pytest
from twisted.internet import reactor

from maascommon.enums.dns import DnsUpdateAction
from maascommon.events import AUDIT
from maascommon.workflows.dhcp import (
    CONFIGURE_DHCP_WORKFLOW_NAME,
    ConfigureDHCPParam,
)
from maasserver import bootsources as bootsources_module
from maasserver.bootsources import cache_boot_sources
from maasserver.enum import ENDPOINT_CHOICES
from maasserver.models import Config, DNSPublication, Event, signals
from maasserver.models import config as config_module
from maasserver.models.config import (
    ensure_uuid_in_config,
    read_hardening_enabled_from_db,
)
from maasserver.models.vlan import VLAN
from maasserver.secrets import SecretManager
from maasserver.testing.factory import factory
from maasserver.utils.orm import post_commit_hooks
from maasservicelayer.models.configurations import (
    BootImagesImportIntervalMinutesConfig,
    ConfigFactory,
)
from provisioningserver.utils.testing import MAASIDFixture


def _get_default_config():
    models = ConfigFactory.ALL_CONFIGS.values()
    return {config.name: config.default for config in models}


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestConfigDefault:
    def test_defaults(self):
        expected = _get_default_config()
        observed = {name: Config.objects.get_config(name) for name in expected}

        # Test isolation is not what it ought to be, so we have to exclude
        # rpc_shared_secret here for now. Attempts to improve isolation have
        # so far resulted in random unreproducible test failures. See the
        # merge proposal for lp:~allenap/maas/increased-test-isolation.
        assert "rpc_shared_secret" in expected
        del expected["rpc_shared_secret"]
        assert "rpc_shared_secret" in observed
        del observed["rpc_shared_secret"]

        # completed_intro is set to True in all tests so that URL manipulation
        # in the middleware does not occur. We check that it is True and
        # remove it from the expected and observed.
        assert observed["completed_intro"]
        del expected["completed_intro"]
        del observed["completed_intro"]

        assert expected == observed


class CallRecorder:
    """A utility class which tracks the calls to its 'call' method and
    stores the arguments given to 'call' in 'self.calls'.
    """

    def __init__(self):
        self.calls = []

    def __call__(self, *args, **kwargs):
        self.calls.append([args, kwargs])


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestConfig:
    def test_config_name_uniqueness_enforced(self):
        name = factory.make_name("name")
        Config.objects.create(name=name, value=factory.make_name("value"))
        with pytest.raises(IntegrityError), transaction.atomic():
            Config.objects.create(name=name, value=factory.make_name("value"))

    def test_manager_get_config_found(self):
        Config.objects.create(name="name", value="config")
        config = Config.objects.get_config("name")
        assert "config" == config

    def test_manager_get_config_not_found(self):
        config = Config.objects.get_config("name", "default value")
        assert "default value" == config

    def test_manager_get_config_not_found_none(self):
        config = Config.objects.get_config("name")
        assert config is None

    def test_manager_get_configs_returns_configs_dict(self):
        expected = _get_default_config()
        # Only get a subset of all the configs.
        expected_names = list(expected)[:5]
        # Set a config value to test that is over the default.
        other_value = factory.make_name("value")
        Config.objects.set_config(expected_names[0], other_value)
        observed = Config.objects.get_configs(expected_names)
        expected_dict = {expected_names[0]: other_value}
        expected_dict.update(
            {
                name: expected[name]
                for name in expected_names
                if name != expected_names[0]
            }
        )
        assert expected_dict == observed

    def test_manager_set_config_creates_config(self):
        Config.objects.set_config("name", "config1")
        Config.objects.set_config("name", "config2")
        assert ["config2"] == [
            config.value for config in Config.objects.filter(name="name")
        ]

    def test_manager_set_config_for_secret_creates_secret(self):
        Config.objects.set_config("rpc_shared_secret", "abcd")
        assert SecretManager().get_simple_secret("rpc-shared") == "abcd"

    def test_manager_set_config_creates_audit_event(self):
        user = factory.make_User()
        request = HttpRequest()
        request.user = user
        endpoint = factory.pick_choice(ENDPOINT_CHOICES)
        Config.objects.set_config("name", "value", endpoint, request)
        event = Event.objects.get(type__level=AUDIT)
        assert event is not None
        assert (
            event.description
            == "Updated configuration setting 'name' to 'value'."
        )


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
@pytest.mark.parametrize(
    "name,value",
    [
        pytest.param(name, value, id=name)
        for name, value in _get_default_config().items()
        if name not in (BootImagesImportIntervalMinutesConfig.name)
    ],
)
class TestSettingConfig:
    @pytest.fixture(autouse=True)
    def _set_scenario_values(self, request):
        name = request.node.callspec.params["name"]
        if name in {"enable_http_proxy", "http_proxy"}:
            manager = signals.bootsources.signals
            manager.disable()
            request.addfinalizer(manager.enable)

    def test_can_be_initialised_to_None_without_crashing(self, name, value):
        with post_commit_hooks:
            Config.objects.set_config(name, None)
        assert Config.objects.get_config(name) is None

    def test_can_be_modified_from_None_without_crashing(self, name, value):
        with post_commit_hooks:
            Config.objects.set_config(name, None)
            Config.objects.set_config(name, value)
        assert value == Config.objects.get_config(name)

    @pytest.mark.real_post_commit_hooks
    def test_changing_ntp_servers_calls_configure_dhcp(
        self, name, value, mocker
    ):
        mock_start_workflow = mocker.patch.object(
            config_module, "start_workflow"
        )

        factory.make_VLAN(dhcp_on=True)

        with post_commit_hooks:
            Config.objects.set_config("ntp_servers", "127.0.0.1")

        mock_start_workflow.assert_called_once_with(
            workflow_name=CONFIGURE_DHCP_WORKFLOW_NAME,
            param=ConfigureDHCPParam(
                vlan_ids=[
                    vlan.id for vlan in VLAN.objects.filter(dhcp_on=True)
                ]
            ),
            task_queue="region",
        )

    @pytest.mark.real_post_commit_hooks
    def test_changing_ntp_external_only_calls_configure_dhcp(
        self, name, value, mocker
    ):
        mock_start_workflow = mocker.patch.object(
            config_module, "start_workflow"
        )

        factory.make_VLAN(dhcp_on=True)

        with post_commit_hooks:
            Config.objects.set_config("ntp_external_only", True)

        mock_start_workflow.assert_called_once_with(
            workflow_name=CONFIGURE_DHCP_WORKFLOW_NAME,
            param=ConfigureDHCPParam(
                vlan_ids=[
                    vlan.id for vlan in VLAN.objects.filter(dhcp_on=True)
                ]
            ),
            task_queue="region",
        )

    def test_arranges_for_update_on_Config_http_proxy(
        self, name, value, mocker
    ):
        post_commit_do = mocker.patch.object(
            bootsources_module, "post_commit_do"
        )
        Config.objects.set_config("http_proxy", factory.make_url())
        post_commit_do.assert_called_once_with(
            reactor.callLater, 0, cache_boot_sources, None
        )

    def test_arranges_for_update_on_Config_http_proxy_enable(
        self, name, value, mocker
    ):
        post_commit_do = mocker.patch.object(
            bootsources_module, "post_commit_do"
        )
        Config.objects.set_config("enable_http_proxy", False)
        post_commit_do.assert_called_once_with(
            reactor.callLater, 0, cache_boot_sources, None
        )

    def test_setting_dns_param_creates_dnspublication(
        self, name, value, mocker
    ):
        mock_create_for_config_update = mocker.patch.object(
            DNSPublication.objects, "create_for_config_update"
        )
        Config.objects.set_config("upstream_dns", "127.0.0.1")
        mock_create_for_config_update.assert_called_once_with(
            source="configuration upstream_dns set to 127.0.0.1",
            action=DnsUpdateAction.RELOAD,
        )


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestEnsureUUIDInConfig:
    def test_create_and_store_uuid(self, request):
        region = factory.make_RegionController()
        fixture = MAASIDFixture(region.system_id)
        fixture.setUp()
        request.addfinalizer(fixture.cleanUp)
        assert Config.objects.get_config("uuid") is None
        created_uuid = ensure_uuid_in_config()
        config_uuid = Config.objects.get_config("uuid")
        assert created_uuid == config_uuid

    def test_return_stored_uuid(self, request):
        region = factory.make_RegionController()
        fixture = MAASIDFixture(region.system_id)
        fixture.setUp()
        request.addfinalizer(fixture.cleanUp)
        created_uuid = ensure_uuid_in_config()
        config_uuid = Config.objects.get_config("uuid")
        stored_uuid = ensure_uuid_in_config()
        assert stored_uuid == config_uuid
        assert created_uuid == stored_uuid


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestReadHardeningEnabledFromDb:
    """Tests for read_hardening_enabled_from_db().

    The function returns the raw DB value when a row exists, or None when
    no row is present, so that callers can distinguish "not set" from
    "explicitly set to auto".
    """

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.read_fn = read_hardening_enabled_from_db

    def test_returns_none_when_no_row_set(self):
        # No CLI write → no row in the Config table → None.
        result = self.read_fn()
        assert result is None

    def test_returns_on_when_explicitly_set(self):
        Config.objects.set_config("hardening_enabled", "on")
        result = self.read_fn()
        assert result == "on"

    def test_returns_off_when_explicitly_set(self):
        Config.objects.set_config("hardening_enabled", "off")
        result = self.read_fn()
        assert result == "off"

    def test_returns_auto_when_explicitly_set_to_auto(self):
        Config.objects.set_config("hardening_enabled", "auto")
        result = self.read_fn()
        assert result == "auto"
