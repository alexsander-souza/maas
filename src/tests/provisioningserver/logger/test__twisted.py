# Copyright 2014-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for Twisted-specific logging stuff."""

import io
import json
import threading
import time

import pytest
from twisted import logger
from twisted.python.failure import Failure

from maascommon.tracing import set_trace_id
from maastesting.factory import factory
from maastesting.twisted import TwistedLoggerFixture
from provisioningserver.logger import _twisted
from provisioningserver.logger._twisted import (
    _getCommandName,
    _getSystemName,
    EventLogger,
    LegacyLogger,
    LogFormatter,
    observe_twisted_internet_tcp,
    observe_twisted_internet_udp,
    observe_twisted_internet_unix,
)
from provisioningserver.logger.testing import (
    find_log_lines,
    make_event,
    pick_log_time,
)


def formatTimeStatic(when):
    """Just return <when>."""
    return "<when>"


class TestLegacyLogger:
    def test_logs_messages(self):
        events = []
        namespace = factory.make_name("namespace")
        legacy_logger = LegacyLogger(namespace, self, events.append)
        message = factory.make_name("message")
        keywords = {
            factory.make_name("key"): factory.make_name("value")
            for _ in range(3)
        }

        t0 = time.time()
        legacy_logger.msg(message, **keywords)
        t1 = time.time()

        expected = {
            "log_format": "{_message_0}",
            "log_level": logger.LogLevel.info,
            "log_logger": legacy_logger,
            "log_namespace": namespace,
            "log_source": self,
            "_message_0": message,
        }
        expected.update(keywords)
        assert len(events) == 1
        event = events[0]
        for key, value in expected.items():
            assert event.get(key) == value
        assert abs(event.get("log_time") - t1) <= (t1 - t0)
        assert (
            f"<when> [{namespace}#info] {message}\n"
            == logger.formatEventAsClassicLogText(events[0], formatTimeStatic)
        )

    def test_logs_multiple_messages(self):
        events = []
        legacy_logger = LegacyLogger(observer=events.append)
        messages = [
            factory.make_name("message"),
            factory.make_name("message"),
            factory.make_name("message"),
        ]

        legacy_logger.msg(*messages)

        expected = {
            "_message_0": messages[0],
            "_message_1": messages[1],
            "_message_2": messages[2],
            "log_format": "{_message_0} {_message_1} {_message_2}",
        }
        assert len(events) == 1
        event = events[0]
        for key, value in expected.items():
            assert event.get(key) == value
        assert "<when> [{}#info] {}\n".format(
            __name__, " ".join(messages)
        ) == logger.formatEventAsClassicLogText(events[0], formatTimeStatic)

    def test_logs_errors(self):
        events = []
        namespace = factory.make_name("namespace")
        legacy_logger = LegacyLogger(namespace, self, events.append)
        message = factory.make_name("message")
        exception_type = factory.make_exception_type()
        keywords = {
            factory.make_name("key"): factory.make_name("value")
            for _ in range(3)
        }
        exc_instance = exception_type()
        try:
            raise exc_instance
        except exception_type:
            t0 = time.time()
            legacy_logger.err(None, message, **keywords)
            t1 = time.time()

        expected = {
            "log_failure": Failure(exc_instance),
            "log_format": "{_why}",
            "log_level": logger.LogLevel.critical,
            "log_logger": legacy_logger,
            "log_namespace": namespace,
            "log_source": self,
            "_why": message,
        }
        expected.update(keywords)
        assert len(events) == 1
        event = events[0]
        for key, value in expected.items():
            if key == "log_failure":
                # Compare failure values directly; Failure.__eq__
                # compares both value and traceback, which may differ.
                assert event.get(key).value == value.value
            else:
                assert event.get(key) == value
        assert abs(event.get("log_time") - t1) <= (t1 - t0)

        # Twisted 16.6.0 (see issue #8858) now includes a traceback,
        # so we only match on the beginning of the string.
        assert logger.formatEventAsClassicLogText(
            event, formatTimeStatic
        ).startswith(f"<when> [{namespace}#critical] {message}\n")


class TestObserveTwistedInternetTCP:
    """Tests for `observe_twisted_internet_tcp`."""

    def test_ignores_port_closed_events(self):
        event = make_event(
            "(%s Port %d Closed)"
            % (factory.make_name("port-name"), factory.pick_port())
        )
        with TwistedLoggerFixture() as logger:
            observe_twisted_internet_tcp(event)
        assert len(logger.events) == 0

    def test_ignores_protocol_starting_on_events(self):
        event = make_event(
            "%s starting on %d"
            % (factory.make_name("protocol"), factory.pick_port())
        )
        with TwistedLoggerFixture() as logger:
            observe_twisted_internet_tcp(event)
        assert len(logger.events) == 0

    def test_propagates_other_events(self):
        event = make_event(factory.make_name("something"))
        with TwistedLoggerFixture() as logger:
            observe_twisted_internet_tcp(event)
        assert event in logger.events


class TestObserveTwistedInternetUDP:
    """Tests for `observe_twisted_internet_udp`."""

    def test_ignores_port_closed_events(self):
        event = make_event(
            "(%s Port %d Closed)"
            % (factory.make_name("port-name"), factory.pick_port())
        )
        with TwistedLoggerFixture() as logger:
            observe_twisted_internet_udp(event)
        assert len(logger.events) == 0

    def test_ignores_protocol_starting_on_events(self):
        event = make_event(
            "%s starting on %d"
            % (factory.make_name("protocol"), factory.pick_port())
        )
        with TwistedLoggerFixture() as logger:
            observe_twisted_internet_udp(event)
        assert len(logger.events) == 0

    def test_propagates_other_events(self):
        event = make_event(factory.make_name("something"))
        with TwistedLoggerFixture() as logger:
            observe_twisted_internet_udp(event)
        assert event in logger.events


class TestObserveTwistedInternetUNIX:
    """Tests for `observe_twisted_internet_unix`."""

    def test_ignores_port_closed_events(self):
        event = make_event(
            "(%s Port %r Closed)"
            % (factory.make_name("port-name"), factory.make_name("port"))
        )
        with TwistedLoggerFixture() as logger:
            observe_twisted_internet_unix(event)
        assert len(logger.events) == 0

    def test_ignores_protocol_starting_on_events(self):
        event = make_event(
            "%s starting on %d"
            % (factory.make_name("protocol"), factory.pick_port())
        )
        with TwistedLoggerFixture() as logger:
            observe_twisted_internet_unix(event)
        assert len(logger.events) == 0

    def test_propagates_other_events(self):
        event = make_event(factory.make_name("something"))
        with TwistedLoggerFixture() as logger:
            observe_twisted_internet_unix(event)
        assert event in logger.events


@pytest.mark.parametrize(
    "string_in,string_out",
    [
        ("foo.bar.baz", "foo.bar.baz"),
        ("f_o.bar.baz", "f_o.bar.baz"),
        ("foo.b_r.baz", "foo.b_r.baz"),
        ("foo.bar.b_z", "foo.bar.b_z"),
        ("foo.bar._az", "foo.bar"),
        ("foo._ar.baz", "foo"),
        ("foo._ar._az", "foo"),
        ("_oo.bar.baz", None),
        ("_", None),
        ("", None),
        (None, None),
    ],
    ids=[
        "foo.bar.baz => foo.bar.baz",
        "f_o.bar.baz => f_o.bar.baz",
        "foo.b_r.baz => foo.b_r.baz",
        "foo.bar.b_z => foo.bar.b_z",
        "foo.bar._az => foo.bar",
        "foo._ar.baz => foo",
        "foo._ar._az => foo",
        "_oo.bar.baz => None",
        "_ => None",
        " => None",
        "None => None",
    ],
)
class TestGetSystemName:
    """Tests for `_getSystemName`."""

    def test(self, string_in, string_out):
        assert string_out == _getSystemName(string_in)


@pytest.mark.parametrize(
    "argv,expected",
    [
        (
            (
                "/usr/bin/twistd3",
                "--nodaemon",
                "--pidfile=",
                "--logger=provisioningserver.logger.EventLogger",
                "maas-rackd",
            ),
            "rackd",
        ),
        (
            (
                "twistd3",
                "--nodaemon",
                "--pidfile=",
                "--logger=provisioningserver.logger.EventLogger",
                "maas-regiond",
            ),
            "regiond",
        ),
        (("twistd3", "--an-option", "something-else"), "daemon"),
        (("some-command",), "some-command"),
        (("some-command-with-suffix.py",), "some-command-with-suffix"),
        (("python", "py-command"), "py-command"),
        (
            ("python", "py-command-with-suffix.py"),
            "py-command-with-suffix",
        ),
        (("python", "-c", "print('woo')"), "command"),
    ],
    ids=[
        "rackd",
        "regiond",
        "daemon",
        "some-command",
        "some-command-with-suffix",
        "py-command",
        "py-command-with-suffix",
        "command",
    ],
)
class TestGetCommandName:
    """Tests for `_getCommandName`."""

    def test(self, argv, expected):
        assert expected == _getCommandName(argv)


_LOG_LEVELS = list(logger.LogLevel.iterconstants())
_LOG_LEVEL_NAMES = [level.name for level in _LOG_LEVELS]


@pytest.mark.parametrize("log_level", _LOG_LEVELS, ids=_LOG_LEVEL_NAMES)
class TestLogFormatter:
    """Tests for `_formatModernEvent`."""

    def test_format_basics(self, log_level):
        thing1 = factory.make_name("thing")
        thing2 = factory.make_name("thing")
        log_system = factory.make_name("system")
        log_format = ">{thing1}< >{thing2}<"
        log_time = pick_log_time()
        assert (
            f"{log_system}: [{log_level.name}] >{thing1}< >{thing2}<\n"
            == LogFormatter(use_json_logging=False)(
                {
                    "log_time": log_time,
                    "log_format": log_format,
                    "log_system": log_system,
                    "log_level": log_level,
                    "thing1": thing1,
                    "thing2": thing2,
                }
            )
        )

    def test_format_failure(self, log_level):
        try:
            1 / 0  # noqa: B018
        except ZeroDivisionError:
            failure = Failure()
        else:
            raise RuntimeError("should have raised ZeroDivisionError")
        log_system = factory.make_name("system")
        assert "%s: [%s] \n\t%s\n" % (
            log_system,
            log_level.name,
            failure.getTraceback().replace("\n", "\n\t"),
        ) == LogFormatter(use_json_logging=False)(
            {
                "log_system": log_system,
                "log_level": log_level,
                "log_failure": failure,
            }
        )

    def test_formats_without_format(self, log_level):
        assert "-: [%s] \n" % log_level.name == LogFormatter(
            use_json_logging=False
        )({"log_level": log_level})

    def test_formats_with_null_format(self, log_level):
        assert f"-: [{log_level.name}] \n" == LogFormatter(
            use_json_logging=False
        )({"log_format": None, "log_level": log_level})

    def test_uses_namespace_if_system_missing(self, log_level):
        log_namespace = factory.make_name("namespace")
        assert f"{log_namespace}: [{log_level.name}] \n" == LogFormatter(
            use_json_logging=False
        )({"log_level": log_level, "log_namespace": log_namespace})

    def test_uses_namespace_if_system_null(self, log_level):
        log_namespace = factory.make_name("namespace")
        assert f"{log_namespace}: [{log_level.name}] \n" == LogFormatter(
            use_json_logging=False
        )(
            {
                "log_level": log_level,
                "log_namespace": log_namespace,
                "log_system": None,
            }
        )

    def test_json_formatting(self, log_level):
        thing1 = factory.make_name("thing")
        thing2 = factory.make_name("thing")
        log_system = factory.make_name("system")
        log_format = ">{thing1}< >{thing2}<"
        log_time = pick_log_time()
        assert {
            "level": log_level.name,
            "message": f">{thing1}< >{thing2}<",
            "name": log_system,
            "trace_id": "",
            "thread": f"{threading.current_thread().name}:{threading.current_thread().ident}",
        } == json.loads(
            LogFormatter(use_json_logging=True)(
                {
                    "log_time": log_time,
                    "log_format": log_format,
                    "log_system": log_system,
                    "log_level": log_level,
                    "thing1": thing1,
                    "thing2": thing2,
                }
            )
        )

    def test_json_formatting_includes_trace_id(self, log_level, request):
        request.addfinalizer(lambda: set_trace_id(""))
        set_trace_id("test_trace_id")
        log_system = factory.make_name("system")
        log_format = "{test}"
        log_time = pick_log_time()
        assert {
            "level": log_level.name,
            "message": "test",
            "name": log_system,
            "thread": f"{threading.current_thread().name}:{threading.current_thread().ident}",
            "trace_id": "test_trace_id",
        } == json.loads(
            LogFormatter(use_json_logging=True)(
                {
                    "log_time": log_time,
                    "log_format": log_format,
                    "log_system": log_system,
                    "log_level": log_level,
                    "test": "test",
                }
            )
        )


@pytest.mark.parametrize("log_level", _LOG_LEVELS, ids=_LOG_LEVEL_NAMES)
class TestEventLogger:
    """Tests for `EventLogger`."""

    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        self._mocker = mocker
        self.output = io.StringIO()
        self._disable_json_logging()
        self.log = EventLogger(self.output)
        self.get_logs = lambda: find_log_lines(
            self.output.getvalue(), use_json_logging=False
        )

    def _disable_json_logging(self):
        from provisioningserver import settings

        settings.USE_JSON_LOGGING = False

    def setLogLevel(self, log_level):
        """Set the level at which events will be logged.

        This is not a minimum level, it is an absolute level.
        """
        self._mocker.patch.object(_twisted, "_filterByLevels", {log_level})

    def test_basics(self, log_level):
        self.setLogLevel(log_level)
        event = make_event(log_level=log_level)
        event["log_system"] = factory.make_name("system")
        self.log(event)
        assert [
            (event["log_system"], log_level.name, event["log_text"])
        ] == self.get_logs()

    def test_filters_by_level(self, log_level):
        self.setLogLevel(log_level)
        events = {
            level: make_event(log_level=level)
            for level in logger.LogLevel.iterconstants()
        }
        for event in events.values():
            self.log(event)
        # Only the log at the current level will get through.
        assert [
            ("-", log_level.name, events[log_level]["log_text"])
        ] == self.get_logs()

    def test_filters_by_noise(self, log_level):
        self.setLogLevel(log_level)
        common = dict(log_namespace="log_legacy", log_system="-")
        noisy = [
            make_event("Log opened.", **common),
            make_event("Main loop terminated.", **common),
        ]
        for event in noisy:
            self.log(event)
        okay = [make_event(log_level=log_level, **common)]
        for event in okay:
            self.log(event)
        # Only the `okay` logs will get through.
        expected = [("-", log_level.name, event["log_text"]) for event in okay]
        assert expected == self.get_logs()
