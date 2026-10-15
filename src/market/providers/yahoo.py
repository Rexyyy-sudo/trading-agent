"""Yahoo Finance chart provider (public endpoint, no API key).

Endpoint: GET https://query1.finance.yahoo.com/v8/finance/chart/{symbol}

Notes / limitations:
  - H4 is served by fetching H1 and resampling locally (labelled).
  - Yahoo FX/metals data can be thin on low timeframes and has no
    reliable volume; the framework reports volume as unavailable.
  - USDT pairs are approximated with the USD pair and clearly labelled.
"""

from __future__ import annotations

from datetime import UTC, datetime

import requests

from src.market.candles import CandleSeries, resample_series
from src.market.data_provider import Availability, MarketDataProvider
from src.market.symbols import SymbolInfo
from src.market.timeframes import normalize_timeframe
from src.utils.errors import ProviderError
from src.utils.logging import get_logger

logger = get_logger("provider.yahoo")

# timeframe -> (yahoo interval, range). H4 handled via resampling.
_INTERVALS = {
    "M1": ("1m", "7d"),
    "M5": ("5m", "60d"),
    "M15": ("15m", "60d"),
    "M30": ("30m", "60d"),
    "H1": ("60m", "730d"),
    "D1": ("1d", "5y"),
    "W1": ("1wk", "10y"),
}

_CRYPTO_QUOTES = {"USDT": "USD", "USDC": "USD", "BUSD": "USD", "FDUSD": "USD", "TUSD": "USD"}

# Yahoo no longer serves spot metal pairs (e.g. XAUUSD=X returned 404 as of
# 2026). These futures links are used ONLY as a clearly-labelled fallback.
_FUTURES_FALLBACK = {
    "XAU": ("GC=F", "Yahoo GC=F (COMEX gold futures) used as proxy for XAUUSD - not spot"),
    "XAG": ("SI=F", "Yahoo SI=F (COMEX silver futures) used as proxy for XAGUSD - not spot"),
}


class YahooProvider(MarketDataProvider):
    name = "yahoo"
    display_name = "Yahoo Finance"
    base_url = "https://query1.finance.yahoo.com/v8/finance/chart"

    def availability(self) -> Availability:
        return Availability(True, "public endpoint (no key required)")

    def supports_symbol(self, info: SymbolInfo) -> bool:
        return info.asset_class in ("forex", "metal", "crypto", "index")

    def map_symbol(self, info: SymbolInfo) -> tuple[str | None, str | None]:
        if info.asset_class in ("forex", "metal"):
            return f"{info.base}{info.quote}=X", None
        if info.asset_class == "crypto":
            quote = _CRYPTO_QUOTES.get(info.quote, info.quote)
            note = None
            if quote != info.quote:
                note = (
                    f"Yahoo {info.base}-{quote} used as proxy for {info.symbol} "
                    "(stablecoins are not USD)"
                )
            return f"{info.base}-{quote}", note
        if info.symbol == "USOIL":
            return "CL=F", "Yahoo CL=F (WTI futures) used as proxy for USOIL"
        if info.symbol == "UKOIL":
            return "BZ=F", "Yahoo BZ=F (Brent futures) used as proxy for UKOIL"
        return None, None

    def fetch_ohlcv(self, info: SymbolInfo, timeframe: str, limit: int) -> CandleSeries:
        tf = normalize_timeframe(timeframe)
        provider_symbol, note = self.map_symbol(info)
        if provider_symbol is None:
            raise ProviderError(f"yahoo cannot serve {info.symbol}")

        resampled_note = None
        fetch_tf = tf
        if tf == "H4":
            fetch_tf = "H1"
            resampled_note = "H4 built locally by resampling Yahoo H1 candles"

        yahoo_interval, yahoo_range = _INTERVALS[fetch_tf]
        params = {
            "interval": yahoo_interval,
            "range": yahoo_range,
            "includePrePost": "false",
            "events": "div,splits",
        }
        candidates = [(provider_symbol, note)]
        fallback = (
            _FUTURES_FALLBACK.get(info.base) if info.asset_class == "metal" else None
        )
        if fallback and fallback[0] != provider_symbol:
            candidates.append(fallback)

        response = None
        for index, (candidate_symbol, candidate_note) in enumerate(candidates):
            try:
                response = requests.get(
                    f"{self.base_url}/{candidate_symbol}",
                    params=params,
                    timeout=self.timeout,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (X11; Linux x86_64) trading-agent/0.1 "
                            "(educational analysis tool)"
                        )
                    },
                )
            except requests.RequestException as exc:
                raise ProviderError(f"yahoo request failed: {exc}") from exc
            if response.status_code == 404 and index < len(candidates) - 1:
                continue
            provider_symbol, note = candidate_symbol, candidate_note
            break
        if response.status_code == 404:
            raise ProviderError(
                f"yahoo has no data for {provider_symbol} ({info.symbol})"
            )
        if response.status_code != 200:
            raise ProviderError(f"yahoo HTTP {response.status_code} for {provider_symbol}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise ProviderError("yahoo returned invalid JSON") from exc

        chart = (payload or {}).get("chart") or {}
        if chart.get("error"):
            raise ProviderError(f"yahoo error: {chart['error']}")
        results = chart.get("result") or []
        if not results:
            raise ProviderError(f"yahoo returned no result for {provider_symbol}")
        result = results[0]
        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []

        rows = []
        for index, timestamp in enumerate(timestamps):
            try:
                open_value = opens[index]
                high_value = highs[index]
                low_value = lows[index]
                close_value = closes[index]
            except IndexError:
                continue
            if None in (open_value, high_value, low_value, close_value):
                continue
            volume = None
            if index < len(volumes) and volumes[index] is not None:
                try:
                    volume = float(volumes[index])
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
            raise ProviderError(
                f"yahoo returned no usable candles for {provider_symbol} "
                f"(interval {yahoo_interval})"
            )

        notes = [f"source symbol: {provider_symbol}"]
        if note:
            notes.append(note)
        if resampled_note:
            notes.append(resampled_note)

        series = CandleSeries.from_rows(
            symbol=info.symbol,
            timeframe=fetch_tf,
            source=f"yahoo:{provider_symbol}",
            rows=rows,
            metadata={
                "live": True,
                "provider_symbol": provider_symbol,
                "fetched_at": datetime.now(UTC).isoformat(),
                "provider_notes": notes,
            },
        )
        if limit and len(series) > limit:
            series.candles = series.candles[-int(limit):]
        if fetch_tf != tf:
            series = resample_series(series, tf)
        return series
