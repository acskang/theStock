from __future__ import annotations

import inspect

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from integrations.models import (
    STATUS_ACTIVE,
    STATUS_PENDING_VERIFICATION,
    STATUS_RESET_REQUIRED,
    IntegrationAuditLog,
)
from integrations.services.credential_crypto import decrypt_text
from integrations.services.credential_lifecycle import register_or_replace_pending_credential
from integrations.services.fingerprints import make_account_hash
from integrations.services.toss_readonly_verification import (
    ACCOUNTS_PATH,
    TOKEN_PATH,
    TossReadonlyVerificationAccountNotFound,
    TossReadonlyVerificationAccountSelectionRequired,
    TossReadonlyVerificationAuthError,
    TossReadonlyVerificationConfigurationError,
    TossReadonlyVerificationStateError,
    TossReadonlyVerificationTransientError,
    build_safe_account_candidates,
    fetch_toss_accounts,
    get_toss_account_candidates_for_user,
    issue_toss_access_token,
    verify_user_toss_credential_readonly,
)


def verification_settings(api_calls_enabled: bool = True):
    return override_settings(
        TOSS_USER_TOSS_API_CALLS_ENABLED=api_calls_enabled,
        TOSS_INVEST_OPENAPI_BASE_URL="https://openapi.tossinvest.example.test",
        TOSS_INVEST_HTTP_TIMEOUT_SECONDS=1,
        CREDENTIAL_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii"),
        CREDENTIAL_ENCRYPTION_KEY_VERSION="v1",
        CREDENTIAL_ENCRYPTION_KEYS="",
        CREDENTIAL_ENCRYPTION_CURRENT_VERSION="",
        CREDENTIAL_HASH_PEPPER="dummy-pepper-for-tests",
    )


class FakeTossTransport:
    def __init__(
        self,
        *,
        token_status: int = 200,
        token_body: dict | None = None,
        accounts_status: int = 200,
        accounts_body: dict | None = None,
        token_error: Exception | None = None,
        accounts_error: Exception | None = None,
    ):
        self.token_status = token_status
        self.token_body = token_body or {
            "access_token": "dummy-access-token-alpha",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        self.accounts_status = accounts_status
        self.accounts_body = accounts_body or {"result": [account("dummy-account-seq-alpha", "dummy-account-no-alpha")]}
        self.token_error = token_error
        self.accounts_error = accounts_error
        self.post_form_calls: list[dict] = []
        self.get_json_calls: list[dict] = []

    def post_form(self, path: str, data: dict[str, str], headers: dict[str, str] | None = None):
        self.post_form_calls.append({"path": path, "data": data, "headers": headers or {}})
        if self.token_error:
            raise self.token_error
        return self.token_status, self.token_body

    def get_json(self, path: str, headers: dict[str, str] | None = None):
        self.get_json_calls.append({"path": path, "headers": headers or {}})
        if self.accounts_error:
            raise self.accounts_error
        return self.accounts_status, self.accounts_body


def account(account_seq: str, account_no: str, account_type: str = "BROKERAGE") -> dict:
    return {"accountSeq": account_seq, "accountNo": account_no, "accountType": account_type}


class TossReadonlyVerificationTests(TestCase):
    def create_user(self, username: str, *, password: str = "safe-password"):
        return get_user_model().objects.create_user(username=username, password=password)

    def create_pending_credential(self, username: str = "user-alpha"):
        user = self.create_user(username)
        credential = register_or_replace_pending_credential(
            user=user,
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
        )
        return user, credential

    @verification_settings()
    def test_issue_toss_access_token_success(self):
        transport = FakeTossTransport()

        payload = issue_toss_access_token(
            client_id="dummy-client-alpha",
            client_secret="dummy-secret-alpha",
            transport=transport,
        )

        self.assertEqual(payload.access_token, "dummy-access-token-alpha")
        self.assertEqual(payload.token_type, "Bearer")
        self.assertEqual(payload.expires_in, 3600)
        call = transport.post_form_calls[0]
        self.assertEqual(call["path"], TOKEN_PATH)
        self.assertEqual(call["data"]["grant_type"], "client_credentials")
        self.assertEqual(call["data"]["client_id"], "dummy-client-alpha")
        self.assertEqual(call["data"]["client_secret"], "dummy-secret-alpha")

    @verification_settings()
    def test_issue_toss_access_token_invalid_client_is_safe_auth_error(self):
        transport = FakeTossTransport(token_status=401, token_body={"error": "invalid_client"})

        with self.assertRaises(TossReadonlyVerificationAuthError) as ctx:
            issue_toss_access_token(
                client_id="dummy-client-alpha",
                client_secret="dummy-secret-alpha",
                transport=transport,
            )

        self.assertNotIn("dummy-client-alpha", str(ctx.exception))
        self.assertNotIn("dummy-secret-alpha", str(ctx.exception))

    @verification_settings()
    def test_issue_toss_access_token_transient_failures(self):
        for status in [429, 500]:
            with self.subTest(status=status):
                with self.assertRaises(TossReadonlyVerificationTransientError):
                    issue_toss_access_token(
                        client_id="dummy-client-alpha",
                        client_secret="dummy-secret-alpha",
                        transport=FakeTossTransport(token_status=status),
                    )

        with self.assertRaises(TossReadonlyVerificationTransientError):
            issue_toss_access_token(
                client_id="dummy-client-alpha",
                client_secret="dummy-secret-alpha",
                transport=FakeTossTransport(token_error=TimeoutError()),
            )

    @verification_settings()
    def test_fetch_toss_accounts_success_uses_bearer_without_account_header(self):
        transport = FakeTossTransport()

        accounts = fetch_toss_accounts(access_token="dummy-access-token-alpha", transport=transport)

        self.assertEqual(len(accounts), 1)
        call = transport.get_json_calls[0]
        self.assertEqual(call["path"], ACCOUNTS_PATH)
        self.assertEqual(call["headers"]["Authorization"], "Bearer dummy-access-token-alpha")
        self.assertNotIn("X-Tossinvest-Account", call["headers"])

    @verification_settings()
    def test_build_safe_account_candidates_excludes_raw_account_values(self):
        candidates = build_safe_account_candidates(
            [account("dummy-account-seq-alpha", "dummy-account-no-alpha")]
        )

        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        rendered = str(candidate)
        self.assertEqual(candidate.account_hash, make_account_hash("dummy-account-seq-alpha"))
        self.assertEqual(candidate.account_type, "BROKERAGE")
        self.assertTrue(candidate.is_selectable)
        self.assertNotIn("dummy-account-seq-alpha", rendered)
        self.assertNotIn("dummy-account-no-alpha", rendered)

    @verification_settings()
    def test_single_account_verification_success_activates_and_stores_encrypted_values(self):
        user, credential = self.create_pending_credential()
        transport = FakeTossTransport()

        result = verify_user_toss_credential_readonly(user=user, transport=transport)

        credential.refresh_from_db()
        self.assertTrue(result.success)
        self.assertEqual(result.status, STATUS_ACTIVE)
        self.assertEqual(credential.status, STATUS_ACTIVE)
        self.assertTrue(credential.account_ref_ciphertext)
        self.assertNotEqual(credential.account_ref_ciphertext, "dummy-account-seq-alpha")
        self.assertEqual(credential.account_hash, make_account_hash("dummy-account-seq-alpha"))
        self.assertEqual(credential.account_masked, "acct_****lpha")
        self.assertTrue(credential.access_token_ciphertext)
        self.assertNotEqual(credential.access_token_ciphertext, "dummy-access-token-alpha")
        self.assertEqual(credential.access_token_type, "Bearer")
        self.assertIsNotNone(credential.access_token_issued_at)
        self.assertIsNotNone(credential.access_token_expires_at)
        self.assertIsNone(credential.refresh_token_ciphertext)
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                credential=credential,
                action=IntegrationAuditLog.ACTION_CREDENTIAL_VERIFICATION_SUCCESS,
            ).exists()
        )
        rendered_result = str(result)
        self.assertNotIn("dummy-access-token-alpha", rendered_result)
        self.assertNotIn("dummy-secret-alpha", rendered_result)
        self.assertNotIn("dummy-account-seq-alpha", rendered_result)
        self.assertNotIn("dummy-account-no-alpha", rendered_result)

    @verification_settings()
    def test_multiple_accounts_without_selection_requires_safe_selection(self):
        user, credential = self.create_pending_credential()
        transport = FakeTossTransport(
            accounts_body={
                "result": [
                    account("dummy-account-seq-alpha", "dummy-account-no-alpha"),
                    account("dummy-account-seq-beta", "dummy-account-no-beta"),
                ]
            }
        )

        with self.assertRaises(TossReadonlyVerificationAccountSelectionRequired) as ctx:
            verify_user_toss_credential_readonly(user=user, transport=transport)

        credential.refresh_from_db()
        self.assertEqual(credential.status, STATUS_PENDING_VERIFICATION)
        self.assertIsNone(credential.access_token_ciphertext)
        self.assertTrue(credential.client_id_ciphertext)
        self.assertEqual(len(ctx.exception.candidates), 2)
        rendered = str(ctx.exception.candidates)
        self.assertNotIn("dummy-account-seq-alpha", rendered)
        self.assertNotIn("dummy-account-no-alpha", rendered)
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                credential=credential,
                action=IntegrationAuditLog.ACTION_CREDENTIAL_VERIFICATION_FAILURE,
                reason_code="account_selection_required",
            ).exists()
        )

    @verification_settings()
    def test_multiple_accounts_with_selected_hash_activates_selected_account(self):
        user, credential = self.create_pending_credential()
        accounts = [
            account("dummy-account-seq-alpha", "dummy-account-no-alpha"),
            account("dummy-account-seq-beta", "dummy-account-no-beta"),
        ]
        selected_hash = build_safe_account_candidates(accounts)[1].account_hash

        result = verify_user_toss_credential_readonly(
            user=user,
            selected_account_hash=selected_hash,
            transport=FakeTossTransport(accounts_body={"result": accounts}),
        )

        credential.refresh_from_db()
        self.assertTrue(result.success)
        self.assertEqual(credential.status, STATUS_ACTIVE)
        self.assertEqual(credential.account_hash, make_account_hash("dummy-account-seq-beta"))
        self.assertEqual(credential.account_masked, "acct_****beta")
        self.assertNotEqual(credential.account_ref_ciphertext, "dummy-account-seq-beta")

    @verification_settings()
    def test_selected_account_hash_not_found_keeps_pending_without_token(self):
        user, credential = self.create_pending_credential()

        with self.assertRaises(TossReadonlyVerificationAccountNotFound):
            verify_user_toss_credential_readonly(
                user=user,
                selected_account_hash=make_account_hash("missing-account"),
                transport=FakeTossTransport(),
            )

        credential.refresh_from_db()
        self.assertEqual(credential.status, STATUS_PENDING_VERIFICATION)
        self.assertIsNone(credential.access_token_ciphertext)
        self.assertTrue(credential.client_id_ciphertext)

    @verification_settings()
    def test_no_accounts_keeps_pending_without_token(self):
        user, credential = self.create_pending_credential()

        with self.assertRaises(TossReadonlyVerificationAccountNotFound):
            verify_user_toss_credential_readonly(
                user=user,
                transport=FakeTossTransport(accounts_body={"result": []}),
            )

        credential.refresh_from_db()
        self.assertEqual(credential.status, STATUS_PENDING_VERIFICATION)
        self.assertIsNone(credential.access_token_ciphertext)
        self.assertTrue(credential.client_id_ciphertext)
        self.assertEqual(credential.error_code, "no_account")

    @verification_settings()
    def test_token_auth_failure_resets_credential(self):
        user, credential = self.create_pending_credential()

        with self.assertRaises(TossReadonlyVerificationAuthError):
            verify_user_toss_credential_readonly(
                user=user,
                transport=FakeTossTransport(token_status=401),
            )

        credential.refresh_from_db()
        self.assertEqual(credential.status, STATUS_RESET_REQUIRED)
        self.assertIsNone(credential.client_id_ciphertext)
        self.assertIsNone(credential.client_secret_ciphertext)
        self.assertIsNone(credential.account_ref_ciphertext)
        self.assertIsNone(credential.access_token_ciphertext)

    @verification_settings()
    def test_account_auth_failure_resets_credential(self):
        user, credential = self.create_pending_credential()

        with self.assertRaises(TossReadonlyVerificationAuthError):
            verify_user_toss_credential_readonly(
                user=user,
                transport=FakeTossTransport(accounts_status=401),
            )

        credential.refresh_from_db()
        self.assertEqual(credential.status, STATUS_RESET_REQUIRED)
        self.assertIsNone(credential.client_id_ciphertext)

    @verification_settings()
    def test_transient_failures_keep_pending_credential(self):
        for name, transport in {
            "token_429": FakeTossTransport(token_status=429),
            "account_500": FakeTossTransport(accounts_status=500),
            "network": FakeTossTransport(accounts_error=TimeoutError()),
        }.items():
            with self.subTest(name=name):
                user = self.create_user(f"user-{name}")
                credential = register_or_replace_pending_credential(
                    user=user,
                    client_id=f"dummy-client-{name}",
                    client_secret=f"dummy-secret-{name}",
                )

                with self.assertRaises(TossReadonlyVerificationTransientError):
                    verify_user_toss_credential_readonly(user=user, transport=transport)

                credential.refresh_from_db()
                self.assertEqual(credential.status, STATUS_PENDING_VERIFICATION)
                self.assertTrue(credential.client_id_ciphertext)
                self.assertTrue(credential.client_secret_ciphertext)
                self.assertIsNone(credential.access_token_ciphertext)

    @verification_settings()
    def test_decryption_failure_resets_and_audits(self):
        user, credential = self.create_pending_credential()
        credential.client_secret_ciphertext = "invalid-ciphertext"
        credential.save()

        with self.assertRaises(TossReadonlyVerificationStateError):
            verify_user_toss_credential_readonly(user=user, transport=FakeTossTransport())

        credential.refresh_from_db()
        self.assertEqual(credential.status, STATUS_RESET_REQUIRED)
        self.assertIsNone(credential.client_id_ciphertext)
        self.assertIsNone(credential.client_secret_ciphertext)
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                credential=credential,
                action=IntegrationAuditLog.ACTION_DECRYPTION_FAILURE,
            ).exists()
        )

    @verification_settings(api_calls_enabled=False)
    def test_api_calls_disabled_blocks_even_fake_transport(self):
        user, _credential = self.create_pending_credential()

        with self.assertRaises(TossReadonlyVerificationConfigurationError) as ctx:
            verify_user_toss_credential_readonly(user=user, transport=FakeTossTransport())

        self.assertNotIn("dummy-client-alpha", str(ctx.exception))
        self.assertNotIn("dummy-secret-alpha", str(ctx.exception))

    @verification_settings()
    def test_service_source_does_not_reference_global_toss_credentials(self):
        from integrations.services import toss_readonly_verification

        source = inspect.getsource(toss_readonly_verification)
        self.assertNotIn("TOSS_INVEST_CLIENT_ID", source)
        self.assertNotIn("TOSS_INVEST_CLIENT_SECRET", source)
        self.assertNotIn("TOSS_INVEST_ACCOUNT_ID", source)

    @verification_settings()
    def test_get_toss_account_candidates_for_user_returns_safe_candidates_without_activation(self):
        user, credential = self.create_pending_credential()

        candidates = get_toss_account_candidates_for_user(user=user, transport=FakeTossTransport())

        credential.refresh_from_db()
        self.assertEqual(credential.status, STATUS_PENDING_VERIFICATION)
        self.assertIsNone(credential.access_token_ciphertext)
        self.assertEqual(len(candidates), 1)
        rendered = str(candidates)
        self.assertNotIn("dummy-access-token-alpha", rendered)
        self.assertNotIn("dummy-account-seq-alpha", rendered)
        self.assertNotIn("dummy-account-no-alpha", rendered)

    @verification_settings()
    def test_token_reveal_never_in_result_or_safe_status(self):
        user, credential = self.create_pending_credential()

        result = verify_user_toss_credential_readonly(user=user, transport=FakeTossTransport())
        credential.refresh_from_db()

        self.assertNotIn("dummy-access-token-alpha", str(result))
        self.assertNotEqual(
            decrypt_text(credential.access_token_ciphertext, credential.access_token_key_version),
            "",
        )
        safe = credential.safe_display_dict()
        self.assertNotIn("access_token_ciphertext", safe)
        self.assertNotIn("refresh_token_ciphertext", safe)

    @verification_settings()
    def test_audit_safety(self):
        user, _credential = self.create_pending_credential()

        verify_user_toss_credential_readonly(user=user, transport=FakeTossTransport())

        unsafe_values = [
            "dummy-access-token-alpha",
            "dummy-secret-alpha",
            "dummy-account-no-alpha",
            "dummy-account-seq-alpha",
            "Authorization",
            "raw_response",
        ]
        for log in IntegrationAuditLog.objects.all():
            rendered = f"{log.safe_summary} {log.safe_metadata}"
            for unsafe in unsafe_values:
                self.assertNotIn(unsafe, rendered)
