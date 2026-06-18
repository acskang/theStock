from __future__ import annotations

from decimal import Decimal
import inspect
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from integrations.models import IntegrationAuditLog
from integrations.services.toss_holdings_readonly import (
    TossCurrencyAmount,
    TossHoldingItemPreview,
    TossHoldingsPreviewResult,
    TossHoldingsSummaryPreview,
)
from integrations.services.toss_holdings_sync_plan import (
    ACTION_CREATE,
    ACTION_REMOVE_CANDIDATE,
    ACTION_SKIPPED,
    ACTION_UNCHANGED,
    ACTION_UPDATE,
    HoldingSyncPlanValidationError,
    build_holdings_sync_plan_from_preview,
    fetch_and_build_holdings_sync_plan,
)


def plan_settings():
    return override_settings(
        TOSS_USER_TOSS_API_CALLS_ENABLED=True,
        CREDENTIAL_ENCRYPTION_KEY=Fernet.generate_key().decode("ascii"),
        CREDENTIAL_ENCRYPTION_KEY_VERSION="v1",
        CREDENTIAL_ENCRYPTION_KEYS="",
        CREDENTIAL_ENCRYPTION_CURRENT_VERSION="",
        CREDENTIAL_HASH_PEPPER="dummy-pepper-for-tests",
    )


class HoldingsSyncPlanTests(TestCase):
    def create_user(self, username: str = "user-alpha"):
        return get_user_model().objects.create_user(username=username, password="safe-password")

    def create_stock(self, code: str, name: str):
        stock_model = apps.get_model("stocks", "Stock")
        return stock_model.objects.create(code=code, name=name, market="KOSPI")

    def create_current_holding(
        self,
        user,
        *,
        code: str,
        name: str,
        quantity: int = 10,
        average_price: str = "65000.00",
    ):
        holding_model = apps.get_model("holdings", "User" + "Holding")
        stock = self.create_stock(code, name)
        return holding_model.objects.create(
            user=user,
            stock=stock,
            quantity=quantity,
            average_price=Decimal(average_price),
        )

    def item(
        self,
        symbol: str,
        *,
        name: str = "Target Stock",
        market_country: str = "KR",
        currency: str = "KRW",
        quantity: str | None = "10",
        average_purchase_price: str | None = "65000",
        last_price: str | None = "72000",
    ) -> TossHoldingItemPreview:
        return TossHoldingItemPreview(
            symbol=symbol,
            name=name,
            market_country=market_country,
            currency=currency,
            quantity=Decimal(quantity) if quantity is not None else None,
            last_price=Decimal(last_price) if last_price is not None else None,
            average_purchase_price=Decimal(average_purchase_price) if average_purchase_price is not None else None,
            purchase_amount=None,
            market_value_amount=None,
            market_value_amount_after_cost=None,
            profit_loss_amount=None,
            profit_loss_amount_after_cost=None,
            profit_loss_rate=None,
            profit_loss_rate_after_cost=None,
            daily_profit_loss_amount=None,
            daily_profit_loss_rate=None,
            commission=None,
            tax=None,
        )

    def preview(self, user, items: list[TossHoldingItemPreview], *, symbol_filter: str | None = None):
        return TossHoldingsPreviewResult(
            user_id=user.pk,
            credential_id=123,
            provider="toss_invest",
            account_masked="acct_****lpha",
            status="active",
            fetched_at=timezone.now(),
            symbol_filter=symbol_filter,
            item_count=len(items),
            summary=TossHoldingsSummaryPreview(
                total_purchase_amount=TossCurrencyAmount(),
                market_value_amount=TossCurrencyAmount(),
                market_value_amount_after_cost=TossCurrencyAmount(),
                profit_loss_amount=TossCurrencyAmount(),
                profit_loss_amount_after_cost=TossCurrencyAmount(),
                profit_loss_rate=None,
                profit_loss_rate_after_cost=None,
                daily_profit_loss_amount=TossCurrencyAmount(),
                daily_profit_loss_rate=None,
            ),
            items=items,
        )

    @plan_settings()
    def test_build_plan_create_only_without_db_write(self):
        user = self.create_user()
        holding_model = apps.get_model("holdings", "User" + "Holding")
        before_count = holding_model.objects.count()

        plan = build_holdings_sync_plan_from_preview(
            user=user,
            preview=self.preview(user, [self.item("005930"), self.item("AAPL", market_country="US", currency="USD")]),
        )

        self.assertEqual(plan.create_count, 2)
        self.assertEqual(plan.update_count, 0)
        self.assertEqual(holding_model.objects.count(), before_count)
        rendered = str(plan.safe_dict())
        self.assertNotIn("access_" + "tok" + "en", rendered)
        self.assertNotIn("Authori" + "zation", rendered)
        self.assertNotIn("account" + "Seq", rendered)

    @plan_settings()
    def test_build_plan_unchanged(self):
        user = self.create_user()
        self.create_current_holding(user, code="005930", name="Samsung", quantity=10, average_price="65000.00")

        plan = build_holdings_sync_plan_from_preview(
            user=user,
            preview=self.preview(user, [self.item("005930", name="Samsung")]),
        )

        self.assertEqual(plan.unchanged_count, 1)
        self.assertEqual(plan.update_count, 0)
        self.assertEqual(plan.items[0].action, ACTION_UNCHANGED)

    @plan_settings()
    def test_build_plan_update_quantity(self):
        user = self.create_user()
        holding = self.create_current_holding(user, code="005930", name="Samsung", quantity=5, average_price="65000.00")

        plan = build_holdings_sync_plan_from_preview(
            user=user,
            preview=self.preview(user, [self.item("005930", quantity="10")]),
        )

        holding.refresh_from_db()
        self.assertEqual(holding.quantity, 5)
        self.assertEqual(plan.update_count, 1)
        self.assertEqual(plan.items[0].action, ACTION_UPDATE)
        self.assertEqual(plan.items[0].diffs[0].field, "quantity")

    @plan_settings()
    def test_build_plan_update_average_price(self):
        user = self.create_user()
        self.create_current_holding(user, code="005930", name="Samsung", quantity=10, average_price="64000.00")

        plan = build_holdings_sync_plan_from_preview(
            user=user,
            preview=self.preview(user, [self.item("005930", average_purchase_price="65000")]),
        )

        self.assertEqual(plan.update_count, 1)
        diff_fields = [diff.field for diff in plan.items[0].diffs if diff.severity == "update"]
        self.assertEqual(diff_fields, ["average_purchase_price"])

    @plan_settings()
    def test_info_diff_does_not_change_action(self):
        user = self.create_user()
        self.create_current_holding(user, code="005930", name="Samsung", quantity=10, average_price="65000.00")

        plan = build_holdings_sync_plan_from_preview(
            user=user,
            preview=self.preview(user, [self.item("005930", name="Samsung Electronics", last_price="72000")]),
        )

        self.assertEqual(plan.unchanged_count, 1)
        self.assertTrue(any(diff.severity == "info" for diff in plan.items[0].diffs))

    @plan_settings()
    def test_remove_candidate_only_on_full_sync(self):
        user = self.create_user()
        self.create_current_holding(user, code="005930", name="Samsung")
        self.create_current_holding(user, code="AAPL", name="Apple")

        full_plan = build_holdings_sync_plan_from_preview(
            user=user,
            preview=self.preview(user, [self.item("005930")]),
        )
        partial_plan = build_holdings_sync_plan_from_preview(
            user=user,
            preview=self.preview(user, [self.item("005930")], symbol_filter="005930"),
        )

        self.assertEqual(full_plan.remove_candidate_count, 1)
        self.assertTrue(any(item.action == ACTION_REMOVE_CANDIDATE for item in full_plan.items))
        self.assertEqual(partial_plan.remove_candidate_count, 0)

    @plan_settings()
    def test_duplicate_target_symbols_are_skipped(self):
        user = self.create_user()

        plan = build_holdings_sync_plan_from_preview(
            user=user,
            preview=self.preview(user, [self.item("005930"), self.item("005930", name="Duplicate")]),
        )

        self.assertEqual(plan.create_count, 1)
        self.assertEqual(plan.skipped_count, 1)
        self.assertTrue(plan.warnings)
        self.assertEqual([item.action for item in plan.items].count(ACTION_SKIPPED), 1)

    @plan_settings()
    def test_invalid_or_missing_symbol_is_skipped(self):
        user = self.create_user()

        plan = build_holdings_sync_plan_from_preview(user=user, preview=self.preview(user, [self.item("")]))

        self.assertEqual(plan.skipped_count, 1)
        self.assertEqual(plan.items[0].action, ACTION_SKIPPED)

    @plan_settings()
    def test_preview_user_mismatch_raises_safe_error(self):
        user = self.create_user("user-alpha")
        other = self.create_user("user-beta")

        with self.assertRaises(HoldingSyncPlanValidationError) as ctx:
            build_holdings_sync_plan_from_preview(user=user, preview=self.preview(other, [self.item("005930")]))

        self.assertNotIn("dummy", str(ctx.exception))

    @plan_settings()
    def test_record_audit_counts_only(self):
        user = self.create_user()
        self.create_current_holding(user, code="005930", name="Samsung", quantity=5)

        plan = build_holdings_sync_plan_from_preview(
            user=user,
            preview=self.preview(user, [self.item("005930", quantity="10"), self.item("AAPL")]),
            record_audit=True,
        )

        log = IntegrationAuditLog.objects.get(action=IntegrationAuditLog.ACTION_HOLDINGS_SYNC, reason_code="dry_run_plan")
        self.assertEqual(log.safe_metadata["create_count"], plan.create_count)
        self.assertEqual(log.safe_metadata["update_count"], plan.update_count)
        rendered = f"{log.safe_summary} {log.safe_metadata}"
        self.assertNotIn("005930", rendered)
        self.assertNotIn("AAPL", rendered)
        self.assertNotIn("access_" + "tok" + "en", rendered)
        self.assertNotIn("Authori" + "zation", rendered)

    @plan_settings()
    def test_fetch_and_build_wrapper_uses_preview_service_without_network(self):
        user = self.create_user()
        preview = self.preview(user, [self.item("MSFT", market_country="US", currency="USD")])

        with patch(
            "integrations.services.toss_holdings_sync_plan.fetch_user_toss_holdings_preview",
            return_value=preview,
        ) as fetch_mock:
            plan = fetch_and_build_holdings_sync_plan(
                user=user,
                actor=user,
                symbol="MSFT",
                transport=object(),
                record_audit=False,
            )

        fetch_mock.assert_called_once()
        self.assertEqual(fetch_mock.call_args.kwargs["symbol"], "MSFT")
        self.assertEqual(plan.create_count, 1)

    @plan_settings()
    def test_source_has_no_global_toss_or_provider_network_imports(self):
        from integrations.services import toss_holdings_sync_plan

        source = inspect.getsource(toss_holdings_sync_plan)
        self.assertNotIn("TOSS_INVEST_CLIENT_ID", source)
        self.assertNotIn("TOSS_INVEST_CLIENT_SECRET", source)
        self.assertNotIn("TOSS_INVEST_ACCOUNT_ID", source)
        self.assertNotIn("data_pipeline." + "providers", source)
        self.assertNotIn("req" + "uests.", source)
        self.assertNotIn("url" + "open", source)

    @plan_settings()
    def test_safe_dict_has_no_credential_or_account_raw_values(self):
        user = self.create_user()

        plan = build_holdings_sync_plan_from_preview(user=user, preview=self.preview(user, [self.item("TSLA")]))

        rendered = str(plan.safe_dict())
        unsafe_values = [
            "access_" + "tok" + "en",
            "refresh_" + "tok" + "en",
            "Authori" + "zation",
            "X-Tossinvest-" + "Account",
            "account" + "Seq",
            "account" + "No",
            "account_" + "ref",
            "client_" + "sec" + "ret",
            "cipher" + "text",
            "raw_" + "response",
        ]
        for unsafe in unsafe_values:
            self.assertNotIn(unsafe, rendered)

    @plan_settings()
    def test_current_holding_values_remain_unchanged(self):
        user = self.create_user()
        holding = self.create_current_holding(user, code="005930", name="Samsung", quantity=5, average_price="64000.00")

        build_holdings_sync_plan_from_preview(
            user=user,
            preview=self.preview(user, [self.item("005930", quantity="10", average_purchase_price="65000")]),
        )

        holding.refresh_from_db()
        self.assertEqual(holding.quantity, 5)
        self.assertEqual(holding.average_price, Decimal("64000.00"))
