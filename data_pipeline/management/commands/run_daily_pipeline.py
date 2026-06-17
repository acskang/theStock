from django.conf import settings
from django.core.management.base import BaseCommand

from data_pipeline.services.pipeline_orchestrator import run_daily_pipeline


class Command(BaseCommand):
    help = "08단계 데이터 파이프라인을 한 번에 실행합니다."

    def add_arguments(self, parser):
        parser.add_argument("--provider", default=settings.DATA_PIPELINE_PROVIDER)
        parser.add_argument("--stock-code", action="append")
        parser.add_argument("--price-days", type=int, default=240)
        parser.add_argument("--investor-flow-days", type=int, default=60)
        parser.add_argument("--market-index-days", type=int, default=240)
        parser.add_argument("--risk-event-days", type=int, default=365)
        parser.add_argument("--financial-years", type=int, default=2)
        parser.add_argument("--all-stocks", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        reports = run_daily_pipeline(
            provider_name=options["provider"],
            stock_codes=options["stock_code"],
            price_days=options["price_days"],
            investor_flow_days=options["investor_flow_days"],
            market_index_days=options["market_index_days"],
            risk_event_days=options["risk_event_days"],
            financial_years=options["financial_years"],
            all_stocks=options["all_stocks"],
            dry_run=options["dry_run"],
        )
        self.stdout.write(self.style.SUCCESS("run_daily_pipeline complete"))
        for key, report in reports.items():
            self.stdout.write(
                f"{key}: status={report.status} targets={report.target_count} "
                f"success={report.success_count} failed={report.failed_count} "
                f"created={report.created_count} updated={report.updated_count}"
            )
