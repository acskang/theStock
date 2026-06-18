from unittest.mock import patch
from datetime import timedelta

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from integrations.models import (
    STATUS_ACTIVE,
    STATUS_DISCONNECTED,
    STATUS_ERROR,
    STATUS_PENDING_VERIFICATION,
    STATUS_RESET_REQUIRED,
    STATUS_REVOKED,
    IntegrationAuditLog,
    TossInvestCredential,
)
from integrations.services.credential_lifecycle import (
    VERIFICATION_FAILURE_AUTH,
    VERIFICATION_FAILURE_REVOKED,
    VERIFICATION_FAILURE_TRANSIENT,
    CredentialDuplicateError,
    CredentialRevealError,
    disconnect_credential,
    get_credential_safe_status,
    mark_credential_verification_failure,
    mark_credential_verification_success,
    register_or_replace_pending_credential,
    reset_credential,
    reveal_client_credentials,
)
from integrations.services.credential_crypto import CredentialCryptoConfigurationError, encrypt_text
from integrations.services.fingerprints import make_account_hash, make_client_id_fingerprint


def lifecycle_settings():
    return override_settings(
        CREDENTIAL_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii"),
        CREDENTIAL_ENCRYPTION_KEY_VERSION="v1",
        CREDENTIAL_ENCRYPTION_KEYS="",
        CREDENTIAL_ENCRYPTION_CURRENT_VERSION="",
        CREDENTIAL_HASH_PEPPER="dummy-pepper-for-tests",
        CREDENTIAL_REVEAL_TIMEOUT_SECONDS=300,
    )


class CredentialLifecycleTests(TestCase):
    def create_user(self, username: str, *, password: str = "safe-password"):
        return get_user_model().objects.create_user(username=username, password=password)

    @lifecycle_settings()
    def test_register_creates_pending_encrypted_credential_and_audit(self):
        user = self.create_user("user-alpha")

        credential = register_or_replace_pending_credential(
            user=user,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
            scopes=["read"],
        )

        self.assertEqual(credential.status, STATUS_PENDING_VERIFICATION)
        self.assertNotEqual(credential.client_id_ciphertext, "dummy-client-alpha")
        self.assertNotEqual(credential.client_secret_ciphertext, "dummy-secret-alpha")
        self.assertEqual(credential.client_id_key_version, "v1")
        self.assertEqual(credential.client_secret_key_version, "v1")
        self.assertTrue(credential.client_id_fingerprint)
        self.assertIsNone(credential.access_token_ciphertext)
        self.assertIsNone(credential.refresh_token_ciphertext)
        self.assertIsNone(credential.account_ref_ciphertext)
        self.assertEqual(credential.account_ref_key_version, "")
        self.assertIsNone(credential.access_token_issued_at)
        self.assertIsNone(credential.access_token_expires_at)
        self.assertEqual(credential.access_token_type, "")
        self.assertIsNone(credential.account_hash)
        self.assertEqual(credential.account_masked, "")
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                credential=credential,
                action=IntegrationAuditLog.ACTION_CREDENTIAL_CREATE,
                safe_summary="credential registered pending verification",
            ).exists()
        )

    @lifecycle_settings()
    def test_register_existing_updates_same_row_and_clears_token_account_metadata(self):
        user = self.create_user("user-alpha")
        credential = register_or_replace_pending_credential(
            user=user,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )
        credential.access_token_ciphertext = "cipher-access"
        credential.refresh_token_ciphertext = "cipher-refresh"
        credential.account_ref_ciphertext = "cipher-account-ref"
        credential.account_ref_key_version = "v1"
        credential.access_token_issued_at = timezone.now()
        credential.access_token_expires_at = timezone.now() + timedelta(minutes=30)
        credential.access_token_type = "Bearer"
        credential.account_hash = "hash-account"
        credential.account_masked = "acct_****1234"
        credential.status = STATUS_ACTIVE
        credential.save()

        updated = register_or_replace_pending_credential(
            user=user,
            client_id="dummy-client-beta",
            client_secret="dummy-secret-beta",
        )

        self.assertEqual(updated.pk, credential.pk)
        self.assertEqual(updated.status, STATUS_PENDING_VERIFICATION)
        self.assertIsNone(updated.access_token_ciphertext)
        self.assertIsNone(updated.refresh_token_ciphertext)
        self.assertIsNone(updated.account_ref_ciphertext)
        self.assertEqual(updated.account_ref_key_version, "")
        self.assertIsNone(updated.access_token_issued_at)
        self.assertIsNone(updated.access_token_expires_at)
        self.assertEqual(updated.access_token_type, "")
        self.assertIsNone(updated.account_hash)
        self.assertEqual(updated.account_masked, "")
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                credential=credential,
                action=IntegrationAuditLog.ACTION_CREDENTIAL_UPDATE,
            ).exists()
        )

    @lifecycle_settings()
    def test_duplicate_client_fingerprint_policy(self):
        user1 = self.create_user("user-alpha")
        user2 = self.create_user("user-beta")

        register_or_replace_pending_credential(
            user=user1,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )

        with self.assertRaises(CredentialDuplicateError):
            register_or_replace_pending_credential(
                user=user2,
                client_id="dummy-client-alpha",
                client_secret="dummy-secret-beta",
            )

        register_or_replace_pending_credential(
            user=user1,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-gamma",
        )

        reset_credential(user=user1)
        credential2 = register_or_replace_pending_credential(
            user=user2,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-beta",
        )
        self.assertEqual(credential2.user, user2)

    @lifecycle_settings()
    def test_mark_verification_success_hashes_account_and_audits(self):
        user = self.create_user("user-alpha")
        credential = register_or_replace_pending_credential(
            user=user,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )

        updated = mark_credential_verification_success(
            credential=credential,
            account_ref="dummy-account-seq-alpha",
            external_user_ref="dummy-external-user-alpha",
            scopes=["read", "orders"],
        )

        self.assertEqual(updated.status, STATUS_ACTIVE)
        self.assertTrue(updated.account_ref_ciphertext)
        self.assertNotEqual(updated.account_ref_ciphertext, "dummy-account-seq-alpha")
        self.assertEqual(updated.account_ref_key_version, "v1")
        self.assertEqual(updated.account_hash, make_account_hash("dummy-account-seq-alpha"))
        self.assertEqual(updated.account_masked, "acct_****lpha")
        self.assertTrue(updated.external_user_hash)
        self.assertEqual(updated.scopes, ["read", "orders"])
        self.assertIsNotNone(updated.last_verified_at)
        log = IntegrationAuditLog.objects.get(action=IntegrationAuditLog.ACTION_CREDENTIAL_VERIFICATION_SUCCESS)
        self.assertEqual(log.account_hash, updated.account_hash)
        self.assertNotIn("dummy-account-seq-alpha", log.safe_summary)
        self.assertNotIn("dummy-account-seq-alpha", str(log.safe_metadata))

    @lifecycle_settings()
    def test_duplicate_active_account_guard(self):
        user1 = self.create_user("user-alpha")
        user2 = self.create_user("user-beta")
        cred1 = register_or_replace_pending_credential(
            user=user1,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )
        cred2 = register_or_replace_pending_credential(
            user=user2,
            client_id="dummy-client-beta",
            client_secret="dummy-secret-beta",
        )
        mark_credential_verification_success(credential=cred1, account_ref="dummy-account-seq-alpha")

        with self.assertRaises(CredentialDuplicateError):
            mark_credential_verification_success(credential=cred2, account_ref="dummy-account-seq-alpha")

    @lifecycle_settings()
    def test_verification_failure_transient_keeps_ciphertexts(self):
        user = self.create_user("user-alpha")
        credential = register_or_replace_pending_credential(
            user=user,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )

        updated = mark_credential_verification_failure(
            credential=credential,
            failure_kind=VERIFICATION_FAILURE_TRANSIENT,
            error_code="timeout",
            safe_summary="temporary provider failure",
        )

        self.assertEqual(updated.status, STATUS_PENDING_VERIFICATION)
        self.assertTrue(updated.client_id_ciphertext)
        self.assertTrue(updated.client_secret_ciphertext)
        self.assertEqual(updated.error_code, "timeout")
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                action=IntegrationAuditLog.ACTION_CREDENTIAL_VERIFICATION_FAILURE,
                success=False,
                reason_code=VERIFICATION_FAILURE_TRANSIENT,
            ).exists()
        )

    @lifecycle_settings()
    def test_verification_failure_auth_and_revoked_reset(self):
        for failure_kind in [VERIFICATION_FAILURE_AUTH, VERIFICATION_FAILURE_REVOKED]:
            with self.subTest(failure_kind=failure_kind):
                user = self.create_user(f"user-{failure_kind}")
                credential = register_or_replace_pending_credential(
                    user=user,
                    client_id=f"dummy-client-{failure_kind}",
                    client_secret=f"dummy-secret-{failure_kind}",
                )

                updated = mark_credential_verification_failure(
                    credential=credential,
                    failure_kind=failure_kind,
                    error_code=failure_kind,
                    safe_summary="credential verification failed",
                )

                self.assertEqual(updated.status, STATUS_RESET_REQUIRED)
                self.assertIsNone(updated.client_id_ciphertext)
                self.assertIsNone(updated.client_secret_ciphertext)

    @lifecycle_settings()
    def test_reset_and_disconnect_credential(self):
        user = self.create_user("user-alpha")
        credential = register_or_replace_pending_credential(
            user=user,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )
        credential.account_hash = "hash-account"
        credential.account_masked = "acct_****1234"
        credential.account_ref_ciphertext = encrypt_text("dummy-account-seq-alpha").ciphertext
        credential.account_ref_key_version = "v1"
        credential.access_token_ciphertext = encrypt_text("dummy-access-token").ciphertext
        credential.access_token_issued_at = timezone.now()
        credential.access_token_expires_at = timezone.now() + timedelta(minutes=30)
        credential.access_token_type = "Bearer"
        credential.save()

        reset = reset_credential(user=user)
        self.assertEqual(reset.status, STATUS_RESET_REQUIRED)
        self.assertIsNone(reset.client_id_ciphertext)
        self.assertIsNone(reset.account_ref_ciphertext)
        self.assertEqual(reset.account_ref_key_version, "")
        self.assertIsNone(reset.access_token_ciphertext)
        self.assertIsNone(reset.access_token_issued_at)
        self.assertIsNone(reset.access_token_expires_at)
        self.assertEqual(reset.access_token_type, "")
        self.assertEqual(reset.account_hash, "hash-account")
        self.assertEqual(reset.account_masked, "acct_****1234")

        credential = register_or_replace_pending_credential(
            user=user,
            client_id="dummy-client-beta",
            client_secret="dummy-secret-beta",
        )
        credential.account_ref_ciphertext = encrypt_text("dummy-account-seq-beta").ciphertext
        credential.account_ref_key_version = "v1"
        credential.access_token_ciphertext = encrypt_text("dummy-access-token").ciphertext
        credential.access_token_type = "Bearer"
        credential.save()
        disconnected = disconnect_credential(user=user)
        self.assertEqual(disconnected.status, STATUS_DISCONNECTED)
        self.assertIsNotNone(disconnected.disconnected_at)
        self.assertIsNone(disconnected.account_ref_ciphertext)
        self.assertEqual(disconnected.account_ref_key_version, "")
        self.assertIsNone(disconnected.access_token_ciphertext)
        self.assertEqual(disconnected.access_token_type, "")
        self.assertTrue(
            IntegrationAuditLog.objects.filter(action=IntegrationAuditLog.ACTION_CREDENTIAL_DISCONNECT).exists()
        )

    @lifecycle_settings()
    def test_reveal_success_returns_client_credentials_only(self):
        user = self.create_user("user-alpha", password="safe-password")
        credential = register_or_replace_pending_credential(
            user=user,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )
        credential.access_token_ciphertext = encrypt_text("dummy-access-token").ciphertext
        credential.refresh_token_ciphertext = encrypt_text("dummy-refresh-token").ciphertext
        credential.account_ref_ciphertext = encrypt_text("dummy-account-seq-alpha").ciphertext
        credential.account_ref_key_version = "v1"
        credential.save()

        revealed = reveal_client_credentials(user=user, password="safe-password")

        self.assertEqual(revealed["client_id"], "dummy-client-alpha")
        self.assertEqual(revealed["client_secret"], "dummy-secret-alpha")
        self.assertIn("reveal_expires_at", revealed)
        self.assertIn("credential_id", revealed)
        self.assertNotIn("access_token", revealed)
        self.assertNotIn("refresh_token", revealed)
        self.assertNotIn("account_ref", revealed)
        self.assertTrue(
            IntegrationAuditLog.objects.filter(action=IntegrationAuditLog.ACTION_CREDENTIAL_REVEAL_SUCCESS).exists()
        )

    @lifecycle_settings()
    def test_reveal_wrong_password_fails_and_audits(self):
        user = self.create_user("user-alpha", password="safe-password")
        register_or_replace_pending_credential(
            user=user,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )

        with self.assertRaises(CredentialRevealError) as ctx:
            reveal_client_credentials(user=user, password="wrong-password")

        self.assertNotIn("dummy-client-alpha", str(ctx.exception))
        self.assertTrue(
            IntegrationAuditLog.objects.filter(action=IntegrationAuditLog.ACTION_CREDENTIAL_REVEAL_FAILURE).exists()
        )

    @lifecycle_settings()
    def test_reveal_not_owner_fails_without_staff_exception(self):
        owner = self.create_user("owner-alpha", password="safe-password")
        staff = get_user_model().objects.create_superuser(username="staff-alpha", password="staff-password")
        register_or_replace_pending_credential(
            user=owner,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )

        with self.assertRaises(CredentialRevealError):
            reveal_client_credentials(user=owner, request_user=staff, password="staff-password")

        self.assertTrue(
            IntegrationAuditLog.objects.filter(action=IntegrationAuditLog.ACTION_CREDENTIAL_REVEAL_FAILURE).exists()
        )

    @lifecycle_settings()
    def test_reveal_forbidden_statuses(self):
        for status in [STATUS_RESET_REQUIRED, STATUS_DISCONNECTED, STATUS_REVOKED, STATUS_ERROR]:
            with self.subTest(status=status):
                user = self.create_user(f"user-{status}", password="safe-password")
                credential = register_or_replace_pending_credential(
                    user=user,
                    client_id=f"dummy-client-{status}",
                    client_secret=f"dummy-secret-{status}",
                )
                credential.status = status
                credential.save()

                with self.assertRaises(CredentialRevealError):
                    reveal_client_credentials(user=user, password="safe-password")

    @lifecycle_settings()
    def test_reveal_decryption_failure_resets_and_audits(self):
        user = self.create_user("user-alpha", password="safe-password")
        credential = register_or_replace_pending_credential(
            user=user,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )
        credential.client_secret_ciphertext = "invalid-ciphertext"
        credential.account_ref_ciphertext = encrypt_text("dummy-account-seq-alpha").ciphertext
        credential.save()

        with self.assertRaises(CredentialRevealError):
            reveal_client_credentials(user=user, password="safe-password")

        credential.refresh_from_db()
        self.assertEqual(credential.status, STATUS_RESET_REQUIRED)
        self.assertIsNone(credential.client_id_ciphertext)
        self.assertIsNone(credential.client_secret_ciphertext)
        self.assertIsNone(credential.account_ref_ciphertext)
        self.assertTrue(
            IntegrationAuditLog.objects.filter(action=IntegrationAuditLog.ACTION_DECRYPTION_FAILURE).exists()
        )

    @lifecycle_settings()
    def test_get_credential_safe_status_does_not_decrypt(self):
        user = self.create_user("user-alpha")
        self.assertEqual(get_credential_safe_status(user)["status"], "not_configured")
        credential = register_or_replace_pending_credential(
            user=user,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )

        with patch("integrations.services.credential_lifecycle.decrypt_text") as decrypt_mock:
            status = get_credential_safe_status(user)

        decrypt_mock.assert_not_called()
        self.assertEqual(status["status"], STATUS_PENDING_VERIFICATION)
        self.assertTrue(status["client_id_stored"])
        self.assertTrue(status["secret_stored"])
        self.assertFalse(status["account_ref_stored"])
        self.assertNotIn("client_id_ciphertext", status)
        self.assertNotIn("client_secret_ciphertext", status)
        self.assertNotIn("account_ref_ciphertext", status)
        self.assertNotIn("account_hash", status)
        self.assertEqual(credential.pk, get_user_model().objects.get(pk=user.pk).toss_invest_credential.pk)

    @override_settings(
        CREDENTIAL_ENCRYPTION_KEY="",
        CREDENTIAL_ENCRYPTION_KEYS="",
        CREDENTIAL_HASH_PEPPER="dummy-pepper-for-tests",
    )
    def test_register_missing_encryption_key_fails_safely(self):
        user = self.create_user("user-alpha")

        with self.assertRaises(CredentialCryptoConfigurationError) as ctx:
            register_or_replace_pending_credential(
                user=user,
                client_id="dummy-client-alpha",
                client_secret="dummy-secret-alpha",
            )

        self.assertNotIn("dummy-client-alpha", str(ctx.exception))
        self.assertFalse(TossInvestCredential.objects.exists())

    @override_settings(
        CREDENTIAL_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii"),
        CREDENTIAL_HASH_PEPPER="",
    )
    def test_register_missing_hash_pepper_fails_safely(self):
        user = self.create_user("user-alpha")

        with self.assertRaises(CredentialCryptoConfigurationError) as ctx:
            register_or_replace_pending_credential(
                user=user,
                client_id="dummy-client-alpha",
                client_secret="dummy-secret-alpha",
            )

        self.assertNotIn("dummy-secret-alpha", str(ctx.exception))
        self.assertFalse(TossInvestCredential.objects.exists())

    @lifecycle_settings()
    def test_lifecycle_audit_metadata_does_not_use_unsafe_keys(self):
        user = self.create_user("user-alpha")
        credential = register_or_replace_pending_credential(
            user=user,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )
        mark_credential_verification_success(credential=credential, account_ref="dummy-account-seq-alpha")

        unsafe_parts = ["token", "secret", "authorization", "accountNo", "accountSeq", "raw_response", "dummy-account-seq-alpha"]
        for log in IntegrationAuditLog.objects.all():
            rendered_metadata = str(log.safe_metadata)
            for unsafe in unsafe_parts:
                self.assertNotIn(unsafe, rendered_metadata)
