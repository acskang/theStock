from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.utils.http import urlencode

from integrations.services.toss_readonly_verification import (
    UrllibTossOpenApiTransport,
    is_toss_api_calls_enabled,
)
from integrations.services.toss_user_context import (
    TossUserContextAuthError,
    TossUserContextConfigurationError,
    TossUserContextDecryptionError,
    TossUserContextNotReadyError,
    TossUserContextPermissionError,
    TossUserContextTransientError,
    build_user_toss_request_context,
)


SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9.\-]+$")
MAX_UI_SYMBOLS = 20
MAX_TRADES_COUNT = 50
MAX_CANDLE_COUNT = 200


@dataclass(frozen=True)
class TossStockPricePreview:
    symbol: str
    timestamp: Any
    last_price: Decimal | None
    currency: str


@dataclass(frozen=True)
class TossStockInfoPreview:
    symbol: str
    name: str
    english_name: str
    isin_code: str
    market: str
    security_type: str
    is_common_share: bool | None
    status: str
    currency: str
    list_date: Any
    delist_date: Any
    shares_outstanding: Decimal | None
    leverage_factor: Decimal | None
    liquidation_trading: bool | None
    nxt_supported: bool | None
    krx_trading_suspended: bool | None
    nxt_trading_suspended: bool | None


@dataclass(frozen=True)
class TossStockQuotePreview:
    symbol: str
    stock_info: TossStockInfoPreview | None
    price: TossStockPricePreview | None


@dataclass(frozen=True)
class TossStockQuoteBatch:
    user_id: int
    credential_id: int
    requested_symbols: list[str]
    item_count: int
    items: list[TossStockQuotePreview]
    missing_symbols: list[str]
    fetched_at: Any


@dataclass(frozen=True)
class TossOrderbookEntryPreview:
    price: Decimal | None
    volume: Decimal | None


@dataclass(frozen=True)
class TossOrderbookPreview:
    timestamp: Any
    currency: str
    asks: list[TossOrderbookEntryPreview]
    bids: list[TossOrderbookEntryPreview]


@dataclass(frozen=True)
class TossTradePreview:
    price: Decimal | None
    volume: Decimal | None
    timestamp: Any
    currency: str


@dataclass(frozen=True)
class TossPriceLimitPreview:
    timestamp: Any
    upper_limit_price: Decimal | None
    lower_limit_price: Decimal | None
    currency: str


@dataclass(frozen=True)
class TossStockWarningPreview:
    warning_type: str
    exchange: str
    start_date: Any
    end_date: Any

    @property
    def warning_label(self) -> str:
        labels = {
            "LIQUIDATION_TRADING": "정리매매",
            "OVERHEATED": "단기과열",
            "INVESTMENT_WARNING": "투자경고",
            "INVESTMENT_RISK": "투자위험",
            "VI_STATIC_AND_DYNAMIC": "VI 정적·동적",
            "VI_STATIC": "VI 정적",
            "VI_DYNAMIC": "VI 동적",
            "STOCK_WARRANTS": "신주인수권",
        }
        return labels.get(self.warning_type, self.warning_type or "-")


@dataclass(frozen=True)
class TossSymbolMarketDetail:
    user_id: int
    credential_id: int
    symbol: str
    quote: TossStockQuotePreview | None
    orderbook: TossOrderbookPreview | None
    recent_trades: list[TossTradePreview]
    price_limits: TossPriceLimitPreview | None
    warnings: list[TossStockWarningPreview]
    section_errors: dict[str, str]
    fetched_at: Any


@dataclass(frozen=True)
class TossCandlePreview:
    timestamp: Any
    open_price: Decimal | None
    high_price: Decimal | None
    low_price: Decimal | None
    close_price: Decimal | None
    volume: Decimal | None
    currency: str


@dataclass(frozen=True)
class TossCandlePagePreview:
    user_id: int
    credential_id: int
    symbol: str
    interval: str
    count: int
    adjusted: bool
    candles: list[TossCandlePreview]
    next_before: str
    fetched_at: Any


@dataclass(frozen=True)
class TossExchangeRatePreview:
    base_currency: str
    quote_currency: str
    rate: Decimal | None
    mid_rate: Decimal | None
    basis_point: Decimal | None
    rate_change_type: str
    valid_from: Any
    valid_until: Any
    fetched_at: Any


class TossMarketExplorerError(Exception):
    """Base exception for Toss market explorer failures."""


class TossMarketValidationError(TossMarketExplorerError):
    """Raised when market explorer input is invalid."""


class TossMarketStateError(TossMarketExplorerError):
    """Raised when user-scoped Toss context is not ready."""


class TossMarketAuthError(TossMarketExplorerError):
    """Raised when Toss rejects market data access."""


class TossMarketTransientError(TossMarketExplorerError):
    """Raised for retryable provider/network failures."""


class TossMarketNotFoundError(TossMarketExplorerError):
    """Raised when requested market data cannot be found."""


class TossMarketParseError(TossMarketExplorerError):
    """Raised when market response cannot be normalized."""


def fetch_user_toss_stock_quotes(*, user, symbols, actor=None, transport=None) -> TossStockQuoteBatch:
    normalized_symbols = normalize_symbols(symbols)
    context = _build_market_context(user=user, actor=actor or user, force_refresh=False, transport=transport)
    prices_body = _get_market_json_with_retry(
        user=user,
        actor=actor or user,
        path=f"/api/v1/prices?{urlencode({'symbols': ','.join(normalized_symbols)})}",
        transport=transport,
        initial_context=context,
    )
    stocks_body = _get_market_json_with_retry(
        user=user,
        actor=actor or user,
        path=f"/api/v1/stocks?{urlencode({'symbols': ','.join(normalized_symbols)})}",
        transport=transport,
        initial_context=context,
    )
    prices = {_safe_text(item.get("symbol"), max_length=32): _normalize_price(item) for item in _extract_result_list(prices_body)}
    infos = {_safe_text(item.get("symbol"), max_length=32): _normalize_stock_info(item) for item in _extract_result_list(stocks_body)}
    items: list[TossStockQuotePreview] = []
    missing: list[str] = []
    for symbol in normalized_symbols:
        price = prices.get(symbol)
        info = infos.get(symbol)
        if not price and not info:
            missing.append(symbol)
            continue
        items.append(TossStockQuotePreview(symbol=symbol, stock_info=info, price=price))
    return TossStockQuoteBatch(
        user_id=context.user_id,
        credential_id=context.credential_id,
        requested_symbols=normalized_symbols,
        item_count=len(items),
        items=items,
        missing_symbols=missing,
        fetched_at=timezone.now(),
    )


def fetch_user_toss_symbol_market_detail(
    *,
    user,
    symbol,
    trades_count=20,
    actor=None,
    transport=None,
) -> TossSymbolMarketDetail:
    normalized_symbol = normalize_symbol(symbol)
    normalized_count = _normalize_count(trades_count, max_value=MAX_TRADES_COUNT)
    context = _build_market_context(user=user, actor=actor or user, force_refresh=False, transport=transport)
    section_errors: dict[str, str] = {}
    quote = None
    try:
        batch = fetch_user_toss_stock_quotes(user=user, actor=actor or user, symbols=[normalized_symbol], transport=transport)
        quote = batch.items[0] if batch.items else None
    except TossMarketExplorerError:
        section_errors["quote"] = "현재가와 종목 기본정보를 불러오지 못했습니다."

    orderbook = _optional_section(
        section_errors,
        "orderbook",
        "호가 정보를 불러오지 못했습니다.",
        lambda: _fetch_orderbook(context=context, user=user, actor=actor or user, symbol=normalized_symbol, transport=transport),
    )
    trades = _optional_section(
        section_errors,
        "trades",
        "최근 체결 정보를 불러오지 못했습니다.",
        lambda: _fetch_trades(
            context=context,
            user=user,
            actor=actor or user,
            symbol=normalized_symbol,
            count=normalized_count,
            transport=transport,
        ),
    ) or []
    limits = _optional_section(
        section_errors,
        "price_limits",
        "상·하한가 정보를 불러오지 못했습니다.",
        lambda: _fetch_price_limits(context=context, user=user, actor=actor or user, symbol=normalized_symbol, transport=transport),
    )
    warnings = _optional_section(
        section_errors,
        "warnings",
        "유의사항을 불러오지 못했습니다.",
        lambda: _fetch_warnings(context=context, user=user, actor=actor or user, symbol=normalized_symbol, transport=transport),
    ) or []
    if not quote and not orderbook and not trades and not limits and not warnings:
        raise TossMarketNotFoundError("Toss symbol market data was not found.")
    return TossSymbolMarketDetail(
        user_id=context.user_id,
        credential_id=context.credential_id,
        symbol=normalized_symbol,
        quote=quote,
        orderbook=orderbook,
        recent_trades=trades,
        price_limits=limits,
        warnings=warnings,
        section_errors=section_errors,
        fetched_at=timezone.now(),
    )


def fetch_user_toss_candles(
    *,
    user,
    symbol,
    interval="1d",
    count=50,
    adjusted=True,
    before=None,
    actor=None,
    transport=None,
) -> TossCandlePagePreview:
    normalized_symbol = normalize_symbol(symbol)
    normalized_interval = _normalize_interval(interval)
    normalized_count = _normalize_count(count, max_value=MAX_CANDLE_COUNT)
    context = _build_market_context(user=user, actor=actor or user, force_refresh=False, transport=transport)
    query = {
        "symbol": normalized_symbol,
        "interval": normalized_interval,
        "count": normalized_count,
        "adjusted": "true" if bool(adjusted) else "false",
    }
    if before:
        query["before"] = str(before).strip()[:128]
    body = _get_market_json_with_retry(
        user=user,
        actor=actor or user,
        path=f"/api/v1/candles?{urlencode(query)}",
        transport=transport,
        initial_context=context,
    )
    result = _extract_result_dict(body)
    candles_raw = result.get("candles", [])
    if not isinstance(candles_raw, list):
        raise TossMarketParseError("Toss candle response is invalid.")
    return TossCandlePagePreview(
        user_id=context.user_id,
        credential_id=context.credential_id,
        symbol=normalized_symbol,
        interval=normalized_interval,
        count=normalized_count,
        adjusted=bool(adjusted),
        candles=[_normalize_candle(item) for item in candles_raw],
        next_before=_safe_text(result.get("nextBefore"), max_length=128),
        fetched_at=timezone.now(),
    )


def fetch_user_toss_usd_krw_exchange_rate(*, user, actor=None, transport=None) -> TossExchangeRatePreview:
    context = _build_market_context(user=user, actor=actor or user, force_refresh=False, transport=transport)
    body = _get_market_json_with_retry(
        user=user,
        actor=actor or user,
        path=f"/api/v1/exchange-rate?{urlencode({'baseCurrency': 'USD', 'quoteCurrency': 'KRW'})}",
        transport=transport,
        initial_context=context,
    )
    result = _extract_result_dict(body)
    return TossExchangeRatePreview(
        base_currency=_safe_text(result.get("baseCurrency"), max_length=8) or "USD",
        quote_currency=_safe_text(result.get("quoteCurrency"), max_length=8) or "KRW",
        rate=_to_decimal(result.get("rate")),
        mid_rate=_to_decimal(result.get("midRate")),
        basis_point=_to_decimal(result.get("basisPoint")),
        rate_change_type=_safe_text(result.get("rateChangeType"), max_length=32),
        valid_from=_to_datetime_or_text(result.get("validFrom")),
        valid_until=_to_datetime_or_text(result.get("validUntil")),
        fetched_at=timezone.now(),
    )


def normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip()
    if not normalized or len(normalized) > 32 or not SYMBOL_PATTERN.match(normalized):
        raise TossMarketValidationError("Toss symbol is invalid.")
    return normalized


def normalize_symbols(symbols) -> list[str]:
    if isinstance(symbols, str):
        raw_items = symbols.split(",")
    else:
        raw_items = list(symbols or [])
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        item = normalize_symbol(str(raw))
        if item in seen:
            continue
        normalized.append(item)
        seen.add(item)
    if not normalized or len(normalized) > MAX_UI_SYMBOLS:
        raise TossMarketValidationError("Toss symbols input is invalid.")
    return normalized


def _build_market_authorization_headers(context) -> dict[str, str]:
    return {"Authorization": context.authorization_header()}


def _get_market_json_with_retry(*, user, actor, path: str, transport, initial_context=None):
    context = initial_context or _build_market_context(user=user, actor=actor, force_refresh=False, transport=transport)
    return _get_market_json_once(
        user=user,
        actor=actor,
        path=path,
        transport=transport,
        context=context,
        force_token_refresh=False,
    )


def _get_market_json_once(*, user, actor, path: str, transport, context, force_token_refresh: bool):
    transport = transport or UrllibTossOpenApiTransport()
    try:
        status_code, body = transport.get_json(path, headers=_build_market_authorization_headers(context))
    except TossMarketExplorerError:
        raise
    except Exception as exc:
        raise TossMarketTransientError("Toss market request failed temporarily.") from exc
    if status_code == 200:
        return body
    if status_code == 401 and not force_token_refresh:
        refreshed_context = _build_market_context(user=user, actor=actor, force_refresh=True, transport=transport)
        return _get_market_json_once(
            user=user,
            actor=actor,
            path=path,
            transport=transport,
            context=refreshed_context,
            force_token_refresh=True,
        )
    if status_code in {401, 403}:
        raise TossMarketAuthError("Toss market request was rejected.")
    if status_code == 404:
        raise TossMarketNotFoundError("Toss market data was not found.")
    if status_code == 429 or status_code >= 500:
        raise TossMarketTransientError("Toss market request is temporarily unavailable.")
    raise TossMarketTransientError("Toss market request failed.")


def _build_market_context(*, user, actor, force_refresh: bool, transport):
    if not is_toss_api_calls_enabled():
        raise TossMarketStateError("Toss market explorer is not enabled.")
    try:
        return build_user_toss_request_context(user=user, actor=actor, force_refresh=force_refresh, transport=transport)
    except TossUserContextAuthError as exc:
        raise TossMarketAuthError("Toss credential reset is required.") from exc
    except TossUserContextTransientError as exc:
        raise TossMarketTransientError("Toss token request failed temporarily.") from exc
    except (
        TossUserContextConfigurationError,
        TossUserContextDecryptionError,
        TossUserContextNotReadyError,
        TossUserContextPermissionError,
    ) as exc:
        raise TossMarketStateError("Toss market explorer is not ready.") from exc


def _fetch_orderbook(*, context, user, actor, symbol: str, transport) -> TossOrderbookPreview:
    body = _get_market_json_with_retry(
        user=user,
        actor=actor,
        path=f"/api/v1/orderbook?{urlencode({'symbol': symbol})}",
        transport=transport,
        initial_context=context,
    )
    result = _extract_result_dict(body)
    return TossOrderbookPreview(
        timestamp=_to_datetime_or_text(result.get("timestamp")),
        currency=_safe_text(result.get("currency"), max_length=8),
        asks=[_normalize_orderbook_entry(item) for item in _list_or_empty(result.get("asks"))],
        bids=[_normalize_orderbook_entry(item) for item in _list_or_empty(result.get("bids"))],
    )


def _fetch_trades(*, context, user, actor, symbol: str, count: int, transport) -> list[TossTradePreview]:
    body = _get_market_json_with_retry(
        user=user,
        actor=actor,
        path=f"/api/v1/trades?{urlencode({'symbol': symbol, 'count': count})}",
        transport=transport,
        initial_context=context,
    )
    return [_normalize_trade(item) for item in _extract_result_list(body)]


def _fetch_price_limits(*, context, user, actor, symbol: str, transport) -> TossPriceLimitPreview:
    body = _get_market_json_with_retry(
        user=user,
        actor=actor,
        path=f"/api/v1/price-limits?{urlencode({'symbol': symbol})}",
        transport=transport,
        initial_context=context,
    )
    result = _extract_result_dict(body)
    return TossPriceLimitPreview(
        timestamp=_to_datetime_or_text(result.get("timestamp")),
        upper_limit_price=_to_decimal(result.get("upperLimitPrice")),
        lower_limit_price=_to_decimal(result.get("lowerLimitPrice")),
        currency=_safe_text(result.get("currency"), max_length=8),
    )


def _fetch_warnings(*, context, user, actor, symbol: str, transport) -> list[TossStockWarningPreview]:
    body = _get_market_json_with_retry(
        user=user,
        actor=actor,
        path=f"/api/v1/stocks/{symbol}/warnings",
        transport=transport,
        initial_context=context,
    )
    return [_normalize_warning(item) for item in _extract_result_list(body)]


def _optional_section(section_errors: dict[str, str], key: str, message: str, func):
    try:
        return func()
    except TossMarketExplorerError:
        section_errors[key] = message
        return None


def _normalize_price(item: dict) -> TossStockPricePreview:
    if not isinstance(item, dict):
        raise TossMarketParseError("Toss price item is invalid.")
    return TossStockPricePreview(
        symbol=_safe_text(item.get("symbol"), max_length=32),
        timestamp=_to_datetime_or_text(item.get("timestamp")),
        last_price=_to_decimal(item.get("lastPrice")),
        currency=_safe_text(item.get("currency"), max_length=8),
    )


def _normalize_stock_info(item: dict) -> TossStockInfoPreview:
    if not isinstance(item, dict):
        raise TossMarketParseError("Toss stock item is invalid.")
    detail = item.get("koreanMarketDetail") if isinstance(item.get("koreanMarketDetail"), dict) else {}
    return TossStockInfoPreview(
        symbol=_safe_text(item.get("symbol"), max_length=32),
        name=_safe_text(item.get("name"), max_length=160),
        english_name=_safe_text(item.get("englishName"), max_length=160),
        isin_code=_safe_text(item.get("isinCode"), max_length=32),
        market=_safe_text(item.get("market"), max_length=32),
        security_type=_safe_text(item.get("securityType"), max_length=48),
        is_common_share=_to_bool_or_none(item.get("isCommonShare")),
        status=_safe_text(item.get("status"), max_length=48),
        currency=_safe_text(item.get("currency"), max_length=8),
        list_date=_to_date_or_text(item.get("listDate")),
        delist_date=_to_date_or_text(item.get("delistDate")),
        shares_outstanding=_to_decimal(item.get("sharesOutstanding")),
        leverage_factor=_to_decimal(item.get("leverageFactor")),
        liquidation_trading=_to_bool_or_none(detail.get("liquidationTrading")),
        nxt_supported=_to_bool_or_none(detail.get("nxtSupported")),
        krx_trading_suspended=_to_bool_or_none(detail.get("krxTradingSuspended")),
        nxt_trading_suspended=_to_bool_or_none(detail.get("nxtTradingSuspended")),
    )


def _normalize_orderbook_entry(item) -> TossOrderbookEntryPreview:
    if not isinstance(item, dict):
        raise TossMarketParseError("Toss orderbook item is invalid.")
    return TossOrderbookEntryPreview(price=_to_decimal(item.get("price")), volume=_to_decimal(item.get("volume")))


def _normalize_trade(item) -> TossTradePreview:
    if not isinstance(item, dict):
        raise TossMarketParseError("Toss trade item is invalid.")
    return TossTradePreview(
        price=_to_decimal(item.get("price")),
        volume=_to_decimal(item.get("volume")),
        timestamp=_to_datetime_or_text(item.get("timestamp")),
        currency=_safe_text(item.get("currency"), max_length=8),
    )


def _normalize_warning(item) -> TossStockWarningPreview:
    if not isinstance(item, dict):
        raise TossMarketParseError("Toss warning item is invalid.")
    return TossStockWarningPreview(
        warning_type=_safe_text(item.get("warningType"), max_length=64),
        exchange=_safe_text(item.get("exchange"), max_length=32),
        start_date=_to_date_or_text(item.get("startDate")),
        end_date=_to_date_or_text(item.get("endDate")),
    )


def _normalize_candle(item) -> TossCandlePreview:
    if not isinstance(item, dict):
        raise TossMarketParseError("Toss candle item is invalid.")
    return TossCandlePreview(
        timestamp=_to_datetime_or_text(item.get("timestamp")),
        open_price=_to_decimal(item.get("openPrice")),
        high_price=_to_decimal(item.get("highPrice")),
        low_price=_to_decimal(item.get("lowPrice")),
        close_price=_to_decimal(item.get("closePrice")),
        volume=_to_decimal(item.get("volume")),
        currency=_safe_text(item.get("currency"), max_length=8),
    )


def _extract_result_dict(body: dict) -> dict:
    if not isinstance(body, dict) or not isinstance(body.get("result"), dict):
        raise TossMarketParseError("Toss market response is invalid.")
    return body["result"]


def _extract_result_list(body: dict) -> list:
    if not isinstance(body, dict) or not isinstance(body.get("result"), list):
        raise TossMarketParseError("Toss market response is invalid.")
    return body["result"]


def _list_or_empty(value) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        raise TossMarketParseError("Toss market list value is invalid.")
    return value


def _normalize_interval(interval: str) -> str:
    normalized = str(interval or "").strip()
    if normalized not in {"1m", "1d"}:
        raise TossMarketValidationError("Toss candle interval is invalid.")
    return normalized


def _normalize_count(count, *, max_value: int) -> int:
    try:
        normalized = int(count)
    except (TypeError, ValueError) as exc:
        raise TossMarketValidationError("Toss count value is invalid.") from exc
    if normalized < 1 or normalized > max_value:
        raise TossMarketValidationError("Toss count value is invalid.")
    return normalized


def _to_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise TossMarketParseError("Toss market numeric value is invalid.") from exc


def _to_datetime_or_text(value):
    text = _safe_text(value, max_length=128)
    if not text:
        return None
    return parse_datetime(text) or text


def _to_date_or_text(value):
    text = _safe_text(value, max_length=32)
    if not text:
        return None
    return parse_date(text) or text


def _to_bool_or_none(value) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _safe_text(value, *, max_length: int) -> str:
    return str(value or "").strip()[:max_length]
