from decimal import Decimal

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from integrations.models import IntegrationAuditLog
from integrations.services.toss_holdings_apply import (
    HoldingApplyPermissionError,
    HoldingApplyPreflightError,
    HoldingApplyStalePlanError,
    apply_holdings_sync_plan,
    compute_plan_digest,
    create_apply_confirmation_token,
    load_apply_confirmation_token,
)
from integrations.services.toss_holdings_sync_plan import (
    ACTION_CREATE,
    ACTION_REMOVE_CANDIDATE,
    ACTION_UNCHANGED,
    ACTION_UPDATE,
    HoldingSnapshotValue,
    HoldingSyncDryRunPlan,
    HoldingSyncPlanItem,
)


def apply_settings(**kwargs):
    settings = {
        "TOSS_USER_HOLDINGS_APPLY_ENABLED": True,
        "TOSS_HOLDINGS_APPLY_CONFIRM_TTL_SECONDS": 600,
        "CREDENTIAL_HASH_PEPPER": "dummy-pepper-for-tests",
    }
    settings.update(kwargs)
    return override_settings(**settings)


class TossHoldingsApplyServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="user-alpha", password="dummy-password")
        self.other = get_user_model().objects.create_user(username="user-beta", password="dummy-password")
        self.Stock = apps.get_model("stocks", "Stock")
        self.UserHolding = apps.get_model("holdings", "UserHolding")

    def stock(self, code: str, name: str = "Test Stock"):
        return self.Stock.objects.create(code=code, name=name, market="KOSPI")

    def current_holding(self, *, code="005930", quantity=10, average_price="70000.00"):
        stock = self.stock(code)
        return self.UserHolding.objects.create(
            user=self.user,
            stock=stock,
            quantity=quantity,
            average_price=Decimal(average_price),
        )

    def plan(self, items, *, current_count=0, target_count=0, symbol_filter=None):
        return HoldingSyncDryRunPlan(
            user_id=self.user.pk,
            provider="toss_invest",
            source="toss_holdings_preview",
            generated_at=timezone.now(),
            symbol_filter=symbol_filter,
            current_count=current_count,
            target_count=target_count,
            create_count=sum(1 for item in items if item.action == ACTION_CREATE),
            update_count=sum(1 for item in items if item.action == ACTION_UPDATE),
            unchanged_count=sum(1 for item in items if item.action == ACTION_UNCHANGED),
            remove_candidate_count=sum(1 for item in items if item.action == ACTION_REMOVE_CANDIDATE),
            skipped_count=0,
            items=items,
        )

    def create_item(self, symbol="AAPL", quantity="2", average_price="180"):
        target = HoldingSnapshotValue(
            symbol=symbol,
            comparison_key=symbol.upper(),
            name="Apple",
            quantity=Decimal(quantity),
            average_purchase_price=Decimal(average_price),
            source="toss",
        )
        return HoldingSyncPlanItem(action=ACTION_CREATE, symbol=symbol, comparison_key=symbol.upper(), target=target)

    def update_item(self, holding, quantity="12", average_price="71000"):
        current = HoldingSnapshotValue(
            symbol=holding.stock.code,
            comparison_key=holding.stock.code.upper(),
            name=holding.stock.name,
            quantity=Decimal(holding.quantity),
            average_purchase_price=holding.average_price,
            source="current",
            object_id=holding.pk,
        )
        target = HoldingSnapshotValue(
            symbol=holding.stock.code,
            comparison_key=holding.stock.code.upper(),
            name=holding.stock.name,
            quantity=Decimal(quantity),
            average_purchase_price=Decimal(average_price),
            source="toss",
        )
        return HoldingSyncPlanItem(
            action=ACTION_UPDATE,
            symbol=holding.stock.code,
            comparison_key=holding.stock.code.upper(),
            current=current,
            target=target,
        )

    @apply_settings()
    def test_confirmation_token_round_trip_and_other_user_rejected(self):
        plan = self.plan([self.create_item()], target_count=1)
        token = create_apply_confirmation_token(user=self.user, plan=plan)

        payload = load_apply_confirmation_token(token=token, user=self.user)

        self.assertEqual(payload["user_id"], self.user.pk)
        self.assertEqual(payload["plan_digest"], compute_plan_digest(plan))
        with self.assertRaises(HoldingApplyPermissionError):
            load_apply_confirmation_token(token=token, user=self.other)

    @apply_settings()
    def test_invalid_token_rejected(self):
        with self.assertRaises(Exception):
            load_apply_confirmation_token(token="not-a-valid-token", user=self.user)

    @apply_settings()
    def test_stale_plan_rejected_without_db_write(self):
        self.stock("AAPL")
        plan = self.plan([self.create_item(quantity="2")], target_count=1)
        payload = load_apply_confirmation_token(
            token=create_apply_confirmation_token(user=self.user, plan=plan),
            user=self.user,
        )
        stale = self.plan([self.create_item(quantity="3")], target_count=1)

        with self.assertRaises(HoldingApplyStalePlanError):
            apply_holdings_sync_plan(user=self.user, actor=self.user, plan=stale, confirmation_payload=payload)

        self.assertFalse(self.UserHolding.objects.filter(user=self.user, stock__code="AAPL").exists())

    @apply_settings()
    def test_create_success(self):
        self.stock("AAPL")
        plan = self.plan([self.create_item()], target_count=1)
        payload = load_apply_confirmation_token(
            token=create_apply_confirmation_token(user=self.user, plan=plan),
            user=self.user,
        )

        result = apply_holdings_sync_plan(user=self.user, actor=self.user, plan=plan, confirmation_payload=payload)
        holding = self.UserHolding.objects.get(user=self.user, stock__code="AAPL")

        self.assertEqual(result.created_count, 1)
        self.assertEqual(holding.quantity, 2)
        self.assertEqual(holding.average_price, Decimal("180"))

    @apply_settings()
    def test_update_success(self):
        holding = self.current_holding()
        plan = self.plan([self.update_item(holding)], current_count=1, target_count=1)
        payload = load_apply_confirmation_token(
            token=create_apply_confirmation_token(user=self.user, plan=plan),
            user=self.user,
        )

        result = apply_holdings_sync_plan(user=self.user, actor=self.user, plan=plan, confirmation_payload=payload)
        holding.refresh_from_db()

        self.assertEqual(result.updated_count, 1)
        self.assertEqual(holding.quantity, 12)
        self.assertEqual(holding.average_price, Decimal("71000"))

    @apply_settings()
    def test_remove_candidate_is_not_deleted(self):
        holding = self.current_holding()
        current = HoldingSnapshotValue(
            symbol=holding.stock.code,
            comparison_key=holding.stock.code.upper(),
            quantity=Decimal(holding.quantity),
            average_purchase_price=holding.average_price,
            source="current",
            object_id=holding.pk,
        )
        plan = self.plan(
            [
                HoldingSyncPlanItem(
                    action=ACTION_REMOVE_CANDIDATE,
                    symbol=holding.stock.code,
                    comparison_key=holding.stock.code.upper(),
                    current=current,
                )
            ],
            current_count=1,
        )
        payload = load_apply_confirmation_token(
            token=create_apply_confirmation_token(user=self.user, plan=plan),
            user=self.user,
        )

        result = apply_holdings_sync_plan(user=self.user, actor=self.user, plan=plan, confirmation_payload=payload)

        self.assertEqual(result.ignored_remove_candidate_count, 1)
        self.assertTrue(self.UserHolding.objects.filter(pk=holding.pk).exists())

    @apply_settings()
    def test_missing_stock_master_aborts_entire_apply(self):
        holding = self.current_holding()
        plan = self.plan([self.update_item(holding), self.create_item("MSFT")], current_count=1, target_count=2)
        payload = load_apply_confirmation_token(
            token=create_apply_confirmation_token(user=self.user, plan=plan),
            user=self.user,
        )

        with self.assertRaises(HoldingApplyPreflightError):
            apply_holdings_sync_plan(user=self.user, actor=self.user, plan=plan, confirmation_payload=payload)

        holding.refresh_from_db()
        self.assertEqual(holding.quantity, 10)
        self.assertFalse(self.UserHolding.objects.filter(user=self.user, stock__code="MSFT").exists())

    @apply_settings()
    def test_audit_counts_only_and_safe_dict_has_no_sensitive_values(self):
        self.stock("AAPL")
        plan = self.plan([self.create_item()], target_count=1)
        payload = load_apply_confirmation_token(
            token=create_apply_confirmation_token(user=self.user, plan=plan),
            user=self.user,
        )

        result = apply_holdings_sync_plan(user=self.user, actor=self.user, plan=plan, confirmation_payload=payload)
        audit = IntegrationAuditLog.objects.filter(action=IntegrationAuditLog.ACTION_HOLDINGS_SYNC).latest("id")
        rendered = str(result.safe_dict()) + str(audit.safe_metadata)

        self.assertEqual(audit.reason_code, "apply_create_update")
        self.assertEqual(audit.safe_metadata["created_count"], 1)
        for unsafe in ["access_token", "client_secret", "accountSeq", "accountNo", "Authorization", "ciphertext"]:
            self.assertNotIn(unsafe, rendered)
