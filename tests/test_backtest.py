"""Backtest engine smoke tests."""

from __future__ import annotations

import pytest
from conftest import make_series, zigzag_closes

from src.backtest.engine import run_backtest
from src.utils.config import load_settings
from src.utils.errors import InsufficientDataError


def _oscillating_series():
    closes = zigzag_closes([120, 110, 118, 108, 116, 106, 114, 104, 112, 102, 110], leg=40)
    return make_series(closes, symbol="TESTUSD", timeframe="M5", volumes=[150.0] * len(closes))


def test_backtest_runs_and_reports(tmp_path):
    settings = load_settings(None, root=tmp_path)
    result = run_backtest(_oscillating_series(), settings, provider_name="test", max_bars=500)
    assert result.bars > 200
    assert result.evaluated_bars > 0
    assert result.stats.total_trades >= 0
    assert result.equity_curve
    assert result.limitations
    assert any("spread" in limitation for limitation in result.limitations)
    payload = result.as_dict()
    assert payload["symbol"] == "TESTUSD"
    assert "stats" in payload


def test_backtest_insufficient_data_raises(tmp_path):
    settings = load_settings(None, root=tmp_path)
    short = make_series([100 + index * 0.1 for index in range(60)])
    with pytest.raises(InsufficientDataError):
        run_backtest(short, settings)
