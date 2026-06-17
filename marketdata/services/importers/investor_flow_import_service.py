from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date

from marketdata.models import InvestorFlow
from stocks.models import Stock


REQUIRED_COLUMNS = (
    "stock_code",
    "date",
    "foreign_net_buy",
    "institution_net_buy",
    "individual_net_buy",
    "program_net_buy",
)


@dataclass
class InvestorFlowImportReport:
    created_count: int = 0
    updated_count: int = 0
    skipped_rows: int = 0
    warnings: list[str] = field(default_factory=list)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value.strip())
    except Exception as exc:
        raise ValueError(f"잘못된 날짜 형식입니다: {value}") from exc


def _parse_int(value: str) -> int:
    normalized = str(value).strip().replace(",", "")
    if normalized == "":
        return 0
    try:
        return int(normalized)
    except Exception as exc:
        raise ValueError(f"정수를 해석할 수 없습니다: {value}") from exc


def _validate_columns(fieldnames):
    if not fieldnames:
        raise ValueError("CSV 헤더가 없습니다.")
    missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
    if missing:
        raise ValueError(f"필수 컬럼이 없습니다: {', '.join(missing)}")


def import_investor_flows_from_csv(file_path, *, dry_run=False, skip_missing_stocks=False):
    report = InvestorFlowImportReport()

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

            flow_date = _parse_date(row["date"])
            defaults = {
                "foreign_net_buy": _parse_int(row["foreign_net_buy"]),
                "institution_net_buy": _parse_int(row["institution_net_buy"]),
                "individual_net_buy": _parse_int(row["individual_net_buy"]),
                "program_net_buy": _parse_int(row["program_net_buy"]),
            }

            if dry_run:
                exists = InvestorFlow.objects.filter(stock=stock, date=flow_date).exists()
                if exists:
                    report.updated_count += 1
                else:
                    report.created_count += 1
                continue

            _, created = InvestorFlow.objects.update_or_create(
                stock=stock,
                date=flow_date,
                defaults=defaults,
            )
            if created:
                report.created_count += 1
            else:
                report.updated_count += 1

    return report
