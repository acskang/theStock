from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from integrations.models import STATUS_ACTIVE, STATUS_RESET_REQUIRED, IntegrationAuditLog, TossInvestCredential
from integrations.services.audit import record_integration_audit
from integrations.services.credential_crypto import (
    CredentialCryptoConfigurationError,
    CredentialDecryptionError,
    decrypt_text,
    encrypt_text,
)
from integrations.services.toss_readonly_verification import (
    DEFAULT_TOKEN_TYPE,
    TossReadonlyVerificationAuthError,
    TossReadonlyVerificationConfigurationError,
    TossReadonlyVerificationTransientError,
    TossTokenPayload,
    issue_toss_access_token,
    is_toss_api_calls_enabled,
)


DEFAULT_REFRESH_SKEW_SECONDS = 60


@dataclass(frozen=True)
class TossUserRequestContext:
    """Internal provider-only Toss request context.

    The values returned by headers() are sensitive and must not be passed to
    templates, API responses, sessions, messages, logs, or audit metadata.
    """

    credential_id: int
    user_id: int
    provider: str
    token_type: str
    access_token: str = field(repr=False)
    account_header: str = field(repr=False)
    account_hash: str
    account_masked: str
    access_token_expires_at: Any
    refreshed: bool = False

    def authorization_header(self) -> str:
        return f"{self.token_type} {self.access_token}"

    def headers(self) -> dict[str, str]:
        return {
            "Authorization": self.authorization_header(),
            "X-Tossinvest-Account": self.account_header,
        }

    def safe_summary(self) -> dict[str, object]:
        return {
            "credential_id": self.credential_id,
            "user_id": self.user_id,
            "provider": self.provider,
            "account_hash": self.account_hash,
            "account_masked": self.account_masked,
            "access_token_expires_at": self.access_token_expires_at,
            "refreshed": self.refreshed,
        }


class TossUserContextError(Exception):
    """Base exception for user-scoped Toss request context failures."""


class TossUserContextConfigurationError(TossUserContextError):
    """Raised when context creation is disabled or not configured."""


class TossUserContextPermissionError(TossUserContextError):
    """Raised when actor is not allowed to resolve the target user's context."""


class TossUserContextNotReadyError(TossUserContextError):
    """Raised when the user's credential is not active or not complete."""


class TossUserContextAuthError(TossUserContextError):
    """Raised when Toss rejects token reissue for the stored credential."""


class TossUserContextTransientError(TossUserContextError):
    """Raised when token reissue fails with a retryable provider/network error."""


class TossUserContextDecryptionError(TossUserContextError):
    """Raised when stored ciphertext cannot be decrypted safely."""


def get_token_refresh_skew_seconds() -> int:
    try:
        value = int(getattr(settings, "TOSS_INVEST_ACCESS_TOKEN_REFRESH_SKEW_SECONDS", DEFAULT_REFRESH_SKEW_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_REFRESH_SKEW_SECONDS
    return max(value, 0)


def is_access_token_usable(credential: TossInvestCredential, *, now=None) -> bool:
    if credential is None or credential.status != STATUS_ACTIVE:
        return False
    if not credential.access_token_ciphertext or not credential.access_token_expires_at:
        return False
    now = now or timezone.now()
    return credential.access_token_expires_at > now + timedelta(seconds=get_token_refresh_skew_seconds())


def get_active_toss_credential_for_user(user) -> TossInvestCredential:
    if user is None:
        raise TossUserContextNotReadyError("Toss credential is not ready.")
    credential = TossInvestCredential.objects.filter(user=user).first()
    if credential is None or credential.status != STATUS_ACTIVE:
        raise TossUserContextNotReadyError("Toss credential is not active.")
    if not credential.has_client_credentials() or not credential.has_account_ref():
        raise TossUserContextNotReadyError("Toss credential requires verification.")
    return credential


def build_user_toss_request_context(
    *,
    user,
    actor=None,
    force_refresh: bool = False,
    transport=None,
) -> TossUserRequestContext:
    """Build an internal user-scoped Toss request context.

    force_refresh may invalidate the previous Toss access token for the same
    client. Use it only for internal recovery/retry paths.
    """

    actor = actor or user
    _assert_actor_is_owner(user=user, actor=actor)
    _assert_api_calls_enabled()
    credential = get_active_toss_credential_for_user(user)
    account_header = _decrypt_account_ref_or_reset(credential, actor=actor)

    if is_access_token_usable(credential) and not force_refresh:
        access_token = _decrypt_access_token_or_reset(credential, actor=actor)
        return _build_context_from_values(
            credential=credential,
            account_header=account_header,
            access_token=access_token,
            refreshed=False,
        )

    client_id, client_secret = _decrypt_client_credentials_or_reset(credential, actor=actor)
    try:
        token_payload = issue_toss_access_token(
            client_id=client_id,
            client_secret=client_secret,
            transport=transport,
        )
    except TossReadonlyVerificationAuthError as exc:
        _mark_reset_for_auth_failure(credential, actor=actor)
        raise TossUserContextAuthError("Toss credential reset is required.") from exc
    except TossReadonlyVerificationTransientError as exc:
        _record_token_refresh_failure(credential, actor=actor, reason_code="transient")
        raise TossUserContextTransientError("Toss token reissue failed temporarily.") from exc
    except TossReadonlyVerificationConfigurationError as exc:
        raise TossUserContextConfigurationError("Toss API calls are disabled.") from exc

    with transaction.atomic():
        _store_access_token(credential=credential, token_payload=token_payload, issued_at=timezone.now())
        credential.save()
        record_integration_audit(
            action=IntegrationAuditLog.ACTION_TOKEN_REFRESH,
            credential=credential,
            actor=actor,
            target_user=user,
            success=True,
            reason_code="reissued",
            safe_summary="Toss access token reissued",
            safe_metadata={"status": credential.status, "refreshed": True},
        )

    return _build_context_from_values(
        credential=credential,
        account_header=account_header,
        access_token=token_payload.access_token,
        refreshed=True,
    )


def clear_user_access_token(
    *,
    user,
    actor=None,
    reason_code: str = "manual_clear",
) -> TossInvestCredential:
    actor = actor or user
    _assert_actor_is_owner(user=user, actor=actor)
    credential = get_active_toss_credential_for_user(user)
    with transaction.atomic():
        credential.access_token_ciphertext = None
        credential.access_token_key_version = ""
        credential.access_token_issued_at = None
        credential.access_token_expires_at = None
        credential.access_token_type = ""
        credential.refresh_token_ciphertext = None
        credential.refresh_token_key_version = ""
        credential.save()
        record_integration_audit(
            action=IntegrationAuditLog.ACTION_TOKEN_REFRESH,
            credential=credential,
            actor=actor,
            target_user=user,
            success=True,
            reason_code=str(reason_code or "manual_clear")[:120],
            safe_summary="Toss access token cleared",
            safe_metadata={"status": credential.status, "cleared": True},
        )
    return credential


def _assert_actor_is_owner(*, user, actor) -> None:
    if user is None or actor is None or getattr(actor, "pk", None) != getattr(user, "pk", None):
        if user is not None:
            record_integration_audit(
                action=IntegrationAuditLog.ACTION_PERMISSION_DENIED,
                actor=actor,
                target_user=user,
                success=False,
                reason_code="not_owner",
                safe_summary="Toss context permission denied",
                safe_metadata={"operation": "context_resolve"},
            )
        raise TossUserContextPermissionError("Toss context resolution is not allowed.")


def _assert_api_calls_enabled() -> None:
    if not is_toss_api_calls_enabled():
        raise TossUserContextConfigurationError("Toss API calls are disabled.")


def _build_context_from_values(
    *,
    credential: TossInvestCredential,
    account_header: str,
    access_token: str,
    refreshed: bool,
) -> TossUserRequestContext:
    return TossUserRequestContext(
        credential_id=credential.pk,
        user_id=credential.user_id,
        provider=credential.provider,
        token_type=credential.access_token_type or DEFAULT_TOKEN_TYPE,
        access_token=access_token,
        account_header=account_header,
        account_hash=credential.account_hash or "",
        account_masked=credential.account_masked,
        access_token_expires_at=credential.access_token_expires_at,
        refreshed=refreshed,
    )


def _decrypt_account_ref_or_reset(credential: TossInvestCredential, *, actor) -> str:
    try:
        return decrypt_text(credential.account_ref_ciphertext, credential.account_ref_key_version)
    except (CredentialDecryptionError, CredentialCryptoConfigurationError, TypeError) as exc:
        _mark_reset_for_decryption_failure(credential, actor=actor)
        raise TossUserContextDecryptionError("Toss credential reset is required.") from exc


def _decrypt_access_token_or_reset(credential: TossInvestCredential, *, actor) -> str:
    try:
        return decrypt_text(credential.access_token_ciphertext, credential.access_token_key_version)
    except (CredentialDecryptionError, CredentialCryptoConfigurationError, TypeError) as exc:
        _mark_reset_for_decryption_failure(credential, actor=actor)
        raise TossUserContextDecryptionError("Toss credential reset is required.") from exc


def _decrypt_client_credentials_or_reset(credential: TossInvestCredential, *, actor) -> tuple[str, str]:
    try:
        return (
            decrypt_text(credential.client_id_ciphertext, credential.client_id_key_version),
            decrypt_text(credential.client_secret_ciphertext, credential.client_secret_key_version),
        )
    except (CredentialDecryptionError, CredentialCryptoConfigurationError, TypeError) as exc:
        _mark_reset_for_decryption_failure(credential, actor=actor)
        raise TossUserContextDecryptionError("Toss credential reset is required.") from exc


def _store_access_token(
    *,
    credential: TossInvestCredential,
    token_payload: TossTokenPayload,
    issued_at,
) -> None:
    encrypted = encrypt_text(token_payload.access_token)
    credential.access_token_ciphertext = encrypted.ciphertext
    credential.access_token_key_version = encrypted.key_version
    credential.refresh_token_ciphertext = None
    credential.refresh_token_key_version = ""
    credential.access_token_issued_at = issued_at
    credential.access_token_expires_at = issued_at + timedelta(seconds=token_payload.expires_in)
    credential.access_token_type = str(token_payload.token_type or DEFAULT_TOKEN_TYPE)[:32]


def _mark_reset_for_decryption_failure(credential: TossInvestCredential, *, actor) -> None:
    with transaction.atomic():
        credential.mark_reset_required(
            error_code="decryption_failure",
            error_summary="credential decryption failed",
        )
        credential.save()
        record_integration_audit(
            action=IntegrationAuditLog.ACTION_DECRYPTION_FAILURE,
            credential=credential,
            actor=actor or credential.user,
            target_user=credential.user,
            success=False,
            reason_code="decryption_failure",
            error_code="decryption_failure",
            safe_summary="credential decryption failed",
            safe_metadata={"status": STATUS_RESET_REQUIRED},
        )


def _mark_reset_for_auth_failure(credential: TossInvestCredential, *, actor) -> None:
    with transaction.atomic():
        credential.mark_reset_required(
            error_code="token_auth_failed",
            error_summary="Toss access token reissue failed",
        )
        credential.save()
        record_integration_audit(
            action=IntegrationAuditLog.ACTION_TOKEN_REFRESH,
            credential=credential,
            actor=actor or credential.user,
            target_user=credential.user,
            success=False,
            reason_code="auth_failure",
            error_code="token_auth_failed",
            safe_summary="Toss access token reissue failed",
            safe_metadata={"status": STATUS_RESET_REQUIRED},
        )


def _record_token_refresh_failure(credential: TossInvestCredential, *, actor, reason_code: str) -> None:
    record_integration_audit(
        action=IntegrationAuditLog.ACTION_TOKEN_REFRESH,
        credential=credential,
        actor=actor or credential.user,
        target_user=credential.user,
        success=False,
        reason_code=reason_code[:120],
        error_code=reason_code[:120],
        safe_summary="Toss access token reissue failed temporarily",
        safe_metadata={"status": credential.status, "retryable": True},
    )
