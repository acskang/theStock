from decimal import Decimal, ROUND_HALF_UP

from indicators.services.indicator_service import calculate_moving_average
from holdings.models import UserHolding


def _to_decimal(value):
    if value is None:
        return None
    return Decimal(str(value))


def _quantize(value, quant=Decimal("0.01")):
    return _to_decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def _get_row_value(row, field_name):
    if isinstance(row, dict):
        return row[field_name]
    return getattr(row, field_name)


def _rolling_average(values):
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(len(values))


def _resolve_indicator_value(indicators, key):
    if indicators is None:
        return None
    if isinstance(indicators, dict):
        return indicators.get(key)
    return getattr(indicators, key, None)


def is_recent_low_higher(price_rows, window=20):
    """Return whether recent low is higher than previous low."""
    rows = sorted(price_rows, key=lambda row: _get_row_value(row, "date"))
    if len(rows) < window:
        return None

    recent_rows = rows[-window:]
    midpoint = window // 2
    previous_low = min(_to_decimal(_get_row_value(row, "low_price")) for row in recent_rows[:midpoint])
    recent_low = min(_to_decimal(_get_row_value(row, "low_price")) for row in recent_rows[midpoint:])
    return recent_low > previous_low


def is_ma_decline_slowing(close_prices, window=20):
    values = [_to_decimal(value) for value in close_prices]
    if len(values) < window + 10:
        return None

    ma_values = []
    for index in range(len(values) - 9, len(values) + 1):
        subset = values[:index]
        moving_average = calculate_moving_average(subset, window)
        if moving_average is not None:
            ma_values.append(_to_decimal(moving_average))

    if len(ma_values) < 6:
        return None

    changes = [ma_values[index] - ma_values[index - 1] for index in range(1, len(ma_values))]
    midpoint = len(changes) // 2
    previous_average_change = _rolling_average(changes[:midpoint])
    recent_average_change = _rolling_average(changes[midpoint:])
    if previous_average_change is None or recent_average_change is None:
        return None
    return recent_average_change > previous_average_change


def calculate_trend_score(price_rows, indicators=None):
    """Calculate trend score from prices and indicators."""
    rows = sorted(price_rows, key=lambda row: _get_row_value(row, "date"))
    if not rows:
        return {
            "score": 0,
            "reasons": ["가격 데이터가 없어 추세 점수를 계산할 수 없습니다."],
            "details": {
                "current_price": None,
                "ma5": None,
                "ma20": None,
                "ma60": None,
            },
        }

    close_prices = [_get_row_value(row, "close_price") for row in rows]
    current_price = _to_decimal(_get_row_value(rows[-1], "close_price"))
    ma5 = _resolve_indicator_value(indicators, "ma5") or calculate_moving_average(close_prices, 5)
    ma20 = _resolve_indicator_value(indicators, "ma20") or calculate_moving_average(close_prices, 20)
    ma60 = _resolve_indicator_value(indicators, "ma60") or calculate_moving_average(close_prices, 60)
    previous_ma5 = calculate_moving_average(close_prices[:-1], 5) if len(close_prices) >= 6 else None
    previous_ma20 = calculate_moving_average(close_prices[:-1], 20) if len(close_prices) >= 21 else None
    previous_ma60 = calculate_moving_average(close_prices[:-1], 60) if len(close_prices) >= 61 else None

    recent_low_higher = is_recent_low_higher(rows)
    ma20_decline_slowing = is_ma_decline_slowing(close_prices, 20)

    score = 0
    reasons = []

    if ma5 is not None and current_price > _to_decimal(ma5):
        score += 5
        reasons.append("현재가가 MA5 위에 있습니다.")

    if ma5 is not None and previous_ma5 is not None and _to_decimal(ma5) > _to_decimal(previous_ma5):
        score += 5
        reasons.append("MA5가 상승 전환 흐름을 보이고 있습니다.")

    if ma20 is not None and current_price >= (_to_decimal(ma20) * Decimal("0.98")):
        score += 5
        if current_price >= _to_decimal(ma20):
            reasons.append("현재가가 MA20 이상입니다.")
        else:
            reasons.append("현재가가 MA20 근처까지 회복했습니다.")

    if recent_low_higher is True:
        score += 5
        reasons.append("최근 저점이 이전 저점보다 높습니다.")
    elif recent_low_higher is False:
        score -= 10
        reasons.append("최근 저점이 이전 저점보다 낮아 하락 추세가 이어지고 있습니다.")

    if ma20_decline_slowing is True:
        score += 5
        reasons.append("MA20 하락 기울기가 둔화되고 있습니다.")

    if None not in (ma5, ma20, ma60) and current_price < _to_decimal(ma5) < _to_decimal(ma20) < _to_decimal(ma60):
        score -= 10
        reasons.append("현재가와 이동평균선 배열이 약세 구간에 있습니다.")

    if None not in (ma20, ma60, previous_ma20, previous_ma60):
        if _to_decimal(ma20) < _to_decimal(previous_ma20) and _to_decimal(ma60) < _to_decimal(previous_ma60):
            score -= 5
            reasons.append("MA20과 MA60이 모두 하락 중입니다.")

    if ma20 is None or ma60 is None or recent_low_higher is None:
        reasons.append("최근 가격 데이터가 부족해 일부 추세 항목을 중립으로 처리했습니다.")

    score = max(0, min(25, score))
    return {
        "score": score,
        "reasons": reasons,
        "details": {
            "current_price": current_price,
            "ma5": ma5,
            "ma20": ma20,
            "ma60": ma60,
        },
    }


def calculate_total_score(*, trend_score, support_score, volume_score, flow_score, market_score, risk_score):
    """Calculate final normalized score."""
    raw_score = trend_score + support_score + volume_score + flow_score + market_score + risk_score
    final_score = max(0, min(100, raw_score))
    return {
        "raw_score": raw_score,
        "final_score": final_score,
    }


def convert_score_to_grade(score):
    """Convert score to A/B/C/D grade."""
    if score >= 75:
        return "A"
    if score >= 55:
        return "B"
    if score >= 35:
        return "C"
    return "D"


def get_decision_text(grade):
    """Return user-facing decision text for a grade."""
    mapping = {
        "A": "추가 매수 가능성 검토 구간",
        "B": "관찰 구간",
        "C": "물타기 금지 구간",
        "D": "손절 또는 비중 축소 기준 점검 구간",
    }
    return mapping.get(grade, "관찰 구간")


def build_reason_summary(grade, reasons):
    """Build a short summary from grade and reasons."""
    lead_reason = reasons[0] if reasons else ""
    templates = {
        "A": "기술적 지표와 수급 조건이 비교적 우호적이며, 주요 위험 이벤트가 확인되지 않았습니다.",
        "B": "일부 반등 신호는 있으나 추세 전환 확인이 충분하지 않아 관찰이 필요한 구간입니다.",
        "C": "하락 추세 또는 리스크 요인이 있어 추가 매수는 신중해야 하는 구간입니다.",
        "D": "위험 신호가 강해 추가 매수보다 손절 또는 비중 축소 기준 점검이 필요한 구간입니다.",
    }
    summary = templates.get(grade, templates["B"])
    if lead_reason:
        return f"{summary} 주요 판단 근거: {lead_reason}"
    return summary


def calculate_suggested_budget(holding, grade):
    """Calculate suggested budget based on grade and risk level."""
    if grade in {"C", "D"}:
        return Decimal("0.00")

    base_ratio = {
        "A": Decimal("0.3"),
        "B": Decimal("0.1"),
    }.get(grade, Decimal("0"))
    risk_multiplier = {
        UserHolding.RISK_CONSERVATIVE: Decimal("0.5"),
        UserHolding.RISK_NORMAL: Decimal("1.0"),
        UserHolding.RISK_AGGRESSIVE: Decimal("1.2"),
    }.get(holding.risk_level, Decimal("1.0"))

    budget = _to_decimal(holding.max_additional_budget) * base_ratio * risk_multiplier
    return _quantize(budget, Decimal("0.01"))


def calculate_stop_loss_price(current_price, support_price=None, atr14=None):
    """Calculate stop-loss review price."""
    current = _to_decimal(current_price)
    support = _to_decimal(support_price)
    atr = _to_decimal(atr14)

    if support is not None:
        return _quantize(support * Decimal("0.97"), Decimal("0.01"))

    if atr is not None:
        fallback = current - (atr * Decimal("1.5"))
        if fallback < 0:
            fallback = Decimal("0")
        return _quantize(fallback, Decimal("0.01"))

    return _quantize(current * Decimal("0.93"), Decimal("0.01"))
