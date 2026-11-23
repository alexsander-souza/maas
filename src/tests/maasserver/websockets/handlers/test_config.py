# Copyright 2016-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maasserver.websockets.handlers.config`"""

from collections import Counter
import random

import pytest

from maasserver.forms.settings import CONFIG_ITEMS, get_config_field
from maasserver.models.config import Config
from maasserver.secrets import SecretManager
from maasserver.testing.factory import factory
from maasserver.utils.orm import post_commit_hooks
from maasserver.websockets.base import (
    HandlerDoesNotExistError,
    HandlerPermissionError,
    HandlerPKError,
    HandlerValidationError,
)
from maasserver.websockets.handlers.config import (
    ConfigHandler,
    get_config_keys,
)
from maasservicelayer.models.configurations import ConfigFactory
from tests.maasserver.auth.test_auth import PytestOpenFGAMockMixin


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestConfigHandler:
    def test_dehydrate_no_choice_config(self):
        no_choice_name = random.choice(
            list(
                name
                for name in CONFIG_ITEMS.keys()
                if not hasattr(get_config_field(name), "choices")
            )
        )

        with post_commit_hooks:
            Config.objects.set_config(no_choice_name, "myvalue")

        user = factory.make_User()
        handler = ConfigHandler(user, {}, None)
        dehydrated = handler.dehydrate_configs([no_choice_name])[0]
        assert no_choice_name == dehydrated["name"]
        assert "myvalue" == dehydrated["value"]
        assert "choices" not in dehydrated

    def test_dehydrate_choice_config(self):
        choice_name, choices = random.choice(
            list(
                (name, get_config_field(name).choices)
                for name in CONFIG_ITEMS.keys()
                if hasattr(get_config_field(name), "choices")
            )
        )

        choice_value = random.choice([value for value, _ in choices])

        with post_commit_hooks:
            Config.objects.set_config(choice_name, choice_value)

        user = factory.make_User()
        handler = ConfigHandler(user, {}, None)
        dehydrated = handler.dehydrate_configs([choice_name])[0]
        assert choice_name == dehydrated["name"]
        assert choice_value == dehydrated["value"]
        assert choices == dehydrated["choices"]

    def test_get(self):
        user = factory.make_User()
        handler = ConfigHandler(user, {}, None)
        Config.objects.set_config("curtin_verbose", True)
        assert {"name": "curtin_verbose", "value": True} == handler.get(
            {"name": "curtin_verbose"}
        )

    def test_get_sets_loaded_pks_in_cache(self):
        user = factory.make_User()
        handler = ConfigHandler(user, {}, None)
        Config.objects.set_config("curtin_verbose", True)
        handler.get({"name": "curtin_verbose"})
        assert {"curtin_verbose"} == handler.cache["loaded_pks"]

    def test_get_requires_name(self):
        user = factory.make_User()
        handler = ConfigHandler(user, {}, None)
        with pytest.raises(HandlerPKError):
            handler.get({})

    def test_get_must_be_known_config(self):
        user = factory.make_User()
        handler = ConfigHandler(user, {}, None)
        with pytest.raises(HandlerDoesNotExistError):
            handler.get({"name": factory.make_name("config")})

    def test_get_must_be_in_config_items(self):
        admin = factory.make_admin()
        allowed_keys = set(get_config_keys(admin))
        all_keys = set(ConfigFactory.ALL_CONFIGS.keys())
        not_allowed_keys = all_keys.difference(allowed_keys)
        key = random.choice(list(not_allowed_keys))
        handler = ConfigHandler(admin, {}, None)
        with pytest.raises(HandlerDoesNotExistError):
            handler.get({"name": key})

    def test_list_admin_includes_all_config(self):
        admin = factory.make_admin()
        config_keys = list(CONFIG_ITEMS) + [
            "maas_url",
            "uuid",
            "rpc_shared_secret",
        ]

        handler = ConfigHandler(admin, {}, None)
        assert Counter(config_keys) == Counter(
            item["name"] for item in handler.list({})
        )

    def test_list_user_excludes_secret(self):
        user = factory.make_User()
        config_keys = list(CONFIG_ITEMS.keys()) + ["maas_url", "uuid"]

        handler = ConfigHandler(user, {}, None)
        assert "rpc_shared_secret" not in config_keys
        assert Counter(config_keys) == Counter(
            item["name"] for item in handler.list({})
        )

    def test_list_admin_includes_rpc_secret(self):
        SecretManager().set_simple_secret("rpc-shared", "my-secret")
        admin = factory.make_admin()
        handler = ConfigHandler(admin, {}, None)
        config = {item["name"]: item["value"] for item in handler.list({})}
        assert "my-secret" == config["rpc_shared_secret"]

    def test_get_admin_allows_rpc_secret(self):
        SecretManager().set_simple_secret("rpc-shared", "my-secret")
        admin = factory.make_admin()
        handler = ConfigHandler(admin, {}, None)
        assert (
            "my-secret" == handler.get({"name": "rpc_shared_secret"})["value"]
        )

    def test_list_non_admin_hides_rpc_secret(self):
        Config.objects.set_config("rpc_shared_secret", "my-secret")
        user = factory.make_User()
        handler = ConfigHandler(user, {}, None)
        config = {item["name"]: item["value"] for item in handler.list({})}
        assert "rpc_shared_secret" not in config

    def test_get_non_admin_disallows_rpc_secret(self):
        Config.objects.set_config("rpc_shared_secret", "my-secret")
        user = factory.make_User()
        handler = ConfigHandler(user, {}, None)
        with pytest.raises(HandlerDoesNotExistError):
            handler.get({"name": "rpc_shared_secret"})

    def test_list_sets_loaded_pks_in_cache(self):
        user = factory.make_User()
        handler = ConfigHandler(user, {}, None)
        configs = handler.list({})
        config_keys = {obj["name"] for obj in configs}
        assert Counter(config_keys) == Counter(handler.cache["loaded_pks"])

    def test_update_as_non_admin_asserts(self):
        user = factory.make_User()
        handler = ConfigHandler(user, {}, None)
        with pytest.raises(HandlerPermissionError):
            handler.update({})

    def test_update_requires_name(self):
        user = factory.make_admin()
        handler = ConfigHandler(user, {}, None)
        with pytest.raises(HandlerPKError):
            handler.update({})

    def test_update_requires_value(self):
        user = factory.make_admin()
        handler = ConfigHandler(user, {}, None)
        with pytest.raises(HandlerValidationError):
            handler.update({"name": "curtin_verbose"})

    def test_update_updates_value(self):
        user = factory.make_admin()
        handler = ConfigHandler(user, {}, None)
        updated = handler.update({"name": "curtin_verbose", "value": True})
        assert {"name": "curtin_verbose", "value": True} == updated
        assert Config.objects.get_config("curtin_verbose")

    def test_update_cannot_update_uuid(self):
        user = factory.make_admin()
        handler = ConfigHandler(user, {}, None)
        with pytest.raises(HandlerDoesNotExistError):
            handler.update({"name": "uuid", "value": "uuid"})

    def test_update_cannot_update_rpc_shared_secret(self):
        user = factory.make_admin()
        handler = ConfigHandler(user, {}, None)
        with pytest.raises(HandlerDoesNotExistError):
            handler.update(
                {"name": "rpc_shared_secret", "value": "rpc_shared_secret"}
            )

    def test_update_cannot_update_maas_url(self):
        user = factory.make_admin()
        handler = ConfigHandler(user, {}, None)
        with pytest.raises(HandlerDoesNotExistError):
            handler.update({"name": "maas_url", "value": "maas_url"})

    def test_update_handles_bad_value(self):
        user = factory.make_admin()
        handler = ConfigHandler(user, {}, None)
        with pytest.raises(HandlerValidationError) as error:
            handler.update(
                {"name": "http_proxy", "value": factory.make_name("invalid")}
            )
        assert {"value": ["Enter a valid URL."]} == error.value.message_dict

    def test_bulk_update_as_non_admin_asserts(self):
        user = factory.make_User()
        handler = ConfigHandler(user, {}, None)
        with pytest.raises(HandlerPermissionError):
            handler.bulk_update({})

    def test_bulk_update_requires_items(self):
        user = factory.make_admin()
        handler = ConfigHandler(user, {}, None)
        with pytest.raises(HandlerPKError):
            handler.bulk_update({})

    def test_bulk_update_updates_multiple_values(self):
        user = factory.make_admin()
        handler = ConfigHandler(user, {}, None)
        bulk_updated = handler.bulk_update(
            {"items": {"curtin_verbose": True, "enable_analytics": False}}
        )
        assert {
            "curtin_verbose": True,
            "enable_analytics": False,
        } == bulk_updated
        assert Config.objects.get_config("curtin_verbose")
        assert not Config.objects.get_config("enable_analytics")

    def test_bulk_update_cannot_bulk_update_maas_url(self):
        user = factory.make_admin()
        handler = ConfigHandler(user, {}, None)
        Config.objects.set_config("curtin_verbose", False)

        assert not Config.objects.get_config("curtin_verbose")
        with pytest.raises(HandlerValidationError) as error:
            handler.bulk_update(
                {"items": {"maas_url": "maas_url", "curtin_verbose": True}}
            )
        assert {
            "maas_url": ["Configuration parameter does not exist."]
        } == error.value.message_dict
        assert not Config.objects.get_config("curtin_verbose")

    def test_bulk_update_handles_bad_value(self):
        user = factory.make_admin()
        handler = ConfigHandler(user, {}, None)
        with pytest.raises(HandlerValidationError) as error:
            handler.bulk_update(
                {"items": {"http_proxy": factory.make_name("invalid")}}
            )
        assert {
            "http_proxy": ["Enter a valid URL."]
        } == error.value.message_dict

    def test_on_listen_returns_None_if_excluded(self):
        user = factory.make_User()
        handler = ConfigHandler(user, {}, None)
        Config.objects.set_config("tls_port", 5443)
        assert handler.on_listen("config", "create", "tls_port") is None

    def test_on_listen_returns_create_for_not_loaded(self):
        user = factory.make_User()
        handler = ConfigHandler(user, {}, None)
        updated = handler.on_listen("config", "update", "curtin_verbose")
        assert (
            "config",
            "create",
            {"name": "curtin_verbose", "value": True},
        ) == updated

    def test_on_listen_returns_update_for_loaded_create(self):
        user = factory.make_User()
        handler = ConfigHandler(user, {}, None)
        handler.cache["loaded_pks"] = {"curtin_verbose"}
        updated = handler.on_listen("config", "create", "curtin_verbose")
        assert (
            "config",
            "update",
            {"name": "curtin_verbose", "value": True},
        ) == updated

    def test_on_listen_returns_update_for_loaded_delete(self):
        user = factory.make_User()
        handler = ConfigHandler(user, {}, None)
        handler.cache["loaded_pks"] = {"curtin_verbose"}
        Config.objects.set_config("curtin_verbose", True)
        updated = handler.on_listen("config", "delete", "curtin_verbose")
        assert (
            "config",
            "update",
            {"name": "curtin_verbose", "value": True},
        ) == updated


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestConfigHandlerOpenFGAIntegration(PytestOpenFGAMockMixin):
    def test_bulk_update_requires_can_edit_configurations(self):
        self.openfga_client.can_edit_configurations.return_value = True
        admin = factory.make_admin()
        handler = ConfigHandler(admin, {}, None)
        updated = handler.bulk_update(
            {"items": {"curtin_verbose": True, "enable_analytics": False}}
        )
        assert {"curtin_verbose": True, "enable_analytics": False} == updated
        self.openfga_client.can_edit_configurations.assert_called_once_with(
            admin
        )

    def test_update_requires_can_edit_configurations(self):
        self.openfga_client.can_edit_configurations.return_value = True
        admin = factory.make_admin()
        handler = ConfigHandler(admin, {}, None)
        updated = handler.update({"name": "curtin_verbose", "value": True})
        assert {"name": "curtin_verbose", "value": True} == updated
        self.openfga_client.can_edit_configurations.assert_called_once_with(
            admin
        )
