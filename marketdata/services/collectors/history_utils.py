from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

import pandas as pd
import yfinance as yf


def fetch_history_frame(symbol: str, days: int):
    calendar_days = max(days * 2, 60)
    frame = yf.Ticker(symbol).history(period=f"{calendar_days}d", auto_adjust=False)
    if frame is None or frame.empty:
        return pd.DataFrame()
    return frame.tail(days).copy()


def quantize_decimal(value, quant):
    return Decimal(str(value)).quantize(Decimal(quant), rounding=ROUND_HALF_UP)


def quantize_price(value):
    return quantize_decimal(value, "0.01")


def quantize_change_rate(value):
    return quantize_decimal(value, "0.0001")


def normalize_frame(frame):
    if frame is None or frame.empty:
        return pd.DataFrame()

    normalized = frame.reset_index()
    date_column = "Date" if "Date" in normalized.columns else normalized.columns[0]
    return normalized.rename(columns={date_column: "date"})


def normalize_date_value(value):
    if hasattr(value, "date"):
        return value.date()
    return value
