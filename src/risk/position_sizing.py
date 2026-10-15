"""Position sizing primitives (pure functions, no side effects)."""

from __future__ import annotations

from src.utils.validation import ensure_positive

STANDARD_LOT_UNITS = 100_000.0


def risk_amount(balance: float, risk_pct: float) -> float:
    """Currency amount risked on a trade."""
    ensure_positive(balance, "balance")
    if risk_pct <= 0 or risk_pct > 100:
        raise ValueError("risk_pct must be within (0, 100]")
    return balance * (risk_pct / 100.0)


def stop_distance(entry: float, stop: float) -> float:
    ensure_positive(entry, "entry")
    ensure_positive(stop, "stop")
    if entry == stop:
        raise ValueError("stop must differ from entry")
    return abs(entry - stop)


def rr_ratio(entry: float, stop: float, target: float) -> float:
    """Reward-to-risk ratio (always >= 0; 0 when target is behind entry)."""
    distance = stop_distance(entry, stop)
    reward = abs(target - entry)
    direction_ok = (entry > stop and target > entry) or (entry < stop and target < entry)
    return reward / distance if direction_ok else 0.0


def position_units(risk: float, distance: float, unit_value: float = 1.0) -> float:
    """Units such that a move of `distance` loses `risk` currency units.

    `unit_value` is the currency value of a 1.0 price move for one unit.
    For CFDs on 1 unit of the base asset it is 1.0.
    """
    ensure_positive(risk, "risk")
    ensure_positive(distance, "stop distance")
    ensure_positive(unit_value, "unit value")
    return risk / (distance * unit_value)


def lots_from_units(units: float, contract_size: float = STANDARD_LOT_UNITS) -> float:
    ensure_positive(contract_size, "contract size")
    return units / contract_size


def pips_between(entry: float, stop: float, pip_size: float) -> float:
    if pip_size <= 0:
        raise ValueError("pip_size must be > 0")
    return stop_distance(entry, stop) / pip_size


def value_per_pip(units: float, pip_size: float) -> float:
    return units * pip_size
