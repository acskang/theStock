import time
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urljoin

from django.conf import settings

from .toss_exceptions import TossAuthError, TossConfigurationError, TossProviderDisabled, TossRateLimitError
from .toss_masking import is_configured, mask_secret

DEFAULT_TOKEN_PATH = "/oauth2/token"


@dataclass(frozen=True)
class TossToken:
    access_token: str
    token_type: str
    expires_in: int
    issued_at: float

    @property
    def expires_at(self) -> float:
        return self.issued_at + self.expires_in

    def is_expired(self, *, skew_seconds: int = 60) -> bool:
        return time.time() >= self.expires_at - max(int(skew_seconds), 0)

    def __repr__(self) -> str:
        return (
            "TossToken("
            f"access_token='{mask_secret(self.access_token)}', "
            f"token_type='{self.token_type}', "
            f"expires_in={self.expires_in}, "
            f"issued_at={self.issued_at!r}"
            ")"
        )


def is_toss_provider_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def get_toss_base_url() -> str:
    base_url = str(getattr(settings, "TOSS_INVEST_BASE_URL", "https://openapi.tossinvest.com")).strip()
    if not base_url:
        raise TossConfigurationError("Toss base URL is not configured.")
    return base_url.rstrip("/")


def get_toss_token_url() -> str:
    token_url = str(getattr(settings, "TOSS_INVEST_TOKEN_URL", "")).strip()
    if token_url:
        return token_url
    return urljoin(f"{get_toss_base_url()}/", DEFAULT_TOKEN_PATH.lstrip("/"))


def validate_toss_auth_settings() -> None:
    if not is_toss_provider_enabled(getattr(settings, "TOSS_INVEST_PROVIDER_ENABLED", False)):
        raise TossProviderDisabled("Toss provider is disabled.")
    if not is_configured(getattr(settings, "TOSS_INVEST_CLIENT_ID", "")):
        raise TossConfigurationError("Toss client id is not configured.")
    if not is_configured(getattr(settings, "TOSS_INVEST_CLIENT_SECRET", "")):
        raise TossConfigurationError("Toss client secret is not configured.")


def issue_toss_access_token(*, transport=None, now=None) -> TossToken:
    validate_toss_auth_settings()
    if transport is None:
        raise TossConfigurationError("Toss auth transport is not configured.")

    token_url = get_toss_token_url()
    client_id = getattr(settings, "TOSS_INVEST_CLIENT_ID", "")
    client_secret = getattr(settings, "TOSS_INVEST_CLIENT_SECRET", "")
    timeout_seconds = int(getattr(settings, "TOSS_REQUEST_TIMEOUT_SECONDS", 10))

    response = transport(
        "POST",
        token_url,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=timeout_seconds,
    )
    status_code, payload = _normalize_token_response(response)

    if status_code == 429:
        raise TossRateLimitError("Toss token request was rate limited.")
    if status_code != 200:
        raise TossAuthError(f"Toss token request failed with status {status_code}.")

    access_token = str(payload.get("access_token", "")).strip()
    if not access_token:
        raise TossAuthError("Toss token response did not include an access token.")
    if "expires_in" not in payload:
        raise TossAuthError("Toss token response did not include expires_in.")

    try:
        expires_in = int(payload["expires_in"])
    except (TypeError, ValueError) as exc:
        raise TossAuthError("Toss token response included invalid expires_in.") from exc

    token_type = str(payload.get("token_type") or "Bearer")
    issued_at = float(now() if callable(now) else time.time())
    return TossToken(
        access_token=access_token,
        token_type=token_type,
        expires_in=expires_in,
        issued_at=issued_at,
    )


def _normalize_token_response(response: Any) -> tuple[int, Mapping[str, Any]]:
    if isinstance(response, Mapping):
        return int(response.get("status_code", 200)), response

    status_code = int(getattr(response, "status_code", 200))
    if not hasattr(response, "json"):
        raise TossAuthError("Toss token response could not be parsed.")

    payload = response.json()
    if not isinstance(payload, Mapping):
        raise TossAuthError("Toss token response body was invalid.")
    return status_code, payload
