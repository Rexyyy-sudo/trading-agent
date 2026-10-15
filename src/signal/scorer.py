"""Transparent weighted scoring engine.

Each component contributes a signed direction (-1..1), a strength and a
data-quality factor. Components with no usable data are EXCLUDED from
the denominator instead of being faked.

The score is 0-100 with a bias direction. It is NOT a probability of
profit and must never be presented as one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.analysis.liquidity import LiquidityResult
from src.analysis.momentum import MomentumResult
from src.analysis.multi_timeframe import MTFResult
from src.analysis.structure import StructureResult
from src.analysis.support_resistance import SRResult
from src.analysis.trend import TrendResult
from src.analysis.types import (
    Direction,
    MomentumState,
    VolatilityClass,
    VolumeState,
)
from src.analysis.volatility import VolatilityResult
from src.analysis.volume import VolumeResult
from src.utils.config import ScoringConfig
from src.utils.validation import clamp

WEAK = "WEAK"
MIXED = "MIXED"
MODERATE = "MODERATE"
STRONG = "STRONG"
VERY_STRONG = "VERY STRONG"


@dataclass
class ScoreComponent:
    name: str
    direction: int  # -1 | 0 | +1
    strength: float  # 0..1
    quality: float  # 0..1 (0 = excluded / no data)
    note: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "direction": self.direction,
            "strength": round(self.strength, 3),
            "quality": round(self.quality, 3),
            "note": self.note,
        }


@dataclass
class ScoreResult:
    signed_score: float  # -100..100
    score: float  # 0..100 (abs)
    label: str
    bias: Direction
    confidence: float  # 0..1
    components: list[ScoreComponent] = field(default_factory=list)
    mtf_multiplier: float = 1.0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "score": round(self.score, 1),
            "signed_score": round(self.signed_score, 1),
            "label": self.label,
            "bias": self.bias.value,
            "confidence": round(self.confidence, 3),
            "mtf_multiplier": round(self.mtf_multiplier, 3),
            "components": [component.as_dict() for component in self.components],
            "notes": self.notes,
        }


def label_for(score: float, thresholds: list[int]) -> str:
    weak, mixed, moderate, strong = thresholds
    if score < weak:
        return WEAK
    if score < mixed:
        return MIXED
    if score < moderate:
        return MODERATE
    if score < strong:
        return STRONG
    return VERY_STRONG


def _structure_component(structure: StructureResult) -> ScoreComponent:
    if structure.trend is Direction.INSUFFICIENT_DATA:
        return ScoreComponent("structure", 0, 0.0, 0.0, "insufficient data")
    direction = structure.trend.sign
    note = f"{structure.label}, BOS={structure.bos}"
    if structure.choch != "NONE":
        note += f", CHoCH={structure.choch}"
    return ScoreComponent("structure", direction, structure.confidence, 1.0, note)


def _trend_component(trend: TrendResult) -> ScoreComponent:
    if trend.state is Direction.INSUFFICIENT_DATA:
        return ScoreComponent("trend", 0, 0.0, 0.0, "insufficient data")
    return ScoreComponent(
        "trend", trend.state.sign, trend.strength, trend.confidence, trend.state.value
    )


def _momentum_component(momentum: MomentumResult) -> ScoreComponent:
    if momentum.state is MomentumState.INSUFFICIENT_DATA:
        return ScoreComponent("momentum", 0, 0.0, 0.0, "insufficient data")
    direction = 1 if momentum.score > 0 else -1 if momentum.score < 0 else 0
    strength = clamp(abs(momentum.score) * 1.2, 0.0, 1.0)
    return ScoreComponent(
        "momentum", direction, strength, momentum.confidence, momentum.state.value
    )


def _liquidity_component(liquidity: LiquidityResult) -> ScoreComponent:
    if liquidity.last_sweep is not None:
        direction = liquidity.last_sweep.sign
        return ScoreComponent(
            "liquidity",
            direction,
            0.6,
            0.8,
            f"potential {liquidity.last_sweep.value.lower()} sweep detected",
        )
    if liquidity.pools:
        return ScoreComponent(
            "liquidity", 0, 0.0, 0.5, "pools mapped, no recent sweep"
        )
    return ScoreComponent("liquidity", 0, 0.0, 0.0, "no liquidity context")


def _sr_component(sr: SRResult) -> ScoreComponent:
    price = sr.current_price
    atr_value = sr.atr
    if price is None:
        return ScoreComponent("support_resistance", 0, 0.0, 0.0, "no price")
    fallback = (atr_value or price * 0.002) * 4
    distance_up = (
        sr.nearest_resistance.lower - price if sr.nearest_resistance else fallback
    )
    distance_down = price - sr.nearest_support.upper if sr.nearest_support else fallback
    total = distance_up + distance_down
    if total <= 0:
        return ScoreComponent("support_resistance", 0, 0.0, 0.5, "levels unclear")
    ratio = (distance_up - distance_down) / total
    direction = 0
    if ratio >= 0.15:
        direction = 1
    elif ratio <= -0.15:
        direction = -1
    note = (
        f"room up {distance_up:.5f} / down {distance_down:.5f}"
        if distance_up and distance_down
        else "limited level context"
    )
    return ScoreComponent(
        "support_resistance", direction, clamp(abs(ratio) * 1.5, 0.0, 1.0), 0.9, note
    )


def _volatility_component(volatility: VolatilityResult) -> ScoreComponent:
    quality_map = {
        VolatilityClass.NORMAL: 1.0,
        VolatilityClass.LOW: 0.7,
        VolatilityClass.HIGH: 0.6,
        VolatilityClass.EXTREME: 0.15,
        VolatilityClass.INSUFFICIENT_DATA: 0.0,
    }
    quality = quality_map.get(volatility.classification, 0.5)
    note = volatility.classification.value
    if volatility.warning:
        note += " (warning)"
    return ScoreComponent("volatility", 0, 0.0, quality, note)


def _volume_component(volume: VolumeResult) -> ScoreComponent:
    if volume.state is VolumeState.INSUFFICIENT_DATA:
        return ScoreComponent("volume", 0, 0.0, 0.0, "no volume data")
    if volume.state is VolumeState.CONFIRMING and volume.direction_sign != 0:
        return ScoreComponent(
            "volume", volume.direction_sign, 0.5, 0.8, "volume confirms the move"
        )
    if volume.state is VolumeState.DIVERGENT:
        return ScoreComponent("volume", 0, 0.0, 0.5, "move lacks volume")
    return ScoreComponent("volume", 0, 0.0, 0.6, "volume neutral")


def score_setup(
    trend: TrendResult,
    structure: StructureResult,
    momentum: MomentumResult,
    liquidity: LiquidityResult,
    sr: SRResult,
    volatility: VolatilityResult,
    volume: VolumeResult,
    mtf: MTFResult,
    config: ScoringConfig,
    news_quality: float = 1.0,
) -> ScoreResult:
    components = [
        _structure_component(structure),
        _liquidity_component(liquidity),
        _momentum_component(momentum),
        _trend_component(trend),
        _sr_component(sr),
        _volatility_component(volatility),
        _volume_component(volume),
    ]
    by_name = {component.name: component for component in components}
    weights = config.weights
    notes: list[str] = []

    numerator = 0.0
    denominator = 0.0
    excluded: list[str] = []
    for name, weight in weights.items():
        component = by_name.get(name)
        if component is None:
            continue
        if component.quality <= 0.0:
            excluded.append(name)
            continue
        quality = component.quality
        if name == "volatility":
            quality *= news_quality
        effective = weight * quality
        denominator += effective
        numerator += effective * component.direction * component.strength

    if denominator <= 0:
        return ScoreResult(
            signed_score=0.0,
            score=0.0,
            label=WEAK,
            bias=Direction.NEUTRAL,
            confidence=0.0,
            components=components,
            mtf_multiplier=mtf.multiplier,
            notes=["no component had sufficient data"],
        )

    raw = (numerator / denominator) * 100.0
    adjusted = clamp(raw * mtf.multiplier, -100.0, 100.0)
    score = abs(adjusted)
    if adjusted >= 15:
        bias = Direction.BULLISH
    elif adjusted <= -15:
        bias = Direction.BEARISH
    else:
        bias = Direction.NEUTRAL

    total_weight = sum(weights.values()) or 1.0
    quality_score = (
        sum(
            weights.get(component.name, 0.0) * component.quality
            for component in components
        )
        / total_weight
    )
    alignment_factor = clamp(mtf.multiplier / 1.15, 0.35, 1.0)
    confidence = clamp(quality_score * alignment_factor, 0.05, 0.95)

    if excluded:
        notes.append(
            "components excluded (insufficient data): " + ", ".join(excluded)
        )
        if "volume" in excluded:
            notes.append("volume weight redistributed to the remaining components")
    if mtf.multiplier < 1.0:
        notes.append(f"multi-timeframe adjustment applied (x{mtf.multiplier:.2f})")
    if abs(raw) > 100:
        notes.append("raw score exceeded +/-100 before adjustment - treat with caution")

    return ScoreResult(
        signed_score=round(adjusted, 2),
        score=round(score, 1),
        label=label_for(score, config.label_thresholds),
        bias=bias,
        confidence=round(confidence, 3),
        components=components,
        mtf_multiplier=mtf.multiplier,
        notes=notes,
    )
