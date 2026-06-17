from datetime import timedelta
from decimal import Decimal
from io import StringIO
import os
import tempfile
from unittest.mock import patch

import pandas as pd
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from data_pipeline.dataclasses import IngestionReport
from holdings.models import UserHolding
from stocks.models import Stock
from stocks.services.collectors.financial_snapshot_collector import FinancialSnapshotCollectionReport
from stocks.services.stock_quality_service import StockQualityResult

from .models import DailyPrice, InvestorFlow, MarketIndex, StockDataCollectionStatus
from .services.collectors.market_index_collector import collect_market_indices
from .services.collectors.investor_flow_collector import collect_investor_flows
from .services.collectors.price_collector import collect_daily_prices
from .services.importers.investor_flow_import_service import import_investor_flows_from_csv
from .services.market_regime_service import evaluate_market_regime
from .services.market_service import calculate_market_score, get_market_context
from .services.price_service import extract_close_prices, get_latest_price, get_recent_prices
from .services.source_resolution import get_market_index_targets, resolve_stock_yfinance_symbol

User = get_user_model()


class MarketdataModelTests(APITestCase):
    def setUp(self):
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)

    def test_daily_price_unique_by_stock_and_date(self):
        DailyPrice.objects.create(
            stock=self.stock,
            date="2026-04-28",
            open_price=Decimal("69000.00"),
            high_price=Decimal("70000.00"),
            low_price=Decimal("68000.00"),
            close_price=Decimal("69500.00"),
            volume=12345678,
        )

        with self.assertRaises(IntegrityError):
            DailyPrice.objects.create(
                stock=self.stock,
                date="2026-04-28",
                open_price=Decimal("69000.00"),
                high_price=Decimal("70000.00"),
                low_price=Decimal("68000.00"),
                close_price=Decimal("69500.00"),
                volume=12345678,
            )

    def test_latest_daily_price_can_be_queried(self):
        DailyPrice.objects.create(
            stock=self.stock,
            date="2026-04-27",
            open_price=Decimal("68000.00"),
            high_price=Decimal("69000.00"),
            low_price=Decimal("67000.00"),
            close_price=Decimal("68500.00"),
            volume=100,
        )
        latest = DailyPrice.objects.create(
            stock=self.stock,
            date="2026-04-28",
            open_price=Decimal("69000.00"),
            high_price=Decimal("70000.00"),
            low_price=Decimal("68000.00"),
            close_price=Decimal("69500.00"),
            volume=200,
        )

        self.assertEqual(DailyPrice.objects.filter(stock=self.stock).first(), latest)

    def test_investor_flow_unique_and_negative_values_allowed(self):
        flow = InvestorFlow.objects.create(
            stock=self.stock,
            date="2026-04-28",
            foreign_net_buy=-1000,
            institution_net_buy=500,
            individual_net_buy=500,
            program_net_buy=-100,
        )

        self.assertEqual(flow.foreign_net_buy, -1000)

        with self.assertRaises(IntegrityError):
            InvestorFlow.objects.create(stock=self.stock, date="2026-04-28")

    def test_collection_status_is_unique_per_stock_and_type(self):
        StockDataCollectionStatus.objects.create(
            stock=self.stock,
            data_type=StockDataCollectionStatus.TYPE_INVESTOR_FLOW,
            status=StockDataCollectionStatus.STATUS_SUCCESS,
            source="test",
        )

        with self.assertRaises(IntegrityError):
            StockDataCollectionStatus.objects.create(
                stock=self.stock,
                data_type=StockDataCollectionStatus.TYPE_INVESTOR_FLOW,
                status=StockDataCollectionStatus.STATUS_ERROR,
                source="test",
            )


class MarketdataApiSmokeTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="alice", password="pw12345")
        self.client.force_authenticate(self.user)
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)
        DailyPrice.objects.create(
            stock=self.stock,
            date="2026-04-28",
            open_price=Decimal("69000.00"),
            high_price=Decimal("70000.00"),
            low_price=Decimal("68000.00"),
            close_price=Decimal("69500.00"),
            volume=12345678,
        )
        InvestorFlow.objects.create(stock=self.stock, date="2026-04-28")
        MarketIndex.objects.create(
            code="KOSPI",
            name="KOSPI",
            date="2026-04-28",
            close_value=Decimal("2750.1200"),
            change_rate=Decimal("1.2500"),
        )

    def test_marketdata_smoke_endpoints(self):
        response_daily = self.client.get("/api/marketdata/daily-prices/")
        response_flow = self.client.get("/api/marketdata/investor-flows/")
        response_index = self.client.get("/api/marketdata/market-indices/")

        self.assertEqual(response_daily.status_code, status.HTTP_200_OK)
        self.assertEqual(response_flow.status_code, status.HTTP_200_OK)
        self.assertEqual(response_index.status_code, status.HTTP_200_OK)


class MarketdataApiPermissionTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="market_user", password="pw12345")
        self.staff_user = User.objects.create_user(username="market_admin", password="pw12345", is_staff=True)
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)
        self.daily_price = DailyPrice.objects.create(
            stock=self.stock,
            date="2026-04-28",
            open_price=Decimal("69000.00"),
            high_price=Decimal("70000.00"),
            low_price=Decimal("68000.00"),
            close_price=Decimal("69500.00"),
            volume=12345678,
        )
        self.investor_flow = InvestorFlow.objects.create(
            stock=self.stock,
            date="2026-04-28",
            foreign_net_buy=1000,
            institution_net_buy=2000,
            individual_net_buy=-3000,
            program_net_buy=500,
        )
        self.market_index = MarketIndex.objects.create(
            code="KOSPI",
            name="KOSPI",
            date="2026-04-28",
            close_value=Decimal("2750.1200"),
            change_rate=Decimal("1.2500"),
        )

    def test_authenticated_user_can_list_marketdata(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/api/marketdata/daily-prices/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_non_staff_user_cannot_create_marketdata(self):
        self.client.force_authenticate(self.user)

        daily_response = self.client.post(
            "/api/marketdata/daily-prices/",
            {
                "stock": self.stock.id,
                "date": "2026-04-29",
                "open_price": "70000.00",
                "high_price": "71000.00",
                "low_price": "69000.00",
                "close_price": "70500.00",
                "volume": 1000,
            },
            format="json",
        )
        flow_response = self.client.post(
            "/api/marketdata/investor-flows/",
            {
                "stock": self.stock.id,
                "date": "2026-04-29",
                "foreign_net_buy": 100,
                "institution_net_buy": 200,
                "individual_net_buy": -300,
                "program_net_buy": 0,
            },
            format="json",
        )
        index_response = self.client.post(
            "/api/marketdata/market-indices/",
            {
                "code": "NASDAQ",
                "name": "NASDAQ",
                "date": "2026-04-29",
                "close_value": "15000.1000",
                "change_rate": "0.1000",
            },
            format="json",
        )

        self.assertEqual(daily_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(flow_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(index_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_user_can_create_daily_price(self):
        self.client.force_authenticate(self.staff_user)

        response = self.client.post(
            "/api/marketdata/daily-prices/",
            {
                "stock": self.stock.id,
                "date": "2026-04-29",
                "open_price": "70000.00",
                "high_price": "71000.00",
                "low_price": "69000.00",
                "close_price": "70500.00",
                "volume": 1000,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(DailyPrice.objects.filter(stock=self.stock, date="2026-04-29").exists())


class MarketdataServiceTests(APITestCase):
    def setUp(self):
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)

    def test_price_service_returns_latest_and_recent_prices(self):
        older = DailyPrice.objects.create(
            stock=self.stock,
            date="2026-04-27",
            open_price=Decimal("68000.00"),
            high_price=Decimal("69000.00"),
            low_price=Decimal("67000.00"),
            close_price=Decimal("68500.00"),
            volume=100,
        )
        latest = DailyPrice.objects.create(
            stock=self.stock,
            date="2026-04-28",
            open_price=Decimal("69000.00"),
            high_price=Decimal("70000.00"),
            low_price=Decimal("68000.00"),
            close_price=Decimal("69500.00"),
            volume=200,
        )

        recent_prices = get_recent_prices(self.stock, limit=2, ascending=True)

        self.assertEqual(get_latest_price(self.stock), latest)
        self.assertEqual(recent_prices, [older, latest])
        self.assertEqual(extract_close_prices(recent_prices), [Decimal("68500.00"), Decimal("69500.00")])

    def test_market_context_uses_stock_market_mapping(self):
        for index in range(25):
            MarketIndex.objects.create(
                code="KOSPI",
                name="KOSPI",
                date=f"2026-03-{index + 1:02d}",
                close_value=Decimal(str(2500 + index)),
                change_rate=Decimal("0.5000"),
            )

        context = get_market_context(self.stock)

        self.assertEqual(context["market_code"], "KOSPI")
        self.assertEqual(len(context["market_index_rows"]), 25)

    def test_market_score_penalizes_market_crash(self):
        market_rows = []
        for index in range(25):
            row = MarketIndex.objects.create(
                code="KOSPI",
                name="KOSPI",
                date=f"2026-04-{index + 1:02d}",
                close_value=Decimal(str(2500 - (index * 15))),
                change_rate=Decimal("-3.0000") if index == 24 else Decimal("-1.0000"),
            )
            market_rows.append(row)

        result = calculate_market_score(self.stock, market_rows)

        self.assertLess(result["score"], 0)
        self.assertTrue(any("급락" in reason for reason in result["reasons"]))


class MarketRegimeServiceTests(APITestCase):
    def _create_market_series(self, code, values):
        start = timezone.localdate() - timedelta(days=len(values) - 1)
        for offset, close_value in enumerate(values):
            MarketIndex.objects.create(
                code=code,
                name=code,
                date=start + timedelta(days=offset),
                close_value=Decimal(str(close_value)),
                change_rate=Decimal("0.5000"),
            )

    def test_market_regime_returns_risk_on_for_uptrend(self):
        self._create_market_series("KOSPI", [2400 + (index * 8) for index in range(60)])

        result = evaluate_market_regime()

        self.assertEqual(result.regime, "risk_on")

    def test_market_regime_returns_risk_off_for_crash(self):
        self._create_market_series("KOSPI", [2400 - (index * 20) for index in range(60)])

        result = evaluate_market_regime()

        self.assertIn(result.regime, {"risk_off", "capitulation"})

    def test_market_regime_returns_unknown_when_data_is_insufficient(self):
        self._create_market_series("KOSPI", [2400 + index for index in range(10)])

        result = evaluate_market_regime()

        self.assertEqual(result.regime, "unknown")
        self.assertEqual(result.grade_cap, "B")


class MarketdataSourceResolutionTests(APITestCase):
    def test_resolve_stock_yfinance_symbol_uses_market_suffix(self):
        stock = Stock(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)

        result = resolve_stock_yfinance_symbol(stock)

        self.assertEqual(result.symbol, "005930.KS")
        self.assertEqual(result.source, "stock_code_market")

    def test_market_index_targets_support_aliases(self):
        targets = get_market_index_targets(codes=["S&P500", "USDKRW"])

        self.assertEqual([target.code for target in targets], ["SP500", "USDKRW"])


class PriceCollectorTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="collector", password="pw12345")
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)
        UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("70000.00"),
            quantity=10,
        )

    def _build_price_frame(self):
        index = pd.to_datetime(["2026-04-01", "2026-04-02", "2026-04-03"])
        return pd.DataFrame(
            {
                "Open": [100, 110, 120],
                "High": [110, 120, 130],
                "Low": [95, 105, 115],
                "Close": [105, 115, 125],
                "Volume": [1000, 1200, 1400],
            },
            index=index,
        )

    @patch("marketdata.services.collectors.price_collector.fetch_history_frame")
    def test_collect_daily_prices_upserts_rows_for_active_holdings(self, mock_fetch_history_frame):
        mock_fetch_history_frame.return_value = self._build_price_frame()

        report = collect_daily_prices(days=3)

        self.assertEqual(report.target_count, 1)
        self.assertEqual(report.created_rows, 3)
        self.assertEqual(DailyPrice.objects.filter(stock=self.stock).count(), 3)
        latest = DailyPrice.objects.filter(stock=self.stock).order_by("-date").first()
        self.assertEqual(latest.close_price, Decimal("125.00"))
        self.assertEqual(latest.change_rate, Decimal("8.6957"))

    @patch("marketdata.services.collectors.price_collector.fetch_history_frame")
    def test_collect_daily_prices_dry_run_does_not_persist(self, mock_fetch_history_frame):
        mock_fetch_history_frame.return_value = self._build_price_frame()

        report = collect_daily_prices(days=3, dry_run=True)

        self.assertEqual(report.created_rows, 3)
        self.assertEqual(DailyPrice.objects.count(), 0)


class InvestorFlowCollectorTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="flow_collector", password="pw12345")
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)
        UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("70000.00"),
            quantity=10,
        )

    def _build_flow_frame(self):
        index = pd.to_datetime(["2026-04-01", "2026-04-02"])
        return pd.DataFrame(
            {
                "기관합계": [1200, 800],
                "개인": [-2000, -1000],
                "외국인합계": [700, 100],
            },
            index=index,
        )

    @patch("marketdata.services.collectors.investor_flow_collector._fetch_investor_flow_frame")
    def test_collect_investor_flows_upserts_rows_and_records_success_status(self, mock_fetch_investor_flow_frame):
        mock_fetch_investor_flow_frame.return_value = self._build_flow_frame()

        report = collect_investor_flows(days=2)

        self.assertEqual(report.target_count, 1)
        self.assertEqual(report.created_rows, 2)
        latest = InvestorFlow.objects.filter(stock=self.stock).order_by("-date").first()
        self.assertEqual(latest.foreign_net_buy, 100)
        self.assertEqual(latest.institution_net_buy, 800)
        status_obj = StockDataCollectionStatus.objects.get(
            stock=self.stock,
            data_type=StockDataCollectionStatus.TYPE_INVESTOR_FLOW,
        )
        self.assertEqual(status_obj.status, StockDataCollectionStatus.STATUS_SUCCESS)
        self.assertEqual(status_obj.last_row_count, 2)

    @patch("marketdata.services.collectors.investor_flow_collector._fetch_investor_flow_frame")
    def test_collect_investor_flows_marks_empty_status_when_source_returns_no_rows(self, mock_fetch_investor_flow_frame):
        mock_fetch_investor_flow_frame.return_value = pd.DataFrame()

        report = collect_investor_flows(days=2)

        self.assertEqual(report.empty_targets, 1)
        status_obj = StockDataCollectionStatus.objects.get(
            stock=self.stock,
            data_type=StockDataCollectionStatus.TYPE_INVESTOR_FLOW,
        )
        self.assertEqual(status_obj.status, StockDataCollectionStatus.STATUS_EMPTY)
        self.assertEqual(status_obj.last_row_count, 0)


class MarketIndexCollectorTests(APITestCase):
    def _build_index_frame(self):
        index = pd.to_datetime(["2026-04-01", "2026-04-02", "2026-04-03"])
        return pd.DataFrame(
            {
                "Close": [2500, 2525, 2550],
            },
            index=index,
        )

    @patch("marketdata.services.collectors.market_index_collector.fetch_history_frame")
    def test_collect_market_indices_upserts_rows(self, mock_fetch_history_frame):
        mock_fetch_history_frame.return_value = self._build_index_frame()

        report = collect_market_indices(codes=["KOSPI"], days=3)

        self.assertEqual(report.target_count, 1)
        self.assertEqual(report.created_rows, 3)
        self.assertEqual(MarketIndex.objects.filter(code="KOSPI").count(), 3)
        latest = MarketIndex.objects.filter(code="KOSPI").order_by("-date").first()
        self.assertEqual(latest.close_value, Decimal("2550.0000"))
        self.assertEqual(latest.change_rate, Decimal("0.9901"))


class MarketdataCommandTests(APITestCase):
    @patch("marketdata.management.commands.collect_daily_prices.ingest_daily_prices")
    def test_collect_daily_prices_command_can_delegate_to_data_pipeline(self, mock_ingest_daily_prices):
        mock_ingest_daily_prices.return_value = IngestionReport(
            job_name="ingest_daily_prices",
            provider="mock",
            target_type="price",
            target_count=1,
            success_count=1,
            failed_count=0,
            created_count=3,
            updated_count=1,
            status="success",
            warnings=["pipeline price warning"],
        )
        output = StringIO()

        call_command(
            "collect_daily_prices",
            "--use-data-pipeline",
            "--provider",
            "mock",
            "--dry-run",
            stdout=output,
        )

        rendered = output.getvalue()
        self.assertIn("daily price collection complete (data pipeline)", rendered)
        self.assertIn("created=3, updated=1", rendered)
        self.assertIn("pipeline price warning", rendered)
        mock_ingest_daily_prices.assert_called_once()

    @patch("marketdata.management.commands.collect_market_indices.ingest_market_indices")
    def test_collect_market_indices_command_can_delegate_to_data_pipeline(self, mock_ingest_market_indices):
        mock_ingest_market_indices.return_value = IngestionReport(
            job_name="ingest_market_indices",
            provider="mock",
            target_type="market",
            target_count=2,
            success_count=2,
            failed_count=0,
            created_count=5,
            updated_count=2,
            status="success",
        )
        output = StringIO()

        call_command(
            "collect_market_indices",
            "--use-data-pipeline",
            "--provider",
            "mock",
            "--dry-run",
            stdout=output,
        )

        self.assertIn("market index collection complete (data pipeline)", output.getvalue())
        mock_ingest_market_indices.assert_called_once()

    @patch("marketdata.management.commands.collect_investor_flows.collect_investor_flows")
    def test_collect_investor_flows_command_emits_summary_log(self, mock_collect_investor_flows):
        from marketdata.services.collectors.investor_flow_collector import InvestorFlowCollectionReport

        mock_collect_investor_flows.return_value = InvestorFlowCollectionReport(
            target_count=1,
            created_rows=2,
            updated_rows=0,
            empty_targets=0,
            skipped_targets=0,
            error_targets=0,
            warnings=[],
        )
        output = StringIO()

        with self.assertLogs("marketdata.management.commands.collect_investor_flows", level="INFO") as logs:
            call_command("collect_investor_flows", "--dry-run", stdout=output)

        rendered = output.getvalue()
        self.assertIn("investor flow auto collection complete", rendered)
        self.assertTrue(any("Investor flow auto collection command started" in message for message in logs.output))
        self.assertTrue(any("Investor flow auto collection command completed" in message for message in logs.output))

    @patch("marketdata.management.commands.collect_investor_flows.ingest_investor_flows")
    def test_collect_investor_flows_command_can_delegate_to_data_pipeline(self, mock_ingest_investor_flows):
        mock_ingest_investor_flows.return_value = IngestionReport(
            job_name="ingest_investor_flows",
            provider="mock",
            target_type="flow",
            target_count=1,
            success_count=1,
            failed_count=0,
            created_count=2,
            updated_count=1,
            status="success",
            warnings=["pipeline flow warning"],
        )
        output = StringIO()

        call_command(
            "collect_investor_flows",
            "--use-data-pipeline",
            "--provider",
            "mock",
            "--dry-run",
            stdout=output,
        )

        rendered = output.getvalue()
        self.assertIn("investor flow auto collection complete (data pipeline)", rendered)
        self.assertIn("pipeline flow warning", rendered)
        mock_ingest_investor_flows.assert_called_once()

    @patch("marketdata.management.commands.refresh_decision_inputs.collect_risk_events")
    @patch("marketdata.management.commands.refresh_decision_inputs.collect_investor_flows")
    @patch("marketdata.management.commands.refresh_decision_inputs.collect_financial_snapshots")
    @patch("marketdata.management.commands.refresh_decision_inputs.collect_market_indices")
    @patch("marketdata.management.commands.refresh_decision_inputs.collect_daily_prices")
    @patch("marketdata.management.commands.refresh_decision_inputs.update_data_quality")
    def test_refresh_decision_inputs_command_prints_stage_summaries_in_legacy_mode(
        self,
        mock_update_data_quality,
        mock_collect_daily_prices,
        mock_collect_market_indices,
        mock_collect_financial_snapshots,
        mock_collect_investor_flows,
        mock_collect_risk_events,
    ):
        from decisions.services.collectors.risk_event_collector import RiskEventCollectionReport
        from marketdata.services.collectors.investor_flow_collector import InvestorFlowCollectionReport
        from marketdata.services.collectors.market_index_collector import MarketIndexCollectionReport
        from marketdata.services.collectors.price_collector import PriceCollectionReport

        mock_collect_daily_prices.return_value = PriceCollectionReport(
            target_count=2,
            created_rows=10,
            updated_rows=5,
            skipped_targets=1,
            warnings=["price warning"],
        )
        mock_collect_market_indices.return_value = MarketIndexCollectionReport(
            target_count=3,
            created_rows=20,
            updated_rows=4,
            skipped_targets=0,
            warnings=["index warning"],
        )
        mock_collect_investor_flows.return_value = InvestorFlowCollectionReport(
            target_count=2,
            created_rows=6,
            updated_rows=1,
            empty_targets=1,
            skipped_targets=0,
            error_targets=0,
            warnings=["flow warning"],
        )
        mock_collect_risk_events.return_value = RiskEventCollectionReport(
            target_count=2,
            created_rows=3,
            updated_rows=2,
            empty_targets=0,
            skipped_targets=1,
            error_targets=1,
            warnings=["risk warning"],
        )
        mock_collect_financial_snapshots.return_value = FinancialSnapshotCollectionReport(
            target_count=2,
            created_rows=2,
            updated_rows=1,
            empty_targets=0,
            skipped_targets=0,
            error_targets=0,
            warnings=["financial warning"],
        )
        mock_update_data_quality.return_value = IngestionReport(
            job_name="update_data_quality",
            provider="internal",
            target_type="quality",
            target_count=2,
            success_count=2,
            failed_count=0,
            status="success",
            warnings=["quality warning"],
        )
        output = StringIO()

        call_command("refresh_decision_inputs", "--legacy", stdout=output)

        rendered = output.getvalue()
        self.assertIn("[APPLY] refresh_decision_inputs complete", rendered)
        self.assertIn("prices: targets=2, created=10, updated=5, skipped=1", rendered)
        self.assertIn("indices: targets=3, created=20, updated=4, skipped=0", rendered)
        self.assertIn("investor_flows: targets=2, created=6, updated=1, empty=1, skipped=0, errors=0", rendered)
        self.assertIn("risk_events: targets=2, created=3, updated=2, empty=0, skipped=1, errors=1", rendered)
        self.assertIn("financial_snapshots: targets=2, created=2, updated=1, empty=0, skipped=0, errors=0", rendered)
        self.assertIn("data_quality: status=success, targets=2, success=2, failed=0", rendered)
        self.assertIn("price warning", rendered)
        self.assertIn("index warning", rendered)
        self.assertIn("flow warning", rendered)
        self.assertIn("risk warning", rendered)
        self.assertIn("financial warning", rendered)
        self.assertIn("quality warning", rendered)
        mock_update_data_quality.assert_called_once_with(stock_codes=None, all_stocks=False)

    @patch("marketdata.management.commands.refresh_decision_inputs.run_daily_pipeline")
    def test_refresh_decision_inputs_uses_data_pipeline_by_default(self, mock_run_daily_pipeline):
        mock_run_daily_pipeline.return_value = {
            "stock_master": IngestionReport(
                job_name="ingest_stock_master",
                provider="mock",
                target_type="stock",
                target_count=3,
                success_count=3,
                failed_count=0,
                created_count=3,
                status="success",
            ),
            "daily_prices": IngestionReport(
                job_name="ingest_daily_prices",
                provider="mock",
                target_type="price",
                target_count=2,
                success_count=2,
                failed_count=0,
                created_count=10,
                updated_count=4,
                status="success",
                warnings=["mock pipeline warning"],
            ),
        }
        output = StringIO()

        call_command(
            "refresh_decision_inputs",
            "--provider",
            "mock",
            "--index-codes",
            "KOSPI",
            "NASDAQ",
            "--skip-investor-flows",
            "--skip-risk-events",
            "--skip-financials",
            "--dry-run",
            stdout=output,
        )

        rendered = output.getvalue()
        self.assertIn("[DRY-RUN] refresh_decision_inputs complete (data pipeline)", rendered)
        self.assertIn("stock_master: status=success, targets=3, success=3, failed=0, created=3, updated=0", rendered)
        self.assertIn("daily_prices: status=success, targets=2, success=2, failed=0, created=10, updated=4", rendered)
        self.assertIn("mock pipeline warning", rendered)
        mock_run_daily_pipeline.assert_called_once_with(
            provider_name="mock",
            stock_codes=None,
            price_days=240,
            investor_flow_days=60,
            market_index_days=240,
            risk_event_days=365,
            financial_years=2,
            market_index_codes=["KOSPI", "NASDAQ"],
            all_stocks=False,
            skip_investor_flows=True,
            skip_risk_events=True,
            skip_financial_data=True,
            dry_run=True,
        )


class InvestorFlowImportTests(APITestCase):
    def setUp(self):
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)

    def _write_csv(self, content):
        temp_file = tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", suffix=".csv", delete=False)
        temp_file.write(content)
        temp_file.close()
        self.addCleanup(lambda: os.path.exists(temp_file.name) and os.unlink(temp_file.name))
        return temp_file.name

    def test_import_investor_flows_from_csv_upserts_rows(self):
        file_path = self._write_csv(
            "stock_code,date,foreign_net_buy,institution_net_buy,individual_net_buy,program_net_buy\n"
            "005930,2026-04-28,1000,2000,-3000,500\n"
        )

        report = import_investor_flows_from_csv(file_path)

        self.assertEqual(report.created_count, 1)
        flow = InvestorFlow.objects.get(stock=self.stock, date="2026-04-28")
        self.assertEqual(flow.foreign_net_buy, 1000)
        self.assertEqual(flow.program_net_buy, 500)

        update_file = self._write_csv(
            "stock_code,date,foreign_net_buy,institution_net_buy,individual_net_buy,program_net_buy\n"
            "005930,2026-04-28,1500,2500,-4000,700\n"
        )
        report = import_investor_flows_from_csv(update_file)

        self.assertEqual(report.updated_count, 1)
        flow.refresh_from_db()
        self.assertEqual(flow.foreign_net_buy, 1500)
        self.assertEqual(flow.program_net_buy, 700)
        self.assertEqual(InvestorFlow.objects.count(), 1)

    def test_import_investor_flows_command_supports_skip_missing_stocks(self):
        file_path = self._write_csv(
            "stock_code,date,foreign_net_buy,institution_net_buy,individual_net_buy,program_net_buy\n"
            "999999,2026-04-28,1000,2000,-3000,500\n"
        )
        output = StringIO()

        call_command("import_investor_flows", "--file", file_path, "--skip-missing-stocks", stdout=output)

        self.assertEqual(InvestorFlow.objects.count(), 0)
        rendered = output.getvalue()
        self.assertIn("skipped=1", rendered)
        self.assertIn("999999", rendered)


class DataQualityAuditCommandTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="auditor", password="pw12345")
        self.active_stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)
        self.inactive_stock = Stock.objects.create(code="000660", name="SK하이닉스", market=Stock.MARKET_KOSPI)
        self.active_holding = UserHolding.objects.create(
            user=self.user,
            stock=self.active_stock,
            average_price=Decimal("70000.00"),
            quantity=10,
            is_active=True,
        )
        UserHolding.objects.create(
            user=self.user,
            stock=self.inactive_stock,
            average_price=Decimal("0.00"),
            quantity=0,
            is_active=False,
        )

    @patch("marketdata.management.commands.audit_decision_input_quality.evaluate_stock_quality")
    @patch("marketdata.management.commands.audit_decision_input_quality.evaluate_data_quality")
    def test_audit_command_reports_only_active_holdings(
        self,
        mock_evaluate_data_quality,
        mock_evaluate_stock_quality,
    ):
        from decisions.services.data_quality_service import DataQualityResult

        StockDataCollectionStatus.objects.create(
            stock=self.active_stock,
            data_type=StockDataCollectionStatus.TYPE_FINANCIAL_SNAPSHOT,
            status=StockDataCollectionStatus.STATUS_SUCCESS,
            source="test",
        )
        mock_evaluate_data_quality.return_value = DataQualityResult(
            overall_score=Decimal("0.8500"),
            label="높음",
            price_data_days=120,
            latest_price_age_days=0,
            investor_flow_days=20,
            market_data_available=True,
            risk_event_available=True,
            warnings=[],
            details={
                "investor_flow_collection_status": StockDataCollectionStatus.STATUS_SUCCESS,
                "risk_event_collection_status": StockDataCollectionStatus.STATUS_EMPTY,
            },
        )
        mock_evaluate_stock_quality.return_value = StockQualityResult("Q2", Decimal("0.8000"), None, [], [], {})
        output = StringIO()

        call_command("audit_decision_input_quality", stdout=output)

        rendered = output.getvalue()
        self.assertIn("auditor:005930 삼성전자", rendered)
        self.assertNotIn("SK하이닉스", rendered)
        self.assertIn("active_holdings=1", rendered)
        self.assertIn("flow_sync=success", rendered)
        self.assertIn("risk_sync=empty", rendered)
        self.assertIn("financial_sync=success", rendered)
        self.assertIn("stock_quality=Q2", rendered)

    @patch("marketdata.management.commands.audit_decision_input_quality.evaluate_stock_quality")
    @patch("marketdata.management.commands.audit_decision_input_quality.evaluate_data_quality")
    def test_audit_command_only_missing_filters_to_holdings_with_missing_inputs(
        self,
        mock_evaluate_data_quality,
        mock_evaluate_stock_quality,
    ):
        from decisions.services.data_quality_service import DataQualityResult

        mock_evaluate_data_quality.return_value = DataQualityResult(
            overall_score=Decimal("0.3500"),
            label="매우 낮음",
            price_data_days=120,
            latest_price_age_days=0,
            investor_flow_days=0,
            market_data_available=True,
            risk_event_available=False,
            warnings=["수급 자동 수집 이력이 없어 수급 판단은 제한적입니다."],
            details={
                "investor_flow_collection_status": StockDataCollectionStatus.STATUS_NEVER,
                "risk_event_collection_status": StockDataCollectionStatus.STATUS_ERROR,
            },
        )
        mock_evaluate_stock_quality.return_value = StockQualityResult(
            "UNKNOWN",
            Decimal("0.5000"),
            "B",
            [],
            ["재무 품질 데이터가 없어 품질 평가는 제한적입니다."],
            {},
        )
        output = StringIO()

        call_command("audit_decision_input_quality", "--only-missing", stdout=output)

        rendered = output.getvalue()
        self.assertIn("auditor:005930 삼성전자", rendered)
        self.assertIn("missing_flow_sync=1", rendered)
        self.assertIn("missing_risk_sync=1", rendered)
        self.assertIn("missing_financial_sync=1", rendered)
        self.assertIn("flow_sync=never", rendered)
        self.assertIn("risk_sync=error", rendered)
        self.assertIn("financial_sync=never", rendered)
        self.assertIn("stock_quality=UNKNOWN", rendered)
