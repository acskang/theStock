from marketdata.models import DailyPrice


def _get_row_value(row, field_name):
    if isinstance(row, dict):
        return row[field_name]
    return getattr(row, field_name)


def get_latest_price(stock):
    """Return the latest DailyPrice for the given stock."""
    return DailyPrice.objects.filter(stock=stock).order_by("-date").first()


def get_recent_prices(stock, limit=120, ascending=True):
    """Return recent DailyPrice records for the given stock."""
    queryset = DailyPrice.objects.filter(stock=stock).order_by("-date")
    if limit is not None:
        queryset = queryset[:limit]

    rows = list(queryset)
    if ascending:
        rows.reverse()
    return rows


def extract_close_prices(price_rows):
    """Extract close prices from DailyPrice rows."""
    return [_get_row_value(row, "close_price") for row in price_rows]


def extract_volumes(price_rows):
    """Extract volumes from DailyPrice rows."""
    return [_get_row_value(row, "volume") for row in price_rows]
