# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for ``provisioningserver.utils.tftp``."""

import pytest
from twisted.python.context import call

from maastesting.factory import factory
from provisioningserver.utils import tftp


@pytest.mark.parametrize(
    "get_address,context_key",
    [
        (tftp.get_local_address, "local"),
        (tftp.get_remote_address, "remote"),
    ],
    ids=["get_local_address", "get_remote_address"],
)
class TestAddressFunctions:
    def test_returns_None_None_tuple_when_not_set(
        self, get_address, context_key
    ):
        assert (None, None) == get_address()

    def test_returns_host_port_tuple_when_set(self, get_address, context_key):
        host, port = factory.make_hostname(), factory.pick_port()
        context = {context_key: (host, port)}
        assert (host, port) == call(context, get_address)

    def test_returns_host_port_tuple_even_when_set_longer(
        self, get_address, context_key
    ):
        # Only the first two elements from the context's value are used.
        host, port = factory.make_hostname(), factory.pick_port()
        context = {context_key: (host, port, factory.make_name("thing"))}
        assert (host, port) == call(context, get_address)

    def test_blows_up_when_tuple_has_no_elements(
        self, get_address, context_key
    ):
        context = {context_key: ()}
        with pytest.raises(AssertionError):
            call(context, get_address)

    def test_blows_up_when_tuple_has_one_element(
        self, get_address, context_key
    ):
        context = {context_key: (factory.make_hostname(),)}
        with pytest.raises(AssertionError):
            call(context, get_address)
