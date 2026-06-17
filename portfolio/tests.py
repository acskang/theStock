from datetime import date
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from data_pipeline.models import DataIngestionLog, DataProviderStatus, DataQualitySnapshot
from decisions.models import AveragingDecision
from holdings.models import UserHolding
from holdings.services.sync_service import sync_all_holdings_for_legacy_user
from marketdata.models import DailyPrice, StockDataCollectionStatus
from portfolio.models import StockSymbol, Transaction
from portfolio.services import (
    aggregate_all_transactions_by_stock,
    build_portfolio_summary,
    build_historical_buy_timing_analysis,
    build_historical_buy_timing_rankings,
)
from stocks.models import Stock

User = get_user_model()


class PortfolioSummaryServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="summary_user", email="summary@example.com", password="pw12345")
        self.other_user = User.objects.create_user(username="other_user", email="other@example.com", password="pw12345")
        self.priced_stock = Stock.objects.create(code="111111", name="가격종목", market=Stock.MARKET_KOSPI)
        self.missing_stock = Stock.objects.create(code="222222", name="가격누락", market=Stock.MARKET_KOSPI)
        self.inactive_stock = Stock.objects.create(code="333333", name="비활성종목", market=Stock.MARKET_KOSDAQ)

        self.priced_holding = UserHolding.objects.create(
            user=self.user,
            stock=self.priced_stock,
            average_price=Decimal("100.00"),
            quantity=10,
            max_additional_budget=Decimal("5000.00"),
            risk_level=UserHolding.RISK_AGGRESSIVE,
        )
        self.missing_price_holding = UserHolding.objects.create(
            user=self.user,
            stock=self.missing_stock,
            average_price=Decimal("50.00"),
            quantity=4,
        )
        self.inactive_holding = UserHolding.objects.create(
            user=self.user,
            stock=self.inactive_stock,
            average_price=Decimal("20.00"),
            quantity=5,
            is_active=False,
        )
        UserHolding.objects.create(
            user=self.other_user,
            stock=self.priced_stock,
            average_price=Decimal("999.00"),
            quantity=99,
        )

        DailyPrice.objects.create(
            stock=self.priced_stock,
            date=date(2026, 1, 2),
            open_price=Decimal("110.00"),
            high_price=Decimal("125.00"),
            low_price=Decimal("105.00"),
            close_price=Decimal("120.00"),
            volume=1000,
        )
        DailyPrice.objects.create(
            stock=self.priced_stock,
            date=date(2026, 1, 3),
            open_price=Decimal("120.00"),
            high_price=Decimal("135.00"),
            low_price=Decimal("115.00"),
            close_price=Decimal("130.00"),
            volume=1200,
        )
        DailyPrice.objects.create(
            stock=self.inactive_stock,
            date=date(2026, 1, 3),
            open_price=Decimal("22.00"),
            high_price=Decimal("27.00"),
            low_price=Decimal("21.00"),
            close_price=Decimal("25.00"),
            volume=100,
        )

    def test_build_portfolio_summary_calculates_active_owner_scoped_summary(self):
        before_counts = {
            "logs": DataIngestionLog.objects.count(),
            "holdings": UserHolding.objects.count(),
            "prices": DailyPrice.objects.count(),
        }

        summary = build_portfolio_summary(self.user)

        self.assertEqual(summary["as_of"], "2026-01-03")
        self.assertEqual(summary["holding_count"], 2)
        self.assertEqual(summary["active_holding_count"], 2)
        self.assertEqual(summary["priced_holding_count"], 1)
        self.assertEqual(summary["missing_price_count"], 1)
        self.assertEqual(summary["totals"]["total_invested_amount_all"], "1200.00")
        self.assertEqual(summary["totals"]["total_invested_amount_priced"], "1000.00")
        self.assertEqual(summary["totals"]["total_market_value_priced"], "1300.00")
        self.assertEqual(summary["totals"]["total_profit_loss_amount_priced"], "300.00")
        self.assertEqual(summary["totals"]["total_profit_loss_rate_priced"], "30.00")
        self.assertIn("1 holdings have no latest DailyPrice", summary["warnings"][0])

        priced = summary["holdings"][0]
        self.assertEqual(priced["holding_id"], self.priced_holding.id)
        self.assertEqual(priced["stock"]["code"], self.priced_stock.code)
        self.assertEqual(priced["stock"]["name"], self.priced_stock.name)
        self.assertEqual(priced["stock"]["market"], self.priced_stock.market)
        self.assertEqual(priced["quantity"], 10)
        self.assertEqual(priced["average_price"], "100.00")
        self.assertEqual(priced["latest_price"], "130.00")
        self.assertEqual(priced["latest_price_date"], "2026-01-03")
        self.assertEqual(priced["invested_amount"], "1000.00")
        self.assertEqual(priced["market_value"], "1300.00")
        self.assertEqual(priced["profit_loss_amount"], "300.00")
        self.assertEqual(priced["profit_loss_rate"], "30.00")
        self.assertEqual(priced["risk_level"], UserHolding.RISK_AGGRESSIVE)
        self.assertEqual(priced["max_additional_budget"], "5000.00")
        self.assertTrue(priced["is_active"])
        self.assertEqual(priced["price_status"], "priced")

        missing = summary["holdings"][1]
        self.assertEqual(missing["stock"]["code"], self.missing_stock.code)
        self.assertIsNone(missing["latest_price"])
        self.assertIsNone(missing["market_value"])
        self.assertIsNone(missing["profit_loss_amount"])
        self.assertIsNone(missing["profit_loss_rate"])
        self.assertEqual(missing["price_status"], "missing_daily_price")

        self.assertEqual(DataIngestionLog.objects.count(), before_counts["logs"])
        self.assertEqual(UserHolding.objects.count(), before_counts["holdings"])
        self.assertEqual(DailyPrice.objects.count(), before_counts["prices"])

    def test_build_portfolio_summary_can_include_inactive_holdings(self):
        summary = build_portfolio_summary(self.user, include_inactive=True)

        self.assertEqual(summary["holding_count"], 3)
        self.assertEqual(summary["active_holding_count"], 2)
        self.assertEqual(summary["priced_holding_count"], 2)
        self.assertEqual(summary["missing_price_count"], 1)
        self.assertEqual(summary["totals"]["total_invested_amount_all"], "1300.00")
        self.assertEqual(summary["totals"]["total_invested_amount_priced"], "1100.00")
        self.assertEqual(summary["totals"]["total_market_value_priced"], "1425.00")
        self.assertEqual(summary["totals"]["total_profit_loss_amount_priced"], "325.00")
        self.assertEqual(summary["totals"]["total_profit_loss_rate_priced"], "29.55")

        inactive = [item for item in summary["holdings"] if item["stock"]["code"] == self.inactive_stock.code][0]
        self.assertFalse(inactive["is_active"])
        self.assertEqual(inactive["price_status"], "priced")

    def test_build_portfolio_summary_returns_empty_summary_for_user_without_holdings(self):
        empty_user = User.objects.create_user(username="empty_user", email="empty@example.com", password="pw12345")

        summary = build_portfolio_summary(empty_user)

        self.assertIsNone(summary["as_of"])
        self.assertEqual(summary["holding_count"], 0)
        self.assertEqual(summary["active_holding_count"], 0)
        self.assertEqual(summary["priced_holding_count"], 0)
        self.assertEqual(summary["missing_price_count"], 0)
        self.assertEqual(summary["totals"]["total_invested_amount_all"], "0.00")
        self.assertEqual(summary["totals"]["total_invested_amount_priced"], "0.00")
        self.assertEqual(summary["totals"]["total_market_value_priced"], "0.00")
        self.assertEqual(summary["totals"]["total_profit_loss_amount_priced"], "0.00")
        self.assertIsNone(summary["totals"]["total_profit_loss_rate_priced"])
        self.assertEqual(summary["holdings"], [])
        self.assertIn("No holdings are available", summary["warnings"][0])

    def test_build_portfolio_summary_rejects_missing_user(self):
        with self.assertRaises(ValueError):
            build_portfolio_summary(None)

    def test_build_portfolio_summary_excludes_sensitive_identity_and_account_keys(self):
        summary = build_portfolio_summary(self.user, include_inactive=True)
        holding_ids = [item["holding_id"] for item in summary["holdings"]]
        self.assertIn(self.priced_holding.id, holding_ids)
        serialized = str(summary).lower()

        forbidden_tokens = [
            "summary_user",
            "summary@example.com",
            "other_user",
            "other@example.com",
            "user_id",
            "username",
            "email",
            "accountno",
            "accountseq",
            "x-tossinvest-account",
            "access_token",
            "authorization",
            "raw_response",
            "request_body",
        ]
        for token in forbidden_tokens:
            self.assertNotIn(token, serialized)


class PortfolioSummaryAPITests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(username="portfolio_api_user", email="portfolio-api@example.com", password="pw12345")
        self.other_user = User.objects.create_user(username="portfolio_other_user", email="portfolio-other@example.com", password="pw12345")
        self.priced_stock = Stock.objects.create(code="444444", name="API가격종목", market=Stock.MARKET_KOSPI)
        self.missing_stock = Stock.objects.create(code="555555", name="API가격누락", market=Stock.MARKET_KOSPI)
        self.inactive_stock = Stock.objects.create(code="666666", name="API비활성", market=Stock.MARKET_KOSDAQ)
        self.url = reverse("portfolio-summary")

        UserHolding.objects.create(
            user=self.user,
            stock=self.priced_stock,
            average_price=Decimal("200.00"),
            quantity=3,
            max_additional_budget=Decimal("10000.00"),
            risk_level=UserHolding.RISK_NORMAL,
        )
        UserHolding.objects.create(
            user=self.user,
            stock=self.missing_stock,
            average_price=Decimal("70.00"),
            quantity=2,
        )
        UserHolding.objects.create(
            user=self.user,
            stock=self.inactive_stock,
            average_price=Decimal("10.00"),
            quantity=5,
            is_active=False,
        )
        UserHolding.objects.create(
            user=self.other_user,
            stock=self.priced_stock,
            average_price=Decimal("1.00"),
            quantity=1,
        )
        DailyPrice.objects.create(
            stock=self.priced_stock,
            date=date(2026, 2, 1),
            open_price=Decimal("210.00"),
            high_price=Decimal("260.00"),
            low_price=Decimal("205.00"),
            close_price=Decimal("250.00"),
            volume=3000,
        )
        DailyPrice.objects.create(
            stock=self.inactive_stock,
            date=date(2026, 2, 1),
            open_price=Decimal("10.00"),
            high_price=Decimal("12.00"),
            low_price=Decimal("9.00"),
            close_price=Decimal("11.00"),
            volume=100,
        )

    def test_portfolio_summary_api_requires_authentication(self):
        response = self.client.get(self.url)

        self.assertIn(response.status_code, (401, 403))

    def test_portfolio_summary_api_returns_active_owner_scoped_summary(self):
        before_counts = {
            "logs": DataIngestionLog.objects.count(),
            "holdings": UserHolding.objects.count(),
            "prices": DailyPrice.objects.count(),
        }
        self.client.force_authenticate(self.user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["as_of"], "2026-02-01")
        self.assertEqual(response.data["holding_count"], 2)
        self.assertEqual(response.data["active_holding_count"], 2)
        self.assertEqual(response.data["priced_holding_count"], 1)
        self.assertEqual(response.data["missing_price_count"], 1)
        self.assertEqual(response.data["totals"]["total_invested_amount_all"], "740.00")
        self.assertEqual(response.data["totals"]["total_invested_amount_priced"], "600.00")
        self.assertEqual(response.data["totals"]["total_market_value_priced"], "750.00")
        self.assertEqual(response.data["totals"]["total_profit_loss_amount_priced"], "150.00")
        self.assertEqual(response.data["totals"]["total_profit_loss_rate_priced"], "25.00")

        codes = [item["stock"]["code"] for item in response.data["holdings"]]
        self.assertEqual(codes, [self.priced_stock.code, self.missing_stock.code])
        self.assertNotIn(self.inactive_stock.code, codes)

        priced = response.data["holdings"][0]
        self.assertIn("holding_id", priced)
        self.assertEqual(priced["quantity"], 3)
        self.assertEqual(priced["average_price"], "200.00")
        self.assertEqual(priced["latest_price"], "250.00")
        self.assertEqual(priced["invested_amount"], "600.00")
        self.assertEqual(priced["market_value"], "750.00")
        self.assertEqual(priced["profit_loss_amount"], "150.00")
        self.assertEqual(priced["profit_loss_rate"], "25.00")
        self.assertEqual(priced["price_status"], "priced")

        missing = response.data["holdings"][1]
        self.assertIsNone(missing["latest_price"])
        self.assertIsNone(missing["market_value"])
        self.assertEqual(missing["price_status"], "missing_daily_price")

        self.assertEqual(DataIngestionLog.objects.count(), before_counts["logs"])
        self.assertEqual(UserHolding.objects.count(), before_counts["holdings"])
        self.assertEqual(DailyPrice.objects.count(), before_counts["prices"])

    def test_portfolio_summary_api_can_include_inactive_holdings(self):
        self.client.force_authenticate(self.user)

        response = self.client.get(self.url, {"include_inactive": "true"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["holding_count"], 3)
        self.assertEqual(response.data["active_holding_count"], 2)
        self.assertEqual(response.data["priced_holding_count"], 2)
        codes = [item["stock"]["code"] for item in response.data["holdings"]]
        self.assertIn(self.inactive_stock.code, codes)
        inactive = [item for item in response.data["holdings"] if item["stock"]["code"] == self.inactive_stock.code][0]
        self.assertFalse(inactive["is_active"])
        self.assertEqual(inactive["price_status"], "priced")

    def test_portfolio_summary_api_excludes_sensitive_identity_account_and_order_fields(self):
        self.client.force_authenticate(self.user)

        response = self.client.get(self.url, {"include_inactive": "true"})

        self.assertEqual(response.status_code, 200)
        serialized = str(response.data).lower()
        forbidden_tokens = [
            "portfolio_api_user",
            "portfolio-api@example.com",
            "portfolio_other_user",
            "portfolio-other@example.com",
            "user_id",
            "username",
            "email",
            "accountno",
            "accountseq",
            "x-tossinvest-account",
            "access_token",
            "authorization",
            "raw_response",
            "request_body",
            "order",
            "buy_order",
            "sell_order",
        ]
        for token in forbidden_tokens:
            self.assertNotIn(token, serialized)


class PortfolioSummaryPageTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="summary_page_user", email="summary-page@example.com", password="pw12345")
        self.other_user = User.objects.create_user(username="summary_page_other", email="summary-page-other@example.com", password="pw12345")
        self.priced_stock = Stock.objects.create(code="777777", name="화면가격종목", market=Stock.MARKET_KOSPI)
        self.missing_stock = Stock.objects.create(code="888888", name="화면가격누락", market=Stock.MARKET_KOSPI)
        self.inactive_stock = Stock.objects.create(code="999999", name="화면비활성", market=Stock.MARKET_KOSDAQ)
        self.url = reverse("portfolio_summary_page")

        self.priced_holding = UserHolding.objects.create(
            user=self.user,
            stock=self.priced_stock,
            average_price=Decimal("200.00"),
            quantity=3,
            max_additional_budget=Decimal("10000.00"),
            risk_level=UserHolding.RISK_NORMAL,
        )
        UserHolding.objects.create(
            user=self.user,
            stock=self.missing_stock,
            average_price=Decimal("70.00"),
            quantity=2,
        )
        UserHolding.objects.create(
            user=self.user,
            stock=self.inactive_stock,
            average_price=Decimal("10.00"),
            quantity=5,
            is_active=False,
        )
        UserHolding.objects.create(
            user=self.other_user,
            stock=self.priced_stock,
            average_price=Decimal("1.00"),
            quantity=1,
        )
        DailyPrice.objects.create(
            stock=self.priced_stock,
            date=date(2026, 3, 1),
            open_price=Decimal("210.00"),
            high_price=Decimal("260.00"),
            low_price=Decimal("205.00"),
            close_price=Decimal("250.00"),
            volume=3000,
        )
        DailyPrice.objects.create(
            stock=self.inactive_stock,
            date=date(2026, 3, 1),
            open_price=Decimal("10.00"),
            high_price=Decimal("12.00"),
            low_price=Decimal("9.00"),
            close_price=Decimal("11.00"),
            volume=100,
        )

    def test_portfolio_summary_page_requires_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_portfolio_summary_page_renders_owner_scoped_read_only_summary(self):
        self.client.login(username="summary_page_user", password="pw12345")
        before_counts = {
            "logs": DataIngestionLog.objects.count(),
            "holdings": UserHolding.objects.count(),
            "prices": DailyPrice.objects.count(),
            "stocks": Stock.objects.count(),
        }

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "포트폴리오 요약")
        self.assertContains(response, "화면가격종목")
        self.assertContains(response, "777777")
        self.assertContains(response, "750.00")
        self.assertContains(response, "150.00")
        self.assertContains(response, "25.00")
        self.assertContains(response, "최근 일봉 종가")
        self.assertContains(response, "일봉 기준일")
        self.assertContains(response, "실시간 가격이 아닙니다")
        self.assertContains(response, "저장된 DailyPrice의 최근 일봉 종가 기준")
        self.assertContains(response, "비워두면 저장된 최근 일봉 종가를 사용합니다")
        self.assertContains(response, "최근 일봉 종가 기준 예상 손익률")
        self.assertContains(response, "portfolio-table-scroll")
        self.assertContains(response, "portfolio-summary-table")
        self.assertContains(response, "portfolio-scroll-hint")
        self.assertContains(response, "표를 좌우로 스크롤할 수 있습니다.")
        self.assertContains(response, 'aria-label="포트폴리오 요약 표"')
        self.assertContains(response, 'tabindex="0"')
        self.assertContains(response, "portfolio-number")
        self.assertContains(response, "simulation-form-grid")
        self.assertContains(response, "simulation-field-grid")
        self.assertContains(response, "simulation-field")
        self.assertContains(response, "simulation-panel")
        self.assertContains(response, "simulation-row")
        self.assertContains(response, "priced")
        self.assertContains(response, "missing_daily_price")
        self.assertContains(response, "평균단가 계산")
        self.assertContains(response, "additional_budget")
        self.assertContains(response, "buy_price")
        self.assertContains(response, "target_price")
        self.assertContains(response, "data-simulation-endpoint")
        self.assertContains(
            response,
            f"/api/holdings/{self.priced_holding.id}/additional-buy-simulation/",
        )
        self.assertContains(response, "simulation-toggle")
        self.assertContains(response, "simulation-submit")
        self.assertContains(response, 'aria-expanded="false"')
        self.assertContains(response, "getCookie")
        self.assertContains(response, "X-CSRFToken")
        self.assertContains(response, "fetch(endpoint")
        self.assertContains(response, 'credentials: "same-origin"')
        self.assertContains(response, "simulation_only")
        self.assertContains(response, "order_execution")
        self.assertContains(response, "계산 중...")
        self.assertContains(response, "응답 안전 조건")
        self.assertContains(response, "계산 전용")
        self.assertContains(response, "주문을 실행하지 않습니다")
        self.assertContains(response, "매수/매도 추천이 아닙니다")
        self.assertContains(response, "수익을 보장하지 않습니다")
        self.assertContains(response, "수수료와 세금은 포함하지 않습니다")
        self.assertContains(response, 'aria-live="polite"')
        self.assertContains(response, 'type="button"')
        self.assertNotContains(response, "<th scope=\"col\">Latest</th>", html=True)
        self.assertNotContains(response, "비워두면 저장된 최신 종가를 사용합니다")
        self.assertNotContains(response, "최근 종가 기준 예상 손익률")
        self.assertNotContains(response, "화면비활성")
        self.assertNotContains(response, "summary_page_other")
        self.assertNotContains(response, "summary-page-other@example.com")

        self.assertEqual(DataIngestionLog.objects.count(), before_counts["logs"])
        self.assertEqual(UserHolding.objects.count(), before_counts["holdings"])
        self.assertEqual(DailyPrice.objects.count(), before_counts["prices"])
        self.assertEqual(Stock.objects.count(), before_counts["stocks"])

    def test_portfolio_summary_mobile_readability_css_is_defined(self):
        css = Path("portfolio/static/portfolio/css/styles.css").read_text(encoding="utf-8")

        self.assertIn(".portfolio-table-scroll", css)
        self.assertIn("overflow-x: auto", css)
        self.assertIn("-webkit-overflow-scrolling: touch", css)
        self.assertIn(".portfolio-summary-table", css)
        self.assertIn("min-width: 1100px", css)
        self.assertIn(".portfolio-number", css)
        self.assertIn("text-align: right", css)
        self.assertIn(".simulation-form-grid", css)
        self.assertIn(".simulation-result", css)
        self.assertIn("@media (max-width: 767.98px)", css)

    def test_portfolio_summary_page_can_include_inactive_holdings(self):
        self.client.login(username="summary_page_user", password="pw12345")

        response = self.client.get(self.url, {"include_inactive": "true"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "화면비활성")
        self.assertContains(response, "999999")

    def test_portfolio_summary_page_excludes_sensitive_and_order_execution_content(self):
        self.client.login(username="summary_page_user", password="pw12345")

        response = self.client.get(self.url, {"include_inactive": "true"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<span class="app-user-label">summary_page_user</span>', html=True)
        content = response.content.decode("utf-8").lower()
        forbidden_tokens = [
            "summary-page@example.com",
            "summary_page_other",
            "summary-page-other@example.com",
            "user_id",
            "username",
            "email",
            "accountno",
            "accountseq",
            "x-tossinvest-account",
            "access_token",
            "authorization",
            "raw_response",
            "request_body",
            "주문하기",
            "매수하기",
            "매도하기",
            "자동매매",
            "order_id",
            "orderno",
        ]
        for token in forbidden_tokens:
            self.assertNotIn(token, content)


@override_settings(LEGACY_PORTFOLIO_USERNAME="legacy_demo")
class TransactionAggregationAndSyncTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="tx_editor", password="pw12345")
        self.client.force_login(self.user)

    def _create_transaction(self, **kwargs):
        defaults = {
            "trade_type": "매수",
            "stock_name": "삼성전자",
            "year": 2026,
            "month": 1,
            "day": 1,
            "hour": 9,
            "minute": 0,
            "quantity": 10,
            "unit_price": 100,
        }
        defaults.update(kwargs)
        return Transaction.objects.create(**defaults)

    def test_aggregate_all_transactions_by_stock_uses_decimal_average_price(self):
        self._create_transaction(quantity=10, unit_price=100, minute=0)
        self._create_transaction(quantity=5, unit_price=120, minute=1)
        self._create_transaction(trade_type="매도", quantity=8, unit_price=130, minute=2)

        positions, warnings = aggregate_all_transactions_by_stock()

        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].stock_name, "삼성전자")
        self.assertEqual(positions[0].quantity, 7)
        self.assertEqual(positions[0].average_price, Decimal("106.67"))
        self.assertEqual(positions[0].total_cost, Decimal("746.67"))
        self.assertEqual(warnings, [])

    def test_sync_service_creates_and_deactivates_holding_without_deleting_history(self):
        StockSymbol.objects.create(stock_name="삼성전자", ticker="005930.KS")
        self._create_transaction(quantity=10, unit_price=70000, minute=0)

        report = sync_all_holdings_for_legacy_user()

        self.assertEqual(report.created_count, 1)
        holding = UserHolding.objects.get(user__username="legacy_demo", stock__code="005930")
        self.assertTrue(holding.is_active)
        self.assertEqual(holding.quantity, 10)
        self.assertEqual(holding.average_price, Decimal("70000.00"))

        decision = AveragingDecision.objects.create(
            holding=holding,
            score=55,
            grade="B",
            decision="관찰 구간",
            reason_summary="이력 보존 확인",
        )
        self._create_transaction(trade_type="매도", quantity=10, unit_price=71000, minute=3)

        report = sync_all_holdings_for_legacy_user()

        holding.refresh_from_db()
        self.assertEqual(report.deactivated_count, 1)
        self.assertFalse(holding.is_active)
        self.assertEqual(holding.quantity, 0)
        self.assertEqual(holding.average_price, Decimal("0.00"))
        self.assertTrue(AveragingDecision.objects.filter(pk=decision.pk).exists())

    def test_sync_command_dry_run_does_not_persist_holding_or_user(self):
        StockSymbol.objects.create(stock_name="삼성전자", ticker="005930.KS")
        self._create_transaction(quantity=3, unit_price=65000)

        output = StringIO()
        call_command("sync_transactions_to_holdings", "--username", "dryrun_user", "--dry-run", stdout=output)

        self.assertFalse(UserHolding.objects.exists())
        self.assertFalse(UserHolding.objects.filter(user__username="dryrun_user").exists())
        self.assertIn("[DRY-RUN] holding sync complete", output.getvalue())

    def test_upload_csv_view_creates_legacy_holding(self):
        StockSymbol.objects.create(stock_name="삼성전자", ticker="005930.KS")
        csv_content = (
            "매매구분,종목,년,월,일,시,분,수량(주),단가(원)\n"
            "매수,삼성전자,2026,1,1,9,0,10,70000\n"
        )
        upload = SimpleUploadedFile("transactions.csv", csv_content.encode("utf-8"), content_type="text/csv")

        response = self.client.post(reverse("upload_csv"), {"csv_file": upload})

        self.assertEqual(response.status_code, 302)
        holding = UserHolding.objects.get(user__username="legacy_demo", stock__code="005930")
        self.assertTrue(holding.is_active)
        self.assertEqual(holding.quantity, 10)
        self.assertEqual(holding.average_price, Decimal("70000.00"))

    def test_transaction_create_view_creates_legacy_holding(self):
        StockSymbol.objects.create(stock_name="삼성전자", ticker="005930.KS")

        response = self.client.post(
            reverse("transaction_create"),
            {
                "trade_type": "매수",
                "stock_name": "삼성전자",
                "year": 2026,
                "month": 1,
                "day": 1,
                "hour": 9,
                "minute": 0,
                "quantity": 7,
                "unit_price": 68000,
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Transaction.objects.filter(stock_name="삼성전자", quantity=7, unit_price=68000).exists())
        holding = UserHolding.objects.get(user__username="legacy_demo", stock__code="005930")
        self.assertTrue(holding.is_active)
        self.assertEqual(holding.quantity, 7)
        self.assertEqual(holding.average_price, Decimal("68000.00"))

    def test_transaction_edit_view_resyncs_legacy_holding(self):
        StockSymbol.objects.create(stock_name="삼성전자", ticker="005930.KS")
        tx = self._create_transaction(quantity=10, unit_price=70000)
        sync_all_holdings_for_legacy_user()

        response = self.client.post(
            reverse("transaction_edit", args=[tx.id]),
            {
                "trade_type": "매수",
                "stock_name": "삼성전자",
                "year": 2026,
                "month": 1,
                "day": 1,
                "hour": 9,
                "minute": 0,
                "quantity": 12,
                "unit_price": 71000,
            },
        )

        self.assertEqual(response.status_code, 302)
        holding = UserHolding.objects.get(user__username="legacy_demo", stock__code="005930")
        self.assertTrue(holding.is_active)
        self.assertEqual(holding.quantity, 12)
        self.assertEqual(holding.average_price, Decimal("71000.00"))

    def test_transaction_delete_view_deactivates_legacy_holding(self):
        StockSymbol.objects.create(stock_name="삼성전자", ticker="005930.KS")
        tx = self._create_transaction(quantity=10, unit_price=70000)
        sync_all_holdings_for_legacy_user()

        response = self.client.post(reverse("transaction_delete", args=[tx.id]))

        self.assertEqual(response.status_code, 302)
        holding = UserHolding.objects.get(user__username="legacy_demo", stock__code="005930")
        self.assertFalse(holding.is_active)
        self.assertEqual(holding.quantity, 0)
        self.assertEqual(holding.average_price, Decimal("0.00"))


class HistoricalBuyAnalysisTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="analysis_user", password="pw12345")
        self.client.force_login(self.user)
        self.stock = Stock.objects.create(
            code="005930",
            name="삼성전자",
            market=Stock.MARKET_KOSPI,
        )
        StockSymbol.objects.create(stock_name="삼성전자", ticker="005930.KS")
        self.second_stock = Stock.objects.create(
            code="066570",
            name="LG전자",
            market=Stock.MARKET_KOSPI,
        )
        StockSymbol.objects.create(stock_name="LG전자", ticker="066570.KS")

        start_date = date(2026, 1, 1)
        for offset in range(60):
            current_date = start_date + timedelta(days=offset)
            if offset < 20:
                close_price = Decimal(str(130 - round((30 / 19) * offset)))
            elif offset < 40:
                close_price = Decimal(str(100 + round((12 / 19) * (offset - 19))))
            else:
                close_price = Decimal("108")
            DailyPrice.objects.create(
                stock=self.stock,
                date=current_date,
                open_price=close_price,
                high_price=close_price + Decimal("1"),
                low_price=close_price - Decimal("1"),
                close_price=close_price,
                volume=1000 + offset,
            )
            second_close_price = Decimal(str(120 - round((30 / 39) * offset))) if offset < 40 else Decimal("90")
            DailyPrice.objects.create(
                stock=self.second_stock,
                date=current_date,
                open_price=second_close_price,
                high_price=second_close_price + Decimal("1"),
                low_price=second_close_price - Decimal("1"),
                close_price=second_close_price,
                volume=2000 + offset,
            )

        Transaction.objects.create(
            trade_type="매수",
            stock_name="삼성전자",
            year=2026,
            month=1,
            day=1,
            hour=9,
            minute=0,
            quantity=10,
            unit_price=130,
        )
        Transaction.objects.create(
            trade_type="매수",
            stock_name="삼성전자",
            year=2026,
            month=1,
            day=20,
            hour=9,
            minute=0,
            quantity=10,
            unit_price=100,
        )
        Transaction.objects.create(
            trade_type="매수",
            stock_name="LG전자",
            year=2026,
            month=1,
            day=1,
            hour=9,
            minute=0,
            quantity=10,
            unit_price=120,
        )
        Transaction.objects.create(
            trade_type="매수",
            stock_name="LG전자",
            year=2026,
            month=1,
            day=20,
            hour=9,
            minute=0,
            quantity=10,
            unit_price=105,
        )

    def test_build_historical_buy_timing_analysis_classifies_buy_points(self):
        result = build_historical_buy_timing_analysis("삼성전자")

        self.assertEqual(len(result["evaluations"]), 2)
        self.assertEqual(result["bad_count"], 1)
        self.assertEqual(result["good_count"], 1)
        self.assertTrue(result["overview_chart"]["available"])
        self.assertEqual(len(result["overview_chart"]["markers"]), 2)
        self.assertEqual(result["evaluations"][0]["evaluation_label"], "아쉬운 매수")
        self.assertEqual(result["evaluations"][0]["evaluation_reason_label"], "20거래일 약세 지속")
        self.assertTrue(result["evaluations"][0]["sparkline_available"])
        self.assertIn(",", result["evaluations"][0]["sparkline_points"])
        self.assertEqual(result["evaluations"][0]["sparkline_day_span"], 20)
        self.assertEqual(result["evaluations"][1]["entry_context"], "물타기 매수")
        self.assertEqual(result["evaluations"][1]["evaluation_label"], "잘한 매수")
        self.assertGreater(result["evaluations"][1]["timing_score"], result["evaluations"][0]["timing_score"])
        self.assertEqual(result["evaluations"][1]["pre_buy_return_5_display"], "-7.41%")
        self.assertEqual(result["evaluations"][1]["pre_avg_gap_display"], "-23.08%")
        self.assertEqual(result["evaluations"][1]["distance_to_trough_20_display"], "0.00%")
        self.assertEqual(result["evaluations"][1]["days_to_trough_20_display"], "1일")
        self.assertEqual(result["evaluations"][1]["days_to_break_even_20_display"], "2일")

    def test_build_historical_buy_timing_rankings_orders_stocks_by_average_score(self):
        rankings = build_historical_buy_timing_rankings(["삼성전자", "LG전자"])

        self.assertEqual(len(rankings), 2)
        self.assertEqual(rankings[0]["stock_name"], "삼성전자")
        self.assertEqual(rankings[1]["stock_name"], "LG전자")
        self.assertGreater(rankings[0]["average_timing_score"], rankings[1]["average_timing_score"])
        self.assertEqual(rankings[0]["good_count"], 1)
        self.assertEqual(rankings[1]["bad_count"], 2)
        self.assertIsNotNone(rankings[0]["average_break_even_days"])
        self.assertIsNotNone(rankings[0]["average_trough_gap"])
        self.assertEqual(rankings[0]["confidence_label"], "보통")
        self.assertEqual(rankings[1]["confidence_label"], "보통")
        self.assertIsNotNone(rankings[0]["timing_score_stddev"])
        self.assertIn(rankings[0]["consistency_label"], {"높음", "보통", "낮음"})

    @patch("portfolio.views.build_holdings_analysis", return_value=[])
    @patch(
        "portfolio.views.build_realized_profit_analysis",
        return_value={
            "total": {"sold_qty": 0, "proceeds": 0, "cost": 0, "profit": 0, "profit_rate": 0},
            "summary_rows": [],
            "rows": [],
            "warnings": [],
        },
    )
    def test_analysis_view_renders_historical_buy_section(self, _mock_realized, _mock_holdings):
        response = self.client.get(reverse("analysis_view"), {"stock_name": "삼성전자"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "과거 추가 매수 회고 분석")
        self.assertContains(response, "평균 점수 최고")
        self.assertContains(response, "회복이 가장 빨랐던 종목")
        self.assertContains(response, "저점 근접도가 좋았던 종목")
        self.assertContains(response, "실행 일관성이 좋았던 종목")
        self.assertContains(response, "가장 어려웠던 종목")
        self.assertContains(response, "종목별 회고 랭킹")
        self.assertContains(response, "평균 회고 점수")
        self.assertContains(response, "현재 정렬 1위")
        self.assertContains(response, "평균 점수 1위")
        self.assertContains(response, "좋은 비율 1위")
        self.assertContains(response, "20일 성과 1위")
        self.assertContains(response, "회복 속도 1위")
        self.assertContains(response, "저점 근접도 1위")

    @patch("portfolio.views.build_holdings_analysis", return_value=[])
    @patch(
        "portfolio.views.build_realized_profit_analysis",
        return_value={
            "total": {"sold_qty": 0, "proceeds": 0, "cost": 0, "profit": 0, "profit_rate": 0},
            "summary_rows": [],
            "rows": [],
            "warnings": [],
        },
    )
    def test_analysis_view_handles_stock_without_daily_price_history(self, _mock_realized, _mock_holdings):
        Transaction.objects.create(
            trade_type="매수",
            stock_name="미수집종목",
            year=2026,
            month=2,
            day=1,
            hour=9,
            minute=0,
            quantity=5,
            unit_price=100,
        )

        response = self.client.get(reverse("analysis_view"), {"stock_name": "미수집종목"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "과거 추가 매수 회고 분석")
        self.assertContains(response, "판단 보류")
        self.assertContains(response, "DailyPrice 이력이 없어 회고 판단을 보류합니다.")
        retrospective = response.context["retrospective"]
        self.assertEqual(retrospective["evaluations"][0]["evaluation_label"], "판단 보류")
        self.assertIsNone(retrospective["evaluations"][0]["pre_buy_return_5"])

    @patch("portfolio.views.build_holdings_analysis", return_value=[])
    @patch(
        "portfolio.views.build_realized_profit_analysis",
        return_value={
            "total": {"sold_qty": 0, "proceeds": 0, "cost": 0, "profit": 0, "profit_rate": 0},
            "summary_rows": [],
            "rows": [],
            "warnings": [],
        },
    )
    def test_analysis_view_supports_ranking_sort_option(self, _mock_realized, _mock_holdings):
        response = self.client.get(
            reverse("analysis_view"),
            {"stock_name": "삼성전자", "ranking_sort": "consistency"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["selected_ranking_sort"], "consistency")
        self.assertContains(response, "랭킹 정렬")
        self.assertContains(response, "점수 편차가 작은 종목 순으로 정렬했습니다.")
        self.assertContains(response, "현재 정렬 1위")
        self.assertContains(response, "평균 점수 1위")

    @patch("portfolio.views.build_holdings_analysis", return_value=[])
    @patch(
        "portfolio.views.build_realized_profit_analysis",
        return_value={
            "total": {"sold_qty": 0, "proceeds": 0, "cost": 0, "profit": 0, "profit_rate": 0},
            "summary_rows": [],
            "rows": [],
            "warnings": [],
        },
    )
    def test_analysis_view_exports_retrospective_rankings_csv(self, _mock_realized, _mock_holdings):
        response = self.client.get(
            reverse("analysis_view"),
            {
                "stock_name": "삼성전자",
                "ranking_sort": "consistency",
                "export": "retrospective_rankings_csv",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertIn("retrospective_rankings_consistency.csv", response["Content-Disposition"])
        content = response.content.decode("utf-8-sig")
        self.assertIn("순위,종목,종목코드,시장,평균 회고 점수", content)
        self.assertIn("삼성전자", content)
        self.assertIn("LG전자", content)
        self.assertIn("consistency", content)

    @patch("portfolio.views.build_holdings_analysis", return_value=[])
    @patch(
        "portfolio.views.build_realized_profit_analysis",
        return_value={
            "total": {"sold_qty": 0, "proceeds": 0, "cost": 0, "profit": 0, "profit_rate": 0},
            "summary_rows": [],
            "rows": [],
            "warnings": [],
        },
    )
    def test_analysis_view_exports_retrospective_details_csv_with_filter(self, _mock_realized, _mock_holdings):
        response = self.client.get(
            reverse("analysis_view"),
            {
                "stock_name": "삼성전자",
                "evaluation_filter": "good",
                "ranking_sort": "score",
                "export": "retrospective_details_csv",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        self.assertTrue(response.has_header("Content-Disposition"))
        content = response.content.decode("utf-8-sig")
        self.assertIn("매수시각,매수 구분,판정,판정 사유,타이밍 점수", content)
        self.assertIn("2026-01-20 09:00", content)
        self.assertIn("잘한 매수", content)
        self.assertIn("good", content)
        self.assertNotIn("2026-01-01 09:00", content)

    @patch("portfolio.views.build_historical_buy_timing_analysis")
    @patch("portfolio.views.build_historical_buy_timing_rankings")
    @patch("portfolio.views.build_holdings_analysis", return_value=[])
    @patch(
        "portfolio.views.build_realized_profit_analysis",
        return_value={
            "total": {"sold_qty": 0, "proceeds": 0, "cost": 0, "profit": 0, "profit_rate": 0},
            "summary_rows": [],
            "rows": [],
            "warnings": [],
        },
    )
    def test_analysis_view_shows_ranking_comparison_card_when_top_differs(
        self,
        _mock_realized,
        _mock_holdings,
        mock_rankings,
        mock_retrospective,
    ):
        mock_rankings.return_value = [
            {
                "stock_name": "LG전자",
                "stock_code": "066570",
                "stock_market": "KOSPI",
                "buy_count": 3,
                "scored_buy_count": 3,
                "good_count": 2,
                "neutral_count": 1,
                "bad_count": 0,
                "pending_count": 0,
                "good_ratio": 66.7,
                "good_ratio_display": "+66.70%",
                "confidence_label": "보통",
                "confidence_badge_class": "bg-warning-subtle text-warning-emphasis",
                "confidence_note": "표본은 적당하지만, 종목별 맥락을 함께 보는 편이 좋습니다.",
                "consistency_label": "높음",
                "consistency_badge_class": "bg-success-subtle text-success",
                "consistency_note": "매수별 점수 편차가 작아 실행 품질이 비교적 안정적이었습니다.",
                "average_timing_score": 72.0,
                "average_timing_score_display": "72.0점",
                "timing_score_stddev": 6.0,
                "timing_score_stddev_display": "6.0점",
                "average_return_20": 5.5,
                "average_return_20_display": "+5.50%",
                "average_break_even_days": 4.0,
                "average_break_even_days_display": "4일",
                "average_trough_gap": 2.0,
                "average_trough_gap_display": "+2.00%",
                "score_bar_width": 72,
                "score_bar_class": "bg-info",
            },
            {
                "stock_name": "삼성전자",
                "stock_code": "005930",
                "stock_market": "KOSPI",
                "buy_count": 3,
                "scored_buy_count": 3,
                "good_count": 1,
                "neutral_count": 1,
                "bad_count": 1,
                "pending_count": 0,
                "good_ratio": 33.3,
                "good_ratio_display": "+33.30%",
                "confidence_label": "보통",
                "confidence_badge_class": "bg-warning-subtle text-warning-emphasis",
                "confidence_note": "표본은 적당하지만, 종목별 맥락을 함께 보는 편이 좋습니다.",
                "consistency_label": "보통",
                "consistency_badge_class": "bg-warning-subtle text-warning-emphasis",
                "consistency_note": "매수별 성과 차이가 있어 구간별 복기가 필요합니다.",
                "average_timing_score": 81.0,
                "average_timing_score_display": "81.0점",
                "timing_score_stddev": 18.0,
                "timing_score_stddev_display": "18.0점",
                "average_return_20": 4.0,
                "average_return_20_display": "+4.00%",
                "average_break_even_days": 6.0,
                "average_break_even_days_display": "6일",
                "average_trough_gap": 3.0,
                "average_trough_gap_display": "+3.00%",
                "score_bar_width": 81,
                "score_bar_class": "bg-success",
            },
        ]
        mock_retrospective.return_value = build_historical_buy_timing_analysis("삼성전자")

        response = self.client.get(
            reverse("analysis_view"),
            {"stock_name": "삼성전자", "ranking_sort": "consistency"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "일관성 1위와 평균 점수 1위가 다릅니다.")
        self.assertContains(response, "현재 정렬 1위는")
        self.assertContains(response, "LG전자")
        self.assertContains(response, "삼성전자")

    @patch("portfolio.views.build_holdings_analysis", return_value=[])
    @patch(
        "portfolio.views.build_realized_profit_analysis",
        return_value={
            "total": {"sold_qty": 0, "proceeds": 0, "cost": 0, "profit": 0, "profit_rate": 0},
            "summary_rows": [],
            "rows": [],
            "warnings": [],
        },
    )
    def test_analysis_view_filters_retrospective_rows_by_evaluation(self, _mock_realized, _mock_holdings):
        response = self.client.get(
            reverse("analysis_view"),
            {"stock_name": "삼성전자", "evaluation_filter": "good"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "현재 필터 기준 1건을 표시합니다.")
        self.assertContains(response, "회고 인사이트 요약")
        self.assertContains(response, "사유 유형 요약")
        self.assertContains(response, "실행 품질 지표")
        self.assertContains(response, "점수 비교 사례")
        self.assertContains(response, "평균 20거래일 성과")
        self.assertContains(response, "가장 자주 나온 매수 구분")
        self.assertContains(response, "20거래일 강한 반등")
        self.assertContains(response, "평균 종합 회고 점수")
        self.assertContains(response, "매수 직전 5일 평균 등락률")
        self.assertContains(response, "이전 평단 대비 평균 매수가")
        self.assertContains(response, "평균 저점 대비 추가 하락")
        self.assertContains(response, "평균 저점 도달일(20일)")
        self.assertContains(response, "평균 손익분기 도달일")
        self.assertContains(response, "-7.41%")
        self.assertContains(response, "0.00%")
        self.assertContains(response, "2일")
        self.assertContains(response, "타이밍 점수")
        self.assertContains(response, "2026-01-20 09:00")
        self.assertNotContains(response, "2026-01-01 09:00")


class ConsultingScreenViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="consult_user", password="pw12345")
        self.other_user = User.objects.create_user(username="consult_other", password="pw12345")
        self.stock = Stock.objects.create(
            code="005930",
            name="삼성전자",
            market=Stock.MARKET_KOSPI,
            sector="반도체",
        )
        self.holding = UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("75000.00"),
            quantity=10,
            max_additional_budget=Decimal("1000000.00"),
        )
        DailyPrice.objects.create(
            stock=self.stock,
            date=date(2026, 4, 30),
            open_price=Decimal("73900.00"),
            high_price=Decimal("74100.00"),
            low_price=Decimal("73800.00"),
            close_price=Decimal("74000.00"),
            volume=1000,
        )

    def test_consulting_holding_list_requires_login(self):
        response = self.client.get(reverse("consulting_holding_list"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_consulting_holding_list_renders_current_user_holdings(self):
        self.client.login(username="consult_user", password="pw12345")

        response = self.client.get(reverse("consulting_holding_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "내 보유 종목 컨설팅")
        self.assertContains(response, "삼성전자")
        self.assertContains(response, reverse("holding_consult_page", args=[self.holding.id]))
        self.assertContains(response, 'data-theme-target="light"')
        self.assertContains(response, 'data-theme-target="dark"')
        self.assertContains(response, "stock-workbench-theme")
        self.assertContains(response, "portfolio/js/theme.js")

    def test_consulting_detail_page_requires_owner(self):
        self.client.login(username="consult_other", password="pw12345")

        response = self.client.get(reverse("holding_consult_page", args=[self.holding.id]))

        self.assertEqual(response.status_code, 404)

    def test_consulting_detail_page_renders_api_config(self):
        self.client.login(username="consult_user", password="pw12345")

        response = self.client.get(reverse("holding_consult_page", args=[self.holding.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "consult-page-config")
        self.assertContains(response, f"/api/holdings/{self.holding.id}/consult/")
        self.assertContains(response, "다시 분석")


class DataPipelineStatusPageTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="ops_user", password="pw12345")
        self.stock = Stock.objects.create(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI)
        self.holding = UserHolding.objects.create(
            user=self.user,
            stock=self.stock,
            average_price=Decimal("70000.00"),
            quantity=5,
        )
        DataQualitySnapshot.objects.create(
            stock=self.stock,
            as_of_date=date.today(),
            price_data_days=120,
            latest_price_age_days=1,
            investor_flow_days=20,
            market_data_available=True,
            financial_data_available=False,
            missing_fields=["financial_snapshots"],
            anomaly_flags=["stale_latest_price"],
            overall_score=Decimal("0.6100"),
            quality_grade="B",
        )
        DataProviderStatus.objects.create(
            provider="finance",
            data_type="price",
            is_active=True,
        )
        DataProviderStatus.objects.create(
            provider="finance",
            data_type="financial",
            is_active=True,
        )
        DataProviderStatus.objects.create(
            provider="disclosure",
            data_type="risk",
            is_active=True,
            consecutive_failures=2,
            last_error_message="opendart unavailable",
        )
        DataIngestionLog.objects.create(
            job_name="ingest_daily_prices",
            provider="finance",
            target_type="price",
            target_code="005930",
            status="success",
            started_at="2026-05-01T00:00:00+09:00",
            finished_at="2026-05-01T00:01:00+09:00",
            total_count=1,
            success_count=1,
        )
        DataIngestionLog.objects.create(
            job_name="ingest_daily_prices",
            provider="finance",
            target_type="price",
            target_code="005930",
            status="failed",
            started_at="2026-05-01T01:00:00+09:00",
            finished_at="2026-05-01T01:01:00+09:00",
            total_count=1,
            failed_count=1,
            error_message="finance timeout",
        )
        DataIngestionLog.objects.create(
            job_name="ingest_daily_prices",
            provider="finance",
            target_type="price",
            target_code="000660",
            status="failed",
            started_at="2026-05-01T02:00:00+09:00",
            finished_at="2026-05-01T02:01:00+09:00",
            total_count=1,
            failed_count=1,
            error_message="other stock failure",
        )
        DataIngestionLog.objects.create(
            job_name="ingest_risk_events",
            provider="disclosure",
            target_type="risk",
            target_code="005930",
            status="failed",
            started_at="2026-05-01T03:00:00+09:00",
            finished_at="2026-05-01T03:01:00+09:00",
            total_count=1,
            failed_count=1,
            error_message="disclosure risk failure",
        )
        StockDataCollectionStatus.objects.create(
            stock=self.stock,
            data_type=StockDataCollectionStatus.TYPE_FINANCIAL_SNAPSHOT,
            source="finance",
            status=StockDataCollectionStatus.STATUS_SUCCESS,
            last_row_count=1,
        )

    def test_data_pipeline_status_page_requires_login(self):
        response = self.client.get(reverse("data_pipeline_status_page"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_data_pipeline_status_page_renders_summary(self):
        self.client.login(username="ops_user", password="pw12345")

        response = self.client.get(reverse("data_pipeline_status_page"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Data Pipeline 운영 현황")
        self.assertContains(response, "상태 주의")
        self.assertContains(response, "finance")
        self.assertContains(response, "disclosure")
        self.assertContains(response, "financial_snapshots")
        self.assertContains(response, "/api/data-pipeline/summary/")
        self.assertContains(response, "/api/data-pipeline/ingestion-logs/")
        self.assertContains(response, "/api/data-pipeline/data-quality/005930/")
        self.assertContains(
            response,
            reverse("data_pipeline_provider_detail_page", args=["disclosure", "risk"]),
        )

    def test_data_pipeline_stock_detail_page_requires_login(self):
        response = self.client.get(reverse("data_pipeline_stock_detail_page", args=[self.stock.code]))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_data_pipeline_stock_detail_page_renders_snapshot_and_links(self):
        self.client.login(username="ops_user", password="pw12345")

        response = self.client.get(reverse("data_pipeline_stock_detail_page", args=[self.stock.code]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "최신 Data Quality Snapshot")
        self.assertContains(response, "Financial Snapshot")
        self.assertContains(response, reverse("data_pipeline_status_page"))
        self.assertContains(response, "/api/data-pipeline/data-quality/005930/")
        self.assertContains(response, "/api/data-pipeline/ingestion-logs/?target_code=005930")
        self.assertContains(
            response,
            reverse("data_pipeline_provider_detail_page", args=["finance", "financial"]) + "?stock_code=005930",
        )
        self.assertContains(response, reverse("holding_consult_page", args=[self.holding.id]))

    def test_data_pipeline_stock_detail_page_provider_status_filters_limit_results(self):
        self.client.login(username="ops_user", password="pw12345")

        response = self.client.get(
            reverse("data_pipeline_stock_detail_page", args=[self.stock.code]) + "?provider=disclosure&status=failed"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "provider disclosure /")
        self.assertContains(response, "status failed /")
        self.assertContains(
            response,
            "/api/data-pipeline/ingestion-logs/?target_code=005930&amp;provider=disclosure&amp;status=failed",
        )
        self.assertContains(response, "disclosure risk failure")
        self.assertNotContains(response, "finance timeout")

    def test_data_pipeline_provider_detail_page_requires_login(self):
        response = self.client.get(reverse("data_pipeline_provider_detail_page", args=["finance", "price"]))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_data_pipeline_provider_detail_page_renders_filtered_links(self):
        self.client.login(username="ops_user", password="pw12345")

        response = self.client.get(
            reverse("data_pipeline_provider_detail_page", args=["finance", "price"]) + "?stock_code=005930"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "finance / price")
        self.assertContains(response, "/api/data-pipeline/provider-status/?provider=finance&amp;data_type=price")
        self.assertContains(
            response,
            "/api/data-pipeline/ingestion-logs/?provider=finance&amp;target_type=price&amp;target_code=005930",
        )
        self.assertContains(response, reverse("data_pipeline_stock_detail_page", args=[self.stock.code]))

    def test_data_pipeline_provider_detail_page_failed_only_filter_limits_results(self):
        self.client.login(username="ops_user", password="pw12345")

        response = self.client.get(
            reverse("data_pipeline_provider_detail_page", args=["finance", "price"]) + "?stock_code=005930&failed_only=1"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "failed_only yes")
        self.assertContains(response, "finance timeout")
        self.assertNotContains(response, "other stock failure")

    def test_data_pipeline_provider_detail_page_status_filter_limits_results(self):
        self.client.login(username="ops_user", password="pw12345")

        response = self.client.get(
            reverse("data_pipeline_provider_detail_page", args=["finance", "price"]) + "?stock_code=005930&status=success"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "status success /")
        self.assertContains(
            response,
            "/api/data-pipeline/ingestion-logs/?provider=finance&amp;target_type=price&amp;target_code=005930&amp;status=success",
        )
        self.assertContains(response, ">success<")
        self.assertNotContains(response, "finance timeout")
