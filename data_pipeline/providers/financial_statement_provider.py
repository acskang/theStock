from django.conf import settings
from django.utils import timezone

from data_pipeline.dataclasses import FinancialSnapshotRow
from decisions.services.collectors.risk_event_collector import get_dart_corp_code_map
from stocks.services.collectors.financial_snapshot_collector import (
    REPORT_CODE_TO_PERIOD,
    _build_snapshot_defaults,
    fetch_financial_statement_rows,
)

from .base import BaseDataProvider


class FinancialStatementProvider(BaseDataProvider):
    provider_name = "financial_statement"

    def get_financial_snapshot_rows(self, stock, years: int):
        if stock.market in {stock.MARKET_ETF, stock.MARKET_ETN}:
            return []

        api_key = getattr(settings, "OPENDART_API_KEY", "").strip()
        if not api_key:
            raise ValueError("OPENDART_API_KEY is not configured.")

        corp_code = get_dart_corp_code_map(api_key).get(stock.code)
        if not corp_code:
            return []

        current_year = timezone.localdate().year
        target_years = [current_year - offset for offset in range(max(years, 1))]
        snapshots = []

        for fiscal_year in target_years:
            for report_code, period_type in REPORT_CODE_TO_PERIOD.items():
                rows = fetch_financial_statement_rows(api_key, corp_code, fiscal_year, report_code, "CFS")
                fs_div = "CFS"
                if not rows:
                    rows = fetch_financial_statement_rows(api_key, corp_code, fiscal_year, report_code, "OFS")
                    fs_div = "OFS"
                if not rows:
                    continue

                defaults = _build_snapshot_defaults(stock, rows, fiscal_year, period_type, fs_div)
                snapshots.append(
                    FinancialSnapshotRow(
                        stock_code=stock.code,
                        fiscal_year=fiscal_year,
                        period_type=period_type,
                        reported_date=defaults["reported_date"],
                        revenue=defaults["revenue"],
                        operating_profit=defaults["operating_profit"],
                        net_income=defaults["net_income"],
                        operating_cash_flow=defaults["operating_cash_flow"],
                        debt_ratio=defaults["debt_ratio"],
                        current_ratio=defaults["current_ratio"],
                        equity=defaults["equity"],
                        capital_impairment_rate=defaults["capital_impairment_rate"],
                        roe=defaults["roe"],
                        per=defaults["per"],
                        pbr=defaults["pbr"],
                        source=defaults["source"],
                        source_key=defaults["source_key"],
                    )
                )

        return snapshots
