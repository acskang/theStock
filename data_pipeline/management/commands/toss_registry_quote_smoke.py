import logging
import re
from typing import Any, Mapping

from django.core.management.base import BaseCommand, CommandError

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
    help = "Run a Toss provider registry get_quote smoke test."

    def add_arguments(self, parser):
        parser.add_argument("--symbol", required=True)
        parser.add_argument("--market", default="")
        parser.add_argument("--no-network", action="store_true")
        parser.add_argument("--raw", action="store_true")
        parser.add_argument("--commit", action="store_true")

    def handle(self, *args, **options):
        symbol = _validate_symbol(options["symbol"])
        market = (options.get("market") or "").strip()
        commit_requested = bool(options.get("commit"))

        provider = None
        provider_registered = False
        try:
            provider = _get_toss_provider_from_registry()
            provider_registered = True
        except ValueError:
            self._write_status(
                "FAILED",
                symbol=symbol,
                market=market,
                reason="provider not registered",
                network_call=False,
                provider_registered=False,
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
                provider_registered=False,
                commit_requested=commit_requested,
            )
            return

        if options["no_network"]:
            self._write_status(
                "SKIPPED",
                symbol=symbol,
                market=market,
                reason="--no-network was provided",
                network_call=False,
                provider_registered=provider_registered,
                commit_requested=commit_requested,
            )
            return

        try:
            result = provider.get_quote(symbol, market)
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
                provider_registered=provider_registered,
                commit_requested=commit_requested,
            )
            return
        except Exception:
            self._write_status(
                "FAILED",
                symbol=symbol,
                market=market,
                reason="provider error",
                network_call=True,
                provider_registered=provider_registered,
                commit_requested=commit_requested,
            )
            return

        normalized = result.get("normalized") if isinstance(result, Mapping) else {}
        if not isinstance(normalized, Mapping):
            normalized = {}

        self.stdout.write("Toss registry quote smoke: OK")
        self.stdout.write(f"symbol: {symbol}")
        self.stdout.write(f"market: {market}")
        self.stdout.write(f"provider: {result.get('provider', 'toss') if isinstance(result, Mapping) else 'toss'}")
        self.stdout.write("dry_run: true")
        if commit_requested:
            self.stdout.write("commit: not_supported_in_step_16")
        self.stdout.write("network_call: true")
        self.stdout.write("registry_path: true")
        self.stdout.write(f"provider_registered: {_bool_text(provider_registered)}")
        self.stdout.write("normalized:")
        self.stdout.write(f"  symbol: {normalized.get('symbol')}")
        self.stdout.write(f"  price: {normalized.get('price')}")
        self.stdout.write(f"  currency: {normalized.get('currency')}")
        self.stdout.write(f"  as_of: {normalized.get('as_of')}")
        if options["raw"]:
            self.stdout.write(f"raw_summary: {_format_raw_summary(result.get('raw') if isinstance(result, Mapping) else None)}")

        logger.info(
            "toss_smoke_result command=%s status=ok provider=toss symbol=%s market=%s "
            "network_call=true dry_run=true registry_path=true provider_registered=%s commit=%s",
            "toss_registry_quote_smoke",
            symbol,
            market,
            _bool_text(provider_registered),
            "not_supported" if commit_requested else "not_requested",
        )
        record_data_ingestion_log(
            provider_name="toss",
            job_type="smoke",
            target_type="quote",
            target_symbol=symbol,
            market=market,
            endpoint_name="registry_get_quote",
            status="success",
            network_call=True,
            dry_run=True,
            commit_mode="not_supported" if commit_requested else "not_requested",
            metadata={
                "command": "toss_registry_quote_smoke",
                "provider": "toss",
                "symbol": symbol,
                "market": market,
                "network_call": True,
                "dry_run": True,
                "registry_path": True,
                "provider_registered": provider_registered,
                "commit_mode": "not_supported" if commit_requested else "not_requested",
            },
        )

    def _write_status(
        self,
        status: str,
        *,
        symbol: str,
        market: str,
        reason: str,
        network_call: bool,
        provider_registered: bool,
        commit_requested: bool,
    ) -> None:
        self.stdout.write(f"Toss registry quote smoke: {status}")
        self.stdout.write(f"symbol: {symbol}")
        self.stdout.write(f"market: {market}")
        self.stdout.write(f"reason: {reason}")
        self.stdout.write("dry_run: true")
        if commit_requested:
            self.stdout.write("commit: not_supported_in_step_16")
        self.stdout.write(f"network_call: {_bool_text(network_call)}")
        self.stdout.write("registry_path: true")
        self.stdout.write(f"provider_registered: {_bool_text(provider_registered)}")

        log_method = logger.warning if status == "FAILED" else logger.info
        log_method(
            "toss_smoke_result command=%s status=%s provider=toss reason=%s symbol=%s market=%s "
            "network_call=%s dry_run=true registry_path=true provider_registered=%s commit=%s",
            "toss_registry_quote_smoke",
            status.lower(),
            reason,
            symbol,
            market,
            _bool_text(network_call),
            _bool_text(provider_registered),
            "not_supported" if commit_requested else "not_requested",
        )
        record_data_ingestion_log(
            provider_name="toss",
            job_type="smoke",
            target_type="quote",
            target_symbol=symbol,
            market=market,
            endpoint_name="registry_get_quote",
            status=_log_status(status),
            safe_reason=_log_safe_reason(reason),
            network_call=network_call,
            dry_run=True,
            commit_mode="not_supported" if commit_requested else "not_requested",
            metadata={
                "command": "toss_registry_quote_smoke",
                "provider": "toss",
                "symbol": symbol,
                "market": market,
                "network_call": network_call,
                "dry_run": True,
                "registry_path": True,
                "provider_registered": provider_registered,
                "commit_mode": "not_supported" if commit_requested else "not_requested",
            },
        )


def _get_toss_provider_from_registry():
    provider = get_provider("toss")
    if isinstance(provider, type):
        return provider()
    return provider


def _validate_symbol(symbol: str) -> str:
    clean_symbol = str(symbol or "").strip()
    if not clean_symbol:
        raise CommandError("symbol is required.")
    if "," in clean_symbol:
        raise CommandError("Only one Toss registry quote smoke symbol is supported.")
    if not SYMBOL_PATTERN.match(clean_symbol):
        raise CommandError("Invalid Toss registry quote smoke symbol.")
    return clean_symbol


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
        return "quote request failed"
    return "provider error"


def _network_call_for_reason(reason: str) -> bool:
    return reason not in {
        "provider not registered",
        "provider disabled",
        "credentials missing",
        "invalid symbol",
        "no-network",
        "registry error",
    }


def _format_raw_summary(raw: Any) -> str:
    if not isinstance(raw, Mapping):
        return "none"
    allowed_keys = ("matched_symbol", "result_count")
    parts = [f"{key}={raw[key]}" for key in allowed_keys if key in raw]
    return " ".join(parts) if parts else "none"


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _log_status(status: str) -> str:
    if status == "SKIPPED":
        return "skipped"
    return "failed" if status == "FAILED" else "success"


def _log_safe_reason(reason: str) -> str:
    return {
        "--no-network was provided": "no_network",
        "provider not registered": "provider_not_registered",
        "registry error": "registry_error",
        "provider disabled": "provider_disabled",
        "credentials missing": "credentials_missing",
        "authentication failed": "authentication_failed",
        "rate limit exceeded": "rate_limit_exceeded",
        "quote request failed": "quote_request_failed",
        "provider error": "provider_error",
    }.get(reason, reason)
