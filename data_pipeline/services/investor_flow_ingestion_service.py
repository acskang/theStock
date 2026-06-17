from __future__ import annotations

import logging
import time

from data_pipeline.dataclasses import IngestionReport
from data_pipeline.models import DataIngestionLog, DataProviderStatus
from data_pipeline.providers import get_provider
from data_pipeline.services import resolve_target_stocks
from data_pipeline.services.ingestion_log_service import finish_ingestion_log, start_ingestion_log, update_provider_status
from marketdata.models import InvestorFlow, StockDataCollectionStatus
from marketdata.services.collection_status_service import record_collection_status

logger = logging.getLogger(__name__)


def ingest_investor_flows(
    *,
    provider_name: str | None = None,
    stock_codes=None,
    days: int = 60,
    all_stocks: bool = False,
    dry_run: bool = False,
):
    provider = get_provider(provider_name)
    target_stocks = resolve_target_stocks(stock_codes=stock_codes, all_stocks=all_stocks)
    started_at = time.monotonic()
    log_entry = start_ingestion_log(
        job_name="ingest_investor_flows",
        provider=provider.provider_name,
        target_type=DataIngestionLog.TARGET_FLOW,
        target_code=",".join(stock_codes or []),
        total_count=len(target_stocks),
    )
    report = IngestionReport(
        job_name="ingest_investor_flows",
        provider=provider.provider_name,
        target_type=DataIngestionLog.TARGET_FLOW,
        target_count=len(target_stocks),
    )
    try:
        for stock in target_stocks:
            try:
                rows = provider.get_investor_flow_rows(stock, days)
                if not rows:
                    report.skipped_count += 1
                    if not dry_run:
                        record_collection_status(
                            stock=stock,
                            data_type=StockDataCollectionStatus.TYPE_INVESTOR_FLOW,
                            status=StockDataCollectionStatus.STATUS_EMPTY,
                            source=provider.provider_name,
                            row_count=0,
                            message="No investor flow rows returned.",
                        )
                    continue
                for row in rows:
                    if not dry_run:
                        _, created = InvestorFlow.objects.update_or_create(
                            stock=stock,
                            date=row.date,
                            defaults={
                                "foreign_net_buy": row.foreign_net_buy,
                                "institution_net_buy": row.institution_net_buy,
                                "individual_net_buy": row.individual_net_buy,
                                "program_net_buy": row.program_net_buy,
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
                        data_type=StockDataCollectionStatus.TYPE_INVESTOR_FLOW,
                        status=StockDataCollectionStatus.STATUS_SUCCESS,
                        source=provider.provider_name,
                        row_count=len(rows),
                    )
            except Exception as exc:
                logger.exception("Investor flow ingestion failed for %s", stock.code)
                report.failed_count += 1
                report.warnings.append(f"{stock.code}: {exc}")
                if not dry_run:
                    record_collection_status(
                        stock=stock,
                        data_type=StockDataCollectionStatus.TYPE_INVESTOR_FLOW,
                        status=StockDataCollectionStatus.STATUS_ERROR,
                        source=provider.provider_name,
                        row_count=0,
                        message=str(exc),
                    )
        if report.failed_count and report.success_count:
            report.status = DataIngestionLog.STATUS_PARTIAL
        elif report.failed_count:
            report.status = DataIngestionLog.STATUS_FAILED
            report.error_message = "Investor flow ingestion failed."
    except Exception as exc:
        report.status = DataIngestionLog.STATUS_FAILED
        report.error_message = str(exc)
        logger.exception("Investor flow ingestion crashed")
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
            "days": days,
            "created_count": report.created_count,
            "updated_count": report.updated_count,
            "warnings": report.warnings,
            "dry_run": dry_run,
        },
    )
    update_provider_status(
        provider=provider.provider_name,
        data_type=DataProviderStatus.TYPE_FLOW,
        status=report.status,
        latency_ms=latency_ms,
        error_message=report.error_message,
    )
    return report
