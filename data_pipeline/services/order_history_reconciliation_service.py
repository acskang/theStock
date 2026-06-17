from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping

from holdings.models import UserHolding


_SYMBOL_RE = re.compile(r"^[A-Za-z0-9.\-]+$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class OrderHistoryReconciliationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def build_order_history_reconciliation(
    *,
    provider,
    symbol,
    from_date=None,
    to_date=None,
    limit=20,
):
    _validate_inputs(provider=provider, symbol=symbol, from_date=from_date, to_date=to_date, limit=limit)

    try:
        result = provider.get_order_history_candidates(
            status="CLOSED",
            symbol=symbol,
            from_date=from_date,
            to_date=to_date,
            limit=int(limit),
        )
    except OrderHistoryReconciliationError:
        raise
    except Exception as exc:
        raise OrderHistoryReconciliationError(
            "order_history_request_failed",
            "Order history request failed.",
        ) from exc

    if not isinstance(result, Mapping):
        raise OrderHistoryReconciliationError(
            "unsupported_order_history_payload",
            "Order history payload is unsupported.",
        )

    orders = result.get("orders") or []
    if not isinstance(orders, list):
        raise OrderHistoryReconciliationError(
            "unsupported_order_history_payload",
            "Order history orders payload is unsupported.",
        )

    warnings = [
        "This is a staff-only read-only reconciliation report.",
        "This is not an official realized P&L calculation.",
        "No orders are placed by this report.",
        "Order IDs are masked and raw responses are not included.",
        "Fees and taxes are summarized separately and not included in weighted average buy price.",
    ]

    aggregates = _aggregate_orders(orders, warnings)
    comparison = _build_user_holding_comparison(symbol=symbol, aggregates=aggregates, warnings=warnings)

    has_next = bool(result.get("has_next"))
    next_cursor_present = bool(result.get("next_cursor_present"))
    if has_next or next_cursor_present:
        warnings.append("Result may be incomplete because more pages exist.")

    return {
        "report_type": "order_history_reconciliation",
        "read_only": True,
        "order_execution": False,
        "provider": str(result.get("provider") or "toss"),
        "symbol": symbol,
        "from_date": from_date,
        "to_date": to_date,
        "limit": int(limit),
        "order_history": {
            "order_count": _safe_int(result.get("order_count"), len(orders)),
            "has_next": has_next,
            "next_cursor_present": next_cursor_present,
            "used_cursor": False,
        },
        "aggregates": _format_aggregates(aggregates),
        "user_holding_comparison": comparison,
        "warnings": warnings,
    }


def _validate_inputs(*, provider, symbol, from_date, to_date, limit) -> None:
    if provider is None or not hasattr(provider, "get_order_history_candidates"):
        raise OrderHistoryReconciliationError("provider_required", "Provider is required.")
    if symbol is None or str(symbol).strip() == "":
        raise OrderHistoryReconciliationError("symbol_required", "Symbol is required.")
    if not _SYMBOL_RE.match(str(symbol)):
        raise OrderHistoryReconciliationError("invalid_symbol", "Symbol is invalid.")
    if from_date is not None and from_date != "" and not _DATE_RE.match(str(from_date)):
        raise OrderHistoryReconciliationError("invalid_date", "from_date is invalid.")
    if to_date is not None and to_date != "" and not _DATE_RE.match(str(to_date)):
        raise OrderHistoryReconciliationError("invalid_date", "to_date is invalid.")
    try:
        limit_value = int(limit)
    except (TypeError, ValueError) as exc:
        raise OrderHistoryReconciliationError("invalid_limit", "Limit is invalid.") from exc
    if limit_value < 1 or limit_value > 100:
        raise OrderHistoryReconciliationError("invalid_limit", "Limit is invalid.")


def _aggregate_orders(orders: list[Any], warnings: list[str]) -> dict[str, Decimal | int]:
    aggregates: dict[str, Decimal | int] = {
        "buy_order_count": 0,
        "sell_order_count": 0,
        "skipped_execution_count": 0,
        "buy_filled_quantity_sum": Decimal("0"),
        "sell_filled_quantity_sum": Decimal("0"),
        "buy_filled_amount_sum": Decimal("0"),
        "sell_filled_amount_sum": Decimal("0"),
        "buy_commission_sum": Decimal("0"),
        "sell_commission_sum": Decimal("0"),
        "buy_tax_sum": Decimal("0"),
        "sell_tax_sum": Decimal("0"),
        "missing_filled_amount_fallback_count": 0,
    }

    for order in orders:
        if not isinstance(order, Mapping):
            aggregates["skipped_execution_count"] += 1
            continue

        execution = order.get("execution") if isinstance(order.get("execution"), Mapping) else {}
        filled_quantity = _to_decimal(execution.get("filled_quantity"))
        if filled_quantity is None or filled_quantity <= 0:
            aggregates["skipped_execution_count"] += 1
            continue

        side = str(order.get("side") or "").upper()
        if side not in {"BUY", "SELL"}:
            aggregates["skipped_execution_count"] += 1
            continue

        filled_amount = _to_decimal(execution.get("filled_amount"))
        if filled_amount is None:
            average_filled_price = _to_decimal(execution.get("average_filled_price"))
            if average_filled_price is None:
                aggregates["skipped_execution_count"] += 1
                continue
            filled_amount = filled_quantity * average_filled_price
            aggregates["missing_filled_amount_fallback_count"] += 1

        commission = _to_decimal(execution.get("commission")) or Decimal("0")
        tax = _to_decimal(execution.get("tax")) or Decimal("0")

        prefix = "buy" if side == "BUY" else "sell"
        aggregates[f"{prefix}_order_count"] += 1
        aggregates[f"{prefix}_filled_quantity_sum"] += filled_quantity
        aggregates[f"{prefix}_filled_amount_sum"] += filled_amount
        aggregates[f"{prefix}_commission_sum"] += commission
        aggregates[f"{prefix}_tax_sum"] += tax

    if aggregates["skipped_execution_count"]:
        warnings.append("Some orders were skipped because filled execution data was unavailable.")
    if aggregates["missing_filled_amount_fallback_count"]:
        warnings.append("Some filled amounts used filled_quantity * average_filled_price fallback.")

    buy_quantity = aggregates["buy_filled_quantity_sum"]
    buy_amount = aggregates["buy_filled_amount_sum"]
    sell_quantity = aggregates["sell_filled_quantity_sum"]
    aggregates["net_filled_quantity"] = buy_quantity - sell_quantity
    aggregates["weighted_average_buy_price"] = _safe_divide(buy_amount, buy_quantity)
    return aggregates


def _build_user_holding_comparison(
    *,
    symbol: str,
    aggregates: Mapping[str, Decimal | int | None],
    warnings: list[str],
) -> dict[str, Any]:
    holdings = list(
        UserHolding.objects.select_related("stock")
        .filter(stock__code=symbol)
        .order_by("stock__code", "id")
    )
    count = len(holdings)
    comparison = {
        "matching_user_holding_exists": count > 0,
        "matching_user_holding_count": count,
        "user_holding_quantity": None,
        "user_holding_average_price": None,
        "quantity_difference": None,
        "average_price_difference": None,
    }

    if count == 0:
        warnings.append("No matching UserHolding exists for this symbol.")
        return comparison

    if count > 1:
        warnings.append("Multiple matching UserHolding rows exist; user-specific details are not returned.")
        return comparison

    holding = holdings[0]
    holding_quantity = Decimal(str(holding.quantity or 0))
    holding_average_price = Decimal(str(holding.average_price or "0"))
    net_quantity = aggregates.get("net_filled_quantity")
    weighted_average = aggregates.get("weighted_average_buy_price")

    quantity_difference = holding_quantity - net_quantity if isinstance(net_quantity, Decimal) else None
    average_price_difference = (
        holding_average_price - weighted_average if isinstance(weighted_average, Decimal) else None
    )

    comparison.update(
        {
            "user_holding_quantity": _format_quantity(holding_quantity),
            "user_holding_average_price": _format_money(holding_average_price),
            "quantity_difference": _format_quantity(quantity_difference),
            "average_price_difference": _format_money(average_price_difference),
        }
    )
    return comparison


def _format_aggregates(aggregates: Mapping[str, Decimal | int | None]) -> dict[str, str | int | None]:
    return {
        "buy_order_count": int(aggregates["buy_order_count"]),
        "sell_order_count": int(aggregates["sell_order_count"]),
        "skipped_execution_count": int(aggregates["skipped_execution_count"]),
        "buy_filled_quantity_sum": _format_quantity(aggregates["buy_filled_quantity_sum"]),
        "sell_filled_quantity_sum": _format_quantity(aggregates["sell_filled_quantity_sum"]),
        "net_filled_quantity": _format_quantity(aggregates["net_filled_quantity"]),
        "buy_filled_amount_sum": _format_money(aggregates["buy_filled_amount_sum"]),
        "sell_filled_amount_sum": _format_money(aggregates["sell_filled_amount_sum"]),
        "buy_commission_sum": _format_money(aggregates["buy_commission_sum"]),
        "sell_commission_sum": _format_money(aggregates["sell_commission_sum"]),
        "buy_tax_sum": _format_money(aggregates["buy_tax_sum"]),
        "sell_tax_sum": _format_money(aggregates["sell_tax_sum"]),
        "weighted_average_buy_price": _format_money(aggregates["weighted_average_buy_price"]),
    }


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, str) and value.strip() == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _safe_divide(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == Decimal("0"):
        return None
    return numerator / denominator


def _format_money(value: Decimal | int | None) -> str | None:
    if value is None:
        return None
    return str(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _format_quantity(value: Decimal | int | None) -> str | None:
    if value is None:
        return None
    decimal_value = Decimal(value).normalize()
    if decimal_value == decimal_value.to_integral_value():
        return str(decimal_value.quantize(Decimal("1")))
    return format(decimal_value, "f")


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
