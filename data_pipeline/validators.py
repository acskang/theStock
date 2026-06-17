from marketdata.models import DailyPrice
from stocks.models import FinancialSnapshot, Stock


def validate_stock_code(code: str) -> None:
    if not code or not code.strip():
        raise ValueError("stock_code is required.")


def validate_market(market: str) -> None:
    allowed = {choice[0] for choice in Stock.MARKET_CHOICES}
    if market not in allowed:
        raise ValueError(f"Unsupported market: {market}")


def validate_daily_price_row(row) -> None:
    probe = DailyPrice(
        stock_id=0,
        date=row.date,
        open_price=row.open_price,
        high_price=row.high_price,
        low_price=row.low_price,
        close_price=row.close_price,
        volume=row.volume,
        change_rate=row.change_rate,
    )
    probe.clean()


def validate_financial_period(period_type: str) -> None:
    allowed = {choice[0] for choice in FinancialSnapshot.PERIOD_CHOICES}
    if period_type not in allowed:
        raise ValueError(f"Unsupported financial period: {period_type}")

