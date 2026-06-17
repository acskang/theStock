from marketdata.models import InvestorFlow


def get_recent_investor_flows(stock, limit=5, ascending=True):
    """Return recent investor flow rows for the given stock."""
    queryset = InvestorFlow.objects.filter(stock=stock).order_by("-date")
    if limit is not None:
        queryset = queryset[:limit]

    rows = list(queryset)
    if ascending:
        rows.reverse()
    return rows


def _get_row_value(row, field_name):
    if isinstance(row, dict):
        return row[field_name]
    return getattr(row, field_name)


def calculate_investor_flow_score(flow_rows):
    """Calculate investor flow score from recent InvestorFlow rows."""
    rows = sorted(flow_rows, key=lambda row: _get_row_value(row, "date"))
    if not rows:
        return {
            "score": 0,
            "reasons": ["수급 데이터가 없어 수급 점수를 중립으로 처리했습니다."],
            "details": {
                "foreign_positive_days": 0,
                "institution_positive_days": 0,
                "foreign_sum": 0,
                "institution_sum": 0,
                "individual_sum": 0,
            },
        }

    recent_rows = rows[-5:]
    foreign_positive_days = sum(1 for row in recent_rows if _get_row_value(row, "foreign_net_buy") > 0)
    institution_positive_days = sum(1 for row in recent_rows if _get_row_value(row, "institution_net_buy") > 0)
    both_positive_days = sum(
        1
        for row in recent_rows
        if _get_row_value(row, "foreign_net_buy") > 0 and _get_row_value(row, "institution_net_buy") > 0
    )
    both_negative_days = sum(
        1
        for row in recent_rows
        if _get_row_value(row, "foreign_net_buy") < 0 and _get_row_value(row, "institution_net_buy") < 0
    )

    foreign_sum = sum(_get_row_value(row, "foreign_net_buy") for row in recent_rows)
    institution_sum = sum(_get_row_value(row, "institution_net_buy") for row in recent_rows)
    individual_sum = sum(_get_row_value(row, "individual_net_buy") for row in recent_rows)

    score = 0
    reasons = []

    if foreign_positive_days >= 3:
        score += 5
        reasons.append("최근 5거래일 중 외국인 순매수가 3일 이상입니다.")

    if institution_positive_days >= 3:
        score += 5
        reasons.append("최근 5거래일 중 기관 순매수가 3일 이상입니다.")

    if both_positive_days >= 3:
        score += 10
        reasons.append("외국인과 기관의 동시 순매수 흐름이 확인됩니다.")

    if both_negative_days >= 3:
        score -= 20
        reasons.append("외국인과 기관의 동시 순매도 흐름이 강합니다.")

    if individual_sum > 0 and foreign_sum < 0 and institution_sum < 0:
        score -= 5
        reasons.append("개인만 순매수하는 구조라 보수적으로 해석했습니다.")

    return {
        "score": max(-20, min(20, score)),
        "reasons": reasons,
        "details": {
            "foreign_positive_days": foreign_positive_days,
            "institution_positive_days": institution_positive_days,
            "foreign_sum": foreign_sum,
            "institution_sum": institution_sum,
            "individual_sum": individual_sum,
        },
    }
