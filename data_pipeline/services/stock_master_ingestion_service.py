from __future__ import annotations

import logging
import time

from data_pipeline.dataclasses import IngestionReport
from data_pipeline.models import DataIngestionLog, DataProviderStatus
from data_pipeline.providers import get_provider
from data_pipeline.services.ingestion_log_service import finish_ingestion_log, start_ingestion_log, update_provider_status
from data_pipeline.validators import validate_market, validate_stock_code
from stocks.models import Stock

logger = logging.getLogger(__name__)


def ingest_stock_master(*, provider_name: str | None = None, dry_run: bool = False):
    provider = get_provider(provider_name)
    started_at = time.monotonic()
    log_entry = start_ingestion_log(
        job_name="ingest_stock_master",
        provider=provider.provider_name,
        target_type=DataIngestionLog.TARGET_STOCK,
    )
    report = IngestionReport(
        job_name="ingest_stock_master",
        provider=provider.provider_name,
        target_type=DataIngestionLog.TARGET_STOCK,
    )
    try:
        rows = provider.get_stock_master_rows()
        report.target_count = len(rows)
        for row in rows:
            try:
                validate_stock_code(row.code)
                validate_market(row.market)
                if dry_run:
                    report.success_count += 1
                    continue
                _, created = Stock.objects.update_or_create(
                    code=row.code,
                    defaults={
                        "name": row.name,
                        "market": row.market,
                        "sector": row.sector,
                        "is_active": row.is_active,
                    },
                )
                report.success_count += 1
                if created:
                    report.created_count += 1
                else:
                    report.updated_count += 1
            except Exception as exc:
                report.failed_count += 1
                report.warnings.append(f"{row.code}: {exc}")
        if report.failed_count and report.success_count:
            report.status = DataIngestionLog.STATUS_PARTIAL
        elif report.failed_count:
            report.status = DataIngestionLog.STATUS_FAILED
            report.error_message = "Stock master ingestion failed."
    except Exception as exc:
        report.status = DataIngestionLog.STATUS_FAILED
        report.error_message = str(exc)
        report.failed_count = max(report.failed_count, 1)
        logger.exception("Stock master ingestion failed")
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
            "created_count": report.created_count,
            "updated_count": report.updated_count,
            "warnings": report.warnings,
            "dry_run": dry_run,
        },
    )
    update_provider_status(
        provider=provider.provider_name,
        data_type=DataProviderStatus.TYPE_STOCK,
        status=report.status,
        latency_ms=latency_ms,
        error_message=report.error_message,
    )
    return report
