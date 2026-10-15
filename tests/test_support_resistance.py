"""Support / resistance zone tests."""

from __future__ import annotations

from conftest import make_series, zigzag_closes

from src.analysis.structure import analyze_structure
from src.analysis.support_resistance import analyze_sr
from src.analysis.volatility import analyze_volatility
from src.utils.config import AnalysisConfig


def _context(closes):
    series = make_series(closes, wick=0.1)
    frame = series.to_frame()
    config = AnalysisConfig()
    structure = analyze_structure(frame, config)
    volatility = analyze_volatility(frame, config)
    return frame, structure.swings, volatility.atr, config


def test_equal_highs_cluster_above_price_become_resistance():
    closes = zigzag_closes([96, 100, 97, 100, 96.5, 100, 97, 95], leg=5)
    frame, swings, atr_value, config = _context(closes)
    result = analyze_sr(frame, swings, atr_value, config)
    assert result.current_price == 95
    assert result.nearest_resistance is not None
    clustered = [zone for zone in result.resistances if 99.5 <= zone.center <= 100.6]
    assert clustered
    assert clustered[0].touches >= 2
    assert 0 < clustered[0].strength <= 1


def test_levels_below_price_become_support():
    closes = zigzag_closes([104, 100, 103, 100, 103.5, 100, 103, 106], leg=5)
    frame, swings, atr_value, config = _context(closes)
    result = analyze_sr(frame, swings, atr_value, config)
    assert result.current_price == 106
    assert result.nearest_support is not None
    clustered = [zone for zone in result.supports if 99.4 <= zone.center <= 100.6]
    assert clustered
    assert clustered[0].touches >= 2


def test_zone_bounds_are_ordered():
    closes = zigzag_closes([96, 100, 97, 100, 96.5, 100, 97, 95], leg=5)
    frame, swings, atr_value, config = _context(closes)
    result = analyze_sr(frame, swings, atr_value, config)
    for zone in result.supports + result.resistances:
        assert zone.lower <= zone.upper
        assert zone.lower < zone.center < zone.upper


def test_no_swings_gives_empty_notes():
    frame = make_series([100] * 30).to_frame()
    result = analyze_sr(frame, [], None, AnalysisConfig())
    assert result.supports == []
    assert result.resistances == []
    assert result.notes
