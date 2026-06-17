import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from data_pipeline.services.price_ingestion_service import ingest_daily_prices
from marketdata.services.collectors.price_collector import collect_daily_prices

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "활성 보유 종목 또는 지정 종목의 일봉 데이터를 수집합니다."

    def add_arguments(self, parser):
        parser.add_argument("--use-data-pipeline", action="store_true")
        parser.add_argument("--provider", default=settings.DATA_PIPELINE_PROVIDER)
        parser.add_argument("--stock-code")
        parser.add_argument("--days", type=int, default=240)
        parser.add_argument("--all-stocks", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        if options["use_data_pipeline"]:
            self._handle_data_pipeline(options)
            return
        logger.info(
            "Daily price collection command started",
            extra={
                "event": "command_start",
                "command": "collect_daily_prices",
                "source": "yfinance",
                "stock_code": options.get("stock_code") or "-",
            },
        )
        report = collect_daily_prices(
            stock_code=options["stock_code"],
            days=options["days"],
            all_stocks=options["all_stocks"],
            dry_run=options["dry_run"],
        )
        mode = "DRY-RUN" if options["dry_run"] else "APPLY"
        self.stdout.write(
            self.style.SUCCESS(
                f"[{mode}] daily price collection complete "
                f"(targets={report.target_count}, created={report.created_rows}, "
                f"updated={report.updated_rows}, skipped={report.skipped_targets})"
            )
        )
        logger.info(
            "Daily price collection command completed",
            extra={
                "event": "command_complete",
                "command": "collect_daily_prices",
                "source": "yfinance",
                "stock_code": options.get("stock_code") or "-",
            },
        )
        for warning in report.warnings:
            logger.warning(
                warning,
                extra={
                    "event": "command_warning",
                    "command": "collect_daily_prices",
                    "source": "yfinance",
                },
            )
            self.stdout.write(self.style.WARNING(f"- {warning}"))

    def _handle_data_pipeline(self, options):
        provider_name = options["provider"] or settings.DATA_PIPELINE_PROVIDER
        stock_codes = [options["stock_code"]] if options["stock_code"] else None
        logger.info(
            "Daily price collection delegated to data pipeline",
            extra={
                "event": "command_start",
                "command": "collect_daily_prices",
                "source": provider_name,
                "stock_code": options.get("stock_code") or "-",
            },
        )
        report = ingest_daily_prices(
            provider_name=provider_name,
            stock_codes=stock_codes,
            days=options["days"],
            all_stocks=options["all_stocks"],
            dry_run=options["dry_run"],
        )
        mode = "DRY-RUN" if options["dry_run"] else "APPLY"
        self.stdout.write(
            self.style.SUCCESS(
                f"[{mode}] daily price collection complete (data pipeline) "
                f"(status={report.status}, targets={report.target_count}, success={report.success_count}, "
                f"failed={report.failed_count}, created={report.created_count}, updated={report.updated_count})"
            )
        )
        logger.info(
            "Daily price collection delegated pipeline completed",
            extra={
                "event": "command_complete",
                "command": "collect_daily_prices",
                "source": provider_name,
                "stock_code": options.get("stock_code") or "-",
            },
        )
        for warning in report.warnings:
            logger.warning(
                warning,
                extra={
                    "event": "command_warning",
                    "command": "collect_daily_prices",
                    "source": provider_name,
                },
            )
            self.stdout.write(self.style.WARNING(f"- {warning}"))
