from django.conf import settings

from .toss_exceptions import TossOrderExecutionDisabled


def is_toss_order_execution_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def ensure_toss_order_execution_enabled() -> None:
    if not is_toss_order_execution_enabled(getattr(settings, "TOSS_ORDER_EXECUTION_ENABLED", False)):
        raise TossOrderExecutionDisabled("Toss order execution is disabled.")
