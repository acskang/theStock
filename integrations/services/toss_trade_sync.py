from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from holdings.services.sync_service import sync_all_holdings_for_legacy_user
from portfolio.models import Transaction
from stocks.models import Stock

from integrations.models import (
    PROVIDER_TOSS_INVEST,
    STATUS_ACTIVE,
    TossInvestCredential,
    TossTradeImportRecord,
    TossTradeSyncState,
)
from integrations.services.credential_lifecycle import get_user_toss_credential
from integrations.services.fingerprints import make_fingerprint
from integrations.services.toss_order_history_readonly import fetch_user_toss_order_history


SYNC_RUNNING_STALE_AFTER = timedelta(minutes=30)
MAX_SYNC_PAGES = 1000


@dataclass(frozen=True)
class TossNormalizedTrade:
    order_id_hash: str
    execution_digest: str
    symbol: str
    side: str
    source_status: str
    currency: str
    ordered_at: Any
    filled_at: Any
    quantity: Decimal
    price: Decimal
    filled_amount: Decimal | None
    commission: Decimal | None
    tax: Decimal | None
    settlement_date: str


@dataclass
class TossTradeSyncResult:
    mode: str
    started_at: Any
    completed_at: Any = None
    initial_sync_completed: bool = False
    fetched_pages: int = 0
    fetched_orders: int = 0
    filled_orders: int = 0
    created_transactions: int = 0
    matched_existing_transactions: int = 0
    updated_transactions: int = 0
    duplicate_orders: int = 0
    no_fill_skipped: int = 0
    missing_stock_skipped: int = 0
    conflict_skipped: int = 0
    error_count: int = 0
    high_water_ordered_at: Any = None
    high_water_filled_at: Any = None
    warnings: list[str] = field(default_factory=list)

    def safe_dict(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "started_at": _display_dt(self.started_at),
            "completed_at": _display_dt(self.completed_at),
            "initial_sync_completed": self.initial_sync_completed,
            "fetched_pages": self.fetched_pages,
            "fetched_orders": self.fetched_orders,
            "filled_orders": self.filled_orders,
            "created_transactions": self.created_transactions,
            "matched_existing_transactions": self.matched_existing_transactions,
            "updated_transactions": self.updated_transactions,
            "duplicate_orders": self.duplicate_orders,
            "no_fill_skipped": self.no_fill_skipped,
            "missing_stock_skipped": self.missing_stock_skipped,
            "conflict_skipped": self.conflict_skipped,
            "error_count": self.error_count,
            "high_water_ordered_at": _display_dt(self.high_water_ordered_at),
            "high_water_filled_at": _display_dt(self.high_water_filled_at),
            "warnings": list(self.warnings),
        }


class TossTradeSyncError(Exception):
    """Base exception for Toss trade sync failures."""


class TossTradeSyncStateError(TossTradeSyncError):
    """Raised when local sync state does not allow the requested run."""


class TossTradeSyncMappingError(TossTradeSyncError):
    """Raised when a Toss order cannot be mapped safely."""


class TossTradeSyncImportError(TossTradeSyncError):
    """Raised when importing into local Transaction fails."""


class TossTradeSyncApiError(TossTradeSyncError):
    """Raised when Toss order history cannot be fully fetched."""


def normalize_order_to_trade(order) -> TossNormalizedTrade | None:
    order_id_hash = getattr(order, "order_id_hash", "") or ""
    if not order_id_hash:
        raise TossTradeSyncMappingError("Toss order identifier is invalid.")

    execution = order.execution
    filled_quantity = _to_decimal(getattr(execution, "filled_quantity", None))
    if filled_quantity is None or filled_quantity <= 0:
        return None

    side = str(order.side or "").upper()
    if side not in {"BUY", "SELL"}:
        return None

    price = _to_decimal(getattr(execution, "average_filled_price", None))
    if price is None or price < 0:
        raise TossTradeSyncMappingError("Toss filled price is invalid.")

    ordered_at = _ensure_datetime(order.ordered_at)
    filled_at = _ensure_datetime(execution.filled_at) or ordered_at
    if ordered_at is None or filled_at is None:
        raise TossTradeSyncMappingError("Toss filled timestamp is invalid.")

    trade = TossNormalizedTrade(
        order_id_hash=order_id_hash,
        execution_digest="",
        symbol=str(order.symbol or "").strip(),
        side=side,
        source_status=str(order.status or "").strip().upper(),
        currency=str(order.currency or "").strip().upper(),
        ordered_at=ordered_at,
        filled_at=filled_at,
        quantity=filled_quantity,
        price=price,
        filled_amount=_to_decimal(getattr(execution, "filled_amount", None)),
        commission=_to_decimal(getattr(execution, "commission", None)),
        tax=_to_decimal(getattr(execution, "tax", None)),
        settlement_date=str(getattr(execution, "settlement_date", "") or "")[:32],
    )
    return TossNormalizedTrade(**{**trade.__dict__, "execution_digest": compute_execution_digest(trade)})


def compute_execution_digest(trade: TossNormalizedTrade) -> str:
    payload = {
        "symbol": trade.symbol,
        "side": trade.side,
        "status": trade.source_status,
        "currency": trade.currency,
        "ordered_at": _display_dt(trade.ordered_at),
        "filled_at": _display_dt(trade.filled_at),
        "filled_quantity": _decimal_to_str(trade.quantity),
        "average_filled_price": _decimal_to_str(trade.price),
        "filled_amount": _decimal_to_str(trade.filled_amount),
        "commission": _decimal_to_str(trade.commission),
        "tax": _decimal_to_str(trade.tax),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_or_create_sync_state(user) -> TossTradeSyncState:
    credential = get_user_toss_credential(user)
    if credential is None or credential.status != STATUS_ACTIVE:
        raise TossTradeSyncStateError("Toss credential 연결 확인을 먼저 완료해 주세요.")
    state, _ = TossTradeSyncState.objects.get_or_create(
        user=user,
        defaults={"credential": credential, "provider": PROVIDER_TOSS_INVEST},
    )
    if state.credential_id != credential.id:
        state.credential = credential
        state.save(update_fields=["credential", "updated_at"])
    return state


def determine_incremental_from_date(state: TossTradeSyncState):
    if not state.initial_sync_completed:
        raise TossTradeSyncStateError("먼저 최초 전체 거래 동기화를 실행해 주세요.")
    if not state.last_successful_ordered_at:
        return None
    try:
        overlap_days = int(getattr(settings, "TOSS_TRADE_SYNC_OVERLAP_DAYS", 2))
    except (TypeError, ValueError):
        overlap_days = 2
    local_dt = timezone.localtime(state.last_successful_ordered_at)
    return (local_dt.date() - timedelta(days=max(overlap_days, 0))).isoformat()


def fetch_all_closed_order_pages(*, user, actor, from_date=None, transport=None):
    cursor = ""
    seen_cursors: set[str] = set()
    for page_number in range(1, MAX_SYNC_PAGES + 1):
        page = fetch_user_toss_order_history(
            user=user,
            actor=actor,
            status="CLOSED",
            from_date=from_date,
            limit=100,
            cursor=cursor,
            transport=transport,
        )
        yield page_number, page
        if not page.has_next:
            return
        cursor = page.next_cursor
        if not cursor or cursor in seen_cursors:
            raise TossTradeSyncApiError("Toss order cursor pagination is invalid.")
        seen_cursors.add(cursor)
    raise TossTradeSyncApiError("Toss order pagination exceeded the safe limit.")


def find_existing_csv_equivalent_transaction(user, trade: TossNormalizedTrade):
    stock = Stock.objects.filter(code=trade.symbol, is_active=True).first()
    if stock is None:
        return None, "missing_stock"
    try:
        quantity = _decimal_to_int_exact(trade.quantity)
        unit_price = _decimal_to_int_exact(trade.price)
    except TossTradeSyncMappingError:
        return None, "conflict"
    trade_type = _trade_type_to_legacy(trade.side)
    local_filled = timezone.localtime(trade.filled_at)
    matches = list(
        Transaction.objects.filter(
            trade_type=trade_type,
            stock_name=stock.name,
            year=local_filled.year,
            month=local_filled.month,
            day=local_filled.day,
            hour=local_filled.hour,
            minute=local_filled.minute,
            quantity=quantity,
            unit_price=unit_price,
        )[:2]
    )
    if len(matches) == 1:
        return matches[0], "matched"
    if len(matches) > 1:
        return None, "conflict"
    return None, ""


def import_normalized_trade(user, credential: TossInvestCredential, trade: TossNormalizedTrade) -> str:
    existing_record = TossTradeImportRecord.objects.filter(
        user=user,
        provider=PROVIDER_TOSS_INVEST,
        account_hash=credential.account_hash or "",
        order_id_hash=trade.order_id_hash,
    ).first()
    if existing_record and existing_record.execution_digest == trade.execution_digest:
        if existing_record.import_result == TossTradeImportRecord.RESULT_SKIPPED_MISSING_STOCK:
            retry_result = _retry_missing_stock_record(existing_record, trade)
            if retry_result:
                return retry_result
        return TossTradeImportRecord.RESULT_DUPLICATE
    if existing_record and existing_record.execution_digest != trade.execution_digest:
        existing_record.import_result = TossTradeImportRecord.RESULT_CONFLICT
        existing_record.execution_digest = trade.execution_digest
        _copy_trade_fields(existing_record, trade)
        existing_record.save()
        return TossTradeImportRecord.RESULT_CONFLICT

    matched_tx, match_result = find_existing_csv_equivalent_transaction(user, trade)
    record = TossTradeImportRecord(
        user=user,
        credential=credential,
        transaction=matched_tx,
        provider=PROVIDER_TOSS_INVEST,
        account_hash=credential.account_hash or "",
        order_id_hash=trade.order_id_hash,
        execution_digest=trade.execution_digest,
        import_result=TossTradeImportRecord.RESULT_MATCHED_EXISTING if matched_tx else "",
    )
    _copy_trade_fields(record, trade)

    if match_result == "missing_stock":
        record.import_result = TossTradeImportRecord.RESULT_SKIPPED_MISSING_STOCK
        record.save()
        return record.import_result
    if match_result == "conflict":
        record.import_result = TossTradeImportRecord.RESULT_CONFLICT
        record.save()
        return record.import_result
    if matched_tx:
        record.save()
        return record.import_result

    stock = Stock.objects.filter(code=trade.symbol, is_active=True).first()
    if stock is None:
        record.import_result = TossTradeImportRecord.RESULT_SKIPPED_MISSING_STOCK
        record.save()
        return record.import_result

    try:
        quantity = _decimal_to_int_exact(trade.quantity)
        unit_price = _decimal_to_int_exact(trade.price)
    except TossTradeSyncMappingError:
        record.import_result = TossTradeImportRecord.RESULT_CONFLICT
        record.save()
        return record.import_result

    try:
        local_filled = timezone.localtime(trade.filled_at)
        tx = Transaction.objects.create(
            trade_type=_trade_type_to_legacy(trade.side),
            stock_name=stock.name,
            year=local_filled.year,
            month=local_filled.month,
            day=local_filled.day,
            hour=local_filled.hour,
            minute=local_filled.minute,
            quantity=quantity,
            unit_price=unit_price,
        )
    except Exception as exc:
        record.import_result = TossTradeImportRecord.RESULT_CONFLICT
        record.save()
        raise TossTradeSyncImportError("Toss trade import failed.") from exc

    record.transaction = tx
    record.import_result = TossTradeImportRecord.RESULT_CREATED
    record.save()
    return record.import_result


def run_initial_trade_sync(*, user, actor=None, transport=None) -> TossTradeSyncResult:
    return _run_trade_sync(user=user, actor=actor or user, mode=TossTradeSyncState.MODE_INITIAL, transport=transport)


def run_incremental_trade_sync(*, user, actor=None, transport=None) -> TossTradeSyncResult:
    return _run_trade_sync(user=user, actor=actor or user, mode=TossTradeSyncState.MODE_INCREMENTAL, transport=transport)


def get_recent_import_records(user, *, limit: int = 50):
    records = list(
        TossTradeImportRecord.objects.filter(user=user)
        .select_related("transaction")
        .order_by("-filled_at", "-created_at")[:limit]
    )
    symbols = {record.symbol for record in records if record.symbol}
    stock_names = dict(Stock.objects.filter(code__in=symbols).values_list("code", "name"))
    for record in records:
        record.display_name = (
            getattr(record.transaction, "stock_name", "")
            or stock_names.get(record.symbol)
            or record.symbol
        )
    return records


def _run_trade_sync(*, user, actor, mode: str, transport=None) -> TossTradeSyncResult:
    if getattr(actor, "pk", None) != getattr(user, "pk", None):
        raise TossTradeSyncStateError("이 거래 동기화를 수행할 권한이 없습니다.")
    state = get_or_create_sync_state(user)
    credential = state.credential
    started_at = timezone.now()
    result = TossTradeSyncResult(mode=mode, started_at=started_at, initial_sync_completed=state.initial_sync_completed)

    _assert_not_recently_running(state)
    if mode == TossTradeSyncState.MODE_INCREMENTAL:
        from_date = determine_incremental_from_date(state)
    else:
        from_date = None

    _mark_running(state, mode=mode, started_at=started_at)
    successful = False
    try:
        for _, page in fetch_all_closed_order_pages(user=user, actor=actor, from_date=from_date, transport=transport):
            result.fetched_pages += 1
            result.fetched_orders += page.item_count
            with transaction.atomic():
                for order in page.orders:
                    trade = normalize_order_to_trade(order)
                    if trade is None:
                        result.no_fill_skipped += 1
                        continue
                    result.filled_orders += 1
                    _update_high_water(result, trade)
                    import_result = import_normalized_trade(user, credential, trade)
                    _increment_result_count(result, import_result)
        with transaction.atomic():
            sync_all_holdings_for_legacy_user(user=user)
        successful = True
        return result
    except Exception as exc:
        result.error_count += 1
        result.completed_at = timezone.now()
        result.warnings.append("일시적인 오류로 거래 동기화를 완료하지 못했습니다. 다시 실행하면 중복 없이 이어서 처리됩니다.")
        _mark_failed(state, result=result, error_code="trade_sync_failed")
        if isinstance(exc, TossTradeSyncError):
            raise
        raise TossTradeSyncApiError("Toss trade sync failed.") from exc
    finally:
        if successful:
            result.completed_at = timezone.now()
            result.initial_sync_completed = True if mode == TossTradeSyncState.MODE_INITIAL else state.initial_sync_completed
            _mark_success(state, result=result, mode=mode)


def _assert_not_recently_running(state: TossTradeSyncState) -> None:
    if state.last_run_status != TossTradeSyncState.STATUS_RUNNING or not state.last_run_started_at:
        return
    if timezone.now() - state.last_run_started_at < SYNC_RUNNING_STALE_AFTER:
        raise TossTradeSyncStateError("이미 거래 동기화가 실행 중입니다. 잠시 후 다시 확인해 주세요.")


def _mark_running(state: TossTradeSyncState, *, mode: str, started_at) -> None:
    state.last_run_started_at = started_at
    state.last_run_completed_at = None
    state.last_run_mode = mode
    state.last_run_status = TossTradeSyncState.STATUS_RUNNING
    state.last_error_code = ""
    state.last_error_summary = ""
    state.save(update_fields=["last_run_started_at", "last_run_completed_at", "last_run_mode", "last_run_status", "last_error_code", "last_error_summary", "updated_at"])


def _mark_success(state: TossTradeSyncState, *, result: TossTradeSyncResult, mode: str) -> None:
    now = result.completed_at or timezone.now()
    state.initial_sync_completed = True if mode == TossTradeSyncState.MODE_INITIAL else state.initial_sync_completed
    state.last_successful_sync_at = now
    if result.high_water_ordered_at and (not state.last_successful_ordered_at or result.high_water_ordered_at > state.last_successful_ordered_at):
        state.last_successful_ordered_at = result.high_water_ordered_at
    if result.high_water_filled_at and (not state.last_successful_filled_at or result.high_water_filled_at > state.last_successful_filled_at):
        state.last_successful_filled_at = result.high_water_filled_at
    state.last_run_completed_at = now
    state.last_run_status = TossTradeSyncState.STATUS_SUCCESS
    state.last_run_counts = result.safe_dict()
    state.last_error_code = ""
    state.last_error_summary = ""
    state.save()


def _mark_failed(state: TossTradeSyncState, *, result: TossTradeSyncResult, error_code: str) -> None:
    state.last_run_completed_at = result.completed_at or timezone.now()
    state.last_run_status = TossTradeSyncState.STATUS_ERROR if result.fetched_pages == 0 else TossTradeSyncState.STATUS_PARTIAL
    state.last_run_counts = result.safe_dict()
    state.last_error_code = error_code[:120]
    state.last_error_summary = "거래 동기화를 완료하지 못했습니다."
    state.save()


def _copy_trade_fields(record: TossTradeImportRecord, trade: TossNormalizedTrade) -> None:
    record.symbol = trade.symbol
    record.side = trade.side
    record.source_status = trade.source_status
    record.currency = trade.currency
    record.ordered_at = trade.ordered_at
    record.filled_at = trade.filled_at
    record.filled_quantity = trade.quantity
    record.average_filled_price = trade.price
    record.filled_amount = trade.filled_amount
    record.commission = trade.commission
    record.tax = trade.tax
    record.settlement_date = trade.settlement_date


def _retry_missing_stock_record(existing_record: TossTradeImportRecord, trade: TossNormalizedTrade) -> str:
    stock = Stock.objects.filter(code=trade.symbol, is_active=True).first()
    if stock is None:
        return ""
    try:
        quantity = _decimal_to_int_exact(trade.quantity)
        unit_price = _decimal_to_int_exact(trade.price)
    except TossTradeSyncMappingError:
        existing_record.import_result = TossTradeImportRecord.RESULT_CONFLICT
        existing_record.save(update_fields=["import_result", "updated_at"])
        return existing_record.import_result

    try:
        local_filled = timezone.localtime(trade.filled_at)
        tx = Transaction.objects.create(
            trade_type=_trade_type_to_legacy(trade.side),
            stock_name=stock.name,
            year=local_filled.year,
            month=local_filled.month,
            day=local_filled.day,
            hour=local_filled.hour,
            minute=local_filled.minute,
            quantity=quantity,
            unit_price=unit_price,
        )
    except Exception as exc:
        existing_record.import_result = TossTradeImportRecord.RESULT_CONFLICT
        existing_record.save(update_fields=["import_result", "updated_at"])
        raise TossTradeSyncImportError("Toss trade import retry failed.") from exc

    existing_record.transaction = tx
    existing_record.import_result = TossTradeImportRecord.RESULT_CREATED
    existing_record.save(update_fields=["transaction", "import_result", "updated_at"])
    return existing_record.import_result


def _increment_result_count(result: TossTradeSyncResult, import_result: str) -> None:
    if import_result == TossTradeImportRecord.RESULT_CREATED:
        result.created_transactions += 1
    elif import_result == TossTradeImportRecord.RESULT_MATCHED_EXISTING:
        result.matched_existing_transactions += 1
    elif import_result == TossTradeImportRecord.RESULT_UPDATED:
        result.updated_transactions += 1
    elif import_result == TossTradeImportRecord.RESULT_DUPLICATE:
        result.duplicate_orders += 1
    elif import_result == TossTradeImportRecord.RESULT_SKIPPED_MISSING_STOCK:
        result.missing_stock_skipped += 1
    elif import_result == TossTradeImportRecord.RESULT_CONFLICT:
        result.conflict_skipped += 1


def _update_high_water(result: TossTradeSyncResult, trade: TossNormalizedTrade) -> None:
    if trade.ordered_at and (result.high_water_ordered_at is None or trade.ordered_at > result.high_water_ordered_at):
        result.high_water_ordered_at = trade.ordered_at
    if trade.filled_at and (result.high_water_filled_at is None or trade.filled_at > result.high_water_filled_at):
        result.high_water_filled_at = trade.filled_at


def _to_decimal(value) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TossTradeSyncMappingError("Toss trade numeric value is invalid.") from exc


def _decimal_to_int_exact(value: Decimal) -> int:
    if value != value.to_integral_value():
        raise TossTradeSyncMappingError("Legacy Transaction supports integer quantity and price only.")
    return int(value)


def _trade_type_to_legacy(side: str) -> str:
    if side == "BUY":
        return "매수"
    if side == "SELL":
        return "매도"
    raise TossTradeSyncMappingError("Toss trade side is invalid.")


def _ensure_datetime(value):
    if value is None:
        return None
    if hasattr(value, "tzinfo"):
        return value if timezone.is_aware(value) else timezone.make_aware(value)
    parsed = parse_datetime(str(value))
    if parsed is None:
        return None
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)


def _decimal_to_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _display_dt(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)
