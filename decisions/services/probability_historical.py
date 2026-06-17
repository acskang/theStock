from __future__ import annotations

from decimal import Decimal

from decisions.models import RiskEvent
from decisions.services.probability_components import (
    DEFAULT_HISTORICAL_WEIGHT,
    PRICE_QUANT,
    clamp,
    normalize_probabilities,
    quantize_probability,
)
from decisions.services.probability_dataclasses import (
    HistoricalCaseOutcome,
    ProbabilityComponent,
    ProbabilityFeatureSnapshot,
)
from decisions.services.support_service import find_support_zone
from indicators.services.indicator_service import calculate_moving_average, calculate_rsi, calculate_volume_ma
from marketdata.services.price_service import extract_close_prices, extract_volumes, get_recent_prices

SIMILARITY_DISTANCE_THRESHOLDS = (
    Decimal("0.30"),
    Decimal("0.40"),
    Decimal("0.50"),
    Decimal("0.65"),
)
FEATURE_WEIGHTS = {
    "rsi14": Decimal("0.16"),
    "price_to_ma20_pct": Decimal("0.16"),
    "price_to_ma60_pct": Decimal("0.09"),
    "support_distance_pct": Decimal("0.15"),
    "volume_ratio": Decimal("0.10"),
    "market_trend_signal": Decimal("0.10"),
    "foreign_flow_signal": Decimal("0.05"),
    "institution_flow_signal": Decimal("0.05"),
    "risk_level_signal": Decimal("0.05"),
    "loss_rate_pct": Decimal("0.09"),
}
TOTAL_FEATURE_WEIGHT = sum(FEATURE_WEIGHTS.values(), Decimal("0"))
MAX_SELECTED_CASES = 100
FEATURE_LABELS = {
    "rsi14": "RSI14",
    "price_to_ma20_pct": "MA20 괴리",
    "price_to_ma60_pct": "MA60 괴리",
    "support_distance_pct": "지지선 거리",
    "volume_ratio": "거래량 비율",
    "market_trend_signal": "시장 추세",
    "foreign_flow_signal": "외국인 수급",
    "institution_flow_signal": "기관 수급",
    "risk_level_signal": "리스크 상태",
    "loss_rate_pct": "평단 대비 손익률",
}
HISTORICAL_RISK_WINDOWS = {
    RiskEvent.RISK_LOW: 60,
    RiskEvent.RISK_MEDIUM: 90,
    RiskEvent.RISK_HIGH: 180,
    RiskEvent.RISK_CRITICAL: 365,
}


def _to_decimal(value):
    return Decimal(str(value))


def _get_row_value(row, field_name):
    if isinstance(row, dict):
        return row[field_name]
    return getattr(row, field_name)


def _quantize_price(value):
    return _to_decimal(value).quantize(PRICE_QUANT)


def _quantize_optional_ratio(numerator: Decimal | None, denominator: Decimal | None):
    if numerator is None or denominator in (None, Decimal("0")):
        return None
    return quantize_probability(numerator / denominator)


def _get_latest_flow_row(flow_rows):
    if not flow_rows:
        return None
    return sorted(flow_rows, key=lambda row: _get_row_value(row, "date"))[-1]


def _calculate_flow_signal(value):
    if value is None:
        return 0
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def _calculate_market_trend_signal(market_rows):
    if not market_rows:
        return 0
    close_values = [
        _to_decimal(_get_row_value(row, "close_value"))
        for row in sorted(market_rows, key=lambda row: _get_row_value(row, "date"))
    ]
    ma20 = calculate_moving_average(close_values, 20)
    if ma20 is None:
        return 0
    latest_close = close_values[-1]
    if latest_close > ma20 * Decimal("1.01"):
        return 1
    if latest_close < ma20 * Decimal("0.99"):
        return -1
    return 0


def _calculate_risk_level_signal(active_risk_events):
    if not active_risk_events:
        return 0
    priority = {
        RiskEvent.RISK_LOW: -1,
        RiskEvent.RISK_MEDIUM: -2,
        RiskEvent.RISK_HIGH: -3,
        RiskEvent.RISK_CRITICAL: -5,
    }
    values = [priority.get(event.risk_level, 0) for event in active_risk_events]
    return min(values) if values else 0


def _normalized_numeric_distance(current_value, past_value, scale: Decimal):
    if current_value is None or past_value is None:
        return None
    if scale <= 0:
        return None
    distance = abs(_to_decimal(current_value) - _to_decimal(past_value)) / scale
    return clamp(distance, Decimal("0"), Decimal("1"))


def _normalized_signal_distance(current_value, past_value):
    if current_value is None or past_value is None:
        return None
    distance = abs(int(current_value) - int(past_value)) / Decimal("2")
    return clamp(distance, Decimal("0"), Decimal("1"))


def _normalized_risk_distance(current_value, past_value):
    if current_value is None or past_value is None:
        return None
    distance = abs(int(current_value) - int(past_value)) / Decimal("5")
    return clamp(distance, Decimal("0"), Decimal("1"))


def serialize_probability_feature_snapshot(snapshot: ProbabilityFeatureSnapshot | None):
    if snapshot is None:
        return None
    return {
        "date": snapshot.date.isoformat(),
        "close_price": snapshot.close_price,
        "loss_rate_pct": snapshot.loss_rate_pct,
        "rsi14": snapshot.rsi14,
        "price_to_ma20_pct": snapshot.price_to_ma20_pct,
        "price_to_ma60_pct": snapshot.price_to_ma60_pct,
        "support_distance_pct": snapshot.support_distance_pct,
        "volume_ratio": snapshot.volume_ratio,
        "foreign_flow_signal": snapshot.foreign_flow_signal,
        "institution_flow_signal": snapshot.institution_flow_signal,
        "market_trend_signal": snapshot.market_trend_signal,
        "risk_level_signal": snapshot.risk_level_signal,
    }


def calculate_snapshot_distance(
    current_snapshot: ProbabilityFeatureSnapshot | None,
    past_snapshot: ProbabilityFeatureSnapshot | None,
):
    if current_snapshot is None or past_snapshot is None:
        return None

    feature_distances = {
        "rsi14": _normalized_numeric_distance(current_snapshot.rsi14, past_snapshot.rsi14, Decimal("100")),
        "price_to_ma20_pct": _normalized_numeric_distance(
            current_snapshot.price_to_ma20_pct,
            past_snapshot.price_to_ma20_pct,
            Decimal("0.20"),
        ),
        "price_to_ma60_pct": _normalized_numeric_distance(
            current_snapshot.price_to_ma60_pct,
            past_snapshot.price_to_ma60_pct,
            Decimal("0.25"),
        ),
        "support_distance_pct": _normalized_numeric_distance(
            current_snapshot.support_distance_pct,
            past_snapshot.support_distance_pct,
            Decimal("0.10"),
        ),
        "loss_rate_pct": _normalized_numeric_distance(
            current_snapshot.loss_rate_pct,
            past_snapshot.loss_rate_pct,
            Decimal("0.30"),
        ),
        "volume_ratio": _normalized_numeric_distance(
            current_snapshot.volume_ratio,
            past_snapshot.volume_ratio,
            Decimal("3.0"),
        ),
        "market_trend_signal": _normalized_signal_distance(
            current_snapshot.market_trend_signal,
            past_snapshot.market_trend_signal,
        ),
        "foreign_flow_signal": _normalized_signal_distance(
            current_snapshot.foreign_flow_signal,
            past_snapshot.foreign_flow_signal,
        ),
        "institution_flow_signal": _normalized_signal_distance(
            current_snapshot.institution_flow_signal,
            past_snapshot.institution_flow_signal,
        ),
        "risk_level_signal": _normalized_risk_distance(
            current_snapshot.risk_level_signal,
            past_snapshot.risk_level_signal,
        ),
    }

    used_weight = Decimal("0")
    weighted_distance = Decimal("0")
    for feature_name, feature_weight in FEATURE_WEIGHTS.items():
        feature_distance = feature_distances[feature_name]
        if feature_distance is None:
            continue
        used_weight += feature_weight
        weighted_distance += feature_distance * feature_weight

    if used_weight == 0:
        return None

    distance = clamp(weighted_distance / used_weight, Decimal("0"), Decimal("1"))
    coverage = clamp(used_weight / TOTAL_FEATURE_WEIGHT, Decimal("0"), Decimal("1"))
    return {
        "distance": quantize_probability(distance),
        "coverage": quantize_probability(coverage),
        "used_weight": quantize_probability(used_weight),
        "feature_distances": {
            key: (quantize_probability(value) if value is not None else None)
            for key, value in feature_distances.items()
        },
    }


def _summarize_feature_matches(feature_distances, *, limit=3, reverse=False):
    ranked = []
    for feature_name, distance in feature_distances.items():
        if distance is None:
            continue
        ranked.append(
            {
                "feature": feature_name,
                "label": FEATURE_LABELS.get(feature_name, feature_name),
                "distance": distance,
            }
        )

    ranked.sort(key=lambda item: (item["distance"], item["label"]), reverse=reverse)
    return ranked[:limit]


def _describe_feature_distance(distance):
    if distance is None:
        return "정보 부족"
    if distance <= Decimal("0.10"):
        return "매우 유사"
    if distance <= Decimal("0.25"):
        return "유사"
    if distance <= Decimal("0.45"):
        return "보통"
    return "차이 큼"


def _format_feature_summary(features):
    if not features:
        return "가용 feature가 부족합니다."
    return ", ".join(
        f"{item['label']} {_describe_feature_distance(item['distance'])}({item['distance']})"
        for item in features
    )


def _build_outcome_bias_summary(*, success_count, failure_count, neutral_count, sample_count):
    if sample_count == 0:
        return "선택된 historical 사례가 없어 방향성 판단이 제한적입니다."

    dominant_label = "중립"
    dominant_count = neutral_count
    if success_count >= failure_count and success_count >= neutral_count:
        dominant_label = "성공"
        dominant_count = success_count
    elif failure_count >= success_count and failure_count >= neutral_count:
        dominant_label = "실패"
        dominant_count = failure_count

    return (
        f"선택된 {sample_count}건 중 성공 {success_count}건, 실패 {failure_count}건, 중립 {neutral_count}건으로 "
        f"{dominant_label} 사례가 {dominant_count}건으로 가장 많습니다."
    )


def _build_selection_summary(*, sample_count, candidate_count, selected_threshold, closest_features, weakest_features):
    if sample_count == 0:
        return "유사 사례를 찾지 못해 historical component를 중립으로 유지했습니다."

    threshold_text = selected_threshold if selected_threshold is not None else "nearest fallback"
    summary = f"후보 {candidate_count}건 중 유사 사례 {sample_count}건을 threshold {threshold_text} 기준으로 선택했습니다."
    if closest_features:
        summary += " 가장 잘 맞는 조건은 " + _format_feature_summary(closest_features) + "입니다."
    if weakest_features:
        summary += " 상대적으로 덜 맞는 조건은 " + _format_feature_summary(weakest_features) + "입니다."
    return summary


def _build_case_reason_summary(case):
    closest_features = _summarize_feature_matches(case["feature_distances"])
    weakest_features = _summarize_feature_matches(case["feature_distances"], reverse=True)
    outcome = case["outcome"]
    summary = (
        f"{outcome.base_date.isoformat()} 사례는 {outcome.outcome} 결과였고 "
        f"distance {case['distance']}, coverage {case['coverage']}입니다."
    )
    if closest_features:
        summary += " 가까운 조건은 " + _format_feature_summary(closest_features) + "입니다."
    if weakest_features:
        summary += " 차이가 큰 조건은 " + _format_feature_summary(weakest_features) + "입니다."
    return summary


def _build_outcome_case_groups(selected_cases):
    grouped = {"success": [], "failure": [], "neutral": []}
    for item in selected_cases:
        outcome_key = item["outcome"].outcome
        if outcome_key not in grouped:
            continue
        grouped[outcome_key].append(
            {
                "base_date": item["outcome"].base_date.isoformat(),
                "distance": item["distance"],
                "coverage": item["coverage"],
                "reason_summary": _build_case_reason_summary(item),
            }
        )

    return {
        outcome_key: {
            "count": len(cases),
            "examples": cases[:2],
        }
        for outcome_key, cases in grouped.items()
    }


def build_probability_feature_snapshot(
    *,
    price_rows,
    reference_price=None,
    flow_rows=None,
    market_rows=None,
    active_risk_events=None,
) -> ProbabilityFeatureSnapshot | None:
    rows = sorted(price_rows, key=lambda row: _get_row_value(row, "date"))
    if not rows:
        return None

    latest_row = rows[-1]
    close_price = _to_decimal(_get_row_value(latest_row, "close_price"))
    reference_price = _to_decimal(reference_price) if reference_price not in (None, "", 0, Decimal("0")) else None
    close_prices = extract_close_prices(rows)
    volumes = extract_volumes(rows)

    rsi14 = calculate_rsi(close_prices, 14)
    ma20 = calculate_moving_average(close_prices, 20)
    ma60 = calculate_moving_average(close_prices, 60)
    support_zone = find_support_zone(rows)
    support_price = support_zone.get("support_price")
    volume_ma20 = calculate_volume_ma(volumes, 20)
    latest_volume = _get_row_value(latest_row, "volume")
    latest_flow_row = _get_latest_flow_row(flow_rows)

    return ProbabilityFeatureSnapshot(
        date=_get_row_value(latest_row, "date"),
        close_price=_quantize_price(close_price),
        loss_rate_pct=_quantize_optional_ratio(close_price - reference_price, reference_price)
        if reference_price is not None
        else None,
        rsi14=rsi14,
        price_to_ma20_pct=_quantize_optional_ratio(close_price - ma20, ma20) if ma20 is not None else None,
        price_to_ma60_pct=_quantize_optional_ratio(close_price - ma60, ma60) if ma60 is not None else None,
        support_distance_pct=_quantize_optional_ratio(close_price - support_price, close_price)
        if support_price is not None
        else None,
        volume_ratio=_quantize_optional_ratio(Decimal(str(latest_volume)), Decimal(str(volume_ma20)))
        if volume_ma20
        else None,
        foreign_flow_signal=_calculate_flow_signal(
            _get_row_value(latest_flow_row, "foreign_net_buy") if latest_flow_row is not None else None
        ),
        institution_flow_signal=_calculate_flow_signal(
            _get_row_value(latest_flow_row, "institution_net_buy") if latest_flow_row is not None else None
        ),
        market_trend_signal=_calculate_market_trend_signal(market_rows),
        risk_level_signal=_calculate_risk_level_signal(active_risk_events),
    )


def _subset_rows_until(rows, target_date, field_name="date"):
    if not rows:
        return []
    return [row for row in rows if _get_row_value(row, field_name) <= target_date]


def _get_historical_active_risk_events(risk_events, base_date):
    if not risk_events:
        return []

    active_events = []
    for event in risk_events:
        event_date = _get_row_value(event, "event_date")
        if event_date is None or event_date > base_date:
            continue
        active_window = HISTORICAL_RISK_WINDOWS.get(_get_row_value(event, "risk_level"), 60)
        if (base_date - event_date).days <= active_window:
            active_events.append(event)
    return active_events


def _build_candidate_case(
    *,
    current_snapshot,
    base_row,
    history_rows,
    future_rows,
    target_return,
    stop_loss_return,
    same_day_hit_policy,
    flow_rows=None,
    market_rows=None,
    risk_events=None,
):
    base_date = _get_row_value(base_row, "date")
    candidate_snapshot = build_probability_feature_snapshot(
        price_rows=history_rows,
        reference_price=_to_decimal(_get_row_value(base_row, "close_price")) * (Decimal("1") + _to_decimal(target_return)),
        flow_rows=_subset_rows_until(flow_rows or [], base_date),
        market_rows=_subset_rows_until(market_rows or [], base_date),
        active_risk_events=_get_historical_active_risk_events(risk_events or [], base_date),
    )
    distance_result = calculate_snapshot_distance(current_snapshot, candidate_snapshot)
    if distance_result is None:
        return None

    base_close = _to_decimal(_get_row_value(base_row, "close_price"))
    target_price = base_close * (Decimal("1") + _to_decimal(target_return))
    stop_price = base_close * (Decimal("1") - _to_decimal(stop_loss_return))
    outcome = determine_historical_outcome(
        future_price_rows=future_rows,
        target_price=target_price,
        stop_loss_price=stop_price,
        same_day_hit_policy=same_day_hit_policy,
        base_date=base_date,
        base_close=base_close,
    )
    return {
        "distance": distance_result["distance"],
        "coverage": distance_result["coverage"],
        "feature_distances": distance_result["feature_distances"],
        "snapshot": candidate_snapshot,
        "outcome": outcome,
    }


def select_similar_historical_cases(candidates, *, min_cases=30):
    ordered = sorted(candidates, key=lambda item: (item["distance"], item["outcome"].base_date))
    if not ordered:
        return [], None, True

    for threshold in SIMILARITY_DISTANCE_THRESHOLDS:
        selected = [item for item in ordered if item["distance"] <= threshold]
        if len(selected) >= min_cases:
            return selected[:MAX_SELECTED_CASES], threshold, False

    relaxed_selected = [item for item in ordered if item["distance"] <= SIMILARITY_DISTANCE_THRESHOLDS[-1]]
    if relaxed_selected:
        return relaxed_selected[:MAX_SELECTED_CASES], SIMILARITY_DISTANCE_THRESHOLDS[-1], len(relaxed_selected) < min_cases

    return ordered[: min(MAX_SELECTED_CASES, min_cases, len(ordered))], None, True


def determine_historical_outcome(
    *,
    future_price_rows,
    target_price: Decimal,
    stop_loss_price: Decimal,
    same_day_hit_policy: str = "conservative",
    base_date=None,
    base_close=None,
) -> HistoricalCaseOutcome:
    rows = list(future_price_rows)
    if base_date is None:
        base_date = _get_row_value(rows[0], "date") if rows else None
    if base_close is None:
        base_close = _to_decimal(_get_row_value(rows[0], "close_price")) if rows else Decimal("0")
    else:
        base_close = _to_decimal(base_close)

    max_favorable_return = Decimal("0")
    max_adverse_return = Decimal("0")
    outcome = "neutral"
    days_to_outcome = None

    for day_index, row in enumerate(rows, start=1):
        high_price = _to_decimal(_get_row_value(row, "high_price"))
        low_price = _to_decimal(_get_row_value(row, "low_price"))

        if base_close > 0:
            favorable_return = (high_price - base_close) / base_close
            adverse_return = (low_price - base_close) / base_close
            max_favorable_return = max(max_favorable_return, favorable_return)
            max_adverse_return = min(max_adverse_return, adverse_return)

        hit_target = high_price >= target_price
        hit_stop = low_price <= stop_loss_price

        if hit_target and hit_stop:
            if same_day_hit_policy == "optimistic":
                outcome = "success"
            elif same_day_hit_policy == "neutral":
                outcome = "neutral"
            else:
                outcome = "failure"
            days_to_outcome = day_index
            break

        if hit_target:
            outcome = "success"
            days_to_outcome = day_index
            break

        if hit_stop:
            outcome = "failure"
            days_to_outcome = day_index
            break

    return HistoricalCaseOutcome(
        base_date=base_date,
        base_close=_quantize_price(base_close),
        target_price=_quantize_price(target_price),
        stop_loss_price=_quantize_price(stop_loss_price),
        outcome=outcome,
        days_to_outcome=days_to_outcome,
        max_favorable_return=quantize_probability(max_favorable_return),
        max_adverse_return=quantize_probability(max_adverse_return),
    )


def calculate_historical_probabilities(
    *,
    stock,
    current_snapshot,
    target_return: Decimal,
    stop_loss_return: Decimal,
    lookahead_days: int,
    max_lookback_days: int = 720,
    min_cases: int = 30,
    same_day_hit_policy: str = "conservative",
    price_rows=None,
    flow_rows=None,
    market_rows=None,
    active_risk_events=None,
    risk_events=None,
) -> ProbabilityComponent:
    rows = list(price_rows) if price_rows is not None else get_recent_prices(
        stock,
        limit=max_lookback_days + lookahead_days,
        ascending=True,
    )
    warnings = []
    if current_snapshot is None and rows:
        current_snapshot = build_probability_feature_snapshot(
            price_rows=rows,
            flow_rows=flow_rows,
            market_rows=market_rows,
            active_risk_events=active_risk_events,
        )
    if len(rows) <= lookahead_days:
        warnings.append("과거 사례가 부족해 historical component를 중립으로 처리했습니다.")
        return ProbabilityComponent(
            success=Decimal("0.0000"),
            failure=Decimal("0.0000"),
            neutral=Decimal("1.0000"),
            weight=Decimal("0.0000"),
            confidence=Decimal("0.0000"),
            sample_count=0,
            details={
                "success": Decimal("0.0000"),
                "failure": Decimal("0.0000"),
                "neutral": Decimal("1.0000"),
                "sample_count": 0,
                "current_snapshot": serialize_probability_feature_snapshot(current_snapshot),
            },
            warnings=warnings,
        )

    success_count = 0
    failure_count = 0
    neutral_count = 0
    candidate_cases = []

    upper_bound = len(rows) - lookahead_days
    for index in range(0, upper_bound):
        base_row = rows[index]
        future_rows = rows[index + 1:index + 1 + lookahead_days]
        if len(future_rows) < lookahead_days:
            continue

        candidate_case = _build_candidate_case(
            current_snapshot=current_snapshot,
            base_row=base_row,
            history_rows=rows[: index + 1],
            future_rows=future_rows,
            target_return=target_return,
            stop_loss_return=stop_loss_return,
            same_day_hit_policy=same_day_hit_policy,
            flow_rows=flow_rows,
            market_rows=market_rows,
            risk_events=risk_events,
        )
        if candidate_case is None:
            continue
        candidate_cases.append(candidate_case)

    selected_cases, selected_threshold, threshold_relaxed = select_similar_historical_cases(
        candidate_cases,
        min_cases=min_cases,
    )

    case_outcomes = [item["outcome"] for item in selected_cases]
    for outcome in case_outcomes:
        if outcome.outcome == "success":
            success_count += 1
        elif outcome.outcome == "failure":
            failure_count += 1
        else:
            neutral_count += 1

    sample_count = len(selected_cases)
    if sample_count < min_cases:
        warnings.append("유사 과거 사례 수가 부족해 historical weight와 confidence가 낮아집니다.")
    if threshold_relaxed:
        warnings.append("유사도 threshold를 완화했지만 충분한 사례를 확보하지 못했습니다.")
    if selected_threshold is None and sample_count > 0:
        warnings.append("distance threshold를 만족하는 사례가 없어 nearest fallback을 사용했습니다.")

    normalized = normalize_probabilities(
        Decimal(success_count),
        Decimal(failure_count),
        Decimal(neutral_count),
    )
    sample_quality = clamp(_to_decimal(sample_count) / Decimal(str(min_cases)), Decimal("0"), Decimal("1"))
    average_distance = (
        sum(item["distance"] for item in selected_cases) / Decimal(sample_count)
        if sample_count
        else Decimal("1")
    )
    similarity_quality = clamp(Decimal("1") - average_distance, Decimal("0"), Decimal("1"))
    average_coverage = (
        sum(item["coverage"] for item in selected_cases) / Decimal(sample_count)
        if sample_count
        else Decimal("0")
    )
    outcome_stability = (
        Decimal(max(success_count, failure_count, neutral_count)) / Decimal(sample_count)
        if sample_count
        else Decimal("0")
    )
    quality = clamp(
        (sample_quality * Decimal("0.40"))
        + (similarity_quality * Decimal("0.25"))
        + (average_coverage * Decimal("0.15"))
        + (outcome_stability * Decimal("0.20")),
        Decimal("0"),
        Decimal("1"),
    )
    weight = quantize_probability(DEFAULT_HISTORICAL_WEIGHT * quality)
    confidence = quantize_probability(quality)
    preview = [
        {
            "base_date": item["outcome"].base_date.isoformat(),
            "outcome": item["outcome"].outcome,
            "days_to_outcome": item["outcome"].days_to_outcome,
            "distance": item["distance"],
            "coverage": item["coverage"],
        }
        for item in selected_cases[:5]
    ]
    top_similar_cases = [
        {
            "base_date": item["outcome"].base_date.isoformat(),
            "base_close": item["outcome"].base_close,
            "outcome": item["outcome"].outcome,
            "days_to_outcome": item["outcome"].days_to_outcome,
            "distance": item["distance"],
            "coverage": item["coverage"],
            "max_favorable_return": item["outcome"].max_favorable_return,
            "max_adverse_return": item["outcome"].max_adverse_return,
            "feature_distances": item["feature_distances"],
            "match_summary": {
                "closest_features": _summarize_feature_matches(item["feature_distances"]),
                "weakest_features": _summarize_feature_matches(item["feature_distances"], reverse=True),
            },
            "reason_summary": _build_case_reason_summary(item),
            "snapshot": serialize_probability_feature_snapshot(item["snapshot"]),
        }
        for item in selected_cases[:5]
    ]
    aggregate_feature_distances = {}
    for feature_name in FEATURE_WEIGHTS:
        values = [
            item["feature_distances"][feature_name]
            for item in selected_cases
            if item["feature_distances"].get(feature_name) is not None
        ]
        aggregate_feature_distances[feature_name] = (
            quantize_probability(sum(values) / Decimal(len(values)))
            if values
            else None
        )
    closest_features = _summarize_feature_matches(aggregate_feature_distances)
    weakest_features = _summarize_feature_matches(aggregate_feature_distances, reverse=True)
    outcome_case_groups = _build_outcome_case_groups(selected_cases)
    return ProbabilityComponent(
        success=normalized["success"],
        failure=normalized["failure"],
        neutral=normalized["neutral"],
        weight=weight,
        confidence=confidence,
        sample_count=sample_count,
        details={
            "success": normalized["success"],
            "failure": normalized["failure"],
            "neutral": normalized["neutral"],
            "sample_count": sample_count,
            "success_count": success_count,
            "failure_count": failure_count,
            "neutral_count": neutral_count,
            "candidate_count": len(candidate_cases),
            "selected_case_count": sample_count,
            "selected_threshold": str(selected_threshold) if selected_threshold is not None else "nearest_fallback",
            "avg_distance": quantize_probability(average_distance) if sample_count else Decimal("1.0000"),
            "avg_feature_coverage": quantize_probability(average_coverage) if sample_count else Decimal("0.0000"),
            "outcome_stability": quantize_probability(outcome_stability) if sample_count else Decimal("0.0000"),
            "current_snapshot": serialize_probability_feature_snapshot(current_snapshot),
            "closest_features": closest_features,
            "weakest_features": weakest_features,
            "selection_summary": _build_selection_summary(
                sample_count=sample_count,
                candidate_count=len(candidate_cases),
                selected_threshold=str(selected_threshold) if selected_threshold is not None else None,
                closest_features=closest_features,
                weakest_features=weakest_features,
            ),
            "outcome_bias_summary": _build_outcome_bias_summary(
                success_count=success_count,
                failure_count=failure_count,
                neutral_count=neutral_count,
                sample_count=sample_count,
            ),
            "outcome_case_groups": outcome_case_groups,
            "case_preview": preview,
            "top_similar_cases": top_similar_cases,
        },
        warnings=warnings,
    )
