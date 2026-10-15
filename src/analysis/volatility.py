"""Volatility classification via ATR relative to its own recent baseline.

Classifies current volatility as LOW / NORMAL / HIGH / EXTREME by
comparing the latest ATR to the median ATR of the recent lookback
window, and warns on extreme readings.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.analysis.indicators import atr, last_value
from src.analysis.types import VolatilityClass
from src.utils.config import AnalysisConfig


@dataclass
class VolatilityResult:
    classification: VolatilityClass
    atr: float | None = None
    atr_percent: float | None = None
    ratio: float | None = None
    warning: bool = False
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "classification": self.classification.value,
            "atr": round(self.atr, 6) if self.atr is not None else None,
            "atr_percent": (
                round(self.atr_percent, 3) if self.atr_percent is not None else None
            ),
            "atr_ratio": round(self.ratio, 3) if self.ratio is not None else None,
            "warning": self.warning,
            "notes": self.notes,
        }


def analyze_volatility(frame: pd.DataFrame, config: AnalysisConfig) -> VolatilityResult:
    if frame.empty or len(frame) < config.atr_period + 20:
        return VolatilityResult(
            classification=VolatilityClass.INSUFFICIENT_DATA,
            notes=[
                f"need >= {config.atr_period + 20} candles for volatility analysis"
            ],
        )

    atr_series = atr(frame, config.atr_period)
    atr_value = last_value(atr_series)
    price = float(frame["close"].iloc[-1])
    if atr_value is None or atr_value <= 0 or price <= 0:
        return VolatilityResult(
            classification=VolatilityClass.INSUFFICIENT_DATA,
            notes=["ATR could not be computed"],
        )

    window = atr_series.dropna().tail(config.volatility_lookback)
    ratio: float | None = None
    if window.size >= 20:
        median = float(window.median())
        if median > 0:
            ratio = atr_value / median
    atr_percent = atr_value / price * 100.0
    notes: list[str] = []
    warning = False

    if ratio is None:
        classification = VolatilityClass.NORMAL
        notes.append("not enough ATR history for a baseline - assumed NORMAL")
    elif ratio < config.volatility_low_ratio:
        classification = VolatilityClass.LOW
        notes.append("volatility is low relative to recent history")
    elif ratio < config.volatility_high_ratio:
        classification = VolatilityClass.NORMAL
    elif ratio < config.volatility_extreme_ratio:
        classification = VolatilityClass.HIGH
        notes.append("volatility is elevated - wider stops may be required")
    else:
        classification = VolatilityClass.EXTREME
        notes.append("volatility is extreme - avoid new entries until it settles")
        warning = True

    bar_range = float((frame["high"] - frame["low"]).iloc[-1])
    if bar_range > atr_value * 3:
        notes.append(
            f"current candle range ({bar_range:.5f}) is over 3x ATR - possible news spike"
        )
        warning = True
        if classification in (VolatilityClass.LOW, VolatilityClass.NORMAL):
            classification = VolatilityClass.HIGH

    return VolatilityResult(
        classification=classification,
        atr=atr_value,
        atr_percent=atr_percent,
        ratio=ratio,
        warning=warning,
        notes=notes,
    )
