from __future__ import annotations

import logging
import time
import uuid

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.shortcuts import resolve_url

from stock_service.logging_context import clear_request_context, set_request_context


logger = logging.getLogger(__name__)


class AuthenticationGateMiddleware:
    PUBLIC_PATHS = {
        "/",
        "/healthz/",
        "/readyz/",
        "/favicon.ico",
        "/robots.txt",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        forced_user = getattr(request, "_force_auth_user", None)
        if forced_user is not None or getattr(request.user, "is_authenticated", False) or self._is_public_request(request.path):
            return self.get_response(request)
        return redirect_to_login(request.get_full_path(), resolve_url(settings.LOGIN_URL))

    def _is_public_request(self, path: str) -> bool:
        if path in self.PUBLIC_PATHS:
            return True
        if path.startswith("/api/"):
            return True
        if path.startswith("/accounts/login/") or path.startswith("/accounts/signup/"):
            return True
        if path.startswith("/admin/login/"):
            return True
        for prefix in (self._normalize_prefix(settings.STATIC_URL), self._normalize_prefix(settings.MEDIA_URL)):
            if prefix and path.startswith(prefix):
                return True
        return False

    def _normalize_prefix(self, value: str) -> str:
        prefix = str(value or "").strip()
        if not prefix:
            return ""
        if not prefix.startswith("/"):
            prefix = f"/{prefix}"
        return prefix


class RequestLogContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        start_time = time.monotonic()
        user_id = self._extract_user_id(request)
        set_request_context(
            request_id=request_id,
            user_id=user_id,
            method=request.method,
            path=request.path,
        )

        try:
            response = self.get_response(request)
        except Exception as exc:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            logger.exception(
                "Request failed",
                extra={
                    "event": "request_failed",
                    "status_code": 500,
                    "duration_ms": duration_ms,
                    "error_type": exc.__class__.__name__,
                    "user_id": self._extract_user_id(request),
                },
            )
            raise
        else:
            duration_ms = int((time.monotonic() - start_time) * 1000)
            response["X-Request-ID"] = request_id
            set_request_context(user_id=self._extract_user_id(request))
            self._log_response(request, response.status_code, duration_ms)
            return response
        finally:
            clear_request_context()

    def _log_response(self, request, status_code: int, duration_ms: int):
        log_method = logger.info
        if status_code >= 500:
            log_method = logger.error
        elif status_code >= 400:
            log_method = logger.warning

        log_method(
            "Request completed",
            extra={
                "event": "request_complete",
                "status_code": status_code,
                "duration_ms": duration_ms,
                "user_id": self._extract_user_id(request),
            },
        )

    def _extract_user_id(self, request):
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return "-"
        return user.id
