from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from indicators.services.indicator_service import calculate_volume_ma
from marketdata.services.price_service import extract_volumes


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


def find_support_zone(price_rows, lookback=60):
    """Find support zone from recent price rows."""
    rows = sorted(price_rows, key=lambda row: _get_row_value(row, "date"))
    if not rows:
        return {
            "support_price": None,
            "lower_bound": None,
            "upper_bound": None,
            "method": None,
            "touch_count": 0,
        }

    recent_rows = rows[-lookback:]
    current_price = _to_decimal(_get_row_value(recent_rows[-1], "close_price"))
    low_prices = [_to_decimal(_get_row_value(row, "low_price")) for row in recent_rows]
    candidate_lower = current_price * Decimal("0.90")
    candidate_upper = current_price * Decimal("1.10")
    candidate_lows = [low_price for low_price in low_prices if candidate_lower <= low_price <= candidate_upper]

    bucket_support = None
    touch_count = 0
    if candidate_lows:
        bucket_size = max(current_price * Decimal("0.01"), Decimal("1"))
        buckets = defaultdict(list)
        for low_price in candidate_lows:
            bucket_key = int((low_price / bucket_size).to_integral_value(rounding=ROUND_HALF_UP))
            buckets[bucket_key].append(low_price)

        repeated_buckets = [
            (_quantize(sum(values) / Decimal(len(values))), len(values))
            for values in buckets.values()
            if len(values) >= 2
        ]
        if repeated_buckets:
            bucket_support, touch_count = min(
                repeated_buckets,
                key=lambda item: abs(current_price - item[0]),
            )

    if bucket_support is not None:
        support_price = bucket_support
        method = "bucket"
    else:
        support_price = min(low_prices)
        method = "lowest_low"
        touch_count = 1

    return {
        "support_price": support_price,
        "lower_bound": _quantize(support_price * Decimal("0.97")),
        "upper_bound": _quantize(support_price * Decimal("1.03")),
        "method": method,
        "touch_count": touch_count,
    }


def calculate_support_score(price_rows):
    """Calculate support score."""
    rows = sorted(price_rows, key=lambda row: _get_row_value(row, "date"))
    zone = find_support_zone(rows)
    if zone["support_price"] is None:
        return {
            "score": 0,
            "reasons": ["지지선 후보를 찾을 수 없어 지지선 점수를 중립으로 처리했습니다."],
            "details": {
                "support_price": None,
                "distance_rate": None,
            },
        }

    latest_row = rows[-1]
    current_price = _to_decimal(_get_row_value(latest_row, "close_price"))
    latest_low = _to_decimal(_get_row_value(latest_row, "low_price"))
    latest_volume = _get_row_value(latest_row, "volume")
    support_price = zone["support_price"]
    lower_bound = zone["lower_bound"]
    upper_bound = zone["upper_bound"]

    score = 0
    reasons = []

    if lower_bound <= current_price <= upper_bound:
        score += 15
        reasons.append("현재가가 주요 지지선 근처에 있습니다.")

    if latest_low < lower_bound <= current_price:
        score += 10
        reasons.append("지지선 이탈 후 회복 흐름이 확인됩니다.")
    elif current_price < lower_bound:
        score -= 20
        reasons.append("현재가가 주요 지지선을 이탈했습니다.")

    volume_ma20 = calculate_volume_ma(extract_volumes(rows), 20)
    if lower_bound <= current_price <= upper_bound and volume_ma20 is not None and latest_volume >= volume_ma20:
        score += 5
        reasons.append("지지선 부근에서 거래량이 증가했습니다.")

    distance_rate = _quantize(((current_price - support_price) / support_price) * Decimal("100"), Decimal("0.0001"))
    return {
        "score": max(-20, min(20, score)),
        "reasons": reasons,
        "details": {
            "support_price": support_price,
            "distance_rate": distance_rate,
            "method": zone["method"],
            "touch_count": zone["touch_count"],
        },
    }
