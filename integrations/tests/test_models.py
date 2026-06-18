from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from integrations.models import (
    STATUS_ACTIVE,
    STATUS_DISCONNECTED,
    STATUS_PENDING_VERIFICATION,
    STATUS_RESET_REQUIRED,
    TossInvestCredential,
)


class TossInvestCredentialModelTests(TestCase):
    def create_user(self, username: str):
        return get_user_model().objects.create_user(username=username, password="unused")

    def create_credential(self, username: str, **kwargs) -> TossInvestCredential:
        defaults = {"user": self.create_user(username)}
        defaults.update(kwargs)
        return TossInvestCredential.objects.create(**defaults)

    def test_create_credential_defaults(self):
        credential = self.create_credential("user-alpha")

        self.assertEqual(credential.status, STATUS_PENDING_VERIFICATION)
        self.assertEqual(credential.provider, TossInvestCredential.PROVIDER_TOSS_INVEST)

    def test_user_one_to_one_constraint(self):
        user = self.create_user("user-alpha")
        TossInvestCredential.objects.create(user=user)

        with self.assertRaises(IntegrityError), transaction.atomic():
            TossInvestCredential.objects.create(user=user)

    def test_has_client_credentials_and_tokens_and_account(self):
        credential = self.create_credential("user-alpha")

        self.assertFalse(credential.has_client_credentials())
        self.assertFalse(credential.has_tokens())
        self.assertFalse(credential.has_account())
        self.assertFalse(credential.has_account_ref())

        credential.client_id_ciphertext = "cipher-client"
        credential.client_secret_ciphertext = "cipher-secret"
        credential.access_token_ciphertext = "cipher-access"
        credential.account_ref_ciphertext = "cipher-account-ref"
        credential.account_hash = "hash-account"

        self.assertTrue(credential.has_client_credentials())
        self.assertTrue(credential.has_tokens())
        self.assertTrue(credential.has_account())
        self.assertTrue(credential.has_account_ref())

    def test_clear_ciphertexts_clears_ciphertexts_and_key_versions(self):
        issued_at = timezone.now()
        expires_at = issued_at + timedelta(minutes=30)
        credential = self.create_credential(
            "user-alpha",
            client_id_ciphertext="cipher-client",
            client_secret_ciphertext="cipher-secret",
            access_token_ciphertext="cipher-access",
            refresh_token_ciphertext="cipher-refresh",
            account_ref_ciphertext="cipher-account-ref",
            client_id_key_version="v1",
            client_secret_key_version="v1",
            access_token_key_version="v2",
            refresh_token_key_version="v2",
            account_ref_key_version="v3",
            access_token_issued_at=issued_at,
            access_token_expires_at=expires_at,
            access_token_type="Bearer",
        )

        credential.clear_ciphertexts()

        self.assertIsNone(credential.client_id_ciphertext)
        self.assertIsNone(credential.client_secret_ciphertext)
        self.assertIsNone(credential.access_token_ciphertext)
        self.assertIsNone(credential.refresh_token_ciphertext)
        self.assertIsNone(credential.account_ref_ciphertext)
        self.assertEqual(credential.client_id_key_version, "")
        self.assertEqual(credential.client_secret_key_version, "")
        self.assertEqual(credential.access_token_key_version, "")
        self.assertEqual(credential.refresh_token_key_version, "")
        self.assertEqual(credential.account_ref_key_version, "")
        self.assertIsNone(credential.access_token_issued_at)
        self.assertIsNone(credential.access_token_expires_at)
        self.assertEqual(credential.access_token_type, "")

    def test_mark_reset_required_clears_ciphertexts_and_sets_status(self):
        credential = self.create_credential(
            "user-alpha",
            client_id_ciphertext="cipher-client",
            client_secret_ciphertext="cipher-secret",
            account_ref_ciphertext="cipher-account-ref",
            access_token_ciphertext="cipher-access",
            access_token_type="Bearer",
            access_token_expires_at=timezone.now(),
        )

        credential.mark_reset_required(error_code="invalid_client", error_summary="safe summary")

        self.assertEqual(credential.status, STATUS_RESET_REQUIRED)
        self.assertIsNone(credential.client_id_ciphertext)
        self.assertIsNone(credential.client_secret_ciphertext)
        self.assertIsNone(credential.account_ref_ciphertext)
        self.assertIsNone(credential.access_token_ciphertext)
        self.assertEqual(credential.access_token_type, "")
        self.assertIsNone(credential.access_token_expires_at)
        self.assertEqual(credential.error_code, "invalid_client")
        self.assertEqual(credential.error_summary, "safe summary")

    def test_mark_disconnected_clears_ciphertexts_and_sets_timestamp(self):
        credential = self.create_credential(
            "user-alpha",
            access_token_ciphertext="cipher-access",
            account_ref_ciphertext="cipher-account-ref",
            access_token_issued_at=timezone.now(),
            access_token_type="Bearer",
        )

        credential.mark_disconnected()

        self.assertEqual(credential.status, STATUS_DISCONNECTED)
        self.assertIsNone(credential.access_token_ciphertext)
        self.assertIsNone(credential.account_ref_ciphertext)
        self.assertIsNone(credential.access_token_issued_at)
        self.assertEqual(credential.access_token_type, "")
        self.assertIsNotNone(credential.disconnected_at)

    def test_str_and_safe_display_do_not_include_sensitive_values(self):
        credential = self.create_credential(
            "user-alpha",
            client_secret_ciphertext="cipher-secret-sensitive",
            account_ref_ciphertext="cipher-account-ref-sensitive",
            access_token_ciphertext="cipher-token-sensitive",
            refresh_token_ciphertext="cipher-refresh-sensitive",
            account_hash="dummy-account-hash",
            account_masked="acct_****1234",
            status=STATUS_ACTIVE,
        )

        rendered = str(credential)
        safe_display = str(credential.safe_display_dict())

        self.assertNotIn("cipher-secret-sensitive", rendered)
        self.assertNotIn("dummy-account-hash", rendered)
        self.assertNotIn("cipher-secret-sensitive", safe_display)
        self.assertNotIn("cipher-account-ref-sensitive", safe_display)
        self.assertNotIn("cipher-token-sensitive", safe_display)
        self.assertNotIn("cipher-refresh-sensitive", safe_display)
        self.assertNotIn("dummy-account-hash", safe_display)
        self.assertIn("acct_****1234", safe_display)
        self.assertIn("account_ref_stored", credential.safe_display_dict())

    def test_active_pending_client_fingerprint_duplicate_blocked(self):
        fp = "a" * 64
        self.create_credential("user-alpha", client_id_fingerprint=fp, status=STATUS_PENDING_VERIFICATION)

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_credential("user-beta", client_id_fingerprint=fp, status=STATUS_ACTIVE)

    def test_disconnected_client_fingerprint_duplicate_allowed(self):
        fp = "b" * 64
        self.create_credential("user-alpha", client_id_fingerprint=fp, status=STATUS_DISCONNECTED)
        credential = self.create_credential("user-beta", client_id_fingerprint=fp, status=STATUS_ACTIVE)

        self.assertEqual(credential.client_id_fingerprint, fp)

    def test_active_account_hash_duplicate_blocked(self):
        account_hash = "c" * 64
        self.create_credential("user-alpha", account_hash=account_hash, status=STATUS_ACTIVE)

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.create_credential("user-beta", account_hash=account_hash, status=STATUS_ACTIVE)

    def test_inactive_account_hash_duplicate_allowed(self):
        account_hash = "d" * 64
        self.create_credential("user-alpha", account_hash=account_hash, status=STATUS_RESET_REQUIRED)
        self.create_credential("user-beta", account_hash=account_hash, status=STATUS_DISCONNECTED)
        credential = self.create_credential("user-gamma", account_hash=account_hash, status=STATUS_ACTIVE)

        self.assertEqual(credential.account_hash, account_hash)

    def test_invalid_status_fails_validation(self):
        credential = TossInvestCredential(user=self.create_user("user-alpha"), status="invalid")

        with self.assertRaises(ValidationError):
            credential.full_clean()
