import logging

from django.conf import settings
from django.core.management.base import BaseCommand

from data_pipeline.services.data_quality_service import update_data_quality
from data_pipeline.services.pipeline_orchestrator import run_daily_pipeline
from decisions.services.collectors.risk_event_collector import collect_risk_events
from marketdata.services.collectors.market_index_collector import collect_market_indices
from marketdata.services.collectors.investor_flow_collector import collect_investor_flows
from marketdata.services.collectors.price_collector import collect_daily_prices
from stocks.services.collectors.financial_snapshot_collector import collect_financial_snapshots

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "물타기 판단 엔진 입력용 가격/시장/수급/리스크 이벤트 데이터를 한 번에 갱신합니다."

    def add_arguments(self, parser):
        parser.add_argument("--legacy", action="store_true")
        parser.add_argument("--use-data-pipeline", action="store_true")
        parser.add_argument("--provider", default=settings.DATA_PIPELINE_PROVIDER)
        parser.add_argument("--stock-code")
        parser.add_argument("--price-days", type=int, default=240)
        parser.add_argument("--index-days", type=int, default=240)
        parser.add_argument("--investor-flow-days", type=int, default=60)
        parser.add_argument("--risk-event-days", type=int, default=365)
        parser.add_argument("--financial-years", type=int, default=2)
        parser.add_argument("--all-stocks", action="store_true")
        parser.add_argument("--index-codes", nargs="*")
        parser.add_argument("--skip-investor-flows", action="store_true")
        parser.add_argument("--skip-risk-events", action="store_true")
        parser.add_argument("--skip-financials", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        if not options["legacy"]:
            self._handle_data_pipeline(options)
            return

        logger.info(
            "Refresh decision inputs command started",
            extra={
                "event": "command_start",
                "command": "refresh_decision_inputs",
                "stock_code": options.get("stock_code") or "-",
            },
        )

        price_report = collect_daily_prices(
            stock_code=options["stock_code"],
            days=options["price_days"],
            all_stocks=options["all_stocks"],
            dry_run=dry_run,
        )
        index_report = collect_market_indices(
            codes=options["index_codes"],
            days=options["index_days"],
            dry_run=dry_run,
        )
        flow_report = None
        if not options["skip_investor_flows"]:
            flow_report = collect_investor_flows(
                stock_code=options["stock_code"],
                days=options["investor_flow_days"],
                all_stocks=options["all_stocks"],
                dry_run=dry_run,
            )
        risk_report = None
        if not options["skip_risk_events"]:
            risk_report = collect_risk_events(
                stock_code=options["stock_code"],
                days=options["risk_event_days"],
                all_stocks=options["all_stocks"],
                dry_run=dry_run,
            )
        financial_report = None
        if not options["skip_financials"]:
            financial_report = collect_financial_snapshots(
                stock_code=options["stock_code"],
                years=options["financial_years"],
                all_stocks=options["all_stocks"],
                dry_run=dry_run,
            )

        mode = "DRY-RUN" if dry_run else "APPLY"
        self.stdout.write(self.style.SUCCESS(f"[{mode}] refresh_decision_inputs complete"))
        self.stdout.write(
            f"prices: targets={price_report.target_count}, created={price_report.created_rows}, "
            f"updated={price_report.updated_rows}, skipped={price_report.skipped_targets}"
        )
        self.stdout.write(
            f"indices: targets={index_report.target_count}, created={index_report.created_rows}, "
            f"updated={index_report.updated_rows}, skipped={index_report.skipped_targets}"
        )
        if flow_report is not None:
            self.stdout.write(
                f"investor_flows: targets={flow_report.target_count}, created={flow_report.created_rows}, "
                f"updated={flow_report.updated_rows}, empty={flow_report.empty_targets}, "
                f"skipped={flow_report.skipped_targets}, errors={flow_report.error_targets}"
            )
        if risk_report is not None:
            self.stdout.write(
                f"risk_events: targets={risk_report.target_count}, created={risk_report.created_rows}, "
                f"updated={risk_report.updated_rows}, empty={risk_report.empty_targets}, "
                f"skipped={risk_report.skipped_targets}, errors={risk_report.error_targets}"
            )
        if financial_report is not None:
            self.stdout.write(
                f"financial_snapshots: targets={financial_report.target_count}, "
                f"created={financial_report.created_rows}, updated={financial_report.updated_rows}, "
                f"empty={financial_report.empty_targets}, skipped={financial_report.skipped_targets}, "
                f"errors={financial_report.error_targets}"
            )
        data_quality_report = None
        if not dry_run:
            stock_codes = [options["stock_code"]] if options["stock_code"] else None
            data_quality_report = update_data_quality(
                stock_codes=stock_codes,
                all_stocks=options["all_stocks"],
            )
            self.stdout.write(
                f"data_quality: status={data_quality_report.status}, targets={data_quality_report.target_count}, "
                f"success={data_quality_report.success_count}, failed={data_quality_report.failed_count}"
            )
        logger.info(
            "Refresh decision inputs command completed",
            extra={
                "event": "command_complete",
                "command": "refresh_decision_inputs",
                "stock_code": options.get("stock_code") or "-",
            },
        )

        warnings = price_report.warnings + index_report.warnings
        if flow_report is not None:
            warnings.extend(flow_report.warnings)
        if risk_report is not None:
            warnings.extend(risk_report.warnings)
        if financial_report is not None:
            warnings.extend(financial_report.warnings)
        if data_quality_report is not None:
            warnings.extend(data_quality_report.warnings)
        for warning in warnings:
            logger.warning(
                warning,
                extra={
                    "event": "command_warning",
                    "command": "refresh_decision_inputs",
                },
            )
            self.stdout.write(self.style.WARNING(f"- {warning}"))

    def _handle_data_pipeline(self, options):
        dry_run = options["dry_run"]
        provider_name = options["provider"] or settings.DATA_PIPELINE_PROVIDER
        stock_codes = [options["stock_code"]] if options["stock_code"] else None
        logger.info(
            "Refresh decision inputs delegated to data pipeline",
            extra={
                "event": "command_start",
                "command": "refresh_decision_inputs",
                "source": provider_name,
                "stock_code": options.get("stock_code") or "-",
            },
        )
        reports = run_daily_pipeline(
            provider_name=provider_name,
            stock_codes=stock_codes,
            price_days=options["price_days"],
            investor_flow_days=options["investor_flow_days"],
            market_index_days=options["index_days"],
            risk_event_days=options["risk_event_days"],
            financial_years=options["financial_years"],
            market_index_codes=options["index_codes"],
            all_stocks=options["all_stocks"],
            skip_investor_flows=options["skip_investor_flows"],
            skip_risk_events=options["skip_risk_events"],
            skip_financial_data=options["skip_financials"],
            dry_run=dry_run,
        )
        mode = "DRY-RUN" if dry_run else "APPLY"
        self.stdout.write(self.style.SUCCESS(f"[{mode}] refresh_decision_inputs complete (data pipeline)"))
        for key, report in reports.items():
            self.stdout.write(
                f"{key}: status={report.status}, targets={report.target_count}, "
                f"success={report.success_count}, failed={report.failed_count}, "
                f"created={report.created_count}, updated={report.updated_count}"
            )
            for warning in report.warnings:
                self.stdout.write(self.style.WARNING(f"- {warning}"))
        logger.info(
            "Refresh decision inputs delegated pipeline completed",
            extra={
                "event": "command_complete",
                "command": "refresh_decision_inputs",
                "source": provider_name,
                "stock_code": options.get("stock_code") or "-",
            },
        )
