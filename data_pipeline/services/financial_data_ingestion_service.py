from __future__ import annotations

import logging
import time

from data_pipeline.dataclasses import IngestionReport
from data_pipeline.models import DataIngestionLog, DataProviderStatus
from data_pipeline.providers import get_provider
from data_pipeline.services import resolve_target_stocks
from data_pipeline.services.ingestion_log_service import finish_ingestion_log, start_ingestion_log, update_provider_status
from data_pipeline.validators import validate_financial_period
from marketdata.models import StockDataCollectionStatus
from marketdata.services.collection_status_service import record_collection_status
from stocks.models import FinancialSnapshot

logger = logging.getLogger(__name__)


def ingest_financial_data(
    *,
    provider_name: str | None = None,
    stock_codes=None,
    years: int = 2,
    all_stocks: bool = False,
    dry_run: bool = False,
):
    provider = get_provider(provider_name)
    target_stocks = [
        stock for stock in resolve_target_stocks(stock_codes=stock_codes, all_stocks=all_stocks)
        if stock.market not in {stock.MARKET_ETF, stock.MARKET_ETN}
    ]
    started_at = time.monotonic()
    log_entry = start_ingestion_log(
        job_name="ingest_financial_data",
        provider=provider.provider_name,
        target_type=DataIngestionLog.TARGET_FINANCIAL,
        target_code=",".join(stock_codes or []),
        total_count=len(target_stocks),
    )
    report = IngestionReport(
        job_name="ingest_financial_data",
        provider=provider.provider_name,
        target_type=DataIngestionLog.TARGET_FINANCIAL,
        target_count=len(target_stocks),
    )
    try:
        for stock in target_stocks:
            try:
                rows = provider.get_financial_snapshot_rows(stock, years)
                if not rows:
                    report.skipped_count += 1
                    if not dry_run:
                        record_collection_status(
                            stock=stock,
                            data_type=StockDataCollectionStatus.TYPE_FINANCIAL_SNAPSHOT,
                            status=StockDataCollectionStatus.STATUS_EMPTY,
                            source=provider.provider_name,
                            row_count=0,
                            message="No financial snapshot rows returned.",
                        )
                    continue
                for row in rows:
                    validate_financial_period(row.period_type)
                    if not dry_run:
                        _, created = FinancialSnapshot.objects.update_or_create(
                            stock=stock,
                            fiscal_year=row.fiscal_year,
                            period_type=row.period_type,
                            defaults={
                                "reported_date": row.reported_date,
                                "revenue": row.revenue,
                                "operating_profit": row.operating_profit,
                                "net_income": row.net_income,
                                "operating_cash_flow": row.operating_cash_flow,
                                "debt_ratio": row.debt_ratio,
                                "current_ratio": row.current_ratio,
                                "equity": row.equity,
                                "capital_impairment_rate": row.capital_impairment_rate,
                                "roe": row.roe,
                                "per": row.per,
                                "pbr": row.pbr,
                                "source": row.source,
                                "source_key": row.source_key or None,
                            },
                        )
                        if created:
                            report.created_count += 1
                        else:
                            report.updated_count += 1
                report.success_count += 1
                if not dry_run:
                    record_collection_status(
                        stock=stock,
                        data_type=StockDataCollectionStatus.TYPE_FINANCIAL_SNAPSHOT,
                        status=StockDataCollectionStatus.STATUS_SUCCESS,
                        source=provider.provider_name,
                        row_count=len(rows),
                    )
            except Exception as exc:
                logger.exception("Financial snapshot ingestion failed for %s", stock.code)
                report.failed_count += 1
                report.warnings.append(f"{stock.code}: {exc}")
                if not dry_run:
                    record_collection_status(
                        stock=stock,
                        data_type=StockDataCollectionStatus.TYPE_FINANCIAL_SNAPSHOT,
                        status=StockDataCollectionStatus.STATUS_ERROR,
                        source=provider.provider_name,
                        row_count=0,
                        message=str(exc),
                    )
        if report.failed_count and report.success_count:
            report.status = DataIngestionLog.STATUS_PARTIAL
        elif report.failed_count:
            report.status = DataIngestionLog.STATUS_FAILED
            report.error_message = "Financial data ingestion failed."
    except Exception as exc:
        report.status = DataIngestionLog.STATUS_FAILED
        report.error_message = str(exc)
        logger.exception("Financial data ingestion crashed")
    latency_ms = int((time.monotonic() - started_at) * 1000)
    finish_ingestion_log(
        log_entry,
        status=report.status,
        success_count=report.success_count,
        failed_count=report.failed_count,
        skipped_count=report.skipped_count,
        total_count=report.target_count,
        error_message=report.error_message,
        details={
            "years": years,
            "created_count": report.created_count,
            "updated_count": report.updated_count,
            "warnings": report.warnings,
            "dry_run": dry_run,
        },
    )
    update_provider_status(
        provider=provider.provider_name,
        data_type=DataProviderStatus.TYPE_FINANCIAL,
        status=report.status,
        latency_ms=latency_ms,
        error_message=report.error_message,
    )
    return report
