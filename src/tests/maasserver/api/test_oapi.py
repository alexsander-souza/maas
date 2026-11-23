# Copyright 2012-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import json

import pytest
import yaml

from maasserver.api.doc_oapi import (
    _prettify,
    _render_oapi_paths,
    endpoint,
    landing_page,
)
from maasserver.models.config import Config
from maasserver.testing.factory import factory


class TestLandingPage:
    def test_links(self):
        request = factory.make_fake_request()
        page = landing_page(request)
        content = json.loads(page.content)
        resources = content["resources"]
        host = request.get_host()
        for link in resources:
            href = f"http://{host}{link['path']}"
            assert link["href"] == href
        assert resources[0]["type"] == page["content-type"]


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestApiEndpoint:
    def test_required_fields(self):
        request = factory.make_fake_request()
        page = endpoint(request)
        content = yaml.safe_load(page.content)
        assert "openapi" in content
        assert "info" in content
        assert "paths" in content
        info = content["info"]
        assert isinstance(info, dict)
        assert "title" in info
        assert "version" in info

    def test_discovered_servers(self):
        request = factory.make_fake_request()
        page = endpoint(request)
        content = yaml.safe_load(page.content)
        assert "servers" in content
        servers = content["servers"]
        assert isinstance(servers, list)
        maasserver = servers[0]
        maas_name = Config.objects.get_config("maas_name")
        assert maasserver["url"] == "http://localhost:5240/MAAS/api/2.0/"
        assert maasserver["description"] == f"{maas_name} API"

    def test_external_docs(self):
        request = factory.make_fake_request()
        page = endpoint(request)
        content = yaml.safe_load(page.content)
        assert "externalDocs" in content
        external_docs = content["externalDocs"]
        assert isinstance(external_docs, dict)
        assert "description" in external_docs
        assert external_docs["url"] == (
            "/MAAS/docs/reference/api-reference/api-v2-generated/"
        )


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestOAPISpec:
    def test_paths(self):
        # TODO add actual tests
        _render_oapi_paths()

    def test_path_parameters(self):
        oapi_types = ["boolean", "integer", "number", "object", "string"]
        for path in _render_oapi_paths().values():
            if "parameters" not in path:
                continue
            for param in path["parameters"]:
                assert "name" in param
                assert "in" in param
                assert param["in"] in ["cookie", "header", "path", "query"]
                assert param["required"]
                if "schema" in param:
                    assert param["schema"]["type"] in oapi_types

    def test_path_operations(self):
        oapi_ops = [
            "get",
            "put",
            "post",
            "delete",
            "options",
            "head",
            "patch",
            "trace",
            "servers",
        ]
        for path in _render_oapi_paths().values():
            isct_ops = list(set(oapi_ops) & set(path.keys()))
            for op in isct_ops:
                for response in path[op]["responses"].values():
                    assert "description" in response

    def test_path_object_types(self):
        def _get_all_key_values(d):
            for k, v in d.items():
                if isinstance(v, dict):
                    yield from _get_all_key_values(v)
                else:
                    yield (k, v)

        oapi_types = ["boolean", "integer", "number", "object", "string"]
        for k, v in _get_all_key_values(_render_oapi_paths()):
            if k == "type":
                assert v in oapi_types


class TestPrettify:
    def test_cleans_newlines(self):
        before = """\
Returns system details -- for example, LLDP and

``lshw`` XML dumps.


Returns a ``{detail_type: xml, ...}`` map, where

``detail_type`` is something like "lldp" or "lshw".


Note that this is returned as BSON and not JSON. This is for

efficiency, but mainly because JSON can''t do binary content without

applying additional encoding like base-64. The example output below is

represented in ASCII using ``bsondump example.bson`` and is for

demonstrative purposes."""

        after = """\
Returns system details - for example, LLDP and `lshw` XML dumps.
Returns a `{detail_type: xml, .}` map, where `detail_type` is something like "lldp" or "lshw".
Note that this is returned as BSON and not JSON. This is for efficiency, but mainly because JSON can't do binary content without applying additional encoding like base-64. The example output below is represented in ASCII using `bsondump example.bson` and is for demonstrative purposes."""

        assert _prettify(before) == after
