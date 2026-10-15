"""Virtual account state and JSON persistence.

This is a PAPER trading account only. There is no live-broker code path
in this project by design.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.utils.errors import ValidationError
from src.utils.logging import get_logger
from src.utils.validation import is_missing

logger = get_logger("paper.account")

OPEN = "OPEN"
CLOSED = "CLOSED"
LONG = "LONG"
SHORT = "SHORT"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class PaperPosition:
    id: str
    symbol: str
    side: str  # LONG | SHORT
    size: float
    entry_price: float
    stop_loss: float | None = None
    take_profit: float | None = None
    opened_at: str = field(default_factory=_now_iso)
    timeframe: str = ""
    note: str = ""
    status: str = OPEN
    exit_price: float | None = None
    exit_at: str | None = None
    pnl: float | None = None
    close_reason: str | None = None

    def unrealized_pnl(self, price: float) -> float:
        if is_missing(price):
            return 0.0
        direction = 1.0 if self.side == LONG else -1.0
        return (float(price) - self.entry_price) * self.size * direction

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "side": self.side,
            "size": self.size,
            "entry_price": self.entry_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "opened_at": self.opened_at,
            "timeframe": self.timeframe,
            "note": self.note,
            "status": self.status,
            "exit_price": self.exit_price,
            "exit_at": self.exit_at,
            "pnl": self.pnl,
            "close_reason": self.close_reason,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> PaperPosition:
        return cls(
            id=str(payload["id"]),
            symbol=str(payload["symbol"]),
            side=str(payload["side"]),
            size=float(payload["size"]),
            entry_price=float(payload["entry_price"]),
            stop_loss=None if payload.get("stop_loss") is None else float(payload["stop_loss"]),
            take_profit=(
                None if payload.get("take_profit") is None else float(payload["take_profit"])
            ),
            opened_at=str(payload.get("opened_at") or _now_iso()),
            timeframe=str(payload.get("timeframe") or ""),
            note=str(payload.get("note") or ""),
            status=str(payload.get("status") or OPEN),
            exit_price=None if payload.get("exit_price") is None else float(payload["exit_price"]),
            exit_at=payload.get("exit_at"),
            pnl=None if payload.get("pnl") is None else float(payload["pnl"]),
            close_reason=payload.get("close_reason"),
        )


@dataclass
class AccountState:
    starting_balance: float
    balance: float
    positions: list[PaperPosition] = field(default_factory=list)
    trades: list[PaperPosition] = field(default_factory=list)

    @property
    def open_positions(self) -> list[PaperPosition]:
        return [position for position in self.positions if position.status == OPEN]

    def equity(self, prices: dict[str, float] | None = None) -> float:
        prices = prices or {}
        total = self.balance
        for position in self.open_positions:
            price = prices.get(position.symbol)
            if price is None:
                price = position.entry_price
            total += position.unrealized_pnl(price)
        return total

    def as_dict(self) -> dict:
        return {
            "starting_balance": self.starting_balance,
            "balance": self.balance,
            "positions": [position.as_dict() for position in self.positions],
            "trades": [trade.as_dict() for trade in self.trades],
        }

    @classmethod
    def from_dict(cls, payload: dict) -> AccountState:
        return cls(
            starting_balance=float(payload.get("starting_balance", 10000.0)),
            balance=float(payload.get("balance", payload.get("starting_balance", 10000.0))),
            positions=[PaperPosition.from_dict(item) for item in payload.get("positions", [])],
            trades=[PaperPosition.from_dict(item) for item in payload.get("trades", [])],
        )


class AccountStore:
    """Loads/saves AccountState. Invalid files are quarantined, never hidden."""

    def __init__(self, path: Path | None, starting_balance: float = 10000.0) -> None:
        self.path = path
        self.starting_balance = starting_balance

    def fresh(self) -> AccountState:
        return AccountState(
            starting_balance=self.starting_balance, balance=self.starting_balance
        )

    def load(self) -> AccountState:
        if self.path is None or not self.path.is_file():
            return self.fresh()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            quarantine = self.path.with_suffix(self.path.suffix + ".corrupt")
            try:
                self.path.replace(quarantine)
                logger.warning(
                    "paper account file was unreadable (%s); moved to %s",
                    exc,
                    quarantine,
                )
            except OSError:
                logger.warning("paper account file unreadable and could not be moved: %s", exc)
            return self.fresh()
        if not isinstance(payload, dict):
            raise ValidationError(f"paper account file {self.path} is malformed")
        return AccountState.from_dict(payload)

    def save(self, state: AccountState) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(state.as_dict(), indent=2), encoding="utf-8"
        )
        temporary.replace(self.path)
