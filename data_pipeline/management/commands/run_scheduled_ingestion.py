import logging
from io import StringIO
from time import monotonic

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from data_pipeline.services.ingestion_log_writer import record_data_ingestion_log


logger = logging.getLogger(__name__)

DEFAULT_PROFILE = "toss_no_network_preflight"
READONLY_SMOKE_PROFILE = "toss_readonly_smoke"

PROFILES = {
    DEFAULT_PROFILE: [
        ("check_toss_provider", [], {}),
        ("toss_token_smoke", [], {"no_network": True}),
        ("toss_quote_smoke", [], {"symbol": "005930", "market": "KR", "no_network": True}),
        ("toss_provider_quote_smoke", [], {"symbol": "005930", "market": "KR", "no_network": True}),
        ("toss_registry_quote_smoke", [], {"symbol": "005930", "market": "KR", "no_network": True}),
        (
            "toss_daily_price_ingest_dryrun",
            [],
            {"symbol": "005930", "market": "KR", "count": 1, "no_network": True},
        ),
        ("toss_holdings_sync_dryrun", [], {"map_user_holdings": True, "no_network": True}),
    ],
    READONLY_SMOKE_PROFILE: [
        ("check_toss_provider", [], {}),
        ("toss_token_smoke", [], {}),
        ("toss_quote_smoke", [], {"symbol": "005930", "market": "KR"}),
        ("toss_provider_quote_smoke", [], {"symbol": "005930", "market": "KR"}),
        ("toss_registry_quote_smoke", [], {"symbol": "005930", "market": "KR"}),
        (
            "toss_daily_price_ingest_dryrun",
            [],
            {"symbol": "005930", "market": "KR", "count": 1},
        ),
        ("toss_holdings_sync_dryrun", [], {}),
    ],
}
NETWORK_PROFILES = {READONLY_SMOKE_PROFILE}


class Command(BaseCommand):
    help = "Run safe scheduled ingestion profiles. Step 21B supports no-network profiles only."

    def add_arguments(self, parser):
        parser.add_argument("--profile", default=DEFAULT_PROFILE)
        parser.add_argument("--list-profiles", action="store_true")
        parser.add_argument("--no-network", action="store_true")
        parser.add_argument("--allow-network", action="store_true")
        parser.add_argument("--stop-on-error", action="store_true")

    def handle(self, *args, **options):
        if options["list_profiles"]:
            self.stdout.write("Available scheduled ingestion profiles:")
            for name in sorted(PROFILES):
                self.stdout.write(f"- {name}")
            return

        profile = str(options.get("profile") or DEFAULT_PROFILE).strip()
        if profile not in PROFILES:
            raise CommandError(f"Unsupported scheduled ingestion profile: {profile}")

        if profile in NETWORK_PROFILES and not options.get("allow_network"):
            self._refuse_network_profile(profile)
            return

        network_call = profile in NETWORK_PROFILES

        self.stdout.write("Scheduled ingestion wrapper: STARTED")
        self.stdout.write(f"profile: {profile}")
        self.stdout.write("dry_run: true")
        self.stdout.write(f"network_call: {_bool_text(network_call)}")
        self.stdout.write("commit: not_requested")
        self.stdout.write(f"allow_network: {_bool_text(bool(options.get('allow_network')))}")
        self.stdout.write(f"stop_on_error: {_bool_text(bool(options.get('stop_on_error')))}")

        started = monotonic()
        step_results = []

        for command_name, command_args, command_kwargs in PROFILES[profile]:
            self.stdout.write(f"step: {command_name}")
            try:
                output = StringIO()
                call_command(command_name, *command_args, stdout=output, **command_kwargs)
            except Exception as exc:
                step_results.append({"command": command_name, "status": "failed"})
                self.stdout.write(f"  status: failed")
                self.stdout.write(f"  reason: {_safe_exception_reason(exc)}")
                if options["stop_on_error"]:
                    break
                continue

            step_results.append({"command": command_name, "status": "success"})
            self.stdout.write("  status: success")
            for line in _safe_output_lines(output.getvalue()):
                self.stdout.write(f"  {line}")

        success_count = sum(1 for row in step_results if row["status"] == "success")
        failed_count = sum(1 for row in step_results if row["status"] == "failed")
        skipped_count = len(PROFILES[profile]) - len(step_results)
        status = "success" if failed_count == 0 and skipped_count == 0 else ("partial" if success_count else "failed")
        duration_ms = int((monotonic() - started) * 1000)

        self.stdout.write("Scheduled ingestion wrapper: COMPLETE" if status != "failed" else "Scheduled ingestion wrapper: FAILED")
        self.stdout.write(f"status: {status}")
        self.stdout.write(f"step_count: {len(PROFILES[profile])}")
        self.stdout.write(f"success_count: {success_count}")
        self.stdout.write(f"failed_count: {failed_count}")
        self.stdout.write(f"skipped_count: {skipped_count}")

        record_data_ingestion_log(
            provider_name="toss",
            job_type="scheduled_ingestion",
            target_type="smoke",
            endpoint_name=profile,
            status=status,
            safe_reason=_summary_safe_reason(profile=profile, status=status),
            network_call=network_call,
            dry_run=True,
            commit_mode="not_requested",
            candidate_count=len(PROFILES[profile]),
            saved_count=0,
            updated_count=0,
            skipped_count=skipped_count,
            failed_count=failed_count,
            duration_ms=duration_ms,
            metadata={
                "command": "run_scheduled_ingestion",
                "provider": "toss",
                "endpoint_name": profile,
                "network_call": network_call,
                "dry_run": True,
                "commit_mode": "not_requested",
                "candidate_count": len(PROFILES[profile]),
                "saved_count": 0,
                "updated_count": 0,
                "skipped_count": skipped_count,
                "failed_count": failed_count,
            },
        )
        logger.info(
            "scheduled_ingestion_result command=%s profile=%s status=%s network_call=%s dry_run=true "
            "step_count=%s success_count=%s failed_count=%s skipped_count=%s",
            "run_scheduled_ingestion",
            profile,
            status,
            _bool_text(network_call),
            len(PROFILES[profile]),
            success_count,
            failed_count,
            skipped_count,
        )

    def _refuse_network_profile(self, profile: str):
        step_count = len(PROFILES[profile])
        self.stdout.write("Scheduled ingestion wrapper: REFUSED")
        self.stdout.write(f"profile: {profile}")
        self.stdout.write("status: skipped")
        self.stdout.write("reason: allow_network_required")
        self.stdout.write("dry_run: true")
        self.stdout.write("network_call: false")
        self.stdout.write("commit: not_requested")
        self.stdout.write("allow_network: false")
        self.stdout.write(f"step_count: {step_count}")
        self.stdout.write("success_count: 0")
        self.stdout.write("failed_count: 0")
        self.stdout.write(f"skipped_count: {step_count}")
        record_data_ingestion_log(
            provider_name="toss",
            job_type="scheduled_ingestion",
            target_type="smoke",
            endpoint_name=profile,
            status="skipped",
            safe_reason="allow_network_required",
            network_call=False,
            dry_run=True,
            commit_mode="not_requested",
            candidate_count=step_count,
            saved_count=0,
            updated_count=0,
            skipped_count=step_count,
            failed_count=0,
            metadata={
                "command": "run_scheduled_ingestion",
                "provider": "toss",
                "endpoint_name": profile,
                "network_call": False,
                "dry_run": True,
                "commit_mode": "not_requested",
                "candidate_count": step_count,
                "saved_count": 0,
                "updated_count": 0,
                "skipped_count": step_count,
                "failed_count": 0,
            },
        )
        logger.info(
            "scheduled_ingestion_result command=%s profile=%s status=skipped reason=allow_network_required "
            "network_call=false dry_run=true step_count=%s success_count=0 failed_count=0 skipped_count=%s",
            "run_scheduled_ingestion",
            profile,
            step_count,
            step_count,
        )


def _safe_output_lines(output: str) -> list[str]:
    safe_lines = []
    for line in output.splitlines():
        clean = line.strip()
        if not clean:
            continue
        lowered = clean.lower()
        if any(
            forbidden in lowered
            for forbidden in (
                "authorization",
                "access_token",
                "client_secret",
                "x-tossinvest-account",
                "accountno",
                "accountseq",
            )
        ):
            continue
        safe_lines.append(clean)
    return safe_lines[:80]


def _safe_exception_reason(exc: Exception) -> str:
    if isinstance(exc, CommandError):
        return "command_error"
    return exc.__class__.__name__


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _summary_safe_reason(*, profile: str, status: str) -> str:
    if profile == DEFAULT_PROFILE:
        return "scheduled_no_network_preflight" if status == "success" else "scheduled_no_network_partial"
    if profile == READONLY_SMOKE_PROFILE:
        return "scheduled_readonly_smoke" if status == "success" else "scheduled_readonly_partial"
    return "scheduled_profile_complete" if status == "success" else "scheduled_profile_partial"
