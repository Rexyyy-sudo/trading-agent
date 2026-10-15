"""Momentum analysis: RSI, MACD, candle displacement, range expansion."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.analysis.indicators import atr, last_value, macd, rsi, slope
from src.analysis.types import MomentumState
from src.utils.config import AnalysisConfig
from src.utils.validation import clamp


@dataclass
class MomentumResult:
    state: MomentumState
    score: float  # -1..1
    confidence: float  # 0..1
    rsi: float | None = None
    rsi_slope: float | None = None
    macd_histogram: float | None = None
    macd_histogram_change: float | None = None
    displacement_atr: float | None = None
    range_expansion: float | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "state": self.state.value,
            "score": round(self.score, 3),
            "confidence": round(self.confidence, 3),
            "rsi": round(self.rsi, 2) if self.rsi is not None else None,
            "macd_histogram": (
                round(self.macd_histogram, 6) if self.macd_histogram is not None else None
            ),
            "displacement_atr": (
                round(self.displacement_atr, 3)
                if self.displacement_atr is not None
                else None
            ),
            "range_expansion": (
                round(self.range_expansion, 3)
                if self.range_expansion is not None
                else None
            ),
            "notes": self.notes,
        }


def analyze_momentum(frame: pd.DataFrame, config: AnalysisConfig) -> MomentumResult:
    minimum = max(config.macd_slow + config.macd_signal, config.rsi_period, config.atr_period) + 5
    if frame.empty or len(frame) < minimum:
        return MomentumResult(
            state=MomentumState.INSUFFICIENT_DATA,
            score=0.0,
            confidence=0.0,
            notes=[f"need >= {minimum} candles for momentum analysis"],
        )

    close = frame["close"]
    atr_series = atr(frame, config.atr_period)
    atr_value = last_value(atr_series)
    rsi_series = rsi(close, config.rsi_period)
    macd_frame = macd(close, config.macd_fast, config.macd_slow, config.macd_signal)

    rsi_value = last_value(rsi_series)
    rsi_gradient = slope(rsi_series, 5)
    histogram = macd_frame["histogram"]
    hist_value = last_value(histogram)
    hist_previous = last_value(histogram.iloc[:-1]) if len(histogram) > 1 else None
    hist_change = (
        hist_value - hist_previous
        if hist_value is not None and hist_previous is not None
        else None
    )

    contributions: list[tuple[float, float]] = []  # (weight, value in -1..1)

    if rsi_value is not None:
        contributions.append((0.25, clamp((rsi_value - 50.0) / 25.0, -1.0, 1.0)))
    if rsi_gradient is not None:
        contributions.append((0.15, clamp(rsi_gradient / 2.0, -1.0, 1.0)))
    if hist_value is not None:
        scale = atr_value * 0.1 if atr_value else abs(hist_value) or 1.0
        contributions.append((0.25, clamp(hist_value / scale, -1.0, 1.0)))
    if hist_change is not None:
        if atr_value:
            contributions.append((0.15, clamp(hist_change / (atr_value * 0.1), -1.0, 1.0)))
        else:
            contributions.append(
                (0.15, 1.0 if hist_change > 0 else -1.0 if hist_change < 0 else 0.0)
            )

    displacement = None
    if atr_value and atr_value > 0 and len(frame) >= 4:
        recent_bodies = (frame["close"] - frame["open"]).tail(3)
        displacement = float(recent_bodies.abs().mean() / atr_value)
        direction = 1.0 if close.iloc[-1] >= close.iloc[-4] else -1.0
        contributions.append((0.2, direction * clamp(displacement / 0.8, 0.0, 1.0)))

    range_expansion = None
    if len(frame) >= 25:
        ranges = (frame["high"] - frame["low"])
        recent = float(ranges.tail(5).mean())
        baseline = float(ranges.tail(20).mean())
        if baseline > 0:
            range_expansion = recent / baseline

    if not contributions:
        return MomentumResult(
            state=MomentumState.INSUFFICIENT_DATA,
            score=0.0,
            confidence=0.0,
            notes=["momentum indicators unavailable"],
        )

    total_weight = sum(weight for weight, _ in contributions)
    score = sum(weight * value for weight, value in contributions) / total_weight
    if score >= 0.25:
        state = MomentumState.BULLISH
    elif score <= -0.25:
        state = MomentumState.BEARISH
    else:
        state = MomentumState.NEUTRAL

    confidence = clamp(0.5 + 0.45 * abs(score), 0.0, 0.9)
    notes: list[str] = []
    if rsi_value is not None and rsi_value > 70:
        notes.append(f"RSI {rsi_value:.1f} is overbought - chasing is risky")
    if rsi_value is not None and rsi_value < 30:
        notes.append(f"RSI {rsi_value:.1f} is oversold - chasing is risky")
    if range_expansion is not None and range_expansion > 1.8:
        notes.append(f"recent range is {range_expansion:.1f}x the 20-bar average")
    if displacement is not None and displacement < 0.25:
        notes.append("candle bodies are small relative to ATR (weak momentum)")

    return MomentumResult(
        state=state,
        score=round(score, 3),
        confidence=round(confidence, 3),
        rsi=rsi_value,
        rsi_slope=rsi_gradient,
        macd_histogram=hist_value,
        macd_histogram_change=hist_change,
        displacement_atr=displacement,
        range_expansion=range_expansion,
        notes=notes,
    )
