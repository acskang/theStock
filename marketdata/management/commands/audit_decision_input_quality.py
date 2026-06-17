from collections import Counter
import logging

from django.core.management.base import BaseCommand

from decisions.services.data_quality_service import evaluate_data_quality
from holdings.models import UserHolding
from marketdata.models import StockDataCollectionStatus
from marketdata.services.collection_status_service import get_collection_status_snapshot
from stocks.models import Stock
from stocks.services.stock_quality_service import evaluate_stock_quality

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "active holding 기준으로 판단 입력 데이터 품질을 점검합니다."

    def add_arguments(self, parser):
        parser.add_argument("--holding-id", type=int)
        parser.add_argument("--only-low", action="store_true")
        parser.add_argument("--only-missing", action="store_true")

    def handle(self, *args, **options):
        logger.info(
            "Decision input quality audit command started",
            extra={
                "event": "command_start",
                "command": "audit_decision_input_quality",
            },
        )
        queryset = UserHolding.objects.select_related("user", "stock").filter(is_active=True)
        holding_id = options.get("holding_id")
        if holding_id:
            queryset = queryset.filter(id=holding_id)

        holdings = list(queryset.order_by("user__username", "stock__code"))
        label_counts = Counter()
        reported = 0
        missing_flow_sync = 0
        missing_risk_sync = 0
        missing_financial_sync = 0
        low_flow_data = 0
        unknown_stock_quality = 0

        for holding in holdings:
            result = evaluate_data_quality(holding)
            stock_quality_result = evaluate_stock_quality(holding.stock)
            label_counts[result.label] += 1
            flow_status = result.details.get("investor_flow_collection_status", StockDataCollectionStatus.STATUS_NEVER)
            risk_status = result.details.get("risk_event_collection_status", StockDataCollectionStatus.STATUS_NEVER)
            financial_status = get_collection_status_snapshot(
                holding.stock,
                StockDataCollectionStatus.TYPE_FINANCIAL_SNAPSHOT,
            ).status
            flow_missing = result.investor_flow_days == 0 and flow_status in {
                StockDataCollectionStatus.STATUS_NEVER,
                StockDataCollectionStatus.STATUS_ERROR,
                StockDataCollectionStatus.STATUS_SKIPPED,
            }
            risk_missing = not result.risk_event_available and risk_status in {
                StockDataCollectionStatus.STATUS_NEVER,
                StockDataCollectionStatus.STATUS_ERROR,
                StockDataCollectionStatus.STATUS_SKIPPED,
            }
            financial_missing = (
                holding.stock.market not in {Stock.MARKET_ETF, Stock.MARKET_ETN}
                and not holding.stock.financial_snapshots.exists()
                and financial_status in {
                    StockDataCollectionStatus.STATUS_NEVER,
                    StockDataCollectionStatus.STATUS_ERROR,
                    StockDataCollectionStatus.STATUS_SKIPPED,
                    StockDataCollectionStatus.STATUS_EMPTY,
                }
            )
            if flow_missing:
                missing_flow_sync += 1
            if risk_missing:
                missing_risk_sync += 1
            if financial_missing:
                missing_financial_sync += 1
            if result.investor_flow_days < 5:
                low_flow_data += 1
            if stock_quality_result.quality_grade == "UNKNOWN":
                unknown_stock_quality += 1

            if options["only_low"] and result.label not in {"낮음", "매우 낮음"}:
                continue
            if options["only_missing"] and not (
                flow_missing or risk_missing or financial_missing or result.investor_flow_days < 5
            ):
                continue

            reported += 1
            latest_age = result.latest_price_age_days if result.latest_price_age_days is not None else "N/A"
            self.stdout.write(
                f"{holding.user.username}:{holding.stock.code} {holding.stock.name} "
                f"score={result.overall_score} label={result.label} "
                f"prices={result.price_data_days} flows={result.investor_flow_days} "
                f"flow_sync={flow_status} risk_sync={risk_status} financial_sync={financial_status} "
                f"stock_quality={stock_quality_result.quality_grade} latest_age={latest_age}"
            )
            if flow_missing:
                self.stdout.write(self.style.WARNING("- 수급 자동 수집 이력이 없거나 실패했습니다."))
            elif result.investor_flow_days < 5:
                self.stdout.write(self.style.WARNING("- 수급 데이터가 5일 미만이라 판단 근거가 약합니다."))
            if risk_missing:
                self.stdout.write(self.style.WARNING("- 리스크 이벤트 자동 수집 이력이 없거나 실패했습니다."))
            if financial_missing:
                self.stdout.write(self.style.WARNING("- 재무 스냅샷 자동 수집 이력이 없거나 실패했습니다."))
            if stock_quality_result.quality_grade == "UNKNOWN":
                self.stdout.write(self.style.WARNING("- 재무 품질 데이터가 부족하거나 적용 대상이 아닙니다."))
            for warning in result.warnings:
                logger.warning(
                    warning,
                    extra={
                        "event": "command_warning",
                        "command": "audit_decision_input_quality",
                        "holding_id": holding.id,
                        "stock_code": holding.stock.code,
                    },
                )
                self.stdout.write(self.style.WARNING(f"- {warning}"))

        logger.info(
            "Decision input quality audit command completed",
            extra={
                "event": "command_complete",
                "command": "audit_decision_input_quality",
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"audit complete (active_holdings={len(holdings)}, reported={reported}, "
                f"높음={label_counts['높음']}, 보통={label_counts['보통']}, "
                f"낮음={label_counts['낮음']}, 매우 낮음={label_counts['매우 낮음']}, "
                f"missing_flow_sync={missing_flow_sync}, missing_risk_sync={missing_risk_sync}, "
                f"missing_financial_sync={missing_financial_sync}, "
                f"unknown_stock_quality={unknown_stock_quality}, low_flow_data={low_flow_data})"
            )
        )
