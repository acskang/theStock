from rest_framework.routers import DefaultRouter

from .views import (
    AveragingDecisionViewSet,
    AveragingProbabilityRecordViewSet,
    HoldingConsultRecordViewSet,
    RiskEventViewSet,
)

router = DefaultRouter()
router.register("risk-events", RiskEventViewSet, basename="risk-event")
router.register("averaging-decisions", AveragingDecisionViewSet, basename="averaging-decision")
router.register("probability-records", AveragingProbabilityRecordViewSet, basename="probability-record")
router.register("consult-records", HoldingConsultRecordViewSet, basename="consult-record")

urlpatterns = router.urls
