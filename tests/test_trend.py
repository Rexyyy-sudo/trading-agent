"""Trend analysis tests."""

from __future__ import annotations

from conftest import downtrend_series, flat_series, make_series, uptrend_series

from src.analysis.trend import analyze_trend
from src.utils.config import AnalysisConfig


def test_uptrend_is_bullish():
    result = analyze_trend(uptrend_series(300).to_frame(), AnalysisConfig())
    assert result.state.value == "BULLISH"
    assert result.strength > 0.3
    assert 0 < result.confidence <= 0.95


def test_downtrend_is_bearish():
    result = analyze_trend(downtrend_series(300).to_frame(), AnalysisConfig())
    assert result.state.value == "BEARISH"
    assert result.strength > 0.3


def test_flat_market_is_ranging():
    result = analyze_trend(flat_series(300).to_frame(), AnalysisConfig())
    assert result.state.value in ("RANGING", "NEUTRAL")


def test_short_series_is_insufficient():
    result = analyze_trend(make_series([100, 101, 102]).to_frame(), AnalysisConfig())
    assert result.state.value == "INSUFFICIENT_DATA"
    assert result.confidence == 0.0
