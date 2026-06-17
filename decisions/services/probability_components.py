import math
from decimal import Decimal, ROUND_HALF_UP
from statistics import pstdev

from decisions.models import RiskEvent
from decisions.services.probability_dataclasses import ProbabilityComponent


PROBABILITY_QUANT = Decimal("0.0001")
PRICE_QUANT = Decimal("0.01")
DEFAULT_HISTORICAL_WEIGHT = Decimal("0.45")
DEFAULT_SCORE_WEIGHT = Decimal("0.35")
DEFAULT_VOLATILITY_WEIGHT = Decimal("0.20")


def _to_decimal(value):
    return Decimal(str(value))


def _get_row_value(row, field_name):
    if isinstance(row, dict):
        return row[field_name]
    return getattr(row, field_name)


def clamp(value, min_value, max_value):
    return max(min_value, min(max_value, value))


def quantize_probability(value: Decimal) -> Decimal:
    return _to_decimal(value).quantize(PROBABILITY_QUANT, rounding=ROUND_HALF_UP)


def normalize_probabilities(success, failure, neutral):
    success = max(Decimal("0"), _to_decimal(success))
    failure = max(Decimal("0"), _to_decimal(failure))
    neutral = max(Decimal("0"), _to_decimal(neutral))

    total = success + failure + neutral
    if total == 0:
        return {
            "success": Decimal("0.0000"),
            "failure": Decimal("0.0000"),
            "neutral": Decimal("1.0000"),
        }

    success = success / total
    failure = failure / total
    neutral = neutral / total

    success = quantize_probability(success)
    failure = quantize_probability(failure)
    neutral = quantize_probability(neutral)

    correction = Decimal("1.0000") - (success + failure + neutral)
    neutral = quantize_probability(neutral + correction)
    if neutral < 0:
        deficit = abs(neutral)
        neutral = Decimal("0.0000")
        if failure >= deficit:
            failure = quantize_probability(failure - deficit)
        else:
            success = quantize_probability(success - (deficit - failure))
            failure = Decimal("0.0000")

    return {
        "success": success,
        "failure": failure,
        "neutral": neutral,
    }


def sigmoid(value):
    return _to_decimal(1 / (1 + math.exp(-float(value))))


def normal_cdf(value):
    return _to_decimal(0.5 * (1 + math.erf(float(value) / math.sqrt(2))))


def calculate_score_component(*, score: int, grade: str, active_risk_events=None) -> ProbabilityComponent:
    success = sigmoid((Decimal(score) - Decimal("55")) / Decimal("10"))
    failure = sigmoid((Decimal("45") - Decimal(score)) / Decimal("10"))
    normalized = normalize_probabilities(success, failure, Decimal("1") - success - failure)

    warnings = []
    highest_risk_level = None
    adjusted_success = normalized["success"]
    adjusted_failure = normalized["failure"]

    if active_risk_events:
        priority = {
            RiskEvent.RISK_LOW: 1,
            RiskEvent.RISK_MEDIUM: 2,
            RiskEvent.RISK_HIGH: 3,
        }
        highest_risk_level = max(
            (
                event.risk_level
                for event in active_risk_events
                if event.risk_level in priority
            ),
            key=lambda level: priority[level],
            default=None,
        )
        if highest_risk_level == RiskEvent.RISK_HIGH:
            adjusted_success *= Decimal("0.75")
            adjusted_failure += Decimal("0.20")
        elif highest_risk_level == RiskEvent.RISK_MEDIUM:
            adjusted_success *= Decimal("0.90")
            adjusted_failure += Decimal("0.10")
        elif highest_risk_level == RiskEvent.RISK_LOW:
            adjusted_success *= Decimal("0.95")
            adjusted_failure += Decimal("0.05")

        if highest_risk_level is not None:
            warnings.append("활성 위험 이벤트를 반영해 score component를 보수적으로 조정했습니다.")

    normalized = normalize_probabilities(
        adjusted_success,
        adjusted_failure,
        Decimal("1") - adjusted_success - adjusted_failure,
    )
    return ProbabilityComponent(
        success=normalized["success"],
        failure=normalized["failure"],
        neutral=normalized["neutral"],
        weight=DEFAULT_SCORE_WEIGHT,
        confidence=Decimal("0.7000"),
        sample_count=0,
        details={
            "success": normalized["success"],
            "failure": normalized["failure"],
            "neutral": normalized["neutral"],
            "score": score,
            "grade": grade,
            "highest_risk_level": highest_risk_level,
        },
        warnings=warnings,
    )


def _calculate_daily_volatility(price_rows, atr14, current_price):
    warnings = []
    if len(price_rows) >= 2:
        close_prices = [_to_decimal(_get_row_value(row, "close_price")) for row in price_rows]
        log_returns = []
        for index in range(1, len(close_prices)):
            previous_close = close_prices[index - 1]
            current_close = close_prices[index]
            if previous_close > 0 and current_close > 0:
                log_returns.append(math.log(float(current_close / previous_close)))
        if log_returns:
            return clamp(_to_decimal(pstdev(log_returns)), Decimal("0.005"), Decimal("0.15")), warnings

    if atr14 is not None and current_price > 0:
        warnings.append("종가 로그수익률이 부족해 ATR 기반 변동성으로 대체했습니다.")
        return clamp(_to_decimal(atr14) / _to_decimal(current_price), Decimal("0.005"), Decimal("0.15")), warnings

    warnings.append("가격 데이터와 ATR이 부족해 기본 변동성 0.02를 사용했습니다.")
    return Decimal("0.0200"), warnings


def calculate_volatility_component(
    *,
    current_price: Decimal,
    target_price: Decimal,
    stop_loss_price: Decimal,
    price_rows,
    atr14: Decimal | None,
    lookahead_days: int,
    trend_score: int = 0,
) -> ProbabilityComponent:
    current_price = _to_decimal(current_price)
    target_price = _to_decimal(target_price)
    stop_loss_price = _to_decimal(stop_loss_price)

    warnings = []
    target_return = (target_price - current_price) / current_price
    stop_loss_return = (current_price - stop_loss_price) / current_price

    if target_return <= 0:
        return ProbabilityComponent(
            success=Decimal("0.9500"),
            failure=Decimal("0.0100"),
            neutral=Decimal("0.0400"),
            weight=DEFAULT_VOLATILITY_WEIGHT,
            confidence=Decimal("0.6500"),
            details={
                "success": Decimal("0.9500"),
                "failure": Decimal("0.0100"),
                "neutral": Decimal("0.0400"),
                "target_return": quantize_probability(target_return),
                "stop_loss_return": quantize_probability(stop_loss_return),
            },
            warnings=["현재가가 이미 목표가 이상이어서 success를 높게 처리했습니다."],
        )

    if stop_loss_return <= 0:
        return ProbabilityComponent(
            success=Decimal("0.0100"),
            failure=Decimal("0.9500"),
            neutral=Decimal("0.0400"),
            weight=DEFAULT_VOLATILITY_WEIGHT,
            confidence=Decimal("0.6500"),
            details={
                "success": Decimal("0.0100"),
                "failure": Decimal("0.9500"),
                "neutral": Decimal("0.0400"),
                "target_return": quantize_probability(target_return),
                "stop_loss_return": quantize_probability(stop_loss_return),
            },
            warnings=["손절 기준이 현재가보다 높거나 같아 failure를 높게 처리했습니다."],
        )

    daily_volatility, volatility_warnings = _calculate_daily_volatility(price_rows, atr14, current_price)
    warnings.extend(volatility_warnings)
    horizon_volatility = daily_volatility * _to_decimal(math.sqrt(lookahead_days))

    p_touch_up = clamp(
        Decimal("2") * (Decimal("1") - normal_cdf(target_return / horizon_volatility)),
        Decimal("0"),
        Decimal("0.98"),
    )
    p_touch_down = clamp(
        Decimal("2") * (Decimal("1") - normal_cdf(stop_loss_return / horizon_volatility)),
        Decimal("0"),
        Decimal("0.98"),
    )

    barrier_success_ratio = stop_loss_return / (target_return + stop_loss_return)
    trend_adjustment = (Decimal(str(trend_score)) - Decimal("12.5")) / Decimal("100")
    barrier_success_ratio = clamp(
        barrier_success_ratio + trend_adjustment,
        Decimal("0.05"),
        Decimal("0.95"),
    )
    barrier_failure_ratio = Decimal("1") - barrier_success_ratio

    normalized = normalize_probabilities(
        p_touch_up * barrier_success_ratio,
        p_touch_down * barrier_failure_ratio,
        Decimal("1") - (p_touch_up * barrier_success_ratio) - (p_touch_down * barrier_failure_ratio),
    )
    return ProbabilityComponent(
        success=normalized["success"],
        failure=normalized["failure"],
        neutral=normalized["neutral"],
        weight=DEFAULT_VOLATILITY_WEIGHT,
        confidence=Decimal("0.6500"),
        details={
            "success": normalized["success"],
            "failure": normalized["failure"],
            "neutral": normalized["neutral"],
            "daily_volatility": quantize_probability(daily_volatility),
            "horizon_volatility": quantize_probability(horizon_volatility),
            "target_return": quantize_probability(target_return),
            "stop_loss_return": quantize_probability(stop_loss_return),
            "p_touch_up": quantize_probability(p_touch_up),
            "p_touch_down": quantize_probability(p_touch_down),
        },
        warnings=warnings,
    )

def combine_probability_components(
    *,
    historical: ProbabilityComponent,
    score: ProbabilityComponent,
    volatility: ProbabilityComponent,
    min_historical_cases: int = 30,
):
    historical_quality = clamp(
        _to_decimal(historical.sample_count) / Decimal(str(min_historical_cases)),
        Decimal("0"),
        Decimal("1"),
    )
    historical_weight = DEFAULT_HISTORICAL_WEIGHT * historical_quality
    remaining_weight = Decimal("1") - historical_weight
    ratio_base = DEFAULT_SCORE_WEIGHT + DEFAULT_VOLATILITY_WEIGHT
    score_weight = remaining_weight * (DEFAULT_SCORE_WEIGHT / ratio_base)
    volatility_weight = remaining_weight * (DEFAULT_VOLATILITY_WEIGHT / ratio_base)

    normalized = normalize_probabilities(
        (historical.success * historical_weight) + (score.success * score_weight) + (volatility.success * volatility_weight),
        (historical.failure * historical_weight) + (score.failure * score_weight) + (volatility.failure * volatility_weight),
        (historical.neutral * historical_weight) + (score.neutral * score_weight) + (volatility.neutral * volatility_weight),
    )
    return {
        "success": normalized["success"],
        "failure": normalized["failure"],
        "neutral": normalized["neutral"],
        "weights": {
            "historical": quantize_probability(historical_weight),
            "score": quantize_probability(score_weight),
            "volatility": quantize_probability(volatility_weight),
        },
    }


def calculate_probability_confidence(
    *,
    historical: ProbabilityComponent,
    score: ProbabilityComponent,
    volatility: ProbabilityComponent,
    data_quality: Decimal,
    min_historical_cases: int = 30,
) -> Decimal:
    sample_quality = clamp(
        _to_decimal(historical.sample_count) / Decimal(str(min_historical_cases)),
        Decimal("0"),
        Decimal("1"),
    )
    success_values = [float(historical.success), float(score.success), float(volatility.success)]
    agreement_std = Decimal(str(pstdev(success_values)))
    component_agreement = clamp(Decimal("1") - (agreement_std / Decimal("0.30")), Decimal("0"), Decimal("1"))
    confidence = (
        sample_quality * Decimal("0.45")
        + _to_decimal(data_quality) * Decimal("0.35")
        + component_agreement * Decimal("0.20")
    )
    return quantize_probability(clamp(confidence, Decimal("0"), Decimal("1")))
