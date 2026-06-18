from __future__ import annotations

import hmac
from hashlib import sha256

from django.conf import settings

from integrations.services.credential_crypto import CredentialCryptoConfigurationError


def normalize_fingerprint_value(value: str, *, kind: str = "generic") -> str:
    if value is None:
        raise TypeError("Fingerprint value must be a string.")

    if kind == "user_ref":
        normalized = str(value).strip()
    elif not isinstance(value, str):
        raise TypeError("Fingerprint value must be a string.")
    elif kind == "account":
        normalized = value.strip().replace(" ", "").replace("-", "")
    elif kind in {"generic", "client_id", "external_user"}:
        normalized = value.strip()
    else:
        normalized = value.strip()

    if not normalized:
        raise ValueError("Fingerprint value must not be empty.")

    return normalized


def make_fingerprint(value: str, *, namespace: str) -> str:
    namespace = str(namespace or "").strip()
    if not namespace:
        raise ValueError("Fingerprint namespace must not be empty.")

    normalized = normalize_fingerprint_value(value, kind=namespace)
    message = f"{namespace}:{normalized}".encode("utf-8")
    pepper = _get_hash_pepper()
    return hmac.new(pepper, message, sha256).hexdigest()


def make_client_id_fingerprint(client_id: str) -> str:
    return make_fingerprint(client_id, namespace="client_id")


def make_account_hash(account_ref: str) -> str:
    return make_fingerprint(account_ref, namespace="account")


def make_external_user_hash(external_user_ref: str) -> str:
    return make_fingerprint(external_user_ref, namespace="external_user")


def make_user_ref_hash(user_ref: str | int) -> str:
    return make_fingerprint(str(user_ref), namespace="user_ref")


def _get_hash_pepper() -> bytes:
    pepper = str(getattr(settings, "CREDENTIAL_HASH_PEPPER", "") or "")
    if not pepper:
        raise CredentialCryptoConfigurationError("Credential hash pepper is not configured.")
    return pepper.encode("utf-8")
