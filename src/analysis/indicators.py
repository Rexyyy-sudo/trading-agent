"""Lightweight technical indicators (pure pandas/numpy - no TA-Lib).

Indicators are SUPPORTING evidence only. The framework prioritises
market structure, price action and liquidity first.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def true_range(frame: pd.DataFrame) -> pd.Series:
    high = frame["high"]
    low = frame["low"]
    previous_close = frame["close"].shift(1)
    ranges = pd.concat(
        [
            high - low,
            (high - previous_close).abs(),
            (low - previous_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder's Average True Range."""
    return true_range(frame).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder's Relative Strength Index."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    average_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    average_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = average_gain / average_loss.replace(0.0, np.nan)
    values = 100.0 - (100.0 / (1.0 + rs))
    values = values.where(average_loss != 0.0, 100.0)
    values = values.where(~((average_gain == 0.0) & (average_loss == 0.0)), 50.0)
    return values


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    histogram = macd_line - signal_line
    return pd.DataFrame({"macd": macd_line, "signal": signal_line, "histogram": histogram})


def bollinger(close: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    middle = sma(close, period)
    deviation = close.rolling(window=period, min_periods=period).std(ddof=0)
    upper = middle + num_std * deviation
    lower = middle - num_std * deviation
    width = (upper - lower) / middle.replace(0.0, np.nan)
    percent_b = (close - lower) / (upper - lower).replace(0.0, np.nan)
    return pd.DataFrame(
        {
            "middle": middle,
            "upper": upper,
            "lower": lower,
            "bandwidth": width,
            "percent_b": percent_b,
        }
    )


def candle_body(frame: pd.DataFrame) -> pd.Series:
    return (frame["close"] - frame["open"]).abs()


def body_ratio(frame: pd.DataFrame) -> pd.Series:
    span = (frame["high"] - frame["low"]).replace(0.0, np.nan)
    return (frame["close"] - frame["open"]).abs() / span


def slope(series: pd.Series, period: int = 14) -> float | None:
    """Least-squares slope of the last `period` non-NaN values."""
    values = series.dropna().to_numpy(dtype=float)
    if values.size < 2:
        return None
    values = values[-period:] if values.size > period else values
    x = np.arange(values.size, dtype=float)
    x_centered = x - x.mean()
    denominator = float((x_centered**2).sum())
    if denominator == 0:
        return None
    return float((x_centered * (values - values.mean())).sum() / denominator)


def rolling_percentile(series: pd.Series, window: int = 200) -> float | None:
    """Percentile rank (0-100) of the latest value within the window."""
    values = series.dropna().tail(window)
    if values.size < 20:
        return None
    latest = values.iloc[-1]
    return float((values < latest).mean() * 100.0)


def last_value(series: pd.Series) -> float | None:
    if series is None or series.empty:
        return None
    value = series.dropna().tail(1)
    if value.empty:
        return None
    return float(value.iloc[0])


def crossover(fast: pd.Series, slow: pd.Series) -> pd.Series:
    return (fast > slow) & (fast.shift(1) <= slow.shift(1))


def crossunder(fast: pd.Series, slow: pd.Series) -> pd.Series:
    return (fast < slow) & (fast.shift(1) >= slow.shift(1))
