from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.utils import timezone

from data_pipeline.dataclasses import IngestionReport
from data_pipeline.models import DataIngestionLog, DataQualitySnapshot, DataProviderStatus
from data_pipeline.services import resolve_target_stocks
from data_pipeline.services.ingestion_log_service import finish_ingestion_log, start_ingestion_log, update_provider_status
from decisions.services.data_quality_service import evaluate_data_quality
from marketdata.models import InvestorFlow, StockDataCollectionStatus
from marketdata.services.collection_status_service import get_collection_status_snapshot
from stocks.models import FinancialSnapshot


def convert_data_quality_grade(score: Decimal) -> str:
    if score >= Decimal("0.8000"):
        return DataQualitySnapshot.GRADE_A
    if score >= Decimal("0.6000"):
        return DataQualitySnapshot.GRADE_B
    if score >= Decimal("0.4000"):
        return DataQualitySnapshot.GRADE_C
    return DataQualitySnapshot.GRADE_D


def _build_missing_fields(result, *, financial_data_available: bool):
    missing = []
    if result.price_data_days == 0:
        missing.append("daily_prices")
    if result.latest_price_age_days is None:
        missing.append("latest_price")
    if result.investor_flow_days == 0:
        missing.append("investor_flows")
    if not result.market_data_available:
        missing.append("market_indices")
    if not result.risk_event_available:
        missing.append("risk_events")
    if not financial_data_available:
        missing.append("financial_snapshots")
    return missing


def _build_anomaly_flags(result):
    flags = []
    if result.latest_price_age_days is not None and result.latest_price_age_days > 3:
        flags.append("stale_latest_price")
    if 0 < result.price_data_days < 120:
        flags.append("insufficient_price_history")
    if 0 < result.investor_flow_days < 20:
        flags.append("insufficient_investor_flow_history")
    if not result.market_data_available:
        flags.append("missing_market_context")
    return flags


def update_data_quality(*, stock_codes=None, all_stocks: bool = False):
    target_stocks = resolve_target_stocks(stock_codes=stock_codes, all_stocks=all_stocks)
    log_entry = start_ingestion_log(
        job_name="update_data_quality",
        provider="internal",
        target_type=DataIngestionLog.TARGET_QUALITY,
        target_code=",".join(stock_codes or []),
        total_count=len(target_stocks),
    )
    report = IngestionReport(
        job_name="update_data_quality",
        provider="internal",
        target_type=DataIngestionLog.TARGET_QUALITY,
        target_count=len(target_stocks),
    )
    try:
        for stock in target_stocks:
            try:
                quality_result = evaluate_data_quality(SimpleNamespace(stock=stock))
                flow_status = get_collection_status_snapshot(stock, StockDataCollectionStatus.TYPE_INVESTOR_FLOW)
                risk_status = get_collection_status_snapshot(stock, StockDataCollectionStatus.TYPE_RISK_EVENT)
                financial_data_available = FinancialSnapshot.objects.filter(stock=stock).exists()
                latest_flow_date = (
                    InvestorFlow.objects.filter(stock=stock).order_by("-date").values_list("date", flat=True).first()
                )
                snapshot_defaults = {
                    "price_data_days": quality_result.price_data_days,
                    "latest_price_date": None
                    if quality_result.latest_price_age_days is None
                    else timezone.localdate() - timedelta(days=quality_result.latest_price_age_days),
                    "latest_price_age_days": quality_result.latest_price_age_days,
                    "investor_flow_days": quality_result.investor_flow_days,
                    "latest_flow_date": latest_flow_date,
                    "market_data_available": quality_result.market_data_available,
                    "risk_event_checked_at": (
                        None
                        if risk_status.status == StockDataCollectionStatus.STATUS_NEVER
                        else timezone.now()
                    ),
                    "financial_data_available": financial_data_available,
                    "missing_fields": _build_missing_fields(
                        quality_result,
                        financial_data_available=financial_data_available,
                    ),
                    "anomaly_flags": _build_anomaly_flags(quality_result),
                    "overall_score": quality_result.overall_score,
                    "quality_grade": convert_data_quality_grade(quality_result.overall_score),
                }
                DataQualitySnapshot.objects.update_or_create(
                    stock=stock,
                    as_of_date=timezone.localdate(),
                    defaults=snapshot_defaults,
                )
                report.success_count += 1
                if flow_status.status == StockDataCollectionStatus.STATUS_ERROR:
                    report.warnings.append(f"{stock.code}: investor flow status is error.")
            except Exception as exc:
                report.failed_count += 1
                report.warnings.append(f"{stock.code}: {exc}")
        if report.failed_count and report.success_count:
            report.status = DataIngestionLog.STATUS_PARTIAL
        elif report.failed_count:
            report.status = DataIngestionLog.STATUS_FAILED
            report.error_message = "Data quality update failed."
    except Exception as exc:
        report.status = DataIngestionLog.STATUS_FAILED
        report.error_message = str(exc)
    finish_ingestion_log(
        log_entry,
        status=report.status,
        success_count=report.success_count,
        failed_count=report.failed_count,
        skipped_count=report.skipped_count,
        total_count=report.target_count,
        error_message=report.error_message,
        details={"warnings": report.warnings},
    )
    update_provider_status(
        provider="internal",
        data_type=DataProviderStatus.TYPE_QUALITY,
        status=report.status,
        error_message=report.error_message,
    )
    return report
