"""Indicator tests."""

from __future__ import annotations

import numpy as np
import pytest
from conftest import make_series

from src.analysis.indicators import (
    atr,
    bollinger,
    ema,
    last_value,
    macd,
    rolling_percentile,
    rsi,
    slope,
    sma,
    true_range,
)


def test_sma_basic():
    series = make_series([1, 2, 3, 4, 5]).to_frame()["close"]
    result = sma(series, 3)
    assert np.isnan(result.iloc[1])
    assert result.iloc[2] == pytest.approx(2.0)
    assert result.iloc[4] == pytest.approx(4.0)


def test_ema_matches_manual_recursion():
    series = make_series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]).to_frame()["close"]
    result = ema(series, 3)
    alpha = 2 / (3 + 1)
    manual = series.iloc[0]
    for value in series.iloc[1:]:
        manual = manual + alpha * (value - manual)
    assert result.iloc[-1] == pytest.approx(manual, rel=1e-9)


def test_rsi_all_gains_is_100():
    series = make_series([100 + index for index in range(40)]).to_frame()["close"]
    value = last_value(rsi(series, 14))
    assert value == pytest.approx(100.0)


def test_rsi_all_losses_is_0():
    series = make_series([100 - index for index in range(40)]).to_frame()["close"]
    value = last_value(rsi(series, 14))
    assert value == pytest.approx(0.0)


def test_rsi_flat_is_50():
    series = make_series([100.0] * 40).to_frame()["close"]
    value = last_value(rsi(series, 14))
    assert value == pytest.approx(50.0)


def test_rsi_range_and_insufficient_data():
    series = make_series([100 + 5 * np.sin(i / 3) for i in range(80)]).to_frame()["close"]
    values = rsi(series, 14).dropna()
    assert not values.empty
    assert values.between(0, 100).all()
    short = make_series([100, 101, 102]).to_frame()["close"]
    assert rsi(short, 14).dropna().empty


def test_atr_known_values():
    frame = make_series([100, 102, 101, 103, 104, 103]).to_frame()
    tr = true_range(frame).dropna()
    assert tr.iloc[1] == pytest.approx(2.4, abs=1e-9)  # high 102.2 low 99.8
    atr_values = atr(frame, 3).dropna()
    assert not atr_values.empty
    assert (atr_values > 0).all()


def test_macd_structure():
    series = make_series([100 + index * 0.5 for index in range(120)]).to_frame()["close"]
    frame = macd(series, 12, 26, 9)
    assert set(frame.columns) == {"macd", "signal", "histogram"}
    latest = frame.dropna().iloc[-1]
    assert latest["macd"] > 0
    assert latest["histogram"] == pytest.approx(latest["macd"] - latest["signal"])


def test_bollinger_ordering_and_bandwidth():
    series = make_series([100 + 3 * np.sin(i / 5) for i in range(80)]).to_frame()["close"]
    bands = bollinger(series, 20, 2.0).dropna()
    assert (bands["upper"] >= bands["middle"]).all()
    assert (bands["middle"] >= bands["lower"]).all()
    assert (bands["bandwidth"] >= 0).all()


def test_slope_and_percentile():
    rising = make_series([100 + index for index in range(30)]).to_frame()["close"]
    falling = make_series([100 - index for index in range(30)]).to_frame()["close"]
    assert slope(rising, 10) > 0
    assert slope(falling, 10) < 0
    frame = make_series([100 + 5 * np.sin(i / 4) for i in range(200)]).to_frame()
    atr_series = atr(frame, 14)
    percentile = rolling_percentile(atr_series, 150)
    assert percentile is not None
    assert 0 <= percentile <= 100


def test_last_value_handles_empty():
    empty = make_series([100]).to_frame()["close"].iloc[0:0]
    assert last_value(empty) is None
