"""Potential-liquidity tests."""

from __future__ import annotations

from conftest import make_series, zigzag_closes

from src.analysis.liquidity import analyze_liquidity
from src.analysis.structure import analyze_structure
from src.analysis.volatility import analyze_volatility
from src.utils.config import AnalysisConfig


def _context(closes, **kwargs):
    series = make_series(closes, wick=0.1, **kwargs)
    frame = series.to_frame()
    config = AnalysisConfig()
    structure = analyze_structure(frame, config)
    volatility = analyze_volatility(frame, config)
    return frame, structure.swings, volatility.atr, config


def test_equal_highs_create_buyside_pool():
    closes = zigzag_closes([96, 100, 97, 100, 96.5, 100, 97, 95], leg=5)
    frame, swings, atr_value, config = _context(closes)
    result = analyze_liquidity(frame, swings, atr_value, config)
    equal_highs = [pool for pool in result.pools if pool.label == "EQUAL_HIGHS"]
    assert equal_highs
    pool = equal_highs[0]
    assert pool.side == "BUYSIDE"
    assert pool.touches >= 2
    assert 99.4 <= pool.level <= 100.6
    assert all(pool.as_dict()["potential"] for pool in equal_highs)


def test_equal_lows_create_sellside_pool():
    closes = zigzag_closes([104, 100, 103, 100, 103.5, 100, 103, 106], leg=5)
    frame, swings, atr_value, config = _context(closes)
    result = analyze_liquidity(frame, swings, atr_value, config)
    equal_lows = [pool for pool in result.pools if pool.label == "EQUAL_LOWS"]
    assert equal_lows
    assert equal_lows[0].side == "SELLSIDE"


def test_sweep_of_highs_is_bearish():
    closes = zigzag_closes([96, 100, 97, 100, 96.5, 100, 97], leg=5)
    closes = closes + [100.4, 99.0, 98.0, 97.5]
    highs = list(closes[:-4]) + [100.4, 101.0, 99.0, 98.2]
    series = make_series(closes, wick=0.05, highs=highs)
    frame = series.to_frame()
    config = AnalysisConfig()
    structure = analyze_structure(frame, config)
    volatility = analyze_volatility(frame, config)
    result = analyze_liquidity(frame, structure.swings, volatility.atr, config)
    assert result.last_sweep is not None
    assert result.last_sweep.value == "BEARISH"
    assert any(pool.is_swept for pool in result.pools)


def test_no_swings_returns_note():
    frame = make_series([100] * 30).to_frame()
    result = analyze_liquidity(frame, [], None, AnalysisConfig())
    assert result.pools == []
    assert result.notes
