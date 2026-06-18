from django.test import SimpleTestCase, override_settings

from integrations.services.credential_crypto import CredentialCryptoConfigurationError
from integrations.services.fingerprints import (
    make_account_hash,
    make_client_id_fingerprint,
    make_fingerprint,
    make_user_ref_hash,
)


class FingerprintTests(SimpleTestCase):
    @override_settings(CREDENTIAL_HASH_PEPPER="pepper-one")
    def test_same_namespace_value_and_pepper_return_same_fingerprint(self):
        first = make_fingerprint(" value ", namespace="generic")
        second = make_fingerprint("value", namespace="generic")

        self.assertEqual(first, second)

    @override_settings(CREDENTIAL_HASH_PEPPER="pepper-one")
    def test_different_namespace_returns_different_fingerprint(self):
        first = make_fingerprint("same-value", namespace="client_id")
        second = make_fingerprint("same-value", namespace="external_user")

        self.assertNotEqual(first, second)

    def test_different_pepper_returns_different_fingerprint(self):
        with override_settings(CREDENTIAL_HASH_PEPPER="pepper-one"):
            first = make_client_id_fingerprint("ClientABC")
        with override_settings(CREDENTIAL_HASH_PEPPER="pepper-two"):
            second = make_client_id_fingerprint("ClientABC")

        self.assertNotEqual(first, second)

    @override_settings(CREDENTIAL_HASH_PEPPER="pepper-one")
    def test_client_id_strip_but_not_lowercase(self):
        mixed = make_client_id_fingerprint(" ClientABC ")
        lower = make_client_id_fingerprint("clientabc")

        self.assertNotEqual(mixed, lower)
        self.assertEqual(mixed, make_client_id_fingerprint("ClientABC"))

    @override_settings(CREDENTIAL_HASH_PEPPER="pepper-one")
    def test_account_hash_normalizes_space_and_hyphen(self):
        first = make_account_hash("ACCT-12 34")
        second = make_account_hash("ACCT1234")

        self.assertEqual(first, second)

    @override_settings(CREDENTIAL_HASH_PEPPER="pepper-one")
    def test_empty_value_raises_value_error(self):
        with self.assertRaises(ValueError):
            make_client_id_fingerprint(" ")

    @override_settings(CREDENTIAL_HASH_PEPPER="")
    def test_missing_pepper_raises_configuration_error(self):
        with self.assertRaises(CredentialCryptoConfigurationError):
            make_client_id_fingerprint("ClientABC")

    @override_settings(CREDENTIAL_HASH_PEPPER="pepper-one")
    def test_fingerprint_does_not_include_raw_value(self):
        raw_value = "ClientABC"
        fingerprint = make_client_id_fingerprint(raw_value)

        self.assertNotIn(raw_value, fingerprint)
        self.assertEqual(len(fingerprint), 64)

    @override_settings(CREDENTIAL_HASH_PEPPER="pepper-one")
    def test_user_ref_hash_accepts_int(self):
        self.assertEqual(make_user_ref_hash(123), make_user_ref_hash("123"))
