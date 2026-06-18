from __future__ import annotations
from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from statistics import mean, pstdev
from typing import Dict, Iterable, List

import pandas as pd
import yfinance as yf
from django.db.models import Count

from holdings.services.stock_resolution_service import resolve_stock_from_legacy_name
from marketdata.models import DailyPrice

from .models import StockSymbol, Transaction


DEFAULT_TICKERS = {
    'KB스타리츠': '432320.KS',
    '엑세스바이오': '950130.KQ',
    '뱅크웨어글로벌': '199480.KQ',
    '심텍홀딩스': '036710.KQ',
    '호텔신라': '008770.KS',
    '신한글로벌액티브리츠': '481850.KS',
    '삼성FN리츠': '448730.KS',
    'SK리츠': '395400.KS',
    'CJ CGV': '079160.KS',
    'LG헬로비전': '037560.KS',
    '송원산업': '004430.KS',
    '롯데리츠': '330590.KS',
    '신일전자': '002700.KS',
    '강원랜드': '035250.KS',
    'GS건설': '006360.KS',
    '한화손해보험': '000370.KS',
}


@dataclass
class PriceSnapshot:
    stock_name: str
    ticker: str
    current_price: int | None
    previous_close: int | None
    change_rate: float | None
    currency: str | None
    fetched_at: datetime
    error: str = ''


@dataclass
class RealizedTrade:
    stock_name: str
    sold_qty: int
    sell_price: int
    avg_buy_price: int
    proceeds: int
    cost: int
    profit: int
    profit_rate: float
    sold_at: str
    note: str = ''


@dataclass(frozen=True)
class AggregatedPosition:
    stock_name: str
    quantity: int
    average_price: Decimal
    total_cost: Decimal


def _round_int(value: Decimal | float | int) -> int:
    return int(Decimal(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _quantize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def _format_money_display(value: int | Decimal | None) -> str:
    if value is None:
        return "-"
    return f"{int(value):,}"


def _format_percent_display(value: float | None) -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:.2f}%"


def _format_days_display(value: int | None) -> str:
    if value is None:
        return "-"
    return f"{value}일"


def _format_summary_decimal(value: Decimal | int | None, places: str = "0.01") -> str | None:
    if value is None:
        return None
    return str(Decimal(value).quantize(Decimal(places), rounding=ROUND_HALF_UP))


def _format_summary_date(value: date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _latest_daily_price(stock):
    return DailyPrice.objects.filter(stock=stock).order_by("-date").first()


def _clamp_score(value: float) -> int:
    return max(0, min(100, int(round(value))))


def _empty_retro_sparkline() -> Dict:
    return {
        "sparkline_available": False,
        "sparkline_points": "",
        "sparkline_baseline_y": None,
        "sparkline_min_display": "-",
        "sparkline_max_display": "-",
        "sparkline_last_display": "-",
        "sparkline_last_return_display": "-",
        "sparkline_day_span": 0,
    }


def _ordered_transactions(transactions: Iterable[Transaction]) -> List[Transaction]:
    if hasattr(transactions, "order_by"):
        transactions = transactions.order_by("year", "month", "day", "hour", "minute", "id")
    return list(transactions)


def seed_default_symbols() -> None:
    for name, ticker in DEFAULT_TICKERS.items():
        StockSymbol.objects.get_or_create(stock_name=name, defaults={'ticker': ticker, 'note': '기본 매핑'})


def import_transactions_from_dataframe(df: pd.DataFrame) -> int:
    expected = ['매매구분', '종목', '년', '월', '일', '시', '분', '수량(주)', '단가(원)']
    missing = [col for col in expected if col not in df.columns]
    if missing:
        raise ValueError(f'필수 컬럼이 없습니다: {", ".join(missing)}')

    rows = []
    for _, row in df.iterrows():
        rows.append(Transaction(
            trade_type=str(row['매매구분']).strip(),
            stock_name=str(row['종목']).strip(),
            year=int(row['년']),
            month=int(row['월']),
            day=int(row['일']),
            hour=int(row['시']),
            minute=int(row['분']),
            quantity=int(row['수량(주)']),
            unit_price=int(row['단가(원)']),
        ))
    Transaction.objects.bulk_create(rows)
    return len(rows)


def load_csv_file(file_obj) -> int:
    df = pd.read_csv(file_obj)
    return import_transactions_from_dataframe(df)


def upsert_symbol_mapping(stock_name: str, ticker: str, note: str = '') -> StockSymbol:
    stock_name = stock_name.strip()
    ticker = ticker.strip().upper()
    symbol, _ = StockSymbol.objects.update_or_create(
        stock_name=stock_name,
        defaults={'ticker': ticker, 'note': note.strip()},
    )
    return symbol


def get_unmapped_stock_names() -> List[str]:
    used_names = set(Transaction.objects.values_list('stock_name', flat=True).distinct())
    mapped_names = set(StockSymbol.objects.values_list('stock_name', flat=True))
    return sorted(used_names - mapped_names)


def get_symbol_usage() -> List[Dict]:
    counts = dict(
        Transaction.objects.values('stock_name').annotate(cnt=Count('id')).values_list('stock_name', 'cnt')
    )
    symbols = []
    for symbol in StockSymbol.objects.all().order_by('stock_name'):
        symbols.append({
            'id': symbol.id,
            'stock_name': symbol.stock_name,
            'ticker': symbol.ticker,
            'note': symbol.note,
            'updated_at': symbol.updated_at,
            'usage_count': counts.get(symbol.stock_name, 0),
        })
    return symbols


def get_price_snapshot(stock_name: str) -> PriceSnapshot:
    mapping = StockSymbol.objects.filter(stock_name=stock_name).first()
    if not mapping:
        return PriceSnapshot(stock_name, '', None, None, None, None, datetime.now(), error='티커 매핑 없음')

    ticker = mapping.ticker
    fetched_at = datetime.now()
    try:
        tk = yf.Ticker(ticker)
        info = tk.fast_info
        current = _safe_fast_info_get(info, 'lastPrice') or _safe_fast_info_get(info, 'regularMarketPrice')
        prev_close = _safe_fast_info_get(info, 'previousClose')
        currency = _safe_fast_info_get(info, 'currency') or 'KRW'
        if current is None:
            history = tk.history(period='5d', auto_adjust=False)
            if not history.empty:
                latest = history.iloc[-1]
                current = latest.get('Close')
                if len(history) >= 2:
                    prev_close = history.iloc[-2].get('Close')
        change_rate = None
        if current is not None and prev_close:
            change_rate = ((current - prev_close) / prev_close) * 100
        return PriceSnapshot(
            stock_name=stock_name,
            ticker=ticker,
            current_price=_round_int(current) if current is not None else None,
            previous_close=_round_int(prev_close) if prev_close is not None else None,
            change_rate=round(change_rate, 2) if change_rate is not None else None,
            currency=currency,
            fetched_at=fetched_at,
            error='' if current is not None else '시세 데이터 없음',
        )
    except Exception as exc:
        return PriceSnapshot(stock_name, ticker, None, None, None, None, fetched_at, error='시세 조회 실패')


def _safe_fast_info_get(info, key):
    try:
        return info.get(key)
    except Exception:
        return None


def get_price_board(names: List[str]) -> List[PriceSnapshot]:
    ordered = sorted(set(name for name in names if name))
    return [get_price_snapshot(name) for name in ordered]


def summarize_transactions() -> Dict:
    qs = Transaction.objects.all()
    monthly = defaultdict(lambda: {'매수': 0, '매도': 0})
    by_stock = defaultdict(int)
    for tx in qs:
        key = f'{tx.year}-{tx.month:02d}'
        monthly[key][tx.trade_type] += tx.total_amount
        by_stock[tx.stock_name] += 1
    labels = sorted(monthly.keys())
    buy_values = [monthly[k]['매수'] for k in labels]
    sell_values = [monthly[k]['매도'] for k in labels]

    stock_items = sorted(by_stock.items(), key=lambda x: (-x[1], x[0]))
    return {
        'monthly_labels': labels,
        'monthly_buy': buy_values,
        'monthly_sell': sell_values,
        'stock_labels': [x[0] for x in stock_items],
        'stock_counts': [x[1] for x in stock_items],
    }


def build_portfolio_summary(user, include_inactive=False):
    if user is None:
        raise ValueError("user is required")

    from holdings.models import UserHolding

    queryset = UserHolding.objects.filter(user=user).select_related("stock").order_by("stock__code", "id")
    if not include_inactive:
        queryset = queryset.filter(is_active=True)

    holdings = []
    warnings = []
    as_of = None
    active_holding_count = 0
    priced_holding_count = 0
    missing_price_count = 0
    calculation_unavailable_count = 0
    total_invested_amount_all = Decimal("0.00")
    total_invested_amount_priced = Decimal("0.00")
    total_market_value_priced = Decimal("0.00")

    for holding in queryset:
        if holding.is_active:
            active_holding_count += 1

        quantity = holding.quantity
        average_price = holding.average_price
        invested_amount = None
        if quantity is not None and average_price is not None:
            invested_amount = Decimal(quantity) * Decimal(average_price)
            total_invested_amount_all += invested_amount
        else:
            calculation_unavailable_count += 1

        latest_price_row = _latest_daily_price(holding.stock)
        latest_price = latest_price_row.close_price if latest_price_row else None
        latest_price_date = latest_price_row.date if latest_price_row else None

        market_value = None
        profit_loss_amount = None
        profit_loss_rate = None
        price_status = "missing_daily_price"

        if latest_price_row and invested_amount is not None:
            price_status = "priced"
            priced_holding_count += 1
            market_value = Decimal(quantity) * Decimal(latest_price)
            profit_loss_amount = market_value - invested_amount
            if invested_amount != Decimal("0"):
                profit_loss_rate = (profit_loss_amount / invested_amount) * Decimal("100")
            total_invested_amount_priced += invested_amount
            total_market_value_priced += market_value
            if as_of is None or latest_price_date > as_of:
                as_of = latest_price_date
        elif not latest_price_row:
            missing_price_count += 1

        holdings.append(
            {
                "holding_id": holding.id,
                "stock": {
                    "code": holding.stock.code,
                    "name": holding.stock.name,
                    "market": holding.stock.market,
                },
                "quantity": quantity,
                "average_price": _format_summary_decimal(average_price),
                "latest_price": _format_summary_decimal(latest_price),
                "latest_price_date": _format_summary_date(latest_price_date),
                "invested_amount": _format_summary_decimal(invested_amount),
                "market_value": _format_summary_decimal(market_value),
                "profit_loss_amount": _format_summary_decimal(profit_loss_amount),
                "profit_loss_rate": _format_summary_decimal(profit_loss_rate),
                "risk_level": holding.risk_level,
                "max_additional_budget": _format_summary_decimal(holding.max_additional_budget),
                "is_active": holding.is_active,
                "price_status": price_status,
            }
        )

    holding_count = len(holdings)
    if holding_count == 0:
        warnings.append("No holdings are available for portfolio summary.")
    if missing_price_count:
        warnings.append(
            f"{missing_price_count} holdings have no latest DailyPrice and are excluded from priced totals."
        )
    if calculation_unavailable_count:
        warnings.append(
            f"{calculation_unavailable_count} holdings have unavailable quantity or average price."
        )

    total_profit_loss_amount_priced = total_market_value_priced - total_invested_amount_priced
    total_profit_loss_rate_priced = None
    if total_invested_amount_priced != Decimal("0"):
        total_profit_loss_rate_priced = (
            total_profit_loss_amount_priced / total_invested_amount_priced
        ) * Decimal("100")

    return {
        "as_of": _format_summary_date(as_of),
        "holding_count": holding_count,
        "active_holding_count": active_holding_count,
        "priced_holding_count": priced_holding_count,
        "missing_price_count": missing_price_count,
        "totals": {
            "total_invested_amount_all": _format_summary_decimal(total_invested_amount_all),
            "total_invested_amount_priced": _format_summary_decimal(total_invested_amount_priced),
            "total_market_value_priced": _format_summary_decimal(total_market_value_priced),
            "total_profit_loss_amount_priced": _format_summary_decimal(total_profit_loss_amount_priced),
            "total_profit_loss_rate_priced": _format_summary_decimal(total_profit_loss_rate_priced),
        },
        "holdings": holdings,
        "warnings": warnings,
    }


def aggregate_transactions_to_positions(transactions: Iterable[Transaction]) -> tuple[List[AggregatedPosition], List[str]]:
    states: Dict[str, Dict[str, Decimal]] = defaultdict(lambda: {'qty': Decimal('0'), 'cost': Decimal('0')})
    warnings: List[str] = []

    for tx in _ordered_transactions(transactions):
        state = states[tx.stock_name]
        quantity = Decimal(str(tx.quantity))
        unit_price = Decimal(str(tx.unit_price))

        if tx.trade_type == '매수':
            state['qty'] += quantity
            state['cost'] += quantity * unit_price
            continue

        if tx.trade_type != '매도':
            continue

        if state['qty'] <= 0:
            warnings.append(
                f'{tx.stock_name} {tx.year}-{tx.month:02d}-{tx.day:02d} {tx.hour:02d}:{tx.minute:02d} '
                '매도는 보유수량이 없어 보유 집계에서 제외했습니다.'
            )
            continue

        sellable_qty = min(quantity, state['qty'])
        average_price = state['cost'] / state['qty'] if state['qty'] > 0 else Decimal('0')
        state['qty'] -= sellable_qty
        state['cost'] -= average_price * sellable_qty

        if quantity > sellable_qty:
            warnings.append(
                f'{tx.stock_name} {tx.year}-{tx.month:02d}-{tx.day:02d} {tx.hour:02d}:{tx.minute:02d} '
                f'매도 {int(quantity)}주 중 보유 {int(sellable_qty)}주만 반영했습니다.'
            )

        if state['qty'] <= 0:
            state['qty'] = Decimal('0')
            state['cost'] = Decimal('0')

    positions = []
    for stock_name, state in sorted(states.items()):
        quantity = int(state['qty'])
        if quantity > 0:
            average_price = _quantize_money(state['cost'] / state['qty'])
            total_cost = _quantize_money(state['cost'])
        else:
            average_price = Decimal('0.00')
            total_cost = Decimal('0.00')
        positions.append(
            AggregatedPosition(
                stock_name=stock_name,
                quantity=quantity,
                average_price=average_price,
                total_cost=total_cost,
            )
        )

    return positions, warnings


def aggregate_all_transactions_by_stock() -> tuple[List[AggregatedPosition], List[str]]:
    return aggregate_transactions_to_positions(Transaction.objects.all())


def _transaction_to_date(tx: Transaction) -> date:
    return date(tx.year, tx.month, tx.day)


def _build_trade_timestamp(tx: Transaction) -> str:
    return f"{tx.year}-{tx.month:02d}-{tx.day:02d} {tx.hour:02d}:{tx.minute:02d}"


def _build_entry_context(pre_quantity: Decimal, pre_average_price: Decimal | None, buy_price: Decimal) -> str:
    if pre_quantity <= 0:
        return "첫 매수"
    if pre_average_price is not None and buy_price < pre_average_price:
        return "물타기 매수"
    if pre_average_price is not None and buy_price > pre_average_price:
        return "추가 매수(평단 상승)"
    return "추가 매수"


def _calculate_retro_timing_score(metrics: Dict, pre_buy_return_5: float | None) -> Dict:
    return_20 = metrics["return_20"]
    distance_to_trough_20 = metrics["distance_to_trough_20"]
    days_to_break_even_20 = metrics["days_to_break_even_20"]

    return_score = 50 if return_20 is None else _clamp_score(50 + (return_20 * 3))
    trough_score = 50 if distance_to_trough_20 is None else _clamp_score(100 - (distance_to_trough_20 * 6))
    break_even_score = 20 if days_to_break_even_20 is None else _clamp_score(100 - ((days_to_break_even_20 - 1) * 6))
    if pre_buy_return_5 is None:
        pre_buy_score = 50
    elif pre_buy_return_5 <= 0:
        pre_buy_score = _clamp_score(50 + (abs(pre_buy_return_5) * 4))
    else:
        pre_buy_score = _clamp_score(50 - (pre_buy_return_5 * 4))

    composite_score = _clamp_score(
        (return_score * 0.35)
        + (trough_score * 0.25)
        + (break_even_score * 0.25)
        + (pre_buy_score * 0.15)
    )

    if composite_score >= 80:
        score_label = "우수"
    elif composite_score >= 65:
        score_label = "양호"
    elif composite_score >= 45:
        score_label = "보통"
    else:
        score_label = "주의"

    return {
        "timing_score": composite_score,
        "timing_score_label": score_label,
        "return_score": return_score,
        "trough_score": trough_score,
        "break_even_score": break_even_score,
        "pre_buy_score": pre_buy_score,
    }


def _build_retro_sparkline(window_rows: List[DailyPrice], trade_price: Decimal) -> Dict:
    if not window_rows:
        return _empty_retro_sparkline()

    closes = [Decimal(str(row.close_price)) for row in window_rows]
    compare_values = closes + [trade_price]
    minimum = min(compare_values)
    maximum = max(compare_values)
    if minimum == maximum:
        maximum = minimum + Decimal("1")

    width = Decimal("140")
    height = Decimal("38")
    span = maximum - minimum

    def _x(index: int) -> str:
        if len(closes) == 1:
            return f"{(width / Decimal('2')):.2f}"
        return f"{((width * Decimal(index)) / Decimal(len(closes) - 1)):.2f}"

    def _y(value: Decimal) -> str:
        normalized = (value - minimum) / span
        y_value = height - (normalized * height)
        return f"{y_value:.2f}"

    def _return_from_price(close_price: Decimal) -> float | None:
        if trade_price <= 0:
            return None
        return round(float(((close_price - trade_price) / trade_price) * Decimal("100")), 2)

    points = " ".join(f"{_x(index)},{_y(close_price)}" for index, close_price in enumerate(closes))
    last_return = _return_from_price(closes[-1])
    return {
        "sparkline_available": True,
        "sparkline_points": points,
        "sparkline_baseline_y": _y(trade_price),
        "sparkline_min_display": _format_money_display(_round_int(minimum)),
        "sparkline_max_display": _format_money_display(_round_int(maximum)),
        "sparkline_last_display": _format_money_display(_round_int(closes[-1])),
        "sparkline_last_return_display": _format_percent_display(last_return),
        "sparkline_day_span": len(closes),
    }


def _build_retro_overview_chart(price_rows: List[DailyPrice], evaluations: List[Dict]) -> Dict:
    if not price_rows:
        return {
            "available": False,
            "polyline_points": "",
            "markers": [],
            "min_price_display": "-",
            "max_price_display": "-",
            "latest_close_display": "-",
            "start_date_display": "",
            "end_date_display": "",
        }

    closes = [Decimal(str(row.close_price)) for row in price_rows]
    marker_prices = [Decimal(str(row["unit_price"])) for row in evaluations]
    compare_values = closes + marker_prices
    minimum = min(compare_values)
    maximum = max(compare_values)
    if minimum == maximum:
        maximum = minimum + Decimal("1")

    width = Decimal("760")
    height = Decimal("180")
    span = maximum - minimum
    price_dates = [row.date for row in price_rows]

    def _x(index: int) -> str:
        if len(price_rows) == 1:
            return f"{(width / Decimal('2')):.2f}"
        return f"{((width * Decimal(index)) / Decimal(len(price_rows) - 1)):.2f}"

    def _y(value: Decimal) -> str:
        normalized = (value - minimum) / span
        y_value = height - (normalized * height)
        return f"{y_value:.2f}"

    markers = []
    for row in evaluations:
        trade_date = row["trade_date"]
        chart_index = bisect_left(price_dates, trade_date)
        if chart_index >= len(price_rows):
            continue
        marker_price = Decimal(str(row["unit_price"]))
        markers.append(
            {
                "x": _x(chart_index),
                "y": _y(marker_price),
                "color": row["sparkline_color"],
                "category": row["evaluation_category"],
                "label": row["evaluation_label"],
                "grade": row["evaluation_grade"],
                "traded_at": row["traded_at"],
                "entry_context": row["entry_context"],
                "return_20_display": row["return_20_display"],
                "unit_price_display": row["unit_price_display"],
            }
        )

    return {
        "available": True,
        "polyline_points": " ".join(
            f"{_x(index)},{_y(close_price)}" for index, close_price in enumerate(closes)
        ),
        "markers": markers,
        "min_price_display": _format_money_display(_round_int(minimum)),
        "max_price_display": _format_money_display(_round_int(maximum)),
        "latest_close_display": _format_money_display(_round_int(closes[-1])),
        "start_date_display": price_rows[0].date.isoformat(),
        "end_date_display": price_rows[-1].date.isoformat(),
    }


def _extract_retro_price_metrics(price_rows: List[DailyPrice], trade_date: date, trade_price: Decimal) -> Dict:
    if not price_rows:
        return {
            "available_days": 0,
            "pre_buy_return_5": None,
            "day_5_close": None,
            "day_20_close": None,
            "day_60_close": None,
            "return_5": None,
            "return_20": None,
            "return_60": None,
            "max_gain_20": None,
            "max_drawdown_20": None,
            "days_to_trough_20": None,
            "distance_to_trough_20": None,
            "days_to_break_even_20": None,
            "days_to_peak_20": None,
            "note": "DailyPrice 이력이 없어 회고 판단을 보류합니다.",
            "sparkline": _empty_retro_sparkline(),
        }

    price_dates = [row.date for row in price_rows]
    start_index = bisect_left(price_dates, trade_date)
    if start_index >= len(price_rows):
        return {
            "available_days": 0,
            "pre_buy_return_5": None,
            "day_5_close": None,
            "day_20_close": None,
            "day_60_close": None,
            "return_5": None,
            "return_20": None,
            "return_60": None,
            "max_gain_20": None,
            "max_drawdown_20": None,
            "days_to_trough_20": None,
            "distance_to_trough_20": None,
            "days_to_break_even_20": None,
            "days_to_peak_20": None,
            "note": "매수 이후 일봉 데이터가 없어 회고 판단을 보류합니다.",
            "sparkline": _empty_retro_sparkline(),
        }

    window = price_rows[start_index:]
    available_days = len(window)
    pre_window = price_rows[max(0, start_index - 5):start_index]

    def _close_after(trading_days: int) -> int | None:
        offset = trading_days - 1
        if offset < 0 or offset >= len(window):
            return None
        return _round_int(window[offset].close_price)

    def _return_from_price(close_price: Decimal | int | None) -> float | None:
        if close_price is None or trade_price <= 0:
            return None
        close_decimal = Decimal(str(close_price))
        return round(float(((close_decimal - trade_price) / trade_price) * Decimal("100")), 2)

    window_20 = window[:20]
    if window_20:
        max_gain_20 = max(_return_from_price(row.close_price) for row in window_20)
        max_drawdown_20 = min(_return_from_price(row.close_price) for row in window_20)
        trough_index = min(range(len(window_20)), key=lambda index: Decimal(str(window_20[index].close_price)))
        trough_close = Decimal(str(window_20[trough_index].close_price))
        days_to_trough_20 = trough_index + 1
        distance_to_trough_20 = round(float(((trade_price - trough_close) / trade_price) * Decimal("100")), 2)
        peak_index = max(range(len(window_20)), key=lambda index: Decimal(str(window_20[index].close_price)))
        days_to_peak_20 = peak_index + 1
        days_to_break_even_20 = next(
            (
                index
                for index, row in enumerate(window_20[1:], start=2)
                if Decimal(str(row.close_price)) >= trade_price
            ),
            None,
        )
    else:
        max_gain_20 = None
        max_drawdown_20 = None
        days_to_trough_20 = None
        distance_to_trough_20 = None
        days_to_break_even_20 = None
        days_to_peak_20 = None

    note = ""
    if available_days < 5:
        note = f"매수 이후 가격 이력이 {available_days}거래일뿐이라 판단을 보류합니다."
    elif available_days < 20:
        note = f"매수 이후 가격 이력이 {available_days}거래일뿐이라 20거래일 이상 평가는 제한적입니다."
    elif available_days < 60:
        note = f"매수 이후 가격 이력이 {available_days}거래일이라 60거래일 평가는 제한적입니다."

    day_5_close = _close_after(5)
    day_20_close = _close_after(20)
    day_60_close = _close_after(60)
    pre_buy_return_5 = None
    if len(pre_window) >= 1:
        baseline_price = Decimal(str(pre_window[0].close_price))
        if baseline_price > 0:
            pre_buy_return_5 = round(float(((trade_price - baseline_price) / baseline_price) * Decimal("100")), 2)
    return {
        "available_days": available_days,
        "pre_buy_return_5": pre_buy_return_5,
        "day_5_close": day_5_close,
        "day_20_close": day_20_close,
        "day_60_close": day_60_close,
        "return_5": _return_from_price(day_5_close),
        "return_20": _return_from_price(day_20_close),
        "return_60": _return_from_price(day_60_close),
        "max_gain_20": max_gain_20,
        "max_drawdown_20": max_drawdown_20,
        "days_to_trough_20": days_to_trough_20,
        "distance_to_trough_20": distance_to_trough_20,
        "days_to_break_even_20": days_to_break_even_20,
        "days_to_peak_20": days_to_peak_20,
        "note": note,
        "sparkline": _build_retro_sparkline(window_20, trade_price),
    }


def _classify_retro_buy(metrics: Dict) -> Dict:
    available_days = metrics["available_days"]
    return_20 = metrics["return_20"]
    return_60 = metrics["return_60"]
    max_gain_20 = metrics["max_gain_20"]
    max_drawdown_20 = metrics["max_drawdown_20"]

    if available_days < 5:
        return {
            "category": "pending",
            "label": "판단 보류",
            "grade": "N/A",
            "reason_key": "insufficient_data",
            "reason_label": "가격 이력 부족",
            "badge_class": "bg-secondary",
            "summary": metrics["note"] or "가격 이력이 부족해 판단을 보류합니다.",
        }

    good_reason_key = "quick_rebound"
    good_reason_label = "단기 반등 우수"
    if return_20 is not None and return_20 >= 5:
        good_reason_key = "strong_20d_return"
        good_reason_label = "20거래일 강한 반등"
    elif return_60 is not None and return_60 >= 8:
        good_reason_key = "strong_60d_follow_through"
        good_reason_label = "60거래일 추세 개선"

    if (
        (return_20 is not None and return_20 >= 5)
        or (return_60 is not None and return_60 >= 8)
        or (
            max_gain_20 is not None
            and max_gain_20 >= 10
            and (max_drawdown_20 is None or max_drawdown_20 > -6)
        )
    ):
        return {
            "category": "good",
            "label": "잘한 매수",
            "grade": "A",
            "reason_key": good_reason_key,
            "reason_label": good_reason_label,
            "badge_class": "bg-success",
            "summary": (
                f"20거래일 후 {_format_percent_display(return_20)}였고 "
                f"20일 내 최대 {_format_percent_display(max_gain_20)} 반등이 나와 타이밍이 좋았습니다."
            ),
        }

    bad_reason_key = "deep_drawdown"
    bad_reason_label = "매수 후 낙폭 확대"
    if return_20 is not None and return_20 <= -8:
        bad_reason_key = "weak_20d_follow_through"
        bad_reason_label = "20거래일 약세 지속"

    if (
        (return_20 is not None and return_20 <= -8)
        or (
            max_drawdown_20 is not None
            and max_drawdown_20 <= -12
            and (return_20 is None or return_20 < 0)
        )
    ):
        return {
            "category": "bad",
            "label": "아쉬운 매수",
            "grade": "D",
            "reason_key": bad_reason_key,
            "reason_label": bad_reason_label,
            "badge_class": "bg-danger",
            "summary": (
                f"20거래일 후 {_format_percent_display(return_20)}였고 "
                f"20일 내 최대 낙폭이 {_format_percent_display(max_drawdown_20)}까지 이어져 타이밍이 좋지 않았습니다."
            ),
        }

    return {
        "category": "neutral",
        "label": "보통 매수",
        "grade": "B",
        "reason_key": "mixed_follow_through",
        "reason_label": "성과 혼조",
        "badge_class": "bg-warning text-dark",
        "summary": (
            f"20거래일 후 {_format_percent_display(return_20)}로 "
            "이후 성과가 엇갈려 명확한 우위가 없었습니다."
        ),
    }


def build_historical_buy_timing_analysis(stock_name: str) -> Dict:
    selected_name = stock_name.strip()
    transactions = _ordered_transactions(Transaction.objects.filter(stock_name=selected_name))
    resolution = resolve_stock_from_legacy_name(selected_name)
    price_rows = []
    if resolution.stock is not None:
        price_rows = list(DailyPrice.objects.filter(stock=resolution.stock).order_by("date"))

    counts = {
        "good": 0,
        "neutral": 0,
        "bad": 0,
        "pending": 0,
    }
    evaluations = []
    state = {"qty": Decimal("0"), "cost": Decimal("0")}

    for tx in transactions:
        quantity = Decimal(str(tx.quantity))
        unit_price = Decimal(str(tx.unit_price))

        if tx.trade_type == "매수":
            trade_date = _transaction_to_date(tx)
            pre_quantity = state["qty"]
            pre_average_price = (state["cost"] / state["qty"]) if state["qty"] > 0 else None
            entry_context = _build_entry_context(pre_quantity, pre_average_price, unit_price)

            state["qty"] += quantity
            state["cost"] += quantity * unit_price
            post_average_price = state["cost"] / state["qty"] if state["qty"] > 0 else unit_price
            pre_avg_gap_pct = None
            if pre_average_price is not None and pre_average_price > 0:
                pre_avg_gap_pct = round(float(((unit_price - pre_average_price) / pre_average_price) * Decimal("100")), 2)

            metrics = _extract_retro_price_metrics(price_rows, trade_date, unit_price)
            classification = _classify_retro_buy(metrics)
            timing_score = _calculate_retro_timing_score(metrics, metrics["pre_buy_return_5"])
            counts[classification["category"]] += 1
            sparkline_color = {
                "good": "#198754",
                "neutral": "#f0ad4e",
                "bad": "#dc3545",
                "pending": "#6c757d",
            }[classification["category"]]

            evaluations.append(
                {
                    "trade_id": tx.id,
                    "trade_date": trade_date,
                    "traded_at": _build_trade_timestamp(tx),
                    "entry_context": entry_context,
                    "quantity": int(quantity),
                    "unit_price": tx.unit_price,
                    "unit_price_display": _format_money_display(tx.unit_price),
                    "total_amount_display": _format_money_display(tx.total_amount),
                    "pre_quantity": int(pre_quantity),
                    "pre_avg_gap_pct": pre_avg_gap_pct,
                    "pre_avg_gap_display": _format_percent_display(pre_avg_gap_pct),
                    "pre_buy_return_5": metrics["pre_buy_return_5"],
                    "pre_buy_return_5_display": _format_percent_display(metrics["pre_buy_return_5"]),
                    "pre_avg_price_display": _format_money_display(
                        None if pre_average_price is None else _round_int(_quantize_money(pre_average_price))
                    ),
                    "post_quantity": int(state["qty"]),
                    "post_avg_price_display": _format_money_display(_round_int(_quantize_money(post_average_price))),
                    "day_5_close_display": _format_money_display(metrics["day_5_close"]),
                    "day_20_close_display": _format_money_display(metrics["day_20_close"]),
                    "day_60_close_display": _format_money_display(metrics["day_60_close"]),
                    "return_5": metrics["return_5"],
                    "return_20": metrics["return_20"],
                    "return_60": metrics["return_60"],
                    "return_5_display": _format_percent_display(metrics["return_5"]),
                    "return_20_display": _format_percent_display(metrics["return_20"]),
                    "return_60_display": _format_percent_display(metrics["return_60"]),
                    "max_gain_20": metrics["max_gain_20"],
                    "max_drawdown_20": metrics["max_drawdown_20"],
                    "days_to_trough_20": metrics["days_to_trough_20"],
                    "distance_to_trough_20": metrics["distance_to_trough_20"],
                    "days_to_break_even_20": metrics["days_to_break_even_20"],
                    "days_to_peak_20": metrics["days_to_peak_20"],
                    "max_gain_20_display": _format_percent_display(metrics["max_gain_20"]),
                    "max_drawdown_20_display": _format_percent_display(metrics["max_drawdown_20"]),
                    "days_to_trough_20_display": _format_days_display(metrics["days_to_trough_20"]),
                    "distance_to_trough_20_display": _format_percent_display(metrics["distance_to_trough_20"]),
                    "days_to_break_even_20_display": _format_days_display(metrics["days_to_break_even_20"]),
                    "days_to_peak_20_display": _format_days_display(metrics["days_to_peak_20"]),
                    "timing_score": timing_score["timing_score"],
                    "timing_score_display": f"{timing_score['timing_score']}점",
                    "timing_score_label": timing_score["timing_score_label"],
                    "timing_component_return_score": timing_score["return_score"],
                    "timing_component_trough_score": timing_score["trough_score"],
                    "timing_component_break_even_score": timing_score["break_even_score"],
                    "timing_component_pre_buy_score": timing_score["pre_buy_score"],
                    "evaluation_grade": classification["grade"],
                    "evaluation_category": classification["category"],
                    "evaluation_label": classification["label"],
                    "evaluation_reason_key": classification["reason_key"],
                    "evaluation_reason_label": classification["reason_label"],
                    "evaluation_summary": classification["summary"],
                    "badge_class": classification["badge_class"],
                    "data_note": metrics["note"],
                    "sparkline_available": metrics["sparkline"]["sparkline_available"],
                    "sparkline_points": metrics["sparkline"]["sparkline_points"],
                    "sparkline_baseline_y": metrics["sparkline"]["sparkline_baseline_y"],
                    "sparkline_min_display": metrics["sparkline"]["sparkline_min_display"],
                    "sparkline_max_display": metrics["sparkline"]["sparkline_max_display"],
                    "sparkline_last_display": metrics["sparkline"]["sparkline_last_display"],
                    "sparkline_last_return_display": metrics["sparkline"]["sparkline_last_return_display"],
                    "sparkline_day_span": metrics["sparkline"]["sparkline_day_span"],
                    "sparkline_color": sparkline_color,
                }
            )
            continue

        if tx.trade_type != "매도":
            continue

        if state["qty"] <= 0:
            continue

        sellable_quantity = min(quantity, state["qty"])
        average_price = state["cost"] / state["qty"] if state["qty"] > 0 else Decimal("0")
        state["qty"] -= sellable_quantity
        state["cost"] -= average_price * sellable_quantity
        if state["qty"] <= 0:
            state["qty"] = Decimal("0")
            state["cost"] = Decimal("0")

    return {
        "stock_name": selected_name,
        "stock_code": resolution.stock.code if resolution.stock else "",
        "stock_market": resolution.stock.market if resolution.stock else "",
        "price_row_count": len(price_rows),
        "mapping_warning": resolution.warning,
        "basis_text": "거래일 기준 5/20/60일 후 종가와 20거래일 내 최대 상승/낙폭으로 회고 평가합니다.",
        "good_count": counts["good"],
        "neutral_count": counts["neutral"],
        "bad_count": counts["bad"],
        "pending_count": counts["pending"],
        "overview_chart": _build_retro_overview_chart(price_rows, evaluations),
        "evaluations": evaluations,
    }


def build_historical_buy_timing_rankings(stock_names: Iterable[str]) -> List[Dict]:
    rankings = []
    unique_names = sorted({name.strip() for name in stock_names if name and name.strip()})

    for stock_name in unique_names:
        retrospective = build_historical_buy_timing_analysis(stock_name)
        evaluations = retrospective["evaluations"]
        if not evaluations:
            continue

        scored_evaluations = [
            row for row in evaluations
            if row["evaluation_category"] != "pending" and row["timing_score"] is not None
        ]
        return_20_values = [
            row["return_20"] for row in scored_evaluations
            if row["return_20"] is not None
        ]
        break_even_values = [
            row["days_to_break_even_20"] for row in scored_evaluations
            if row["days_to_break_even_20"] is not None
        ]
        trough_gap_values = [
            row["distance_to_trough_20"] for row in scored_evaluations
            if row["distance_to_trough_20"] is not None
        ]
        timing_scores = [row["timing_score"] for row in scored_evaluations]
        average_timing_score = round(mean(timing_scores), 1) if scored_evaluations else None
        average_return_20 = round(mean(return_20_values), 2) if return_20_values else None
        average_break_even_days = round(mean(break_even_values), 1) if break_even_values else None
        average_trough_gap = round(mean(trough_gap_values), 2) if trough_gap_values else None
        timing_score_stddev = round(pstdev(timing_scores), 1) if len(timing_scores) >= 2 else None
        scored_buy_count = len(scored_evaluations)
        good_count = retrospective["good_count"]
        bad_count = retrospective["bad_count"]
        pending_count = retrospective["pending_count"]
        good_ratio = round((good_count / scored_buy_count) * 100, 1) if scored_buy_count else None

        if scored_buy_count >= 4 and pending_count == 0:
            confidence_label = "높음"
            confidence_badge_class = "bg-success-subtle text-success"
            confidence_note = "평가 완료 매수가 충분해 평균 점수 해석 신뢰도가 높습니다."
        elif scored_buy_count >= 2 and pending_count <= 1:
            confidence_label = "보통"
            confidence_badge_class = "bg-warning-subtle text-warning-emphasis"
            confidence_note = "표본은 적당하지만, 종목별 맥락을 함께 보는 편이 좋습니다."
        else:
            confidence_label = "낮음"
            confidence_badge_class = "bg-secondary-subtle text-secondary"
            confidence_note = "평가 완료 건수가 적거나 판단 보류가 많아 평균 점수 해석에 주의가 필요합니다."

        if timing_score_stddev is None:
            consistency_label = "판단 보류"
            consistency_badge_class = "bg-secondary-subtle text-secondary"
            consistency_note = "비교할 평가 점수 표본이 아직 충분하지 않습니다."
        elif timing_score_stddev <= 10:
            consistency_label = "높음"
            consistency_badge_class = "bg-success-subtle text-success"
            consistency_note = "매수별 점수 편차가 작아 실행 품질이 비교적 안정적이었습니다."
        elif timing_score_stddev <= 22:
            consistency_label = "보통"
            consistency_badge_class = "bg-warning-subtle text-warning-emphasis"
            consistency_note = "매수별 성과 차이가 있어 구간별 복기가 필요합니다."
        else:
            consistency_label = "낮음"
            consistency_badge_class = "bg-danger-subtle text-danger"
            consistency_note = "매수별 결과 편차가 커서 평균 점수만으로 해석하면 왜곡될 수 있습니다."

        if average_timing_score is None:
            score_bar_width = 0
            score_bar_class = "bg-secondary"
        elif average_timing_score >= 80:
            score_bar_width = max(8, int(round(average_timing_score)))
            score_bar_class = "bg-success"
        elif average_timing_score >= 65:
            score_bar_width = max(8, int(round(average_timing_score)))
            score_bar_class = "bg-info"
        elif average_timing_score >= 45:
            score_bar_width = max(8, int(round(average_timing_score)))
            score_bar_class = "bg-warning"
        else:
            score_bar_width = max(8, int(round(average_timing_score)))
            score_bar_class = "bg-danger"

        rankings.append(
            {
                "stock_name": retrospective["stock_name"],
                "stock_code": retrospective["stock_code"],
                "stock_market": retrospective["stock_market"],
                "buy_count": len(evaluations),
                "scored_buy_count": scored_buy_count,
                "good_count": good_count,
                "neutral_count": retrospective["neutral_count"],
                "bad_count": bad_count,
                "pending_count": pending_count,
                "good_ratio": good_ratio,
                "good_ratio_display": _format_percent_display(good_ratio),
                "confidence_label": confidence_label,
                "confidence_badge_class": confidence_badge_class,
                "confidence_note": confidence_note,
                "consistency_label": consistency_label,
                "consistency_badge_class": consistency_badge_class,
                "consistency_note": consistency_note,
                "average_timing_score": average_timing_score,
                "average_timing_score_display": "-" if average_timing_score is None else f"{average_timing_score:.1f}점",
                "timing_score_stddev": timing_score_stddev,
                "timing_score_stddev_display": "-" if timing_score_stddev is None else f"{timing_score_stddev:.1f}점",
                "average_return_20": average_return_20,
                "average_return_20_display": _format_percent_display(average_return_20),
                "average_break_even_days": average_break_even_days,
                "average_break_even_days_display": _format_days_display(
                    None if average_break_even_days is None else int(round(average_break_even_days))
                ),
                "average_trough_gap": average_trough_gap,
                "average_trough_gap_display": _format_percent_display(average_trough_gap),
                "score_bar_width": score_bar_width,
                "score_bar_class": score_bar_class,
            }
        )

    rankings.sort(
        key=lambda row: (
            row["average_timing_score"] is None,
            -(row["average_timing_score"] if row["average_timing_score"] is not None else -1),
            -row["good_count"],
            row["bad_count"],
            row["stock_name"],
        )
    )
    return rankings


def build_holdings_analysis() -> List[Dict]:
    positions, _ = aggregate_all_transactions_by_stock()
    result = []
    for position in positions:
        if position.quantity <= 0:
            continue
        avg_price = _round_int(position.average_price)
        snapshot = get_price_snapshot(position.stock_name)
        current_price = snapshot.current_price or 0
        market_value = current_price * position.quantity
        book_value = avg_price * position.quantity
        profit = market_value - book_value
        profit_rate = round((profit / book_value) * 100, 2) if book_value else 0
        result.append({
            'stock_name': position.stock_name,
            'ticker': snapshot.ticker,
            'quantity': position.quantity,
            'avg_price': avg_price,
            'current_price': current_price,
            'market_value': market_value,
            'book_value': book_value,
            'profit': profit,
            'profit_rate': profit_rate,
            'price_error': snapshot.error,
        })
    return result


def build_realized_profit_analysis() -> Dict:
    positions: Dict[str, Dict[str, Decimal]] = defaultdict(lambda: {'qty': Decimal('0'), 'cost': Decimal('0')})
    realized_rows: List[RealizedTrade] = []
    summary = defaultdict(lambda: {'sold_qty': 0, 'proceeds': 0, 'cost': 0, 'profit': 0})
    warnings: List[str] = []

    for tx in Transaction.objects.all().order_by('year', 'month', 'day', 'hour', 'minute', 'id'):
        state = positions[tx.stock_name]
        qty = Decimal(str(tx.quantity))
        unit_price = Decimal(str(tx.unit_price))

        if tx.trade_type == '매수':
            state['qty'] += qty
            state['cost'] += qty * unit_price
            continue

        if tx.trade_type != '매도':
            continue

        if state['qty'] <= 0:
            warnings.append(f'{tx.stock_name} {tx.year}-{tx.month:02d}-{tx.day:02d} {tx.hour:02d}:{tx.minute:02d} 매도는 보유수량이 없어 실현손익 계산에서 제외했습니다.')
            continue

        sellable_qty = min(qty, state['qty'])
        avg_buy_price = state['cost'] / state['qty'] if state['qty'] > 0 else Decimal('0')
        realized_cost = avg_buy_price * sellable_qty
        proceeds = unit_price * sellable_qty
        profit = proceeds - realized_cost
        profit_rate = float((profit / realized_cost) * Decimal('100')) if realized_cost > 0 else 0.0

        state['qty'] -= sellable_qty
        state['cost'] -= realized_cost
        if state['qty'] <= 0:
            state['qty'] = Decimal('0')
            state['cost'] = Decimal('0')

        sold_at = f'{tx.year}-{tx.month:02d}-{tx.day:02d} {tx.hour:02d}:{tx.minute:02d}'
        note = ''
        if qty > sellable_qty:
            note = f'요청 매도 {int(qty)}주 중 {int(sellable_qty)}주만 계산'
            warnings.append(f'{tx.stock_name} {sold_at} 매도 {int(qty)}주 중 보유 {int(sellable_qty)}주만 실현손익에 반영했습니다.')

        row = RealizedTrade(
            stock_name=tx.stock_name,
            sold_qty=int(sellable_qty),
            sell_price=tx.unit_price,
            avg_buy_price=_round_int(avg_buy_price),
            proceeds=_round_int(proceeds),
            cost=_round_int(realized_cost),
            profit=_round_int(profit),
            profit_rate=round(profit_rate, 2),
            sold_at=sold_at,
            note=note,
        )
        realized_rows.append(row)

        item = summary[tx.stock_name]
        item['sold_qty'] += row.sold_qty
        item['proceeds'] += row.proceeds
        item['cost'] += row.cost
        item['profit'] += row.profit

    summary_rows = []
    for name, item in sorted(summary.items(), key=lambda kv: (-kv[1]['profit'], kv[0])):
        profit_rate = round((item['profit'] / item['cost']) * 100, 2) if item['cost'] else 0
        summary_rows.append({
            'stock_name': name,
            'sold_qty': item['sold_qty'],
            'proceeds': item['proceeds'],
            'cost': item['cost'],
            'profit': item['profit'],
            'profit_rate': profit_rate,
        })

    total_cost = sum(row['cost'] for row in summary_rows)
    total_profit = sum(row['profit'] for row in summary_rows)
    total_proceeds = sum(row['proceeds'] for row in summary_rows)
    return {
        'rows': realized_rows,
        'summary_rows': summary_rows,
        'total': {
            'sold_qty': sum(row['sold_qty'] for row in summary_rows),
            'proceeds': total_proceeds,
            'cost': total_cost,
            'profit': total_profit,
            'profit_rate': round((total_profit / total_cost) * 100, 2) if total_cost else 0,
        },
        'warnings': warnings,
    }
