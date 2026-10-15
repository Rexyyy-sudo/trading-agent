"""Multi-timeframe alignment tests."""

from __future__ import annotations

from src.analysis.multi_timeframe import TFAssessment, analyze_multi_timeframe
from src.analysis.types import Direction, MomentumState
from src.utils.config import DecisionConfig


def _assessment(tf, role, trend, structure, momentum):
    return TFAssessment(
        timeframe=tf, role=role, trend=trend, structure=structure, momentum=momentum
    )


def test_aligned_bullish():
    assessments = [
        _assessment("H1", "htf", Direction.BULLISH, Direction.BULLISH, MomentumState.BULLISH),
        _assessment("M15", "mtf", Direction.BULLISH, Direction.BULLISH, MomentumState.BULLISH),
        _assessment("M5", "ltf", Direction.BULLISH, Direction.BULLISH, MomentumState.BULLISH),
    ]
    result = analyze_multi_timeframe(assessments, DecisionConfig())
    assert result.alignment == "ALIGNED_BULLISH"
    assert result.bullish_count == 3
    assert result.multiplier == 1.15
    assert result.ltf_confirms(Direction.BULLISH)


def test_conflict_htf_bullish_ltf_bearish():
    assessments = [
        _assessment("H1", "htf", Direction.BULLISH, Direction.BULLISH, MomentumState.BULLISH),
        _assessment("M15", "mtf", Direction.BEARISH, Direction.BEARISH, MomentumState.BEARISH),
        _assessment("M5", "ltf", Direction.BEARISH, Direction.BEARISH, MomentumState.BEARISH),
    ]
    result = analyze_multi_timeframe(assessments, DecisionConfig())
    assert result.conflict is True
    assert result.multiplier < 1.0
    assert not result.ltf_confirms(Direction.BULLISH)


def test_mixed_when_not_enough_agree():
    assessments = [
        _assessment("H1", "htf", Direction.BULLISH, Direction.BULLISH, MomentumState.BULLISH),
        _assessment("M15", "mtf", Direction.BEARISH, Direction.BEARISH, MomentumState.BEARISH),
        _assessment("M5", "ltf", Direction.RANGING, Direction.RANGING, MomentumState.NEUTRAL),
    ]
    result = analyze_multi_timeframe(assessments, DecisionConfig())
    assert result.alignment in ("MIXED", "CONFLICT")


def test_insufficient_all():
    assessments = [
        _assessment(
            "H1", "htf", Direction.INSUFFICIENT_DATA, Direction.INSUFFICIENT_DATA,
            MomentumState.INSUFFICIENT_DATA,
        ),
    ]
    result = analyze_multi_timeframe(assessments, DecisionConfig())
    assert result.alignment == "INSUFFICIENT_DATA"
