# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `p.logger._maaslog`."""

import logging
import logging.handlers

import pytest

from maastesting.factory import factory
from provisioningserver.logger import _maaslog
from provisioningserver.logger._maaslog import get_maas_logger, MAASLogger


class TestMAASLogger:
    """Tests for the logger returned by `get_maas_logger`."""

    def test_sets_logger_name(self, mocker):
        mocker.patch.object(_maaslog, "SysLogHandler", create=True)
        mocker.patch.object(logging, "Formatter")
        name = factory.make_string()
        maaslog = get_maas_logger(name)
        assert "maas.%s" % name == maaslog.name

    def test_returns_same_logger_if_called_twice(self, mocker):
        mocker.patch.object(_maaslog, "SysLogHandler", create=True)
        mocker.patch.object(logging, "Formatter")
        name = factory.make_string()
        maaslog = get_maas_logger(name)
        maaslog_2 = get_maas_logger(name)
        assert maaslog is maaslog_2

    def test_exception_calls_disallowed(self, mocker):
        mocker.patch.object(_maaslog, "SysLogHandler", create=True)
        mocker.patch.object(logging, "Formatter")
        name = factory.make_string()
        maaslog = get_maas_logger(name)
        with pytest.raises(NotImplementedError):
            maaslog.exception(factory.make_string())

    def test_returns_MAASLogger_instances(self, mocker):
        mocker.patch.object(_maaslog, "SysLogHandler", create=True)
        mocker.patch.object(logging, "Formatter")
        name = factory.make_string()
        maaslog = get_maas_logger(name)
        assert isinstance(maaslog, MAASLogger)

    def test_doesnt_affect_general_logger_class(self, mocker):
        mocker.patch.object(logging, "Formatter")
        name = factory.make_string()
        get_maas_logger(name)
        assert MAASLogger is not logging.getLoggerClass()

    def test_general_logger_class_accepts_exceptions(self, mocker):
        mocker.patch.object(logging, "Formatter")
        name = factory.make_string()
        get_maas_logger(name)
        other_logger = logging.getLogger()
        assert other_logger.exception(factory.make_string()) is None
