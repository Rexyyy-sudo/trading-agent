"""Shared test helpers: deterministic SYNTHETIC series (test fixtures only).

These series are clearly synthetic and are used only inside the test
suite. The application itself never fabricates market data.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from src.market.candles import Candle, CandleSeries

BASE_TIME = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)

_TF_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}


def ramp(start: float, end: float, bars: int) -> list[float]:
    if bars <= 1:
        return [end]
    return [start + (end - start) * index / (bars - 1) for index in range(bars)]


def zigzag_closes(points: list[float], leg: int = 5) -> list[float]:
    closes = [points[0]]
    for start, end in zip(points, points[1:], strict=False):
        closes.extend(ramp(start, end, leg + 1)[1:])
    return closes


def make_series(
    closes: list[float],
    symbol: str = "TESTUSD",
    timeframe: str = "M5",
    volume: float | None = 100.0,
    volumes: list[float] | None = None,
    wick: float = 0.2,
    start_time: datetime | None = None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> CandleSeries:
    """Build a CandleSeries from closes (open = previous close)."""
    spacing = _TF_MINUTES.get(timeframe, 5)
    start = start_time or BASE_TIME
    candles: list[Candle] = []
    for index, close in enumerate(closes):
        open_ = closes[index - 1] if index else close
        high = max(open_, close) + wick
        low = min(open_, close) - wick
        if highs is not None:
            high = max(high, highs[index])
        if lows is not None:
            low = min(low, lows[index])
        if volumes is not None:
            bar_volume = volumes[index]
        else:
            bar_volume = volume
        candles.append(
            Candle(
                time=start + timedelta(minutes=spacing * index),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=bar_volume,
            )
        )
    return CandleSeries(symbol=symbol, timeframe=timeframe, source="test", candles=candles)


def uptrend_series(bars: int = 260, start: float = 100.0, step: float = 0.1) -> CandleSeries:
    return make_series([start + step * index for index in range(bars)])


def downtrend_series(bars: int = 260, start: float = 130.0, step: float = 0.1) -> CandleSeries:
    return make_series([start - step * index for index in range(bars)])


def flat_series(bars: int = 260, price: float = 100.0) -> CandleSeries:
    return make_series([price] * bars)
