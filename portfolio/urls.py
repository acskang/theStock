from django.urls import path

from .views import PortfolioSummaryAPIView

urlpatterns = [
    path("summary/", PortfolioSummaryAPIView.as_view(), name="portfolio-summary"),
]
