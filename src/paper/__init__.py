"""Paper-trading subpackage (simulation only - no live execution)."""

from src.paper.account import (
    CLOSED,
    OPEN,
    AccountState,
    AccountStore,
    PaperPosition,
)
from src.paper.broker import PaperBroker, PaperStats, compute_stats
from src.paper.simulator import SimulationReport, run_over_candles, summarize

__all__ = [
    "CLOSED",
    "OPEN",
    "AccountState",
    "AccountStore",
    "PaperBroker",
    "PaperPosition",
    "PaperStats",
    "SimulationReport",
    "compute_stats",
    "run_over_candles",
    "summarize",
]
