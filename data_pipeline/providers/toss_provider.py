import re
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from django.conf import settings

from .base import BaseDataProvider
from .toss_auth import issue_toss_access_token, is_toss_provider_enabled
from .toss_client import TossOpenApiClient
from .toss_exceptions import TossOpenApiError, TossProviderDisabled
from .toss_masking import is_configured, mask_account_id
from .toss_transport import urllib_form_transport, urllib_json_transport


PRICE_PATH = "/api/v1/prices"
CANDLES_PATH = "/api/v1/candles"
ACCOUNTS_PATH = "/api/v1/accounts"
HOLDINGS_PATH = "/api/v1/holdings"
ORDERS_PATH = "/api/v1/orders"
SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9.\-]+$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TossOpenApiProvider(BaseDataProvider):
    provider_name = "toss"
    name = "toss"

    def __init__(self, *, client: TossOpenApiClient | None = None):
        self.client = client or self._build_default_client()

    def is_enabled(self) -> bool:
        return is_toss_provider_enabled(getattr(settings, "TOSS_INVEST_PROVIDER_ENABLED", False))

    def capabilities(self) -> dict[str, bool]:
        return {
            "auth": True,
            "health_check": True,
            "quote": True,
            "daily_price": False,
            "holdings": True,
            "order_history": True,
            "orders": False,
            "order_execution": False,
        }

    def health_check(self) -> dict[str, Any]:
        enabled = self.is_enabled()
        client_id_configured = is_configured(getattr(settings, "TOSS_INVEST_CLIENT_ID", ""))
        client_secret_configured = is_configured(getattr(settings, "TOSS_INVEST_CLIENT_SECRET", ""))
        client_health = self.client.health_check()

        status = "disabled"
        if enabled and not (client_id_configured and client_secret_configured):
            status = "misconfigured"
        elif enabled:
            status = "configured"

        return {
            "provider": self.name,
            "enabled": enabled,
            "status": status,
            "base_url_configured": is_configured(getattr(self.client, "base_url", "")),
            "client_id_configured": client_id_configured,
            "client_secret_configured": client_secret_configured,
            "account_id_configured": is_configured(getattr(settings, "TOSS_INVEST_ACCOUNT_ID", "")),
            "client_ready": client_health.get("token_provider_configured", False),
            "client_transport_configured": client_health.get("transport_configured", False),
            "capabilities": self.capabilities(),
        }

    def get_quote(self, symbol: str, market: str | None = None) -> dict[str, Any]:
        if not self.is_enabled():
            raise TossProviderDisabled("Toss provider is disabled.")

        clean_symbol = _validate_symbol(symbol)
        response = self.client.request(
            "GET",
            PRICE_PATH,
            params={"symbols": clean_symbol},
            account_required=False,
        )
        data = getattr(response, "data", response)
        normalized, raw_summary = _normalize_price_response(data, clean_symbol)

        return {
            "provider": self.name,
            "symbol": clean_symbol,
            "market": (market or "").strip(),
            "raw": raw_summary,
            "normalized": normalized,
            "dry_run": True,
        }

    def get_daily_price_candidates(
        self,
        symbol: str,
        *,
        market: str | None = None,
        count: int = 1,
        before: str | None = None,
        adjusted: bool = True,
    ) -> dict[str, Any]:
        if not self.is_enabled():
            raise TossProviderDisabled("Toss provider is disabled.")

        clean_symbol = _validate_symbol(symbol)
        clean_count = _validate_count(count)
        clean_market = (market or "").strip()
        clean_before = str(before).strip() if before is not None else ""
        params: dict[str, Any] = {
            "symbol": clean_symbol,
            "interval": "1d",
            "count": clean_count,
            "adjusted": "true" if adjusted else "false",
        }
        if clean_before:
            params["before"] = clean_before

        response = self.client.request(
            "GET",
            CANDLES_PATH,
            params=params,
            account_required=False,
        )
        data = getattr(response, "data", response)
        candidates, raw_summary = _normalize_daily_candle_candidates(
            data,
            symbol=clean_symbol,
            market=clean_market,
            adjusted=bool(adjusted),
        )

        return {
            "provider": self.name,
            "symbol": clean_symbol,
            "market": clean_market,
            "endpoint": CANDLES_PATH,
            "interval": "1d",
            "adjusted": bool(adjusted),
            "dry_run": True,
            "raw": raw_summary,
            "candidates": candidates,
            "model_mapping": {
                "model": "DailyPrice",
                "save_supported": False,
                "reason": "dry_run_only_step_17",
            },
        }

    def get_accounts(self) -> dict[str, Any]:
        if not self.is_enabled():
            raise TossProviderDisabled("Toss provider is disabled.")

        response = self.client.request(
            "GET",
            ACCOUNTS_PATH,
            account_required=False,
        )
        data = getattr(response, "data", response)
        accounts = _extract_accounts(data)

        return {
            "provider": self.name,
            "endpoint": ACCOUNTS_PATH,
            "dry_run": True,
            "account_count": len(accounts),
            "account_types": _account_types(accounts),
            "account_seq_usable_count": sum(
                1
                for account in accounts
                if isinstance(account, Mapping) and _is_account_seq_like(account.get("accountSeq"))
            ),
            "accounts": [
                {
                    "account_type": account.get("accountType"),
                    "masked": mask_account_id(account.get("accountSeq") or account.get("accountNo")),
                    "account_seq_shape": _classify_account_value(account.get("accountSeq")),
                    "account_seq_usable": _is_account_seq_like(account.get("accountSeq")),
                }
                for account in accounts
                if isinstance(account, Mapping)
            ],
            "raw": {"result_count": len(accounts)},
        }

    def get_holdings_candidates(
        self,
        *,
        account_id: str | None = None,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        if not self.is_enabled():
            raise TossProviderDisabled("Toss provider is disabled.")

        clean_symbol = _validate_optional_symbol(symbol)
        selected_account_id, account_source = self._resolve_holdings_account_id(account_id)
        params = {"symbol": clean_symbol} if clean_symbol else None
        account_diagnostic = _safe_account_diagnostic(
            selected_account_id,
            source=account_source,
            accounts_api_called=account_source == "accounts_api_single",
        )

        response = self.client.request(
            "GET",
            HOLDINGS_PATH,
            params=params,
            account_required=True,
            account_id=selected_account_id,
        )
        data = getattr(response, "data", response)
        candidates, raw_summary = _normalize_holdings_candidates(data)

        return {
            "provider": self.name,
            "endpoint": HOLDINGS_PATH,
            "dry_run": True,
            "account": {
                "source": account_source,
                "masked": mask_account_id(selected_account_id),
                "shape": _classify_account_value(selected_account_id),
            },
            "summary": {
                "item_count": len(candidates),
                "has_krw": any(candidate.get("currency") == "KRW" for candidate in candidates),
                "has_usd": any(candidate.get("currency") == "USD" for candidate in candidates),
                "account_diagnostic": account_diagnostic,
            },
            "raw": raw_summary,
            "candidates": candidates,
            "model_mapping": {
                "model": "UserHolding",
                "save_supported": False,
                "reason": "dry_run_only_step_20",
            },
        }

    def get_order_history_candidates(
        self,
        *,
        status: str,
        symbol: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        cursor: str | None = None,
        limit: int | None = 20,
        account: str | None = None,
    ) -> dict[str, Any]:
        if not self.is_enabled():
            raise TossProviderDisabled("Toss provider is disabled.")

        clean_status = _validate_order_history_status(status)
        clean_symbol = _validate_optional_symbol(symbol)
        clean_from_date = _validate_optional_date(from_date)
        clean_to_date = _validate_optional_date(to_date)
        clean_limit = _validate_order_history_limit(limit)
        clean_cursor = str(cursor or "").strip()
        selected_account_id, account_source = self._resolve_holdings_account_id(account)
        account_diagnostic = _safe_account_diagnostic(
            selected_account_id,
            source=account_source,
            accounts_api_called=account_source == "accounts_api_single",
        )

        params: dict[str, Any] = {"status": clean_status}
        if clean_symbol:
            params["symbol"] = clean_symbol
        if clean_from_date:
            params["from"] = clean_from_date
        if clean_to_date:
            params["to"] = clean_to_date
        if clean_status == "CLOSED":
            params["limit"] = clean_limit
            if clean_cursor:
                params["cursor"] = clean_cursor

        response = self.client.request(
            "GET",
            ORDERS_PATH,
            params=params,
            account_required=True,
            account_id=selected_account_id,
        )
        data = getattr(response, "data", response)
        orders, raw_summary = _normalize_order_history_response(data)

        return {
            "provider": self.name,
            "endpoint": ORDERS_PATH,
            "status_filter": clean_status,
            "symbol": clean_symbol,
            "from_date": clean_from_date,
            "to_date": clean_to_date,
            "network_call": True,
            "dry_run": True,
            "account_source": account_source,
            "account_fallback_used": account_source == "accounts_api_single",
            "account_header_configured": is_configured(selected_account_id),
            "order_count": len(orders),
            "has_next": bool(raw_summary.get("has_next")),
            "next_cursor_present": bool(raw_summary.get("next_cursor_present")),
            "orders": orders,
            "raw_summary": raw_summary,
            "account_diagnostic": account_diagnostic,
        }

    def _resolve_holdings_account_id(self, account_id: str | None) -> tuple[str, str]:
        clean_account_id = str(account_id or "").strip()
        if clean_account_id:
            if not _is_account_seq_like(clean_account_id):
                raise _safe_toss_error(
                    "invalid_account_identifier",
                    diagnostic={
                        "account_arg_shape": _classify_account_value(clean_account_id),
                        "account_header_configured": False,
                        "accounts_api_called": False,
                        "selected_account_source": "cli_invalid",
                    },
                )
            return clean_account_id, "cli"

        configured_account_id = getattr(settings, "TOSS_INVEST_ACCOUNT_ID", "")
        if _is_account_seq_like(configured_account_id):
            return str(configured_account_id).strip(), "env"

        response = self.client.request(
            "GET",
            ACCOUNTS_PATH,
            account_required=False,
        )
        data = getattr(response, "data", response)
        accounts = _extract_accounts(data)
        if not accounts:
            raise _safe_toss_error(
                "account_not_found",
                diagnostic={
                    "account_count": 0,
                    "account_env_shape": _classify_account_value(configured_account_id),
                    "accounts_api_called": True,
                    "selected_account_source": "none",
                    "account_header_configured": False,
                },
            )
        if len(accounts) > 1:
            raise _safe_toss_error(
                "ambiguous_account",
                diagnostic={
                    "account_count": len(accounts),
                    "account_types": _account_types(accounts),
                    "account_env_shape": _classify_account_value(configured_account_id),
                    "accounts_api_called": True,
                    "selected_account_source": "ambiguous",
                    "account_header_configured": False,
                },
            )

        account_seq = accounts[0].get("accountSeq") if isinstance(accounts[0], Mapping) else None
        if not _is_account_seq_like(account_seq):
            raise _safe_toss_error(
                "account_seq_required",
                diagnostic={
                    "account_count": 1,
                    "account_types": _account_types(accounts),
                    "account_env_shape": _classify_account_value(configured_account_id),
                    "account_seq_shape": _classify_account_value(account_seq),
                    "accounts_api_called": True,
                    "selected_account_source": "none",
                    "account_header_configured": False,
                },
            )
        return str(account_seq).strip(), "accounts_api_single"

    def _build_default_client(self) -> TossOpenApiClient:
        return TossOpenApiClient(
            token_provider=lambda: issue_toss_access_token(transport=urllib_form_transport),
            transport=urllib_json_transport,
        )

    def get_stock_master_rows(self):
        raise TossOpenApiError("Toss stock master collection is not implemented yet.")

    def get_daily_price_rows(self, stock, days: int):
        raise TossOpenApiError("Toss daily price collection is not implemented yet.")

    def get_investor_flow_rows(self, stock, days: int):
        raise TossOpenApiError("Toss investor flow collection is not implemented yet.")

    def get_market_index_rows(self, code: str, days: int):
        raise TossOpenApiError("Toss market index collection is not implemented yet.")

    def get_risk_event_rows(self, stock, days: int):
        raise TossOpenApiError("Toss risk event collection is not implemented yet.")

    def get_financial_snapshot_rows(self, stock, years: int):
        raise TossOpenApiError("Toss financial snapshot collection is not implemented yet.")


def _validate_symbol(symbol: str) -> str:
    clean_symbol = str(symbol or "").strip()
    if not clean_symbol:
        raise TossOpenApiError("Toss quote symbol is required.")
    if "," in clean_symbol:
        raise TossOpenApiError("Only one Toss quote symbol is supported.")
    if not SYMBOL_PATTERN.match(clean_symbol):
        raise TossOpenApiError("Invalid Toss quote symbol.")
    return clean_symbol


def _validate_optional_symbol(symbol: str | None) -> str:
    if symbol in {None, ""}:
        return ""
    return _validate_symbol(str(symbol))


def _validate_order_history_status(status: str) -> str:
    clean_status = str(status or "").strip().upper()
    if clean_status not in {"OPEN", "CLOSED"}:
        raise TossOpenApiError("Invalid Toss order history status.")
    return clean_status


def _validate_optional_date(value: str | None) -> str:
    clean_value = str(value or "").strip()
    if not clean_value:
        return ""
    if not DATE_PATTERN.match(clean_value):
        raise TossOpenApiError("Invalid Toss order history date.")
    return clean_value


def _validate_order_history_limit(value: int | None) -> int:
    try:
        clean_limit = int(20 if value in {None, ""} else value)
    except (TypeError, ValueError) as exc:
        raise TossOpenApiError("Invalid Toss order history limit.") from exc
    if clean_limit < 1 or clean_limit > 100:
        raise TossOpenApiError("Invalid Toss order history limit.")
    return clean_limit


def _validate_count(count: int) -> int:
    try:
        clean_count = int(count)
    except (TypeError, ValueError) as exc:
        raise TossOpenApiError("Invalid Toss candle count.") from exc
    if clean_count < 1 or clean_count > 200:
        raise TossOpenApiError("Invalid Toss candle count.")
    return clean_count


def _normalize_daily_candle_candidates(
    data: Any,
    *,
    symbol: str,
    market: str,
    adjusted: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    result = data.get("result") if isinstance(data, Mapping) else None
    candles = result.get("candles") if isinstance(result, Mapping) else None
    next_before = result.get("nextBefore") if isinstance(result, Mapping) else None
    if not isinstance(candles, list):
        return [], {"result_count": 0, "next_before": next_before}

    candidates = []
    for candle in candles:
        if not isinstance(candle, Mapping):
            continue
        timestamp = candle.get("timestamp")
        date_value = str(timestamp)[:10] if timestamp else None
        candidates.append(
            {
                "symbol": symbol,
                "market": market,
                "date": date_value,
                "timestamp": timestamp,
                "open_price": _normalize_price(candle.get("openPrice")),
                "high_price": _normalize_price(candle.get("highPrice")),
                "low_price": _normalize_price(candle.get("lowPrice")),
                "close_price": _normalize_price(candle.get("closePrice")),
                "volume": _normalize_price(candle.get("volume")),
                "currency": candle.get("currency"),
                "source": "toss",
                "adjusted": adjusted,
            }
        )
    return candidates, {"result_count": len(candidates), "next_before": next_before}


def _extract_accounts(data: Any) -> list[Any]:
    if not isinstance(data, Mapping):
        return []
    result = data.get("result")
    if isinstance(result, list):
        return result
    if isinstance(result, Mapping):
        items = result.get("items")
        return items if isinstance(items, list) else []
    return []


def _account_types(accounts: list[Any]) -> list[str]:
    values = []
    for account in accounts:
        if not isinstance(account, Mapping):
            continue
        account_type = str(account.get("accountType") or "").strip()
        if account_type and account_type not in values:
            values.append(account_type)
    return values[:20]


def _classify_account_value(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "missing"
    if not text.isdigit():
        return "non_integer"
    if len(text) > 20:
        return "too_long"
    return "integer_like"


def _is_account_seq_like(value: object) -> bool:
    return _classify_account_value(value) == "integer_like"


def _safe_account_diagnostic(
    selected_account_id: object,
    *,
    source: str,
    accounts_api_called: bool,
) -> dict[str, Any]:
    return {
        "account_header_configured": is_configured(selected_account_id),
        "account_env_configured": is_configured(getattr(settings, "TOSS_INVEST_ACCOUNT_ID", "")),
        "account_env_shape": _classify_account_value(getattr(settings, "TOSS_INVEST_ACCOUNT_ID", "")),
        "accounts_api_called": bool(accounts_api_called),
        "selected_account_source": source,
        "account_fallback_used": source == "accounts_api_single",
        "selected_account_masked": mask_account_id(selected_account_id),
        "selected_account_shape": _classify_account_value(selected_account_id),
    }


def _normalize_holdings_candidates(data: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    result = data.get("result") if isinstance(data, Mapping) else None
    items = result.get("items") if isinstance(result, Mapping) else None
    if not isinstance(items, list):
        return [], {"result_count": 0}

    candidates = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        market_value = item.get("marketValue") if isinstance(item.get("marketValue"), Mapping) else {}
        profit_loss = item.get("profitLoss") if isinstance(item.get("profitLoss"), Mapping) else {}
        daily_profit_loss = item.get("dailyProfitLoss") if isinstance(item.get("dailyProfitLoss"), Mapping) else {}
        candidates.append(
            {
                "symbol": item.get("symbol"),
                "name": item.get("name"),
                "market_country": item.get("marketCountry"),
                "currency": item.get("currency"),
                "quantity": _normalize_price(item.get("quantity")),
                "last_price": _normalize_price(item.get("lastPrice")),
                "average_purchase_price": _normalize_price(item.get("averagePurchasePrice")),
                "purchase_amount": _normalize_price(market_value.get("purchaseAmount")),
                "market_value": _normalize_price(market_value.get("amount")),
                "market_value_after_cost": _normalize_price(market_value.get("amountAfterCost")),
                "profit_loss_amount": _normalize_price(profit_loss.get("amount")),
                "profit_loss_amount_after_cost": _normalize_price(profit_loss.get("amountAfterCost")),
                "profit_loss_rate": _normalize_price(profit_loss.get("rate")),
                "profit_loss_rate_after_cost": _normalize_price(profit_loss.get("rateAfterCost")),
                "daily_profit_loss_amount": _normalize_price(daily_profit_loss.get("amount")),
                "daily_profit_loss_rate": _normalize_price(daily_profit_loss.get("rate")),
                "source": "toss",
            }
        )
    return candidates, {"result_count": len(candidates)}


def _normalize_order_history_response(data: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    result = data.get("result") if isinstance(data, Mapping) else None
    orders = result.get("orders") if isinstance(result, Mapping) else None
    if not isinstance(orders, list):
        orders = []

    normalized_orders = [_normalize_order_item(order) for order in orders if isinstance(order, Mapping)]
    next_cursor = result.get("nextCursor") if isinstance(result, Mapping) else None
    has_next = bool(result.get("hasNext")) if isinstance(result, Mapping) else False
    return normalized_orders, {
        "result_type": "paginated_orders",
        "has_next": has_next,
        "next_cursor_present": bool(str(next_cursor or "").strip()),
        "order_count": len(normalized_orders),
    }


def _normalize_order_item(order: Mapping[str, Any]) -> dict[str, Any]:
    execution = order.get("execution") if isinstance(order.get("execution"), Mapping) else {}
    if not execution:
        execution = order.get("executions") if isinstance(order.get("executions"), Mapping) else {}
    return {
        "order_id_masked": _mask_order_id(order.get("orderId")),
        "symbol": order.get("symbol"),
        "side": order.get("side"),
        "order_type": order.get("orderType") or order.get("order_type"),
        "time_in_force": order.get("timeInForce") or order.get("time_in_force"),
        "status": order.get("status"),
        "price": _normalize_price(order.get("price")),
        "quantity": _normalize_price(order.get("quantity")),
        "order_amount": _normalize_price(order.get("orderAmount") or order.get("order_amount")),
        "currency": order.get("currency"),
        "ordered_at": order.get("orderedAt") or order.get("ordered_at"),
        "canceled_at": order.get("canceledAt") or order.get("canceled_at"),
        "execution": {
            "filled_quantity": _normalize_price(execution.get("filledQuantity") or execution.get("filled_quantity")),
            "average_filled_price": _normalize_price(
                execution.get("averageFilledPrice") or execution.get("average_filled_price")
            ),
            "filled_amount": _normalize_price(execution.get("filledAmount") or execution.get("filled_amount")),
            "commission": _normalize_price(execution.get("commission")),
            "tax": _normalize_price(execution.get("tax")),
            "filled_at": execution.get("filledAt") or execution.get("filled_at"),
            "settlement_date": execution.get("settlementDate") or execution.get("settlement_date"),
        },
    }


def _mask_order_id(value: Any) -> str:
    from .toss_masking import mask_secret

    return mask_secret(value)


def _normalize_price_response(data: Any, symbol: str) -> tuple[dict[str, Any], dict[str, Any]]:
    result = data.get("result") if isinstance(data, Mapping) else None
    if not isinstance(result, list) or not result:
        return _empty_normalized(symbol), {"result_count": 0, "matched_symbol": False}

    selected = None
    for item in result:
        if isinstance(item, Mapping) and str(item.get("symbol", "")).upper() == symbol.upper():
            selected = item
            break

    matched_symbol = selected is not None
    if selected is None:
        selected = result[0] if isinstance(result[0], Mapping) else {}

    normalized = {
        "symbol": selected.get("symbol") or symbol,
        "price": _normalize_price(selected.get("lastPrice")),
        "currency": selected.get("currency"),
        "as_of": selected.get("timestamp"),
    }
    return normalized, {"result_count": len(result), "matched_symbol": matched_symbol}


def _empty_normalized(symbol: str) -> dict[str, Any]:
    return {"symbol": symbol, "price": None, "currency": None, "as_of": None}


def _safe_toss_error(reason: str, *, diagnostic: dict[str, Any] | None = None) -> TossOpenApiError:
    exc = TossOpenApiError("Toss holdings request could not be completed.")
    exc.safe_reason = reason
    exc.account_diagnostic = diagnostic or {}
    return exc


def _normalize_price(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return str(value)
