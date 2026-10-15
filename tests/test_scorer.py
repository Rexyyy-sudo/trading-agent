"""Scoring engine tests."""

from __future__ import annotations

import pytest

from src.analysis.liquidity import LiquidityResult
from src.analysis.momentum import MomentumResult
from src.analysis.multi_timeframe import MTFResult, TFAssessment
from src.analysis.structure import StructureResult
from src.analysis.support_resistance import SRResult, Zone
from src.analysis.trend import TrendResult
from src.analysis.types import (
    Direction,
    MomentumState,
    VolatilityClass,
    VolumeState,
)
from src.analysis.volatility import VolatilityResult
from src.analysis.volume import VolumeResult
from src.signal.scorer import label_for, score_setup
from src.utils.config import ScoringConfig


def _mtf(alignment="ALIGNED_BULLISH", multiplier=1.15, bullish=3, bearish=0):
    assessments = [
        TFAssessment("H1", "htf", Direction.BULLISH, Direction.BULLISH, MomentumState.BULLISH),
        TFAssessment("M15", "mtf", Direction.BULLISH, Direction.BULLISH, MomentumState.BULLISH),
        TFAssessment("M5", "ltf", Direction.BULLISH, Direction.BULLISH, MomentumState.BULLISH),
    ]
    return MTFResult(
        alignment=alignment,
        bullish_count=bullish,
        bearish_count=bearish,
        required=2,
        htf_bias=Direction.BULLISH if alignment != "ALIGNED_BEARISH" else Direction.BEARISH,
        multiplier=multiplier,
        assessments=assessments,
    )


def _zone(lower, upper, kind="SUPPORT"):
    return Zone(lower, upper, 2, 0.8, 50, kind)


def _bundle(direction="BULLISH", volume_state=VolumeState.CONFIRMING):
    bullish = direction == "BULLISH"
    trend_dir = Direction.BULLISH if bullish else Direction.BEARISH
    trend = TrendResult(state=trend_dir, strength=0.8, confidence=0.85)
    structure = StructureResult(
        trend=trend_dir,
        label="HIGHER_HIGH_HIGHER_LOW" if bullish else "LOWER_HIGH_LOWER_LOW",
        bos="BULLISH" if bullish else "BEARISH",
        choch="NONE",
        last_swing_high=110,
        last_swing_low=100,
        confidence=0.8,
    )
    momentum = MomentumResult(
        state=MomentumState.BULLISH if bullish else MomentumState.BEARISH,
        score=0.7 if bullish else -0.7,
        confidence=0.8,
    )
    liquidity = LiquidityResult(
        last_sweep=Direction.BULLISH if bullish else Direction.BEARISH
    )
    sr = SRResult(
        supports=[_zone(99, 100)],
        resistances=[_zone(120, 121, "RESISTANCE")],
        nearest_support=_zone(99, 100),
        nearest_resistance=_zone(120, 121, "RESISTANCE"),
        current_price=105,
        atr=1.0,
    )
    volatility = VolatilityResult(classification=VolatilityClass.NORMAL, atr=1.0)
    volume = VolumeResult(
        state=volume_state,
        direction_sign=1 if volume_state is VolumeState.CONFIRMING and bullish else -1
        if volume_state is VolumeState.CONFIRMING
        else 0,
    )
    return trend, structure, momentum, liquidity, sr, volatility, volume


def test_bullish_setup_scores_positive():
    bundle = _bundle("BULLISH")
    result = score_setup(*bundle, _mtf(), ScoringConfig())
    assert result.signed_score > 30
    assert result.bias is Direction.BULLISH
    assert 0 <= result.score <= 100
    assert result.label in ("WEAK", "MIXED", "MODERATE", "STRONG", "VERY STRONG")
    assert 0 < result.confidence <= 0.95


def test_bearish_setup_scores_negative():
    bundle = _bundle("BEARISH")
    result = score_setup(*bundle, _mtf("ALIGNED_BEARISH", 1.15, 0, 3), ScoringConfig())
    assert result.signed_score < -30
    assert result.bias is Direction.BEARISH


def test_conflict_multiplier_reduces_score():
    bullish = _bundle("BULLISH")
    aligned = score_setup(*bullish, _mtf(), ScoringConfig())
    conflicted = score_setup(
        *bullish,
        _mtf("CONFLICT", 0.55, 1, 2),
        ScoringConfig(),
    )
    assert abs(conflicted.signed_score) < abs(aligned.signed_score)


def test_insufficient_everything_scores_zero():
    trend = TrendResult(state=Direction.INSUFFICIENT_DATA, strength=0, confidence=0)
    structure = StructureResult(
        trend=Direction.INSUFFICIENT_DATA,
        label="INSUFFICIENT_DATA",
        bos="NONE",
        choch="NONE",
        last_swing_high=None,
        last_swing_low=None,
    )
    momentum = MomentumResult(
        state=MomentumState.INSUFFICIENT_DATA, score=0, confidence=0
    )
    result = score_setup(
        trend,
        structure,
        momentum,
        LiquidityResult(),
        SRResult(),
        VolatilityResult(classification=VolatilityClass.INSUFFICIENT_DATA),
        VolumeResult(state=VolumeState.INSUFFICIENT_DATA),
        MTFResult(alignment="INSUFFICIENT_DATA", multiplier=0.8),
        ScoringConfig(),
    )
    assert result.score == 0
    assert result.label == "WEAK"
    assert result.bias is Direction.NEUTRAL
    assert result.confidence == 0


def test_volume_excluded_when_missing():
    bundle = _bundle("BULLISH", volume_state=VolumeState.INSUFFICIENT_DATA)
    result = score_setup(*bundle, _mtf(), ScoringConfig())
    names = {component.name for component in result.components}
    assert "volume" in names
    assert any("volume" in note for note in result.notes)


def test_custom_weights_change_result():
    trend, structure, momentum, liquidity, sr, volatility, volume = _bundle("BULLISH")
    heavy_structure = ScoringConfig(
        weights={
            "structure": 1.0,
            "liquidity": 0.0,
            "momentum": 0.0,
            "trend": 0.0,
            "support_resistance": 0.0,
            "volatility": 0.0,
            "volume": 0.0,
        }
    )
    result = score_setup(
        trend, structure, momentum, liquidity, sr, volatility, volume, _mtf(), heavy_structure
    )
    assert result.bias is Direction.BULLISH
    assert result.score == pytest.approx(structure.confidence * 100 * 1.15, rel=0.05)


def test_labels_thresholds():
    thresholds = [40, 60, 75, 90]
    assert label_for(0, thresholds) == "WEAK"
    assert label_for(39.9, thresholds) == "WEAK"
    assert label_for(40, thresholds) == "MIXED"
    assert label_for(60, thresholds) == "MODERATE"
    assert label_for(75, thresholds) == "STRONG"
    assert label_for(90, thresholds) == "VERY STRONG"
