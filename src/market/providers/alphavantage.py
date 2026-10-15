"""Alpha Vantage provider (API key required).

Env var: ALPHA_VANTAGE_API_KEY (or MARKET_DATA_API_KEY as fallback).

Supported here:
    forex/metals : FX_INTRADAY (M1..H1), FX_DAILY (D1), FX_WEEKLY (W1)
    crypto       : DIGITAL_CURRENCY_INTRADAY (M1..H1), DIGITAL_CURRENCY_DAILY (D1),
                   DIGITAL_CURRENCY_WEEKLY (W1)
    H4           : built locally by resampling H1 (labelled)

Free tier is rate-limited (approx. 25 requests/day); rate-limit
responses are converted into ProviderError so the caller can fall back.
"""

from __future__ import annotations

from datetime import UTC, datetime

import requests

from src.market.candles import CandleSeries, resample_series
from src.market.data_provider import Availability, MarketDataProvider
from src.market.symbols import SymbolInfo
from src.market.timeframes import normalize_timeframe
from src.utils.errors import ProviderError, ProviderNotConfiguredError
from src.utils.logging import get_logger

logger = get_logger("provider.alphavantage")

_INTRADAY_INTERVALS = {"M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min", "H1": "60min"}
_CRYPTO_QUOTE_MAP = {"USDT": "USD", "USDC": "USD", "BUSD": "USD", "FDUSD": "USD", "TUSD": "USD"}


class AlphaVantageProvider(MarketDataProvider):
    name = "alphavantage"
    display_name = "Alpha Vantage"
    requires_key = "ALPHA_VANTAGE_API_KEY"
    base_url = "https://www.alphavantage.co/query"

    def availability(self) -> Availability:
        if not self.api_key():
            return Availability(False, "ALPHA_VANTAGE_API_KEY is not set (see .env.example)")
        return Availability(True, "API key present")

    def supports_symbol(self, info: SymbolInfo) -> bool:
        return info.asset_class in ("forex", "metal", "crypto")

    def _request(self, params: dict[str, str]) -> dict:
        if not self.api_key():
            raise ProviderNotConfiguredError(
                "ALPHA_VANTAGE_API_KEY is not set; cannot use the alphavantage provider"
            )
        params = {**params, "apikey": self.api_key() or ""}
        try:
            response = requests.get(self.base_url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ProviderError(f"alphavantage request failed: {exc}") from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError("alphavantage returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise ProviderError("alphavantage returned an unexpected payload")
        for key in ("Error Message", "Note", "Information"):
            if key in payload:
                raise ProviderError(f"alphavantage: {payload[key]}")
        return payload

    @staticmethod
    def _extract_series(payload: dict) -> tuple[str, dict]:
        for key, value in payload.items():
            if key.startswith("Time Series") and isinstance(value, dict):
                return key, value
        raise ProviderError("alphavantage returned no recognizable time series")

    def fetch_ohlcv(self, info: SymbolInfo, timeframe: str, limit: int) -> CandleSeries:
        tf = normalize_timeframe(timeframe)
        if info.asset_class in ("forex", "metal"):
            payload, notes, resample = self._fetch_fx(info, tf)
        elif info.asset_class == "crypto":
            payload, notes, resample = self._fetch_crypto(info, tf)
        else:
            raise ProviderError(f"alphavantage cannot serve {info.symbol}")

        try:
            series_key, values = self._extract_series(payload)
        except ProviderError:
            raise
        rows = []
        for timestamp, item in values.items():
            if not isinstance(item, dict):
                continue
            open_value = item.get("1. open") or item.get("open")
            high_value = item.get("2. high") or item.get("high")
            low_value = item.get("3. low") or item.get("low")
            close_value = item.get("4. close") or item.get("close")
            volume_raw = (
                item.get("5. volume")
                or item.get("6. volume")
                or item.get("volume")
            )
            try:
                volume = float(volume_raw) if volume_raw not in (None, "") else None
            except (TypeError, ValueError):
                volume = None
            rows.append(
                {
                    "time": timestamp,
                    "open": open_value,
                    "high": high_value,
                    "low": low_value,
                    "close": close_value,
                    "volume": volume,
                }
            )
        if not rows:
            raise ProviderError(f"alphavantage returned no candles for {info.symbol} {tf}")

        series = CandleSeries.from_rows(
            symbol=info.symbol,
            timeframe=tf,
            source=f"alphavantage:{series_key}",
            rows=rows,
            metadata={
                "live": True,
                "fetched_at": datetime.now(UTC).isoformat(),
                "provider_notes": notes,
            },
        )
        if resample:
            series = resample_series(series, resample)
        if limit and len(series) > limit:
            series.candles = series.candles[-int(limit):]
        return series

    def _fetch_fx(self, info: SymbolInfo, tf: str) -> tuple[dict, list[str], str | None]:
        notes = [f"source pair: {info.base}/{info.quote}"]
        if tf in _INTRADAY_INTERVALS:
            payload = self._request(
                {
                    "function": "FX_INTRADAY",
                    "from_symbol": info.base,
                    "to_symbol": info.quote,
                    "interval": _INTRADAY_INTERVALS[tf],
                    "outputsize": "full",
                }
            )
            return payload, notes, None
        if tf == "H4":
            payload = self._request(
                {
                    "function": "FX_INTRADAY",
                    "from_symbol": info.base,
                    "to_symbol": info.quote,
                    "interval": "60min",
                    "outputsize": "full",
                }
            )
            notes.append("H4 built locally from alphavantage H1 candles")
            return payload, notes, "H4"
        if tf == "D1":
            payload = self._request(
                {
                    "function": "FX_DAILY",
                    "from_symbol": info.base,
                    "to_symbol": info.quote,
                    "outputsize": "full",
                }
            )
            return payload, notes, None
        payload = self._request(
            {
                "function": "FX_WEEKLY",
                "from_symbol": info.base,
                "to_symbol": info.quote,
            }
        )
        return payload, notes, None

    def _fetch_crypto(self, info: SymbolInfo, tf: str) -> tuple[dict, list[str], str | None]:
        market = _CRYPTO_QUOTE_MAP.get(info.quote, info.quote)
        notes = [f"source pair: {info.base}/{market}"]
        if market != info.quote:
            notes.append(
                f"alphavantage {info.base}/{market} used as proxy for {info.symbol} "
                "(stablecoins are not USD)"
            )
        if tf in _INTRADAY_INTERVALS:
            payload = self._request(
                {
                    "function": "DIGITAL_CURRENCY_INTRADAY",
                    "symbol": info.base,
                    "market": market,
                    "interval": _INTRADAY_INTERVALS[tf],
                }
            )
            return payload, notes, None
        if tf == "H4":
            payload = self._request(
                {
                    "function": "DIGITAL_CURRENCY_INTRADAY",
                    "symbol": info.base,
                    "market": market,
                    "interval": "60min",
                }
            )
            notes.append("H4 built locally from alphavantage H1 candles")
            return payload, notes, "H4"
        if tf == "D1":
            payload = self._request(
                {
                    "function": "DIGITAL_CURRENCY_DAILY",
                    "symbol": info.base,
                    "market": market,
                }
            )
            return payload, notes, None
        payload = self._request(
            {
                "function": "DIGITAL_CURRENCY_WEEKLY",
                "symbol": info.base,
                "market": market,
            }
        )
        return payload, notes, None
