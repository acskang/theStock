from __future__ import annotations

from dataclasses import dataclass, field
import logging

import pandas as pd

from marketdata.models import MarketIndex
from marketdata.services.collectors.history_utils import (
    fetch_history_frame,
    normalize_date_value,
    normalize_frame,
    quantize_change_rate,
    quantize_decimal,
)
from marketdata.services.source_resolution import get_market_index_targets

logger = logging.getLogger(__name__)


@dataclass
class MarketIndexCollectionReport:
    target_count: int = 0
    created_rows: int = 0
    updated_rows: int = 0
    skipped_targets: int = 0
    warnings: list[str] = field(default_factory=list)


def _build_market_index_rows(frame):
    normalized = normalize_frame(frame)
    if normalized.empty:
        return []

    rows = []
    previous_close = None
    for _, row in normalized.iterrows():
        close_value = row.get("Close")
        if pd.isna(close_value):
            continue

        change_rate = None
        if previous_close not in (None, 0):
            change_rate = quantize_change_rate(((close_value - previous_close) / previous_close) * 100)

        rows.append(
            {
                "date": normalize_date_value(row["date"]),
                "close_value": quantize_decimal(close_value, "0.0001"),
                "change_rate": change_rate,
            }
        )
        previous_close = close_value
    return rows


def collect_market_indices(*, codes=None, days=240, dry_run=False):
    report = MarketIndexCollectionReport()
    targets = get_market_index_targets(codes=codes)
    report.target_count = len(targets)

    for target in targets:
        frame = fetch_history_frame(target.symbol, days)
        rows = _build_market_index_rows(frame)
        if not rows:
            report.skipped_targets += 1
            report.warnings.append(f"{target.code}: 시장지수 데이터를 수집하지 못했습니다.")
            logger.warning(
                "Market index collection returned no rows",
                extra={
                    "event": "market_index_collect_empty",
                    "stock_code": target.code,
                    "source": "yfinance",
                },
            )
            continue

        for row in rows:
            if dry_run:
                exists = MarketIndex.objects.filter(code=target.code, date=row["date"]).exists()
                if exists:
                    report.updated_rows += 1
                else:
                    report.created_rows += 1
                continue

            _, created = MarketIndex.objects.update_or_create(
                code=target.code,
                date=row["date"],
                defaults={
                    "name": target.name,
                    "close_value": row["close_value"],
                    "change_rate": row["change_rate"],
                },
            )
            if created:
                report.created_rows += 1
            else:
                report.updated_rows += 1

    return report
