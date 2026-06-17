from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from marketdata.services.price_service import get_latest_price


@dataclass(frozen=True)
class CapitalPlanResult:
    max_allowed_budget: Decimal
    first_entry_budget: Decimal
    second_entry_budget: Decimal
    third_entry_budget: Decimal
    first_entry_condition: str
    second_entry_condition: str
    third_entry_condition: str
    stop_loss_price: Optional[Decimal]
    estimated_max_loss: Optional[Decimal]
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


def _to_decimal(value):
    return Decimal(str(value))


def _quantize_budget(value):
    return _to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _risk_multiplier(status):
    return {
        "PASS": Decimal("1.00"),
        "CAUTION": Decimal("0.50"),
        "BLOCK": Decimal("0.00"),
        "CRITICAL": Decimal("0.00"),
    }.get(status, Decimal("0.00"))


def _market_multiplier(regime):
    return {
        "risk_on": Decimal("1.00"),
        "pullback": Decimal("0.80"),
        "sideways": Decimal("0.60"),
        "risk_off": Decimal("0.30"),
        "capitulation": Decimal("0.00"),
        "unknown": Decimal("0.50"),
        "rebound": Decimal("0.80"),
    }.get(regime, Decimal("0.50"))


def _data_quality_multiplier(label):
    return {
        "높음": Decimal("1.00"),
        "보통": Decimal("0.80"),
        "낮음": Decimal("0.50"),
        "매우 낮음": Decimal("0.00"),
    }.get(label, Decimal("0.50"))


def _select_stop_loss_price(scenario_items):
    if not scenario_items:
        return None

    for item in scenario_items:
        if item.scenario_type == "base":
            return item.stop_loss_price
    return scenario_items[0].stop_loss_price


def build_capital_plan(
    holding,
    *,
    risk_gate_result,
    market_regime_result,
    data_quality_result,
    scenario_items=None,
):
    scenario_items = scenario_items or []
    warnings = []

    risk_multiplier = _risk_multiplier(risk_gate_result.status)
    market_multiplier = _market_multiplier(market_regime_result.regime)
    data_quality_multiplier = _data_quality_multiplier(data_quality_result.label)
    max_allowed_budget = _quantize_budget(
        holding.max_additional_budget * risk_multiplier * market_multiplier * data_quality_multiplier
    )

    blocked_condition = "현재 리스크 조건에서는 추가 매수 검토를 중단하고 재평가 조건 충족 여부를 확인"
    first_entry_condition = "현재 조건이 유지되고 치명적 리스크가 없을 때만 검토"
    second_entry_condition = "20일 이동평균 회복 후 2거래일 이상 유지"
    third_entry_condition = "거래량 증가와 함께 직전 고점 돌파 확인"

    if risk_gate_result.status in {"BLOCK", "CRITICAL"} or max_allowed_budget == 0:
        return CapitalPlanResult(
            max_allowed_budget=max_allowed_budget,
            first_entry_budget=Decimal("0.00"),
            second_entry_budget=Decimal("0.00"),
            third_entry_budget=Decimal("0.00"),
            first_entry_condition=blocked_condition,
            second_entry_condition=blocked_condition,
            third_entry_condition=blocked_condition,
            stop_loss_price=_select_stop_loss_price(scenario_items),
            estimated_max_loss=Decimal("0.00"),
            warnings=warnings,
            details={
                "risk_multiplier": risk_multiplier,
                "market_multiplier": market_multiplier,
                "data_quality_multiplier": data_quality_multiplier,
            },
        )

    stop_loss_price = _select_stop_loss_price(scenario_items)
    latest_price = get_latest_price(holding.stock)
    estimated_max_loss = None
    if latest_price is not None and stop_loss_price is not None and latest_price.close_price > stop_loss_price:
        loss_rate = (latest_price.close_price - stop_loss_price) / latest_price.close_price
        estimated_max_loss = _quantize_budget(max_allowed_budget * loss_rate)
    elif stop_loss_price is None:
        warnings.append("손절 기준 가격이 없어 최대 손실 추정은 제한적입니다.")
    else:
        warnings.append("최신 가격 데이터가 없어 최대 손실 추정은 제한적입니다.")

    if risk_gate_result.status == "CAUTION":
        warnings.append("주의 구간이라 2차·3차 분할 예산은 보류합니다.")
        return CapitalPlanResult(
            max_allowed_budget=max_allowed_budget,
            first_entry_budget=max_allowed_budget,
            second_entry_budget=Decimal("0.00"),
            third_entry_budget=Decimal("0.00"),
            first_entry_condition=first_entry_condition,
            second_entry_condition="리스크 완화와 추세 확인 전에는 2차 진입을 보류",
            third_entry_condition="시장과 수급 개선 확인 전에는 3차 진입을 보류",
            stop_loss_price=stop_loss_price,
            estimated_max_loss=estimated_max_loss,
            warnings=warnings,
            details={
                "risk_multiplier": risk_multiplier,
                "market_multiplier": market_multiplier,
                "data_quality_multiplier": data_quality_multiplier,
            },
        )

    return CapitalPlanResult(
        max_allowed_budget=max_allowed_budget,
        first_entry_budget=_quantize_budget(max_allowed_budget * Decimal("0.40")),
        second_entry_budget=_quantize_budget(max_allowed_budget * Decimal("0.30")),
        third_entry_budget=_quantize_budget(max_allowed_budget * Decimal("0.30")),
        first_entry_condition=first_entry_condition,
        second_entry_condition=second_entry_condition,
        third_entry_condition=third_entry_condition,
        stop_loss_price=stop_loss_price,
        estimated_max_loss=estimated_max_loss,
        warnings=warnings,
        details={
            "risk_multiplier": risk_multiplier,
            "market_multiplier": market_multiplier,
            "data_quality_multiplier": data_quality_multiplier,
        },
    )
