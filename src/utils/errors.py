"""Exception hierarchy for the trading-agent framework.

All framework errors derive from TradingAgentError so the CLI can
degrade gracefully instead of crashing with a traceback.
"""


class TradingAgentError(Exception):
    """Base class for every framework error."""


class ConfigError(TradingAgentError):
    """Invalid or unreadable configuration."""


class ValidationError(TradingAgentError):
    """Invalid user input (symbol, timeframe, price, size, ...)."""


class DataUnavailableError(TradingAgentError):
    """The requested data is not available from any source.

    This must ALWAYS be preferred over fabricating data.
    """


class InsufficientDataError(DataUnavailableError):
    """Data exists but is not sufficient for the requested analysis."""


class ProviderError(DataUnavailableError):
    """A market-data provider failed (network, API, malformed payload)."""


class ProviderNotConfiguredError(ProviderError):
    """A provider was selected but is not configured (usually missing key)."""
