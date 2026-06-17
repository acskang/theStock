from django.core.management.base import BaseCommand

from data_pipeline.services.financial_data_ingestion_service import ingest_financial_data


class Command(BaseCommand):
    help = "재무 스냅샷 데이터를 수집합니다."

    def add_arguments(self, parser):
        parser.add_argument("--provider", default="financial_statement")
        parser.add_argument("--stock-code", action="append")
        parser.add_argument("--years", type=int, default=2)
        parser.add_argument("--all-stocks", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        report = ingest_financial_data(
            provider_name=options["provider"],
            stock_codes=options["stock_code"],
            years=options["years"],
            all_stocks=options["all_stocks"],
            dry_run=options["dry_run"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"financial_data: status={report.status} targets={report.target_count} "
                f"created={report.created_count} updated={report.updated_count} failed={report.failed_count}"
            )
        )
