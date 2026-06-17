from .auto_provider import AutoProvider
from django.conf import settings

from .disclosure_provider import DisclosureProvider
from .finance_provider import FinanceProvider
from .financial_statement_provider import FinancialStatementProvider
from .krx_provider import KRXProvider
from .mock_provider import MockDataProvider


def get_provider(provider_name: str | None = None):
    name = (provider_name or getattr(settings, "DATA_PIPELINE_PROVIDER", "mock")).lower()
    provider_map = {
        "auto": AutoProvider,
        "mock": MockDataProvider,
        "krx": KRXProvider,
        "finance": FinanceProvider,
        "disclosure": DisclosureProvider,
        "financial_statement": FinancialStatementProvider,
    }
    if name == "toss":
        from .toss_provider import TossOpenApiProvider

        provider_map["toss"] = TossOpenApiProvider
    provider_class = provider_map.get(name)
    if provider_class is None:
        raise ValueError(f"Unsupported data provider: {name}")
    return provider_class()
