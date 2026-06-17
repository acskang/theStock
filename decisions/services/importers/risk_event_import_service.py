from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date

from decisions.models import RiskEvent
from stocks.models import Stock


REQUIRED_COLUMNS = (
    "stock_code",
    "event_date",
    "event_type",
    "risk_level",
    "title",
)
VALID_EVENT_TYPES = {choice[0] for choice in RiskEvent.EVENT_TYPE_CHOICES}
VALID_RISK_LEVELS = {choice[0] for choice in RiskEvent.RISK_LEVEL_CHOICES}


@dataclass
class RiskEventImportReport:
    created_count: int = 0
    updated_count: int = 0
    skipped_rows: int = 0
    warnings: list[str] = field(default_factory=list)


def normalize_risk_event_title(title: str) -> str:
    collapsed = re.sub(r"\s+", " ", (title or "").strip().lower())
    collapsed = re.sub(r"[^0-9a-z가-힣 ]", "", collapsed)
    return collapsed.strip()


def build_risk_event_source_key(stock_code: str, event_date: date, event_type: str, title: str) -> str:
    normalized_title = normalize_risk_event_title(title)
    return f"{stock_code}:{event_date.isoformat()}:{event_type}:{normalized_title}"


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except Exception as exc:
        raise ValueError(f"잘못된 날짜 형식입니다: {value}") from exc


def _parse_bool(value) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"", "1", "true", "t", "yes", "y"}:
        return True
    if normalized in {"0", "false", "f", "no", "n"}:
        return False
    raise ValueError(f"불리언 값을 해석할 수 없습니다: {value}")


def _validate_columns(fieldnames):
    if not fieldnames:
        raise ValueError("CSV 헤더가 없습니다.")
    missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    if missing:
        raise ValueError(f"필수 컬럼이 없습니다: {', '.join(missing)}")


def import_risk_events_from_csv(file_path, *, dry_run=False, skip_missing_stocks=False):
    report = RiskEventImportReport()

    with open(file_path, "r", encoding="utf-8-sig", newline="") as file_obj:
        reader = csv.DictReader(file_obj)
        _validate_columns(reader.fieldnames)

        for row_number, row in enumerate(reader, start=2):
            stock_code = (row.get("stock_code") or "").strip()
            if not stock_code:
                report.skipped_rows += 1
                report.warnings.append(f"{row_number}행: stock_code 가 비어 있어 건너뛰었습니다.")
                continue

            stock = Stock.objects.filter(code=stock_code).first()
            if stock is None:
                if skip_missing_stocks:
                    report.skipped_rows += 1
                    report.warnings.append(f"{row_number}행: stock_code={stock_code} 종목이 없어 건너뛰었습니다.")
                    continue
                raise ValueError(f"{row_number}행: stock_code={stock_code} 종목이 존재하지 않습니다.")

            event_date = _parse_date(row["event_date"])
            event_type = (row.get("event_type") or "").strip()
            risk_level = (row.get("risk_level") or "").strip()
            title = (row.get("title") or "").strip()
            if event_type not in VALID_EVENT_TYPES:
                raise ValueError(f"{row_number}행: event_type={event_type} 는 허용되지 않습니다.")
            if risk_level not in VALID_RISK_LEVELS:
                raise ValueError(f"{row_number}행: risk_level={risk_level} 는 허용되지 않습니다.")
            if not title:
                raise ValueError(f"{row_number}행: title 이 비어 있습니다.")

            source_key = (row.get("source_key") or "").strip() or build_risk_event_source_key(
                stock_code=stock_code,
                event_date=event_date,
                event_type=event_type,
                title=title,
            )
            defaults = {
                "stock": stock,
                "event_type": event_type,
                "title": title,
                "source": (row.get("source") or "").strip(),
                "url": (row.get("url") or "").strip(),
                "event_date": event_date,
                "risk_level": risk_level,
                "description": (row.get("description") or "").strip(),
                "is_active": _parse_bool(row.get("is_active", "")),
            }

            if dry_run:
                exists = RiskEvent.objects.filter(source_key=source_key).exists()
                if exists:
                    report.updated_count += 1
                else:
                    report.created_count += 1
                continue

            _, created = RiskEvent.objects.update_or_create(
                source_key=source_key,
                defaults=defaults,
            )
            if created:
                report.created_count += 1
            else:
                report.updated_count += 1

    return report
