# Copyright 2015-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `maasserver.utils.threads`."""

import random
from unittest.mock import sentinel

from django.db import connection
import pytest
from twisted.internet import reactor
from twisted.internet.defer import DeferredSemaphore, inlineCallbacks

from maasserver.utils import orm, threads
from maastesting.crochet import wait_for
from provisioningserver.utils.twisted import ThreadPool, ThreadUnpool

wait_for_reactor = wait_for()


class TestMakeFunctions:
    """Tests for the `make_*` functions."""

    def test_make_default_pool_creates_disconnected_pool(self):
        pool = threads.make_default_pool()
        assert isinstance(pool, ThreadPool)
        assert pool.context.contextFactory is orm.TotallyDisconnected
        assert threads.max_threads_for_default_pool == pool.max
        assert 0 == pool.min

    def test_make_default_pool_accepts_max_threads_setting(self):
        maxthreads = random.randint(1, 1000)
        pool = threads.make_default_pool(maxthreads)
        assert maxthreads == pool.max
        assert 0 == pool.min

    def test_make_database_pool_creates_connected_pool(self):
        pool = threads.make_database_pool()
        assert isinstance(pool, ThreadPool)
        assert pool.context.contextFactory is orm.FullyConnected
        assert threads.max_threads_for_database_pool == pool.max
        assert 0 == pool.min

    def test_make_database_pool_accepts_max_threads_setting(self):
        maxthreads = random.randint(1, 1000)
        pool = threads.make_database_pool(maxthreads)
        assert maxthreads == pool.max
        assert 0 == pool.min

    def test_make_database_unpool_creates_unpool(self):
        pool = threads.make_database_unpool()
        assert isinstance(pool, ThreadUnpool)
        assert pool.contextFactory is orm.FullyConnected
        assert isinstance(pool.lock, DeferredSemaphore)
        assert threads.max_threads_for_database_pool == pool.lock.limit

    def test_make_database_unpool_accepts_max_threads_setting(self):
        maxthreads = random.randint(1, 1000)
        pool = threads.make_database_unpool(maxthreads)
        assert maxthreads == pool.lock.limit


class TestInstallFunctions:
    """Tests for the `install_*` functions."""

    def test_install_default_pool_will_not_work_now(self):
        with pytest.raises(AssertionError) as error:
            threads.install_default_pool()
        assert "Too late; " in str(error.value)

    def test_default_pool_is_disconnected_pool(self):
        pool = reactor.threadpool
        assert isinstance(pool, ThreadPool)
        assert pool.context.contextFactory is orm.TotallyDisconnected
        assert 0 == pool.min

    def test_install_database_pool_will_not_work_now(self):
        with pytest.raises(AssertionError) as error:
            threads.install_database_pool()
        assert "Too late; " in str(error.value)

    def test_database_pool_is_connected_unpool(self):
        pool = reactor.threadpoolForDatabase
        assert isinstance(pool, ThreadUnpool)
        assert pool.contextFactory is orm.FullyConnected


@pytest.mark.usefixtures("maasdb")
class TestDeferToDatabase:
    @wait_for_reactor
    @inlineCallbacks
    def test_defers_to_database_threadpool(self):
        @orm.transactional
        def call_in_database_thread(a, b):
            orm.validate_in_transaction(connection)
            return sentinel.called, a, b

        result = yield threads.deferToDatabase(
            call_in_database_thread, sentinel.a, b=sentinel.b
        )
        assert (sentinel.called, sentinel.a, sentinel.b) == result


@pytest.mark.usefixtures("maasdb")
class TestCallOutToDatabase:
    @wait_for_reactor
    @inlineCallbacks
    def test_calls_out_to_database_threadpool(self):
        @orm.transactional
        def call_in_database_thread(a, b):
            orm.validate_in_transaction(connection)
            return sentinel.bar, a, b

        result = yield threads.callOutToDatabase(
            sentinel.foo, call_in_database_thread, sentinel.a, b=sentinel.b
        )
        assert result is sentinel.foo
