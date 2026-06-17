def mask_secret(value: object, *, visible: int = 4, mask: str = "********") -> str:
    if value is None:
        return ""

    text = str(value).strip()
    if not text:
        return ""

    visible = max(int(visible), 1)
    if len(text) <= visible * 2:
        return "****"

    return f"{text[:visible]}{mask}{text[-visible:]}"


def mask_account_id(value: object) -> str:
    return mask_secret(value)


def is_configured(value: object) -> bool:
    if value is None:
        return False
    return bool(str(value).strip())
