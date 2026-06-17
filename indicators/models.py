from django.db import models


class TechnicalIndicator(models.Model):
    stock = models.ForeignKey(
        "stocks.Stock",
        on_delete=models.CASCADE,
        related_name="technical_indicators",
    )
    date = models.DateField(db_index=True)
    ma5 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    ma20 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    ma60 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    ma120 = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    rsi14 = models.DecimalField(max_digits=8, decimal_places=4, null=True, blank=True)
    macd = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    macd_signal = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    macd_histogram = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    atr14 = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    volume_ma20 = models.BigIntegerField(null=True, blank=True)
    bb_upper = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    bb_middle = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    bb_lower = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(
                fields=["stock", "date"],
                name="unique_stock_technical_indicator",
            )
        ]
        indexes = [
            models.Index(fields=["stock", "-date"]),
        ]

    def __str__(self):
        return f"{self.stock} {self.date}"

