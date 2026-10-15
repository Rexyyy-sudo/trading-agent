"""Risk calculator and position sizing tests."""

from __future__ import annotations

import pytest

from src.risk.calculator import RiskInput, calculate_risk
from src.risk.position_sizing import (
    lots_from_units,
    pips_between,
    position_units,
    risk_amount,
    rr_ratio,
    stop_distance,
)
from src.utils.errors import ValidationError


def test_risk_amount_and_stop_distance():
    assert risk_amount(10000, 1.0) == pytest.approx(100.0)
    assert risk_amount(5000, 2.0) == pytest.approx(100.0)
    assert stop_distance(100, 99) == pytest.approx(1.0)
    with pytest.raises(ValueError):
        stop_distance(100, 100)


def test_rr_ratio_direction_aware():
    assert rr_ratio(100, 99, 102) == pytest.approx(2.0)
    assert rr_ratio(100, 101, 98) == pytest.approx(2.0)
    assert rr_ratio(100, 99, 98) == 0.0  # wrong side
    assert rr_ratio(100, 101, 102) == 0.0


def test_position_units_and_lots():
    units = position_units(100, 1.0)
    assert units == pytest.approx(100.0)
    assert lots_from_units(units) == pytest.approx(0.001)
    assert pips_between(100.0, 99.0, 0.0001) == pytest.approx(10000.0)


def test_calculate_risk_long_basic():
    result = calculate_risk(
        RiskInput(balance=10000, risk_pct=1.0, entry=100, stop=99, targets=[101.5, 102, 103]),
        max_risk_pct=2.0,
        pip_size=0.0001,
    )
    assert result.valid
    assert result.side == "LONG"
    assert result.risk_amount == pytest.approx(100.0)
    assert result.position_units == pytest.approx(100.0)
    assert result.rr_targets == pytest.approx([1.5, 2.0, 3.0])
    assert result.pips == pytest.approx(10000.0)
    assert result.warnings == []


def test_calculate_risk_short_basic():
    result = calculate_risk(
        RiskInput(balance=10000, risk_pct=0.5, entry=100, stop=101, targets=[99, 98]),
        max_risk_pct=2.0,
    )
    assert result.side == "SHORT"
    assert result.risk_amount == pytest.approx(50.0)
    assert result.position_units == pytest.approx(50.0)
    assert result.rr_targets == pytest.approx([1.0, 2.0])


def test_max_risk_warning():
    result = calculate_risk(
        RiskInput(balance=10000, risk_pct=3.0, entry=100, stop=99, targets=[102]),
        max_risk_pct=2.0,
    )
    assert any("exceeds" in warning for warning in result.warnings)


def test_wrong_side_target_is_rejected():
    result = calculate_risk(
        RiskInput(balance=10000, risk_pct=1.0, entry=100, stop=99, targets=[98]),
    )
    assert result.rr_targets == []
    assert any("wrong side" in warning for warning in result.warnings)


def test_low_rr_warning():
    result = calculate_risk(
        RiskInput(balance=10000, risk_pct=1.0, entry=100, stop=99, targets=[100.5]),
        warn_rr_below=1.5,
    )
    assert any("R:R" in warning for warning in result.warnings)


def test_invalid_inputs_raise():
    with pytest.raises((ValueError, ValidationError)):
        calculate_risk(RiskInput(balance=0, risk_pct=1.0, entry=100, stop=99))
    with pytest.raises((ValueError, ValidationError)):
        calculate_risk(RiskInput(balance=1000, risk_pct=1.0, entry=100, stop=100))
    with pytest.raises((ValueError, ValidationError)):
        calculate_risk(RiskInput(balance=1000, risk_pct=0, entry=100, stop=99))


def test_disclaimers_present():
    result = calculate_risk(RiskInput(balance=1000, risk_pct=1.0, entry=100, stop=99))
    assert result.disclaimers
    assert any("estimates" in line for line in result.disclaimers)
