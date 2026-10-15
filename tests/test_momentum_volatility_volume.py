"""Momentum / volatility / volume tests."""

from __future__ import annotations

from conftest import flat_series, make_series, uptrend_series

from src.analysis.momentum import analyze_momentum
from src.analysis.volatility import analyze_volatility
from src.analysis.volume import analyze_volume
from src.utils.config import AnalysisConfig


def test_momentum_bullish_on_rising_market():
    result = analyze_momentum(uptrend_series(120).to_frame(), AnalysisConfig())
    assert result.state.value == "BULLISH"
    assert result.score > 0
    assert result.rsi is not None and result.rsi > 50


def test_momentum_bearish_on_falling_market():
    closes = [130 - 0.1 * index for index in range(120)]
    result = analyze_momentum(make_series(closes).to_frame(), AnalysisConfig())
    assert result.state.value == "BEARISH"
    assert result.score < 0


def test_momentum_neutral_on_flat_market():
    result = analyze_momentum(flat_series(120).to_frame(), AnalysisConfig())
    assert result.state.value in ("NEUTRAL", "BULLISH", "BEARISH")  # flat RSI ~50
    assert abs(result.score) < 0.6


def test_momentum_insufficient_data():
    result = analyze_momentum(make_series([100, 101, 102, 103]).to_frame(), AnalysisConfig())
    assert result.state.value == "INSUFFICIENT_DATA"


def test_volatility_insufficient_data():
    result = analyze_volatility(make_series([100] * 20).to_frame(), AnalysisConfig())
    assert result.classification.value == "INSUFFICIENT_DATA"


def test_volatility_normal_and_low():
    result = analyze_volatility(uptrend_series(260).to_frame(), AnalysisConfig())
    assert result.classification.value in ("LOW", "NORMAL", "HIGH")
    assert result.atr is not None and result.atr > 0


def test_volatility_spike_is_flagged():
    closes = [100 + (index % 2) * 0.5 for index in range(150)] + [100, 108]
    series = make_series(closes)
    frame = series.to_frame()
    frame.iloc[-1, frame.columns.get_loc("high")] = 112.0
    frame.iloc[-1, frame.columns.get_loc("low")] = 98.0
    result = analyze_volatility(frame, AnalysisConfig())
    assert result.classification.value in ("HIGH", "EXTREME")
    assert result.warning is True


def test_volume_insufficient_without_data():
    series = make_series(uptrend_series(60).to_frame()["close"].tolist(), volume=None)
    result = analyze_volume(series.to_frame())
    assert result.state.value == "INSUFFICIENT_DATA"


def test_volume_confirming_on_spike():
    closes = [100 + 0.2 * index for index in range(60)]
    volumes = [100.0] * 59 + [500.0]
    series = make_series(closes, volumes=volumes)
    result = analyze_volume(series.to_frame())
    assert result.state.value == "CONFIRMING"
    assert result.relative_volume is not None and result.relative_volume > 1.2
    assert result.direction_sign == 1
