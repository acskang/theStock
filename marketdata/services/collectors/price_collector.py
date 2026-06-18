from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging

import pandas as pd
import requests
from bs4 import BeautifulSoup

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

NAVER_DAILY_PRICE_URL = "https://finance.naver.com/item/sise_day.naver"
NAVER_USER_AGENT = "Mozilla/5.0 (compatible; theStock price collector)"


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


def _is_krx_stock_code(stock_code: str) -> bool:
    return len(str(stock_code)) == 6 and str(stock_code).isdigit()


def _parse_naver_date(value):
    return datetime.strptime(str(value).strip().replace(".", "-"), "%Y-%m-%d").date()


def _parse_naver_int(value):
    normalized = str(value or "").replace(",", "").strip()
    if not normalized:
        return 0
    return int(normalized)


def _fetch_naver_daily_price_frame(stock_code: str, days: int):
    rows = []
    max_pages = max((days // 10) + 3, 3)
    for page in range(1, max_pages + 1):
        response = requests.get(
            NAVER_DAILY_PRICE_URL,
            params={"code": stock_code, "page": page},
            headers={"User-Agent": NAVER_USER_AGENT},
            timeout=10,
        )
        response.raise_for_status()
        response.encoding = "euc-kr"
        page_rows = _parse_naver_daily_price_rows(response.text)
        if not page_rows:
            break
        rows.extend(page_rows)
        if len(rows) >= days:
            break
    if not rows:
        return pd.DataFrame()
    rows = sorted({row["Date"]: row for row in rows}.values(), key=lambda row: row["Date"])
    return pd.DataFrame(rows[-days:])


def _parse_naver_daily_price_rows(html: str):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="type2")
    if table is None:
        return []

    rows = []
    for tr in table.find_all("tr"):
        cells = [cell.get_text(" ", strip=True) for cell in tr.find_all("td")]
        if len(cells) < 7:
            continue
        try:
            row_date = _parse_naver_date(cells[0])
            close_price = _parse_naver_int(cells[1])
            open_price = _parse_naver_int(cells[3])
            high_price = _parse_naver_int(cells[4])
            low_price = _parse_naver_int(cells[5])
            volume = _parse_naver_int(cells[6])
        except Exception:
            continue
        rows.append(
            {
                "Date": row_date,
                "Open": open_price,
                "High": high_price,
                "Low": low_price,
                "Close": close_price,
                "Volume": volume,
            }
        )
    return rows


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
        if (frame is None or frame.empty) and _is_krx_stock_code(stock.code):
            frame = _fetch_naver_daily_price_frame(stock.code, days)
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
