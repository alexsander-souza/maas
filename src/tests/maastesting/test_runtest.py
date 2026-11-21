# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import pytest
from testtools import TestCase

from maastesting.runtest import MAASRunTest, MAASTwistedRunTest


class TestExecutors:
    def _run_and_check(self, executor):
        class BrokenTests(TestCase):
            run_tests_with = executor

            def test(self):
                yield None

        test = BrokenTests("test")
        result = test.run()

        assert len(result.errors) == 1
        failed_test, traceback = result.errors[0]
        assert failed_test is test
        assert (
            "InvalidTest: Test returned a generator. Should it be decorated with inlineCallbacks?"
            in str(traceback)
        )

    def test_catches_generator_tests_maasruntest(self):
        """MAASRunTest should catch tests that return a generator."""
        self._run_and_check(MAASRunTest)

    def test_catches_generator_tests_maastwistedruntest(self):
        """MAASTwistedRunTest should catch tests that return a generator.

        Note: this test only works when the Twisted reactor is not already
        running. In the MAAS test environment the reactor is managed by
        crochet, so the MAASTwistedRunTest variant is skipped if the
        reactor is already running.
        """

        class BrokenTests(TestCase):
            run_tests_with = MAASTwistedRunTest

            def test(self):
                yield None

        test = BrokenTests("test")
        try:
            result = test.run()
        except Exception as e:
            if "ReactorAlreadyRunning" in str(e):
                pytest.skip(
                    "MAASTwistedRunTest requires the reactor to be stopped"
                )
            raise

        if len(result.errors) == 1:
            failed_test, traceback = result.errors[0]
            if "ReactorAlreadyRunning" in str(traceback):
                pytest.skip(
                    "MAASTwistedRunTest requires the reactor to be stopped"
                )

        assert len(result.errors) == 1
        failed_test, traceback = result.errors[0]
        assert failed_test is test
        assert (
            "InvalidTest: Test returned a generator. Should it be decorated with inlineCallbacks?"
            in str(traceback)
        )
