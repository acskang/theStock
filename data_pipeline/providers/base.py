class BaseDataProvider:
    provider_name = "base"

    def get_stock_master_rows(self):
        raise NotImplementedError

    def get_daily_price_rows(self, stock, days: int):
        raise NotImplementedError

    def get_investor_flow_rows(self, stock, days: int):
        raise NotImplementedError

    def get_market_index_rows(self, code: str, days: int):
        raise NotImplementedError

    def get_risk_event_rows(self, stock, days: int):
        raise NotImplementedError

    def get_financial_snapshot_rows(self, stock, years: int):
        raise NotImplementedError

