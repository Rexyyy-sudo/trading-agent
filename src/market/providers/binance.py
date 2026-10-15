"""Binance public REST provider (crypto, no API key required).

Public endpoints used:
    GET /api/v3/klines
    GET /api/v3/ticker/price
"""

from __future__ import annotations

from datetime import UTC, datetime

import requests

from src.market.candles import CandleSeries
from src.market.data_provider import Availability, MarketDataProvider
from src.market.symbols import SymbolInfo
from src.market.timeframes import normalize_timeframe
from src.utils.errors import ProviderError
from src.utils.logging import get_logger

logger = get_logger("provider.binance")

INTERVALS = {
    "M1": "1m",
    "M5": "5m",
    "M15": "15m",
    "M30": "30m",
    "H1": "1h",
    "H4": "4h",
    "D1": "1d",
    "W1": "1w",
}

_ALLOWED_QUOTES = {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "BTC", "ETH", "EUR", "TRY"}


class BinanceProvider(MarketDataProvider):
    name = "binance"
    display_name = "Binance public API"
    base_url = "https://api.binance.com"

    def availability(self) -> Availability:
        return Availability(True, "public REST API (no key required)")

    def supports_symbol(self, info: SymbolInfo) -> bool:
        return info.asset_class == "crypto"

    def map_symbol(self, info: SymbolInfo) -> tuple[str | None, str | None]:
        """Return (binance_symbol, note). None symbol -> unsupported."""
        if info.asset_class != "crypto":
            return None, None
        if info.quote == "USD":
            mapped = f"{info.base}USDT"
            note = (
                f"Binance {mapped} used as proxy for {info.symbol} "
                "(USDT and USD prices can differ slightly)"
            )
            return mapped, note
        if info.quote not in _ALLOWED_QUOTES:
            return None, None
        return info.symbol, None

    def _get(self, path: str, params: dict[str, object]) -> object:
        try:
            response = requests.get(
                f"{self.base_url}{path}", params=params, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise ProviderError(f"binance request failed: {exc}") from exc
        if response.status_code != 200:
            raise ProviderError(
                f"binance HTTP {response.status_code}: {self._error_message(response)}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError("binance returned invalid JSON") from exc

    @staticmethod
    def _error_message(response: requests.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict) and "msg" in payload:
                return str(payload["msg"])
        except ValueError:
            pass
        return response.text[:200].strip() or "unknown error"

    def fetch_ohlcv(self, info: SymbolInfo, timeframe: str, limit: int) -> CandleSeries:
        symbol, note = self.map_symbol(info)
        if symbol is None:
            raise ProviderError(f"binance cannot serve {info.symbol}")
        tf = normalize_timeframe(timeframe)
        interval = INTERVALS[tf]
        payload = self._get(
            "/api/v3/klines",
            {"symbol": symbol, "interval": interval, "limit": min(max(limit, 10), 1000)},
        )
        if not isinstance(payload, list):
            raise ProviderError(
                f"binance returned an unexpected payload for {symbol} {interval}"
            )
        rows = [
            {
                "time": item[0],
                "open": item[1],
                "high": item[2],
                "low": item[3],
                "close": item[4],
                "volume": item[5],
            }
            for item in payload
            if isinstance(item, list) and len(item) >= 6
        ]
        if not rows:
            raise ProviderError(f"binance returned no candles for {symbol} {interval}")
        notes = [f"source symbol: {symbol}"]
        if note:
            notes.append(note)
        return CandleSeries.from_rows(
            symbol=info.symbol,
            timeframe=tf,
            source=f"binance:{symbol}",
            rows=rows,
            metadata={
                "live": True,
                "provider_symbol": symbol,
                "fetched_at": datetime.now(UTC).isoformat(),
                "provider_notes": notes,
            },
        )

    def get_latest_price_detail(self, info: SymbolInfo) -> tuple[float, str]:
        symbol, _ = self.map_symbol(info)
        if symbol is None:
            raise ProviderError(f"binance cannot serve {info.symbol}")
        payload = self._get("/api/v3/ticker/price", {"symbol": symbol})
        if not isinstance(payload, dict) or "price" not in payload:
            raise ProviderError(f"binance ticker returned no price for {symbol}")
        return float(payload["price"]), f"binance ticker {symbol}"
