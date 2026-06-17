from rest_framework import viewsets

from stock_service.permissions import AuthenticatedReadOnlyOrStaffWrite

from .models import AveragingDecision, AveragingProbabilityRecord, HoldingConsultRecord, RiskEvent
from .serializers import (
    AveragingDecisionSerializer,
    AveragingProbabilityRecordSerializer,
    HoldingConsultRecordSerializer,
    RiskEventSerializer,
)


class RiskEventViewSet(viewsets.ModelViewSet):
    queryset = RiskEvent.objects.select_related("stock").all()
    serializer_class = RiskEventSerializer
    permission_classes = [AuthenticatedReadOnlyOrStaffWrite]
    filterset_fields = ("stock", "event_type", "risk_level", "is_active")
    search_fields = ("stock__code", "stock__name", "title", "description")
    ordering_fields = ("event_date", "risk_level", "created_at")


class AveragingDecisionViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AveragingDecisionSerializer
    filterset_fields = ("grade", "holding")
    search_fields = ("holding__stock__code", "holding__stock__name", "decision", "reason_summary")
    ordering_fields = ("created_at", "score", "grade")

    def get_queryset(self):
        return AveragingDecision.objects.filter(holding__user=self.request.user).select_related(
            "holding",
            "holding__stock",
            "holding__user",
        )


class AveragingProbabilityRecordViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AveragingProbabilityRecordSerializer
    filterset_fields = ("holding",)
    search_fields = ("holding__stock__code", "holding__stock__name")
    ordering_fields = ("created_at", "success_probability", "failure_probability", "confidence")

    def get_queryset(self):
        return AveragingProbabilityRecord.objects.filter(holding__user=self.request.user).select_related(
            "holding",
            "holding__stock",
            "holding__user",
        )


class HoldingConsultRecordViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = HoldingConsultRecordSerializer
    filterset_fields = ("holding", "final_grade")
    search_fields = ("holding__stock__code", "holding__stock__name", "consulting_status", "summary")
    ordering_fields = ("created_at", "final_grade")

    def get_queryset(self):
        return HoldingConsultRecord.objects.filter(holding__user=self.request.user).select_related(
            "holding",
            "holding__stock",
            "holding__user",
        )
