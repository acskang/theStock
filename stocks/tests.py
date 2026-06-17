from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.db import IntegrityError
from django.core.management import call_command
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from holdings.models import UserHolding
from marketdata.models import StockDataCollectionStatus
from .models import FinancialSnapshot, Stock
from .services.collectors.financial_snapshot_collector import collect_financial_snapshots
from .services.stock_quality_service import evaluate_stock_quality

User = get_user_model()


class StockModelTests(TestCase):
    def test_stock_can_be_created(self):
        stock = Stock.objects.create(
            code="005930",
            name="삼성전자",
            market=Stock.MARKET_KOSPI,
            sector="반도체",
        )

        self.assertEqual(stock.code, "005930")
        self.assertTrue(stock.is_active)

    def test_stock_code_must_be_unique(self):
        Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)

        with self.assertRaises(IntegrityError):
            Stock.objects.create(code="005930", name="삼성전자우", market=Stock.MARKET_KOSPI)

    def test_stock_string_representation(self):
        stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)

        self.assertEqual(str(stock), "005930 삼성전자")

    def test_financial_snapshot_can_be_created(self):
        stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)

        snapshot = FinancialSnapshot.objects.create(
            stock=stock,
            fiscal_year=2025,
            period_type=FinancialSnapshot.PERIOD_Q4,
            revenue=Decimal("300000000000.00"),
            operating_profit=Decimal("40000000000.00"),
            net_income=Decimal("35000000000.00"),
            operating_cash_flow=Decimal("45000000000.00"),
            debt_ratio=Decimal("32.50"),
            current_ratio=Decimal("210.00"),
            equity=Decimal("350000000000.00"),
            capital_impairment_rate=Decimal("0.00"),
            roe=Decimal("11.20"),
            per=Decimal("14.5000"),
            pbr=Decimal("1.2000"),
            source="manual",
            source_key="manual:005930:2025:Q4",
        )

        self.assertEqual(snapshot.stock, stock)
        self.assertEqual(snapshot.period_type, FinancialSnapshot.PERIOD_Q4)
        self.assertEqual(snapshot.source, "manual")

    def test_financial_snapshot_period_must_be_unique_per_stock_and_year(self):
        stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)
        FinancialSnapshot.objects.create(
            stock=stock,
            fiscal_year=2025,
            period_type=FinancialSnapshot.PERIOD_Q4,
        )

        with self.assertRaises(IntegrityError):
            FinancialSnapshot.objects.create(
                stock=stock,
                fiscal_year=2025,
                period_type=FinancialSnapshot.PERIOD_Q4,
            )

    def test_financial_snapshot_source_key_must_be_unique_when_present(self):
        first_stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)
        second_stock = Stock.objects.create(code="000660", name="SK하이닉스", market=Stock.MARKET_KOSPI)

        FinancialSnapshot.objects.create(
            stock=first_stock,
            fiscal_year=2025,
            period_type=FinancialSnapshot.PERIOD_Q4,
            source_key="opendart:001",
        )

        with self.assertRaises(IntegrityError):
            FinancialSnapshot.objects.create(
                stock=second_stock,
                fiscal_year=2025,
                period_type=FinancialSnapshot.PERIOD_Q4,
                source_key="opendart:001",
            )

    def test_financial_snapshot_string_representation(self):
        stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)
        snapshot = FinancialSnapshot.objects.create(
            stock=stock,
            fiscal_year=2025,
            period_type=FinancialSnapshot.PERIOD_ANNUAL,
        )

        self.assertEqual(str(snapshot), "005930 2025 ANNUAL")


class StockQualityServiceTests(TestCase):
    def _create_snapshot(self, stock, **overrides):
        payload = {
            "stock": stock,
            "fiscal_year": 2025,
            "period_type": FinancialSnapshot.PERIOD_Q4,
            "revenue": Decimal("1000000000.00"),
            "operating_profit": Decimal("100000000.00"),
            "net_income": Decimal("80000000.00"),
            "operating_cash_flow": Decimal("90000000.00"),
            "debt_ratio": Decimal("80.00"),
            "current_ratio": Decimal("180.00"),
            "equity": Decimal("500000000.00"),
            "capital_impairment_rate": Decimal("0.00"),
            "roe": Decimal("12.00"),
            "source": "manual",
            "source_key": f"manual:{stock.code}:{overrides.get('fiscal_year', 2025)}:{overrides.get('period_type', FinancialSnapshot.PERIOD_Q4)}",
        }
        payload.update(overrides)
        return FinancialSnapshot.objects.create(**payload)

    def test_stock_quality_returns_unknown_when_financial_data_is_unavailable(self):
        stock = Stock.objects.create(code="123456", name="품질", market=Stock.MARKET_KOSPI)

        result = evaluate_stock_quality(stock)

        self.assertEqual(result.quality_grade, "UNKNOWN")
        self.assertEqual(result.grade_cap, "B")
        self.assertTrue(result.warnings)

    def test_stock_quality_returns_q5_for_inactive_stock(self):
        stock = Stock.objects.create(code="654321", name="비활성", market=Stock.MARKET_KOSPI, is_active=False)

        result = evaluate_stock_quality(stock)

        self.assertEqual(result.quality_grade, "Q5")
        self.assertEqual(result.grade_cap, "D")

    def test_stock_quality_returns_unknown_for_etf(self):
        stock = Stock.objects.create(code="069500", name="KODEX 200", market=Stock.MARKET_ETF)

        result = evaluate_stock_quality(stock)

        self.assertEqual(result.quality_grade, "UNKNOWN")
        self.assertEqual(result.grade_cap, "B")
        self.assertTrue(any("ETF/ETN" in warning for warning in result.warnings))

    def test_stock_quality_returns_q1_for_strong_financials(self):
        stock = Stock.objects.create(code="111111", name="우량", market=Stock.MARKET_KOSPI)
        self._create_snapshot(
            stock,
            fiscal_year=2025,
            period_type=FinancialSnapshot.PERIOD_Q4,
            source_key="manual:111111:2025:Q4",
        )
        self._create_snapshot(
            stock,
            fiscal_year=2025,
            period_type=FinancialSnapshot.PERIOD_Q3,
            source_key="manual:111111:2025:Q3",
        )

        result = evaluate_stock_quality(stock)

        self.assertEqual(result.quality_grade, "Q1")
        self.assertIsNone(result.grade_cap)

    def test_stock_quality_returns_q3_for_multiple_weak_signals(self):
        stock = Stock.objects.create(code="222222", name="취약", market=Stock.MARKET_KOSPI)
        self._create_snapshot(
            stock,
            operating_profit=Decimal("-1000.00"),
            net_income=Decimal("100.00"),
            operating_cash_flow=Decimal("50.00"),
            debt_ratio=Decimal("190.00"),
            current_ratio=Decimal("150.00"),
            roe=Decimal("2.00"),
            source_key="manual:222222:2025:Q4",
        )

        result = evaluate_stock_quality(stock)

        self.assertEqual(result.quality_grade, "Q3")
        self.assertEqual(result.grade_cap, "B")
        self.assertTrue(result.blockers)

    def test_stock_quality_returns_q4_for_repeated_losses_and_high_debt(self):
        stock = Stock.objects.create(code="333333", name="위험", market=Stock.MARKET_KOSPI)
        self._create_snapshot(
            stock,
            fiscal_year=2025,
            period_type=FinancialSnapshot.PERIOD_Q4,
            operating_profit=Decimal("-1000.00"),
            net_income=Decimal("-800.00"),
            operating_cash_flow=Decimal("-700.00"),
            debt_ratio=Decimal("320.00"),
            current_ratio=Decimal("90.00"),
            roe=Decimal("-10.00"),
            source_key="manual:333333:2025:Q4",
        )
        self._create_snapshot(
            stock,
            fiscal_year=2025,
            period_type=FinancialSnapshot.PERIOD_Q3,
            operating_profit=Decimal("-1200.00"),
            net_income=Decimal("-900.00"),
            operating_cash_flow=Decimal("-750.00"),
            debt_ratio=Decimal("310.00"),
            current_ratio=Decimal("95.00"),
            roe=Decimal("-9.00"),
            source_key="manual:333333:2025:Q3",
        )

        result = evaluate_stock_quality(stock)

        self.assertEqual(result.quality_grade, "Q4")
        self.assertEqual(result.grade_cap, "C")
        self.assertTrue(result.blockers)

    def test_stock_quality_returns_q5_for_negative_equity(self):
        stock = Stock.objects.create(code="444444", name="자본잠식", market=Stock.MARKET_KOSPI)
        self._create_snapshot(
            stock,
            equity=Decimal("-100.00"),
            capital_impairment_rate=Decimal("60.00"),
            source_key="manual:444444:2025:Q4",
        )

        result = evaluate_stock_quality(stock)

        self.assertEqual(result.quality_grade, "Q5")
        self.assertEqual(result.grade_cap, "D")
        self.assertTrue(result.blockers)


class StockApiPermissionTests(APITestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="stock_user", password="pw12345")
        self.staff_user = User.objects.create_user(username="stock_admin", password="pw12345", is_staff=True)
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)

    def test_authenticated_user_can_list_stocks(self):
        self.client.force_authenticate(self.user)

        response = self.client.get("/api/stocks/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_non_staff_user_cannot_create_update_or_delete_stock(self):
        self.client.force_authenticate(self.user)

        create_response = self.client.post(
            "/api/stocks/",
            {
                "code": "000660",
                "name": "SK하이닉스",
                "market": Stock.MARKET_KOSPI,
                "sector": "반도체",
                "is_active": True,
            },
            format="json",
        )
        patch_response = self.client.patch(
            f"/api/stocks/{self.stock.id}/",
            {"sector": "전자"},
            format="json",
        )
        delete_response = self.client.delete(f"/api/stocks/{self.stock.id}/")

        self.assertEqual(create_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(patch_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(delete_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_user_can_create_stock(self):
        self.client.force_authenticate(self.staff_user)

        response = self.client.post(
            "/api/stocks/",
            {
                "code": "000660",
                "name": "SK하이닉스",
                "market": Stock.MARKET_KOSPI,
                "sector": "반도체",
                "is_active": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(Stock.objects.filter(code="000660").exists())


class FinancialSnapshotCollectorTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="financial_collector", password="pw12345")
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)
        UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("70000.00"),
            quantity=10,
            is_active=True,
        )

    def _build_financial_rows(self):
        return [
            {"account_nm": "매출액", "account_id": "ifrs-full_Revenue", "thstrm_amount": "1000", "thstrm_dt": "2025.12.31"},
            {"account_nm": "영업이익", "account_id": "ifrs-full_ProfitLossFromOperatingActivities", "thstrm_amount": "100", "thstrm_dt": "2025.12.31"},
            {"account_nm": "당기순이익", "account_id": "ifrs-full_ProfitLoss", "thstrm_amount": "80", "thstrm_dt": "2025.12.31"},
            {"account_nm": "영업활동으로인한현금흐름", "account_id": "ifrs-full_CashFlowsFromUsedInOperatingActivities", "thstrm_amount": "90", "thstrm_dt": "2025.12.31"},
            {"account_nm": "자본총계", "account_id": "ifrs-full_Equity", "thstrm_amount": "600", "thstrm_dt": "2025.12.31"},
            {"account_nm": "부채총계", "account_id": "ifrs-full_Liabilities", "thstrm_amount": "400", "thstrm_dt": "2025.12.31"},
            {"account_nm": "유동자산", "account_id": "ifrs-full_CurrentAssets", "thstrm_amount": "500", "thstrm_dt": "2025.12.31"},
            {"account_nm": "유동부채", "account_id": "ifrs-full_CurrentLiabilities", "thstrm_amount": "200", "thstrm_dt": "2025.12.31"},
            {"account_nm": "자본금", "account_id": "ifrs-full_IssuedCapital", "thstrm_amount": "600", "thstrm_dt": "2025.12.31"},
        ]

    @patch("stocks.services.collectors.financial_snapshot_collector.fetch_financial_statement_rows")
    @patch("stocks.services.collectors.financial_snapshot_collector.get_dart_corp_code_map")
    def test_collect_financial_snapshots_upserts_rows_and_records_success_status(
        self,
        mock_get_dart_corp_code_map,
        mock_fetch_financial_statement_rows,
    ):
        mock_get_dart_corp_code_map.return_value = {"005930": "00126380"}

        def side_effect(api_key, corp_code, fiscal_year, report_code, fs_div):
            if report_code == "11011" and fs_div == "CFS":
                return self._build_financial_rows()
            return []

        mock_fetch_financial_statement_rows.side_effect = side_effect

        with self.settings(OPENDART_API_KEY="dart-key"):
            report = collect_financial_snapshots(years=1)

        self.assertEqual(report.target_count, 1)
        self.assertEqual(report.created_rows, 1)
        snapshot = FinancialSnapshot.objects.get(stock=self.stock)
        self.assertEqual(snapshot.debt_ratio, Decimal("66.67"))
        self.assertEqual(snapshot.current_ratio, Decimal("250.00"))
        self.assertEqual(snapshot.capital_impairment_rate, Decimal("0.00"))
        status_obj = StockDataCollectionStatus.objects.get(
            stock=self.stock,
            data_type=StockDataCollectionStatus.TYPE_FINANCIAL_SNAPSHOT,
        )
        self.assertEqual(status_obj.status, StockDataCollectionStatus.STATUS_SUCCESS)
        self.assertEqual(status_obj.last_row_count, 1)

    def test_collect_financial_snapshots_marks_error_when_api_key_is_missing(self):
        report = collect_financial_snapshots(years=1)

        self.assertEqual(report.error_targets, 1)
        status_obj = StockDataCollectionStatus.objects.get(
            stock=self.stock,
            data_type=StockDataCollectionStatus.TYPE_FINANCIAL_SNAPSHOT,
        )
        self.assertEqual(status_obj.status, StockDataCollectionStatus.STATUS_ERROR)

    @patch("stocks.management.commands.collect_financial_snapshots.collect_financial_snapshots")
    def test_collect_financial_snapshots_command_emits_summary(self, mock_collect_financial_snapshots):
        from stocks.services.collectors.financial_snapshot_collector import FinancialSnapshotCollectionReport

        mock_collect_financial_snapshots.return_value = FinancialSnapshotCollectionReport(
            target_count=1,
            created_rows=2,
            updated_rows=0,
            skipped_targets=0,
            empty_targets=0,
            error_targets=0,
            warnings=[],
        )
        output = StringIO()

        call_command("collect_financial_snapshots", "--dry-run", stdout=output)

        self.assertIn("financial snapshot auto collection complete", output.getvalue())

    @patch("stocks.management.commands.collect_financial_snapshots.ingest_financial_data")
    def test_collect_financial_snapshots_command_can_delegate_to_data_pipeline(self, mock_ingest_financial_data):
        from data_pipeline.dataclasses import IngestionReport

        mock_ingest_financial_data.return_value = IngestionReport(
            job_name="ingest_financial_data",
            provider="mock",
            target_type="financial",
            target_count=1,
            success_count=1,
            failed_count=0,
            created_count=1,
            updated_count=0,
            status="success",
            warnings=["pipeline financial warning"],
        )
        output = StringIO()

        call_command(
            "collect_financial_snapshots",
            "--use-data-pipeline",
            "--provider",
            "mock",
            "--dry-run",
            stdout=output,
        )

        rendered = output.getvalue()
        self.assertIn("financial snapshot auto collection complete (data pipeline)", rendered)
        self.assertIn("pipeline financial warning", rendered)
        mock_ingest_financial_data.assert_called_once()
