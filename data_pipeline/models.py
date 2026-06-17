from django.db import models


class DataIngestionLog(models.Model):
    STATUS_STARTED = "started"
    STATUS_SUCCESS = "success"
    STATUS_PARTIAL = "partial"
    STATUS_FAILED = "failed"
    STATUS_SKIPPED = "skipped"

    TARGET_STOCK = "stock"
    TARGET_PRICE = "price"
    TARGET_FLOW = "flow"
    TARGET_MARKET = "market"
    TARGET_RISK = "risk"
    TARGET_FINANCIAL = "financial"
    TARGET_QUALITY = "quality"
    TARGET_PROVIDER_HEALTH = "provider_health"
    TARGET_AUTH = "auth"
    TARGET_QUOTE = "quote"
    TARGET_SMOKE = "smoke"
    TARGET_DAILY_PRICE = "daily_price"
    TARGET_HOLDINGS = "holdings"

    STATUS_CHOICES = [
        (STATUS_STARTED, "Started"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_PARTIAL, "Partial"),
        (STATUS_FAILED, "Failed"),
        (STATUS_SKIPPED, "Skipped"),
    ]
    TARGET_TYPE_CHOICES = [
        (TARGET_STOCK, "Stock"),
        (TARGET_PRICE, "Price"),
        (TARGET_FLOW, "Investor Flow"),
        (TARGET_MARKET, "Market"),
        (TARGET_RISK, "Risk Event"),
        (TARGET_FINANCIAL, "Financial"),
        (TARGET_QUALITY, "Data Quality"),
        (TARGET_PROVIDER_HEALTH, "Provider Health"),
        (TARGET_AUTH, "Authentication"),
        (TARGET_QUOTE, "Quote"),
        (TARGET_SMOKE, "Smoke"),
        (TARGET_DAILY_PRICE, "Daily Price"),
        (TARGET_HOLDINGS, "Holdings"),
    ]

    job_name = models.CharField(max_length=100)
    provider = models.CharField(max_length=50)
    target_type = models.CharField(max_length=30, choices=TARGET_TYPE_CHOICES)
    target_code = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_STARTED)
    started_at = models.DateTimeField(db_index=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    job_type = models.CharField(max_length=50, blank=True)
    provider_name = models.CharField(max_length=50, blank=True)
    endpoint_name = models.CharField(max_length=100, blank=True)
    target_symbol = models.CharField(max_length=50, blank=True)
    market = models.CharField(max_length=20, blank=True)
    network_call = models.BooleanField(null=True, blank=True)
    dry_run = models.BooleanField(null=True, blank=True)
    commit_mode = models.CharField(max_length=30, blank=True)
    total_count = models.PositiveIntegerField(default=0)
    success_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    saved_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    candidate_count = models.PositiveIntegerField(default=0)
    safe_reason = models.CharField(max_length=100, blank=True)
    error_code = models.CharField(max_length=100, blank=True)
    http_status_code = models.PositiveIntegerField(null=True, blank=True)
    duration_ms = models.PositiveIntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-started_at", "-id"]
        indexes = [
            models.Index(fields=["job_name", "-started_at"]),
            models.Index(fields=["provider", "-started_at"]),
            models.Index(fields=["status", "-started_at"]),
            models.Index(fields=["target_type", "target_code"]),
        ]

    def __str__(self):
        return f"{self.job_name} {self.provider} {self.status}"


class DataProviderStatus(models.Model):
    TYPE_STOCK = DataIngestionLog.TARGET_STOCK
    TYPE_PRICE = DataIngestionLog.TARGET_PRICE
    TYPE_FLOW = DataIngestionLog.TARGET_FLOW
    TYPE_MARKET = DataIngestionLog.TARGET_MARKET
    TYPE_RISK = DataIngestionLog.TARGET_RISK
    TYPE_FINANCIAL = DataIngestionLog.TARGET_FINANCIAL
    TYPE_QUALITY = DataIngestionLog.TARGET_QUALITY

    DATA_TYPE_CHOICES = DataIngestionLog.TARGET_TYPE_CHOICES

    provider = models.CharField(max_length=50)
    data_type = models.CharField(max_length=30, choices=DATA_TYPE_CHOICES)
    is_active = models.BooleanField(default=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_failed_at = models.DateTimeField(null=True, blank=True)
    last_error_message = models.TextField(blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    average_latency_ms = models.PositiveIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["provider", "data_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "data_type"],
                name="unique_provider_data_type_status",
            )
        ]
        indexes = [
            models.Index(fields=["provider", "data_type"]),
        ]

    def __str__(self):
        return f"{self.provider} {self.data_type}"


class DataQualitySnapshot(models.Model):
    GRADE_A = "A"
    GRADE_B = "B"
    GRADE_C = "C"
    GRADE_D = "D"

    GRADE_CHOICES = [
        (GRADE_A, "A"),
        (GRADE_B, "B"),
        (GRADE_C, "C"),
        (GRADE_D, "D"),
    ]

    stock = models.ForeignKey(
        "stocks.Stock",
        on_delete=models.CASCADE,
        related_name="data_quality_snapshots",
    )
    as_of_date = models.DateField(db_index=True)
    price_data_days = models.PositiveIntegerField(default=0)
    latest_price_date = models.DateField(null=True, blank=True)
    latest_price_age_days = models.PositiveIntegerField(null=True, blank=True)
    investor_flow_days = models.PositiveIntegerField(default=0)
    latest_flow_date = models.DateField(null=True, blank=True)
    market_data_available = models.BooleanField(default=False)
    risk_event_checked_at = models.DateTimeField(null=True, blank=True)
    financial_data_available = models.BooleanField(default=False)
    missing_fields = models.JSONField(default=list, blank=True)
    anomaly_flags = models.JSONField(default=list, blank=True)
    overall_score = models.DecimalField(max_digits=5, decimal_places=4)
    quality_grade = models.CharField(max_length=1, choices=GRADE_CHOICES)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["stock__code", "-as_of_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["stock", "as_of_date"],
                name="unique_stock_data_quality_snapshot_date",
            )
        ]
        indexes = [
            models.Index(fields=["stock", "-as_of_date"]),
            models.Index(fields=["quality_grade", "-as_of_date"]),
        ]

    def __str__(self):
        return f"{self.stock.code} {self.as_of_date} {self.quality_grade}"
