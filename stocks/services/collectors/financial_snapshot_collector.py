from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import logging
import re
import urllib.parse
import urllib.request

from django.conf import settings

from decisions.services.collectors.risk_event_collector import get_dart_corp_code_map
from holdings.models import UserHolding
from marketdata.models import StockDataCollectionStatus
from marketdata.services.collection_status_service import record_collection_status
from stocks.models import FinancialSnapshot, Stock

logger = logging.getLogger(__name__)


OPENDART_FINANCIAL_STATEMENT_URL = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"
FINANCIAL_SNAPSHOT_SOURCE = "opendart_financial_auto"
REPORT_CODE_TO_PERIOD = {
    "11011": FinancialSnapshot.PERIOD_ANNUAL,
    "11014": FinancialSnapshot.PERIOD_Q3,
    "11012": FinancialSnapshot.PERIOD_Q2,
    "11013": FinancialSnapshot.PERIOD_Q1,
}
DATE_PATTERN = re.compile(r"(\d{4})[.\-](\d{2})[.\-](\d{2})")


@dataclass
class FinancialSnapshotCollectionReport:
    target_count: int = 0
    created_rows: int = 0
    updated_rows: int = 0
    skipped_targets: int = 0
    empty_targets: int = 0
    error_targets: int = 0
    warnings: list[str] = field(default_factory=list)


def _quantize(value: Decimal | None, places: str = "0.01"):
    if value is None:
        return None
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def _to_decimal(raw_value):
    if raw_value in (None, "", "-"):
        return None
    normalized = str(raw_value).replace(",", "").strip()
    if not normalized:
        return None
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def _parse_reported_date(raw_value):
    if not raw_value:
        return None
    match = DATE_PATTERN.search(str(raw_value))
    if not match:
        return None
    year, month, day = match.groups()
    return datetime.strptime(f"{year}-{month}-{day}", "%Y-%m-%d").date()


def _normalize_account_map(rows):
    account_map = {}
    for row in rows:
        account_nm = (row.get("account_nm") or "").replace(" ", "")
        account_id = (row.get("account_id") or "").strip()
        amount = _to_decimal(row.get("thstrm_amount"))
        if amount is None:
            continue
        if account_nm:
            account_map[account_nm] = amount
        if account_id:
            account_map[account_id] = amount
    return account_map


def _pick_amount(account_map, *keys):
    for key in keys:
        if key in account_map:
            return account_map[key]
    return None


def _build_snapshot_defaults(stock, rows, fiscal_year, period_type, fs_div):
    account_map = _normalize_account_map(rows)
    revenue = _pick_amount(account_map, "매출액", "영업수익", "ifrs-full_Revenue")
    operating_profit = _pick_amount(account_map, "영업이익", "ifrs-full_ProfitLossFromOperatingActivities")
    net_income = _pick_amount(account_map, "당기순이익", "당기순이익(손실)", "ifrs-full_ProfitLoss")
    operating_cash_flow = _pick_amount(
        account_map,
        "영업활동으로인한현금흐름",
        "ifrs-full_CashFlowsFromUsedInOperatingActivities",
    )
    equity = _pick_amount(account_map, "자본총계", "ifrs-full_Equity")
    liabilities = _pick_amount(account_map, "부채총계", "ifrs-full_Liabilities")
    current_assets = _pick_amount(account_map, "유동자산", "ifrs-full_CurrentAssets")
    current_liabilities = _pick_amount(account_map, "유동부채", "ifrs-full_CurrentLiabilities")
    capital = _pick_amount(account_map, "자본금", "ifrs-full_IssuedCapital")

    debt_ratio = None
    if liabilities is not None and equity not in (None, Decimal("0")):
        debt_ratio = _quantize((liabilities / equity) * Decimal("100"))

    current_ratio = None
    if current_assets is not None and current_liabilities not in (None, Decimal("0")):
        current_ratio = _quantize((current_assets / current_liabilities) * Decimal("100"))

    capital_impairment_rate = None
    if capital not in (None, Decimal("0")) and equity is not None:
        impairment = Decimal("0")
        if equity < capital:
            impairment = ((capital - equity) / capital) * Decimal("100")
        capital_impairment_rate = _quantize(impairment)

    roe = None
    if net_income is not None and equity not in (None, Decimal("0")):
        roe = _quantize((net_income / equity) * Decimal("100"))

    reported_date = None
    for row in rows:
        reported_date = _parse_reported_date(row.get("thstrm_dt"))
        if reported_date is not None:
            break

    return {
        "reported_date": reported_date,
        "revenue": revenue,
        "operating_profit": operating_profit,
        "net_income": net_income,
        "operating_cash_flow": operating_cash_flow,
        "debt_ratio": debt_ratio,
        "current_ratio": current_ratio,
        "equity": equity,
        "capital_impairment_rate": capital_impairment_rate,
        "roe": roe,
        "per": None,
        "pbr": None,
        "source": FINANCIAL_SNAPSHOT_SOURCE,
        "source_key": f"{FINANCIAL_SNAPSHOT_SOURCE}:{stock.code}:{fiscal_year}:{period_type}:{fs_div}",
    }


def fetch_financial_statement_rows(api_key: str, corp_code: str, fiscal_year: int, report_code: str, fs_div: str):
    params = {
        "crtfc_key": api_key,
        "corp_code": corp_code,
        "bsns_year": str(fiscal_year),
        "reprt_code": report_code,
        "fs_div": fs_div,
    }
    url = f"{OPENDART_FINANCIAL_STATEMENT_URL}?{urllib.parse.urlencode(params)}"
    with urllib.request.urlopen(url, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))

    status = payload.get("status")
    if status == "013":
        return []
    if status != "000":
        raise ValueError(payload.get("message") or f"OpenDART 오류(status={status})")
    return payload.get("list", [])


def _get_target_stocks(*, stock_code=None, all_stocks=False):
    if stock_code:
        return Stock.objects.filter(code=stock_code)
    if all_stocks:
        return Stock.objects.filter(is_active=True).order_by("code")
    holding_stock_ids = UserHolding.objects.filter(is_active=True).values_list("stock_id", flat=True)
    return Stock.objects.filter(id__in=holding_stock_ids, is_active=True).order_by("code")


def collect_financial_snapshots(*, stock_code=None, years=2, all_stocks=False, dry_run=False):
    report = FinancialSnapshotCollectionReport()
    stocks = list(_get_target_stocks(stock_code=stock_code, all_stocks=all_stocks))
    report.target_count = len(stocks)

    api_key = getattr(settings, "OPENDART_API_KEY", "").strip()
    if not api_key:
        report.error_targets = len(stocks)
        report.warnings.append("OPENDART_API_KEY 가 설정되지 않아 재무 스냅샷 자동 수집을 실행할 수 없습니다.")
        if not dry_run:
            for stock in stocks:
                record_collection_status(
                    stock=stock,
                    data_type=StockDataCollectionStatus.TYPE_FINANCIAL_SNAPSHOT,
                    status=StockDataCollectionStatus.STATUS_ERROR,
                    source=FINANCIAL_SNAPSHOT_SOURCE,
                    row_count=0,
                    message="OPENDART_API_KEY 미설정",
                )
        logger.error(
            "Financial snapshot collection skipped because API key is missing",
            extra={
                "event": "financial_snapshot_collect_config_error",
                "source": FINANCIAL_SNAPSHOT_SOURCE,
                "error_type": "MissingApiKey",
            },
        )
        return report

    try:
        corp_code_map = get_dart_corp_code_map(api_key)
    except Exception as exc:
        report.error_targets = len(stocks)
        report.warnings.append(f"OpenDART corp code 조회에 실패했습니다. ({exc})")
        if not dry_run:
            for stock in stocks:
                record_collection_status(
                    stock=stock,
                    data_type=StockDataCollectionStatus.TYPE_FINANCIAL_SNAPSHOT,
                    status=StockDataCollectionStatus.STATUS_ERROR,
                    source=FINANCIAL_SNAPSHOT_SOURCE,
                    row_count=0,
                    message=str(exc),
                )
        logger.error(
            "Financial snapshot collection failed during corp code lookup",
            extra={
                "event": "financial_snapshot_collect_corp_code_error",
                "source": FINANCIAL_SNAPSHOT_SOURCE,
                "error_type": exc.__class__.__name__,
            },
        )
        return report

    current_year = datetime.now().year
    target_years = [current_year - offset for offset in range(max(years, 1))]

    for stock in stocks:
        if stock.market in {Stock.MARKET_ETF, Stock.MARKET_ETN}:
            report.skipped_targets += 1
            message = f"{stock.code} {stock.name}: ETF/ETN 은 재무 스냅샷 자동 수집 대상에서 제외합니다."
            report.warnings.append(message)
            if not dry_run:
                record_collection_status(
                    stock=stock,
                    data_type=StockDataCollectionStatus.TYPE_FINANCIAL_SNAPSHOT,
                    status=StockDataCollectionStatus.STATUS_SKIPPED,
                    source=FINANCIAL_SNAPSHOT_SOURCE,
                    row_count=0,
                    message="ETF/ETN 제외",
                )
            continue

        corp_code = corp_code_map.get(stock.code)
        if not corp_code:
            report.skipped_targets += 1
            message = f"{stock.code} {stock.name}: OpenDART corp_code 를 찾지 못했습니다."
            report.warnings.append(message)
            if not dry_run:
                record_collection_status(
                    stock=stock,
                    data_type=StockDataCollectionStatus.TYPE_FINANCIAL_SNAPSHOT,
                    status=StockDataCollectionStatus.STATUS_SKIPPED,
                    source=FINANCIAL_SNAPSHOT_SOURCE,
                    row_count=0,
                    message="corp_code 미해결",
                )
            continue

        stock_created = 0
        stock_updated = 0
        stock_found = 0

        try:
            for fiscal_year in target_years:
                for report_code, period_type in REPORT_CODE_TO_PERIOD.items():
                    rows = fetch_financial_statement_rows(api_key, corp_code, fiscal_year, report_code, "CFS")
                    fs_div = "CFS"
                    if not rows:
                        rows = fetch_financial_statement_rows(api_key, corp_code, fiscal_year, report_code, "OFS")
                        fs_div = "OFS"
                    if not rows:
                        continue

                    stock_found += 1
                    defaults = _build_snapshot_defaults(stock, rows, fiscal_year, period_type, fs_div)
                    existing = FinancialSnapshot.objects.filter(
                        stock=stock,
                        fiscal_year=fiscal_year,
                        period_type=period_type,
                    ).exists()

                    if dry_run:
                        if existing:
                            stock_updated += 1
                        else:
                            stock_created += 1
                        continue

                    _, created = FinancialSnapshot.objects.update_or_create(
                        stock=stock,
                        fiscal_year=fiscal_year,
                        period_type=period_type,
                        defaults=defaults,
                    )
                    if created:
                        stock_created += 1
                    else:
                        stock_updated += 1

            report.created_rows += stock_created
            report.updated_rows += stock_updated

            if stock_found == 0:
                report.empty_targets += 1
                message = f"{stock.code} {stock.name}: OpenDART 재무 스냅샷이 비어 있습니다."
                report.warnings.append(message)
                if not dry_run:
                    record_collection_status(
                        stock=stock,
                        data_type=StockDataCollectionStatus.TYPE_FINANCIAL_SNAPSHOT,
                        status=StockDataCollectionStatus.STATUS_EMPTY,
                        source=FINANCIAL_SNAPSHOT_SOURCE,
                        row_count=0,
                        message="재무 스냅샷 없음",
                    )
                logger.warning(
                    "Financial snapshot collection returned no rows",
                    extra={
                        "event": "financial_snapshot_collect_empty",
                        "stock_code": stock.code,
                        "source": FINANCIAL_SNAPSHOT_SOURCE,
                    },
                )
                continue

            if not dry_run:
                record_collection_status(
                    stock=stock,
                    data_type=StockDataCollectionStatus.TYPE_FINANCIAL_SNAPSHOT,
                    status=StockDataCollectionStatus.STATUS_SUCCESS,
                    source=FINANCIAL_SNAPSHOT_SOURCE,
                    row_count=stock_found,
                    message=f"{stock_found}개 스냅샷 동기화",
                )
        except Exception as exc:
            report.error_targets += 1
            message = f"{stock.code} {stock.name}: 재무 스냅샷 자동 수집에 실패했습니다. ({exc})"
            report.warnings.append(message)
            if not dry_run:
                record_collection_status(
                    stock=stock,
                    data_type=StockDataCollectionStatus.TYPE_FINANCIAL_SNAPSHOT,
                    status=StockDataCollectionStatus.STATUS_ERROR,
                    source=FINANCIAL_SNAPSHOT_SOURCE,
                    row_count=0,
                    message=str(exc),
                )
            logger.exception(
                "Financial snapshot collection failed",
                extra={
                    "event": "financial_snapshot_collect_error",
                    "stock_code": stock.code,
                    "source": FINANCIAL_SNAPSHOT_SOURCE,
                    "error_type": exc.__class__.__name__,
                },
            )

    return report
