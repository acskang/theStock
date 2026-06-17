from __future__ import annotations

import logging
import time

from data_pipeline.dataclasses import IngestionReport
from data_pipeline.models import DataIngestionLog, DataProviderStatus
from data_pipeline.providers import get_provider
from data_pipeline.services.ingestion_log_service import finish_ingestion_log, start_ingestion_log, update_provider_status
from marketdata.models import MarketIndex

logger = logging.getLogger(__name__)

DEFAULT_MARKET_INDEX_CODES = ["KOSPI", "KOSDAQ", "USDKRW", "NASDAQ", "SP500"]


def ingest_market_indices(*, provider_name: str | None = None, codes=None, days: int = 240, dry_run: bool = False):
    provider = get_provider(provider_name)
    target_codes = list(codes or DEFAULT_MARKET_INDEX_CODES)
    started_at = time.monotonic()
    log_entry = start_ingestion_log(
        job_name="ingest_market_indices",
        provider=provider.provider_name,
        target_type=DataIngestionLog.TARGET_MARKET,
        target_code=",".join(target_codes),
        total_count=len(target_codes),
    )
    report = IngestionReport(
        job_name="ingest_market_indices",
        provider=provider.provider_name,
        target_type=DataIngestionLog.TARGET_MARKET,
        target_count=len(target_codes),
    )
    try:
        for code in target_codes:
            try:
                rows = provider.get_market_index_rows(code, days)
                if not rows:
                    report.skipped_count += 1
                    continue
                for row in rows:
                    if not dry_run:
                        _, created = MarketIndex.objects.update_or_create(
                            code=row.code,
                            date=row.date,
                            defaults={
                                "name": row.name,
                                "close_value": row.close_value,
                                "change_rate": row.change_rate,
                            },
                        )
                        if created:
                            report.created_count += 1
                        else:
                            report.updated_count += 1
                report.success_count += 1
            except Exception as exc:
                logger.exception("Market index ingestion failed for %s", code)
                report.failed_count += 1
                report.warnings.append(f"{code}: {exc}")
        if report.failed_count and report.success_count:
            report.status = DataIngestionLog.STATUS_PARTIAL
        elif report.failed_count:
            report.status = DataIngestionLog.STATUS_FAILED
            report.error_message = "Market index ingestion failed."
    except Exception as exc:
        report.status = DataIngestionLog.STATUS_FAILED
        report.error_message = str(exc)
        logger.exception("Market index ingestion crashed")
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
        data_type=DataProviderStatus.TYPE_MARKET,
        status=report.status,
        latency_ms=latency_ms,
        error_message=report.error_message,
    )
    return report
