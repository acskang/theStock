from decimal import Decimal


def get_success_probability_label(probability: Decimal) -> str:
    if probability >= Decimal("0.75"):
        return "높음"
    if probability >= Decimal("0.55"):
        return "보통 이상"
    if probability >= Decimal("0.40"):
        return "중립"
    if probability >= Decimal("0.25"):
        return "낮음"
    return "매우 낮음"


def get_failure_probability_label(probability: Decimal) -> str:
    if probability >= Decimal("0.60"):
        return "매우 위험"
    if probability >= Decimal("0.40"):
        return "위험"
    if probability >= Decimal("0.25"):
        return "주의"
    return "상대적으로 낮음"


def get_confidence_label(confidence: Decimal) -> str:
    if confidence >= Decimal("0.75"):
        return "높음"
    if confidence >= Decimal("0.50"):
        return "보통"
    if confidence >= Decimal("0.25"):
        return "낮음"
    return "매우 낮음"
