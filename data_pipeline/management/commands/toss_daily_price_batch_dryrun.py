import logging
import re
from typing import Any, Mapping

from django.core.management.base import BaseCommand, CommandError

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
MAX_BATCH_SYMBOLS = 20
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Build Toss DailyPrice candidate rows for multiple symbols without saving them."

    def add_arguments(self, parser):
        parser.add_argument("--symbols", default="")
        parser.add_argument("--from-stock-db", action="store_true")
        parser.add_argument("--market", default="KR")
        parser.add_argument("--count", default=1)
        parser.add_argument("--before", default=None)
        parser.add_argument("--adjusted", default="true")
        parser.add_argument("--limit", default=None)
        parser.add_argument("--continue-on-error", action="store_true")
        parser.add_argument("--stop-on-error", action="store_true")
        parser.add_argument("--no-network", action="store_true")
        parser.add_argument("--raw", action="store_true")

    def handle(self, *args, **options):
        if options["continue_on_error"] and options["stop_on_error"]:
            raise CommandError("Use only one of --continue-on-error or --stop-on-error.")

        market = (options.get("market") or "").strip()
        count = _validate_count(options.get("count"))
        before = (options.get("before") or "").strip() or None
        adjusted = _parse_bool(options.get("adjusted"))
        limit = _validate_limit(options.get("limit"))
        stop_on_error = bool(options.get("stop_on_error"))
        symbols = _selected_symbols(
            symbols_option=options.get("symbols"),
            from_stock_db=bool(options.get("from_stock_db")),
            limit=limit,
        )

        if options["no_network"]:
            self._write_no_network_summary(symbols=symbols, market=market, count=count, adjusted=adjusted, before=before)
            return

        try:
            provider = _get_toss_provider_from_registry()
        except ValueError:
            self._write_registry_failure(symbols=symbols, market=market, reason="provider_not_registered")
            return
        except Exception:
            self._write_registry_failure(symbols=symbols, market=market, reason="registry_error")
            return

        results = []
        for symbol in symbols:
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
                row = _failure_result(symbol=symbol, reason=_safe_reason(exc), diagnostics=_safe_diagnostics(exc, before=before))
                results.append(row)
                if stop_on_error:
                    break
                continue
            except Exception:
                row = _failure_result(symbol=symbol, reason="provider_error", diagnostics={})
                results.append(row)
                if stop_on_error:
                    break
                continue

            candidates = result.get("candidates") if isinstance(result, Mapping) else []
            if not isinstance(candidates, list):
                candidates = []
            row = _success_result(
                symbol=symbol,
                market=market,
                candidates=candidates,
                raw=result.get("raw") if isinstance(result, Mapping) else None,
            )
            results.append(row)

        skipped_symbols = len(symbols) - len(results)
        summary = _summarize_results(results=results, skipped_symbols=skipped_symbols)
        self._write_result_summary(
            symbols=symbols,
            market=market,
            count=count,
            adjusted=adjusted,
            before=before,
            results=results,
            summary=summary,
            raw=bool(options.get("raw")),
            stopped_early=skipped_symbols > 0,
        )

    def _write_no_network_summary(
        self,
        *,
        symbols: list[str],
        market: str,
        count: int,
        adjusted: bool,
        before: str | None,
    ) -> None:
        symbol_count = len(symbols)
        self.stdout.write("Toss daily price batch dry-run: SKIPPED")
        self.stdout.write("reason: --no-network was provided")
        self.stdout.write("provider: toss")
        self.stdout.write("endpoint: /api/v1/candles")
        self.stdout.write("interval: 1d")
        self.stdout.write(f"market: {market}")
        self.stdout.write(f"count: {count}")
        self.stdout.write(f"adjusted: {_bool_text(adjusted)}")
        self.stdout.write("dry_run: true")
        self.stdout.write("network_call: false")
        self.stdout.write("commit: not_supported")
        self.stdout.write(f"symbol_count: {symbol_count}")
        self.stdout.write("candidate_count: 0")
        self.stdout.write("saved_count: 0")
        self.stdout.write("updated_count: 0")
        self.stdout.write(f"skipped_count: {symbol_count}")
        self.stdout.write("failed_count: 0")
        self.stdout.write("symbols:")
        for symbol in symbols:
            self.stdout.write(f"  - symbol: {symbol}")
            self.stdout.write("    status: skipped")
            self.stdout.write("    reason: no_network")

        _record_summary_log(
            status="skipped",
            safe_reason="no_network",
            target_symbol=_target_symbol(symbols),
            market=market,
            network_call=False,
            candidate_count=0,
            skipped_count=symbol_count,
            failed_count=0,
            count=count,
            adjusted=adjusted,
            before=before,
        )

    def _write_registry_failure(self, *, symbols: list[str], market: str, reason: str) -> None:
        failed_count = len(symbols)
        self.stdout.write("Toss daily price batch dry-run: FAILED")
        self.stdout.write(f"reason: {reason}")
        self.stdout.write("provider: toss")
        self.stdout.write("endpoint: /api/v1/candles")
        self.stdout.write(f"market: {market}")
        self.stdout.write("dry_run: true")
        self.stdout.write("network_call: false")
        self.stdout.write("commit: not_supported")
        self.stdout.write(f"symbol_count: {len(symbols)}")
        self.stdout.write("candidate_count: 0")
        self.stdout.write("saved_count: 0")
        self.stdout.write("updated_count: 0")
        self.stdout.write("skipped_count: 0")
        self.stdout.write(f"failed_count: {failed_count}")
        _record_summary_log(
            status="failed",
            safe_reason=reason,
            target_symbol=_target_symbol(symbols),
            market=market,
            network_call=False,
            candidate_count=0,
            skipped_count=0,
            failed_count=failed_count,
        )

    def _write_result_summary(
        self,
        *,
        symbols: list[str],
        market: str,
        count: int,
        adjusted: bool,
        before: str | None,
        results: list[dict[str, Any]],
        summary: dict[str, int | str],
        raw: bool,
        stopped_early: bool,
    ) -> None:
        status = str(summary["status"])
        self.stdout.write("Toss daily price batch dry-run: OK" if status in {"success", "partial"} else "Toss daily price batch dry-run: FAILED")
        self.stdout.write(f"status: {status}")
        self.stdout.write("provider: toss")
        self.stdout.write("endpoint: /api/v1/candles")
        self.stdout.write("interval: 1d")
        self.stdout.write(f"market: {market}")
        self.stdout.write(f"count: {count}")
        self.stdout.write(f"adjusted: {_bool_text(adjusted)}")
        self.stdout.write("dry_run: true")
        self.stdout.write("network_call: true")
        self.stdout.write("commit: not_supported")
        self.stdout.write(f"stop_on_error_triggered: {_bool_text(stopped_early)}")
        self.stdout.write(f"symbol_count: {len(symbols)}")
        self.stdout.write(f"candidate_count: {summary['candidate_count']}")
        self.stdout.write("saved_count: 0")
        self.stdout.write("updated_count: 0")
        self.stdout.write(f"skipped_count: {summary['skipped_count']}")
        self.stdout.write(f"failed_count: {summary['failed_count']}")
        self.stdout.write("symbols:")
        for row in results:
            self.stdout.write(f"  - symbol: {row['symbol']}")
            self.stdout.write(f"    status: {row['status']}")
            self.stdout.write(f"    candidate_count: {row['candidate_count']}")
            self.stdout.write(f"    existing_count: {row.get('existing_count', 0)}")
            if row.get("reason"):
                self.stdout.write(f"    reason: {row['reason']}")
            if row.get("first_date"):
                self.stdout.write(f"    first_date: {row['first_date']}")
            if row.get("first_close_price"):
                self.stdout.write(f"    first_close_price: {row['first_close_price']}")
            if raw:
                self.stdout.write(f"    raw_summary: {_format_raw_summary(row.get('raw'))}")

        _record_summary_log(
            status=status,
            safe_reason=_summary_safe_reason(status),
            target_symbol=_target_symbol(symbols),
            market=market,
            network_call=True,
            candidate_count=int(summary["candidate_count"]),
            skipped_count=int(summary["skipped_count"]),
            failed_count=int(summary["failed_count"]),
            count=count,
            adjusted=adjusted,
            before=before,
        )
        logger.info(
            "toss_daily_price_batch_result command=%s status=%s provider=toss symbol_count=%s "
            "candidate_count=%s skipped_count=%s failed_count=%s network_call=true dry_run=true",
            "toss_daily_price_batch_dryrun",
            status,
            len(symbols),
            summary["candidate_count"],
            summary["skipped_count"],
            summary["failed_count"],
        )


def _get_toss_provider_from_registry():
    provider = get_provider("toss")
    if isinstance(provider, type):
        return provider()
    return provider


def _selected_symbols(*, symbols_option: Any, from_stock_db: bool, limit: int | None) -> list[str]:
    symbols = []
    if symbols_option:
        symbols.extend(_parse_symbols(symbols_option))
    if from_stock_db:
        symbols.extend(Stock.objects.filter(is_active=True).order_by("code").values_list("code", flat=True))

    deduped = []
    seen = set()
    for symbol in symbols:
        clean_symbol = _validate_symbol(symbol)
        if clean_symbol in seen:
            continue
        deduped.append(clean_symbol)
        seen.add(clean_symbol)

    if limit is not None:
        deduped = deduped[:limit]
    if not deduped:
        raise CommandError("At least one symbol source is required.")
    if len(deduped) > MAX_BATCH_SYMBOLS:
        raise CommandError(f"Too many symbols for one Toss daily price batch dry-run. Use --limit <= {MAX_BATCH_SYMBOLS}.")
    return deduped


def _parse_symbols(value: Any) -> list[str]:
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _validate_symbol(symbol: Any) -> str:
    clean_symbol = str(symbol or "").strip()
    if not clean_symbol:
        raise CommandError("Invalid Toss daily price batch symbol.")
    if not SYMBOL_PATTERN.match(clean_symbol):
        raise CommandError("Invalid Toss daily price batch symbol.")
    return clean_symbol


def _validate_count(count: Any) -> int:
    try:
        clean_count = int(count)
    except (TypeError, ValueError) as exc:
        raise CommandError("Invalid Toss daily price batch count.") from exc
    if clean_count < 1 or clean_count > 200:
        raise CommandError("Invalid Toss daily price batch count.")
    return clean_count


def _validate_limit(limit: Any) -> int | None:
    if limit in {None, ""}:
        return None
    try:
        clean_limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise CommandError("Invalid Toss daily price batch limit.") from exc
    if clean_limit < 1 or clean_limit > MAX_BATCH_SYMBOLS:
        raise CommandError(f"Invalid Toss daily price batch limit. Use 1..{MAX_BATCH_SYMBOLS}.")
    return clean_limit


def _parse_bool(value: Any) -> bool:
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _success_result(*, symbol: str, market: str, candidates: list[Any], raw: Any) -> dict[str, Any]:
    stock = Stock.objects.filter(code=symbol).first()
    existing_count = 0
    if stock is not None:
        dates = [str(candidate.get("date") or "").strip() for candidate in candidates if isinstance(candidate, Mapping)]
        existing_count = DailyPrice.objects.filter(stock=stock, date__in=[date for date in dates if date]).count()

    first_candidate = next((candidate for candidate in candidates if isinstance(candidate, Mapping)), {})
    reason = ""
    skipped = 0
    if stock is None:
        reason = "stock_not_found"
        skipped = len(candidates) or 1
    elif not candidates:
        reason = "no_candidates"
        skipped = 1

    return {
        "symbol": symbol,
        "market": market,
        "status": "success" if not reason else "skipped",
        "reason": reason,
        "candidate_count": len(candidates),
        "existing_count": existing_count,
        "skipped_count": skipped,
        "failed_count": 0,
        "first_date": first_candidate.get("date") if isinstance(first_candidate, Mapping) else "",
        "first_close_price": first_candidate.get("close_price") if isinstance(first_candidate, Mapping) else "",
        "raw": raw,
    }


def _failure_result(*, symbol: str, reason: str, diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "status": "failed",
        "reason": reason,
        "candidate_count": 0,
        "existing_count": 0,
        "skipped_count": 0,
        "failed_count": 1,
        "diagnostics": dict(diagnostics),
    }


def _summarize_results(*, results: list[dict[str, Any]], skipped_symbols: int) -> dict[str, int | str]:
    candidate_count = sum(int(row.get("candidate_count") or 0) for row in results)
    skipped_count = skipped_symbols + sum(int(row.get("skipped_count") or 0) for row in results)
    failed_count = sum(int(row.get("failed_count") or 0) for row in results)
    success_count = sum(1 for row in results if row.get("status") == "success")
    if failed_count and success_count:
        status = "partial"
    elif failed_count:
        status = "failed"
    else:
        status = "success"
    return {
        "status": status,
        "candidate_count": candidate_count,
        "skipped_count": skipped_count,
        "failed_count": failed_count,
    }


def _record_summary_log(
    *,
    status: str,
    safe_reason: str,
    target_symbol: str = "",
    market: str = "",
    network_call: bool,
    candidate_count: int,
    skipped_count: int,
    failed_count: int,
    count: int = 0,
    adjusted: bool = True,
    before: str | None = None,
) -> None:
    record_data_ingestion_log(
        provider_name="toss",
        job_type="daily_price_batch_dryrun",
        target_type="daily_price",
        target_symbol=target_symbol,
        market=market,
        endpoint_name="/api/v1/candles",
        status=status,
        safe_reason=safe_reason,
        network_call=network_call,
        dry_run=True,
        commit_mode="not_supported",
        candidate_count=candidate_count,
        saved_count=0,
        updated_count=0,
        skipped_count=skipped_count,
        failed_count=failed_count,
        metadata={
            "command": "toss_daily_price_batch_dryrun",
            "provider": "toss",
            "symbol": target_symbol,
            "market": market,
            "endpoint_name": "/api/v1/candles",
            "interval": "1d",
            "count": count,
            "adjusted": adjusted,
            "network_call": network_call,
            "dry_run": True,
            "commit_mode": "not_supported",
            "candidate_count": candidate_count,
            "saved_count": 0,
            "updated_count": 0,
            "skipped_count": skipped_count,
            "failed_count": failed_count,
            "params_shape": "symbols,market,count,adjusted,before" if before else "symbols,market,count,adjusted",
        },
    )


def _target_symbol(symbols: list[str]) -> str:
    return symbols[0] if len(symbols) == 1 else ""


def _safe_reason(exc: Exception) -> str:
    if isinstance(exc, TossProviderDisabled):
        return "provider_disabled"
    if isinstance(exc, TossConfigurationError):
        return "credentials_missing"
    if isinstance(exc, TossAuthError):
        return "authentication_failed"
    if isinstance(exc, TossRateLimitError):
        return "rate_limit_exceeded"
    if isinstance(exc, TossOpenApiError):
        return "candle_request_failed"
    return "provider_error"


def _safe_diagnostics(exc: Exception, *, before: str | None = None) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {
        "params_shape": "symbols,market,count,adjusted,before" if before else "symbols,market,count,adjusted",
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


def _summary_safe_reason(status: str) -> str:
    if status == "success":
        return "batch_candidates_received"
    if status == "partial":
        return "batch_partial"
    if status == "skipped":
        return "no_network"
    return "batch_failed"


def _format_raw_summary(raw: Any) -> str:
    if not isinstance(raw, Mapping):
        return "none"
    allowed_keys = ("result_count", "next_before")
    parts = [f"{key}={raw[key]}" for key in allowed_keys if key in raw]
    return " ".join(parts) if parts else "none"


def _clean_diagnostic_value(value: Any) -> str:
    return str(value).replace("\n", " ").replace("\r", " ")[:120]


def _bool_text(value: bool) -> str:
    return "true" if value else "false"
