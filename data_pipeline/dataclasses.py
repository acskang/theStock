from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True)
class StockMasterRow:
    code: str
    name: str
    market: str
    sector: str = ""
    is_active: bool = True


@dataclass(frozen=True)
class DailyPriceRow:
    stock_code: str
    date: date
    open_price: Decimal
    high_price: Decimal
    low_price: Decimal
    close_price: Decimal
    volume: int
    change_rate: Optional[Decimal] = None


@dataclass(frozen=True)
class InvestorFlowRow:
    stock_code: str
    date: date
    foreign_net_buy: int = 0
    institution_net_buy: int = 0
    individual_net_buy: int = 0
    program_net_buy: int = 0


@dataclass(frozen=True)
class MarketIndexRow:
    code: str
    name: str
    date: date
    close_value: Decimal
    change_rate: Optional[Decimal] = None


@dataclass(frozen=True)
class RiskEventRow:
    stock_code: str
    event_type: str
    title: str
    event_date: date
    risk_level: str
    description: str = ""
    source: str = ""
    source_key: str = ""
    url: str = ""
    is_active: bool = True


@dataclass(frozen=True)
class FinancialSnapshotRow:
    stock_code: str
    fiscal_year: int
    period_type: str
    reported_date: Optional[date] = None
    revenue: Optional[Decimal] = None
    operating_profit: Optional[Decimal] = None
    net_income: Optional[Decimal] = None
    operating_cash_flow: Optional[Decimal] = None
    debt_ratio: Optional[Decimal] = None
    current_ratio: Optional[Decimal] = None
    equity: Optional[Decimal] = None
    capital_impairment_rate: Optional[Decimal] = None
    roe: Optional[Decimal] = None
    per: Optional[Decimal] = None
    pbr: Optional[Decimal] = None
    source: str = ""
    source_key: str = ""


@dataclass
class IngestionReport:
    job_name: str
    provider: str
    target_type: str
    target_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    created_count: int = 0
    updated_count: int = 0
    status: str = "success"
    error_message: str = ""
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

