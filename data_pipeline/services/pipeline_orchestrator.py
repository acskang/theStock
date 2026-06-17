from __future__ import annotations

from data_pipeline.services.data_quality_service import update_data_quality
from data_pipeline.services.financial_data_ingestion_service import ingest_financial_data
from data_pipeline.services.investor_flow_ingestion_service import ingest_investor_flows
from data_pipeline.services.market_index_ingestion_service import ingest_market_indices
from data_pipeline.services.price_ingestion_service import ingest_daily_prices
from data_pipeline.services.risk_event_ingestion_service import ingest_risk_events
from data_pipeline.services.stock_master_ingestion_service import ingest_stock_master


def run_daily_pipeline(
    *,
    provider_name: str | None = None,
    stock_codes=None,
    price_days: int = 240,
    investor_flow_days: int = 60,
    market_index_days: int = 240,
    risk_event_days: int = 365,
    financial_years: int = 2,
    market_index_codes=None,
    all_stocks: bool = False,
    skip_investor_flows: bool = False,
    skip_risk_events: bool = False,
    skip_financial_data: bool = False,
    dry_run: bool = False,
):
    reports = {
        "stock_master": ingest_stock_master(provider_name=provider_name, dry_run=dry_run),
        "daily_prices": ingest_daily_prices(
            provider_name=provider_name,
            stock_codes=stock_codes,
            days=price_days,
            all_stocks=all_stocks,
            dry_run=dry_run,
        ),
        "investor_flows": ingest_investor_flows(
            provider_name=provider_name,
            stock_codes=stock_codes,
            days=investor_flow_days,
            all_stocks=all_stocks,
            dry_run=dry_run,
        ),
        "market_indices": ingest_market_indices(
            provider_name=provider_name,
            codes=market_index_codes,
            days=market_index_days,
            dry_run=dry_run,
        ),
    }
    if not skip_investor_flows:
        reports["investor_flows"] = ingest_investor_flows(
            provider_name=provider_name,
            stock_codes=stock_codes,
            days=investor_flow_days,
            all_stocks=all_stocks,
            dry_run=dry_run,
        )
    if not skip_risk_events:
        reports["risk_events"] = ingest_risk_events(
            provider_name=provider_name,
            stock_codes=stock_codes,
            days=risk_event_days,
            all_stocks=all_stocks,
            dry_run=dry_run,
        )
    if not skip_financial_data:
        reports["financial_data"] = ingest_financial_data(
            provider_name=provider_name,
            stock_codes=stock_codes,
            years=financial_years,
            all_stocks=all_stocks,
            dry_run=dry_run,
        )
    if dry_run:
        return reports
    reports["data_quality"] = update_data_quality(stock_codes=stock_codes, all_stocks=all_stocks)
    return reports
