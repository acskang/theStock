from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from django.utils import timezone

from decisions.services.investor_flow_service import get_recent_investor_flows
from decisions.services.probability_components import clamp, quantize_probability
from decisions.services.risk_event_service import get_active_risk_events
from indicators.services.indicator_service import calculate_atr, calculate_moving_average, calculate_rsi
from marketdata.models import StockDataCollectionStatus
from marketdata.services.collection_status_service import get_collection_status_snapshot
from marketdata.services.market_service import get_market_context
from marketdata.services.price_service import extract_close_prices, get_latest_price, get_recent_prices
from decisions.models import RiskEvent


@dataclass(frozen=True)
class DataQualityResult:
    overall_score: Decimal
    label: str
    price_data_days: int
    latest_price_age_days: Optional[int]
    investor_flow_days: int
    market_data_available: bool
    risk_event_available: bool
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


def _get_data_quality_label(score: Decimal) -> str:
    if score >= Decimal("0.8000"):
        return "높음"
    if score >= Decimal("0.6000"):
        return "보통"
    if score >= Decimal("0.4000"):
        return "낮음"
    return "매우 낮음"


def evaluate_data_quality(holding) -> DataQualityResult:
    stock = holding.stock
    latest_price = get_latest_price(stock)
    price_rows = get_recent_prices(stock, limit=120, ascending=True)
    flow_rows = get_recent_investor_flows(stock, limit=20, ascending=True)
    market_context = get_market_context(stock)
    risk_events = get_active_risk_events(stock)
    flow_status = get_collection_status_snapshot(stock, StockDataCollectionStatus.TYPE_INVESTOR_FLOW)
    risk_status = get_collection_status_snapshot(stock, StockDataCollectionStatus.TYPE_RISK_EVENT)
    risk_event_row_exists = RiskEvent.objects.filter(stock=stock).exists()

    price_data_days = len(price_rows)
    investor_flow_days = len(flow_rows)
    market_data_available = bool(market_context["market_index_rows"])
    risk_event_available = bool(risk_events) or risk_event_row_exists or (
        risk_status.status
        in {
            StockDataCollectionStatus.STATUS_SUCCESS,
            StockDataCollectionStatus.STATUS_EMPTY,
        }
    )
    effective_flow_status = flow_status.status
    if investor_flow_days > 0 and flow_status.status == StockDataCollectionStatus.STATUS_NEVER:
        effective_flow_status = "legacy_data"
    effective_risk_status = risk_status.status
    if risk_event_row_exists and risk_status.status == StockDataCollectionStatus.STATUS_NEVER:
        effective_risk_status = "legacy_data"

    latest_price_age_days = None
    if latest_price is not None:
        latest_price_age_days = max((timezone.localdate() - latest_price.date).days, 0)

    score = Decimal("0")
    warnings = []

    if price_data_days >= 120:
        score += Decimal("0.30")
    elif price_data_days >= 60:
        score += Decimal("0.20")
    elif price_data_days >= 30:
        score += Decimal("0.10")
    else:
        warnings.append("가격 데이터가 부족해 결과 신뢰도가 낮을 수 있습니다.")

    if latest_price_age_days is not None:
        if latest_price_age_days <= 1:
            score += Decimal("0.20")
        elif latest_price_age_days <= 3:
            score += Decimal("0.10")
        else:
            warnings.append("최신 가격 데이터가 오래되어 현재 판단과 차이가 날 수 있습니다.")
    else:
        warnings.append("최신 가격 데이터가 없습니다.")

    if investor_flow_days >= 20:
        score += Decimal("0.15")
    elif investor_flow_days >= 5:
        score += Decimal("0.08")
    else:
        if flow_status.status == StockDataCollectionStatus.STATUS_ERROR:
            warnings.append("수급 자동 수집이 실패해 수급 판단은 제한적입니다.")
        elif flow_status.status == StockDataCollectionStatus.STATUS_NEVER:
            warnings.append("수급 자동 수집 이력이 없어 수급 판단은 제한적입니다.")
        else:
            warnings.append("수급 데이터가 부족해 수급 판단은 제한적입니다.")

    if market_data_available:
        score += Decimal("0.15")
    else:
        warnings.append("시장 데이터가 부족해 시장 국면 판단은 제한적입니다.")

    if risk_event_available:
        score += Decimal("0.10")
    elif risk_status.status == StockDataCollectionStatus.STATUS_ERROR:
        warnings.append("리스크 이벤트 자동 수집이 실패해 악재 판단은 제한적입니다.")
    elif risk_status.status == StockDataCollectionStatus.STATUS_NEVER:
        warnings.append("리스크 이벤트 수집 이력이 없어 악재 판단은 제한적입니다.")

    close_prices = extract_close_prices(price_rows)
    ma20 = calculate_moving_average(close_prices, 20)
    rsi14 = calculate_rsi(close_prices, 14)
    atr14 = calculate_atr(price_rows, 14)
    essential_calculations_available = latest_price is not None and ma20 is not None and rsi14 is not None
    if essential_calculations_available:
        score += Decimal("0.10")
    else:
        warnings.append("핵심 기술 지표 계산이 충분하지 않아 보수적으로 해석해야 합니다.")

    final_score = quantize_probability(clamp(score, Decimal("0"), Decimal("1")))
    return DataQualityResult(
        overall_score=final_score,
        label=_get_data_quality_label(final_score),
        price_data_days=price_data_days,
        latest_price_age_days=latest_price_age_days,
        investor_flow_days=investor_flow_days,
        market_data_available=market_data_available,
        risk_event_available=risk_event_available,
        warnings=warnings,
        details={
            "market_code": market_context["market_code"],
            "latest_price_available": latest_price is not None,
            "ma20_available": ma20 is not None,
            "rsi14_available": rsi14 is not None,
            "atr14_available": atr14 is not None,
            "essential_calculations_available": essential_calculations_available,
            "investor_flow_collection_status": effective_flow_status,
            "risk_event_collection_status": effective_risk_status,
            "risk_event_row_exists": risk_event_row_exists,
        },
    )


def get_data_quality_grade_cap(result: DataQualityResult) -> Optional[str]:
    if result.overall_score < Decimal("0.4000"):
        return "C"
    if result.overall_score < Decimal("0.6000"):
        return "B"
    return None
