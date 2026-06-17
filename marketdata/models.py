from django.core.exceptions import ValidationError
from django.db import models


class DailyPrice(models.Model):
    stock = models.ForeignKey(
        "stocks.Stock",
        on_delete=models.CASCADE,
        related_name="daily_prices",
    )
    date = models.DateField(db_index=True)
    open_price = models.DecimalField(max_digits=14, decimal_places=2)
    high_price = models.DecimalField(max_digits=14, decimal_places=2)
    low_price = models.DecimalField(max_digits=14, decimal_places=2)
    close_price = models.DecimalField(max_digits=14, decimal_places=2)
    volume = models.BigIntegerField(default=0)
    change_rate = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(
                fields=["stock", "date"],
                name="unique_stock_daily_price",
            )
        ]
        indexes = [
            models.Index(fields=["stock", "-date"]),
        ]

    def __str__(self):
        return f"{self.stock} {self.date} {self.close_price}"

    def clean(self):
        if self.high_price < self.low_price:
            raise ValidationError("high_price must be greater than or equal to low_price.")
        if self.high_price < self.open_price or self.high_price < self.close_price:
            raise ValidationError("high_price must be the maximum price of the day.")
        if self.low_price > self.open_price or self.low_price > self.close_price:
            raise ValidationError("low_price must be the minimum price of the day.")
        if self.volume < 0:
            raise ValidationError("volume must be greater than or equal to zero.")


class InvestorFlow(models.Model):
    stock = models.ForeignKey(
        "stocks.Stock",
        on_delete=models.CASCADE,
        related_name="investor_flows",
    )
    date = models.DateField(db_index=True)
    foreign_net_buy = models.BigIntegerField(default=0)
    institution_net_buy = models.BigIntegerField(default=0)
    individual_net_buy = models.BigIntegerField(default=0)
    program_net_buy = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(
                fields=["stock", "date"],
                name="unique_stock_investor_flow",
            )
        ]

    def __str__(self):
        return f"{self.stock} {self.date}"


class StockDataCollectionStatus(models.Model):
    TYPE_INVESTOR_FLOW = "investor_flow"
    TYPE_RISK_EVENT = "risk_event"
    TYPE_FINANCIAL_SNAPSHOT = "financial_snapshot"

    STATUS_NEVER = "never"
    STATUS_SUCCESS = "success"
    STATUS_EMPTY = "empty"
    STATUS_ERROR = "error"
    STATUS_SKIPPED = "skipped"

    DATA_TYPE_CHOICES = [
        (TYPE_INVESTOR_FLOW, "Investor Flow"),
        (TYPE_RISK_EVENT, "Risk Event"),
        (TYPE_FINANCIAL_SNAPSHOT, "Financial Snapshot"),
    ]
    STATUS_CHOICES = [
        (STATUS_NEVER, "Never"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_EMPTY, "Empty"),
        (STATUS_ERROR, "Error"),
        (STATUS_SKIPPED, "Skipped"),
    ]

    stock = models.ForeignKey(
        "stocks.Stock",
        on_delete=models.CASCADE,
        related_name="collection_statuses",
    )
    data_type = models.CharField(max_length=30, choices=DATA_TYPE_CHOICES)
    source = models.CharField(max_length=50, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_NEVER)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_row_count = models.PositiveIntegerField(default=0)
    last_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["data_type", "stock__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["stock", "data_type"],
                name="unique_stock_collection_status_type",
            )
        ]
        indexes = [
            models.Index(fields=["data_type", "status"]),
        ]

    def __str__(self):
        return f"{self.stock} {self.data_type} {self.status}"


class MarketIndex(models.Model):
    code = models.CharField(max_length=30, db_index=True)
    name = models.CharField(max_length=100)
    date = models.DateField(db_index=True)
    close_value = models.DecimalField(max_digits=16, decimal_places=4)
    change_rate = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["code", "date"],
                name="unique_market_index_date",
            )
        ]

    def __str__(self):
        return f"{self.code} {self.date}"
