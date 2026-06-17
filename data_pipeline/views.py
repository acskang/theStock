from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from rest_framework import generics, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from stock_service.openapi import RequestResponseAutoSchema

from .models import DataIngestionLog, DataProviderStatus, DataQualitySnapshot
from .providers import get_provider
from .providers.toss_exceptions import (
    TossAuthError,
    TossConfigurationError,
    TossOpenApiError,
    TossProviderDisabled,
    TossRateLimitError,
)
from .serializers import (
    DataIngestionLogSerializer,
    DataPipelineSummarySerializer,
    DataProviderStatusSerializer,
    DataQualitySnapshotSerializer,
    TossOrderHistoryQuerySerializer,
    TossOrderHistoryReconciliationQuerySerializer,
)
from .services.order_history_reconciliation_service import (
    OrderHistoryReconciliationError,
    build_order_history_reconciliation,
)
from .services.summary_service import build_data_pipeline_summary


FORBIDDEN_ORDER_HISTORY_KEYS = {
    "orderid",
    "clientorderid",
    "accountno",
    "account",
    "accountseq",
    "x-tossinvest-account",
    "authorization",
    "access_token",
    "accesstoken",
    "client_secret",
    "clientsecret",
    "raw",
    "rawsummary",
    "raw_response",
    "rawresponse",
    "headers",
    "header",
    "request",
    "response",
    "token",
    "secret",
    "nextcursor",
    "next_cursor",
    "cursor",
    "userid",
    "user_id",
    "username",
    "email",
}


def _build_toss_order_history_provider():
    return get_provider("toss")


def _build_toss_accounts_provider():
    return get_provider("toss")


def _date_to_api_string(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _sanitize_order_history_payload(value):
    if isinstance(value, list):
        return [_sanitize_order_history_payload(item) for item in value]
    if not isinstance(value, dict):
        return value

    sanitized = {}
    for key, item in value.items():
        key_text = str(key)
        normalized_key = key_text.replace("_", "").replace("-", "").lower()
        if key_text.lower() in FORBIDDEN_ORDER_HISTORY_KEYS or normalized_key in FORBIDDEN_ORDER_HISTORY_KEYS:
            continue
        sanitized[key] = _sanitize_order_history_payload(item)
    return sanitized


def _sanitize_order_history_result(result):
    safe_payload = _sanitize_order_history_payload(result)
    if isinstance(safe_payload, dict):
        safe_payload.pop("account_diagnostic", None)
        safe_payload.pop("account_source", None)
        safe_payload.pop("account_fallback_used", None)
        safe_payload.pop("account_header_configured", None)
    return safe_payload


def _sanitize_toss_accounts_result(result):
    safe_payload = _sanitize_order_history_payload(result)
    if not isinstance(safe_payload, dict):
        return safe_payload
    safe_payload.pop("raw", None)
    return safe_payload


def _safe_order_history_error(error, message, http_status):
    return Response({"error": error, "message": message}, status=http_status)


def _order_history_error_context(error, message):
    return {"code": error, "message": message}


def _map_order_history_exception(exc):
    if isinstance(exc, TossProviderDisabled):
        return _order_history_error_context("provider_disabled", "Toss provider is disabled.")
    if isinstance(exc, TossConfigurationError):
        return _order_history_error_context("configuration_error", "Toss provider is not configured.")
    if isinstance(exc, TossAuthError):
        return _order_history_error_context("authentication_failed", "Toss authentication failed.")
    if isinstance(exc, TossRateLimitError):
        return _order_history_error_context("rate_limit_exceeded", "Toss rate limit was exceeded.")
    if isinstance(exc, TossOpenApiError):
        return _order_history_error_context("order_history_request_failed", "Toss order history request failed.")
    return _order_history_error_context("order_history_request_failed", "Toss order history request failed.")


def _map_toss_accounts_exception(exc):
    if isinstance(exc, TossProviderDisabled):
        return _order_history_error_context("provider_disabled", "Toss provider is disabled.")
    if isinstance(exc, TossConfigurationError):
        return _order_history_error_context("configuration_error", "Toss provider is not configured.")
    if isinstance(exc, TossAuthError):
        return _order_history_error_context("authentication_failed", "Toss authentication failed.")
    if isinstance(exc, TossRateLimitError):
        return _order_history_error_context("rate_limit_exceeded", "Toss rate limit was exceeded.")
    if isinstance(exc, TossOpenApiError):
        return _order_history_error_context("toss_accounts_request_failed", "Toss accounts request failed.")
    return _order_history_error_context("toss_accounts_request_failed", "Toss accounts request failed.")


class DataQualitySnapshotDetailAPIView(generics.RetrieveAPIView):
    serializer_class = DataQualitySnapshotSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = "stock__code"
    lookup_url_kwarg = "stock_code"

    def get_queryset(self):
        return DataQualitySnapshot.objects.select_related("stock").order_by("stock__code", "-as_of_date")

    def get_object(self):
        stock_code = self.kwargs[self.lookup_url_kwarg]
        snapshot = self.get_queryset().filter(stock__code=stock_code).first()
        if snapshot is None:
            raise NotFound()
        return snapshot


class DataPipelineSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated]
    response_serializer_class = DataPipelineSummarySerializer
    response_status_code = 200
    schema = RequestResponseAutoSchema(operation_id_base="DataPipelineSummary")

    def get(self, request):
        serializer = DataPipelineSummarySerializer(build_data_pipeline_summary())
        return Response(serializer.data, status=status.HTTP_200_OK)


class TossOrderHistoryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not bool(getattr(request.user, "is_staff", False)):
            return _safe_order_history_error(
                "staff_required",
                "Staff permission is required.",
                status.HTTP_403_FORBIDDEN,
            )

        query_serializer = TossOrderHistoryQuerySerializer(data=request.query_params)
        if not query_serializer.is_valid():
            return Response(
                {"error": "invalid_query", "message": "Order history query is invalid.", "fields": query_serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        params = query_serializer.validated_data
        try:
            provider = _build_toss_order_history_provider()
            result = provider.get_order_history_candidates(
                status=params.get("status") or "CLOSED",
                symbol=params.get("symbol") or None,
                from_date=_date_to_api_string(params.get("from_date")),
                to_date=_date_to_api_string(params.get("to_date")),
                cursor=params.get("cursor") or None,
                limit=params.get("limit") or 20,
            )
        except TossProviderDisabled:
            return _safe_order_history_error(
                "provider_disabled",
                "Toss provider is disabled.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except TossConfigurationError:
            return _safe_order_history_error(
                "configuration_error",
                "Toss provider is not configured.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except TossAuthError:
            return _safe_order_history_error(
                "authentication_failed",
                "Toss authentication failed.",
                status.HTTP_502_BAD_GATEWAY,
            )
        except TossRateLimitError:
            return _safe_order_history_error(
                "rate_limit_exceeded",
                "Toss rate limit was exceeded.",
                status.HTTP_429_TOO_MANY_REQUESTS,
            )
        except TossOpenApiError:
            return _safe_order_history_error(
                "order_history_request_failed",
                "Toss order history request failed.",
                status.HTTP_502_BAD_GATEWAY,
            )
        except Exception:
            return _safe_order_history_error(
                "order_history_request_failed",
                "Toss order history request failed.",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        safe_payload = _sanitize_order_history_result(result)
        return Response(safe_payload, status=status.HTTP_200_OK)


class TossOrderHistoryReconciliationAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not bool(getattr(request.user, "is_staff", False)):
            return _safe_order_history_error(
                "staff_required",
                "Staff permission is required.",
                status.HTTP_403_FORBIDDEN,
            )

        query_serializer = TossOrderHistoryReconciliationQuerySerializer(data=request.query_params)
        if not query_serializer.is_valid():
            return Response(
                {
                    "error": "invalid_query",
                    "message": "Order history reconciliation query is invalid.",
                    "fields": query_serializer.errors,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        params = query_serializer.validated_data
        try:
            provider = _build_toss_order_history_provider()
            result = build_order_history_reconciliation(
                provider=provider,
                symbol=params["symbol"],
                from_date=_date_to_api_string(params.get("from_date")) or None,
                to_date=_date_to_api_string(params.get("to_date")) or None,
                limit=params.get("limit") or 20,
            )
        except OrderHistoryReconciliationError as exc:
            return _safe_order_history_error(exc.code, exc.message, status.HTTP_400_BAD_REQUEST)
        except Exception:
            return _safe_order_history_error(
                "order_history_reconciliation_failed",
                "Order history reconciliation failed.",
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        safe_payload = _sanitize_order_history_result(result)
        return Response(safe_payload, status=status.HTTP_200_OK)


@login_required
def toss_order_history_page(request):
    if not bool(getattr(request.user, "is_staff", False)):
        raise PermissionDenied("Staff permission is required.")

    run_requested = request.GET.get("run") == "1"
    query = {
        "status": request.GET.get("status", "CLOSED") or "CLOSED",
        "symbol": request.GET.get("symbol", ""),
        "from_date": request.GET.get("from_date", ""),
        "to_date": request.GET.get("to_date", ""),
        "limit": request.GET.get("limit", "20") or "20",
    }
    context = {
        "query": query,
        "run_requested": run_requested,
        "result": None,
        "error": None,
        "network_call": False,
        "dry_run": True,
        "read_only": True,
        "order_execution": False,
    }

    if not run_requested:
        return render(request, "data_pipeline/toss_order_history.html", context)

    query_serializer = TossOrderHistoryQuerySerializer(data=request.GET)
    if not query_serializer.is_valid():
        context["error"] = {
            "code": "invalid_query",
            "message": "Order history query is invalid.",
            "fields": query_serializer.errors,
        }
        return render(request, "data_pipeline/toss_order_history.html", context)

    params = query_serializer.validated_data
    query.update(
        {
            "status": params.get("status") or "CLOSED",
            "symbol": params.get("symbol") or "",
            "from_date": _date_to_api_string(params.get("from_date")) or "",
            "to_date": _date_to_api_string(params.get("to_date")) or "",
            "limit": str(params.get("limit") or 20),
        }
    )
    try:
        provider = _build_toss_order_history_provider()
        result = provider.get_order_history_candidates(
            status=params.get("status") or "CLOSED",
            symbol=params.get("symbol") or None,
            from_date=_date_to_api_string(params.get("from_date")),
            to_date=_date_to_api_string(params.get("to_date")),
            cursor=params.get("cursor") or None,
            limit=params.get("limit") or 20,
        )
    except Exception as exc:
        context["query"] = query
        context["error"] = _map_order_history_exception(exc)
        return render(request, "data_pipeline/toss_order_history.html", context)

    safe_result = _sanitize_order_history_result(result)
    context["query"] = query
    context["result"] = safe_result
    context["network_call"] = bool(safe_result.get("network_call")) if isinstance(safe_result, dict) else False
    context["dry_run"] = bool(safe_result.get("dry_run")) if isinstance(safe_result, dict) else True
    return render(request, "data_pipeline/toss_order_history.html", context)


@login_required
def toss_customer_info_page(request):
    if not bool(getattr(request.user, "is_staff", False)):
        raise PermissionDenied("Staff permission is required.")

    run_requested = request.GET.get("run") == "1"
    context = {
        "run_requested": run_requested,
        "result": None,
        "error": None,
        "network_call": False,
        "dry_run": True,
        "read_only": True,
        "order_execution": False,
    }

    if not run_requested:
        return render(request, "data_pipeline/toss_customer_info.html", context)

    try:
        provider = _build_toss_accounts_provider()
        result = provider.get_accounts()
    except Exception as exc:
        context["error"] = _map_toss_accounts_exception(exc)
        return render(request, "data_pipeline/toss_customer_info.html", context)

    context["result"] = _sanitize_toss_accounts_result(result)
    context["network_call"] = True
    return render(request, "data_pipeline/toss_customer_info.html", context)


@login_required
def toss_order_history_reconciliation_page(request):
    if not bool(getattr(request.user, "is_staff", False)):
        raise PermissionDenied("Staff permission is required.")

    run_requested = request.GET.get("run") == "1"
    query = {
        "symbol": request.GET.get("symbol", ""),
        "from_date": request.GET.get("from_date", ""),
        "to_date": request.GET.get("to_date", ""),
        "limit": request.GET.get("limit", "20") or "20",
    }
    context = {
        "query": query,
        "run_requested": run_requested,
        "result": None,
        "error": None,
        "network_call": False,
        "read_only": True,
        "order_execution": False,
    }

    if not run_requested:
        return render(request, "data_pipeline/toss_order_history_reconciliation.html", context)

    query_serializer = TossOrderHistoryReconciliationQuerySerializer(data=request.GET)
    if not query_serializer.is_valid():
        context["error"] = {
            "code": "invalid_query",
            "message": "Order history reconciliation query is invalid.",
        }
        return render(request, "data_pipeline/toss_order_history_reconciliation.html", context)

    params = query_serializer.validated_data
    query.update(
        {
            "symbol": params["symbol"],
            "from_date": _date_to_api_string(params.get("from_date")) or "",
            "to_date": _date_to_api_string(params.get("to_date")) or "",
            "limit": str(params.get("limit") or 20),
        }
    )
    context["query"] = query

    try:
        provider = _build_toss_order_history_provider()
        result = build_order_history_reconciliation(
            provider=provider,
            symbol=params["symbol"],
            from_date=_date_to_api_string(params.get("from_date")) or None,
            to_date=_date_to_api_string(params.get("to_date")) or None,
            limit=params.get("limit") or 20,
        )
    except OrderHistoryReconciliationError as exc:
        context["error"] = {"code": exc.code, "message": exc.message}
        return render(request, "data_pipeline/toss_order_history_reconciliation.html", context)
    except Exception:
        context["error"] = {
            "code": "order_history_reconciliation_failed",
            "message": "Order history reconciliation failed.",
        }
        return render(request, "data_pipeline/toss_order_history_reconciliation.html", context)

    context["result"] = _sanitize_order_history_result(result)
    context["network_call"] = True
    return render(request, "data_pipeline/toss_order_history_reconciliation.html", context)


class DataIngestionLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DataIngestionLog.objects.all()
    serializer_class = DataIngestionLogSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = (
        "status",
        "job_name",
        "job_type",
        "provider",
        "provider_name",
        "target_type",
        "target_code",
        "target_symbol",
        "market",
        "endpoint_name",
        "network_call",
        "dry_run",
        "commit_mode",
        "safe_reason",
        "error_code",
        "http_status_code",
    )
    ordering_fields = (
        "started_at",
        "finished_at",
        "created_at",
        "status",
        "provider",
        "provider_name",
        "job_type",
        "target_type",
        "target_symbol",
        "candidate_count",
        "saved_count",
        "updated_count",
        "skipped_count",
        "failed_count",
        "duration_ms",
        "http_status_code",
    )


class DataProviderStatusViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DataProviderStatus.objects.all()
    serializer_class = DataProviderStatusSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ("provider", "data_type", "is_active")
    ordering_fields = ("provider", "data_type", "updated_at", "consecutive_failures")
