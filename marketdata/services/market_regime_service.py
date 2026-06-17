from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.db.models import Count

from marketdata.models import MarketIndex
from marketdata.services.market_service import get_recent_market_indices


REGIME_CONFIG = {
    "risk_on": {"score_adjustment": 5, "score_multiplier": Decimal("1.10"), "grade_cap": None},
    "pullback": {"score_adjustment": 0, "score_multiplier": Decimal("1.00"), "grade_cap": None},
    "sideways": {"score_adjustment": -2, "score_multiplier": Decimal("0.95"), "grade_cap": "A"},
    "risk_off": {"score_adjustment": -10, "score_multiplier": Decimal("0.75"), "grade_cap": "B"},
    "capitulation": {"score_adjustment": -15, "score_multiplier": Decimal("0.60"), "grade_cap": "C"},
    "rebound": {"score_adjustment": 0, "score_multiplier": Decimal("1.00"), "grade_cap": "B"},
    "unknown": {"score_adjustment": -5, "score_multiplier": Decimal("0.90"), "grade_cap": "B"},
}
PREFERRED_CODES = ("KOSPI", "KOSDAQ", "KS11", "KQ11")


@dataclass(frozen=True)
class MarketRegimeResult:
    regime: str
    score_adjustment: int
    score_multiplier: Decimal
    grade_cap: Optional[str]
    reasons: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


def _to_decimal(value):
    return Decimal(str(value))


def _quantize(value, quant=Decimal("0.0001")):
    return _to_decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def _get_row_value(row, field_name):
    if isinstance(row, dict):
        return row[field_name]
    return getattr(row, field_name)


def _calculate_return(rows, periods):
    ordered_rows = sorted(rows, key=lambda row: _get_row_value(row, "date"))
    if len(ordered_rows) < periods:
        return None
    window = ordered_rows[-periods:]
    first_close = _to_decimal(_get_row_value(window[0], "close_value"))
    last_close = _to_decimal(_get_row_value(window[-1], "close_value"))
    if first_close == 0:
        return None
    return _quantize(((last_close - first_close) / first_close) * Decimal("100"))


def _select_reference_market_rows():
    for code in PREFERRED_CODES:
        rows = get_recent_market_indices(code, limit=60, ascending=True)
        if rows:
            return code, rows

    fallback = (
        MarketIndex.objects.values("code")
        .annotate(row_count=Count("id"))
        .order_by("-row_count", "code")
        .first()
    )
    if fallback:
        code = fallback["code"]
        return code, get_recent_market_indices(code, limit=60, ascending=True)
    return None, []


def _build_result(regime, reasons, details):
    config = REGIME_CONFIG[regime]
    return MarketRegimeResult(
        regime=regime,
        score_adjustment=config["score_adjustment"],
        score_multiplier=config["score_multiplier"],
        grade_cap=config["grade_cap"],
        reasons=reasons,
        details=details,
    )


def evaluate_market_regime(stock=None) -> MarketRegimeResult:
    del stock

    market_code, rows = _select_reference_market_rows()
    if len(rows) < 20:
        return _build_result(
            "unknown",
            ["시장 국면을 판단하기에 데이터가 부족합니다."],
            {"market_code": market_code, "row_count": len(rows)},
        )

    return_20d = _calculate_return(rows, 20)
    return_60d = _calculate_return(rows, 60)
    return_5d = _calculate_return(rows, 5)
    details = {
        "market_code": market_code,
        "row_count": len(rows),
        "return_20d": return_20d,
        "return_60d": return_60d,
        "return_5d": return_5d,
    }

    if return_20d is None or return_5d is None:
        return _build_result("unknown", ["핵심 시장 수익률 계산이 불가능합니다."], details)

    if return_60d is not None and return_20d > Decimal("3") and return_60d > Decimal("5"):
        return _build_result("risk_on", ["시장 전반이 상승 우호 국면에 가깝습니다."], details)
    if return_20d < Decimal("-12") or return_5d <= Decimal("-10"):
        return _build_result("capitulation", ["시장 투매 구간 신호가 강해 매우 보수적으로 접근해야 합니다."], details)
    if return_20d < Decimal("-8") or return_5d <= Decimal("-6"):
        return _build_result("risk_off", ["시장 위험 회피 흐름이 강해 추가 매수 검토를 제한해야 합니다."], details)
    if return_60d is not None and return_60d > Decimal("3") and Decimal("-5") <= return_20d <= Decimal("0"):
        return _build_result("pullback", ["상승 추세 내 조정 구간으로 해석할 수 있습니다."], details)
    if return_60d is not None and Decimal("-3") <= return_20d <= Decimal("3") and Decimal("-5") <= return_60d <= Decimal("5"):
        return _build_result("sideways", ["시장 방향성이 뚜렷하지 않은 박스권 흐름입니다."], details)
    if return_60d is not None and return_20d > Decimal("5") and return_60d < Decimal("0"):
        return _build_result("rebound", ["하락 이후 초기 반등 국면으로 볼 수 있습니다."], details)
    return _build_result("unknown", ["시장 국면을 명확히 분류하기 어려워 보수적으로 해석합니다."], details)
