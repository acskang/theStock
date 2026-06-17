from django.db import models
from django.db.models import Q

DISCLAIMER_TEXT = (
    "본 결과는 투자 참고용 데이터 분석이며, 매수·매도 추천이 아닙니다. "
    "최종 투자 판단과 책임은 사용자 본인에게 있습니다."
)
PROBABILITY_DISCLAIMER_TEXT = (
    "본 결과는 과거 데이터와 현재 조건 기반의 추정 확률이며, "
    "매수·매도 추천이 아닙니다. 미래 수익 또는 손실 회피를 보장하지 않습니다."
)
CONSULTING_DISCLAIMER_TEXT = (
    "본 결과는 투자 참고용 데이터 분석이며, 매수·매도 추천이 아닙니다. "
    "미래 수익 또는 손실 회피를 보장하지 않습니다. 최종 투자 판단과 책임은 사용자 본인에게 있습니다."
)


class RiskEvent(models.Model):
    EVENT_TYPE_CHOICES = [
        ("trading_halt", "Trading Halt"),
        ("delisting_risk", "Delisting Risk"),
        ("managed_stock", "Managed Stock"),
        ("audit_opinion_rejected", "Audit Opinion Rejected"),
        ("capital_reduction", "Capital Reduction"),
        ("paid_in_capital_increase", "Paid-in Capital Increase"),
        ("embezzlement", "Embezzlement"),
        ("earnings_shock", "Earnings Shock"),
        ("operating_loss", "Operating Loss"),
        ("capital_impairment", "Capital Impairment"),
        ("disclosure_violation", "Disclosure Violation"),
        ("other", "Other"),
    ]

    RISK_LOW = "low"
    RISK_MEDIUM = "medium"
    RISK_HIGH = "high"
    RISK_CRITICAL = "critical"

    RISK_LEVEL_CHOICES = [
        (RISK_LOW, "Low"),
        (RISK_MEDIUM, "Medium"),
        (RISK_HIGH, "High"),
        (RISK_CRITICAL, "Critical"),
    ]

    stock = models.ForeignKey(
        "stocks.Stock",
        on_delete=models.CASCADE,
        related_name="risk_events",
    )
    event_type = models.CharField(max_length=100, choices=EVENT_TYPE_CHOICES)
    title = models.CharField(max_length=255)
    source = models.CharField(max_length=100, blank=True)
    source_key = models.CharField(max_length=255, blank=True, default="", db_index=True)
    url = models.URLField(blank=True)
    event_date = models.DateField(db_index=True)
    risk_level = models.CharField(max_length=20, choices=RISK_LEVEL_CHOICES)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-event_date"]
        indexes = [
            models.Index(fields=["stock", "-event_date"]),
            models.Index(fields=["risk_level", "is_active"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source_key"],
                condition=~Q(source_key=""),
                name="unique_risk_event_source_key",
            ),
        ]

    def __str__(self):
        return f"{self.stock} {self.risk_level} {self.title}"


class AveragingDecision(models.Model):
    GRADE_A = "A"
    GRADE_B = "B"
    GRADE_C = "C"
    GRADE_D = "D"

    GRADE_CHOICES = [
        (GRADE_A, "A - Reviewable"),
        (GRADE_B, "B - Watch"),
        (GRADE_C, "C - Avoid Averaging Down"),
        (GRADE_D, "D - Review Stop Loss"),
    ]

    holding = models.ForeignKey(
        "holdings.UserHolding",
        on_delete=models.CASCADE,
        related_name="decisions",
    )
    score = models.PositiveSmallIntegerField()
    grade = models.CharField(max_length=1, choices=GRADE_CHOICES)
    decision = models.CharField(max_length=100)
    reason_summary = models.TextField()
    reasons = models.JSONField(default=list, blank=True)
    score_breakdown = models.JSONField(default=dict, blank=True)
    suggested_budget = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    stop_loss_price = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    disclaimer = models.TextField(default=DISCLAIMER_TEXT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["holding", "-created_at"]),
            models.Index(fields=["grade", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.holding} {self.grade} {self.created_at:%Y-%m-%d}"


class AveragingProbabilityRecord(models.Model):
    holding = models.ForeignKey(
        "holdings.UserHolding",
        on_delete=models.CASCADE,
        related_name="probability_records",
    )
    scenario_input = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    success_probability = models.DecimalField(max_digits=6, decimal_places=4)
    failure_probability = models.DecimalField(max_digits=6, decimal_places=4)
    neutral_probability = models.DecimalField(max_digits=6, decimal_places=4)
    confidence = models.DecimalField(max_digits=6, decimal_places=4)
    disclaimer = models.TextField(default=PROBABILITY_DISCLAIMER_TEXT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["holding", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.holding} probability {self.created_at:%Y-%m-%d %H:%M:%S}"


class HoldingConsultRecord(models.Model):
    holding = models.ForeignKey(
        "holdings.UserHolding",
        on_delete=models.CASCADE,
        related_name="consult_records",
    )
    request_input = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(default=dict, blank=True)
    final_grade = models.CharField(max_length=1, choices=AveragingDecision.GRADE_CHOICES)
    consulting_status = models.CharField(max_length=100)
    summary = models.TextField()
    disclaimer = models.TextField(default=CONSULTING_DISCLAIMER_TEXT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["holding", "-created_at"]),
            models.Index(fields=["final_grade", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.holding} consult {self.final_grade} {self.created_at:%Y-%m-%d %H:%M:%S}"
