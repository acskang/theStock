from __future__ import annotations

import logging
import time

from data_pipeline.dataclasses import IngestionReport
from data_pipeline.models import DataIngestionLog, DataProviderStatus
from data_pipeline.providers import get_provider
from data_pipeline.services import resolve_target_stocks
from data_pipeline.services.ingestion_log_service import finish_ingestion_log, start_ingestion_log, update_provider_status
from data_pipeline.validators import validate_daily_price_row
from marketdata.models import DailyPrice

logger = logging.getLogger(__name__)


def ingest_daily_prices(
    *,
    provider_name: str | None = None,
    stock_codes=None,
    days: int = 240,
    all_stocks: bool = False,
    dry_run: bool = False,
):
    provider = get_provider(provider_name)
    target_stocks = resolve_target_stocks(stock_codes=stock_codes, all_stocks=all_stocks)
    started_at = time.monotonic()
    log_entry = start_ingestion_log(
        job_name="ingest_daily_prices",
        provider=provider.provider_name,
        target_type=DataIngestionLog.TARGET_PRICE,
        target_code=",".join(stock_codes or []),
        total_count=len(target_stocks),
    )
    report = IngestionReport(
        job_name="ingest_daily_prices",
        provider=provider.provider_name,
        target_type=DataIngestionLog.TARGET_PRICE,
        target_count=len(target_stocks),
    )
    try:
        for stock in target_stocks:
            try:
                rows = provider.get_daily_price_rows(stock, days)
                if not rows:
                    report.skipped_count += 1
                    continue
                for row in rows:
                    validate_daily_price_row(row)
                    if not dry_run:
                        _, created = DailyPrice.objects.update_or_create(
                            stock=stock,
                            date=row.date,
                            defaults={
                                "open_price": row.open_price,
                                "high_price": row.high_price,
                                "low_price": row.low_price,
                                "close_price": row.close_price,
                                "volume": row.volume,
                                "change_rate": row.change_rate,
                            },
                        )
                        if created:
                            report.created_count += 1
                        else:
                            report.updated_count += 1
                report.success_count += 1
            except Exception as exc:
                logger.exception("Daily price ingestion failed for %s", stock.code)
                report.failed_count += 1
                report.warnings.append(f"{stock.code}: {exc}")
        if report.failed_count and report.success_count:
            report.status = DataIngestionLog.STATUS_PARTIAL
        elif report.failed_count:
            report.status = DataIngestionLog.STATUS_FAILED
            report.error_message = "Daily price ingestion failed."
    except Exception as exc:
        report.status = DataIngestionLog.STATUS_FAILED
        report.error_message = str(exc)
        logger.exception("Daily price ingestion crashed")
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
        data_type=DataProviderStatus.TYPE_PRICE,
        status=report.status,
        latency_ms=latency_ms,
        error_message=report.error_message,
    )
    return report
