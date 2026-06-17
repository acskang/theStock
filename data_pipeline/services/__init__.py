from holdings.models import UserHolding
from stocks.models import Stock


def resolve_target_stocks(*, stock_codes=None, all_stocks=False):
    queryset = Stock.objects.all()
    if stock_codes:
        return list(queryset.filter(code__in=stock_codes).order_by("code"))
    if all_stocks:
        return list(queryset.filter(is_active=True).order_by("code"))

    active_stock_ids = (
        UserHolding.objects.filter(is_active=True)
        .values_list("stock_id", flat=True)
        .distinct()
    )
    return list(queryset.filter(id__in=active_stock_ids).order_by("code"))

