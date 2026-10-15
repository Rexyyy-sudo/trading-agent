"""Null provider: used when nothing else is available.

It exists so the analysis pipeline can produce a clean
"NO TRADE - INSUFFICIENT DATA" result instead of crashing.
"""

from __future__ import annotations

from src.market.candles import CandleSeries
from src.market.data_provider import Availability, MarketDataProvider
from src.market.symbols import SymbolInfo
from src.utils.errors import ProviderError


class NullProvider(MarketDataProvider):
    name = "null"
    display_name = "No provider"

    def availability(self) -> Availability:
        return Availability(False, "no market-data provider configured")

    def supports_symbol(self, info: SymbolInfo) -> bool:
        return True

    def fetch_ohlcv(self, info: SymbolInfo, timeframe: str, limit: int) -> CandleSeries:
        raise ProviderError(
            "No market-data source is available. Configure an API key "
            "(see .env.example) or place CSV files in data/raw/ "
            f"({info.symbol}_{timeframe}.csv)."
        )
