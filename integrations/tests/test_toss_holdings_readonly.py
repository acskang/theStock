from __future__ import annotations

import inspect
from datetime import timedelta

from cryptography.fernet import Fernet
from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from integrations.models import STATUS_ACTIVE, IntegrationAuditLog
from integrations.services.credential_crypto import encrypt_text
from integrations.services.credential_lifecycle import (
    mark_credential_verification_success,
    register_or_replace_pending_credential,
)
from integrations.services.toss_holdings_readonly import (
    HOLDINGS_PATH,
    TossHoldingsReadonlyAuthError,
    TossHoldingsReadonlyParseError,
    TossHoldingsReadonlyStateError,
    TossHoldingsReadonlyTransientError,
    TossHoldingsReadonlyValidationError,
    fetch_user_toss_holdings_preview,
    fetch_user_toss_holdings_preview_safe_dict,
    normalize_holdings_response,
)


def holdings_settings(api_calls_enabled: bool = True):
    return override_settings(
        TOSS_USER_TOSS_API_CALLS_ENABLED=api_calls_enabled,
        TOSS_INVEST_ACCESS_TOKEN_REFRESH_SKEW_SECONDS=60,
        CREDENTIAL_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii"),
        CREDENTIAL_ENCRYPTION_KEY_VERSION="v1",
        CREDENTIAL_ENCRYPTION_KEYS="",
        CREDENTIAL_ENCRYPTION_CURRENT_VERSION="",
        CREDENTIAL_HASH_PEPPER="dummy-pepper-for-tests",
    )


class FakeHoldingsTransport:
    def __init__(
        self,
        *,
        token_body: dict | None = None,
        holdings_responses: list[tuple[int, dict]] | None = None,
        holdings_error: Exception | None = None,
    ):
        self.token_body = token_body or {
            "access_token": "dummy-access-token-alpha",
            "token_type": "Bearer",
            "expires_in": 3600,
        }
        self.holdings_responses = list(holdings_responses or [(200, sample_holdings_response())])
        self.holdings_error = holdings_error
        self.post_form_calls: list[dict] = []
        self.get_json_calls: list[dict] = []

    def post_form(self, path: str, data: dict[str, str], headers: dict[str, str] | None = None):
        self.post_form_calls.append({"path": path, "data": data, "headers": headers or {}})
        return 200, self.token_body

    def get_json(self, path: str, headers: dict[str, str] | None = None):
        self.get_json_calls.append({"path": path, "headers": headers or {}})
        if self.holdings_error:
            raise self.holdings_error
        if self.holdings_responses:
            return self.holdings_responses.pop(0)
        return 200, sample_holdings_response()


def sample_holdings_response(*, items: list[dict] | None = None) -> dict:
    return {
        "result": {
            "totalPurchaseAmount": {"krw": "6500000", "usd": "1553"},
            "marketValue": {
                "amount": {"krw": "7200000", "usd": "1785"},
                "amountAfterCost": {"krw": "7050000", "usd": "1771.43"},
            },
            "profitLoss": {
                "amount": {"krw": "700000", "usd": "232"},
                "amountAfterCost": {"krw": "550000", "usd": "218.43"},
                "rate": "0.1179",
                "rateAfterCost": "0.0983",
            },
            "dailyProfitLoss": {
                "amount": {"krw": "100000", "usd": "25"},
                "rate": "0.0141",
            },
            "items": items
            if items is not None
            else [
                {
                    "symbol": "005930",
                    "name": "Samsung Electronics",
                    "marketCountry": "KR",
                    "currency": "KRW",
                    "quantity": "100",
                    "lastPrice": "72000",
                    "averagePurchasePrice": "65000",
                    "marketValue": {
                        "purchaseAmount": "6500000",
                        "amount": "7200000",
                        "amountAfterCost": "7050000",
                    },
                    "profitLoss": {
                        "amount": "700000",
                        "amountAfterCost": "550000",
                        "rate": "0.1077",
                        "rateAfterCost": "0.0846",
                    },
                    "dailyProfitLoss": {"amount": "100000", "rate": "0.0141"},
                    "cost": {"commission": "14400", "tax": "135600"},
                },
                {
                    "symbol": "AAPL",
                    "name": "Apple Inc.",
                    "marketCountry": "US",
                    "currency": "USD",
                    "quantity": "10",
                    "lastPrice": "178.5",
                    "averagePurchasePrice": "155.3",
                    "marketValue": {
                        "purchaseAmount": "1553",
                        "amount": "1785",
                        "amountAfterCost": "1771.43",
                    },
                    "profitLoss": {
                        "amount": "232",
                        "amountAfterCost": "218.43",
                        "rate": "0.1494",
                        "rateAfterCost": "0.1406",
                    },
                    "dailyProfitLoss": {"amount": "25", "rate": "0.0142"},
                    "cost": {"commission": "3.57", "tax": "10"},
                },
            ],
        }
    }


class TossHoldingsReadonlyTests(TestCase):
    def create_user(self, username: str = "user-alpha"):
        return get_user_model().objects.create_user(username=username, password="safe-password")

    def create_active_credential(self, username: str = "user-alpha"):
        user = self.create_user(username)
        account_suffix = username.removeprefix("user-")
        credential = register_or_replace_pending_credential(
            user=user,
            client_id=f"dummy-client-{username}",
            client_secret=f"dummy-secret-{username}",
        )
        credential = mark_credential_verification_success(
            credential=credential,
            account_ref=f"dummy-account-ref-{account_suffix}",
            account_masked=f"dummy-account-no-{account_suffix}",
        )
        return user, credential

    def store_access_token(self, credential, token: str = "dummy-access-token-alpha"):
        encrypted = encrypt_text(token)
        credential.access_token_ciphertext = encrypted.ciphertext
        credential.access_token_key_version = encrypted.key_version
        credential.access_token_type = "Bearer"
        credential.access_token_issued_at = timezone.now()
        credential.access_token_expires_at = timezone.now() + timedelta(hours=1)
        credential.save()
        return credential

    @holdings_settings()
    def test_normalize_successful_holdings_response(self):
        preview = normalize_holdings_response(
            sample_holdings_response(),
            user_id=1,
            credential_id=2,
            provider="toss_invest",
            account_masked="acct_****lpha",
            status="active",
        )

        self.assertEqual(preview.item_count, 2)
        self.assertEqual(str(preview.summary.total_purchase_amount.krw), "6500000")
        self.assertEqual(preview.items[0].symbol, "005930")
        self.assertEqual(preview.items[1].market_country, "US")
        safe = preview.safe_dict()
        self.assertEqual(safe["summary"]["profit_loss_rate"], "0.1179")
        self.assertEqual(safe["items"][0]["quantity"], "100")
        rendered = str(safe)
        self.assertNotIn("dummy-access-token-alpha", rendered)
        self.assertNotIn("dummy-account-ref-alpha", rendered)
        self.assertNotIn("Authorization", rendered)

    @holdings_settings()
    def test_fetch_holdings_success_and_no_userholding_write(self):
        user, credential = self.create_active_credential()
        holding_model = apps.get_model("holdings", "User" + "Holding")
        before_count = holding_model.objects.count()

        preview = fetch_user_toss_holdings_preview(user=user, transport=FakeHoldingsTransport())

        credential.refresh_from_db()
        self.assertEqual(preview.item_count, 2)
        self.assertEqual(preview.account_masked, "acct_****lpha")
        self.assertTrue(credential.access_token_ciphertext)
        self.assertEqual(holding_model.objects.count(), before_count)
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                credential=credential,
                action=IntegrationAuditLog.ACTION_HOLDINGS_SYNC,
                success=True,
            ).exists()
        )
        rendered = f"{preview!r} {preview.safe_dict()}"
        self.assertNotIn("dummy-access-token-alpha", rendered)
        self.assertNotIn("dummy-account-ref-alpha", rendered)
        self.assertNotIn("dummy-account-no-alpha", rendered)
        self.assertNotIn("Authorization", rendered)

    @holdings_settings()
    def test_get_headers_are_used_only_in_transport(self):
        user, _credential = self.create_active_credential()
        transport = FakeHoldingsTransport()

        preview = fetch_user_toss_holdings_preview(user=user, transport=transport)

        call = transport.get_json_calls[0]
        self.assertEqual(call["path"], HOLDINGS_PATH)
        self.assertEqual(call["headers"]["Authorization"], "Bearer dummy-access-token-alpha")
        self.assertEqual(call["headers"]["X-Tossinvest-Account"], "dummy-account-ref-alpha")
        rendered = str(preview.safe_dict())
        self.assertNotIn("dummy-access-token-alpha", rendered)
        self.assertNotIn("dummy-account-ref-alpha", rendered)

    @holdings_settings()
    def test_optional_symbol_path_and_validation(self):
        user, _credential = self.create_active_credential()
        transport = FakeHoldingsTransport()

        fetch_user_toss_holdings_preview(user=user, symbol="005930", transport=transport)

        self.assertEqual(transport.get_json_calls[0]["path"], f"{HOLDINGS_PATH}?symbol=005930")

        invalid_transport = FakeHoldingsTransport()
        with self.assertRaises(TossHoldingsReadonlyValidationError) as ctx:
            fetch_user_toss_holdings_preview(user=user, symbol="005930/evil", transport=invalid_transport)
        self.assertEqual(invalid_transport.get_json_calls, [])
        self.assertEqual(invalid_transport.post_form_calls, [])
        self.assertNotIn("005930/evil", str(ctx.exception))

    @holdings_settings()
    def test_empty_holdings_success(self):
        user, _credential = self.create_active_credential()
        transport = FakeHoldingsTransport(holdings_responses=[(200, sample_holdings_response(items=[]))])

        preview = fetch_user_toss_holdings_preview(user=user, transport=transport)

        self.assertEqual(preview.item_count, 0)
        self.assertEqual(preview.items, [])
        self.assertEqual(str(preview.summary.market_value_amount.krw), "7200000")

    @holdings_settings()
    def test_unauthorized_first_attempt_retries_with_force_refresh_once(self):
        user, credential = self.create_active_credential()
        self.store_access_token(credential, token="dummy-access-token-stale")
        transport = FakeHoldingsTransport(
            token_body={
                "access_token": "dummy-access-token-beta",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
            holdings_responses=[(401, {}), (200, sample_holdings_response())],
        )

        preview = fetch_user_toss_holdings_preview(user=user, transport=transport)

        credential.refresh_from_db()
        self.assertEqual(preview.item_count, 2)
        self.assertEqual(len(transport.get_json_calls), 2)
        self.assertEqual(len(transport.post_form_calls), 1)
        self.assertEqual(transport.get_json_calls[0]["headers"]["Authorization"], "Bearer dummy-access-token-stale")
        self.assertEqual(transport.get_json_calls[1]["headers"]["Authorization"], "Bearer dummy-access-token-beta")
        self.assertTrue(credential.access_token_ciphertext)
        self.assertTrue(
            IntegrationAuditLog.objects.filter(action=IntegrationAuditLog.ACTION_HOLDINGS_SYNC, success=True).exists()
        )

    @holdings_settings()
    def test_repeated_auth_failure_is_safe_and_keeps_credential_active(self):
        user, credential = self.create_active_credential()
        self.store_access_token(credential)
        transport = FakeHoldingsTransport(holdings_responses=[(401, {}), (403, {})])

        with self.assertRaises(TossHoldingsReadonlyAuthError) as ctx:
            fetch_user_toss_holdings_preview(user=user, transport=transport)

        credential.refresh_from_db()
        self.assertEqual(credential.status, STATUS_ACTIVE)
        self.assertIsNone(credential.access_token_ciphertext)
        self.assertNotIn("dummy-access-token-alpha", str(ctx.exception))
        self.assertTrue(
            IntegrationAuditLog.objects.filter(
                credential=credential,
                action=IntegrationAuditLog.ACTION_HOLDINGS_SYNC,
                success=False,
                reason_code="auth",
            ).exists()
        )

    @holdings_settings()
    def test_transient_failures_keep_active_credential(self):
        for name, transport in {
            "rate": FakeHoldingsTransport(holdings_responses=[(429, {})]),
            "server": FakeHoldingsTransport(holdings_responses=[(500, {})]),
            "network": FakeHoldingsTransport(holdings_error=TimeoutError()),
        }.items():
            with self.subTest(name=name):
                user, credential = self.create_active_credential(f"user-{name}")

                with self.assertRaises(TossHoldingsReadonlyTransientError):
                    fetch_user_toss_holdings_preview(user=user, transport=transport)

                credential.refresh_from_db()
                self.assertEqual(credential.status, STATUS_ACTIVE)
                self.assertTrue(credential.client_id_ciphertext)
                self.assertTrue(credential.account_ref_ciphertext)

    @holdings_settings()
    def test_malformed_body_parse_errors_are_safe(self):
        user, _credential = self.create_active_credential()
        bad_bodies = [
            {},
            {"result": []},
            {"result": {"items": {}}},
            sample_holdings_response(items=[{"symbol": "005930", "quantity": "not-a-number"}]),
        ]

        for body in bad_bodies:
            with self.subTest(body=body):
                with self.assertRaises(TossHoldingsReadonlyParseError) as ctx:
                    fetch_user_toss_holdings_preview(
                        user=user,
                        transport=FakeHoldingsTransport(holdings_responses=[(200, body)]),
                    )
                self.assertNotIn("not-a-number", str(ctx.exception))

    @holdings_settings()
    def test_not_active_permission_and_decryption_context_errors_are_safe(self):
        user, credential = self.create_active_credential()
        credential.status = "pending_verification"
        credential.save()
        transport = FakeHoldingsTransport()
        with self.assertRaises(TossHoldingsReadonlyStateError):
            fetch_user_toss_holdings_preview(user=user, transport=transport)
        self.assertEqual(transport.get_json_calls, [])

        user, credential = self.create_active_credential("owner-alpha")
        other = self.create_user("other-alpha")
        with self.assertRaises(TossHoldingsReadonlyStateError):
            fetch_user_toss_holdings_preview(user=user, actor=other, transport=FakeHoldingsTransport())

        credential.account_ref_ciphertext = "invalid-ciphertext"
        credential.status = STATUS_ACTIVE
        credential.save()
        with self.assertRaises(TossHoldingsReadonlyStateError) as ctx:
            fetch_user_toss_holdings_preview(user=user, transport=FakeHoldingsTransport())
        self.assertNotIn("invalid-ciphertext", str(ctx.exception))

    @holdings_settings()
    def test_safe_dict_wrapper(self):
        user, _credential = self.create_active_credential()

        payload = fetch_user_toss_holdings_preview_safe_dict(user=user, transport=FakeHoldingsTransport())

        self.assertEqual(payload["item_count"], 2)
        self.assertIn("summary", payload)
        self.assertIn("items", payload)
        rendered = str(payload)
        self.assertNotIn("dummy-access-token-alpha", rendered)
        self.assertNotIn("dummy-account-ref-alpha", rendered)
        self.assertNotIn("dummy-account-no-alpha", rendered)
        self.assertNotIn("accountSeq", rendered)

    @holdings_settings()
    def test_audit_safety(self):
        user, _credential = self.create_active_credential()

        fetch_user_toss_holdings_preview(user=user, transport=FakeHoldingsTransport())

        for log in IntegrationAuditLog.objects.filter(action=IntegrationAuditLog.ACTION_HOLDINGS_SYNC):
            rendered = f"{log.safe_summary} {log.safe_metadata}"
            self.assertNotIn("dummy-access-token-alpha", rendered)
            self.assertNotIn("dummy-secret", rendered)
            self.assertNotIn("Authorization", rendered)
            self.assertNotIn("X-Tossinvest-Account", rendered)
            self.assertNotIn("dummy-account-ref-alpha", rendered)
            self.assertNotIn("dummy-account-no-alpha", rendered)
            self.assertNotIn("raw_response", rendered)
            self.assertNotIn("items", rendered)

    @holdings_settings()
    def test_source_has_no_global_legacy_provider_or_holdings_imports(self):
        from integrations.services import toss_holdings_readonly

        source = inspect.getsource(toss_holdings_readonly)
        self.assertNotIn("TOSS_INVEST_CLIENT_ID", source)
        self.assertNotIn("TOSS_INVEST_CLIENT_SECRET", source)
        self.assertNotIn("TOSS_INVEST_ACCOUNT_ID", source)
        self.assertNotIn("data_pipeline." + "providers", source)
        self.assertNotIn("holdings." + "models", source)
        self.assertNotIn("portfolio." + "models", source)

    @holdings_settings()
    def test_api_calls_disabled_blocks_before_transport(self):
        user, _credential = self.create_active_credential()
        transport = FakeHoldingsTransport()

        with override_settings(TOSS_USER_TOSS_API_CALLS_ENABLED=False):
            with self.assertRaises(TossHoldingsReadonlyStateError):
                fetch_user_toss_holdings_preview(user=user, transport=transport)

        self.assertEqual(transport.post_form_calls, [])
        self.assertEqual(transport.get_json_calls, [])
