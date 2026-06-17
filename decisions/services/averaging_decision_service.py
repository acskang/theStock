import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from decisions.models import AveragingDecision, DISCLAIMER_TEXT
from decisions.services.investor_flow_service import calculate_investor_flow_score, get_recent_investor_flows
from decisions.services.risk_event_service import calculate_risk_score, get_active_risk_events, has_critical_risk
from decisions.services.scoring_service import (
    build_reason_summary,
    calculate_stop_loss_price,
    calculate_suggested_budget,
    calculate_total_score,
    calculate_trend_score,
    convert_score_to_grade,
    get_decision_text,
)
from decisions.services.support_service import calculate_support_score
from decisions.services.volume_service import calculate_volume_score
from indicators.services.indicator_service import (
    calculate_atr,
    calculate_bollinger_bands,
    calculate_macd,
    calculate_moving_average,
    calculate_rsi,
    calculate_volume_ma,
)
from marketdata.services.market_service import calculate_market_score, get_market_context
from marketdata.services.price_service import extract_close_prices, get_latest_price, get_recent_prices

logger = logging.getLogger(__name__)


@dataclass
class EvaluationResult:
    score: int
    grade: str
    decision: str
    reason_summary: str
    reasons: list[str] = field(default_factory=list)
    score_breakdown: dict = field(default_factory=dict)
    suggested_budget: Decimal = Decimal("0")
    stop_loss_price: Optional[Decimal] = None
    disclaimer: str = DISCLAIMER_TEXT


def _build_indicator_snapshot(price_rows):
    close_prices = extract_close_prices(price_rows)
    return {
        "ma5": calculate_moving_average(close_prices, 5),
        "ma20": calculate_moving_average(close_prices, 20),
        "ma60": calculate_moving_average(close_prices, 60),
        "ma120": calculate_moving_average(close_prices, 120),
        "rsi14": calculate_rsi(close_prices, 14),
        "atr14": calculate_atr(price_rows, 14),
        "volume_ma20": calculate_volume_ma([row.volume for row in price_rows], 20),
        **{
            "macd": calculate_macd(close_prices)["macd"],
            "macd_signal": calculate_macd(close_prices)["signal"],
            "macd_histogram": calculate_macd(close_prices)["histogram"],
        },
        **{
            "bb_upper": calculate_bollinger_bands(close_prices)["upper"],
            "bb_middle": calculate_bollinger_bands(close_prices)["middle"],
            "bb_lower": calculate_bollinger_bands(close_prices)["lower"],
        },
    }


def _empty_breakdown(risk=0):
    return {
        "trend": 0,
        "support": 0,
        "volume": 0,
        "flow": 0,
        "market": 0,
        "risk": risk,
        "raw_total": 0,
        "final_total": 0,
    }


def evaluate_averaging_timing(holding):
    """Evaluate averaging-down timing for the given holding."""
    stock = holding.stock
    latest_price = get_latest_price(stock)
    if latest_price is None:
        logger.info(
            "Latest price missing during evaluation",
            extra={
                "holding_id": holding.id,
                "stock_code": stock.code,
            },
        )
        return EvaluationResult(
            score=0,
            grade="D",
            decision="데이터 부족으로 평가 불가",
            reason_summary="최신 가격 데이터가 없어 평가할 수 없습니다.",
            reasons=["최신 가격 데이터가 없어 평가를 진행하지 못했습니다."],
            score_breakdown=_empty_breakdown(),
            suggested_budget=Decimal("0"),
            stop_loss_price=None,
        )

    recent_prices = get_recent_prices(stock, limit=120, ascending=True)
    active_risk_events = get_active_risk_events(stock)
    critical_risk = has_critical_risk(stock)
    if critical_risk["has_critical"]:
        reasons = [f"치명적 위험 이벤트가 감지되었습니다: {event.title}" for event in critical_risk["events"]]
        logger.info(
            "Critical risk detected during evaluation",
            extra={
                "holding_id": holding.id,
                "stock_code": stock.code,
                "critical_event_count": len(critical_risk["events"]),
            },
        )
        return EvaluationResult(
            score=0,
            grade="D",
            decision=get_decision_text("D"),
            reason_summary="치명적 위험 이벤트가 감지되어 추가 매수 검토보다 리스크 점검이 우선입니다.",
            reasons=reasons,
            score_breakdown=_empty_breakdown(risk=-50),
            suggested_budget=Decimal("0"),
            stop_loss_price=None,
        )

    indicators = _build_indicator_snapshot(recent_prices)
    trend_result = calculate_trend_score(recent_prices, indicators=indicators)
    support_result = calculate_support_score(recent_prices)
    volume_result = calculate_volume_score(recent_prices)
    flow_result = calculate_investor_flow_score(get_recent_investor_flows(stock, limit=5, ascending=True))

    market_context = get_market_context(stock)
    market_result = calculate_market_score(
        stock,
        market_context["market_index_rows"],
        fx_rows=market_context["fx_rows"],
        global_index_rows=market_context["global_index_rows"],
    )
    risk_result = calculate_risk_score(active_risk_events)

    total_score = calculate_total_score(
        trend_score=trend_result["score"],
        support_score=support_result["score"],
        volume_score=volume_result["score"],
        flow_score=flow_result["score"],
        market_score=market_result["score"],
        risk_score=risk_result["score"],
    )
    grade = convert_score_to_grade(total_score["final_score"])
    decision_text = get_decision_text(grade)

    reasons = (
        risk_result["reasons"]
        + market_result["reasons"]
        + trend_result["reasons"]
        + support_result["reasons"]
        + volume_result["reasons"]
        + flow_result["reasons"]
    )
    reason_summary = build_reason_summary(grade, reasons)
    suggested_budget = calculate_suggested_budget(holding, grade)
    stop_loss_price = calculate_stop_loss_price(
        latest_price.close_price,
        support_price=support_result["details"].get("support_price"),
        atr14=indicators.get("atr14"),
    )

    logger.info(
        "Evaluation result calculated",
        extra={
            "holding_id": holding.id,
            "stock_code": stock.code,
            "score": total_score["final_score"],
            "grade": grade,
        },
    )

    return EvaluationResult(
        score=total_score["final_score"],
        grade=grade,
        decision=decision_text,
        reason_summary=reason_summary,
        reasons=reasons,
        score_breakdown={
            "trend": trend_result["score"],
            "support": support_result["score"],
            "volume": volume_result["score"],
            "flow": flow_result["score"],
            "market": market_result["score"],
            "risk": risk_result["score"],
            "raw_total": total_score["raw_score"],
            "final_total": total_score["final_score"],
        },
        suggested_budget=suggested_budget,
        stop_loss_price=stop_loss_price,
    )


def create_decision_from_result(holding, result):
    """Persist AveragingDecision from evaluation result."""
    return AveragingDecision.objects.create(
        holding=holding,
        score=result.score,
        grade=result.grade,
        decision=result.decision,
        reason_summary=result.reason_summary,
        reasons=result.reasons,
        score_breakdown=result.score_breakdown,
        suggested_budget=result.suggested_budget,
        stop_loss_price=result.stop_loss_price,
        disclaimer=result.disclaimer,
    )
