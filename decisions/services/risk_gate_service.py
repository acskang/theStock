from dataclasses import dataclass, field
from typing import Optional

from django.utils import timezone

from decisions.services.risk_event_service import get_active_risk_events


CRITICAL_KEYWORDS = ("거래정지", "상장폐지", "감사의견 거절", "관리종목", "회생절차", "자본잠식")
BLOCK_KEYWORDS = ("감자", "유상증자", "횡령", "배임")
CAUTION_KEYWORDS = ("영업손실", "적자", "실적 부진", "투자주의", "투자경고")
STATUS_PRIORITY = {
    "PASS": 0,
    "CAUTION": 1,
    "BLOCK": 2,
    "CRITICAL": 3,
}
STATUS_CONFIG = {
    "PASS": {"grade_cap": None, "score_multiplier": 1.0},
    "CAUTION": {"grade_cap": "B", "score_multiplier": 0.8},
    "BLOCK": {"grade_cap": "C", "score_multiplier": 0.5},
    "CRITICAL": {"grade_cap": "D", "score_multiplier": 0.0},
}


@dataclass(frozen=True)
class RiskGateResult:
    status: str
    grade_cap: Optional[str]
    score_multiplier: float
    critical_events: list
    blockers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)


def _get_time_decay_weight(event_date):
    age_days = max((timezone.localdate() - event_date).days, 0)
    if age_days <= 7:
        return age_days, 1.0
    if age_days <= 30:
        return age_days, 0.8
    if age_days <= 90:
        return age_days, 0.6
    if age_days <= 180:
        return age_days, 0.4
    return age_days, 0.25


def _apply_time_decay_to_status(status, time_weight):
    if status == "CRITICAL":
        if time_weight >= 0.8:
            return "CRITICAL"
        if time_weight >= 0.4:
            return "BLOCK"
        return "CAUTION"
    if status == "BLOCK":
        if time_weight >= 0.6:
            return "BLOCK"
        return "CAUTION"
    if status == "CAUTION":
        if time_weight >= 0.4:
            return "CAUTION"
        return "PASS"
    return "PASS"


def _build_event_message(event, raw_status, effective_status, age_days):
    if raw_status != effective_status:
        decay_suffix = f" ({age_days}일 경과로 {raw_status} -> {effective_status} 완화)"
    else:
        decay_suffix = ""

    if effective_status == "CRITICAL":
        return "blocker", f"치명적 위험 이벤트: {event.title}{decay_suffix}"
    if effective_status == "BLOCK":
        return "blocker", f"추가 매수 차단 사유: {event.title}{decay_suffix}"
    if effective_status == "CAUTION":
        if raw_status in {"CRITICAL", "BLOCK"} and raw_status != effective_status:
            return "warning", f"과거 위험 이벤트 이력이 있어 주의가 필요합니다: {event.title}{decay_suffix}"
        return "warning", f"주의 이벤트가 감지되었습니다: {event.title}{decay_suffix}"
    return "warning", f"오래된 이벤트 이력: {event.title} ({age_days}일 경과)"


def classify_risk_event(event) -> str:
    combined_text = " ".join(
        filter(
            None,
            [
                getattr(event, "event_type", ""),
                getattr(event, "title", ""),
                getattr(event, "description", ""),
            ],
        )
    ).lower()

    if getattr(event, "risk_level", "") == "critical":
        return "CRITICAL"
    if any(keyword in combined_text for keyword in CRITICAL_KEYWORDS):
        return "CRITICAL"
    if any(keyword in combined_text for keyword in BLOCK_KEYWORDS):
        return "BLOCK"
    if any(keyword in combined_text for keyword in CAUTION_KEYWORDS):
        return "CAUTION"

    risk_level = getattr(event, "risk_level", "")
    if risk_level == "high":
        return "BLOCK"
    if risk_level in {"medium", "low"}:
        return "CAUTION"
    return "CAUTION"


def evaluate_risk_gate(holding) -> RiskGateResult:
    events = get_active_risk_events(holding.stock)
    if not events:
        return RiskGateResult(
            status="PASS",
            grade_cap=None,
            score_multiplier=1.0,
            critical_events=[],
            blockers=[],
            warnings=[],
            details={"event_count": 0, "event_statuses": []},
        )

    final_status = "PASS"
    critical_events = []
    blockers = []
    warnings = []
    event_statuses = []
    final_status_before_decay = "PASS"
    decayed_event_count = 0

    for event in events:
        status = classify_risk_event(event)
        age_days, time_weight = _get_time_decay_weight(event.event_date)
        effective_status = _apply_time_decay_to_status(status, time_weight)
        event_statuses.append(
            {
                "title": event.title,
                "status": effective_status,
                "raw_status": status,
                "effective_status": effective_status,
                "age_days": age_days,
                "time_weight": time_weight,
            }
        )
        if STATUS_PRIORITY[status] > STATUS_PRIORITY[final_status_before_decay]:
            final_status_before_decay = status
        if STATUS_PRIORITY[effective_status] > STATUS_PRIORITY[final_status]:
            final_status = effective_status
        if effective_status != status:
            decayed_event_count += 1

        if effective_status == "CRITICAL":
            critical_events.append(event.title)

        message_type, message = _build_event_message(event, status, effective_status, age_days)
        if message_type == "blocker":
            blockers.append(message)
        else:
            warnings.append(message)

    config = STATUS_CONFIG[final_status]
    return RiskGateResult(
        status=final_status,
        grade_cap=config["grade_cap"],
        score_multiplier=config["score_multiplier"],
        critical_events=critical_events,
        blockers=blockers,
        warnings=warnings,
        details={
            "event_count": len(events),
            "final_status_before_decay": final_status_before_decay,
            "final_status_after_decay": final_status,
            "decayed_event_count": decayed_event_count,
            "event_statuses": event_statuses,
        },
    )
