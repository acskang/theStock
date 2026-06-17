import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings
from django.core.management.base import BaseCommand

from data_pipeline.providers.toss_auth import issue_toss_access_token, is_toss_provider_enabled
from data_pipeline.providers.toss_exceptions import (
    TossAuthError,
    TossConfigurationError,
    TossOpenApiError,
    TossProviderDisabled,
    TossRateLimitError,
)
from data_pipeline.providers.toss_masking import is_configured, mask_secret
from data_pipeline.services.ingestion_log_writer import record_data_ingestion_log


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run a Toss OpenAPI token smoke test."

    def add_arguments(self, parser):
        parser.add_argument(
            "--no-network",
            action="store_true",
            help="Check configuration only and skip the token endpoint request.",
        )

    def handle(self, *args, **options):
        if options["no_network"]:
            self._write_result("SKIPPED", "reason: --no-network was provided", network_call=False)
            return

        if not is_toss_provider_enabled(getattr(settings, "TOSS_INVEST_PROVIDER_ENABLED", False)):
            self._write_result(
                "SKIPPED",
                "reason: TOSS_INVEST_PROVIDER_ENABLED is false",
                network_call=False,
            )
            return

        client_id = getattr(settings, "TOSS_INVEST_CLIENT_ID", "")
        client_secret = getattr(settings, "TOSS_INVEST_CLIENT_SECRET", "")
        if not (is_configured(client_id) and is_configured(client_secret)):
            self._write_result(
                "FAILED",
                "reason: TOSS_INVEST_CLIENT_ID or TOSS_INVEST_CLIENT_SECRET is missing",
                network_call=False,
            )
            return

        try:
            token = issue_toss_access_token(transport=_urllib_form_transport)
        except TossRateLimitError:
            self._write_result("FAILED", "reason: rate limit exceeded", network_call=True)
            return
        except (TossAuthError, TossProviderDisabled):
            self._write_result("FAILED", "reason: authentication failed", network_call=True)
            return
        except TossConfigurationError:
            self._write_result("FAILED", "reason: credentials missing", network_call=False)
            return
        except TossOpenApiError:
            self._write_result("FAILED", "reason: token endpoint request failed", network_call=True)
            return

        self.stdout.write("Toss token smoke: OK")
        self.stdout.write(f"access_token: {mask_secret(token.access_token)}")
        self.stdout.write(f"token_type: {token.token_type}")
        self.stdout.write(f"expires_in: {token.expires_in}")
        self.stdout.write("network_call: true")
        logger.info(
            "toss_smoke_result command=%s status=ok provider=toss network_call=true dry_run=true "
            "token_type=%s expires_in=%s",
            "toss_token_smoke",
            token.token_type,
            token.expires_in,
        )
        record_data_ingestion_log(
            provider_name="toss",
            job_type="smoke",
            target_type="auth",
            endpoint_name="token",
            status="success",
            network_call=True,
            dry_run=True,
            commit_mode="not_requested",
            metadata={
                "command": "toss_token_smoke",
                "provider": "toss",
                "network_call": True,
                "dry_run": True,
            },
        )

    def _write_result(self, status: str, reason: str, *, network_call: bool) -> None:
        self.stdout.write(f"Toss token smoke: {status}")
        self.stdout.write(reason)
        self.stdout.write(f"network_call: {_bool_text(network_call)}")
        log_method = logger.warning if status == "FAILED" else logger.info
        log_method(
            "toss_smoke_result command=%s status=%s provider=toss reason=%s network_call=%s dry_run=true",
            "toss_token_smoke",
            status.lower(),
            _safe_reason(reason),
            _bool_text(network_call),
        )
        record_data_ingestion_log(
            provider_name="toss",
            job_type="smoke",
            target_type="auth",
            endpoint_name="token",
            status=_log_status(status, reason),
            safe_reason=_log_safe_reason(reason),
            network_call=network_call,
            dry_run=True,
            commit_mode="not_requested",
            metadata={
                "command": "toss_token_smoke",
                "provider": "toss",
                "network_call": network_call,
                "dry_run": True,
            },
        )


class _SimpleResponse:
    def __init__(self, status_code, data, headers=None):
        self.status_code = status_code
        self._data = data
        self.headers = headers or {}

    def json(self):
        return self._data


def _urllib_form_transport(method, url, *, headers=None, data=None, json=None, params=None, timeout=None):
    if method.upper() != "POST":
        raise TossOpenApiError("Toss token smoke only supports POST token requests.")
    if json is not None:
        raise TossOpenApiError("Toss token smoke does not send JSON request bodies.")

    request_data = urllib.parse.urlencode(data or {}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=request_data,
        headers=dict(headers or {}),
        method=method.upper(),
    )

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
        raise TossOpenApiError("Toss token endpoint request failed.") from exc


def _load_response_json(raw_body):
    if not raw_body:
        return {}
    try:
        return json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"error": "invalid_json_response"}


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _safe_reason(reason: str) -> str:
    return str(reason).removeprefix("reason: ").strip()


def _log_status(status: str, reason: str) -> str:
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
        "token endpoint request failed": "token_endpoint_request_failed",
    }.get(safe_reason, safe_reason)
