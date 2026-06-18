from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from django.utils.http import urlencode
from django.utils import timezone

from integrations.models import IntegrationAuditLog, TossInvestCredential
from integrations.services.audit import record_integration_audit
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
    clear_user_access_token,
)


HOLDINGS_PATH = "/api/v1/holdings"
SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9.\-]+$")


@dataclass(frozen=True)
class TossCurrencyAmount:
    krw: Decimal | None = None
    usd: Decimal | None = None

    def safe_dict(self) -> dict[str, str | None]:
        return {
            "krw": _decimal_to_str(self.krw),
            "usd": _decimal_to_str(self.usd),
        }


@dataclass(frozen=True)
class TossHoldingItemPreview:
    symbol: str
    name: str
    market_country: str
    currency: str
    quantity: Decimal | None
    last_price: Decimal | None
    average_purchase_price: Decimal | None
    purchase_amount: Decimal | None
    market_value_amount: Decimal | None
    market_value_amount_after_cost: Decimal | None
    profit_loss_amount: Decimal | None
    profit_loss_amount_after_cost: Decimal | None
    profit_loss_rate: Decimal | None
    profit_loss_rate_after_cost: Decimal | None
    daily_profit_loss_amount: Decimal | None
    daily_profit_loss_rate: Decimal | None
    commission: Decimal | None
    tax: Decimal | None

    def safe_dict(self) -> dict[str, str | None]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "market_country": self.market_country,
            "currency": self.currency,
            "quantity": _decimal_to_str(self.quantity),
            "last_price": _decimal_to_str(self.last_price),
            "average_purchase_price": _decimal_to_str(self.average_purchase_price),
            "purchase_amount": _decimal_to_str(self.purchase_amount),
            "market_value_amount": _decimal_to_str(self.market_value_amount),
            "market_value_amount_after_cost": _decimal_to_str(self.market_value_amount_after_cost),
            "profit_loss_amount": _decimal_to_str(self.profit_loss_amount),
            "profit_loss_amount_after_cost": _decimal_to_str(self.profit_loss_amount_after_cost),
            "profit_loss_rate": _decimal_to_str(self.profit_loss_rate),
            "profit_loss_rate_after_cost": _decimal_to_str(self.profit_loss_rate_after_cost),
            "daily_profit_loss_amount": _decimal_to_str(self.daily_profit_loss_amount),
            "daily_profit_loss_rate": _decimal_to_str(self.daily_profit_loss_rate),
            "commission": _decimal_to_str(self.commission),
            "tax": _decimal_to_str(self.tax),
        }


@dataclass(frozen=True)
class TossHoldingsSummaryPreview:
    total_purchase_amount: TossCurrencyAmount
    market_value_amount: TossCurrencyAmount
    market_value_amount_after_cost: TossCurrencyAmount
    profit_loss_amount: TossCurrencyAmount
    profit_loss_amount_after_cost: TossCurrencyAmount
    profit_loss_rate: Decimal | None
    profit_loss_rate_after_cost: Decimal | None
    daily_profit_loss_amount: TossCurrencyAmount
    daily_profit_loss_rate: Decimal | None

    def safe_dict(self) -> dict[str, object]:
        return {
            "total_purchase_amount": self.total_purchase_amount.safe_dict(),
            "market_value_amount": self.market_value_amount.safe_dict(),
            "market_value_amount_after_cost": self.market_value_amount_after_cost.safe_dict(),
            "profit_loss_amount": self.profit_loss_amount.safe_dict(),
            "profit_loss_amount_after_cost": self.profit_loss_amount_after_cost.safe_dict(),
            "profit_loss_rate": _decimal_to_str(self.profit_loss_rate),
            "profit_loss_rate_after_cost": _decimal_to_str(self.profit_loss_rate_after_cost),
            "daily_profit_loss_amount": self.daily_profit_loss_amount.safe_dict(),
            "daily_profit_loss_rate": _decimal_to_str(self.daily_profit_loss_rate),
        }


@dataclass(frozen=True)
class TossHoldingsPreviewResult:
    user_id: int
    credential_id: int
    provider: str
    account_masked: str
    status: str
    fetched_at: Any
    symbol_filter: str | None
    item_count: int
    summary: TossHoldingsSummaryPreview
    items: list[TossHoldingItemPreview]

    def safe_dict(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "credential_id": self.credential_id,
            "provider": self.provider,
            "account_masked": self.account_masked,
            "status": self.status,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "symbol_filter": self.symbol_filter,
            "item_count": self.item_count,
            "summary": self.summary.safe_dict(),
            "items": [item.safe_dict() for item in self.items],
        }


class TossHoldingsReadonlyError(Exception):
    """Base exception for Toss holdings read-only preview failures."""


class TossHoldingsReadonlyStateError(TossHoldingsReadonlyError):
    """Raised when local credential/context state does not allow holdings preview."""


class TossHoldingsReadonlyAuthError(TossHoldingsReadonlyError):
    """Raised when Toss rejects the holdings request."""


class TossHoldingsReadonlyTransientError(TossHoldingsReadonlyError):
    """Raised for retryable holdings provider/network failures."""


class TossHoldingsReadonlyParseError(TossHoldingsReadonlyError):
    """Raised when the holdings response cannot be safely normalized."""


class TossHoldingsReadonlyValidationError(TossHoldingsReadonlyError):
    """Raised when local user input is invalid."""


def fetch_user_toss_holdings_preview(
    *,
    user,
    actor=None,
    symbol: str | None = None,
    transport=None,
    force_token_refresh: bool = False,
) -> TossHoldingsPreviewResult:
    """Fetch a user-scoped Toss holdings preview without writing portfolio rows."""

    actor = actor or user
    credential = _credential_for_audit(user)
    try:
        normalized_symbol = _normalize_symbol(symbol)
        result = _fetch_user_toss_holdings_preview_once(
            user=user,
            actor=actor,
            symbol=normalized_symbol,
            transport=transport,
            force_token_refresh=force_token_refresh,
        )
    except TossHoldingsReadonlyValidationError:
        _record_holdings_audit(
            credential=credential,
            user=user,
            actor=actor,
            success=False,
            reason_code="validation",
            error_code="invalid_symbol",
            item_count=0,
            symbol_filter=None,
        )
        raise
    except TossHoldingsReadonlyAuthError:
        _record_holdings_audit(
            credential=credential,
            user=user,
            actor=actor,
            success=False,
            reason_code="auth",
            error_code="holdings_auth_failed",
            item_count=0,
            symbol_filter=normalized_symbol,
        )
        raise
    except TossHoldingsReadonlyTransientError:
        _record_holdings_audit(
            credential=credential,
            user=user,
            actor=actor,
            success=False,
            reason_code="transient",
            error_code="holdings_transient",
            item_count=0,
            symbol_filter=normalized_symbol,
        )
        raise
    except TossHoldingsReadonlyParseError:
        _record_holdings_audit(
            credential=credential,
            user=user,
            actor=actor,
            success=False,
            reason_code="parse",
            error_code="holdings_parse_failed",
            item_count=0,
            symbol_filter=normalized_symbol,
        )
        raise
    except TossHoldingsReadonlyStateError:
        _record_holdings_audit(
            credential=credential,
            user=user,
            actor=actor,
            success=False,
            reason_code="state",
            error_code="holdings_state_not_ready",
            item_count=0,
            symbol_filter=normalized_symbol,
        )
        raise

    _record_holdings_audit(
        credential=credential,
        user=user,
        actor=actor,
        success=True,
        reason_code="",
        error_code="",
        item_count=result.item_count,
        symbol_filter=normalized_symbol,
    )
    return result


def fetch_user_toss_holdings_preview_safe_dict(
    *,
    user,
    actor=None,
    symbol: str | None = None,
    transport=None,
    force_token_refresh: bool = False,
) -> dict[str, object]:
    return fetch_user_toss_holdings_preview(
        user=user,
        actor=actor,
        symbol=symbol,
        transport=transport,
        force_token_refresh=force_token_refresh,
    ).safe_dict()


def normalize_holdings_response(
    body: dict[str, Any],
    *,
    user_id: int,
    credential_id: int,
    provider: str,
    account_masked: str,
    status: str,
    symbol_filter: str | None = None,
) -> TossHoldingsPreviewResult:
    result = _extract_result(body)
    items_raw = result.get("items", [])
    if not isinstance(items_raw, list):
        raise TossHoldingsReadonlyParseError("Toss holdings response is invalid.")
    items = [_normalize_holding_item(item) for item in items_raw]
    market_value = _mapping_or_empty(result.get("marketValue"))
    profit_loss = _mapping_or_empty(result.get("profitLoss"))
    daily_profit_loss = _mapping_or_empty(result.get("dailyProfitLoss"))
    summary = TossHoldingsSummaryPreview(
        total_purchase_amount=_parse_currency_amount(result.get("totalPurchaseAmount")),
        market_value_amount=_parse_currency_amount(market_value.get("amount")),
        market_value_amount_after_cost=_parse_currency_amount(market_value.get("amountAfterCost")),
        profit_loss_amount=_parse_currency_amount(profit_loss.get("amount")),
        profit_loss_amount_after_cost=_parse_currency_amount(profit_loss.get("amountAfterCost")),
        profit_loss_rate=_to_decimal(profit_loss.get("rate")),
        profit_loss_rate_after_cost=_to_decimal(profit_loss.get("rateAfterCost")),
        daily_profit_loss_amount=_parse_currency_amount(daily_profit_loss.get("amount")),
        daily_profit_loss_rate=_to_decimal(daily_profit_loss.get("rate")),
    )
    return TossHoldingsPreviewResult(
        user_id=user_id,
        credential_id=credential_id,
        provider=provider,
        account_masked=account_masked,
        status=status,
        fetched_at=timezone.now(),
        symbol_filter=symbol_filter,
        item_count=len(items),
        summary=summary,
        items=items,
    )


def _fetch_user_toss_holdings_preview_once(
    *,
    user,
    actor,
    symbol: str | None,
    transport,
    force_token_refresh: bool,
) -> TossHoldingsPreviewResult:
    context = _build_context(
        user=user,
        actor=actor,
        force_refresh=force_token_refresh,
        transport=transport,
    )
    transport = transport or UrllibTossOpenApiTransport()
    path = _build_holdings_path(symbol)
    try:
        status_code, body = transport.get_json(path, headers=context.headers())
    except TossHoldingsReadonlyError:
        raise
    except Exception as exc:
        raise TossHoldingsReadonlyTransientError("Toss holdings request failed temporarily.") from exc

    if status_code == 200:
        return normalize_holdings_response(
            body,
            user_id=context.user_id,
            credential_id=context.credential_id,
            provider=context.provider,
            account_masked=context.account_masked,
            status="active",
            symbol_filter=symbol,
        )
    if status_code == 401 and not force_token_refresh:
        return _fetch_user_toss_holdings_preview_once(
            user=user,
            actor=actor,
            symbol=symbol,
            transport=transport,
            force_token_refresh=True,
        )
    if status_code in {401, 403}:
        _clear_token_after_holdings_auth_failure(user=user, actor=actor)
        raise TossHoldingsReadonlyAuthError("Toss holdings request was rejected.")
    if status_code == 429 or status_code >= 500:
        raise TossHoldingsReadonlyTransientError("Toss holdings request is temporarily unavailable.")
    raise TossHoldingsReadonlyTransientError("Toss holdings request failed.")


def _build_context(*, user, actor, force_refresh: bool, transport):
    if not is_toss_api_calls_enabled():
        raise TossHoldingsReadonlyStateError("Toss holdings preview is not enabled.")
    try:
        return build_user_toss_request_context(
            user=user,
            actor=actor,
            force_refresh=force_refresh,
            transport=transport,
        )
    except TossUserContextAuthError as exc:
        raise TossHoldingsReadonlyAuthError("Toss credential reset is required.") from exc
    except TossUserContextTransientError as exc:
        raise TossHoldingsReadonlyTransientError("Toss token request failed temporarily.") from exc
    except (
        TossUserContextConfigurationError,
        TossUserContextDecryptionError,
        TossUserContextNotReadyError,
        TossUserContextPermissionError,
    ) as exc:
        raise TossHoldingsReadonlyStateError("Toss holdings preview is not ready.") from exc


def _to_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise TossHoldingsReadonlyParseError("Toss holdings numeric value is invalid.") from exc


def _parse_currency_amount(obj: dict | None) -> TossCurrencyAmount:
    if obj is None:
        return TossCurrencyAmount()
    if not isinstance(obj, dict):
        raise TossHoldingsReadonlyParseError("Toss holdings amount value is invalid.")
    return TossCurrencyAmount(
        krw=_to_decimal(obj.get("krw")),
        usd=_to_decimal(obj.get("usd")),
    )


def _normalize_symbol(symbol: str | None) -> str | None:
    if symbol is None:
        return None
    normalized = str(symbol).strip()
    if not normalized:
        return None
    if len(normalized) > 32 or not SYMBOL_PATTERN.match(normalized):
        raise TossHoldingsReadonlyValidationError("Toss holdings symbol is invalid.")
    return normalized


def _build_holdings_path(symbol: str | None) -> str:
    if not symbol:
        return HOLDINGS_PATH
    return f"{HOLDINGS_PATH}?{urlencode({'symbol': symbol})}"


def _extract_result(body: dict) -> dict:
    if not isinstance(body, dict):
        raise TossHoldingsReadonlyParseError("Toss holdings response is invalid.")
    result = body.get("result")
    if not isinstance(result, dict):
        raise TossHoldingsReadonlyParseError("Toss holdings response is invalid.")
    return result


def _normalize_holding_item(item: dict) -> TossHoldingItemPreview:
    if not isinstance(item, dict):
        raise TossHoldingsReadonlyParseError("Toss holdings item is invalid.")
    market_value = _mapping_or_empty(item.get("marketValue"))
    profit_loss = _mapping_or_empty(item.get("profitLoss"))
    daily_profit_loss = _mapping_or_empty(item.get("dailyProfitLoss"))
    cost = _mapping_or_empty(item.get("cost"))
    return TossHoldingItemPreview(
        symbol=_safe_text(item.get("symbol"), max_length=32),
        name=_safe_text(item.get("name"), max_length=200),
        market_country=_safe_text(item.get("marketCountry"), max_length=16),
        currency=_safe_text(item.get("currency"), max_length=16),
        quantity=_to_decimal(item.get("quantity")),
        last_price=_to_decimal(item.get("lastPrice")),
        average_purchase_price=_to_decimal(item.get("averagePurchasePrice")),
        purchase_amount=_to_decimal(item.get("purchaseAmount") or market_value.get("purchaseAmount")),
        market_value_amount=_to_decimal(market_value.get("amount")),
        market_value_amount_after_cost=_to_decimal(market_value.get("amountAfterCost")),
        profit_loss_amount=_to_decimal(profit_loss.get("amount")),
        profit_loss_amount_after_cost=_to_decimal(profit_loss.get("amountAfterCost")),
        profit_loss_rate=_to_decimal(profit_loss.get("rate")),
        profit_loss_rate_after_cost=_to_decimal(profit_loss.get("rateAfterCost")),
        daily_profit_loss_amount=_to_decimal(daily_profit_loss.get("amount")),
        daily_profit_loss_rate=_to_decimal(daily_profit_loss.get("rate")),
        commission=_to_decimal(cost.get("commission")),
        tax=_to_decimal(cost.get("tax")),
    )


def _mapping_or_empty(value) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TossHoldingsReadonlyParseError("Toss holdings nested value is invalid.")
    return value


def _safe_text(value, *, max_length: int) -> str:
    return str(value or "").strip()[:max_length]


def _decimal_to_str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _credential_for_audit(user) -> TossInvestCredential | None:
    if user is None:
        return None
    return TossInvestCredential.objects.filter(user=user).first()


def _record_holdings_audit(
    *,
    credential,
    user,
    actor,
    success: bool,
    reason_code: str,
    error_code: str,
    item_count: int,
    symbol_filter: str | None,
) -> None:
    record_integration_audit(
        action=IntegrationAuditLog.ACTION_HOLDINGS_SYNC,
        credential=credential,
        actor=actor or user,
        target_user=user,
        success=success,
        reason_code=reason_code[:120],
        error_code=error_code[:120],
        safe_summary="holdings preview fetched" if success else "holdings preview failed",
        safe_metadata={
            "item_count": item_count,
            "has_symbol_filter": bool(symbol_filter),
            "source": "toss_readonly_preview",
        },
    )


def _clear_token_after_holdings_auth_failure(*, user, actor) -> None:
    try:
        clear_user_access_token(user=user, actor=actor, reason_code="holdings_auth_failed")
    except Exception:
        # The holdings auth failure remains the primary safe error. Token clear
        # is best-effort and must not expose stored credentials or headers.
        return
