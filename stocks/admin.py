from django.contrib import admin

from .models import FinancialSnapshot, Stock


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "market", "sector", "is_active", "updated_at")
    list_filter = ("market", "is_active", "sector")
    search_fields = ("code", "name", "sector")
    ordering = ("code",)


@admin.register(FinancialSnapshot)
class FinancialSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        "stock",
        "fiscal_year",
        "period_type",
        "reported_date",
        "revenue",
        "operating_profit",
        "net_income",
        "source",
    )
    list_filter = ("period_type", "source", "stock__market")
    search_fields = ("stock__code", "stock__name", "source_key")
    ordering = ("stock__code", "-fiscal_year", "-reported_date", "period_type")
