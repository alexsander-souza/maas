# Copyright 2020-2026 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509 import (
    CertificateBuilder,
    Name,
    NameAttribute,
    random_serial_number,
)
from cryptography.x509.oid import NameOID
from OpenSSL import crypto
import pytest

from maastesting.factory import factory
from provisioningserver.certificates import (
    Certificate,
    CertificateError,
    CertificateRequest,
    get_maas_cert_tuple,
    get_maas_cluster_cert_paths,
    store_maas_cluster_cert_tuple,
)
from provisioningserver.testing.certificates import get_sample_cert


class TestCertificateRequest:
    def test_certificate_request(self):
        request = CertificateRequest.generate(
            "maas", "organization", "organization_unit", 2048, b"DNS:*"
        )
        assert isinstance(request.csr, crypto.X509Req)
        assert isinstance(request.key, crypto.PKey)

        assert request.csr.get_subject().CN == "maas"
        assert request.csr.get_subject().O == "organization"
        assert request.csr.get_subject().OU == "organization_unit"

        assert len(request.csr.get_extensions()) == 1
        subject_alt_name_extension = request.csr.get_extensions()[0]
        assert subject_alt_name_extension.get_short_name() == b"subjectAltName"
        assert not subject_alt_name_extension.get_critical()


class TestCertificate:
    @pytest.fixture(autouse=True)
    def _setup(self):
        self.sample_cert = get_sample_cert()

    def test_certificate(self):
        assert self.sample_cert.cn() == "maas"
        assert (
            datetime.now(timezone.utc) + timedelta(days=3650)
            >= self.sample_cert.expiration()
        )
        assert self.sample_cert.certificate_pem().startswith(
            "-----BEGIN CERTIFICATE-----"
        )
        assert self.sample_cert.public_key_pem().startswith(
            "-----BEGIN PUBLIC KEY-----"
        )
        assert self.sample_cert.private_key_pem().startswith(
            "-----BEGIN PRIVATE KEY-----"
        )
        assert self.sample_cert.ca_certificates_pem() == ""
        assert (
            self.sample_cert.certificate_pem()
            == self.sample_cert.fullchain_pem()
        )

    def test_from_pem_single_material(self):
        cert = Certificate.from_pem(
            self.sample_cert.certificate_pem()
            + self.sample_cert.private_key_pem()
        )
        assert self.sample_cert.certificate_pem() == cert.certificate_pem()
        assert self.sample_cert.private_key_pem() == cert.private_key_pem()

    def test_from_pem_multiple_material(self):
        cert = Certificate.from_pem(
            self.sample_cert.certificate_pem(),
            self.sample_cert.private_key_pem(),
        )
        assert self.sample_cert.certificate_pem() == cert.certificate_pem()
        assert self.sample_cert.private_key_pem() == cert.private_key_pem()

    def test_from_pem_multiple_material_adds_newlines(self):
        # material entries are joined with a newline since each PEM material
        # must start on a new line to be valid
        cert = Certificate.from_pem(
            self.sample_cert.certificate_pem().strip(),
            self.sample_cert.private_key_pem().strip(),
        )
        assert self.sample_cert.certificate_pem() == cert.certificate_pem()
        assert self.sample_cert.private_key_pem() == cert.private_key_pem()

    def test_from_pem_invalid_material(self):
        with pytest.raises(CertificateError, match="Invalid PEM material"):
            Certificate.from_pem("random stuff")

    def test_from_pem_private_key_with_passphrase(self):
        encrypted_privatekey_pem = crypto.dump_privatekey(
            crypto.FILETYPE_PEM,
            self.sample_cert.key,
            cipher="AES128",
            passphrase=b"sekret",
        ).decode("ascii")
        with pytest.raises(
            CertificateError, match="Private key can't have a passphrase"
        ):
            Certificate.from_pem(
                self.sample_cert.certificate_pem(),
                encrypted_privatekey_pem,
            )

    def test_from_pem_no_key(self):
        with pytest.raises(CertificateError, match="Invalid PEM material"):
            Certificate.from_pem(self.sample_cert.certificate_pem())

    def test_from_pem_check_keys_match(self):
        cert = Certificate.generate("maas")
        material = self.sample_cert.certificate_pem() + cert.private_key_pem()
        with pytest.raises(
            CertificateError, match="Private and public keys don't match"
        ):
            Certificate.from_pem(material)

    def test_check_key_match_uses_cryptography_api(self):
        """Test that _check_key_match properly uses the cryptography library."""
        cert = Certificate.generate("maas")
        # This should succeed without raising an exception
        Certificate._check_key_match(cert.key, cert.cert)

    def test_check_key_match_raises_on_mismatch(self):
        """Test that _check_key_match raises CertificateError on key mismatch."""
        cert1 = Certificate.generate("maas1")
        cert2 = Certificate.generate("maas2")

        with pytest.raises(
            CertificateError, match="Private and public keys don't match"
        ):
            Certificate._check_key_match(cert1.key, cert2.cert)

    def test_check_key_match_with_different_key_sizes(self):
        """Test key matching works with different RSA key sizes."""
        cert_2048 = Certificate.generate("maas", key_bits=2048)
        cert_4096 = Certificate.generate("maas", key_bits=4096)

        # Same cert and key should work
        Certificate._check_key_match(cert_2048.key, cert_2048.cert)
        Certificate._check_key_match(cert_4096.key, cert_4096.cert)

        # Mismatched should fail
        with pytest.raises(
            CertificateError, match="Private and public keys don't match"
        ):
            Certificate._check_key_match(cert_2048.key, cert_4096.cert)

    def _generate_ec_certificate_pem(self) -> tuple[str, str]:
        key = ec.generate_private_key(ec.SECP256R1())
        name = Name([NameAttribute(NameOID.COMMON_NAME, "maas")])
        now = datetime.now(timezone.utc)
        cert = (
            CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + timedelta(days=1))
            .sign(key, hashes.SHA256())
        )
        return (
            cert.public_bytes(serialization.Encoding.PEM).decode("ascii"),
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode("ascii"),
        )

    def test_from_pem_ec_key(self):
        cert_pem, key_pem = self._generate_ec_certificate_pem()
        cert = Certificate.from_pem(cert_pem, key_pem)
        assert cert.certificate_pem() == cert_pem

    def test_from_pem_ec_key_mismatch(self):
        cert_pem, _ = self._generate_ec_certificate_pem()
        _, other_key_pem = self._generate_ec_certificate_pem()
        with pytest.raises(
            CertificateError, match="Private and public keys don't match"
        ):
            Certificate.from_pem(cert_pem, other_key_pem)

    def test_from_pem_ca_certs(self):
        other_cert = Certificate.generate("maas")
        other_cert_pem = other_cert.certificate_pem()
        cert = Certificate.from_pem(
            self.sample_cert.certificate_pem().strip(),
            self.sample_cert.private_key_pem().strip(),
            ca_certs_material=other_cert_pem,
        )
        assert cert.ca_certificates_pem() == other_cert_pem
        assert cert.fullchain_pem() == cert.certificate_pem() + other_cert_pem

    def test_tempfiles(self):
        cert_file, key_file = self.sample_cert.tempfiles()
        assert (
            Path(cert_file).read_text() == self.sample_cert.certificate_pem()
        )
        assert Path(key_file).read_text() == self.sample_cert.private_key_pem()

    def test_generate_certificate_defaults(self):
        cert = Certificate.generate("maas")
        assert isinstance(cert.cert, crypto.X509)
        assert isinstance(cert.key, crypto.PKey)
        assert cert.cert.get_subject().CN == "maas"
        assert cert.cert.get_issuer().organizationName is None
        assert cert.cert.get_issuer().organizationalUnitName is None
        assert crypto.dump_publickey(
            crypto.FILETYPE_PEM, cert.cert.get_pubkey()
        ) == crypto.dump_publickey(crypto.FILETYPE_PEM, cert.key)
        assert cert.key.bits() == 4096
        assert cert.key.type() == crypto.TYPE_RSA
        assert (
            datetime.now(timezone.utc) + timedelta(days=3650)
            >= cert.expiration()
        )

    def test_generate_certificate_key_bits(self):
        cert = Certificate.generate("maas", key_bits=1024)
        assert cert.key.bits() == 1024

    def test_generate_certificate_validity(self):
        cert = Certificate.generate("maas", validity=timedelta(days=100))
        assert (
            datetime.now(timezone.utc) + timedelta(days=100)
            >= cert.expiration()
        )

    def test_generate_certificate_organization(self):
        cert = Certificate.generate(
            "maas",
            organization_name="myorg",
            organizational_unit_name="myunit",
        )
        assert cert.cert.get_issuer().organizationName == "myorg"
        assert cert.cert.get_issuer().organizationalUnitName == "myunit"

    def test_generate_truncate_fields(self):
        cn = factory.make_string(size=65)
        o = factory.make_string(size=65)
        ou = factory.make_string(size=65)
        cert = Certificate.generate(
            cn, organization_name=o, organizational_unit_name=ou
        )
        # max fields length is 64, so the last char is truncated
        assert cert.cn() == cn[:-1]
        assert cert.o() == o[:-1]
        assert cert.ou() == ou[:-1]

    def test_generate_certificate_not_before(self):
        cert = Certificate.generate("maas", validity=timedelta(days=100))
        assert (
            datetime.now(timezone.utc) + timedelta(days=-1)
            <= cert.not_before()
        )
        assert cert.expiration() > cert.not_before()

    def test_generate_ca_certificate(self):
        cert = Certificate.generate_ca_certificate(
            "maas",
            organization_name="test",
            organizational_unit_name="unit",
            validity=timedelta(days=100),
        )

        assert isinstance(cert.cert, crypto.X509)
        assert isinstance(cert.key, crypto.PKey)
        assert cert.cert.get_subject().CN == "maas"
        assert crypto.dump_publickey(
            crypto.FILETYPE_PEM, cert.cert.get_pubkey()
        ) == crypto.dump_publickey(crypto.FILETYPE_PEM, cert.key)
        assert cert.key.bits() == 4096
        assert cert.key.type() == crypto.TYPE_RSA
        assert (
            datetime.now(timezone.utc) + timedelta(days=-1)
            <= cert.not_before()
        )
        assert cert.expiration() > cert.not_before()

        x509certificate = cert.cert
        assert x509certificate.get_issuer() == x509certificate.get_subject()
        assert x509certificate.get_version() == crypto.x509.Version.v3.value
        assert x509certificate.get_extension_count() == 1

        # Extensions are kept in order
        basic_constraints_extension = x509certificate.get_extension(0)
        assert (
            basic_constraints_extension.get_short_name() == b"basicConstraints"
        )
        assert basic_constraints_extension.get_critical()

    def test_sign_certificate(self):
        certificate_request = CertificateRequest.generate(
            "maas", "organization", "organization_unit", 2048, b"DNS:*"
        )
        ca = Certificate.generate_ca_certificate(
            "maas",
            organization_name="test",
            organizational_unit_name="unit",
            validity=timedelta(days=100),
        )

        signed_certificate = ca.sign_certificate_request(certificate_request)

        assert isinstance(signed_certificate.cert, crypto.X509)
        assert isinstance(signed_certificate.key, crypto.PKey)
        assert len(signed_certificate.ca_certs) == 1
        assert signed_certificate.cert.get_subject().CN == "maas"
        assert signed_certificate.key == certificate_request.key
        assert (
            datetime.now(timezone.utc) + timedelta(days=-1)
            <= signed_certificate.not_before()
        )
        assert (
            signed_certificate.expiration() > signed_certificate.not_before()
        )
        assert (
            len(certificate_request.csr.get_extensions())
            == signed_certificate.cert.get_extension_count()
        )
        assert (
            certificate_request.csr.get_extensions()[0].get_short_name()
            == signed_certificate.cert.get_extension(0).get_short_name()
        )
        assert signed_certificate.cert.get_issuer() == ca.cert.get_subject()

        # check that the signed certificate is valid
        store = crypto.X509Store()
        store.add_cert(ca.cert)
        context = crypto.X509StoreContext(store, signed_certificate.cert)
        try:
            context.verify_certificate()
        except crypto.X509StoreContextError:
            pytest.fail("Failed to verify the signed certificate.")


class TestClusterCertificates:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.tempdir = tmp_path
        self.monkeypatch = monkeypatch

    def test_get_maas_cluster_cert_paths(self):
        self.monkeypatch.setenv("MAAS_ROOT", str(self.tempdir))
        (self.tempdir / "certificates").mkdir(parents=True)
        assert get_maas_cluster_cert_paths() is None

    def test_get_maas_cluster_cert(self):
        self.monkeypatch.setenv("MAAS_ROOT", str(self.tempdir))

        certs_dir = self.tempdir / "certificates"
        certs_dir.mkdir(parents=True)
        (certs_dir / "cluster.pem").touch()
        (certs_dir / "cluster.key").touch()
        (certs_dir / "cacerts.pem").touch()
        assert get_maas_cluster_cert_paths() == (
            f"{certs_dir}/cluster.pem",
            f"{certs_dir}/cluster.key",
            f"{certs_dir}/cacerts.pem",
        )

    def test_store_maas_cluster_cert_tuple(self):
        certs_dir = self.tempdir / "certificates"
        certs_dir.mkdir(parents=True)
        self.monkeypatch.setenv("MAAS_ROOT", str(self.tempdir))
        store_maas_cluster_cert_tuple(
            b"private_key", b"certificate", b"cacerts"
        )
        (
            certificate_path,
            private_key_path,
            cacerts_path,
        ) = get_maas_cluster_cert_paths()
        assert Path(certificate_path).lstat().st_mode & 0o777 == 0o644
        assert Path(private_key_path).lstat().st_mode & 0o777 == 0o600
        assert Path(cacerts_path).lstat().st_mode & 0o777 == 0o644


class TestGetMAASCertTuple:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        self.tempdir = tmp_path
        self.monkeypatch = monkeypatch

    def test_get_maas_cert_tuple_missing_files(self):
        self.monkeypatch.setenv("SNAP_COMMON", str(self.tempdir))
        self.monkeypatch.setenv("SNAP", "/snap/maas/current")
        assert get_maas_cert_tuple() is None

    def test_get_maas_cert_tuple(self):
        certs_dir = self.tempdir / "certificates"
        certs_dir.mkdir(parents=True)
        (certs_dir / "maas.crt").touch()
        (certs_dir / "maas.key").touch()
        self.monkeypatch.setenv("SNAP_COMMON", str(self.tempdir))
        self.monkeypatch.setenv("SNAP", "/snap/maas/current")
        assert get_maas_cert_tuple() == (
            f"{certs_dir}/maas.crt",
            f"{certs_dir}/maas.key",
        )
