from decimal import Decimal, ROUND_HALF_UP

from indicators.services.indicator_service import calculate_volume_ma
from marketdata.services.price_service import extract_volumes


def _to_decimal(value):
    if value is None:
        return None
    return Decimal(str(value))


def _quantize(value, quant=Decimal("0.0001")):
    return _to_decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def _get_row_value(row, field_name):
    if isinstance(row, dict):
        return row[field_name]
    return getattr(row, field_name)


def calculate_volume_score(price_rows):
    """Calculate volume score from price rows."""
    rows = sorted(price_rows, key=lambda row: _get_row_value(row, "date"))
    if len(rows) < 2:
        return {
            "score": 0,
            "reasons": ["거래량 점수를 계산하기에 가격 데이터가 부족합니다."],
            "details": {
                "latest_volume": None,
                "volume_ma20": None,
                "volume_ratio": None,
            },
        }

    latest_row = rows[-1]
    previous_row = rows[-2]
    latest_volume = int(_get_row_value(latest_row, "volume"))
    volume_ma20 = calculate_volume_ma(extract_volumes(rows), 20)
    if volume_ma20 is None:
        return {
            "score": 0,
            "reasons": ["최근 20거래일 거래량 데이터가 부족해 거래량 점수를 중립으로 처리했습니다."],
            "details": {
                "latest_volume": latest_volume,
                "volume_ma20": None,
                "volume_ratio": None,
            },
        }

    latest_close = _to_decimal(_get_row_value(latest_row, "close_price"))
    previous_close = _to_decimal(_get_row_value(previous_row, "close_price"))
    latest_high = _to_decimal(_get_row_value(latest_row, "high_price"))
    latest_low = _to_decimal(_get_row_value(latest_row, "low_price"))
    volume_ratio = _quantize(Decimal(latest_volume) / Decimal(volume_ma20))
    score = 0
    reasons = []

    if volume_ratio >= Decimal("1.5"):
        score += 5
        reasons.append("최근 거래량이 20일 평균 대비 150% 이상입니다.")

    close_position = None
    if latest_high != latest_low:
        close_position = (latest_close - latest_low) / (latest_high - latest_low)
        if volume_ratio >= Decimal("1.5") and close_position >= Decimal("0.6") and latest_close >= previous_close * Decimal("0.98"):
            score += 10
            reasons.append("하락 압력 속에서도 거래량 증가와 가격 방어가 확인됩니다.")

    if latest_close > previous_close and latest_volume > volume_ma20:
        score += 10
        reasons.append("반등 구간에서 거래량이 함께 증가했습니다.")
    elif latest_close < previous_close and latest_volume > volume_ma20:
        score -= 10
        reasons.append("하락 구간에서 거래량이 증가해 매도 압력이 강합니다.")
    elif latest_close > previous_close and latest_volume <= volume_ma20:
        score -= 5
        reasons.append("반등 시도가 있으나 거래량 뒷받침은 약합니다.")

    return {
        "score": max(-15, min(20, score)),
        "reasons": reasons,
        "details": {
            "latest_volume": latest_volume,
            "volume_ma20": volume_ma20,
            "volume_ratio": volume_ratio,
            "close_position": _quantize(close_position) if close_position is not None else None,
        },
    }
