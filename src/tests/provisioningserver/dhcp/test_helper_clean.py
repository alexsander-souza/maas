# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for maas-dhcp-helper clean and notify commands."""

from pathlib import Path
import subprocess
import tempfile

from maastesting import dev_root
from provisioningserver.utils.fs import read_text_file
from provisioningserver.utils.shell import call_and_check

LEASES_FILE_WITH_HOSTS = """\
lease 192.168.10.67 {
  starts 2 2016/03/22 13:44:15;
  ends 3 2016/03/23 01:44:15;
  cltt 2 2016/03/22 13:44:15;
  binding state active;
  next binding state free;
  rewind binding state free;
  hardware ethernet 74:d4:35:89:bc:f2;
  set clht = "zoochemical-carlton";
  set cllt = "43200";
  set clip = "192.168.10.67";
  set clhw = "74:d4:35:89:bc:f2";
  set vendor-class-identifier = "Linux ipconfig";
  client-hostname "zoochemical-carlton";
}
host 74-d4-35-89-b9-e8 {
  dynamic;
  hardware ethernet 74:d4:35:89:b9:e8;
  fixed-address 192.168.10.5;
}
lease 192.168.10.69 {
  starts 2 2016/03/22 13:44:15;
  ends 3 2016/03/23 01:44:15;
  cltt 2 2016/03/22 13:44:15;
  binding state active;
  next binding state free;
  rewind binding state free;
  hardware ethernet 74:d4:35:89:bd:25;
  set clht = "undetesting-johnetta";
  set cllt = "43200";
  set clip = "192.168.10.69";
  set clhw = "74:d4:35:89:bd:25";
  set vendor-class-identifier = "Linux ipconfig";
}
host 74-d4-35-89-bc-26 {
  dynamic;
  hardware ethernet 74:d4:35:89:bc:26;
  fixed-address 192.168.10.7;
}
host 74-d4-35-89-bc-23 {
  dynamic;
  deleted;
}
"""


LEASES_FILE_WITHOUT_HOSTS = """\
lease 192.168.10.67 {
  starts 2 2016/03/22 13:44:15;
  ends 3 2016/03/23 01:44:15;
  cltt 2 2016/03/22 13:44:15;
  binding state active;
  next binding state free;
  rewind binding state free;
  hardware ethernet 74:d4:35:89:bc:f2;
  set clht = "zoochemical-carlton";
  set cllt = "43200";
  set clip = "192.168.10.67";
  set clhw = "74:d4:35:89:bc:f2";
  set vendor-class-identifier = "Linux ipconfig";
  client-hostname "zoochemical-carlton";
}
lease 192.168.10.69 {
  starts 2 2016/03/22 13:44:15;
  ends 3 2016/03/23 01:44:15;
  cltt 2 2016/03/22 13:44:15;
  binding state active;
  next binding state free;
  rewind binding state free;
  hardware ethernet 74:d4:35:89:bd:25;
  set clht = "undetesting-johnetta";
  set cllt = "43200";
  set clip = "192.168.10.69";
  set clhw = "74:d4:35:89:bd:25";
  set vendor-class-identifier = "Linux ipconfig";
}
"""


class TestDHCPClean:
    def test_removes_hosts_from_leases_file(self, tmp_path):
        path = str(tmp_path / "leases")
        with open(path, "w") as f:
            f.write(LEASES_FILE_WITH_HOSTS)
        call_and_check(
            [
                f"{dev_root}/package-files/usr/sbin/maas-dhcp-helper",
                "clean",
                path,
            ]
        )
        assert LEASES_FILE_WITHOUT_HOSTS == read_text_file(path)


class TestDHCPHelperNotify:
    """Tests for maas-dhcp-helper notify graceful degradation."""

    def test_notify_exits_cleanly_when_socket_missing(self):
        helper = f"{dev_root}/package-files/usr/sbin/maas-dhcp-helper"
        nonexistent = Path(tempfile.mktemp(suffix=".sock"))
        result = subprocess.run(
            [
                helper,
                "notify",
                "--action",
                "commit",
                "--mac",
                "aa:bb:cc:dd:ee:ff",
                "--ip-family",
                "ipv4",
                "--ip",
                "10.0.0.1",
                "--lease-time",
                "3600",
                "--socket",
                str(nonexistent),
            ],
            capture_output=True,
            text=True,
        )
        assert 0 == result.returncode, (
            f"Helper crashed with exit code {result.returncode}:\n{result.stderr}"
        )
        assert "not found" in result.stderr

    def test_notify_exits_cleanly_when_socket_dir_missing(self):
        helper = f"{dev_root}/package-files/usr/sbin/maas-dhcp-helper"
        nonexistent = "/nonexistent/path/dhcpd.sock"
        result = subprocess.run(
            [
                helper,
                "notify",
                "--action",
                "commit",
                "--mac",
                "aa:bb:cc:dd:ee:ff",
                "--ip-family",
                "ipv4",
                "--ip",
                "10.0.0.1",
                "--lease-time",
                "3600",
                "--socket",
                nonexistent,
            ],
            capture_output=True,
            text=True,
        )
        assert 0 == result.returncode, (
            f"Helper crashed with exit code {result.returncode}:\n{result.stderr}"
        )
        assert "not found" in result.stderr
