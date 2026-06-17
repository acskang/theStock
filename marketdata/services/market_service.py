from decimal import Decimal, ROUND_HALF_UP

from indicators.services.indicator_service import calculate_moving_average

from marketdata.models import MarketIndex


MARKET_CODE_MAP = {
    "KOSPI": "KOSPI",
    "KOSDAQ": "KOSDAQ",
    "KONEX": "KOSDAQ",
    "ETF": "KOSPI",
    "ETN": "KOSPI",
}
FX_CODES = ("USDKRW", "USD/KRW", "USDKRW")
GLOBAL_INDEX_CODES = ("NASDAQ", "IXIC", "NASDAQ100")


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


def _market_code_for_stock(stock):
    return MARKET_CODE_MAP.get(stock.market, "KOSPI")


def _get_recent_return(rows, periods=5):
    ordered_rows = sorted(rows, key=lambda row: _get_row_value(row, "date"))
    if len(ordered_rows) < periods:
        return None

    window_rows = ordered_rows[-periods:]
    first_close = _to_decimal(_get_row_value(window_rows[0], "close_value"))
    last_close = _to_decimal(_get_row_value(window_rows[-1], "close_value"))
    if first_close == 0:
        return None
    return _quantize(((last_close - first_close) / first_close) * Decimal("100"))


def _get_first_available_rows(codes, limit=60):
    for code in codes:
        rows = get_recent_market_indices(code, limit=limit, ascending=True)
        if rows:
            return code, rows
    return None, []


def get_latest_market_index(code):
    """Return the latest MarketIndex by code."""
    return MarketIndex.objects.filter(code=code).order_by("-date").first()


def get_recent_market_indices(code, limit=60, ascending=True):
    """Return recent MarketIndex rows for the given code."""
    queryset = MarketIndex.objects.filter(code=code).order_by("-date")
    if limit is not None:
        queryset = queryset[:limit]

    rows = list(queryset)
    if ascending:
        rows.reverse()
    return rows


def get_market_context(stock):
    """Return market context for the stock's market."""
    market_code = _market_code_for_stock(stock)
    fx_code, fx_rows = _get_first_available_rows(FX_CODES)
    global_index_code, global_index_rows = _get_first_available_rows(GLOBAL_INDEX_CODES)
    return {
        "market_code": market_code,
        "market_index_rows": get_recent_market_indices(market_code, limit=60, ascending=True),
        "fx_code": fx_code,
        "fx_rows": fx_rows,
        "global_index_code": global_index_code,
        "global_index_rows": global_index_rows,
    }


def calculate_market_score(stock, market_index_rows, fx_rows=None, global_index_rows=None):
    """Calculate market context score."""
    rows = sorted(market_index_rows, key=lambda row: _get_row_value(row, "date"))
    if not rows:
        return {
            "score": 0,
            "reasons": ["시장 지수 데이터가 부족해 시장 점수를 중립으로 처리했습니다."],
            "details": {
                "market_code": _market_code_for_stock(stock),
                "market_above_ma20": None,
                "market_recent_return_5d": None,
            },
        }

    close_values = [_get_row_value(row, "close_value") for row in rows]
    latest_row = rows[-1]
    latest_close = _to_decimal(_get_row_value(latest_row, "close_value"))
    latest_change_rate = _to_decimal(_get_row_value(latest_row, "change_rate"))
    ma20 = calculate_moving_average(close_values, 20)
    previous_ma20 = calculate_moving_average(close_values[:-1], 20) if len(close_values) >= 21 else None
    recent_return_5d = _get_recent_return(rows, 5)
    market_above_ma20 = ma20 is not None and latest_close > ma20
    market_ma20_falling = ma20 is not None and previous_ma20 is not None and ma20 < previous_ma20

    score = 0
    reasons = []

    if market_above_ma20:
        score += 5
        reasons.append("해당 시장 지수가 20일선 위에 있습니다.")

    if recent_return_5d is not None and recent_return_5d > 0:
        score += 5
        reasons.append("해당 시장 지수가 최근 반등 흐름을 보이고 있습니다.")

    market_crash = False
    if latest_change_rate is not None and latest_change_rate <= Decimal("-2.5"):
        market_crash = True
    if recent_return_5d is not None and recent_return_5d <= Decimal("-5"):
        market_crash = True
    if ma20 is not None and latest_close < ma20 and market_ma20_falling:
        market_crash = True

    if market_crash:
        score -= 15
        reasons.append("시장 급락 신호가 감지되어 보수적으로 평가했습니다.")

    if global_index_rows:
        global_rows = sorted(global_index_rows, key=lambda row: _get_row_value(row, "date"))
        global_close_values = [_get_row_value(row, "close_value") for row in global_rows]
        global_latest_row = global_rows[-1]
        global_latest_close = _to_decimal(_get_row_value(global_latest_row, "close_value"))
        global_change_rate = _to_decimal(_get_row_value(global_latest_row, "change_rate"))
        global_ma20 = calculate_moving_average(global_close_values, 20)
        global_recent_return_5d = _get_recent_return(global_rows, 5)

        if (
            global_recent_return_5d is not None and global_recent_return_5d >= 0
        ) or (global_ma20 is not None and global_latest_close >= global_ma20):
            score += 5
            reasons.append("미국 주요 지수가 비교적 안정적인 흐름을 보이고 있습니다.")
        elif (
            global_change_rate is not None and global_change_rate <= Decimal("-2.5")
        ) or (global_recent_return_5d is not None and global_recent_return_5d <= Decimal("-5")):
            score -= 5
            reasons.append("미국 주요 지수 급락이 부담 요인으로 작용합니다.")

    fx_surge = False
    fx_recent_return_5d = None
    if fx_rows:
        ordered_fx_rows = sorted(fx_rows, key=lambda row: _get_row_value(row, "date"))
        fx_close_values = [_get_row_value(row, "close_value") for row in ordered_fx_rows]
        fx_latest_close = _to_decimal(_get_row_value(ordered_fx_rows[-1], "close_value"))
        fx_ma20 = calculate_moving_average(fx_close_values, 20)
        fx_recent_return_5d = _get_recent_return(ordered_fx_rows, 5)
        if fx_recent_return_5d is not None and fx_recent_return_5d >= Decimal("2"):
            fx_surge = True
        if fx_ma20 is not None and fx_latest_close > (fx_ma20 * Decimal("1.02")):
            fx_surge = True

    if fx_surge:
        score -= 5
        reasons.append("환율 급등 신호가 확인되어 시장 점수를 낮췄습니다.")

    score = max(-25, min(15, score))
    return {
        "score": score,
        "reasons": reasons,
        "details": {
            "market_code": _market_code_for_stock(stock),
            "market_above_ma20": market_above_ma20,
            "market_recent_return_5d": recent_return_5d,
            "fx_recent_return_5d": fx_recent_return_5d,
        },
    }
