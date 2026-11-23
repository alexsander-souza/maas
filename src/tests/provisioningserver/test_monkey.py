# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test monkey patches."""

import pytest
from twisted.internet.defer import Deferred, inlineCallbacks
from twisted.internet.threads import deferToThread

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.factory import factory
from provisioningserver.monkey import (
    augment_twisted_deferToThreadPool,
    get_patched_URI,
)

TIMEOUT = get_testing_timeout()


@pytest.mark.rack_reactor_guard
class TestAugmentDeferToThreadPool:
    """Tests for `augment_twisted_deferToThreadPool`."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        augment_twisted_deferToThreadPool()

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_functions_returning_Deferreds_from_threads_crash(self):
        with pytest.raises(
            TypeError, match="Synchronous call returned a Deferred:"
        ):
            yield deferToThread(Deferred)

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_functions_returning_other_from_threads_are_okay(self):
        res = yield deferToThread(round, 12.34)
        assert res == 12


class TestPatchedURI:
    def test_parses_URL_with_hostname(self):
        hostname = factory.make_name("host")
        path = factory.make_name("path")
        uri = get_patched_URI().fromBytes(
            f"http://{hostname}/{path}".encode("utf-8")
        )
        assert uri.host == hostname.encode("utf-8")
        assert uri.path == f"/{path}".encode("utf-8")
        assert uri.port == 80

    def test_parses_URL_with_hostname_and_port(self):
        hostname = factory.make_name("host")
        port = factory.pick_port()
        path = factory.make_name("path")
        uri = get_patched_URI().fromBytes(
            f"http://{hostname}:{port}/{path}".encode("utf-8")
        )
        assert uri.host == hostname.encode("utf-8")
        assert uri.path == f"/{path}".encode("utf-8")
        assert uri.port == port

    def test_parses_URL_with_IPv4_address(self):
        ip = factory.make_ipv4_address()
        path = factory.make_name("path").encode("ascii")
        uri = get_patched_URI().fromBytes(
            f"http://{ip}/{path}".encode("utf-8")
        )
        assert uri.host == ip.encode("utf-8")
        assert uri.path == f"/{path}".encode("utf-8")
        assert uri.port == 80

    def test_parses_URL_with_IPv4_address_and_port(self):
        ip = factory.make_ipv4_address()
        port = factory.pick_port()
        path = factory.make_name("path")
        uri = get_patched_URI().fromBytes(
            f"http://{ip}:{port}/{path}".encode("utf-8")
        )
        assert uri.host == ip.encode("utf-8")
        assert uri.path == f"/{path}".encode("utf-8")
        assert uri.port == port

    def test_parses_URL_with_IPv6_address(self):
        ip = factory.make_ipv6_address()
        path = factory.make_name("path")
        uri = get_patched_URI().fromBytes(f"http://[{ip}]/{path}".encode())
        assert uri.host == ip.encode("utf-8")
        assert uri.path == f"/{path}".encode("utf-8")
        assert uri.port == 80

    def test_parses_URL_with_IPv6_address_and_port(self):
        ip = factory.make_ipv6_address()
        port = factory.pick_port()
        path = factory.make_name("path")
        uri = get_patched_URI().fromBytes(
            f"http://[{ip}]:{port}/{path}".encode()
        )
        assert uri.host == ip.encode("utf-8")
        assert uri.path == f"/{path}".encode("utf-8")
        assert uri.port == port
