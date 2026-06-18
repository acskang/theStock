from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
import hashlib
import json
from typing import Any

from django.apps import apps
from django.conf import settings
from django.core import signing
from django.db import DatabaseError, transaction
from django.utils import timezone

from integrations.models import IntegrationAuditLog
from integrations.services.audit import record_integration_audit
from integrations.services.toss_holdings_sync_plan import (
    ACTION_CREATE,
    ACTION_REMOVE_CANDIDATE,
    ACTION_SKIPPED,
    ACTION_UNCHANGED,
    ACTION_UPDATE,
    HoldingSnapshotValue,
    HoldingSyncDryRunPlan,
    HoldingSyncPlanItem,
)


APPLY_SIGNING_SALT = "integrations.toss_holdings_apply.v1"
APPLY_CONFIRM_TEXT = "반영"


class HoldingApplyError(Exception):
    """Base exception for holdings apply failures."""


class HoldingApplyPermissionError(HoldingApplyError):
    """Raised when an actor attempts to apply another user's plan."""


class HoldingApplyFeatureDisabledError(HoldingApplyError):
    """Raised when the holdings apply feature flag is disabled."""


class HoldingApplyConfirmationError(HoldingApplyError):
    """Raised when confirmation input is missing or invalid."""


class HoldingApplyTokenExpiredError(HoldingApplyError):
    """Raised when a signed confirmation token is expired."""


class HoldingApplyTokenInvalidError(HoldingApplyError):
    """Raised when a signed confirmation token is invalid."""


class HoldingApplyStalePlanError(HoldingApplyError):
    """Raised when the fresh plan no longer matches the confirmed dry-run."""


class HoldingApplyPreflightError(HoldingApplyError):
    """Raised when the full apply cannot be safely performed."""


class HoldingApplyMappingError(HoldingApplyError):
    """Raised when holdings/stocks models cannot be mapped."""


class HoldingApplyDatabaseError(HoldingApplyError):
    """Raised when the database apply transaction fails and is rolled back."""


@dataclass(frozen=True)
class HoldingApplyItemResult:
    action: str
    symbol: str
    status: str
    before_quantity: Decimal | None = None
    after_quantity: Decimal | None = None
    before_average_price: Decimal | None = None
    after_average_price: Decimal | None = None
    safe_message: str = ""

    def safe_dict(self) -> dict[str, str | None]:
        return {
            "action": self.action,
            "symbol": self.symbol,
            "status": self.status,
            "before_quantity": _decimal_to_canonical(self.before_quantity),
            "after_quantity": _decimal_to_canonical(self.after_quantity),
            "before_average_price": _decimal_to_canonical(self.before_average_price),
            "after_average_price": _decimal_to_canonical(self.after_average_price),
            "safe_message": self.safe_message,
        }


@dataclass(frozen=True)
class HoldingApplyResult:
    user_id: int
    provider: str
    applied_at: Any
    created_count: int
    updated_count: int
    unchanged_count: int
    ignored_remove_candidate_count: int
    skipped_count: int
    items: list[HoldingApplyItemResult]
    warnings: list[str] = field(default_factory=list)

    def safe_dict(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "provider": self.provider,
            "applied_at": self.applied_at.isoformat() if self.applied_at else None,
            "created_count": self.created_count,
            "updated_count": self.updated_count,
            "unchanged_count": self.unchanged_count,
            "ignored_remove_candidate_count": self.ignored_remove_candidate_count,
            "skipped_count": self.skipped_count,
            "items": [item.safe_dict() for item in self.items],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class HoldingApplyConfirmationPayload:
    user_id: int
    plan_digest: str
    symbol_filter: str | None
    create_count: int
    update_count: int
    remove_candidate_count: int
    generated_at: str

    def as_dict(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "plan_digest": self.plan_digest,
            "symbol_filter": self.symbol_filter,
            "create_count": self.create_count,
            "update_count": self.update_count,
            "remove_candidate_count": self.remove_candidate_count,
            "generated_at": self.generated_at,
        }


def get_apply_confirm_ttl_seconds() -> int:
    try:
        value = int(getattr(settings, "TOSS_HOLDINGS_APPLY_CONFIRM_TTL_SECONDS", 600))
    except (TypeError, ValueError):
        return 600
    return value if value > 0 else 600


def is_holdings_apply_enabled() -> bool:
    return bool(getattr(settings, "TOSS_USER_HOLDINGS_APPLY_ENABLED", False))


def _decimal_to_canonical(value) -> str | None:
    if value is None:
        return None
    decimal = value if isinstance(value, Decimal) else Decimal(str(value))
    return format(decimal.normalize(), "f")


def build_plan_canonical_payload(plan: HoldingSyncDryRunPlan) -> dict[str, object]:
    items = []
    for item in plan.items:
        items.append(
            {
                "action": item.action,
                "comparison_key": item.comparison_key,
                "current_object_id": item.current.object_id if item.current else None,
                "current_quantity": _decimal_to_canonical(item.current.quantity) if item.current else None,
                "current_average_purchase_price": (
                    _decimal_to_canonical(item.current.average_purchase_price) if item.current else None
                ),
                "target_quantity": _decimal_to_canonical(item.target.quantity) if item.target else None,
                "target_average_purchase_price": (
                    _decimal_to_canonical(item.target.average_purchase_price) if item.target else None
                ),
            }
        )
    return {
        "user_id": int(plan.user_id),
        "provider": plan.provider,
        "symbol_filter": plan.symbol_filter,
        "current_count": plan.current_count,
        "target_count": plan.target_count,
        "items": sorted(items, key=lambda row: (str(row["action"]), str(row["comparison_key"]))),
    }


def compute_plan_digest(plan: HoldingSyncDryRunPlan) -> str:
    payload = build_plan_canonical_payload(plan)
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def create_apply_confirmation_token(*, user, plan: HoldingSyncDryRunPlan) -> str:
    if int(getattr(user, "pk", 0) or 0) != int(plan.user_id):
        raise HoldingApplyPermissionError("This apply request is not allowed.")
    payload = HoldingApplyConfirmationPayload(
        user_id=int(plan.user_id),
        plan_digest=compute_plan_digest(plan),
        symbol_filter=plan.symbol_filter,
        create_count=plan.create_count,
        update_count=plan.update_count,
        remove_candidate_count=plan.remove_candidate_count,
        generated_at=timezone.now().isoformat(),
    )
    return signing.dumps(payload.as_dict(), salt=APPLY_SIGNING_SALT, compress=True)


def load_apply_confirmation_token(*, token: str, user) -> dict[str, object]:
    if not token:
        raise HoldingApplyTokenInvalidError("The apply confirmation token is invalid.")
    try:
        payload = signing.loads(
            token,
            salt=APPLY_SIGNING_SALT,
            max_age=get_apply_confirm_ttl_seconds(),
        )
    except signing.SignatureExpired as exc:
        raise HoldingApplyTokenExpiredError("The apply confirmation token has expired.") from exc
    except signing.BadSignature as exc:
        raise HoldingApplyTokenInvalidError("The apply confirmation token is invalid.") from exc
    if int(payload.get("user_id") or 0) != int(getattr(user, "pk", 0) or 0):
        raise HoldingApplyPermissionError("This apply request is not allowed.")
    return payload


def assert_plan_matches_confirmation(*, plan: HoldingSyncDryRunPlan, payload: dict[str, object]) -> None:
    if int(plan.user_id) != int(payload.get("user_id") or 0):
        raise HoldingApplyStalePlanError("The holdings plan has changed.")
    if (plan.symbol_filter or None) != (payload.get("symbol_filter") or None):
        raise HoldingApplyStalePlanError("The holdings plan has changed.")
    if compute_plan_digest(plan) != payload.get("plan_digest"):
        raise HoldingApplyStalePlanError("The holdings plan has changed.")
    if plan.create_count != int(payload.get("create_count") or 0):
        raise HoldingApplyStalePlanError("The holdings plan has changed.")
    if plan.update_count != int(payload.get("update_count") or 0):
        raise HoldingApplyStalePlanError("The holdings plan has changed.")


def create_apply_confirmation_context(*, user, plan: HoldingSyncDryRunPlan) -> dict[str, object]:
    return {
        "confirmation_token": create_apply_confirmation_token(user=user, plan=plan),
        "create_count": plan.create_count,
        "update_count": plan.update_count,
        "remove_candidate_count": plan.remove_candidate_count,
        "symbol_filter": plan.symbol_filter,
    }


def preflight_holdings_apply(*, user, plan: HoldingSyncDryRunPlan) -> None:
    for item in plan.items:
        if item.action == ACTION_CREATE:
            _validate_target(item.target)
            stock = _resolve_stock_for_symbol(item.target.symbol)
            if _get_user_holding_model().objects.filter(user=user, stock=stock).exists():
                raise HoldingApplyPreflightError("A target holding already exists.")
        elif item.action == ACTION_UPDATE:
            _validate_target(item.target)
            holding = _get_user_holding_for_update(user=user, object_id=item.current.object_id if item.current else None)
            if holding.stock.code.upper() != item.comparison_key:
                raise HoldingApplyPreflightError("A target holding cannot be safely updated.")


def apply_holdings_sync_plan(
    *,
    user,
    actor,
    plan: HoldingSyncDryRunPlan,
    confirmation_payload: dict[str, object],
) -> HoldingApplyResult:
    if not is_holdings_apply_enabled():
        raise HoldingApplyFeatureDisabledError("Holdings apply is disabled.")
    if actor is None or int(getattr(actor, "pk", 0) or 0) != int(getattr(user, "pk", 0) or 0):
        _record_apply_audit(user=user, actor=actor, success=False, reason_code="permission")
        raise HoldingApplyPermissionError("This apply request is not allowed.")
    if int(plan.user_id) != int(getattr(user, "pk", 0) or 0):
        _record_apply_audit(user=user, actor=actor, success=False, reason_code="permission")
        raise HoldingApplyPermissionError("This apply request is not allowed.")
    try:
        assert_plan_matches_confirmation(plan=plan, payload=confirmation_payload)
    except HoldingApplyStalePlanError:
        _record_apply_audit(user=user, actor=actor, success=False, reason_code="stale_plan", plan=plan)
        raise

    try:
        with transaction.atomic():
            preflight_holdings_apply(user=user, plan=plan)
            result = _apply_plan_items(user=user, plan=plan)
    except HoldingApplyPreflightError:
        _record_apply_audit(user=user, actor=actor, success=False, reason_code="preflight", plan=plan)
        raise
    except DatabaseError as exc:
        _record_apply_audit(user=user, actor=actor, success=False, reason_code="database", plan=plan)
        raise HoldingApplyDatabaseError("Holdings apply failed.") from exc

    _record_apply_audit(user=user, actor=actor, success=True, reason_code="apply_create_update", result=result)
    return result


def _apply_plan_items(*, user, plan: HoldingSyncDryRunPlan) -> HoldingApplyResult:
    results: list[HoldingApplyItemResult] = []
    counts = {
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "ignored_remove_candidate": 0,
        "skipped": 0,
    }

    for item in plan.items:
        if item.action == ACTION_CREATE:
            stock = _resolve_stock_for_symbol(item.target.symbol)
            holding = _get_user_holding_model().objects.create(
                user=user,
                stock=stock,
                quantity=int(item.target.quantity),
                average_price=item.target.average_purchase_price,
            )
            counts["created"] += 1
            results.append(
                HoldingApplyItemResult(
                    action=item.action,
                    symbol=item.symbol,
                    status="created",
                    after_quantity=Decimal(holding.quantity),
                    after_average_price=holding.average_price,
                    safe_message="created",
                )
            )
        elif item.action == ACTION_UPDATE:
            holding = _get_user_holding_for_update(user=user, object_id=item.current.object_id if item.current else None)
            before_quantity = Decimal(holding.quantity)
            before_average_price = holding.average_price
            update_fields = []
            if before_quantity != item.target.quantity:
                holding.quantity = int(item.target.quantity)
                update_fields.append("quantity")
            if before_average_price != item.target.average_purchase_price:
                holding.average_price = item.target.average_purchase_price
                update_fields.append("average_price")
            if update_fields:
                holding.save(update_fields=[*update_fields, "updated_at"])
                counts["updated"] += 1
                status = "updated"
            else:
                counts["unchanged"] += 1
                status = "unchanged"
            results.append(
                HoldingApplyItemResult(
                    action=item.action,
                    symbol=item.symbol,
                    status=status,
                    before_quantity=before_quantity,
                    after_quantity=Decimal(holding.quantity),
                    before_average_price=before_average_price,
                    after_average_price=holding.average_price,
                    safe_message=status,
                )
            )
        elif item.action == ACTION_UNCHANGED:
            counts["unchanged"] += 1
            results.append(_no_write_result(item=item, status="unchanged"))
        elif item.action == ACTION_REMOVE_CANDIDATE:
            counts["ignored_remove_candidate"] += 1
            results.append(_no_write_result(item=item, status="ignored_remove_candidate"))
        elif item.action == ACTION_SKIPPED:
            counts["skipped"] += 1
            results.append(_no_write_result(item=item, status="skipped"))

    return HoldingApplyResult(
        user_id=plan.user_id,
        provider=plan.provider,
        applied_at=timezone.now(),
        created_count=counts["created"],
        updated_count=counts["updated"],
        unchanged_count=counts["unchanged"],
        ignored_remove_candidate_count=counts["ignored_remove_candidate"],
        skipped_count=counts["skipped"],
        items=results,
        warnings=list(plan.warnings),
    )


def _no_write_result(*, item: HoldingSyncPlanItem, status: str) -> HoldingApplyItemResult:
    current = item.current
    target = item.target
    return HoldingApplyItemResult(
        action=item.action,
        symbol=item.symbol,
        status=status,
        before_quantity=current.quantity if current else None,
        after_quantity=target.quantity if target else (current.quantity if current else None),
        before_average_price=current.average_purchase_price if current else None,
        after_average_price=target.average_purchase_price if target else (current.average_purchase_price if current else None),
        safe_message=status,
    )


def _validate_target(target: HoldingSnapshotValue | None) -> None:
    if target is None:
        raise HoldingApplyPreflightError("A target holding is invalid.")
    if target.quantity is None or target.average_purchase_price is None:
        raise HoldingApplyPreflightError("A target holding is invalid.")
    if target.quantity <= 0 or target.average_purchase_price < 0:
        raise HoldingApplyPreflightError("A target holding is invalid.")
    if target.quantity != target.quantity.to_integral_value():
        raise HoldingApplyPreflightError("A target holding is invalid.")


def _get_user_holding_model():
    try:
        return apps.get_model("holdings", "UserHolding")
    except LookupError as exc:
        raise HoldingApplyMappingError("User holding model is unavailable.") from exc


def _get_stock_model():
    try:
        return apps.get_model("stocks", "Stock")
    except LookupError as exc:
        raise HoldingApplyMappingError("Stock model is unavailable.") from exc


def _resolve_stock_for_symbol(symbol: str):
    stock = _get_stock_model().objects.filter(code__iexact=str(symbol or "").strip()).first()
    if stock is None:
        raise HoldingApplyPreflightError("A target stock master is missing.")
    return stock


def _get_user_holding_for_update(*, user, object_id):
    if not object_id:
        raise HoldingApplyPreflightError("A target holding cannot be safely updated.")
    holding = (
        _get_user_holding_model()
        .objects.select_for_update()
        .select_related("stock")
        .filter(pk=object_id, user=user)
        .first()
    )
    if holding is None:
        raise HoldingApplyPreflightError("A target holding cannot be safely updated.")
    return holding


def _record_apply_audit(
    *,
    user,
    actor,
    success: bool,
    reason_code: str,
    plan: HoldingSyncDryRunPlan | None = None,
    result: HoldingApplyResult | None = None,
) -> None:
    metadata = {
        "created_count": result.created_count if result else 0,
        "updated_count": result.updated_count if result else 0,
        "unchanged_count": result.unchanged_count if result else 0,
        "ignored_remove_candidate_count": result.ignored_remove_candidate_count if result else 0,
        "skipped_count": result.skipped_count if result else 0,
        "has_symbol_filter": bool(plan.symbol_filter) if plan else False,
        "source": "toss_holdings_apply",
    }
    record_integration_audit(
        action=IntegrationAuditLog.ACTION_HOLDINGS_SYNC,
        actor=actor,
        target_user=user,
        success=success,
        reason_code=reason_code,
        safe_summary="holdings create/update applied" if success else "holdings apply failed",
        safe_metadata=metadata,
    )
