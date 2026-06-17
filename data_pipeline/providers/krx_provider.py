from datetime import timedelta

from django.utils import timezone

from data_pipeline.dataclasses import InvestorFlowRow, StockMasterRow
from marketdata.services.collectors.investor_flow_collector import (
    _build_investor_flow_rows,
    _fetch_investor_flow_frame,
)
from stocks.models import Stock

from .base import BaseDataProvider


class KRXProvider(BaseDataProvider):
    provider_name = "krx"

    def get_stock_master_rows(self):
        return [
            StockMasterRow(
                code=stock.code,
                name=stock.name,
                market=stock.market,
                sector=stock.sector,
                is_active=stock.is_active,
            )
            for stock in Stock.objects.order_by("code")
        ]

    def get_investor_flow_rows(self, stock, days: int):
        from_date = (timezone.localdate() - timedelta(days=max(days - 1, 0))).strftime("%Y%m%d")
        to_date = timezone.localdate().strftime("%Y%m%d")
        rows = _build_investor_flow_rows(_fetch_investor_flow_frame(stock.code, from_date, to_date))
        return [
            InvestorFlowRow(
                stock_code=stock.code,
                date=row["date"],
                foreign_net_buy=row["foreign_net_buy"],
                institution_net_buy=row["institution_net_buy"],
                individual_net_buy=row["individual_net_buy"],
                program_net_buy=row["program_net_buy"],
            )
            for row in rows
        ]
