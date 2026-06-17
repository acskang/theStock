from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from decisions.services.probability_dataclasses import AveragingScenario
from decisions.services.probability_service import (
    calculate_averaging_success_failure_probability,
    calculate_new_average_price,
    calculate_probability_stop_loss_price,
    calculate_target_price,
)
from decisions.services.support_service import find_support_zone
from indicators.services.indicator_service import calculate_atr
from marketdata.services.price_service import get_latest_price, get_recent_prices


@dataclass(frozen=True)
class ScenarioComparisonItem:
    scenario_type: str
    buy_price: Decimal
    buy_quantity: int
    new_average_price: Decimal
    target_price: Decimal
    stop_loss_price: Decimal
    success_probability: Optional[Decimal]
    failure_probability: Optional[Decimal]
    neutral_probability: Optional[Decimal]
    confidence: Optional[Decimal]
    efficiency_score: Decimal
    status: str
    reason_summary: Optional[str] = None
    probability_explanation: Optional[dict] = None
    warnings: list[str] = field(default_factory=list)


def _to_decimal(value):
    return Decimal(str(value))


def _quantize_probability(value):
    return _to_decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _quantize_price(value):
    return _to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _round_half_up_quantity(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def build_default_scenarios(holding, buy_price=None, lookahead_days=20):
    warnings = []
    if buy_price is None:
        latest_price = get_latest_price(holding.stock)
        if latest_price is None:
            return {
                "scenarios": [],
                "warnings": ["최신 가격 데이터가 없어 기본 시나리오를 생성할 수 없습니다."],
            }
        resolved_buy_price = latest_price.close_price
    else:
        resolved_buy_price = buy_price

    conservative_quantity = max(1, _round_half_up_quantity(Decimal(holding.quantity) * Decimal("0.25")))
    base_quantity = max(1, _round_half_up_quantity(Decimal(holding.quantity) * Decimal("0.50")))
    aggressive_quantity = max(1, int(holding.quantity))

    return {
        "scenarios": [
            {
                "scenario_type": "conservative",
                "buy_price": _to_decimal(resolved_buy_price),
                "buy_quantity": conservative_quantity,
                "lookahead_days": lookahead_days,
            },
            {
                "scenario_type": "base",
                "buy_price": _to_decimal(resolved_buy_price),
                "buy_quantity": base_quantity,
                "lookahead_days": lookahead_days,
            },
            {
                "scenario_type": "aggressive",
                "buy_price": _to_decimal(resolved_buy_price),
                "buy_quantity": aggressive_quantity,
                "lookahead_days": lookahead_days,
            },
        ],
        "warnings": warnings,
    }


def _fallback_price_context(holding, buy_price, buy_quantity, target_profit_rate, stop_loss_type, stop_loss_price):
    price_rows = get_recent_prices(holding.stock, limit=120, ascending=True)
    support_zone = find_support_zone(price_rows)
    atr14 = calculate_atr(price_rows, 14)
    latest_price = get_latest_price(holding.stock)
    current_price = buy_price if latest_price is None else latest_price.close_price
    target_type = "new_average_price_plus_profit" if target_profit_rate and target_profit_rate > 0 else "new_average_price"
    new_average_price = calculate_new_average_price(
        holding.average_price,
        holding.quantity,
        buy_price,
        buy_quantity,
    )
    target_price = calculate_target_price(
        current_average_price=holding.average_price,
        current_quantity=holding.quantity,
        buy_price=buy_price,
        buy_quantity=buy_quantity,
        target_type=target_type,
        target_profit_rate=Decimal("0") if target_profit_rate is None else target_profit_rate,
    )
    calculated_stop_loss = calculate_probability_stop_loss_price(
        current_price=current_price,
        stop_loss_type=stop_loss_type,
        manual_stop_loss_price=stop_loss_price,
        support_price=support_zone["support_price"],
        atr14=atr14,
    )
    return {
        "new_average_price": new_average_price,
        "target_price": target_price,
        "stop_loss_price": calculated_stop_loss,
    }


def _calculate_efficiency_score(holding, buy_price, buy_quantity, success_probability, failure_probability, confidence):
    if success_probability is None or failure_probability is None or confidence is None:
        return Decimal("0.0000")

    additional_amount = _to_decimal(buy_price) * Decimal(buy_quantity)
    if not holding.max_additional_budget or holding.max_additional_budget <= 0:
        capital_pressure_penalty = Decimal("0.2")
    else:
        capital_pressure_penalty = (additional_amount / holding.max_additional_budget) * Decimal("0.2")

    score = (
        success_probability
        - (failure_probability * Decimal("1.3"))
        - capital_pressure_penalty
        + (confidence * Decimal("0.1"))
    )
    return _quantize_probability(score)


def _determine_status(risk_gate_result, success_probability, failure_probability, confidence):
    if risk_gate_result and risk_gate_result.status in {"CRITICAL", "BLOCK"}:
        return "금지"
    if failure_probability is not None and failure_probability >= Decimal("0.4500"):
        return "위험"
    if (
        success_probability is not None
        and failure_probability is not None
        and confidence is not None
        and success_probability >= Decimal("0.5500")
        and failure_probability < Decimal("0.3000")
        and confidence >= Decimal("0.5000")
    ):
        return "제한 검토"
    if confidence is not None and confidence < Decimal("0.4000"):
        return "신뢰도 낮음"
    return "관찰"


def _build_scenario_reason_summary(
    *,
    scenario_type,
    buy_price,
    buy_quantity,
    new_average_price,
    target_price,
    stop_loss_price,
    status,
    probability_available,
):
    type_labels = {
        "conservative": "보수적",
        "base": "기준",
        "aggressive": "공격적",
    }
    summary = (
        f"{type_labels.get(scenario_type, scenario_type)} 시나리오는 매수가 {buy_price}, 수량 {buy_quantity}주 기준이며 "
        f"새 평단 {new_average_price}, 목표가 {target_price}, 손절가 {stop_loss_price}로 계산했습니다."
    )
    if probability_available:
        summary += f" 현재 상태 평가는 {status}입니다."
    else:
        summary += " 확률 엔진 unavailable fallback 기준이라 가격 컨텍스트 중심으로만 산출했습니다."
    return summary


def _extract_probability_explanation(probability_result):
    basis = getattr(probability_result, "basis", None) or {}
    historical = ((basis.get("components") or {}).get("historical") or {})
    if not historical:
        return None
    return {
        "selection_summary": historical.get("selection_summary"),
        "outcome_bias_summary": historical.get("outcome_bias_summary"),
        "selected_case_count": historical.get("selected_case_count"),
        "selected_threshold": historical.get("selected_threshold"),
        "avg_distance": historical.get("avg_distance"),
        "closest_features": historical.get("closest_features"),
        "weakest_features": historical.get("weakest_features"),
        "outcome_case_groups": historical.get("outcome_case_groups"),
    }


def build_fallback_scenario_items(
    holding,
    *,
    buy_price=None,
    lookahead_days=20,
    target_profit_rate=None,
    stop_loss_type="support_or_atr",
    stop_loss_price=None,
    risk_gate_result=None,
):
    scenario_bundle = build_default_scenarios(holding, buy_price=buy_price, lookahead_days=lookahead_days)
    warnings = list(scenario_bundle["warnings"])
    items = []

    for scenario_def in scenario_bundle["scenarios"]:
        resolved_buy_price = _to_decimal(scenario_def["buy_price"])
        resolved_buy_quantity = int(scenario_def["buy_quantity"])
        fallback_context = _fallback_price_context(
            holding,
            resolved_buy_price,
            resolved_buy_quantity,
            Decimal("0") if target_profit_rate is None else target_profit_rate,
            stop_loss_type,
            stop_loss_price,
        )
        items.append(
            ScenarioComparisonItem(
                scenario_type=scenario_def["scenario_type"],
                buy_price=_quantize_price(resolved_buy_price),
                buy_quantity=resolved_buy_quantity,
                new_average_price=_quantize_price(fallback_context["new_average_price"]),
                target_price=_quantize_price(fallback_context["target_price"]),
                stop_loss_price=_quantize_price(fallback_context["stop_loss_price"]),
                success_probability=None,
                failure_probability=None,
                neutral_probability=None,
                confidence=None,
                efficiency_score=Decimal("0.0000"),
                status=_determine_status(risk_gate_result, None, None, None),
                reason_summary=_build_scenario_reason_summary(
                    scenario_type=scenario_def["scenario_type"],
                    buy_price=_quantize_price(resolved_buy_price),
                    buy_quantity=resolved_buy_quantity,
                    new_average_price=_quantize_price(fallback_context["new_average_price"]),
                    target_price=_quantize_price(fallback_context["target_price"]),
                    stop_loss_price=_quantize_price(fallback_context["stop_loss_price"]),
                    status=_determine_status(risk_gate_result, None, None, None),
                    probability_available=False,
                ),
                probability_explanation=None,
                warnings=["Probability Engine unavailable fallback scenario"],
            )
        )

    return {
        "items": items,
        "warnings": warnings,
    }


def compare_scenarios(
    holding,
    *,
    buy_price=None,
    lookahead_days=20,
    target_profit_rate=None,
    stop_loss_type="support_or_atr",
    stop_loss_price=None,
    risk_gate_result=None,
):
    scenario_bundle = build_default_scenarios(holding, buy_price=buy_price, lookahead_days=lookahead_days)
    warnings = list(scenario_bundle["warnings"])
    items = []
    probability_engine_warning_added = False

    for scenario_def in scenario_bundle["scenarios"]:
        scenario_warnings = []
        resolved_buy_price = _to_decimal(scenario_def["buy_price"])
        resolved_buy_quantity = int(scenario_def["buy_quantity"])
        target_type = "new_average_price_plus_profit" if target_profit_rate and target_profit_rate > 0 else "new_average_price"

        try:
            probability_result = calculate_averaging_success_failure_probability(
                holding=holding,
                scenario=AveragingScenario(
                    buy_price=resolved_buy_price,
                    buy_quantity=resolved_buy_quantity,
                    lookahead_days=lookahead_days,
                    target_type=target_type,
                    target_profit_rate=Decimal("0") if target_profit_rate is None else target_profit_rate,
                    stop_loss_type=stop_loss_type,
                    stop_loss_price=stop_loss_price,
                ),
            )
            success_probability = probability_result.success_probability
            failure_probability = probability_result.failure_probability
            neutral_probability = probability_result.neutral_probability
            confidence = probability_result.confidence
            new_average_price = probability_result.new_average_price
            target_price = probability_result.target_price
            resolved_stop_loss_price = probability_result.stop_loss_price
            probability_explanation = _extract_probability_explanation(probability_result)
            scenario_warnings.extend(probability_result.warnings)
        except Exception:
            if not probability_engine_warning_added:
                warnings.append("Probability Engine을 사용할 수 없어 시나리오 확률 계산을 생략했습니다.")
                probability_engine_warning_added = True

            fallback_context = _fallback_price_context(
                holding,
                resolved_buy_price,
                resolved_buy_quantity,
                Decimal("0") if target_profit_rate is None else target_profit_rate,
                stop_loss_type,
                stop_loss_price,
            )
            success_probability = None
            failure_probability = None
            neutral_probability = None
            confidence = None
            new_average_price = fallback_context["new_average_price"]
            target_price = fallback_context["target_price"]
            resolved_stop_loss_price = fallback_context["stop_loss_price"]
            probability_explanation = None
            scenario_warnings.append("해당 시나리오의 확률 계산을 생략했습니다.")

        efficiency_score = _calculate_efficiency_score(
            holding,
            resolved_buy_price,
            resolved_buy_quantity,
            success_probability,
            failure_probability,
            confidence,
        )
        status = _determine_status(risk_gate_result, success_probability, failure_probability, confidence)
        quantized_buy_price = _quantize_price(resolved_buy_price)
        quantized_new_average_price = _quantize_price(new_average_price)
        quantized_target_price = _quantize_price(target_price)
        quantized_stop_loss_price = _quantize_price(resolved_stop_loss_price)
        items.append(
            ScenarioComparisonItem(
                scenario_type=scenario_def["scenario_type"],
                buy_price=quantized_buy_price,
                buy_quantity=resolved_buy_quantity,
                new_average_price=quantized_new_average_price,
                target_price=quantized_target_price,
                stop_loss_price=quantized_stop_loss_price,
                success_probability=success_probability,
                failure_probability=failure_probability,
                neutral_probability=neutral_probability,
                confidence=confidence,
                efficiency_score=efficiency_score,
                status=status,
                reason_summary=_build_scenario_reason_summary(
                    scenario_type=scenario_def["scenario_type"],
                    buy_price=quantized_buy_price,
                    buy_quantity=resolved_buy_quantity,
                    new_average_price=quantized_new_average_price,
                    target_price=quantized_target_price,
                    stop_loss_price=quantized_stop_loss_price,
                    status=status,
                    probability_available=success_probability is not None,
                ),
                probability_explanation=probability_explanation,
                warnings=scenario_warnings,
            )
        )

    return {
        "items": items,
        "warnings": warnings,
    }
