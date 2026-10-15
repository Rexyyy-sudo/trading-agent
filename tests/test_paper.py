"""Paper trading tests (simulation only)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from conftest import make_series

from src.market.candles import Candle
from src.paper.account import AccountStore
from src.paper.broker import PaperBroker, compute_stats
from src.paper.simulator import run_over_candles
from src.utils.errors import ValidationError


def _broker(tmp_path, balance: float = 10000.0) -> PaperBroker:
    store = AccountStore(tmp_path / "account.json", starting_balance=balance)
    return PaperBroker(store)


def _candle(low: float, high: float, close: float | None = None) -> Candle:
    open_ = (low + high) / 2
    return Candle(
        datetime(2026, 1, 5, tzinfo=UTC), open_, high, low, close or open_, 100.0
    )


def test_open_position_does_not_change_balance(tmp_path):
    broker = _broker(tmp_path)
    position = broker.open_position("TESTUSD", "LONG", 10, 100, stop_loss=99, take_profit=105)
    assert position.status == "OPEN"
    assert broker.state.balance == pytest.approx(10000.0)
    assert broker.equity({"TESTUSD": 102}) == pytest.approx(10020.0)


def test_stop_loss_fill(tmp_path):
    broker = _broker(tmp_path)
    broker.open_position("TESTUSD", "LONG", 10, 100, stop_loss=99, take_profit=105)
    events = broker.process_candle("TESTUSD", _candle(98.0, 101.0))
    assert len(events) == 1
    assert events[0]["reason"] == "STOP_LOSS"
    assert events[0]["pnl"] == pytest.approx(-10.0)
    assert broker.state.balance == pytest.approx(9990.0)
    assert len(broker.state.trades) == 1
    assert not broker.state.open_positions


def test_take_profit_fill(tmp_path):
    broker = _broker(tmp_path)
    broker.open_position("TESTUSD", "LONG", 10, 100, stop_loss=95, take_profit=105)
    events = broker.process_candle("TESTUSD", _candle(100.5, 106.0))
    assert events[0]["reason"] == "TAKE_PROFIT"
    assert events[0]["pnl"] == pytest.approx(50.0)
    assert broker.state.balance == pytest.approx(10050.0)


def test_stop_wins_when_both_touched_same_candle(tmp_path):
    broker = _broker(tmp_path)
    broker.open_position("TESTUSD", "LONG", 10, 100, stop_loss=99, take_profit=101)
    events = broker.process_candle("TESTUSD", _candle(98.0, 102.0))
    assert events[0]["reason"] == "STOP_LOSS"


def test_short_take_profit(tmp_path):
    broker = _broker(tmp_path)
    broker.open_position("TESTUSD", "SHORT", 10, 100, stop_loss=105, take_profit=95)
    events = broker.process_candle("TESTUSD", _candle(94.0, 100.0))
    assert events[0]["reason"] == "TAKE_PROFIT"
    assert events[0]["pnl"] == pytest.approx(50.0)


def test_close_position_manual(tmp_path):
    broker = _broker(tmp_path)
    position = broker.open_position("TESTUSD", "LONG", 10, 100, stop_loss=95)
    closed = broker.close_position(position.id, 103, reason="MANUAL")
    assert closed["reason"] == "MANUAL"
    assert closed["pnl"] == pytest.approx(30.0)
    assert broker.state.balance == pytest.approx(10030.0)


def test_invalid_orders_rejected(tmp_path):
    broker = _broker(tmp_path)
    with pytest.raises(ValidationError):
        broker.open_position("TESTUSD", "LONG", 10, 100, stop_loss=101)
    with pytest.raises(ValidationError):
        broker.open_position("TESTUSD", "SHORT", 10, 100, stop_loss=99)
    with pytest.raises(ValidationError):
        broker.open_position("TESTUSD", "LONG", -1, 100)
    with pytest.raises(ValidationError):
        broker.open_position("TESTUSD", "LONG", 2000, 100, stop_loss=90)
    with pytest.raises(ValidationError):
        broker.open_position("TESTUSD", "LONG", 10, 100, take_profit=95)


def test_stats_win_rate_and_drawdown(tmp_path):
    broker = _broker(tmp_path)
    broker.open_position("TESTUSD", "LONG", 10, 100, stop_loss=99, take_profit=110)
    broker.process_candle("TESTUSD", _candle(98.0, 101.0))  # loss -10
    broker.open_position("TESTUSD", "LONG", 10, 100, stop_loss=95, take_profit=105)
    broker.process_candle("TESTUSD", _candle(100.0, 106.0))  # win +50
    stats = broker.stats()
    assert stats.total_trades == 2
    assert stats.wins == 1
    assert stats.losses == 1
    assert stats.win_rate == pytest.approx(0.5)
    assert stats.gross_profit == pytest.approx(50.0)
    assert stats.gross_loss == pytest.approx(10.0)
    assert stats.profit_factor == pytest.approx(5.0)
    assert stats.total_pnl == pytest.approx(40.0)
    assert stats.max_drawdown == pytest.approx(10.0)


def test_persistence_roundtrip(tmp_path):
    broker = _broker(tmp_path)
    broker.open_position("TESTUSD", "LONG", 10, 100, stop_loss=99)
    reloaded = PaperBroker(AccountStore(tmp_path / "account.json", 10000.0))
    assert len(reloaded.state.open_positions) == 1
    assert reloaded.state.open_positions[0].symbol == "TESTUSD"


def test_corrupt_account_file_quarantined(tmp_path):
    path = tmp_path / "account.json"
    path.write_text("{not json", encoding="utf-8")
    broker = PaperBroker(AccountStore(path, 5000.0))
    assert broker.state.balance == pytest.approx(5000.0)
    assert path.with_suffix(".json.corrupt").exists()


def test_simulator_over_series(tmp_path):
    broker = _broker(tmp_path)
    broker.open_position("TESTUSD", "LONG", 10, 100, stop_loss=99, take_profit=105)
    series = make_series([100, 100.5, 106, 99])
    report = run_over_candles(broker, "TESTUSD", series)
    assert report.candles_processed == 4
    assert len(report.closed_events) == 1
    assert report.closed_events[0]["reason"] == "TAKE_PROFIT"


def test_compute_stats_empty_account(tmp_path):
    broker = _broker(tmp_path)
    stats = compute_stats(broker.state)
    assert stats.total_trades == 0
    assert stats.win_rate == 0.0
    assert stats.profit_factor is None
