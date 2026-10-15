"""Paper-trading simulator helpers.

Feeds candles through a PaperBroker so stops/targets of open positions
are processed bar by bar. Used by both `paper` CLI commands and the
backtester.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.market.candles import CandleSeries
from src.paper.broker import PaperBroker


@dataclass
class SimulationReport:
    candles_processed: int
    events: list[dict]

    @property
    def closed_events(self) -> list[dict]:
        return [event for event in self.events if event.get("event") == "CLOSED"]

    def as_dict(self) -> dict:
        return {
            "candles_processed": self.candles_processed,
            "closed": len(self.closed_events),
            "events": self.events,
        }


def run_over_candles(
    broker: PaperBroker, symbol: str, series: CandleSeries
) -> SimulationReport:
    """Process an entire candle series for stop/target fills."""
    events: list[dict] = []
    for candle in series.candles:
        events.extend(broker.process_candle(symbol, candle))
    return SimulationReport(candles_processed=len(series.candles), events=events)


def summarize(report: SimulationReport) -> str:
    closed = report.closed_events
    stops = sum(1 for event in closed if event.get("reason") == "STOP_LOSS")
    targets = sum(1 for event in closed if event.get("reason") == "TAKE_PROFIT")
    manual = len(closed) - stops - targets
    return (
        f"processed {report.candles_processed} candles; "
        f"{len(closed)} position(s) closed "
        f"(SL: {stops}, TP: {targets}, other: {manual})"
    )
