from django.contrib import admin
from django.urls import include, path
from data_pipeline.views import (
    TossOrderHistoryAPIView,
    TossOrderHistoryReconciliationAPIView,
    toss_customer_info_page,
    toss_order_history_page,
    toss_order_history_reconciliation_page,
)
from portfolio import views

from .api_docs import ApiDocsView, schema_view
from .monitoring import healthz, readyz

urlpatterns = [
    path('admin/', admin.site.urls),
    path("accounts/", include("platform_auth.urls")),
    path("accounts/", include("django.contrib.auth.urls")),
    path("healthz/", healthz, name="healthz"),
    path("readyz/", readyz, name="readyz"),
    path("api/schema/", schema_view, name="api-schema"),
    path("api/docs/", ApiDocsView.as_view(), name="api-docs"),
    path('api/stocks/', include('stocks.urls')),
    path('api/holdings/', include('holdings.urls')),
    path('api/marketdata/', include('marketdata.urls')),
    path('api/indicators/', include('indicators.urls')),
    path('api/decisions/', include('decisions.urls')),
    path("api/portfolio/", include("portfolio.urls")),
    path("api/data-pipeline/", include("data_pipeline.urls")),
    path(
        "api/operations/toss/order-history/",
        TossOrderHistoryAPIView.as_view(),
        name="toss-order-history",
    ),
    path(
        "api/operations/toss/order-history/reconciliation/",
        TossOrderHistoryReconciliationAPIView.as_view(),
        name="toss-order-history-reconciliation",
    ),
    path('', views.landing_page, name='dashboard'),
    path('workspace/', views.dashboard, name='workspace_dashboard'),
    path('transactions/', views.transaction_list, name='transaction_list'),
    path('transactions/create/', views.transaction_create, name='transaction_create'),
    path('transactions/<int:pk>/edit/', views.transaction_edit, name='transaction_edit'),
    path('transactions/<int:pk>/delete/', views.transaction_delete, name='transaction_delete'),
    path('upload/', views.upload_csv, name='upload_csv'),
    path('prices/', views.price_board, name='price_board'),
    path('analysis/', views.analysis_view, name='analysis_view'),
    path('portfolio/summary/', views.portfolio_summary_page, name='portfolio_summary_page'),
    path("manual/", views.manual_page, name="manual_page"),
    path("manual/docs/<path:doc_path>/", views.manual_page, name="manual_view"),
    path("manual/raw/<path:doc_path>/", views.manual_raw, name="manual_raw"),
    path('consulting/holdings/', views.consulting_holding_list, name='consulting_holding_list'),
    path('consulting/holdings/<int:pk>/', views.holding_consult_page, name='holding_consult_page'),
    path('operations/data-pipeline/', views.data_pipeline_status_page, name='data_pipeline_status_page'),
    path(
        'operations/data-pipeline/stocks/<str:stock_code>/',
        views.data_pipeline_stock_detail_page,
        name='data_pipeline_stock_detail_page',
    ),
    path(
        'operations/data-pipeline/providers/<str:provider>/<str:data_type>/',
        views.data_pipeline_provider_detail_page,
        name='data_pipeline_provider_detail_page',
    ),
    path(
        "operations/toss/customer-info/",
        toss_customer_info_page,
        name="toss-customer-info-page",
    ),
    path(
        "operations/toss/order-history/",
        toss_order_history_page,
        name="toss-order-history-page",
    ),
    path(
        "operations/toss/order-history/reconciliation/",
        toss_order_history_reconciliation_page,
        name="toss-order-history-reconciliation-page",
    ),
    path('symbols/', views.symbol_list, name='symbol_list'),
    path('symbols/create/', views.symbol_create, name='symbol_create'),
    path('symbols/<int:pk>/edit/', views.symbol_edit, name='symbol_edit'),
    path('symbols/<int:pk>/delete/', views.symbol_delete, name='symbol_delete'),
    path('api/charts/summary/', views.chart_summary_api, name='chart_summary_api'),
]
