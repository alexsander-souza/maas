# Copyright 2012-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for MAAS fields from the region test suite."""

from random import choice, randint
import re

from django.core.exceptions import ValidationError
from django.db import connection, DatabaseError, transaction
from psycopg2 import OperationalError
import pytest

from maasserver.fields import (
    HostListFormField,
    IPListFormField,
    IPPortListFormField,
    IPWithOptionalPort,
    LargeObjectField,
    LargeObjectFile,
    MODEL_NAME_VALIDATOR,
    NodeChoiceField,
    SubnetListFormField,
    SystemdIntervalField,
    URLOrPPAFormField,
    URLOrPPAValidator,
    VersionedTextFileField,
)
from maasserver.models import Node, VersionedTextFile
from maasserver.models.interface import Interface
from maasserver.testing.factory import factory
from maasserver.tests.models import (
    CIDRTestModel,
    IPv4CIDRTestModel,
    LargeObjectFieldModel,
    XMLFieldModel,
)
from maasserver.utils.orm import reload_object


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestModelNameValidator:
    def test_valid_name(self):
        assert MODEL_NAME_VALIDATOR("a-valid-name") is None

    def test_valid_with_number(self):
        assert MODEL_NAME_VALIDATOR("with-number-10") is None

    def test_valid_with_spaces(self):
        assert MODEL_NAME_VALIDATOR("with spaces") is None

    def test_invalid_start_space(self):
        with pytest.raises(ValidationError):
            MODEL_NAME_VALIDATOR(" not-at-start")

    def test_invalid_start_dash(self):
        with pytest.raises(ValidationError):
            MODEL_NAME_VALIDATOR("-not-at-start")


class TestIPListFormField:
    def test_accepts_none(self):
        assert IPListFormField().clean(None) is None

    def test_accepts_single_ip(self):
        ip = factory.make_ip_address()
        assert ip == IPListFormField().clean(ip)

    def test_accepts_space_separated_ips(self):
        ips = [factory.make_ip_address() for _ in range(5)]
        input = " ".join(ips)
        assert input == IPListFormField().clean(input)

    def test_accepts_comma_separated_ips(self):
        ips = [factory.make_ip_address() for _ in range(5)]
        input = ",".join(ips)
        assert " ".join(ips) == IPListFormField().clean(input)

    def test_rejects_invalid_input(self):
        invalid = factory.make_name("invalid")
        input = " ".join([factory.make_ip_address(), invalid])
        with pytest.raises(ValidationError) as excinfo:
            IPListFormField().clean(input)
        assert "Invalid IP address: %s" % invalid in excinfo.value.message

    def test_separators_dont_conflict_with_ipv4_address(self):
        assert (
            re.search(IPListFormField.separators, factory.make_ipv4_address())
            is None
        )

    def test_separators_dont_conflict_with_ipv6_address(self):
        assert (
            re.search(IPListFormField.separators, factory.make_ipv6_address())
            is None
        )


class TestIPPortListFormField:
    def test_accepts_ipv4_with_port(self):
        ips = [factory.make_ip_address(ipv6=False) for _ in range(5)]
        ip_ports = [f"{ip}:80" for ip in ips]
        input = ",".join(ip_ports)
        assert [(ip, 80) for ip in ips] == IPPortListFormField().clean(input)

    def test_accepts_ipv4_without_port(self):
        ips = [factory.make_ip_address(ipv6=False) for _ in range(5)]
        input = ",".join(ips)
        assert [(ip, 80) for ip in ips] == IPPortListFormField(
            default_port=80
        ).clean(input)

    def test_accepts_ipv6_with_port(self):
        ips = [factory.make_ip_address(ipv6=True) for _ in range(5)]
        ip_ports = [f"[{ip}]:80" for ip in ips]
        input = ",".join(ip_ports)
        assert [(ip, 80) for ip in ips] == IPPortListFormField().clean(input)

    def test_accepts_ipv6_without_port(self):
        ips = [factory.make_ip_address(ipv6=True) for _ in range(5)]
        input = ",".join(ips)
        assert [(ip, 80) for ip in ips] == IPPortListFormField(
            default_port=80
        ).clean(input)

    def test_rejects_invalid_ip(self):
        ip_ports = [
            f"{factory.make_ip_address(ipv6=False)}:80" for _ in range(4)
        ]
        invalid = f"{factory.make_name()}:80"
        ip_ports.append(invalid)
        input = ",".join(ip_ports)
        with pytest.raises(ValidationError) as excinfo:
            IPPortListFormField().clean(input)
        assert (
            f"Invalid IP and port combination: {invalid}"
            in excinfo.value.message
        )


class TestHostListFormField:
    def test_accepts_none(self):
        assert HostListFormField().clean(None) is None

    def test_accepts_single_ip(self):
        ip = factory.make_ip_address()
        assert ip == HostListFormField().clean(ip)

    def test_accepts_space_separated_ips(self):
        ips = [factory.make_ip_address() for _ in range(5)]
        input = " ".join(ips)
        assert input == HostListFormField().clean(input)

    def test_accepts_comma_separated_ips(self):
        ips = [factory.make_ip_address() for _ in range(5)]
        input = ",".join(ips)
        assert " ".join(ips) == HostListFormField().clean(input)

    def test_accepts_hostname(self):
        hostname = factory.make_hostname()
        assert hostname == HostListFormField().clean(hostname)

    def test_accepts_space_separated_hostnames(self):
        hostnames = factory.make_hostname(), factory.make_hostname()
        input = " ".join(hostnames)
        assert input == HostListFormField().clean(input)

    def test_accepts_comma_separated_hostnames(self):
        hostnames = factory.make_hostname(), factory.make_hostname()
        input = ",".join(hostnames)
        assert " ".join(hostnames) == HostListFormField().clean(input)

    def test_accepts_misc(self):
        servers = {
            "::1",
            "1::",
            "1::2",
            "1:2::3",
            "1::2:3",
            "1:2::3:4",
            "::127.0.0.1",
        }
        input = ",".join(servers)
        assert " ".join(servers) == HostListFormField().clean(input)

    def test_rejects_invalid_ipv4_address(self):
        input = "%s 12.34.56.999" % factory.make_hostname()
        with pytest.raises(ValidationError) as excinfo:
            HostListFormField().clean(input)
        assert (
            "Failed to detect a valid IP address from '12.34.56.999'."
            == excinfo.value.message
        )

    def test_rejects_invalid_ipv6_address(self):
        input = "%s fe80::abcde" % factory.make_hostname()
        with pytest.raises(ValidationError) as excinfo:
            HostListFormField().clean(input)
        assert (
            "Failed to detect a valid IP address from 'fe80::abcde'."
            == excinfo.value.message
        )

    def test_rejects_invalid_hostname(self):
        input = "%s abc-.foo" % factory.make_hostname()
        with pytest.raises(ValidationError) as excinfo:
            HostListFormField().clean(input)
        assert (
            excinfo.value.message
            == "Invalid hostname: Label cannot start or end with hyphen: 'abc-'."
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestNodeChoiceField:
    def test_allows_selecting_by_system_id(self):
        node = factory.make_Node()
        for _ in range(3):
            factory.make_Node()
        node_field = NodeChoiceField(Node.objects.filter())
        assert node == node_field.clean(node.system_id)

    def test_allows_selecting_by_hostname(self):
        node = factory.make_Node()
        for _ in range(3):
            factory.make_Node()
        node_field = NodeChoiceField(Node.objects.filter())
        assert node == node_field.clean(node.hostname)

    def test_raises_exception_when_not_found(self):
        for _ in range(3):
            factory.make_Node()
        node_field = NodeChoiceField(Node.objects.filter())
        with pytest.raises(ValidationError):
            node_field.clean(factory.make_name("query"))

    def test_works_with_multiple_entries_in_queryset(self):
        # Regression test for lp:1551399
        vlan = factory.make_VLAN()
        node = factory.make_Node_with_Interface_on_Subnet(vlan=vlan)
        factory.make_Interface(node=node, vlan=vlan)
        qs = Node.objects.filter_by_vids([vlan.vid])
        node_field = NodeChoiceField(qs)
        # Double check that we have duplicated entires
        assert 2 == len(qs.filter(system_id=node.system_id))
        assert node == node_field.clean(node.system_id)


class TestSubnetListFormField:
    def test_accepts_none(self):
        assert SubnetListFormField().clean(None) is None

    def test_accepts_single_ip(self):
        ip = factory.make_ip_address()
        assert ip == SubnetListFormField().clean(ip)

    def test_accepts_space_separated_ips(self):
        ips = [factory.make_ip_address() for _ in range(5)]
        input = " ".join(ips)
        assert input == SubnetListFormField().clean(input)

    def test_accepts_comma_separated_ips(self):
        ips = [factory.make_ip_address() for _ in range(5)]
        input = ",".join(ips)
        assert " ".join(ips) == SubnetListFormField().clean(input)

    def test_accepts_single_subnet(self):
        subnet = str(factory.make_ipv4_network())
        assert subnet == SubnetListFormField().clean(subnet)

    def test_accepts_space_separated_subnets(self):
        subnets = [str(factory.make_ipv6_network()) for _ in range(5)]
        input = " ".join(subnets)
        assert input == SubnetListFormField().clean(input)

    def test_accepts_comma_separated_subnets(self):
        subnets = [str(factory.make_ipv4_network()) for _ in range(5)]
        input = ",".join(subnets)
        assert " ".join(subnets) == SubnetListFormField().clean(input)

    def test_accepts_hostname(self):
        hostname = factory.make_hostname()
        assert hostname == SubnetListFormField().clean(hostname)

    def test_accepts_space_separated_hostnames(self):
        hostnames = factory.make_hostname(), factory.make_hostname()
        input = " ".join(hostnames)
        assert input == SubnetListFormField().clean(input)

    def test_accepts_comma_separated_hostnames(self):
        hostnames = factory.make_hostname(), factory.make_hostname()
        input = ",".join(hostnames)
        assert " ".join(hostnames) == SubnetListFormField().clean(input)

    def test_accepts_misc(self):
        servers = {
            "::1",
            "1::",
            "1::2",
            "1:2::3",
            "1::2:3",
            "1:2::3:4",
            "::127.0.0.1",
        }
        input = ",".join(servers)
        assert " ".join(servers) == SubnetListFormField().clean(input)

    def test_rejects_invalid_ipv4_address(self):
        input = "%s 12.34.56.999" % factory.make_hostname()
        with pytest.raises(ValidationError) as excinfo:
            SubnetListFormField().clean(input)
        assert "Invalid IP address: 12.34.56.999." == excinfo.value.message

    def test_rejects_invalid_ipv6_address(self):
        input = "%s fe80::abcde" % factory.make_hostname()
        with pytest.raises(ValidationError) as excinfo:
            SubnetListFormField().clean(input)
        assert "Invalid IP address: fe80::abcde." == excinfo.value.message

    def test_rejects_invalid_ipv4_subnet(self):
        input = "%s 10.10.10.300/24" % factory.make_ipv4_network()
        with pytest.raises(ValidationError) as excinfo:
            SubnetListFormField().clean(input)
        assert "Invalid network: 10.10.10.300/24." == excinfo.value.message

    def test_rejects_invalid_ipv6_subnet(self):
        input = "%s 100::/300" % factory.make_ipv6_network()
        with pytest.raises(ValidationError) as excinfo:
            SubnetListFormField().clean(input)
        assert "Invalid network: 100::/300." == excinfo.value.message

    def test_rejects_invalid_hostname(self):
        input = "%s abc-.foo" % factory.make_hostname()
        with pytest.raises(ValidationError) as excinfo:
            SubnetListFormField().clean(input)
        assert (
            excinfo.value.message
            == "Invalid hostname: Label cannot start or end with hyphen: 'abc-'."
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestVersionedTextFileField:
    def test_creates_new(self):
        data = factory.make_string()
        versioned_text_file_field = VersionedTextFileField()
        versioned_text_file = versioned_text_file_field.clean(data)
        assert data == versioned_text_file.data
        assert versioned_text_file.previous_version is None

    def test_create_requires_value(self):
        versioned_text_file_field = VersionedTextFileField()
        with pytest.raises(ValidationError):
            versioned_text_file_field.clean(None)

    def test_create_new_accepts_dict_with_comment(self):
        data = factory.make_string()
        comment = factory.make_name("comment")
        versioned_text_file_field = VersionedTextFileField()
        versioned_text_file = versioned_text_file_field.clean(
            {"data": data, "comment": comment}
        )
        assert data == versioned_text_file.data
        assert comment == versioned_text_file.comment
        assert versioned_text_file.previous_version is None

    def test_update_does_nothing_on_none(self):
        data = VersionedTextFile.objects.create(data=factory.make_string())
        versioned_text_file_field = VersionedTextFileField(initial=data)
        assert data == versioned_text_file_field.clean(None)

    def test_creates_new_link(self):
        old_ver = VersionedTextFile.objects.create(data=factory.make_string())
        versioned_text_file_field = VersionedTextFileField(initial=old_ver)
        data = factory.make_string()
        new_ver = versioned_text_file_field.clean(data)
        assert data == new_ver.data
        assert old_ver == new_ver.previous_version

    def test_creates_new_link_accepts_dict(self):
        old_ver = VersionedTextFile.objects.create(data=factory.make_string())
        versioned_text_file_field = VersionedTextFileField(initial=old_ver)
        data = factory.make_string()
        comment = factory.make_name("comment")
        new_ver = versioned_text_file_field.clean(
            {"new_data": data, "comment": comment}
        )
        assert data == new_ver.data
        assert comment == new_ver.comment
        assert old_ver == new_ver.previous_version


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestURLOrPPAValidator:
    def test_URLOrPPAValidator_validates_URL(self):
        validator = URLOrPPAValidator()
        assert validator(factory.make_url(scheme="http")) is None
        assert validator(factory.make_url(scheme="https")) is None

    def test_URLOrPPAValidator_catches_bad_url(self):
        validator = URLOrPPAValidator()
        bad_url = factory.make_name("bad_url")
        with pytest.raises(ValidationError) as excinfo:
            validator(bad_url)
        assert (
            "Enter a valid repository URL or PPA location."
            == excinfo.value.message
        )

    def test_URLOrPPAValidator_catches_bad_scheme(self):
        validator = URLOrPPAValidator()
        bad_url = factory.make_url(scheme="bad_scheme")
        with pytest.raises(ValidationError) as excinfo:
            validator(bad_url)
        assert (
            "Enter a valid repository URL or PPA location."
            == excinfo.value.message
        )

    def test_URLOrPPAValidator_validates_PPA(self):
        validator = URLOrPPAValidator()
        good_ppa = "ppa:{}/{}".format(
            factory.make_hostname(),
            factory.make_hostname(),
        )
        assert validator(good_ppa) is None

    def test_URLOrPPAValidator_catches_bad_PPA_format(self):
        validator = URLOrPPAValidator()
        bad_ppa = "ppa:%s" % factory.make_hostname()
        with pytest.raises(ValidationError) as excinfo:
            validator(bad_ppa)
        assert (
            "Enter a valid repository URL or PPA location."
            == excinfo.value.message
        )

    def test_URLOrPPAValidator_catches_bad_PPA_hostname(self):
        validator = URLOrPPAValidator()
        bad_ppa = "ppa:{}/-{}".format(
            factory.make_hostname(),
            factory.make_hostname(),
        )
        with pytest.raises(ValidationError) as excinfo:
            validator(bad_ppa)
        assert (
            "Enter a valid repository URL or PPA location."
            == excinfo.value.message
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestURLOrPPAFormField:
    def test_rejects_none(self):
        with pytest.raises(ValidationError) as excinfo:
            URLOrPPAFormField().clean(None)
        assert "This field is required." == excinfo.value.message

    def test_URLOrPPAFormField_validates_URL(self):
        url = factory.make_url(scheme="http")
        assert url == URLOrPPAFormField().clean(url)

    def test_URLOrPPAFormField_catches_bad_url(self):
        bad_url = factory.make_name("bad_url")
        with pytest.raises(ValidationError) as excinfo:
            URLOrPPAFormField().clean(bad_url)
        assert (
            "Enter a valid repository URL or PPA location."
            == excinfo.value.messages[0]
        )

    def test_URLOrPPAFormField_catches_bad_scheme(self):
        bad_url = factory.make_url(scheme="bad_scheme")
        with pytest.raises(ValidationError) as excinfo:
            URLOrPPAFormField().clean(bad_url)
        assert (
            "Enter a valid repository URL or PPA location."
            == excinfo.value.messages[0]
        )

    def test_URLOrPPAFormField_validates_PPA(self):
        url = f"ppa:{factory.make_hostname()}/{factory.make_hostname()}"
        assert url == URLOrPPAFormField().clean(url)

    def test_URLOrPPAFormField_catches_bad_PPA_format(self):
        bad_url = "ppa:%s" % factory.make_hostname()
        with pytest.raises(ValidationError) as excinfo:
            URLOrPPAFormField().clean(bad_url)
        assert (
            "Enter a valid repository URL or PPA location."
            == excinfo.value.messages[0]
        )

    def test_URLOrPPAFormField_catches_bad_PPA_hostname(self):
        bad_url = "ppa:{}/-{}".format(
            factory.make_hostname(),
            factory.make_hostname(),
        )
        with pytest.raises(ValidationError) as excinfo:
            URLOrPPAFormField().clean(bad_url)
        assert (
            "Enter a valid repository URL or PPA location."
            == excinfo.value.messages[0]
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestURLOrPPAField:
    def test_create_package_repository_ppa(self):
        # PackageRepository contains a URLOrPPAField. Make one with PPA.
        ppa_url = "ppa:{}/{}".format(
            factory.make_hostname(),
            factory.make_hostname(),
        )
        factory.make_PackageRepository(url=ppa_url)

    def test_create_package_repository_url(self):
        # PackageRepository contains a URLOrPPAField. Make one with URL.
        url = factory.make_url(scheme="http")
        factory.make_PackageRepository(url=url)

    def test_cannot_create_package_repository_bad_url(self):
        # PackageRepository contains a URLOrPPAField. Make one with bad URL.
        bad_url = factory.make_name("bad_url")
        with pytest.raises(ValidationError) as excinfo:
            factory.make_PackageRepository(url=bad_url)
        assert (
            "Enter a valid repository URL or PPA location."
            == excinfo.value.messages[0]
        )

    def test_cannot_create_package_repository_bad_ppa(self):
        # PackageRepository contains a URLOrPPAField. Make one with bad PPA.
        bad_url = "ppa:%s" % factory.make_hostname()
        with pytest.raises(ValidationError) as excinfo:
            factory.make_PackageRepository(url=bad_url)
        assert (
            "Enter a valid repository URL or PPA location."
            == excinfo.value.messages[0]
        )


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestSystemdIntervalField:
    def test_valid_interval(self):
        intervals = [
            "h",
            "hr",
            "hour",
            "hours",
            "m",
            "min",
            "minute",
            "minutes",
            "s",
            "sec",
            "second",
            "seconds",
        ]
        interval = choice(intervals)
        value = f"1{interval}"
        field = SystemdIntervalField()
        assert value == field.clean(value)

    def test_invalid_interval(self):
        value = "1 year"
        field = SystemdIntervalField()
        with pytest.raises(ValidationError):
            field.clean(value)


class TestIPWithOptionalPort:
    def test_accepts_ipv4(self):
        ip = factory.make_ip_address(ipv6=False)
        assert ip == IPWithOptionalPort().clean(ip)

    def test_accepts_ipv6(self):
        ips = [
            "::1",
            "ff06::c3",
            "0:0:0:0:0:ffff:192.1.56.10",
            "::ffff:12.12.12.12",
            factory.make_ip_address(ipv6=True),
        ]
        for ip in ips:
            assert ip == IPWithOptionalPort().clean(ip)

    def test_accepts_ipv4_with_port(self):
        ip = factory.make_ip_address(ipv6=False)
        ip_port = f"{ip}:5000"
        assert ip_port == IPWithOptionalPort().clean(ip_port)

    def test_accepts_ipv6_with_port(self):
        ips = [
            "::1",
            "ff06::c3",
            "0:0:0:0:0:ffff:192.1.56.10",
            "::ffff:12.12.12.12",
            factory.make_ip_address(ipv6=True),
        ]
        for ip in ips:
            # test ipv6 with and without square brackets
            ip_port = f"{ip}:5000"
            assert ip_port == IPWithOptionalPort().clean(ip_port)
            ip_port = f"[{ip}]:5000"
            assert ip_port == IPWithOptionalPort().clean(ip_port)

    def test_rejects_invalid_ipv4_address(self):
        ip = "12.34.56.999"
        with pytest.raises(ValidationError) as excinfo:
            IPWithOptionalPort().clean(ip)
        assert (
            "Invalid IPv4/IPv6 address with optional port."
            == excinfo.value.message
        )

    def test_rejects_invalid_ipv6_address(self):
        ips = ["fe80::abcde", "fe800:0:0:0:abcdfe:0"]
        for ip in ips:
            with pytest.raises(ValidationError) as excinfo:
                IPWithOptionalPort().clean(ip)
            assert (
                "Invalid IPv4/IPv6 address with optional port."
                == excinfo.value.message
            )

    def test_rejects_invalid_port(self):
        ip = "12.34.56.78"
        ports = [-1, 65536, 99999]
        for port in ports:
            with pytest.raises(ValidationError) as excinfo:
                IPWithOptionalPort().clean(f"{ip}:{port}")
            assert (
                "Invalid IPv4/IPv6 address with optional port."
                == excinfo.value.message
            )


@pytest.mark.usefixtures("maasdb", "mock_openfga")
class TestMACAddressFieldLookups:
    """Format-agnostic ``startswith``/``contains`` lookups on mac_address."""

    def make_interface(self, mac_address):
        return factory.make_Interface(mac_address=mac_address)

    def test_startswith_ignores_separator_and_case(self):
        interface = self.make_interface("00:16:3e:55:60:96")
        for term in ("00:16:3E", "00-16-3e", "00163E", "0016.3e55"):
            assert [interface] == list(
                Interface.objects.filter(mac_address__startswith=term)
            ), term

    def test_startswith_does_not_match_other_prefix(self):
        self.make_interface("00:16:3e:55:60:96")
        assert [] == list(
            Interface.objects.filter(mac_address__startswith="aa:bb")
        )

    def test_contains_ignores_separator_and_case(self):
        interface = self.make_interface("00:16:3e:55:60:96")
        for term in ("3E:55", "3e-55", "3e55"):
            assert [interface] == list(
                Interface.objects.filter(mac_address__contains=term)
            ), term

    def test_contains_does_not_match_absent_fragment(self):
        self.make_interface("00:16:3e:55:60:96")
        assert [] == list(
            Interface.objects.filter(mac_address__contains="ffff")
        )

    def test_icontains_behaves_like_contains(self):
        interface = self.make_interface("00:16:3e:55:60:96")
        assert [interface] == list(
            Interface.objects.filter(mac_address__icontains="3E-55")
        )


@pytest.mark.usefixtures("maasdb", "maas_region_test")
class TestXMLField:
    def test_loads_string(self):
        name = factory.make_string()
        value = "<test/>"
        XMLFieldModel.objects.create(name=name, value=value)
        instance = XMLFieldModel.objects.get(name=name)
        assert value == instance.value

    def test_lookup_xpath_exists_result(self):
        name = factory.make_string()
        XMLFieldModel.objects.create(name=name, value="<test/>")
        result = XMLFieldModel.objects.raw(
            "SELECT * FROM docs WHERE xpath_exists(%s, value)", ["//test"]
        )
        assert name == result[0].name

    def test_lookup_xpath_exists_no_result(self):
        name = factory.make_string()
        XMLFieldModel.objects.create(name=name, value="<test/>")
        result = XMLFieldModel.objects.raw(
            "SELECT * FROM docs WHERE xpath_exists(%s, value)", ["//miss"]
        )
        assert [] == list(result)

    def test_save_non_wellformed_rejected(self):
        with pytest.raises(DatabaseError):
            XMLFieldModel.objects.create(value="<bad>")

    def test_lookup_none(self):
        XMLFieldModel.objects.create(value=None)
        test_instance = XMLFieldModel.objects.get(value__isnull=True)
        assert test_instance.value is None


@pytest.mark.usefixtures("maasdb", "maas_region_test")
class TestLargeObjectField:
    def test_stores_data(self):
        data = factory.make_bytes()
        test_name = factory.make_name("name")
        test_instance = LargeObjectFieldModel(name=test_name)
        large_object = LargeObjectFile()
        with large_object.open("wb") as stream:
            stream.write(data)
        test_instance.large_object = large_object
        test_instance.save()
        test_instance = LargeObjectFieldModel.objects.get(name=test_name)
        with test_instance.large_object.open("rb") as stream:
            saved_data = stream.read()
        assert data == saved_data

    def test_insists_on_binary_mode(self):
        message = "Large objects must be opened in binary mode."
        with pytest.raises(ValueError, match=message):
            large_object = LargeObjectFile()
            large_object.open("w")

    def test_with_exit_calls_close(self, mocker, request):
        data = factory.make_bytes()
        large_object = LargeObjectFile()
        with large_object.open("wb") as stream:
            request.addfinalizer(large_object.close)
            mock_close = mocker.patch.object(large_object, "close")
            stream.write(data)
        mock_close.assert_called_once_with()

    def test_unlink(self):
        data = factory.make_bytes()
        large_object = LargeObjectFile()
        with large_object.open("wb") as stream:
            stream.write(data)
        oid = large_object.oid
        large_object.unlink()
        with transaction.atomic():
            with pytest.raises(OperationalError):
                connection.connection.lobject(oid)
            transaction.set_rollback(True)

    def test_interates_on_block_size(self):
        # String size is multiple of block_size in the testing model
        data = factory.make_bytes(10 * 2)
        test_name = factory.make_name("name")
        test_instance = LargeObjectFieldModel(name=test_name)
        large_object = LargeObjectFile()
        with large_object.open("wb") as stream:
            stream.write(data)
        test_instance.large_object = large_object
        test_instance.save()
        test_instance = LargeObjectFieldModel.objects.get(name=test_name)
        with test_instance.large_object.open("rb") as stream:
            offset = 0
            for block in stream:
                assert data[offset : offset + 10] == block
                offset += 10

    def test_get_db_prep_value_returns_None_when_value_None(self):
        field = LargeObjectField()
        assert field.get_db_prep_value(None) is None

    def test_get_db_prep_value_returns_oid_when_value_LargeObjectFile(self):
        oid = randint(1, 100)
        field = LargeObjectField()
        obj_file = LargeObjectFile()
        obj_file.oid = oid
        assert oid == field.get_db_prep_value(obj_file)

    def test_get_db_prep_value_raises_error_when_oid_less_than_zero(self):
        oid = randint(-100, 0)
        field = LargeObjectField()
        obj_file = LargeObjectFile()
        obj_file.oid = oid
        with pytest.raises(AssertionError):
            field.get_db_prep_value(obj_file)

    def test_get_db_prep_value_raises_error_when_not_LargeObjectFile(self):
        field = LargeObjectField()
        with pytest.raises(AssertionError):
            field.get_db_prep_value(factory.make_string())

    def test_to_python_returns_None_when_value_None(self):
        field = LargeObjectField()
        assert field.to_python(None) is None

    def test_to_python_returns_value_when_value_LargeObjectFile(self):
        field = LargeObjectField()
        obj_file = LargeObjectFile()
        assert obj_file == field.to_python(obj_file)

    def test_to_python_returns_LargeObjectFile_when_value_int(self, mocker):
        oid = randint(1, 100)
        field = LargeObjectField()
        # South normally substitutes a FakeModel here, but with a baseline
        # schema, we can skip the migration that creates LargeObjectField.
        mocker.patch.object(field, "model", create=True)
        obj_file = field.to_python(oid)
        assert oid == obj_file.oid

    def test_to_python_returns_LargeObjectFile_when_value_long(self, mocker):
        oid = int(randint(1, 100))
        field = LargeObjectField()
        # South normally substitutes a FakeModel here, but with a baseline
        # schema, we can skip the migration that creates LargeObjectField.
        mocker.patch.object(field, "model", create=True)
        obj_file = field.to_python(oid)
        assert oid == obj_file.oid

    def test_to_python_raises_error_when_not_valid_type(self):
        field = LargeObjectField()
        with pytest.raises(AssertionError):
            field.to_python(factory.make_string())


@pytest.mark.usefixtures("maasdb", "maas_region_test")
class TestCIDRField:
    def test_stores_cidr(self):
        cidr = "192.0.2.0/24"
        instance = CIDRTestModel.objects.create(cidr=cidr)
        assert cidr == reload_object(instance).cidr

    def test_validates_cidr(self):
        cidr = "invalid-cidr"
        with pytest.raises(ValidationError) as error:
            CIDRTestModel.objects.create(cidr=cidr)
        assert ["invalid IPNetwork %s" % cidr] == error.value.messages

    def test_stores_cidr_with_bit_set_in_host_part(self):
        cidr = "192.0.2.1/24"
        normalized_cidr = "192.0.2.0/24"
        instance = CIDRTestModel.objects.create(cidr=cidr)
        assert normalized_cidr == reload_object(instance).cidr


@pytest.mark.usefixtures("maasdb", "maas_region_test")
class TestIPv4CIDRField:
    def test_stores_cidr(self):
        cidr = "192.0.2.0/24"
        instance = IPv4CIDRTestModel.objects.create(cidr=cidr)
        assert cidr == reload_object(instance).cidr

    def test_validates_cidr(self):
        cidr = "invalid-cidr"
        with pytest.raises(ValidationError) as error:
            IPv4CIDRTestModel.objects.create(cidr=cidr)
        assert ["Invalid network: %s" % cidr] == error.value.messages

    def test_stores_cidr_with_bit_set_in_host_part(self):
        cidr = "192.0.2.1/24"
        normalized_cidr = "192.0.2.0/24"
        instance = IPv4CIDRTestModel.objects.create(cidr=cidr)
        assert normalized_cidr == reload_object(instance).cidr

    def test_fails_to_store_ipv6_cidr(self):
        cidr = "2001:DB8::/32"
        with pytest.raises(ValidationError) as error:
            IPv4CIDRTestModel.objects.create(cidr=cidr)
        assert ["2001:DB8::/32: Only IPv4 networks supported."] == (
            error.value.messages
        )
