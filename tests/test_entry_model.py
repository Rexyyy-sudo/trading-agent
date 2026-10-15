"""Entry model tests."""

from __future__ import annotations

from conftest import make_series

from src.analysis.structure import StructureResult
from src.analysis.support_resistance import SRResult, Zone
from src.analysis.types import Direction
from src.signal.entry_model import (
    BREAKOUT_RETEST,
    LONG,
    PULLBACK_RETEST,
    SHORT,
    build_entry_plan,
)
from src.utils.config import RiskConfig


def _frame(price: float):
    closes = [price - 0.5, price - 0.2, price]
    return make_series(closes).to_frame()


def _bullish_structure():
    return StructureResult(
        trend=Direction.BULLISH,
        label="HIGHER_HIGH_HIGHER_LOW",
        bos="BULLISH",
        choch="NONE",
        last_swing_high=108.0,
        last_swing_low=104.0,
        confidence=0.8,
    )


def _bearish_structure():
    return StructureResult(
        trend=Direction.BEARISH,
        label="LOWER_HIGH_LOWER_LOW",
        bos="BEARISH",
        choch="NONE",
        last_swing_high=96.0,
        last_swing_low=92.0,
        confidence=0.8,
    )


def test_long_pullback_plan_levels():
    frame = _frame(106.0)
    sr = SRResult(
        supports=[Zone(103.5, 104.5, 2, 0.8, 10, "SUPPORT")],
        resistances=[Zone(110.0, 111.0, 2, 0.7, 12, "RESISTANCE")],
        nearest_support=Zone(103.5, 104.5, 2, 0.8, 10, "SUPPORT"),
        nearest_resistance=Zone(110.0, 111.0, 2, 0.7, 12, "RESISTANCE"),
        current_price=106.0,
        atr=1.0,
    )
    plan = build_entry_plan(LONG, frame, _bullish_structure(), sr, 1.0, RiskConfig())
    assert plan is not None
    assert plan.model == PULLBACK_RETEST
    assert plan.entry_lower <= plan.entry_mid <= plan.entry_upper
    assert plan.stop_loss < plan.entry_mid
    assert plan.targets == sorted(plan.targets)
    assert all(target > plan.entry_mid for target in plan.targets)
    assert all(rr > 0 for rr in plan.rr_values)
    assert "invalidates" in plan.invalidation
    assert plan.confirmation


def test_short_pullback_plan_levels():
    frame = _frame(94.0)
    sr = SRResult(
        supports=[Zone(88.0, 89.0, 2, 0.7, 10, "SUPPORT")],
        resistances=[Zone(95.5, 96.5, 2, 0.8, 12, "RESISTANCE")],
        nearest_support=Zone(88.0, 89.0, 2, 0.7, 10, "SUPPORT"),
        nearest_resistance=Zone(95.5, 96.5, 2, 0.8, 12, "RESISTANCE"),
        current_price=94.0,
        atr=1.0,
    )
    plan = build_entry_plan(SHORT, frame, _bearish_structure(), sr, 1.0, RiskConfig())
    assert plan is not None
    assert plan.entry_lower <= plan.entry_mid <= plan.entry_upper
    assert plan.stop_loss > plan.entry_mid
    assert all(target < plan.entry_mid for target in plan.targets)


def test_breakout_model_when_support_far():
    frame = _frame(112.0)
    sr = SRResult(
        supports=[Zone(98.0, 99.0, 2, 0.6, 10, "SUPPORT")],
        resistances=[],
        nearest_support=Zone(98.0, 99.0, 2, 0.6, 10, "SUPPORT"),
        nearest_resistance=None,
        current_price=112.0,
        atr=1.0,
    )
    plan = build_entry_plan(LONG, frame, _bullish_structure(), sr, 1.0, RiskConfig())
    assert plan is not None
    assert plan.model == BREAKOUT_RETEST


def test_atr_stop_method():
    frame = _frame(106.0)
    sr = SRResult(
        supports=[Zone(103.5, 104.5, 2, 0.8, 10, "SUPPORT")],
        nearest_support=Zone(103.5, 104.5, 2, 0.8, 10, "SUPPORT"),
        current_price=106.0,
        atr=1.0,
    )
    config = RiskConfig(sl_method="atr", atr_sl_multiplier=1.5)
    plan = build_entry_plan(LONG, frame, _bullish_structure(), sr, 1.0, config)
    assert plan is not None
    assert plan.stop_loss == plan.entry_mid - 1.5


def test_no_plan_without_structure_or_atr():
    frame = _frame(106.0)
    no_levels = StructureResult(
        trend=Direction.INSUFFICIENT_DATA,
        label="INSUFFICIENT_DATA",
        bos="NONE",
        choch="NONE",
        last_swing_high=None,
        last_swing_low=None,
    )
    assert build_entry_plan(LONG, frame, no_levels, SRResult(), None, RiskConfig()) is None
    assert build_entry_plan(LONG, frame, no_levels, SRResult(), 1.0, RiskConfig()) is None
