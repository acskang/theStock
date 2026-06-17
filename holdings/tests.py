from io import StringIO
from decimal import Decimal
from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from data_pipeline.models import DataIngestionLog
from decisions.models import AveragingDecision, AveragingProbabilityRecord, HoldingConsultRecord
from marketdata.models import DailyPrice, InvestorFlow, MarketIndex
from stocks.models import Stock

from .models import UserHolding
from .serializers import UserHoldingSerializer

User = get_user_model()


class UserHoldingModelTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="pw12345")
        self.other_user = User.objects.create_user(username="bob", password="pw12345")
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)

    def test_holding_can_be_created(self):
        holding = UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("75000.00"),
            quantity=10,
            max_additional_budget=Decimal("1000000.00"),
        )

        self.assertEqual(holding.risk_level, UserHolding.RISK_NORMAL)
        self.assertTrue(holding.is_active)

    def test_same_user_cannot_register_same_stock_twice(self):
        UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("75000.00"),
            quantity=10,
        )

        with self.assertRaises(IntegrityError):
            UserHolding.objects.create(
                user=self.user,
                stock=self.stock,
                average_price=Decimal("73000.00"),
                quantity=5,
            )

    def test_different_users_can_register_same_stock(self):
        UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("75000.00"),
            quantity=10,
        )
        other_holding = UserHolding.objects.create(
            user=self.other_user,
            stock=self.stock,
            average_price=Decimal("73000.00"),
            quantity=5,
        )

        self.assertEqual(other_holding.user, self.other_user)

    def test_total_invested_amount_is_exposed(self):
        holding = UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("75000.00"),
            quantity=10,
            max_additional_budget=Decimal("1000000.00"),
        )

        serializer = UserHoldingSerializer(holding)
        self.assertEqual(serializer.data["total_invested_amount"], "750000.00")


class UserHoldingApiTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="alice", password="pw12345")
        self.other_user = User.objects.create_user(username="bob", password="pw12345")
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)
        self.holding = UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("75000.00"),
            quantity=10,
            max_additional_budget=Decimal("1000000.00"),
        )
        UserHolding.objects.create(
            user=self.other_user,
            stock=self.stock,
            average_price=Decimal("73000.00"),
            quantity=5,
        )
        self.client.force_authenticate(self.user)

    def _create_price_series(self, stock, *, start_day, count, base_close, step):
        start = date(2026, 1, start_day)
        rows = []
        for offset in range(count):
            close_price = Decimal(str(base_close + (step * offset)))
            volume = 1000
            if offset == count - 1:
                volume = 3000
            row = DailyPrice.objects.create(
                stock=stock,
                date=start + timedelta(days=offset),
                open_price=close_price - Decimal("1.00"),
                high_price=close_price + Decimal("2.00"),
                low_price=close_price - Decimal("2.00"),
                close_price=close_price,
                volume=volume,
            )
            rows.append(row)
        return rows

    def _create_market_series(self, code, name, *, start_day, count, base_close, step):
        start = date(2026, 1, start_day)
        for offset in range(count):
            MarketIndex.objects.create(
                code=code,
                name=name,
                date=start + timedelta(days=offset),
                close_value=Decimal(str(base_close + (step * offset))),
                change_rate=Decimal("0.5000"),
            )

    def _create_evaluation_inputs(self, stock):
        self._create_price_series(stock, start_day=1, count=120, base_close=100, step=1)
        for index in range(5):
            InvestorFlow.objects.create(
                stock=stock,
                date=date(2026, 5, 1) + timedelta(days=index),
                foreign_net_buy=1000,
                institution_net_buy=1200,
                individual_net_buy=-2200,
                program_net_buy=100,
            )
        self._create_market_series("KOSPI", "KOSPI", start_day=1, count=60, base_close=2400, step=5)
        self._create_market_series("NASDAQ", "NASDAQ", start_day=1, count=60, base_close=15000, step=10)

    def _create_probability_inputs(self, stock):
        self._create_price_series(stock, start_day=1, count=120, base_close=68000, step=50)
        for index in range(5):
            InvestorFlow.objects.create(
                stock=stock,
                date=date(2026, 5, 1) + timedelta(days=index),
                foreign_net_buy=1000,
                institution_net_buy=1200,
                individual_net_buy=-2200,
                program_net_buy=100,
            )
        self._create_market_series("KOSPI", "KOSPI", start_day=1, count=60, base_close=2400, step=5)
        self._create_market_series("NASDAQ", "NASDAQ", start_day=1, count=60, base_close=15000, step=10)

    def test_holdings_api_returns_only_current_user_data(self):
        response = self.client.get("/api/holdings/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["id"], self.holding.id)

    def test_holdings_api_excludes_inactive_by_default_and_can_include_them(self):
        inactive_stock = Stock.objects.create(code="000660", name="SK하이닉스", market=Stock.MARKET_KOSPI)
        inactive_holding = UserHolding.objects.create(
            user=self.user,
            stock=inactive_stock,
            average_price=Decimal("0.00"),
            quantity=0,
            is_active=False,
        )

        response = self.client.get("/api/holdings/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([item["id"] for item in response.data], [self.holding.id])

        response = self.client.get("/api/holdings/?include_inactive=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertCountEqual([item["id"] for item in response.data], [self.holding.id, inactive_holding.id])

    def test_evaluate_endpoint_persists_decision_and_returns_expected_payload(self):
        self._create_evaluation_inputs(self.stock)

        response = self.client.post(f"/api/holdings/{self.holding.id}/evaluate/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(AveragingDecision.objects.filter(holding=self.holding).count(), 1)
        self.assertEqual(response.data["holding_id"], self.holding.id)
        self.assertEqual(response.data["stock_code"], self.stock.code)
        self.assertEqual(response.data["stock_name"], self.stock.name)
        self.assertIn("score", response.data)
        self.assertIn("grade", response.data)
        self.assertIn("decision", response.data)
        self.assertIn("reason_summary", response.data)
        self.assertIn("reasons", response.data)
        self.assertIn("score_breakdown", response.data)
        self.assertIn("suggested_budget", response.data)
        self.assertIn("disclaimer", response.data)

    def test_evaluate_endpoint_returns_404_for_other_users_holding(self):
        self.client.force_authenticate(self.other_user)

        response = self.client.post(f"/api/holdings/{self.holding.id}/evaluate/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(AveragingDecision.objects.count(), 0)

    def test_evaluate_endpoint_saves_data_insufficient_result(self):
        response = self.client.post(f"/api/holdings/{self.holding.id}/evaluate/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(AveragingDecision.objects.filter(holding=self.holding).count(), 1)
        self.assertEqual(response.data["decision"], "데이터 부족으로 평가 불가")
        self.assertEqual(response.data["suggested_budget"], "0.00")
        self.assertTrue(any("최신 가격 데이터" in reason for reason in response.data["reasons"]))

    def test_holding_decision_history_returns_latest_first(self):
        older = AveragingDecision.objects.create(
            holding=self.holding,
            score=40,
            grade="C",
            decision="물타기 금지 구간",
            reason_summary="이전 판단",
        )
        newer = AveragingDecision.objects.create(
            holding=self.holding,
            score=60,
            grade="B",
            decision="관찰 구간",
            reason_summary="최신 판단",
        )
        AveragingDecision.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=1))
        AveragingDecision.objects.filter(pk=newer.pk).update(created_at=timezone.now())

        response = self.client.get(f"/api/holdings/{self.holding.id}/decisions/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]["id"], newer.id)
        self.assertEqual(response.data[0]["holding_id"], self.holding.id)
        self.assertEqual(response.data[0]["stock_code"], self.stock.code)
        self.assertEqual(response.data[0]["stock_name"], self.stock.name)

    def test_holdings_smoke_endpoint(self):
        response = self.client.get(reverse("holding-list"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_request_id_header_is_added_and_request_log_is_emitted(self):
        with self.assertLogs("stock_service.middleware", level="INFO") as logs:
            response = self.client.get(reverse("holding-list"), HTTP_X_REQUEST_ID="req-holdings-1")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["X-Request-ID"], "req-holdings-1")
        self.assertTrue(any("Request completed" in message for message in logs.output))

    def test_evaluate_endpoint_logs_and_returns_500_on_unexpected_error(self):
        with self.assertLogs("holdings.views", level="ERROR") as logs:
            with patch("holdings.views.evaluate_averaging_timing", side_effect=RuntimeError("boom")):
                response = self.client.post(f"/api/holdings/{self.holding.id}/evaluate/")

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertEqual(response.data["detail"], "Internal server error.")
        self.assertEqual(AveragingDecision.objects.count(), 0)
        self.assertTrue(any("Averaging decision evaluation failed" in message for message in logs.output))

    def test_probability_endpoint_returns_expected_payload_and_persists_record(self):
        self._create_probability_inputs(self.stock)

        response = self.client.post(
            f"/api/holdings/{self.holding.id}/probability/",
            data={
                "buy_price": "69000.00",
                "buy_quantity": 5,
                "lookahead_days": 20,
                "target_type": "new_average_price",
                "stop_loss_type": "support_or_atr",
                "same_day_hit_policy": "conservative",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(AveragingProbabilityRecord.objects.count(), 1)
        self.assertIn("success_probability", response.data)
        self.assertIn("failure_probability", response.data)
        self.assertIn("neutral_probability", response.data)
        self.assertIn("confidence", response.data)
        self.assertIn("basis", response.data)
        self.assertIn("warnings", response.data)
        self.assertIn("disclaimer", response.data)
        self.assertIn("scenario", response.data["basis"])
        self.assertIn("components", response.data["basis"])
        record = AveragingProbabilityRecord.objects.get()
        self.assertEqual(record.holding, self.holding)
        self.assertEqual(record.scenario_input["buy_price"], "69000.00")
        self.assertEqual(record.scenario_input["buy_quantity"], 5)
        self.assertEqual(record.response_payload["success_probability"], response.data["success_probability"])

    def test_probability_endpoint_returns_404_for_other_users_holding(self):
        self.client.force_authenticate(self.other_user)

        response = self.client.post(
            f"/api/holdings/{self.holding.id}/probability/",
            data={"buy_price": "69000.00", "buy_quantity": 5},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(AveragingProbabilityRecord.objects.count(), 0)

    def test_probability_history_endpoint_returns_current_user_history(self):
        self._create_probability_inputs(self.stock)
        self.client.post(
            f"/api/holdings/{self.holding.id}/probability/",
            data={"buy_price": "69000.00", "buy_quantity": 5},
            format="json",
        )

        response = self.client.get(f"/api/holdings/{self.holding.id}/probabilities/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["holding_id"], self.holding.id)
        self.assertEqual(response.data[0]["stock_code"], self.stock.code)
        self.assertIn("response_payload", response.data[0])

    def test_probability_endpoint_validates_manual_stop_loss_input(self):
        response = self.client.post(
            f"/api/holdings/{self.holding.id}/probability/",
            data={
                "buy_price": "69000.00",
                "buy_quantity": 5,
                "stop_loss_type": "manual",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("stop_loss_price", response.data)

    def test_probability_endpoint_validates_manual_target_input(self):
        response = self.client.post(
            f"/api/holdings/{self.holding.id}/probability/",
            data={
                "buy_price": "69000.00",
                "buy_quantity": 5,
                "target_type": "manual",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("manual_target_price", response.data)

    def test_probability_endpoint_validates_positive_quantity(self):
        response = self.client.post(
            f"/api/holdings/{self.holding.id}/probability/",
            data={
                "buy_price": "69000.00",
                "buy_quantity": 0,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("buy_quantity", response.data)

    def test_consult_endpoint_returns_expected_payload(self):
        self._create_probability_inputs(self.stock)

        response = self.client.post(
            f"/api/holdings/{self.holding.id}/consult/",
            data={
                "buy_price": "69000.00",
                "lookahead_days": 20,
                "target_profit_rate": "0.0000",
                "stop_loss_type": "support_or_atr",
                "include_scenarios": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("stock", response.data)
        self.assertIn("holding", response.data)
        self.assertIn("final_grade", response.data)
        self.assertIn("consulting_status", response.data)
        self.assertIn("decision_summary", response.data)
        self.assertIn("score_breakdown", response.data)
        self.assertIn("risk_gate", response.data)
        self.assertIn("data_quality", response.data)
        self.assertIn("market_regime", response.data)
        self.assertIn("stock_quality", response.data)
        self.assertIn("base_decision", response.data)
        self.assertIn("capital_plan", response.data)
        self.assertIn("recheck_conditions", response.data)
        self.assertEqual(HoldingConsultRecord.objects.count(), 1)
        self.assertGreaterEqual(len(response.data["scenario_table"]), 1)
        self.assertIn("probability", response.data)
        self.assertEqual(response.data["stock"]["market"], "KOSPI")
        self.assertEqual(response.data["stock"]["code"], self.stock.code)
        self.assertEqual(response.data["holding"]["average_price"], "75000.00")
        self.assertEqual(response.data["holding"]["current_price"], "73950.00")
        self.assertEqual(response.data["holding"]["loss_rate"], "-1.40")
        self.assertEqual(response.data["decision_summary"], response.data["summary"])
        self.assertEqual(response.data["score_breakdown"], response.data["base_decision"]["score_breakdown"])
        self.assertIn("explanation", response.data["probability"])
        self.assertIn("highlights", response.data["probability"])
        self.assertIn("selection_summary", response.data["probability"]["explanation"])
        self.assertIn("headline", response.data["probability"]["highlights"])
        self.assertIn("representative_cases", response.data["probability"]["highlights"])
        self.assertIn("reason_summary", response.data["scenario_table"][0])
        self.assertTrue(response.data["scenario_table"][0]["reason_summary"])
        self.assertIn("probability_explanation", response.data["scenario_table"][0])
        record = HoldingConsultRecord.objects.get()
        self.assertEqual(record.holding, self.holding)
        self.assertEqual(record.final_grade, response.data["final_grade"])
        self.assertEqual(record.response_payload["consulting_status"], response.data["consulting_status"])

    def test_consult_endpoint_returns_404_for_other_users_holding(self):
        self.client.force_authenticate(self.other_user)

        response = self.client.post(f"/api/holdings/{self.holding.id}/consult/", data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_consult_endpoint_honors_include_scenarios_false(self):
        self._create_probability_inputs(self.stock)

        response = self.client.post(
            f"/api/holdings/{self.holding.id}/consult/",
            data={"include_scenarios": False},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["scenario_table"], [])

    def test_consult_history_endpoint_returns_current_user_history(self):
        self._create_probability_inputs(self.stock)
        self.client.post(
            f"/api/holdings/{self.holding.id}/consult/",
            data={},
            format="json",
        )

        response = self.client.get(f"/api/holdings/{self.holding.id}/consults/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["holding_id"], self.holding.id)
        self.assertEqual(response.data[0]["stock_code"], self.stock.code)
        self.assertIn("response_payload", response.data[0])

    def test_consult_endpoint_returns_200_with_warnings_when_data_is_missing(self):
        response = self.client.post(f"/api/holdings/{self.holding.id}/consult/", data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["warnings"])
        self.assertEqual(response.data["final_grade"], "D")

    def test_additional_buy_simulation_endpoint_returns_expected_payload(self):
        DailyPrice.objects.create(
            stock=self.stock,
            date=date(2026, 6, 16),
            open_price=Decimal("16000.00"),
            high_price=Decimal("16470.00"),
            low_price=Decimal("15830.00"),
            close_price=Decimal("16340.00"),
            volume=2613186,
        )
        self.holding.average_price = Decimal("15116.50")
        self.holding.quantity = 2
        self.holding.save(update_fields=["average_price", "quantity"])
        counts_before = {
            "holdings": UserHolding.objects.count(),
            "daily_prices": DailyPrice.objects.count(),
            "logs": DataIngestionLog.objects.count(),
        }

        response = self.client.post(
            f"/api/holdings/{self.holding.id}/additional-buy-simulation/",
            data={"additional_budget": "100000.00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["simulation_only"])
        self.assertFalse(response.data["order_execution"])
        self.assertEqual(response.data["stock"]["code"], self.stock.code)
        self.assertEqual(response.data["price_source"]["type"], "daily_price")
        self.assertEqual(response.data["price_source"]["simulation_buy_price"], "16340.00")
        self.assertEqual(response.data["current_position"]["invested_amount"], "30233.00")
        self.assertEqual(response.data["current_position"]["market_value"], "32680.00")
        self.assertEqual(response.data["current_position"]["profit_loss_rate"], "8.09")
        self.assertEqual(response.data["simulation"]["additional_quantity"], 6)
        self.assertEqual(response.data["simulation"]["new_average_price"], "16034.13")
        self.assertEqual(response.data["simulation"]["break_even_price"], "16034.13")
        self.assertIsNone(response.data["target_projection"])
        warnings_text = " ".join(response.data["warnings"])
        self.assertIn("calculation-only simulation", warnings_text)
        self.assertIn("does not place orders", warnings_text)
        self.assertIn("not investment advice", warnings_text)
        self.assertIn("does not guarantee returns", warnings_text)
        self.assertIn("Fees and taxes are not included", warnings_text)
        rendered = str(response.data)
        self.assertNotIn("order_id", rendered)
        self.assertNotIn("orderNo", rendered)
        self.assertEqual(UserHolding.objects.count(), counts_before["holdings"])
        self.assertEqual(DailyPrice.objects.count(), counts_before["daily_prices"])
        self.assertEqual(DataIngestionLog.objects.count(), counts_before["logs"])

    def test_additional_buy_simulation_endpoint_requires_authentication(self):
        self.client.force_authenticate(user=None)

        response = self.client.post(
            f"/api/holdings/{self.holding.id}/additional-buy-simulation/",
            data={"additional_budget": "100000.00"},
            format="json",
        )

        self.assertIn(response.status_code, (status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN))

    def test_additional_buy_simulation_endpoint_returns_404_for_other_users_holding(self):
        self.client.force_authenticate(self.other_user)

        response = self.client.post(
            f"/api/holdings/{self.holding.id}/additional-buy-simulation/",
            data={"additional_budget": "100000.00", "buy_price": "16000.00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_additional_buy_simulation_endpoint_rejects_inactive_holding(self):
        inactive_stock = Stock.objects.create(code="051910", name="LG화학", market=Stock.MARKET_KOSPI)
        inactive_holding = UserHolding.objects.create(
            user=self.user,
            stock=inactive_stock,
            average_price=Decimal("700000.00"),
            quantity=1,
            is_active=False,
        )

        response = self.client.post(
            f"/api/holdings/{inactive_holding.id}/additional-buy-simulation/",
            data={"additional_budget": "100000.00", "buy_price": "600000.00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "inactive_holding")

    def test_additional_buy_simulation_endpoint_uses_manual_buy_price_and_target_price(self):
        DailyPrice.objects.create(
            stock=self.stock,
            date=date(2026, 6, 16),
            open_price=Decimal("16000.00"),
            high_price=Decimal("16470.00"),
            low_price=Decimal("15830.00"),
            close_price=Decimal("16340.00"),
            volume=2613186,
        )
        self.holding.average_price = Decimal("15116.50")
        self.holding.quantity = 2
        self.holding.save(update_fields=["average_price", "quantity"])

        response = self.client.post(
            f"/api/holdings/{self.holding.id}/additional-buy-simulation/",
            data={
                "additional_budget": "100000.00",
                "buy_price": "16000.00",
                "target_price": "18000.00",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["price_source"]["type"], "manual_buy_price")
        self.assertEqual(response.data["price_source"]["simulation_buy_price"], "16000.00")
        self.assertEqual(response.data["input"]["target_price"], "18000.00")
        self.assertEqual(response.data["simulation"]["additional_quantity"], 6)
        self.assertEqual(response.data["simulation"]["new_average_price"], "15779.13")
        self.assertEqual(response.data["target_projection"]["target_market_value"], "144000.00")

    def test_additional_buy_simulation_endpoint_returns_safe_validation_errors(self):
        cases = [
            ({"additional_budget": "0"}, "invalid_additional_budget"),
            ({"additional_budget": "100000.00", "buy_price": "0"}, "invalid_buy_price"),
            ({"additional_budget": "100000.00", "target_price": "0"}, "invalid_target_price"),
            ({"additional_budget": "100000.00", "additional_quantity": "1"}, "conflicting_input"),
            ({"additional_quantity": "1"}, "additional_quantity_not_supported"),
        ]

        for payload, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                response = self.client.post(
                    f"/api/holdings/{self.holding.id}/additional-buy-simulation/",
                    data=payload,
                    format="json",
                )
                self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
                self.assertEqual(response.data["error"], expected_error)

    def test_additional_buy_simulation_endpoint_returns_service_errors(self):
        response = self.client.post(
            f"/api/holdings/{self.holding.id}/additional-buy-simulation/",
            data={"additional_budget": "100000.00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "latest_price_required")

        response = self.client.post(
            f"/api/holdings/{self.holding.id}/additional-buy-simulation/",
            data={"additional_budget": "100.00", "buy_price": "16000.00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data["error"], "additional_quantity_too_small")

    def test_additional_buy_simulation_endpoint_response_excludes_sensitive_keys(self):
        response = self.client.post(
            f"/api/holdings/{self.holding.id}/additional-buy-simulation/",
            data={"additional_budget": "100000.00", "buy_price": "16000.00"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        rendered = str(response.data)
        for forbidden in [
            "username",
            "email",
            "user_id",
            "accountNo",
            "accountSeq",
            "X-Tossinvest-Account",
            "access_token",
            "Authorization",
            "raw_response",
            "order_id",
        ]:
            self.assertNotIn(forbidden, rendered)

    def test_consult_endpoint_returns_fallback_probability_when_scenario_comparison_fails(self):
        self._create_probability_inputs(self.stock)

        with patch("decisions.services.consulting_service.compare_scenarios", side_effect=RuntimeError("boom")):
            response = self.client.post(f"/api/holdings/{self.holding.id}/consult/", data={}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("probability", response.data)
        self.assertEqual(response.data["probability"]["scenario_type"], "fallback")
        self.assertIn("highlights", response.data["probability"])
        self.assertTrue(response.data["probability"]["highlights"]["headline"])
        self.assertGreaterEqual(len(response.data["scenario_table"]), 1)
        self.assertEqual(response.data["scenario_table"][0]["scenario_type"], "conservative")
        self.assertIn("reason_summary", response.data["scenario_table"][0])
        self.assertTrue(response.data["scenario_table"][0]["reason_summary"])

    def test_inactive_holding_endpoints_return_400(self):
        inactive_stock = Stock.objects.create(code="051910", name="LG화학", market=Stock.MARKET_KOSPI)
        inactive_holding = UserHolding.objects.create(
            user=self.user,
            stock=inactive_stock,
            average_price=Decimal("0.00"),
            quantity=0,
            is_active=False,
        )

        for path in (
            f"/api/holdings/{inactive_holding.id}/evaluate/",
            f"/api/holdings/{inactive_holding.id}/probability/",
            f"/api/holdings/{inactive_holding.id}/consult/",
        ):
            response = self.client.post(path, data={}, format="json")
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertEqual(response.data["detail"], "Inactive holding cannot be evaluated.")

    def test_api_schema_endpoint_returns_openapi_paths_for_authenticated_user(self):
        response = self.client.get(
            "/api/schema/",
            HTTP_ACCEPT="application/vnd.oai.openapi+json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("paths", response.data)
        self.assertIn("/api/holdings/", response.data["paths"])
        self.assertIn("/api/holdings/{id}/consult/", response.data["paths"])
        consult_post = response.data["paths"]["/api/holdings/{id}/consult/"]["post"]
        self.assertIn("requestBody", consult_post)
        self.assertIn("responses", consult_post)
        consult_response_schema = consult_post["responses"]["200"]["content"]["application/json"]["schema"]
        self.assertEqual(consult_response_schema["$ref"], "#/components/schemas/HoldingConsultResponse")
        consult_component = response.data["components"]["schemas"]["HoldingConsultResponse"]
        self.assertIn("final_grade", consult_component["properties"])
        self.assertIn("consulting_status", consult_component["properties"])
        self.assertIn("holding", consult_component["properties"])
        self.assertIn("decision_summary", consult_component["properties"])
        self.assertIn("score_breakdown", consult_component["properties"])
        self.assertIn("probability", consult_component["properties"])
        self.assertIn("scenario_table", consult_component["properties"])

    def test_api_docs_page_renders_schema_summary_for_authenticated_user(self):
        response = self.client.get("/api/docs/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertContains(response, "Stock Workbench API")
        self.assertContains(response, "/api/holdings/{id}/consult/")
        self.assertContains(response, "Raw OpenAPI Schema")


class UserHoldingReleaseTests(APITestCase):
    def test_seed_averaging_demo_command_creates_sample_records(self):
        output = StringIO()

        call_command("seed_averaging_demo", username="release_demo", password="demo12345!", stdout=output)

        demo_user = User.objects.get(username="release_demo")
        self.assertTrue(Stock.objects.filter(code="005930").exists())
        self.assertTrue(UserHolding.objects.filter(user=demo_user).exists())
        self.assertGreater(DailyPrice.objects.count(), 0)
        self.assertGreater(InvestorFlow.objects.count(), 0)
        self.assertGreater(MarketIndex.objects.count(), 0)
        self.assertIn("샘플 데이터 생성 완료", output.getvalue())
