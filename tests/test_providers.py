"""Provider tests (offline: CSV + null + registry)."""

from __future__ import annotations

import pytest
from conftest import make_series

from src.market.data_provider import build_provider, build_provider_chain, provider_names
from src.market.providers.csv_provider import CSVProvider, save_series_csv
from src.market.providers.null_provider import NullProvider
from src.market.symbols import resolve_symbol
from src.utils.config import load_settings
from src.utils.errors import ProviderError, ValidationError


def _settings(tmp_path):
    (tmp_path / "data" / "raw").mkdir(parents=True, exist_ok=True)
    return load_settings(None, root=tmp_path)


def test_registry_contains_core_providers():
    names = set(provider_names())
    assert {"csv", "null", "binance", "yahoo", "twelvedata", "alphavantage"} <= names


def test_unknown_provider_raises(tmp_path):
    settings = _settings(tmp_path)
    with pytest.raises(ValidationError):
        build_provider("does-not-exist", settings)


def test_null_provider_is_unavailable():
    provider = NullProvider(load_settings(None, root="/tmp/opencode"))
    assert provider.availability().available is False
    with pytest.raises(ProviderError):
        provider.fetch_ohlcv(resolve_symbol("XAUUSD"), "M5", 100)


def test_csv_roundtrip(tmp_path):
    settings = _settings(tmp_path)
    series = make_series(
        [100 + index * 0.1 for index in range(200)],
        symbol="XAUUSD",
        timeframe="M5",
        volumes=[120.0] * 200,
    )
    path = tmp_path / "data" / "raw" / "XAUUSD_M5.csv"
    save_series_csv(series, path)
    provider = CSVProvider(settings)
    assert provider.availability().available
    fetched = provider.get_ohlcv(resolve_symbol("XAUUSD"), "M5", 500)
    assert len(fetched) == 200
    assert fetched.last_close() == pytest.approx(series.last_close())
    assert fetched.candles[0].volume == pytest.approx(120.0)
    assert fetched.metadata["provider"] == "csv"


def test_csv_missing_file_helpful_error(tmp_path):
    settings = _settings(tmp_path)
    provider = CSVProvider(settings)
    with pytest.raises(ProviderError) as excinfo:
        provider.get_ohlcv(resolve_symbol("XAUUSD"), "M5", 100)
    assert "XAUUSD_M5.csv" in str(excinfo.value)


def test_csv_malformed_file(tmp_path):
    settings = _settings(tmp_path)
    path = tmp_path / "data" / "raw" / "XAUUSD_M5.csv"
    path.write_text("foo,bar\n1,2\n", encoding="utf-8")
    provider = CSVProvider(settings)
    with pytest.raises(ProviderError):
        provider.get_ohlcv(resolve_symbol("XAUUSD"), "M5", 100)

    path.write_text("", encoding="utf-8")
    with pytest.raises(ProviderError):
        provider.get_ohlcv(resolve_symbol("XAUUSD"), "M5", 100)


def test_csv_interval_mismatch_warning(tmp_path):
    settings = _settings(tmp_path)
    series = make_series([100 + index for index in range(50)], timeframe="M5")
    save_series_csv(series, tmp_path / "data" / "raw" / "XAUUSD_M15.csv")
    provider = CSVProvider(settings)
    fetched = provider.get_ohlcv(resolve_symbol("XAUUSD"), "M15", 100)
    notes = fetched.metadata.get("provider_notes", [])
    assert any("declared as M15" in note for note in notes)


def test_chain_falls_back_to_null(tmp_path):
    settings = _settings(tmp_path)
    settings.providers.priority = ["csv"]
    chain = build_provider_chain(settings, resolve_symbol("XAUUSD"), "auto")
    assert [provider.name for provider in chain] == ["null"]


def test_chain_uses_available_csv(tmp_path):
    settings = _settings(tmp_path)
    series = make_series([100 + index for index in range(50)], timeframe="M5")
    save_series_csv(series, tmp_path / "data" / "raw" / "XAUUSD_M5.csv")
    settings.providers.priority = ["csv"]
    chain = build_provider_chain(settings, resolve_symbol("XAUUSD"), "auto")
    assert chain[0].name == "csv"


def test_explicit_unavailable_provider_raises(tmp_path):
    settings = _settings(tmp_path)
    with pytest.raises(ProviderError):
        build_provider_chain(settings, resolve_symbol("XAUUSD"), "twelvedata")
