import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from data_pipeline.services.risk_event_ingestion_service import ingest_risk_events
from decisions.services.collectors.risk_event_collector import collect_risk_events

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "OpenDART 기반으로 RiskEvent 데이터를 자동 수집합니다."

    def add_arguments(self, parser):
        parser.add_argument("--use-data-pipeline", action="store_true")
        parser.add_argument("--provider", default=settings.DATA_PIPELINE_PROVIDER)
        parser.add_argument("--stock-code")
        parser.add_argument("--days", type=int, default=365)
        parser.add_argument("--all-stocks", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if options["use_data_pipeline"]:
            self._handle_data_pipeline(options)
            return
        logger.info(
            "Risk event auto collection command started",
            extra={
                "event": "command_start",
                "command": "collect_risk_events",
                "source": "opendart",
                "stock_code": options.get("stock_code") or "-",
            },
        )
        report = collect_risk_events(
            stock_code=options["stock_code"],
            days=options["days"],
            all_stocks=options["all_stocks"],
            dry_run=options["dry_run"],
        )
        mode = "DRY-RUN" if options["dry_run"] else "APPLY"
        self.stdout.write(
            self.style.SUCCESS(
                f"[{mode}] risk event auto collection complete "
                f"(targets={report.target_count}, created={report.created_rows}, "
                f"updated={report.updated_rows}, empty={report.empty_targets}, "
                f"skipped={report.skipped_targets}, errors={report.error_targets})"
            )
        )
        logger.info(
            "Risk event auto collection command completed",
            extra={
                "event": "command_complete",
                "command": "collect_risk_events",
                "source": "opendart",
                "stock_code": options.get("stock_code") or "-",
            },
        )
        for warning in report.warnings:
            logger.warning(
                warning,
                extra={
                    "event": "command_warning",
                    "command": "collect_risk_events",
                    "source": "opendart",
                    "stock_code": options.get("stock_code") or "-",
                },
            )
            self.stdout.write(self.style.WARNING(f"- {warning}"))

    def _handle_data_pipeline(self, options):
        provider_name = options["provider"] or settings.DATA_PIPELINE_PROVIDER
        stock_codes = [options["stock_code"]] if options["stock_code"] else None
        logger.info(
            "Risk event collection delegated to data pipeline",
            extra={
                "event": "command_start",
                "command": "collect_risk_events",
                "source": provider_name,
                "stock_code": options.get("stock_code") or "-",
            },
        )
        report = ingest_risk_events(
            provider_name=provider_name,
            stock_codes=stock_codes,
            days=options["days"],
            all_stocks=options["all_stocks"],
            dry_run=options["dry_run"],
        )
        mode = "DRY-RUN" if options["dry_run"] else "APPLY"
        self.stdout.write(
            self.style.SUCCESS(
                f"[{mode}] risk event auto collection complete (data pipeline) "
                f"(status={report.status}, targets={report.target_count}, success={report.success_count}, "
                f"failed={report.failed_count}, created={report.created_count}, updated={report.updated_count})"
            )
        )
        logger.info(
            "Risk event delegated pipeline completed",
            extra={
                "event": "command_complete",
                "command": "collect_risk_events",
                "source": provider_name,
                "stock_code": options.get("stock_code") or "-",
            },
        )
        for warning in report.warnings:
            logger.warning(
                warning,
                extra={
                    "event": "command_warning",
                    "command": "collect_risk_events",
                    "source": provider_name,
                    "stock_code": options.get("stock_code") or "-",
                },
            )
            self.stdout.write(self.style.WARNING(f"- {warning}"))
