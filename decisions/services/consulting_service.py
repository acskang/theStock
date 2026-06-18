import logging
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Optional

from decisions.services.averaging_decision_service import evaluate_averaging_timing
from decisions.services.capital_allocation_service import build_capital_plan
from decisions.services.data_quality_service import evaluate_data_quality, get_data_quality_grade_cap
from decisions.services.risk_gate_service import evaluate_risk_gate
from decisions.services.scenario_comparison_service import build_fallback_scenario_items, compare_scenarios
from data_pipeline.models import DataQualitySnapshot
from marketdata.services.market_regime_service import evaluate_market_regime
from marketdata.services.price_service import get_latest_price
from stocks.services.stock_quality_service import evaluate_stock_quality

logger = logging.getLogger(__name__)

CONSULTING_DISCLAIMER_TEXT = (
    "본 결과는 투자 참고용 데이터 분석이며, 매수·매도 추천이 아닙니다. "
    "미래 수익 또는 손실 회피를 보장하지 않습니다. 최종 투자 판단과 책임은 사용자 본인에게 있습니다."
)
GRADE_ORDER = ["A", "B", "C", "D"]


@dataclass(frozen=True)
class ConsultingResult:
    final_grade: str
    consulting_status: str
    summary: str
    risk_gate: dict
    data_quality: dict
    market_regime: dict
    stock_quality: dict
    base_decision: dict
    probability: Optional[dict]
    scenario_table: list[dict]
    capital_plan: dict
    main_blockers: list[str] = field(default_factory=list)
    positive_factors: list[str] = field(default_factory=list)
    recheck_conditions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    disclaimer: str = CONSULTING_DISCLAIMER_TEXT


def _stringify_decimal_tree(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _stringify_decimal_tree(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_stringify_decimal_tree(item) for item in value]
    return value


def _unique_strings(values):
    seen = set()
    result = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _downgrade_grade(grade: str) -> str:
    if grade not in GRADE_ORDER:
        return "D"
    index = GRADE_ORDER.index(grade)
    return GRADE_ORDER[min(index + 1, len(GRADE_ORDER) - 1)]


def cap_grade(grade: str, cap: Optional[str]) -> str:
    if grade not in GRADE_ORDER:
        grade = "D"
    if cap is None:
        return grade
    if cap not in GRADE_ORDER:
        return grade
    return GRADE_ORDER[max(GRADE_ORDER.index(grade), GRADE_ORDER.index(cap))]


def get_consulting_status(final_grade: str) -> str:
    return {
        "A": "추가 매수 가능성 검토 구간",
        "B": "관찰 후 제한 검토 구간",
        "C": "물타기 금지 구간",
        "D": "손절 또는 비중 축소 기준 점검 구간",
    }.get(final_grade, "손절 또는 비중 축소 기준 점검 구간")


def _get_dominant_outcome(success_probability, failure_probability, neutral_probability):
    candidates = [
        ("success", success_probability),
        ("failure", failure_probability),
        ("neutral", neutral_probability),
    ]
    available = [(name, value) for name, value in candidates if value is not None]
    if not available:
        return None
    return max(available, key=lambda item: (item[1], item[0]))[0]


def _build_probability_highlights(
    explanation,
    *,
    success_probability=None,
    failure_probability=None,
    neutral_probability=None,
    fallback_headline=None,
):
    outcome_labels = {
        "success": "성공",
        "failure": "실패",
        "neutral": "중립",
    }
    if not explanation:
        dominant_outcome = _get_dominant_outcome(success_probability, failure_probability, neutral_probability)
        headline = fallback_headline
        if headline is None:
            if dominant_outcome is None:
                headline = "확률 엔진 설명 정보를 사용할 수 없어 점수·리스크·데이터 품질 중심으로 해석했습니다."
            else:
                headline = (
                    f"{outcome_labels.get(dominant_outcome, dominant_outcome)} 확률이 가장 높지만 "
                    "historical 설명 정보는 확보하지 못했습니다."
                )
        return {
            "headline": headline,
            "dominant_outcome": dominant_outcome,
            "selection_summary": None,
            "outcome_bias_summary": None,
            "representative_cases": {
                "success": None,
                "failure": None,
                "neutral": None,
            },
        }

    outcome_case_groups = explanation.get("outcome_case_groups") or {}
    dominant_outcome = None
    dominant_count = -1
    for outcome_name in ("success", "failure", "neutral"):
        count = (outcome_case_groups.get(outcome_name) or {}).get("count", 0)
        if count > dominant_count:
            dominant_outcome = outcome_name
            dominant_count = count

    representative_cases = {
        outcome_name: ((outcome_case_groups.get(outcome_name) or {}).get("examples") or [None])[0]
        for outcome_name in ("success", "failure", "neutral")
    }
    headline = explanation.get("outcome_bias_summary") or explanation.get("selection_summary")
    if dominant_outcome and dominant_count > 0:
        headline = f"{outcome_labels.get(dominant_outcome, dominant_outcome)} 성향 사례가 우세합니다. {headline}"

    return {
        "headline": headline,
        "dominant_outcome": dominant_outcome,
        "selection_summary": explanation.get("selection_summary"),
        "outcome_bias_summary": explanation.get("outcome_bias_summary"),
        "representative_cases": representative_cases,
    }


def _probability_item_to_summary(item):
    return {
        "scenario_type": item.scenario_type,
        "success_probability": item.success_probability,
        "failure_probability": item.failure_probability,
        "neutral_probability": item.neutral_probability,
        "confidence": item.confidence,
        "explanation": item.probability_explanation,
        "highlights": _build_probability_highlights(
            item.probability_explanation,
            success_probability=item.success_probability,
            failure_probability=item.failure_probability,
            neutral_probability=item.neutral_probability,
        ),
    }


def _build_probability_summary(scenario_items):
    for item in scenario_items:
        if item.scenario_type == "base" and item.success_probability is not None:
            return _probability_item_to_summary(item)
    for item in scenario_items:
        if item.success_probability is not None:
            return _probability_item_to_summary(item)
    return None


def _build_probability_fallback_summary(base_decision, risk_gate_result, data_quality_result):
    if risk_gate_result.status in {"CRITICAL", "BLOCK"}:
        headline = "이 종목은 현재 악재 또는 위험 이벤트가 있어서, 단순 확률 계산으로 추가 매수를 판단하지 말고 리스크를 먼저 확인하세요."
    elif data_quality_result.label in {"낮음", "매우 낮음"}:
        headline = "확률 엔진을 생략했고, 데이터 품질이 낮아 점수·리스크·시장 조건 중심으로 해석했습니다."
    else:
        headline = (
            "확률 엔진을 사용할 수 없어 base scoring과 리스크·데이터 품질 중심으로 해석했습니다. "
            f"현재 기본 판단은 {base_decision['grade']} 등급입니다."
        )
    return {
        "scenario_type": "fallback",
        "success_probability": None,
        "failure_probability": None,
        "neutral_probability": None,
        "confidence": None,
        "explanation": None,
        "highlights": _build_probability_highlights(
            None,
            fallback_headline=headline,
        ),
        "fallback_reason": "Probability Engine unavailable",
    }


def _build_main_blockers(risk_gate_result, market_regime_result, data_quality_result, stock_quality_result, base_decision, probability):
    blockers = []
    blockers.extend(risk_gate_result.blockers)
    if market_regime_result.regime in {"risk_off", "capitulation"}:
        blockers.append(f"시장 국면이 {market_regime_result.regime}로 분류됩니다.")
    if data_quality_result.label in {"낮음", "매우 낮음"}:
        blockers.append(f"데이터 품질이 {data_quality_result.label} 수준입니다.")
    if stock_quality_result.quality_grade in {"Q4", "Q5", "UNKNOWN"}:
        if stock_quality_result.blockers:
            blockers.extend(stock_quality_result.blockers)
        else:
            blockers.append(f"종목 품질 등급이 {stock_quality_result.quality_grade}입니다.")
    if probability and probability.get("failure_probability") is not None and probability["failure_probability"] >= Decimal("0.4000"):
        blockers.append("실패 확률이 높아 보수적 접근이 필요합니다.")
    if base_decision["grade"] in {"C", "D"}:
        blockers.append(base_decision["reason_summary"])

    for reason in base_decision["reasons"]:
        if "지지선" in reason and "이탈" in reason:
            blockers.append(reason)
        if "동시 순매도" in reason:
            blockers.append(reason)

    return _unique_strings(blockers)


def _build_positive_factors(data_quality_result, market_regime_result, base_decision, probability):
    factors = []
    if data_quality_result.label in {"높음", "보통"}:
        factors.append(f"데이터 품질이 {data_quality_result.label} 수준입니다.")
    if market_regime_result.regime in {"risk_on", "pullback", "rebound"}:
        factors.append(f"시장 국면이 {market_regime_result.regime}로 분류됩니다.")
    if base_decision["grade"] in {"A", "B"}:
        factors.append(base_decision["reason_summary"])
    if (
        probability
        and probability.get("success_probability") is not None
        and probability.get("failure_probability") is not None
        and probability["success_probability"] > probability["failure_probability"]
    ):
        factors.append("대표 시나리오에서 성공 확률이 실패 확률보다 높습니다.")
    return _unique_strings(factors)


def _build_recheck_conditions(risk_gate_result, market_regime_result, data_quality_result, stock_quality_result):
    conditions = [
        "20일 이동평균 회복 후 2거래일 유지",
        "주요 지지선 재회복 여부 확인",
        "외국인 또는 기관 순매수 전환 확인",
        "거래량 증가를 동반한 반등 확인",
        "시장 국면 risk_off 해제 확인",
    ]
    if risk_gate_result.status in {"BLOCK", "CRITICAL", "CAUTION"}:
        conditions.append("critical 또는 high risk event 해소 확인")
    if data_quality_result.label in {"낮음", "매우 낮음"}:
        conditions.append("데이터 품질 보강 후 재평가")
    if stock_quality_result.quality_grade == "UNKNOWN":
        conditions.append("재무 품질 데이터 확인 후 재평가")
    if market_regime_result.regime in {"risk_off", "capitulation"}:
        conditions.append("시장 하락 국면 완화 여부 확인")

    deduplicated = _unique_strings(conditions)
    if len(deduplicated) < 3:
        deduplicated.extend(
            [
                "추가 리스크 이벤트 발생 여부 확인",
                "손절 기준 가격 재점검",
                "보유 비중 재조정 필요성 확인",
            ]
        )
    return deduplicated[:6]


def _build_summary(final_grade, main_blockers, positive_factors):
    if final_grade == "A":
        return "여러 조건이 비교적 우호적이지만 추가 매수 전 손절 기준과 예산 제한을 함께 확인해야 합니다."
    if final_grade == "B":
        return "일부 반등 신호는 있으나 시장 국면과 데이터 신뢰도를 함께 고려해 제한적 관찰이 필요합니다."
    if final_grade == "C":
        blocker = main_blockers[0] if main_blockers else "핵심 리스크 해소 전 재점검이 우선입니다."
        return f"현재 조건에서는 물타기 금지 구간으로 분류되며, {blocker}"
    positive = positive_factors[0] if positive_factors else "추가 매수 검토보다 리스크 관리가 앞섭니다."
    return f"손절 또는 비중 축소 기준 점검이 우선이며, {positive}"


def _data_quality_to_dict(result):
    return {
        "overall_score": result.overall_score,
        "label": result.label,
        "as_of_date": None,
        "price_data_days": result.price_data_days,
        "latest_price_age_days": result.latest_price_age_days,
        "investor_flow_days": result.investor_flow_days,
        "market_data_available": result.market_data_available,
        "risk_event_available": result.risk_event_available,
        "financial_data_available": False,
        "quality_grade": "UNKNOWN",
        "missing_fields": [],
        "anomaly_flags": [],
        "warning": "Data quality snapshot is not available.",
        "warnings": result.warnings,
        "details": result.details,
    }


def _merge_data_quality_snapshot(data_quality_dict, snapshot):
    if snapshot is None:
        return data_quality_dict
    merged = dict(data_quality_dict)
    merged.update(
        {
            "overall_score": snapshot.overall_score,
            "as_of_date": snapshot.as_of_date,
            "latest_price_age_days": snapshot.latest_price_age_days,
            "financial_data_available": snapshot.financial_data_available,
            "quality_grade": snapshot.quality_grade,
            "missing_fields": snapshot.missing_fields,
            "anomaly_flags": snapshot.anomaly_flags,
            "warning": "",
        }
    )
    return merged


def _get_latest_data_quality_snapshot(stock):
    return (
        DataQualitySnapshot.objects.filter(stock=stock)
        .order_by("-as_of_date", "-updated_at")
        .first()
    )


def _get_data_quality_snapshot_grade_cap(snapshot):
    if snapshot is None:
        return None
    if snapshot.quality_grade == DataQualitySnapshot.GRADE_D:
        return "C"
    if snapshot.quality_grade == DataQualitySnapshot.GRADE_C:
        return "B"
    return None


def _risk_gate_to_dict(result):
    return {
        "status": result.status,
        "grade_cap": result.grade_cap,
        "score_multiplier": result.score_multiplier,
        "critical_events": result.critical_events,
        "blockers": result.blockers,
        "warnings": result.warnings,
        "details": result.details,
    }


def _market_regime_to_dict(result):
    return {
        "regime": result.regime,
        "score_adjustment": result.score_adjustment,
        "score_multiplier": result.score_multiplier,
        "grade_cap": result.grade_cap,
        "reasons": result.reasons,
        "details": result.details,
    }


def _stock_quality_to_dict(result):
    return {
        "quality_grade": result.quality_grade,
        "score": result.score,
        "grade_cap": result.grade_cap,
        "blockers": result.blockers,
        "warnings": result.warnings,
        "details": result.details,
    }


def _capital_plan_to_dict(result):
    return {
        "max_allowed_budget": result.max_allowed_budget,
        "first_entry_budget": result.first_entry_budget,
        "second_entry_budget": result.second_entry_budget,
        "third_entry_budget": result.third_entry_budget,
        "first_entry_condition": result.first_entry_condition,
        "second_entry_condition": result.second_entry_condition,
        "third_entry_condition": result.third_entry_condition,
        "stop_loss_price": result.stop_loss_price,
        "estimated_max_loss": result.estimated_max_loss,
        "warnings": result.warnings,
        "details": result.details,
    }


def _scenario_item_to_dict(item):
    return {
        "scenario_type": item.scenario_type,
        "buy_price": item.buy_price,
        "buy_quantity": item.buy_quantity,
        "new_average_price": item.new_average_price,
        "target_price": item.target_price,
        "stop_loss_price": item.stop_loss_price,
        "success_probability": item.success_probability,
        "failure_probability": item.failure_probability,
        "neutral_probability": item.neutral_probability,
        "confidence": item.confidence,
        "efficiency_score": item.efficiency_score,
        "status": item.status,
        "reason_summary": item.reason_summary,
        "probability_explanation": item.probability_explanation,
        "warnings": item.warnings,
    }


def consult_holding(
    holding,
    *,
    buy_price=None,
    lookahead_days=20,
    target_profit_rate=None,
    stop_loss_type="support_or_atr",
    stop_loss_price=None,
    include_scenarios=True,
):
    warnings = []

    data_quality_result = evaluate_data_quality(holding)
    data_quality_snapshot = _get_latest_data_quality_snapshot(holding.stock)
    risk_gate_result = evaluate_risk_gate(holding)
    market_regime_result = evaluate_market_regime(holding.stock)
    stock_quality_result = evaluate_stock_quality(holding.stock)
    base_result = evaluate_averaging_timing(holding)

    base_decision = {
        "score": base_result.score,
        "grade": base_result.grade,
        "decision": base_result.decision,
        "reason_summary": base_result.reason_summary,
        "reasons": base_result.reasons,
        "score_breakdown": base_result.score_breakdown,
        "suggested_budget": base_result.suggested_budget,
        "stop_loss_price": base_result.stop_loss_price,
    }

    warnings.extend(data_quality_result.warnings)
    warnings.extend(risk_gate_result.warnings)
    warnings.extend(stock_quality_result.warnings)

    scenario_items = []
    probability_summary = None
    try:
        scenario_result = compare_scenarios(
            holding,
            buy_price=buy_price,
            lookahead_days=lookahead_days,
            target_profit_rate=target_profit_rate,
            stop_loss_type=stop_loss_type,
            stop_loss_price=stop_loss_price,
            risk_gate_result=risk_gate_result,
        )
        scenario_items = scenario_result["items"]
        warnings.extend(scenario_result["warnings"])
        probability_summary = _build_probability_summary(scenario_items)
    except Exception as exc:
        logger.warning(
            "Scenario comparison degraded during consulting",
            extra={
                "event": "consulting_scenario_degraded",
                "holding_id": holding.id,
                "stock_code": holding.stock.code,
                "error_type": exc.__class__.__name__,
            },
        )
        warnings.append(f"확률 기반 시나리오 비교 중 오류가 발생해 해당 계산을 생략했습니다: {exc}")
        fallback_scenarios = build_fallback_scenario_items(
            holding,
            buy_price=buy_price,
            lookahead_days=lookahead_days,
            target_profit_rate=target_profit_rate,
            stop_loss_type=stop_loss_type,
            stop_loss_price=stop_loss_price,
            risk_gate_result=risk_gate_result,
        )
        warnings.extend(fallback_scenarios["warnings"])
        scenario_items = fallback_scenarios["items"]
        probability_summary = _build_probability_fallback_summary(
            base_decision,
            risk_gate_result,
            data_quality_result,
        )

    capital_plan_result = build_capital_plan(
        holding,
        risk_gate_result=risk_gate_result,
        market_regime_result=market_regime_result,
        data_quality_result=data_quality_result,
        scenario_items=scenario_items,
    )
    warnings.extend(capital_plan_result.warnings)

    final_grade = base_result.grade
    for grade_cap in [
        risk_gate_result.grade_cap,
        market_regime_result.grade_cap,
        stock_quality_result.grade_cap,
        get_data_quality_grade_cap(data_quality_result),
        _get_data_quality_snapshot_grade_cap(data_quality_snapshot),
    ]:
        final_grade = cap_grade(final_grade, grade_cap)

    if (
        probability_summary
        and probability_summary.get("failure_probability") is not None
        and probability_summary["failure_probability"] >= Decimal("0.4000")
    ):
        final_grade = _downgrade_grade(final_grade)

    main_blockers = _build_main_blockers(
        risk_gate_result,
        market_regime_result,
        data_quality_result,
        stock_quality_result,
        base_decision,
        probability_summary,
    )
    positive_factors = _build_positive_factors(
        data_quality_result,
        market_regime_result,
        base_decision,
        probability_summary,
    )
    recheck_conditions = _build_recheck_conditions(
        risk_gate_result,
        market_regime_result,
        data_quality_result,
        stock_quality_result,
    )
    consulting_status = get_consulting_status(final_grade)
    summary = _build_summary(final_grade, main_blockers, positive_factors)

    logger.info(
        "Consulting result calculated",
        extra={
            "event": "consulting_result",
            "holding_id": holding.id,
            "stock_code": holding.stock.code,
            "status_code": 200,
        },
    )

    return ConsultingResult(
        final_grade=final_grade,
        consulting_status=consulting_status,
        summary=summary,
        risk_gate=_risk_gate_to_dict(risk_gate_result),
        data_quality=_merge_data_quality_snapshot(_data_quality_to_dict(data_quality_result), data_quality_snapshot),
        market_regime=_market_regime_to_dict(market_regime_result),
        stock_quality=_stock_quality_to_dict(stock_quality_result),
        base_decision=base_decision,
        probability=probability_summary,
        scenario_table=[_scenario_item_to_dict(item) for item in scenario_items] if include_scenarios else [],
        capital_plan=_capital_plan_to_dict(capital_plan_result),
        main_blockers=main_blockers,
        positive_factors=positive_factors,
        recheck_conditions=recheck_conditions,
        warnings=_unique_strings(warnings),
        disclaimer=CONSULTING_DISCLAIMER_TEXT,
    )


def build_consult_response(holding, result: ConsultingResult):
    latest_price = get_latest_price(holding.stock)
    current_price = getattr(latest_price, "close_price", None)
    current_price_date = getattr(latest_price, "date", None)
    loss_rate = None
    if current_price is not None and holding.average_price:
        loss_rate = (((current_price - holding.average_price) / holding.average_price) * Decimal("100")).quantize(
            Decimal("0.01")
        )

    payload = asdict(result)
    payload["stock"] = {
        "code": holding.stock.code,
        "name": holding.stock.name,
        "market": holding.stock.market,
        "sector": holding.stock.sector,
    }
    payload["holding"] = {
        "average_price": holding.average_price,
        "quantity": holding.quantity,
        "current_price": current_price,
        "current_price_date": current_price_date,
        "loss_rate": loss_rate,
        "max_additional_budget": holding.max_additional_budget,
        "risk_level": holding.risk_level,
        "is_active": holding.is_active,
        "memo": holding.memo,
    }
    payload["decision_summary"] = result.summary
    payload["score_breakdown"] = result.base_decision.get("score_breakdown", {})
    return _stringify_decimal_tree(payload)
