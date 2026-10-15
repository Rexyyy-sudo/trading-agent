"""Validation tests: symbols, timeframes, candles, config, resampling."""

from __future__ import annotations

from datetime import timedelta

import pytest
from conftest import BASE_TIME, make_series

from src.market.candles import Candle, CandleSeries, resample_series
from src.market.symbols import resolve_symbol
from src.market.timeframes import (
    assign_roles,
    auto_timeframe_set,
    normalize_timeframe,
    parse_timeframes,
    timeframe_minutes,
)
from src.utils.config import load_settings
from src.utils.errors import ConfigError, ValidationError


def test_symbol_resolution_classes():
    gold = resolve_symbol("XAUUSD")
    assert gold.asset_class == "metal"
    assert gold.base == "XAU"
    assert gold.pip_size == pytest.approx(0.1)

    eurusd = resolve_symbol("eur/usd")
    assert eurusd.asset_class == "forex"
    assert eurusd.pip_size == pytest.approx(0.0001)

    usdjpy = resolve_symbol("USDJPY")
    assert usdjpy.pip_size == pytest.approx(0.01)
    assert usdjpy.price_decimals == 3

    btc = resolve_symbol("btc-usdt")
    assert btc.asset_class == "crypto"
    assert btc.symbol == "BTCUSDT"

    gold_alias = resolve_symbol("GOLD")
    assert gold_alias.symbol == "XAUUSD"


def test_symbol_invalid_raises():
    for bad in ("", "!!", "A"):
        with pytest.raises(ValidationError):
            resolve_symbol(bad)


def test_timeframe_normalisation():
    assert normalize_timeframe("5m") == "M5"
    assert normalize_timeframe("15min") == "M15"
    assert normalize_timeframe("1h") == "H1"
    assert normalize_timeframe("h4") == "H4"
    assert normalize_timeframe("1d") == "D1"
    assert timeframe_minutes("H1") == 60
    with pytest.raises(ValidationError):
        normalize_timeframe("M7")


def test_parse_timeframes_dedupes_and_orders():
    assert parse_timeframes("H1, M15,M5,h1") == ["H1", "M15", "M5"]
    assert parse_timeframes(None, default=["M5", "H1"]) == ["M5", "H1"]
    with pytest.raises(ValidationError):
        parse_timeframes("")
    with pytest.raises(ValidationError):
        parse_timeframes(None, default=[])


def test_auto_timeframe_sets_and_roles():
    assert auto_timeframe_set("M5") == ["H1", "M15", "M5"]
    assert auto_timeframe_set("M15") == ["H4", "H1", "M15"]
    roles = assign_roles(["H1", "M15", "M5"])
    assert roles == {"H1": "htf", "M15": "mtf", "M5": "ltf"}


def test_candle_series_validation_fatal_cases():
    good = make_series([100, 101, 102, 103, 104])
    assert good.fatal_issues() == []

    bad_candle = Candle(BASE_TIME, 100, 99, 101, 100)  # high < low
    bad = CandleSeries("TESTUSD", "M5", "test", [bad_candle])
    assert bad.fatal_issues()

    empty = CandleSeries("TESTUSD", "M5", "test", [])
    assert not empty
    assert empty.fatal_issues()


def test_candle_series_sanitize_sorts_and_dedupes():
    time = BASE_TIME
    candles = [
        Candle(time + timedelta(minutes=5), 101, 102, 100, 101.5),
        Candle(time, 100, 101, 99, 100.5),
        Candle(time, 100, 101, 99, 100.7),  # duplicate timestamp
    ]
    series = CandleSeries("TESTUSD", "M5", "test", candles)
    cleaned, fixes = series.sanitize()
    assert len(cleaned) == 2
    assert cleaned.candles[0].close == pytest.approx(100.7)
    assert fixes


def test_is_usable_min_bars():
    series = make_series([100] * 50)
    ok, reasons = series.is_usable(120)
    assert not ok
    assert reasons
    ok, reasons = series.is_usable(30)
    assert ok
    assert reasons == []


def test_resample_aggregation():
    closes = [100, 101, 102, 103, 104, 105, 106]
    series = make_series(closes, timeframe="M5")
    resampled = resample_series(series, "M15")
    assert len(resampled) == 3
    first_frame = series.to_frame().iloc[:3]
    first = resampled.candles[0]
    assert first.open == pytest.approx(first_frame["open"].iloc[0])
    assert first.close == pytest.approx(first_frame["close"].iloc[-1])
    assert first.high == pytest.approx(first_frame["high"].max())
    assert first.low == pytest.approx(first_frame["low"].min())
    with pytest.raises(ValidationError):
        resample_series(series, "M1")


def test_settings_validation_errors(tmp_path):
    bad_weight = tmp_path / "bad.yaml"
    bad_weight.write_text("scoring:\n  weights:\n    structure: -1\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(bad_weight)

    bad_thresholds = tmp_path / "bad2.yaml"
    bad_thresholds.write_text(
        "scoring:\n  label_thresholds: [50, 40, 75, 90]\n", encoding="utf-8"
    )
    with pytest.raises(ConfigError):
        load_settings(bad_thresholds)

    bad_method = tmp_path / "bad3.yaml"
    bad_method.write_text("risk:\n  sl_method: magic\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(bad_method)


def test_settings_defaults_loaded(tmp_path):
    settings = load_settings(None, root=tmp_path)
    assert settings.analysis.min_bars >= 30
    assert settings.scoring.weights["structure"] == pytest.approx(0.30)
    assert settings.risk.sl_method in ("structure", "atr")
    assert settings.root == tmp_path.resolve()
