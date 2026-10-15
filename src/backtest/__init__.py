"""Backtesting subpackage (rule-based, walk-forward, honest about limits)."""

from src.backtest.engine import BacktestResult, run_backtest

__all__ = ["BacktestResult", "run_backtest"]
