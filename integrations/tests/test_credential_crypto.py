from cryptography.fernet import Fernet
from django.test import SimpleTestCase, override_settings

from integrations.services.credential_crypto import (
    CredentialCryptoConfigurationError,
    CredentialDecryptionError,
    decrypt_text,
    encrypt_text,
    get_current_key_version,
    is_encryption_configured,
)


class CredentialCryptoTests(SimpleTestCase):
    def _key(self) -> str:
        return Fernet.generate_key().decode("ascii")

    def test_encrypt_and_decrypt_with_single_key(self):
        key = self._key()
        plaintext = "dummy-client-value"

        with override_settings(
            CREDENTIAL_ENCRYPTION_KEY=key,
            CREDENTIAL_ENCRYPTION_KEY_VERSION="v1",
            CREDENTIAL_ENCRYPTION_KEYS="",
            CREDENTIAL_ENCRYPTION_CURRENT_VERSION="",
        ):
            encrypted = encrypt_text(plaintext)

            self.assertEqual(encrypted.key_version, "v1")
            self.assertNotEqual(encrypted.ciphertext, plaintext)
            self.assertEqual(decrypt_text(encrypted.ciphertext, encrypted.key_version), plaintext)
            self.assertTrue(is_encryption_configured())
            self.assertEqual(get_current_key_version(), "v1")

    @override_settings(
        CREDENTIAL_ENCRYPTION_KEY="",
        CREDENTIAL_ENCRYPTION_KEYS="",
        CREDENTIAL_ENCRYPTION_CURRENT_VERSION="",
    )
    def test_missing_key_raises_configuration_error(self):
        with self.assertRaises(CredentialCryptoConfigurationError):
            encrypt_text("dummy")
        self.assertFalse(is_encryption_configured())

    @override_settings(
        CREDENTIAL_ENCRYPTION_KEY="not-a-fernet-key",
        CREDENTIAL_ENCRYPTION_KEYS="",
        CREDENTIAL_ENCRYPTION_CURRENT_VERSION="",
    )
    def test_invalid_key_raises_configuration_error(self):
        with self.assertRaises(CredentialCryptoConfigurationError):
            encrypt_text("dummy")

    def test_invalid_ciphertext_raises_decryption_error_without_plaintext(self):
        key = self._key()
        plaintext = "dummy-sensitive-value"

        with override_settings(CREDENTIAL_ENCRYPTION_KEY=key, CREDENTIAL_ENCRYPTION_KEYS=""):
            with self.assertRaises(CredentialDecryptionError) as ctx:
                decrypt_text("not-valid-ciphertext")

        self.assertNotIn(plaintext, str(ctx.exception))

    def test_key_ring_dict_decrypts_old_key_and_encrypts_current_key(self):
        old_key = self._key()
        current_key = self._key()

        with override_settings(
            CREDENTIAL_ENCRYPTION_KEYS={"v1": old_key, "v2": current_key},
            CREDENTIAL_ENCRYPTION_CURRENT_VERSION="v1",
            CREDENTIAL_ENCRYPTION_KEY="",
        ):
            old_encrypted = encrypt_text("old-value")

        with override_settings(
            CREDENTIAL_ENCRYPTION_KEYS={"v1": old_key, "v2": current_key},
            CREDENTIAL_ENCRYPTION_CURRENT_VERSION="v2",
            CREDENTIAL_ENCRYPTION_KEY="",
        ):
            self.assertEqual(decrypt_text(old_encrypted.ciphertext, old_encrypted.key_version), "old-value")
            new_encrypted = encrypt_text("new-value")
            self.assertEqual(new_encrypted.key_version, "v2")

    def test_key_ring_string_mode(self):
        old_key = self._key()
        current_key = self._key()

        with override_settings(
            CREDENTIAL_ENCRYPTION_KEYS=f"v1:{old_key},v2:{current_key}",
            CREDENTIAL_ENCRYPTION_CURRENT_VERSION="v2",
            CREDENTIAL_ENCRYPTION_KEY="",
        ):
            encrypted = encrypt_text("dummy-value")
            self.assertEqual(encrypted.key_version, "v2")
            self.assertEqual(decrypt_text(encrypted.ciphertext), "dummy-value")

    def test_none_inputs_raise_type_error(self):
        key = self._key()

        with override_settings(CREDENTIAL_ENCRYPTION_KEY=key, CREDENTIAL_ENCRYPTION_KEYS=""):
            with self.assertRaises(TypeError):
                encrypt_text(None)  # type: ignore[arg-type]
            with self.assertRaises(TypeError):
                decrypt_text(None)  # type: ignore[arg-type]

    def test_empty_plaintext_allowed_but_empty_ciphertext_rejected(self):
        key = self._key()

        with override_settings(CREDENTIAL_ENCRYPTION_KEY=key, CREDENTIAL_ENCRYPTION_KEYS=""):
            encrypted = encrypt_text("")
            self.assertEqual(decrypt_text(encrypted.ciphertext), "")
            with self.assertRaises(CredentialDecryptionError):
                decrypt_text("")
