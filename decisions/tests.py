from decimal import Decimal
from datetime import date, timedelta
from io import StringIO
import os
import tempfile
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase
from django.test.utils import override_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from data_pipeline.models import DataIngestionLog
from holdings.models import UserHolding
from marketdata.models import DailyPrice, InvestorFlow, MarketIndex, StockDataCollectionStatus
from marketdata.services.market_regime_service import MarketRegimeResult
from stocks.models import FinancialSnapshot, Stock

from .models import (
    AveragingDecision,
    AveragingProbabilityRecord,
    DISCLAIMER_TEXT,
    HoldingConsultRecord,
    RiskEvent,
)
from .services.additional_buy_simulation_service import (
    AdditionalBuySimulationError,
    build_additional_buy_simulation,
)
from .services.averaging_decision_service import EvaluationResult, evaluate_averaging_timing
from .services.capital_allocation_service import build_capital_plan
from .services.collectors.risk_event_collector import collect_risk_events
from .services.consulting_service import cap_grade, consult_holding
from .services.data_quality_service import DataQualityResult, evaluate_data_quality, get_data_quality_grade_cap
from .services.investor_flow_service import calculate_investor_flow_score
from .services.importers.risk_event_import_service import build_risk_event_source_key
from .services.probability_components import (
    calculate_score_component,
    calculate_volatility_component,
)
from .services.probability_dataclasses import AveragingScenario, ProbabilityFeatureSnapshot, ProbabilityResult
from .services.probability_historical import (
    build_probability_feature_snapshot,
    calculate_snapshot_distance,
    calculate_historical_probabilities,
    determine_historical_outcome,
)
from .services.probability_service import (
    calculate_averaging_success_failure_probability,
    calculate_new_average_price,
    calculate_probability_stop_loss_price,
    calculate_target_price,
)
from .services.risk_gate_service import RiskGateResult, evaluate_risk_gate
from .services.risk_event_service import calculate_risk_score, has_critical_risk
from .services.scenario_comparison_service import ScenarioComparisonItem, build_default_scenarios, compare_scenarios
from .services.scoring_service import convert_score_to_grade
from .services.support_service import calculate_support_score
from .services.volume_service import calculate_volume_score

User = get_user_model()


class DecisionModelTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="pw12345")
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)
        self.holding = UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("75000.00"),
            quantity=10,
        )

    def test_critical_risk_event_can_be_created(self):
        event = RiskEvent.objects.create(
            stock=self.stock,
            event_type="trading_halt",
            title="거래정지",
            event_date="2026-04-28",
            risk_level=RiskEvent.RISK_CRITICAL,
        )

        self.assertTrue(event.is_active)

    def test_risk_event_can_be_deactivated(self):
        event = RiskEvent.objects.create(
            stock=self.stock,
            event_type="other",
            title="테스트",
            event_date="2026-04-28",
            risk_level=RiskEvent.RISK_LOW,
            is_active=False,
        )

        self.assertFalse(event.is_active)

    def test_risk_event_source_key_must_be_unique_when_present(self):
        RiskEvent.objects.create(
            stock=self.stock,
            event_type="other",
            title="테스트1",
            event_date="2026-04-28",
            risk_level=RiskEvent.RISK_LOW,
            source_key="005930:2026-04-28:other:test",
        )

        with self.assertRaises(IntegrityError):
            RiskEvent.objects.create(
                stock=self.stock,
                event_type="other",
                title="테스트2",
                event_date="2026-04-29",
                risk_level=RiskEvent.RISK_LOW,
                source_key="005930:2026-04-28:other:test",
            )

    def test_risk_event_blank_source_key_can_repeat(self):
        RiskEvent.objects.create(
            stock=self.stock,
            event_type="other",
            title="테스트1",
            event_date="2026-04-28",
            risk_level=RiskEvent.RISK_LOW,
        )
        RiskEvent.objects.create(
            stock=self.stock,
            event_type="other",
            title="테스트2",
            event_date="2026-04-29",
            risk_level=RiskEvent.RISK_LOW,
        )

        self.assertEqual(RiskEvent.objects.count(), 2)

    def test_averaging_decision_includes_default_disclaimer(self):
        decision = AveragingDecision.objects.create(
            holding=self.holding,
            score=55,
            grade=AveragingDecision.GRADE_B,
            decision="관찰 구간",
            reason_summary="테스트",
        )

        self.assertEqual(decision.disclaimer, DISCLAIMER_TEXT)

    def test_averaging_decision_grade_choices_are_validated(self):
        decision = AveragingDecision(
            holding=self.holding,
            score=55,
            grade="Z",
            decision="관찰 구간",
            reason_summary="테스트",
        )

        with self.assertRaises(ValidationError):
            decision.full_clean()


class RiskEventImportTests(APITestCase):
    def setUp(self):
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)

    def _write_csv(self, content):
        temp_file = tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".csv", delete=False)
        temp_file.write(content)
        temp_file.close()
        self.addCleanup(lambda: os.path.exists(temp_file.name) and os.unlink(temp_file.name))
        return temp_file.name

    def test_import_risk_events_command_generates_source_key_and_updates_existing_event(self):
        file_path = self._write_csv(
            "stock_code,event_date,event_type,risk_level,title,description,source,url,is_active\n"
            "005930,2026-04-28,operating_loss,medium,영업손실 발생,1분기 영업손실,manual,,true\n"
        )
        output = StringIO()

        call_command("import_risk_events", "--file", file_path, stdout=output)

        event = RiskEvent.objects.get(stock=self.stock)
        expected_source_key = build_risk_event_source_key(
            stock_code="005930",
            event_date=date(2026, 4, 28),
            event_type="operating_loss",
            title="영업손실 발생",
        )
        self.assertEqual(event.source_key, expected_source_key)
        self.assertEqual(event.risk_level, RiskEvent.RISK_MEDIUM)
        self.assertTrue(event.is_active)

        update_file = self._write_csv(
            "stock_code,event_date,event_type,risk_level,title,description,source,url,is_active\n"
            "005930,2026-04-28,operating_loss,high,영업손실 발생,영업손실 확대,manual,,false\n"
        )
        output = StringIO()

        call_command("import_risk_events", "--file", update_file, stdout=output)

        event.refresh_from_db()
        self.assertEqual(RiskEvent.objects.count(), 1)
        self.assertEqual(event.risk_level, RiskEvent.RISK_HIGH)
        self.assertFalse(event.is_active)

    def test_import_risk_events_command_supports_skip_missing_stocks(self):
        file_path = self._write_csv(
            "stock_code,event_date,event_type,risk_level,title\n"
            "999999,2026-04-28,other,low,테스트 이벤트\n"
        )
        output = StringIO()

        call_command("import_risk_events", "--file", file_path, "--skip-missing-stocks", stdout=output)

        self.assertEqual(RiskEvent.objects.count(), 0)
        rendered = output.getvalue()
        self.assertIn("skipped=1", rendered)
        self.assertIn("999999", rendered)


class RiskEventCollectorTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="risk_collector", password="pw12345")
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)
        UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("70000.00"),
            quantity=10,
        )

    @override_settings(OPENDART_API_KEY="dart-key")
    @patch("decisions.services.collectors.risk_event_collector.fetch_dart_disclosures")
    @patch("decisions.services.collectors.risk_event_collector.get_dart_corp_code_map")
    def test_collect_risk_events_creates_events_and_records_success_status(
        self,
        mock_get_dart_corp_code_map,
        mock_fetch_dart_disclosures,
    ):
        mock_get_dart_corp_code_map.return_value = {"005930": "00126380"}
        mock_fetch_dart_disclosures.return_value = [
            {
                "report_nm": "관리종목 지정",
                "rcept_no": "20260429000001",
                "rcept_dt": timezone.localdate().strftime("%Y%m%d"),
                "flr_nm": "한국거래소",
                "rm": "K",
            },
            {
                "report_nm": "정기주주총회 결과",
                "rcept_no": "20260429000002",
                "rcept_dt": timezone.localdate().strftime("%Y%m%d"),
                "flr_nm": "테스트",
                "rm": "",
            },
        ]

        report = collect_risk_events(days=30)

        self.assertEqual(report.target_count, 1)
        self.assertEqual(report.created_rows, 1)
        event = RiskEvent.objects.get(stock=self.stock)
        self.assertEqual(event.event_type, "managed_stock")
        self.assertEqual(event.risk_level, RiskEvent.RISK_HIGH)
        self.assertEqual(event.source_key, "opendart:20260429000001")
        status_obj = StockDataCollectionStatus.objects.get(
            stock=self.stock,
            data_type=StockDataCollectionStatus.TYPE_RISK_EVENT,
        )
        self.assertEqual(status_obj.status, StockDataCollectionStatus.STATUS_SUCCESS)
        self.assertEqual(status_obj.last_row_count, 1)

    @override_settings(OPENDART_API_KEY="dart-key")
    @patch("decisions.services.collectors.risk_event_collector.fetch_dart_disclosures")
    @patch("decisions.services.collectors.risk_event_collector.get_dart_corp_code_map")
    def test_collect_risk_events_marks_empty_status_when_no_matching_disclosures(
        self,
        mock_get_dart_corp_code_map,
        mock_fetch_dart_disclosures,
    ):
        mock_get_dart_corp_code_map.return_value = {"005930": "00126380"}
        mock_fetch_dart_disclosures.return_value = [
            {
                "report_nm": "정기주주총회 결과",
                "rcept_no": "20260429000002",
                "rcept_dt": timezone.localdate().strftime("%Y%m%d"),
                "flr_nm": "테스트",
                "rm": "",
            }
        ]

        report = collect_risk_events(days=30)

        self.assertEqual(report.empty_targets, 1)
        status_obj = StockDataCollectionStatus.objects.get(
            stock=self.stock,
            data_type=StockDataCollectionStatus.TYPE_RISK_EVENT,
        )
        self.assertEqual(status_obj.status, StockDataCollectionStatus.STATUS_EMPTY)
        self.assertEqual(RiskEvent.objects.count(), 0)

    def test_collect_risk_events_marks_error_when_api_key_is_missing(self):
        report = collect_risk_events(days=30)

        self.assertEqual(report.error_targets, 1)
        status_obj = StockDataCollectionStatus.objects.get(
            stock=self.stock,
            data_type=StockDataCollectionStatus.TYPE_RISK_EVENT,
        )
        self.assertEqual(status_obj.status, StockDataCollectionStatus.STATUS_ERROR)

    @patch("decisions.management.commands.collect_risk_events.ingest_risk_events")
    def test_collect_risk_events_command_can_delegate_to_data_pipeline(self, mock_ingest_risk_events):
        from data_pipeline.dataclasses import IngestionReport

        mock_ingest_risk_events.return_value = IngestionReport(
            job_name="ingest_risk_events",
            provider="mock",
            target_type="risk",
            target_count=1,
            success_count=1,
            failed_count=0,
            created_count=1,
            updated_count=0,
            status="success",
            warnings=["pipeline risk warning"],
        )
        output = StringIO()

        call_command(
            "collect_risk_events",
            "--use-data-pipeline",
            "--provider",
            "mock",
            "--dry-run",
            stdout=output,
        )

        rendered = output.getvalue()
        self.assertIn("risk event auto collection complete (data pipeline)", rendered)
        self.assertIn("pipeline risk warning", rendered)
        mock_ingest_risk_events.assert_called_once()


class RiskEventApiPermissionTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="risk_user", password="pw12345")
        self.staff_user = User.objects.create_user(username="risk_admin", password="pw12345", is_staff=True)
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)
        self.event = RiskEvent.objects.create(
            stock=self.stock,
            event_type="other",
            title="테스트",
            event_date="2026-04-28",
            risk_level=RiskEvent.RISK_LOW,
        )

    def test_authenticated_user_can_list_risk_events(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/api/decisions/risk-events/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_non_staff_user_cannot_create_update_or_delete_risk_event(self):
        self.client.force_authenticate(self.user)

        create_response = self.client.post(
            "/api/decisions/risk-events/",
            {
                "stock": self.stock.id,
                "event_type": "operating_loss",
                "title": "영업손실",
                "event_date": "2026-04-29",
                "risk_level": RiskEvent.RISK_MEDIUM,
                "description": "테스트",
                "is_active": True,
            },
            format="json",
        )
        patch_response = self.client.patch(
            f"/api/decisions/risk-events/{self.event.id}/",
            {"title": "수정 시도"},
            format="json",
        )
        delete_response = self.client.delete(f"/api/decisions/risk-events/{self.event.id}/")

        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(patch_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(delete_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_user_can_create_risk_event(self):
        self.client.force_authenticate(self.staff_user)

        response = self.client.post(
            "/api/decisions/risk-events/",
            {
                "stock": self.stock.id,
                "event_type": "operating_loss",
                "title": "영업손실",
                "event_date": "2026-04-29",
                "risk_level": RiskEvent.RISK_MEDIUM,
                "description": "테스트",
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(RiskEvent.objects.filter(stock=self.stock).count(), 2)


class DecisionApiSmokeTests(APITestCase):
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
        )
        other_holding = UserHolding.objects.create(
            user=self.other_user,
            stock=Stock.objects.create(code="000660", name="SK하이닉스", market=Stock.MARKET_KOSPI),
            average_price=Decimal("180000.00"),
            quantity=3,
        )
        AveragingDecision.objects.create(
            holding=self.holding,
            score=55,
            grade=AveragingDecision.GRADE_B,
            decision="관찰 구간",
            reason_summary="내 데이터",
        )
        AveragingDecision.objects.create(
            holding=other_holding,
            score=20,
            grade=AveragingDecision.GRADE_D,
            decision="손절 또는 비중 축소 기준 점검 구간",
            reason_summary="남의 데이터",
        )
        RiskEvent.objects.create(
            stock=self.stock,
            event_type="other",
            title="테스트",
            event_date="2026-04-28",
            risk_level=RiskEvent.RISK_LOW,
        )
        self.client.force_authenticate(self.user)

    def test_decision_endpoints_smoke(self):
        response_events = self.client.get("/api/decisions/risk-events/")
        response_decisions = self.client.get("/api/decisions/averaging-decisions/")

        self.assertEqual(response_events.status_code, status.HTTP_200_OK)
        self.assertEqual(response_decisions.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response_decisions.data), 1)

    def test_probability_and_consult_record_endpoints_are_owner_scoped(self):
        AveragingProbabilityRecord.objects.create(
            holding=self.holding,
            scenario_input={"buy_price": "70000.00", "buy_quantity": 3},
            response_payload={"success_probability": "0.5500"},
            success_probability=Decimal("0.5500"),
            failure_probability=Decimal("0.2500"),
            neutral_probability=Decimal("0.2000"),
            confidence=Decimal("0.7000"),
        )
        HoldingConsultRecord.objects.create(
            holding=self.holding,
            request_input={"include_scenarios": True},
            response_payload={"final_grade": "B", "consulting_status": "관찰 후 제한 검토 구간"},
            final_grade="B",
            consulting_status="관찰 후 제한 검토 구간",
            summary="내 데이터",
        )
        other_holding = UserHolding.objects.get(user=self.other_user)
        AveragingProbabilityRecord.objects.create(
            holding=other_holding,
            scenario_input={"buy_price": "100.00", "buy_quantity": 1},
            response_payload={"success_probability": "0.1000"},
            success_probability=Decimal("0.1000"),
            failure_probability=Decimal("0.7000"),
            neutral_probability=Decimal("0.2000"),
            confidence=Decimal("0.3000"),
        )
        HoldingConsultRecord.objects.create(
            holding=other_holding,
            request_input={},
            response_payload={"final_grade": "D", "consulting_status": "손절 또는 비중 축소 기준 점검 구간"},
            final_grade="D",
            consulting_status="손절 또는 비중 축소 기준 점검 구간",
            summary="남의 데이터",
        )

        response_probabilities = self.client.get("/api/decisions/probability-records/")
        response_consults = self.client.get("/api/decisions/consult-records/")

        self.assertEqual(response_probabilities.status_code, status.HTTP_200_OK)
        self.assertEqual(response_consults.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response_probabilities.data), 1)
        self.assertEqual(len(response_consults.data), 1)
        self.assertEqual(response_probabilities.data[0]["stock_code"], self.stock.code)
        self.assertEqual(response_consults.data[0]["stock_code"], self.stock.code)

    def test_holding_decisions_endpoint_returns_current_user_history(self):
        response = self.client.get(f"/api/holdings/{self.holding.id}/decisions/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["reason_summary"], "내 데이터")


class DecisionServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="alice", password="pw12345")
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)
        self.holding = UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("75000.00"),
            quantity=10,
            max_additional_budget=Decimal("1000000.00"),
            risk_level=UserHolding.RISK_NORMAL,
        )

    def _create_price_series(self, *, start_date, count, base_close, step, last_volume_multiplier=1):
        prices = []
        start = date(2026, 1, start_date)
        for offset in range(count):
            close_price = Decimal(str(base_close + (step * offset)))
            volume = 1000
            if offset == count - 1:
                volume = int(volume * last_volume_multiplier)
            price = DailyPrice.objects.create(
                stock=self.stock,
                date=start + timedelta(days=offset),
                open_price=close_price - Decimal("1.00"),
                high_price=close_price + Decimal("2.00"),
                low_price=close_price - Decimal("2.00"),
                close_price=close_price,
                volume=volume,
            )
            prices.append(price)
        return prices

    def _create_market_series(self, code, name, count, base_close, step, change_rate=Decimal("0.5000")):
        rows = []
        start = date(2026, 1, 1)
        for offset in range(count):
            row = MarketIndex.objects.create(
                code=code,
                name=name,
                date=start + timedelta(days=offset),
                close_value=Decimal(str(base_close + (step * offset))),
                change_rate=change_rate,
            )
            rows.append(row)
        return rows

    def test_support_score_is_positive_near_support(self):
        rows = []
        for offset, close_value in enumerate([100, 99, 101, 100, 99, 100, 101, 100, 99, 100, 100, 101, 100, 99, 100, 101, 100, 99, 100, 100]):
            rows.append(
                DailyPrice(
                    stock=self.stock,
                    date=f"2026-04-{offset + 1:02d}",
                    open_price=Decimal(str(close_value)),
                    high_price=Decimal(str(close_value + 2)),
                    low_price=Decimal("97.00") if offset % 5 == 0 else Decimal(str(close_value - 1)),
                    close_price=Decimal(str(close_value)),
                    volume=1500 if offset == 19 else 1000,
                )
            )

        result = calculate_support_score(rows)

        self.assertGreater(result["score"], 0)
        self.assertIsNotNone(result["details"]["support_price"])

    def test_volume_score_is_positive_when_bounce_has_strong_volume(self):
        rows = []
        for offset in range(20):
            close_price = Decimal("100.00")
            volume = 1000
            if offset == 18:
                close_price = Decimal("99.00")
            if offset == 19:
                close_price = Decimal("101.00")
                volume = 2500
            rows.append(
                DailyPrice(
                    stock=self.stock,
                    date=f"2026-04-{offset + 1:02d}",
                    open_price=close_price - Decimal("1.00"),
                    high_price=close_price + Decimal("2.00"),
                    low_price=close_price - Decimal("2.00"),
                    close_price=close_price,
                    volume=volume,
                )
            )

        result = calculate_volume_score(rows)

        self.assertGreater(result["score"], 0)

    def test_investor_flow_score_rewards_foreign_and_institution_buying(self):
        flow_rows = [
            InvestorFlow(stock=self.stock, date=f"2026-04-{index + 1:02d}", foreign_net_buy=100, institution_net_buy=200, individual_net_buy=-300, program_net_buy=0)
            for index in range(5)
        ]

        result = calculate_investor_flow_score(flow_rows)

        self.assertEqual(result["score"], 20)

    def test_has_critical_risk_detects_active_critical_event(self):
        event = RiskEvent.objects.create(
            stock=self.stock,
            event_type="trading_halt",
            title="거래정지",
            event_date="2026-04-28",
            risk_level=RiskEvent.RISK_CRITICAL,
        )

        result = has_critical_risk(self.stock)

        self.assertTrue(result["has_critical"])
        self.assertEqual(result["events"], [event])

    def test_risk_score_is_capped_at_minus_fifty(self):
        events = [
            RiskEvent(stock=self.stock, event_type="other", title=f"이벤트 {index}", event_date="2026-04-28", risk_level=RiskEvent.RISK_HIGH)
            for index in range(3)
        ]

        result = calculate_risk_score(events)

        self.assertEqual(result["score"], -50)

    def test_convert_score_to_grade_boundaries(self):
        self.assertEqual(convert_score_to_grade(75), "A")
        self.assertEqual(convert_score_to_grade(55), "B")
        self.assertEqual(convert_score_to_grade(35), "C")
        self.assertEqual(convert_score_to_grade(34), "D")

    def test_evaluate_averaging_timing_returns_data_insufficient_when_latest_price_is_missing(self):
        result = evaluate_averaging_timing(self.holding)

        self.assertIsInstance(result, EvaluationResult)
        self.assertEqual(result.grade, "D")
        self.assertEqual(result.decision, "데이터 부족으로 평가 불가")
        self.assertEqual(result.suggested_budget, Decimal("0"))

    def test_evaluate_averaging_timing_returns_d_on_critical_risk(self):
        DailyPrice.objects.create(
            stock=self.stock,
            date="2026-04-28",
            open_price=Decimal("69000.00"),
            high_price=Decimal("70000.00"),
            low_price=Decimal("68000.00"),
            close_price=Decimal("69500.00"),
            volume=12345678,
        )
        RiskEvent.objects.create(
            stock=self.stock,
            event_type="trading_halt",
            title="거래정지",
            event_date="2026-04-28",
            risk_level=RiskEvent.RISK_CRITICAL,
        )

        result = evaluate_averaging_timing(self.holding)

        self.assertEqual(result.grade, "D")
        self.assertEqual(result.suggested_budget, Decimal("0"))
        self.assertTrue(any("거래정지" in reason for reason in result.reasons))

    def test_evaluate_averaging_timing_returns_a_grade_for_strong_setup(self):
        self._create_price_series(start_date=1, count=120, base_close=100, step=1, last_volume_multiplier=3)
        for index in range(5):
            InvestorFlow.objects.create(
                stock=self.stock,
                date=f"2026-04-{index + 1:02d}",
                foreign_net_buy=1000,
                institution_net_buy=1200,
                individual_net_buy=-2200,
                program_net_buy=100,
            )
        self._create_market_series("KOSPI", "KOSPI", 60, 2400, 5)
        self._create_market_series("NASDAQ", "NASDAQ", 60, 15000, 10)

        result = evaluate_averaging_timing(self.holding)

        self.assertIsInstance(result, EvaluationResult)
        self.assertEqual(result.grade, "A")
        self.assertGreater(result.suggested_budget, Decimal("0"))
        self.assertIn("trend", result.score_breakdown)
        self.assertIn("support", result.score_breakdown)
        self.assertIn("volume", result.score_breakdown)
        self.assertIn("flow", result.score_breakdown)
        self.assertIn("market", result.score_breakdown)
        self.assertIn("risk", result.score_breakdown)
        self.assertEqual(result.disclaimer, DISCLAIMER_TEXT)


class ProbabilityFormulaTests(TestCase):
    def test_calculate_new_average_price_returns_weighted_average(self):
        result = calculate_new_average_price(
            current_average_price=Decimal("75000.00"),
            current_quantity=10,
            buy_price=Decimal("69000.00"),
            buy_quantity=5,
        )

        self.assertEqual(result, Decimal("73000.00"))

    def test_calculate_new_average_price_rejects_invalid_quantity(self):
        with self.assertRaises(ValueError):
            calculate_new_average_price(
                current_average_price=Decimal("75000.00"),
                current_quantity=10,
                buy_price=Decimal("69000.00"),
                buy_quantity=0,
            )

    def test_calculate_target_price_supports_profit_and_manual_modes(self):
        profit_target = calculate_target_price(
            current_average_price=Decimal("75000.00"),
            current_quantity=10,
            buy_price=Decimal("69000.00"),
            buy_quantity=5,
            target_type="new_average_price_plus_profit",
            target_profit_rate=Decimal("0.0300"),
        )
        manual_target = calculate_target_price(
            current_average_price=Decimal("75000.00"),
            current_quantity=10,
            buy_price=Decimal("69000.00"),
            buy_quantity=5,
            target_type="manual",
            manual_target_price=Decimal("74000.00"),
        )

        self.assertEqual(profit_target, Decimal("75190.00"))
        self.assertEqual(manual_target, Decimal("74000.00"))

    def test_calculate_probability_stop_loss_price_supports_multiple_modes(self):
        support_stop = calculate_probability_stop_loss_price(
            current_price=Decimal("69000.00"),
            stop_loss_type="support",
            support_price=Decimal("67000.00"),
        )
        atr_stop = calculate_probability_stop_loss_price(
            current_price=Decimal("69000.00"),
            stop_loss_type="atr",
            atr14=Decimal("1000.0000"),
        )
        fallback_stop = calculate_probability_stop_loss_price(
            current_price=Decimal("69000.00"),
            stop_loss_type="support_or_atr",
            support_price=None,
            atr14=None,
        )
        manual_stop = calculate_probability_stop_loss_price(
            current_price=Decimal("69000.00"),
            stop_loss_type="manual",
            manual_stop_loss_price=Decimal("65000.00"),
        )

        self.assertEqual(support_stop, Decimal("64990.00"))
        self.assertEqual(atr_stop, Decimal("67500.00"))
        self.assertEqual(fallback_stop, Decimal("64170.00"))
        self.assertEqual(manual_stop, Decimal("65000.00"))


class ProbabilityComponentTests(TestCase):
    def setUp(self):
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)

    def test_score_component_midpoint_is_balanced(self):
        component = calculate_score_component(score=55, grade="B", active_risk_events=[])

        self.assertEqual(component.success + component.failure + component.neutral, Decimal("1.0000"))
        self.assertGreater(component.success, Decimal("0.4900"))
        self.assertLess(component.success, Decimal("0.5100"))

    def test_score_component_increases_failure_when_high_risk_exists(self):
        plain = calculate_score_component(score=55, grade="B", active_risk_events=[])
        high_risk_event = RiskEvent(
            stock=self.stock,
            event_type="other",
            title="고위험",
            event_date="2026-04-28",
            risk_level=RiskEvent.RISK_HIGH,
        )
        adjusted = calculate_score_component(score=55, grade="B", active_risk_events=[high_risk_event])

        self.assertGreater(adjusted.failure, plain.failure)
        self.assertEqual(adjusted.success + adjusted.failure + adjusted.neutral, Decimal("1.0000"))

    def test_volatility_component_uses_fallback_and_sums_to_one(self):
        price_rows = [
            DailyPrice(
                stock=self.stock,
                date="2026-04-01",
                open_price=Decimal("100.00"),
                high_price=Decimal("101.00"),
                low_price=Decimal("99.00"),
                close_price=Decimal("100.00"),
                volume=1000,
            )
        ]

        component = calculate_volatility_component(
            current_price=Decimal("100.00"),
            target_price=Decimal("105.00"),
            stop_loss_price=Decimal("95.00"),
            price_rows=price_rows,
            atr14=None,
            lookahead_days=20,
            trend_score=15,
        )

        self.assertEqual(component.success + component.failure + component.neutral, Decimal("1.0000"))
        self.assertTrue(any("기본 변동성" in warning for warning in component.warnings))

    def test_determine_historical_outcome_respects_same_day_policy(self):
        future_rows = [
            DailyPrice(
                stock=self.stock,
                date="2026-04-02",
                open_price=Decimal("100.00"),
                high_price=Decimal("106.00"),
                low_price=Decimal("94.00"),
                close_price=Decimal("100.00"),
                volume=1000,
            )
        ]

        conservative = determine_historical_outcome(
            future_price_rows=future_rows,
            target_price=Decimal("105.00"),
            stop_loss_price=Decimal("95.00"),
            same_day_hit_policy="conservative",
            base_close=Decimal("100.00"),
        )
        optimistic = determine_historical_outcome(
            future_price_rows=future_rows,
            target_price=Decimal("105.00"),
            stop_loss_price=Decimal("95.00"),
            same_day_hit_policy="optimistic",
            base_close=Decimal("100.00"),
        )
        neutral = determine_historical_outcome(
            future_price_rows=future_rows,
            target_price=Decimal("105.00"),
            stop_loss_price=Decimal("95.00"),
            same_day_hit_policy="neutral",
            base_close=Decimal("100.00"),
        )

        self.assertEqual(conservative.outcome, "failure")
        self.assertEqual(optimistic.outcome, "success")
        self.assertEqual(neutral.outcome, "neutral")

    def test_historical_component_warns_when_samples_are_insufficient(self):
        start = date(2026, 1, 1)
        for offset in range(12):
            close_price = Decimal(str(100 + offset))
            DailyPrice.objects.create(
                stock=self.stock,
                date=start + timedelta(days=offset),
                open_price=close_price,
                high_price=close_price + Decimal("2.00"),
                low_price=close_price - Decimal("2.00"),
                close_price=close_price,
                volume=1000,
            )

        component = calculate_historical_probabilities(
            stock=self.stock,
            current_snapshot=None,
            target_return=Decimal("0.0500"),
            stop_loss_return=Decimal("0.0500"),
            lookahead_days=5,
            min_cases=30,
        )

        self.assertLess(component.sample_count, 30)
        self.assertTrue(any("historical weight" in warning for warning in component.warnings))

    def test_build_probability_feature_snapshot_populates_core_fields(self):
        start = date(2026, 1, 1)
        for offset in range(25):
            close_price = Decimal("100.00") + Decimal(str(offset))
            DailyPrice.objects.create(
                stock=self.stock,
                date=start + timedelta(days=offset),
                open_price=close_price - Decimal("1.00"),
                high_price=close_price + Decimal("2.00"),
                low_price=close_price - Decimal("2.00"),
                close_price=close_price,
                volume=1000 + (offset * 100),
            )
            MarketIndex.objects.create(
                code="KOSPI",
                name="KOSPI",
                date=start + timedelta(days=offset),
                close_value=Decimal("2400.00") + Decimal(str(offset * 3)),
                change_rate=Decimal("0.5000"),
            )
        InvestorFlow.objects.create(
            stock=self.stock,
            date=start + timedelta(days=24),
            foreign_net_buy=1200,
            institution_net_buy=-500,
            individual_net_buy=-700,
            program_net_buy=0,
        )

        snapshot = build_probability_feature_snapshot(
            price_rows=list(DailyPrice.objects.filter(stock=self.stock).order_by("date")),
            flow_rows=list(InvestorFlow.objects.filter(stock=self.stock).order_by("date")),
            market_rows=list(MarketIndex.objects.filter(code="KOSPI").order_by("date")),
            active_risk_events=[],
        )

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.date, start + timedelta(days=24))
        self.assertIsNone(snapshot.loss_rate_pct)
        self.assertIsNotNone(snapshot.rsi14)
        self.assertIsNotNone(snapshot.price_to_ma20_pct)
        self.assertIsNotNone(snapshot.support_distance_pct)
        self.assertIsNotNone(snapshot.volume_ratio)
        self.assertEqual(snapshot.foreign_flow_signal, 1)
        self.assertEqual(snapshot.institution_flow_signal, -1)

    def test_calculate_snapshot_distance_returns_low_distance_for_similar_snapshots(self):
        current_snapshot = build_probability_feature_snapshot(
            price_rows=[
                DailyPrice(
                    stock=self.stock,
                    date=date(2026, 1, day),
                    open_price=Decimal("100.00") + day,
                    high_price=Decimal("101.00") + day,
                    low_price=Decimal("99.00") + day,
                    close_price=Decimal("100.00") + day,
                    volume=1000 + (day * 10),
                )
                for day in range(1, 26)
            ],
            active_risk_events=[],
        )
        past_snapshot = build_probability_feature_snapshot(
            price_rows=[
                DailyPrice(
                    stock=self.stock,
                    date=date(2025, 12, day),
                    open_price=Decimal("101.00") + day,
                    high_price=Decimal("102.00") + day,
                    low_price=Decimal("100.00") + day,
                    close_price=Decimal("101.00") + day,
                    volume=1010 + (day * 10),
                )
                for day in range(1, 26)
            ],
            active_risk_events=[],
        )

        distance_result = calculate_snapshot_distance(current_snapshot, past_snapshot)

        self.assertIsNotNone(distance_result)
        self.assertLess(distance_result["distance"], Decimal("0.3000"))
        self.assertGreater(distance_result["coverage"], Decimal("0.5000"))

    def test_calculate_snapshot_distance_penalizes_risk_signal_difference(self):
        base_rows = [
            DailyPrice(
                stock=self.stock,
                date=date(2026, 1, day),
                open_price=Decimal("100.00") + day,
                high_price=Decimal("101.00") + day,
                low_price=Decimal("99.00") + day,
                close_price=Decimal("100.00") + day,
                volume=1000 + (day * 10),
            )
            for day in range(1, 26)
        ]
        plain_snapshot = build_probability_feature_snapshot(price_rows=base_rows, active_risk_events=[])
        risky_snapshot = build_probability_feature_snapshot(
            price_rows=base_rows,
            active_risk_events=[
                RiskEvent(
                    stock=self.stock,
                    event_type="managed_stock",
                    title="관리종목 지정",
                    event_date=date(2026, 1, 25),
                    risk_level=RiskEvent.RISK_HIGH,
                )
            ],
        )

        distance_result = calculate_snapshot_distance(plain_snapshot, risky_snapshot)

        self.assertIsNotNone(distance_result)
        self.assertGreater(distance_result["distance"], Decimal("0.0000"))
        self.assertIsNotNone(distance_result["feature_distances"]["risk_level_signal"])

    def test_calculate_snapshot_distance_uses_loss_rate_feature_when_available(self):
        current_snapshot = ProbabilityFeatureSnapshot(
            date=date(2026, 1, 25),
            close_price=Decimal("120.00"),
            loss_rate_pct=Decimal("-0.0500"),
            rsi14=Decimal("55.0000"),
            price_to_ma20_pct=Decimal("0.0200"),
            price_to_ma60_pct=Decimal("0.0500"),
            support_distance_pct=Decimal("0.0100"),
            volume_ratio=Decimal("1.2000"),
            foreign_flow_signal=1,
            institution_flow_signal=1,
            market_trend_signal=1,
            risk_level_signal=0,
        )
        past_snapshot = ProbabilityFeatureSnapshot(
            date=date(2025, 12, 25),
            close_price=Decimal("110.00"),
            loss_rate_pct=Decimal("-0.2500"),
            rsi14=Decimal("55.0000"),
            price_to_ma20_pct=Decimal("0.0200"),
            price_to_ma60_pct=Decimal("0.0500"),
            support_distance_pct=Decimal("0.0100"),
            volume_ratio=Decimal("1.2000"),
            foreign_flow_signal=1,
            institution_flow_signal=1,
            market_trend_signal=1,
            risk_level_signal=0,
        )

        distance_result = calculate_snapshot_distance(current_snapshot, past_snapshot)

        self.assertIsNotNone(distance_result)
        self.assertGreater(distance_result["distance"], Decimal("0.0000"))
        self.assertIsNotNone(distance_result["feature_distances"]["loss_rate_pct"])

    def test_historical_component_selects_similar_cases_instead_of_all_candidates(self):
        start = date(2026, 1, 1)
        for offset in range(60):
            if offset < 30:
                close_price = Decimal("100.00") + Decimal(str((offset % 3) * 0.2))
                volume = 1000
            else:
                close_price = Decimal("100.00") + Decimal(str(offset - 29))
                volume = 5000
            DailyPrice.objects.create(
                stock=self.stock,
                date=start + timedelta(days=offset),
                open_price=close_price - Decimal("1.00"),
                high_price=close_price + Decimal("3.00"),
                low_price=close_price - Decimal("2.00"),
                close_price=close_price,
                volume=volume,
            )
            MarketIndex.objects.create(
                code="KOSPI",
                name="KOSPI",
                date=start + timedelta(days=offset),
                close_value=Decimal("2400.00") + Decimal(str(offset * 2)),
                change_rate=Decimal("0.5000"),
            )
        InvestorFlow.objects.create(
            stock=self.stock,
            date=start + timedelta(days=59),
            foreign_net_buy=1500,
            institution_net_buy=500,
            individual_net_buy=-2000,
            program_net_buy=0,
        )

        price_rows = list(DailyPrice.objects.filter(stock=self.stock).order_by("date"))
        market_rows = list(MarketIndex.objects.filter(code="KOSPI").order_by("date"))
        flow_rows = list(InvestorFlow.objects.filter(stock=self.stock).order_by("date"))
        current_snapshot = build_probability_feature_snapshot(
            price_rows=price_rows,
            flow_rows=flow_rows,
            market_rows=market_rows,
            active_risk_events=[],
        )

        component = calculate_historical_probabilities(
            stock=self.stock,
            current_snapshot=current_snapshot,
            target_return=Decimal("0.0500"),
            stop_loss_return=Decimal("0.0500"),
            lookahead_days=5,
            min_cases=10,
            price_rows=price_rows,
            flow_rows=flow_rows,
            market_rows=market_rows,
            active_risk_events=[],
        )

        self.assertLess(component.details["selected_case_count"], component.details["candidate_count"])
        self.assertIn("selected_threshold", component.details)
        self.assertIn("avg_distance", component.details)
        self.assertIn("outcome_stability", component.details)
        self.assertIn("selection_summary", component.details)
        self.assertIn("outcome_bias_summary", component.details)
        self.assertIn("outcome_case_groups", component.details)
        self.assertIn("closest_features", component.details)
        self.assertIn("weakest_features", component.details)
        self.assertIn("top_similar_cases", component.details)
        self.assertTrue(component.details["top_similar_cases"])
        self.assertIn("match_summary", component.details["top_similar_cases"][0])
        self.assertIn("reason_summary", component.details["top_similar_cases"][0])
        self.assertTrue(component.details["selection_summary"])
        self.assertTrue(component.details["outcome_bias_summary"])


class ProbabilityServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="probability_user", password="pw12345")
        self.stock = Stock.objects.create(code="035420", name="NAVER", market=Stock.MARKET_KOSPI)
        self.holding = UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("105.00"),
            quantity=10,
            max_additional_budget=Decimal("1000000.00"),
        )

    def _create_price_series(self, *, count=120, base_close=90, step=Decimal("0.25")):
        start = date(2026, 1, 1)
        for offset in range(count):
            close_price = Decimal(str(base_close)) + (step * offset)
            DailyPrice.objects.create(
                stock=self.stock,
                date=start + timedelta(days=offset),
                open_price=close_price - Decimal("1.00"),
                high_price=close_price + Decimal("2.00"),
                low_price=close_price - Decimal("2.00"),
                close_price=close_price,
                volume=3000 if offset == count - 1 else 1000,
            )

    def _create_market_series(self):
        start = date(2026, 1, 1)
        for offset in range(60):
            MarketIndex.objects.create(
                code="KOSPI",
                name="KOSPI",
                date=start + timedelta(days=offset),
                close_value=Decimal("2400.00") + Decimal(offset * 5),
                change_rate=Decimal("0.5000"),
            )
            MarketIndex.objects.create(
                code="NASDAQ",
                name="NASDAQ",
                date=start + timedelta(days=offset),
                close_value=Decimal("15000.00") + Decimal(offset * 10),
                change_rate=Decimal("0.5000"),
            )

    def _create_flow_series(self):
        for index in range(5):
            InvestorFlow.objects.create(
                stock=self.stock,
                date=date(2026, 5, 1) + timedelta(days=index),
                foreign_net_buy=1000,
                institution_net_buy=1200,
                individual_net_buy=-2200,
                program_net_buy=100,
            )

    def test_probability_service_returns_neutral_when_latest_price_is_missing(self):
        scenario = AveragingScenario(
            buy_price=Decimal("98.00"),
            buy_quantity=5,
        )

        result = calculate_averaging_success_failure_probability(holding=self.holding, scenario=scenario)

        self.assertIsInstance(result, ProbabilityResult)
        self.assertEqual(result.success_probability, Decimal("0.0000"))
        self.assertEqual(result.failure_probability, Decimal("0.0000"))
        self.assertEqual(result.neutral_probability, Decimal("1.0000"))
        self.assertEqual(result.confidence, Decimal("0.0000"))

    def test_probability_service_applies_critical_risk_override(self):
        self._create_price_series()
        RiskEvent.objects.create(
            stock=self.stock,
            event_type="trading_halt",
            title="거래정지",
            event_date="2026-04-28",
            risk_level=RiskEvent.RISK_CRITICAL,
        )
        scenario = AveragingScenario(
            buy_price=Decimal("98.00"),
            buy_quantity=5,
        )

        result = calculate_averaging_success_failure_probability(holding=self.holding, scenario=scenario)

        self.assertEqual(result.success_probability, Decimal("0.0200"))
        self.assertEqual(result.failure_probability, Decimal("0.9500"))
        self.assertEqual(result.neutral_probability, Decimal("0.0300"))
        self.assertEqual(result.confidence, Decimal("0.9000"))
        self.assertTrue(any("치명적 위험 이벤트" in warning for warning in result.warnings))

    def test_probability_service_returns_result_with_basis_without_creating_decision(self):
        self._create_price_series()
        self._create_flow_series()
        self._create_market_series()
        scenario = AveragingScenario(
            buy_price=Decimal("98.00"),
            buy_quantity=5,
            lookahead_days=20,
            target_type="new_average_price",
            stop_loss_type="support_or_atr",
        )

        result = calculate_averaging_success_failure_probability(holding=self.holding, scenario=scenario)

        self.assertIsInstance(result, ProbabilityResult)
        self.assertEqual(
            result.success_probability + result.failure_probability + result.neutral_probability,
            Decimal("1.0000"),
        )
        self.assertIn("scenario", result.basis)
        self.assertIn("prices", result.basis)
        self.assertIn("components", result.basis)
        self.assertIn("weights", result.basis)
        self.assertIn("current_snapshot", result.basis["components"]["historical"])
        self.assertIn("top_similar_cases", result.basis["components"]["historical"])
        self.assertIn("selection_summary", result.basis["components"]["historical"])
        self.assertIn("outcome_bias_summary", result.basis["components"]["historical"])
        self.assertIn("outcome_case_groups", result.basis["components"]["historical"])
        self.assertIn("reason_summary", result.basis["components"]["historical"]["top_similar_cases"][0])
        self.assertIsNotNone(result.basis["components"]["historical"]["current_snapshot"]["loss_rate_pct"])
        self.assertEqual(result.disclaimer.count("매수·매도 추천"), 1)
        self.assertEqual(AveragingDecision.objects.count(), 0)
        self.assertEqual(AveragingProbabilityRecord.objects.count(), 0)


class DataQualityServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="dq_user", password="pw12345")
        self.stock = Stock.objects.create(code="111111", name="테스트", market=Stock.MARKET_KOSPI)
        self.holding = UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("100.00"),
            quantity=10,
            max_additional_budget=Decimal("500000.00"),
        )

    def _create_price_series(self, count):
        start = timezone.localdate() - timedelta(days=count - 1)
        for offset in range(count):
            close_price = Decimal("100.00") + Decimal(offset)
            DailyPrice.objects.create(
                stock=self.stock,
                date=start + timedelta(days=offset),
                open_price=close_price - Decimal("1.00"),
                high_price=close_price + Decimal("2.00"),
                low_price=close_price - Decimal("2.00"),
                close_price=close_price,
                volume=1000,
            )

    def _create_flow_series(self, count):
        start = timezone.localdate() - timedelta(days=count - 1)
        for offset in range(count):
            InvestorFlow.objects.create(
                stock=self.stock,
                date=start + timedelta(days=offset),
                foreign_net_buy=100,
                institution_net_buy=200,
                individual_net_buy=-300,
                program_net_buy=0,
            )

    def _create_market_series(self, count):
        start = timezone.localdate() - timedelta(days=count - 1)
        for offset in range(count):
            MarketIndex.objects.create(
                code="KOSPI",
                name="KOSPI",
                date=start + timedelta(days=offset),
                close_value=Decimal("2400.00") + Decimal(offset * 5),
                change_rate=Decimal("0.5000"),
            )

    def test_evaluate_data_quality_returns_high_with_sufficient_data(self):
        self._create_price_series(120)
        self._create_flow_series(20)
        self._create_market_series(60)

        result = evaluate_data_quality(self.holding)

        self.assertEqual(result.label, "높음")
        self.assertIsNone(get_data_quality_grade_cap(result))

    def test_evaluate_data_quality_returns_very_low_when_price_data_is_missing(self):
        result = evaluate_data_quality(self.holding)

        self.assertEqual(result.label, "매우 낮음")
        self.assertEqual(get_data_quality_grade_cap(result), "C")
        self.assertTrue(any("최신 가격 데이터" in warning for warning in result.warnings))


class RiskGateServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="rg_user", password="pw12345")
        self.stock = Stock.objects.create(code="222222", name="리스크", market=Stock.MARKET_KOSPI)
        self.holding = UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("100.00"),
            quantity=10,
        )

    def test_risk_gate_returns_critical_for_active_critical_event(self):
        RiskEvent.objects.create(
            stock=self.stock,
            event_type="trading_halt",
            title="거래정지",
            event_date=timezone.localdate(),
            risk_level=RiskEvent.RISK_CRITICAL,
        )

        result = evaluate_risk_gate(self.holding)

        self.assertEqual(result.status, "CRITICAL")
        self.assertEqual(result.grade_cap, "D")

    def test_risk_gate_detects_block_keyword(self):
        RiskEvent.objects.create(
            stock=self.stock,
            event_type="other",
            title="대규모 유상증자",
            event_date=timezone.localdate(),
            risk_level=RiskEvent.RISK_LOW,
        )

        result = evaluate_risk_gate(self.holding)

        self.assertEqual(result.status, "BLOCK")
        self.assertEqual(result.grade_cap, "C")

    def test_risk_gate_decays_old_critical_event_to_block(self):
        RiskEvent.objects.create(
            stock=self.stock,
            event_type="trading_halt",
            title="거래정지",
            event_date=timezone.localdate() - timedelta(days=60),
            risk_level=RiskEvent.RISK_CRITICAL,
        )

        result = evaluate_risk_gate(self.holding)

        self.assertEqual(result.status, "BLOCK")
        self.assertEqual(result.grade_cap, "C")
        self.assertEqual(result.details["final_status_before_decay"], "CRITICAL")
        self.assertEqual(result.details["final_status_after_decay"], "BLOCK")
        self.assertEqual(result.details["event_statuses"][0]["raw_status"], "CRITICAL")
        self.assertEqual(result.details["event_statuses"][0]["effective_status"], "BLOCK")
        self.assertEqual(result.details["decayed_event_count"], 1)

    def test_risk_gate_decays_old_block_event_to_caution(self):
        RiskEvent.objects.create(
            stock=self.stock,
            event_type="other",
            title="대규모 유상증자",
            event_date=timezone.localdate() - timedelta(days=120),
            risk_level=RiskEvent.RISK_LOW,
        )

        result = evaluate_risk_gate(self.holding)

        self.assertEqual(result.status, "CAUTION")
        self.assertEqual(result.grade_cap, "B")
        self.assertTrue(any("완화" in warning for warning in result.warnings))

    def test_risk_gate_decays_stale_caution_event_to_pass(self):
        RiskEvent.objects.create(
            stock=self.stock,
            event_type="other",
            title="투자주의",
            event_date=timezone.localdate() - timedelta(days=240),
            risk_level=RiskEvent.RISK_LOW,
        )

        result = evaluate_risk_gate(self.holding)

        self.assertEqual(result.status, "PASS")
        self.assertIsNone(result.grade_cap)
        self.assertEqual(result.details["event_statuses"][0]["effective_status"], "PASS")
        self.assertTrue(any("오래된 이벤트 이력" in warning for warning in result.warnings))

    def test_risk_gate_returns_pass_without_events(self):
        result = evaluate_risk_gate(self.holding)

        self.assertEqual(result.status, "PASS")
        self.assertIsNone(result.grade_cap)


class ScenarioComparisonServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="scenario_user", password="pw12345")
        self.stock = Stock.objects.create(code="333333", name="시나리오", market=Stock.MARKET_KOSPI)
        self.holding = UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("100.00"),
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
                volume=1000,
            )

    def test_build_default_scenarios_returns_three_quantities(self):
        result = build_default_scenarios(self.holding)

        self.assertEqual([scenario["buy_quantity"] for scenario in result["scenarios"]], [3, 5, 10])

    def test_compare_scenarios_marks_all_items_forbidden_when_risk_gate_blocks(self):
        risk_gate_result = RiskGateResult(
            status="BLOCK",
            grade_cap="C",
            score_multiplier=0.5,
            critical_events=[],
            blockers=["테스트"],
        )

        result = compare_scenarios(self.holding, risk_gate_result=risk_gate_result)

        self.assertEqual(len(result["items"]), 3)
        self.assertTrue(all(item.status == "금지" for item in result["items"]))

    def test_compare_scenarios_gracefully_handles_probability_failure(self):
        with patch(
            "decisions.services.scenario_comparison_service.calculate_averaging_success_failure_probability",
            side_effect=RuntimeError("boom"),
        ):
            result = compare_scenarios(self.holding)

        self.assertEqual(len(result["items"]), 3)
        self.assertTrue(all(item.success_probability is None for item in result["items"]))
        self.assertTrue(any("Probability Engine" in warning for warning in result["warnings"]))


class CapitalAllocationServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="capital_user", password="pw12345")
        self.stock = Stock.objects.create(code="444444", name="예산", market=Stock.MARKET_KOSPI)
        self.holding = UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("100.00"),
            quantity=10,
            max_additional_budget=Decimal("1000000.00"),
        )
        DailyPrice.objects.create(
            stock=self.stock,
            date=timezone.localdate(),
            open_price=Decimal("100.00"),
            high_price=Decimal("102.00"),
            low_price=Decimal("98.00"),
            close_price=Decimal("100.00"),
            volume=1000,
        )
        self.scenario_items = [
            ScenarioComparisonItem(
                scenario_type="base",
                buy_price=Decimal("100.00"),
                buy_quantity=5,
                new_average_price=Decimal("100.00"),
                target_price=Decimal("103.00"),
                stop_loss_price=Decimal("95.00"),
                success_probability=Decimal("0.5000"),
                failure_probability=Decimal("0.2000"),
                neutral_probability=Decimal("0.3000"),
                confidence=Decimal("0.6000"),
                efficiency_score=Decimal("0.2000"),
                status="관찰",
            )
        ]
        self.market_risk_on = MarketRegimeResult(
            regime="risk_on",
            score_adjustment=5,
            score_multiplier=Decimal("1.10"),
            grade_cap=None,
        )
        self.data_quality_high = DataQualityResult(
            overall_score=Decimal("0.9000"),
            label="높음",
            price_data_days=120,
            latest_price_age_days=0,
            investor_flow_days=20,
            market_data_available=True,
            risk_event_available=True,
        )

    def test_build_capital_plan_keeps_budget_in_supportive_conditions(self):
        risk_gate_result = RiskGateResult(
            status="PASS",
            grade_cap=None,
            score_multiplier=1.0,
            critical_events=[],
        )

        result = build_capital_plan(
            self.holding,
            risk_gate_result=risk_gate_result,
            market_regime_result=self.market_risk_on,
            data_quality_result=self.data_quality_high,
            scenario_items=self.scenario_items,
        )

        self.assertEqual(result.max_allowed_budget, Decimal("1000000.00"))
        self.assertEqual(result.first_entry_budget, Decimal("400000.00"))

    def test_build_capital_plan_zeroes_budget_when_blocked(self):
        risk_gate_result = RiskGateResult(
            status="BLOCK",
            grade_cap="C",
            score_multiplier=0.5,
            critical_events=[],
        )

        result = build_capital_plan(
            self.holding,
            risk_gate_result=risk_gate_result,
            market_regime_result=self.market_risk_on,
            data_quality_result=self.data_quality_high,
            scenario_items=self.scenario_items,
        )

        self.assertEqual(result.max_allowed_budget, Decimal("0.00"))
        self.assertEqual(result.first_entry_budget, Decimal("0.00"))

    def test_build_capital_plan_limits_second_and_third_entry_for_caution(self):
        risk_gate_result = RiskGateResult(
            status="CAUTION",
            grade_cap="B",
            score_multiplier=0.8,
            critical_events=[],
        )

        result = build_capital_plan(
            self.holding,
            risk_gate_result=risk_gate_result,
            market_regime_result=self.market_risk_on,
            data_quality_result=self.data_quality_high,
            scenario_items=self.scenario_items,
        )

        self.assertEqual(result.second_entry_budget, Decimal("0.00"))
        self.assertEqual(result.third_entry_budget, Decimal("0.00"))


class ConsultingServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="consult_user", password="pw12345")
        self.stock = Stock.objects.create(code="555555", name="컨설팅", market=Stock.MARKET_KOSPI)
        self.holding = UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("120.00"),
            quantity=10,
            max_additional_budget=Decimal("1000000.00"),
        )

    def _create_full_inputs(self):
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
                volume=3000 if offset == 119 else 1000,
            )
        for index in range(20):
            InvestorFlow.objects.create(
                stock=self.stock,
                date=timezone.localdate() - timedelta(days=19 - index),
                foreign_net_buy=1000,
                institution_net_buy=1200,
                individual_net_buy=-2200,
                program_net_buy=100,
            )
        for offset in range(60):
            current_date = timezone.localdate() - timedelta(days=59 - offset)
            MarketIndex.objects.create(
                code="KOSPI",
                name="KOSPI",
                date=current_date,
                close_value=Decimal("2400.00") + Decimal(offset * 5),
                change_rate=Decimal("0.5000"),
            )
            MarketIndex.objects.create(
                code="NASDAQ",
                name="NASDAQ",
                date=current_date,
                close_value=Decimal("15000.00") + Decimal(offset * 10),
                change_rate=Decimal("0.5000"),
            )

    def test_cap_grade_applies_expected_grade_limits(self):
        self.assertEqual(cap_grade("A", "B"), "B")
        self.assertEqual(cap_grade("A", "C"), "C")
        self.assertEqual(cap_grade("C", "B"), "C")

    def test_consult_holding_returns_result_and_recheck_conditions(self):
        self._create_full_inputs()

        result = consult_holding(self.holding)

        self.assertEqual(result.final_grade, "B")
        self.assertEqual(result.consulting_status, "관찰 후 제한 검토 구간")
        self.assertGreaterEqual(len(result.recheck_conditions), 3)
        self.assertIn("score", result.base_decision)
        self.assertIsNotNone(result.probability)
        self.assertIn("explanation", result.probability)
        self.assertIn("highlights", result.probability)
        self.assertIn("selection_summary", result.probability["explanation"])
        self.assertIn("outcome_case_groups", result.probability["explanation"])
        self.assertIn("headline", result.probability["highlights"])
        self.assertIn("representative_cases", result.probability["highlights"])

    def test_consult_holding_returns_d_when_critical_risk_exists(self):
        self._create_full_inputs()
        RiskEvent.objects.create(
            stock=self.stock,
            event_type="trading_halt",
            title="거래정지",
            event_date=timezone.localdate(),
            risk_level=RiskEvent.RISK_CRITICAL,
        )

        result = consult_holding(self.holding)

        self.assertEqual(result.final_grade, "D")
        self.assertEqual(result.risk_gate["status"], "CRITICAL")

    def test_consult_holding_gracefully_handles_probability_failure(self):
        self._create_full_inputs()

        with patch("decisions.services.consulting_service.compare_scenarios", side_effect=RuntimeError("boom")):
            result = consult_holding(self.holding)

        self.assertIsNotNone(result.probability)
        self.assertEqual(result.probability["scenario_type"], "fallback")
        self.assertIn("highlights", result.probability)
        self.assertTrue(result.probability["highlights"]["headline"])
        self.assertGreaterEqual(len(result.scenario_table), 1)
        self.assertEqual(result.scenario_table[0]["scenario_type"], "conservative")
        self.assertTrue(result.scenario_table[0]["reason_summary"])
        self.assertTrue(result.scenario_table[0]["warnings"])
        self.assertTrue(any("확률 기반 시나리오 비교" in warning for warning in result.warnings))

    def test_consult_holding_applies_stock_quality_grade_cap(self):
        self._create_full_inputs()
        FinancialSnapshot.objects.create(
            stock=self.stock,
            fiscal_year=2025,
            period_type=FinancialSnapshot.PERIOD_Q4,
            reported_date=timezone.localdate(),
            revenue=Decimal("1000000.00"),
            operating_profit=Decimal("-1000.00"),
            net_income=Decimal("-1500.00"),
            operating_cash_flow=Decimal("-800.00"),
            debt_ratio=Decimal("320.00"),
            current_ratio=Decimal("90.00"),
            equity=Decimal("500000.00"),
            capital_impairment_rate=Decimal("30.00"),
            roe=Decimal("-10.00"),
            source="manual",
            source_key="manual:005930:2025:Q4",
        )
        FinancialSnapshot.objects.create(
            stock=self.stock,
            fiscal_year=2025,
            period_type=FinancialSnapshot.PERIOD_Q3,
            reported_date=timezone.localdate() - timedelta(days=90),
            revenue=Decimal("1200000.00"),
            operating_profit=Decimal("-1200.00"),
            net_income=Decimal("-1300.00"),
            operating_cash_flow=Decimal("-900.00"),
            debt_ratio=Decimal("300.00"),
            current_ratio=Decimal("95.00"),
            equity=Decimal("520000.00"),
            capital_impairment_rate=Decimal("28.00"),
            roe=Decimal("-8.00"),
            source="manual",
            source_key="manual:005930:2025:Q3",
        )

        result = consult_holding(self.holding)

        self.assertEqual(result.stock_quality["quality_grade"], "Q4")
        self.assertEqual(result.final_grade, "C")


class AdditionalBuySimulationServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="simulation-user", password="pw12345")
        self.stock = Stock.objects.create(code="035250", name="강원랜드", market=Stock.MARKET_KOSPI)
        self.holding = UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("15116.50"),
            quantity=2,
            is_active=True,
        )
        DailyPrice.objects.create(
            stock=self.stock,
            date=date(2026, 6, 16),
            open_price=Decimal("16000.00"),
            high_price=Decimal("16470.00"),
            low_price=Decimal("15830.00"),
            close_price=Decimal("16340.00"),
            volume=2613186,
        )

    def test_build_additional_buy_simulation_uses_latest_daily_price(self):
        result = build_additional_buy_simulation(
            holding=self.holding,
            additional_budget=Decimal("100000.00"),
        )

        self.assertTrue(result["simulation_only"])
        self.assertFalse(result["order_execution"])
        self.assertEqual(result["stock"]["code"], "035250")
        self.assertEqual(result["price_source"]["type"], "daily_price")
        self.assertEqual(result["price_source"]["latest_price"], "16340.00")
        self.assertEqual(result["price_source"]["latest_price_date"], "2026-06-16")
        self.assertEqual(result["price_source"]["simulation_buy_price"], "16340.00")
        self.assertEqual(result["current_position"]["quantity"], 2)
        self.assertEqual(result["current_position"]["average_price"], "15116.50")
        self.assertEqual(result["current_position"]["invested_amount"], "30233.00")
        self.assertEqual(result["current_position"]["market_value"], "32680.00")
        self.assertEqual(result["current_position"]["profit_loss_amount"], "2447.00")
        self.assertEqual(result["current_position"]["profit_loss_rate"], "8.09")
        self.assertEqual(result["simulation"]["additional_quantity"], 6)
        self.assertEqual(result["simulation"]["additional_invested_amount"], "98040.00")
        self.assertEqual(result["simulation"]["unused_budget"], "1960.00")
        self.assertEqual(result["simulation"]["new_quantity"], 8)
        self.assertEqual(result["simulation"]["new_total_invested_amount"], "128273.00")
        self.assertEqual(result["simulation"]["new_average_price"], "16034.13")
        self.assertEqual(result["simulation"]["break_even_price"], "16034.13")
        self.assertEqual(result["simulation"]["required_rise_to_break_even"], "-1.87")
        self.assertEqual(result["simulation"]["simulated_market_value_at_latest"], "130720.00")
        self.assertEqual(result["simulation"]["simulated_profit_loss_amount_at_latest"], "2447.00")
        self.assertEqual(result["simulation"]["simulated_profit_loss_rate_at_latest"], "1.91")
        self.assertIsNone(result["target_projection"])
        warnings_text = " ".join(result["warnings"])
        self.assertIn("calculation-only simulation", warnings_text)
        self.assertIn("does not place orders", warnings_text)
        self.assertIn("not investment advice", warnings_text)
        self.assertIn("does not guarantee returns", warnings_text)
        self.assertIn("Fees and taxes are not included", warnings_text)

    def test_manual_buy_price_overrides_simulation_price(self):
        result = build_additional_buy_simulation(
            holding=self.holding,
            additional_budget=Decimal("100000.00"),
            buy_price=Decimal("16000.00"),
        )

        self.assertEqual(result["price_source"]["type"], "manual_buy_price")
        self.assertEqual(result["price_source"]["latest_price"], "16340.00")
        self.assertEqual(result["price_source"]["simulation_buy_price"], "16000.00")
        self.assertEqual(result["input"]["buy_price"], "16000.00")
        self.assertEqual(result["simulation"]["additional_quantity"], 6)
        self.assertEqual(result["simulation"]["additional_invested_amount"], "96000.00")
        self.assertEqual(result["simulation"]["unused_budget"], "4000.00")
        self.assertEqual(result["simulation"]["new_average_price"], "15779.13")

    def test_target_price_builds_projection(self):
        result = build_additional_buy_simulation(
            holding=self.holding,
            additional_budget=Decimal("100000.00"),
            target_price=Decimal("18000.00"),
        )

        self.assertEqual(result["target_projection"]["target_price"], "18000.00")
        self.assertEqual(result["target_projection"]["target_market_value"], "144000.00")
        self.assertEqual(result["target_projection"]["target_profit_loss_amount"], "15727.00")
        self.assertEqual(result["target_projection"]["target_profit_loss_rate"], "12.26")

    def test_missing_latest_price_can_still_simulate_with_buy_price(self):
        DailyPrice.objects.filter(stock=self.stock).delete()

        result = build_additional_buy_simulation(
            holding=self.holding,
            additional_budget=Decimal("100000.00"),
            buy_price=Decimal("16000.00"),
        )

        self.assertEqual(result["price_source"]["type"], "manual_buy_price")
        self.assertIsNone(result["price_source"]["latest_price"])
        self.assertIsNone(result["current_position"]["market_value"])
        self.assertIsNone(result["current_position"]["profit_loss_amount"])
        self.assertIsNone(result["current_position"]["profit_loss_rate"])
        self.assertIsNone(result["simulation"]["simulated_market_value_at_latest"])
        self.assertIsNone(result["simulation"]["simulated_profit_loss_amount_at_latest"])
        self.assertIsNone(result["simulation"]["simulated_profit_loss_rate_at_latest"])
        self.assertEqual(result["simulation"]["new_average_price"], "15779.13")

    def test_missing_latest_price_without_buy_price_raises_error(self):
        DailyPrice.objects.filter(stock=self.stock).delete()

        with self.assertRaises(AdditionalBuySimulationError) as ctx:
            build_additional_buy_simulation(
                holding=self.holding,
                additional_budget=Decimal("100000.00"),
            )

        self.assertEqual(ctx.exception.code, "latest_price_required")

    def test_validation_errors_have_safe_codes(self):
        cases = [
            ({"additional_budget": Decimal("0")}, "invalid_additional_budget"),
            ({"additional_budget": Decimal("100000"), "buy_price": Decimal("0")}, "invalid_buy_price"),
            ({"additional_budget": Decimal("100000"), "target_price": Decimal("0")}, "invalid_target_price"),
            (
                {"additional_budget": Decimal("100000"), "additional_quantity": 1},
                "conflicting_input",
            ),
            ({"additional_quantity": 1}, "additional_quantity_not_supported"),
            ({"additional_budget": Decimal("100")}, "additional_quantity_too_small"),
        ]

        for kwargs, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(AdditionalBuySimulationError) as ctx:
                    build_additional_buy_simulation(holding=self.holding, **kwargs)
                self.assertEqual(ctx.exception.code, expected_code)

    def test_inactive_holding_raises_error(self):
        self.holding.is_active = False
        self.holding.save(update_fields=["is_active"])

        with self.assertRaises(AdditionalBuySimulationError) as ctx:
            build_additional_buy_simulation(
                holding=self.holding,
                additional_budget=Decimal("100000.00"),
            )

        self.assertEqual(ctx.exception.code, "inactive_holding")

    def test_service_does_not_return_sensitive_keys_or_write_logs(self):
        counts_before = {
            "holdings": UserHolding.objects.count(),
            "daily_prices": DailyPrice.objects.count(),
            "logs": DataIngestionLog.objects.count(),
        }

        result = build_additional_buy_simulation(
            holding=self.holding,
            additional_budget=Decimal("100000.00"),
        )

        self.assertEqual(UserHolding.objects.count(), counts_before["holdings"])
        self.assertEqual(DailyPrice.objects.count(), counts_before["daily_prices"])
        self.assertEqual(DataIngestionLog.objects.count(), counts_before["logs"])

        rendered = str(result)
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
