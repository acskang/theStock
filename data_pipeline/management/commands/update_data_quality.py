from django.core.management.base import BaseCommand

from data_pipeline.services.data_quality_service import update_data_quality


class Command(BaseCommand):
    help = "데이터 품질 스냅샷을 계산해 저장합니다."

    def add_arguments(self, parser):
        parser.add_argument("--stock-code", action="append")
        parser.add_argument("--all-stocks", action="store_true")

    def handle(self, *args, **options):
        report = update_data_quality(
            stock_codes=options["stock_code"],
            all_stocks=options["all_stocks"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"data_quality: status={report.status} targets={report.target_count} "
                f"success={report.success_count} failed={report.failed_count}"
            )
        )

