from __future__ import annotations

from django.utils import timezone

from data_pipeline.models import DataIngestionLog, DataProviderStatus


def start_ingestion_log(*, job_name: str, provider: str, target_type: str, target_code: str = "", total_count: int = 0):
    return DataIngestionLog.objects.create(
        job_name=job_name,
        provider=provider,
        target_type=target_type,
        target_code=target_code,
        status=DataIngestionLog.STATUS_STARTED,
        started_at=timezone.now(),
        total_count=total_count,
    )


def finish_ingestion_log(
    log_entry: DataIngestionLog,
    *,
    status: str,
    success_count: int = 0,
    failed_count: int = 0,
    skipped_count: int = 0,
    total_count: int | None = None,
    error_message: str = "",
    details: dict | None = None,
):
    log_entry.status = status
    log_entry.finished_at = timezone.now()
    if total_count is not None:
        log_entry.total_count = total_count
    log_entry.success_count = max(int(success_count), 0)
    log_entry.failed_count = max(int(failed_count), 0)
    log_entry.skipped_count = max(int(skipped_count), 0)
    log_entry.error_message = error_message.strip()
    log_entry.details = details or {}
    log_entry.save(
        update_fields=[
            "status",
            "finished_at",
            "total_count",
            "success_count",
            "failed_count",
            "skipped_count",
            "error_message",
            "details",
        ]
    )
    return log_entry


def update_provider_status(
    *,
    provider: str,
    data_type: str,
    status: str,
    latency_ms: int | None = None,
    error_message: str = "",
):
    provider_status, _ = DataProviderStatus.objects.get_or_create(
        provider=provider,
        data_type=data_type,
        defaults={"is_active": True},
    )
    now = timezone.now()
    if status == DataIngestionLog.STATUS_FAILED:
        provider_status.last_failed_at = now
        provider_status.last_error_message = error_message.strip()
        provider_status.consecutive_failures += 1
    else:
        provider_status.last_success_at = now
        provider_status.last_error_message = error_message.strip()
        provider_status.consecutive_failures = 0
    if latency_ms is not None:
        latency_ms = max(int(latency_ms), 0)
        if provider_status.average_latency_ms is None:
            provider_status.average_latency_ms = latency_ms
        else:
            provider_status.average_latency_ms = int((provider_status.average_latency_ms + latency_ms) / 2)
    provider_status.is_active = True
    provider_status.save()
    return provider_status
