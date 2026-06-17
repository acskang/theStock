import logging
import re
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping

from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from django.db import transaction

from marketdata.models import DailyPrice
from stocks.models import Stock

from data_pipeline.providers import get_provider
from data_pipeline.providers.toss_exceptions import (
    TossAuthError,
    TossConfigurationError,
    TossOpenApiError,
    TossProviderDisabled,
    TossRateLimitError,
)
from data_pipeline.services.ingestion_log_writer import record_data_ingestion_log


SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9.\-]+$")
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Build Toss DailyPrice candidate rows without saving them."

    def add_arguments(self, parser):
        parser.add_argument("--symbol", required=True)
        parser.add_argument("--market", default="KR")
        parser.add_argument("--count", default=1)
        parser.add_argument("--before", default=None)
        parser.add_argument("--adjusted", default="true")
        parser.add_argument("--no-network", action="store_true")
        parser.add_argument("--raw", action="store_true")
        parser.add_argument("--commit", action="store_true")
        parser.add_argument("--confirm-save", action="store_true")
        parser.add_argument("--update-existing", action="store_true")

    def handle(self, *args, **options):
        symbol = _validate_symbol(options["symbol"])
        market = (options.get("market") or "").strip()
        count = _validate_count(options.get("count"))
        before = (options.get("before") or "").strip() or None
        adjusted = _parse_bool(options.get("adjusted"))
        commit_requested = bool(options.get("commit"))
        confirm_save = bool(options.get("confirm_save"))
        update_existing = bool(options.get("update_existing"))

        if options["no_network"]:
            self._write_status(
                "SKIPPED",
                symbol=symbol,
                market=market,
                reason="--no-network was provided",
                network_call=False,
                commit_requested=commit_requested,
            )
            return

        if commit_requested and not confirm_save:
            self._write_status(
                "FAILED",
                symbol=symbol,
                market=market,
                reason="confirm-save required",
                network_call=False,
                commit_requested=commit_requested,
            )
            return

        try:
            provider = _get_toss_provider_from_registry()
        except ValueError:
            self._write_status(
                "FAILED",
                symbol=symbol,
                market=market,
                reason="provider not registered",
                network_call=False,
                commit_requested=commit_requested,
            )
            return
        except Exception:
            self._write_status(
                "FAILED",
                symbol=symbol,
                market=market,
                reason="registry error",
                network_call=False,
                commit_requested=commit_requested,
            )
            return

        try:
            result = provider.get_daily_price_candidates(
                symbol,
                market=market,
                count=count,
                before=before,
                adjusted=adjusted,
            )
        except (
            TossProviderDisabled,
            TossConfigurationError,
            TossAuthError,
            TossRateLimitError,
            TossOpenApiError,
        ) as exc:
            reason = _safe_reason(exc)
            self._write_status(
                "FAILED",
                symbol=symbol,
                market=market,
                reason=reason,
                network_call=_network_call_for_reason(reason),
                commit_requested=commit_requested,
                diagnostics=_safe_diagnostics(exc, before=before),
            )
            return
        except Exception:
            self._write_status(
                "FAILED",
                symbol=symbol,
                market=market,
                reason="provider error",
                network_call=True,
                commit_requested=commit_requested,
            )
            return

        candidates = result.get("candidates") if isinstance(result, Mapping) else []
        if not isinstance(candidates, list):
            candidates = []
        save_result = _empty_save_result()
        if commit_requested and confirm_save:
            save_result = _save_daily_price_candidates(
                symbol=symbol,
                candidates=candidates,
                update_existing=update_existing,
            )
            if save_result["status"] == "failed":
                self._write_status(
                    "FAILED",
                    symbol=symbol,
                    market=market,
                    reason=save_result["reason"],
                    network_call=True,
                    commit_requested=commit_requested,
                    diagnostics={"params_shape": "symbol,interval,count,adjusted"},
                )
                return

        self.stdout.write("Toss daily price ingest dry-run: OK")
        self.stdout.write(f"symbol: {symbol}")
        self.stdout.write(f"market: {market}")
        self.stdout.write(f"provider: {result.get('provider', 'toss') if isinstance(result, Mapping) else 'toss'}")
        self.stdout.write(f"endpoint: {result.get('endpoint', '/api/v1/candles') if isinstance(result, Mapping) else '/api/v1/candles'}")
        self.stdout.write(f"interval: {result.get('interval', '1d') if isinstance(result, Mapping) else '1d'}")
        self.stdout.write(f"adjusted: {_bool_text(adjusted)}")
        self.stdout.write(f"dry_run: {_bool_text(not (commit_requested and confirm_save))}")
        if commit_requested:
            self.stdout.write("commit: saved" if confirm_save else "commit: rejected")
            self.stdout.write(f"update_existing: {_bool_text(update_existing)}")
        self.stdout.write("network_call: true")
        self.stdout.write(f"candidate_count: {len(candidates)}")
        self.stdout.write("candidates:")
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                continue
            self.stdout.write(f"  - date: {candidate.get('date')}")
            self.stdout.write(f"    open_price: {candidate.get('open_price')}")
            self.stdout.write(f"    high_price: {candidate.get('high_price')}")
            self.stdout.write(f"    low_price: {candidate.get('low_price')}")
            self.stdout.write(f"    close_price: {candidate.get('close_price')}")
            self.stdout.write(f"    volume: {candidate.get('volume')}")
            self.stdout.write(f"    currency: {candidate.get('currency')}")
            self.stdout.write(f"    source: {candidate.get('source')}")
        if commit_requested and confirm_save:
            self.stdout.write(f"created_count: {save_result['created_count']}")
            self.stdout.write(f"updated_count: {save_result['updated_count']}")
            self.stdout.write(f"skipped_count: {save_result['skipped_count']}")
        if options["raw"]:
            self.stdout.write(f"raw_summary: {_format_raw_summary(result.get('raw') if isinstance(result, Mapping) else None)}")

        dry_run = not (commit_requested and confirm_save)
        commit_mode = "saved" if commit_requested and confirm_save else ("rejected" if commit_requested else "not_requested")
        ingestion_log = record_data_ingestion_log(
            provider_name="toss",
            job_type="daily_price_ingest",
            target_type="daily_price",
            target_symbol=symbol,
            market=market,
            endpoint_name="/api/v1/candles",
            status="success",
            network_call=True,
            dry_run=dry_run,
            commit_mode=commit_mode,
            candidate_count=len(candidates),
            saved_count=save_result["created_count"],
            updated_count=save_result["updated_count"],
            skipped_count=save_result["skipped_count"],
            failed_count=0,
            metadata={
                "command": "toss_daily_price_ingest_dryrun",
                "provider": "toss",
                "symbol": symbol,
                "market": market,
                "endpoint_name": "/api/v1/candles",
                "interval": "1d",
                "count": count,
                "adjusted": adjusted,
                "network_call": True,
                "dry_run": dry_run,
                "commit_mode": commit_mode,
                "update_existing": update_existing,
                "candidate_count": len(candidates),
                "saved_count": save_result["created_count"],
                "updated_count": save_result["updated_count"],
                "skipped_count": save_result["skipped_count"],
                "failed_count": 0,
            },
        )
        if commit_requested and confirm_save:
            self.stdout.write(f"data_ingestion_log: {'recorded' if ingestion_log else 'record_failed'}")

        logger.info(
            "toss_ingest_dryrun_result command=%s status=ok provider=toss symbol=%s market=%s "
            "endpoint=%s interval=1d count=%s candidate_count=%s network_call=true dry_run=%s commit=%s "
            "created_count=%s updated_count=%s skipped_count=%s",
            "toss_daily_price_ingest_dryrun",
            symbol,
            market,
            "/api/v1/candles",
            count,
            len(candidates),
            _bool_text(not (commit_requested and confirm_save)),
            "saved" if commit_requested and confirm_save else ("rejected" if commit_requested else "not_requested"),
            save_result["created_count"],
            save_result["updated_count"],
            save_result["skipped_count"],
        )

    def _write_status(
        self,
        status: str,
        *,
        symbol: str,
        market: str,
        reason: str,
        network_call: bool,
        commit_requested: bool,
        diagnostics: Mapping[str, Any] | None = None,
    ) -> None:
        safe_diagnostics = dict(diagnostics or {})
        self.stdout.write(f"Toss daily price ingest dry-run: {status}")
        self.stdout.write(f"symbol: {symbol}")
        self.stdout.write(f"market: {market}")
        self.stdout.write(f"reason: {reason}")
        self.stdout.write("dry_run: true")
        if commit_requested:
            self.stdout.write("commit: rejected")
        self.stdout.write(f"network_call: {_bool_text(network_call)}")
        self.stdout.write("provider: toss")
        self.stdout.write("registry_path: true")
        for key in ("http_status_code", "error_code", "error_field", "safe_message", "params_shape"):
            if key in safe_diagnostics and safe_diagnostics[key] not in {None, ""}:
                self.stdout.write(f"{key}: {safe_diagnostics[key]}")

        log_method = logger.warning if status == "FAILED" else logger.info
        log_method(
            "toss_ingest_dryrun_result command=%s status=%s provider=toss reason=%s symbol=%s market=%s "
            "endpoint=%s interval=1d network_call=%s dry_run=true commit=%s diagnostics=%s",
            "toss_daily_price_ingest_dryrun",
            status.lower(),
            reason,
            symbol,
            market,
            "/api/v1/candles",
            _bool_text(network_call),
            "rejected" if commit_requested else "not_requested",
            _format_diagnostics(safe_diagnostics),
        )
        record_data_ingestion_log(
            provider_name="toss",
            job_type="daily_price_ingest",
            target_type="daily_price",
            target_symbol=symbol,
            market=market,
            endpoint_name="/api/v1/candles",
            status=_log_status(status),
            safe_reason=_log_safe_reason(reason),
            error_code=str(safe_diagnostics.get("error_code", "")),
            http_status_code=_diagnostic_http_status_code(safe_diagnostics.get("http_status_code")),
            network_call=network_call,
            dry_run=True,
            commit_mode="rejected" if commit_requested else "not_requested",
            failed_count=1 if status == "FAILED" else 0,
            metadata={
                "command": "toss_daily_price_ingest_dryrun",
                "provider": "toss",
                "symbol": symbol,
                "market": market,
                "endpoint_name": "/api/v1/candles",
                "interval": "1d",
                "network_call": network_call,
                "dry_run": True,
                "commit_mode": "rejected" if commit_requested else "not_requested",
                "http_status_code": safe_diagnostics.get("http_status_code"),
                "error_code": safe_diagnostics.get("error_code", ""),
                "error_field": safe_diagnostics.get("error_field", ""),
                "safe_message": safe_diagnostics.get("safe_message", ""),
                "params_shape": safe_diagnostics.get("params_shape", ""),
                "failed_count": 1 if status == "FAILED" else 0,
            },
        )


def _get_toss_provider_from_registry():
    provider = get_provider("toss")
    if isinstance(provider, type):
        return provider()
    return provider


def _save_daily_price_candidates(
    *,
    symbol: str,
    candidates: list[Any],
    update_existing: bool,
) -> dict[str, Any]:
    try:
        stock = Stock.objects.get(code=symbol)
    except Stock.DoesNotExist:
        return _failed_save_result("stock not found")

    result = _empty_save_result()
    try:
        with transaction.atomic():
            for candidate in candidates:
                if not isinstance(candidate, Mapping):
                    result["skipped_count"] += 1
                    continue
                values = _build_daily_price_values(candidate, stock=stock)
                existing = DailyPrice.objects.filter(stock=stock, date=values["date"]).first()
                if existing is not None and not update_existing:
                    result["skipped_count"] += 1
                    continue
                if existing is not None:
                    for field, value in values.items():
                        if field != "date":
                            setattr(existing, field, value)
                    existing.full_clean()
                    existing.save()
                    result["updated_count"] += 1
                    continue
                row = DailyPrice(stock=stock, **values)
                row.full_clean()
                row.save()
                result["created_count"] += 1
    except (InvalidOperation, TypeError, ValueError, ValidationError):
        return _failed_save_result("candidate validation failed")
    return result


def _build_daily_price_values(candidate: Mapping[str, Any], *, stock: Stock) -> dict[str, Any]:
    trade_date = _parse_date(candidate.get("date"))
    open_price = _parse_decimal(candidate.get("open_price"))
    high_price = _parse_decimal(candidate.get("high_price"))
    low_price = _parse_decimal(candidate.get("low_price"))
    close_price = _parse_decimal(candidate.get("close_price"))
    volume = _parse_volume(candidate.get("volume"))
    change_rate = _calculate_change_rate(stock=stock, trade_date=trade_date, close_price=close_price)
    return {
        "date": trade_date,
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "close_price": close_price,
        "volume": volume,
        "change_rate": change_rate,
    }


def _parse_date(value: Any) -> date:
    clean_value = str(value or "").strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", clean_value):
        raise ValueError("invalid date")
    return date.fromisoformat(clean_value)


def _parse_decimal(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _parse_volume(value: Any) -> int:
    volume = int(Decimal(str(value or 0)))
    if volume < 0:
        raise ValueError("invalid volume")
    return volume


def _calculate_change_rate(*, stock: Stock, trade_date: date, close_price: Decimal) -> Decimal | None:
    previous = (
        DailyPrice.objects.filter(stock=stock, date__lt=trade_date)
        .order_by("-date")
        .only("close_price")
        .first()
    )
    if previous is None or previous.close_price in {None, Decimal("0")}:
        return None
    return ((close_price - previous.close_price) / previous.close_price * Decimal("100")).quantize(
        Decimal("0.0001"),
        rounding=ROUND_HALF_UP,
    )


def _empty_save_result() -> dict[str, Any]:
    return {
        "status": "ok",
        "reason": "",
        "created_count": 0,
        "updated_count": 0,
        "skipped_count": 0,
    }


def _failed_save_result(reason: str) -> dict[str, Any]:
    result = _empty_save_result()
    result["status"] = "failed"
    result["reason"] = reason
    return result


def _validate_symbol(symbol: str) -> str:
    clean_symbol = str(symbol or "").strip()
    if not clean_symbol:
        raise CommandError("symbol is required.")
    if "," in clean_symbol:
        raise CommandError("Only one Toss daily price dry-run symbol is supported.")
    if not SYMBOL_PATTERN.match(clean_symbol):
        raise CommandError("Invalid Toss daily price dry-run symbol.")
    return clean_symbol


def _validate_count(count: Any) -> int:
    try:
        clean_count = int(count)
    except (TypeError, ValueError) as exc:
        raise CommandError("Invalid Toss daily price dry-run count.") from exc
    if clean_count < 1 or clean_count > 200:
        raise CommandError("Invalid Toss daily price dry-run count.")
    return clean_count


def _parse_bool(value: Any) -> bool:
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _safe_reason(exc: Exception) -> str:
    if isinstance(exc, TossProviderDisabled):
        return "provider disabled"
    if isinstance(exc, TossConfigurationError):
        return "credentials missing"
    if isinstance(exc, TossAuthError):
        return "authentication failed"
    if isinstance(exc, TossRateLimitError):
        return "rate limit exceeded"
    if isinstance(exc, TossOpenApiError):
        return "candle request failed"
    return "provider error"


def _safe_diagnostics(exc: Exception, *, before: str | None = None) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "params_shape": "symbol,interval,count,adjusted,before" if before else "symbol,interval,count,adjusted",
    }
    for attr, key in (
        ("http_status_code", "http_status_code"),
        ("status_code", "http_status_code"),
        ("error_code", "error_code"),
        ("error_field", "error_field"),
        ("field", "error_field"),
        ("safe_message", "safe_message"),
    ):
        value = getattr(exc, attr, None)
        if value in {None, ""}:
            continue
        diagnostics.setdefault(key, _clean_diagnostic_value(value))
    return diagnostics


def _network_call_for_reason(reason: str) -> bool:
    return reason not in {
        "provider not registered",
        "provider disabled",
        "credentials missing",
        "invalid symbol",
        "invalid count",
        "no-network",
        "registry error",
    }


def _format_raw_summary(raw: Any) -> str:
    if not isinstance(raw, Mapping):
        return "none"
    allowed_keys = ("result_count", "next_before")
    parts = [f"{key}={raw[key]}" for key in allowed_keys if key in raw]
    return " ".join(parts) if parts else "none"


def _format_diagnostics(diagnostics: Mapping[str, Any]) -> str:
    if not diagnostics:
        return "none"
    allowed_keys = ("http_status_code", "error_code", "error_field", "safe_message", "params_shape")
    parts = [f"{key}={diagnostics[key]}" for key in allowed_keys if key in diagnostics and diagnostics[key] not in {None, ""}]
    return " ".join(parts) if parts else "none"


def _clean_diagnostic_value(value: Any) -> str:
    return str(value).replace("\n", " ").replace("\r", " ")[:120]


def _diagnostic_http_status_code(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _log_status(status: str) -> str:
    if status == "SKIPPED":
        return "skipped"
    return "failed" if status == "FAILED" else "success"


def _log_safe_reason(reason: str) -> str:
    return {
        "--no-network was provided": "no_network",
        "confirm-save required": "confirm-save_required",
        "provider not registered": "provider_not_registered",
        "registry error": "registry_error",
        "provider disabled": "provider_disabled",
        "credentials missing": "credentials_missing",
        "authentication failed": "authentication_failed",
        "rate limit exceeded": "rate_limit_exceeded",
        "candle request failed": "candle_request_failed",
        "stock not found": "stock_not_found",
        "candidate validation failed": "candidate_validation_failed",
        "provider error": "provider_error",
    }.get(reason, reason)
