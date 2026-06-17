import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from data_pipeline.providers.toss_auth import issue_toss_access_token, is_toss_provider_enabled
from data_pipeline.providers.toss_client import TossOpenApiClient
from data_pipeline.providers.toss_exceptions import (
    TossAuthError,
    TossConfigurationError,
    TossOpenApiError,
    TossProviderDisabled,
    TossRateLimitError,
)
from data_pipeline.providers.toss_masking import is_configured
from data_pipeline.services.ingestion_log_writer import record_data_ingestion_log


PRICE_PATH = "/api/v1/prices"
SYMBOL_PATTERN = re.compile(r"^[A-Za-z0-9.\-]+$")
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run a Toss OpenAPI quote smoke test."

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

        if not is_toss_provider_enabled(getattr(settings, "TOSS_INVEST_PROVIDER_ENABLED", False)):
            self._write_status(
                "SKIPPED",
                symbol=symbol,
                market=market,
                reason="TOSS_INVEST_PROVIDER_ENABLED is false",
                network_call=False,
                commit_requested=commit_requested,
            )
            return

        client_id = getattr(settings, "TOSS_INVEST_CLIENT_ID", "")
        client_secret = getattr(settings, "TOSS_INVEST_CLIENT_SECRET", "")
        if not (is_configured(client_id) and is_configured(client_secret)):
            self._write_status(
                "FAILED",
                symbol=symbol,
                market=market,
                reason="TOSS_INVEST_CLIENT_ID or TOSS_INVEST_CLIENT_SECRET is missing",
                network_call=False,
                commit_requested=commit_requested,
            )
            return

        try:
            token = issue_toss_access_token(transport=_urllib_form_transport)
            client = TossOpenApiClient(
                token_provider=lambda: token,
                transport=_urllib_json_transport,
            )
            response = client.request("GET", PRICE_PATH, params={"symbols": symbol}, account_required=False)
        except TossRateLimitError:
            self._write_status(
                "FAILED",
                symbol=symbol,
                market=market,
                reason="rate limit exceeded",
                network_call=True,
                commit_requested=commit_requested,
            )
            return
        except (TossAuthError, TossProviderDisabled):
            self._write_status(
                "FAILED",
                symbol=symbol,
                market=market,
                reason="authentication failed",
                network_call=True,
                commit_requested=commit_requested,
            )
            return
        except TossConfigurationError:
            self._write_status(
                "FAILED",
                symbol=symbol,
                market=market,
                reason="credentials missing",
                network_call=False,
                commit_requested=commit_requested,
            )
            return
        except TossOpenApiError:
            self._write_status(
                "FAILED",
                symbol=symbol,
                market=market,
                reason="quote request failed",
                network_call=True,
                commit_requested=commit_requested,
            )
            return

        normalized = _normalize_price_response(response.data, symbol)
        self.stdout.write("Toss quote smoke: OK")
        self.stdout.write(f"symbol: {symbol}")
        self.stdout.write(f"market: {market}")
        self.stdout.write("provider: toss")
        self.stdout.write("dry_run: true")
        if commit_requested:
            self.stdout.write("commit: not_supported_in_step_10")
        self.stdout.write("network_call: true")
        self.stdout.write("normalized:")
        self.stdout.write(f"  symbol: {normalized['symbol']}")
        self.stdout.write(f"  price: {normalized['price']}")
        self.stdout.write(f"  currency: {normalized['currency']}")
        self.stdout.write(f"  as_of: {normalized['as_of']}")
        if options["raw"]:
            self.stdout.write(f"raw_summary: {_summarize_raw_response(response.data)}")
        logger.info(
            "toss_smoke_result command=%s status=ok provider=toss symbol=%s market=%s endpoint=%s "
            "network_call=true dry_run=true commit=%s",
            "toss_quote_smoke",
            symbol,
            market,
            PRICE_PATH,
            "not_supported" if commit_requested else "not_requested",
        )
        record_data_ingestion_log(
            provider_name="toss",
            job_type="smoke",
            target_type="quote",
            target_symbol=symbol,
            market=market,
            endpoint_name=PRICE_PATH,
            status="success",
            network_call=True,
            dry_run=True,
            commit_mode="not_supported" if commit_requested else "not_requested",
            metadata={
                "command": "toss_quote_smoke",
                "provider": "toss",
                "symbol": symbol,
                "market": market,
                "endpoint_name": PRICE_PATH,
                "network_call": True,
                "dry_run": True,
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
        commit_requested: bool,
    ) -> None:
        self.stdout.write(f"Toss quote smoke: {status}")
        self.stdout.write(f"symbol: {symbol}")
        self.stdout.write(f"market: {market}")
        self.stdout.write(f"reason: {reason}")
        self.stdout.write("dry_run: true")
        if commit_requested:
            self.stdout.write("commit: not_supported_in_step_10")
        self.stdout.write(f"network_call: {_bool_text(network_call)}")
        log_method = logger.warning if status == "FAILED" else logger.info
        log_method(
            "toss_smoke_result command=%s status=%s provider=toss reason=%s symbol=%s market=%s endpoint=%s "
            "network_call=%s dry_run=true commit=%s",
            "toss_quote_smoke",
            status.lower(),
            _safe_reason(reason),
            symbol,
            market,
            PRICE_PATH,
            _bool_text(network_call),
            "not_supported" if commit_requested else "not_requested",
        )
        record_data_ingestion_log(
            provider_name="toss",
            job_type="smoke",
            target_type="quote",
            target_symbol=symbol,
            market=market,
            endpoint_name=PRICE_PATH,
            status=_log_status(status),
            safe_reason=_log_safe_reason(reason),
            network_call=network_call,
            dry_run=True,
            commit_mode="not_supported" if commit_requested else "not_requested",
            metadata={
                "command": "toss_quote_smoke",
                "provider": "toss",
                "symbol": symbol,
                "market": market,
                "endpoint_name": PRICE_PATH,
                "network_call": network_call,
                "dry_run": True,
                "commit_mode": "not_supported" if commit_requested else "not_requested",
            },
        )


class _SimpleResponse:
    def __init__(self, status_code, data, headers=None):
        self.status_code = status_code
        self._data = data
        self.headers = headers or {}

    def json(self):
        return self._data


def _validate_symbol(symbol):
    clean_symbol = str(symbol or "").strip()
    if not clean_symbol:
        raise CommandError("symbol is required.")
    if "," in clean_symbol:
        raise CommandError("Only one Toss quote smoke symbol is supported.")
    if not SYMBOL_PATTERN.match(clean_symbol):
        raise CommandError("Invalid Toss quote smoke symbol.")
    return clean_symbol


def _urllib_form_transport(method, url, *, headers=None, data=None, json=None, params=None, timeout=None):
    if method.upper() != "POST":
        raise TossOpenApiError("Toss token request only supports POST.")
    if json is not None:
        raise TossOpenApiError("Toss token request does not send JSON request bodies.")

    request_data = urllib.parse.urlencode(data or {}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=request_data,
        headers=dict(headers or {}),
        method=method.upper(),
    )
    return _open_json_request(request, timeout=timeout)


def _urllib_json_transport(method, url, *, headers=None, params=None, data=None, json=None, timeout=None):
    if method.upper() != "GET":
        raise TossOpenApiError("Toss quote smoke only supports GET quote requests.")
    parsed_url = urllib.parse.urlparse(url)
    if parsed_url.path != PRICE_PATH:
        raise TossOpenApiError("Toss quote smoke only supports the current price endpoint.")
    if data is not None or json is not None:
        raise TossOpenApiError("Toss quote smoke does not send request bodies.")

    query = urllib.parse.urlencode(params or {})
    request_url = urllib.parse.urlunparse(parsed_url._replace(query=query))
    request = urllib.request.Request(
        request_url,
        headers=dict(headers or {}),
        method=method.upper(),
    )
    return _open_json_request(request, timeout=timeout)


def _open_json_request(request, *, timeout=None):
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return _SimpleResponse(
                response.getcode(),
                _load_response_json(response.read()),
                headers=dict(response.headers.items()),
            )
    except urllib.error.HTTPError as exc:
        return _SimpleResponse(
            exc.code,
            _load_response_json(exc.read()),
            headers=dict(exc.headers.items()) if exc.headers else {},
        )
    except urllib.error.URLError as exc:
        raise TossOpenApiError("Toss endpoint request failed.") from exc


def _load_response_json(raw_body):
    if not raw_body:
        return {}
    try:
        return json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"error": "invalid_json_response"}


def _normalize_price_response(data, symbol):
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, list) or not result:
        return {"symbol": symbol, "price": None, "currency": None, "as_of": None}

    selected = None
    for item in result:
        if isinstance(item, dict) and str(item.get("symbol", "")).upper() == symbol.upper():
            selected = item
            break
    if selected is None:
        selected = result[0] if isinstance(result[0], dict) else {}

    return {
        "symbol": selected.get("symbol") or symbol,
        "price": _normalize_price(selected.get("lastPrice")),
        "currency": selected.get("currency"),
        "as_of": selected.get("timestamp"),
    }


def _normalize_price(value):
    if value is None:
        return None
    try:
        return str(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return str(value)


def _summarize_raw_response(data):
    if isinstance(data, dict):
        result = data.get("result")
        result_count = len(result) if isinstance(result, list) else 0
        return f"keys={','.join(sorted(map(str, data.keys())))} result_count={result_count}"
    return f"type={type(data).__name__}"


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _safe_reason(reason: str) -> str:
    return str(reason).strip()


def _log_status(status: str) -> str:
    if status == "SKIPPED":
        return "skipped"
    return "failed" if status == "FAILED" else "success"


def _log_safe_reason(reason: str) -> str:
    safe_reason = _safe_reason(reason)
    return {
        "--no-network was provided": "no_network",
        "TOSS_INVEST_PROVIDER_ENABLED is false": "provider_disabled",
        "TOSS_INVEST_CLIENT_ID or TOSS_INVEST_CLIENT_SECRET is missing": "credentials_missing",
        "rate limit exceeded": "rate_limit_exceeded",
        "authentication failed": "authentication_failed",
        "credentials missing": "credentials_missing",
        "quote request failed": "quote_request_failed",
    }.get(safe_reason, safe_reason)
