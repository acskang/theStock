from django.core.management.base import BaseCommand

from data_pipeline.services.market_index_ingestion_service import ingest_market_indices


class Command(BaseCommand):
    help = "시장지수 데이터를 수집합니다."

    def add_arguments(self, parser):
        parser.add_argument("--provider", default="finance")
        parser.add_argument("--code", action="append")
        parser.add_argument("--days", type=int, default=240)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        report = ingest_market_indices(
            provider_name=options["provider"],
            codes=options["code"],
            days=options["days"],
            dry_run=options["dry_run"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"market_indices: status={report.status} targets={report.target_count} "
                f"created={report.created_count} updated={report.updated_count} failed={report.failed_count}"
            )
        )
