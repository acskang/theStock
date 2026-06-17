import logging

from django.shortcuts import get_object_or_404
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.schemas.openapi import AutoSchema
from rest_framework.views import APIView

from stock_service.logging_context import set_request_context
from stock_service.openapi import RequestResponseAutoSchema
from decisions.models import AveragingDecision
from decisions.serializers import (
    AveragingDecisionListSerializer,
    AveragingDecisionSerializer,
    AveragingProbabilityRecordSerializer,
    AveragingProbabilityResultSerializer,
    HoldingConsultResponseSerializer,
    HoldingConsultRecordSerializer,
    AveragingProbabilityScenarioSerializer,
    HoldingConsultRequestSerializer,
)
from decisions.services.averaging_decision_service import (
    create_decision_from_result,
    evaluate_averaging_timing,
)
from decisions.services.additional_buy_simulation_service import (
    AdditionalBuySimulationError,
    build_additional_buy_simulation,
)
from decisions.services.consulting_service import build_consult_response, consult_holding
from decisions.services.persistence_service import create_consult_record, create_probability_record
from decisions.services.probability_dataclasses import AveragingScenario
from decisions.services.probability_service import calculate_averaging_success_failure_probability
from decisions.models import AveragingProbabilityRecord, HoldingConsultRecord

from .models import UserHolding
from .serializers import AdditionalBuySimulationInputSerializer, UserHoldingSerializer

logger = logging.getLogger(__name__)


def _get_owned_holding(user, pk):
    return get_object_or_404(
        UserHolding.objects.select_related("stock"),
        id=pk,
        user=user,
    )


def _inactive_holding_response():
    return Response(
        {"detail": "Inactive holding cannot be evaluated."},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _simulation_serializer_error_response(errors):
    error = errors.get("error")
    message = errors.get("message")
    if isinstance(error, list) and error:
        error = str(error[0])
    if isinstance(message, list) and message:
        message = str(message[0])
    if error and message:
        return Response({"error": error, "message": message}, status=status.HTTP_400_BAD_REQUEST)

    detail = errors.get("non_field_errors")
    if detail and isinstance(detail, list) and detail:
        item = detail[0]
        if isinstance(item, dict):
            return Response(item, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        {"error": "invalid_input", "message": "additional buy simulation input is invalid.", "fields": errors},
        status=status.HTTP_400_BAD_REQUEST,
    )


class UserHoldingViewSet(viewsets.ModelViewSet):
    serializer_class = UserHoldingSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ("stock", "risk_level", "is_active")
    search_fields = ("stock__code", "stock__name", "memo")
    ordering_fields = ("created_at", "updated_at", "quantity", "average_price")

    def get_queryset(self):
        queryset = (
            UserHolding.objects.filter(user=self.request.user)
            .select_related("stock", "user")
            .order_by("-updated_at", "-id")
        )
        if self.request.query_params.get("include_inactive", "").lower() != "true" and "is_active" not in self.request.query_params:
            queryset = queryset.filter(is_active=True)
        return queryset

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=["post"], url_path="additional-buy-simulation")
    def additional_buy_simulation(self, request, pk=None):
        holding = _get_owned_holding(request.user, pk)
        if not holding.is_active or holding.quantity <= 0:
            return Response(
                {"error": "inactive_holding", "message": "inactive holding cannot be simulated."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = AdditionalBuySimulationInputSerializer(data=request.data)
        if not serializer.is_valid():
            return _simulation_serializer_error_response(serializer.errors)

        try:
            result = build_additional_buy_simulation(
                holding=holding,
                **serializer.validated_data,
            )
        except AdditionalBuySimulationError as exc:
            return Response({"error": exc.code, "message": exc.message}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            logger.exception(
                "Additional buy simulation failed",
                extra={
                    "event": "additional_buy_simulation_error",
                    "holding_id": holding.id,
                    "stock_code": holding.stock.code,
                },
            )
            return Response({"detail": "Internal server error."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return Response(result, status=status.HTTP_200_OK)


class HoldingEvaluateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        holding = _get_owned_holding(request.user, pk)
        set_request_context(user_id=request.user.id)
        logger.info(
            "Averaging decision evaluation requested",
            extra={
                "event": "evaluate_start",
                "user_id": request.user.id,
                "holding_id": holding.id,
                "stock_code": holding.stock.code,
            },
        )
        if not holding.is_active or holding.quantity <= 0:
            logger.warning(
                "Inactive holding evaluation rejected",
                extra={
                    "event": "evaluate_inactive",
                    "user_id": request.user.id,
                    "holding_id": holding.id,
                    "stock_code": holding.stock.code,
                    "status_code": 400,
                },
            )
            return _inactive_holding_response()
        try:
            result = evaluate_averaging_timing(holding)
            decision = create_decision_from_result(holding, result)

            logger.info(
                "Averaging decision evaluated",
                extra={
                    "event": "evaluate",
                    "user_id": request.user.id,
                    "holding_id": holding.id,
                    "stock_code": holding.stock.code,
                    "score": result.score,
                    "grade": result.grade,
                },
            )

            serializer = AveragingDecisionSerializer(decision)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception:
            logger.exception(
                "Averaging decision evaluation failed",
                extra={
                    "event": "evaluate_error",
                    "user_id": request.user.id,
                    "holding_id": holding.id,
                    "stock_code": holding.stock.code,
                },
            )
            return Response({"detail": "Internal server error."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class HoldingDecisionHistoryAPIView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AveragingDecisionListSerializer
    queryset = AveragingDecision.objects.none()
    filter_backends = []
    schema = AutoSchema(operation_id_base="HoldingDecisionHistory")

    def get_queryset(self):
        holding = get_object_or_404(
            UserHolding.objects.select_related("stock").filter(user=self.request.user),
            id=self.kwargs["pk"],
        )
        return AveragingDecision.objects.filter(holding=holding).select_related(
            "holding",
            "holding__stock",
        ).order_by("-created_at")


class HoldingProbabilityAPIView(APIView):
    permission_classes = [IsAuthenticated]
    request_serializer_class = AveragingProbabilityScenarioSerializer
    response_serializer_class = AveragingProbabilityResultSerializer
    response_status_code = 200
    schema = RequestResponseAutoSchema(operation_id_base="HoldingProbability")

    def post(self, request, pk):
        holding = _get_owned_holding(request.user, pk)
        set_request_context(user_id=request.user.id)
        logger.info(
            "Averaging probability evaluation requested",
            extra={
                "event": "probability_start",
                "user_id": request.user.id,
                "holding_id": holding.id,
                "stock_code": holding.stock.code,
            },
        )
        if not holding.is_active or holding.quantity <= 0:
            logger.warning(
                "Inactive holding probability rejected",
                extra={
                    "event": "probability_inactive",
                    "user_id": request.user.id,
                    "holding_id": holding.id,
                    "stock_code": holding.stock.code,
                    "status_code": 400,
                },
            )
            return _inactive_holding_response()
        serializer = AveragingProbabilityScenarioSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        scenario = AveragingScenario(**serializer.validated_data)

        try:
            result = calculate_averaging_success_failure_probability(
                holding=holding,
                scenario=scenario,
            )
        except ValueError as exc:
            logger.warning(
                "Averaging probability validation failed",
                extra={
                    "event": "probability_bad_input",
                    "user_id": request.user.id,
                    "holding_id": holding.id,
                    "stock_code": holding.stock.code,
                    "status_code": 400,
                    "error_type": exc.__class__.__name__,
                },
            )
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception:
            logger.exception(
                "Averaging probability evaluation failed",
                extra={
                    "event": "probability_error",
                    "user_id": request.user.id,
                    "holding_id": holding.id,
                    "stock_code": holding.stock.code,
                },
            )
            return Response({"detail": "Internal server error."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        logger.info(
            "Averaging probability calculated",
            extra={
                "event": "probability",
                "user_id": request.user.id,
                "holding_id": holding.id,
                "stock_code": holding.stock.code,
                "success_probability": str(result.success_probability),
                "failure_probability": str(result.failure_probability),
                "confidence": str(result.confidence),
            },
        )
        response_serializer = AveragingProbabilityResultSerializer(result)
        response_payload = response_serializer.data
        create_probability_record(holding, serializer.validated_data, response_payload)
        return Response(response_payload, status=status.HTTP_200_OK)


class HoldingProbabilityHistoryAPIView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = AveragingProbabilityRecordSerializer
    queryset = AveragingProbabilityRecord.objects.none()
    filter_backends = []
    schema = AutoSchema(operation_id_base="HoldingProbabilityHistory")

    def get_queryset(self):
        holding = get_object_or_404(
            UserHolding.objects.select_related("stock").filter(user=self.request.user),
            id=self.kwargs["pk"],
        )
        return AveragingProbabilityRecord.objects.filter(holding=holding).select_related(
            "holding",
            "holding__stock",
        ).order_by("-created_at")


class HoldingConsultAPIView(APIView):
    permission_classes = [IsAuthenticated]
    request_serializer_class = HoldingConsultRequestSerializer
    response_serializer_class = HoldingConsultResponseSerializer
    response_status_code = 200
    schema = RequestResponseAutoSchema(operation_id_base="HoldingConsult")

    def post(self, request, pk):
        holding = _get_owned_holding(request.user, pk)
        set_request_context(user_id=request.user.id)
        logger.info(
            "Holding consulting requested",
            extra={
                "event": "consult_holding_start",
                "user_id": request.user.id,
                "holding_id": holding.id,
                "stock_code": holding.stock.code,
            },
        )
        if not holding.is_active or holding.quantity <= 0:
            logger.warning(
                "Inactive holding consulting rejected",
                extra={
                    "event": "consult_holding_inactive",
                    "user_id": request.user.id,
                    "holding_id": holding.id,
                    "stock_code": holding.stock.code,
                    "status_code": 400,
                },
            )
            return _inactive_holding_response()
        serializer = HoldingConsultRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = consult_holding(holding, **serializer.validated_data)
        except Exception:
            logger.exception(
                "Holding consulting failed",
                extra={
                    "event": "consult_holding_failed",
                    "user_id": request.user.id,
                    "holding_id": pk,
                },
            )
            return Response({"detail": "Internal server error."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        logger.info(
            "Holding consulting calculated",
            extra={
                "event": "consult_holding",
                "user_id": request.user.id,
                "holding_id": holding.id,
                "stock_code": holding.stock.code,
                "final_grade": result.final_grade,
                "risk_gate": result.risk_gate.get("status"),
                "market_regime": result.market_regime.get("regime"),
            },
        )
        response_payload = build_consult_response(holding, result)
        response_serializer = HoldingConsultResponseSerializer(response_payload)
        serialized_payload = response_serializer.data
        create_consult_record(holding, serializer.validated_data, serialized_payload)
        return Response(serialized_payload, status=status.HTTP_200_OK)


class HoldingConsultHistoryAPIView(generics.ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = HoldingConsultRecordSerializer
    queryset = HoldingConsultRecord.objects.none()
    filter_backends = []
    schema = AutoSchema(operation_id_base="HoldingConsultHistory")

    def get_queryset(self):
        holding = get_object_or_404(
            UserHolding.objects.select_related("stock").filter(user=self.request.user),
            id=self.kwargs["pk"],
        )
        return HoldingConsultRecord.objects.filter(holding=holding).select_related(
            "holding",
            "holding__stock",
        ).order_by("-created_at")
