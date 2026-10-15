"""Twelve Data provider (API key required).

Env var: TWELVE_DATA_API_KEY (or MARKET_DATA_API_KEY as fallback).
Free tier is rate-limited (approx. 8 requests/minute, 800/day) - the
framework treats rate-limit responses as provider errors and falls back
to the next provider.

Endpoint: GET https://api.twelvedata.com/time_series
"""

from __future__ import annotations

from datetime import UTC, datetime

import requests

from src.market.candles import CandleSeries
from src.market.data_provider import Availability, MarketDataProvider
from src.market.symbols import SymbolInfo
from src.market.timeframes import normalize_timeframe
from src.utils.errors import ProviderError, ProviderNotConfiguredError
from src.utils.logging import get_logger

logger = get_logger("provider.twelvedata")

INTERVALS = {
    "M1": "1min",
    "M5": "5min",
    "M15": "15min",
    "M30": "30min",
    "H1": "1h",
    "H4": "4h",
    "D1": "1day",
    "W1": "1week",
}


class TwelveDataProvider(MarketDataProvider):
    name = "twelvedata"
    display_name = "Twelve Data"
    requires_key = "TWELVE_DATA_API_KEY"
    base_url = "https://api.twelvedata.com/time_series"

    def availability(self) -> Availability:
        if not self.api_key():
            return Availability(
                False,
                "TWELVE_DATA_API_KEY is not set (see .env.example)",
            )
        return Availability(True, "API key present")

    def supports_symbol(self, info: SymbolInfo) -> bool:
        return info.asset_class in ("forex", "metal", "crypto")

    def map_symbol(self, info: SymbolInfo) -> tuple[str | None, str | None]:
        if info.asset_class in ("forex", "metal", "crypto"):
            return f"{info.base}/{info.quote}", None
        return None, None

    def fetch_ohlcv(self, info: SymbolInfo, timeframe: str, limit: int) -> CandleSeries:
        key = self.api_key()
        if not key:
            raise ProviderNotConfiguredError(
                "TWELVE_DATA_API_KEY is not set; cannot use the twelvedata provider"
            )
        symbol, _ = self.map_symbol(info)
        if symbol is None:
            raise ProviderError(f"twelvedata cannot serve {info.symbol}")
        tf = normalize_timeframe(timeframe)
        params = {
            "symbol": symbol,
            "interval": INTERVALS[tf],
            "outputsize": min(max(int(limit), 10), 5000),
            "order": "ASC",
            "apikey": key,
            "timezone": "UTC",
        }
        try:
            response = requests.get(self.base_url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ProviderError(f"twelvedata request failed: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError("twelvedata returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderError("twelvedata returned an unexpected payload")
        if payload.get("status") == "error" or "code" in payload:
            message = payload.get("message") or payload.get("code") or "unknown error"
            raise ProviderError(f"twelvedata error for {symbol}: {message}")
        values = payload.get("values")
        if not values:
            raise ProviderError(f"twelvedata returned no candles for {symbol} {tf}")

        rows = []
        for item in values:
            if not isinstance(item, dict):
                continue
            volume = item.get("volume")
            try:
                volume_value = float(volume) if volume not in (None, "", "0") else None
            except (TypeError, ValueError):
                volume_value = None
            rows.append(
                {
                    "time": item.get("datetime"),
                    "open": item.get("open"),
                    "high": item.get("high"),
                    "low": item.get("low"),
                    "close": item.get("close"),
                    "volume": volume_value,
                }
            )
        if not rows:
            raise ProviderError(f"twelvedata returned no usable candles for {symbol} {tf}")
        return CandleSeries.from_rows(
            symbol=info.symbol,
            timeframe=tf,
            source=f"twelvedata:{symbol}",
            rows=rows,
            metadata={
                "live": True,
                "provider_symbol": symbol,
                "fetched_at": datetime.now(UTC).isoformat(),
                "provider_notes": [f"source symbol: {symbol}"],
            },
        )
