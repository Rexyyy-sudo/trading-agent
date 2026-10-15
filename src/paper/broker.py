"""Paper broker: simulated fills, stops and statistics.

Conservative conventions (documented, not hidden):
  - if a single candle touches both SL and TP, the STOP is assumed
    to fill first (worst case);
  - fills happen exactly at the SL/TP price (no spread/slippage);
  - no commissions, swaps or margin mechanics are simulated.

NO live broker execution exists anywhere in this project.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from src.market.candles import Candle, CandleSeries
from src.paper.account import (
    CLOSED,
    LONG,
    SHORT,
    AccountState,
    AccountStore,
    PaperPosition,
    _now_iso,
)
from src.utils.errors import ValidationError
from src.utils.logging import get_logger

logger = get_logger("paper.broker")


@dataclass
class PaperStats:
    starting_balance: float
    balance: float
    equity: float
    open_positions: int
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    gross_profit: float
    gross_loss: float
    profit_factor: float | None
    average_win: float
    average_loss: float
    expectancy: float
    total_pnl: float
    return_pct: float
    max_drawdown: float
    max_drawdown_pct: float
    best_trade: float
    worst_trade: float

    def as_dict(self) -> dict:
        return {
            "starting_balance": round(self.starting_balance, 2),
            "balance": round(self.balance, 2),
            "equity": round(self.equity, 2),
            "open_positions": self.open_positions,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 4),
            "gross_profit": round(self.gross_profit, 2),
            "gross_loss": round(self.gross_loss, 2),
            "profit_factor": (
                round(self.profit_factor, 3) if self.profit_factor is not None else None
            ),
            "average_win": round(self.average_win, 2),
            "average_loss": round(self.average_loss, 2),
            "expectancy": round(self.expectancy, 2),
            "total_pnl": round(self.total_pnl, 2),
            "return_pct": round(self.return_pct, 2),
            "max_drawdown": round(self.max_drawdown, 2),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "best_trade": round(self.best_trade, 2),
            "worst_trade": round(self.worst_trade, 2),
        }


def compute_stats(state: AccountState, prices: dict[str, float] | None = None) -> PaperStats:
    trades = state.trades
    realized = [float(trade.pnl or 0.0) for trade in trades]
    wins = [value for value in realized if value > 0]
    losses = [value for value in realized if value < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    total_pnl = sum(realized)

    equity_curve: list[float] = [state.starting_balance]
    for value in realized:
        equity_curve.append(equity_curve[-1] + value)
    peak = equity_curve[0]
    max_drawdown = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, peak - value)

    return PaperStats(
        starting_balance=state.starting_balance,
        balance=state.balance,
        equity=state.equity(prices),
        open_positions=len(state.open_positions),
        total_trades=len(trades),
        wins=len(wins),
        losses=len(losses),
        win_rate=(len(wins) / len(trades)) if trades else 0.0,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=(gross_profit / gross_loss) if gross_loss > 0 else None,
        average_win=(gross_profit / len(wins)) if wins else 0.0,
        average_loss=(gross_loss / len(losses)) if losses else 0.0,
        expectancy=(total_pnl / len(trades)) if trades else 0.0,
        total_pnl=total_pnl,
        return_pct=(total_pnl / state.starting_balance * 100.0)
        if state.starting_balance
        else 0.0,
        max_drawdown=max_drawdown,
        max_drawdown_pct=(max_drawdown / state.starting_balance * 100.0)
        if state.starting_balance
        else 0.0,
        best_trade=max(realized) if realized else 0.0,
        worst_trade=min(realized) if realized else 0.0,
    )


class PaperBroker:
    def __init__(self, store: AccountStore, persist: bool = True) -> None:
        self.store = store
        self.persist = persist
        self.state = store.load()

    # ---- account ---------------------------------------------------------
    def reset(self, starting_balance: float | None = None) -> AccountState:
        balance = starting_balance or self.store.starting_balance
        self.state = AccountState(starting_balance=balance, balance=balance)
        self._save()
        return self.state

    def equity(self, prices: dict[str, float] | None = None) -> float:
        return self.state.equity(prices)

    def stats(self, prices: dict[str, float] | None = None) -> PaperStats:
        return compute_stats(self.state, prices)

    # ---- orders ----------------------------------------------------------
    def open_position(
        self,
        symbol: str,
        side: str,
        size: float,
        entry_price: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        timeframe: str = "",
        note: str = "",
        opened_at: str | None = None,
    ) -> PaperPosition:
        side = side.upper()
        if side not in (LONG, SHORT):
            raise ValidationError("side must be LONG or SHORT")
        if size <= 0:
            raise ValidationError("size must be > 0")
        if entry_price <= 0:
            raise ValidationError("entry_price must be > 0")
        if stop_loss is not None:
            if side == LONG and stop_loss >= entry_price:
                raise ValidationError("for LONG, stop_loss must be below entry_price")
            if side == SHORT and stop_loss <= entry_price:
                raise ValidationError("for SHORT, stop_loss must be above entry_price")
        if take_profit is not None:
            if side == LONG and take_profit <= entry_price:
                raise ValidationError("for LONG, take_profit must be above entry_price")
            if side == SHORT and take_profit >= entry_price:
                raise ValidationError("for SHORT, take_profit must be below entry_price")

        if stop_loss is not None:
            risk = abs(entry_price - stop_loss) * size
            if risk > self.state.balance:
                raise ValidationError(
                    f"position risk ({risk:.2f}) exceeds the virtual balance "
                    f"({self.state.balance:.2f})"
                )

        position = PaperPosition(
            id=uuid.uuid4().hex[:10],
            symbol=symbol,
            side=side,
            size=float(size),
            entry_price=float(entry_price),
            stop_loss=stop_loss,
            take_profit=take_profit,
            opened_at=opened_at or _now_iso(),
            timeframe=timeframe,
            note=note,
        )
        self.state.positions.append(position)
        self._save()
        return position

    def close_position(
        self, position_id: str, price: float, reason: str = "MANUAL"
    ) -> dict:
        position = self._find_open(position_id)
        return self._close(position, price, reason)

    def process_candle(self, symbol: str, candle: Candle) -> list[dict]:
        events: list[dict] = []
        for position in list(self.state.open_positions):
            if position.symbol != symbol:
                continue
            if position.side == LONG:
                if position.stop_loss is not None and candle.low <= position.stop_loss:
                    events.append(
                        self._close(
                            position,
                            position.stop_loss,
                            "STOP_LOSS",
                            at=candle.time.isoformat(),
                        )
                    )
                elif position.take_profit is not None and candle.high >= position.take_profit:
                    events.append(
                        self._close(
                            position,
                            position.take_profit,
                            "TAKE_PROFIT",
                            at=candle.time.isoformat(),
                        )
                    )
            else:
                if position.stop_loss is not None and candle.high >= position.stop_loss:
                    events.append(
                        self._close(
                            position,
                            position.stop_loss,
                            "STOP_LOSS",
                            at=candle.time.isoformat(),
                        )
                    )
                elif position.take_profit is not None and candle.low <= position.take_profit:
                    events.append(
                        self._close(
                            position,
                            position.take_profit,
                            "TAKE_PROFIT",
                            at=candle.time.isoformat(),
                        )
                    )
        return events

    def process_series(self, symbol: str, series: CandleSeries) -> list[dict]:
        events: list[dict] = []
        for candle in series.candles:
            events.extend(self.process_candle(symbol, candle))
        return events

    # ---- internals -------------------------------------------------------
    def _find_open(self, position_id: str) -> PaperPosition:
        for position in self.state.open_positions:
            if position.id == position_id:
                return position
        raise ValidationError(f"no open position with id {position_id!r}")

    def _close(
        self, position: PaperPosition, price: float, reason: str, at: str | None = None
    ) -> dict:
        if price <= 0:
            raise ValidationError("exit price must be > 0")
        position.status = CLOSED
        position.exit_price = float(price)
        position.exit_at = at or datetime.now(UTC).isoformat()
        position.pnl = position.unrealized_pnl(price)
        position.close_reason = reason
        self.state.balance += position.pnl
        if position in self.state.positions:
            self.state.positions.remove(position)
        self.state.trades.append(position)
        self._save()
        logger.info(
            "paper %s %s closed at %s (%s) pnl=%.2f",
            position.side,
            position.symbol,
            price,
            reason,
            position.pnl or 0.0,
        )
        return {
            "event": "CLOSED",
            "position_id": position.id,
            "symbol": position.symbol,
            "side": position.side,
            "exit_price": float(price),
            "reason": reason,
            "pnl": position.pnl,
        }

    def _save(self) -> None:
        if self.persist:
            self.store.save(self.state)
