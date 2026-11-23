from datetime import datetime
import io
import os
from pathlib import Path
import pstats

from provisioningserver.utils import debug
from provisioningserver.utils.debug import (
    register_sigusr1_toggle_cprofile,
    toggle_cprofile,
)


class TestToggleCprofile:
    def _get_prof_path(self, process_name):
        maas_data = os.getenv("MAAS_DATA")
        return (
            Path(maas_data)
            / "profiling"
            / f"{process_name}-{os.getpid()}-2019-01-31T01:02:03.000004.pyprof"
        )

    def test_toggle_cprofile_writes_file(self, mocker):
        now = datetime(2019, 1, 31, 1, 2, 3, 4)
        datetime_mock = mocker.patch.object(debug, "datetime")
        datetime_mock.now.return_value = now
        toggle_cprofile("my-process")
        toggle_cprofile("my-process")
        assert self._get_prof_path("my-process").exists()

    def test_toggle_cprofile_profiles(self, mocker):
        now = datetime(2019, 1, 31, 1, 2, 3, 4)
        datetime_mock = mocker.patch.object(debug, "datetime")
        datetime_mock.now.return_value = now

        def my_method():
            return 1

        toggle_cprofile("my-process")
        my_method()
        toggle_cprofile("my-process")
        prof_path = self._get_prof_path("my-process")
        output = io.StringIO()
        stats = pstats.Stats(str(prof_path), stream=output)
        stats.print_callers()
        assert "my_method" in output.getvalue()

    def test_register_sigusr1(self, mocker):
        now = datetime(2019, 1, 31, 1, 2, 3, 4)
        datetime_mock = mocker.patch.object(debug, "datetime")
        datetime_mock.now.return_value = now
        mock_signal = mocker.patch.object(debug.signal, "signal")
        register_sigusr1_toggle_cprofile("my-process")
        [(_, args, kwargs)] = mock_signal.mock_calls
        assert {} == kwargs
        signal, func = args
        assert signal.SIGUSR1 == signal
        func()
        func()
        assert self._get_prof_path("my-process").exists()
