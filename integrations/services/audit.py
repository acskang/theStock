from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from integrations.models import IntegrationAuditLog, PROVIDER_TOSS_INVEST
from integrations.services.fingerprints import make_user_ref_hash


DANGEROUS_METADATA_KEY_PARTS = (
    "token",
    "secret",
    "authorization",
    "accountno",
    "accountseq",
    "raw_response",
    "rawresponse",
    "orderid",
    "clientorderid",
    "credential",
)


def user_ref_for_hash(user_or_id: Any) -> str:
    if user_or_id is None:
        return ""
    if hasattr(user_or_id, "pk"):
        user_or_id = user_or_id.pk
    return str(user_or_id).strip()


def record_integration_audit(
    *,
    action: str,
    provider: str = PROVIDER_TOSS_INVEST,
    credential=None,
    actor=None,
    target_user=None,
    account_hash: str = "",
    success: bool = True,
    reason_code: str = "",
    error_code: str = "",
    safe_summary: str = "",
    safe_metadata: dict | None = None,
) -> IntegrationAuditLog:
    """Create a safe integration audit event.

    The caller must not pass raw credentials, tokens, account identifiers, order
    identifiers, Authorization headers, request bodies, or raw Toss responses.
    Basic metadata key validation blocks obvious unsafe fields, but this is not
    a complete DLP system.
    """

    if target_user is None and credential is not None:
        target_user = credential.user
    if not account_hash and credential is not None:
        account_hash = credential.account_hash or ""

    safe_metadata = safe_metadata or {}
    _validate_safe_metadata(safe_metadata)

    actor_ref = user_ref_for_hash(actor)
    target_ref = user_ref_for_hash(target_user)

    return IntegrationAuditLog.objects.create(
        provider=provider,
        credential=credential,
        actor=actor,
        target_user=target_user,
        actor_ref_hash=make_user_ref_hash(actor_ref) if actor_ref else "",
        target_user_ref_hash=make_user_ref_hash(target_ref) if target_ref else "",
        action=action,
        account_hash=account_hash or "",
        success=success,
        reason_code=reason_code[:120],
        error_code=error_code[:120],
        safe_summary=(safe_summary or "")[:2000],
        safe_metadata=safe_metadata,
    )


def _validate_safe_metadata(metadata: Mapping[str, Any], *, path: str = "") -> None:
    for key, value in metadata.items():
        key_text = str(key)
        normalized_key = key_text.lower().replace("_", "").replace("-", "")
        if any(part in normalized_key for part in DANGEROUS_METADATA_KEY_PARTS):
            raise ValueError("Unsafe audit metadata key is not allowed.")
        if isinstance(value, Mapping):
            next_path = f"{path}.{key_text}" if path else key_text
            _validate_safe_metadata(value, path=next_path)
