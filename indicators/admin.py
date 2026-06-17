from django.contrib import admin

from .models import TechnicalIndicator


@admin.register(TechnicalIndicator)
class TechnicalIndicatorAdmin(admin.ModelAdmin):
    list_display = (
        "stock",
        "date",
        "ma5",
        "ma20",
        "ma60",
        "rsi14",
        "macd",
        "atr14",
        "volume_ma20",
    )
    list_filter = ("date", "stock__market")
    search_fields = ("stock__code", "stock__name")
    autocomplete_fields = ("stock",)
    date_hierarchy = "date"

