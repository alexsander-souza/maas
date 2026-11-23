# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maasserver.third_party_drivers`."""

import os

import pytest

from maasserver import third_party_drivers
from maasserver.testing.factory import factory
from maasserver.third_party_drivers import (
    DriversConfig,
    get_third_party_driver,
    match_aliases_to_driver,
    populate_kernel_opts,
)
from maastesting import dev_root
from provisioningserver.refresh.node_info_scripts import (
    LIST_MODALIASES_OUTPUT_NAME,
)


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNodeModaliases:
    def test_uses_commissioning_modaliases(self):
        test_data = b"hulla\nbaloo"
        node = factory.make_Node(with_empty_script_sets=True)
        script_set = node.current_commissioning_script_set
        script_result = script_set.scriptresult_set.get(
            script_name=LIST_MODALIASES_OUTPUT_NAME
        )
        script_result.store_result(exit_status=0, stdout=test_data)

        aliases = node.modaliases
        assert aliases == ["hulla", "baloo"]

    def test_survives_no_commissioning_data(self):
        node = factory.make_Node()
        aliases = node.modaliases
        assert aliases == []

    def test_only_returns_data_from_passed_results(self):
        test_data = b"hulla\nbaloo"
        node = factory.make_Node(with_empty_script_sets=True)
        script_set = node.current_commissioning_script_set
        script_result = script_set.scriptresult_set.get(
            script_name=LIST_MODALIASES_OUTPUT_NAME
        )
        script_result.store_result(exit_status=1, stdout=test_data)

        aliases = node.modaliases
        assert aliases == []


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestMatchAliasesToDriver:
    def test_finds_first_match(self):
        drivers = [
            {"modaliases": ["foo*"], "comment": "first"},
            {"modaliases": ["foo*"], "comment": "notfirst"},
        ]

        aliases = ["foobar"]

        driver = match_aliases_to_driver(aliases, drivers)
        assert driver == drivers[0]

    def test_finds_no_match(self):
        drivers = [{"modaliases": ["foo*"]}]
        aliases = ["bar"]
        driver = match_aliases_to_driver(aliases, drivers)
        assert driver is None


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestPopulateKernelOpts:
    def test_blacklist_provided(self):
        driver = {"blacklist": "bad"}
        driver = populate_kernel_opts(driver)
        assert driver["kernel_opts"] == "modprobe.blacklist=bad"

    def test_no_blacklist_provided(self):
        driver = {}
        driver = populate_kernel_opts(driver)
        assert "kernel_opts" not in driver


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestGetThirdPartyDriver:
    def test_finds_match(self, mocker):
        node = factory.make_Node()
        mock = mocker.patch.object(
            third_party_drivers, "match_aliases_to_driver"
        )
        base_driver = dict(comment="hooray")
        mock.return_value = base_driver

        driver = get_third_party_driver(node)
        assert driver == base_driver

        # ensure driver is a copy, not the original
        base_driver["comment"] = "boo"
        assert driver["comment"] == "hooray"

    def test_finds_no_match(self, mocker):
        node = factory.make_Node()
        mocker.patch.object(
            third_party_drivers, "match_aliases_to_driver", return_value=None
        )
        driver = get_third_party_driver(node)
        assert driver == {}

    def test_matching_series(self, mocker):
        node = factory.make_Node()
        driver = {"series": ["xenial", "bionic"], "name": "somedriver"}
        mocker.patch.object(
            third_party_drivers, "match_aliases_to_driver", return_value=driver
        )
        assert get_third_party_driver(node, series="bionic") == driver

    def test_not_matching_series(self, mocker):
        node = factory.make_Node()
        driver = {"series": ["xenial", "bionic"], "name": "somedriver"}
        mocker.patch.object(
            third_party_drivers, "match_aliases_to_driver", return_value=driver
        )
        assert get_third_party_driver(node, series="precise") == {}

    def test_series_without_available_series(self, mocker):
        node = factory.make_Node()
        driver = {"name": "somedriver"}
        mocker.patch.object(
            third_party_drivers, "match_aliases_to_driver", return_value=driver
        )
        assert get_third_party_driver(node, series="precise") == driver


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestDriversConfig:
    def test_get_defaults_returns_empty_drivers_list(self):
        observed = DriversConfig.get_defaults()
        assert observed == {"drivers": []}

    def test_load_from_yaml(self):
        filename = os.path.join(
            dev_root, "package-files", "etc", "maas", "drivers.yaml"
        )
        for entry in DriversConfig.load(filename)["drivers"]:
            assert entry.keys() == {
                "blacklist",
                "comment",
                "key_binary",
                "modaliases",
                "module",
                "repository",
                "package",
                "series",
            }
