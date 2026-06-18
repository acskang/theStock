from django.urls import path

from integrations import views


app_name = "integrations"

urlpatterns = [
    path("toss/", views.toss_dashboard, name="toss_dashboard"),
    path("toss/dashboard/holdings/", views.toss_dashboard_holdings, name="toss_dashboard_holdings"),
    path("toss/dashboard/orders/", views.toss_dashboard_orders, name="toss_dashboard_orders"),
    path("toss/trading-info/", views.toss_trading_info, name="toss_trading_info"),
    path("toss/trading-info/account/", views.toss_account_trading_info, name="toss_account_trading_info"),
    path("toss/trading-info/sellable/", views.toss_sellable_quantity, name="toss_sellable_quantity"),
    path("toss/market/", views.toss_market_explorer, name="toss_market_explorer"),
    path("toss/market/local-search/", views.toss_market_local_search, name="toss_market_local_search"),
    path("toss/market/quotes/", views.toss_market_quotes, name="toss_market_quotes"),
    path("toss/market/detail/", views.toss_market_symbol_detail, name="toss_market_symbol_detail"),
    path("toss/market/candles/", views.toss_market_candles, name="toss_market_candles"),
    path("toss/market/exchange-rate/", views.toss_market_exchange_rate, name="toss_market_exchange_rate"),
    path("toss/trades/sync/", views.toss_trade_sync_page, name="toss_trade_sync"),
    path("toss/trades/sync/run/", views.toss_trade_sync_run, name="toss_trade_sync_run"),
    path("toss/credentials/", views.toss_credential_settings, name="toss_credential_settings"),
    path("toss/credentials/save/", views.toss_credential_save, name="toss_credential_save"),
    path("toss/credentials/reveal/", views.toss_credential_reveal, name="toss_credential_reveal"),
    path("toss/credentials/verify/", views.toss_credential_verify, name="toss_credential_verify"),
    path("toss/credentials/reset/", views.toss_credential_reset, name="toss_credential_reset"),
    path(
        "toss/credentials/disconnect/",
        views.toss_credential_disconnect,
        name="toss_credential_disconnect",
    ),
    path("toss/holdings/dry-run/", views.toss_holdings_dry_run, name="toss_holdings_dry_run"),
    path("toss/holdings/apply/", views.toss_holdings_apply, name="toss_holdings_apply"),
    path("toss/orders/", views.toss_order_history, name="toss_order_history"),
]
