from django.core.management.base import BaseCommand

from data_pipeline.services.stock_master_ingestion_service import ingest_stock_master


class Command(BaseCommand):
    help = "종목 마스터 데이터를 수집합니다."

    def add_arguments(self, parser):
        parser.add_argument("--provider", default="krx")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        report = ingest_stock_master(provider_name=options["provider"], dry_run=options["dry_run"])
        self.stdout.write(
            self.style.SUCCESS(
                f"stock_master: status={report.status} targets={report.target_count} "
                f"created={report.created_count} updated={report.updated_count} failed={report.failed_count}"
            )
        )
