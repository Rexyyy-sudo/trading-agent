"""Shared analysis types (enums used by every analysis module)."""

from __future__ import annotations

from enum import StrEnum


class Direction(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    RANGING = "RANGING"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

    @classmethod
    def from_score(cls, score: float, threshold: float = 0.25) -> Direction:
        if score >= threshold:
            return cls.BULLISH
        if score <= -threshold:
            return cls.BEARISH
        return cls.NEUTRAL

    @property
    def sign(self) -> int:
        if self is Direction.BULLISH:
            return 1
        if self is Direction.BEARISH:
            return -1
        return 0


class MomentumState(StrEnum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class VolatilityClass(StrEnum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    EXTREME = "EXTREME"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class VolumeState(StrEnum):
    CONFIRMING = "CONFIRMING"
    DIVERGENT = "DIVERGENT"
    NEUTRAL = "NEUTRAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
