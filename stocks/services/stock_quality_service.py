from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from django.utils import timezone

from stocks.models import FinancialSnapshot, Stock


@dataclass(frozen=True)
class StockQualityResult:
    quality_grade: str
    score: Decimal
    grade_cap: Optional[str]
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


GRADE_SCORES = {
    "Q1": Decimal("0.9500"),
    "Q2": Decimal("0.8000"),
    "Q3": Decimal("0.6000"),
    "Q4": Decimal("0.3000"),
    "Q5": Decimal("0.0000"),
    "UNKNOWN": Decimal("0.5000"),
}
GRADE_CAPS = {
    "Q1": None,
    "Q2": None,
    "Q3": "B",
    "Q4": "C",
    "Q5": "D",
    "UNKNOWN": "B",
}
CORE_FINANCIAL_FIELDS = (
    "operating_profit",
    "net_income",
    "operating_cash_flow",
    "debt_ratio",
    "current_ratio",
    "equity",
    "capital_impairment_rate",
    "roe",
)


def _build_result(quality_grade: str, *, blockers=None, warnings=None, details=None) -> StockQualityResult:
    return StockQualityResult(
        quality_grade=quality_grade,
        score=GRADE_SCORES[quality_grade],
        grade_cap=GRADE_CAPS[quality_grade],
        blockers=blockers or [],
        warnings=warnings or [],
        details=details or {},
    )


def _ordered_snapshots(stock):
    return list(
        FinancialSnapshot.objects.filter(stock=stock).order_by(
            "-fiscal_year",
            "-reported_date",
            "-id",
        )[:4]
    )


def _snapshot_to_dict(snapshot):
    return {
        "fiscal_year": snapshot.fiscal_year,
        "period_type": snapshot.period_type,
        "reported_date": snapshot.reported_date.isoformat() if snapshot.reported_date else None,
        "revenue": snapshot.revenue,
        "operating_profit": snapshot.operating_profit,
        "net_income": snapshot.net_income,
        "operating_cash_flow": snapshot.operating_cash_flow,
        "debt_ratio": snapshot.debt_ratio,
        "current_ratio": snapshot.current_ratio,
        "equity": snapshot.equity,
        "capital_impairment_rate": snapshot.capital_impairment_rate,
        "roe": snapshot.roe,
        "per": snapshot.per,
        "pbr": snapshot.pbr,
        "source": snapshot.source,
    }


def _negative_streak(snapshots, field_name: str) -> int:
    streak = 0
    for snapshot in snapshots:
        value = getattr(snapshot, field_name)
        if value is None or value >= 0:
            break
        streak += 1
    return streak


def _count_available_metrics(snapshot) -> int:
    return sum(1 for field_name in CORE_FINANCIAL_FIELDS if getattr(snapshot, field_name) is not None)


def _collect_details(stock, snapshots):
    latest = snapshots[0]
    age_days = None
    if latest.reported_date:
        age_days = (timezone.localdate() - latest.reported_date).days
    return {
        "is_active": stock.is_active,
        "financial_data_available": True,
        "snapshot_count": len(snapshots),
        "available_metric_count": _count_available_metrics(latest),
        "latest_snapshot_age_days": age_days,
        "latest_snapshot": _snapshot_to_dict(latest),
        "operating_loss_streak": _negative_streak(snapshots, "operating_profit"),
        "net_loss_streak": _negative_streak(snapshots, "net_income"),
        "negative_cash_flow_streak": _negative_streak(snapshots, "operating_cash_flow"),
    }


def evaluate_stock_quality(stock) -> StockQualityResult:
    if not stock.is_active:
        return _build_result(
            "Q5",
            blockers=["비활성 종목으로 분류되어 있습니다."],
            details={"is_active": stock.is_active},
        )

    if stock.market in {Stock.MARKET_ETF, Stock.MARKET_ETN}:
        return _build_result(
            "UNKNOWN",
            blockers=[],
            warnings=["ETF/ETN은 일반 기업 재무제표 기준 품질 평가를 적용하지 않아 품질 평가는 제한적입니다."],
            details={
                "is_active": stock.is_active,
                "financial_data_available": False,
                "market": stock.market,
            },
        )

    snapshots = _ordered_snapshots(stock)
    if not snapshots:
        return _build_result(
            "UNKNOWN",
            warnings=["재무 품질 데이터가 없어 품질 평가는 제한적입니다."],
            details={
                "is_active": stock.is_active,
                "financial_data_available": False,
                "snapshot_count": 0,
            },
        )

    latest = snapshots[0]
    details = _collect_details(stock, snapshots)
    warnings = []
    blockers = []

    if details["available_metric_count"] < 4:
        return _build_result(
            "UNKNOWN",
            warnings=["핵심 재무 지표가 부족해 품질 평가는 제한적입니다."],
            details=details,
        )

    if details["latest_snapshot_age_days"] is not None and details["latest_snapshot_age_days"] > 540:
        warnings.append("최신 재무 스냅샷이 오래되어 품질 판단 신뢰도가 낮습니다.")

    if len(snapshots) < 2:
        warnings.append("재무 이력이 1건뿐이라 추세 판단은 제한적입니다.")

    equity = latest.equity
    capital_impairment_rate = latest.capital_impairment_rate
    debt_ratio = latest.debt_ratio
    current_ratio = latest.current_ratio
    operating_profit = latest.operating_profit
    net_income = latest.net_income
    operating_cash_flow = latest.operating_cash_flow
    roe = latest.roe

    if equity is not None and equity <= 0:
        blockers.append("최근 재무 기준 자본총계가 0 이하입니다.")
    if capital_impairment_rate is not None and capital_impairment_rate >= Decimal("50.00"):
        blockers.append("자본잠식률이 50% 이상입니다.")
    if blockers:
        return _build_result("Q5", blockers=blockers, warnings=warnings, details=details)

    severe_signals = 0
    if details["operating_loss_streak"] >= 2:
        severe_signals += 1
        blockers.append("최근 재무 기준 영업적자가 2회 이상 연속되었습니다.")
    if details["net_loss_streak"] >= 2:
        severe_signals += 1
        blockers.append("최근 재무 기준 순손실이 2회 이상 연속되었습니다.")
    if details["negative_cash_flow_streak"] >= 2:
        severe_signals += 1
        blockers.append("최근 재무 기준 영업현금흐름이 2회 이상 연속 음수입니다.")
    if debt_ratio is not None and debt_ratio >= Decimal("250.00"):
        severe_signals += 1
        blockers.append("부채비율이 250% 이상입니다.")
    if current_ratio is not None and current_ratio < Decimal("100.00"):
        severe_signals += 1
        blockers.append("유동비율이 100% 미만입니다.")

    if severe_signals >= 2:
        return _build_result("Q4", blockers=blockers, warnings=warnings, details=details)

    weak_signals = 0
    q3_reasons = []
    if operating_profit is not None and operating_profit < 0:
        weak_signals += 1
        q3_reasons.append("최근 영업이익이 적자입니다.")
    if net_income is not None and net_income < 0:
        weak_signals += 1
        q3_reasons.append("최근 순이익이 적자입니다.")
    if operating_cash_flow is not None and operating_cash_flow < 0:
        weak_signals += 1
        q3_reasons.append("최근 영업현금흐름이 음수입니다.")
    if debt_ratio is not None and debt_ratio >= Decimal("180.00"):
        weak_signals += 1
        q3_reasons.append("부채비율이 180% 이상입니다.")
    if current_ratio is not None and current_ratio < Decimal("120.00"):
        weak_signals += 1
        q3_reasons.append("유동비율이 120% 미만입니다.")
    if roe is not None and roe < Decimal("3.00"):
        weak_signals += 1
        q3_reasons.append("ROE가 3% 미만입니다.")
    if capital_impairment_rate is not None and capital_impairment_rate >= Decimal("20.00"):
        weak_signals += 1
        q3_reasons.append("자본잠식률이 20% 이상입니다.")

    if weak_signals >= 2:
        return _build_result("Q3", blockers=q3_reasons, warnings=warnings, details=details)

    strong_signals = 0
    if operating_profit is not None and operating_profit > 0:
        strong_signals += 1
    if net_income is not None and net_income > 0:
        strong_signals += 1
    if operating_cash_flow is not None and operating_cash_flow > 0:
        strong_signals += 1
    if debt_ratio is not None and debt_ratio <= Decimal("100.00"):
        strong_signals += 1
    if current_ratio is not None and current_ratio >= Decimal("150.00"):
        strong_signals += 1
    if roe is not None and roe >= Decimal("10.00"):
        strong_signals += 1
    if capital_impairment_rate is not None and capital_impairment_rate <= Decimal("0.00"):
        strong_signals += 1

    if strong_signals >= 6 and len(snapshots) >= 2:
        return _build_result("Q1", warnings=warnings, details=details)

    return _build_result("Q2", warnings=warnings, details=details)
