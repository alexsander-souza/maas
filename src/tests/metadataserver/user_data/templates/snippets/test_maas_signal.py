# Copyright 2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from importlib import import_module
import sys
from unittest.mock import patch

import pytest

from snippets import maas_api_helper


@pytest.fixture
def maas_signal():
    with patch.dict(sys.modules, {"maas_api_helper": maas_api_helper}):
        return import_module("snippets.maas_signal")


def test_rejects_unsupported_power_type(maas_signal, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        maas_signal, "signal", lambda *args: calls.append(args)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "maas-signal",
            "--url",
            "http://maas.example.com",
            "--power-type",
            "wedge",
            "OK",
        ],
    )

    with pytest.raises(SystemExit) as error:
        maas_signal.main()

    assert error.value.code == 2
    assert calls == []


def test_signals_supported_power_types(maas_signal, monkeypatch):
    calls = []
    monkeypatch.setattr(
        maas_signal, "signal", lambda *args: calls.append(args)
    )

    for power_type in ("ipmi", "virsh", "manual", "moonshot"):
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "maas-signal",
                "--url",
                "http://maas.example.com",
                "--power-type",
                power_type,
                "OK",
            ],
        )
        maas_signal.main()

        assert calls[-1][-2:] == (power_type, None)

    assert len(calls) == 4
