from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from portfolio.models import StockSymbol
from stocks.models import Stock


@dataclass(frozen=True)
class ProviderSymbolResolution:
    symbol: Optional[str]
    source: str
    warning: str = ""


@dataclass(frozen=True)
class MarketIndexTarget:
    code: str
    name: str
    symbol: str


MARKET_INDEX_TARGETS = {
    "KOSPI": MarketIndexTarget(code="KOSPI", name="KOSPI", symbol="^KS11"),
    "KOSDAQ": MarketIndexTarget(code="KOSDAQ", name="KOSDAQ", symbol="^KQ11"),
    "USDKRW": MarketIndexTarget(code="USDKRW", name="USD/KRW", symbol="KRW=X"),
    "NASDAQ": MarketIndexTarget(code="NASDAQ", name="NASDAQ", symbol="^IXIC"),
    "SP500": MarketIndexTarget(code="SP500", name="S&P500", symbol="^GSPC"),
}
MARKET_INDEX_CODE_ALIASES = {
    "S&P500": "SP500",
    "GSPC": "SP500",
    "USD/KRW": "USDKRW",
}


def _infer_stock_symbol(stock: Stock) -> Optional[str]:
    if stock.market in {Stock.MARKET_KOSPI, Stock.MARKET_ETF, Stock.MARKET_ETN}:
        return f"{stock.code}.KS"
    if stock.market in {Stock.MARKET_KOSDAQ, Stock.MARKET_KONEX}:
        return f"{stock.code}.KQ"
    return None


def resolve_stock_yfinance_symbol(stock: Stock) -> ProviderSymbolResolution:
    inferred_symbol = _infer_stock_symbol(stock)
    if inferred_symbol:
        return ProviderSymbolResolution(symbol=inferred_symbol, source="stock_code_market")

    mapping = StockSymbol.objects.filter(stock_name=stock.name).first()
    if mapping and mapping.ticker:
        return ProviderSymbolResolution(symbol=mapping.ticker.strip().upper(), source="legacy_stock_symbol")

    return ProviderSymbolResolution(
        symbol=None,
        source="unresolved",
        warning=f"{stock.code} {stock.name}: yfinance 심볼을 해석하지 못했습니다.",
    )


def get_market_index_targets(codes=None):
    if not codes:
        return list(MARKET_INDEX_TARGETS.values())

    targets = []
    for code in codes:
        normalized = MARKET_INDEX_CODE_ALIASES.get(code, code)
        target = MARKET_INDEX_TARGETS.get(normalized)
        if target:
            targets.append(target)
    return targets
