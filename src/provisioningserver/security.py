# Copyright 2014-2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from base64 import urlsafe_b64decode, urlsafe_b64encode
import binascii
from binascii import a2b_hex, b2a_hex
from hashlib import sha256
from hmac import HMAC
import os
from sys import stderr, stdin
from threading import Lock

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import dsa, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from OpenSSL import crypto
import structlog

from maascommon.fips import is_fips_enabled
from maascommon.logging.security import FIPS_CRYPTO_ERROR
from provisioningserver.utils.env import MAAS_SECRET, MAAS_SHARED_SECRET

logger = structlog.getLogger()


class MissingSharedSecret(RuntimeError):
    """Raised when the MAAS shared secret is missing."""


class FIPSCryptoError(Exception):
    """Raised when a cryptographic operation violates FIPS policy."""


def _raise_fips_crypto_error(
    *, operation: str, algorithm: str, reason: str
) -> None:
    logger.error(
        FIPS_CRYPTO_ERROR,
        operation=operation,
        algorithm=algorithm,
        reason=reason,
    )
    raise FIPSCryptoError(reason)


def validate_key_fips_compliance(key: object) -> None:
    """Validate that a key complies with FIPS policy."""
    if not is_fips_enabled():
        return

    if isinstance(key, (dsa.DSAPrivateKey, dsa.DSAPublicKey)):
        _raise_fips_crypto_error(
            operation="key_validation",
            algorithm="DSA",
            reason="DSA keys are not permitted in FIPS mode",
        )

    if isinstance(key, (rsa.RSAPrivateKey, rsa.RSAPublicKey)):
        if key.key_size < 2048:
            _raise_fips_crypto_error(
                operation="key_validation",
                algorithm=f"RSA-{key.key_size}",
                reason=("RSA key size below FIPS minimum of 2048 bits"),
            )
        return

    if isinstance(key, crypto.PKey):
        if key.type() == crypto.TYPE_DSA:
            _raise_fips_crypto_error(
                operation="key_validation",
                algorithm="DSA",
                reason="DSA keys are not permitted in FIPS mode",
            )
        if key.type() == crypto.TYPE_RSA and key.bits() < 2048:
            _raise_fips_crypto_error(
                operation="key_validation",
                algorithm=f"RSA-{key.bits()}",
                reason=("RSA key size below FIPS minimum of 2048 bits"),
            )
        return

    get_name = getattr(key, "get_name", None)
    get_bits = getattr(key, "get_bits", None)
    if callable(get_name):
        key_name = str(get_name()).lower()
        if key_name == "ssh-dss":
            _raise_fips_crypto_error(
                operation="key_validation",
                algorithm="DSA",
                reason="DSA keys are not permitted in FIPS mode",
            )
        if "rsa" in key_name and callable(get_bits):
            key_bits = int(get_bits())
            if key_bits < 2048:
                _raise_fips_crypto_error(
                    operation="key_validation",
                    algorithm=f"RSA-{key_bits}",
                    reason=("RSA key size below FIPS minimum of 2048 bits"),
                )


def generate_ssh_key(
    key_type: str,
    bits: int | None = None,
) -> object:
    """Generate an SSH key pair enforcing FIPS 140-2/140-3 restrictions when FIPS mode is active.

    Rejects DSA and ed25519 in FIPS mode.  RSA keys < 2048 bits are also
    rejected.  On non-FIPS hosts the function performs best-effort generation
    with no size restrictions.
    """
    from cryptography.hazmat.primitives.asymmetric import ec

    key_type_lower = key_type.lower()

    if is_fips_enabled():
        if key_type_lower in ("dsa", "ed25519"):
            _raise_fips_crypto_error(
                operation="ssh_key_generation",
                algorithm=key_type_lower.upper(),
                reason=f"{key_type_lower.upper()} key generation is not permitted in FIPS mode",
            )
        if key_type_lower == "rsa":
            effective_bits = bits if bits is not None else 4096
            if effective_bits < 2048:
                _raise_fips_crypto_error(
                    operation="ssh_key_generation",
                    algorithm=f"RSA-{effective_bits}",
                    reason=(
                        f"RSA key size {effective_bits} bits is below the "
                        "FIPS minimum of 2048 bits"
                    ),
                )

    if key_type_lower == "rsa":
        effective_bits = bits if bits is not None else 4096
        return rsa.generate_private_key(
            public_exponent=65537,
            key_size=effective_bits,
        )
    elif key_type_lower == "ecdsa":
        return ec.generate_private_key(ec.SECP256R1())
    elif key_type_lower == "dsa":
        return dsa.generate_parameters(key_size=2048).generate_private_key()
    elif key_type_lower == "ed25519":
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
        )

        return Ed25519PrivateKey.generate()
    else:
        raise ValueError(
            f"Unsupported SSH key type: {key_type!r}. "
            "Expected one of 'rsa', 'ecdsa', 'dsa', 'ed25519'."
        )


def to_hex(b: bytes) -> str:
    """Convert byte string to hex encoding."""
    assert isinstance(b, bytes), f"{b!r} is not a byte string"
    return b2a_hex(b).decode("ascii")


def to_bin(u: str) -> bytes:
    """Convert ASCII-only unicode string to hex encoding."""
    assert isinstance(u, str), f"{u!r} is not a unicode string"
    # Strip ASCII whitespace from u before converting.
    return a2b_hex(u.encode("ascii").strip())


def calculate_digest(secret, message, salt):
    """Calculate a SHA-256 HMAC digest for the given data."""
    assert isinstance(secret, bytes), f"{secret!r} is not a byte string."
    assert isinstance(message, bytes), f"{message!r} is not byte string."
    assert isinstance(salt, bytes), f"{salt!r} is not a byte string."
    hmacr = HMAC(secret, digestmod=sha256)
    hmacr.update(message)
    hmacr.update(salt)
    return hmacr.digest()


# Cache the AES-256-GCM pre-shared key, since it's expensive to derive.
# Note: this will need to change to become a dictionary if salts are supported.
_aes_psk = None
_aes_lock = Lock()

# Warning: this should not generally be changed; a MAAS server will not be able
# to communicate with any peers using this value unless it matches. This value
# should be set relatively high, in order to make a brute-force attack to
# determine the MAAS secret impractical.
DEFAULT_ITERATION_COUNT = 100000


def _get_or_create_aes_psk() -> bytes:
    """Get or create the AES-256-GCM pre-shared key.

    The key is cached globally and derived from the MAAS secret using PBKDF2.
    """
    with _aes_lock:
        global _aes_psk
        if _aes_psk is None:
            secret = MAAS_SECRET.get()
            if secret is None:
                raise MissingSharedSecret("MAAS shared secret not found.")
            # Keying material is required by PBKDF2 to be a byte string.
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                # XXX: It might be better to use the maas_id for the salt.
                # But that requires the maas_id to be known in advance by all
                # parties to the encrypted communication. The format of the
                # cached pre-shared key would also need to change.
                salt=b"",
                # XXX: an infrequently-changing variable iteration count might
                # be nice, but that would require protocol support, and
                # changing the way the PSK is cached.
                iterations=DEFAULT_ITERATION_COUNT,
                backend=default_backend(),
            )
            key = kdf.derive(secret)
            _aes_psk = key
        else:
            key = _aes_psk
    return key


def _get_aesgcm_context() -> AESGCM:
    """Return an AESGCM instance based on the MAAS secret."""
    key = _get_or_create_aes_psk()
    return AESGCM(key)


def encrypt_psk(message, raw=False):
    """Encrypt the specified message using AES-256-GCM.

    Returns the encrypted token as a byte string.
    Output format: nonce (12 bytes) || ciphertext || tag (16 bytes),
    all base64-encoded.
    """
    aesgcm = _get_aesgcm_context()
    if isinstance(message, str):
        message = message.encode("utf-8")
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, message, None)
    token = urlsafe_b64encode(nonce + ciphertext)
    if raw is True:
        token = urlsafe_b64decode(token)
    return token


def _is_fernet_token(token_bytes: bytes) -> bool:
    """Check if the token appears to be a Fernet token.

    Fernet tokens always start with version byte 0x80, which when
    base64-encoded produces a string starting with 'gAAAAA'.
    """
    try:
        decoded = urlsafe_b64decode(token_bytes)
    except Exception:
        return False
    return len(decoded) > 0 and decoded[0] == 0x80


def _fernet_decrypt(token: bytes) -> bytes:
    """Decrypt a legacy Fernet token.

    This is used only for backward compatibility during migration.
    """
    from cryptography.fernet import Fernet

    key = _get_or_create_aes_psk()
    fernet_key = urlsafe_b64encode(key)
    fernet = Fernet(fernet_key)
    return fernet.decrypt(token)


def decrypt_psk(token, ttl=None, raw=False):
    """Decrypt the specified token using AES-256-GCM.

    For backward compatibility, legacy Fernet tokens (detected by the 'gAAAAA'
    base64 prefix) are automatically decrypted using the legacy Fernet
    algorithm.
    """
    if ttl is not None:
        logger.warning(
            "TTL parameter is ignored in AES-256-GCM decryption. "
            "TTL enforcement is not implemented for backward compatibility."
        )
    if raw is True:
        token = urlsafe_b64encode(token)
    if isinstance(token, str):
        token = token.encode("ascii")
    # Detect legacy Fernet tokens and decrypt accordingly.
    if _is_fernet_token(token):
        return _fernet_decrypt(token)
    # Decrypt with AES-256-GCM.
    aesgcm = _get_aesgcm_context()
    raw_token = urlsafe_b64decode(token)
    if len(raw_token) < 28:  # 12 (nonce) + 16 (tag) minimum
        raise ValueError("Token too short to be valid AES-256-GCM")
    nonce = raw_token[:12]
    ciphertext = raw_token[12:]
    return aesgcm.decrypt(nonce, ciphertext, None)


class InstallSharedSecretScript:
    """Install a shared-secret onto a cluster.

    This class conforms to the contract that :py:func:`MainScript.register`
    requires.
    """

    @staticmethod
    def add_arguments(parser):
        """Initialise options for storing a shared-secret.

        :param parser: An instance of :class:`ArgumentParser`.
        """

    @staticmethod
    def run(args):
        """Install a shared-secret to this cluster.

        When invoked interactively, you'll be prompted to enter the secret.
        Otherwise the secret will be read from the first line of stdin.

        In both cases, the secret must be hex/base16 encoded.
        """
        # Obtain the secret from the invoker.
        if stdin.isatty():
            try:
                secret_hex = input("Secret (hex/base16 encoded): ")
            except EOFError:
                print()  # So that the shell prompt appears on the next line.
                raise SystemExit(1)  # noqa: B904
            except KeyboardInterrupt:
                print()  # So that the shell prompt appears on the next line.
                raise
        else:
            secret_hex = stdin.readline()
        # Decode and install the secret.
        try:
            to_bin(secret_hex.strip())
        except binascii.Error as error:
            print("Secret could not be decoded:", str(error), file=stderr)
            raise SystemExit(1)  # noqa: B904
        else:
            MAAS_SHARED_SECRET.set(secret_hex)
            print(f"Secret installed to {MAAS_SHARED_SECRET.path}.")
            raise SystemExit(0)
