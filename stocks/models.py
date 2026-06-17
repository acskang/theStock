from django.db import models


class Stock(models.Model):
    MARKET_KOSPI = "KOSPI"
    MARKET_KOSDAQ = "KOSDAQ"
    MARKET_KONEX = "KONEX"
    MARKET_ETF = "ETF"
    MARKET_ETN = "ETN"

    MARKET_CHOICES = [
        (MARKET_KOSPI, "KOSPI"),
        (MARKET_KOSDAQ, "KOSDAQ"),
        (MARKET_KONEX, "KONEX"),
        (MARKET_ETF, "ETF"),
        (MARKET_ETN, "ETN"),
    ]

    code = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=100, db_index=True)
    market = models.CharField(max_length=20, choices=MARKET_CHOICES)
    sector = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "Stock"
        verbose_name_plural = "Stocks"

    def __str__(self):
        return f"{self.code} {self.name}"


class FinancialSnapshot(models.Model):
    PERIOD_Q1 = "Q1"
    PERIOD_Q2 = "Q2"
    PERIOD_Q3 = "Q3"
    PERIOD_Q4 = "Q4"
    PERIOD_ANNUAL = "ANNUAL"

    PERIOD_CHOICES = [
        (PERIOD_Q1, "Q1"),
        (PERIOD_Q2, "Q2"),
        (PERIOD_Q3, "Q3"),
        (PERIOD_Q4, "Q4"),
        (PERIOD_ANNUAL, "ANNUAL"),
    ]

    stock = models.ForeignKey(
        Stock,
        on_delete=models.CASCADE,
        related_name="financial_snapshots",
    )
    fiscal_year = models.PositiveIntegerField()
    period_type = models.CharField(max_length=10, choices=PERIOD_CHOICES)
    reported_date = models.DateField(null=True, blank=True)
    revenue = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    operating_profit = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    net_income = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    operating_cash_flow = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    debt_ratio = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    current_ratio = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    equity = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)
    capital_impairment_rate = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    roe = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    per = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    pbr = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    source = models.CharField(max_length=50, blank=True)
    source_key = models.CharField(max_length=120, null=True, blank=True, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["stock_id", "-fiscal_year", "-reported_date", "period_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["stock", "fiscal_year", "period_type"],
                name="unique_stock_financial_snapshot_period",
            )
        ]
        indexes = [
            models.Index(fields=["stock", "-reported_date"]),
            models.Index(fields=["stock", "-fiscal_year", "period_type"]),
        ]
        verbose_name = "Financial Snapshot"
        verbose_name_plural = "Financial Snapshots"

    def __str__(self):
        return f"{self.stock.code} {self.fiscal_year} {self.period_type}"
