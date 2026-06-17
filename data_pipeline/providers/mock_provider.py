from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from data_pipeline.dataclasses import (
    DailyPriceRow,
    FinancialSnapshotRow,
    InvestorFlowRow,
    MarketIndexRow,
    RiskEventRow,
    StockMasterRow,
)
from decisions.models import RiskEvent
from stocks.models import FinancialSnapshot, Stock

from .base import BaseDataProvider


class MockDataProvider(BaseDataProvider):
    provider_name = "mock"

    def get_stock_master_rows(self):
        return [
            StockMasterRow(code="005930", name="삼성전자", market=Stock.MARKET_KOSPI, sector="반도체"),
            StockMasterRow(code="000660", name="SK하이닉스", market=Stock.MARKET_KOSPI, sector="반도체"),
            StockMasterRow(code="035420", name="NAVER", market=Stock.MARKET_KOSPI, sector="인터넷"),
        ]

    def get_daily_price_rows(self, stock, days: int):
        today = timezone.localdate()
        base_price = Decimal(str(50000 + (int(stock.code[-2:]) * 10)))
        rows = []
        previous_close = None
        for offset in range(days):
            current_date = today - timedelta(days=days - offset - 1)
            close_price = base_price + Decimal(offset * 20)
            open_price = close_price - Decimal("50.00")
            high_price = close_price + Decimal("100.00")
            low_price = close_price - Decimal("100.00")
            change_rate = None
            if previous_close:
                change_rate = ((close_price - previous_close) / previous_close * Decimal("100")).quantize(
                    Decimal("0.0001")
                )
            rows.append(
                DailyPriceRow(
                    stock_code=stock.code,
                    date=current_date,
                    open_price=open_price,
                    high_price=high_price,
                    low_price=low_price,
                    close_price=close_price,
                    volume=100000 + (offset * 100),
                    change_rate=change_rate,
                )
            )
            previous_close = close_price
        return rows

    def get_investor_flow_rows(self, stock, days: int):
        today = timezone.localdate()
        rows = []
        for offset in range(days):
            current_date = today - timedelta(days=days - offset - 1)
            foreign = 100000 + (offset * 10)
            institution = 80000 + (offset * 8)
            rows.append(
                InvestorFlowRow(
                    stock_code=stock.code,
                    date=current_date,
                    foreign_net_buy=foreign,
                    institution_net_buy=institution,
                    individual_net_buy=-(foreign + institution),
                    program_net_buy=5000 + offset,
                )
            )
        return rows

    def get_market_index_rows(self, code: str, days: int):
        today = timezone.localdate()
        index_map = {
            "KOSPI": ("KOSPI", Decimal("2500.0000"), Decimal("2.5000")),
            "KOSDAQ": ("KOSDAQ", Decimal("800.0000"), Decimal("1.2000")),
            "USDKRW": ("USD/KRW", Decimal("1350.0000"), Decimal("0.3000")),
            "NASDAQ": ("NASDAQ", Decimal("16000.0000"), Decimal("12.5000")),
            "SP500": ("S&P500", Decimal("5000.0000"), Decimal("4.2000")),
        }
        name, base_value, step = index_map.get(code, (code, Decimal("1000.0000"), Decimal("1.0000")))
        rows = []
        previous_close = None
        for offset in range(days):
            current_date = today - timedelta(days=days - offset - 1)
            close_value = base_value + (step * offset)
            change_rate = None
            if previous_close:
                change_rate = ((close_value - previous_close) / previous_close * Decimal("100")).quantize(
                    Decimal("0.0001")
                )
            rows.append(
                MarketIndexRow(
                    code=code,
                    name=name,
                    date=current_date,
                    close_value=close_value,
                    change_rate=change_rate,
                )
            )
            previous_close = close_value
        return rows

    def get_risk_event_rows(self, stock, days: int):
        if stock.code != "035420":
            return []
        event_date = timezone.localdate() - timedelta(days=min(days, 14))
        return [
            RiskEventRow(
                stock_code=stock.code,
                event_type="earnings_shock",
                title="실적 충격 점검",
                event_date=event_date,
                risk_level=RiskEvent.RISK_LOW,
                description="Mock provider generated event.",
                source="mock",
                source_key=f"mock:{stock.code}:{event_date.isoformat()}:earnings_shock",
                url="https://example.com/mock-risk-event",
                is_active=True,
            )
        ]

    def get_financial_snapshot_rows(self, stock, years: int):
        current_year = timezone.localdate().year
        rows = []
        for offset in range(years):
            fiscal_year = current_year - offset - 1
            rows.append(
                FinancialSnapshotRow(
                    stock_code=stock.code,
                    fiscal_year=fiscal_year,
                    period_type=FinancialSnapshot.PERIOD_ANNUAL,
                    reported_date=timezone.localdate() - timedelta(days=offset * 365),
                    revenue=Decimal("1000000000.00") + Decimal(offset * 10000000),
                    operating_profit=Decimal("150000000.00") - Decimal(offset * 5000000),
                    net_income=Decimal("120000000.00") - Decimal(offset * 4000000),
                    operating_cash_flow=Decimal("170000000.00") - Decimal(offset * 3000000),
                    debt_ratio=Decimal("80.00") + Decimal(offset * 2),
                    current_ratio=Decimal("140.00") - Decimal(offset * 2),
                    equity=Decimal("800000000.00") + Decimal(offset * 10000000),
                    capital_impairment_rate=Decimal("0.00"),
                    roe=Decimal("12.50") - Decimal(offset),
                    per=Decimal("15.0000"),
                    pbr=Decimal("1.2000"),
                    source="mock",
                    source_key=f"mock:{stock.code}:{fiscal_year}:ANNUAL",
                )
            )
        return rows

