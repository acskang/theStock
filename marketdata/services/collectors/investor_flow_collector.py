from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass, field
from datetime import timedelta
import logging

import pandas as pd
from django.utils import timezone

from marketdata.models import InvestorFlow, StockDataCollectionStatus
from marketdata.services.collection_status_service import record_collection_status
from marketdata.services.collectors.history_utils import normalize_date_value
from stocks.models import Stock

logger = logging.getLogger(__name__)


INVESTOR_FLOW_SOURCE = "pykrx_auto"


@dataclass
class InvestorFlowCollectionReport:
    target_count: int = 0
    created_rows: int = 0
    updated_rows: int = 0
    skipped_targets: int = 0
    empty_targets: int = 0
    error_targets: int = 0
    warnings: list[str] = field(default_factory=list)


def _get_target_stocks(*, stock_code=None, all_stocks=False):
    if stock_code:
        return Stock.objects.filter(code=stock_code)
    if all_stocks:
        return Stock.objects.filter(is_active=True).order_by("code")
    return Stock.objects.filter(holdings__is_active=True).distinct().order_by("code")


def _load_pykrx_stock_module():
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        from pykrx import stock as pykrx_stock

    return pykrx_stock


def _fetch_investor_flow_frame(stock_code: str, fromdate: str, todate: str):
    pykrx_stock = _load_pykrx_stock_module()
    return pykrx_stock.get_market_trading_value_by_date(
        fromdate,
        todate,
        stock_code,
        on="순매수",
        freq="d",
    )


def _parse_int_value(value) -> int:
    if pd.isna(value):
        return 0
    normalized = str(value).strip().replace(",", "")
    if normalized == "":
        return 0
    return int(float(normalized))


def _get_row_value(row, *column_names) -> int:
    for column_name in column_names:
        if column_name in row.index:
            return _parse_int_value(row[column_name])
    return 0


def _build_investor_flow_rows(frame):
    if frame is None or frame.empty:
        return []

    normalized = frame.reset_index()
    date_column = "날짜" if "날짜" in normalized.columns else normalized.columns[0]
    rows = []
    for _, row in normalized.iterrows():
        rows.append(
            {
                "date": normalize_date_value(row[date_column]),
                "foreign_net_buy": _get_row_value(row, "외국인합계", "외국인"),
                "institution_net_buy": _get_row_value(row, "기관합계", "기관"),
                "individual_net_buy": _get_row_value(row, "개인"),
                "program_net_buy": 0,
            }
        )
    return rows


def collect_investor_flows(*, stock_code=None, days=60, all_stocks=False, dry_run=False):
    report = InvestorFlowCollectionReport()
    stocks = list(_get_target_stocks(stock_code=stock_code, all_stocks=all_stocks))
    report.target_count = len(stocks)

    from_date = (timezone.localdate() - timedelta(days=max(days - 1, 0))).strftime("%Y%m%d")
    to_date = timezone.localdate().strftime("%Y%m%d")

    for stock in stocks:
        try:
            frame = _fetch_investor_flow_frame(stock.code, from_date, to_date)
            rows = _build_investor_flow_rows(frame)
        except Exception as exc:
            report.error_targets += 1
            message = f"{stock.code} {stock.name}: 수급 자동 수집에 실패했습니다. ({exc})"
            report.warnings.append(message)
            logger.error(
                "Investor flow collection failed",
                extra={
                    "event": "investor_flow_collect_error",
                    "stock_code": stock.code,
                    "source": INVESTOR_FLOW_SOURCE,
                    "error_type": exc.__class__.__name__,
                },
            )
            if not dry_run:
                record_collection_status(
                    stock=stock,
                    data_type=StockDataCollectionStatus.TYPE_INVESTOR_FLOW,
                    status=StockDataCollectionStatus.STATUS_ERROR,
                    source=INVESTOR_FLOW_SOURCE,
                    row_count=0,
                    message=str(exc),
                )
            continue

        if not rows:
            report.empty_targets += 1
            report.warnings.append(f"{stock.code} {stock.name}: 수급 데이터를 찾지 못했습니다.")
            logger.warning(
                "Investor flow collection returned no rows",
                extra={
                    "event": "investor_flow_collect_empty",
                    "stock_code": stock.code,
                    "source": INVESTOR_FLOW_SOURCE,
                },
            )
            if not dry_run:
                record_collection_status(
                    stock=stock,
                    data_type=StockDataCollectionStatus.TYPE_INVESTOR_FLOW,
                    status=StockDataCollectionStatus.STATUS_EMPTY,
                    source=INVESTOR_FLOW_SOURCE,
                    row_count=0,
                    message="수집 결과가 비어 있습니다.",
                )
            continue

        for row in rows:
            if dry_run:
                exists = InvestorFlow.objects.filter(stock=stock, date=row["date"]).exists()
                if exists:
                    report.updated_rows += 1
                else:
                    report.created_rows += 1
                continue

            _, created = InvestorFlow.objects.update_or_create(
                stock=stock,
                date=row["date"],
                defaults={
                    "foreign_net_buy": row["foreign_net_buy"],
                    "institution_net_buy": row["institution_net_buy"],
                    "individual_net_buy": row["individual_net_buy"],
                    "program_net_buy": row["program_net_buy"],
                },
            )
            if created:
                report.created_rows += 1
            else:
                report.updated_rows += 1

        if not dry_run:
            record_collection_status(
                stock=stock,
                data_type=StockDataCollectionStatus.TYPE_INVESTOR_FLOW,
                status=StockDataCollectionStatus.STATUS_SUCCESS,
                source=INVESTOR_FLOW_SOURCE,
                row_count=len(rows),
                message="",
            )

    return report
