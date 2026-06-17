from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP, InvalidOperation

from marketdata.models import DailyPrice


class AdditionalBuySimulationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


SUPPORTED_MARKETS = {"KOSPI", "KOSDAQ", "KONEX", "ETF", "ETN", "KR"}
WARNING_CALCULATION_ONLY = "This is a calculation-only simulation and does not place orders."
WARNING_NOT_INVESTMENT_ADVICE = "This is not investment advice and does not guarantee returns."
WARNING_FEES_TAXES_EXCLUDED = "Fees and taxes are not included."


def _to_decimal(value, *, code: str, message: str) -> Decimal:
    if value is None:
        raise AdditionalBuySimulationError(code, message)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise AdditionalBuySimulationError(code, message)


def _format_money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _format_rate(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _latest_daily_price(stock):
    return DailyPrice.objects.filter(stock=stock).order_by("-date").first()


def _validate_positive(value: Decimal, *, code: str, message: str) -> None:
    if value <= 0:
        raise AdditionalBuySimulationError(code, message)


def _safe_rate(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return (numerator / denominator) * Decimal("100")


def _target_projection(new_quantity: Decimal, target_price: Decimal, total_invested: Decimal) -> dict:
    target_market_value = new_quantity * target_price
    target_profit_loss_amount = target_market_value - total_invested
    target_profit_loss_rate = _safe_rate(target_profit_loss_amount, total_invested)
    return {
        "target_price": _format_money(target_price),
        "target_market_value": _format_money(target_market_value),
        "target_profit_loss_amount": _format_money(target_profit_loss_amount),
        "target_profit_loss_rate": _format_rate(target_profit_loss_rate),
    }


def build_additional_buy_simulation(
    *,
    holding,
    additional_budget=None,
    additional_quantity=None,
    buy_price=None,
    target_price=None,
):
    if holding is None:
        raise AdditionalBuySimulationError("holding_required", "holding is required.")

    if not getattr(holding, "is_active", False):
        raise AdditionalBuySimulationError("inactive_holding", "inactive holding cannot be simulated.")

    if additional_budget is not None and additional_quantity is not None:
        raise AdditionalBuySimulationError(
            "conflicting_input",
            "additional_budget and additional_quantity cannot be used together.",
        )
    if additional_quantity is not None:
        raise AdditionalBuySimulationError(
            "additional_quantity_not_supported",
            "additional_quantity is not supported in this MVP.",
        )
    if additional_budget is None:
        raise AdditionalBuySimulationError(
            "additional_budget_required",
            "additional_budget is required.",
        )

    budget = _to_decimal(
        additional_budget,
        code="invalid_additional_budget",
        message="additional_budget must be greater than zero.",
    )
    _validate_positive(
        budget,
        code="invalid_additional_budget",
        message="additional_budget must be greater than zero.",
    )

    current_quantity = _to_decimal(
        getattr(holding, "quantity", None),
        code="invalid_holding_quantity",
        message="holding quantity is required.",
    )
    _validate_positive(
        current_quantity,
        code="invalid_holding_quantity",
        message="holding quantity must be greater than zero.",
    )

    current_average_price = _to_decimal(
        getattr(holding, "average_price", None),
        code="invalid_holding_price",
        message="holding average_price is required.",
    )
    _validate_positive(
        current_average_price,
        code="invalid_holding_price",
        message="holding average_price must be greater than zero.",
    )

    stock = holding.stock
    market = getattr(stock, "market", "") or ""
    warnings = [WARNING_CALCULATION_ONLY, WARNING_NOT_INVESTMENT_ADVICE, WARNING_FEES_TAXES_EXCLUDED]
    if market and market not in SUPPORTED_MARKETS:
        raise AdditionalBuySimulationError("unsupported_market", "stock market is not supported.")
    if not market:
        warnings.append("Stock market is missing; calculation assumes integer share quantity.")

    latest = _latest_daily_price(stock)
    latest_price = Decimal(str(latest.close_price)) if latest else None

    manual_buy_price = None
    if buy_price is not None:
        manual_buy_price = _to_decimal(
            buy_price,
            code="invalid_buy_price",
            message="buy_price must be greater than zero.",
        )
        _validate_positive(
            manual_buy_price,
            code="invalid_buy_price",
            message="buy_price must be greater than zero.",
        )

    if target_price is not None:
        target_price_decimal = _to_decimal(
            target_price,
            code="invalid_target_price",
            message="target_price must be greater than zero.",
        )
        _validate_positive(
            target_price_decimal,
            code="invalid_target_price",
            message="target_price must be greater than zero.",
        )
    else:
        target_price_decimal = None

    simulation_buy_price = manual_buy_price or latest_price
    if simulation_buy_price is None:
        raise AdditionalBuySimulationError(
            "latest_price_required",
            "latest DailyPrice is required when buy_price is not provided.",
        )

    current_invested_amount = current_quantity * current_average_price
    current_market_value = current_quantity * latest_price if latest_price is not None else None
    current_profit_loss_amount = (
        current_market_value - current_invested_amount if current_market_value is not None else None
    )
    current_profit_loss_rate = _safe_rate(current_profit_loss_amount, current_invested_amount)

    additional_quantity_decimal = (budget / simulation_buy_price).to_integral_value(rounding=ROUND_FLOOR)
    if additional_quantity_decimal < 1:
        raise AdditionalBuySimulationError(
            "additional_quantity_too_small",
            "additional_budget is too small to buy at least one share.",
        )

    additional_invested_amount = additional_quantity_decimal * simulation_buy_price
    unused_budget = budget - additional_invested_amount
    new_quantity = current_quantity + additional_quantity_decimal
    new_total_invested_amount = current_invested_amount + additional_invested_amount
    new_average_price = new_total_invested_amount / new_quantity
    break_even_price = new_average_price

    if latest_price is not None:
        simulated_market_value_at_latest = new_quantity * latest_price
        simulated_profit_loss_amount_at_latest = simulated_market_value_at_latest - new_total_invested_amount
        simulated_profit_loss_rate_at_latest = _safe_rate(
            simulated_profit_loss_amount_at_latest,
            new_total_invested_amount,
        )
        required_rise_to_break_even = _safe_rate(break_even_price - latest_price, latest_price)
    else:
        simulated_market_value_at_latest = None
        simulated_profit_loss_amount_at_latest = None
        simulated_profit_loss_rate_at_latest = None
        required_rise_to_break_even = None
        warnings.append("Latest DailyPrice is missing; current P/L fields are not available.")

    return {
        "simulation_only": True,
        "order_execution": False,
        "stock": {
            "code": stock.code,
            "name": stock.name,
            "market": stock.market,
        },
        "price_source": {
            "type": "manual_buy_price" if manual_buy_price is not None else "daily_price",
            "latest_price": _format_money(latest_price),
            "latest_price_date": latest.date.isoformat() if latest else None,
            "simulation_buy_price": _format_money(simulation_buy_price),
        },
        "current_position": {
            "quantity": int(current_quantity),
            "average_price": _format_money(current_average_price),
            "invested_amount": _format_money(current_invested_amount),
            "market_value": _format_money(current_market_value),
            "profit_loss_amount": _format_money(current_profit_loss_amount),
            "profit_loss_rate": _format_rate(current_profit_loss_rate),
        },
        "input": {
            "additional_budget": _format_money(budget),
            "buy_price": _format_money(manual_buy_price),
            "target_price": _format_money(target_price_decimal),
        },
        "simulation": {
            "additional_quantity": int(additional_quantity_decimal),
            "additional_invested_amount": _format_money(additional_invested_amount),
            "unused_budget": _format_money(unused_budget),
            "new_quantity": int(new_quantity),
            "new_total_invested_amount": _format_money(new_total_invested_amount),
            "new_average_price": _format_money(new_average_price),
            "break_even_price": _format_money(break_even_price),
            "required_rise_to_break_even": _format_rate(required_rise_to_break_even),
            "simulated_market_value_at_latest": _format_money(simulated_market_value_at_latest),
            "simulated_profit_loss_amount_at_latest": _format_money(simulated_profit_loss_amount_at_latest),
            "simulated_profit_loss_rate_at_latest": _format_rate(simulated_profit_loss_rate_at_latest),
        },
        "target_projection": (
            _target_projection(new_quantity, target_price_decimal, new_total_invested_amount)
            if target_price_decimal is not None
            else None
        ),
        "warnings": warnings,
    }
