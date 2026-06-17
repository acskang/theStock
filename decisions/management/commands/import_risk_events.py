import logging

from django.core.management.base import BaseCommand

from decisions.services.importers.risk_event_import_service import import_risk_events_from_csv

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "CSV 파일에서 RiskEvent 데이터를 import 합니다."

    def add_arguments(self, parser):
        parser.add_argument("--file", required=True)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--skip-missing-stocks", action="store_true")

    def handle(self, *args, **options):
        logger.info(
            "Risk event import command started",
            extra={
                "event": "command_start",
                "command": "import_risk_events",
                "source": "csv",
            },
        )
        report = import_risk_events_from_csv(
            options["file"],
            dry_run=options["dry_run"],
            skip_missing_stocks=options["skip_missing_stocks"],
        )
        mode = "DRY-RUN" if options["dry_run"] else "APPLY"
        self.stdout.write(
            self.style.SUCCESS(
                f"[{mode}] risk event import complete "
                f"(created={report.created_count}, updated={report.updated_count}, skipped={report.skipped_rows})"
            )
        )
        logger.info(
            "Risk event import command completed",
            extra={
                "event": "command_complete",
                "command": "import_risk_events",
                "source": "csv",
            },
        )
        for warning in report.warnings:
            logger.warning(
                warning,
                extra={
                    "event": "command_warning",
                    "command": "import_risk_events",
                    "source": "csv",
                },
            )
            self.stdout.write(self.style.WARNING(f"- {warning}"))
