# Copyright 2014-2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for MAAS's cluster security module."""

from binascii import b2a_hex
from random import randint
from unittest.mock import sentinel

import pytest

from maastesting.factory import factory
from provisioningserver import security
from provisioningserver.security import (
    aesgcm_decrypt,
    aesgcm_encrypt,
    fernet_decrypt_psk,
    fernet_encrypt_psk,
    MissingSharedSecret,
)
from provisioningserver.utils import env as utils_env
from provisioningserver.utils.env import MAAS_SECRET


class TestInstallSharedSecretScript:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker, tmp_path):
        utils_env.MAAS_SHARED_SECRET.clear_cached()
        mocker.patch.object(
            utils_env.MAAS_SHARED_SECRET, "_path", lambda: tmp_path / "secret"
        )
        self._mock_print = mocker.patch.object(security, "print")

    def read_secret_from_fs(self):
        secret = utils_env.MAAS_SHARED_SECRET.get()
        return security.to_bin(secret) if secret else None

    def test_has_add_arguments(self):
        # It doesn't do anything, but it's there to fulfil the contract with
        # ActionScript/MainScript.
        security.InstallSharedSecretScript.add_arguments(sentinel.parser)

    def installAndCheckExitCode(self, code):
        with pytest.raises(SystemExit) as error:
            security.InstallSharedSecretScript.run(sentinel.args)
        assert code == error.value.code

    def test_reads_secret_from_stdin(self, mocker):
        secret = factory.make_bytes()

        stdin = mocker.patch.object(security, "stdin", autospec=True)
        stdin.readline.return_value = b2a_hex(secret).decode("ascii")
        stdin.isatty.return_value = False

        self.installAndCheckExitCode(0)
        assert self.read_secret_from_fs() == secret

    def test_ignores_surrounding_whitespace_from_stdin(self, mocker):
        secret = factory.make_bytes()

        stdin = mocker.patch.object(security, "stdin", autospec=True)
        stdin.readline.return_value = (
            " " + b2a_hex(secret).decode("ascii") + " \n"
        )
        stdin.isatty.return_value = False

        self.installAndCheckExitCode(0)
        assert self.read_secret_from_fs() == secret

    def test_reads_secret_from_tty(self, mocker):
        secret = factory.make_bytes()

        stdin = mocker.patch.object(security, "stdin", autospec=True)
        stdin.isatty.return_value = True

        input = mocker.patch.object(security, "input")
        input.return_value = b2a_hex(secret).decode("ascii")

        self.installAndCheckExitCode(0)
        input.assert_called_once_with("Secret (hex/base16 encoded): ")
        assert self.read_secret_from_fs() == secret

    def test_ignores_surrounding_whitespace_from_tty(self, mocker):
        secret = factory.make_bytes()

        stdin = mocker.patch.object(security, "stdin", autospec=True)
        stdin.isatty.return_value = True

        input = mocker.patch.object(security, "input")
        input.return_value = " " + b2a_hex(secret).decode("ascii") + " \n"

        self.installAndCheckExitCode(0)
        assert self.read_secret_from_fs() == secret

    def test_deals_gracefully_with_eof_from_tty(self, mocker):
        stdin = mocker.patch.object(security, "stdin", autospec=True)
        stdin.isatty.return_value = True

        input = mocker.patch.object(security, "input")
        input.side_effect = EOFError()

        self.installAndCheckExitCode(1)
        assert self.read_secret_from_fs() is None

    def test_deals_gracefully_with_interrupt_from_tty(self, mocker):
        stdin = mocker.patch.object(security, "stdin", autospec=True)
        stdin.isatty.return_value = True

        input = mocker.patch.object(security, "input")
        input.side_effect = KeyboardInterrupt()

        with pytest.raises(KeyboardInterrupt):
            security.InstallSharedSecretScript.run(sentinel.args)
        assert self.read_secret_from_fs() is None

    def test_prints_error_message_when_secret_cannot_be_decoded(self, mocker):
        stdin = mocker.patch.object(security, "stdin", autospec=True)
        stdin.readline.return_value = "garbage"
        stdin.isatty.return_value = False

        self.installAndCheckExitCode(1)
        self._mock_print.assert_called_once_with(
            "Secret could not be decoded:",
            "Odd-length string",
            file=security.stderr,
        )

    def test_prints_message_when_secret_is_installed(self, mocker):
        stdin = mocker.patch.object(security, "stdin", autospec=True)
        stdin.readline.return_value = b2a_hex(factory.make_bytes()).decode(
            "ascii"
        )
        stdin.isatty.return_value = False

        self.installAndCheckExitCode(0)
        self._mock_print.assert_called_once_with(
            f"Secret installed to {utils_env.MAAS_SHARED_SECRET.path}."
        )


class TestFernetEncryption:
    @pytest.fixture(autouse=True)
    def _setup(self, mocker):
        MAAS_SECRET.set(None)
        mocker.patch.object(security, "_aesgcm_key", None)
        original_iteration_count = security.DEFAULT_ITERATION_COUNT
        security.DEFAULT_ITERATION_COUNT = 2
        MAAS_SECRET.set(factory.make_bytes())
        yield
        security.DEFAULT_ITERATION_COUNT = original_iteration_count

    def test_first_encrypt_caches_key(self):
        assert security._aesgcm_key is None
        testdata = factory.make_string()
        fernet_encrypt_psk(testdata)
        assert security._aesgcm_key is not None

    def test_derives_identical_key_on_decrypt(self):
        assert security._aesgcm_key is None
        testdata = factory.make_bytes()
        token = fernet_encrypt_psk(testdata)
        first_key = security._aesgcm_key
        # Make it seem like we're decrypting something without ever encrypting
        # anything first.
        security._aesgcm_key = None
        decrypted = fernet_decrypt_psk(token)
        second_key = security._aesgcm_key
        assert first_key == second_key
        assert testdata == decrypted

    def test_can_encrypt_and_decrypt_string(self):
        testdata = factory.make_string()
        token = fernet_encrypt_psk(testdata)
        # Round-trip this to a string, since tokens are used inside
        # strings (such as JSON objects) typically.
        token = token.decode("ascii")
        decrypted = fernet_decrypt_psk(token)
        decrypted = decrypted.decode("ascii")
        assert testdata == decrypted

    def test_can_encrypt_and_decrypt_with_raw_bytes(self):
        testdata = factory.make_bytes()
        token = fernet_encrypt_psk(testdata, raw=True)
        assert isinstance(token, bytes)
        decrypted = fernet_decrypt_psk(token, raw=True)
        assert testdata == decrypted

    def test_can_encrypt_and_decrypt_bytes(self):
        testdata = factory.make_bytes()
        token = fernet_encrypt_psk(testdata)
        decrypted = fernet_decrypt_psk(token)
        assert testdata == decrypted

    def test_raises_when_no_secret_exists(self):
        MAAS_SECRET.set(None)
        testdata = factory.make_bytes()
        with pytest.raises(
            MissingSharedSecret, match="MAAS shared secret not found"
        ):
            fernet_encrypt_psk(testdata)
        with pytest.raises(
            MissingSharedSecret, match="MAAS shared secret not found"
        ):
            fernet_decrypt_psk(b"")

    def test_assures_data_integrity(self):
        testdata = factory.make_bytes(size=10)
        raw_token = fernet_encrypt_psk(testdata, raw=True)
        bad_token = bytearray(raw_token)
        # Flip a bit in the raw token (after nonce, to hit ciphertext/tag).
        byte_to_flip = randint(12, len(bad_token) - 1)
        bit_to_flip = 1 << randint(0, 7)
        bad_token[byte_to_flip] ^= bit_to_flip
        with pytest.raises(ValueError):
            fernet_decrypt_psk(bytes(bad_token), raw=True)

    def test_direct_aesgcm_round_trip(self):
        testdata = factory.make_bytes()
        token = aesgcm_encrypt(testdata)
        assert isinstance(token, bytes)
        decrypted = aesgcm_decrypt(token)
        assert testdata == decrypted

    def test_direct_aesgcm_corruption_fails(self):
        testdata = factory.make_bytes(size=10)
        token = bytearray(aesgcm_encrypt(testdata))
        byte_to_flip = randint(0, len(token) - 1)
        token[byte_to_flip] ^= 1 << randint(0, 7)
        with pytest.raises(ValueError):
            aesgcm_decrypt(bytes(token))

    def test_ttl_ignored_for_backwards_compatibility(self):
        testdata = factory.make_bytes()
        token = fernet_encrypt_psk(testdata)
        decrypted = fernet_decrypt_psk(token, ttl=1)
        assert testdata == decrypted
