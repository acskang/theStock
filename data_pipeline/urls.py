from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    DataIngestionLogViewSet,
    DataPipelineSummaryAPIView,
    DataProviderStatusViewSet,
    DataQualitySnapshotDetailAPIView,
)

router = DefaultRouter()
router.register("ingestion-logs", DataIngestionLogViewSet, basename="data-pipeline-ingestion-log")
router.register("provider-status", DataProviderStatusViewSet, basename="data-pipeline-provider-status")

urlpatterns = [
    path(
        "summary/",
        DataPipelineSummaryAPIView.as_view(),
        name="data-pipeline-summary",
    ),
    path(
        "data-quality/<str:stock_code>/",
        DataQualitySnapshotDetailAPIView.as_view(),
        name="data-pipeline-data-quality-detail",
    ),
]

urlpatterns += router.urls
