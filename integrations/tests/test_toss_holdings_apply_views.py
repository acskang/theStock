from decimal import Decimal
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from integrations.services.toss_holdings_apply import create_apply_confirmation_token
from integrations.services.toss_holdings_sync_plan import (
    ACTION_CREATE,
    ACTION_UPDATE,
    HoldingSnapshotValue,
    HoldingSyncDryRunPlan,
    HoldingSyncPlanItem,
)


def view_settings(*, apply_enabled=True, api_enabled=True, ui_enabled=True):
    return override_settings(
        TOSS_USER_CREDENTIAL_UI_ENABLED=ui_enabled,
        TOSS_USER_TOSS_API_CALLS_ENABLED=api_enabled,
        TOSS_USER_HOLDINGS_APPLY_ENABLED=apply_enabled,
        TOSS_HOLDINGS_APPLY_CONFIRM_TTL_SECONDS=600,
        CREDENTIAL_HASH_PEPPER="dummy-pepper-for-tests",
    )


class TossHoldingsApplyViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="user-alpha", password="dummy-password")
        self.Stock = apps.get_model("stocks", "Stock")
        self.UserHolding = apps.get_model("holdings", "UserHolding")
        self.apply_url = reverse("integrations:toss_holdings_apply")

    def login(self):
        self.client.login(username="user-alpha", password="dummy-password")

    def stock(self, code: str, name: str = "Test Stock"):
        return self.Stock.objects.create(code=code, name=name, market="KOSPI")

    def current_holding(self):
        stock = self.stock("005930", "Samsung")
        return self.UserHolding.objects.create(
            user=self.user,
            stock=stock,
            quantity=10,
            average_price=Decimal("70000.00"),
        )

    def create_plan(self):
        target = HoldingSnapshotValue(
            symbol="AAPL",
            comparison_key="AAPL",
            name="Apple",
            quantity=Decimal("2"),
            average_purchase_price=Decimal("180"),
            source="toss",
        )
        return HoldingSyncDryRunPlan(
            user_id=self.user.pk,
            provider="toss_invest",
            source="toss_holdings_preview",
            generated_at=timezone.now(),
            symbol_filter=None,
            current_count=0,
            target_count=1,
            create_count=1,
            update_count=0,
            unchanged_count=0,
            remove_candidate_count=0,
            skipped_count=0,
            items=[HoldingSyncPlanItem(action=ACTION_CREATE, symbol="AAPL", comparison_key="AAPL", target=target)],
        )

    def update_plan(self, holding, *, quantity="12"):
        current = HoldingSnapshotValue(
            symbol="005930",
            comparison_key="005930",
            name="Samsung",
            quantity=Decimal(holding.quantity),
            average_purchase_price=holding.average_price,
            source="current",
            object_id=holding.pk,
        )
        target = HoldingSnapshotValue(
            symbol="005930",
            comparison_key="005930",
            name="Samsung",
            quantity=Decimal(quantity),
            average_purchase_price=Decimal("71000"),
            source="toss",
        )
        return HoldingSyncDryRunPlan(
            user_id=self.user.pk,
            provider="toss_invest",
            source="toss_holdings_preview",
            generated_at=timezone.now(),
            symbol_filter=None,
            current_count=1,
            target_count=1,
            create_count=0,
            update_count=1,
            unchanged_count=0,
            remove_candidate_count=0,
            skipped_count=0,
            items=[
                HoldingSyncPlanItem(
                    action=ACTION_UPDATE,
                    symbol="005930",
                    comparison_key="005930",
                    current=current,
                    target=target,
                )
            ],
        )

    def post_payload(self, plan, *, password="dummy-password", confirmation_text="반영", confirm="on"):
        return {
            "confirmation_token": create_apply_confirmation_token(user=self.user, plan=plan),
            "password": password,
            "confirmation_text": confirmation_text,
            "confirm": confirm,
        }

    @view_settings(apply_enabled=False)
    def test_apply_feature_flag_false_blocks(self):
        self.login()
        plan = self.create_plan()

        with patch("integrations.views.fetch_and_build_holdings_sync_plan") as fetch_mock:
            response = self.client.post(self.apply_url, self.post_payload(plan))

        self.assertEqual(response.status_code, 403)
        fetch_mock.assert_not_called()
        self.assertContains(response, "활성화되지 않았습니다", status_code=403)

    @view_settings()
    def test_wrong_password_does_not_write(self):
        self.login()
        self.stock("AAPL")
        plan = self.create_plan()

        with patch("integrations.views.fetch_and_build_holdings_sync_plan") as fetch_mock:
            response = self.client.post(self.apply_url, self.post_payload(plan, password="wrong-password"))

        self.assertEqual(response.status_code, 400)
        fetch_mock.assert_not_called()
        self.assertFalse(self.UserHolding.objects.filter(user=self.user, stock__code="AAPL").exists())
        self.assertContains(response, "비밀번호가 올바르지 않습니다", status_code=400)

    @view_settings()
    def test_confirmation_inputs_required(self):
        self.login()
        plan = self.create_plan()

        with patch("integrations.views.fetch_and_build_holdings_sync_plan") as fetch_mock:
            response = self.client.post(
                self.apply_url,
                self.post_payload(plan, confirmation_text="no", confirm=""),
            )

        self.assertEqual(response.status_code, 400)
        fetch_mock.assert_not_called()
        self.assertContains(response, "반영 확인 입력값을 확인해 주세요", status_code=400)

    @view_settings()
    def test_success_apply_screen(self):
        self.login()
        self.stock("AAPL")
        plan = self.create_plan()

        with patch("integrations.views.fetch_and_build_holdings_sync_plan", return_value=plan) as fetch_mock:
            response = self.client.post(self.apply_url, self.post_payload(plan))

        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        fetch_mock.assert_called_once()
        self.assertTrue(self.UserHolding.objects.filter(user=self.user, stock__code="AAPL").exists())
        self.assertIn("UserHolding create/update 반영이 완료되었습니다", body)
        self.assertIn("created", body)
        self.assertIn("AAPL", body)
        self.assertIn("no-store", response["Cache-Control"])
        for unsafe in ["dummy-access-token-alpha", "dummy-secret-alpha", "dummy-account-ref-alpha", "accountSeq", "accountNo", "ciphertext"]:
            self.assertNotIn(unsafe, body)

    @view_settings()
    def test_stale_plan_safe_error_without_write(self):
        self.login()
        holding = self.current_holding()
        confirmed_plan = self.update_plan(holding, quantity="12")
        stale_plan = self.update_plan(holding, quantity="13")

        with patch("integrations.views.fetch_and_build_holdings_sync_plan", return_value=stale_plan):
            response = self.client.post(self.apply_url, self.post_payload(confirmed_plan))

        holding.refresh_from_db()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(holding.quantity, 10)
        self.assertContains(response, "dry-run을 다시 실행", status_code=400)

    @view_settings()
    def test_htmx_apply_no_store(self):
        self.login()
        self.stock("AAPL")
        plan = self.create_plan()

        with patch("integrations.views.fetch_and_build_holdings_sync_plan", return_value=plan):
            response = self.client.post(
                self.apply_url,
                self.post_payload(plan),
                HTTP_HX_REQUEST="true",
            )

        body = response.content.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("toss-holdings-dry-run-panel", body)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertNotIn("accountSeq", body)
        self.assertNotIn("client_secret", body)
