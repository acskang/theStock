from decimal import Decimal, ROUND_HALF_UP
from math import sqrt


PRICE_QUANT = Decimal("0.01")
INDICATOR_QUANT = Decimal("0.0001")


def _to_decimal(value):
    return Decimal(str(value))


def _quantize(value, quant):
    return _to_decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def _normalize_numeric_values(values):
    return [_to_decimal(value) for value in values]


def _get_row_value(row, field_name):
    if isinstance(row, dict):
        return row[field_name]
    return getattr(row, field_name)


def calculate_moving_average(close_prices, window):
    """Calculate simple moving average from close prices."""
    if window <= 0:
        raise ValueError("window must be greater than zero.")

    values = _normalize_numeric_values(close_prices)
    if len(values) < window:
        return None

    return _quantize(sum(values[-window:]) / Decimal(window), PRICE_QUANT)


def calculate_rsi(close_prices, period=14):
    """Calculate RSI using close prices."""
    if period <= 0:
        raise ValueError("period must be greater than zero.")

    values = _normalize_numeric_values(close_prices)
    if len(values) < period + 1:
        return None

    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    recent_changes = changes[-period:]
    gains = [change for change in recent_changes if change > 0]
    losses = [abs(change) for change in recent_changes if change < 0]

    average_gain = sum(gains, Decimal("0")) / Decimal(period)
    average_loss = sum(losses, Decimal("0")) / Decimal(period)

    if average_gain == 0 and average_loss == 0:
        return _quantize(Decimal("50"), INDICATOR_QUANT)
    if average_loss == 0:
        return _quantize(Decimal("100"), INDICATOR_QUANT)

    relative_strength = average_gain / average_loss
    rsi = Decimal("100") - (Decimal("100") / (Decimal("1") + relative_strength))
    return _quantize(rsi, INDICATOR_QUANT)


def calculate_ema(values, period):
    """Calculate EMA from a sequence of values."""
    if period <= 0:
        raise ValueError("period must be greater than zero.")

    normalized = _normalize_numeric_values(values)
    if len(normalized) < period:
        return None

    multiplier = Decimal("2") / Decimal(period + 1)
    ema = sum(normalized[:period]) / Decimal(period)
    for price in normalized[period:]:
        ema = ((price - ema) * multiplier) + ema
    return ema


def _calculate_ema_series(values, period):
    normalized = _normalize_numeric_values(values)
    if len(normalized) < period:
        return []

    multiplier = Decimal("2") / Decimal(period + 1)
    ema = sum(normalized[:period]) / Decimal(period)
    series = [ema]
    for price in normalized[period:]:
        ema = ((price - ema) * multiplier) + ema
        series.append(ema)
    return series


def calculate_macd(close_prices, short_period=12, long_period=26, signal_period=9):
    """Calculate MACD, signal, and histogram."""
    if short_period <= 0 or long_period <= 0 or signal_period <= 0:
        raise ValueError("period values must be greater than zero.")

    values = _normalize_numeric_values(close_prices)
    if len(values) < long_period + signal_period - 1:
        return {"macd": None, "signal": None, "histogram": None}

    short_series = _calculate_ema_series(values, short_period)
    long_series = _calculate_ema_series(values, long_period)
    if not short_series or not long_series:
        return {"macd": None, "signal": None, "histogram": None}

    short_start_index = short_period - 1
    long_start_index = long_period - 1
    macd_values = []
    for price_index in range(long_start_index, len(values)):
        short_value = short_series[price_index - short_start_index]
        long_value = long_series[price_index - long_start_index]
        macd_values.append(short_value - long_value)

    signal_series = _calculate_ema_series(macd_values, signal_period)
    if not signal_series:
        return {"macd": None, "signal": None, "histogram": None}

    macd_value = macd_values[-1]
    signal_value = signal_series[-1]
    histogram_value = macd_value - signal_value
    return {
        "macd": _quantize(macd_value, INDICATOR_QUANT),
        "signal": _quantize(signal_value, INDICATOR_QUANT),
        "histogram": _quantize(histogram_value, INDICATOR_QUANT),
    }


def calculate_atr(price_rows, period=14):
    """Calculate ATR from rows containing high, low, and close."""
    if period <= 0:
        raise ValueError("period must be greater than zero.")

    rows = list(price_rows)
    if len(rows) < period + 1:
        return None

    recent_rows = rows[-(period + 1):]
    true_ranges = []
    previous_close = _to_decimal(_get_row_value(recent_rows[0], "close_price"))
    for row in recent_rows[1:]:
        high_price = _to_decimal(_get_row_value(row, "high_price"))
        low_price = _to_decimal(_get_row_value(row, "low_price"))
        close_price = _to_decimal(_get_row_value(row, "close_price"))
        true_range = max(
            high_price - low_price,
            abs(high_price - previous_close),
            abs(low_price - previous_close),
        )
        true_ranges.append(true_range)
        previous_close = close_price

    return _quantize(sum(true_ranges) / Decimal(period), INDICATOR_QUANT)


def calculate_volume_ma(volumes, window=20):
    """Calculate average volume."""
    if window <= 0:
        raise ValueError("window must be greater than zero.")

    normalized = [int(value) for value in volumes]
    if len(normalized) < window:
        return None

    average = Decimal(sum(normalized[-window:])) / Decimal(window)
    return int(_quantize(average, Decimal("1")))


def calculate_bollinger_bands(close_prices, window=20, num_std=2):
    """Calculate Bollinger Bands."""
    if window <= 0:
        raise ValueError("window must be greater than zero.")

    values = _normalize_numeric_values(close_prices)
    if len(values) < window:
        return {"upper": None, "middle": None, "lower": None}

    window_values = values[-window:]
    middle = sum(window_values) / Decimal(window)
    variance = sum((value - middle) ** 2 for value in window_values) / Decimal(window)
    std_dev = _to_decimal(sqrt(float(variance)))
    upper = middle + (std_dev * Decimal(str(num_std)))
    lower = middle - (std_dev * Decimal(str(num_std)))

    return {
        "upper": _quantize(upper, PRICE_QUANT),
        "middle": _quantize(middle, PRICE_QUANT),
        "lower": _quantize(lower, PRICE_QUANT),
    }
