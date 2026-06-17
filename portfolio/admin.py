from django.contrib import admin
from .models import StockSymbol, Transaction


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('trade_type', 'stock_name', 'year', 'month', 'day', 'hour', 'minute', 'quantity', 'unit_price')
    list_filter = ('trade_type', 'year', 'month', 'stock_name')
    search_fields = ('stock_name',)


@admin.register(StockSymbol)
class StockSymbolAdmin(admin.ModelAdmin):
    list_display = ('stock_name', 'ticker', 'note', 'updated_at')
    search_fields = ('stock_name', 'ticker', 'note')
