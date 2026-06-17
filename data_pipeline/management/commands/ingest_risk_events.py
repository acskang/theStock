from django.core.management.base import BaseCommand

from data_pipeline.services.risk_event_ingestion_service import ingest_risk_events


class Command(BaseCommand):
    help = "리스크 이벤트 데이터를 수집합니다."

    def add_arguments(self, parser):
        parser.add_argument("--provider", default="disclosure")
        parser.add_argument("--stock-code", action="append")
        parser.add_argument("--days", type=int, default=365)
        parser.add_argument("--all-stocks", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        report = ingest_risk_events(
            provider_name=options["provider"],
            stock_codes=options["stock_code"],
            days=options["days"],
            all_stocks=options["all_stocks"],
            dry_run=options["dry_run"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"risk_events: status={report.status} targets={report.target_count} "
                f"created={report.created_count} updated={report.updated_count} failed={report.failed_count}"
            )
        )
