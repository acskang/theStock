from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.http import urlencode

from integrations.models import IntegrationAuditLog, TossInvestCredential
from integrations.services.audit import record_integration_audit
from integrations.services.fingerprints import make_fingerprint
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


ORDERS_PATH = "/api/v1/orders"
ORDER_STATUS_OPEN = "OPEN"
ORDER_STATUS_CLOSED = "CLOSED"
ORDER_LIMIT_DEFAULT = 20
ORDER_LIMIT_MAX = 100
SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9.\-]+$")


@dataclass(frozen=True)
class TossOrderExecutionPreview:
    filled_quantity: Decimal | None = None
    average_filled_price: Decimal | None = None
    filled_amount: Decimal | None = None
    commission: Decimal | None = None
    tax: Decimal | None = None
    filled_at: Any = None
    settlement_date: str = ""

    def safe_dict(self) -> dict[str, object]:
        return {
            "filled_quantity": _decimal_to_str(self.filled_quantity),
            "average_filled_price": _decimal_to_str(self.average_filled_price),
            "filled_amount": _decimal_to_str(self.filled_amount),
            "commission": _decimal_to_str(self.commission),
            "tax": _decimal_to_str(self.tax),
            "filled_at": _date_to_display(self.filled_at),
            "settlement_date": self.settlement_date,
        }


@dataclass(frozen=True)
class TossOrderItemPreview:
    order_ref: str
    order_id_hash: str
    symbol: str
    side: str
    order_type: str
    time_in_force: str
    status: str
    price: Decimal | None
    quantity: Decimal | None
    order_amount: Decimal | None
    currency: str
    ordered_at: Any = None
    canceled_at: Any = None
    execution: TossOrderExecutionPreview | None = None

    @property
    def side_label(self) -> str:
        return {"BUY": "매수", "SELL": "매도"}.get(self.side, self.side or "-")

    @property
    def status_label(self) -> str:
        labels = {
            "FILLED": "체결 완료",
            "PARTIAL_FILLED": "부분 체결",
            "PENDING": "대기",
            "CANCELED": "취소",
            "REJECTED": "거부",
        }
        return labels.get(self.status, self.status or "-")

    def safe_dict(self) -> dict[str, object]:
        return {
            "order_ref": self.order_ref,
            "symbol": self.symbol,
            "side": self.side,
            "side_label": self.side_label,
            "order_type": self.order_type,
            "time_in_force": self.time_in_force,
            "status": self.status,
            "status_label": self.status_label,
            "price": _decimal_to_str(self.price),
            "quantity": _decimal_to_str(self.quantity),
            "order_amount": _decimal_to_str(self.order_amount),
            "currency": self.currency,
            "ordered_at": _date_to_display(self.ordered_at),
            "canceled_at": _date_to_display(self.canceled_at),
            "execution": self.execution.safe_dict() if self.execution else TossOrderExecutionPreview().safe_dict(),
        }


@dataclass(frozen=True)
class TossOrderHistoryPage:
    user_id: int
    credential_id: int
    status_filter: str
    symbol_filter: str | None
    from_date: Any
    to_date: Any
    item_count: int
    orders: list[TossOrderItemPreview]
    has_next: bool
    next_cursor: str
    fetched_at: Any

    def safe_dict(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "credential_id": self.credential_id,
            "status_filter": self.status_filter,
            "symbol_filter": self.symbol_filter,
            "from_date": _date_to_display(self.from_date),
            "to_date": _date_to_display(self.to_date),
            "item_count": self.item_count,
            "orders": [order.safe_dict() for order in self.orders],
            "has_next": self.has_next,
            "next_cursor": self.next_cursor,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
        }


class TossOrderHistoryError(Exception):
    """Base exception for Toss order history read-only failures."""


class TossOrderHistoryValidationError(TossOrderHistoryError):
    """Raised when order history filters are invalid."""


class TossOrderHistoryStateError(TossOrderHistoryError):
    """Raised when local credential/context state is not ready."""


class TossOrderHistoryAuthError(TossOrderHistoryError):
    """Raised when Toss rejects the order history request."""


class TossOrderHistoryTransientError(TossOrderHistoryError):
    """Raised for retryable Toss order history provider/network failures."""


class TossOrderHistoryParseError(TossOrderHistoryError):
    """Raised when the order history response cannot be normalized."""


def fetch_user_toss_order_history(
    *,
    user,
    actor=None,
    status: str = ORDER_STATUS_CLOSED,
    symbol: str | None = None,
    from_date=None,
    to_date=None,
    cursor: str | None = None,
    limit: int | str = ORDER_LIMIT_DEFAULT,
    transport=None,
) -> TossOrderHistoryPage:
    """Fetch a user-scoped Toss order/filled-history page without storing rows."""

    actor = actor or user
    credential = _credential_for_audit(user)
    normalized_status = _normalize_status(status)
    normalized_symbol = _normalize_symbol(symbol)
    normalized_limit = _normalize_limit(limit)
    _validate_date_range(from_date=from_date, to_date=to_date)
    normalized_cursor = _normalize_cursor(cursor) if normalized_status == ORDER_STATUS_CLOSED else ""
    try:
        page = _fetch_user_toss_order_history_once(
            user=user,
            actor=actor,
            status=normalized_status,
            symbol=normalized_symbol,
            from_date=from_date,
            to_date=to_date,
            cursor=normalized_cursor,
            limit=normalized_limit,
            transport=transport,
            force_token_refresh=False,
        )
    except TossOrderHistoryValidationError:
        _record_order_history_audit(
            credential=credential,
            user=user,
            actor=actor,
            success=False,
            reason_code="validation",
            error_code="invalid_filter",
            status_filter=normalized_status if normalized_status in {ORDER_STATUS_OPEN, ORDER_STATUS_CLOSED} else "",
            symbol_filter=normalized_symbol,
            item_count=0,
            has_next=False,
        )
        raise
    except TossOrderHistoryAuthError:
        _record_order_history_audit(
            credential=credential,
            user=user,
            actor=actor,
            success=False,
            reason_code="auth",
            error_code="orders_auth_failed",
            status_filter=normalized_status,
            symbol_filter=normalized_symbol,
            item_count=0,
            has_next=False,
        )
        raise
    except TossOrderHistoryTransientError:
        _record_order_history_audit(
            credential=credential,
            user=user,
            actor=actor,
            success=False,
            reason_code="transient",
            error_code="orders_transient",
            status_filter=normalized_status,
            symbol_filter=normalized_symbol,
            item_count=0,
            has_next=False,
        )
        raise
    except TossOrderHistoryParseError:
        _record_order_history_audit(
            credential=credential,
            user=user,
            actor=actor,
            success=False,
            reason_code="parse",
            error_code="orders_parse_failed",
            status_filter=normalized_status,
            symbol_filter=normalized_symbol,
            item_count=0,
            has_next=False,
        )
        raise
    except TossOrderHistoryStateError:
        _record_order_history_audit(
            credential=credential,
            user=user,
            actor=actor,
            success=False,
            reason_code="state",
            error_code="orders_state_not_ready",
            status_filter=normalized_status,
            symbol_filter=normalized_symbol,
            item_count=0,
            has_next=False,
        )
        raise

    _record_order_history_audit(
        credential=credential,
        user=user,
        actor=actor,
        success=True,
        reason_code="",
        error_code="",
        status_filter=page.status_filter,
        symbol_filter=page.symbol_filter,
        item_count=page.item_count,
        has_next=page.has_next,
    )
    return page


def normalize_order_history_response(
    body: dict[str, Any],
    *,
    user_id: int,
    credential_id: int,
    status_filter: str,
    symbol_filter: str | None,
    from_date=None,
    to_date=None,
) -> TossOrderHistoryPage:
    result = _extract_result(body)
    orders_raw = result.get("orders", [])
    if not isinstance(orders_raw, list):
        raise TossOrderHistoryParseError("Toss order history response is invalid.")
    orders = [_normalize_order_item(item) for item in orders_raw]
    return TossOrderHistoryPage(
        user_id=user_id,
        credential_id=credential_id,
        status_filter=status_filter,
        symbol_filter=symbol_filter,
        from_date=from_date,
        to_date=to_date,
        item_count=len(orders),
        orders=orders,
        has_next=bool(result.get("hasNext")),
        next_cursor=_safe_text(result.get("nextCursor"), max_length=512),
        fetched_at=timezone.now(),
    )


def _fetch_user_toss_order_history_once(
    *,
    user,
    actor,
    status: str,
    symbol: str | None,
    from_date,
    to_date,
    cursor: str,
    limit: int,
    transport,
    force_token_refresh: bool,
) -> TossOrderHistoryPage:
    context = _build_context(user=user, actor=actor, force_refresh=force_token_refresh, transport=transport)
    transport = transport or UrllibTossOpenApiTransport()
    path = _build_orders_path(
        status=status,
        symbol=symbol,
        from_date=from_date,
        to_date=to_date,
        cursor=cursor,
        limit=limit,
    )
    try:
        status_code, body = transport.get_json(path, headers=context.headers())
    except TossOrderHistoryError:
        raise
    except Exception as exc:
        raise TossOrderHistoryTransientError("Toss order history request failed temporarily.") from exc

    if status_code == 200:
        return normalize_order_history_response(
            body,
            user_id=context.user_id,
            credential_id=context.credential_id,
            status_filter=status,
            symbol_filter=symbol,
            from_date=from_date,
            to_date=to_date,
        )
    if status_code == 401 and not force_token_refresh:
        return _fetch_user_toss_order_history_once(
            user=user,
            actor=actor,
            status=status,
            symbol=symbol,
            from_date=from_date,
            to_date=to_date,
            cursor=cursor,
            limit=limit,
            transport=transport,
            force_token_refresh=True,
        )
    if status_code in {401, 403}:
        raise TossOrderHistoryAuthError("Toss order history request was rejected.")
    if status_code == 429 or status_code >= 500:
        raise TossOrderHistoryTransientError("Toss order history request is temporarily unavailable.")
    raise TossOrderHistoryTransientError("Toss order history request failed.")


def _build_context(*, user, actor, force_refresh: bool, transport):
    if not is_toss_api_calls_enabled():
        raise TossOrderHistoryStateError("Toss order history is not enabled.")
    try:
        return build_user_toss_request_context(
            user=user,
            actor=actor,
            force_refresh=force_refresh,
            transport=transport,
        )
    except TossUserContextAuthError as exc:
        raise TossOrderHistoryAuthError("Toss credential reset is required.") from exc
    except TossUserContextTransientError as exc:
        raise TossOrderHistoryTransientError("Toss token request failed temporarily.") from exc
    except (
        TossUserContextConfigurationError,
        TossUserContextDecryptionError,
        TossUserContextNotReadyError,
        TossUserContextPermissionError,
    ) as exc:
        raise TossOrderHistoryStateError("Toss order history is not ready.") from exc


def _normalize_status(status: str) -> str:
    normalized = str(status or "").strip().upper()
    if normalized not in {ORDER_STATUS_OPEN, ORDER_STATUS_CLOSED}:
        raise TossOrderHistoryValidationError("Toss order status filter is invalid.")
    return normalized


def _normalize_symbol(symbol: str | None) -> str | None:
    if symbol is None:
        return None
    normalized = str(symbol).strip()
    if not normalized:
        return None
    if len(normalized) > 32 or not SYMBOL_PATTERN.match(normalized):
        raise TossOrderHistoryValidationError("Toss order symbol filter is invalid.")
    return normalized


def _normalize_limit(limit: int | str) -> int:
    try:
        normalized = int(limit)
    except (TypeError, ValueError) as exc:
        raise TossOrderHistoryValidationError("Toss order limit is invalid.") from exc
    if normalized < 1 or normalized > ORDER_LIMIT_MAX:
        raise TossOrderHistoryValidationError("Toss order limit is invalid.")
    return normalized


def _validate_date_range(*, from_date, to_date) -> None:
    if from_date and to_date and from_date > to_date:
        raise TossOrderHistoryValidationError("Toss order date range is invalid.")


def _normalize_cursor(cursor: str | None) -> str:
    return str(cursor or "").strip()[:512]


def _build_orders_path(
    *,
    status: str,
    symbol: str | None,
    from_date,
    to_date,
    cursor: str,
    limit: int,
) -> str:
    query: dict[str, object] = {"status": status}
    if symbol:
        query["symbol"] = symbol
    if from_date:
        query["from"] = _date_to_query(from_date)
    if to_date:
        query["to"] = _date_to_query(to_date)
    if status == ORDER_STATUS_CLOSED:
        query["limit"] = limit
        if cursor:
            query["cursor"] = cursor
    return f"{ORDERS_PATH}?{urlencode(query)}"


def _extract_result(body: dict) -> dict:
    if not isinstance(body, dict):
        raise TossOrderHistoryParseError("Toss order history response is invalid.")
    result = body.get("result")
    if not isinstance(result, dict):
        raise TossOrderHistoryParseError("Toss order history response is invalid.")
    return result


def _normalize_order_item(item: dict) -> TossOrderItemPreview:
    if not isinstance(item, dict):
        raise TossOrderHistoryParseError("Toss order item is invalid.")
    order_id = _safe_text(item.get("orderId"), max_length=256)
    if not order_id:
        raise TossOrderHistoryParseError("Toss order item is invalid.")
    execution = _mapping_or_empty(item.get("execution"))
    return TossOrderItemPreview(
        order_ref=make_fingerprint(order_id, namespace="order_id")[:12],
        order_id_hash=make_fingerprint(order_id, namespace="order_id"),
        symbol=_safe_text(item.get("symbol"), max_length=32),
        side=_safe_text(item.get("side"), max_length=24).upper(),
        order_type=_safe_text(item.get("orderType"), max_length=48),
        time_in_force=_safe_text(item.get("timeInForce"), max_length=48),
        status=_safe_text(item.get("status"), max_length=48).upper(),
        price=_to_decimal(item.get("price")),
        quantity=_to_decimal(item.get("quantity")),
        order_amount=_to_decimal(item.get("orderAmount")),
        currency=_safe_text(item.get("currency"), max_length=16),
        ordered_at=_to_datetime_or_text(item.get("orderedAt")),
        canceled_at=_to_datetime_or_text(item.get("canceledAt")),
        execution=TossOrderExecutionPreview(
            filled_quantity=_to_decimal(execution.get("filledQuantity")),
            average_filled_price=_to_decimal(execution.get("averageFilledPrice")),
            filled_amount=_to_decimal(execution.get("filledAmount")),
            commission=_to_decimal(execution.get("commission")),
            tax=_to_decimal(execution.get("tax")),
            filled_at=_to_datetime_or_text(execution.get("filledAt")),
            settlement_date=_safe_text(execution.get("settlementDate"), max_length=32),
        ),
    )


def _mapping_or_empty(value) -> dict:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TossOrderHistoryParseError("Toss order nested value is invalid.")
    return value


def _to_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise TossOrderHistoryParseError("Toss order numeric value is invalid.") from exc


def _to_datetime_or_text(value):
    text = _safe_text(value, max_length=64)
    if not text:
        return None
    parsed = parse_datetime(text)
    return parsed or text


def _safe_text(value, *, max_length: int) -> str:
    return str(value or "").strip()[:max_length]


def _date_to_query(value) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _date_to_display(value) -> str | None:
    if value is None or value == "":
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _decimal_to_str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _credential_for_audit(user) -> TossInvestCredential | None:
    if user is None:
        return None
    return TossInvestCredential.objects.filter(user=user).first()


def _record_order_history_audit(
    *,
    credential,
    user,
    actor,
    success: bool,
    reason_code: str,
    error_code: str,
    status_filter: str,
    symbol_filter: str | None,
    item_count: int,
    has_next: bool,
) -> None:
    record_integration_audit(
        action=IntegrationAuditLog.ACTION_ORDER_HISTORY_SYNC,
        credential=credential,
        actor=actor or user,
        target_user=user,
        success=success,
        reason_code=reason_code[:120],
        error_code=error_code[:120],
        safe_summary="order history fetched" if success else "order history failed",
        safe_metadata={
            "status_filter": status_filter,
            "has_symbol_filter": bool(symbol_filter),
            "item_count": item_count,
            "has_next": has_next,
            "source": "toss_readonly_orders",
        },
    )
