# Copyright 2014-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `provisioningserver.drivers.hardware.virsh`."""

import random
from textwrap import dedent
from unittest.mock import call

from lxml import etree
import pexpect
import pytest
from twisted.internet.defer import inlineCallbacks
from twisted.internet.threads import deferToThread

from maastesting import get_testing_timeout
from maastesting.crochet import wait_for
from maastesting.factory import factory
from provisioningserver.drivers.hardware import virsh
from provisioningserver.utils.arch import KERNEL_TO_DEBIAN_ARCHITECTURES
from provisioningserver.utils.shell import get_env_with_locale
from provisioningserver.utils.twisted import asynchronous

TIMEOUT = get_testing_timeout()


SAMPLE_IFLIST = dedent(
    """
    Interface  Type       Source     Model       MAC
    -------------------------------------------------------
    -          bridge     br0        e1000       %s
    -          bridge     br1        e1000       %s
    """
)

SAMPLE_DUMPXML = dedent(
    """
    <domain type='kvm'>
      <name>test</name>
      <memory unit='KiB'>4096576</memory>
      <currentMemory unit='KiB'>4096576</currentMemory>
      <vcpu placement='static'>1</vcpu>
      <os>
        <type arch='%s'>hvm</type>
        <boot dev='hd'/>
      </os>
    </domain>
    """
)

SAMPLE_DUMPXML_2 = dedent(
    """
    <domain type='kvm'>
      <name>test</name>
      <memory unit='KiB'>4096576</memory>
      <currentMemory unit='KiB'>4096576</currentMemory>
      <vcpu placement='static'>1</vcpu>
      <os>
        <type arch='%s'>hvm</type>
        <boot dev='hd'/>
        <boot dev='network'/>
      </os>
    </domain>
    """
)

SAMPLE_DUMPXML_3 = dedent(
    """
    <domain type='kvm'>
      <name>test</name>
      <memory unit='KiB'>4096576</memory>
      <currentMemory unit='KiB'>4096576</currentMemory>
      <vcpu placement='static'>1</vcpu>
      <os>
        <type arch='%s'>hvm</type>
        <boot dev='network'/>
      </os>
    </domain>
    """
)

SAMPLE_DUMPXML_4 = dedent(
    """
    <domain type='kvm'>
      <name>test</name>
      <memory unit='KiB'>4096576</memory>
      <currentMemory unit='KiB'>4096576</currentMemory>
      <vcpu placement='static'>1</vcpu>
      <os>
        <type arch='%s'>hvm</type>
        <boot dev='network'/>
        <boot dev='hd'/>
      </os>
    </domain>
    """
)


@pytest.fixture(autouse=True)
def _pytest_test_helpers(request, mocker):
    if request.instance is not None:
        request.instance.mocker = mocker
        request.instance.request = request


class TestVirshSSH:
    """Tests for `VirshSSH`."""

    def configure_virshssh_pexpect(self, inputs=None, dom_prefix=None):
        """Configures the VirshSSH class to use 'cat' process
        for testing instead of the actual virsh."""
        conn = virsh.VirshSSH(timeout=0.1, dom_prefix=dom_prefix)
        self.request.addfinalizer(conn.close)
        self.mocker.patch.object(conn, "_execute")
        conn._spawn("cat")
        if inputs is not None:
            for line in inputs:
                conn.sendline(line)
        return conn

    def configure_virshssh(self, output, dom_prefix=None):
        self.mocker.patch.object(virsh.VirshSSH, "run").return_value = output
        return virsh.VirshSSH(dom_prefix=dom_prefix)

    def test_login_prompt(self):
        virsh_outputs = ["virsh # "]
        conn = self.configure_virshssh_pexpect(virsh_outputs)
        assert conn.login(poweraddr=None)

    def test_login_with_sshkey(self):
        virsh_outputs = [
            "The authenticity of host '127.0.0.1' can't be established.",
            "ECDSA key fingerprint is "
            "00:11:22:33:44:55:66:77:88:99:aa:bb:cc:dd:ee:ff.",
            "Are you sure you want to continue connecting (yes/no)? ",
        ]
        conn = self.configure_virshssh_pexpect(virsh_outputs)
        mock_sendline = self.mocker.patch.object(conn, "sendline")
        conn.login(poweraddr=None)
        mock_sendline.assert_called_once_with("yes")

    def test_login_with_password(self):
        virsh_outputs = [
            "ubuntu@%s's password: " % factory.make_ipv4_address()
        ]
        conn = self.configure_virshssh_pexpect(virsh_outputs)
        fake_password = factory.make_name("password")
        mock_sendline = self.mocker.patch.object(conn, "sendline")
        conn.login(poweraddr=None, password=fake_password)
        mock_sendline.assert_called_once_with(fake_password)

    def test_login_missing_password(self):
        virsh_outputs = [
            "ubuntu@%s's password: " % factory.make_ipv4_address()
        ]
        conn = self.configure_virshssh_pexpect(virsh_outputs)
        mock_close = self.mocker.patch.object(conn, "close")
        assert not (conn.login(poweraddr=None, password=None))
        mock_close.assert_called_once_with()

    def test_login_invalid(self):
        virsh_outputs = [factory.make_string()]
        conn = self.configure_virshssh_pexpect(virsh_outputs)
        mock_close = self.mocker.patch.object(conn, "close")
        assert not (conn.login(poweraddr=None))
        mock_close.assert_called_once_with()

    def test_logout(self):
        conn = self.configure_virshssh_pexpect()
        mock_sendline = self.mocker.patch.object(conn, "sendline")
        mock_close = self.mocker.patch.object(conn, "close")
        conn.logout()
        mock_sendline.assert_called_once_with("quit")
        mock_close.assert_called_once_with()

    def test_prompt(self):
        virsh_outputs = ["virsh # "]
        conn = self.configure_virshssh_pexpect(virsh_outputs)
        assert conn.prompt()

    def test_invalid_prompt(self):
        virsh_outputs = [factory.make_string()]
        conn = self.configure_virshssh_pexpect(virsh_outputs)
        assert not (conn.prompt())

    def test_run(self):
        cmd = ["list", "--all", "--name"]
        expected = " ".join(cmd)
        names = [factory.make_name("machine") for _ in range(3)]
        conn = self.configure_virshssh_pexpect()
        conn.before = ("\n".join([expected] + names)).encode("utf-8")
        mock_sendline = self.mocker.patch.object(conn, "sendline")
        mock_prompt = self.mocker.patch.object(conn, "prompt")
        output = conn.run(cmd)
        mock_sendline.assert_called_once_with(expected)
        mock_prompt.assert_called_once_with()
        assert "\n".join(names) == output

    def test_list(self):
        names = [factory.make_name("machine") for _ in range(3)]
        conn = self.configure_virshssh("\n".join(names))
        expected = conn.list()
        assert names == expected

    def test_list_dom_prefix(self):
        prefix = "dom_prefix"
        names = [prefix + factory.make_name("machine") for _ in range(3)]
        conn = self.configure_virshssh("\n".join(names), dom_prefix=prefix)
        expected = conn.list()
        assert names == expected

    def test_get_state(self):
        state = factory.make_name("state")
        conn = self.configure_virshssh(state)
        expected = conn.get_state("")
        assert state == expected

    def test_get_state_error(self):
        conn = self.configure_virshssh("error:")
        expected = conn.get_state("")
        assert expected is None

    def test_mac_addresses_returns_list(self):
        macs = [factory.make_mac_address() for _ in range(2)]
        output = SAMPLE_IFLIST % (macs[0], macs[1])
        conn = self.configure_virshssh(output)
        expected = conn.get_mac_addresses("")
        assert macs == expected

    def test_get_arch_returns_valid(self):
        arch = factory.make_name("arch")
        output = SAMPLE_DUMPXML % arch
        conn = self.configure_virshssh(output)
        expected = conn.get_arch("machine")
        assert arch == expected

    def test_get_arch_returns_valid_fixed(self):
        arch = random.choice(list(KERNEL_TO_DEBIAN_ARCHITECTURES))
        fixed_arch = f"{KERNEL_TO_DEBIAN_ARCHITECTURES[arch]}/generic"
        output = SAMPLE_DUMPXML % arch
        conn = self.configure_virshssh(output)
        expected = conn.get_arch("machine")
        assert fixed_arch == expected

    def test_resets_locale(self):
        """
        VirshSSH resets the locale to ensure we only ever get English strings.
        """
        c_utf8_environment = get_env_with_locale()
        mock_spawn = self.mocker.patch.object(pexpect.spawn, "__init__")
        self.configure_virshssh("")
        mock_spawn.assert_called_once_with(
            None, timeout=30, maxread=2000, env=c_utf8_environment
        )


@pytest.mark.rack_reactor_guard
class TestVirsh:
    """Tests for `probe_virsh_and_enlist`."""

    def _probe_and_enlist_mock_run(self, *args):
        args = args[0]
        # if the argument is "define", we want to ensure that the boot
        # order has been set up correctly.
        if args[0] == "define":
            xml_file = args[1]
            with open(xml_file) as f:
                xml = f.read()
                doc = etree.XML(xml)
                evaluator = etree.XPathEvaluator(doc)
                boot_elements = evaluator(virsh.XPATH_BOOT)
                assert 2 == len(boot_elements)
                # make sure we set the network to come first, then the HD
                assert "network" == boot_elements[0].attrib["dev"]
                assert "hd" == boot_elements[1].attrib["dev"]
        return ""

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_probe_and_enlist(self):
        # Patch VirshSSH list so that some machines are returned
        # with some fake architectures.
        user = factory.make_name("user")
        system_id = factory.make_name("system_id")
        machines = [factory.make_name("machine") for _ in range(5)]
        self.mocker.patch.object(
            virsh.VirshSSH, "list"
        ).return_value = machines
        fake_arch = factory.make_name("arch")
        mock_arch = self.mocker.patch.object(virsh.VirshSSH, "get_arch")
        mock_arch.return_value = fake_arch
        domain = factory.make_name("domain")

        # Patch get_state so that one of the machines is on, so we
        # can check that it will be forced off.
        fake_states = [
            virsh.VirshVMState.ON,
            virsh.VirshVMState.OFF,
            virsh.VirshVMState.OFF,
            virsh.VirshVMState.ON,
            virsh.VirshVMState.ON,
        ]
        mock_state = self.mocker.patch.object(virsh.VirshSSH, "get_state")
        mock_state.side_effect = fake_states

        # Setup the power parameters that we should expect to be
        # the output of the probe_and_enlist
        fake_password = factory.make_string()
        poweraddr = factory.make_name("poweraddr")
        called_params = []
        fake_macs = []
        for machine in machines:
            macs = [factory.make_mac_address() for _ in range(4)]
            fake_macs.append(macs)
            called_params.append(
                {
                    "power_address": poweraddr,
                    "power_id": machine,
                    "power_pass": fake_password,
                }
            )

        # Patch the get_mac_addresses so we get a known list of
        # mac addresses for each machine.
        mock_macs = self.mocker.patch.object(
            virsh.VirshSSH, "get_mac_addresses"
        )
        mock_macs.side_effect = fake_macs

        # Patch the poweroff and create as we really don't want these
        # actions to occur, but want to also check that they are called.
        mock_poweroff = self.mocker.patch.object(virsh.VirshSSH, "poweroff")
        mock_create_node = self.mocker.patch.object(virsh, "create_node")
        mock_create_node.side_effect = asynchronous(
            lambda *args, **kwargs: None if machines[4] in args else system_id
        )
        mock_commission_node = self.mocker.patch.object(
            virsh, "commission_node"
        )

        # Patch login and logout so that we don't really contact
        # a server at the fake poweraddr
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = True
        mock_logout = self.mocker.patch.object(virsh.VirshSSH, "logout")
        mock_get_machine_xml = self.mocker.patch.object(
            virsh.VirshSSH, "get_machine_xml"
        )
        mock_get_machine_xml.side_effect = [
            SAMPLE_DUMPXML,
            SAMPLE_DUMPXML_2,
            SAMPLE_DUMPXML_3,
            SAMPLE_DUMPXML_4,
            SAMPLE_DUMPXML,
        ]

        mock_run = self.mocker.patch.object(virsh.VirshSSH, "run")
        mock_run.side_effect = self._probe_and_enlist_mock_run

        # Perform the probe and enlist
        yield deferToThread(
            virsh.probe_virsh_and_enlist,
            user,
            poweraddr,
            fake_password,
            accept_all=True,
            domain=domain,
        )

        # Check that login was called with the provided poweraddr and
        # password.
        mock_login.assert_called_once_with(poweraddr, fake_password)

        # Check that the create command had the correct parameters for
        # each machine.
        mock_create_node.assert_has_calls(
            [
                call(
                    fake_macs[0],
                    fake_arch,
                    "virsh",
                    called_params[0],
                    domain,
                    machines[0],
                ),
                call(
                    fake_macs[1],
                    fake_arch,
                    "virsh",
                    called_params[1],
                    domain,
                    machines[1],
                ),
                call(
                    fake_macs[2],
                    fake_arch,
                    "virsh",
                    called_params[2],
                    domain,
                    machines[2],
                ),
                call(
                    fake_macs[3],
                    fake_arch,
                    "virsh",
                    called_params[3],
                    domain,
                    machines[3],
                ),
                call(
                    fake_macs[4],
                    fake_arch,
                    "virsh",
                    called_params[4],
                    domain,
                    machines[4],
                ),
            ]
        )

        # The first and last machine should have poweroff called on it, as it
        # was initial in the on state.
        mock_poweroff.assert_has_calls([call(machines[0]), call(machines[3])])

        mock_logout.assert_called_once_with()
        mock_commission_node.assert_has_calls(
            [
                call(system_id, user),
                call().wait(30),
                call(system_id, user),
                call().wait(30),
                call(system_id, user),
                call().wait(30),
                call(system_id, user),
                call().wait(30),
            ]
        )

    @wait_for(timeout=TIMEOUT)
    @inlineCallbacks
    def test_probe_and_enlist_login_failure(self):
        user = factory.make_name("user")
        poweraddr = factory.make_name("poweraddr")
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = False
        with pytest.raises(
            virsh.VirshError, match=r"^Failed to login to virsh console\.$"
        ):
            yield deferToThread(
                virsh.probe_virsh_and_enlist,
                user,
                poweraddr,
                password=factory.make_string(),
            )


class TestVirshPowerControl:
    """Tests for `power_control_virsh`."""

    def test_power_control_login_failure(self):
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = False
        with pytest.raises(virsh.VirshError):
            virsh.power_control_virsh(
                factory.make_name("poweraddr"),
                factory.make_name("machine"),
                "on",
                password=factory.make_string(),
            )

    def test_power_control_on(self):
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = True
        mock_state = self.mocker.patch.object(virsh.VirshSSH, "get_state")
        mock_state.return_value = virsh.VirshVMState.OFF
        mock_poweron = self.mocker.patch.object(virsh.VirshSSH, "poweron")

        poweraddr = factory.make_name("poweraddr")
        machine = factory.make_name("machine")
        virsh.power_control_virsh(poweraddr, machine, "on")

        mock_login.assert_called_once_with(poweraddr, None)
        mock_state.assert_called_once_with(machine)
        mock_poweron.assert_called_once_with(machine)

    def test_power_control_off(self):
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = True
        mock_state = self.mocker.patch.object(virsh.VirshSSH, "get_state")
        mock_state.return_value = virsh.VirshVMState.ON
        mock_poweroff = self.mocker.patch.object(virsh.VirshSSH, "poweroff")

        poweraddr = factory.make_name("poweraddr")
        machine = factory.make_name("machine")
        virsh.power_control_virsh(poweraddr, machine, "off")

        mock_login.assert_called_once_with(poweraddr, None)
        mock_state.assert_called_once_with(machine)
        mock_poweroff.assert_called_once_with(machine)

    def test_power_control_bad_domain(self):
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = True
        mock_state = self.mocker.patch.object(virsh.VirshSSH, "get_state")
        mock_state.return_value = None

        poweraddr = factory.make_name("poweraddr")
        machine = factory.make_name("machine")
        with pytest.raises(virsh.VirshError):
            virsh.power_control_virsh(poweraddr, machine, "on")

    def test_power_control_power_failure(self):
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = True
        mock_state = self.mocker.patch.object(virsh.VirshSSH, "get_state")
        mock_state.return_value = virsh.VirshVMState.ON
        mock_poweroff = self.mocker.patch.object(virsh.VirshSSH, "poweroff")
        mock_poweroff.return_value = False

        poweraddr = factory.make_name("poweraddr")
        machine = factory.make_name("machine")
        with pytest.raises(virsh.VirshError):
            virsh.power_control_virsh(poweraddr, machine, "off")


class TestVirshPowerState:
    """Tests for `power_state_virsh`."""

    def test_power_state_login_failure(self):
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = False
        with pytest.raises(virsh.VirshError):
            virsh.power_state_virsh(
                factory.make_name("poweraddr"),
                factory.make_name("machine"),
                password=factory.make_string(),
            )

    def test_power_state_get_on(self):
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = True
        mock_state = self.mocker.patch.object(virsh.VirshSSH, "get_state")
        mock_state.return_value = virsh.VirshVMState.ON

        poweraddr = factory.make_name("poweraddr")
        machine = factory.make_name("machine")
        assert "on" == virsh.power_state_virsh(poweraddr, machine)

    def test_power_state_get_off(self):
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = True
        mock_state = self.mocker.patch.object(virsh.VirshSSH, "get_state")
        mock_state.return_value = virsh.VirshVMState.OFF

        poweraddr = factory.make_name("poweraddr")
        machine = factory.make_name("machine")
        assert "off" == virsh.power_state_virsh(poweraddr, machine)

    def test_power_control_bad_domain(self):
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = True
        mock_state = self.mocker.patch.object(virsh.VirshSSH, "get_state")
        mock_state.return_value = None

        poweraddr = factory.make_name("poweraddr")
        machine = factory.make_name("machine")
        with pytest.raises(virsh.VirshError):
            virsh.power_state_virsh(poweraddr, machine)

    def test_power_state_error_on_unknown_state(self):
        mock_login = self.mocker.patch.object(virsh.VirshSSH, "login")
        mock_login.return_value = True
        mock_state = self.mocker.patch.object(virsh.VirshSSH, "get_state")
        mock_state.return_value = "unknown"

        poweraddr = factory.make_name("poweraddr")
        machine = factory.make_name("machine")
        with pytest.raises(virsh.VirshError):
            virsh.power_state_virsh(poweraddr, machine)
