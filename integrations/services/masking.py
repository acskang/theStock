from __future__ import annotations


EMPTY_MASK = "Not configured"
SECRET_MASK = "********"
TOKEN_MASK = "********"
ACCOUNT_MASK = "acct_****"


def mask_client_id(value: str | None, *, prefix: int = 4, suffix: int = 4) -> str:
    if not value:
        return EMPTY_MASK

    text = str(value).strip()
    if not text:
        return EMPTY_MASK

    prefix = max(prefix, 0)
    suffix = max(suffix, 0)
    visible = prefix + suffix
    if len(text) <= max(visible + 2, 8):
        if len(text) <= 2:
            return "*" * max(len(text), 4)
        return f"{text[0]}{'*' * max(len(text) - 2, 4)}{text[-1]}"

    return f"{text[:prefix]}****{text[-suffix:] if suffix else ''}"


def mask_secret(value: str | None = None) -> str:
    return SECRET_MASK if value else EMPTY_MASK


def mask_token(value: str | None = None) -> str:
    return TOKEN_MASK if value else EMPTY_MASK


def mask_account(value: str | None) -> str:
    if not value:
        return EMPTY_MASK

    text = str(value).strip()
    if not text:
        return EMPTY_MASK

    if "*" in text and len(text) <= 32:
        return text

    compact = text.replace(" ", "").replace("-", "")
    if len(compact) <= 4:
        return ACCOUNT_MASK

    return f"acct_****{compact[-4:]}"
