from django.contrib import admin

from .models import UserHolding


@admin.register(UserHolding)
class UserHoldingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "stock",
        "is_active",
        "average_price",
        "quantity",
        "max_additional_budget",
        "risk_level",
        "updated_at",
    )
    list_filter = ("is_active", "risk_level", "stock__market")
    search_fields = ("user__username", "stock__code", "stock__name")
    autocomplete_fields = ("user", "stock")
