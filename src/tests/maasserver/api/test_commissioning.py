# Copyright 2013-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the commissioning-related portions of the MAAS API."""

from base64 import b64decode, b64encode
from collections import Counter
import http.client
from itertools import chain
import random

from django.urls import reverse
from piston3.utils import rc
import pytest

from maascommon.events import AUDIT
from maasserver.models import Event, Script
from maasserver.testing.factory import factory
from maasserver.utils.converters import json_load_bytes
from maasserver.utils.orm import reload_object
from metadataserver.enum import (
    SCRIPT_STATUS,
    SCRIPT_STATUS_CHOICES,
    SCRIPT_TYPE,
)
from metadataserver.fields import Bin


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("admin=admin,client=oauth", id="user=admin,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestAdminCommissioningScriptsAPI:
    """Tests for `CommissioningScriptsHandler`."""

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, admin, admin_api_client):
        self.user = admin
        self.client = admin_api_client

    def get_url(self):
        return reverse("commissioning_scripts_handler")

    def test_GET_lists_commissioning_scripts(self):
        names = {
            factory.make_Script(script_type=SCRIPT_TYPE.COMMISSIONING).name
            for _ in range(5)
        }

        response = self.client.get(self.get_url())

        assert (http.client.OK, sorted(names)) == (
            response.status_code,
            json_load_bytes(response.content),
        )

    def test_POST_creates_commissioning_script(self):
        # This uses Piston's built-in POST code, so there are no tests for
        # corner cases (like "script already exists") here.
        name = factory.make_name("script")
        content = factory.make_script_content()

        # Every uploaded file also has a name.  But this is completely
        # unrelated to the name we give to the commissioning script.
        response = self.client.post(
            self.get_url(),
            {
                "name": name,
                "content": factory.make_file_upload(content=content.encode()),
            },
        )
        assert response.status_code == http.client.OK

        returned_script = response.json()
        assert name == returned_script["name"]
        assert content.encode() == b64decode(returned_script["content"])

        stored_script = Script.objects.get(name=name)
        assert content == stored_script.script.data
        assert SCRIPT_TYPE.COMMISSIONING == stored_script.script_type

    def test_POST_creates_errors(self):
        content = factory.make_script_content(
            yaml_content={"name": factory.make_name("name")}
        )
        response = self.client.post(
            self.get_url(),
            {
                "name": factory.make_name("name"),
                "content": factory.make_file_upload(content=content.encode()),
            },
        )
        assert response.status_code == http.client.BAD_REQUEST

        ret = json_load_bytes(response.content)
        assert {
            "name": ["May not override values defined in embedded YAML."]
        } == ret


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestCommissioningScriptsAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def get_url(self):
        return reverse("commissioning_scripts_handler")

    def test_GET_is_forbidden(self):
        response = self.client.get(self.get_url())
        assert response.status_code == http.client.FORBIDDEN

    def test_POST_is_forbidden(self):
        response = self.client.post(
            self.get_url(), {"name": factory.make_name("script")}
        )
        assert response.status_code == http.client.FORBIDDEN


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("admin=admin,client=oauth", id="user=admin,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestAdminCommissioningScriptAPI:
    """Tests for `CommissioningScriptHandler`."""

    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, admin, admin_api_client):
        self.user = admin
        self.client = admin_api_client

    def get_url(self, script_name):
        return reverse("commissioning_script_handler", args=[script_name])

    def test_GET_returns_script_contents(self):
        script = factory.make_Script(script_type=SCRIPT_TYPE.COMMISSIONING)
        response = self.client.get(self.get_url(script.name))
        assert response.status_code == http.client.OK
        assert script.script.data == response.content.decode("utf-8")

    def test_PUT_updates_contents(self):
        old_content = factory.make_script_content().encode("ascii")
        script = factory.make_Script(
            script_type=SCRIPT_TYPE.COMMISSIONING, script=old_content
        )
        new_content = factory.make_script_content().encode("ascii")

        response = self.client.put(
            self.get_url(script.name),
            {"content": factory.make_file_upload(content=new_content)},
        )
        assert response.status_code == http.client.OK
        assert rc.ALL_OK.content == response.content

        assert new_content.decode("utf-8") == reload_object(script).script.data

    def test_PUT_errors(self):
        old_content = factory.make_script_content(
            yaml_content={"name": factory.make_name("name")}
        )
        old_content = old_content.encode("ascii")
        script = factory.make_Script(
            script_type=SCRIPT_TYPE.COMMISSIONING, script=old_content
        )
        new_content = factory.make_script_content(
            yaml_content={"name": factory.make_name("name")}
        )
        new_content = new_content.encode("ascii")

        response = self.client.put(
            self.get_url(script.name),
            {
                "name": factory.make_name("name"),
                "content": factory.make_file_upload(content=new_content),
            },
        )
        assert response.status_code == http.client.BAD_REQUEST

        ret = json_load_bytes(response.content)
        assert {
            "name": ["May not override values defined in embedded YAML."]
        } == ret

    def test_DELETE_deletes_script(self):
        script = factory.make_Script(script_type=SCRIPT_TYPE.COMMISSIONING)
        self.client.delete(self.get_url(script.name))
        assert not Script.objects.filter(name=script.name).exists()
        event = Event.objects.get(type__level=AUDIT)
        assert event is not None
        assert event.description == "Deleted script '%s'." % script.name


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestCommissioningScriptAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def get_url(self, script_name):
        return reverse("commissioning_script_handler", args=[script_name])

    def test_GET_is_forbidden(self):
        # It's not inconceivable that commissioning scripts contain
        # credentials of some sort.  There is no need for regular users
        # (consumers of the MAAS) to see these.
        script = factory.make_Script(script_type=SCRIPT_TYPE.COMMISSIONING)
        response = self.client.get(self.get_url(script.name))
        assert response.status_code == http.client.FORBIDDEN

    def test_PUT_is_forbidden(self):
        script = factory.make_Script(script_type=SCRIPT_TYPE.COMMISSIONING)
        response = self.client.put(
            self.get_url(script.name), {"content": factory.make_string()}
        )
        assert response.status_code == http.client.FORBIDDEN

    def test_DELETE_is_forbidden(self):
        script = factory.make_Script(script_type=SCRIPT_TYPE.COMMISSIONING)
        response = self.client.put(self.get_url(script.name))
        assert response.status_code == http.client.FORBIDDEN


@pytest.mark.parametrize(
    "api_identity",
    [pytest.param("user=user,client=oauth", id="user=user,client=oauth")],
)
@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestNodeCommissionResultHandlerAPI:
    @pytest.fixture(autouse=True)
    def _setup(self, api_identity, maas_user, api_client):
        self.user = maas_user
        self.client = api_client

    def store_result(
        self, script_result, output=None, stdout=None, stderr=None, **kwargs
    ):
        # Create a test store_result which doesn't run the script hooks.
        if output is not None:
            script_result.output = Bin(output.encode("utf-8"))
        if stdout is not None:
            script_result.stdout = Bin(stdout.encode("utf-8"))
        if stderr is not None:
            script_result.stderr = Bin(stderr.encode("utf-8"))
        for arg, value in kwargs.items():
            setattr(script_result, arg, value)
        if script_result.exit_status == 0:
            script_result.status = SCRIPT_STATUS.PASSED
        else:
            script_result.status = SCRIPT_STATUS.FAILED
        script_result.save()

    def test_list_returns_expected_fields(self):
        node = factory.make_Node(with_empty_script_sets=True)
        for script_set in (
            node.current_commissioning_script_set,
            node.current_testing_script_set,
            node.current_installation_script_set,
        ):
            for script_result in script_set:
                self.store_result(
                    script_result, exit_status=0, stdout=factory.make_string()
                )

        script_set = node.current_commissioning_script_set
        script_result = script_set.scriptresult_set.first()

        url = reverse("node_results_handler")
        response = self.client.get(url, {"system_id": [node.system_id]})
        assert response.status_code == http.client.OK
        parsed_results = json_load_bytes(response.content)
        for parsed_result in parsed_results:
            if parsed_result["name"] == script_result.name:
                break
        assert (
            node.current_commissioning_script_set.scriptresult_set.count()
            + node.current_testing_script_set.scriptresult_set.count()
            + node.current_installation_script_set.scriptresult_set.count()
            == len(parsed_results)
        )
        assert {
            "created",
            "updated",
            "id",
            "name",
            "script_result",
            "result_type",
            "node",
            "data",
            "resource_uri",
        } == parsed_result.keys()
        assert script_result.id == parsed_result["id"]
        assert script_result.name == parsed_result["name"]
        assert script_result.exit_status == parsed_result["script_result"]
        assert script_set.result_type == parsed_result["result_type"]
        assert {"system_id": script_set.node.system_id} == parsed_result[
            "node"
        ]
        assert script_result.stdout == b64decode(parsed_result["data"])

    def test_list_returns_with_multiple_empty_data(self):
        node = factory.make_Node(with_empty_script_sets=True)
        for script_result in chain(
            node.current_commissioning_script_set,
            node.current_testing_script_set,
            node.current_installation_script_set,
        ):
            self.store_result(
                script_result, exit_status=0, stdout="", stderr=""
            )

        url = reverse("node_results_handler")
        response = self.client.get(url)
        assert response.status_code == http.client.OK
        parsed_results = json_load_bytes(response.content)
        assert Counter(
            script_result.stdout.decode("utf-8")
            for script_result in chain(
                node.current_commissioning_script_set,
                node.current_testing_script_set,
                node.current_installation_script_set,
            )
        ) == Counter(
            parsed_result.get("data") for parsed_result in parsed_results
        )

    def test_list_returns_stderr(self):
        node = factory.make_Node(with_empty_script_sets=True)
        for script_result in chain(
            node.current_commissioning_script_set,
            node.current_testing_script_set,
            node.current_installation_script_set,
        ):
            self.store_result(
                script_result, exit_status=0, stdout="", stderr=""
            )

        url = reverse("node_results_handler")
        response = self.client.get(url, {"system_id": [node.system_id]})
        assert response.status_code == http.client.OK
        parsed_results = json_load_bytes(response.content)
        assert Counter(
            script_result.stdout.decode("utf-8")
            for script_result in chain(
                node.current_commissioning_script_set,
                node.current_testing_script_set,
                node.current_installation_script_set,
            )
        ) == Counter(parsed_result["data"] for parsed_result in parsed_results)

    def test_list_returns_output_if_stdout_empty(self):
        node = factory.make_Node(with_empty_script_sets=True)
        for script_result in chain(
            node.current_commissioning_script_set,
            node.current_testing_script_set,
            node.current_installation_script_set,
        ):
            self.store_result(
                script_result, exit_status=0, output=factory.make_string()
            )

        url = reverse("node_results_handler")
        response = self.client.get(url, {"system_id": [node.system_id]})
        assert response.status_code == http.client.OK
        parsed_results = json_load_bytes(response.content)
        assert Counter(
            b64encode(script_result.output).decode()
            for script_result in chain(
                node.current_commissioning_script_set,
                node.current_testing_script_set,
                node.current_installation_script_set,
            )
        ) == Counter(parsed_result["data"] for parsed_result in parsed_results)

    def test_list_shows_all_latest_results(self):
        # XXX ltrager 2017-01-23 - Needed until builtin tests are added.
        factory.make_Script(script_type=SCRIPT_TYPE.TESTING)
        node = factory.make_Node(with_empty_script_sets=True)
        script_results = []
        for script_result in node.current_commissioning_script_set:
            self.store_result(script_result, exit_status=0)
            script_results.append(script_result)

        for script_result in node.current_testing_script_set:
            self.store_result(script_result, exit_status=0)
            script_results.append(script_result)

        for script_result in node.current_installation_script_set:
            script_result.store_result(exit_status=0)
            script_results.append(script_result)

        url = reverse("node_results_handler")
        response = self.client.get(url, {"system_id": [node.system_id]})
        assert response.status_code == http.client.OK
        parsed_results = json_load_bytes(response.content)
        assert Counter(
            script_result.id for script_result in script_results
        ) == Counter(parsed_result["id"] for parsed_result in parsed_results)

    def test_list_can_be_filtered_by_name(self):
        node = factory.make_Node(with_empty_script_sets=True)
        script_results = []
        for script_result in node.current_commissioning_script_set:
            self.store_result(script_result, exit_status=0)
            script_results.append(script_result)
        script_result = random.choice(script_results)

        url = reverse("node_results_handler")
        response = self.client.get(url, {"name": script_result.name})
        assert response.status_code == http.client.OK
        parsed_results = json_load_bytes(response.content)
        assert script_result.id == parsed_results[0]["id"]

    def test_list_displays_only_visible_nodes(self):
        node = factory.make_Node(
            owner=factory.make_User(), with_empty_script_sets=True
        )
        for script_result in node.current_commissioning_script_set:
            self.store_result(script_result, exit_status=0)

        url = reverse("node_results_handler")
        response = self.client.get(url)
        assert response.status_code == http.client.OK
        parsed_results = json_load_bytes(response.content)
        assert [] == parsed_results

    def test_list_displays_all_results(self):
        script_results = []
        for _ in range(3):
            node = factory.make_Node(with_empty_script_sets=True)
            for script_result in node.current_commissioning_script_set:
                self.store_result(script_result, exit_status=0)
                script_results.append(script_result)
            for script_result in node.current_testing_script_set:
                self.store_result(script_result, exit_status=0)
                script_results.append(script_result)
            for script_result in node.current_installation_script_set:
                self.store_result(script_result, exit_status=0)
                script_results.append(script_result)

        url = reverse("node_results_handler")
        response = self.client.get(url)
        assert response.status_code == http.client.OK
        parsed_results = json_load_bytes(response.content)
        assert Counter(
            script_result.id for script_result in script_results
        ) == Counter(parsed_result["id"] for parsed_result in parsed_results)

    def test_list_only_displayed_completed_results(self):
        node = factory.make_Node(with_empty_script_sets=True)
        expected_results = []
        for script_set in (
            node.current_commissioning_script_set,
            node.current_testing_script_set,
            node.current_installation_script_set,
        ):
            for status, _ in SCRIPT_STATUS_CHOICES:
                script_result = factory.make_ScriptResult(
                    script_set=script_set, status=status, stderr=b""
                )
                if status in (
                    SCRIPT_STATUS.PASSED,
                    SCRIPT_STATUS.FAILED,
                    SCRIPT_STATUS.TIMEDOUT,
                    SCRIPT_STATUS.ABORTED,
                ):
                    expected_results.append(script_result)

        url = reverse("node_results_handler")
        response = self.client.get(url)
        assert response.status_code == http.client.OK
        parsed_results = json_load_bytes(response.content)
        assert Counter(
            script_result.id for script_result in expected_results
        ) == Counter(parsed_result["id"] for parsed_result in parsed_results)
