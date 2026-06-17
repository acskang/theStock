import logging
import re
from typing import Any, Mapping

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from data_pipeline.providers import get_provider
from data_pipeline.providers.toss_exceptions import (
    TossAuthError,
    TossConfigurationError,
    TossOpenApiError,
    TossProviderDisabled,
    TossRateLimitError,
)
from data_pipeline.providers.toss_masking import is_configured, mask_account_id
from data_pipeline.services.ingestion_log_writer import record_data_ingestion_log


ORDERS_ENDPOINT = "/api/v1/orders"
SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9.\-]+$")
DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Fetch Toss order history candidates without saving them or placing orders."

    def add_arguments(self, parser):
        parser.add_argument("--status", default="CLOSED")
        parser.add_argument("--symbol", default=None)
        parser.add_argument("--from-date", default=None)
        parser.add_argument("--to-date", default=None)
        parser.add_argument("--cursor", default=None)
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--account", default=None)
        parser.add_argument("--no-network", action="store_true")
        parser.add_argument("--raw", action="store_true")

    def handle(self, *args, **options):
        status_filter = _validate_status(options.get("status"))
        symbol = _validate_optional_symbol(options.get("symbol"))
        from_date = _validate_optional_date(options.get("from_date"))
        to_date = _validate_optional_date(options.get("to_date"))
        limit = _validate_limit(options.get("limit"))
        cursor = str(options.get("cursor") or "").strip()
        account = str(options.get("account") or "").strip() or None

        if options.get("no_network"):
            self._write_no_network(
                status_filter=status_filter,
                symbol=symbol,
                from_date=from_date,
                to_date=to_date,
                limit=limit,
                cursor_present=bool(cursor),
            )
            return

        try:
            provider = _get_toss_provider_from_registry()
        except ValueError:
            self._write_failure(
                reason="provider_not_registered",
                status_filter=status_filter,
                symbol=symbol,
                network_call=False,
            )
            return
        except Exception:
            self._write_failure(
                reason="provider_error",
                status_filter=status_filter,
                symbol=symbol,
                network_call=False,
            )
            return

        try:
            result = provider.get_order_history_candidates(
                status=status_filter,
                symbol=symbol or None,
                from_date=from_date or None,
                to_date=to_date or None,
                cursor=cursor or None,
                limit=limit,
                account=account,
            )
        except (
            TossProviderDisabled,
            TossConfigurationError,
            TossAuthError,
            TossRateLimitError,
            TossOpenApiError,
        ) as exc:
            reason = _safe_reason(exc)
            self._write_failure(
                reason=reason,
                status_filter=status_filter,
                symbol=symbol,
                network_call=_network_call_for_reason(reason),
                diagnostics=_safe_diagnostics(exc, account=account),
            )
            return
        except Exception:
            self._write_failure(
                reason="provider_error",
                status_filter=status_filter,
                symbol=symbol,
                network_call=True,
                diagnostics=_safe_diagnostics(None, account=account),
            )
            return

        self._write_success(result, raw=bool(options.get("raw")))

    def _write_no_network(
        self,
        *,
        status_filter: str,
        symbol: str,
        from_date: str,
        to_date: str,
        limit: int,
        cursor_present: bool,
    ) -> None:
        self.stdout.write("Toss order history dry-run: SKIPPED")
        self.stdout.write("reason: no_network")
        self.stdout.write("provider: toss")
        self.stdout.write(f"endpoint: {ORDERS_ENDPOINT}")
        self.stdout.write(f"status_filter: {status_filter}")
        if symbol:
            self.stdout.write(f"symbol: {symbol}")
        if from_date:
            self.stdout.write(f"from_date: {from_date}")
        if to_date:
            self.stdout.write(f"to_date: {to_date}")
        self.stdout.write(f"limit: {limit}")
        self.stdout.write(f"cursor_present: {_bool_text(cursor_present)}")
        self.stdout.write("network_call: false")
        self.stdout.write("dry_run: true")
        self.stdout.write("commit: not_supported")
        self.stdout.write(f"order_execution_enabled: {_bool_text(_order_execution_enabled())}")
        _record_order_history_log(
            status="skipped",
            safe_reason="no_network",
            status_filter=status_filter,
            symbol=symbol,
            network_call=False,
            order_count=0,
            has_next=False,
            next_cursor_present=False,
            limit=limit,
        )
        logger.info(
            "toss_order_history_dryrun_result command=%s status=skipped provider=toss endpoint=%s "
            "status_filter=%s symbol=%s network_call=false dry_run=true order_execution_enabled=%s",
            "toss_order_history_dryrun",
            ORDERS_ENDPOINT,
            status_filter,
            symbol,
            _bool_text(_order_execution_enabled()),
        )

    def _write_success(self, result: Mapping[str, Any], *, raw: bool) -> None:
        orders = result.get("orders") if isinstance(result.get("orders"), list) else []
        raw_summary = result.get("raw_summary") if isinstance(result.get("raw_summary"), Mapping) else {}
        status_filter = str(result.get("status_filter") or "")
        symbol = str(result.get("symbol") or "")
        self.stdout.write("Toss order history dry-run: OK")
        self.stdout.write("provider: toss")
        self.stdout.write(f"endpoint: {result.get('endpoint', ORDERS_ENDPOINT)}")
        self.stdout.write(f"status_filter: {status_filter}")
        if symbol:
            self.stdout.write(f"symbol: {symbol}")
        self.stdout.write("network_call: true")
        self.stdout.write("dry_run: true")
        self.stdout.write("commit: not_supported")
        self.stdout.write(f"order_execution_enabled: {_bool_text(_order_execution_enabled())}")
        self.stdout.write(f"account_source: {result.get('account_source', 'unknown')}")
        self.stdout.write(f"account_fallback_used: {_bool_text(bool(result.get('account_fallback_used')))}")
        self.stdout.write(f"account_header_configured: {_bool_text(bool(result.get('account_header_configured')))}")
        self.stdout.write(f"order_count: {len(orders)}")
        self.stdout.write(f"has_next: {_bool_text(bool(result.get('has_next')))}")
        self.stdout.write(f"next_cursor_present: {_bool_text(bool(result.get('next_cursor_present')))}")
        self.stdout.write("orders:")
        for order in orders:
            if not isinstance(order, Mapping):
                continue
            execution = order.get("execution") if isinstance(order.get("execution"), Mapping) else {}
            self.stdout.write(f"  - order_id: {order.get('order_id_masked')}")
            self.stdout.write(f"    symbol: {order.get('symbol')}")
            self.stdout.write(f"    side: {order.get('side')}")
            self.stdout.write(f"    order_type: {order.get('order_type')}")
            self.stdout.write(f"    status: {order.get('status')}")
            self.stdout.write(f"    quantity: {order.get('quantity')}")
            self.stdout.write(f"    price: {order.get('price')}")
            self.stdout.write(f"    currency: {order.get('currency')}")
            self.stdout.write(f"    ordered_at: {order.get('ordered_at')}")
            self.stdout.write(f"    filled_quantity: {execution.get('filled_quantity')}")
            self.stdout.write(f"    average_filled_price: {execution.get('average_filled_price')}")
            self.stdout.write(f"    filled_amount: {execution.get('filled_amount')}")
            self.stdout.write(f"    commission: {execution.get('commission')}")
            self.stdout.write(f"    tax: {execution.get('tax')}")
            self.stdout.write(f"    filled_at: {execution.get('filled_at')}")
            self.stdout.write(f"    settlement_date: {execution.get('settlement_date')}")
        if raw:
            self.stdout.write(f"raw_summary: {_format_raw_summary(raw_summary)}")

        _record_order_history_log(
            status="success",
            safe_reason="order_history_received",
            status_filter=status_filter,
            symbol=symbol,
            network_call=True,
            order_count=len(orders),
            has_next=bool(result.get("has_next")),
            next_cursor_present=bool(result.get("next_cursor_present")),
            limit=0,
        )
        logger.info(
            "toss_order_history_dryrun_result command=%s status=ok provider=toss endpoint=%s "
            "status_filter=%s symbol=%s order_count=%s network_call=true dry_run=true order_execution_enabled=%s",
            "toss_order_history_dryrun",
            ORDERS_ENDPOINT,
            status_filter,
            symbol,
            len(orders),
            _bool_text(_order_execution_enabled()),
        )

    def _write_failure(
        self,
        *,
        reason: str,
        status_filter: str,
        symbol: str,
        network_call: bool,
        diagnostics: Mapping[str, Any] | None = None,
    ) -> None:
        diagnostics = dict(diagnostics or {})
        self.stdout.write("Toss order history dry-run: FAILED")
        self.stdout.write(f"reason: {reason}")
        self.stdout.write("provider: toss")
        self.stdout.write(f"endpoint: {ORDERS_ENDPOINT}")
        self.stdout.write(f"status_filter: {status_filter}")
        if symbol:
            self.stdout.write(f"symbol: {symbol}")
        self.stdout.write(f"network_call: {_bool_text(network_call)}")
        self.stdout.write("dry_run: true")
        self.stdout.write("commit: not_supported")
        self.stdout.write(f"order_execution_enabled: {_bool_text(_order_execution_enabled())}")
        for key in (
            "http_status_code",
            "error_code",
            "error_field",
            "safe_message",
            "account_env_configured",
            "account_env_shape",
            "accounts_api_called",
            "selected_account_source",
            "account_arg_shape",
            "account_count",
            "account_fallback_used",
            "account_header_configured",
        ):
            value = diagnostics.get(key)
            if value not in {None, ""}:
                self.stdout.write(f"{key}: {value}")

        _record_order_history_log(
            status="failed",
            safe_reason=_log_safe_reason(reason),
            status_filter=status_filter,
            symbol=symbol,
            network_call=network_call,
            order_count=0,
            has_next=False,
            next_cursor_present=False,
            failed_count=1,
            http_status_code=_diagnostic_int(diagnostics.get("http_status_code")),
            error_code=str(diagnostics.get("error_code") or ""),
        )
        logger.warning(
            "toss_order_history_dryrun_result command=%s status=failed provider=toss reason=%s "
            "endpoint=%s status_filter=%s symbol=%s network_call=%s dry_run=true diagnostics=%s",
            "toss_order_history_dryrun",
            reason,
            ORDERS_ENDPOINT,
            status_filter,
            symbol,
            _bool_text(network_call),
            _format_diagnostics_for_log(diagnostics),
        )


def _get_toss_provider_from_registry():
    provider = get_provider("toss")
    if isinstance(provider, type):
        return provider()
    return provider


def _record_order_history_log(
    *,
    status: str,
    safe_reason: str,
    status_filter: str,
    symbol: str,
    network_call: bool,
    order_count: int,
    has_next: bool,
    next_cursor_present: bool,
    limit: int = 0,
    failed_count: int = 0,
    http_status_code: int | None = None,
    error_code: str = "",
) -> None:
    record_data_ingestion_log(
        provider_name="toss",
        job_type="toss_order_history_dryrun",
        target_type="smoke",
        target_symbol=symbol,
        endpoint_name=ORDERS_ENDPOINT,
        status=status,
        safe_reason=safe_reason,
        error_code=error_code,
        http_status_code=http_status_code,
        network_call=network_call,
        dry_run=True,
        commit_mode="not_supported",
        candidate_count=order_count,
        saved_count=0,
        updated_count=0,
        skipped_count=0,
        failed_count=failed_count,
        metadata={
            "command": "toss_order_history_dryrun",
            "provider": "toss",
            "symbol": symbol,
            "endpoint_name": ORDERS_ENDPOINT,
            "network_call": network_call,
            "dry_run": True,
            "commit_mode": "not_supported",
            "order_execution_enabled": _order_execution_enabled(),
            "candidate_count": order_count,
            "saved_count": 0,
            "updated_count": 0,
            "skipped_count": 0,
            "failed_count": failed_count,
            "params_shape": _params_shape(
                status_filter=status_filter,
                symbol=symbol,
                limit=limit,
                has_cursor=next_cursor_present,
            ),
            "http_status_code": http_status_code,
            "error_code": error_code,
        },
    )


def _validate_status(value: Any) -> str:
    clean_value = str(value or "").strip().upper()
    if clean_value not in {"OPEN", "CLOSED"}:
        raise CommandError("Invalid Toss order history status.")
    return clean_value


def _validate_optional_symbol(value: Any) -> str:
    clean_value = str(value or "").strip()
    if not clean_value:
        return ""
    if "," in clean_value:
        raise CommandError("Only one Toss order history symbol is supported.")
    if not SYMBOL_PATTERN.match(clean_value):
        raise CommandError("Invalid Toss order history symbol.")
    return clean_value


def _validate_optional_date(value: Any) -> str:
    clean_value = str(value or "").strip()
    if not clean_value:
        return ""
    if not DATE_PATTERN.match(clean_value):
        raise CommandError("Invalid Toss order history date.")
    return clean_value


def _validate_limit(value: Any) -> int:
    try:
        clean_value = int(value)
    except (TypeError, ValueError) as exc:
        raise CommandError("Invalid Toss order history limit.") from exc
    if clean_value < 1 or clean_value > 100:
        raise CommandError("Invalid Toss order history limit.")
    return clean_value


def _safe_reason(exc: Exception) -> str:
    explicit_reason = getattr(exc, "safe_reason", "")
    if explicit_reason:
        return str(explicit_reason)
    if isinstance(exc, TossProviderDisabled):
        return "provider_disabled"
    if isinstance(exc, TossConfigurationError):
        return "credentials_missing"
    if isinstance(exc, TossAuthError):
        return "authentication_failed"
    if isinstance(exc, TossRateLimitError):
        return "rate_limit_exceeded"
    if isinstance(exc, TossOpenApiError):
        return "order_history_request_failed"
    return "provider_error"


def _safe_diagnostics(exc: Exception | None, *, account: str | None = None) -> dict[str, Any]:
    env_account = getattr(settings, "TOSS_INVEST_ACCOUNT_ID", "")
    diagnostic = getattr(exc, "account_diagnostic", {}) if exc is not None else {}
    diagnostic = dict(diagnostic) if isinstance(diagnostic, Mapping) else {}
    selected_source = (
        str(diagnostic.get("selected_account_source") or "")
        or ("cli" if is_configured(account) else ("env" if is_configured(env_account) else "accounts_api_single"))
    )
    diagnostics = {
        "account_env_configured": _bool_text(is_configured(env_account)),
        "account_env_shape": diagnostic.get("account_env_shape") or _classify_account_value(env_account),
        "accounts_api_called": _bool_text(bool(diagnostic.get("accounts_api_called"))),
        "selected_account_source": selected_source,
        "account_header_configured": _bool_text(bool(diagnostic.get("account_header_configured", is_configured(account or env_account)))),
    }
    for key in ("account_arg_shape", "account_count", "account_fallback_used"):
        if key in diagnostic:
            diagnostics[key] = diagnostic[key]
    selected_value = account if is_configured(account) else env_account
    if is_configured(selected_value) and selected_source not in {"cli_invalid", "none", "ambiguous"}:
        diagnostics["selected_account_masked"] = mask_account_id(selected_value)
    if exc is not None:
        status_code = getattr(exc, "http_status_code", None)
        if status_code is not None:
            diagnostics["http_status_code"] = status_code
        for attr in ("error_code", "error_field", "safe_message"):
            value = _safe_diagnostic_text(getattr(exc, attr, ""))
            if value:
                diagnostics[attr] = value
    return diagnostics


def _network_call_for_reason(reason: str) -> bool:
    return reason not in {
        "provider_not_registered",
        "provider_disabled",
        "credentials_missing",
        "account_required",
        "account_seq_required",
        "invalid_account_identifier",
        "invalid_status",
        "invalid_symbol",
        "invalid_date",
        "invalid_limit",
        "no_network",
    }


def _log_safe_reason(reason: str) -> str:
    return {
        "account_required": "order_history_request_failed",
        "account_not_found": "order_history_request_failed",
        "ambiguous_account": "order_history_request_failed",
        "account_seq_required": "order_history_request_failed",
        "invalid_account_identifier": "order_history_request_failed",
    }.get(reason, reason)


def _classify_account_value(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return "missing"
    if not text.isdigit():
        return "non_integer"
    if len(text) > 20:
        return "too_long"
    return "integer_like"


def _safe_diagnostic_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 120:
        return ""
    lowered = text.lower()
    forbidden = (
        "authorization",
        "bearer ",
        "access_token",
        "client_secret",
        "x-tossinvest-account",
        "accountno",
        "accountseq",
        "orderid",
        "clientorderid",
    )
    if any(part in lowered for part in forbidden):
        return ""
    return text


def _format_diagnostics_for_log(diagnostics: Mapping[str, Any]) -> str:
    parts = []
    for key in (
        "http_status_code",
        "error_code",
        "error_field",
        "account_env_configured",
        "account_env_shape",
        "accounts_api_called",
        "selected_account_source",
        "account_header_configured",
    ):
        value = diagnostics.get(key)
        if value not in {None, ""}:
            parts.append(f"{key}={value}")
    return " ".join(parts) if parts else "none"


def _format_raw_summary(raw_summary: Mapping[str, Any]) -> str:
    allowed_keys = ("result_type", "has_next", "next_cursor_present", "order_count")
    parts = [f"{key}={raw_summary[key]}" for key in allowed_keys if key in raw_summary]
    return " ".join(parts) if parts else "none"


def _params_shape(*, status_filter: str, symbol: str, limit: int, has_cursor: bool) -> str:
    parts = [f"status:{status_filter}"]
    if symbol:
        parts.append("symbol")
    if limit:
        parts.append("limit")
    if has_cursor:
        parts.append("cursor_present")
    return ",".join(parts)


def _diagnostic_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _order_execution_enabled() -> bool:
    return bool(getattr(settings, "TOSS_ORDER_EXECUTION_ENABLED", False))


def _bool_text(value: bool) -> str:
    return "true" if value else "false"
