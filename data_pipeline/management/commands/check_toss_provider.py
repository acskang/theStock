import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from data_pipeline.providers.toss_auth import is_toss_provider_enabled
from data_pipeline.providers.toss_masking import is_configured, mask_account_id, mask_secret
from data_pipeline.providers.toss_order_guard import is_toss_order_execution_enabled
from data_pipeline.providers.toss_provider import TossOpenApiProvider
from data_pipeline.services.ingestion_log_writer import record_data_ingestion_log


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Check Toss OpenAPI provider configuration without making network calls."

    def handle(self, *args, **options):
        provider = TossOpenApiProvider()
        health = provider.health_check()

        client_id = getattr(settings, "TOSS_INVEST_CLIENT_ID", "")
        client_secret = getattr(settings, "TOSS_INVEST_CLIENT_SECRET", "")
        account_id = getattr(settings, "TOSS_INVEST_ACCOUNT_ID", "")
        token_url = getattr(settings, "TOSS_INVEST_TOKEN_URL", "")
        order_execution_enabled = is_toss_order_execution_enabled(
            getattr(settings, "TOSS_ORDER_EXECUTION_ENABLED", False)
        )

        self.stdout.write("TossOpenApiProvider")
        self.stdout.write(f"- enabled: {_bool_text(is_toss_provider_enabled(getattr(settings, 'TOSS_INVEST_PROVIDER_ENABLED', False)))}")
        self.stdout.write(f"- status: {health.get('status', 'unknown')}")
        self.stdout.write(f"- base_url: {getattr(provider.client, 'base_url', '')}")
        self.stdout.write(
            f"- token_url: {'configured_explicitly' if is_configured(token_url) else 'configured_by_default'}"
        )
        self.stdout.write(f"- client_id: {mask_secret(client_id) if is_configured(client_id) else 'missing'}")
        self.stdout.write(f"- client_secret: {'configured' if is_configured(client_secret) else 'missing'}")
        self.stdout.write(f"- account_id: {mask_account_id(account_id) if is_configured(account_id) else 'missing'}")
        self.stdout.write(f"- order_execution_enabled: {_bool_text(order_execution_enabled)}")
        self.stdout.write("- transport_check: not_performed")
        self.stdout.write("- network_call: false")
        logger.info(
            "toss_smoke_result command=%s status=%s provider=toss enabled=%s network_call=false dry_run=true "
            "order_execution_enabled=%s",
            "check_toss_provider",
            health.get("status", "unknown"),
            _bool_text(is_toss_provider_enabled(getattr(settings, "TOSS_INVEST_PROVIDER_ENABLED", False))),
            _bool_text(order_execution_enabled),
        )
        _record_check_result(
            health_status=health.get("status", "unknown"),
            enabled=is_toss_provider_enabled(getattr(settings, "TOSS_INVEST_PROVIDER_ENABLED", False)),
            order_execution_enabled=order_execution_enabled,
        )


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _record_check_result(*, health_status: str, enabled: bool, order_execution_enabled: bool) -> None:
    if health_status == "configured":
        status = "success"
        safe_reason = "provider_configured"
    elif health_status == "disabled" or not enabled:
        status = "skipped"
        safe_reason = "provider_disabled"
    else:
        status = "failed"
        safe_reason = "misconfigured"

    record_data_ingestion_log(
        provider_name="toss",
        job_type="provider_check",
        target_type="provider_health",
        endpoint_name="provider_health",
        status=status,
        safe_reason=safe_reason,
        network_call=False,
        dry_run=True,
        commit_mode="not_requested",
        metadata={
            "command": "check_toss_provider",
            "provider": "toss",
            "network_call": False,
            "dry_run": True,
            "order_execution_enabled": order_execution_enabled,
        },
    )
