from decisions.models import RiskEvent


RISK_SCORE_MAP = {
    RiskEvent.RISK_LOW: -5,
    RiskEvent.RISK_MEDIUM: -15,
    RiskEvent.RISK_HIGH: -30,
    RiskEvent.RISK_CRITICAL: -50,
}
RISK_LEVEL_PRIORITY = {
    RiskEvent.RISK_LOW: 1,
    RiskEvent.RISK_MEDIUM: 2,
    RiskEvent.RISK_HIGH: 3,
    RiskEvent.RISK_CRITICAL: 4,
}


def get_active_risk_events(stock):
    """Return active risk events for a stock."""
    return list(RiskEvent.objects.filter(stock=stock, is_active=True).order_by("-event_date"))


def has_critical_risk(stock):
    """Return whether the stock has critical risk events."""
    events = [event for event in get_active_risk_events(stock) if event.risk_level == RiskEvent.RISK_CRITICAL]
    return {
        "has_critical": bool(events),
        "events": events,
    }


def calculate_risk_score(risk_events):
    """Calculate risk penalty from active risk events."""
    active_events = [event for event in risk_events if event.is_active]
    if not active_events:
        return {
            "score": 0,
            "reasons": [],
            "details": {
                "event_count": 0,
                "highest_risk_level": None,
            },
        }

    score = 0
    reasons = []
    highest_risk_level = None
    highest_priority = 0

    for event in active_events:
        penalty = RISK_SCORE_MAP.get(event.risk_level, 0)
        score += penalty
        if event.risk_level == RiskEvent.RISK_HIGH:
            reasons.append(f"고위험 이벤트가 감지되었습니다: {event.title}")
        elif event.risk_level == RiskEvent.RISK_MEDIUM:
            reasons.append(f"중간 수준의 위험 이벤트가 감지되었습니다: {event.title}")
        elif event.risk_level == RiskEvent.RISK_LOW:
            reasons.append(f"경미한 위험 이벤트가 감지되었습니다: {event.title}")
        elif event.risk_level == RiskEvent.RISK_CRITICAL:
            reasons.append(f"치명적 위험 이벤트가 감지되었습니다: {event.title}")

        priority = RISK_LEVEL_PRIORITY.get(event.risk_level, 0)
        if priority > highest_priority:
            highest_priority = priority
            highest_risk_level = event.risk_level

    return {
        "score": max(-50, score),
        "reasons": reasons,
        "details": {
            "event_count": len(active_events),
            "highest_risk_level": highest_risk_level,
        },
    }
