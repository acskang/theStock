from __future__ import annotations

from dataclasses import dataclass

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings


class CredentialCryptoError(Exception):
    """Base exception for credential crypto failures."""


class CredentialCryptoConfigurationError(CredentialCryptoError):
    """Raised when encryption settings are missing or invalid."""


class CredentialDecryptionError(CredentialCryptoError):
    """Raised when ciphertext cannot be decrypted with configured keys."""


@dataclass(frozen=True)
class EncryptedValue:
    ciphertext: str
    key_version: str


def is_encryption_configured() -> bool:
    try:
        _build_key_ring()
    except CredentialCryptoConfigurationError:
        return False
    return True


def get_current_key_version() -> str:
    key_ring, current_version = _build_key_ring()
    if current_version not in key_ring:
        raise CredentialCryptoConfigurationError("Current encryption key version is not configured.")
    return current_version


def encrypt_text(plaintext: str) -> EncryptedValue:
    if plaintext is None:
        raise TypeError("Plaintext must be a string.")
    if not isinstance(plaintext, str):
        raise TypeError("Plaintext must be a string.")

    key_ring, current_version = _build_key_ring()
    fernet = key_ring[current_version]
    token = fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
    return EncryptedValue(ciphertext=token, key_version=current_version)


def decrypt_text(ciphertext: str, key_version: str | None = None) -> str:
    if ciphertext is None:
        raise TypeError("Ciphertext must be a string.")
    if not isinstance(ciphertext, str):
        raise TypeError("Ciphertext must be a string.")
    if ciphertext == "":
        raise CredentialDecryptionError("Ciphertext is empty.")

    key_ring, _current_version = _build_key_ring()

    if key_version:
        preferred = key_ring.get(key_version)
        if preferred is None:
            raise CredentialCryptoConfigurationError("Requested encryption key version is not configured.")
        fernets = [preferred] + [fernet for version, fernet in key_ring.items() if version != key_version]
    else:
        fernets = list(key_ring.values())

    try:
        plaintext = MultiFernet(fernets).decrypt(ciphertext.encode("ascii"))
    except (InvalidToken, ValueError):
        raise CredentialDecryptionError("Ciphertext could not be decrypted.") from None

    return plaintext.decode("utf-8")


def _build_key_ring() -> tuple[dict[str, Fernet], str]:
    raw_key_ring = getattr(settings, "CREDENTIAL_ENCRYPTION_KEYS", "")
    single_key = str(getattr(settings, "CREDENTIAL_ENCRYPTION_KEY", "") or "").strip()
    single_version = str(getattr(settings, "CREDENTIAL_ENCRYPTION_KEY_VERSION", "v1") or "v1").strip()
    current_version = str(getattr(settings, "CREDENTIAL_ENCRYPTION_CURRENT_VERSION", "") or "").strip()

    parsed = _parse_key_ring(raw_key_ring)
    if not parsed and single_key:
        parsed = {single_version or "v1": single_key}

    if not parsed:
        raise CredentialCryptoConfigurationError("Credential encryption key is not configured.")

    if not current_version:
        current_version = single_version or "v1"

    key_ring: dict[str, Fernet] = {}
    for version, key in parsed.items():
        version = str(version).strip()
        if not version:
            raise CredentialCryptoConfigurationError("Credential encryption key version is invalid.")
        key_ring[version] = _make_fernet(key)

    if current_version not in key_ring:
        raise CredentialCryptoConfigurationError("Current encryption key version is not configured.")

    return key_ring, current_version


def _parse_key_ring(raw_key_ring: object) -> dict[str, str]:
    if raw_key_ring is None:
        return {}

    if isinstance(raw_key_ring, dict):
        return {str(version).strip(): str(key).strip() for version, key in raw_key_ring.items() if str(key).strip()}

    raw_text = str(raw_key_ring).strip()
    if not raw_text:
        return {}

    parsed: dict[str, str] = {}
    for item in raw_text.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise CredentialCryptoConfigurationError("Credential encryption key ring format is invalid.")
        version, key = item.split(":", 1)
        version = version.strip()
        key = key.strip()
        if not version or not key:
            raise CredentialCryptoConfigurationError("Credential encryption key ring format is invalid.")
        parsed[version] = key
    return parsed


def _make_fernet(key: object) -> Fernet:
    try:
        return Fernet(str(key).strip().encode("ascii"))
    except (TypeError, ValueError):
        raise CredentialCryptoConfigurationError("Credential encryption key is invalid.") from None
