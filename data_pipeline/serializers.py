from rest_framework import serializers

from .models import DataIngestionLog, DataProviderStatus, DataQualitySnapshot


class TossOrderHistoryQuerySerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=("OPEN", "CLOSED"), default="CLOSED", required=False)
    symbol = serializers.RegexField(
        regex=r"^[A-Za-z0-9.\-]+$",
        required=False,
        allow_blank=True,
        max_length=32,
    )
    from_date = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    to_date = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    cursor = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    limit = serializers.IntegerField(required=False, default=20, min_value=1, max_value=100)

    def validate_symbol(self, value):
        clean_value = str(value or "").strip()
        if not clean_value:
            return ""
        if any(token in clean_value for token in (",", "/", "?", "&", "=", ":", "\\")) or any(
            char.isspace() for char in clean_value
        ):
            raise serializers.ValidationError("Invalid Toss order history symbol.")
        return clean_value

    def validate_from_date(self, value):
        return self._validate_date_string(value)

    def validate_to_date(self, value):
        return self._validate_date_string(value)

    def _validate_date_string(self, value):
        clean_value = str(value or "").strip()
        if not clean_value:
            return ""
        if len(clean_value) != 10 or clean_value[4] != "-" or clean_value[7] != "-":
            raise serializers.ValidationError("Date must use YYYY-MM-DD format.")
        year, month, day = clean_value.split("-")
        if not (year.isdigit() and month.isdigit() and day.isdigit()):
            raise serializers.ValidationError("Date must use YYYY-MM-DD format.")
        if not (1 <= int(month) <= 12 and 1 <= int(day) <= 31):
            raise serializers.ValidationError("Date must use YYYY-MM-DD format.")
        return clean_value


class TossOrderHistoryReconciliationQuerySerializer(serializers.Serializer):
    symbol = serializers.RegexField(
        regex=r"^[A-Za-z0-9.\-]+$",
        required=True,
        allow_blank=False,
        max_length=32,
    )
    from_date = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    to_date = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    limit = serializers.IntegerField(required=False, default=20, min_value=1, max_value=100)

    unsupported_params = {
        "status",
        "cursor",
        "account",
        "raw",
        "user_id",
        "username",
        "email",
    }

    def validate(self, attrs):
        rejected = sorted(name for name in self.unsupported_params if name in self.initial_data)
        if rejected:
            raise serializers.ValidationError(
                {name: "This query parameter is not supported for reconciliation." for name in rejected}
            )
        return attrs

    def validate_symbol(self, value):
        clean_value = str(value or "").strip()
        if any(token in clean_value for token in (",", "/", "?", "&", "=", ":", "\\")) or any(
            char.isspace() for char in clean_value
        ):
            raise serializers.ValidationError("Invalid Toss order history reconciliation symbol.")
        return clean_value

    def validate_from_date(self, value):
        return self._validate_date_string(value)

    def validate_to_date(self, value):
        return self._validate_date_string(value)

    def _validate_date_string(self, value):
        clean_value = str(value or "").strip()
        if not clean_value:
            return ""
        if len(clean_value) != 10 or clean_value[4] != "-" or clean_value[7] != "-":
            raise serializers.ValidationError("Date must use YYYY-MM-DD format.")
        year, month, day = clean_value.split("-")
        if not (year.isdigit() and month.isdigit() and day.isdigit()):
            raise serializers.ValidationError("Date must use YYYY-MM-DD format.")
        if not (1 <= int(month) <= 12 and 1 <= int(day) <= 31):
            raise serializers.ValidationError("Date must use YYYY-MM-DD format.")
        return clean_value


class DataIngestionLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataIngestionLog
        fields = [
            "id",
            "job_name",
            "job_type",
            "provider",
            "provider_name",
            "target_type",
            "target_code",
            "target_symbol",
            "market",
            "endpoint_name",
            "status",
            "safe_reason",
            "error_code",
            "http_status_code",
            "network_call",
            "dry_run",
            "commit_mode",
            "started_at",
            "finished_at",
            "total_count",
            "success_count",
            "failed_count",
            "skipped_count",
            "candidate_count",
            "saved_count",
            "updated_count",
            "duration_ms",
            "error_message",
            "metadata",
            "details",
            "created_at",
        ]
        read_only_fields = fields


class DataProviderStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = DataProviderStatus
        fields = [
            "id",
            "provider",
            "data_type",
            "is_active",
            "last_success_at",
            "last_failed_at",
            "last_error_message",
            "consecutive_failures",
            "average_latency_ms",
            "updated_at",
        ]
        read_only_fields = fields


class DataQualitySnapshotSerializer(serializers.ModelSerializer):
    stock_code = serializers.CharField(source="stock.code", read_only=True)
    stock_name = serializers.CharField(source="stock.name", read_only=True)

    class Meta:
        model = DataQualitySnapshot
        fields = [
            "id",
            "stock_code",
            "stock_name",
            "as_of_date",
            "price_data_days",
            "latest_price_date",
            "latest_price_age_days",
            "investor_flow_days",
            "latest_flow_date",
            "market_data_available",
            "risk_event_checked_at",
            "financial_data_available",
            "missing_fields",
            "anomaly_flags",
            "overall_score",
            "quality_grade",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class DataPipelineFailingProviderSerializer(serializers.Serializer):
    provider = serializers.CharField(read_only=True)
    data_type = serializers.CharField(read_only=True)
    consecutive_failures = serializers.IntegerField(read_only=True)
    last_error_message = serializers.CharField(read_only=True, allow_blank=True)
    last_failed_at = serializers.DateTimeField(read_only=True, allow_null=True)


class DataPipelineSnapshotSummarySerializer(serializers.Serializer):
    latest_as_of_date = serializers.DateField(read_only=True, allow_null=True)
    latest_snapshot_age_days = serializers.IntegerField(read_only=True, allow_null=True)
    snapshot_is_stale = serializers.BooleanField(read_only=True)
    stock_count = serializers.IntegerField(read_only=True)
    grade_counts = serializers.DictField(child=serializers.IntegerField(), read_only=True)
    financial_missing_count = serializers.IntegerField(read_only=True)
    anomaly_stock_count = serializers.IntegerField(read_only=True)
    missing_field_counts = serializers.DictField(child=serializers.IntegerField(), read_only=True)
    anomaly_flag_counts = serializers.DictField(child=serializers.IntegerField(), read_only=True)


class DataPipelineProviderSummarySerializer(serializers.Serializer):
    total = serializers.IntegerField(read_only=True)
    active = serializers.IntegerField(read_only=True)
    inactive = serializers.IntegerField(read_only=True)
    failing = serializers.IntegerField(read_only=True)
    failing_providers = DataPipelineFailingProviderSerializer(many=True, read_only=True)


class DataPipelineIngestionSummarySerializer(serializers.Serializer):
    latest_jobs = DataIngestionLogSerializer(many=True, read_only=True)
    recent_failures = DataIngestionLogSerializer(many=True, read_only=True)


class DataPipelineHealthSummarySerializer(serializers.Serializer):
    overall_status = serializers.CharField(read_only=True)
    latest_snapshot_age_days = serializers.IntegerField(read_only=True, allow_null=True)
    snapshot_is_stale = serializers.BooleanField(read_only=True)
    failing_provider_count = serializers.IntegerField(read_only=True)
    recent_failure_count = serializers.IntegerField(read_only=True)
    latest_ingestion_started_at = serializers.DateTimeField(read_only=True, allow_null=True)
    latest_success_started_at = serializers.DateTimeField(read_only=True, allow_null=True)


class DataPipelineSummarySerializer(serializers.Serializer):
    health_summary = DataPipelineHealthSummarySerializer(read_only=True)
    snapshot_summary = DataPipelineSnapshotSummarySerializer(read_only=True)
    provider_summary = DataPipelineProviderSummarySerializer(read_only=True)
    ingestion_summary = DataPipelineIngestionSummarySerializer(read_only=True)
