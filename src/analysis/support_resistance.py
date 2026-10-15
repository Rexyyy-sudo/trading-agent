"""Support / resistance zone detection.

Swing levels are clustered into ZONES (not exact prices) using an
ATR-scaled tolerance. A zone is a *potential* area of interest.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.analysis.structure import SwingPoint
from src.utils.config import AnalysisConfig
from src.utils.validation import clamp


@dataclass
class Zone:
    lower: float
    upper: float
    touches: int
    strength: float  # 0..1
    last_touch_index: int
    kind: str  # SUPPORT | RESISTANCE

    @property
    def center(self) -> float:
        return (self.lower + self.upper) / 2

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "lower": round(self.lower, 6),
            "upper": round(self.upper, 6),
            "touches": self.touches,
            "strength": round(self.strength, 3),
        }


@dataclass
class SRResult:
    supports: list[Zone] = field(default_factory=list)
    resistances: list[Zone] = field(default_factory=list)
    nearest_support: Zone | None = None
    nearest_resistance: Zone | None = None
    current_price: float | None = None
    atr: float | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "supports": [z.as_dict() for z in self.supports],
            "resistances": [z.as_dict() for z in self.resistances],
            "nearest_support": self.nearest_support.as_dict() if self.nearest_support else None,
            "nearest_resistance": (
                self.nearest_resistance.as_dict() if self.nearest_resistance else None
            ),
            "notes": self.notes,
        }


def _cluster_levels(
    levels: list[tuple[float, int]], tolerance: float
) -> list[list[tuple[float, int]]]:
    if not levels:
        return []
    ordered = sorted(levels, key=lambda item: item[0])
    clusters: list[list[tuple[float, int]]] = [[ordered[0]]]
    for price, index in ordered[1:]:
        if price - clusters[-1][-1][0] <= tolerance:
            clusters[-1].append((price, index))
        else:
            clusters.append([(price, index)])
    return clusters


def analyze_sr(
    frame: pd.DataFrame,
    swings: list[SwingPoint],
    atr_value: float | None,
    config: AnalysisConfig,
) -> SRResult:
    result = SRResult(atr=atr_value)
    if frame.empty:
        result.notes.append("no candles available for support/resistance")
        return result
    price = float(frame["close"].iloc[-1])
    result.current_price = price
    if not swings:
        result.notes.append("no swing points available for zone detection")
        return result

    if not atr_value or atr_value <= 0:
        atr_value = price * 0.002
        result.notes.append("ATR unavailable - using 0.2% of price as zone tolerance")

    tolerance = atr_value * config.sr_cluster_tolerance_atr
    levels = [(swing.price, swing.index) for swing in swings]
    clusters = _cluster_levels(levels, tolerance)
    total_bars = len(frame)

    zones: list[Zone] = []
    for cluster in clusters:
        prices = [price_ for price_, _ in cluster]
        last_index = max(index for _, index in cluster)
        lower, upper = min(prices), max(prices)
        minimum_width = atr_value * 0.2
        if upper - lower < minimum_width:
            center = (lower + upper) / 2
            lower, upper = center - minimum_width / 2, center + minimum_width / 2
        touches = len(cluster)
        recency = 1.0 if total_bars <= 1 else last_index / (total_bars - 1)
        strength = clamp(0.35 + 0.15 * (touches - 1) + 0.35 * recency, 0.0, 1.0)
        zones.append(
            Zone(
                lower=lower,
                upper=upper,
                touches=touches,
                strength=strength,
                last_touch_index=last_index,
                kind="SUPPORT" if (lower + upper) / 2 < price else "RESISTANCE",
            )
        )

    for zone in zones:
        if zone.upper < price:
            zone.kind = "SUPPORT"
        elif zone.lower > price:
            zone.kind = "RESISTANCE"
        elif zone.center < price:
            zone.kind = "SUPPORT"
            result.notes.append(
                f"price is inside the {zone.lower:.5f}-{zone.upper:.5f} zone (treated as support)"
            )
        else:
            zone.kind = "RESISTANCE"
            result.notes.append(
                f"price is inside the {zone.lower:.5f}-{zone.upper:.5f} zone (treated as resistance)"
            )

    supports = [zone for zone in zones if zone.kind == "SUPPORT"]
    resistances = [zone for zone in zones if zone.kind == "RESISTANCE"]
    supports.sort(key=lambda zone: (-zone.strength, -zone.upper))
    resistances.sort(key=lambda zone: (-zone.strength, zone.lower))
    result.supports = supports[: config.sr_max_zones_per_side]
    result.resistances = resistances[: config.sr_max_zones_per_side]

    if result.supports:
        result.nearest_support = max(result.supports, key=lambda zone: zone.upper)
    if result.resistances:
        result.nearest_resistance = min(result.resistances, key=lambda zone: zone.lower)
    if not result.supports:
        result.notes.append("no support zones detected below price")
    if not result.resistances:
        result.notes.append("no resistance zones detected above price")
    return result
