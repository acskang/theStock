from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urljoin

from django.conf import settings

from .toss_auth import TossToken, get_toss_base_url, issue_toss_access_token
from .toss_exceptions import TossAuthError, TossConfigurationError, TossOpenApiError, TossRateLimitError
from .toss_masking import is_configured, mask_account_id, mask_secret


@dataclass(frozen=True)
class TossApiResponse:
    status_code: int
    data: Any
    headers: Mapping[str, str] | None = None

    def __repr__(self) -> str:
        safe_headers = {}
        for key, value in dict(self.headers or {}).items():
            normalized_key = key.lower()
            if normalized_key == "authorization":
                safe_headers[key] = "Bearer ***masked***"
            elif normalized_key == "x-tossinvest-account":
                safe_headers[key] = mask_account_id(value)
            else:
                safe_headers[key] = value
        return (
            "TossApiResponse("
            f"status_code={self.status_code}, "
            f"data_type='{type(self.data).__name__}', "
            f"headers={safe_headers!r}"
            ")"
        )


class TossOpenApiClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        token_provider=None,
        transport=None,
        timeout_seconds: int | None = None,
    ):
        self.base_url = (base_url or get_toss_base_url()).rstrip("/")
        self.token_provider = token_provider or issue_toss_access_token
        self.transport = transport
        self.timeout_seconds = int(
            timeout_seconds
            if timeout_seconds is not None
            else getattr(settings, "TOSS_REQUEST_TIMEOUT_SECONDS", 10)
        )

    def get_access_token(self) -> TossToken:
        if self.token_provider is issue_toss_access_token:
            token = self.token_provider(transport=self.transport)
        else:
            token = self.token_provider()
        if not isinstance(token, TossToken):
            raise TossAuthError("Toss token provider returned an invalid token.")
        return token

    def build_url(self, path: str) -> str:
        clean_path = str(path).strip()
        if clean_path.lower().startswith(("http://", "https://")):
            raise TossConfigurationError("Absolute Toss API request URLs are not allowed.")
        if not clean_path:
            raise TossConfigurationError("Toss API request path is required.")
        return urljoin(f"{self.base_url}/", clean_path.lstrip("/"))

    def build_headers(
        self,
        *,
        extra_headers: Mapping[str, str] | None = None,
        account_required: bool = False,
        account_id: str | None = None,
    ) -> dict[str, str]:
        token = self.get_access_token()
        headers = {}
        for key, value in dict(extra_headers or {}).items():
            if key.lower() in {"authorization", "x-tossinvest-account"}:
                continue
            headers[key] = value
        headers["Authorization"] = f"{token.token_type or 'Bearer'} {token.access_token}"
        if account_required:
            selected_account_id = account_id or getattr(settings, "TOSS_INVEST_ACCOUNT_ID", "")
            if not is_configured(selected_account_id):
                raise TossConfigurationError("Toss account id is not configured.")
            headers["X-Tossinvest-Account"] = str(selected_account_id).strip()
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Any = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        account_required: bool = False,
        account_id: str | None = None,
    ) -> TossApiResponse:
        if self.transport is None:
            raise TossConfigurationError("Toss API transport is not configured.")

        url = self.build_url(path)
        request_headers = self.build_headers(
            extra_headers=headers,
            account_required=account_required,
            account_id=account_id,
        )
        response = self.transport(
            method,
            url,
            headers=request_headers,
            params=params,
            data=data,
            json=json,
            timeout=self.timeout_seconds,
        )
        api_response = self._normalize_response(response)
        self._raise_for_status(api_response)
        return api_response

    def health_check(self) -> dict[str, Any]:
        return {
            "provider": "toss",
            "base_url": self.base_url,
            "transport_configured": self.transport is not None,
            "token_provider_configured": self.token_provider is not None,
            "client_id_configured": is_configured(getattr(settings, "TOSS_INVEST_CLIENT_ID", "")),
            "client_secret_configured": is_configured(getattr(settings, "TOSS_INVEST_CLIENT_SECRET", "")),
            "status": "configured" if self.transport is not None else "missing_transport",
        }

    def _normalize_response(self, response: Any) -> TossApiResponse:
        if isinstance(response, TossApiResponse):
            return response
        if isinstance(response, Mapping):
            status_code = int(response.get("status_code", 200))
            headers = response.get("headers")
            data = response.get("data", response)
            return TossApiResponse(status_code=status_code, data=data, headers=headers)

        status_code = int(getattr(response, "status_code", 200))
        headers = getattr(response, "headers", None)
        if not hasattr(response, "json"):
            raise TossOpenApiError("Toss API response could not be parsed.")
        try:
            payload = response.json()
        except Exception as exc:
            raise TossOpenApiError("Toss API response JSON parsing failed.") from exc
        return TossApiResponse(status_code=status_code, data=payload, headers=headers)

    def _raise_for_status(self, response: TossApiResponse) -> None:
        status_code = int(response.status_code)
        if 200 <= status_code <= 299:
            return
        error_detail = _extract_safe_error_detail(response.data)
        if status_code in {401, 403}:
            exc = TossAuthError(f"Toss API request failed with auth status {status_code}.")
            _attach_safe_error_detail(exc, status_code=status_code, error_detail=error_detail)
            raise exc
        if status_code == 429:
            exc = TossRateLimitError("Toss API request was rate limited.")
            _attach_safe_error_detail(exc, status_code=status_code, error_detail=error_detail)
            raise exc
        if status_code >= 400:
            exc = TossOpenApiError(f"Toss API request failed with status {status_code}.")
            _attach_safe_error_detail(exc, status_code=status_code, error_detail=error_detail)
            raise exc


def _attach_safe_error_detail(exc: Exception, *, status_code: int, error_detail: dict[str, str]) -> None:
    exc.http_status_code = status_code
    exc.error_code = error_detail.get("error_code", "")
    exc.error_field = error_detail.get("error_field", "")
    exc.safe_message = error_detail.get("safe_message", "")


def _extract_safe_error_detail(data: Any) -> dict[str, str]:
    if not isinstance(data, Mapping):
        return {}

    error = data.get("error")
    source = error if isinstance(error, Mapping) else data

    error_code = _safe_error_text(
        source.get("code")
        or source.get("errorCode")
        or source.get("error_code")
        or source.get("type")
    )
    error_field = _safe_error_text(
        source.get("field")
        or source.get("errorField")
        or source.get("error_field")
        or source.get("parameter")
    )
    safe_message = _safe_error_text(
        source.get("message")
        or source.get("safeMessage")
        or source.get("safe_message")
    )

    return {
        "error_code": error_code,
        "error_field": error_field,
        "safe_message": safe_message,
    }


def _safe_error_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) > 120:
        return ""
    lowered = text.lower()
    forbidden_parts = (
        "authorization",
        "bearer ",
        "access_token",
        "client_secret",
        "x-tossinvest-account",
        "accountno",
        "accountseq",
        "account_no",
        "account_seq",
        "account id",
        "account_id",
    )
    if any(part in lowered for part in forbidden_parts):
        return ""
    return text
