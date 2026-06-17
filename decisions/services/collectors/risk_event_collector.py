from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache
import io
import json
import logging
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

from django.conf import settings
from django.utils import timezone

from decisions.models import RiskEvent
from decisions.services.importers.risk_event_import_service import build_risk_event_source_key
from marketdata.models import StockDataCollectionStatus
from marketdata.services.collection_status_service import record_collection_status
from stocks.models import Stock

logger = logging.getLogger(__name__)


OPENDART_CORP_CODE_URL = "https://opendart.fss.or.kr/api/corpCode.xml"
OPENDART_LIST_URL = "https://opendart.fss.or.kr/api/list.json"
OPENDART_DISCLOSURE_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt_no}"
RISK_EVENT_SOURCE = "opendart_auto"
AUTO_ACTIVE_WINDOWS = {
    RiskEvent.RISK_CRITICAL: 365,
    RiskEvent.RISK_HIGH: 180,
    RiskEvent.RISK_MEDIUM: 90,
    RiskEvent.RISK_LOW: 60,
}


@dataclass
class RiskEventCollectionReport:
    target_count: int = 0
    created_rows: int = 0
    updated_rows: int = 0
    skipped_targets: int = 0
    empty_targets: int = 0
    error_targets: int = 0
    warnings: list[str] = field(default_factory=list)


def _get_target_stocks(*, stock_code=None, all_stocks=False):
    if stock_code:
        return Stock.objects.filter(code=stock_code)
    if all_stocks:
        return Stock.objects.filter(is_active=True).order_by("code")
    return Stock.objects.filter(holdings__is_active=True).distinct().order_by("code")


def _load_json(url: str):
    with urllib.request.urlopen(url, timeout=20) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


@lru_cache(maxsize=4)
def get_dart_corp_code_map(api_key: str):
    url = f"{OPENDART_CORP_CODE_URL}?{urllib.parse.urlencode({'crtfc_key': api_key})}"
    with urllib.request.urlopen(url, timeout=20) as response:
        raw_payload = response.read()

    with zipfile.ZipFile(io.BytesIO(raw_payload)) as archive:
        xml_name = archive.namelist()[0]
        xml_payload = archive.read(xml_name)

    root = ET.fromstring(xml_payload)
    mapping = {}
    for item in root.findall("list"):
        stock_code = (item.findtext("stock_code") or "").strip()
        corp_code = (item.findtext("corp_code") or "").strip()
        if stock_code and corp_code:
            mapping[stock_code] = corp_code
    return mapping


def fetch_dart_disclosures(api_key: str, corp_code: str, bgn_de: str, end_de: str):
    items = []
    page_no = 1
    while True:
        params = {
            "crtfc_key": api_key,
            "corp_code": corp_code,
            "bgn_de": bgn_de,
            "end_de": end_de,
            "last_reprt_at": "Y",
            "sort": "date",
            "sort_mth": "desc",
            "page_no": page_no,
            "page_count": 100,
        }
        payload = _load_json(f"{OPENDART_LIST_URL}?{urllib.parse.urlencode(params)}")
        status = payload.get("status")
        if status == "013":
            return []
        if status != "000":
            raise ValueError(payload.get("message") or f"OpenDART 오류(status={status})")

        items.extend(payload.get("list", []))
        total_page = int(payload.get("total_page") or 1)
        if page_no >= total_page:
            break
        page_no += 1
    return items


def classify_dart_risk_event(report_name: str):
    normalized = (report_name or "").replace(" ", "")
    if "거래정지" in normalized:
        return ("trading_halt", RiskEvent.RISK_CRITICAL)
    if "상장폐지" in normalized:
        return ("delisting_risk", RiskEvent.RISK_CRITICAL)
    if "관리종목" in normalized:
        return ("managed_stock", RiskEvent.RISK_HIGH)
    if "감사의견" in normalized and any(keyword in normalized for keyword in ("거절", "부적정")):
        return ("audit_opinion_rejected", RiskEvent.RISK_CRITICAL)
    if "감사의견" in normalized and "한정" in normalized:
        return ("audit_opinion_rejected", RiskEvent.RISK_HIGH)
    if any(keyword in normalized for keyword in ("횡령", "배임")):
        return ("embezzlement", RiskEvent.RISK_CRITICAL)
    if "감자" in normalized:
        return ("capital_reduction", RiskEvent.RISK_HIGH)
    if "유상증자" in normalized:
        return ("paid_in_capital_increase", RiskEvent.RISK_MEDIUM)
    if any(keyword in normalized for keyword in ("자본잠식", "자본전액잠식", "완전자본잠식")):
        return ("capital_impairment", RiskEvent.RISK_HIGH)
    if "불성실공시" in normalized:
        return ("disclosure_violation", RiskEvent.RISK_HIGH)
    if any(keyword in normalized for keyword in ("영업손실", "적자전환", "손익구조", "매출액또는손익구조")):
        return ("operating_loss", RiskEvent.RISK_MEDIUM)
    return None


def _parse_receipt_date(value: str):
    return datetime.strptime(value, "%Y%m%d").date()


def _should_auto_event_be_active(event_date, risk_level: str, today=None):
    current_date = today or timezone.localdate()
    window_days = AUTO_ACTIVE_WINDOWS.get(risk_level, 60)
    return (current_date - event_date).days <= window_days


def _refresh_auto_risk_event_activity(stock):
    current_date = timezone.localdate()
    for event in RiskEvent.objects.filter(stock=stock, source=RISK_EVENT_SOURCE):
        should_be_active = _should_auto_event_be_active(event.event_date, event.risk_level, today=current_date)
        if event.is_active != should_be_active:
            event.is_active = should_be_active
            event.save(update_fields=["is_active", "updated_at"])


def _build_risk_event_defaults(stock, disclosure):
    report_name = (disclosure.get("report_nm") or "").strip()
    classification = classify_dart_risk_event(report_name)
    if classification is None:
        return None

    event_type, risk_level = classification
    event_date = _parse_receipt_date(disclosure["rcept_dt"])
    receipt_no = (disclosure.get("rcept_no") or "").strip()
    source_key = f"opendart:{receipt_no}" if receipt_no else build_risk_event_source_key(
        stock_code=stock.code,
        event_date=event_date,
        event_type=event_type,
        title=report_name,
    )
    rm_value = (disclosure.get("rm") or "").strip()
    filer_name = (disclosure.get("flr_nm") or "").strip()
    description = f"제출인={filer_name} 비고={rm_value}".strip()
    return {
        "source_key": source_key,
        "defaults": {
            "stock": stock,
            "event_type": event_type,
            "title": report_name,
            "source": RISK_EVENT_SOURCE,
            "url": OPENDART_DISCLOSURE_URL.format(receipt_no=receipt_no) if receipt_no else "",
            "event_date": event_date,
            "risk_level": risk_level,
            "description": description,
            "is_active": _should_auto_event_be_active(event_date, risk_level),
        },
    }


def collect_risk_events(*, stock_code=None, days=365, all_stocks=False, dry_run=False):
    report = RiskEventCollectionReport()
    stocks = list(_get_target_stocks(stock_code=stock_code, all_stocks=all_stocks))
    report.target_count = len(stocks)

    api_key = getattr(settings, "OPENDART_API_KEY", "").strip()
    if not api_key:
        report.error_targets = len(stocks)
        report.warnings.append("OPENDART_API_KEY 가 설정되지 않아 리스크 이벤트 자동 수집을 실행할 수 없습니다.")
        logger.error(
            "Risk event collection skipped because API key is missing",
            extra={
                "event": "risk_event_collect_config_error",
                "source": RISK_EVENT_SOURCE,
                "error_type": "MissingApiKey",
            },
        )
        if not dry_run:
            for stock in stocks:
                record_collection_status(
                    stock=stock,
                    data_type=StockDataCollectionStatus.TYPE_RISK_EVENT,
                    status=StockDataCollectionStatus.STATUS_ERROR,
                    source=RISK_EVENT_SOURCE,
                    row_count=0,
                    message="OPENDART_API_KEY 미설정",
                )
        return report

    bgn_de = (timezone.localdate() - timedelta(days=max(days - 1, 0))).strftime("%Y%m%d")
    end_de = timezone.localdate().strftime("%Y%m%d")

    try:
        corp_code_map = get_dart_corp_code_map(api_key)
    except Exception as exc:
        report.error_targets = len(stocks)
        report.warnings.append(f"OpenDART corp code 조회에 실패했습니다. ({exc})")
        logger.error(
            "Risk event collection failed during corp code lookup",
            extra={
                "event": "risk_event_collect_corp_code_error",
                "source": RISK_EVENT_SOURCE,
                "error_type": exc.__class__.__name__,
            },
        )
        if not dry_run:
            for stock in stocks:
                record_collection_status(
                    stock=stock,
                    data_type=StockDataCollectionStatus.TYPE_RISK_EVENT,
                    status=StockDataCollectionStatus.STATUS_ERROR,
                    source=RISK_EVENT_SOURCE,
                    row_count=0,
                    message=str(exc),
                )
        return report

    for stock in stocks:
        corp_code = corp_code_map.get(stock.code)
        if not corp_code:
            report.skipped_targets += 1
            message = f"{stock.code} {stock.name}: OpenDART corp_code 를 찾지 못했습니다."
            report.warnings.append(message)
            logger.warning(
                "Risk event collection skipped because corp code is unresolved",
                extra={
                    "event": "risk_event_collect_skipped",
                    "stock_code": stock.code,
                    "source": RISK_EVENT_SOURCE,
                },
            )
            if not dry_run:
                record_collection_status(
                    stock=stock,
                    data_type=StockDataCollectionStatus.TYPE_RISK_EVENT,
                    status=StockDataCollectionStatus.STATUS_SKIPPED,
                    source=RISK_EVENT_SOURCE,
                    row_count=0,
                    message="corp_code 미매핑",
                )
            continue

        try:
            disclosures = fetch_dart_disclosures(api_key, corp_code, bgn_de, end_de)
        except Exception as exc:
            report.error_targets += 1
            message = f"{stock.code} {stock.name}: 리스크 이벤트 자동 수집에 실패했습니다. ({exc})"
            report.warnings.append(message)
            logger.error(
                "Risk event collection failed",
                extra={
                    "event": "risk_event_collect_error",
                    "stock_code": stock.code,
                    "source": RISK_EVENT_SOURCE,
                    "error_type": exc.__class__.__name__,
                },
            )
            if not dry_run:
                record_collection_status(
                    stock=stock,
                    data_type=StockDataCollectionStatus.TYPE_RISK_EVENT,
                    status=StockDataCollectionStatus.STATUS_ERROR,
                    source=RISK_EVENT_SOURCE,
                    row_count=0,
                    message=str(exc),
                )
            continue

        relevant_items = []
        for disclosure in disclosures:
            built = _build_risk_event_defaults(stock, disclosure)
            if built is not None:
                relevant_items.append(built)

        if not relevant_items:
            report.empty_targets += 1
            logger.warning(
                "Risk event collection returned no matching disclosures",
                extra={
                    "event": "risk_event_collect_empty",
                    "stock_code": stock.code,
                    "source": RISK_EVENT_SOURCE,
                },
            )
            if not dry_run:
                _refresh_auto_risk_event_activity(stock)
                record_collection_status(
                    stock=stock,
                    data_type=StockDataCollectionStatus.TYPE_RISK_EVENT,
                    status=StockDataCollectionStatus.STATUS_EMPTY,
                    source=RISK_EVENT_SOURCE,
                    row_count=0,
                    message="매칭된 위험 공시가 없습니다.",
                )
            continue

        for item in relevant_items:
            if dry_run:
                exists = RiskEvent.objects.filter(source_key=item["source_key"]).exists()
                if exists:
                    report.updated_rows += 1
                else:
                    report.created_rows += 1
                continue

            _, created = RiskEvent.objects.update_or_create(
                source_key=item["source_key"],
                defaults=item["defaults"],
            )
            if created:
                report.created_rows += 1
            else:
                report.updated_rows += 1

        if not dry_run:
            _refresh_auto_risk_event_activity(stock)
            record_collection_status(
                stock=stock,
                data_type=StockDataCollectionStatus.TYPE_RISK_EVENT,
                status=StockDataCollectionStatus.STATUS_SUCCESS,
                source=RISK_EVENT_SOURCE,
                row_count=len(relevant_items),
                message="",
            )

    return report
