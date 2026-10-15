"""Market-data provider abstraction.

The analysis engine is NEVER coupled to one vendor. Providers expose a
uniform interface and fail loudly (never invent data) when unavailable.

Available providers:
    csv          - local CSV files in data/raw/ (offline, no key)
    binance      - public crypto REST API (no key)
    yahoo        - public Yahoo Finance chart API (no key)
    twelvedata   - forex/metals/crypto (API key)
    alphavantage - forex/metals/crypto (API key)
"""

from __future__ import annotations

import abc
from dataclasses import dataclass

from src.market.candles import CandleSeries
from src.market.symbols import SymbolInfo
from src.utils.config import Settings, env_secret
from src.utils.errors import (
    DataUnavailableError,
    InsufficientDataError,
    ProviderError,
    ValidationError,
)
from src.utils.logging import get_logger

logger = get_logger("provider")


@dataclass(frozen=True)
class Availability:
    available: bool
    reason: str


class MarketDataProvider(abc.ABC):
    """Base class for all market-data providers."""

    name: str = "base"
    display_name: str = "Base provider"
    requires_key: str | None = None

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.timeout = int(settings.providers.request_timeout)

    # ---- required hooks -------------------------------------------------
    @abc.abstractmethod
    def availability(self) -> Availability:
        """Whether the provider can be used right now (key/file present)."""

    @abc.abstractmethod
    def supports_symbol(self, info: SymbolInfo) -> bool:
        """Whether this provider can serve the given instrument class."""

    @abc.abstractmethod
    def fetch_ohlcv(self, info: SymbolInfo, timeframe: str, limit: int) -> CandleSeries:
        """Fetch raw candles. Raises ProviderError on any failure."""

    # ---- shared behaviour ----------------------------------------------
    def api_key(self) -> str | None:
        if self.requires_key is None:
            return None
        return env_secret(self.requires_key, "MARKET_DATA_API_KEY")

    def get_ohlcv(self, info: SymbolInfo, timeframe: str, limit: int = 500) -> CandleSeries:
        """Fetch, sanitize and usability-check a candle series."""
        if limit < 10:
            raise ValidationError("limit must be >= 10 candles")
        series = self.fetch_ohlcv(info, timeframe, limit)
        series, repaired = series.sanitize()
        if repaired:
            logger.debug("%s: sanitized data: %s", self.name, "; ".join(repaired))
            notes = series.metadata.setdefault("provider_notes", [])
            notes.extend(repaired)
        usable, reasons = series.is_usable(min_bars=10)
        if not usable:
            raise InsufficientDataError(
                f"{self.name}: unusable data for {info.symbol} {timeframe}: "
                + "; ".join(reasons)
            )
        series.metadata.setdefault("provider", self.name)
        return series

    def get_latest_price(self, info: SymbolInfo) -> float:
        price, _ = self.get_latest_price_detail(info)
        return price

    def get_latest_price_detail(self, info: SymbolInfo) -> tuple[float, str]:
        """Return (price, provenance note). Falls back through small TFs."""
        errors: list[str] = []
        for timeframe in ("M1", "M5", "M15", "H1", "D1"):
            try:
                series = self.get_ohlcv(info, timeframe, 5)
            except DataUnavailableError as exc:
                errors.append(str(exc))
                continue
            price = series.last_close()
            if price is None:
                errors.append(f"{timeframe}: last close missing")
                continue
            last_time = series.end
            provenance = (
                f"{self.name} {timeframe} close"
                + (f" ({last_time.isoformat()})" if last_time else "")
            )
            return price, provenance
        raise ProviderError(
            f"{self.name}: latest price unavailable for {info.symbol}: "
            + "; ".join(errors[-2:] or ["no timeframe succeeded"])
        )

    def get_multiple_timeframes(
        self, info: SymbolInfo, timeframes: list[str], limit: int = 500
    ) -> dict[str, CandleSeries]:
        """Fetch several timeframes, skipping the ones that fail."""
        result: dict[str, CandleSeries] = {}
        for timeframe in timeframes:
            try:
                result[timeframe] = self.get_ohlcv(info, timeframe, limit)
            except DataUnavailableError as exc:
                logger.warning("provider %s missing %s %s: %s", self.name, info.symbol, timeframe, exc)
        return result


def _registry() -> dict[str, type[MarketDataProvider]]:
    from src.market.providers.alphavantage import AlphaVantageProvider
    from src.market.providers.binance import BinanceProvider
    from src.market.providers.csv_provider import CSVProvider
    from src.market.providers.null_provider import NullProvider
    from src.market.providers.twelvedata import TwelveDataProvider
    from src.market.providers.yahoo import YahooProvider

    classes = [
        CSVProvider,
        BinanceProvider,
        YahooProvider,
        TwelveDataProvider,
        AlphaVantageProvider,
        NullProvider,
    ]
    return {cls.name: cls for cls in classes}


def provider_names() -> list[str]:
    return list(_registry())


def build_provider(name: str, settings: Settings) -> MarketDataProvider:
    registry = _registry()
    if name not in registry:
        raise ValidationError(
            f"unknown provider {name!r}. Available: {', '.join(sorted(registry))}"
        )
    return registry[name](settings)


def build_provider_chain(
    settings: Settings, info: SymbolInfo, requested: str = "auto"
) -> list[MarketDataProvider]:
    """Ordered list of providers to try for an instrument.

    'auto' follows providers.priority; named providers are returned
    alone (plus CSV as a last-resort fallback for ``auto`` only).
    """
    if requested and requested != "auto":
        provider = build_provider(requested, settings)
        availability = provider.availability()
        if not availability.available and requested != "null":
            raise ProviderError(
                f"provider {requested!r} is not available: {availability.reason}"
            )
        return [provider]
    chain: list[MarketDataProvider] = []
    for name in settings.providers.priority:
        try:
            provider = build_provider(name, settings)
        except ValidationError:
            logger.warning("unknown provider %r in providers.priority; ignored", name)
            continue
        availability = provider.availability()
        if not availability.available:
            logger.debug("provider %s unavailable: %s", name, availability.reason)
            continue
        if not provider.supports_symbol(info):
            logger.debug("provider %s does not support %s", name, info.symbol)
            continue
        if provider.name not in {p.name for p in chain}:
            chain.append(provider)
    if "csv" not in {p.name for p in chain}:
        try:
            csv_provider = build_provider("csv", settings)
        except ValidationError:
            csv_provider = None
        if csv_provider is not None and csv_provider.availability().available:
            chain.append(csv_provider)
    if not chain:
        chain.append(build_provider("null", settings))
    return chain
