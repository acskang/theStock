import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from data_pipeline.services.market_index_ingestion_service import ingest_market_indices
from marketdata.services.collectors.market_index_collector import collect_market_indices

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "시장지수 및 환율 데이터를 수집합니다."

    def add_arguments(self, parser):
        parser.add_argument("--use-data-pipeline", action="store_true")
        parser.add_argument("--provider", default=settings.DATA_PIPELINE_PROVIDER)
        parser.add_argument("--codes", nargs="*")
        parser.add_argument("--days", type=int, default=240)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if options["use_data_pipeline"]:
            self._handle_data_pipeline(options)
            return
        logger.info(
            "Market index collection command started",
            extra={
                "event": "command_start",
                "command": "collect_market_indices",
                "source": "yfinance",
            },
        )
        report = collect_market_indices(
            codes=options["codes"],
            days=options["days"],
            dry_run=options["dry_run"],
        )
        mode = "DRY-RUN" if options["dry_run"] else "APPLY"
        self.stdout.write(
            self.style.SUCCESS(
                f"[{mode}] market index collection complete "
                f"(targets={report.target_count}, created={report.created_rows}, "
                f"updated={report.updated_rows}, skipped={report.skipped_targets})"
            )
        )
        logger.info(
            "Market index collection command completed",
            extra={
                "event": "command_complete",
                "command": "collect_market_indices",
                "source": "yfinance",
            },
        )
        for warning in report.warnings:
            logger.warning(
                warning,
                extra={
                    "event": "command_warning",
                    "command": "collect_market_indices",
                    "source": "yfinance",
                },
            )
            self.stdout.write(self.style.WARNING(f"- {warning}"))

    def _handle_data_pipeline(self, options):
        provider_name = options["provider"] or settings.DATA_PIPELINE_PROVIDER
        logger.info(
            "Market index collection delegated to data pipeline",
            extra={
                "event": "command_start",
                "command": "collect_market_indices",
                "source": provider_name,
            },
        )
        report = ingest_market_indices(
            provider_name=provider_name,
            codes=options["codes"],
            days=options["days"],
            dry_run=options["dry_run"],
        )
        mode = "DRY-RUN" if options["dry_run"] else "APPLY"
        self.stdout.write(
            self.style.SUCCESS(
                f"[{mode}] market index collection complete (data pipeline) "
                f"(status={report.status}, targets={report.target_count}, success={report.success_count}, "
                f"failed={report.failed_count}, created={report.created_count}, updated={report.updated_count})"
            )
        )
        logger.info(
            "Market index collection delegated pipeline completed",
            extra={
                "event": "command_complete",
                "command": "collect_market_indices",
                "source": provider_name,
            },
        )
        for warning in report.warnings:
            logger.warning(
                warning,
                extra={
                    "event": "command_warning",
                    "command": "collect_market_indices",
                    "source": provider_name,
                },
            )
            self.stdout.write(self.style.WARNING(f"- {warning}"))
