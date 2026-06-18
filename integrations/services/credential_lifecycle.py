from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from integrations.models import (
    PROVIDER_TOSS_INVEST,
    STATUS_ACTIVE,
    STATUS_DISCONNECTED,
    STATUS_ERROR,
    STATUS_PENDING_VERIFICATION,
    STATUS_RESET_REQUIRED,
    STATUS_REVOKED,
    IntegrationAuditLog,
    TossInvestCredential,
)
from integrations.services.audit import record_integration_audit
from integrations.services.credential_crypto import (
    CredentialCryptoConfigurationError,
    CredentialDecryptionError,
    decrypt_text,
    encrypt_text,
)
from integrations.services.fingerprints import (
    make_account_hash,
    make_client_id_fingerprint,
    make_external_user_hash,
)
from integrations.services.masking import mask_account


VERIFICATION_FAILURE_TRANSIENT = "transient"
VERIFICATION_FAILURE_AUTH = "auth"
VERIFICATION_FAILURE_REVOKED = "revoked"
DEFAULT_REVEAL_TIMEOUT_SECONDS = 300


class CredentialLifecycleError(Exception):
    """Base exception for credential lifecycle failures."""


class CredentialLifecycleValidationError(CredentialLifecycleError):
    """Raised when lifecycle input is invalid."""


class CredentialLifecyclePermissionError(CredentialLifecycleError):
    """Raised when a user is not allowed to perform the lifecycle operation."""


class CredentialDuplicateError(CredentialLifecycleError):
    """Raised when a credential fingerprint or account hash is already active."""


class CredentialNotFoundError(CredentialLifecycleError):
    """Raised when a user's Toss credential row does not exist."""


class CredentialRevealError(CredentialLifecycleError):
    """Raised when credential reveal is denied or fails."""


class CredentialVerificationStateError(CredentialLifecycleError):
    """Raised when verification state transition is invalid."""


def get_user_toss_credential(user) -> TossInvestCredential | None:
    if user is None:
        return None
    return TossInvestCredential.objects.filter(user=user, provider=PROVIDER_TOSS_INVEST).first()


def get_user_toss_credential_or_raise(user) -> TossInvestCredential:
    credential = get_user_toss_credential(user)
    if credential is None:
        raise CredentialNotFoundError("Toss credential is not configured.")
    return credential


def register_or_replace_pending_credential(
    *,
    user,
    client_id: str,
    client_secret: str,
    scopes: list[str] | None = None,
    actor=None,
) -> TossInvestCredential:
    """Register or replace encrypted Toss client credentials.

    The client secret is stripped to handle common form-entry mistakes. If Toss
    ever treats leading/trailing whitespace as valid secret characters, this
    policy must be revisited before user-facing rollout.
    """

    if user is None:
        raise CredentialLifecycleValidationError("User is required.")
    normalized_client_id = _validate_required_string(client_id, "client_id")
    normalized_client_secret = _validate_required_string(client_secret, "client_secret")
    normalized_scopes = _validate_scopes(scopes)
    actor = actor or user

    fingerprint = make_client_id_fingerprint(normalized_client_id)

    existing = get_user_toss_credential(user)
    _assert_client_fingerprint_available(fingerprint, user=user, credential=existing)

    encrypted_client_id = encrypt_text(normalized_client_id)
    encrypted_client_secret = encrypt_text(normalized_client_secret)
    is_create = existing is None

    try:
        with transaction.atomic():
            credential = existing or TossInvestCredential(user=user, provider=PROVIDER_TOSS_INVEST)
            credential.provider = PROVIDER_TOSS_INVEST
            credential.client_id_ciphertext = encrypted_client_id.ciphertext
            credential.client_secret_ciphertext = encrypted_client_secret.ciphertext
            credential.client_id_key_version = encrypted_client_id.key_version
            credential.client_secret_key_version = encrypted_client_secret.key_version
            credential.access_token_ciphertext = None
            credential.refresh_token_ciphertext = None
            credential.account_ref_ciphertext = None
            credential.access_token_key_version = ""
            credential.refresh_token_key_version = ""
            credential.account_ref_key_version = ""
            credential.access_token_expires_at = None
            credential.access_token_issued_at = None
            credential.access_token_type = ""
            credential.client_id_fingerprint = fingerprint
            credential.account_hash = None
            credential.account_masked = ""
            credential.external_user_hash = None
            credential.scopes = normalized_scopes
            credential.status = STATUS_PENDING_VERIFICATION
            credential.last_verified_at = None
            credential.last_used_at = None
            credential.disconnected_at = None
            credential.error_code = ""
            credential.error_summary = ""
            credential.save()

            record_integration_audit(
                action=(
                    IntegrationAuditLog.ACTION_CREDENTIAL_CREATE
                    if is_create
                    else IntegrationAuditLog.ACTION_CREDENTIAL_UPDATE
                ),
                credential=credential,
                actor=actor,
                target_user=user,
                success=True,
                safe_summary="credential registered pending verification",
                safe_metadata={"status": STATUS_PENDING_VERIFICATION},
            )
    except IntegrityError as exc:
        raise CredentialDuplicateError("Credential conflicts with an active or pending credential.") from exc

    return credential


def mark_credential_verification_success(
    *,
    credential: TossInvestCredential,
    account_ref: str,
    account_masked: str | None = None,
    external_user_ref: str | None = None,
    scopes: list[str] | None = None,
    actor=None,
) -> TossInvestCredential:
    if credential is None:
        raise CredentialVerificationStateError("Credential is required.")
    if not credential.has_client_credentials():
        raise CredentialVerificationStateError("Credential is not ready for verification.")

    normalized_account_ref = _validate_required_string(account_ref, "account_ref")
    account_hash = make_account_hash(normalized_account_ref)
    external_user_hash = make_external_user_hash(external_user_ref) if external_user_ref else None
    normalized_scopes = _validate_scopes(scopes) if scopes is not None else None
    _assert_client_fingerprint_available(credential.client_id_fingerprint, user=credential.user, credential=credential)
    _assert_account_hash_available(account_hash, user=credential.user, credential=credential)
    encrypted_account_ref = encrypt_text(normalized_account_ref)

    try:
        with transaction.atomic():
            credential.account_ref_ciphertext = encrypted_account_ref.ciphertext
            credential.account_ref_key_version = encrypted_account_ref.key_version
            credential.account_hash = account_hash
            credential.account_masked = mask_account(account_masked or normalized_account_ref)
            credential.external_user_hash = external_user_hash
            if normalized_scopes is not None:
                credential.scopes = normalized_scopes
            credential.status = STATUS_ACTIVE
            credential.last_verified_at = timezone.now()
            credential.error_code = ""
            credential.error_summary = ""
            credential.save()
            record_integration_audit(
                action=IntegrationAuditLog.ACTION_CREDENTIAL_VERIFICATION_SUCCESS,
                credential=credential,
                actor=actor or credential.user,
                target_user=credential.user,
                account_hash=account_hash,
                success=True,
                safe_summary="credential verification succeeded",
                safe_metadata={"status": STATUS_ACTIVE},
            )
    except IntegrityError as exc:
        raise CredentialDuplicateError("Credential account conflicts with an active credential.") from exc

    return credential


def mark_credential_verification_failure(
    *,
    credential: TossInvestCredential,
    failure_kind: str,
    error_code: str = "",
    safe_summary: str = "",
    actor=None,
) -> TossInvestCredential:
    if credential is None:
        raise CredentialVerificationStateError("Credential is required.")
    if failure_kind not in {VERIFICATION_FAILURE_TRANSIENT, VERIFICATION_FAILURE_AUTH, VERIFICATION_FAILURE_REVOKED}:
        raise CredentialLifecycleValidationError("Verification failure kind is invalid.")

    with transaction.atomic():
        if failure_kind == VERIFICATION_FAILURE_TRANSIENT:
            credential.status = STATUS_PENDING_VERIFICATION
            credential.error_code = _safe_code(error_code)
            credential.error_summary = _safe_summary(safe_summary)
        else:
            credential.mark_reset_required(
                error_code=_safe_code(error_code or failure_kind),
                error_summary=_safe_summary(safe_summary),
            )
        credential.save()
        record_integration_audit(
            action=IntegrationAuditLog.ACTION_CREDENTIAL_VERIFICATION_FAILURE,
            credential=credential,
            actor=actor or credential.user,
            target_user=credential.user,
            success=False,
            reason_code=failure_kind,
            error_code=_safe_code(error_code),
            safe_summary=_safe_summary(safe_summary) or "credential verification failed",
            safe_metadata={"failure_kind": failure_kind, "status": credential.status},
        )
    return credential


def reset_credential(
    *,
    user,
    actor=None,
    reason_code: str = "user_reset",
    error_code: str = "",
    safe_summary: str = "",
) -> TossInvestCredential:
    credential = get_user_toss_credential_or_raise(user)
    with transaction.atomic():
        credential.mark_reset_required(
            error_code=_safe_code(error_code),
            error_summary=_safe_summary(safe_summary),
        )
        credential.save()
        record_integration_audit(
            action=IntegrationAuditLog.ACTION_CREDENTIAL_RESET,
            credential=credential,
            actor=actor or user,
            target_user=user,
            success=True,
            reason_code=_safe_code(reason_code),
            error_code=_safe_code(error_code),
            safe_summary=_safe_summary(safe_summary) or "credential reset required",
            safe_metadata={"status": STATUS_RESET_REQUIRED},
        )
    return credential


def disconnect_credential(
    *,
    user,
    actor=None,
    reason_code: str = "user_disconnect",
    safe_summary: str = "",
) -> TossInvestCredential:
    credential = get_user_toss_credential_or_raise(user)
    with transaction.atomic():
        credential.mark_disconnected()
        credential.save()
        record_integration_audit(
            action=IntegrationAuditLog.ACTION_CREDENTIAL_DISCONNECT,
            credential=credential,
            actor=actor or user,
            target_user=user,
            success=True,
            reason_code=_safe_code(reason_code),
            safe_summary=_safe_summary(safe_summary) or "credential disconnected",
            safe_metadata={"status": STATUS_DISCONNECTED},
        )
    return credential


def reveal_client_credentials(
    *,
    user,
    password: str,
    request_user=None,
) -> dict[str, Any]:
    request_user = request_user or user
    credential = get_user_toss_credential(user)

    try:
        _assert_reveal_allowed(user=user, request_user=request_user, password=password, credential=credential)
        client_id = decrypt_text(credential.client_id_ciphertext, credential.client_id_key_version)
        client_secret = decrypt_text(credential.client_secret_ciphertext, credential.client_secret_key_version)
    except (CredentialLifecyclePermissionError, CredentialRevealError) as exc:
        _record_reveal_failure(credential, actor=request_user, target_user=user, reason_code="reveal_denied")
        raise CredentialRevealError("Credential reveal is not allowed.") from exc
    except (CredentialDecryptionError, CredentialCryptoConfigurationError) as exc:
        if credential is not None:
            _handle_decryption_failure(credential, actor=request_user)
        raise CredentialRevealError("Credential reveal failed and reset is required.") from exc

    record_integration_audit(
        action=IntegrationAuditLog.ACTION_CREDENTIAL_REVEAL_SUCCESS,
        credential=credential,
        actor=request_user,
        target_user=user,
        success=True,
        safe_summary="credential reveal succeeded",
        safe_metadata={"revealed": "client_credentials"},
    )
    return {
        "client_id": client_id,
        "client_secret": client_secret,
        "reveal_expires_at": timezone.now() + timedelta(seconds=get_reveal_timeout_seconds()),
        "credential_id": credential.pk,
    }


def get_credential_safe_status(user) -> dict[str, Any]:
    credential = get_user_toss_credential(user)
    if credential is None:
        return {
            "connected": False,
            "status": "not_configured",
            "client_id_stored": False,
            "secret_stored": False,
        "token_stored": False,
        "account_masked": "",
        "account_ref_stored": False,
        "access_token_expires_at": None,
    }

    safe = credential.safe_display_dict()
    safe.update(
        {
            "connected": credential.status in {STATUS_PENDING_VERIFICATION, STATUS_ACTIVE},
            "client_id_stored": bool(credential.client_id_ciphertext),
            "secret_stored": bool(credential.client_secret_ciphertext),
            "token_stored": credential.has_tokens(),
            "account_ref_stored": credential.has_account_ref(),
        }
    )
    return safe


def get_reveal_timeout_seconds() -> int:
    try:
        timeout = int(getattr(settings, "CREDENTIAL_REVEAL_TIMEOUT_SECONDS", DEFAULT_REVEAL_TIMEOUT_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_REVEAL_TIMEOUT_SECONDS
    return max(timeout, 1)


def _assert_client_fingerprint_available(
    fingerprint: str | None,
    *,
    user,
    credential: TossInvestCredential | None = None,
) -> None:
    if not fingerprint:
        return
    qs = TossInvestCredential.objects.filter(
        provider=PROVIDER_TOSS_INVEST,
        status__in=[STATUS_PENDING_VERIFICATION, STATUS_ACTIVE],
        client_id_fingerprint=fingerprint,
    )
    if credential and credential.pk:
        qs = qs.exclude(pk=credential.pk)
    if qs.exclude(user=user).exists() or qs.exists():
        raise CredentialDuplicateError("Credential conflicts with an active or pending credential.")
    # DB partial unique constraints remain the final race-condition defense.


def _assert_account_hash_available(
    account_hash: str | None,
    *,
    user,
    credential: TossInvestCredential | None = None,
) -> None:
    if not account_hash:
        return
    qs = TossInvestCredential.objects.filter(
        provider=PROVIDER_TOSS_INVEST,
        status=STATUS_ACTIVE,
        account_hash=account_hash,
    )
    if credential and credential.pk:
        qs = qs.exclude(pk=credential.pk)
    if qs.exclude(user=user).exists() or qs.exists():
        raise CredentialDuplicateError("Credential account conflicts with an active credential.")
    # DB partial unique constraints remain the final race-condition defense.


def _assert_reveal_allowed(*, user, request_user, password: str, credential: TossInvestCredential | None) -> None:
    if user is None or request_user is None or getattr(request_user, "pk", None) != getattr(user, "pk", None):
        raise CredentialLifecyclePermissionError("Credential reveal is not allowed.")
    if not password:
        raise CredentialRevealError("Credential reveal is not allowed.")
    if not user.check_password(password):
        raise CredentialRevealError("Credential reveal is not allowed.")
    if credential is None:
        raise CredentialRevealError("Credential reveal is not allowed.")
    if credential.status not in {STATUS_PENDING_VERIFICATION, STATUS_ACTIVE}:
        raise CredentialRevealError("Credential reveal is not allowed.")
    if not credential.client_id_ciphertext or not credential.client_secret_ciphertext:
        raise CredentialRevealError("Credential reveal is not allowed.")


def _handle_decryption_failure(credential: TossInvestCredential, *, actor=None) -> None:
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
        record_integration_audit(
            action=IntegrationAuditLog.ACTION_CREDENTIAL_REVEAL_FAILURE,
            credential=credential,
            actor=actor or credential.user,
            target_user=credential.user,
            success=False,
            reason_code="decryption_failure",
            error_code="decryption_failure",
            safe_summary="credential reveal failed",
            safe_metadata={"status": STATUS_RESET_REQUIRED},
        )


def _record_reveal_failure(
    credential: TossInvestCredential | None,
    *,
    actor=None,
    target_user=None,
    reason_code: str,
) -> None:
    record_integration_audit(
        action=IntegrationAuditLog.ACTION_CREDENTIAL_REVEAL_FAILURE,
        credential=credential,
        actor=actor,
        target_user=target_user,
        success=False,
        reason_code=_safe_code(reason_code),
        safe_summary="credential reveal failed",
        safe_metadata={"result": "denied"},
    )


def _validate_required_string(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise CredentialLifecycleValidationError(f"{field_name} is required.")
    normalized = value.strip()
    if not normalized:
        raise CredentialLifecycleValidationError(f"{field_name} is required.")
    return normalized


def _validate_scopes(scopes: list[str] | None) -> list[str]:
    if scopes is None:
        return []
    if not isinstance(scopes, list) or not all(isinstance(scope, str) for scope in scopes):
        raise CredentialLifecycleValidationError("Credential scopes must be a list of strings.")
    return scopes


def _safe_code(value: str) -> str:
    return str(value or "")[:120]


def _safe_summary(value: str) -> str:
    return str(value or "")[:2000]
