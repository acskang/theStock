import time
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError
from django.test import Client, TestCase
from django.test.utils import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient

from decisions.services.consulting_service import consult_holding
from holdings.models import UserHolding
from marketdata.models import DailyPrice, InvestorFlow, MarketIndex
from marketdata.services.source_resolution import ProviderSymbolResolution
from stocks.models import Stock

from .dataclasses import DailyPriceRow, FinancialSnapshotRow, IngestionReport, InvestorFlowRow, MarketIndexRow, RiskEventRow
from .admin import DataIngestionLogAdmin
from .models import DataIngestionLog, DataProviderStatus, DataQualitySnapshot
from .providers import get_provider
from .providers.disclosure_provider import DisclosureProvider
from .providers.finance_provider import FinanceProvider
from .providers.financial_statement_provider import FinancialStatementProvider
from .providers.krx_provider import KRXProvider
from .providers.toss_auth import (
    TossToken,
    get_toss_base_url,
    get_toss_token_url,
    is_toss_provider_enabled,
    issue_toss_access_token,
    validate_toss_auth_settings,
)
from .providers.toss_client import TossApiResponse, TossOpenApiClient
from .providers.toss_exceptions import (
    TossAuthError,
    TossConfigurationError,
    TossOpenApiError,
    TossOrderExecutionDisabled,
    TossProviderDisabled,
    TossRateLimitError,
)
from .providers.toss_masking import is_configured, mask_account_id, mask_secret
from .providers.toss_order_guard import ensure_toss_order_execution_enabled, is_toss_order_execution_enabled
from .providers.toss_provider import TossOpenApiProvider
from .services.data_quality_service import convert_data_quality_grade
from .services.ingestion_log_writer import record_data_ingestion_log
from .services.order_history_reconciliation_service import (
    OrderHistoryReconciliationError,
    build_order_history_reconciliation,
)

User = get_user_model()


def _fake_toss_daily_price_result(*, symbol="005930", market="KR"):
    return {
        "provider": "toss",
        "symbol": symbol,
        "market": market,
        "endpoint": "/api/v1/candles",
        "interval": "1d",
        "adjusted": True,
        "dry_run": True,
        "raw": {"result_count": 1, "next_before": None},
        "candidates": [
            {
                "symbol": symbol,
                "market": market,
                "date": "2026-03-25",
                "timestamp": "2026-03-25T09:00:00+09:00",
                "open_price": "71600",
                "high_price": "72300",
                "low_price": "71500",
                "close_price": "72000",
                "volume": "3521000",
                "currency": "KRW",
                "source": "toss",
                "adjusted": True,
            }
        ],
    }


class TossProviderUtilityTests(TestCase):
    def test_toss_exception_classes_are_importable(self):
        exception_classes = [
            TossOpenApiError,
            TossConfigurationError,
            TossAuthError,
            TossRateLimitError,
            TossProviderDisabled,
            TossOrderExecutionDisabled,
        ]

        for exception_class in exception_classes:
            self.assertTrue(issubclass(exception_class, TossOpenApiError))

    def test_mask_secret_masks_empty_short_and_long_values(self):
        self.assertEqual(mask_secret(None), "")
        self.assertEqual(mask_secret(""), "")
        self.assertEqual(mask_secret("abcd"), "****")
        self.assertEqual(mask_secret("12345678"), "****")
        self.assertEqual(mask_secret("abcdefghijklmnop"), "abcd********mnop")

    def test_mask_account_id_masks_with_secret_rules(self):
        self.assertEqual(mask_account_id("abcdefghijklmnop"), "abcd********mnop")

    def test_is_configured_checks_non_blank_values(self):
        self.assertFalse(is_configured(None))
        self.assertFalse(is_configured(""))
        self.assertFalse(is_configured("   "))
        self.assertTrue(is_configured("abc"))

    def test_toss_order_guard_blocks_when_disabled(self):
        disabled_values = [False, "false", "False", "0", 0, None]

        for disabled_value in disabled_values:
            with self.subTest(value=disabled_value):
                with override_settings(TOSS_ORDER_EXECUTION_ENABLED=disabled_value):
                    with self.assertRaises(TossOrderExecutionDisabled):
                        ensure_toss_order_execution_enabled()

    def test_toss_order_guard_allows_when_enabled(self):
        enabled_values = [True, "true", "True", "1", 1]

        for enabled_value in enabled_values:
            with self.subTest(value=enabled_value):
                with override_settings(TOSS_ORDER_EXECUTION_ENABLED=enabled_value):
                    ensure_toss_order_execution_enabled()

    def test_is_toss_order_execution_enabled_parses_expected_values(self):
        self.assertFalse(is_toss_order_execution_enabled(False))
        self.assertFalse(is_toss_order_execution_enabled("0"))
        self.assertFalse(is_toss_order_execution_enabled(None))
        self.assertTrue(is_toss_order_execution_enabled(True))
        self.assertTrue(is_toss_order_execution_enabled("1"))

    def test_toss_token_repr_masks_access_token(self):
        token = TossToken(
            access_token="fake_access_token_value_for_test_only",
            token_type="Bearer",
            expires_in=3600,
            issued_at=1000.0,
        )

        token_repr = repr(token)

        self.assertNotIn("fake_access_token_value_for_test_only", token_repr)
        self.assertIn("fake********only", token_repr)

    def test_toss_token_expiration_uses_skew(self):
        token = TossToken(
            access_token="fake_access_token_value_for_test_only",
            token_type="Bearer",
            expires_in=100,
            issued_at=time.time() - 50,
        )

        self.assertFalse(token.is_expired(skew_seconds=10))
        self.assertTrue(token.is_expired(skew_seconds=60))

    def test_is_toss_provider_enabled_parses_expected_values(self):
        enabled_values = [True, 1, "1", "true", "True", "yes", "on"]
        disabled_values = [False, 0, "0", "false", "False", None, "", "   "]

        for enabled_value in enabled_values:
            with self.subTest(value=enabled_value):
                self.assertTrue(is_toss_provider_enabled(enabled_value))
        for disabled_value in disabled_values:
            with self.subTest(value=disabled_value):
                self.assertFalse(is_toss_provider_enabled(disabled_value))

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=False)
    def test_validate_toss_auth_settings_blocks_disabled_provider(self):
        with self.assertRaises(TossProviderDisabled):
            validate_toss_auth_settings()

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="",
        TOSS_INVEST_CLIENT_SECRET="fake_client_secret",
    )
    def test_validate_toss_auth_settings_requires_client_id(self):
        with self.assertRaises(TossConfigurationError):
            validate_toss_auth_settings()

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="fake_client_id",
        TOSS_INVEST_CLIENT_SECRET="",
    )
    def test_validate_toss_auth_settings_requires_client_secret(self):
        with self.assertRaises(TossConfigurationError) as context:
            validate_toss_auth_settings()

        self.assertNotIn("fake_client_secret", str(context.exception))

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="fake_client_id",
        TOSS_INVEST_CLIENT_SECRET="fake_client_secret",
    )
    def test_issue_toss_access_token_requires_transport(self):
        with self.assertRaises(TossConfigurationError):
            issue_toss_access_token()

    @override_settings(
        TOSS_INVEST_BASE_URL="https://openapi.tossinvest.com",
        TOSS_INVEST_TOKEN_URL="",
    )
    def test_get_toss_token_url_uses_official_default_path(self):
        self.assertEqual(get_toss_base_url(), "https://openapi.tossinvest.com")
        self.assertEqual(get_toss_token_url(), "https://openapi.tossinvest.com/oauth2/token")

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="fake_client_id",
        TOSS_INVEST_CLIENT_SECRET="fake_client_secret",
        TOSS_INVEST_TOKEN_URL="https://openapi.tossinvest.com/oauth2/token",
        TOSS_REQUEST_TIMEOUT_SECONDS=10,
    )
    def test_issue_toss_access_token_uses_fake_transport(self):
        calls = []

        def fake_transport(method, url, *, headers, data, timeout):
            calls.append(
                {
                    "method": method,
                    "url": url,
                    "headers": headers,
                    "data": data,
                    "timeout": timeout,
                }
            )
            return {
                "access_token": "fake_access_token_value_for_test_only",
                "token_type": "Bearer",
                "expires_in": 3600,
            }

        token = issue_toss_access_token(transport=fake_transport, now=lambda: 1000.0)

        self.assertEqual(token.access_token, "fake_access_token_value_for_test_only")
        self.assertEqual(token.token_type, "Bearer")
        self.assertEqual(token.expires_in, 3600)
        self.assertEqual(token.issued_at, 1000.0)
        self.assertEqual(calls[0]["method"], "POST")
        self.assertEqual(calls[0]["headers"], {"Content-Type": "application/x-www-form-urlencoded"})
        self.assertEqual(calls[0]["data"]["grant_type"], "client_credentials")
        self.assertEqual(calls[0]["data"]["client_id"], "fake_client_id")
        self.assertEqual(calls[0]["data"]["client_secret"], "fake_client_secret")

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="fake_client_id",
        TOSS_INVEST_CLIENT_SECRET="fake_client_secret",
    )
    def test_issue_toss_access_token_raises_auth_error_for_401(self):
        def fake_transport(_method, _url, *, headers, data, timeout):
            return {"status_code": 401, "error": "unauthorized"}

        with self.assertRaises(TossAuthError) as context:
            issue_toss_access_token(transport=fake_transport)

        message = str(context.exception)
        self.assertNotIn("fake_client_secret", message)
        self.assertNotIn("fake_access_token_value_for_test_only", message)

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="fake_client_id",
        TOSS_INVEST_CLIENT_SECRET="fake_client_secret",
    )
    def test_issue_toss_access_token_requires_access_token_in_response(self):
        def fake_transport(_method, _url, *, headers, data, timeout):
            return {"token_type": "Bearer", "expires_in": 3600}

        with self.assertRaises(TossAuthError) as context:
            issue_toss_access_token(transport=fake_transport)

        self.assertNotIn("fake_client_secret", str(context.exception))

    def _fake_toss_token(self):
        return TossToken(
            access_token="fake_access_token_value_for_test_only",
            token_type="Bearer",
            expires_in=3600,
            issued_at=1000.0,
        )

    def test_toss_openapi_client_can_be_created(self):
        client = TossOpenApiClient(
            base_url="https://openapi.tossinvest.com",
            token_provider=self._fake_toss_token,
            transport=lambda *args, **kwargs: {},
        )

        self.assertEqual(client.base_url, "https://openapi.tossinvest.com")

    def test_toss_openapi_client_builds_relative_urls(self):
        client = TossOpenApiClient(base_url="https://openapi.tossinvest.com", token_provider=self._fake_toss_token)

        self.assertEqual(client.build_url("/api/v1/prices"), "https://openapi.tossinvest.com/api/v1/prices")
        self.assertEqual(client.build_url("api/v1/prices"), "https://openapi.tossinvest.com/api/v1/prices")

    def test_toss_openapi_client_rejects_absolute_url(self):
        client = TossOpenApiClient(base_url="https://openapi.tossinvest.com", token_provider=self._fake_toss_token)

        with self.assertRaises(TossConfigurationError):
            client.build_url("https://evil.example.com/path")

    def test_toss_openapi_client_builds_authorization_header(self):
        client = TossOpenApiClient(base_url="https://openapi.tossinvest.com", token_provider=self._fake_toss_token)

        headers = client.build_headers(extra_headers={"Authorization": "ignored", "X-Trace-ID": "trace"})

        self.assertEqual(headers["Authorization"], "Bearer " + "fake_access_token_value_for_test_only")
        self.assertEqual(headers["X-Trace-ID"], "trace")
        self.assertNotEqual(headers["Authorization"], "ignored")

    @override_settings(TOSS_INVEST_ACCOUNT_ID="")
    def test_toss_openapi_client_requires_account_id_when_needed(self):
        client = TossOpenApiClient(base_url="https://openapi.tossinvest.com", token_provider=self._fake_toss_token)

        with self.assertRaises(TossConfigurationError) as context:
            client.build_headers(account_required=True)

        self.assertNotIn("fake_account_id_for_test_only", str(context.exception))

    @override_settings(TOSS_INVEST_ACCOUNT_ID="fake_account_id_for_test_only")
    def test_toss_openapi_client_builds_account_header(self):
        client = TossOpenApiClient(base_url="https://openapi.tossinvest.com", token_provider=self._fake_toss_token)

        headers = client.build_headers(
            extra_headers={"X-Tossinvest-Account": "ignored"},
            account_required=True,
        )

        self.assertEqual(headers["X-Tossinvest-Account"], "fake_account_id_for_test_only")
        self.assertNotEqual(headers["X-Tossinvest-Account"], "ignored")

    def test_toss_openapi_client_request_requires_transport(self):
        client = TossOpenApiClient(base_url="https://openapi.tossinvest.com", token_provider=self._fake_toss_token)

        with self.assertRaises(TossConfigurationError):
            client.request("GET", "/api/v1/prices")

    def test_toss_openapi_client_request_normalizes_dict_response(self):
        calls = []

        def fake_transport(method, url, *, headers, params, data, json, timeout):
            calls.append({"method": method, "url": url, "headers": headers, "params": params})
            return {"prices": [{"symbol": "005930"}]}

        client = TossOpenApiClient(
            base_url="https://openapi.tossinvest.com",
            token_provider=self._fake_toss_token,
            transport=fake_transport,
        )

        response = client.request("GET", "/api/v1/prices", params={"symbol": "005930"})

        self.assertIsInstance(response, TossApiResponse)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["prices"][0]["symbol"], "005930")
        self.assertEqual(calls[0]["headers"]["Authorization"], "Bearer " + "fake_access_token_value_for_test_only")

    def test_toss_openapi_client_raises_auth_error_for_401_and_403(self):
        for status_code in (401, 403):
            with self.subTest(status_code=status_code):
                client = TossOpenApiClient(
                    base_url="https://openapi.tossinvest.com",
                    token_provider=self._fake_toss_token,
                    transport=lambda *args, **kwargs: {"status_code": status_code, "error": "auth"},
                )

                with self.assertRaises(TossAuthError) as context:
                    client.request("GET", "/api/v1/prices")

                message = str(context.exception)
                self.assertNotIn("fake_access_token_value_for_test_only", message)
                self.assertNotIn("fake_account_id_for_test_only", message)

    def test_toss_openapi_client_raises_rate_limit_error_for_429(self):
        client = TossOpenApiClient(
            base_url="https://openapi.tossinvest.com",
            token_provider=self._fake_toss_token,
            transport=lambda *args, **kwargs: {"status_code": 429, "error": "rate_limited"},
        )

        with self.assertRaises(TossRateLimitError):
            client.request("GET", "/api/v1/prices")

    def test_toss_openapi_client_raises_openapi_error_for_500(self):
        client = TossOpenApiClient(
            base_url="https://openapi.tossinvest.com",
            token_provider=self._fake_toss_token,
            transport=lambda *args, **kwargs: {"status_code": 500, "error": "server"},
        )

        with self.assertRaises(TossOpenApiError) as context:
            client.request("GET", "/api/v1/prices")

        self.assertNotIn("fake_access_token_value_for_test_only", str(context.exception))

    def test_toss_openapi_client_preserves_safe_error_detail(self):
        client = TossOpenApiClient(
            base_url="https://openapi.tossinvest.com",
            token_provider=self._fake_toss_token,
            transport=lambda *args, **kwargs: {
                "status_code": 400,
                "data": {
                    "error": {
                        "code": "invalid-request",
                        "field": "X-Tossinvest-Account",
                        "message": "fake_account_seq_for_test_only",
                    }
                },
            },
        )

        with self.assertRaises(TossOpenApiError) as context:
            client.request("GET", "/api/v1/holdings", account_required=True, account_id="fake_account_seq_for_test_only")

        exc = context.exception
        self.assertEqual(exc.http_status_code, 400)
        self.assertEqual(exc.error_code, "invalid-request")
        self.assertEqual(exc.error_field, "")
        self.assertEqual(exc.safe_message, "")
        self.assertNotIn("fake_account_seq_for_test_only", str(exc))

    def test_toss_openapi_client_health_check_does_not_call_network(self):
        called = False

        def fake_transport(*args, **kwargs):
            nonlocal called
            called = True
            return {}

        client = TossOpenApiClient(
            base_url="https://openapi.tossinvest.com",
            token_provider=self._fake_toss_token,
            transport=fake_transport,
        )

        result = client.health_check()

        self.assertEqual(result["provider"], "toss")
        self.assertEqual(result["status"], "configured")
        self.assertTrue(result["transport_configured"])
        self.assertFalse(called)

    def test_toss_api_response_repr_masks_sensitive_headers(self):
        response = TossApiResponse(
            status_code=200,
            data={"ok": True},
            headers={
                "Authorization": "Bearer " + "fake_access_token_value_for_test_only",
                "X-Tossinvest-Account": "fake_account_id_for_test_only",
            },
        )

        response_repr = repr(response)

        self.assertNotIn("fake_access_token_value_for_test_only", response_repr)
        self.assertNotIn("fake_account_id_for_test_only", response_repr)

    def test_toss_openapi_provider_can_be_created(self):
        provider = TossOpenApiProvider(client=self._fake_toss_client())

        self.assertEqual(provider.name, "toss")
        self.assertEqual(provider.provider_name, "toss")

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=False)
    def test_toss_openapi_provider_disabled_by_default(self):
        provider = TossOpenApiProvider(client=self._fake_toss_client())

        self.assertFalse(provider.is_enabled())

    def test_toss_openapi_provider_enabled_parsing(self):
        enabled_values = [True, "true", "1", "yes", "on"]
        disabled_values = [False, "false", "0", None, "", "   "]

        for enabled_value in enabled_values:
            with self.subTest(value=enabled_value):
                with override_settings(TOSS_INVEST_PROVIDER_ENABLED=enabled_value):
                    self.assertTrue(TossOpenApiProvider(client=self._fake_toss_client()).is_enabled())

        for disabled_value in disabled_values:
            with self.subTest(value=disabled_value):
                with override_settings(TOSS_INVEST_PROVIDER_ENABLED=disabled_value):
                    self.assertFalse(TossOpenApiProvider(client=self._fake_toss_client()).is_enabled())

    def test_toss_openapi_provider_capabilities_are_safe(self):
        capabilities = TossOpenApiProvider(client=self._fake_toss_client()).capabilities()

        self.assertEqual(
            set(capabilities),
            {
                "auth",
                "health_check",
                "quote",
                "daily_price",
                "holdings",
                "order_history",
                "orders",
                "order_execution",
            },
        )
        self.assertTrue(capabilities["auth"])
        self.assertTrue(capabilities["health_check"])
        self.assertTrue(capabilities["quote"])
        self.assertTrue(capabilities["order_history"])
        self.assertFalse(capabilities["orders"])
        self.assertFalse(capabilities["order_execution"])

        with override_settings(TOSS_ORDER_EXECUTION_ENABLED=True):
            self.assertFalse(TossOpenApiProvider(client=self._fake_toss_client()).capabilities()["order_execution"])

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=False)
    def test_toss_openapi_provider_health_check_disabled_without_network(self):
        client = self._fake_toss_client()
        provider = TossOpenApiProvider(client=client)

        result = provider.health_check()

        self.assertEqual(result["provider"], "toss")
        self.assertEqual(result["status"], "disabled")
        self.assertFalse(result["enabled"])
        self.assertFalse(client.called)

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="",
        TOSS_INVEST_CLIENT_SECRET="",
    )
    def test_toss_openapi_provider_health_check_reports_misconfigured(self):
        provider = TossOpenApiProvider(client=self._fake_toss_client())

        result = provider.health_check()

        self.assertEqual(result["status"], "misconfigured")
        self.assertFalse(result["client_id_configured"])
        self.assertFalse(result["client_secret_configured"])

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="fake_client_id",
        TOSS_INVEST_CLIENT_SECRET="fake_client_secret",
        TOSS_INVEST_ACCOUNT_ID="fake_account_id_for_test_only",
    )
    def test_toss_openapi_provider_health_check_reports_configured_without_secrets(self):
        provider = TossOpenApiProvider(client=self._fake_toss_client())

        result = provider.health_check()
        result_repr = repr(result)

        self.assertEqual(result["status"], "configured")
        self.assertTrue(result["client_id_configured"])
        self.assertTrue(result["client_secret_configured"])
        self.assertTrue(result["account_id_configured"])
        self.assertNotIn("fake_client_secret", result_repr)
        self.assertNotIn("fake_account_id_for_test_only", result_repr)
        self.assertNotIn("fake_access_token_value_for_test_only", result_repr)

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True)
    def test_toss_openapi_provider_get_quote_returns_normalized_read_only_result(self):
        before_count = DataIngestionLog.objects.count()
        client = self._fake_toss_client(
            {
                "result": [
                    {
                        "symbol": "005930",
                        "timestamp": "2026-03-25T09:30:00.123+09:00",
                        "lastPrice": "72000",
                        "currency": "KRW",
                        "client_secret": "fake_client_secret_for_test_only",
                        "access_token": "fake_access_token_for_test_only",
                    }
                ],
            }
        )
        provider = TossOpenApiProvider(client=client)

        result = provider.get_quote("005930", market="KR")
        result_repr = repr(result)

        self.assertEqual(result["provider"], "toss")
        self.assertEqual(result["symbol"], "005930")
        self.assertEqual(result["market"], "KR")
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["normalized"]["symbol"], "005930")
        self.assertEqual(result["normalized"]["price"], "72000")
        self.assertEqual(result["normalized"]["currency"], "KRW")
        self.assertEqual(result["normalized"]["as_of"], "2026-03-25T09:30:00.123+09:00")
        self.assertEqual(result["raw"], {"result_count": 1, "matched_symbol": True})
        self.assertEqual(client.calls[0]["method"], "GET")
        self.assertEqual(client.calls[0]["path"], "/api/v1/prices")
        self.assertEqual(client.calls[0]["params"], {"symbols": "005930"})
        self.assertFalse(client.calls[0]["account_required"])
        self.assertEqual(DataIngestionLog.objects.count(), before_count)
        self.assertNotIn("fake_client_secret_for_test_only", result_repr)
        self.assertNotIn("fake_access_token_for_test_only", result_repr)
        self.assertNotIn("Authorization", result_repr)

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=False)
    def test_toss_openapi_provider_get_quote_blocks_disabled_provider_without_network(self):
        client = self._fake_toss_client()
        provider = TossOpenApiProvider(client=client)

        with self.assertRaises(TossProviderDisabled) as context:
            provider.get_quote("005930", market="KR")

        self.assertFalse(client.called)
        self.assertNotIn("fake_access_token_value_for_test_only", str(context.exception))

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True)
    def test_toss_openapi_provider_get_quote_rejects_invalid_symbols_without_network(self):
        invalid_symbols = ["", "005930,000660", "005930/evil", "https://example.com", "005930?x=1", "005 930"]

        for symbol in invalid_symbols:
            with self.subTest(symbol=symbol):
                client = self._fake_toss_client()
                provider = TossOpenApiProvider(client=client)

                with self.assertRaises(TossOpenApiError) as context:
                    provider.get_quote(symbol, market="KR")

                self.assertFalse(client.called)
                self.assertNotIn("fake_client_secret_for_test_only", str(context.exception))

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True)
    def test_toss_openapi_provider_get_quote_falls_back_to_first_result_summary(self):
        client = self._fake_toss_client(
            {
                "result": [
                    {
                        "symbol": "000660",
                        "timestamp": "2026-03-25T09:30:00.123+09:00",
                        "lastPrice": 100000,
                        "currency": "KRW",
                    }
                ]
            }
        )
        provider = TossOpenApiProvider(client=client)

        result = provider.get_quote("005930", market="KR")

        self.assertEqual(result["normalized"]["symbol"], "000660")
        self.assertEqual(result["normalized"]["price"], "100000")
        self.assertEqual(result["raw"], {"result_count": 1, "matched_symbol": False})

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True)
    def test_toss_openapi_provider_get_daily_price_candidates_returns_read_only_rows(self):
        before_count = DataIngestionLog.objects.count()
        client = self._fake_toss_client(
            {
                "result": {
                    "candles": [
                        {
                            "timestamp": "2026-03-25T09:00:00+09:00",
                            "openPrice": "71600",
                            "highPrice": "72300",
                            "lowPrice": "71500",
                            "closePrice": "72000",
                            "volume": "3521000",
                            "currency": "KRW",
                            "client_secret": "fake_client_secret_for_test_only",
                            "access_token": "fake_access_token_for_test_only",
                        }
                    ],
                    "nextBefore": "2026-03-24T09:00:00+09:00",
                }
            }
        )
        provider = TossOpenApiProvider(client=client)

        result = provider.get_daily_price_candidates("005930", market="KR", count=2, adjusted=True)
        candidate = result["candidates"][0]
        result_repr = repr(result)

        self.assertEqual(result["provider"], "toss")
        self.assertEqual(result["endpoint"], "/api/v1/candles")
        self.assertEqual(result["interval"], "1d")
        self.assertTrue(result["adjusted"])
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["raw"], {"result_count": 1, "next_before": "2026-03-24T09:00:00+09:00"})
        self.assertEqual(result["model_mapping"]["model"], "DailyPrice")
        self.assertFalse(result["model_mapping"]["save_supported"])
        self.assertEqual(candidate["symbol"], "005930")
        self.assertEqual(candidate["market"], "KR")
        self.assertEqual(candidate["date"], "2026-03-25")
        self.assertEqual(candidate["timestamp"], "2026-03-25T09:00:00+09:00")
        self.assertEqual(candidate["open_price"], "71600")
        self.assertEqual(candidate["high_price"], "72300")
        self.assertEqual(candidate["low_price"], "71500")
        self.assertEqual(candidate["close_price"], "72000")
        self.assertEqual(candidate["volume"], "3521000")
        self.assertEqual(candidate["currency"], "KRW")
        self.assertEqual(candidate["source"], "toss")
        self.assertTrue(candidate["adjusted"])
        self.assertEqual(client.calls[0]["method"], "GET")
        self.assertEqual(client.calls[0]["path"], "/api/v1/candles")
        self.assertEqual(
            client.calls[0]["params"],
            {"symbol": "005930", "interval": "1d", "count": 2, "adjusted": "true"},
        )
        self.assertNotIn("symbols", client.calls[0]["params"])
        self.assertNotIn("before", client.calls[0]["params"])
        self.assertFalse(client.calls[0]["account_required"])
        self.assertEqual(DataIngestionLog.objects.count(), before_count)
        self.assertNotIn("candles", result["raw"])
        self.assertNotIn("fake_client_secret_for_test_only", result_repr)
        self.assertNotIn("fake_access_token_for_test_only", result_repr)
        self.assertNotIn("Authorization", result_repr)

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True)
    def test_toss_openapi_provider_get_daily_price_candidates_accepts_before(self):
        client = self._fake_toss_client({"result": {"candles": [], "nextBefore": None}})
        provider = TossOpenApiProvider(client=client)

        provider.get_daily_price_candidates("005930", market="KR", count=1, before="2026-03-24T09:00:00+09:00")

        self.assertEqual(
            client.calls[0]["params"],
            {
                "symbol": "005930",
                "interval": "1d",
                "count": 1,
                "adjusted": "true",
                "before": "2026-03-24T09:00:00+09:00",
            },
        )

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True)
    def test_toss_openapi_provider_get_daily_price_candidates_sends_adjusted_false_as_lowercase_string(self):
        client = self._fake_toss_client({"result": {"candles": [], "nextBefore": None}})
        provider = TossOpenApiProvider(client=client)

        provider.get_daily_price_candidates("005930", market="KR", count=1, adjusted=False)

        self.assertEqual(client.calls[0]["params"]["adjusted"], "false")
        self.assertNotIn("symbols", client.calls[0]["params"])

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True)
    def test_toss_openapi_provider_get_daily_price_candidates_rejects_invalid_inputs_without_network(self):
        invalid_symbols = ["", "005930,000660", "005930/evil", "https://example.com", "005930?x=1", "005930 KR"]

        for symbol in invalid_symbols:
            with self.subTest(symbol=symbol):
                client = self._fake_toss_client()
                provider = TossOpenApiProvider(client=client)

                with self.assertRaises(TossOpenApiError):
                    provider.get_daily_price_candidates(symbol, market="KR")

                self.assertFalse(client.called)

        for count in (0, 201, "bad"):
            with self.subTest(count=count):
                client = self._fake_toss_client()
                provider = TossOpenApiProvider(client=client)

                with self.assertRaises(TossOpenApiError):
                    provider.get_daily_price_candidates("005930", market="KR", count=count)

                self.assertFalse(client.called)

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True)
    def test_toss_openapi_provider_get_accounts_returns_safe_summary(self):
        client = self._fake_toss_client(
            {
                "result": [
                    {
                        "accountNo": "fake_account_no_for_test_only",
                        "accountSeq": "fake_account_seq_for_test_only",
                        "accountType": "stock",
                    }
                ]
            }
        )
        provider = TossOpenApiProvider(client=client)

        result = provider.get_accounts()
        result_repr = repr(result)

        self.assertEqual(result["provider"], "toss")
        self.assertEqual(result["endpoint"], "/api/v1/accounts")
        self.assertEqual(result["account_count"], 1)
        self.assertEqual(result["accounts"][0]["account_type"], "stock")
        self.assertNotIn("fake_account_no_for_test_only", result_repr)
        self.assertNotIn("fake_account_seq_for_test_only", result_repr)
        self.assertEqual(client.calls[0]["method"], "GET")
        self.assertEqual(client.calls[0]["path"], "/api/v1/accounts")
        self.assertFalse(client.calls[0]["account_required"])

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True, TOSS_INVEST_ACCOUNT_ID="")
    def test_toss_openapi_provider_get_holdings_candidates_uses_accounts_lookup_and_normalizes(self):
        class FakeClient:
            def __init__(self):
                self.calls = []

            def request(self, method, path, *, params=None, account_required=False, account_id=None, **_kwargs):
                call = {
                    "method": method,
                    "path": path,
                    "params": params,
                    "account_required": account_required,
                }
                if account_id is not None:
                    call["account_id"] = account_id
                self.calls.append(call)
                if path == "/api/v1/accounts":
                    return TossApiResponse(
                        status_code=200,
                        data={
                            "result": [
                                {
                                    "accountNo": "fake_account_no_for_test_only",
                                    "accountSeq": "123456789",
                                    "accountType": "stock",
                                }
                            ]
                        },
                    )
                return TossApiResponse(
                    status_code=200,
                    data={
                        "result": {
                            "items": [
                                {
                                    "symbol": "005930",
                                    "name": "삼성전자",
                                    "marketCountry": "KR",
                                    "currency": "KRW",
                                    "quantity": "100",
                                    "lastPrice": "72000",
                                    "averagePurchasePrice": "65000",
                                    "marketValue": {
                                        "purchaseAmount": "6500000",
                                        "amount": "7200000",
                                        "amountAfterCost": "7199000",
                                    },
                                    "profitLoss": {
                                        "amount": "700000",
                                        "amountAfterCost": "699000",
                                        "rate": "0.1077",
                                        "rateAfterCost": "0.1075",
                                    },
                                    "dailyProfitLoss": {"amount": "100000", "rate": "0.0141"},
                                    "accountSeq": "123456789",
                                }
                            ]
                        }
                    },
                )

        client = FakeClient()
        provider = TossOpenApiProvider(client=client)

        result = provider.get_holdings_candidates(symbol="005930")
        candidate = result["candidates"][0]
        result_repr = repr(result)

        self.assertEqual(client.calls[0]["path"], "/api/v1/accounts")
        self.assertFalse(client.calls[0]["account_required"])
        self.assertEqual(client.calls[1]["path"], "/api/v1/holdings")
        self.assertTrue(client.calls[1]["account_required"])
        self.assertEqual(client.calls[1]["account_id"], "123456789")
        self.assertEqual(client.calls[1]["params"], {"symbol": "005930"})
        self.assertEqual(result["account"]["source"], "accounts_api_single")
        self.assertTrue(result["summary"]["account_diagnostic"]["account_fallback_used"])
        self.assertEqual(result["summary"]["item_count"], 1)
        self.assertTrue(result["summary"]["has_krw"])
        self.assertEqual(candidate["symbol"], "005930")
        self.assertEqual(candidate["name"], "삼성전자")
        self.assertEqual(candidate["market_country"], "KR")
        self.assertEqual(candidate["currency"], "KRW")
        self.assertEqual(candidate["quantity"], "100")
        self.assertEqual(candidate["average_purchase_price"], "65000")
        self.assertEqual(candidate["last_price"], "72000")
        self.assertEqual(candidate["purchase_amount"], "6500000")
        self.assertEqual(candidate["market_value"], "7200000")
        self.assertEqual(candidate["profit_loss_rate"], "0.1077")
        self.assertEqual(candidate["daily_profit_loss_amount"], "100000")
        self.assertEqual(candidate["daily_profit_loss_rate"], "0.0141")
        self.assertEqual(candidate["source"], "toss")
        self.assertEqual(result["model_mapping"]["model"], "UserHolding")
        self.assertFalse(result["model_mapping"]["save_supported"])
        self.assertNotIn("fake_account_no_for_test_only", result_repr)
        self.assertNotIn("123456789", result_repr)
        self.assertNotIn("Authorization", result_repr)

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True, TOSS_INVEST_ACCOUNT_ID="123456789")
    def test_toss_openapi_provider_get_holdings_candidates_uses_env_account_and_rejects_bad_symbol(self):
        client = self._fake_toss_client({"result": {"items": []}})
        provider = TossOpenApiProvider(client=client)

        result = provider.get_holdings_candidates()

        self.assertEqual(result["summary"]["item_count"], 0)
        self.assertEqual(client.calls[0]["path"], "/api/v1/holdings")
        self.assertTrue(client.calls[0]["account_required"])
        self.assertEqual(client.calls[0]["account_id"], "123456789")
        self.assertEqual(result["account"]["source"], "env")
        self.assertFalse(result["summary"]["account_diagnostic"]["account_fallback_used"])
        self.assertIsNone(client.calls[0]["params"])
        self.assertNotIn("123456789", repr(result))

        bad_client = self._fake_toss_client({"result": {"items": []}})
        bad_provider = TossOpenApiProvider(client=bad_client)
        with self.assertRaises(TossOpenApiError):
            bad_provider.get_holdings_candidates(symbol="005930/evil")
        self.assertFalse(bad_client.called)

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True, TOSS_INVEST_ACCOUNT_ID="fake_env_account_for_test_only")
    def test_toss_openapi_provider_get_holdings_candidates_falls_back_when_env_is_not_account_seq(self):
        class FakeClient:
            def __init__(self):
                self.calls = []

            def request(self, method, path, *, params=None, account_required=False, account_id=None, **_kwargs):
                self.calls.append(
                    {
                        "method": method,
                        "path": path,
                        "params": params,
                        "account_required": account_required,
                        "account_id": account_id,
                    }
                )
                if path == "/api/v1/accounts":
                    return TossApiResponse(
                        status_code=200,
                        data={
                            "result": [
                                {
                                    "accountNo": "fake_account_no_for_test_only",
                                    "accountSeq": "987654321",
                                    "accountType": "BROKERAGE",
                                }
                            ]
                        },
                    )
                return TossApiResponse(status_code=200, data={"result": {"items": []}})

        client = FakeClient()
        provider = TossOpenApiProvider(client=client)

        result = provider.get_holdings_candidates()
        result_repr = repr(result)

        self.assertEqual(client.calls[0]["path"], "/api/v1/accounts")
        self.assertFalse(client.calls[0]["account_required"])
        self.assertEqual(client.calls[1]["path"], "/api/v1/holdings")
        self.assertTrue(client.calls[1]["account_required"])
        self.assertEqual(client.calls[1]["account_id"], "987654321")
        self.assertEqual(result["account"]["source"], "accounts_api_single")
        diagnostic = result["summary"]["account_diagnostic"]
        self.assertEqual(diagnostic["account_env_shape"], "non_integer")
        self.assertTrue(diagnostic["accounts_api_called"])
        self.assertTrue(diagnostic["account_fallback_used"])
        self.assertNotIn("fake_env_account_for_test_only", result_repr)
        self.assertNotIn("fake_account_no_for_test_only", result_repr)
        self.assertNotIn("987654321", result_repr)

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True)
    def test_toss_openapi_provider_get_holdings_candidates_rejects_invalid_cli_account_without_fallback(self):
        client = self._fake_toss_client({"result": {"items": []}})
        provider = TossOpenApiProvider(client=client)

        with self.assertRaises(TossOpenApiError) as context:
            provider.get_holdings_candidates(account_id="fake_account_seq_for_test_only")

        exc = context.exception
        self.assertEqual(exc.safe_reason, "invalid_account_identifier")
        self.assertEqual(exc.account_diagnostic["selected_account_source"], "cli_invalid")
        self.assertFalse(client.called)

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True, TOSS_INVEST_ACCOUNT_ID="123456789")
    def test_toss_openapi_provider_get_order_history_candidates_normalizes_safely(self):
        client = self._fake_toss_client(
            {
                "result": {
                    "orders": [
                        {
                            "orderId": "abcd1234wxyz5678",
                            "clientOrderId": "client-order-raw",
                            "symbol": "035250",
                            "side": "BUY",
                            "orderType": "LIMIT",
                            "timeInForce": "DAY",
                            "status": "FILLED",
                            "price": "16000",
                            "quantity": "2",
                            "orderAmount": "32000",
                            "currency": "KRW",
                            "orderedAt": "2026-06-16T09:30:00+09:00",
                            "execution": {
                                "filledQuantity": "2",
                                "averageFilledPrice": "16000",
                                "filledAmount": "32000",
                                "commission": "64",
                                "tax": "0",
                                "filledAt": "2026-06-16T09:31:15+09:00",
                                "settlementDate": "2026-06-18",
                            },
                            "accountSeq": "123456789",
                        }
                    ],
                    "nextCursor": "cursor-raw-value",
                    "hasNext": True,
                }
            }
        )
        provider = TossOpenApiProvider(client=client)

        result = provider.get_order_history_candidates(
            status="CLOSED",
            symbol="035250",
            from_date="2026-06-01",
            to_date="2026-06-30",
            cursor="cursor-raw-value",
            limit=50,
        )
        order = result["orders"][0]
        result_repr = repr(result)

        self.assertEqual(client.calls[0]["method"], "GET")
        self.assertEqual(client.calls[0]["path"], "/api/v1/orders")
        self.assertTrue(client.calls[0]["account_required"])
        self.assertEqual(client.calls[0]["account_id"], "123456789")
        self.assertEqual(
            client.calls[0]["params"],
            {
                "status": "CLOSED",
                "symbol": "035250",
                "from": "2026-06-01",
                "to": "2026-06-30",
                "limit": 50,
                "cursor": "cursor-raw-value",
            },
        )
        self.assertEqual(result["endpoint"], "/api/v1/orders")
        self.assertEqual(result["status_filter"], "CLOSED")
        self.assertEqual(result["order_count"], 1)
        self.assertTrue(result["has_next"])
        self.assertTrue(result["next_cursor_present"])
        self.assertEqual(order["order_id_masked"], "abcd********5678")
        self.assertEqual(order["symbol"], "035250")
        self.assertEqual(order["order_type"], "LIMIT")
        self.assertEqual(order["execution"]["filled_quantity"], "2")
        self.assertEqual(order["execution"]["average_filled_price"], "16000")
        self.assertNotIn("orderId", order)
        self.assertNotIn("clientOrderId", result_repr)
        self.assertNotIn("client-order-raw", result_repr)
        self.assertNotIn("abcd1234wxyz5678", result_repr)
        self.assertNotIn("123456789", result_repr)
        self.assertNotIn("accountSeq", result_repr)
        self.assertNotIn("Authorization", result_repr)

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True, TOSS_INVEST_ACCOUNT_ID="123456789")
    def test_toss_openapi_provider_get_order_history_candidates_validates_inputs(self):
        provider = TossOpenApiProvider(client=self._fake_toss_client({"result": {"orders": []}}))

        invalid_kwargs = [
            {"status": "PENDING"},
            {"status": "CLOSED", "symbol": "035250/evil"},
            {"status": "CLOSED", "from_date": "20260601"},
            {"status": "CLOSED", "to_date": "2026-6-1"},
            {"status": "CLOSED", "limit": 0},
            {"status": "CLOSED", "limit": 101},
        ]
        for kwargs in invalid_kwargs:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(TossOpenApiError):
                    provider.get_order_history_candidates(**kwargs)

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True, TOSS_INVEST_ACCOUNT_ID="123456789")
    def test_toss_openapi_provider_get_order_history_candidates_open_omits_limit_and_cursor(self):
        client = self._fake_toss_client({"result": {"orders": [], "hasNext": False}})
        provider = TossOpenApiProvider(client=client)

        result = provider.get_order_history_candidates(status="OPEN", cursor="cursor-raw-value", limit=100)

        self.assertEqual(client.calls[0]["path"], "/api/v1/orders")
        self.assertEqual(client.calls[0]["params"], {"status": "OPEN"})
        self.assertEqual(result["status_filter"], "OPEN")
        self.assertEqual(result["order_count"], 0)

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True)
    def test_toss_openapi_provider_default_client_creation_does_not_call_network(self):
        with patch("data_pipeline.providers.toss_transport.urllib_json_transport") as mock_json_transport:
            provider = TossOpenApiProvider()

        self.assertIsNotNone(provider.client)
        mock_json_transport.assert_not_called()

    def test_toss_openapi_provider_is_registered_for_explicit_opt_in_without_network(self):
        with (
            patch("data_pipeline.providers.toss_provider.issue_toss_access_token") as mock_token,
            patch("data_pipeline.providers.toss_client.TossOpenApiClient.request") as mock_request,
        ):
            provider = get_provider("toss")

        self.assertIsInstance(provider, TossOpenApiProvider)
        mock_token.assert_not_called()
        mock_request.assert_not_called()

    @override_settings(DATA_PIPELINE_PROVIDER="mock", TOSS_INVEST_PROVIDER_ENABLED=True)
    def test_toss_registry_does_not_change_default_provider(self):
        provider = get_provider()

        self.assertEqual(provider.provider_name, "mock")

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True)
    def test_toss_enabled_does_not_change_auto_provider(self):
        provider = get_provider("auto")

        self.assertEqual(provider.provider_name, "auto")
        self.assertIsInstance(provider.finance_provider, FinanceProvider)
        self.assertFalse(hasattr(provider, "toss_provider"))

    def _fake_toss_client(self, response_data=None):
        class FakeTossClient:
            base_url = "https://openapi.tossinvest.com"

            def __init__(self, response_data):
                self.called = False
                self.calls = []
                self.response_data = response_data

            def health_check(self):
                return {
                    "provider": "toss",
                    "base_url": self.base_url,
                    "transport_configured": True,
                    "token_provider_configured": True,
                    "status": "configured",
                }

            def request(self, method, path, *, params=None, account_required=False, account_id=None, **kwargs):
                self.called = True
                self.calls.append(
                    {
                        "method": method,
                        "path": path,
                        "params": params,
                        "account_required": account_required,
                        "account_id": account_id,
                    }
                )
                if self.response_data is None:
                    raise AssertionError("Fake Toss client request should not be called.")
                return TossApiResponse(status_code=200, data=self.response_data)

        return FakeTossClient(response_data)


class DataPipelineModelTests(TestCase):
    def setUp(self):
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)

    def test_data_ingestion_log_keeps_existing_choices_and_supports_toss_choices(self):
        status_values = {value for value, _label in DataIngestionLog.STATUS_CHOICES}
        self.assertTrue(
            {
                DataIngestionLog.STATUS_STARTED,
                DataIngestionLog.STATUS_SUCCESS,
                DataIngestionLog.STATUS_PARTIAL,
                DataIngestionLog.STATUS_FAILED,
                DataIngestionLog.STATUS_SKIPPED,
            }.issubset(status_values)
        )

        target_type_values = {value for value, _label in DataIngestionLog.TARGET_TYPE_CHOICES}
        self.assertTrue(
            {
                DataIngestionLog.TARGET_STOCK,
                DataIngestionLog.TARGET_PRICE,
                DataIngestionLog.TARGET_FLOW,
                DataIngestionLog.TARGET_MARKET,
                DataIngestionLog.TARGET_RISK,
                DataIngestionLog.TARGET_FINANCIAL,
                DataIngestionLog.TARGET_QUALITY,
                DataIngestionLog.TARGET_PROVIDER_HEALTH,
                DataIngestionLog.TARGET_AUTH,
                DataIngestionLog.TARGET_QUOTE,
                DataIngestionLog.TARGET_SMOKE,
                DataIngestionLog.TARGET_DAILY_PRICE,
                DataIngestionLog.TARGET_HOLDINGS,
            }.issubset(target_type_values)
        )

    def test_data_ingestion_log_existing_create_path_remains_compatible(self):
        log = DataIngestionLog.objects.create(
            job_name="ingest_daily_prices",
            provider="mock",
            target_type=DataIngestionLog.TARGET_PRICE,
            target_code="005930",
            status=DataIngestionLog.STATUS_SUCCESS,
            started_at=timezone.now(),
            total_count=1,
            success_count=1,
        )

        self.assertEqual(log.job_type, "")
        self.assertEqual(log.provider_name, "")
        self.assertEqual(log.endpoint_name, "")
        self.assertEqual(log.target_symbol, "")
        self.assertIsNone(log.network_call)
        self.assertIsNone(log.dry_run)
        self.assertEqual(log.saved_count, 0)
        self.assertEqual(log.updated_count, 0)
        self.assertEqual(log.skipped_count, 0)
        self.assertEqual(log.failed_count, 0)
        self.assertEqual(log.candidate_count, 0)
        self.assertEqual(log.metadata, {})

    def test_data_ingestion_log_supports_safe_toss_operational_metadata(self):
        log = DataIngestionLog.objects.create(
            job_name="toss_daily_price_ingest_dryrun",
            job_type="ingestion",
            provider="toss",
            provider_name="toss",
            target_type=DataIngestionLog.TARGET_DAILY_PRICE,
            target_code="005930",
            target_symbol="005930",
            market="KR",
            endpoint_name="candles",
            status=DataIngestionLog.STATUS_SKIPPED,
            started_at=timezone.now(),
            finished_at=timezone.now(),
            total_count=1,
            skipped_count=1,
            candidate_count=1,
            saved_count=0,
            updated_count=0,
            network_call=False,
            dry_run=True,
            commit_mode="not_requested",
            safe_reason="no_network",
            error_code="",
            http_status_code=None,
            duration_ms=12,
            metadata={
                "command": "toss_daily_price_ingest_dryrun",
                "params_shape": "symbol,interval,count,adjusted",
            },
            details={"legacy_safe_detail": "kept_for_backward_compatibility"},
        )

        self.assertEqual(log.provider_name, "toss")
        self.assertEqual(log.target_type, DataIngestionLog.TARGET_DAILY_PRICE)
        self.assertEqual(log.status, DataIngestionLog.STATUS_SKIPPED)
        self.assertEqual(log.safe_reason, "no_network")
        self.assertEqual(log.duration_ms, 12)
        self.assertEqual(log.candidate_count, 1)
        self.assertEqual(log.metadata["params_shape"], "symbol,interval,count,adjusted")
        self.assertEqual(log.details["legacy_safe_detail"], "kept_for_backward_compatibility")
        forbidden_values = {
            "fake_client_secret_for_test_only",
            "fake_access_token_for_test_only",
            "fake_account_id_for_test_only",
            "Bearer fake_token",
        }
        serialized_values = " ".join(
            [
                log.error_message,
                log.safe_reason,
                log.error_code,
                str(log.metadata),
                str(log.details),
            ]
        )
        for value in forbidden_values:
            self.assertNotIn(value, serialized_values)

    def test_data_ingestion_log_admin_exposes_safe_operational_fields(self):
        model_admin = DataIngestionLogAdmin(DataIngestionLog, AdminSite())

        expected_list_fields = {
            "provider_name",
            "job_type",
            "target_symbol",
            "endpoint_name",
            "safe_reason",
            "network_call",
            "dry_run",
            "commit_mode",
            "candidate_count",
            "saved_count",
            "updated_count",
            "skipped_count",
            "failed_count",
            "http_status_code",
            "duration_ms",
            "created_at",
        }
        self.assertTrue(expected_list_fields.issubset(set(model_admin.list_display)))
        self.assertIn("metadata", model_admin.readonly_fields)
        self.assertIn("details", model_admin.readonly_fields)
        self.assertIn("safe_reason", model_admin.search_fields)
        self.assertIn("provider_name", model_admin.list_filter)

    def test_record_data_ingestion_log_creates_safe_daily_price_row(self):
        started_at = timezone.now()
        finished_at = started_at + timedelta(milliseconds=25)

        log = record_data_ingestion_log(
            provider_name="toss",
            job_type="ingestion",
            target_type=DataIngestionLog.TARGET_DAILY_PRICE,
            target_symbol="005930",
            market="KR",
            endpoint_name="candles",
            status=DataIngestionLog.STATUS_SUCCESS,
            network_call=True,
            dry_run=False,
            commit_mode="confirmed",
            candidate_count=1,
            saved_count=1,
            duration_ms=25,
            metadata={
                "command": "toss_daily_price_ingest_dryrun",
                "symbol": "005930",
                "market": "KR",
                "endpoint_name": "candles",
                "interval": "1d",
                "count": 1,
                "adjusted": True,
            },
            started_at=started_at,
            finished_at=finished_at,
        )

        self.assertIsNotNone(log)
        self.assertEqual(log.job_name, "toss_daily_price_ingest_dryrun")
        self.assertEqual(log.provider, "toss")
        self.assertEqual(log.provider_name, "toss")
        self.assertEqual(log.target_type, DataIngestionLog.TARGET_DAILY_PRICE)
        self.assertEqual(log.target_code, "005930")
        self.assertEqual(log.target_symbol, "005930")
        self.assertEqual(log.status, DataIngestionLog.STATUS_SUCCESS)
        self.assertTrue(log.network_call)
        self.assertFalse(log.dry_run)
        self.assertEqual(log.commit_mode, "confirmed")
        self.assertEqual(log.candidate_count, 1)
        self.assertEqual(log.total_count, 1)
        self.assertEqual(log.success_count, 1)
        self.assertEqual(log.saved_count, 1)
        self.assertEqual(log.updated_count, 0)
        self.assertEqual(log.skipped_count, 0)
        self.assertEqual(log.failed_count, 0)
        self.assertEqual(log.duration_ms, 25)
        self.assertEqual(log.metadata["interval"], "1d")

    def test_record_data_ingestion_log_maps_smoke_counts(self):
        log = record_data_ingestion_log(
            provider_name="toss",
            job_type="smoke",
            target_type=DataIngestionLog.TARGET_AUTH,
            endpoint_name="token",
            status=DataIngestionLog.STATUS_SKIPPED,
            safe_reason="no_network",
            network_call=False,
            dry_run=True,
            skipped_count=1,
            metadata={"command": "toss_token_smoke", "network_call": False, "dry_run": True},
        )

        self.assertEqual(log.status, DataIngestionLog.STATUS_SKIPPED)
        self.assertEqual(log.safe_reason, "no_network")
        self.assertEqual(log.total_count, 1)
        self.assertEqual(log.success_count, 0)
        self.assertEqual(log.skipped_count, 1)
        self.assertEqual(log.failed_count, 0)
        self.assertEqual(log.metadata["command"], "toss_token_smoke")

    def test_record_data_ingestion_log_normalizes_invalid_status_and_target_type(self):
        log = record_data_ingestion_log(
            provider_name="toss",
            job_type="smoke",
            target_type="not-a-target",
            endpoint_name="https://openapi.example.invalid/api/v1/prices?symbol=005930",
            status="not-a-status",
            http_status_code=999,
            duration_ms=-5,
            failed_count=-2,
        )

        self.assertEqual(log.status, DataIngestionLog.STATUS_FAILED)
        self.assertEqual(log.target_type, DataIngestionLog.TARGET_SMOKE)
        self.assertEqual(log.endpoint_name, "redacted")
        self.assertIsNone(log.http_status_code)
        self.assertEqual(log.duration_ms, 0)
        self.assertEqual(log.failed_count, 0)

    def test_record_data_ingestion_log_filters_sensitive_metadata_and_reason(self):
        token_value = "fake_access_token_for_test_" + "only"
        bearer_value = "Bearer " + token_value
        client_secret_value = "fake_client_secret_for_test_" + "only"
        account_id_value = "fake_account_id_for_test_" + "only"

        log = record_data_ingestion_log(
            provider_name="toss",
            job_type="smoke",
            target_type=DataIngestionLog.TARGET_QUOTE,
            target_symbol="005930",
            endpoint_name="prices",
            status=DataIngestionLog.STATUS_FAILED,
            safe_reason=bearer_value,
            error_code="client_secret=" + client_secret_value,
            metadata={
                "command": "toss_quote_smoke",
                "Authorization": bearer_value,
                "access_token": token_value,
                "account_id": account_id_value,
                "raw_response": {"access_token": token_value},
                "safe_message": bearer_value,
                "params_shape": "symbols",
            },
            details={
                "request_headers": {"Authorization": bearer_value},
                "safe_message": "client_secret=" + client_secret_value,
            },
        )

        serialized = " ".join(
            [
                log.safe_reason,
                log.error_code,
                log.error_message,
                str(log.metadata),
                str(log.details),
            ]
        )
        self.assertEqual(log.safe_reason, "redacted")
        self.assertEqual(log.error_code, "redacted")
        self.assertEqual(log.metadata["safe_message"], "redacted")
        self.assertEqual(log.details["safe_message"], "redacted")
        self.assertNotIn("Authorization", serialized)
        self.assertNotIn(token_value, serialized)
        self.assertNotIn(client_secret_value, serialized)
        self.assertNotIn(account_id_value, serialized)

    def test_record_data_ingestion_log_returns_none_on_error_by_default(self):
        with patch("data_pipeline.services.ingestion_log_writer.DataIngestionLog.objects.create") as mock_create:
            mock_create.side_effect = RuntimeError("db unavailable")

            log = record_data_ingestion_log(provider_name="toss")

        self.assertIsNone(log)

    def test_record_data_ingestion_log_can_raise_errors(self):
        with patch("data_pipeline.services.ingestion_log_writer.DataIngestionLog.objects.create") as mock_create:
            mock_create.side_effect = RuntimeError("db unavailable")

            with self.assertRaises(RuntimeError):
                record_data_ingestion_log(provider_name="toss", raise_errors=True)

    def test_data_quality_snapshot_unique_per_stock_and_date(self):
        DataQualitySnapshot.objects.create(
            stock=self.stock,
            as_of_date="2026-04-30",
            price_data_days=120,
            investor_flow_days=20,
            market_data_available=True,
            financial_data_available=True,
            overall_score=Decimal("0.8600"),
            quality_grade="A",
        )

        with self.assertRaises(IntegrityError):
            DataQualitySnapshot.objects.create(
                stock=self.stock,
                as_of_date="2026-04-30",
                price_data_days=120,
                investor_flow_days=20,
                market_data_available=True,
                financial_data_available=True,
                overall_score=Decimal("0.8600"),
                quality_grade="A",
            )


class DataPipelineProviderTests(TestCase):
    def setUp(self):
        self.stock = Stock.objects.create(
            code="005930",
            name="삼성전자",
            market=Stock.MARKET_KOSPI,
            sector="반도체",
        )

    def test_auto_provider_delegates_to_domain_providers(self):
        with (
            patch.object(FinanceProvider, "get_daily_price_rows", return_value=["price"]) as mock_prices,
            patch.object(FinanceProvider, "get_market_index_rows", return_value=["index"]) as mock_indices,
            patch.object(KRXProvider, "get_stock_master_rows", return_value=["stock"]) as mock_stocks,
            patch.object(KRXProvider, "get_investor_flow_rows", return_value=["flow"]) as mock_flows,
            patch.object(DisclosureProvider, "get_risk_event_rows", return_value=["risk"]) as mock_risks,
            patch.object(
                FinancialStatementProvider,
                "get_financial_snapshot_rows",
                return_value=["financial"],
            ) as mock_financials,
        ):
            provider = get_provider("auto")

            self.assertEqual(provider.get_stock_master_rows(), ["stock"])
            self.assertEqual(provider.get_daily_price_rows(self.stock, 30), ["price"])
            self.assertEqual(provider.get_investor_flow_rows(self.stock, 30), ["flow"])
            self.assertEqual(provider.get_market_index_rows("KOSPI", 30), ["index"])
            self.assertEqual(provider.get_risk_event_rows(self.stock, 30), ["risk"])
            self.assertEqual(provider.get_financial_snapshot_rows(self.stock, 2), ["financial"])

        mock_stocks.assert_called_once_with()
        mock_prices.assert_called_once_with(self.stock, 30)
        mock_flows.assert_called_once_with(self.stock, 30)
        mock_indices.assert_called_once_with("KOSPI", 30)
        mock_risks.assert_called_once_with(self.stock, 30)
        mock_financials.assert_called_once_with(self.stock, 2)

    def test_finance_provider_builds_daily_price_rows_from_existing_helpers(self):
        fake_rows = [
            {
                "date": timezone.localdate(),
                "open_price": Decimal("70000.00"),
                "high_price": Decimal("71000.00"),
                "low_price": Decimal("69000.00"),
                "close_price": Decimal("70500.00"),
                "volume": 1000,
                "change_rate": Decimal("1.5000"),
            }
        ]
        with (
            patch(
                "data_pipeline.providers.finance_provider.resolve_stock_yfinance_symbol",
                return_value=ProviderSymbolResolution(symbol="005930.KS", source="test"),
            ),
            patch("data_pipeline.providers.finance_provider.fetch_history_frame", return_value=object()),
            patch("data_pipeline.providers.finance_provider._build_price_rows", return_value=fake_rows),
        ):
            rows = FinanceProvider().get_daily_price_rows(self.stock, 30)

        self.assertEqual(
            rows,
            [
                DailyPriceRow(
                    stock_code="005930",
                    date=timezone.localdate(),
                    open_price=Decimal("70000.00"),
                    high_price=Decimal("71000.00"),
                    low_price=Decimal("69000.00"),
                    close_price=Decimal("70500.00"),
                    volume=1000,
                    change_rate=Decimal("1.5000"),
                )
            ],
        )

    def test_finance_provider_builds_market_index_rows_from_existing_helpers(self):
        fake_rows = [
            {
                "date": timezone.localdate(),
                "close_value": Decimal("2750.0000"),
                "change_rate": Decimal("0.5000"),
            }
        ]
        with (
            patch("data_pipeline.providers.finance_provider.fetch_history_frame", return_value=object()),
            patch("data_pipeline.providers.finance_provider._build_market_index_rows", return_value=fake_rows),
        ):
            rows = FinanceProvider().get_market_index_rows("KOSPI", 30)

        self.assertEqual(
            rows,
            [
                MarketIndexRow(
                    code="KOSPI",
                    name="KOSPI",
                    date=timezone.localdate(),
                    close_value=Decimal("2750.0000"),
                    change_rate=Decimal("0.5000"),
                )
            ],
        )

    def test_krx_provider_builds_investor_flow_rows_from_existing_helpers(self):
        fake_rows = [
            {
                "date": timezone.localdate(),
                "foreign_net_buy": 100,
                "institution_net_buy": 50,
                "individual_net_buy": -150,
                "program_net_buy": 10,
            }
        ]
        with (
            patch("data_pipeline.providers.krx_provider._fetch_investor_flow_frame", return_value=object()),
            patch("data_pipeline.providers.krx_provider._build_investor_flow_rows", return_value=fake_rows),
        ):
            rows = KRXProvider().get_investor_flow_rows(self.stock, 20)

        self.assertEqual(
            rows,
            [
                InvestorFlowRow(
                    stock_code="005930",
                    date=timezone.localdate(),
                    foreign_net_buy=100,
                    institution_net_buy=50,
                    individual_net_buy=-150,
                    program_net_buy=10,
                )
            ],
        )

    @override_settings(OPENDART_API_KEY="test-key")
    def test_disclosure_provider_builds_risk_event_rows_from_existing_helpers(self):
        built_defaults = {
            "source_key": "opendart:12345",
            "defaults": {
                "event_type": "trading_halt",
                "title": "거래정지",
                "event_date": timezone.localdate(),
                "risk_level": "critical",
                "description": "중요 공시",
                "source": "opendart_auto",
                "url": "https://example.com/risk",
                "is_active": True,
            },
        }
        with (
            patch("data_pipeline.providers.disclosure_provider.get_dart_corp_code_map", return_value={"005930": "corp"}),
            patch("data_pipeline.providers.disclosure_provider.fetch_dart_disclosures", return_value=[{"rcept_dt": "20260430"}]),
            patch("data_pipeline.providers.disclosure_provider._build_risk_event_defaults", return_value=built_defaults),
        ):
            rows = DisclosureProvider().get_risk_event_rows(self.stock, 90)

        self.assertEqual(
            rows,
            [
                RiskEventRow(
                    stock_code="005930",
                    event_type="trading_halt",
                    title="거래정지",
                    event_date=timezone.localdate(),
                    risk_level="critical",
                    description="중요 공시",
                    source="opendart_auto",
                    source_key="opendart:12345",
                    url="https://example.com/risk",
                    is_active=True,
                )
            ],
        )

    @override_settings(OPENDART_API_KEY="test-key")
    def test_financial_statement_provider_builds_snapshot_rows_from_existing_helpers(self):
        current_year = timezone.localdate().year
        defaults = {
            "reported_date": timezone.localdate(),
            "revenue": Decimal("1000.00"),
            "operating_profit": Decimal("100.00"),
            "net_income": Decimal("80.00"),
            "operating_cash_flow": Decimal("120.00"),
            "debt_ratio": Decimal("80.00"),
            "current_ratio": Decimal("140.00"),
            "equity": Decimal("900.00"),
            "capital_impairment_rate": Decimal("0.00"),
            "roe": Decimal("12.50"),
            "per": None,
            "pbr": None,
            "source": "opendart_financial_auto",
            "source_key": f"financial:005930:{current_year}:ANNUAL:CFS",
        }

        def fake_fetch(_api_key, _corp_code, _fiscal_year, report_code, fs_div):
            if report_code == "11011" and fs_div == "CFS":
                return [{"dummy": "row"}]
            return []

        with (
            patch("data_pipeline.providers.financial_statement_provider.get_dart_corp_code_map", return_value={"005930": "corp"}),
            patch("data_pipeline.providers.financial_statement_provider.fetch_financial_statement_rows", side_effect=fake_fetch),
            patch("data_pipeline.providers.financial_statement_provider._build_snapshot_defaults", return_value=defaults),
        ):
            rows = FinancialStatementProvider().get_financial_snapshot_rows(self.stock, 1)

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0],
            FinancialSnapshotRow(
                stock_code="005930",
                fiscal_year=timezone.localdate().year,
                period_type="ANNUAL",
                reported_date=timezone.localdate(),
                revenue=Decimal("1000.00"),
                operating_profit=Decimal("100.00"),
                net_income=Decimal("80.00"),
                operating_cash_flow=Decimal("120.00"),
                debt_ratio=Decimal("80.00"),
                current_ratio=Decimal("140.00"),
                equity=Decimal("900.00"),
                capital_impairment_rate=Decimal("0.00"),
                roe=Decimal("12.50"),
                per=None,
                pbr=None,
                source="opendart_financial_auto",
                source_key=f"financial:005930:{current_year}:ANNUAL:CFS",
            ),
        )


class DataPipelineCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pipeline", password="pw12345")
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)
        self.holding = UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("70000.00"),
            quantity=10,
            is_active=True,
        )

    def test_run_daily_pipeline_with_mock_provider_creates_snapshots_and_logs(self):
        out = StringIO()

        call_command("run_daily_pipeline", "--provider", "mock", stdout=out)

        self.assertTrue(DataIngestionLog.objects.filter(job_name="run_daily_pipeline").exists() is False)
        self.assertTrue(DataIngestionLog.objects.filter(job_name="ingest_daily_prices").exists())
        self.assertTrue(DataProviderStatus.objects.filter(provider="mock", data_type="price").exists())
        self.assertTrue(DailyPrice.objects.filter(stock=self.stock).exists())
        self.assertTrue(InvestorFlow.objects.filter(stock=self.stock).exists())
        self.assertTrue(MarketIndex.objects.filter(code="KOSPI").exists())
        self.assertTrue(DataQualitySnapshot.objects.filter(stock=self.stock).exists())

    def test_update_data_quality_command_creates_snapshot(self):
        DailyPrice.objects.create(
            stock=self.stock,
            date="2026-04-29",
            open_price=Decimal("70000.00"),
            high_price=Decimal("71000.00"),
            low_price=Decimal("69000.00"),
            close_price=Decimal("70500.00"),
            volume=1000,
        )
        InvestorFlow.objects.create(stock=self.stock, date="2026-04-29")
        MarketIndex.objects.create(
            code="KOSPI",
            name="KOSPI",
            date="2026-04-29",
            close_value=Decimal("2750.0000"),
            change_rate=Decimal("1.0000"),
        )
        MarketIndex.objects.create(
            code="NASDAQ",
            name="NASDAQ",
            date="2026-04-29",
            close_value=Decimal("15000.0000"),
            change_rate=Decimal("1.0000"),
        )

        call_command("update_data_quality", "--stock-code", "005930")

        snapshot = DataQualitySnapshot.objects.get(stock=self.stock)
        self.assertEqual(snapshot.stock, self.stock)
        self.assertIn(snapshot.quality_grade, {"A", "B", "C", "D"})

    @override_settings(DATA_PIPELINE_PROVIDER="auto")
    def test_run_daily_pipeline_command_uses_settings_default_provider(self):
        report = IngestionReport(job_name="run", provider="auto", target_type="price")
        with patch(
            "data_pipeline.management.commands.run_daily_pipeline.run_daily_pipeline",
            return_value={"daily_prices": report},
        ) as mock_run:
            call_command("run_daily_pipeline", "--dry-run", stdout=StringIO())

        mock_run.assert_called_once_with(
            provider_name="auto",
            stock_codes=None,
            price_days=240,
            investor_flow_days=60,
            market_index_days=240,
            risk_event_days=365,
            financial_years=2,
            all_stocks=False,
            dry_run=True,
        )

    def test_ingest_stock_master_command_defaults_to_krx_provider(self):
        report = IngestionReport(job_name="ingest_stock_master", provider="krx", target_type="stock")
        with patch(
            "data_pipeline.management.commands.ingest_stock_master.ingest_stock_master",
            return_value=report,
        ) as mock_ingest:
            call_command("ingest_stock_master", "--dry-run", stdout=StringIO())

        mock_ingest.assert_called_once_with(provider_name="krx", dry_run=True)

    def test_ingest_daily_prices_command_defaults_to_finance_provider(self):
        report = IngestionReport(job_name="ingest_daily_prices", provider="finance", target_type="price")
        with patch(
            "data_pipeline.management.commands.ingest_daily_prices.ingest_daily_prices",
            return_value=report,
        ) as mock_ingest:
            call_command("ingest_daily_prices", "--dry-run", stdout=StringIO())

        mock_ingest.assert_called_once_with(
            provider_name="finance",
            stock_codes=None,
            days=240,
            all_stocks=False,
            dry_run=True,
        )

    def test_ingest_market_indices_command_defaults_to_finance_provider(self):
        report = IngestionReport(job_name="ingest_market_indices", provider="finance", target_type="market")
        with patch(
            "data_pipeline.management.commands.ingest_market_indices.ingest_market_indices",
            return_value=report,
        ) as mock_ingest:
            call_command("ingest_market_indices", "--dry-run", stdout=StringIO())

        mock_ingest.assert_called_once_with(
            provider_name="finance",
            codes=None,
            days=240,
            dry_run=True,
        )

    def test_ingest_investor_flows_command_defaults_to_krx_provider(self):
        report = IngestionReport(job_name="ingest_investor_flows", provider="krx", target_type="flow")
        with patch(
            "data_pipeline.management.commands.ingest_investor_flows.ingest_investor_flows",
            return_value=report,
        ) as mock_ingest:
            call_command("ingest_investor_flows", "--dry-run", stdout=StringIO())

        mock_ingest.assert_called_once_with(
            provider_name="krx",
            stock_codes=None,
            days=60,
            all_stocks=False,
            dry_run=True,
        )

    def test_ingest_risk_events_command_defaults_to_disclosure_provider(self):
        report = IngestionReport(job_name="ingest_risk_events", provider="disclosure", target_type="risk")
        with patch(
            "data_pipeline.management.commands.ingest_risk_events.ingest_risk_events",
            return_value=report,
        ) as mock_ingest:
            call_command("ingest_risk_events", "--dry-run", stdout=StringIO())

        mock_ingest.assert_called_once_with(
            provider_name="disclosure",
            stock_codes=None,
            days=365,
            all_stocks=False,
            dry_run=True,
        )

    def test_ingest_financial_data_command_defaults_to_financial_statement_provider(self):
        report = IngestionReport(
            job_name="ingest_financial_data",
            provider="financial_statement",
            target_type="financial",
        )
        with patch(
            "data_pipeline.management.commands.ingest_financial_data.ingest_financial_data",
            return_value=report,
        ) as mock_ingest:
            call_command("ingest_financial_data", "--dry-run", stdout=StringIO())

        mock_ingest.assert_called_once_with(
            provider_name="financial_statement",
            stock_codes=None,
            years=2,
            all_stocks=False,
            dry_run=True,
        )

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=False,
        TOSS_INVEST_CLIENT_ID="",
        TOSS_INVEST_CLIENT_SECRET="",
        TOSS_INVEST_ACCOUNT_ID="",
        TOSS_ORDER_EXECUTION_ENABLED=False,
    )
    def test_check_toss_provider_command_runs_with_default_settings(self):
        out = StringIO()

        call_command("check_toss_provider", stdout=out)

        output = out.getvalue()
        self.assertIn("TossOpenApiProvider", output)
        self.assertIn("- enabled: false", output)
        self.assertIn("- status: disabled", output)
        self.assertIn("- order_execution_enabled: false", output)
        self.assertIn("- network_call: false", output)

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="",
        TOSS_INVEST_CLIENT_SECRET="",
    )
    def test_check_toss_provider_command_reports_misconfigured(self):
        out = StringIO()

        call_command("check_toss_provider", stdout=out)

        output = out.getvalue()
        self.assertIn("- enabled: true", output)
        self.assertIn("- status: misconfigured", output)
        self.assertIn("- client_id: missing", output)
        self.assertIn("- client_secret: missing", output)

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="fake_client_id_for_test_only",
        TOSS_INVEST_CLIENT_SECRET="fake_client_secret_for_test_only",
        TOSS_INVEST_ACCOUNT_ID="fake_account_id_for_test_only",
        TOSS_ORDER_EXECUTION_ENABLED=False,
    )
    def test_check_toss_provider_command_reports_configured_without_secrets(self):
        out = StringIO()

        call_command("check_toss_provider", stdout=out)

        output = out.getvalue()
        self.assertIn("- enabled: true", output)
        self.assertIn("- status: configured", output)
        self.assertIn("- client_id: fake********only", output)
        self.assertIn("- client_secret: configured", output)
        self.assertIn("- account_id: fake********only", output)
        self.assertNotIn("fake_client_id_for_test_only", output)
        self.assertNotIn("fake_client_secret_for_test_only", output)
        self.assertNotIn("fake_account_id_for_test_only", output)
        self.assertNotIn("access_token", output)

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="fake_client_id_for_test_only",
        TOSS_INVEST_CLIENT_SECRET="fake_client_secret_for_test_only",
        TOSS_ORDER_EXECUTION_ENABLED=True,
    )
    def test_check_toss_provider_command_reports_order_execution_flag_only(self):
        out = StringIO()
        with patch("data_pipeline.providers.toss_client.TossOpenApiClient.request") as mock_request:
            call_command("check_toss_provider", stdout=out)

        output = out.getvalue()
        self.assertIn("- order_execution_enabled: true", output)
        self.assertIn("- network_call: false", output)
        mock_request.assert_not_called()

    def test_check_toss_provider_command_leaves_toss_registry_read_only(self):
        before_count = DataIngestionLog.objects.count()

        provider = get_provider("toss")

        self.assertIsInstance(provider, TossOpenApiProvider)
        self.assertEqual(DataIngestionLog.objects.count(), before_count)

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="fake_client_id_for_test_only",
        TOSS_INVEST_CLIENT_SECRET="fake_client_secret_for_test_only",
        TOSS_INVEST_ACCOUNT_ID="fake_account_id_for_test_only",
    )
    def test_check_toss_provider_command_logs_safe_result(self):
        out = StringIO()

        with self.assertLogs("data_pipeline.management.commands.check_toss_provider", level="INFO") as logs:
            call_command("check_toss_provider", stdout=out)

        log_output = "\n".join(logs.output)
        self.assertIn("toss_smoke_result", log_output)
        self.assertIn("command=check_toss_provider", log_output)
        self.assertIn("provider=toss", log_output)
        self.assertNotIn("fake_client_secret_for_test_only", log_output)
        self.assertNotIn("fake_account_id_for_test_only", log_output)
        self.assertIn("TossOpenApiProvider", out.getvalue())
        ingestion_log = DataIngestionLog.objects.filter(job_name="check_toss_provider").latest("id")
        self.assertEqual(ingestion_log.provider_name, "toss")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_PROVIDER_HEALTH)
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SUCCESS)
        self.assertEqual(ingestion_log.safe_reason, "provider_configured")
        self.assertFalse(ingestion_log.network_call)
        self.assertTrue(ingestion_log.dry_run)
        self.assertNotIn("fake_client_secret_for_test_only", str(ingestion_log.metadata))
        self.assertNotIn("fake_account_id_for_test_only", str(ingestion_log.metadata))

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=False)
    def test_toss_token_smoke_skips_when_provider_disabled(self):
        out = StringIO()

        call_command("toss_token_smoke", stdout=out)

        output = out.getvalue()
        self.assertIn("Toss token smoke: SKIPPED", output)
        self.assertIn("reason: TOSS_INVEST_PROVIDER_ENABLED is false", output)
        self.assertIn("network_call: false", output)

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="",
        TOSS_INVEST_CLIENT_SECRET="",
    )
    def test_toss_token_smoke_fails_without_credentials(self):
        out = StringIO()

        call_command("toss_token_smoke", stdout=out)

        output = out.getvalue()
        self.assertIn("Toss token smoke: FAILED", output)
        self.assertIn("reason: TOSS_INVEST_CLIENT_ID or TOSS_INVEST_CLIENT_SECRET is missing", output)
        self.assertIn("network_call: false", output)

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="fake_client_id_for_test_only",
        TOSS_INVEST_CLIENT_SECRET="fake_client_secret_for_test_only",
    )
    def test_toss_token_smoke_no_network_skips_transport(self):
        before_count = DataIngestionLog.objects.count()
        out = StringIO()
        with patch("data_pipeline.management.commands.toss_token_smoke._urllib_form_transport") as mock_transport:
            call_command("toss_token_smoke", "--no-network", stdout=out)

        output = out.getvalue()
        self.assertIn("Toss token smoke: SKIPPED", output)
        self.assertIn("reason: --no-network was provided", output)
        self.assertIn("network_call: false", output)
        mock_transport.assert_not_called()
        self.assertEqual(DataIngestionLog.objects.count(), before_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_token_smoke")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_AUTH)
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SKIPPED)
        self.assertEqual(ingestion_log.safe_reason, "no_network")
        self.assertFalse(ingestion_log.network_call)
        self.assertTrue(ingestion_log.dry_run)

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="fake_client_id_for_test_only",
        TOSS_INVEST_CLIENT_SECRET="fake_client_secret_for_test_only",
    )
    def test_toss_token_smoke_reports_success_with_fake_transport(self):
        before_count = DataIngestionLog.objects.count()
        out = StringIO()

        def fake_transport(method, url, *, headers, data, timeout):
            self.assertEqual(method, "POST")
            self.assertEqual(headers, {"Content-Type": "application/x-www-form-urlencoded"})
            self.assertEqual(data["grant_type"], "client_credentials")
            return {
                "access_token": "fake_access_token_for_test_only",
                "token_type": "Bearer",
                "expires_in": 86400,
            }

        with patch("data_pipeline.management.commands.toss_token_smoke._urllib_form_transport", fake_transport):
            call_command("toss_token_smoke", stdout=out)

        output = out.getvalue()
        self.assertIn("Toss token smoke: OK", output)
        self.assertIn("access_token: fake********only", output)
        self.assertIn("token_type: Bearer", output)
        self.assertIn("expires_in: 86400", output)
        self.assertIn("network_call: true", output)
        self.assertNotIn("fake_access_token_for_test_only", output)
        self.assertNotIn("fake_client_secret_for_test_only", output)
        self.assertEqual(DataIngestionLog.objects.count(), before_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_token_smoke")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_AUTH)
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SUCCESS)
        self.assertTrue(ingestion_log.network_call)
        self.assertNotIn("fake_access_token_for_test_only", str(ingestion_log.metadata))

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="fake_client_id_for_test_only",
        TOSS_INVEST_CLIENT_SECRET="fake_client_secret_for_test_only",
    )
    def test_toss_token_smoke_reports_auth_failure_safely(self):
        before_count = DataIngestionLog.objects.count()
        out = StringIO()

        def fake_transport(_method, _url, *, headers, data, timeout):
            return {"status_code": 401, "error_description": "contains fake_client_secret_for_test_only"}

        with patch("data_pipeline.management.commands.toss_token_smoke._urllib_form_transport", fake_transport):
            call_command("toss_token_smoke", stdout=out)

        output = out.getvalue()
        self.assertIn("Toss token smoke: FAILED", output)
        self.assertIn("reason: authentication failed", output)
        self.assertIn("network_call: true", output)
        self.assertNotIn("fake_client_secret_for_test_only", output)
        self.assertNotIn("fake_access_token_for_test_only", output)
        self.assertEqual(DataIngestionLog.objects.count(), before_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_FAILED)
        self.assertEqual(ingestion_log.safe_reason, "authentication_failed")
        self.assertTrue(ingestion_log.network_call)

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="fake_client_id_for_test_only",
        TOSS_INVEST_CLIENT_SECRET="fake_client_secret_for_test_only",
    )
    def test_toss_token_smoke_reports_rate_limit_safely(self):
        before_count = DataIngestionLog.objects.count()
        out = StringIO()

        def fake_transport(_method, _url, *, headers, data, timeout):
            return {"status_code": 429, "error": "rate_limited"}

        with patch("data_pipeline.management.commands.toss_token_smoke._urllib_form_transport", fake_transport):
            call_command("toss_token_smoke", stdout=out)

        output = out.getvalue()
        self.assertIn("Toss token smoke: FAILED", output)
        self.assertIn("reason: rate limit exceeded", output)
        self.assertNotIn("fake_client_secret_for_test_only", output)
        self.assertEqual(DataIngestionLog.objects.count(), before_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.safe_reason, "rate_limit_exceeded")
        self.assertTrue(ingestion_log.network_call)

    @override_settings(DATA_PIPELINE_PROVIDER="mock")
    def test_toss_token_smoke_does_not_write_ingestion_log_or_change_default_provider(self):
        before_count = DataIngestionLog.objects.count()

        provider = get_provider("toss")

        self.assertIsInstance(provider, TossOpenApiProvider)
        self.assertEqual(get_provider().provider_name, "mock")
        self.assertEqual(DataIngestionLog.objects.count(), before_count)

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="fake_client_id_for_test_only",
        TOSS_INVEST_CLIENT_SECRET="fake_client_secret_for_test_only",
    )
    def test_toss_token_smoke_logs_safe_success_and_failure(self):
        def fake_success_transport(method, url, *, headers, data, timeout):
            return {
                "access_token": "fake_access_token_for_test_only",
                "token_type": "Bearer",
                "expires_in": 86400,
            }

        out = StringIO()
        with (
            patch("data_pipeline.management.commands.toss_token_smoke._urllib_form_transport", fake_success_transport),
            self.assertLogs("data_pipeline.management.commands.toss_token_smoke", level="INFO") as success_logs,
        ):
            call_command("toss_token_smoke", stdout=out)

        success_log_output = "\n".join(success_logs.output)
        self.assertIn("toss_smoke_result", success_log_output)
        self.assertIn("status=ok", success_log_output)
        self.assertNotIn("fake_access_token_for_test_only", success_log_output)
        self.assertNotIn("fake_client_secret_for_test_only", success_log_output)
        self.assertNotIn("fake_access_token_for_test_only", out.getvalue())

        def fake_failure_transport(_method, _url, *, headers, data, timeout):
            return {"status_code": 401, "error_description": "fake_client_secret_for_test_only"}

        out = StringIO()
        with (
            patch("data_pipeline.management.commands.toss_token_smoke._urllib_form_transport", fake_failure_transport),
            self.assertLogs("data_pipeline.management.commands.toss_token_smoke", level="WARNING") as failure_logs,
        ):
            call_command("toss_token_smoke", stdout=out)

        failure_log_output = "\n".join(failure_logs.output)
        self.assertIn("status=failed", failure_log_output)
        self.assertIn("reason=authentication failed", failure_log_output)
        self.assertNotIn("fake_client_secret_for_test_only", failure_log_output)

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True)
    def test_toss_quote_smoke_no_network_skips(self):
        out = StringIO()
        with (
            patch("data_pipeline.management.commands.toss_quote_smoke._urllib_form_transport") as mock_token_transport,
            patch("data_pipeline.management.commands.toss_quote_smoke._urllib_json_transport") as mock_quote_transport,
        ):
            call_command("toss_quote_smoke", symbol="005930", market="KR", no_network=True, stdout=out)

        output = out.getvalue()
        self.assertIn("Toss quote smoke: SKIPPED", output)
        self.assertIn("symbol: 005930", output)
        self.assertIn("market: KR", output)
        self.assertIn("reason: --no-network was provided", output)
        self.assertIn("network_call: false", output)
        mock_token_transport.assert_not_called()
        mock_quote_transport.assert_not_called()

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=False)
    def test_toss_quote_smoke_skips_when_provider_disabled(self):
        out = StringIO()

        call_command("toss_quote_smoke", symbol="005930", market="KR", stdout=out)

        output = out.getvalue()
        self.assertIn("Toss quote smoke: SKIPPED", output)
        self.assertIn("reason: TOSS_INVEST_PROVIDER_ENABLED is false", output)
        self.assertIn("network_call: false", output)

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="",
        TOSS_INVEST_CLIENT_SECRET="",
    )
    def test_toss_quote_smoke_fails_without_credentials(self):
        out = StringIO()

        call_command("toss_quote_smoke", symbol="005930", market="KR", stdout=out)

        output = out.getvalue()
        self.assertIn("Toss quote smoke: FAILED", output)
        self.assertIn("reason: TOSS_INVEST_CLIENT_ID or TOSS_INVEST_CLIENT_SECRET is missing", output)
        self.assertIn("network_call: false", output)

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="fake_client_id_for_test_only",
        TOSS_INVEST_CLIENT_SECRET="fake_client_secret_for_test_only",
    )
    def test_toss_quote_smoke_reports_success_with_fake_transports(self):
        before_count = DataIngestionLog.objects.count()
        out = StringIO()

        def fake_token_transport(method, url, *, headers, data, timeout):
            return {
                "access_token": "fake_access_token_for_test_only",
                "token_type": "Bearer",
                "expires_in": 86400,
            }

        def fake_quote_transport(method, url, *, headers, params, data, json, timeout):
            self.assertEqual(method, "GET")
            self.assertEqual(params, {"symbols": "005930"})
            self.assertIn("Authorization", headers)
            self.assertNotIn("X-Tossinvest-Account", headers)
            return {
                "result": [
                    {
                        "symbol": "005930",
                        "timestamp": "2026-03-25T09:30:00.123+09:00",
                        "lastPrice": "72000",
                        "currency": "KRW",
                    }
                ]
            }

        with (
            patch("data_pipeline.management.commands.toss_quote_smoke._urllib_form_transport", fake_token_transport),
            patch("data_pipeline.management.commands.toss_quote_smoke._urllib_json_transport", fake_quote_transport),
        ):
            call_command("toss_quote_smoke", symbol="005930", market="KR", stdout=out)

        output = out.getvalue()
        self.assertIn("Toss quote smoke: OK", output)
        self.assertIn("provider: toss", output)
        self.assertIn("network_call: true", output)
        self.assertIn("  symbol: 005930", output)
        self.assertIn("  price: 72000", output)
        self.assertIn("  currency: KRW", output)
        self.assertIn("  as_of: 2026-03-25T09:30:00.123+09:00", output)
        self.assertNotIn("fake_access_token_for_test_only", output)
        self.assertNotIn("fake_client_secret_for_test_only", output)
        self.assertEqual(DataIngestionLog.objects.count(), before_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_quote_smoke")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_QUOTE)
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SUCCESS)
        self.assertEqual(ingestion_log.endpoint_name, "/api/v1/prices")
        self.assertTrue(ingestion_log.network_call)
        self.assertNotIn("fake_access_token_for_test_only", str(ingestion_log.metadata))

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="fake_client_id_for_test_only",
        TOSS_INVEST_CLIENT_SECRET="fake_client_secret_for_test_only",
    )
    def test_toss_quote_smoke_reports_auth_rate_limit_and_server_failures_safely(self):
        cases = [
            (401, "authentication failed"),
            (429, "rate limit exceeded"),
            (500, "quote request failed"),
        ]

        def fake_token_transport(method, url, *, headers, data, timeout):
            return {
                "access_token": "fake_access_token_for_test_only",
                "token_type": "Bearer",
                "expires_in": 86400,
            }

        for status_code, reason in cases:
            with self.subTest(status_code=status_code):
                before_count = DataIngestionLog.objects.count()
                out = StringIO()

                def fake_quote_transport(_method, _url, *, headers, params, data, json, timeout):
                    return {"status_code": status_code, "error_description": "fake_client_secret_for_test_only"}

                with (
                    patch(
                        "data_pipeline.management.commands.toss_quote_smoke._urllib_form_transport",
                        fake_token_transport,
                    ),
                    patch(
                        "data_pipeline.management.commands.toss_quote_smoke._urllib_json_transport",
                        fake_quote_transport,
                    ),
                ):
                    call_command("toss_quote_smoke", symbol="005930", market="KR", stdout=out)

                output = out.getvalue()
                self.assertIn("Toss quote smoke: FAILED", output)
                self.assertIn(f"reason: {reason}", output)
                self.assertNotIn("fake_client_secret_for_test_only", output)
                self.assertNotIn("fake_access_token_for_test_only", output)
                self.assertEqual(DataIngestionLog.objects.count(), before_count + 1)
                ingestion_log = DataIngestionLog.objects.latest("id")
                self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_FAILED)
                self.assertTrue(ingestion_log.network_call)

    def test_toss_quote_smoke_rejects_invalid_symbols(self):
        invalid_symbols = ["005930,000660", "005930/evil", "https://example.com", "005930?x=1"]

        for symbol in invalid_symbols:
            with self.subTest(symbol=symbol):
                with self.assertRaises(CommandError):
                    call_command("toss_quote_smoke", symbol=symbol, market="KR", no_network=True, stdout=StringIO())

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True)
    def test_toss_quote_smoke_commit_no_network_records_log_only(self):
        before_count = DataIngestionLog.objects.count()
        out = StringIO()

        call_command("toss_quote_smoke", symbol="005930", market="KR", no_network=True, commit=True, stdout=out)

        output = out.getvalue()
        self.assertIn("commit: not_supported_in_step_10", output)
        self.assertEqual(DataIngestionLog.objects.count(), before_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_quote_smoke")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_QUOTE)
        self.assertEqual(ingestion_log.target_symbol, "005930")
        self.assertEqual(ingestion_log.market, "KR")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SKIPPED)
        self.assertEqual(ingestion_log.safe_reason, "no_network")
        self.assertEqual(ingestion_log.commit_mode, "not_supported")
        self.assertFalse(ingestion_log.network_call)
        self.assertTrue(ingestion_log.dry_run)

    @override_settings(DATA_PIPELINE_PROVIDER="mock")
    def test_toss_quote_smoke_keeps_toss_registry_opt_in_only(self):
        self.assertIsInstance(get_provider("toss"), TossOpenApiProvider)
        self.assertEqual(get_provider().provider_name, "mock")

    @override_settings(
        TOSS_INVEST_PROVIDER_ENABLED=True,
        TOSS_INVEST_CLIENT_ID="fake_client_id_for_test_only",
        TOSS_INVEST_CLIENT_SECRET="fake_client_secret_for_test_only",
        TOSS_INVEST_ACCOUNT_ID="fake_account_id_for_test_only",
    )
    def test_toss_quote_smoke_logs_safe_success_and_failure(self):
        def fake_token_transport(method, url, *, headers, data, timeout):
            return {
                "access_token": "fake_access_token_for_test_only",
                "token_type": "Bearer",
                "expires_in": 86400,
            }

        def fake_quote_success_transport(method, url, *, headers, params, data, json, timeout):
            return {
                "result": [
                    {
                        "symbol": "005930",
                        "timestamp": "2026-03-25T09:30:00.123+09:00",
                        "lastPrice": "72000",
                        "currency": "KRW",
                    }
                ]
            }

        out = StringIO()
        with (
            patch("data_pipeline.management.commands.toss_quote_smoke._urllib_form_transport", fake_token_transport),
            patch("data_pipeline.management.commands.toss_quote_smoke._urllib_json_transport", fake_quote_success_transport),
            self.assertLogs("data_pipeline.management.commands.toss_quote_smoke", level="INFO") as success_logs,
        ):
            call_command("toss_quote_smoke", symbol="005930", market="KR", stdout=out)

        success_log_output = "\n".join(success_logs.output)
        self.assertIn("toss_smoke_result", success_log_output)
        self.assertIn("command=toss_quote_smoke", success_log_output)
        self.assertIn("symbol=005930", success_log_output)
        self.assertIn("market=KR", success_log_output)
        self.assertNotIn("fake_access_token_for_test_only", success_log_output)
        self.assertNotIn("fake_client_secret_for_test_only", success_log_output)
        self.assertNotIn("fake_account_id_for_test_only", success_log_output)
        self.assertNotIn("Authorization", success_log_output)

        def fake_quote_failure_transport(_method, _url, *, headers, params, data, json, timeout):
            return {"status_code": 500, "error_description": "fake_client_secret_for_test_only"}

        out = StringIO()
        with (
            patch("data_pipeline.management.commands.toss_quote_smoke._urllib_form_transport", fake_token_transport),
            patch("data_pipeline.management.commands.toss_quote_smoke._urllib_json_transport", fake_quote_failure_transport),
            self.assertLogs("data_pipeline.management.commands.toss_quote_smoke", level="WARNING") as failure_logs,
        ):
            call_command("toss_quote_smoke", symbol="005930", market="KR", stdout=out)

        failure_log_output = "\n".join(failure_logs.output)
        self.assertIn("status=failed", failure_log_output)
        self.assertIn("reason=quote request failed", failure_log_output)
        self.assertNotIn("fake_client_secret_for_test_only", failure_log_output)

    @override_settings(TOSS_INVEST_PROVIDER_ENABLED=True)
    def test_toss_smoke_no_network_creates_safe_ingestion_log(self):
        before_count = DataIngestionLog.objects.count()

        with self.assertLogs("data_pipeline.management.commands.toss_quote_smoke", level="INFO"):
            call_command("toss_quote_smoke", symbol="005930", market="KR", no_network=True, stdout=StringIO())

        self.assertEqual(DataIngestionLog.objects.count(), before_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_quote_smoke")
        self.assertEqual(ingestion_log.provider_name, "toss")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_QUOTE)
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SKIPPED)
        self.assertEqual(ingestion_log.safe_reason, "no_network")
        self.assertFalse(ingestion_log.network_call)

    def test_toss_provider_quote_smoke_no_network_skips_without_provider_call(self):
        before_count = DataIngestionLog.objects.count()
        out = StringIO()
        with patch("data_pipeline.management.commands.toss_provider_quote_smoke._build_provider") as mock_build_provider:
            call_command("toss_provider_quote_smoke", symbol="005930", market="KR", no_network=True, stdout=out)

        output = out.getvalue()
        self.assertIn("Toss provider quote smoke: SKIPPED", output)
        self.assertIn("symbol: 005930", output)
        self.assertIn("market: KR", output)
        self.assertIn("reason: --no-network was provided", output)
        self.assertIn("network_call: false", output)
        self.assertIn("provider_path: true", output)
        mock_build_provider.assert_not_called()
        self.assertEqual(DataIngestionLog.objects.count(), before_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_provider_quote_smoke")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_QUOTE)
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SKIPPED)
        self.assertEqual(ingestion_log.safe_reason, "no_network")
        self.assertFalse(ingestion_log.network_call)
        self.assertTrue(ingestion_log.metadata["provider_path"])

    def test_toss_provider_quote_smoke_reports_success_with_fake_provider(self):
        before_count = DataIngestionLog.objects.count()
        out = StringIO()

        class FakeProvider:
            def __init__(self):
                self.calls = []

            def get_quote(self, symbol, market=None):
                self.calls.append((symbol, market))
                return {
                    "provider": "toss",
                    "symbol": symbol,
                    "market": market,
                    "raw": {"result_count": 1, "matched_symbol": True},
                    "normalized": {
                        "symbol": "005930",
                        "price": "72000",
                        "currency": "KRW",
                        "as_of": "2026-03-25T09:30:00.123+09:00",
                    },
                    "dry_run": True,
                }

        fake_provider = FakeProvider()
        with patch("data_pipeline.management.commands.toss_provider_quote_smoke._build_provider", return_value=fake_provider):
            call_command("toss_provider_quote_smoke", symbol="005930", market="KR", raw=True, stdout=out)

        output = out.getvalue()
        self.assertEqual(fake_provider.calls, [("005930", "KR")])
        self.assertIn("Toss provider quote smoke: OK", output)
        self.assertIn("provider: toss", output)
        self.assertIn("network_call: true", output)
        self.assertIn("provider_path: true", output)
        self.assertIn("  symbol: 005930", output)
        self.assertIn("  price: 72000", output)
        self.assertIn("  currency: KRW", output)
        self.assertIn("  as_of: 2026-03-25T09:30:00.123+09:00", output)
        self.assertIn("raw_summary: matched_symbol=True result_count=1", output)
        self.assertEqual(DataIngestionLog.objects.count(), before_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_provider_quote_smoke")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_QUOTE)
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SUCCESS)
        self.assertEqual(ingestion_log.endpoint_name, "provider_get_quote")
        self.assertTrue(ingestion_log.network_call)
        self.assertTrue(ingestion_log.metadata["provider_path"])

    def test_toss_provider_quote_smoke_reports_failure_safely(self):
        before_count = DataIngestionLog.objects.count()
        out = StringIO()

        class FakeProvider:
            def get_quote(self, _symbol, _market=None):
                raise TossOpenApiError("fake_client_secret_for_test_only")

        with patch("data_pipeline.management.commands.toss_provider_quote_smoke._build_provider", return_value=FakeProvider()):
            call_command("toss_provider_quote_smoke", symbol="005930", market="KR", stdout=out)

        output = out.getvalue()
        self.assertIn("Toss provider quote smoke: FAILED", output)
        self.assertIn("reason: quote request failed", output)
        self.assertIn("network_call: true", output)
        self.assertIn("provider_path: true", output)
        self.assertNotIn("fake_client_secret_for_test_only", output)
        self.assertEqual(DataIngestionLog.objects.count(), before_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_FAILED)
        self.assertEqual(ingestion_log.safe_reason, "quote_request_failed")
        self.assertTrue(ingestion_log.network_call)

    def test_toss_provider_quote_smoke_maps_expected_failure_reasons(self):
        cases = [
            (TossProviderDisabled("disabled details"), "provider disabled", "network_call: false"),
            (TossConfigurationError("fake_client_secret_for_test_only"), "credentials missing", "network_call: false"),
            (TossAuthError("fake_access_token_for_test_only"), "authentication failed", "network_call: true"),
            (TossRateLimitError("rate limit details"), "rate limit exceeded", "network_call: true"),
        ]

        for exc, reason, network_line in cases:
            with self.subTest(reason=reason):
                out = StringIO()

                class FakeProvider:
                    def get_quote(self, _symbol, _market=None):
                        raise exc

                with patch(
                    "data_pipeline.management.commands.toss_provider_quote_smoke._build_provider",
                    return_value=FakeProvider(),
                ):
                    call_command("toss_provider_quote_smoke", symbol="005930", market="KR", stdout=out)

                output = out.getvalue()
                self.assertIn("Toss provider quote smoke: FAILED", output)
                self.assertIn(f"reason: {reason}", output)
                self.assertIn(network_line, output)
                self.assertNotIn("fake_client_secret_for_test_only", output)
                self.assertNotIn("fake_access_token_for_test_only", output)

    def test_toss_provider_quote_smoke_rejects_invalid_symbols(self):
        invalid_symbols = ["", "005930,000660", "005930/evil", "https://example.com", "005930?x=1", "005930 KR"]

        for symbol in invalid_symbols:
            with self.subTest(symbol=symbol):
                with self.assertRaises(CommandError):
                    call_command(
                        "toss_provider_quote_smoke",
                        symbol=symbol,
                        market="KR",
                        no_network=True,
                        stdout=StringIO(),
                    )

    def test_toss_provider_quote_smoke_commit_no_network_records_log_only(self):
        before_count = DataIngestionLog.objects.count()
        out = StringIO()

        call_command(
            "toss_provider_quote_smoke",
            symbol="005930",
            market="KR",
            no_network=True,
            commit=True,
            stdout=out,
        )

        output = out.getvalue()
        self.assertIn("commit: not_supported_in_step_15", output)
        self.assertEqual(DataIngestionLog.objects.count(), before_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.commit_mode, "not_supported")
        self.assertEqual(ingestion_log.safe_reason, "no_network")
        self.assertFalse(ingestion_log.network_call)

    @override_settings(DATA_PIPELINE_PROVIDER="mock")
    def test_toss_provider_quote_smoke_keeps_toss_registry_opt_in_only(self):
        self.assertIsInstance(get_provider("toss"), TossOpenApiProvider)
        self.assertEqual(get_provider().provider_name, "mock")

    def test_toss_registry_quote_smoke_no_network_skips_without_quote_call(self):
        before_count = DataIngestionLog.objects.count()
        out = StringIO()

        class FakeProvider:
            def get_quote(self, _symbol, _market=None):
                raise AssertionError("get_quote should not be called in no-network mode.")

        with patch(
            "data_pipeline.management.commands.toss_registry_quote_smoke._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ) as mock_get_provider:
            call_command("toss_registry_quote_smoke", symbol="005930", market="KR", no_network=True, stdout=out)

        output = out.getvalue()
        self.assertIn("Toss registry quote smoke: SKIPPED", output)
        self.assertIn("symbol: 005930", output)
        self.assertIn("market: KR", output)
        self.assertIn("reason: --no-network was provided", output)
        self.assertIn("network_call: false", output)
        self.assertIn("registry_path: true", output)
        self.assertIn("provider_registered: true", output)
        mock_get_provider.assert_called_once_with()
        self.assertEqual(DataIngestionLog.objects.count(), before_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_registry_quote_smoke")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_QUOTE)
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SKIPPED)
        self.assertEqual(ingestion_log.safe_reason, "no_network")
        self.assertFalse(ingestion_log.network_call)
        self.assertTrue(ingestion_log.metadata["registry_path"])
        self.assertTrue(ingestion_log.metadata["provider_registered"])

    def test_toss_registry_quote_smoke_reports_success_with_fake_registry_provider(self):
        before_count = DataIngestionLog.objects.count()
        out = StringIO()

        class FakeProvider:
            def __init__(self):
                self.calls = []

            def get_quote(self, symbol, market=None):
                self.calls.append((symbol, market))
                return {
                    "provider": "toss",
                    "symbol": symbol,
                    "market": market,
                    "raw": {"result_count": 1, "matched_symbol": True},
                    "normalized": {
                        "symbol": "005930",
                        "price": "72000",
                        "currency": "KRW",
                        "as_of": "2026-03-25T09:30:00.123+09:00",
                    },
                    "dry_run": True,
                }

        fake_provider = FakeProvider()
        with patch(
            "data_pipeline.management.commands.toss_registry_quote_smoke._get_toss_provider_from_registry",
            return_value=fake_provider,
        ):
            call_command("toss_registry_quote_smoke", symbol="005930", market="KR", raw=True, stdout=out)

        output = out.getvalue()
        self.assertEqual(fake_provider.calls, [("005930", "KR")])
        self.assertIn("Toss registry quote smoke: OK", output)
        self.assertIn("provider: toss", output)
        self.assertIn("network_call: true", output)
        self.assertIn("registry_path: true", output)
        self.assertIn("provider_registered: true", output)
        self.assertIn("  symbol: 005930", output)
        self.assertIn("  price: 72000", output)
        self.assertIn("  currency: KRW", output)
        self.assertIn("  as_of: 2026-03-25T09:30:00.123+09:00", output)
        self.assertIn("raw_summary: matched_symbol=True result_count=1", output)
        self.assertEqual(DataIngestionLog.objects.count(), before_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_registry_quote_smoke")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_QUOTE)
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SUCCESS)
        self.assertEqual(ingestion_log.endpoint_name, "registry_get_quote")
        self.assertTrue(ingestion_log.network_call)
        self.assertTrue(ingestion_log.metadata["registry_path"])
        self.assertTrue(ingestion_log.metadata["provider_registered"])

    def test_toss_registry_quote_smoke_reports_failure_safely(self):
        before_count = DataIngestionLog.objects.count()
        out = StringIO()

        class FakeProvider:
            def get_quote(self, _symbol, _market=None):
                raise TossOpenApiError("fake_client_secret_for_test_only")

        with patch(
            "data_pipeline.management.commands.toss_registry_quote_smoke._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ):
            call_command("toss_registry_quote_smoke", symbol="005930", market="KR", stdout=out)

        output = out.getvalue()
        self.assertIn("Toss registry quote smoke: FAILED", output)
        self.assertIn("reason: quote request failed", output)
        self.assertIn("network_call: true", output)
        self.assertIn("registry_path: true", output)
        self.assertIn("provider_registered: true", output)
        self.assertNotIn("fake_client_secret_for_test_only", output)
        self.assertEqual(DataIngestionLog.objects.count(), before_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_FAILED)
        self.assertEqual(ingestion_log.safe_reason, "quote_request_failed")
        self.assertTrue(ingestion_log.network_call)

    def test_toss_registry_quote_smoke_maps_expected_failure_reasons(self):
        cases = [
            (TossProviderDisabled("disabled details"), "provider disabled", "network_call: false"),
            (TossConfigurationError("fake_client_secret_for_test_only"), "credentials missing", "network_call: false"),
            (TossAuthError("fake_access_token_for_test_only"), "authentication failed", "network_call: true"),
            (TossRateLimitError("rate limit details"), "rate limit exceeded", "network_call: true"),
        ]

        for exc, reason, network_line in cases:
            with self.subTest(reason=reason):
                out = StringIO()

                class FakeProvider:
                    def get_quote(self, _symbol, _market=None):
                        raise exc

                with patch(
                    "data_pipeline.management.commands.toss_registry_quote_smoke._get_toss_provider_from_registry",
                    return_value=FakeProvider(),
                ):
                    call_command("toss_registry_quote_smoke", symbol="005930", market="KR", stdout=out)

                output = out.getvalue()
                self.assertIn("Toss registry quote smoke: FAILED", output)
                self.assertIn(f"reason: {reason}", output)
                self.assertIn(network_line, output)
                self.assertNotIn("fake_client_secret_for_test_only", output)
                self.assertNotIn("fake_access_token_for_test_only", output)

    def test_toss_registry_quote_smoke_rejects_invalid_symbols(self):
        invalid_symbols = ["", "005930,000660", "005930/evil", "https://example.com", "005930?x=1", "005930 KR"]

        for symbol in invalid_symbols:
            with self.subTest(symbol=symbol):
                with self.assertRaises(CommandError):
                    call_command(
                        "toss_registry_quote_smoke",
                        symbol=symbol,
                        market="KR",
                        no_network=True,
                        stdout=StringIO(),
                    )

    def test_toss_registry_quote_smoke_commit_no_network_records_log_only(self):
        before_count = DataIngestionLog.objects.count()
        out = StringIO()

        call_command(
            "toss_registry_quote_smoke",
            symbol="005930",
            market="KR",
            no_network=True,
            commit=True,
            stdout=out,
        )

        output = out.getvalue()
        self.assertIn("commit: not_supported_in_step_16", output)
        self.assertEqual(DataIngestionLog.objects.count(), before_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.commit_mode, "not_supported")
        self.assertEqual(ingestion_log.safe_reason, "no_network")
        self.assertFalse(ingestion_log.network_call)

    def test_toss_registry_quote_smoke_logs_safe_success_and_failure(self):
        class FakeSuccessProvider:
            def get_quote(self, symbol, market=None):
                return {
                    "provider": "toss",
                    "symbol": symbol,
                    "market": market,
                    "raw": {"result_count": 1},
                    "normalized": {
                        "symbol": symbol,
                        "price": "72000",
                        "currency": "KRW",
                        "as_of": "2026-03-25T09:30:00.123+09:00",
                    },
                    "dry_run": True,
                }

        out = StringIO()
        with (
            patch(
                "data_pipeline.management.commands.toss_registry_quote_smoke._get_toss_provider_from_registry",
                return_value=FakeSuccessProvider(),
            ),
            self.assertLogs("data_pipeline.management.commands.toss_registry_quote_smoke", level="INFO") as success_logs,
        ):
            call_command("toss_registry_quote_smoke", symbol="005930", market="KR", stdout=out)

        success_log_output = "\n".join(success_logs.output)
        self.assertIn("toss_smoke_result", success_log_output)
        self.assertIn("command=toss_registry_quote_smoke", success_log_output)
        self.assertIn("registry_path=true", success_log_output)
        self.assertIn("provider_registered=true", success_log_output)
        self.assertNotIn("fake_access_token_for_test_only", success_log_output)
        self.assertNotIn("fake_client_secret_for_test_only", success_log_output)
        self.assertNotIn("fake_account_id_for_test_only", success_log_output)
        self.assertNotIn("Authorization", success_log_output)

        class FakeFailureProvider:
            def get_quote(self, _symbol, _market=None):
                raise TossOpenApiError("fake_account_id_for_test_only")

        out = StringIO()
        with (
            patch(
                "data_pipeline.management.commands.toss_registry_quote_smoke._get_toss_provider_from_registry",
                return_value=FakeFailureProvider(),
            ),
            self.assertLogs(
                "data_pipeline.management.commands.toss_registry_quote_smoke",
                level="WARNING",
            ) as failure_logs,
        ):
            call_command("toss_registry_quote_smoke", symbol="005930", market="KR", stdout=out)

        failure_log_output = "\n".join(failure_logs.output)
        self.assertIn("status=failed", failure_log_output)
        self.assertIn("reason=quote request failed", failure_log_output)
        self.assertNotIn("fake_account_id_for_test_only", failure_log_output)

    def test_toss_daily_price_ingest_dryrun_no_network_skips_without_provider_call(self):
        before_count = DataIngestionLog.objects.count()
        out = StringIO()
        with patch("data_pipeline.management.commands.toss_daily_price_ingest_dryrun._get_toss_provider_from_registry") as mock_get_provider:
            call_command(
                "toss_daily_price_ingest_dryrun",
                symbol="005930",
                market="KR",
                count=1,
                no_network=True,
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("Toss daily price ingest dry-run: SKIPPED", output)
        self.assertIn("symbol: 005930", output)
        self.assertIn("market: KR", output)
        self.assertIn("reason: --no-network was provided", output)
        self.assertIn("dry_run: true", output)
        self.assertIn("network_call: false", output)
        self.assertIn("provider: toss", output)
        self.assertIn("registry_path: true", output)
        mock_get_provider.assert_not_called()
        self.assertEqual(DataIngestionLog.objects.count(), before_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_daily_price_ingest_dryrun")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_DAILY_PRICE)
        self.assertEqual(ingestion_log.target_symbol, "005930")
        self.assertEqual(ingestion_log.market, "KR")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SKIPPED)
        self.assertEqual(ingestion_log.safe_reason, "no_network")
        self.assertFalse(ingestion_log.network_call)
        self.assertTrue(ingestion_log.dry_run)

    def test_toss_daily_price_ingest_dryrun_reports_success_with_fake_provider(self):
        before_daily_count = DailyPrice.objects.count()
        before_stock_count = Stock.objects.count()
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        class FakeProvider:
            def __init__(self):
                self.calls = []

            def get_daily_price_candidates(self, symbol, *, market=None, count=1, before=None, adjusted=True):
                self.calls.append(
                    {
                        "symbol": symbol,
                        "market": market,
                        "count": count,
                        "before": before,
                        "adjusted": adjusted,
                    }
                )
                return {
                    "provider": "toss",
                    "symbol": symbol,
                    "market": market,
                    "endpoint": "/api/v1/candles",
                    "interval": "1d",
                    "adjusted": adjusted,
                    "dry_run": True,
                    "raw": {"result_count": 1, "next_before": "2026-03-24T09:00:00+09:00"},
                    "candidates": [
                        {
                            "symbol": symbol,
                            "market": market,
                            "date": "2026-03-25",
                            "timestamp": "2026-03-25T09:00:00+09:00",
                            "open_price": "71600",
                            "high_price": "72300",
                            "low_price": "71500",
                            "close_price": "72000",
                            "volume": "3521000",
                            "currency": "KRW",
                            "source": "toss",
                            "adjusted": adjusted,
                        }
                    ],
                    "model_mapping": {
                        "model": "DailyPrice",
                        "save_supported": False,
                        "reason": "dry_run_only_step_17",
                    },
                }

        fake_provider = FakeProvider()
        with patch(
            "data_pipeline.management.commands.toss_daily_price_ingest_dryrun._get_toss_provider_from_registry",
            return_value=fake_provider,
        ):
            call_command(
                "toss_daily_price_ingest_dryrun",
                symbol="005930",
                market="KR",
                count=1,
                raw=True,
                stdout=out,
            )

        output = out.getvalue()
        self.assertEqual(
            fake_provider.calls,
            [{"symbol": "005930", "market": "KR", "count": 1, "before": None, "adjusted": True}],
        )
        self.assertIn("Toss daily price ingest dry-run: OK", output)
        self.assertIn("provider: toss", output)
        self.assertIn("endpoint: /api/v1/candles", output)
        self.assertIn("interval: 1d", output)
        self.assertIn("adjusted: true", output)
        self.assertIn("network_call: true", output)
        self.assertIn("candidate_count: 1", output)
        self.assertIn("  - date: 2026-03-25", output)
        self.assertIn("    open_price: 71600", output)
        self.assertIn("    high_price: 72300", output)
        self.assertIn("    low_price: 71500", output)
        self.assertIn("    close_price: 72000", output)
        self.assertIn("    volume: 3521000", output)
        self.assertIn("    currency: KRW", output)
        self.assertIn("    source: toss", output)
        self.assertIn("raw_summary: result_count=1 next_before=2026-03-24T09:00:00+09:00", output)
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_daily_price_ingest_dryrun")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_DAILY_PRICE)
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SUCCESS)
        self.assertEqual(ingestion_log.candidate_count, 1)
        self.assertEqual(ingestion_log.saved_count, 0)
        self.assertEqual(ingestion_log.updated_count, 0)
        self.assertEqual(ingestion_log.skipped_count, 0)
        self.assertTrue(ingestion_log.network_call)
        self.assertTrue(ingestion_log.dry_run)

    def test_toss_daily_price_ingest_dryrun_reports_failure_safely(self):
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        class SafeDiagnosticError(TossOpenApiError):
            http_status_code = 400
            error_code = "invalid-request"
            error_field = "symbol"

        class FakeProvider:
            def get_daily_price_candidates(self, _symbol, **_kwargs):
                raise SafeDiagnosticError("fake_client_secret_for_test_only")

        with patch(
            "data_pipeline.management.commands.toss_daily_price_ingest_dryrun._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ):
            call_command("toss_daily_price_ingest_dryrun", symbol="005930", market="KR", count=1, stdout=out)

        output = out.getvalue()
        self.assertIn("Toss daily price ingest dry-run: FAILED", output)
        self.assertIn("reason: candle request failed", output)
        self.assertIn("network_call: true", output)
        self.assertIn("http_status_code: 400", output)
        self.assertIn("error_code: invalid-request", output)
        self.assertIn("error_field: symbol", output)
        self.assertIn("params_shape: symbol,interval,count,adjusted", output)
        self.assertNotIn("fake_client_secret_for_test_only", output)
        self.assertNotIn("Authorization", output)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_FAILED)
        self.assertEqual(ingestion_log.safe_reason, "candle_request_failed")
        self.assertEqual(ingestion_log.error_code, "invalid-request")
        self.assertEqual(ingestion_log.http_status_code, 400)
        self.assertTrue(ingestion_log.network_call)

    def test_toss_daily_price_ingest_dryrun_maps_expected_failure_reasons(self):
        cases = [
            (TossProviderDisabled("disabled details"), "provider disabled", "network_call: false"),
            (TossConfigurationError("fake_client_secret_for_test_only"), "credentials missing", "network_call: false"),
            (TossAuthError("fake_access_token_for_test_only"), "authentication failed", "network_call: true"),
            (TossRateLimitError("rate limit details"), "rate limit exceeded", "network_call: true"),
        ]

        for exc, reason, network_line in cases:
            with self.subTest(reason=reason):
                out = StringIO()

                class FakeProvider:
                    def get_daily_price_candidates(self, _symbol, **_kwargs):
                        raise exc

                with patch(
                    "data_pipeline.management.commands.toss_daily_price_ingest_dryrun._get_toss_provider_from_registry",
                    return_value=FakeProvider(),
                ):
                    call_command("toss_daily_price_ingest_dryrun", symbol="005930", market="KR", count=1, stdout=out)

                output = out.getvalue()
                self.assertIn("Toss daily price ingest dry-run: FAILED", output)
                self.assertIn(f"reason: {reason}", output)
                self.assertIn(network_line, output)
                self.assertNotIn("fake_client_secret_for_test_only", output)
                self.assertNotIn("fake_access_token_for_test_only", output)

    def test_toss_daily_price_ingest_dryrun_rejects_invalid_inputs(self):
        invalid_symbols = ["", "005930,000660", "005930/evil", "https://example.com", "005930?x=1", "005930 KR"]

        for symbol in invalid_symbols:
            with self.subTest(symbol=symbol):
                with self.assertRaises(CommandError):
                    call_command(
                        "toss_daily_price_ingest_dryrun",
                        symbol=symbol,
                        market="KR",
                        count=1,
                        no_network=True,
                        stdout=StringIO(),
                    )

        for count in (0, 201, "bad"):
            with self.subTest(count=count):
                with self.assertRaises(CommandError):
                    call_command(
                        "toss_daily_price_ingest_dryrun",
                        symbol="005930",
                        market="KR",
                        count=count,
                        no_network=True,
                        stdout=StringIO(),
                    )

    def test_toss_daily_price_ingest_dryrun_commit_without_confirm_is_rejected_without_provider_call(self):
        before_daily_count = DailyPrice.objects.count()
        before_stock_count = Stock.objects.count()
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        with patch("data_pipeline.management.commands.toss_daily_price_ingest_dryrun._get_toss_provider_from_registry") as mock_get_provider:
            call_command(
                "toss_daily_price_ingest_dryrun",
                symbol="005930",
                market="KR",
                count=1,
                commit=True,
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("Toss daily price ingest dry-run: FAILED", output)
        self.assertIn("reason: confirm-save required", output)
        self.assertIn("commit: rejected", output)
        self.assertIn("network_call: false", output)
        mock_get_provider.assert_not_called()
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_daily_price_ingest_dryrun")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_FAILED)
        self.assertEqual(ingestion_log.safe_reason, "confirm-save_required")
        self.assertEqual(ingestion_log.commit_mode, "rejected")
        self.assertFalse(ingestion_log.network_call)

    def test_toss_daily_price_ingest_dryrun_commit_confirm_fails_when_stock_missing(self):
        symbol = "888888"
        before_daily_count = DailyPrice.objects.count()
        before_stock_count = Stock.objects.count()
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        class FakeProvider:
            def get_daily_price_candidates(self, symbol, **_kwargs):
                return _fake_toss_daily_price_result(symbol=symbol)

        with patch(
            "data_pipeline.management.commands.toss_daily_price_ingest_dryrun._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ):
            call_command(
                "toss_daily_price_ingest_dryrun",
                symbol=symbol,
                market="KR",
                count=1,
                commit=True,
                confirm_save=True,
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("Toss daily price ingest dry-run: FAILED", output)
        self.assertIn("reason: stock not found", output)
        self.assertIn("commit: rejected", output)
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_FAILED)
        self.assertEqual(ingestion_log.safe_reason, "stock_not_found")
        self.assertEqual(ingestion_log.commit_mode, "rejected")
        self.assertTrue(ingestion_log.network_call)

    def test_toss_daily_price_ingest_dryrun_commit_confirm_creates_daily_price_only(self):
        symbol = "777001"
        stock = Stock.objects.create(code=symbol, name="Step18 Test Stock", market=Stock.MARKET_KOSPI)
        DailyPrice.objects.create(
            stock=stock,
            date="2026-03-24",
            open_price=Decimal("70000.00"),
            high_price=Decimal("71500.00"),
            low_price=Decimal("69500.00"),
            close_price=Decimal("71000.00"),
            volume=1000,
        )
        before_stock_count = Stock.objects.count()
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        class FakeProvider:
            def get_daily_price_candidates(self, symbol, **_kwargs):
                return _fake_toss_daily_price_result(symbol=symbol)

        with patch(
            "data_pipeline.management.commands.toss_daily_price_ingest_dryrun._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ):
            call_command(
                "toss_daily_price_ingest_dryrun",
                symbol=symbol,
                market="KR",
                count=1,
                commit=True,
                confirm_save=True,
                stdout=out,
            )

        output = out.getvalue()
        created = DailyPrice.objects.get(stock=stock, date="2026-03-25")
        self.assertIn("Toss daily price ingest dry-run: OK", output)
        self.assertIn("dry_run: false", output)
        self.assertIn("commit: saved", output)
        self.assertIn("created_count: 1", output)
        self.assertIn("updated_count: 0", output)
        self.assertIn("skipped_count: 0", output)
        self.assertIn("data_ingestion_log: recorded", output)
        self.assertEqual(created.open_price, Decimal("71600.00"))
        self.assertEqual(created.high_price, Decimal("72300.00"))
        self.assertEqual(created.low_price, Decimal("71500.00"))
        self.assertEqual(created.close_price, Decimal("72000.00"))
        self.assertEqual(created.volume, 3521000)
        self.assertEqual(created.change_rate, Decimal("1.4085"))
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SUCCESS)
        self.assertEqual(ingestion_log.commit_mode, "saved")
        self.assertEqual(ingestion_log.candidate_count, 1)
        self.assertEqual(ingestion_log.saved_count, 1)
        self.assertEqual(ingestion_log.updated_count, 0)
        self.assertEqual(ingestion_log.skipped_count, 0)
        self.assertTrue(ingestion_log.network_call)
        self.assertFalse(ingestion_log.dry_run)

    def test_toss_daily_price_ingest_dryrun_commit_confirm_skips_existing_by_default(self):
        symbol = "777002"
        stock = Stock.objects.create(code=symbol, name="Step18 Test Stock", market=Stock.MARKET_KOSPI)
        DailyPrice.objects.create(
            stock=stock,
            date="2026-03-25",
            open_price=Decimal("70000.00"),
            high_price=Decimal("71000.00"),
            low_price=Decimal("69000.00"),
            close_price=Decimal("70500.00"),
            volume=1000,
        )
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        class FakeProvider:
            def get_daily_price_candidates(self, symbol, **_kwargs):
                return _fake_toss_daily_price_result(symbol=symbol)

        with patch(
            "data_pipeline.management.commands.toss_daily_price_ingest_dryrun._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ):
            call_command(
                "toss_daily_price_ingest_dryrun",
                symbol=symbol,
                market="KR",
                count=1,
                commit=True,
                confirm_save=True,
                stdout=out,
            )

        existing = DailyPrice.objects.get(stock=stock, date="2026-03-25")
        output = out.getvalue()
        self.assertIn("created_count: 0", output)
        self.assertIn("updated_count: 0", output)
        self.assertIn("skipped_count: 1", output)
        self.assertEqual(existing.close_price, Decimal("70500.00"))
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SUCCESS)
        self.assertEqual(ingestion_log.saved_count, 0)
        self.assertEqual(ingestion_log.updated_count, 0)
        self.assertEqual(ingestion_log.skipped_count, 1)
        self.assertFalse(ingestion_log.dry_run)

    def test_toss_daily_price_ingest_dryrun_commit_confirm_updates_existing_only_with_flag(self):
        symbol = "777003"
        stock = Stock.objects.create(code=symbol, name="Step18 Test Stock", market=Stock.MARKET_KOSPI)
        DailyPrice.objects.create(
            stock=stock,
            date="2026-03-25",
            open_price=Decimal("70000.00"),
            high_price=Decimal("71000.00"),
            low_price=Decimal("69000.00"),
            close_price=Decimal("70500.00"),
            volume=1000,
        )
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        class FakeProvider:
            def get_daily_price_candidates(self, symbol, **_kwargs):
                return _fake_toss_daily_price_result(symbol=symbol)

        with patch(
            "data_pipeline.management.commands.toss_daily_price_ingest_dryrun._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ):
            call_command(
                "toss_daily_price_ingest_dryrun",
                symbol=symbol,
                market="KR",
                count=1,
                commit=True,
                confirm_save=True,
                update_existing=True,
                stdout=out,
            )

        existing = DailyPrice.objects.get(stock=stock, date="2026-03-25")
        output = out.getvalue()
        self.assertIn("created_count: 0", output)
        self.assertIn("updated_count: 1", output)
        self.assertIn("skipped_count: 0", output)
        self.assertEqual(existing.close_price, Decimal("72000.00"))
        self.assertEqual(existing.volume, 3521000)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SUCCESS)
        self.assertEqual(ingestion_log.saved_count, 0)
        self.assertEqual(ingestion_log.updated_count, 1)
        self.assertEqual(ingestion_log.skipped_count, 0)
        self.assertFalse(ingestion_log.dry_run)

    @override_settings(DATA_PIPELINE_PROVIDER="mock", TOSS_INVEST_PROVIDER_ENABLED=True)
    def test_toss_daily_price_ingest_dryrun_keeps_registry_opt_in_only(self):
        self.assertIsInstance(get_provider("toss"), TossOpenApiProvider)
        self.assertEqual(get_provider().provider_name, "mock")

    def test_toss_daily_price_ingest_dryrun_logs_safely(self):
        class FakeSuccessProvider:
            def get_daily_price_candidates(self, symbol, **kwargs):
                return {
                    "provider": "toss",
                    "symbol": symbol,
                    "market": kwargs.get("market"),
                    "endpoint": "/api/v1/candles",
                    "interval": "1d",
                    "adjusted": True,
                    "dry_run": True,
                    "raw": {"result_count": 1},
                    "candidates": [
                        {
                            "date": "2026-03-25",
                            "open_price": "71600",
                            "high_price": "72300",
                            "low_price": "71500",
                            "close_price": "72000",
                            "volume": "3521000",
                            "currency": "KRW",
                            "source": "toss",
                        }
                    ],
                }

        out = StringIO()
        with (
            patch(
                "data_pipeline.management.commands.toss_daily_price_ingest_dryrun._get_toss_provider_from_registry",
                return_value=FakeSuccessProvider(),
            ),
            self.assertLogs("data_pipeline.management.commands.toss_daily_price_ingest_dryrun", level="INFO") as success_logs,
        ):
            call_command("toss_daily_price_ingest_dryrun", symbol="005930", market="KR", count=1, stdout=out)

        success_log_output = "\n".join(success_logs.output)
        self.assertIn("toss_ingest_dryrun_result", success_log_output)
        self.assertIn("command=toss_daily_price_ingest_dryrun", success_log_output)
        self.assertIn("candidate_count=1", success_log_output)
        self.assertNotIn("fake_access_token_for_test_only", success_log_output)
        self.assertNotIn("fake_client_secret_for_test_only", success_log_output)
        self.assertNotIn("fake_account_id_for_test_only", success_log_output)
        self.assertNotIn("Authorization", success_log_output)
        self.assertNotIn("fake_access_token_for_test_only", out.getvalue())

    def test_toss_daily_price_batch_dryrun_no_network_skips_without_provider_call(self):
        before_holding_count = UserHolding.objects.count()
        before_stock_count = Stock.objects.count()
        before_daily_count = DailyPrice.objects.count()
        before_provider_status_count = DataProviderStatus.objects.count()
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        with patch("data_pipeline.management.commands.toss_daily_price_batch_dryrun._get_toss_provider_from_registry") as mock_get_provider:
            call_command(
                "toss_daily_price_batch_dryrun",
                symbols="005930,035250",
                market="KR",
                count=1,
                no_network=True,
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("Toss daily price batch dry-run: SKIPPED", output)
        self.assertIn("reason: --no-network was provided", output)
        self.assertIn("provider: toss", output)
        self.assertIn("endpoint: /api/v1/candles", output)
        self.assertIn("dry_run: true", output)
        self.assertIn("network_call: false", output)
        self.assertIn("commit: not_supported", output)
        self.assertIn("symbol_count: 2", output)
        self.assertIn("candidate_count: 0", output)
        self.assertIn("skipped_count: 2", output)
        self.assertIn("failed_count: 0", output)
        self.assertIn("symbol: 005930", output)
        self.assertIn("symbol: 035250", output)
        mock_get_provider.assert_not_called()
        self.assertEqual(UserHolding.objects.count(), before_holding_count)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(DataProviderStatus.objects.count(), before_provider_status_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_daily_price_batch_dryrun")
        self.assertEqual(ingestion_log.job_type, "daily_price_batch_dryrun")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_DAILY_PRICE)
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SKIPPED)
        self.assertEqual(ingestion_log.safe_reason, "no_network")
        self.assertFalse(ingestion_log.network_call)
        self.assertTrue(ingestion_log.dry_run)
        self.assertEqual(ingestion_log.commit_mode, "not_supported")
        self.assertEqual(ingestion_log.candidate_count, 0)
        self.assertEqual(ingestion_log.saved_count, 0)
        self.assertEqual(ingestion_log.updated_count, 0)
        self.assertEqual(ingestion_log.skipped_count, 2)
        self.assertEqual(ingestion_log.failed_count, 0)
        self.assertNotIn("Authorization", repr(ingestion_log.metadata))
        self.assertNotIn("access_token", repr(ingestion_log.metadata))

    def test_toss_daily_price_batch_dryrun_rejects_invalid_inputs(self):
        with self.assertRaises(CommandError):
            call_command("toss_daily_price_batch_dryrun", no_network=True, stdout=StringIO())

        for symbols in ("005930,005930/evil", "https://example.com", "005930?x=1", "005930 KR"):
            with self.subTest(symbols=symbols):
                with self.assertRaises(CommandError):
                    call_command(
                        "toss_daily_price_batch_dryrun",
                        symbols=symbols,
                        no_network=True,
                        stdout=StringIO(),
                    )

        for count in (0, 201, "bad"):
            with self.subTest(count=count):
                with self.assertRaises(CommandError):
                    call_command(
                        "toss_daily_price_batch_dryrun",
                        symbols="005930",
                        count=count,
                        no_network=True,
                        stdout=StringIO(),
                    )

        with self.assertRaises(CommandError):
            call_command(
                "toss_daily_price_batch_dryrun",
                symbols="005930",
                continue_on_error=True,
                stop_on_error=True,
                no_network=True,
                stdout=StringIO(),
            )

    def test_toss_daily_price_batch_dryrun_from_stock_db_limit_uses_existing_stocks(self):
        Stock.objects.create(code="000001", name="Batch Test 1", market=Stock.MARKET_KOSPI)
        Stock.objects.create(code="000002", name="Batch Test 2", market=Stock.MARKET_KOSPI)
        Stock.objects.create(code="000003", name="Batch Test 3", market=Stock.MARKET_KOSPI, is_active=False)
        out = StringIO()

        call_command(
            "toss_daily_price_batch_dryrun",
            from_stock_db=True,
            limit=2,
            no_network=True,
            stdout=out,
        )

        output = out.getvalue()
        self.assertIn("symbol_count: 2", output)
        self.assertIn("symbol: 000001", output)
        self.assertIn("symbol: 000002", output)
        self.assertNotIn("symbol: 000003", output)

    def test_toss_daily_price_batch_dryrun_reports_success_with_fake_provider(self):
        Stock.objects.create(code="777201", name="Batch Test 1", market=Stock.MARKET_KOSPI)
        Stock.objects.create(code="777202", name="Batch Test 2", market=Stock.MARKET_KOSPI)
        before_holding_count = UserHolding.objects.count()
        before_stock_count = Stock.objects.count()
        before_daily_count = DailyPrice.objects.count()
        before_provider_status_count = DataProviderStatus.objects.count()
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        class FakeProvider:
            def __init__(self):
                self.calls = []

            def get_daily_price_candidates(self, symbol, *, market=None, count=1, before=None, adjusted=True):
                self.calls.append(
                    {
                        "symbol": symbol,
                        "market": market,
                        "count": count,
                        "before": before,
                        "adjusted": adjusted,
                    }
                )
                return _fake_toss_daily_price_result(symbol=symbol, market=market)

        fake_provider = FakeProvider()
        with patch(
            "data_pipeline.management.commands.toss_daily_price_batch_dryrun._get_toss_provider_from_registry",
            return_value=fake_provider,
        ):
            call_command(
                "toss_daily_price_batch_dryrun",
                symbols="777201,777202",
                market="KR",
                count=1,
                raw=True,
                stdout=out,
            )

        output = out.getvalue()
        self.assertEqual(
            fake_provider.calls,
            [
                {"symbol": "777201", "market": "KR", "count": 1, "before": None, "adjusted": True},
                {"symbol": "777202", "market": "KR", "count": 1, "before": None, "adjusted": True},
            ],
        )
        self.assertIn("Toss daily price batch dry-run: OK", output)
        self.assertIn("status: success", output)
        self.assertIn("network_call: true", output)
        self.assertIn("dry_run: true", output)
        self.assertIn("commit: not_supported", output)
        self.assertIn("symbol_count: 2", output)
        self.assertIn("candidate_count: 2", output)
        self.assertIn("saved_count: 0", output)
        self.assertIn("updated_count: 0", output)
        self.assertIn("skipped_count: 0", output)
        self.assertIn("failed_count: 0", output)
        self.assertIn("first_date: 2026-03-25", output)
        self.assertIn("first_close_price: 72000", output)
        self.assertIn("raw_summary: result_count=1 next_before=None", output)
        self.assertEqual(UserHolding.objects.count(), before_holding_count)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(DataProviderStatus.objects.count(), before_provider_status_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_daily_price_batch_dryrun")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_DAILY_PRICE)
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SUCCESS)
        self.assertTrue(ingestion_log.network_call)
        self.assertTrue(ingestion_log.dry_run)
        self.assertEqual(ingestion_log.commit_mode, "not_supported")
        self.assertEqual(ingestion_log.candidate_count, 2)
        self.assertEqual(ingestion_log.saved_count, 0)
        self.assertEqual(ingestion_log.updated_count, 0)
        self.assertEqual(ingestion_log.skipped_count, 0)
        self.assertEqual(ingestion_log.failed_count, 0)

    def test_toss_daily_price_batch_dryrun_continues_after_symbol_failure(self):
        Stock.objects.create(code="777301", name="Batch Test 1", market=Stock.MARKET_KOSPI)
        Stock.objects.create(code="777302", name="Batch Test 2", market=Stock.MARKET_KOSPI)
        before_daily_count = DailyPrice.objects.count()
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        class FakeProvider:
            def get_daily_price_candidates(self, symbol, **kwargs):
                if symbol == "777301":
                    exc = TossOpenApiError("fake_client_secret_for_test_only")
                    exc.error_code = "bad-request"
                    raise exc
                return _fake_toss_daily_price_result(symbol=symbol, market=kwargs.get("market"))

        with patch(
            "data_pipeline.management.commands.toss_daily_price_batch_dryrun._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ):
            call_command(
                "toss_daily_price_batch_dryrun",
                symbols="777301,777302",
                market="KR",
                count=1,
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("Toss daily price batch dry-run: OK", output)
        self.assertIn("status: partial", output)
        self.assertIn("symbol: 777301", output)
        self.assertIn("reason: candle_request_failed", output)
        self.assertIn("symbol: 777302", output)
        self.assertIn("candidate_count: 1", output)
        self.assertIn("failed_count: 1", output)
        self.assertNotIn("fake_client_secret_for_test_only", output)
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_PARTIAL)
        self.assertEqual(ingestion_log.candidate_count, 1)
        self.assertEqual(ingestion_log.failed_count, 1)

    def test_toss_daily_price_batch_dryrun_stop_on_error_does_not_call_remaining_symbols(self):
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()
        calls = []

        class FakeProvider:
            def get_daily_price_candidates(self, symbol, **_kwargs):
                calls.append(symbol)
                raise TossOpenApiError("fake_access_token_for_test_only")

        with patch(
            "data_pipeline.management.commands.toss_daily_price_batch_dryrun._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ):
            call_command(
                "toss_daily_price_batch_dryrun",
                symbols="777401,777402",
                market="KR",
                count=1,
                stop_on_error=True,
                stdout=out,
            )

        output = out.getvalue()
        self.assertEqual(calls, ["777401"])
        self.assertIn("Toss daily price batch dry-run: FAILED", output)
        self.assertIn("status: failed", output)
        self.assertIn("stop_on_error_triggered: true", output)
        self.assertIn("failed_count: 1", output)
        self.assertNotIn("fake_access_token_for_test_only", output)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_FAILED)
        self.assertEqual(ingestion_log.failed_count, 1)

    def test_toss_holdings_sync_dryrun_no_network_skips_without_provider_call(self):
        before_holding_count = UserHolding.objects.count()
        before_stock_count = Stock.objects.count()
        before_daily_count = DailyPrice.objects.count()
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        with patch("data_pipeline.management.commands.toss_holdings_sync_dryrun._get_toss_provider_from_registry") as mock_get_provider:
            call_command("toss_holdings_sync_dryrun", no_network=True, stdout=out)

        output = out.getvalue()
        self.assertIn("Toss holdings sync dry-run: SKIPPED", output)
        self.assertIn("reason: --no-network was provided", output)
        self.assertIn("dry_run: true", output)
        self.assertIn("network_call: false", output)
        self.assertIn("provider: toss", output)
        mock_get_provider.assert_not_called()
        self.assertEqual(UserHolding.objects.count(), before_holding_count)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_holdings_sync_dryrun")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_HOLDINGS)
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SKIPPED)
        self.assertEqual(ingestion_log.safe_reason, "no_network")
        self.assertFalse(ingestion_log.network_call)
        self.assertTrue(ingestion_log.dry_run)

    def test_toss_holdings_sync_dryrun_diagnose_no_network_skips_without_provider_call(self):
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        with patch("data_pipeline.management.commands.toss_holdings_sync_dryrun._get_toss_provider_from_registry") as mock_get_provider:
            call_command("toss_holdings_sync_dryrun", diagnose_account=True, no_network=True, stdout=out)

        output = out.getvalue()
        self.assertIn("Toss holdings sync dry-run: SKIPPED", output)
        self.assertIn("reason: --no-network was provided", output)
        self.assertIn("network_call: false", output)
        mock_get_provider.assert_not_called()
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_holdings_sync_dryrun")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_HOLDINGS)
        self.assertEqual(ingestion_log.endpoint_name, "acct_list")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SKIPPED)
        self.assertFalse(ingestion_log.network_call)
        self.assertTrue(ingestion_log.dry_run)

    def test_toss_holdings_sync_dryrun_diagnose_account_reports_safe_summary(self):
        before_holding_count = UserHolding.objects.count()
        before_stock_count = Stock.objects.count()
        before_daily_count = DailyPrice.objects.count()
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        class FakeProvider:
            def __init__(self):
                self.holdings_called = False

            def get_accounts(self):
                return {
                    "provider": "toss",
                    "endpoint": "/api/v1/accounts",
                    "dry_run": True,
                    "account_count": 1,
                    "account_types": ["BROKERAGE"],
                    "account_seq_usable_count": 1,
                    "accounts": [
                        {
                            "account_type": "BROKERAGE",
                            "masked": "****",
                            "account_seq_shape": "integer_like",
                            "account_seq_usable": True,
                        }
                    ],
                    "raw": {"result_count": 1},
                }

            def get_holdings_candidates(self, **_kwargs):
                self.holdings_called = True
                return {"candidates": []}

        fake_provider = FakeProvider()
        with patch(
            "data_pipeline.management.commands.toss_holdings_sync_dryrun._get_toss_provider_from_registry",
            return_value=fake_provider,
        ):
            call_command("toss_holdings_sync_dryrun", diagnose_account=True, raw=True, stdout=out)

        output = out.getvalue()
        self.assertIn("Toss holdings account diagnostic: OK", output)
        self.assertIn("endpoint: /api/v1/accounts", output)
        self.assertIn("network_call: true", output)
        self.assertIn("account_count: 1", output)
        self.assertIn("account_types: BROKERAGE", output)
        self.assertIn("account_seq_usable_count: 1", output)
        self.assertIn("account_seq_usable: true", output)
        self.assertIn("raw_summary: result_count=1", output)
        self.assertFalse(fake_provider.holdings_called)
        self.assertNotIn("fake_account_seq_for_test_only", output)
        self.assertNotIn("accountSeq", output)
        self.assertNotIn("accountNo", output)
        self.assertNotIn("X-Tossinvest-Account", output)
        self.assertNotIn("Authorization", output)
        self.assertEqual(UserHolding.objects.count(), before_holding_count)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_holdings_sync_dryrun")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_HOLDINGS)
        self.assertEqual(ingestion_log.endpoint_name, "acct_list")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SUCCESS)
        self.assertEqual(ingestion_log.safe_reason, "acct_received")
        self.assertTrue(ingestion_log.network_call)
        self.assertTrue(ingestion_log.dry_run)
        self.assertEqual(ingestion_log.candidate_count, 1)
        self.assertNotIn("fake_account_seq_for_test_only", repr(ingestion_log.metadata))
        self.assertNotIn("accountSeq", repr(ingestion_log.metadata))
        self.assertNotIn("accountNo", repr(ingestion_log.metadata))

    def test_toss_holdings_sync_dryrun_reports_success_with_fake_provider_without_saving(self):
        before_holding_count = UserHolding.objects.count()
        before_stock_count = Stock.objects.count()
        before_daily_count = DailyPrice.objects.count()
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        class FakeProvider:
            def __init__(self):
                self.calls = []

            def get_holdings_candidates(self, *, account_id=None, symbol=None):
                self.calls.append({"account_id": account_id, "symbol": symbol})
                return {
                    "provider": "toss",
                    "endpoint": "/api/v1/holdings",
                    "dry_run": True,
                    "account": {"source": "option", "masked": "****"},
                    "summary": {"item_count": 1, "has_krw": True, "has_usd": False},
                    "raw": {"result_count": 1},
                    "candidates": [
                        {
                            "symbol": "005930",
                            "name": "삼성전자",
                            "market_country": "KR",
                            "currency": "KRW",
                            "quantity": "100",
                            "average_purchase_price": "65000",
                            "last_price": "72000",
                            "profit_loss_rate": "0.1077",
                            "source": "toss",
                            "accountSeq": "fake_account_seq_for_test_only",
                        }
                    ],
                }

        fake_provider = FakeProvider()
        with patch(
            "data_pipeline.management.commands.toss_holdings_sync_dryrun._get_toss_provider_from_registry",
            return_value=fake_provider,
        ):
            call_command(
                "toss_holdings_sync_dryrun",
                symbol="005930",
                account="fake_account_seq_for_test_only",
                raw=True,
                stdout=out,
            )

        output = out.getvalue()
        self.assertEqual(
            fake_provider.calls,
            [{"account_id": "fake_account_seq_for_test_only", "symbol": "005930"}],
        )
        self.assertIn("Toss holdings sync dry-run: OK", output)
        self.assertIn("provider: toss", output)
        self.assertIn("endpoint: /api/v1/holdings", output)
        self.assertIn("dry_run: true", output)
        self.assertIn("network_call: true", output)
        self.assertIn("account: configured", output)
        self.assertIn("account_source: option", output)
        self.assertIn("symbol: 005930", output)
        self.assertIn("item_count: 1", output)
        self.assertIn("  - symbol: 005930", output)
        self.assertIn("    name: 삼성전자", output)
        self.assertIn("    market_country: KR", output)
        self.assertIn("    currency: KRW", output)
        self.assertIn("    quantity: 100", output)
        self.assertIn("    average_purchase_price: 65000", output)
        self.assertIn("    last_price: 72000", output)
        self.assertIn("    profit_loss_rate: 0.1077", output)
        self.assertIn("    source: toss", output)
        self.assertIn("raw_summary: result_count=1", output)
        self.assertNotIn("fake_account_seq_for_test_only", output)
        self.assertNotIn("Authorization", output)
        self.assertEqual(UserHolding.objects.count(), before_holding_count)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_holdings_sync_dryrun")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_HOLDINGS)
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SUCCESS)
        self.assertEqual(ingestion_log.candidate_count, 1)
        self.assertEqual(ingestion_log.saved_count, 0)
        self.assertEqual(ingestion_log.updated_count, 0)
        self.assertEqual(ingestion_log.skipped_count, 0)
        self.assertEqual(ingestion_log.failed_count, 0)
        self.assertTrue(ingestion_log.network_call)
        self.assertTrue(ingestion_log.dry_run)
        self.assertNotIn("fake_account_seq_for_test_only", repr(ingestion_log.metadata))

    def test_toss_holdings_sync_dryrun_commit_requires_confirm_save(self):
        before_holding_count = UserHolding.objects.count()
        before_stock_count = Stock.objects.count()
        before_daily_count = DailyPrice.objects.count()
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        with patch(
            "data_pipeline.management.commands.toss_holdings_sync_dryrun._get_toss_provider_from_registry",
        ) as mock_get_provider:
            call_command("toss_holdings_sync_dryrun", map_user_holdings=True, commit=True, stdout=out)

        output = out.getvalue()
        self.assertIn("Toss holdings sync dry-run: FAILED", output)
        self.assertIn("reason: confirm_save_required", output)
        self.assertIn("commit: confirm_required", output)
        self.assertIn("network_call: false", output)
        mock_get_provider.assert_not_called()
        self.assertEqual(UserHolding.objects.count(), before_holding_count)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_FAILED)
        self.assertEqual(ingestion_log.safe_reason, "confirm_save_required")
        self.assertEqual(ingestion_log.commit_mode, "confirm_required")
        self.assertEqual(ingestion_log.saved_count, 0)
        self.assertFalse(ingestion_log.network_call)

    def test_toss_holdings_sync_dryrun_reports_failure_safely(self):
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        class FakeProvider:
            def get_holdings_candidates(self, **_kwargs):
                exc = TossOpenApiError("fake_account_seq_for_test_only")
                exc.safe_reason = "ambiguous_account"
                exc.http_status_code = 400
                exc.error_code = "invalid-request"
                exc.error_field = "symbol"
                exc.safe_message = "invalid account header"
                raise exc

        with patch(
            "data_pipeline.management.commands.toss_holdings_sync_dryrun._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ):
            call_command("toss_holdings_sync_dryrun", stdout=out)

        output = out.getvalue()
        self.assertIn("Toss holdings sync dry-run: FAILED", output)
        self.assertIn("reason: ambiguous_account", output)
        self.assertIn("network_call: true", output)
        self.assertIn("http_status_code: 400", output)
        self.assertIn("error_code: invalid-request", output)
        self.assertIn("error_field: symbol", output)
        self.assertIn("safe_message: invalid account header", output)
        self.assertIn("account_env_shape:", output)
        self.assertNotIn("fake_account_seq_for_test_only", output)
        self.assertNotIn("Authorization", output)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_FAILED)
        self.assertEqual(ingestion_log.safe_reason, "holdings_request_failed")
        self.assertEqual(ingestion_log.http_status_code, 400)
        self.assertEqual(ingestion_log.error_code, "invalid-request")
        self.assertEqual(ingestion_log.failed_count, 1)
        self.assertEqual(ingestion_log.metadata["http_status_code"], 400)
        self.assertEqual(ingestion_log.metadata["error_code"], "invalid-request")
        self.assertEqual(ingestion_log.metadata["error_field"], "symbol")
        self.assertNotIn("fake_account_seq_for_test_only", repr(ingestion_log.metadata))

    def test_toss_order_history_dryrun_no_network_skips_without_provider_call(self):
        before_holding_count = UserHolding.objects.count()
        before_stock_count = Stock.objects.count()
        before_daily_count = DailyPrice.objects.count()
        before_provider_status_count = DataProviderStatus.objects.count()
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        with patch("data_pipeline.management.commands.toss_order_history_dryrun._get_toss_provider_from_registry") as mock_get_provider:
            call_command(
                "toss_order_history_dryrun",
                status="CLOSED",
                symbol="035250",
                from_date="2026-06-01",
                to_date="2026-06-30",
                no_network=True,
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("Toss order history dry-run: SKIPPED", output)
        self.assertIn("reason: no_network", output)
        self.assertIn("endpoint: /api/v1/orders", output)
        self.assertIn("status_filter: CLOSED", output)
        self.assertIn("symbol: 035250", output)
        self.assertIn("network_call: false", output)
        self.assertIn("dry_run: true", output)
        self.assertIn("commit: not_supported", output)
        self.assertIn("order_execution_enabled: false", output)
        mock_get_provider.assert_not_called()
        self.assertEqual(UserHolding.objects.count(), before_holding_count)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(DataProviderStatus.objects.count(), before_provider_status_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_order_history_dryrun")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_SMOKE)
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SKIPPED)
        self.assertEqual(ingestion_log.safe_reason, "no_network")
        self.assertFalse(ingestion_log.network_call)
        self.assertTrue(ingestion_log.dry_run)
        self.assertEqual(ingestion_log.candidate_count, 0)
        self.assertNotIn("accountSeq", repr(ingestion_log.metadata))
        self.assertNotIn("orderId", repr(ingestion_log.metadata))

    def test_toss_order_history_dryrun_open_no_network_skips_without_provider_call(self):
        out = StringIO()

        with patch("data_pipeline.management.commands.toss_order_history_dryrun._get_toss_provider_from_registry") as mock_get_provider:
            call_command("toss_order_history_dryrun", status="OPEN", no_network=True, stdout=out)

        output = out.getvalue()
        self.assertIn("Toss order history dry-run: SKIPPED", output)
        self.assertIn("status_filter: OPEN", output)
        self.assertIn("network_call: false", output)
        mock_get_provider.assert_not_called()

    def test_toss_order_history_dryrun_reports_success_with_fake_provider_without_saving(self):
        before_holding_count = UserHolding.objects.count()
        before_stock_count = Stock.objects.count()
        before_daily_count = DailyPrice.objects.count()
        before_provider_status_count = DataProviderStatus.objects.count()
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        class FakeProvider:
            def __init__(self):
                self.calls = []

            def get_order_history_candidates(
                self,
                *,
                status,
                symbol=None,
                from_date=None,
                to_date=None,
                cursor=None,
                limit=20,
                account=None,
            ):
                self.calls.append(
                    {
                        "status": status,
                        "symbol": symbol,
                        "from_date": from_date,
                        "to_date": to_date,
                        "cursor": cursor,
                        "limit": limit,
                        "account": account,
                    }
                )
                return {
                    "provider": "toss",
                    "endpoint": "/api/v1/orders",
                    "status_filter": status,
                    "symbol": symbol or "",
                    "network_call": True,
                    "dry_run": True,
                    "account_source": "cli",
                    "account_fallback_used": False,
                    "account_header_configured": True,
                    "order_count": 1,
                    "has_next": False,
                    "next_cursor_present": False,
                    "orders": [
                        {
                            "order_id_masked": "abcd********5678",
                            "symbol": "035250",
                            "side": "BUY",
                            "order_type": "LIMIT",
                            "time_in_force": "DAY",
                            "status": "FILLED",
                            "price": "16000",
                            "quantity": "2",
                            "order_amount": "32000",
                            "currency": "KRW",
                            "ordered_at": "2026-06-16T09:30:00+09:00",
                            "execution": {
                                "filled_quantity": "2",
                                "average_filled_price": "16000",
                                "filled_amount": "32000",
                                "commission": "64",
                                "tax": "0",
                                "filled_at": "2026-06-16T09:31:15+09:00",
                                "settlement_date": "2026-06-18",
                            },
                            "orderId": "abcd1234wxyz5678",
                            "clientOrderId": "client-order-raw",
                            "accountSeq": "123456789",
                        }
                    ],
                    "raw_summary": {
                        "result_type": "paginated_orders",
                        "has_next": False,
                        "next_cursor_present": False,
                        "order_count": 1,
                    },
                }

        fake_provider = FakeProvider()
        with patch(
            "data_pipeline.management.commands.toss_order_history_dryrun._get_toss_provider_from_registry",
            return_value=fake_provider,
        ):
            call_command(
                "toss_order_history_dryrun",
                status="CLOSED",
                symbol="035250",
                from_date="2026-06-01",
                to_date="2026-06-30",
                cursor="cursor-raw-value",
                account="123456789",
                raw=True,
                stdout=out,
            )

        output = out.getvalue()
        self.assertEqual(
            fake_provider.calls,
            [
                {
                    "status": "CLOSED",
                    "symbol": "035250",
                    "from_date": "2026-06-01",
                    "to_date": "2026-06-30",
                    "cursor": "cursor-raw-value",
                    "limit": 20,
                    "account": "123456789",
                }
            ],
        )
        self.assertIn("Toss order history dry-run: OK", output)
        self.assertIn("endpoint: /api/v1/orders", output)
        self.assertIn("status_filter: CLOSED", output)
        self.assertIn("network_call: true", output)
        self.assertIn("order_count: 1", output)
        self.assertIn("  - order_id: abcd********5678", output)
        self.assertIn("    symbol: 035250", output)
        self.assertIn("    filled_quantity: 2", output)
        self.assertIn("raw_summary: result_type=paginated_orders", output)
        self.assertNotIn("abcd1234wxyz5678", output)
        self.assertNotIn("clientOrderId", output)
        self.assertNotIn("client-order-raw", output)
        self.assertNotIn("123456789", output)
        self.assertNotIn("accountSeq", output)
        self.assertNotIn("X-Tossinvest-Account", output)
        self.assertNotIn("Authorization", output)
        self.assertEqual(UserHolding.objects.count(), before_holding_count)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(DataProviderStatus.objects.count(), before_provider_status_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "toss_order_history_dryrun")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_SMOKE)
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SUCCESS)
        self.assertEqual(ingestion_log.safe_reason, "order_history_received")
        self.assertEqual(ingestion_log.candidate_count, 1)
        self.assertEqual(ingestion_log.saved_count, 0)
        self.assertEqual(ingestion_log.updated_count, 0)
        self.assertEqual(ingestion_log.failed_count, 0)
        self.assertTrue(ingestion_log.network_call)
        self.assertTrue(ingestion_log.dry_run)
        self.assertNotIn("abcd1234wxyz5678", repr(ingestion_log.metadata))
        self.assertNotIn("clientOrderId", repr(ingestion_log.metadata))
        self.assertNotIn("accountSeq", repr(ingestion_log.metadata))

    def test_toss_order_history_dryrun_reports_failure_safely(self):
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        class FakeProvider:
            def get_order_history_candidates(self, **_kwargs):
                exc = TossOpenApiError("raw value must not be shown")
                exc.safe_reason = "ambiguous_account"
                exc.http_status_code = 400
                exc.error_code = "invalid-request"
                exc.error_field = "status"
                exc.safe_message = "invalid request"
                raise exc

        with patch(
            "data_pipeline.management.commands.toss_order_history_dryrun._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ):
            call_command("toss_order_history_dryrun", stdout=out)

        output = out.getvalue()
        self.assertIn("Toss order history dry-run: FAILED", output)
        self.assertIn("reason: ambiguous_account", output)
        self.assertIn("network_call: true", output)
        self.assertIn("http_status_code: 400", output)
        self.assertIn("error_code: invalid-request", output)
        self.assertIn("error_field: status", output)
        self.assertIn("safe_message: invalid request", output)
        self.assertNotIn("Authorization", output)
        self.assertNotIn("X-Tossinvest-Account", output)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_FAILED)
        self.assertEqual(ingestion_log.safe_reason, "order_history_request_failed")
        self.assertEqual(ingestion_log.failed_count, 1)

    def test_toss_order_history_dryrun_rejects_invalid_options_and_mutation_options(self):
        invalid_options = [
            {"status": "PENDING", "no_network": True},
            {"status": "CLOSED", "symbol": "035250/evil", "no_network": True},
            {"status": "CLOSED", "from_date": "20260601", "no_network": True},
            {"status": "CLOSED", "to_date": "2026-6-1", "no_network": True},
            {"status": "CLOSED", "limit": 0, "no_network": True},
            {"status": "CLOSED", "limit": 101, "no_network": True},
        ]
        for kwargs in invalid_options:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(CommandError):
                    call_command("toss_order_history_dryrun", stdout=StringIO(), **kwargs)

        mutation_like_options = [
            {"commit": True},
            {"confirm_save": True},
            {"create_order": True},
            {"cancel_order": True},
            {"modify_order": True},
        ]
        for kwargs in mutation_like_options:
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(TypeError):
                    call_command("toss_order_history_dryrun", stdout=StringIO(), **kwargs)

    def test_toss_holdings_sync_dryrun_rejects_invalid_symbol(self):
        invalid_symbols = ["005930,000660", "005930/evil", "https://example.com", "005930?x=1", "005930 KR"]

        for symbol in invalid_symbols:
            with self.subTest(symbol=symbol):
                with self.assertRaises(CommandError):
                    call_command("toss_holdings_sync_dryrun", symbol=symbol, no_network=True, stdout=StringIO())

    def test_toss_holdings_sync_dryrun_maps_user_holdings_without_saving(self):
        user = User.objects.create_user(username="mapping_user", password="pw12345")
        Stock.objects.create(code="777101", name="매핑테스트", market=Stock.MARKET_KOSPI)
        before_holding_count = UserHolding.objects.count()
        before_stock_count = Stock.objects.count()
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        class FakeProvider:
            def get_holdings_candidates(self, **_kwargs):
                return {
                    "provider": "toss",
                    "endpoint": "/api/v1/holdings",
                    "dry_run": True,
                    "account": {"source": "accounts_api_single", "masked": "****"},
                    "summary": {"item_count": 4, "has_krw": True, "has_usd": True},
                    "candidates": [
                        {
                            "symbol": "777101",
                            "name": "매핑테스트",
                            "market_country": "KR",
                            "currency": "KRW",
                            "quantity": "10",
                            "average_purchase_price": "65000",
                            "last_price": "72000",
                            "source": "toss",
                        },
                        {
                            "symbol": "AAPL",
                            "name": "Apple",
                            "market_country": "US",
                            "currency": "USD",
                            "quantity": "0.5",
                            "average_purchase_price": "180",
                            "source": "toss",
                        },
                        {
                            "symbol": "777102",
                            "name": "SK하이닉스",
                            "market_country": "KR",
                            "currency": "KRW",
                            "quantity": "3",
                            "average_purchase_price": "100000",
                            "source": "toss",
                        },
                        {
                            "symbol": "035420",
                            "name": "네이버",
                            "market_country": "KR",
                            "currency": "KRW",
                            "quantity": "1.25",
                            "average_purchase_price": "200000",
                            "source": "toss",
                        },
                    ],
                }

        with patch(
            "data_pipeline.management.commands.toss_holdings_sync_dryrun._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ):
            call_command(
                "toss_holdings_sync_dryrun",
                map_user_holdings=True,
                user_id=user.id,
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("user_holding_mapping:", output)
        self.assertIn("owner_status: configured", output)
        self.assertIn("would_create_count: 1", output)
        self.assertIn("skipped_count: 3", output)
        self.assertIn("mapping_status: would_create", output)
        self.assertIn("reason: new_holding", output)
        self.assertIn("reason: unsupported_market_country", output)
        self.assertIn("reason: stock_not_found", output)
        self.assertIn("reason: unsupported_fractional_quantity", output)
        self.assertNotIn("accountSeq", output)
        self.assertNotIn("Authorization", output)
        self.assertEqual(UserHolding.objects.count(), before_holding_count)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_HOLDINGS)
        self.assertEqual(ingestion_log.candidate_count, 4)
        self.assertEqual(ingestion_log.saved_count, 0)
        self.assertEqual(ingestion_log.updated_count, 0)
        self.assertEqual(ingestion_log.skipped_count, 3)

    def test_toss_holdings_sync_dryrun_maps_existing_skip_and_update_without_saving(self):
        user = User.objects.create_user(username="existing_mapping_user", password="pw12345")
        UserHolding.objects.create(
            user=user,
            stock=self.stock,
            average_price=Decimal("70000.00"),
            quantity=5,
            max_additional_budget=Decimal("1000000.00"),
        )

        class FakeProvider:
            def get_holdings_candidates(self, **_kwargs):
                return {
                    "provider": "toss",
                    "endpoint": "/api/v1/holdings",
                    "dry_run": True,
                    "account": {"source": "env", "masked": "****"},
                    "summary": {"item_count": 1},
                    "candidates": [
                        {
                            "symbol": "005930",
                            "name": "삼성전자",
                            "market_country": "KR",
                            "currency": "KRW",
                            "quantity": "10",
                            "average_purchase_price": "65000",
                            "source": "toss",
                        }
                    ],
                }

        out = StringIO()
        with patch(
            "data_pipeline.management.commands.toss_holdings_sync_dryrun._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ):
            call_command(
                "toss_holdings_sync_dryrun",
                map_user_holdings=True,
                username=user.username,
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("existing_skip_count: 1", output)
        self.assertIn("mapping_status: existing_skip", output)
        self.assertIn("reason: existing_holding", output)

        out = StringIO()
        with patch(
            "data_pipeline.management.commands.toss_holdings_sync_dryrun._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ):
            call_command(
                "toss_holdings_sync_dryrun",
                map_user_holdings=True,
                username=user.username,
                update_existing=True,
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("update_existing: true", output)
        self.assertIn("would_update_count: 1", output)
        self.assertIn("mapping_status: would_update", output)
        self.assertIn("reason: update_existing", output)
        holding = UserHolding.objects.get(user=user, stock=self.stock)
        self.assertEqual(holding.average_price, Decimal("70000.00"))
        self.assertEqual(holding.quantity, 5)

    def test_toss_holdings_sync_dryrun_maps_owner_required_and_inactive_without_saving(self):
        user = User.objects.create_user(username="inactive_mapping_user", password="pw12345")
        stock = Stock.objects.create(code="777103", name="비활성매핑", market=Stock.MARKET_KOSPI)
        UserHolding.objects.create(
            user=user,
            stock=stock,
            average_price=Decimal("0.00"),
            quantity=0,
            is_active=False,
        )

        class FakeProvider:
            def get_holdings_candidates(self, **_kwargs):
                return {
                    "provider": "toss",
                    "endpoint": "/api/v1/holdings",
                    "dry_run": True,
                    "account": {"source": "env", "masked": "****"},
                    "summary": {"item_count": 1},
                    "candidates": [
                        {
                            "symbol": "777103",
                            "name": "비활성매핑",
                            "market_country": "KR",
                            "currency": "KRW",
                            "quantity": "10",
                            "average_purchase_price": "65000",
                            "source": "toss",
                        }
                    ],
                }

        out = StringIO()
        with patch(
            "data_pipeline.management.commands.toss_holdings_sync_dryrun._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ):
            call_command("toss_holdings_sync_dryrun", map_user_holdings=True, stdout=out)

        output = out.getvalue()
        self.assertIn("owner_status: owner_required", output)
        self.assertIn("reason: owner_required", output)

        out = StringIO()
        with patch(
            "data_pipeline.management.commands.toss_holdings_sync_dryrun._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ):
            call_command(
                "toss_holdings_sync_dryrun",
                map_user_holdings=True,
                username=user.username,
                update_existing=True,
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("owner_status: configured", output)
        self.assertIn("reason: inactive_existing", output)
        self.assertIn("would_update_count: 0", output)
        self.assertEqual(UserHolding.objects.filter(user=user, stock=stock, is_active=False).count(), 1)

    def test_toss_holdings_sync_dryrun_commit_creates_user_holdings_with_confirm_save(self):
        user = User.objects.create_user(username="commit_mapping_user", password="pw12345")
        stock = Stock.objects.create(code="777201", name="커밋매핑", market=Stock.MARKET_KOSPI)
        before_stock_count = Stock.objects.count()
        before_daily_count = DailyPrice.objects.count()
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        class FakeProvider:
            def get_holdings_candidates(self, **_kwargs):
                return {
                    "provider": "toss",
                    "endpoint": "/api/v1/holdings",
                    "dry_run": True,
                    "account": {"source": "accounts_api_single", "masked": "****"},
                    "summary": {"item_count": 1},
                    "candidates": [
                        {
                            "symbol": "777201",
                            "name": "커밋매핑",
                            "market_country": "KR",
                            "currency": "KRW",
                            "quantity": "10",
                            "average_purchase_price": "65000.126",
                            "source": "toss",
                        }
                    ],
                }

        with patch(
            "data_pipeline.management.commands.toss_holdings_sync_dryrun._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ):
            call_command(
                "toss_holdings_sync_dryrun",
                map_user_holdings=True,
                user_id=user.id,
                commit=True,
                confirm_save=True,
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("Toss holdings sync dry-run: OK", output)
        self.assertIn("dry_run: false", output)
        self.assertIn("commit: confirmed", output)
        self.assertIn("user_holding_commit:", output)
        self.assertIn("saved_count: 1", output)
        self.assertIn("updated_count: 0", output)
        self.assertIn("skipped_count: 0", output)
        self.assertIn("failed_count: 0", output)
        holding = UserHolding.objects.get(user=user, stock=stock)
        self.assertEqual(holding.quantity, 10)
        self.assertEqual(holding.average_price, Decimal("65000.13"))
        self.assertTrue(holding.is_active)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SUCCESS)
        self.assertEqual(ingestion_log.commit_mode, "confirmed")
        self.assertFalse(ingestion_log.dry_run)
        self.assertEqual(ingestion_log.saved_count, 1)
        self.assertEqual(ingestion_log.updated_count, 0)
        self.assertEqual(ingestion_log.skipped_count, 0)
        self.assertNotIn("accountSeq", repr(ingestion_log.metadata))
        self.assertNotIn("Authorization", repr(ingestion_log.metadata))
        self.assertNotIn(user.username, repr(ingestion_log.metadata))

    def test_toss_holdings_sync_dryrun_commit_skips_existing_without_update_existing(self):
        user = User.objects.create_user(username="commit_skip_user", password="pw12345")
        stock = Stock.objects.create(code="777202", name="커밋스킵", market=Stock.MARKET_KOSPI)
        UserHolding.objects.create(
            user=user,
            stock=stock,
            average_price=Decimal("70000.00"),
            quantity=5,
        )
        out = StringIO()

        class FakeProvider:
            def get_holdings_candidates(self, **_kwargs):
                return {
                    "provider": "toss",
                    "endpoint": "/api/v1/holdings",
                    "dry_run": True,
                    "account": {"source": "env", "masked": "****"},
                    "summary": {"item_count": 1},
                    "candidates": [
                        {
                            "symbol": "777202",
                            "name": "커밋스킵",
                            "market_country": "KR",
                            "currency": "KRW",
                            "quantity": "10",
                            "average_purchase_price": "65000",
                            "source": "toss",
                        }
                    ],
                }

        with patch(
            "data_pipeline.management.commands.toss_holdings_sync_dryrun._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ):
            call_command(
                "toss_holdings_sync_dryrun",
                map_user_holdings=True,
                user_id=user.id,
                commit=True,
                confirm_save=True,
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("mapping_status: existing_skip", output)
        self.assertIn("saved_count: 0", output)
        self.assertIn("updated_count: 0", output)
        self.assertIn("skipped_count: 1", output)
        holding = UserHolding.objects.get(user=user, stock=stock)
        self.assertEqual(holding.average_price, Decimal("70000.00"))
        self.assertEqual(holding.quantity, 5)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.saved_count, 0)
        self.assertEqual(ingestion_log.updated_count, 0)
        self.assertEqual(ingestion_log.skipped_count, 1)

    def test_toss_holdings_sync_dryrun_commit_updates_existing_only_when_allowed(self):
        user = User.objects.create_user(username="commit_update_user", password="pw12345")
        stock = Stock.objects.create(code="777203", name="커밋업데이트", market=Stock.MARKET_KOSPI)
        UserHolding.objects.create(
            user=user,
            stock=stock,
            average_price=Decimal("70000.00"),
            quantity=5,
        )
        out = StringIO()

        class FakeProvider:
            def get_holdings_candidates(self, **_kwargs):
                return {
                    "provider": "toss",
                    "endpoint": "/api/v1/holdings",
                    "dry_run": True,
                    "account": {"source": "env", "masked": "****"},
                    "summary": {"item_count": 1},
                    "candidates": [
                        {
                            "symbol": "777203",
                            "name": "커밋업데이트",
                            "market_country": "KR",
                            "currency": "KRW",
                            "quantity": "12",
                            "average_purchase_price": "64000",
                            "source": "toss",
                        }
                    ],
                }

        with patch(
            "data_pipeline.management.commands.toss_holdings_sync_dryrun._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ):
            call_command(
                "toss_holdings_sync_dryrun",
                map_user_holdings=True,
                user_id=user.id,
                commit=True,
                confirm_save=True,
                update_existing=True,
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("mapping_status: would_update", output)
        self.assertIn("saved_count: 0", output)
        self.assertIn("updated_count: 1", output)
        self.assertIn("skipped_count: 0", output)
        holding = UserHolding.objects.get(user=user, stock=stock)
        self.assertEqual(holding.average_price, Decimal("64000.00"))
        self.assertEqual(holding.quantity, 12)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.saved_count, 0)
        self.assertEqual(ingestion_log.updated_count, 1)
        self.assertEqual(ingestion_log.skipped_count, 0)

    def test_toss_holdings_sync_dryrun_commit_does_not_reactivate_inactive_existing(self):
        user = User.objects.create_user(username="commit_inactive_user", password="pw12345")
        stock = Stock.objects.create(code="777204", name="커밋비활성", market=Stock.MARKET_KOSPI)
        UserHolding.objects.create(
            user=user,
            stock=stock,
            average_price=Decimal("0.00"),
            quantity=0,
            is_active=False,
        )
        out = StringIO()

        class FakeProvider:
            def get_holdings_candidates(self, **_kwargs):
                return {
                    "provider": "toss",
                    "endpoint": "/api/v1/holdings",
                    "dry_run": True,
                    "account": {"source": "env", "masked": "****"},
                    "summary": {"item_count": 1},
                    "candidates": [
                        {
                            "symbol": "777204",
                            "name": "커밋비활성",
                            "market_country": "KR",
                            "currency": "KRW",
                            "quantity": "10",
                            "average_purchase_price": "65000",
                            "source": "toss",
                        }
                    ],
                }

        with patch(
            "data_pipeline.management.commands.toss_holdings_sync_dryrun._get_toss_provider_from_registry",
            return_value=FakeProvider(),
        ):
            call_command(
                "toss_holdings_sync_dryrun",
                map_user_holdings=True,
                user_id=user.id,
                commit=True,
                confirm_save=True,
                update_existing=True,
                stdout=out,
            )

        output = out.getvalue()
        self.assertIn("reason: inactive_existing", output)
        self.assertIn("saved_count: 0", output)
        self.assertIn("updated_count: 0", output)
        self.assertIn("skipped_count: 1", output)
        holding = UserHolding.objects.get(user=user, stock=stock)
        self.assertFalse(holding.is_active)
        self.assertEqual(holding.average_price, Decimal("0.00"))
        self.assertEqual(holding.quantity, 0)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.saved_count, 0)
        self.assertEqual(ingestion_log.updated_count, 0)
        self.assertEqual(ingestion_log.skipped_count, 1)

    def test_run_scheduled_ingestion_lists_profiles_without_log_write(self):
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        call_command("run_scheduled_ingestion", list_profiles=True, stdout=out)

        output = out.getvalue()
        self.assertIn("Available scheduled ingestion profiles:", output)
        self.assertIn("toss_no_network_preflight", output)
        self.assertIn("toss_readonly_smoke", output)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count)

    def test_run_scheduled_ingestion_refuses_readonly_profile_without_allow_network(self):
        before_holding_count = UserHolding.objects.count()
        before_stock_count = Stock.objects.count()
        before_daily_count = DailyPrice.objects.count()
        before_provider_status_count = DataProviderStatus.objects.count()
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        with patch("data_pipeline.management.commands.run_scheduled_ingestion.call_command") as child_call:
            call_command("run_scheduled_ingestion", profile="toss_readonly_smoke", stdout=out)

        output = out.getvalue()
        self.assertIn("Scheduled ingestion wrapper: REFUSED", output)
        self.assertIn("profile: toss_readonly_smoke", output)
        self.assertIn("status: skipped", output)
        self.assertIn("reason: allow_network_required", output)
        self.assertIn("network_call: false", output)
        self.assertIn("allow_network: false", output)
        self.assertIn("step_count: 7", output)
        child_call.assert_not_called()
        self.assertEqual(UserHolding.objects.count(), before_holding_count)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(DataProviderStatus.objects.count(), before_provider_status_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "run_scheduled_ingestion")
        self.assertEqual(ingestion_log.job_type, "scheduled_ingestion")
        self.assertEqual(ingestion_log.endpoint_name, "toss_readonly_smoke")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SKIPPED)
        self.assertEqual(ingestion_log.safe_reason, "allow_network_required")
        self.assertFalse(ingestion_log.network_call)
        self.assertTrue(ingestion_log.dry_run)
        self.assertEqual(ingestion_log.commit_mode, "not_requested")
        self.assertEqual(ingestion_log.candidate_count, 7)
        self.assertEqual(ingestion_log.saved_count, 0)
        self.assertEqual(ingestion_log.updated_count, 0)
        self.assertEqual(ingestion_log.skipped_count, 7)
        self.assertEqual(ingestion_log.failed_count, 0)
        self.assertNotIn("Authorization", repr(ingestion_log.metadata))
        self.assertNotIn("accountSeq", repr(ingestion_log.metadata))
        self.assertNotIn("accountNo", repr(ingestion_log.metadata))

    def test_run_scheduled_ingestion_runs_no_network_profile_and_summary_log(self):
        before_holding_count = UserHolding.objects.count()
        before_stock_count = Stock.objects.count()
        before_daily_count = DailyPrice.objects.count()
        before_provider_status_count = DataProviderStatus.objects.count()
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()

        call_command("run_scheduled_ingestion", no_network=True, stdout=out)

        output = out.getvalue()
        self.assertIn("Scheduled ingestion wrapper: STARTED", output)
        self.assertIn("profile: toss_no_network_preflight", output)
        self.assertIn("network_call: false", output)
        self.assertIn("commit: not_requested", output)
        self.assertIn("step: check_toss_provider", output)
        self.assertIn("step: toss_token_smoke", output)
        self.assertIn("step: toss_quote_smoke", output)
        self.assertIn("step: toss_daily_price_ingest_dryrun", output)
        self.assertIn("step: toss_holdings_sync_dryrun", output)
        self.assertIn("status: success", output)
        self.assertIn("step_count: 7", output)
        self.assertIn("success_count: 7", output)
        self.assertIn("failed_count: 0", output)
        self.assertNotIn("Authorization", output)
        self.assertNotIn("accountSeq", output)
        self.assertNotIn("accountNo", output)
        self.assertEqual(UserHolding.objects.count(), before_holding_count)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(DataProviderStatus.objects.count(), before_provider_status_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 8)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "run_scheduled_ingestion")
        self.assertEqual(ingestion_log.job_type, "scheduled_ingestion")
        self.assertEqual(ingestion_log.target_type, DataIngestionLog.TARGET_SMOKE)
        self.assertEqual(ingestion_log.endpoint_name, "toss_no_network_preflight")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_SUCCESS)
        self.assertEqual(ingestion_log.safe_reason, "scheduled_no_network_preflight")
        self.assertFalse(ingestion_log.network_call)
        self.assertTrue(ingestion_log.dry_run)
        self.assertEqual(ingestion_log.commit_mode, "not_requested")
        self.assertEqual(ingestion_log.candidate_count, 7)
        self.assertEqual(ingestion_log.saved_count, 0)
        self.assertEqual(ingestion_log.updated_count, 0)
        self.assertEqual(ingestion_log.skipped_count, 0)
        self.assertEqual(ingestion_log.failed_count, 0)
        self.assertNotIn("Authorization", repr(ingestion_log.metadata))
        self.assertNotIn("accountSeq", repr(ingestion_log.metadata))
        self.assertNotIn("accountNo", repr(ingestion_log.metadata))

    def test_run_scheduled_ingestion_stop_on_error_records_partial_safely(self):
        before_log_count = DataIngestionLog.objects.count()
        out = StringIO()
        calls = []

        def fake_call_command(command_name, *args, **kwargs):
            calls.append((command_name, args, kwargs))
            if command_name == "toss_token_smoke":
                raise CommandError("fake_client_secret_for_test_only")

        with patch(
            "data_pipeline.management.commands.run_scheduled_ingestion.call_command",
            side_effect=fake_call_command,
        ):
            call_command("run_scheduled_ingestion", stop_on_error=True, stdout=out)

        output = out.getvalue()
        self.assertIn("Scheduled ingestion wrapper: COMPLETE", output)
        self.assertIn("status: partial", output)
        self.assertIn("success_count: 1", output)
        self.assertIn("failed_count: 1", output)
        self.assertIn("skipped_count: 5", output)
        self.assertIn("reason: command_error", output)
        self.assertNotIn("fake_client_secret_for_test_only", output)
        self.assertEqual([call[0] for call in calls], ["check_toss_provider", "toss_token_smoke"])
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count + 1)
        ingestion_log = DataIngestionLog.objects.latest("id")
        self.assertEqual(ingestion_log.job_name, "run_scheduled_ingestion")
        self.assertEqual(ingestion_log.status, DataIngestionLog.STATUS_PARTIAL)
        self.assertEqual(ingestion_log.safe_reason, "scheduled_no_network_partial")
        self.assertEqual(ingestion_log.candidate_count, 7)
        self.assertEqual(ingestion_log.skipped_count, 5)
        self.assertEqual(ingestion_log.failed_count, 1)

    def test_toss_provider_quote_smoke_logs_safe_success_and_failure(self):
        class FakeSuccessProvider:
            def get_quote(self, symbol, market=None):
                return {
                    "provider": "toss",
                    "symbol": symbol,
                    "market": market,
                    "raw": {"result_count": 1},
                    "normalized": {
                        "symbol": symbol,
                        "price": "72000",
                        "currency": "KRW",
                        "as_of": "2026-03-25T09:30:00.123+09:00",
                    },
                    "dry_run": True,
                }

        out = StringIO()
        with (
            patch(
                "data_pipeline.management.commands.toss_provider_quote_smoke._build_provider",
                return_value=FakeSuccessProvider(),
            ),
            self.assertLogs("data_pipeline.management.commands.toss_provider_quote_smoke", level="INFO") as success_logs,
        ):
            call_command("toss_provider_quote_smoke", symbol="005930", market="KR", stdout=out)

        success_log_output = "\n".join(success_logs.output)
        self.assertIn("toss_smoke_result", success_log_output)
        self.assertIn("command=toss_provider_quote_smoke", success_log_output)
        self.assertIn("provider_path=true", success_log_output)
        self.assertNotIn("fake_access_token_for_test_only", success_log_output)
        self.assertNotIn("fake_client_secret_for_test_only", success_log_output)
        self.assertNotIn("fake_account_id_for_test_only", success_log_output)
        self.assertNotIn("Authorization", success_log_output)

        class FakeFailureProvider:
            def get_quote(self, _symbol, _market=None):
                raise TossOpenApiError("fake_account_id_for_test_only")

        out = StringIO()
        with (
            patch(
                "data_pipeline.management.commands.toss_provider_quote_smoke._build_provider",
                return_value=FakeFailureProvider(),
            ),
            self.assertLogs(
                "data_pipeline.management.commands.toss_provider_quote_smoke",
                level="WARNING",
            ) as failure_logs,
        ):
            call_command("toss_provider_quote_smoke", symbol="005930", market="KR", stdout=out)

        failure_log_output = "\n".join(failure_logs.output)
        self.assertIn("status=failed", failure_log_output)
        self.assertIn("reason=quote request failed", failure_log_output)
        self.assertNotIn("fake_account_id_for_test_only", failure_log_output)


class DataPipelineApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="apiuser", password="pw12345")
        self.client.force_authenticate(self.user)
        self.snapshot_date = timezone.localdate() - timedelta(days=1)
        self.base_started_at = timezone.now() - timedelta(days=1, hours=1)
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)
        self.snapshot = DataQualitySnapshot.objects.create(
            stock=self.stock,
            as_of_date=self.snapshot_date,
            price_data_days=120,
            latest_price_age_days=1,
            investor_flow_days=20,
            market_data_available=True,
            financial_data_available=True,
            missing_fields=[],
            anomaly_flags=[],
            overall_score=Decimal("0.8600"),
            quality_grade="A",
        )
        self.log = DataIngestionLog.objects.create(
            job_name="ingest_daily_prices",
            job_type="ingestion",
            provider="mock",
            provider_name="mock",
            target_type="price",
            target_code="005930",
            target_symbol="005930",
            market="KR",
            endpoint_name="daily_prices",
            status="success",
            safe_reason="",
            network_call=False,
            dry_run=False,
            commit_mode="confirmed",
            started_at=self.base_started_at,
            finished_at=self.base_started_at + timedelta(minutes=1),
            total_count=1,
            success_count=1,
            candidate_count=1,
            saved_count=1,
            metadata={
                "command": "ingest_daily_prices",
                "params_shape": "symbol,count",
            },
        )
        self.provider_status = DataProviderStatus.objects.create(
            provider="mock",
            data_type="price",
            is_active=True,
        )

    def test_data_quality_snapshot_api_returns_latest_snapshot(self):
        response = self.client.get("/api/data-pipeline/data-quality/005930/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["stock_code"], "005930")
        self.assertEqual(response.data["quality_grade"], "A")

    def test_ingestion_log_api_filters_by_status(self):
        response = self.client.get("/api/data-pipeline/ingestion-logs/?status=success")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["job_name"], "ingest_daily_prices")

    def test_ingestion_log_api_returns_extended_safe_fields(self):
        response = self.client.get("/api/data-pipeline/ingestion-logs/?provider_name=mock")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        payload = response.data[0]
        self.assertEqual(payload["job_type"], "ingestion")
        self.assertEqual(payload["provider_name"], "mock")
        self.assertEqual(payload["target_symbol"], "005930")
        self.assertEqual(payload["market"], "KR")
        self.assertEqual(payload["endpoint_name"], "daily_prices")
        self.assertEqual(payload["network_call"], False)
        self.assertEqual(payload["dry_run"], False)
        self.assertEqual(payload["commit_mode"], "confirmed")
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["saved_count"], 1)
        self.assertEqual(payload["updated_count"], 0)
        self.assertEqual(payload["safe_reason"], "")
        self.assertEqual(payload["metadata"]["params_shape"], "symbol,count")

    def test_ingestion_log_api_does_not_expose_unsaved_sensitive_values(self):
        response = self.client.get("/api/data-pipeline/ingestion-logs/?provider_name=mock")

        serialized = str(response.data)
        self.assertNotIn("fake_client_secret_for_test_only", serialized)
        self.assertNotIn("fake_access_token_for_test_only", serialized)
        self.assertNotIn("fake_account_id_for_test_only", serialized)
        self.assertNotIn("Authorization", serialized)

    def test_provider_status_api_returns_rows(self):
        response = self.client.get("/api/data-pipeline/provider-status/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["provider"], "mock")

    def test_summary_api_returns_aggregated_snapshot_provider_and_ingestion_data(self):
        DataIngestionLog.objects.create(
            job_name="ingest_risk_events",
            provider="disclosure",
            target_type="risk",
            target_code="005930",
            status="failed",
            started_at=self.base_started_at + timedelta(hours=1),
            finished_at=self.base_started_at + timedelta(hours=1, minutes=1),
            total_count=1,
            failed_count=1,
            error_message="opendart unavailable",
        )
        DataProviderStatus.objects.create(
            provider="disclosure",
            data_type="risk",
            is_active=True,
            consecutive_failures=2,
            last_error_message="opendart unavailable",
            last_failed_at=self.base_started_at + timedelta(hours=1, minutes=1),
        )
        DataQualitySnapshot.objects.create(
            stock=Stock.objects.create(code="000660", name="SK하이닉스", market=Stock.MARKET_KOSPI),
            as_of_date=self.snapshot_date,
            price_data_days=40,
            latest_price_age_days=5,
            investor_flow_days=0,
            market_data_available=False,
            financial_data_available=False,
            missing_fields=["investor_flows", "financial_snapshots"],
            anomaly_flags=["stale_latest_price", "missing_market_context"],
            overall_score=Decimal("0.3900"),
            quality_grade="D",
        )

        response = self.client.get("/api/data-pipeline/summary/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["health_summary"]["overall_status"], "degraded")
        self.assertEqual(response.data["health_summary"]["latest_snapshot_age_days"], 1)
        self.assertFalse(response.data["health_summary"]["snapshot_is_stale"])
        self.assertEqual(response.data["health_summary"]["failing_provider_count"], 1)
        self.assertEqual(response.data["health_summary"]["recent_failure_count"], 1)
        self.assertEqual(response.data["snapshot_summary"]["stock_count"], 2)
        self.assertEqual(response.data["snapshot_summary"]["latest_snapshot_age_days"], 1)
        self.assertFalse(response.data["snapshot_summary"]["snapshot_is_stale"])
        self.assertEqual(response.data["snapshot_summary"]["grade_counts"]["A"], 1)
        self.assertEqual(response.data["snapshot_summary"]["grade_counts"]["D"], 1)
        self.assertEqual(response.data["snapshot_summary"]["financial_missing_count"], 1)
        self.assertEqual(response.data["provider_summary"]["total"], 2)
        self.assertEqual(response.data["provider_summary"]["failing"], 1)
        self.assertEqual(response.data["provider_summary"]["failing_providers"][0]["provider"], "disclosure")
        self.assertEqual(response.data["ingestion_summary"]["latest_jobs"][0]["job_name"], "ingest_risk_events")
        self.assertEqual(response.data["ingestion_summary"]["recent_failures"][0]["status"], "failed")

    def test_summary_api_marks_stale_snapshot_as_critical_when_provider_is_failing(self):
        self.snapshot.as_of_date = timezone.localdate() - timedelta(days=3)
        self.snapshot.save(update_fields=["as_of_date"])
        self.provider_status.consecutive_failures = 1
        self.provider_status.last_failed_at = timezone.now()
        self.provider_status.last_error_message = "timeout"
        self.provider_status.save(
            update_fields=["consecutive_failures", "last_failed_at", "last_error_message"]
        )

        response = self.client.get("/api/data-pipeline/summary/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["health_summary"]["overall_status"], "critical")
        self.assertTrue(response.data["health_summary"]["snapshot_is_stale"])
        self.assertEqual(response.data["health_summary"]["latest_snapshot_age_days"], 3)

    def _staff_order_history_client(self):
        staff_user = User.objects.create_user(username="order_history_staff", password="pw12345", is_staff=True)
        client = APIClient()
        client.force_authenticate(staff_user)
        return client

    def test_toss_order_history_api_requires_staff(self):
        url = "/api/operations/toss/order-history/"

        with patch("data_pipeline.views._build_toss_order_history_provider") as mock_provider:
            anonymous_response = APIClient().get(url)
            non_staff_response = self.client.get(url)

        self.assertIn(anonymous_response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
        self.assertEqual(non_staff_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(non_staff_response.data["error"], "staff_required")
        mock_provider.assert_not_called()

    def test_toss_order_history_api_staff_success_sanitizes_sensitive_payload(self):
        before_holding_count = UserHolding.objects.count()
        before_stock_count = Stock.objects.count()
        before_daily_count = DailyPrice.objects.count()
        before_provider_status_count = DataProviderStatus.objects.count()
        before_log_count = DataIngestionLog.objects.count()

        class FakeProvider:
            def __init__(self):
                self.calls = []

            def get_order_history_candidates(self, **kwargs):
                self.calls.append(kwargs)
                return {
                    "provider": "toss",
                    "endpoint": "/api/v1/orders",
                    "status_filter": kwargs["status"],
                    "symbol": kwargs.get("symbol") or "",
                    "from_date": kwargs.get("from_date"),
                    "to_date": kwargs.get("to_date"),
                    "network_call": True,
                    "dry_run": True,
                    "account_source": "env",
                    "account_fallback_used": False,
                    "account_header_configured": True,
                    "account": {"accountSeq": "123456789", "masked": "****"},
                    "order_count": 1,
                    "has_next": True,
                    "next_cursor_present": True,
                    "nextCursor": "cursor-raw-value",
                    "next_cursor": "cursor-raw-value",
                    "orders": [
                        {
                            "order_id_masked": "abcd********5678",
                            "orderId": "abcd1234wxyz5678",
                            "clientOrderId": "client-order-raw",
                            "accountNo": "fake_account_no_for_test_only",
                            "accountSeq": "123456789",
                            "X-Tossinvest-Account": "123456789",
                            "Authorization": "Bearer fake",
                            "access_token": "fake_access_token_value_for_test_only",
                            "client_secret": "fake_client_secret_for_test_only",
                            "raw_response": {"secret": "must-not-render"},
                            "symbol": "035250",
                            "side": "BUY",
                            "order_type": "LIMIT",
                            "time_in_force": "DAY",
                            "status": "FILLED",
                            "price": "16000",
                            "quantity": "2",
                            "order_amount": "32000",
                            "currency": "KRW",
                            "ordered_at": "2026-06-16T09:30:00+09:00",
                            "execution": {
                                "filled_quantity": "2",
                                "average_filled_price": "16000",
                                "filled_amount": "32000",
                                "commission": "64",
                                "tax": "0",
                                "filled_at": "2026-06-16T09:31:15+09:00",
                                "settlement_date": "2026-06-18",
                                "token": "fake_access_token_value_for_test_only",
                            },
                        }
                    ],
                    "raw_summary": {"nextCursor": "cursor-raw-value"},
                    "headers": {"Authorization": "Bearer fake"},
                    "request": {"accountSeq": "123456789"},
                    "response": {"raw": True},
                }

        fake_provider = FakeProvider()
        client = self._staff_order_history_client()
        with patch("data_pipeline.views._build_toss_order_history_provider", return_value=fake_provider) as mock_builder:
            response = client.get(
                "/api/operations/toss/order-history/",
                {
                    "status": "CLOSED",
                    "symbol": "035250",
                    "from_date": "2026-06-01",
                    "to_date": "2026-06-30",
                    "cursor": "cursor-raw-value",
                    "limit": "5",
                    "account": "123456789",
                    "raw": "true",
                },
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            fake_provider.calls,
            [
                {
                    "status": "CLOSED",
                    "symbol": "035250",
                    "from_date": "2026-06-01",
                    "to_date": "2026-06-30",
                    "cursor": "cursor-raw-value",
                    "limit": 5,
                }
            ],
        )
        mock_builder.assert_called_once()
        payload = response.data
        payload_repr = repr(payload)
        self.assertEqual(payload["endpoint"], "/api/v1/orders")
        self.assertEqual(payload["status_filter"], "CLOSED")
        self.assertEqual(payload["order_count"], 1)
        self.assertTrue(payload["has_next"])
        self.assertTrue(payload["next_cursor_present"])
        self.assertEqual(payload["orders"][0]["order_id_masked"], "abcd********5678")
        self.assertEqual(payload["orders"][0]["symbol"], "035250")
        self.assertNotIn("orderId", payload_repr)
        self.assertNotIn("abcd1234wxyz5678", payload_repr)
        self.assertNotIn("clientOrderId", payload_repr)
        self.assertNotIn("client-order-raw", payload_repr)
        self.assertNotIn("accountNo", payload_repr)
        self.assertNotIn("accountSeq", payload_repr)
        self.assertNotIn("123456789", payload_repr)
        self.assertNotIn("X-Tossinvest-Account", payload_repr)
        self.assertNotIn("Authorization", payload_repr)
        self.assertNotIn("fake_access_token_value_for_test_only", payload_repr)
        self.assertNotIn("fake_client_secret_for_test_only", payload_repr)
        self.assertNotIn("raw_response", payload_repr)
        self.assertNotIn("raw_summary", payload_repr)
        self.assertNotIn("cursor-raw-value", payload_repr)
        self.assertEqual(UserHolding.objects.count(), before_holding_count)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(DataProviderStatus.objects.count(), before_provider_status_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count)

    def test_toss_order_history_api_defaults_and_validates_query(self):
        class FakeProvider:
            def __init__(self):
                self.calls = []

            def get_order_history_candidates(self, **kwargs):
                self.calls.append(kwargs)
                return {
                    "provider": "toss",
                    "endpoint": "/api/v1/orders",
                    "status_filter": kwargs["status"],
                    "network_call": True,
                    "dry_run": True,
                    "order_count": 0,
                    "has_next": False,
                    "next_cursor_present": False,
                    "orders": [],
                }

        fake_provider = FakeProvider()
        client = self._staff_order_history_client()
        with patch("data_pipeline.views._build_toss_order_history_provider", return_value=fake_provider):
            default_response = client.get("/api/operations/toss/order-history/")
            open_response = client.get("/api/operations/toss/order-history/", {"status": "OPEN"})

        self.assertEqual(default_response.status_code, status.HTTP_200_OK)
        self.assertEqual(open_response.status_code, status.HTTP_200_OK)
        self.assertEqual(fake_provider.calls[0]["status"], "CLOSED")
        self.assertEqual(fake_provider.calls[0]["limit"], 20)
        self.assertEqual(fake_provider.calls[1]["status"], "OPEN")

        invalid_queries = [
            {"status": "PENDING"},
            {"symbol": "035250/evil"},
            {"symbol": "035250,000660"},
            {"symbol": "035250 KR"},
            {"from_date": "20260601"},
            {"to_date": "2026-6-1"},
            {"limit": "0"},
            {"limit": "101"},
        ]
        for query in invalid_queries:
            with self.subTest(query=query):
                response = client.get("/api/operations/toss/order-history/", query)
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data["error"], "invalid_query")

    def test_toss_order_history_api_maps_provider_errors_safely(self):
        error_cases = [
            (TossProviderDisabled("disabled"), status.HTTP_503_SERVICE_UNAVAILABLE, "provider_disabled"),
            (TossConfigurationError("raw config value"), status.HTTP_503_SERVICE_UNAVAILABLE, "configuration_error"),
            (TossAuthError("raw auth value"), status.HTTP_502_BAD_GATEWAY, "authentication_failed"),
            (TossRateLimitError("raw rate value"), status.HTTP_429_TOO_MANY_REQUESTS, "rate_limit_exceeded"),
            (TossOpenApiError("raw api body"), status.HTTP_502_BAD_GATEWAY, "order_history_request_failed"),
            (RuntimeError("raw exception"), status.HTTP_500_INTERNAL_SERVER_ERROR, "order_history_request_failed"),
        ]
        client = self._staff_order_history_client()

        for exc, expected_status, expected_error in error_cases:
            class FakeProvider:
                def get_order_history_candidates(self, **_kwargs):
                    raise exc

            with self.subTest(expected_error=expected_error):
                with patch("data_pipeline.views._build_toss_order_history_provider", return_value=FakeProvider()):
                    response = client.get("/api/operations/toss/order-history/")

                self.assertEqual(response.status_code, expected_status)
                self.assertEqual(response.data["error"], expected_error)
                response_repr = repr(response.data)
                self.assertNotIn("raw config value", response_repr)
                self.assertNotIn("raw auth value", response_repr)
                self.assertNotIn("raw rate value", response_repr)
                self.assertNotIn("raw api body", response_repr)
                self.assertNotIn("raw exception", response_repr)

    def test_toss_order_history_api_rejects_post(self):
        client = self._staff_order_history_client()

        response = client.post("/api/operations/toss/order-history/", {"status": "CLOSED"})

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)

    def _staff_order_history_page_client(self):
        staff_user = User.objects.create_user(username="order_history_page_staff", password="pw12345", is_staff=True)
        client = Client()
        client.login(username=staff_user.username, password="pw12345")
        return client

    def _fake_order_history_provider(self):
        class FakeProvider:
            def __init__(self):
                self.calls = []

            def get_order_history_candidates(self, **kwargs):
                self.calls.append(kwargs)
                return {
                    "provider": "toss",
                    "endpoint": "/api/v1/orders",
                    "status_filter": kwargs["status"],
                    "symbol": kwargs.get("symbol") or "",
                    "network_call": True,
                    "dry_run": True,
                    "account_source": "env",
                    "account_fallback_used": False,
                    "account_header_configured": True,
                    "order_count": 1,
                    "has_next": True,
                    "next_cursor_present": True,
                    "nextCursor": "cursor-raw-value",
                    "cursor": "cursor-raw-value",
                    "orders": [
                        {
                            "order_id_masked": "abcd********5678",
                            "orderId": "abcd1234wxyz5678",
                            "clientOrderId": "client-order-raw",
                            "accountNo": "fake_account_no_for_test_only",
                            "accountSeq": "123456789",
                            "X-Tossinvest-Account": "123456789",
                            "Authorization": "Bearer fake",
                            "access_token": "fake_access_token_value_for_test_only",
                            "client_secret": "fake_client_secret_for_test_only",
                            "raw_response": {"secret": "must-not-render"},
                            "symbol": "035250",
                            "side": "BUY",
                            "order_type": "LIMIT",
                            "status": "FILLED",
                            "price": "16000",
                            "quantity": "2",
                            "currency": "KRW",
                            "ordered_at": "2026-06-16T09:30:00+09:00",
                            "execution": {
                                "filled_quantity": "2",
                                "average_filled_price": "16000",
                                "filled_amount": "32000",
                                "settlement_date": "2026-06-18",
                                "token": "fake_access_token_value_for_test_only",
                            },
                        }
                    ],
                    "raw_summary": {"nextCursor": "cursor-raw-value"},
                    "headers": {"Authorization": "Bearer fake"},
                    "request": {"accountSeq": "123456789"},
                    "response": {"raw": True},
                }

        return FakeProvider()

    def test_toss_order_history_page_requires_staff(self):
        url = "/operations/toss/order-history/"
        non_staff_user = User.objects.create_user(username="order_history_page_non_staff", password="pw12345")
        non_staff_client = Client()
        non_staff_client.login(username=non_staff_user.username, password="pw12345")

        with patch("data_pipeline.views._build_toss_order_history_provider") as mock_provider:
            anonymous_response = Client().get(url)
            non_staff_response = non_staff_client.get(url)

        self.assertIn(anonymous_response.status_code, (status.HTTP_302_FOUND, status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
        self.assertEqual(non_staff_response.status_code, status.HTTP_403_FORBIDDEN)
        mock_provider.assert_not_called()

    def test_toss_order_history_page_default_get_renders_form_without_provider_call(self):
        before_log_count = DataIngestionLog.objects.count()
        client = self._staff_order_history_page_client()

        with patch("data_pipeline.views._build_toss_order_history_provider") as mock_provider:
            response = client.get("/operations/toss/order-history/")

        content = response.content.decode("utf-8")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_provider.assert_not_called()
        self.assertContains(response, "Toss 주문/체결 내역 조회")
        self.assertContains(response, "읽기 전용 조회입니다.")
        self.assertContains(response, "주문을 실행하지 않습니다.")
        self.assertContains(response, "주문 생성, 정정, 취소 기능을 제공하지 않습니다.")
        self.assertContains(response, "주문 식별자는 마스킹되어 표시됩니다.")
        self.assertContains(response, "계좌 식별자는 표시하지 않습니다.")
        self.assertContains(response, 'name="run" value="1"', html=False)
        self.assertContains(response, "조회하기")
        self.assertContains(response, "기본 진입 화면에서는 Toss API를 호출하지 않습니다.")
        self.assertNotIn("order_id_masked=", content)
        self.assertNotIn("username", content)
        self.assertNotIn("email", content)
        self.assertNotIn("user_id", content)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count)

    def test_toss_order_history_page_run_renders_sanitized_result(self):
        before_holding_count = UserHolding.objects.count()
        before_stock_count = Stock.objects.count()
        before_daily_count = DailyPrice.objects.count()
        before_provider_status_count = DataProviderStatus.objects.count()
        before_log_count = DataIngestionLog.objects.count()

        fake_provider = self._fake_order_history_provider()
        client = self._staff_order_history_page_client()
        with patch("data_pipeline.views._build_toss_order_history_provider", return_value=fake_provider) as mock_builder:
            response = client.get(
                "/operations/toss/order-history/",
                {
                    "run": "1",
                    "status": "CLOSED",
                    "symbol": "035250",
                    "from_date": "2026-06-01",
                    "to_date": "2026-06-30",
                    "cursor": "cursor-raw-value",
                    "limit": "5",
                },
            )

        content = response.content.decode("utf-8")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_builder.assert_called_once()
        self.assertEqual(
            fake_provider.calls,
            [
                {
                    "status": "CLOSED",
                    "symbol": "035250",
                    "from_date": "2026-06-01",
                    "to_date": "2026-06-30",
                    "cursor": "cursor-raw-value",
                    "limit": 5,
                }
            ],
        )
        self.assertContains(response, "조회 결과 요약")
        self.assertContains(response, "abcd********5678")
        self.assertContains(response, "035250")
        self.assertContains(response, "FILLED")
        self.assertContains(response, "next_cursor_present")
        self.assertContains(response, "network_call")
        self.assertNotIn("abcd1234wxyz5678", content)
        self.assertNotIn("orderId", content)
        self.assertNotIn("clientOrderId", content)
        self.assertNotIn("client-order-raw", content)
        self.assertNotIn("accountNo", content)
        self.assertNotIn("accountSeq", content)
        self.assertNotIn("123456789", content)
        self.assertNotIn("X-Tossinvest-Account", content)
        self.assertNotIn("Authorization", content)
        self.assertNotIn("fake_access_token_value_for_test_only", content)
        self.assertNotIn("fake_client_secret_for_test_only", content)
        self.assertNotIn("raw_response", content)
        self.assertNotIn("raw_summary", content)
        self.assertNotIn("cursor-raw-value", content)
        self.assertNotIn("주문하기", content)
        self.assertNotIn("취소하기", content)
        self.assertNotIn("정정하기", content)
        self.assertNotIn("자동매매", content)
        self.assertEqual(UserHolding.objects.count(), before_holding_count)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(DataProviderStatus.objects.count(), before_provider_status_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count)

    def test_toss_order_history_page_validation_error_does_not_call_provider(self):
        client = self._staff_order_history_page_client()

        with patch("data_pipeline.views._build_toss_order_history_provider") as mock_provider:
            response = client.get(
                "/operations/toss/order-history/",
                {"run": "1", "status": "BAD", "symbol": "035250,000660"},
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_provider.assert_not_called()
        self.assertContains(response, "invalid_query")
        self.assertContains(response, "Order history query is invalid.")

    def test_toss_order_history_page_provider_error_is_safe(self):
        class FakeProvider:
            def get_order_history_candidates(self, **_kwargs):
                raise TossOpenApiError("raw api body")

        client = self._staff_order_history_page_client()
        with patch("data_pipeline.views._build_toss_order_history_provider", return_value=FakeProvider()):
            response = client.get("/operations/toss/order-history/", {"run": "1", "status": "CLOSED"})

        content = response.content.decode("utf-8")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertContains(response, "order_history_request_failed")
        self.assertContains(response, "Toss order history request failed.")
        self.assertNotIn("raw api body", content)

    def _staff_toss_customer_info_client(self):
        staff_user = User.objects.create_user(username="toss_customer_info_staff", password="pw12345", is_staff=True)
        client = Client()
        client.login(username=staff_user.username, password="pw12345")
        return client

    def _fake_toss_accounts_provider(self):
        class FakeProvider:
            def __init__(self):
                self.calls = 0

            def get_accounts(self):
                self.calls += 1
                return {
                    "provider": "toss",
                    "endpoint": "/api/v1/accounts",
                    "dry_run": True,
                    "account_count": 1,
                    "account_types": ["BROKERAGE"],
                    "account_seq_usable_count": 1,
                    "accounts": [
                        {
                            "account_type": "BROKERAGE",
                            "masked": "1234********5678",
                            "account_seq_shape": "integer_like",
                            "account_seq_usable": True,
                            "accountNo": "fake_account_no_for_test_only",
                            "accountSeq": "123456789",
                            "Authorization": "Bearer fake",
                            "access_token": "fake_access_token_value_for_test_only",
                        }
                    ],
                    "raw": {
                        "accountNo": "fake_account_no_for_test_only",
                        "accountSeq": "123456789",
                        "raw_response": {"secret": "must-not-render"},
                    },
                }

        return FakeProvider()

    def test_toss_customer_info_page_requires_staff(self):
        url = "/operations/toss/customer-info/"
        non_staff_user = User.objects.create_user(username="toss_customer_info_non_staff", password="pw12345")
        non_staff_client = Client()
        non_staff_client.login(username=non_staff_user.username, password="pw12345")

        with patch("data_pipeline.views._build_toss_accounts_provider") as mock_provider:
            anonymous_response = Client().get(url)
            non_staff_response = non_staff_client.get(url)

        self.assertIn(anonymous_response.status_code, (status.HTTP_302_FOUND, status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
        self.assertEqual(non_staff_response.status_code, status.HTTP_403_FORBIDDEN)
        mock_provider.assert_not_called()

    def test_toss_customer_info_page_default_get_does_not_call_provider(self):
        before_log_count = DataIngestionLog.objects.count()
        client = self._staff_toss_customer_info_client()

        with patch("data_pipeline.views._build_toss_accounts_provider") as mock_provider:
            response = client.get("/operations/toss/customer-info/")

        content = response.content.decode("utf-8")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_provider.assert_not_called()
        self.assertContains(response, "Toss 고객/계좌 정보 조회")
        self.assertContains(response, "staff-only read-only 조회입니다.")
        self.assertContains(response, "기본 진입 화면에서는 Toss API를 호출하지 않습니다.")
        self.assertContains(response, 'name="run" value="1"', html=False)
        self.assertNotIn("accountNo", content)
        self.assertNotIn("accountSeq", content)
        self.assertNotIn("Authorization", content)
        self.assertNotIn("access_token", content)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count)

    def test_toss_customer_info_page_run_renders_sanitized_result(self):
        before_holding_count = UserHolding.objects.count()
        before_stock_count = Stock.objects.count()
        before_daily_count = DailyPrice.objects.count()
        before_provider_status_count = DataProviderStatus.objects.count()
        before_log_count = DataIngestionLog.objects.count()

        fake_provider = self._fake_toss_accounts_provider()
        client = self._staff_toss_customer_info_client()
        with patch("data_pipeline.views._build_toss_accounts_provider", return_value=fake_provider) as mock_builder:
            response = client.get("/operations/toss/customer-info/", {"run": "1"})

        content = response.content.decode("utf-8")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_builder.assert_called_once()
        self.assertEqual(fake_provider.calls, 1)
        self.assertContains(response, "조회 결과 요약")
        self.assertContains(response, "/api/v1/accounts")
        self.assertContains(response, "BROKERAGE")
        self.assertContains(response, "1234********5678")
        self.assertContains(response, "network_call")
        self.assertNotIn("fake_account_no_for_test_only", content)
        self.assertNotIn("accountNo", content)
        self.assertNotIn("accountSeq", content)
        self.assertNotIn("123456789", content)
        self.assertNotIn("Authorization", content)
        self.assertNotIn("fake_access_token_value_for_test_only", content)
        self.assertNotIn("raw_response", content)
        self.assertNotIn("must-not-render", content)
        self.assertNotIn("주문하기", content)
        self.assertNotIn("취소하기", content)
        self.assertNotIn("정정하기", content)
        self.assertNotIn("자동매매", content)
        self.assertEqual(UserHolding.objects.count(), before_holding_count)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(DataProviderStatus.objects.count(), before_provider_status_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count)

    def test_toss_customer_info_page_provider_error_is_safe(self):
        class FakeProvider:
            def get_accounts(self):
                raise TossOpenApiError("raw accounts api body")

        client = self._staff_toss_customer_info_client()
        with patch("data_pipeline.views._build_toss_accounts_provider", return_value=FakeProvider()):
            response = client.get("/operations/toss/customer-info/", {"run": "1"})

        content = response.content.decode("utf-8")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertContains(response, "toss_accounts_request_failed")
        self.assertContains(response, "Toss accounts request failed.")
        self.assertNotIn("raw accounts api body", content)


class OrderHistoryReconciliationAPITests(TestCase):
    url = "/api/operations/toss/order-history/reconciliation/"

    def setUp(self):
        self.user = User.objects.create_user(username="reconciliation_api_user", password="pw12345")
        self.staff_user = User.objects.create_user(
            username="reconciliation_api_staff",
            password="pw12345",
            is_staff=True,
        )
        self.stock = Stock.objects.create(code="035250", name="강원랜드", market=Stock.MARKET_KOSPI)

    def _staff_client(self):
        client = APIClient()
        client.force_authenticate(self.staff_user)
        return client

    def _non_staff_client(self):
        client = APIClient()
        client.force_authenticate(self.user)
        return client

    def _fake_provider(self, payload):
        class FakeProvider:
            def __init__(self, result):
                self.result = result
                self.calls = []

            def get_order_history_candidates(self, **kwargs):
                self.calls.append(kwargs)
                return self.result

        return FakeProvider(payload)

    def _payload_with_sensitive_fields(self):
        return {
            "provider": "toss",
            "endpoint": "/api/v1/orders",
            "status_filter": "CLOSED",
            "symbol": "035250",
            "order_count": 2,
            "has_next": True,
            "next_cursor_present": True,
            "nextCursor": "cursor-raw-value",
            "orders": [
                {
                    "order_id_masked": "abcd********5678",
                    "orderId": "abcd1234wxyz5678",
                    "clientOrderId": "client-order-raw",
                    "accountNo": "fake_account_no_for_test_only",
                    "accountSeq": "123456789",
                    "X-Tossinvest-Account": "123456789",
                    "Authorization": "Bearer fake",
                    "access_token": "fake_access_token_value_for_test_only",
                    "raw_response": {"secret": "must-not-return"},
                    "symbol": "035250",
                    "side": "BUY",
                    "status": "FILLED",
                    "execution": {
                        "filled_quantity": "2",
                        "average_filled_price": "16000",
                        "filled_amount": "32000",
                        "commission": "64",
                        "tax": "0",
                    },
                },
                {
                    "order_id_masked": "sell********1111",
                    "symbol": "035250",
                    "side": "SELL",
                    "status": "FILLED",
                    "execution": {
                        "filled_quantity": "1",
                        "average_filled_price": "17000",
                        "filled_amount": "17000",
                        "commission": "34",
                        "tax": "20",
                    },
                },
            ],
            "raw_summary": {"nextCursor": "cursor-raw-value"},
            "headers": {"Authorization": "Bearer fake"},
            "request": {"accountSeq": "123456789"},
            "response": {"raw": True},
        }

    def test_reconciliation_api_requires_staff(self):
        with patch("data_pipeline.views._build_toss_order_history_provider") as mock_provider:
            anonymous_response = APIClient().get(self.url, {"symbol": "035250"})
            non_staff_response = self._non_staff_client().get(self.url, {"symbol": "035250"})

        self.assertIn(anonymous_response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))
        self.assertEqual(non_staff_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(non_staff_response.data["error"], "staff_required")
        mock_provider.assert_not_called()

    def test_reconciliation_api_staff_success_returns_safe_summary(self):
        UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("15500.00"),
            quantity=1,
        )
        before_holding_count = UserHolding.objects.count()
        before_stock_count = Stock.objects.count()
        before_daily_count = DailyPrice.objects.count()
        before_provider_status_count = DataProviderStatus.objects.count()
        before_log_count = DataIngestionLog.objects.count()

        fake_provider = self._fake_provider(self._payload_with_sensitive_fields())
        client = self._staff_client()
        with patch("data_pipeline.views._build_toss_order_history_provider", return_value=fake_provider) as mock_builder:
            response = client.get(
                self.url,
                {
                    "symbol": "035250",
                    "from_date": "2026-01-01",
                    "to_date": "2026-06-17",
                    "limit": "5",
                },
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_builder.assert_called_once()
        self.assertEqual(
            fake_provider.calls,
            [
                {
                    "status": "CLOSED",
                    "symbol": "035250",
                    "from_date": "2026-01-01",
                    "to_date": "2026-06-17",
                    "limit": 5,
                }
            ],
        )
        payload = response.data
        payload_repr = repr(payload)
        self.assertEqual(payload["report_type"], "order_history_reconciliation")
        self.assertTrue(payload["read_only"])
        self.assertFalse(payload["order_execution"])
        self.assertEqual(payload["symbol"], "035250")
        self.assertEqual(payload["order_history"]["order_count"], 2)
        self.assertTrue(payload["order_history"]["has_next"])
        self.assertTrue(payload["order_history"]["next_cursor_present"])
        self.assertEqual(payload["aggregates"]["buy_order_count"], 1)
        self.assertEqual(payload["aggregates"]["sell_order_count"], 1)
        self.assertEqual(payload["aggregates"]["net_filled_quantity"], "1")
        self.assertEqual(payload["aggregates"]["weighted_average_buy_price"], "16000.00")
        self.assertTrue(payload["user_holding_comparison"]["matching_user_holding_exists"])
        self.assertIn("warnings", payload)
        self.assertNotIn("orders", payload)
        for forbidden in [
            "orderId",
            "abcd1234wxyz5678",
            "clientOrderId",
            "client-order-raw",
            "accountNo",
            "accountSeq",
            "123456789",
            "X-Tossinvest-Account",
            "Authorization",
            "fake_access_token_value_for_test_only",
            "raw_response",
            "raw_summary",
            "cursor-raw-value",
            "user_id",
            "username",
            "email",
        ]:
            self.assertNotIn(forbidden, payload_repr)
        self.assertEqual(UserHolding.objects.count(), before_holding_count)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(DataProviderStatus.objects.count(), before_provider_status_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count)

    def test_reconciliation_api_validates_query_and_rejects_unsupported_params(self):
        client = self._staff_client()
        invalid_queries = [
            {},
            {"symbol": "035250,000660"},
            {"symbol": "035250/evil"},
            {"symbol": "035250 KR"},
            {"symbol": "035250", "from_date": "20260101"},
            {"symbol": "035250", "to_date": "2026-1-1"},
            {"symbol": "035250", "limit": "0"},
            {"symbol": "035250", "limit": "101"},
            {"symbol": "035250", "status": "CLOSED"},
            {"symbol": "035250", "cursor": "cursor-raw-value"},
            {"symbol": "035250", "account": "123456789"},
            {"symbol": "035250", "raw": "true"},
            {"symbol": "035250", "user_id": "1"},
            {"symbol": "035250", "username": "someone"},
            {"symbol": "035250", "email": "person@example.test"},
        ]

        with patch("data_pipeline.views._build_toss_order_history_provider") as mock_provider:
            for query in invalid_queries:
                with self.subTest(query=query):
                    response = client.get(self.url, query)
                    self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                    self.assertEqual(response.data["error"], "invalid_query")

        mock_provider.assert_not_called()

    def test_reconciliation_api_maps_service_and_unknown_errors_safely(self):
        class BadPayloadProvider:
            def get_order_history_candidates(self, **_kwargs):
                return {"orders": "not-a-list"}

        client = self._staff_client()
        with patch("data_pipeline.views._build_toss_order_history_provider", return_value=BadPayloadProvider()):
            response = client.get(self.url, {"symbol": "035250"})

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "unsupported_order_history_payload")
        self.assertNotIn("not-a-list", repr(response.data))

        with patch("data_pipeline.views.build_order_history_reconciliation", side_effect=RuntimeError("raw secret")):
            with patch("data_pipeline.views._build_toss_order_history_provider", return_value=object()):
                unknown_response = client.get(self.url, {"symbol": "035250"})

        self.assertEqual(unknown_response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(unknown_response.data["error"], "order_history_reconciliation_failed")
        self.assertNotIn("raw secret", repr(unknown_response.data))

    def test_reconciliation_api_rejects_post(self):
        response = self._staff_client().post(self.url, {"symbol": "035250"})

        self.assertEqual(response.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)


class OrderHistoryReconciliationPageTests(TestCase):
    url = "/operations/toss/order-history/reconciliation/"

    def setUp(self):
        self.user = User.objects.create_user(username="reconciliation_page_user", password="pw12345")
        self.staff_user = User.objects.create_user(
            username="reconciliation_page_staff",
            password="pw12345",
            is_staff=True,
        )
        self.stock = Stock.objects.create(code="035250", name="강원랜드", market=Stock.MARKET_KOSPI)

    def _staff_client(self):
        client = Client()
        client.login(username=self.staff_user.username, password="pw12345")
        return client

    def _non_staff_client(self):
        client = Client()
        client.login(username=self.user.username, password="pw12345")
        return client

    def _fake_provider(self, payload):
        class FakeProvider:
            def __init__(self, result):
                self.result = result
                self.calls = []

            def get_order_history_candidates(self, **kwargs):
                self.calls.append(kwargs)
                return self.result

        return FakeProvider(payload)

    def _payload_with_sensitive_fields(self):
        return {
            "provider": "toss",
            "endpoint": "/api/v1/orders",
            "status_filter": "CLOSED",
            "symbol": "035250",
            "order_count": 2,
            "has_next": True,
            "next_cursor_present": True,
            "nextCursor": "cursor-raw-value",
            "orders": [
                {
                    "order_id_masked": "abcd********5678",
                    "orderId": "abcd1234wxyz5678",
                    "clientOrderId": "client-order-raw",
                    "accountNo": "fake_account_no_for_test_only",
                    "accountSeq": "123456789",
                    "X-Tossinvest-Account": "123456789",
                    "Authorization": "Bearer fake",
                    "access_token": "fake_access_token_value_for_test_only",
                    "raw_response": {"secret": "must-not-render"},
                    "symbol": "035250",
                    "side": "BUY",
                    "status": "FILLED",
                    "execution": {
                        "filled_quantity": "2",
                        "average_filled_price": "16000",
                        "filled_amount": "32000",
                        "commission": "64",
                        "tax": "0",
                    },
                },
                {
                    "order_id_masked": "sell********1111",
                    "symbol": "035250",
                    "side": "SELL",
                    "status": "FILLED",
                    "execution": {
                        "filled_quantity": "1",
                        "average_filled_price": "17000",
                        "filled_amount": "17000",
                        "commission": "34",
                        "tax": "20",
                    },
                },
            ],
            "raw_summary": {"nextCursor": "cursor-raw-value"},
            "headers": {"Authorization": "Bearer fake"},
            "request": {"accountSeq": "123456789"},
            "response": {"raw": True},
            "user_id": "999",
            "username": "must-not-render",
            "email": "must-not-render@example.test",
        }

    def test_reconciliation_page_requires_staff(self):
        with patch("data_pipeline.views._build_toss_order_history_provider") as mock_provider:
            anonymous_response = Client().get(self.url)
            non_staff_response = self._non_staff_client().get(self.url)

        self.assertIn(
            anonymous_response.status_code,
            (status.HTTP_302_FOUND, status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN),
        )
        self.assertEqual(non_staff_response.status_code, status.HTTP_403_FORBIDDEN)
        mock_provider.assert_not_called()

    def test_reconciliation_page_default_get_renders_form_without_provider_call(self):
        before_log_count = DataIngestionLog.objects.count()
        client = self._staff_client()

        with patch("data_pipeline.views._build_toss_order_history_provider") as mock_provider:
            response = client.get(self.url)

        content = response.content.decode("utf-8")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_provider.assert_not_called()
        self.assertContains(response, "Toss 주문/체결 정합성 참고 비교")
        self.assertContains(response, "staff-only read-only report")
        self.assertContains(response, "공식 실현손익 계산이 아닙니다.")
        self.assertContains(response, "주문을 실행하지 않습니다.")
        self.assertContains(response, "order id 원문과 계좌 식별자는 표시하지 않습니다.")
        self.assertContains(response, 'name="run" value="1"', html=False)
        self.assertContains(response, 'name="symbol"', html=False)
        self.assertContains(response, "비교 조회")
        self.assertContains(response, "symbol을 입력하고 비교 조회를 실행하세요.")
        for forbidden in [
            'name="status"',
            'name="cursor"',
            'name="account"',
            'name="user_id"',
            'name="username"',
            'name="email"',
            "orderId",
            "clientOrderId",
            "accountNo",
            "accountSeq",
            "X-Tossinvest-Account",
            "Authorization",
            "access_token",
            "raw_response",
            "nextCursor",
            "주문하기",
            "취소하기",
            "정정하기",
            "자동매매",
        ]:
            self.assertNotIn(forbidden, content)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count)

    def test_reconciliation_page_run_renders_safe_summary(self):
        UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("15500.00"),
            quantity=1,
        )
        before_holding_count = UserHolding.objects.count()
        before_stock_count = Stock.objects.count()
        before_daily_count = DailyPrice.objects.count()
        before_provider_status_count = DataProviderStatus.objects.count()
        before_log_count = DataIngestionLog.objects.count()

        fake_provider = self._fake_provider(self._payload_with_sensitive_fields())
        client = self._staff_client()
        with patch("data_pipeline.views._build_toss_order_history_provider", return_value=fake_provider) as mock_builder:
            response = client.get(
                self.url,
                {
                    "run": "1",
                    "symbol": "035250",
                    "from_date": "2026-01-01",
                    "to_date": "2026-06-17",
                    "limit": "5",
                },
            )

        content = response.content.decode("utf-8")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_builder.assert_called_once()
        self.assertEqual(
            fake_provider.calls,
            [
                {
                    "status": "CLOSED",
                    "symbol": "035250",
                    "from_date": "2026-01-01",
                    "to_date": "2026-06-17",
                    "limit": 5,
                }
            ],
        )
        self.assertContains(response, "order_history_reconciliation")
        self.assertContains(response, "read_only")
        self.assertContains(response, "order_execution")
        self.assertContains(response, "order_count")
        self.assertContains(response, "has_next")
        self.assertContains(response, "next_cursor_present")
        self.assertContains(response, "weighted_average_buy_price")
        self.assertContains(response, "16000.00")
        self.assertContains(response, "matching_user_holding_count")
        self.assertContains(response, "user_holding_average_price")
        self.assertContains(response, "15500.00")
        self.assertContains(response, "This is a staff-only read-only reconciliation report.")
        self.assertContains(response, "This is not an official realized P&amp;L calculation.")
        for forbidden in [
            "order_id_masked",
            "abcd********5678",
            "orderId",
            "abcd1234wxyz5678",
            "clientOrderId",
            "client-order-raw",
            "accountNo",
            "accountSeq",
            "123456789",
            "X-Tossinvest-Account",
            "Authorization",
            "fake_access_token_value_for_test_only",
            "raw_response",
            "raw_summary",
            "cursor-raw-value",
            "user_id",
            "username",
            "must-not-render",
            "email",
            "주문하기",
            "취소하기",
            "정정하기",
            "자동매매",
        ]:
            self.assertNotIn(forbidden, content)
        self.assertEqual(UserHolding.objects.count(), before_holding_count)
        self.assertEqual(Stock.objects.count(), before_stock_count)
        self.assertEqual(DailyPrice.objects.count(), before_daily_count)
        self.assertEqual(DataProviderStatus.objects.count(), before_provider_status_count)
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count)

    def test_reconciliation_page_validation_error_does_not_call_provider(self):
        client = self._staff_client()

        with patch("data_pipeline.views._build_toss_order_history_provider") as mock_provider:
            response = client.get(self.url, {"run": "1", "status": "CLOSED"})

        content = response.content.decode("utf-8")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_provider.assert_not_called()
        self.assertContains(response, "invalid_query")
        self.assertContains(response, "Order history reconciliation query is invalid.")
        self.assertNotIn("status:", content)
        self.assertNotIn("user_id", content)

    def test_reconciliation_page_service_error_is_safe(self):
        client = self._staff_client()
        with patch("data_pipeline.views._build_toss_order_history_provider", return_value=object()):
            with patch(
                "data_pipeline.views.build_order_history_reconciliation",
                side_effect=OrderHistoryReconciliationError("unsupported_order_history_payload", "Order history payload is unsupported."),
            ):
                response = client.get(self.url, {"run": "1", "symbol": "035250"})

        content = response.content.decode("utf-8")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertContains(response, "unsupported_order_history_payload")
        self.assertContains(response, "Order history payload is unsupported.")
        self.assertNotIn("raw", content)


class OrderHistoryReconciliationServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="reconciliation_user", password="pw12345")
        self.stock = Stock.objects.create(code="035250", name="강원랜드", market=Stock.MARKET_KOSPI)

    def _fake_provider(self, payload):
        class FakeProvider:
            def __init__(self, result):
                self.result = result
                self.calls = []

            def get_order_history_candidates(self, **kwargs):
                self.calls.append(kwargs)
                return self.result

        return FakeProvider(payload)

    def _base_payload(self, *, has_next=False):
        return {
            "provider": "toss",
            "endpoint": "/api/v1/orders",
            "status_filter": "CLOSED",
            "symbol": "035250",
            "network_call": True,
            "dry_run": True,
            "order_count": 4,
            "has_next": has_next,
            "next_cursor_present": has_next,
            "nextCursor": "cursor-raw-value",
            "orders": [
                {
                    "order_id_masked": "abcd********5678",
                    "orderId": "abcd1234wxyz5678",
                    "clientOrderId": "client-order-raw",
                    "accountNo": "fake_account_no_for_test_only",
                    "accountSeq": "123456789",
                    "X-Tossinvest-Account": "123456789",
                    "Authorization": "Bearer fake",
                    "access_token": "fake_access_token_value_for_test_only",
                    "raw_response": {"secret": "must-not-return"},
                    "symbol": "035250",
                    "side": "BUY",
                    "status": "FILLED",
                    "quantity": "2",
                    "price": "16000",
                    "execution": {
                        "filled_quantity": "2",
                        "average_filled_price": "16000",
                        "filled_amount": "32000",
                        "commission": "64",
                        "tax": "0",
                    },
                },
                {
                    "order_id_masked": "efgh********9999",
                    "symbol": "035250",
                    "side": "BUY",
                    "status": "FILLED",
                    "execution": {
                        "filled_quantity": "1",
                        "average_filled_price": "17000",
                        "commission": "34",
                        "tax": "0",
                    },
                },
                {
                    "order_id_masked": "sell********1111",
                    "symbol": "035250",
                    "side": "SELL",
                    "status": "FILLED",
                    "execution": {
                        "filled_quantity": "1",
                        "average_filled_price": "18000",
                        "filled_amount": "18000",
                        "commission": "36",
                        "tax": "20",
                    },
                },
                {
                    "order_id_masked": "skip********2222",
                    "symbol": "035250",
                    "side": "BUY",
                    "status": "CANCELED",
                    "execution": {
                        "filled_quantity": "0",
                        "average_filled_price": "16000",
                    },
                },
            ],
            "raw_summary": {"nextCursor": "cursor-raw-value"},
        }

    def test_reconciliation_builds_safe_aggregate_and_holding_comparison(self):
        UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("15500.00"),
            quantity=2,
        )
        before_log_count = DataIngestionLog.objects.count()
        before_provider_status_count = DataProviderStatus.objects.count()
        provider = self._fake_provider(self._base_payload(has_next=True))

        result = build_order_history_reconciliation(
            provider=provider,
            symbol="035250",
            from_date="2026-01-01",
            to_date="2026-06-17",
            limit=5,
        )

        self.assertEqual(
            provider.calls,
            [
                {
                    "status": "CLOSED",
                    "symbol": "035250",
                    "from_date": "2026-01-01",
                    "to_date": "2026-06-17",
                    "limit": 5,
                }
            ],
        )
        self.assertEqual(result["report_type"], "order_history_reconciliation")
        self.assertTrue(result["read_only"])
        self.assertFalse(result["order_execution"])
        self.assertEqual(result["provider"], "toss")
        self.assertEqual(result["symbol"], "035250")
        self.assertEqual(result["order_history"]["order_count"], 4)
        self.assertTrue(result["order_history"]["has_next"])
        self.assertTrue(result["order_history"]["next_cursor_present"])
        self.assertFalse(result["order_history"]["used_cursor"])

        aggregates = result["aggregates"]
        self.assertEqual(aggregates["buy_order_count"], 2)
        self.assertEqual(aggregates["sell_order_count"], 1)
        self.assertEqual(aggregates["skipped_execution_count"], 1)
        self.assertEqual(aggregates["buy_filled_quantity_sum"], "3")
        self.assertEqual(aggregates["sell_filled_quantity_sum"], "1")
        self.assertEqual(aggregates["net_filled_quantity"], "2")
        self.assertEqual(aggregates["buy_filled_amount_sum"], "49000.00")
        self.assertEqual(aggregates["sell_filled_amount_sum"], "18000.00")
        self.assertEqual(aggregates["buy_commission_sum"], "98.00")
        self.assertEqual(aggregates["sell_commission_sum"], "36.00")
        self.assertEqual(aggregates["buy_tax_sum"], "0.00")
        self.assertEqual(aggregates["sell_tax_sum"], "20.00")
        self.assertEqual(aggregates["weighted_average_buy_price"], "16333.33")

        comparison = result["user_holding_comparison"]
        self.assertTrue(comparison["matching_user_holding_exists"])
        self.assertEqual(comparison["matching_user_holding_count"], 1)
        self.assertEqual(comparison["user_holding_quantity"], "2")
        self.assertEqual(comparison["user_holding_average_price"], "15500.00")
        self.assertEqual(comparison["quantity_difference"], "0")
        self.assertEqual(comparison["average_price_difference"], "-833.33")

        result_repr = repr(result)
        self.assertNotIn("orders", result)
        self.assertNotIn("orderId", result_repr)
        self.assertNotIn("abcd1234wxyz5678", result_repr)
        self.assertNotIn("clientOrderId", result_repr)
        self.assertNotIn("client-order-raw", result_repr)
        self.assertNotIn("accountNo", result_repr)
        self.assertNotIn("accountSeq", result_repr)
        self.assertNotIn("123456789", result_repr)
        self.assertNotIn("X-Tossinvest-Account", result_repr)
        self.assertNotIn("Authorization", result_repr)
        self.assertNotIn("fake_access_token_value_for_test_only", result_repr)
        self.assertNotIn("raw_response", result_repr)
        self.assertNotIn("cursor-raw-value", result_repr)
        self.assertNotIn("user_id", result_repr)
        self.assertNotIn("username", result_repr)
        self.assertNotIn("email", result_repr)
        self.assertTrue(any("not an official realized P&L" in warning for warning in result["warnings"]))
        self.assertTrue(any("more pages exist" in warning for warning in result["warnings"]))
        self.assertTrue(any("fallback" in warning for warning in result["warnings"]))
        self.assertEqual(DataIngestionLog.objects.count(), before_log_count)
        self.assertEqual(DataProviderStatus.objects.count(), before_provider_status_count)

    def test_reconciliation_warns_without_matching_holding(self):
        provider = self._fake_provider({"provider": "toss", "orders": [], "order_count": 0})

        result = build_order_history_reconciliation(provider=provider, symbol="035250")

        self.assertFalse(result["user_holding_comparison"]["matching_user_holding_exists"])
        self.assertEqual(result["user_holding_comparison"]["matching_user_holding_count"], 0)
        self.assertTrue(any("No matching UserHolding" in warning for warning in result["warnings"]))

    def test_reconciliation_multiple_holdings_do_not_return_user_details(self):
        other_user = User.objects.create_user(username="reconciliation_other", password="pw12345")
        UserHolding.objects.create(user=self.user, stock=self.stock, average_price=Decimal("15000.00"), quantity=2)
        UserHolding.objects.create(user=other_user, stock=self.stock, average_price=Decimal("16000.00"), quantity=3)
        provider = self._fake_provider({"provider": "toss", "orders": [], "order_count": 0})

        result = build_order_history_reconciliation(provider=provider, symbol="035250")

        comparison = result["user_holding_comparison"]
        result_repr = repr(result)
        self.assertTrue(comparison["matching_user_holding_exists"])
        self.assertEqual(comparison["matching_user_holding_count"], 2)
        self.assertIsNone(comparison["user_holding_quantity"])
        self.assertIsNone(comparison["user_holding_average_price"])
        self.assertTrue(any("Multiple matching UserHolding" in warning for warning in result["warnings"]))
        self.assertNotIn("user_id", result_repr)
        self.assertNotIn("reconciliation_user", result_repr)
        self.assertNotIn("reconciliation_other", result_repr)

    def test_reconciliation_validates_inputs(self):
        provider = self._fake_provider({"provider": "toss", "orders": []})
        invalid_cases = [
            ({"provider": None, "symbol": "035250"}, "provider_required"),
            ({"provider": provider, "symbol": ""}, "symbol_required"),
            ({"provider": provider, "symbol": "035250,000660"}, "invalid_symbol"),
            ({"provider": provider, "symbol": "035250/evil"}, "invalid_symbol"),
            ({"provider": provider, "symbol": "035250", "from_date": "20260101"}, "invalid_date"),
            ({"provider": provider, "symbol": "035250", "to_date": "2026-1-1"}, "invalid_date"),
            ({"provider": provider, "symbol": "035250", "limit": 0}, "invalid_limit"),
            ({"provider": provider, "symbol": "035250", "limit": 101}, "invalid_limit"),
        ]

        for kwargs, expected_code in invalid_cases:
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(OrderHistoryReconciliationError) as context:
                    build_order_history_reconciliation(**kwargs)
                self.assertEqual(context.exception.code, expected_code)

    def test_reconciliation_provider_exception_is_safe(self):
        class FakeProvider:
            def get_order_history_candidates(self, **_kwargs):
                raise RuntimeError("raw exception with secret")

        with self.assertRaises(OrderHistoryReconciliationError) as context:
            build_order_history_reconciliation(provider=FakeProvider(), symbol="035250")

        self.assertEqual(context.exception.code, "order_history_request_failed")
        self.assertEqual(context.exception.message, "Order history request failed.")
        self.assertNotIn("raw exception with secret", str(context.exception))

    def test_reconciliation_rejects_unsupported_payload(self):
        provider = self._fake_provider({"provider": "toss", "orders": "not-a-list"})

        with self.assertRaises(OrderHistoryReconciliationError) as context:
            build_order_history_reconciliation(provider=provider, symbol="035250")

        self.assertEqual(context.exception.code, "unsupported_order_history_payload")


class DataPipelineConsultIntegrationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="consult_snapshot", password="pw12345")
        self.stock = Stock.objects.create(code="555555", name="컨설팅", market=Stock.MARKET_KOSPI)
        self.holding = UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("120.00"),
            quantity=10,
            max_additional_budget=Decimal("1000000.00"),
        )
        start = timezone.localdate() - timedelta(days=119)
        for offset in range(120):
            close_price = Decimal("90.00") + Decimal(offset) / Decimal("2")
            DailyPrice.objects.create(
                stock=self.stock,
                date=start + timedelta(days=offset),
                open_price=close_price - Decimal("1.00"),
                high_price=close_price + Decimal("2.00"),
                low_price=close_price - Decimal("2.00"),
                close_price=close_price,
                volume=3000,
            )
        for index in range(20):
            InvestorFlow.objects.create(stock=self.stock, date=timezone.localdate() - timedelta(days=19 - index))
        for offset in range(60):
            MarketIndex.objects.create(
                code="KOSPI",
                name="KOSPI",
                date=timezone.localdate() - timedelta(days=59 - offset),
                close_value=Decimal("2400.00") + Decimal(offset),
                change_rate=Decimal("0.5000"),
            )
            MarketIndex.objects.create(
                code="NASDAQ",
                name="NASDAQ",
                date=timezone.localdate() - timedelta(days=59 - offset),
                close_value=Decimal("15000.00") + Decimal(offset),
                change_rate=Decimal("0.5000"),
            )
        DataQualitySnapshot.objects.create(
            stock=self.stock,
            as_of_date="2026-04-30",
            price_data_days=120,
            latest_price_age_days=1,
            investor_flow_days=20,
            market_data_available=True,
            financial_data_available=False,
            missing_fields=["financial_snapshots"],
            anomaly_flags=[],
            overall_score=Decimal("0.3000"),
            quality_grade="D",
        )

    def test_consult_holding_includes_snapshot_quality_and_caps_grade(self):
        result = consult_holding(self.holding)

        self.assertEqual(result.data_quality["quality_grade"], "D")
        self.assertEqual(result.final_grade, "C")


class DataPipelineServiceTests(TestCase):
    def test_convert_data_quality_grade(self):
        self.assertEqual(convert_data_quality_grade(Decimal("0.8000")), "A")
        self.assertEqual(convert_data_quality_grade(Decimal("0.6000")), "B")
        self.assertEqual(convert_data_quality_grade(Decimal("0.4000")), "C")
        self.assertEqual(convert_data_quality_grade(Decimal("0.3999")), "D")
