from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from data_pipeline.dataclasses import RiskEventRow
from decisions.services.collectors.risk_event_collector import (
    _build_risk_event_defaults,
    fetch_dart_disclosures,
    get_dart_corp_code_map,
)

from .base import BaseDataProvider


class DisclosureProvider(BaseDataProvider):
    provider_name = "disclosure"

    def get_risk_event_rows(self, stock, days: int):
        api_key = getattr(settings, "OPENDART_API_KEY", "").strip()
        if not api_key:
            raise ValueError("OPENDART_API_KEY is not configured.")

        corp_code = get_dart_corp_code_map(api_key).get(stock.code)
        if not corp_code:
            return []

        bgn_de = (timezone.localdate() - timedelta(days=max(days - 1, 0))).strftime("%Y%m%d")
        end_de = timezone.localdate().strftime("%Y%m%d")
        rows = []
        for disclosure in fetch_dart_disclosures(api_key, corp_code, bgn_de, end_de):
            built = _build_risk_event_defaults(stock, disclosure)
            if built is None:
                continue
            defaults = built["defaults"]
            rows.append(
                RiskEventRow(
                    stock_code=stock.code,
                    event_type=defaults["event_type"],
                    title=defaults["title"],
                    event_date=defaults["event_date"],
                    risk_level=defaults["risk_level"],
                    description=defaults["description"],
                    source=defaults["source"],
                    source_key=built["source_key"],
                    url=defaults["url"],
                    is_active=defaults["is_active"],
                )
            )
        return rows
