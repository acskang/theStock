from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from django.utils import timezone
from django.utils.http import urlencode

from integrations.services.toss_readonly_verification import (
    UrllibTossOpenApiTransport,
    is_toss_api_calls_enabled,
)
from integrations.services.toss_user_context import (
    TossUserContextAuthError,
    TossUserContextConfigurationError,
    TossUserContextDecryptionError,
    TossUserContextNotReadyError,
    TossUserContextPermissionError,
    TossUserContextTransientError,
    build_user_toss_request_context,
)


BUYING_POWER_PATH = "/api/v1/buying-power"
COMMISSIONS_PATH = "/api/v1/commissions"
SELLABLE_QUANTITY_PATH = "/api/v1/sellable-quantity"
SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9.\-]+$")
SUPPORTED_CURRENCIES = {"KRW", "USD"}


@dataclass(frozen=True)
class TossBuyingPowerPreview:
    currency: str
    cash_buying_power: Decimal | None
    fetched_at: Any

    def safe_dict(self) -> dict[str, object]:
        return {
            "currency": self.currency,
            "cash_buying_power": _decimal_to_str(self.cash_buying_power),
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
        }


@dataclass(frozen=True)
class TossCommissionPreview:
    market_country: str
    commission_rate: Decimal | None
    start_date: str
    end_date: str

    @property
    def market_label(self) -> str:
        return {"KR": "국내", "US": "미국"}.get(self.market_country, self.market_country or "-")

    def safe_dict(self) -> dict[str, object]:
        return {
            "market_country": self.market_country,
            "market_label": self.market_label,
            "commission_rate": _decimal_to_str(self.commission_rate),
            "start_date": self.start_date,
            "end_date": self.end_date,
        }


@dataclass(frozen=True)
class TossAccountTradingInfoPreview:
    user_id: int
    credential_id: int
    account_masked: str
    krw_buying_power: TossBuyingPowerPreview
    usd_buying_power: TossBuyingPowerPreview
    commissions: list[TossCommissionPreview]
    fetched_at: Any

    def safe_dict(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "credential_id": self.credential_id,
            "account_masked": self.account_masked,
            "krw_buying_power": self.krw_buying_power.safe_dict(),
            "usd_buying_power": self.usd_buying_power.safe_dict(),
            "commissions": [commission.safe_dict() for commission in self.commissions],
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
        }


@dataclass(frozen=True)
class TossSellableQuantityPreview:
    user_id: int
    credential_id: int
    symbol: str
    sellable_quantity: Decimal | None
    fetched_at: Any

    def safe_dict(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "credential_id": self.credential_id,
            "symbol": self.symbol,
            "sellable_quantity": _decimal_to_str(self.sellable_quantity),
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
        }


class TossTradingInfoError(Exception):
    """Base exception for Toss trading-info read-only failures."""


class TossTradingInfoValidationError(TossTradingInfoError):
    """Raised when trading-info filters are invalid."""


class TossTradingInfoStateError(TossTradingInfoError):
    """Raised when local credential/context state is not ready."""


class TossTradingInfoAuthError(TossTradingInfoError):
    """Raised when Toss rejects a trading-info request."""


class TossTradingInfoTransientError(TossTradingInfoError):
    """Raised for retryable Toss trading-info provider/network failures."""


class TossTradingInfoParseError(TossTradingInfoError):
    """Raised when Toss trading-info response cannot be normalized."""


def fetch_user_toss_buying_power(
    *,
    user,
    currency: str,
    actor=None,
    transport=None,
) -> TossBuyingPowerPreview:
    normalized_currency = _normalize_currency(currency)
    context = _build_context(user=user, actor=actor or user, force_refresh=False, transport=transport)
    body = _get_json_with_context_retry(
        user=user,
        actor=actor or user,
        path=f"{BUYING_POWER_PATH}?{urlencode({'currency': normalized_currency})}",
        transport=transport,
    )
    result = _extract_result_dict(body)
    return TossBuyingPowerPreview(
        currency=_safe_text(result.get("currency"), max_length=8) or normalized_currency,
        cash_buying_power=_to_decimal(result.get("cashBuyingPower")),
        fetched_at=timezone.now(),
    )


def fetch_user_toss_commissions(
    *,
    user,
    actor=None,
    transport=None,
) -> list[TossCommissionPreview]:
    body = _get_json_with_context_retry(
        user=user,
        actor=actor or user,
        path=COMMISSIONS_PATH,
        transport=transport,
    )
    result = body.get("result") if isinstance(body, dict) else None
    if not isinstance(result, list):
        raise TossTradingInfoParseError("Toss trading-info response is invalid.")
    return [_normalize_commission(item) for item in result]


def fetch_user_toss_account_trading_info(
    *,
    user,
    actor=None,
    transport=None,
) -> TossAccountTradingInfoPreview:
    actor = actor or user
    context = _build_context(user=user, actor=actor, force_refresh=False, transport=transport)
    krw = _fetch_buying_power_with_context(context=context, user=user, actor=actor, currency="KRW", transport=transport)
    usd = _fetch_buying_power_with_context(context=context, user=user, actor=actor, currency="USD", transport=transport)
    commissions = _fetch_commissions_with_context(context=context, user=user, actor=actor, transport=transport)
    return TossAccountTradingInfoPreview(
        user_id=context.user_id,
        credential_id=context.credential_id,
        account_masked=context.account_masked,
        krw_buying_power=krw,
        usd_buying_power=usd,
        commissions=commissions,
        fetched_at=timezone.now(),
    )


def fetch_user_toss_sellable_quantity(
    *,
    user,
    symbol: str,
    actor=None,
    transport=None,
) -> TossSellableQuantityPreview:
    normalized_symbol = _normalize_symbol(symbol)
    context = _build_context(user=user, actor=actor or user, force_refresh=False, transport=transport)
    body = _get_json_with_context_retry(
        user=user,
        actor=actor or user,
        path=f"{SELLABLE_QUANTITY_PATH}?{urlencode({'symbol': normalized_symbol})}",
        transport=transport,
        initial_context=context,
    )
    result = _extract_result_dict(body)
    return TossSellableQuantityPreview(
        user_id=context.user_id,
        credential_id=context.credential_id,
        symbol=normalized_symbol,
        sellable_quantity=_to_decimal(result.get("sellableQuantity")),
        fetched_at=timezone.now(),
    )


def _fetch_buying_power_with_context(*, context, user, actor, currency: str, transport) -> TossBuyingPowerPreview:
    body = _get_json_with_context_retry(
        user=user,
        actor=actor,
        path=f"{BUYING_POWER_PATH}?{urlencode({'currency': currency})}",
        transport=transport,
        initial_context=context,
    )
    result = _extract_result_dict(body)
    return TossBuyingPowerPreview(
        currency=_safe_text(result.get("currency"), max_length=8) or currency,
        cash_buying_power=_to_decimal(result.get("cashBuyingPower")),
        fetched_at=timezone.now(),
    )


def _fetch_commissions_with_context(*, context, user, actor, transport) -> list[TossCommissionPreview]:
    body = _get_json_with_context_retry(
        user=user,
        actor=actor,
        path=COMMISSIONS_PATH,
        transport=transport,
        initial_context=context,
    )
    result = body.get("result") if isinstance(body, dict) else None
    if not isinstance(result, list):
        raise TossTradingInfoParseError("Toss trading-info response is invalid.")
    return [_normalize_commission(item) for item in result]


def _get_json_with_context_retry(*, user, actor, path: str, transport, initial_context=None):
    context = initial_context or _build_context(user=user, actor=actor, force_refresh=False, transport=transport)
    return _get_json_once(
        user=user,
        actor=actor,
        path=path,
        transport=transport,
        context=context,
        force_token_refresh=False,
    )


def _get_json_once(*, user, actor, path: str, transport, context, force_token_refresh: bool):
    transport = transport or UrllibTossOpenApiTransport()
    try:
        status_code, body = transport.get_json(path, headers=context.headers())
    except TossTradingInfoError:
        raise
    except Exception as exc:
        raise TossTradingInfoTransientError("Toss trading-info request failed temporarily.") from exc
    if status_code == 200:
        return body
    if status_code == 401 and not force_token_refresh:
        refreshed_context = _build_context(user=user, actor=actor, force_refresh=True, transport=transport)
        return _get_json_once(
            user=user,
            actor=actor,
            path=path,
            transport=transport,
            context=refreshed_context,
            force_token_refresh=True,
        )
    if status_code in {401, 403}:
        raise TossTradingInfoAuthError("Toss trading-info request was rejected.")
    if status_code == 429 or status_code >= 500:
        raise TossTradingInfoTransientError("Toss trading-info request is temporarily unavailable.")
    raise TossTradingInfoTransientError("Toss trading-info request failed.")


def _build_context(*, user, actor, force_refresh: bool, transport):
    if not is_toss_api_calls_enabled():
        raise TossTradingInfoStateError("Toss trading-info is not enabled.")
    try:
        return build_user_toss_request_context(
            user=user,
            actor=actor,
            force_refresh=force_refresh,
            transport=transport,
        )
    except TossUserContextAuthError as exc:
        raise TossTradingInfoAuthError("Toss credential reset is required.") from exc
    except TossUserContextTransientError as exc:
        raise TossTradingInfoTransientError("Toss token request failed temporarily.") from exc
    except (
        TossUserContextConfigurationError,
        TossUserContextDecryptionError,
        TossUserContextNotReadyError,
        TossUserContextPermissionError,
    ) as exc:
        raise TossTradingInfoStateError("Toss trading-info is not ready.") from exc


def _normalize_currency(currency: str) -> str:
    normalized = str(currency or "").strip().upper()
    if normalized not in SUPPORTED_CURRENCIES:
        raise TossTradingInfoValidationError("Toss currency filter is invalid.")
    return normalized


def _normalize_symbol(symbol: str) -> str:
    normalized = str(symbol or "").strip()
    if not normalized or len(normalized) > 32 or not SYMBOL_PATTERN.match(normalized):
        raise TossTradingInfoValidationError("Toss symbol filter is invalid.")
    return normalized


def _extract_result_dict(body: dict) -> dict:
    if not isinstance(body, dict):
        raise TossTradingInfoParseError("Toss trading-info response is invalid.")
    result = body.get("result")
    if not isinstance(result, dict):
        raise TossTradingInfoParseError("Toss trading-info response is invalid.")
    return result


def _normalize_commission(item) -> TossCommissionPreview:
    if not isinstance(item, dict):
        raise TossTradingInfoParseError("Toss trading-info commission value is invalid.")
    return TossCommissionPreview(
        market_country=_safe_text(item.get("marketCountry"), max_length=16),
        commission_rate=_to_decimal(item.get("commissionRate")),
        start_date=_safe_text(item.get("startDate"), max_length=32),
        end_date=_safe_text(item.get("endDate"), max_length=32),
    )


def _to_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise TossTradingInfoParseError("Toss trading-info numeric value is invalid.") from exc


def _safe_text(value, *, max_length: int) -> str:
    return str(value or "").strip()[:max_length]


def _decimal_to_str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None
