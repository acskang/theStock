class TossOpenApiError(Exception):
    """Base exception for Toss OpenAPI integration."""


class TossConfigurationError(TossOpenApiError):
    """Raised when Toss OpenAPI settings are missing or invalid."""


class TossAuthError(TossOpenApiError):
    """Raised when Toss OpenAPI authentication fails."""


class TossRateLimitError(TossOpenApiError):
    """Raised when Toss OpenAPI rate limit is exceeded."""


class TossProviderDisabled(TossOpenApiError):
    """Raised when Toss provider is disabled by settings."""


class TossOrderExecutionDisabled(TossOpenApiError):
    """Raised when Toss order execution is disabled by settings."""
