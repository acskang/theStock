from django.contrib import admin

from .models import DataIngestionLog, DataProviderStatus, DataQualitySnapshot


@admin.register(DataIngestionLog)
class DataIngestionLogAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "provider_name",
        "job_type",
        "job_name",
        "provider",
        "target_type",
        "target_symbol",
        "target_code",
        "endpoint_name",
        "status",
        "safe_reason",
        "network_call",
        "dry_run",
        "commit_mode",
        "candidate_count",
        "saved_count",
        "updated_count",
        "skipped_count",
        "failed_count",
        "http_status_code",
        "duration_ms",
        "created_at",
        "started_at",
        "finished_at",
    )
    list_filter = (
        "provider_name",
        "provider",
        "job_type",
        "target_type",
        "status",
        "network_call",
        "dry_run",
        "commit_mode",
    )
    search_fields = (
        "job_name",
        "job_type",
        "provider",
        "provider_name",
        "target_code",
        "target_symbol",
        "endpoint_name",
        "safe_reason",
        "error_code",
        "error_message",
    )
    readonly_fields = (
        "created_at",
        "metadata",
        "details",
    )
    ordering = ("-started_at", "-id")


@admin.register(DataProviderStatus)
class DataProviderStatusAdmin(admin.ModelAdmin):
    list_display = (
        "provider",
        "data_type",
        "is_active",
        "last_success_at",
        "last_failed_at",
        "consecutive_failures",
        "average_latency_ms",
    )
    list_filter = ("provider", "data_type", "is_active")
    search_fields = ("provider", "data_type", "last_error_message")


@admin.register(DataQualitySnapshot)
class DataQualitySnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "stock",
        "as_of_date",
        "quality_grade",
        "overall_score",
        "price_data_days",
        "investor_flow_days",
        "market_data_available",
        "financial_data_available",
    )
    list_filter = ("quality_grade", "market_data_available", "financial_data_available")
    search_fields = ("stock__code", "stock__name")
    readonly_fields = ("created_at", "updated_at")
