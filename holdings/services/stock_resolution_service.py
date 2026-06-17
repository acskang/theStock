from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from portfolio.models import StockSymbol
from stocks.models import Stock


@dataclass(frozen=True)
class StockResolutionResult:
    stock: Optional[Stock]
    created: bool
    source: str
    warning: str = ""


def _infer_market_from_ticker(ticker: str) -> Optional[str]:
    normalized = ticker.strip().upper()
    if normalized.endswith(".KS"):
        return Stock.MARKET_KOSPI
    if normalized.endswith(".KQ"):
        return Stock.MARKET_KOSDAQ
    return None


def _extract_code_from_ticker(ticker: str) -> str:
    return ticker.strip().upper().split(".", 1)[0]


def resolve_stock_from_legacy_name(stock_name: str) -> StockResolutionResult:
    normalized_name = stock_name.strip()
    if not normalized_name:
        return StockResolutionResult(
            stock=None,
            created=False,
            source="empty_name",
            warning="빈 종목명은 Stock으로 해석할 수 없습니다.",
        )

    stock = Stock.objects.filter(name=normalized_name).order_by("code").first()
    if stock:
        return StockResolutionResult(stock=stock, created=False, source="stock_name_exact")

    mapping = StockSymbol.objects.filter(stock_name=normalized_name).first()
    if not mapping:
        return StockResolutionResult(
            stock=None,
            created=False,
            source="missing_symbol_mapping",
            warning=f"{normalized_name}: StockSymbol 매핑이 없어 Stock으로 변환하지 못했습니다.",
        )

    code = _extract_code_from_ticker(mapping.ticker)
    market = _infer_market_from_ticker(mapping.ticker)
    if not code or not market:
        return StockResolutionResult(
            stock=None,
            created=False,
            source="invalid_ticker_mapping",
            warning=f"{normalized_name}: ticker={mapping.ticker} 에서 종목코드 또는 시장을 추론하지 못했습니다.",
        )

    stock, created = Stock.objects.get_or_create(
        code=code,
        defaults={
            "name": normalized_name,
            "market": market,
        },
    )
    return StockResolutionResult(
        stock=stock,
        created=created,
        source="symbol_mapping",
    )
