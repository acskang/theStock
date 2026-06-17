from decimal import Decimal

from django.conf import settings
from django.db import models


class UserHolding(models.Model):
    RISK_CONSERVATIVE = "conservative"
    RISK_NORMAL = "normal"
    RISK_AGGRESSIVE = "aggressive"

    RISK_LEVEL_CHOICES = [
        (RISK_CONSERVATIVE, "Conservative"),
        (RISK_NORMAL, "Normal"),
        (RISK_AGGRESSIVE, "Aggressive"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="holdings",
    )
    stock = models.ForeignKey(
        "stocks.Stock",
        on_delete=models.CASCADE,
        related_name="holdings",
    )
    average_price = models.DecimalField(max_digits=14, decimal_places=2)
    quantity = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    max_additional_budget = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    risk_level = models.CharField(
        max_length=20,
        choices=RISK_LEVEL_CHOICES,
        default=RISK_NORMAL,
    )
    memo = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "stock"],
                name="unique_user_stock_holding",
            )
        ]

    def __str__(self):
        return f"{self.user} - {self.stock}"

    @property
    def total_invested_amount(self):
        return (self.average_price or Decimal("0")) * Decimal(self.quantity or 0)
