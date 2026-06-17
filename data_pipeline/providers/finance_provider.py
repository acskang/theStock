from data_pipeline.dataclasses import DailyPriceRow, MarketIndexRow
from marketdata.services.collectors.history_utils import fetch_history_frame
from marketdata.services.collectors.market_index_collector import _build_market_index_rows
from marketdata.services.collectors.price_collector import _build_price_rows
from marketdata.services.source_resolution import get_market_index_targets, resolve_stock_yfinance_symbol

from .base import BaseDataProvider


class FinanceProvider(BaseDataProvider):
    provider_name = "finance"

    def get_daily_price_rows(self, stock, days: int):
        resolution = resolve_stock_yfinance_symbol(stock)
        if resolution.warning or not resolution.symbol:
            raise ValueError(resolution.warning or f"{stock.code}: price symbol could not be resolved.")

        rows = _build_price_rows(fetch_history_frame(resolution.symbol, days))
        return [
            DailyPriceRow(
                stock_code=stock.code,
                date=row["date"],
                open_price=row["open_price"],
                high_price=row["high_price"],
                low_price=row["low_price"],
                close_price=row["close_price"],
                volume=row["volume"],
                change_rate=row["change_rate"],
            )
            for row in rows
        ]

    def get_market_index_rows(self, code: str, days: int):
        targets = get_market_index_targets(codes=[code])
        if not targets:
            raise ValueError(f"Unsupported market index code: {code}")

        target = targets[0]
        rows = _build_market_index_rows(fetch_history_frame(target.symbol, days))
        return [
            MarketIndexRow(
                code=target.code,
                name=target.name,
                date=row["date"],
                close_value=row["close_value"],
                change_rate=row["change_rate"],
            )
            for row in rows
        ]
