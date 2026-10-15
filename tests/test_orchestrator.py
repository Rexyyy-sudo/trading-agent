"""End-to-end orchestration tests using the CSV provider (offline)."""

from __future__ import annotations

import json

from conftest import make_series, zigzag_closes

from src.agent.orchestrator import Orchestrator
from src.agent.prompts import explain_report
from src.market.providers.csv_provider import save_series_csv
from src.reporting.formatter import display_width, format_analysis
from src.utils.config import load_settings

CLOSES = zigzag_closes([100, 110, 105, 115, 108, 120, 112, 125], leg=30)
SYMBOL = "XAUUSD"


def _write_csvs(root, timeframes=("H1", "M15", "M5"), scale: float = 1.0):
    raw = root / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for timeframe in timeframes:
        series = make_series(
            [close * scale for close in CLOSES],
            symbol=SYMBOL,
            timeframe=timeframe,
            volumes=[100.0] * len(CLOSES),
        )
        save_series_csv(series, raw / f"{SYMBOL}_{timeframe}.csv")


def _orchestrator(root) -> Orchestrator:
    settings = load_settings(None, root=root)
    return Orchestrator(settings, provider_name="csv")


def test_full_analysis_end_to_end(tmp_path):
    _write_csvs(tmp_path)
    report = _orchestrator(tmp_path).analyze(SYMBOL, timeframe="M5")

    assert report.data_status == "SUFFICIENT"
    assert report.provider == "csv"
    assert report.timeframes == ["H1", "M15", "M5"]
    assert report.candle_count >= 120
    assert report.price is not None
    assert report.score is not None
    assert report.decision.signal in ("LONG", "SHORT", "WAIT", "NO TRADE")
    assert report.last_candle_time is not None
    assert report.news.risk_level in ("LOW", "MEDIUM", "HIGH", "EXTREME", "UNKNOWN")

    payload = report.to_dict()
    json.dumps(payload)  # must be JSON-serializable

    text = format_analysis(report)
    assert "FINAL STATUS:" in text
    assert "News risk" in text
    assert "risk" in text.lower()

    box_lines = [
        line for line in text.splitlines() if line[:1] in ("╔", "╠", "╚", "║")
    ]
    assert box_lines
    widths = {display_width(line) for line in box_lines}
    assert len(widths) == 1


def test_box_stays_aligned_with_large_prices(tmp_path):
    _write_csvs(tmp_path, scale=25.0)
    report = _orchestrator(tmp_path).analyze(SYMBOL, timeframe="M5")
    text = format_analysis(report)
    box_lines = [
        line for line in text.splitlines() if line[:1] in ("╔", "╠", "╚", "║")
    ]
    assert box_lines
    widths = {display_width(line) for line in box_lines}
    assert len(widths) == 1


def test_insufficient_data_reports_no_trade(tmp_path):
    report = _orchestrator(tmp_path).analyze(SYMBOL, timeframe="M5")
    assert report.data_status == "INSUFFICIENT"
    assert report.decision.signal == "NO TRADE"
    assert any("NO TRADE" in warning for warning in report.warnings)
    text = format_analysis(report)
    assert "NO TRADE" in text


def test_partial_data_when_htf_missing(tmp_path):
    _write_csvs(tmp_path, timeframes=("M15", "M5"))
    report = _orchestrator(tmp_path).analyze(SYMBOL, timeframe="M5")
    assert report.data_status == "PARTIAL"
    assert any("H1" in warning for warning in report.warnings)
    assert report.mtf is not None


def test_single_timeframe_mode(tmp_path):
    _write_csvs(tmp_path, timeframes=("M5",))
    settings = load_settings(None, root=tmp_path)
    settings.symbols.auto_multi_timeframe = False
    report = Orchestrator(settings, provider_name="csv").analyze(SYMBOL, timeframe="M5")
    assert report.data_status == "SUFFICIENT"
    assert report.timeframes == ["M5"]
    assert report.score is not None


def test_explain_report_renders(tmp_path):
    _write_csvs(tmp_path)
    report = _orchestrator(tmp_path).analyze(SYMBOL, timeframe="M5")
    explanation = explain_report(report)
    assert isinstance(explanation, str)
    assert explanation.strip()
