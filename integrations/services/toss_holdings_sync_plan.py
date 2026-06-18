from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from django.apps import apps
from django.utils import timezone

from integrations.models import IntegrationAuditLog, PROVIDER_TOSS_INVEST
from integrations.services.audit import record_integration_audit
from integrations.services.toss_holdings_readonly import (
    TossHoldingItemPreview,
    TossHoldingsPreviewResult,
    fetch_user_toss_holdings_preview,
)


ACTION_CREATE = "create"
ACTION_UPDATE = "update"
ACTION_UNCHANGED = "unchanged"
ACTION_REMOVE_CANDIDATE = "remove_candidate"
ACTION_SKIPPED = "skipped"


@dataclass(frozen=True)
class HoldingSnapshotValue:
    symbol: str
    comparison_key: str
    name: str = ""
    market_country: str = ""
    currency: str = ""
    quantity: Decimal | None = None
    average_purchase_price: Decimal | None = None
    last_price: Decimal | None = None
    source: str = "current"
    object_id: int | None = None

    def safe_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "comparison_key": self.comparison_key,
            "name": self.name,
            "market_country": self.market_country,
            "currency": self.currency,
            "quantity": _decimal_to_str(self.quantity),
            "average_purchase_price": _decimal_to_str(self.average_purchase_price),
            "last_price": _decimal_to_str(self.last_price),
            "source": self.source,
            "object_id": self.object_id,
        }


@dataclass(frozen=True)
class HoldingFieldDiff:
    field: str
    current: str | None
    target: str | None
    severity: str = "update"
    reason: str = ""

    def safe_dict(self) -> dict[str, str | None]:
        return {
            "field": self.field,
            "current": self.current,
            "target": self.target,
            "severity": self.severity,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class HoldingSyncPlanItem:
    action: str
    symbol: str
    comparison_key: str
    current: HoldingSnapshotValue | None = None
    target: HoldingSnapshotValue | None = None
    diffs: list[HoldingFieldDiff] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def safe_dict(self) -> dict[str, object]:
        return {
            "action": self.action,
            "symbol": self.symbol,
            "comparison_key": self.comparison_key,
            "current": self.current.safe_dict() if self.current else None,
            "target": self.target.safe_dict() if self.target else None,
            "diffs": [diff.safe_dict() for diff in self.diffs],
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class HoldingSyncDryRunPlan:
    user_id: int
    provider: str
    source: str
    generated_at: Any
    symbol_filter: str | None
    current_count: int
    target_count: int
    create_count: int
    update_count: int
    unchanged_count: int
    remove_candidate_count: int
    skipped_count: int
    items: list[HoldingSyncPlanItem]
    warnings: list[str] = field(default_factory=list)

    @property
    def action_counts(self) -> dict[str, int]:
        return {
            ACTION_CREATE: self.create_count,
            ACTION_UPDATE: self.update_count,
            ACTION_UNCHANGED: self.unchanged_count,
            ACTION_REMOVE_CANDIDATE: self.remove_candidate_count,
            ACTION_SKIPPED: self.skipped_count,
        }

    def safe_dict(self) -> dict[str, object]:
        return {
            "user_id": self.user_id,
            "provider": self.provider,
            "source": self.source,
            "generated_at": self.generated_at.isoformat() if self.generated_at else None,
            "symbol_filter": self.symbol_filter,
            "current_count": self.current_count,
            "target_count": self.target_count,
            "create_count": self.create_count,
            "update_count": self.update_count,
            "unchanged_count": self.unchanged_count,
            "remove_candidate_count": self.remove_candidate_count,
            "skipped_count": self.skipped_count,
            "action_counts": self.action_counts,
            "items": [item.safe_dict() for item in self.items],
            "warnings": list(self.warnings),
        }


class HoldingSyncPlanError(Exception):
    """Base exception for holdings dry-run plan failures."""


class HoldingSyncPlanMappingError(HoldingSyncPlanError):
    """Raised when current holding mapping cannot be read safely."""


class HoldingSyncPlanValidationError(HoldingSyncPlanError):
    """Raised when preview data cannot be converted to a plan."""


def normalize_symbol_for_compare(symbol: str | None) -> str:
    normalized = str(symbol or "").strip()
    if not normalized:
        raise HoldingSyncPlanValidationError("Holding symbol is required.")
    if len(normalized) > 32:
        raise HoldingSyncPlanValidationError("Holding symbol is invalid.")
    return normalized.upper()


def snapshot_from_user_holding(holding) -> HoldingSnapshotValue:
    symbol = _extract_symbol_from_user_holding(holding)
    return HoldingSnapshotValue(
        symbol=symbol,
        comparison_key=normalize_symbol_for_compare(symbol),
        name=_extract_name_from_user_holding(holding),
        quantity=_extract_quantity_from_user_holding(holding),
        average_purchase_price=_extract_average_price_from_user_holding(holding),
        source="current",
        object_id=getattr(holding, "pk", None),
    )


def snapshot_from_toss_item(item: TossHoldingItemPreview) -> HoldingSnapshotValue:
    return HoldingSnapshotValue(
        symbol=item.symbol,
        comparison_key=normalize_symbol_for_compare(item.symbol),
        name=item.name,
        market_country=item.market_country,
        currency=item.currency,
        quantity=_to_decimal(item.quantity),
        average_purchase_price=_to_decimal(item.average_purchase_price),
        last_price=_to_decimal(item.last_price),
        source="toss",
        object_id=None,
    )


def compare_snapshots(current: HoldingSnapshotValue, target: HoldingSnapshotValue) -> list[HoldingFieldDiff]:
    diffs: list[HoldingFieldDiff] = []
    _append_decimal_diff(diffs, "quantity", current.quantity, target.quantity, severity="update")
    _append_decimal_diff(
        diffs,
        "average_purchase_price",
        current.average_purchase_price,
        target.average_purchase_price,
        severity="update",
    )
    if current.name and target.name and current.name != target.name:
        diffs.append(HoldingFieldDiff("name", current.name, target.name, severity="info", reason="display metadata differs"))
    if target.market_country:
        diffs.append(
            HoldingFieldDiff(
                "market_country",
                current.market_country or None,
                target.market_country,
                severity="info",
                reason="target metadata only",
            )
        )
    if target.currency:
        diffs.append(
            HoldingFieldDiff(
                "currency",
                current.currency or None,
                target.currency,
                severity="info",
                reason="target metadata only",
            )
        )
    if target.last_price is not None:
        diffs.append(
            HoldingFieldDiff(
                "last_price",
                _decimal_to_str(current.last_price),
                _decimal_to_str(target.last_price),
                severity="info",
                reason="price is informational",
            )
        )
    return diffs


def build_holdings_sync_plan_from_preview(
    *,
    user,
    preview: TossHoldingsPreviewResult,
    record_audit: bool = False,
) -> HoldingSyncDryRunPlan:
    if user is None or int(preview.user_id) != int(getattr(user, "pk", 0) or 0):
        raise HoldingSyncPlanValidationError("Holdings preview does not match the target user.")

    current_snapshots, current_warnings = _build_current_snapshot_map(user)
    target_snapshots, target_warnings, skipped_items = _build_target_snapshot_map(preview.items)
    plan_items: list[HoldingSyncPlanItem] = []
    warnings = [*current_warnings, *target_warnings]

    for key in sorted(target_snapshots):
        target = target_snapshots[key]
        current = current_snapshots.get(key)
        if current is None:
            plan_items.append(
                HoldingSyncPlanItem(
                    action=ACTION_CREATE,
                    symbol=target.symbol,
                    comparison_key=key,
                    target=target,
                )
            )
            continue
        diffs = compare_snapshots(current, target)
        action = ACTION_UPDATE if any(diff.severity == "update" for diff in diffs) else ACTION_UNCHANGED
        plan_items.append(
            HoldingSyncPlanItem(
                action=action,
                symbol=target.symbol,
                comparison_key=key,
                current=current,
                target=target,
                diffs=diffs,
            )
        )

    if preview.symbol_filter is None:
        for key in sorted(set(current_snapshots) - set(target_snapshots)):
            current = current_snapshots[key]
            plan_items.append(
                HoldingSyncPlanItem(
                    action=ACTION_REMOVE_CANDIDATE,
                    symbol=current.symbol,
                    comparison_key=key,
                    current=current,
                    warnings=["remove_candidate requires explicit confirmation in a later phase"],
                )
            )

    plan_items.extend(skipped_items)
    plan = _build_plan(
        user_id=user.pk,
        provider=preview.provider or PROVIDER_TOSS_INVEST,
        symbol_filter=preview.symbol_filter,
        current_count=len(current_snapshots),
        target_count=len(target_snapshots),
        items=plan_items,
        warnings=warnings,
    )
    if record_audit:
        _record_plan_audit(user=user, plan=plan)
    return plan


def fetch_and_build_holdings_sync_plan(
    *,
    user,
    actor=None,
    symbol: str | None = None,
    transport=None,
    record_audit: bool = True,
) -> HoldingSyncDryRunPlan:
    preview = fetch_user_toss_holdings_preview(
        user=user,
        actor=actor,
        symbol=symbol,
        transport=transport,
    )
    return build_holdings_sync_plan_from_preview(user=user, preview=preview, record_audit=record_audit)


def _to_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise HoldingSyncPlanValidationError("Holding numeric value is invalid.") from exc


def _get_user_holding_model():
    try:
        return apps.get_model("holdings", "UserHolding")
    except LookupError as exc:
        raise HoldingSyncPlanMappingError("User holding model is unavailable.") from exc


def _get_user_holdings_queryset(user):
    model = _get_user_holding_model()
    return model.objects.filter(user=user).select_related("stock")


def _extract_symbol_from_user_holding(holding) -> str:
    # Current project mapping: UserHolding.stock -> stocks.Stock.code.
    stock = getattr(holding, "stock", None)
    symbol = getattr(stock, "code", None)
    if not symbol:
        raise HoldingSyncPlanMappingError("User holding symbol is unavailable.")
    return str(symbol).strip()


def _extract_name_from_user_holding(holding) -> str:
    stock = getattr(holding, "stock", None)
    return str(getattr(stock, "name", "") or "").strip()


def _extract_quantity_from_user_holding(holding) -> Decimal | None:
    return _to_decimal(getattr(holding, "quantity", None))


def _extract_average_price_from_user_holding(holding) -> Decimal | None:
    return _to_decimal(getattr(holding, "average_price", None))


def _build_current_snapshot_map(user) -> tuple[dict[str, HoldingSnapshotValue], list[str]]:
    snapshots: dict[str, HoldingSnapshotValue] = {}
    warnings: list[str] = []
    for holding in _get_user_holdings_queryset(user):
        try:
            snapshot = snapshot_from_user_holding(holding)
        except HoldingSyncPlanError:
            warnings.append("current holding skipped because symbol mapping is unavailable")
            continue
        if snapshot.comparison_key in snapshots:
            warnings.append("duplicate current holding comparison key skipped")
            continue
        snapshots[snapshot.comparison_key] = snapshot
    return snapshots, warnings


def _build_target_snapshot_map(
    items: list[TossHoldingItemPreview],
) -> tuple[dict[str, HoldingSnapshotValue], list[str], list[HoldingSyncPlanItem]]:
    snapshots: dict[str, HoldingSnapshotValue] = {}
    warnings: list[str] = []
    skipped: list[HoldingSyncPlanItem] = []
    for item in items:
        try:
            snapshot = snapshot_from_toss_item(item)
        except HoldingSyncPlanValidationError:
            skipped.append(
                HoldingSyncPlanItem(
                    action=ACTION_SKIPPED,
                    symbol=str(getattr(item, "symbol", "") or ""),
                    comparison_key="",
                    target=None,
                    warnings=["target holding skipped because symbol is invalid"],
                )
            )
            continue
        if snapshot.comparison_key in snapshots:
            warnings.append("duplicate target holding comparison key skipped")
            skipped.append(
                HoldingSyncPlanItem(
                    action=ACTION_SKIPPED,
                    symbol=snapshot.symbol,
                    comparison_key=snapshot.comparison_key,
                    target=snapshot,
                    warnings=["duplicate target symbol"],
                )
            )
            continue
        snapshots[snapshot.comparison_key] = snapshot
    return snapshots, warnings, skipped


def _append_decimal_diff(
    diffs: list[HoldingFieldDiff],
    field_name: str,
    current: Decimal | None,
    target: Decimal | None,
    *,
    severity: str,
) -> None:
    if current != target:
        diffs.append(
            HoldingFieldDiff(
                field=field_name,
                current=_decimal_to_str(current),
                target=_decimal_to_str(target),
                severity=severity,
            )
        )


def _decimal_to_str(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _build_plan(
    *,
    user_id: int,
    provider: str,
    symbol_filter: str | None,
    current_count: int,
    target_count: int,
    items: list[HoldingSyncPlanItem],
    warnings: list[str],
) -> HoldingSyncDryRunPlan:
    counts = {
        ACTION_CREATE: 0,
        ACTION_UPDATE: 0,
        ACTION_UNCHANGED: 0,
        ACTION_REMOVE_CANDIDATE: 0,
        ACTION_SKIPPED: 0,
    }
    for item in items:
        counts[item.action] = counts.get(item.action, 0) + 1
    return HoldingSyncDryRunPlan(
        user_id=user_id,
        provider=provider,
        source="toss_holdings_preview",
        generated_at=timezone.now(),
        symbol_filter=symbol_filter,
        current_count=current_count,
        target_count=target_count,
        create_count=counts[ACTION_CREATE],
        update_count=counts[ACTION_UPDATE],
        unchanged_count=counts[ACTION_UNCHANGED],
        remove_candidate_count=counts[ACTION_REMOVE_CANDIDATE],
        skipped_count=counts[ACTION_SKIPPED],
        items=items,
        warnings=warnings,
    )


def _record_plan_audit(*, user, plan: HoldingSyncDryRunPlan) -> None:
    record_integration_audit(
        action=IntegrationAuditLog.ACTION_HOLDINGS_SYNC,
        actor=user,
        target_user=user,
        success=True,
        reason_code="dry_run_plan",
        safe_summary="holdings sync dry-run plan generated",
        safe_metadata={
            "create_count": plan.create_count,
            "update_count": plan.update_count,
            "unchanged_count": plan.unchanged_count,
            "remove_candidate_count": plan.remove_candidate_count,
            "skipped_count": plan.skipped_count,
            "has_symbol_filter": bool(plan.symbol_filter),
            "source": plan.source,
        },
    )
