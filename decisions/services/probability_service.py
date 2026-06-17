import logging
from decimal import Decimal, ROUND_HALF_UP

from decisions.models import RiskEvent
from decisions.services.averaging_decision_service import evaluate_averaging_timing
from decisions.services.investor_flow_service import get_recent_investor_flows
from decisions.services.probability_components import (
    PRICE_QUANT,
    calculate_probability_confidence,
    calculate_score_component,
    calculate_volatility_component,
    clamp,
    combine_probability_components,
    normalize_probabilities,
    quantize_probability,
)
from decisions.services.probability_dataclasses import (
    AveragingScenario,
    PROBABILITY_DISCLAIMER_TEXT,
    ProbabilityResult,
)
from decisions.services.probability_historical import (
    build_probability_feature_snapshot,
    calculate_historical_probabilities,
)
from decisions.services.probability_labels import (
    get_confidence_label,
    get_failure_probability_label,
    get_success_probability_label,
)
from decisions.services.risk_event_service import get_active_risk_events, has_critical_risk
from decisions.services.support_service import find_support_zone
from indicators.services.indicator_service import calculate_atr, calculate_moving_average, calculate_rsi, calculate_volume_ma
from marketdata.services.market_service import get_market_context
from marketdata.services.price_service import extract_close_prices, extract_volumes, get_latest_price, get_recent_prices

logger = logging.getLogger(__name__)


def _to_decimal(value):
    return Decimal(str(value))


def _quantize_price(value):
    return _to_decimal(value).quantize(PRICE_QUANT, rounding=ROUND_HALF_UP)


def _stringify_decimal_tree(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _stringify_decimal_tree(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_stringify_decimal_tree(item) for item in value]
    return value


def validate_scenario(scenario: AveragingScenario):
    if scenario.buy_price <= 0:
        raise ValueError("buy_price must be greater than zero.")
    if scenario.buy_quantity <= 0:
        raise ValueError("buy_quantity must be greater than zero.")
    if scenario.lookahead_days < 5 or scenario.lookahead_days > 120:
        raise ValueError("lookahead_days must be between 5 and 120.")
    if scenario.target_profit_rate < 0:
        raise ValueError("target_profit_rate cannot be negative.")
    if scenario.target_type == "manual" and not scenario.manual_target_price:
        raise ValueError("manual_target_price is required when target_type is manual.")
    if scenario.stop_loss_type == "manual" and not scenario.stop_loss_price:
        raise ValueError("stop_loss_price is required when stop_loss_type is manual.")
    if scenario.same_day_hit_policy not in {"conservative", "optimistic", "neutral"}:
        raise ValueError("same_day_hit_policy is invalid.")


def calculate_new_average_price(
    current_average_price: Decimal,
    current_quantity: int,
    buy_price: Decimal,
    buy_quantity: int,
) -> Decimal:
    if current_average_price <= 0:
        raise ValueError("current_average_price must be greater than zero.")
    if current_quantity <= 0:
        raise ValueError("current_quantity must be greater than zero.")
    if buy_price <= 0:
        raise ValueError("buy_price must be greater than zero.")
    if buy_quantity <= 0:
        raise ValueError("buy_quantity must be greater than zero.")

    total_cost = (current_average_price * Decimal(current_quantity)) + (buy_price * Decimal(buy_quantity))
    total_quantity = Decimal(current_quantity + buy_quantity)
    return _quantize_price(total_cost / total_quantity)


def calculate_target_price(
    *,
    current_average_price: Decimal,
    current_quantity: int,
    buy_price: Decimal,
    buy_quantity: int,
    target_type: str,
    target_profit_rate: Decimal = Decimal("0"),
    manual_target_price: Decimal | None = None,
) -> Decimal:
    new_average_price = calculate_new_average_price(
        current_average_price=current_average_price,
        current_quantity=current_quantity,
        buy_price=buy_price,
        buy_quantity=buy_quantity,
    )
    if target_type == "new_average_price":
        return new_average_price
    if target_type == "new_average_price_plus_profit":
        if target_profit_rate < 0:
            raise ValueError("target_profit_rate cannot be negative.")
        return _quantize_price(new_average_price * (Decimal("1") + target_profit_rate))
    if target_type == "manual":
        if manual_target_price is None or manual_target_price <= 0:
            raise ValueError("manual_target_price must be greater than zero.")
        return _quantize_price(manual_target_price)
    raise ValueError("Unsupported target_type.")


def calculate_probability_stop_loss_price(
    *,
    current_price: Decimal,
    stop_loss_type: str,
    manual_stop_loss_price: Decimal | None = None,
    support_price: Decimal | None = None,
    atr14: Decimal | None = None,
    fixed_rate: Decimal = Decimal("0.07"),
) -> Decimal:
    current_price = _to_decimal(current_price)
    if current_price <= 0:
        raise ValueError("current_price must be greater than zero.")

    if stop_loss_type == "manual":
        if manual_stop_loss_price is None or manual_stop_loss_price <= 0:
            raise ValueError("manual_stop_loss_price must be greater than zero.")
        if manual_stop_loss_price >= current_price:
            raise ValueError("manual_stop_loss_price must be less than current_price.")
        return _quantize_price(manual_stop_loss_price)

    if stop_loss_type == "support":
        if support_price is None or support_price <= 0:
            raise ValueError("support_price is required for support stop loss.")
        return _quantize_price(_to_decimal(support_price) * Decimal("0.97"))

    if stop_loss_type == "atr":
        if atr14 is None or atr14 <= 0:
            raise ValueError("atr14 is required for atr stop loss.")
        return _quantize_price(current_price - (_to_decimal(atr14) * Decimal("1.5")))

    if stop_loss_type == "fixed_rate":
        if fixed_rate <= 0 or fixed_rate >= 1:
            raise ValueError("fixed_rate must be between 0 and 1.")
        return _quantize_price(current_price * (Decimal("1") - fixed_rate))

    if stop_loss_type == "support_or_atr":
        if support_price is not None and support_price > 0:
            return _quantize_price(_to_decimal(support_price) * Decimal("0.97"))
        if atr14 is not None and atr14 > 0:
            return _quantize_price(current_price - (_to_decimal(atr14) * Decimal("1.5")))
        return _quantize_price(current_price * Decimal("0.93"))

    raise ValueError("Unsupported stop_loss_type.")


def calculate_data_quality(
    *,
    latest_price,
    price_rows,
    atr14,
    indicators_available: bool,
    flow_rows=None,
    market_rows=None,
    risk_events=None,
) -> Decimal:
    quality = Decimal("0")
    if latest_price is not None:
        quality += Decimal("0.20")
    if len(price_rows) >= 60:
        quality += Decimal("0.25")
    elif len(price_rows) >= 20:
        quality += Decimal("0.15")
    if atr14 is not None or len(price_rows) >= 2:
        quality += Decimal("0.15")
    if indicators_available:
        quality += Decimal("0.15")
    if flow_rows:
        quality += Decimal("0.10")
    if market_rows:
        quality += Decimal("0.10")
    if risk_events is not None:
        quality += Decimal("0.05")
    return quantize_probability(clamp(quality, Decimal("0"), Decimal("1")))


def _build_unavailable_result(scenario: AveragingScenario) -> ProbabilityResult:
    warnings = ["최신 가격 데이터가 없어 확률을 계산할 수 없습니다."]
    return ProbabilityResult(
        success_probability=Decimal("0.0000"),
        failure_probability=Decimal("0.0000"),
        neutral_probability=Decimal("1.0000"),
        success_label=get_success_probability_label(Decimal("0.0000")),
        failure_label=get_failure_probability_label(Decimal("0.0000")),
        confidence=Decimal("0.0000"),
        confidence_label=get_confidence_label(Decimal("0.0000")),
        target_price=Decimal("0.00"),
        stop_loss_price=Decimal("0.00"),
        new_average_price=Decimal("0.00"),
        lookahead_days=scenario.lookahead_days,
        basis={
            "scenario": {
                "buy_price": str(scenario.buy_price),
                "buy_quantity": scenario.buy_quantity,
                "lookahead_days": scenario.lookahead_days,
                "target_type": scenario.target_type,
                "target_profit_rate": str(scenario.target_profit_rate),
                "stop_loss_type": scenario.stop_loss_type,
                "same_day_hit_policy": scenario.same_day_hit_policy,
            },
        },
        warnings=warnings,
        disclaimer=PROBABILITY_DISCLAIMER_TEXT,
    )


def _build_critical_override_result(
    *,
    scenario: AveragingScenario,
    current_price: Decimal,
    new_average_price: Decimal,
    target_price: Decimal,
    stop_loss_price: Decimal,
    critical_events,
) -> ProbabilityResult:
    warnings = ["치명적 위험 이벤트가 감지되어 확률 계산보다 리스크 차단이 우선입니다."]
    basis = {
        "scenario": {
            "buy_price": str(scenario.buy_price),
            "buy_quantity": scenario.buy_quantity,
            "lookahead_days": scenario.lookahead_days,
            "target_type": scenario.target_type,
            "target_profit_rate": str(scenario.target_profit_rate),
            "stop_loss_type": scenario.stop_loss_type,
            "same_day_hit_policy": scenario.same_day_hit_policy,
        },
        "prices": {
            "current_price": str(current_price),
            "new_average_price": str(new_average_price),
            "target_price": str(target_price),
            "stop_loss_price": str(stop_loss_price),
        },
        "critical_risk_events": [event.title for event in critical_events],
    }
    return ProbabilityResult(
        success_probability=Decimal("0.0200"),
        failure_probability=Decimal("0.9500"),
        neutral_probability=Decimal("0.0300"),
        success_label=get_success_probability_label(Decimal("0.0200")),
        failure_label=get_failure_probability_label(Decimal("0.9500")),
        confidence=Decimal("0.9000"),
        confidence_label=get_confidence_label(Decimal("0.9000")),
        target_price=target_price,
        stop_loss_price=stop_loss_price,
        new_average_price=new_average_price,
        lookahead_days=scenario.lookahead_days,
        basis=basis,
        warnings=warnings,
        disclaimer=PROBABILITY_DISCLAIMER_TEXT,
    )


def calculate_averaging_success_failure_probability(
    *,
    holding,
    scenario: AveragingScenario,
) -> ProbabilityResult:
    validate_scenario(scenario)

    stock = holding.stock
    latest_price = get_latest_price(stock)
    if latest_price is None:
        logger.info(
            "Latest price missing during probability evaluation",
            extra={"holding_id": holding.id, "stock_code": stock.code},
        )
        return _build_unavailable_result(scenario)

    price_rows = get_recent_prices(stock, limit=720, ascending=True)
    current_price = latest_price.close_price
    new_average_price = calculate_new_average_price(
        holding.average_price,
        holding.quantity,
        scenario.buy_price,
        scenario.buy_quantity,
    )
    target_price = calculate_target_price(
        current_average_price=holding.average_price,
        current_quantity=holding.quantity,
        buy_price=scenario.buy_price,
        buy_quantity=scenario.buy_quantity,
        target_type=scenario.target_type,
        target_profit_rate=scenario.target_profit_rate,
        manual_target_price=scenario.manual_target_price,
    )

    support_zone = find_support_zone(price_rows)
    support_price = support_zone["support_price"]
    atr14 = calculate_atr(price_rows, 14)
    stop_loss_price = calculate_probability_stop_loss_price(
        current_price=current_price,
        stop_loss_type=scenario.stop_loss_type,
        manual_stop_loss_price=scenario.stop_loss_price,
        support_price=support_price,
        atr14=atr14,
    )

    active_risk_events = get_active_risk_events(stock)
    risk_event_rows = list(RiskEvent.objects.filter(stock=stock).order_by("event_date"))
    critical_risk = has_critical_risk(stock)
    if critical_risk["has_critical"]:
        logger.info(
            "Critical risk override used during probability evaluation",
            extra={
                "holding_id": holding.id,
                "stock_code": stock.code,
                "critical_event_count": len(critical_risk["events"]),
            },
        )
        return _build_critical_override_result(
            scenario=scenario,
            current_price=current_price,
            new_average_price=new_average_price,
            target_price=target_price,
            stop_loss_price=stop_loss_price,
            critical_events=critical_risk["events"],
        )

    evaluation_result = evaluate_averaging_timing(holding)
    target_return = quantize_probability((target_price - current_price) / current_price)
    stop_loss_return = quantize_probability((current_price - stop_loss_price) / current_price)

    close_prices = extract_close_prices(price_rows)
    indicators_available = (
        calculate_rsi(close_prices, 14) is not None
        and calculate_moving_average(close_prices, 20) is not None
    )
    flow_rows = get_recent_investor_flows(stock, limit=5, ascending=True)
    market_context = get_market_context(stock)
    market_rows = market_context["market_index_rows"]
    current_snapshot = build_probability_feature_snapshot(
        price_rows=price_rows,
        reference_price=holding.average_price,
        flow_rows=flow_rows,
        market_rows=market_rows,
        active_risk_events=active_risk_events,
    )

    historical_component = calculate_historical_probabilities(
        stock=stock,
        current_snapshot=current_snapshot,
        target_return=target_return,
        stop_loss_return=stop_loss_return,
        lookahead_days=scenario.lookahead_days,
        same_day_hit_policy=scenario.same_day_hit_policy,
        price_rows=price_rows,
        flow_rows=flow_rows,
        market_rows=market_rows,
        active_risk_events=active_risk_events,
    )
    score_component = calculate_score_component(
        score=evaluation_result.score,
        grade=evaluation_result.grade,
        active_risk_events=active_risk_events,
    )
    volatility_component = calculate_volatility_component(
        current_price=current_price,
        target_price=target_price,
        stop_loss_price=stop_loss_price,
        price_rows=price_rows,
        atr14=atr14,
        lookahead_days=scenario.lookahead_days,
        trend_score=evaluation_result.score_breakdown.get("trend", 0),
    )
    combined = combine_probability_components(
        historical=historical_component,
        score=score_component,
        volatility=volatility_component,
    )

    data_quality = calculate_data_quality(
        latest_price=latest_price,
        price_rows=price_rows,
        atr14=atr14,
        indicators_available=indicators_available,
        flow_rows=flow_rows,
        market_rows=market_rows,
        risk_events=active_risk_events,
    )
    confidence = calculate_probability_confidence(
        historical=historical_component,
        score=score_component,
        volatility=volatility_component,
        data_quality=data_quality,
    )
    normalized = normalize_probabilities(
        combined["success"],
        combined["failure"],
        combined["neutral"],
    )

    volume_ma20 = calculate_volume_ma(extract_volumes(price_rows), 20)
    warnings = []
    warnings.extend(historical_component.warnings)
    warnings.extend(score_component.warnings)
    warnings.extend(volatility_component.warnings)
    if historical_component.sample_count < 30:
        warnings.append("historical sample이 부족해 score/volatility 비중을 높였습니다.")
    warnings.extend(
        [
            "확률은 과거 데이터와 현재 조건 기반의 추정값입니다.",
            "미래 수익을 보장하지 않습니다.",
        ]
    )

    basis = _stringify_decimal_tree(
        {
            "scenario": {
                "buy_price": scenario.buy_price,
                "buy_quantity": scenario.buy_quantity,
                "lookahead_days": scenario.lookahead_days,
                "target_type": scenario.target_type,
                "target_profit_rate": scenario.target_profit_rate,
                "manual_target_price": scenario.manual_target_price,
                "stop_loss_type": scenario.stop_loss_type,
                "stop_loss_price": scenario.stop_loss_price,
                "same_day_hit_policy": scenario.same_day_hit_policy,
            },
            "prices": {
                "current_price": current_price,
                "new_average_price": new_average_price,
                "target_price": target_price,
                "stop_loss_price": stop_loss_price,
                "target_return": target_return,
                "stop_loss_return": stop_loss_return,
                "support_price": support_price,
                "atr14": atr14,
                "volume_ma20": volume_ma20,
            },
            "components": {
                "historical": historical_component.details,
                "score": score_component.details,
                "volatility": volatility_component.details,
            },
            "weights": combined["weights"],
            "score_context": {
                "score": evaluation_result.score,
                "grade": evaluation_result.grade,
                "score_breakdown": evaluation_result.score_breakdown,
            },
        }
    )

    result = ProbabilityResult(
        success_probability=normalized["success"],
        failure_probability=normalized["failure"],
        neutral_probability=normalized["neutral"],
        success_label=get_success_probability_label(normalized["success"]),
        failure_label=get_failure_probability_label(normalized["failure"]),
        confidence=confidence,
        confidence_label=get_confidence_label(confidence),
        target_price=_quantize_price(target_price),
        stop_loss_price=_quantize_price(stop_loss_price),
        new_average_price=_quantize_price(new_average_price),
        lookahead_days=scenario.lookahead_days,
        basis=basis,
        warnings=warnings,
        disclaimer=PROBABILITY_DISCLAIMER_TEXT,
    )
    logger.info(
        "Probability result calculated",
        extra={
            "holding_id": holding.id,
            "stock_code": stock.code,
            "success_probability": str(result.success_probability),
            "failure_probability": str(result.failure_probability),
            "confidence": str(result.confidence),
        },
    )
    return result
