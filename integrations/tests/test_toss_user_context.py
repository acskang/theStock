from __future__ import annotations

import inspect
from datetime import timedelta
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from integrations.models import (
    STATUS_ACTIVE,
    STATUS_DISCONNECTED,
    STATUS_PENDING_VERIFICATION,
    STATUS_RESET_REQUIRED,
    IntegrationAuditLog,
    TossInvestCredential,
)
from integrations.services.credential_crypto import decrypt_text, encrypt_text
from integrations.services.credential_lifecycle import (
    mark_credential_verification_success,
    register_or_replace_pending_credential,
)
from integrations.services.toss_readonly_verification import (
    TossReadonlyVerificationAuthError,
    TossReadonlyVerificationTransientError,
    TossTokenPayload,
)
from integrations.services.toss_user_context import (
    TossUserContextAuthError,
    TossUserContextConfigurationError,
    TossUserContextDecryptionError,
    TossUserContextNotReadyError,
    TossUserContextPermissionError,
    TossUserContextTransientError,
    build_user_toss_request_context,
    clear_user_access_token,
    get_active_toss_credential_for_user,
    get_token_refresh_skew_seconds,
    is_access_token_usable,
)


def context_settings(api_calls_enabled: bool = True):
    return override_settings(
        TOSS_USER_TOSS_API_CALLS_ENABLED=api_calls_enabled,
        TOSS_INVEST_ACCESS_TOKEN_REFRESH_SKEW_SECONDS=60,
        CREDENTIAL_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii"),
        CREDENTIAL_ENCRYPTION_KEY_VERSION="v1",
        CREDENTIAL_ENCRYPTION_KEYS="",
        CREDENTIAL_ENCRYPTION_CURRENT_VERSION="",
        CREDENTIAL_HASH_PEPPER="dummy-pepper-for-tests",
    )


class TossUserContextTests(TestCase):
    def create_user(self, username: str, *, password: str = "safe-password"):
        return get_user_model().objects.create_user(username=username, password=password)

    def create_active_credential(self, username: str = "user-alpha"):
        user = self.create_user(username)
        credential = register_or_replace_pending_credential(
            user=user,
            client_id=f"dummy-client-{username}",
            client_secret=f"dummy-secret-{username}",
        )
        credential = mark_credential_verification_success(
            credential=credential,
            account_ref="dummy-account-ref-alpha",
            account_masked="dummy-account-no-alpha",
        )
        return user, credential

    def store_access_token(self, credential, token: str = "dummy-access-token-alpha", *, expires_in: int = 3600):
        encrypted = encrypt_text(token)
        credential.access_token_ciphertext = encrypted.ciphertext
        credential.access_token_key_version = encrypted.key_version
        credential.access_token_type = "Bearer"
        credential.access_token_issued_at = timezone.now()
        credential.access_token_expires_at = timezone.now() + timedelta(seconds=expires_in)
        credential.save()
        return credential

    @context_settings()
    def test_refresh_skew_and_token_usable(self):
        user, credential = self.create_active_credential()
        self.assertEqual(get_token_refresh_skew_seconds(), 60)
        self.assertFalse(is_access_token_usable(credential))

        self.store_access_token(credential, expires_in=3600)
        credential.refresh_from_db()
        with patch("integrations.services.toss_user_context.decrypt_text") as decrypt_mock:
            self.assertTrue(is_access_token_usable(credential))
        decrypt_mock.assert_not_called()

        credential.access_token_expires_at = timezone.now() + timedelta(seconds=30)
        credential.save()
        self.assertFalse(is_access_token_usable(credential))
        self.assertEqual(get_active_toss_credential_for_user(user).pk, credential.pk)

    @context_settings()
    def test_build_context_with_usable_token_does_not_reissue(self):
        user, credential = self.create_active_credential()
        self.store_access_token(credential)

        with patch("integrations.services.toss_user_context.issue_toss_access_token") as issue_mock:
            context = build_user_toss_request_context(user=user)

        issue_mock.assert_not_called()
        self.assertFalse(context.refreshed)
        self.assertEqual(context.authorization_header(), "Bearer dummy-access-token-alpha")
        self.assertEqual(context.headers()["X-Tossinvest-Account"], "dummy-account-ref-alpha")
        rendered = repr(context)
        self.assertNotIn("dummy-access-token-alpha", rendered)
        self.assertNotIn("dummy-account-ref-alpha", rendered)
        summary = str(context.safe_summary())
        self.assertNotIn("dummy-access-token-alpha", summary)
        self.assertNotIn("dummy-account-ref-alpha", summary)

    @context_settings()
    def test_build_context_reissues_missing_token_and_audits(self):
        user, credential = self.create_active_credential()

        with patch(
            "integrations.services.toss_user_context.issue_toss_access_token",
            return_value=TossTokenPayload("dummy-access-token-alpha", "Bearer", 3600),
        ) as issue_mock:
            context = build_user_toss_request_context(user=user, transport=object())

        issue_mock.assert_called_once()
        credential.refresh_from_db()
        self.assertTrue(context.refreshed)
        self.assertEqual(context.authorization_header(), "Bearer dummy-access-token-alpha")
        self.assertTrue(credential.access_token_ciphertext)
        self.assertNotEqual(credential.access_token_ciphertext, "dummy-access-token-alpha")
        self.assertEqual(decrypt_text(credential.access_token_ciphertext, credential.access_token_key_version), "dummy-access-token-alpha")
        self.assertEqual(credential.access_token_type, "Bearer")
        self.assertIsNotNone(credential.access_token_issued_at)
        self.assertIsNotNone(credential.access_token_expires_at)
        self.assertIsNone(credential.refresh_token_ciphertext)
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                credential=credential,
                action=IntegrationAuditLog.ACTION_TOKEN_REFRESH,
                success=True,
            ).exists()
        )

    @context_settings()
    def test_force_refresh_reissues_even_usable_token(self):
        user, credential = self.create_active_credential()
        self.store_access_token(credential, token="dummy-access-token-alpha")
        old_ciphertext = credential.access_token_ciphertext

        with patch(
            "integrations.services.toss_user_context.issue_toss_access_token",
            return_value=TossTokenPayload("dummy-access-token-beta", "Bearer", 3600),
        ):
            context = build_user_toss_request_context(user=user, force_refresh=True)

        credential.refresh_from_db()
        self.assertTrue(context.refreshed)
        self.assertEqual(context.authorization_header(), "Bearer dummy-access-token-beta")
        self.assertNotEqual(credential.access_token_ciphertext, old_ciphertext)
        self.assertEqual(decrypt_text(credential.access_token_ciphertext, credential.access_token_key_version), "dummy-access-token-beta")

    @context_settings(api_calls_enabled=False)
    def test_api_calls_disabled_blocks_context_and_transport(self):
        user, _credential = self.create_active_credential()

        with patch("integrations.services.toss_user_context.issue_toss_access_token") as issue_mock:
            with self.assertRaises(TossUserContextConfigurationError) as ctx:
                build_user_toss_request_context(user=user)

        issue_mock.assert_not_called()
        self.assertNotIn("dummy-client", str(ctx.exception))

    @context_settings()
    def test_not_ready_states_and_missing_account_ref(self):
        user, credential = self.create_active_credential()
        for status in [STATUS_PENDING_VERIFICATION, STATUS_RESET_REQUIRED, STATUS_DISCONNECTED]:
            with self.subTest(status=status):
                credential.status = status
                credential.save()
                with self.assertRaises(TossUserContextNotReadyError):
                    build_user_toss_request_context(user=user)
        credential.status = STATUS_ACTIVE
        credential.account_ref_ciphertext = None
        credential.save()
        with self.assertRaises(TossUserContextNotReadyError):
            build_user_toss_request_context(user=user)

    @context_settings()
    def test_permission_denied_for_other_user_even_staff(self):
        owner, _credential = self.create_active_credential("owner-alpha")
        staff = get_user_model().objects.create_superuser(username="staff-alpha", password="safe-password")

        with patch("integrations.services.toss_user_context.issue_toss_access_token") as issue_mock:
            with self.assertRaises(TossUserContextPermissionError):
                build_user_toss_request_context(user=owner, actor=staff)

        issue_mock.assert_not_called()
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                action=IntegrationAuditLog.ACTION_PERMISSION_DENIED,
                success=False,
            ).exists()
        )

    @context_settings()
    def test_account_ref_decryption_failure_resets(self):
        user, credential = self.create_active_credential()
        credential.account_ref_ciphertext = "invalid-ciphertext"
        credential.save()

        with self.assertRaises(TossUserContextDecryptionError) as ctx:
            build_user_toss_request_context(user=user)

        credential.refresh_from_db()
        self.assertEqual(credential.status, STATUS_RESET_REQUIRED)
        self.assertIsNone(credential.client_id_ciphertext)
        self.assertIsNone(credential.account_ref_ciphertext)
        self.assertNotIn("invalid-ciphertext", str(ctx.exception))
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                credential=credential,
                action=IntegrationAuditLog.ACTION_DECRYPTION_FAILURE,
            ).exists()
        )

    @context_settings()
    def test_access_token_decryption_failure_resets(self):
        user, credential = self.create_active_credential()
        credential.access_token_ciphertext = "invalid-ciphertext"
        credential.access_token_key_version = "v1"
        credential.access_token_type = "Bearer"
        credential.access_token_expires_at = timezone.now() + timedelta(hours=1)
        credential.save()

        with self.assertRaises(TossUserContextDecryptionError):
            build_user_toss_request_context(user=user)

        credential.refresh_from_db()
        self.assertEqual(credential.status, STATUS_RESET_REQUIRED)
        self.assertIsNone(credential.access_token_ciphertext)
        self.assertTrue(
            IntegrationAuditLog.objects.filter(action=IntegrationAuditLog.ACTION_DECRYPTION_FAILURE).exists()
        )

    @context_settings()
    def test_client_credential_decryption_failure_resets_before_transport(self):
        user, credential = self.create_active_credential()
        credential.client_secret_ciphertext = "invalid-ciphertext"
        credential.save()

        with patch("integrations.services.toss_user_context.issue_toss_access_token") as issue_mock:
            with self.assertRaises(TossUserContextDecryptionError):
                build_user_toss_request_context(user=user)

        issue_mock.assert_not_called()
        credential.refresh_from_db()
        self.assertEqual(credential.status, STATUS_RESET_REQUIRED)
        self.assertIsNone(credential.client_secret_ciphertext)

    @context_settings()
    def test_token_auth_failure_resets_credential(self):
        user, credential = self.create_active_credential()

        with patch(
            "integrations.services.toss_user_context.issue_toss_access_token",
            side_effect=TossReadonlyVerificationAuthError("raw dummy-secret-alpha"),
        ):
            with self.assertRaises(TossUserContextAuthError) as ctx:
                build_user_toss_request_context(user=user)

        credential.refresh_from_db()
        self.assertEqual(credential.status, STATUS_RESET_REQUIRED)
        self.assertIsNone(credential.client_id_ciphertext)
        self.assertIsNone(credential.account_ref_ciphertext)
        self.assertNotIn("dummy-secret-alpha", str(ctx.exception))
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                credential=credential,
                action=IntegrationAuditLog.ACTION_TOKEN_REFRESH,
                success=False,
                reason_code="auth_failure",
            ).exists()
        )

    @context_settings()
    def test_token_transient_failure_keeps_active(self):
        user, credential = self.create_active_credential()

        with patch(
            "integrations.services.toss_user_context.issue_toss_access_token",
            side_effect=TossReadonlyVerificationTransientError("raw dummy-access-token-alpha"),
        ):
            with self.assertRaises(TossUserContextTransientError) as ctx:
                build_user_toss_request_context(user=user)

        credential.refresh_from_db()
        self.assertEqual(credential.status, STATUS_ACTIVE)
        self.assertTrue(credential.client_id_ciphertext)
        self.assertTrue(credential.account_ref_ciphertext)
        self.assertIsNone(credential.access_token_ciphertext)
        self.assertNotIn("dummy-access-token-alpha", str(ctx.exception))
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                credential=credential,
                action=IntegrationAuditLog.ACTION_TOKEN_REFRESH,
                success=False,
                reason_code="transient",
            ).exists()
        )

    @context_settings()
    def test_clear_user_access_token_only_clears_token(self):
        user, credential = self.create_active_credential()
        self.store_access_token(credential)

        cleared = clear_user_access_token(user=user)

        self.assertEqual(cleared.status, STATUS_ACTIVE)
        self.assertTrue(cleared.client_id_ciphertext)
        self.assertTrue(cleared.client_secret_ciphertext)
        self.assertTrue(cleared.account_ref_ciphertext)
        self.assertIsNone(cleared.access_token_ciphertext)
        self.assertIsNone(cleared.access_token_expires_at)
        self.assertEqual(cleared.access_token_type, "")
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                credential=credential,
                action=IntegrationAuditLog.ACTION_TOKEN_REFRESH,
                reason_code="manual_clear",
            ).exists()
        )

    @context_settings()
    def test_source_does_not_reference_global_toss_credentials(self):
        from integrations.services import toss_user_context

        source = inspect.getsource(toss_user_context)
        self.assertNotIn("TOSS_INVEST_CLIENT_ID", source)
        self.assertNotIn("TOSS_INVEST_CLIENT_SECRET", source)
        self.assertNotIn("TOSS_INVEST_ACCOUNT_ID", source)

    @context_settings()
    def test_audit_and_summary_do_not_include_sensitive_values(self):
        user, _credential = self.create_active_credential()

        with patch(
            "integrations.services.toss_user_context.issue_toss_access_token",
            return_value=TossTokenPayload("dummy-access-token-alpha", "Bearer", 3600),
        ):
            context = build_user_toss_request_context(user=user)

        rendered_summary = str(context.safe_summary())
        self.assertNotIn("dummy-access-token-alpha", rendered_summary)
        self.assertNotIn("dummy-account-ref-alpha", rendered_summary)
        self.assertNotIn("dummy-secret", rendered_summary)
        for log in IntegrationAuditLog.objects.all():
            rendered = f"{log.safe_summary} {log.safe_metadata}"
            self.assertNotIn("dummy-access-token-alpha", rendered)
            self.assertNotIn("dummy-account-ref-alpha", rendered)
            self.assertNotIn("dummy-secret", rendered)
