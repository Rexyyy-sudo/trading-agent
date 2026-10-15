"""Market structure tests (synthetic zigzag data)."""

from __future__ import annotations

from conftest import make_series, zigzag_closes

from src.analysis.structure import analyze_structure, find_swings, simplify_swings


def _config():
    from src.utils.config import AnalysisConfig

    return AnalysisConfig()


UPTREND_POINTS = [100, 104, 102, 108, 105, 112, 107, 116]
DOWNTREND_POINTS = [116, 112, 114, 108, 110, 104, 107, 100]


def test_find_swings_alternates_kinds():
    series = make_series(zigzag_closes(UPTREND_POINTS, leg=5))
    swings = find_swings(series.to_frame(), lookback=3)
    assert len(swings) >= 6
    assert {swing.kind for swing in swings} == {"HIGH", "LOW"}
    simplified = simplify_swings(swings)
    for previous, current in zip(simplified, simplified[1:], strict=False):
        assert previous.kind != current.kind


def test_uptrend_structure_is_bullish_with_hh_hl():
    series = make_series(zigzag_closes(UPTREND_POINTS, leg=5))
    result = analyze_structure(series.to_frame(), _config())
    assert result.trend.value == "BULLISH"
    assert result.label == "HIGHER_HIGH_HIGHER_LOW"
    assert result.last_swing_high is not None
    assert result.last_swing_low is not None
    assert result.last_swing_high > result.last_swing_low
    assert 0.0 < result.confidence <= 1.0


def test_downtrend_structure_is_bearish_with_lh_ll():
    series = make_series(zigzag_closes(DOWNTREND_POINTS, leg=5))
    result = analyze_structure(series.to_frame(), _config())
    assert result.trend.value == "BEARISH"
    assert result.label == "LOWER_HIGH_LOWER_LOW"


def test_bos_detected_on_continuation():
    points = [100, 104, 102, 108, 105, 112, 106, 116, 108, 120]
    series = make_series(zigzag_closes(points, leg=5))
    result = analyze_structure(series.to_frame(), _config())
    assert result.bos == "BULLISH"
    assert result.trend.value == "BULLISH"


def test_choch_detected_after_reversal():
    points = [100, 104, 102, 108, 105, 112, 106, 98, 103, 95]
    series = make_series(zigzag_closes(points, leg=5))
    result = analyze_structure(series.to_frame(), _config())
    assert result.choch == "BEARISH"
    assert result.trend.value in ("BEARISH", "RANGING")


def test_insufficient_data_structure():
    series = make_series([100, 101, 102, 103, 104])
    result = analyze_structure(series.to_frame(), _config())
    assert result.trend.value == "INSUFFICIENT_DATA"
    assert result.bos == "NONE"
