# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test OpenApi commands work correctly."""

from io import StringIO

from django.core.management import call_command
import pytest
import yaml

from maasserver.api.doc_oapi import get_api_endpoint


@pytest.mark.usefixtures("maasdb", "maas_region_test", "factory")
class TestOAPIDoc:
    def test_generate_spec(self):
        spec = get_api_endpoint()
        spec["externalDocs"]["url"] = "https://maas.io/docs"
        out = StringIO()
        call_command("generate_oapi_spec", stdout=out)
        assert yaml.dump(spec) == out.getvalue()
