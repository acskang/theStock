from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
import json
from typing import Any
from urllib import error, parse, request

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from integrations.models import (
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
from integrations.services.credential_lifecycle import (
    VERIFICATION_FAILURE_AUTH,
    VERIFICATION_FAILURE_TRANSIENT,
    CredentialNotFoundError,
    CredentialVerificationStateError,
    get_user_toss_credential_or_raise,
    mark_credential_verification_failure,
    mark_credential_verification_success,
)
from integrations.services.fingerprints import make_account_hash
from integrations.services.masking import mask_account


TOKEN_PATH = "/oauth2/token"
ACCOUNTS_PATH = "/api/v1/accounts"
DEFAULT_TOKEN_TYPE = "Bearer"


@dataclass(frozen=True)
class TossTokenPayload:
    access_token: str
    token_type: str
    expires_in: int


@dataclass(frozen=True)
class TossAccountCandidate:
    account_hash: str
    account_masked: str
    account_type: str
    is_selectable: bool = True


@dataclass(frozen=True)
class TossVerificationResult:
    credential_id: int
    status: str
    success: bool
    selected_account_hash: str | None
    account_candidates: list[TossAccountCandidate]
    reason_code: str
    safe_summary: str


class TossReadonlyVerificationError(Exception):
    """Base exception for safe Toss read-only verification failures."""


class TossReadonlyVerificationConfigurationError(TossReadonlyVerificationError):
    """Raised when read-only verification is not safely configured."""


class TossReadonlyVerificationAuthError(TossReadonlyVerificationError):
    """Raised when Toss rejects the credential or account request."""


class TossReadonlyVerificationTransientError(TossReadonlyVerificationError):
    """Raised for retryable network, rate-limit, or provider failures."""


class TossReadonlyVerificationAccountSelectionRequired(TossReadonlyVerificationError):
    """Raised when multiple safe account candidates require user selection."""

    def __init__(self, candidates: list[TossAccountCandidate]):
        super().__init__("Account selection is required.")
        self.candidates = candidates


class TossReadonlyVerificationAccountNotFound(TossReadonlyVerificationError):
    """Raised when no selectable account matches the verification request."""


class TossReadonlyVerificationStateError(TossReadonlyVerificationError):
    """Raised when local credential state does not allow verification."""


class UrllibTossOpenApiTransport:
    """Small JSON/form transport used only when API calls are explicitly enabled."""

    def __init__(self, *, base_url: str | None = None, timeout: int | None = None) -> None:
        self.base_url = (base_url or getattr(settings, "TOSS_INVEST_OPENAPI_BASE_URL", "")).rstrip("/")
        self.timeout = int(timeout or getattr(settings, "TOSS_INVEST_HTTP_TIMEOUT_SECONDS", 10))

    def post_form(
        self,
        path: str,
        data: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        body = parse.urlencode(data).encode("utf-8")
        request_headers = {"Content-Type": "application/x-www-form-urlencoded"}
        request_headers.update(headers or {})
        return self._open(path, method="POST", data=body, headers=request_headers)

    def get_json(self, path: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, Any]]:
        return self._open(path, method="GET", data=None, headers=headers or {})

    def _open(
        self,
        path: str,
        *,
        method: str,
        data: bytes | None,
        headers: dict[str, str],
    ) -> tuple[int, dict[str, Any]]:
        if not is_toss_api_calls_enabled():
            raise TossReadonlyVerificationConfigurationError("Toss API calls are disabled.")
        if not self.base_url:
            raise TossReadonlyVerificationConfigurationError("Toss OpenAPI base URL is not configured.")

        req = request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                return response.status, _decode_json_body(response.read())
        except error.HTTPError as exc:
            return exc.code, _decode_json_body(exc.read())
        except (error.URLError, TimeoutError, OSError) as exc:
            raise TossReadonlyVerificationTransientError("Toss OpenAPI network request failed.") from exc


def is_toss_api_calls_enabled() -> bool:
    return bool(getattr(settings, "TOSS_USER_TOSS_API_CALLS_ENABLED", False))


def issue_toss_access_token(
    *,
    client_id: str,
    client_secret: str,
    transport=None,
) -> TossTokenPayload:
    _assert_api_calls_enabled()
    transport = transport or UrllibTossOpenApiTransport()
    try:
        status_code, body = transport.post_form(
            TOKEN_PATH,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
    except TossReadonlyVerificationTransientError:
        raise
    except Exception as exc:
        raise TossReadonlyVerificationTransientError("Toss token request failed.") from exc

    if status_code == 200:
        return _parse_token_payload(body)
    if status_code in {400, 401, 403}:
        raise TossReadonlyVerificationAuthError("Toss token request was rejected.")
    if status_code == 429 or status_code >= 500:
        raise TossReadonlyVerificationTransientError("Toss token request is temporarily unavailable.")
    raise TossReadonlyVerificationTransientError("Toss token request failed.")


def fetch_toss_accounts(
    *,
    access_token: str,
    token_type: str = DEFAULT_TOKEN_TYPE,
    transport=None,
) -> list[dict[str, Any]]:
    _assert_api_calls_enabled()
    transport = transport or UrllibTossOpenApiTransport()
    token_type = _safe_token_type(token_type)
    try:
        status_code, body = transport.get_json(
            ACCOUNTS_PATH,
            headers={"Authorization": f"{token_type} {access_token}"},
        )
    except TossReadonlyVerificationTransientError:
        raise
    except Exception as exc:
        raise TossReadonlyVerificationTransientError("Toss account request failed.") from exc

    if status_code == 200:
        result = body.get("result")
        if not isinstance(result, list):
            raise TossReadonlyVerificationTransientError("Toss account response is invalid.")
        return result
    if status_code in {401, 403}:
        raise TossReadonlyVerificationAuthError("Toss account request was rejected.")
    if status_code == 429 or status_code >= 500:
        raise TossReadonlyVerificationTransientError("Toss account request is temporarily unavailable.")
    raise TossReadonlyVerificationTransientError("Toss account request failed.")


def build_safe_account_candidates(accounts: list[dict[str, Any]]) -> list[TossAccountCandidate]:
    candidates: list[TossAccountCandidate] = []
    for account in accounts:
        account_ref = _account_ref_from_account(account)
        account_type = str(account.get("accountType") or "")
        candidates.append(
            TossAccountCandidate(
                account_hash=make_account_hash(account_ref),
                account_masked=mask_account(account.get("accountNo")),
                account_type=account_type,
                is_selectable=(not account_type or account_type == "BROKERAGE"),
            )
        )
    return candidates


def select_account_from_accounts(
    *,
    accounts: list[dict[str, Any]],
    selected_account_hash: str | None = None,
) -> tuple[dict[str, Any], list[TossAccountCandidate]]:
    candidates = build_safe_account_candidates(accounts)
    selectable = [
        (account, candidate)
        for account, candidate in zip(accounts, candidates, strict=True)
        if candidate.is_selectable
    ]
    if not selectable:
        raise TossReadonlyVerificationAccountNotFound("No selectable Toss account was found.")

    if selected_account_hash:
        for account, candidate in selectable:
            if candidate.account_hash == selected_account_hash:
                return account, candidates
        raise TossReadonlyVerificationAccountNotFound("Selected Toss account was not found.")

    if len(selectable) > 1:
        raise TossReadonlyVerificationAccountSelectionRequired(candidates)

    return selectable[0][0], candidates


def verify_user_toss_credential_readonly(
    *,
    user,
    selected_account_hash: str | None = None,
    actor=None,
    transport=None,
) -> TossVerificationResult:
    actor = actor or user
    credential = _get_verifiable_credential(user=user, actor=actor)
    client_id, client_secret = _decrypt_client_credentials_for_verification(credential, actor=actor)

    try:
        token_payload = issue_toss_access_token(
            client_id=client_id,
            client_secret=client_secret,
            transport=transport,
        )
        accounts = fetch_toss_accounts(
            access_token=token_payload.access_token,
            token_type=token_payload.token_type,
            transport=transport,
        )
        selected_account, candidates = select_account_from_accounts(
            accounts=accounts,
            selected_account_hash=selected_account_hash,
        )
    except TossReadonlyVerificationAccountSelectionRequired as exc:
        _record_account_selection_required(credential, actor=actor, candidates=exc.candidates)
        raise
    except TossReadonlyVerificationAccountNotFound:
        mark_credential_verification_failure(
            credential=credential,
            failure_kind=VERIFICATION_FAILURE_TRANSIENT,
            error_code="no_account",
            safe_summary="no selectable Toss account was found",
            actor=actor,
        )
        raise
    except TossReadonlyVerificationAuthError:
        mark_credential_verification_failure(
            credential=credential,
            failure_kind=VERIFICATION_FAILURE_AUTH,
            error_code="toss_auth_failed",
            safe_summary="Toss read-only verification authorization failed",
            actor=actor,
        )
        raise
    except TossReadonlyVerificationTransientError:
        mark_credential_verification_failure(
            credential=credential,
            failure_kind=VERIFICATION_FAILURE_TRANSIENT,
            error_code="toss_transient",
            safe_summary="Toss read-only verification failed temporarily",
            actor=actor,
        )
        raise

    account_ref = _account_ref_from_account(selected_account)
    account_masked = mask_account(selected_account.get("accountNo"))
    issued_at = timezone.now()

    with transaction.atomic():
        credential = mark_credential_verification_success(
            credential=credential,
            account_ref=account_ref,
            account_masked=account_masked,
            actor=actor,
        )
        _store_access_token_on_credential(
            credential=credential,
            token_payload=token_payload,
            issued_at=issued_at,
        )
        credential.save()

    return TossVerificationResult(
        credential_id=credential.pk,
        status=credential.status,
        success=True,
        selected_account_hash=credential.account_hash,
        account_candidates=candidates,
        reason_code="",
        safe_summary="verification succeeded",
    )


def get_toss_account_candidates_for_user(
    *,
    user,
    actor=None,
    transport=None,
) -> list[TossAccountCandidate]:
    actor = actor or user
    credential = _get_verifiable_credential(user=user, actor=actor)
    client_id, client_secret = _decrypt_client_credentials_for_verification(credential, actor=actor)

    try:
        token_payload = issue_toss_access_token(
            client_id=client_id,
            client_secret=client_secret,
            transport=transport,
        )
        accounts = fetch_toss_accounts(
            access_token=token_payload.access_token,
            token_type=token_payload.token_type,
            transport=transport,
        )
        candidates = build_safe_account_candidates(accounts)
    except TossReadonlyVerificationAuthError:
        mark_credential_verification_failure(
            credential=credential,
            failure_kind=VERIFICATION_FAILURE_AUTH,
            error_code="toss_auth_failed",
            safe_summary="Toss read-only verification authorization failed",
            actor=actor,
        )
        raise
    except TossReadonlyVerificationTransientError:
        mark_credential_verification_failure(
            credential=credential,
            failure_kind=VERIFICATION_FAILURE_TRANSIENT,
            error_code="toss_transient",
            safe_summary="Toss read-only verification failed temporarily",
            actor=actor,
        )
        raise

    if not any(candidate.is_selectable for candidate in candidates):
        mark_credential_verification_failure(
            credential=credential,
            failure_kind=VERIFICATION_FAILURE_TRANSIENT,
            error_code="no_account",
            safe_summary="no selectable Toss account was found",
            actor=actor,
        )
        raise TossReadonlyVerificationAccountNotFound("No selectable Toss account was found.")
    return candidates


def _store_access_token_on_credential(
    *,
    credential: TossInvestCredential,
    token_payload: TossTokenPayload,
    issued_at,
) -> None:
    encrypted_token = encrypt_text(token_payload.access_token)
    credential.access_token_ciphertext = encrypted_token.ciphertext
    credential.access_token_key_version = encrypted_token.key_version
    credential.refresh_token_ciphertext = None
    credential.refresh_token_key_version = ""
    credential.access_token_issued_at = issued_at
    credential.access_token_expires_at = issued_at + timedelta(seconds=token_payload.expires_in)
    credential.access_token_type = _safe_token_type(token_payload.token_type)


def _get_verifiable_credential(*, user, actor) -> TossInvestCredential:
    if user is None:
        raise TossReadonlyVerificationStateError("User is required.")
    if actor is None or getattr(actor, "pk", None) != getattr(user, "pk", None):
        raise TossReadonlyVerificationStateError("Toss verification is not allowed.")

    try:
        credential = get_user_toss_credential_or_raise(user)
    except CredentialNotFoundError as exc:
        raise TossReadonlyVerificationStateError("Toss credential is not configured.") from exc

    if credential.status in {STATUS_DISCONNECTED, STATUS_REVOKED, STATUS_RESET_REQUIRED}:
        raise TossReadonlyVerificationStateError("Toss credential state does not allow verification.")
    if credential.status not in {STATUS_PENDING_VERIFICATION, STATUS_ACTIVE, STATUS_ERROR}:
        raise TossReadonlyVerificationStateError("Toss credential state does not allow verification.")
    if not credential.has_client_credentials():
        raise TossReadonlyVerificationStateError("Toss credential is not ready for verification.")
    return credential


def _decrypt_client_credentials_for_verification(credential: TossInvestCredential, *, actor) -> tuple[str, str]:
    try:
        return (
            decrypt_text(credential.client_id_ciphertext, credential.client_id_key_version),
            decrypt_text(credential.client_secret_ciphertext, credential.client_secret_key_version),
        )
    except (CredentialDecryptionError, CredentialCryptoConfigurationError) as exc:
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
        raise TossReadonlyVerificationStateError("Toss credential reset is required.") from exc


def _record_account_selection_required(
    credential: TossInvestCredential,
    *,
    actor,
    candidates: list[TossAccountCandidate],
) -> None:
    credential.status = STATUS_PENDING_VERIFICATION
    credential.error_code = "account_selection_required"
    credential.error_summary = "account selection is required"
    credential.save(update_fields=["status", "error_code", "error_summary", "updated_at"])
    record_integration_audit(
        action=IntegrationAuditLog.ACTION_CREDENTIAL_VERIFICATION_FAILURE,
        credential=credential,
        actor=actor or credential.user,
        target_user=credential.user,
        success=False,
        reason_code="account_selection_required",
        error_code="account_selection_required",
        safe_summary="account selection is required",
        safe_metadata={"status": STATUS_PENDING_VERIFICATION, "candidate_count": len(candidates)},
    )


def _assert_api_calls_enabled() -> None:
    if not is_toss_api_calls_enabled():
        raise TossReadonlyVerificationConfigurationError("Toss API calls are disabled.")


def _parse_token_payload(body: dict[str, Any]) -> TossTokenPayload:
    access_token = body.get("access_token")
    expires_in = body.get("expires_in")
    if not isinstance(access_token, str) or not access_token.strip():
        raise TossReadonlyVerificationAuthError("Toss token response is invalid.")
    try:
        expires_in_int = int(expires_in)
    except (TypeError, ValueError):
        raise TossReadonlyVerificationAuthError("Toss token response is invalid.") from None
    if expires_in_int <= 0:
        raise TossReadonlyVerificationAuthError("Toss token response is invalid.")
    return TossTokenPayload(
        access_token=access_token,
        token_type=_safe_token_type(body.get("token_type") or DEFAULT_TOKEN_TYPE),
        expires_in=expires_in_int,
    )


def _safe_token_type(value: object) -> str:
    token_type = str(value or DEFAULT_TOKEN_TYPE).strip() or DEFAULT_TOKEN_TYPE
    return token_type[:32]


def _account_ref_from_account(account: dict[str, Any]) -> str:
    if not isinstance(account, dict):
        raise TossReadonlyVerificationTransientError("Toss account response is invalid.")
    account_ref = account.get("accountSeq")
    if account_ref is None or str(account_ref).strip() == "":
        raise TossReadonlyVerificationTransientError("Toss account response is invalid.")
    return str(account_ref).strip()


def _decode_json_body(raw_body: bytes) -> dict[str, Any]:
    if not raw_body:
        return {}
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
