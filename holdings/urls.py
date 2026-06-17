from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    HoldingConsultAPIView,
    HoldingConsultHistoryAPIView,
    HoldingDecisionHistoryAPIView,
    HoldingEvaluateAPIView,
    HoldingProbabilityAPIView,
    HoldingProbabilityHistoryAPIView,
    UserHoldingViewSet,
)

router = DefaultRouter()
router.register("", UserHoldingViewSet, basename="holding")

urlpatterns = [
    path("<int:pk>/evaluate/", HoldingEvaluateAPIView.as_view(), name="holding-evaluate"),
    path("<int:pk>/decisions/", HoldingDecisionHistoryAPIView.as_view(), name="holding-decisions"),
    path("<int:pk>/probability/", HoldingProbabilityAPIView.as_view(), name="holding-probability"),
    path("<int:pk>/probabilities/", HoldingProbabilityHistoryAPIView.as_view(), name="holding-probabilities"),
    path("<int:pk>/consult/", HoldingConsultAPIView.as_view(), name="holding-consult"),
    path("<int:pk>/consults/", HoldingConsultHistoryAPIView.as_view(), name="holding-consults"),
]

urlpatterns += router.urls
