from collections import Counter

from django.db.models import Max
from django.utils import timezone

from data_pipeline.models import DataIngestionLog, DataProviderStatus, DataQualitySnapshot


SNAPSHOT_STALE_AFTER_DAYS = 1


def build_data_pipeline_summary(*, latest_job_limit: int = 10, recent_failure_limit: int = 5):
    latest_snapshot_date = DataQualitySnapshot.objects.aggregate(value=Max("as_of_date"))["value"]
    latest_snapshots = []
    latest_snapshot_age_days = None
    snapshot_is_stale = True
    if latest_snapshot_date is not None:
        latest_snapshot_age_days = (timezone.localdate() - latest_snapshot_date).days
        snapshot_is_stale = latest_snapshot_age_days > SNAPSHOT_STALE_AFTER_DAYS
        latest_snapshots = list(
            DataQualitySnapshot.objects.filter(as_of_date=latest_snapshot_date)
            .select_related("stock")
            .order_by("stock__code")
        )

    grade_counts = {
        DataQualitySnapshot.GRADE_A: 0,
        DataQualitySnapshot.GRADE_B: 0,
        DataQualitySnapshot.GRADE_C: 0,
        DataQualitySnapshot.GRADE_D: 0,
    }
    missing_field_counts = Counter()
    anomaly_flag_counts = Counter()
    financial_missing_count = 0
    anomaly_stock_count = 0

    for snapshot in latest_snapshots:
        grade_counts[snapshot.quality_grade] += 1
        if not snapshot.financial_data_available:
            financial_missing_count += 1
        if snapshot.anomaly_flags:
            anomaly_stock_count += 1
        missing_field_counts.update(snapshot.missing_fields)
        anomaly_flag_counts.update(snapshot.anomaly_flags)

    provider_status_rows = list(DataProviderStatus.objects.order_by("provider", "data_type"))
    failing_provider_rows = [
        row
        for row in provider_status_rows
        if row.consecutive_failures > 0 or row.last_failed_at is not None
    ]

    latest_logs = []
    seen_job_names = set()
    for log in DataIngestionLog.objects.order_by("-started_at", "-id"):
        if log.job_name in seen_job_names:
            continue
        latest_logs.append(log)
        seen_job_names.add(log.job_name)
        if len(latest_logs) >= latest_job_limit:
            break

    recent_failures = list(
        DataIngestionLog.objects.filter(
            status__in=[DataIngestionLog.STATUS_FAILED, DataIngestionLog.STATUS_PARTIAL]
        ).order_by("-started_at", "-id")[:recent_failure_limit]
    )
    latest_ingestion_log = DataIngestionLog.objects.order_by("-started_at", "-id").first()
    latest_success_log = (
        DataIngestionLog.objects.filter(status=DataIngestionLog.STATUS_SUCCESS)
        .order_by("-started_at", "-id")
        .first()
    )
    failing_provider_count = len(failing_provider_rows)
    if latest_snapshot_date is None or (snapshot_is_stale and failing_provider_count > 0):
        overall_status = "critical"
    elif snapshot_is_stale or failing_provider_count > 0 or recent_failures:
        overall_status = "degraded"
    else:
        overall_status = "healthy"

    return {
        "health_summary": {
            "overall_status": overall_status,
            "latest_snapshot_age_days": latest_snapshot_age_days,
            "snapshot_is_stale": snapshot_is_stale,
            "failing_provider_count": failing_provider_count,
            "recent_failure_count": len(recent_failures),
            "latest_ingestion_started_at": None if latest_ingestion_log is None else latest_ingestion_log.started_at,
            "latest_success_started_at": None if latest_success_log is None else latest_success_log.started_at,
        },
        "snapshot_summary": {
            "latest_as_of_date": latest_snapshot_date,
            "latest_snapshot_age_days": latest_snapshot_age_days,
            "snapshot_is_stale": snapshot_is_stale,
            "stock_count": len(latest_snapshots),
            "grade_counts": grade_counts,
            "financial_missing_count": financial_missing_count,
            "anomaly_stock_count": anomaly_stock_count,
            "missing_field_counts": dict(sorted(missing_field_counts.items())),
            "anomaly_flag_counts": dict(sorted(anomaly_flag_counts.items())),
        },
        "provider_summary": {
            "total": len(provider_status_rows),
            "active": sum(1 for row in provider_status_rows if row.is_active),
            "inactive": sum(1 for row in provider_status_rows if not row.is_active),
            "failing": len(failing_provider_rows),
            "failing_providers": [
                {
                    "provider": row.provider,
                    "data_type": row.data_type,
                    "consecutive_failures": row.consecutive_failures,
                    "last_error_message": row.last_error_message,
                    "last_failed_at": row.last_failed_at,
                }
                for row in failing_provider_rows
            ],
        },
        "ingestion_summary": {
            "latest_jobs": latest_logs,
            "recent_failures": recent_failures,
        },
    }
