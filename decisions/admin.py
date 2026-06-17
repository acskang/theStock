from django.contrib import admin

from .models import AveragingDecision, AveragingProbabilityRecord, HoldingConsultRecord, RiskEvent


@admin.register(RiskEvent)
class RiskEventAdmin(admin.ModelAdmin):
    list_display = ("stock", "event_type", "risk_level", "title", "event_date", "is_active", "source_key")
    list_filter = ("risk_level", "event_type", "is_active", "event_date")
    search_fields = ("stock__code", "stock__name", "title", "description", "source_key")
    autocomplete_fields = ("stock",)
    readonly_fields = ("source_key",)
    date_hierarchy = "event_date"


@admin.register(AveragingDecision)
class AveragingDecisionAdmin(admin.ModelAdmin):
    list_display = ("holding", "score", "grade", "decision", "suggested_budget", "stop_loss_price", "created_at")
    list_filter = ("grade", "created_at")
    search_fields = ("holding__user__username", "holding__stock__code", "holding__stock__name", "reason_summary")
    autocomplete_fields = ("holding",)
    date_hierarchy = "created_at"


@admin.register(AveragingProbabilityRecord)
class AveragingProbabilityRecordAdmin(admin.ModelAdmin):
    list_display = (
        "holding",
        "success_probability",
        "failure_probability",
        "neutral_probability",
        "confidence",
        "created_at",
    )
    list_filter = ("created_at",)
    search_fields = ("holding__user__username", "holding__stock__code", "holding__stock__name")
    autocomplete_fields = ("holding",)
    date_hierarchy = "created_at"


@admin.register(HoldingConsultRecord)
class HoldingConsultRecordAdmin(admin.ModelAdmin):
    list_display = ("holding", "final_grade", "consulting_status", "created_at")
    list_filter = ("final_grade", "created_at")
    search_fields = ("holding__user__username", "holding__stock__code", "holding__stock__name", "summary")
    autocomplete_fields = ("holding",)
    date_hierarchy = "created_at"
