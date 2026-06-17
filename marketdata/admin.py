from django.contrib import admin

from .models import DailyPrice, InvestorFlow, MarketIndex, StockDataCollectionStatus


@admin.register(DailyPrice)
class DailyPriceAdmin(admin.ModelAdmin):
    list_display = ("stock", "date", "open_price", "high_price", "low_price", "close_price", "volume")
    list_filter = ("stock__market", "date")
    search_fields = ("stock__code", "stock__name")
    autocomplete_fields = ("stock",)
    date_hierarchy = "date"


@admin.register(InvestorFlow)
class InvestorFlowAdmin(admin.ModelAdmin):
    list_display = ("stock", "date", "foreign_net_buy", "institution_net_buy", "individual_net_buy")
    list_filter = ("date", "stock__market")
    search_fields = ("stock__code", "stock__name")
    autocomplete_fields = ("stock",)
    date_hierarchy = "date"


@admin.register(MarketIndex)
class MarketIndexAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "date", "close_value", "change_rate")
    list_filter = ("code", "date")
    search_fields = ("code", "name")
    date_hierarchy = "date"


@admin.register(StockDataCollectionStatus)
class StockDataCollectionStatusAdmin(admin.ModelAdmin):
    list_display = (
        "stock",
        "data_type",
        "status",
        "source",
        "last_row_count",
        "last_synced_at",
        "last_success_at",
    )
    list_filter = ("data_type", "status", "stock__market")
    search_fields = ("stock__code", "stock__name", "last_message")
    autocomplete_fields = ("stock",)
