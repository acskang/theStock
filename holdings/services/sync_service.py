from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction

from holdings.models import UserHolding
from portfolio.services import aggregate_all_transactions_by_stock

from .stock_resolution_service import resolve_stock_from_legacy_name


@dataclass
class LegacySyncReport:
    created_count: int = 0
    updated_count: int = 0
    deactivated_count: int = 0
    unresolved_names: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def get_or_create_legacy_portfolio_user(username=None):
    user_model = get_user_model()
    username = username or settings.LEGACY_PORTFOLIO_USERNAME
    user, created = user_model.objects.get_or_create(
        username=username,
        defaults={"email": f"{username}@example.com"},
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    return user


def _sync_position_to_holding(user, position, report: LegacySyncReport, *, commit: bool):
    resolution = resolve_stock_from_legacy_name(position.stock_name)
    if resolution.warning:
        report.unresolved_names.append(position.stock_name)
        report.warnings.append(resolution.warning)
        return None

    holding = UserHolding.objects.filter(user=user, stock=resolution.stock).first()
    if position.quantity <= 0:
        if holding and (
            holding.is_active
            or holding.quantity != 0
            or holding.average_price != Decimal("0.00")
        ):
            if commit:
                holding.quantity = 0
                holding.average_price = Decimal("0.00")
                holding.is_active = False
                holding.save(update_fields=["quantity", "average_price", "is_active", "updated_at"])
            report.deactivated_count += 1
        return resolution.stock.id

    if holding is None:
        if commit:
            UserHolding.objects.create(
                user=user,
                stock=resolution.stock,
                average_price=position.average_price,
                quantity=position.quantity,
                is_active=True,
            )
        report.created_count += 1
        return resolution.stock.id

    changed = (
        holding.average_price != position.average_price
        or holding.quantity != position.quantity
        or not holding.is_active
    )
    if changed:
        if commit:
            holding.average_price = position.average_price
            holding.quantity = position.quantity
            holding.is_active = True
            holding.save(update_fields=["average_price", "quantity", "is_active", "updated_at"])
        report.updated_count += 1
    return resolution.stock.id


def _deactivate_unmatched_holdings(user, resolved_stock_ids, report: LegacySyncReport, *, commit: bool):
    if report.unresolved_names:
        report.warnings.append("매핑 실패 종목이 있어 이번 동기화에서는 잔여 active holding 자동 비활성화를 건너뛰었습니다.")
        return
    stale_holdings = UserHolding.objects.filter(user=user, is_active=True).exclude(stock_id__in=resolved_stock_ids)
    for holding in stale_holdings:
        if commit:
            holding.quantity = 0
            holding.average_price = Decimal("0.00")
            holding.is_active = False
            holding.save(update_fields=["quantity", "average_price", "is_active", "updated_at"])
        report.deactivated_count += 1


@transaction.atomic
def sync_all_holdings_for_legacy_user(user=None, *, username=None, commit: bool = True) -> LegacySyncReport:
    if user is None:
        user = get_or_create_legacy_portfolio_user(username=username)

    report = LegacySyncReport()
    positions, warnings = aggregate_all_transactions_by_stock()
    report.warnings.extend(warnings)

    resolved_stock_ids = set()
    for position in positions:
        stock_id = _sync_position_to_holding(user, position, report, commit=commit)
        if stock_id is not None:
            resolved_stock_ids.add(stock_id)

    _deactivate_unmatched_holdings(user, resolved_stock_ids, report, commit=commit)

    if not commit:
        transaction.set_rollback(True)

    return report
