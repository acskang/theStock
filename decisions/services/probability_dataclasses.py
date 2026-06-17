from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional


PROBABILITY_DISCLAIMER_TEXT = (
    "본 결과는 과거 데이터와 현재 조건 기반의 추정 확률이며, "
    "매수·매도 추천이 아닙니다. 미래 수익 또는 손실 회피를 보장하지 않습니다."
)


@dataclass(frozen=True)
class AveragingScenario:
    buy_price: Decimal
    buy_quantity: int
    lookahead_days: int = 20
    target_type: str = "new_average_price"
    target_profit_rate: Decimal = Decimal("0")
    manual_target_price: Optional[Decimal] = None
    stop_loss_type: str = "support_or_atr"
    stop_loss_price: Optional[Decimal] = None
    same_day_hit_policy: str = "conservative"


@dataclass(frozen=True)
class ProbabilityComponent:
    success: Decimal
    failure: Decimal
    neutral: Decimal
    weight: Decimal
    confidence: Decimal
    sample_count: int = 0
    details: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProbabilityFeatureSnapshot:
    date: date
    close_price: Decimal
    loss_rate_pct: Optional[Decimal]
    rsi14: Optional[Decimal]
    price_to_ma20_pct: Optional[Decimal]
    price_to_ma60_pct: Optional[Decimal]
    support_distance_pct: Optional[Decimal]
    volume_ratio: Optional[Decimal]
    foreign_flow_signal: int = 0
    institution_flow_signal: int = 0
    market_trend_signal: int = 0
    risk_level_signal: int = 0


@dataclass(frozen=True)
class HistoricalCaseOutcome:
    base_date: date
    base_close: Decimal
    target_price: Decimal
    stop_loss_price: Decimal
    outcome: str
    days_to_outcome: Optional[int]
    max_favorable_return: Decimal
    max_adverse_return: Decimal


@dataclass(frozen=True)
class ProbabilityResult:
    success_probability: Decimal
    failure_probability: Decimal
    neutral_probability: Decimal
    success_label: str
    failure_label: str
    confidence: Decimal
    confidence_label: str
    target_price: Decimal
    stop_loss_price: Decimal
    new_average_price: Decimal
    lookahead_days: int
    basis: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    disclaimer: str = PROBABILITY_DISCLAIMER_TEXT
