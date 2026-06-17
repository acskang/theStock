from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from django.utils import timezone

from data_pipeline.models import DataIngestionLog

logger = logging.getLogger(__name__)

_SAFE_METADATA_KEYS = {
    "command",
    "provider",
    "symbol",
    "market",
    "endpoint_name",
    "interval",
    "count",
    "adjusted",
    "network_call",
    "dry_run",
    "commit_mode",
    "update_existing",
    "provider_path",
    "registry_path",
    "provider_registered",
    "order_execution_enabled",
    "candidate_count",
    "saved_count",
    "updated_count",
    "skipped_count",
    "failed_count",
    "http_status_code",
    "error_code",
    "error_field",
    "params_shape",
    "safe_message",
}
_FORBIDDEN_KEY_PARTS = (
    "authorization",
    "access_token",
    "client_id",
    "client_secret",
    "secret",
    "account",
    "x-tossinvest-account",
    "header",
    "headers",
    "request_body",
    "request_headers",
    "response_body",
    "raw_response",
    "raw_token_response",
)
_SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9_.-]{8,}", re.IGNORECASE),
    re.compile(r"access_token\s*[:=]\s*[A-Za-z0-9_.-]{8,}", re.IGNORECASE),
    re.compile(r"client_secret\s*[:=]\s*[A-Za-z0-9_.-]{8,}", re.IGNORECASE),
    re.compile(r"account[_-]?id\s*[:=]\s*[A-Za-z0-9_.-]{6,}", re.IGNORECASE),
)
_CODE_PATTERN = re.compile(r"[^a-z0-9_.-]+")


def record_data_ingestion_log(
    *,
    provider_name: str = "",
    job_type: str = "",
    target_type: str = "",
    target_symbol: str = "",
    market: str = "",
    endpoint_name: str = "",
    status: str = "",
    safe_reason: str = "",
    error_code: str = "",
    http_status_code: int | None = None,
    network_call: bool = False,
    dry_run: bool = True,
    commit_mode: str = "",
    candidate_count: int = 0,
    saved_count: int = 0,
    updated_count: int = 0,
    skipped_count: int = 0,
    failed_count: int = 0,
    duration_ms: int | None = None,
    metadata: dict | None = None,
    details: dict | None = None,
    started_at=None,
    finished_at=None,
    raise_errors: bool = False,
):
    try:
        cleaned_metadata = _clean_mapping(metadata)
        cleaned_details = _clean_mapping(details)
        normalized_status = _normalize_status(status)
        normalized_target_type = _normalize_target_type(target_type)
        normalized_counts = {
            "candidate_count": _non_negative_int(candidate_count),
            "saved_count": _non_negative_int(saved_count),
            "updated_count": _non_negative_int(updated_count),
            "skipped_count": _non_negative_int(skipped_count),
            "failed_count": _non_negative_int(failed_count),
        }
        total_count = _derive_total_count(**normalized_counts)
        success_count = _derive_success_count(
            status=normalized_status,
            saved_count=normalized_counts["saved_count"],
            updated_count=normalized_counts["updated_count"],
            total_count=total_count,
        )

        provider = _clean_text(provider_name, max_length=50) or "unknown"
        symbol = _clean_text(target_symbol, max_length=50)
        command = _clean_text(cleaned_metadata.get("command", ""), max_length=100)
        job_name = command or _derive_job_name(job_type=job_type, endpoint_name=endpoint_name)
        now = timezone.now()

        return DataIngestionLog.objects.create(
            job_name=job_name,
            job_type=_clean_text(job_type, max_length=50),
            provider=provider,
            provider_name=provider,
            target_type=normalized_target_type,
            target_code=symbol,
            target_symbol=symbol,
            market=_clean_text(market, max_length=20),
            endpoint_name=_normalize_endpoint_name(endpoint_name),
            status=normalized_status,
            safe_reason=_normalize_code(safe_reason, max_length=100),
            error_code=_normalize_code(error_code, max_length=100),
            http_status_code=_normalize_http_status_code(http_status_code),
            network_call=bool(network_call),
            dry_run=bool(dry_run),
            commit_mode=_normalize_code(commit_mode, max_length=30),
            started_at=started_at or now,
            finished_at=finished_at,
            total_count=total_count,
            success_count=success_count,
            failed_count=normalized_counts["failed_count"],
            skipped_count=normalized_counts["skipped_count"],
            candidate_count=normalized_counts["candidate_count"],
            saved_count=normalized_counts["saved_count"],
            updated_count=normalized_counts["updated_count"],
            duration_ms=_normalize_optional_int(duration_ms),
            error_message=_error_message_from_reason(safe_reason, error_code),
            metadata=cleaned_metadata,
            details=cleaned_details,
        )
    except Exception:
        logger.warning("data_ingestion_log_record_failed")
        if raise_errors:
            raise
        return None


def _clean_mapping(value: dict | None) -> dict:
    if not isinstance(value, Mapping):
        return {}

    cleaned = {}
    for key, item in value.items():
        key_text = _clean_text(str(key), max_length=100)
        key_lower = key_text.lower()
        if key_lower not in _SAFE_METADATA_KEYS or _is_forbidden_key(key_lower):
            continue
        cleaned[key_text] = _clean_value(item)
    return cleaned


def _clean_value(value: Any):
    if isinstance(value, Mapping):
        return _clean_mapping(dict(value))
    if isinstance(value, list | tuple):
        return [_clean_value(item) for item in value[:20]]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return value
    return _redact_sensitive_text(str(value))


def _is_forbidden_key(key: str) -> bool:
    return any(part in key for part in _FORBIDDEN_KEY_PARTS)


def _clean_text(value: Any, *, max_length: int) -> str:
    text = _redact_sensitive_text(str(value or "").strip())
    return text[:max_length]


def _redact_sensitive_text(text: str) -> str:
    if not text:
        return ""
    lowered = text.lower()
    if any(part in lowered for part in _FORBIDDEN_KEY_PARTS):
        return "redacted"
    for pattern in _SENSITIVE_VALUE_PATTERNS:
        if pattern.search(text):
            return "redacted"
    return text


def _normalize_code(value: Any, *, max_length: int) -> str:
    text = _clean_text(value, max_length=max_length).lower()
    text = _CODE_PATTERN.sub("_", text).strip("_")
    return text[:max_length]


def _normalize_status(status: str) -> str:
    valid_statuses = {value for value, _label in DataIngestionLog.STATUS_CHOICES}
    normalized = _normalize_code(status, max_length=20)
    return normalized if normalized in valid_statuses else DataIngestionLog.STATUS_FAILED


def _normalize_target_type(target_type: str) -> str:
    valid_target_types = {value for value, _label in DataIngestionLog.TARGET_TYPE_CHOICES}
    normalized = _normalize_code(target_type, max_length=30)
    return normalized if normalized in valid_target_types else DataIngestionLog.TARGET_SMOKE


def _normalize_endpoint_name(endpoint_name: str) -> str:
    text = _clean_text(endpoint_name, max_length=100)
    if "://" in text or "?" in text:
        return "redacted"
    return text[:100]


def _non_negative_int(value: Any) -> int:
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _normalize_optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return _non_negative_int(value)


def _normalize_http_status_code(value: int | None) -> int | None:
    if value is None:
        return None
    code = _non_negative_int(value)
    return code if 100 <= code <= 599 else None


def _derive_total_count(
    *,
    candidate_count: int,
    saved_count: int,
    updated_count: int,
    skipped_count: int,
    failed_count: int,
) -> int:
    if candidate_count:
        return candidate_count
    total = saved_count + updated_count + skipped_count + failed_count
    return total if total else 1


def _derive_success_count(*, status: str, saved_count: int, updated_count: int, total_count: int) -> int:
    saved_or_updated = saved_count + updated_count
    if saved_or_updated:
        return saved_or_updated
    if status == DataIngestionLog.STATUS_SUCCESS and total_count:
        return 1
    return 0


def _derive_job_name(*, job_type: str, endpoint_name: str) -> str:
    normalized_job_type = _normalize_code(job_type, max_length=50) or "data_ingestion"
    normalized_endpoint = _normalize_code(endpoint_name, max_length=50)
    if normalized_endpoint:
        return f"{normalized_job_type}_{normalized_endpoint}"[:100]
    return normalized_job_type[:100]


def _error_message_from_reason(safe_reason: str, error_code: str) -> str:
    reason = _normalize_code(safe_reason, max_length=100)
    code = _normalize_code(error_code, max_length=100)
    if reason and code:
        return f"{reason}:{code}"
    return reason or code
