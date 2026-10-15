"""Trend analysis: EMA alignment + slope, as supporting evidence."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.analysis.indicators import atr, ema, last_value, slope
from src.analysis.types import Direction
from src.utils.config import AnalysisConfig
from src.utils.validation import clamp


@dataclass
class TrendResult:
    state: Direction
    strength: float  # 0..1
    confidence: float  # 0..1
    details: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "state": self.state.value,
            "strength": round(self.strength, 3),
            "confidence": round(self.confidence, 3),
            "details": self.details,
            "notes": self.notes,
        }


def _direction_vote(value: float, reference: float) -> float:
    epsilon = 1e-9 * max(1.0, abs(reference))
    if abs(value - reference) <= epsilon:
        return 0.0
    return 1.0 if value > reference else -1.0


def analyze_trend(frame: pd.DataFrame, config: AnalysisConfig) -> TrendResult:
    notes: list[str] = []
    details: dict = {}
    if frame.empty or len(frame) < max(config.ema_fast, config.atr_period) + 2:
        return TrendResult(
            state=Direction.INSUFFICIENT_DATA,
            strength=0.0,
            confidence=0.0,
            notes=[f"not enough candles for trend analysis (need >= {config.ema_fast + 2})"],
        )

    close = frame["close"]
    price = float(close.iloc[-1])
    atr_value = last_value(atr(frame, config.atr_period))
    fast = ema(close, config.ema_fast)
    slow = ema(close, config.ema_slow)
    trend_ema = ema(close, config.ema_trend) if len(frame) >= config.ema_trend else None

    fast_value = last_value(fast)
    slow_value = last_value(slow)
    trend_value = last_value(trend_ema) if trend_ema is not None else None
    slow_slope = slope(slow, min(20, config.ema_slow))

    details.update(
        {
            "price": round(price, 6),
            "ema_fast": round(fast_value, 6) if fast_value else None,
            "ema_slow": round(slow_value, 6) if slow_value else None,
            "ema_trend": round(trend_value, 6) if trend_value else None,
            "ema_slow_slope": round(slow_slope, 6) if slow_slope is not None else None,
        }
    )

    votes: list[float] = []
    weights: list[float] = []

    if fast_value is not None:
        votes.append(_direction_vote(price, fast_value))
        weights.append(1.0)
    if fast_value is not None and slow_value is not None:
        votes.append(_direction_vote(fast_value, slow_value))
        weights.append(1.2)
    if slow_slope is not None and atr_value:
        normalized = slow_slope / atr_value
        if abs(normalized) < 0.02:
            votes.append(0.0)
        else:
            votes.append(clamp(normalized * 4.0, -1.0, 1.0))
        weights.append(1.0)
    if trend_value is not None:
        votes.append(_direction_vote(price, trend_value))
        weights.append(0.8)
        notes.append(f"EMA{config.ema_trend} available and used")

    if not votes or sum(weights) == 0:
        return TrendResult(
            state=Direction.INSUFFICIENT_DATA,
            strength=0.0,
            confidence=0.0,
            details=details,
            notes=["trend indicators unavailable"],
        )

    score = sum(v * w for v, w in zip(votes, weights, strict=True)) / sum(weights)
    strength = abs(score)
    if score >= 0.35:
        state = Direction.BULLISH
    elif score <= -0.35:
        state = Direction.BEARISH
    else:
        state = Direction.RANGING

    data_quality = 1.0 if trend_value is not None else 0.75
    confidence = clamp(0.45 + 0.5 * strength, 0.0, 0.95) * data_quality
    if state is Direction.RANGING:
        notes.append("EMA structure is mixed - no clear trend")

    return TrendResult(
        state=state,
        strength=round(strength, 3),
        confidence=round(confidence, 3),
        details=details,
        notes=notes,
    )
