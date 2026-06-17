from __future__ import annotations

from dataclasses import dataclass, field
import logging

import pandas as pd

from holdings.models import UserHolding
from marketdata.models import DailyPrice
from marketdata.services.collectors.history_utils import (
    fetch_history_frame,
    normalize_date_value,
    normalize_frame,
    quantize_change_rate,
    quantize_price,
)
from marketdata.services.source_resolution import resolve_stock_yfinance_symbol
from stocks.models import Stock

logger = logging.getLogger(__name__)


@dataclass
class PriceCollectionReport:
    target_count: int = 0
    created_rows: int = 0
    updated_rows: int = 0
    skipped_targets: int = 0
    warnings: list[str] = field(default_factory=list)


def _get_target_stocks(*, stock_code=None, all_stocks=False):
    if stock_code:
        return Stock.objects.filter(code=stock_code)
    if all_stocks:
        return Stock.objects.filter(is_active=True).order_by("code")
    return Stock.objects.filter(holdings__is_active=True).distinct().order_by("code")


def _build_price_rows(frame):
    normalized = normalize_frame(frame)
    if normalized.empty:
        return []

    rows = []
    previous_close = None
    for _, row in normalized.iterrows():
        open_price = row.get("Open")
        high_price = row.get("High")
        low_price = row.get("Low")
        close_price = row.get("Close")

        if any(pd.isna(value) for value in (open_price, high_price, low_price, close_price)):
            continue

        change_rate = None
        if previous_close not in (None, 0):
            change_rate = quantize_change_rate(((close_price - previous_close) / previous_close) * 100)

        volume = row.get("Volume", 0)
        if pd.isna(volume):
            volume = 0

        rows.append(
            {
                "date": normalize_date_value(row["date"]),
                "open_price": quantize_price(open_price),
                "high_price": quantize_price(high_price),
                "low_price": quantize_price(low_price),
                "close_price": quantize_price(close_price),
                "volume": int(volume),
                "change_rate": change_rate,
            }
        )
        previous_close = close_price
    return rows


def collect_daily_prices(*, stock_code=None, days=240, all_stocks=False, dry_run=False):
    report = PriceCollectionReport()
    stocks = list(_get_target_stocks(stock_code=stock_code, all_stocks=all_stocks))
    report.target_count = len(stocks)

    for stock in stocks:
        resolution = resolve_stock_yfinance_symbol(stock)
        if resolution.warning or not resolution.symbol:
            report.skipped_targets += 1
            if resolution.warning:
                report.warnings.append(resolution.warning)
                logger.warning(
                    "Price collection skipped due to unresolved symbol",
                    extra={
                        "event": "price_collect_skipped",
                        "stock_code": stock.code,
                        "source": "yfinance",
                    },
                )
            continue

        frame = fetch_history_frame(resolution.symbol, days)
        rows = _build_price_rows(frame)
        if not rows:
            report.skipped_targets += 1
            report.warnings.append(f"{stock.code} {stock.name}: 가격 데이터를 수집하지 못했습니다.")
            logger.warning(
                "Price collection returned no rows",
                extra={
                    "event": "price_collect_empty",
                    "stock_code": stock.code,
                    "source": "yfinance",
                },
            )
            continue

        for row in rows:
            if dry_run:
                exists = DailyPrice.objects.filter(stock=stock, date=row["date"]).exists()
                if exists:
                    report.updated_rows += 1
                else:
                    report.created_rows += 1
                continue

            _, created = DailyPrice.objects.update_or_create(
                stock=stock,
                date=row["date"],
                defaults={
                    "open_price": row["open_price"],
                    "high_price": row["high_price"],
                    "low_price": row["low_price"],
                    "close_price": row["close_price"],
                    "volume": row["volume"],
                    "change_rate": row["change_rate"],
                },
            )
            if created:
                report.created_rows += 1
            else:
                report.updated_rows += 1

    return report
