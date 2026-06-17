from .base import BaseDataProvider
from .disclosure_provider import DisclosureProvider
from .finance_provider import FinanceProvider
from .financial_statement_provider import FinancialStatementProvider
from .krx_provider import KRXProvider


class AutoProvider(BaseDataProvider):
    provider_name = "auto"

    def __init__(self):
        self.finance_provider = FinanceProvider()
        self.krx_provider = KRXProvider()
        self.disclosure_provider = DisclosureProvider()
        self.financial_statement_provider = FinancialStatementProvider()

    def get_stock_master_rows(self):
        return self.krx_provider.get_stock_master_rows()

    def get_daily_price_rows(self, stock, days: int):
        return self.finance_provider.get_daily_price_rows(stock, days)

    def get_investor_flow_rows(self, stock, days: int):
        return self.krx_provider.get_investor_flow_rows(stock, days)

    def get_market_index_rows(self, code: str, days: int):
        return self.finance_provider.get_market_index_rows(code, days)

    def get_risk_event_rows(self, stock, days: int):
        return self.disclosure_provider.get_risk_event_rows(stock, days)

    def get_financial_snapshot_rows(self, stock, years: int):
        return self.financial_statement_provider.get_financial_snapshot_rows(stock, years)
