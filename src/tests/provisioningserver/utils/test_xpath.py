# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for XPath utilities."""

from lxml import etree
import pytest

from provisioningserver.utils import xpath as xpath_module
from provisioningserver.utils.xpath import try_match_xpath


@pytest.mark.parametrize(
    "xpath_compile",
    [etree.XPath, lambda expr: expr],
    ids=["xpath-compiler=XPath", "xpath-compiler=None"],
)
@pytest.mark.parametrize(
    "doc_compile",
    [etree.XPathDocumentEvaluator, lambda doc: doc],
    ids=["doc-compiler=XPathDocumentEvaluator", "doc-compiler=None"],
)
@pytest.mark.parametrize(
    "xpath,doc,expected_result,expected_log",
    [
        ("/foo", etree.fromstring("<foo/>").getroottree(), True, ""),
        ("/foo", etree.fromstring("<bar/>").getroottree(), False, ""),
        (
            "/foo/text()",
            etree.fromstring("<foo>bar</foo>").getroottree(),
            True,
            "",
        ),
        (
            "/foo/text()",
            etree.fromstring("<foo></foo>").getroottree(),
            False,
            "",
        ),
        (
            "string()",
            etree.fromstring("<foo>bar</foo>").getroottree(),
            True,
            "",
        ),
        (
            "string()",
            etree.fromstring("<foo></foo>").getroottree(),
            False,
            "",
        ),
        (
            "/foo:bar",
            etree.fromstring("<foo/>").getroottree(),
            False,
            "Invalid expression '/foo:bar': Undefined namespace prefix: foo",
        ),
    ],
    ids=[
        "expression matches",
        "expression does not match",
        "text expression matches",
        "text expression does not match",
        "string expression matches",
        "string expression does not match",
        "unrecognised namespace",
    ],
)
class TestTryMatchXPathScenarios:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        self.logger = mocker.patch.object(xpath_module, "logger")

    def test(
        self,
        xpath,
        doc,
        expected_result,
        expected_log,
        xpath_compile,
        doc_compile,
    ):
        compiled_xpath = xpath_compile(xpath)
        compiled_doc = doc_compile(doc)
        assert expected_result is try_match_xpath(compiled_xpath, compiled_doc)
        if expected_log:
            self.logger.warn.assert_called_once()
            args, _ = self.logger.warn.call_args
            assert expected_log == args[0]


class TestTryMatchXPath:
    def test_logs_to_specified_logger(self, mocker):
        logger = mocker.patch.object(xpath_module, "logger")
        xpath = etree.XPath("/foo:bar")
        doc = etree.XML("<foo/>")
        try_match_xpath(xpath, doc)
        logger.warn.assert_called_once_with(
            "Invalid expression '/foo:bar': Undefined namespace prefix: foo"
        )
