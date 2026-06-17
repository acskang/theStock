import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from data_pipeline.services.financial_data_ingestion_service import ingest_financial_data
from stocks.services.collectors.financial_snapshot_collector import collect_financial_snapshots

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "OpenDART 기반 재무 스냅샷을 수집해 FinancialSnapshot 으로 저장합니다."

    def add_arguments(self, parser):
        parser.add_argument("--use-data-pipeline", action="store_true")
        parser.add_argument("--provider", default=settings.DATA_PIPELINE_PROVIDER)
        parser.add_argument("--stock-code")
        parser.add_argument("--years", type=int, default=2)
        parser.add_argument("--all-stocks", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if options["use_data_pipeline"]:
            self._handle_data_pipeline(options)
            return
        logger.info(
            "Financial snapshot collection command started",
            extra={
                "event": "command_start",
                "command": "collect_financial_snapshots",
                "stock_code": options.get("stock_code") or "-",
                "source": "opendart_financial",
            },
        )
        report = collect_financial_snapshots(
            stock_code=options["stock_code"],
            years=options["years"],
            all_stocks=options["all_stocks"],
            dry_run=options["dry_run"],
        )

        mode = "DRY-RUN" if options["dry_run"] else "APPLY"
        self.stdout.write(
            self.style.SUCCESS(
                f"[{mode}] financial snapshot auto collection complete "
                f"(targets={report.target_count}, created={report.created_rows}, "
                f"updated={report.updated_rows}, empty={report.empty_targets}, "
                f"skipped={report.skipped_targets}, errors={report.error_targets})"
            )
        )
        logger.info(
            "Financial snapshot collection command completed",
            extra={
                "event": "command_complete",
                "command": "collect_financial_snapshots",
                "stock_code": options.get("stock_code") or "-",
                "source": "opendart_financial",
            },
        )
        for warning in report.warnings:
            logger.warning(
                warning,
                extra={
                    "event": "command_warning",
                    "command": "collect_financial_snapshots",
                    "source": "opendart_financial",
                },
            )
            self.stdout.write(self.style.WARNING(f"- {warning}"))

    def _handle_data_pipeline(self, options):
        provider_name = options["provider"] or settings.DATA_PIPELINE_PROVIDER
        stock_codes = [options["stock_code"]] if options["stock_code"] else None
        logger.info(
            "Financial snapshot collection delegated to data pipeline",
            extra={
                "event": "command_start",
                "command": "collect_financial_snapshots",
                "stock_code": options.get("stock_code") or "-",
                "source": provider_name,
            },
        )
        report = ingest_financial_data(
            provider_name=provider_name,
            stock_codes=stock_codes,
            years=options["years"],
            all_stocks=options["all_stocks"],
            dry_run=options["dry_run"],
        )
        mode = "DRY-RUN" if options["dry_run"] else "APPLY"
        self.stdout.write(
            self.style.SUCCESS(
                f"[{mode}] financial snapshot auto collection complete (data pipeline) "
                f"(status={report.status}, targets={report.target_count}, success={report.success_count}, "
                f"failed={report.failed_count}, created={report.created_count}, updated={report.updated_count})"
            )
        )
        logger.info(
            "Financial snapshot delegated pipeline completed",
            extra={
                "event": "command_complete",
                "command": "collect_financial_snapshots",
                "stock_code": options.get("stock_code") or "-",
                "source": provider_name,
            },
        )
        for warning in report.warnings:
            logger.warning(
                warning,
                extra={
                    "event": "command_warning",
                    "command": "collect_financial_snapshots",
                    "source": provider_name,
                },
            )
            self.stdout.write(self.style.WARNING(f"- {warning}"))
