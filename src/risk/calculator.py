"""Risk calculator.

All numbers are ESTIMATES. Broker contract specifications, spreads,
slippage, swaps and margin rules differ per broker and instrument.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.risk.position_sizing import (
    STANDARD_LOT_UNITS,
    lots_from_units,
    pips_between,
    position_units,
    rr_ratio,
    stop_distance,
)
from src.risk.position_sizing import (
    risk_amount as compute_risk_amount,
)
from src.utils.validation import ensure_positive

DISCLAIMERS = (
    "Risk and position size are estimates only.",
    "Broker contract sizes, pip values, spreads and margin differ per broker.",
    "This tool never recommends leverage. Keep risk per trade small.",
)


@dataclass
class RiskInput:
    balance: float
    risk_pct: float
    entry: float
    stop: float
    targets: list[float] = field(default_factory=list)


@dataclass
class RiskResult:
    valid: bool
    side: str  # LONG | SHORT
    balance: float
    risk_amount: float
    risk_pct: float
    entry: float
    stop: float
    stop_distance: float
    stop_pct: float
    position_units: float
    standard_lots: float
    pips: float | None
    rr_targets: list[float] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    disclaimers: list[str] = field(default_factory=lambda: list(DISCLAIMERS))

    def as_dict(self) -> dict:
        return {
            "valid": self.valid,
            "side": self.side,
            "balance": self.balance,
            "risk_amount": round(self.risk_amount, 2),
            "risk_pct": self.risk_pct,
            "entry": self.entry,
            "stop": self.stop,
            "stop_distance": round(self.stop_distance, 6),
            "position_units": round(self.position_units, 4),
            "standard_lots": round(self.standard_lots, 4),
            "pips": round(self.pips, 1) if self.pips is not None else None,
            "rr_targets": [round(value, 2) for value in self.rr_targets],
            "warnings": self.warnings,
            "disclaimers": self.disclaimers,
        }


def calculate_risk(
    risk_input: RiskInput,
    max_risk_pct: float = 2.0,
    warn_rr_below: float = 1.5,
    pip_size: float | None = None,
    unit_value: float = 1.0,
) -> RiskResult:
    balance = ensure_positive(risk_input.balance, "balance")
    entry = ensure_positive(risk_input.entry, "entry")
    stop = ensure_positive(risk_input.stop, "stop")
    if risk_input.risk_pct <= 0 or risk_input.risk_pct > 100:
        raise ValueError("risk_pct must be within (0, 100]")
    identity = stop_distance(entry, stop)

    side = "LONG" if entry > stop else "SHORT"
    amount = compute_risk_amount(balance, risk_input.risk_pct)
    units = position_units(amount, identity, unit_value=unit_value)
    warnings: list[str] = []

    if risk_input.risk_pct > max_risk_pct:
        warnings.append(
            f"risk {risk_input.risk_pct:.2f}% exceeds the configured maximum "
            f"{max_risk_pct:.2f}% - reduce size"
        )
    rr_values: list[float] = []
    for index, target in enumerate(risk_input.targets, start=1):
        if target <= 0:
            warnings.append(f"TP{index} is not a valid price - ignored")
            continue
        direction_ok = (side == "LONG" and target > entry) or (
            side == "SHORT" and target < entry
        )
        if not direction_ok:
            warnings.append(
                f"TP{index} ({target:g}) is on the wrong side of entry for a {side} - ignored"
            )
            continue
        rr = rr_ratio(entry, stop, target)
        rr_values.append(rr)
        if index == 1 and rr < warn_rr_below:
            warnings.append(
                f"TP1 R:R is only {rr:.2f} (below {warn_rr_below:.2f}) - consider waiting "
                "for a better price"
            )
    if not rr_values:
        warnings.append("no valid targets supplied - R:R not computed")

    pips = None
    if pip_size and pip_size > 0:
        pips = pips_between(entry, stop, pip_size)

    return RiskResult(
        valid=True,
        side=side,
        balance=balance,
        risk_amount=amount,
        risk_pct=risk_input.risk_pct,
        entry=entry,
        stop=stop,
        stop_distance=identity,
        stop_pct=identity / entry * 100.0,
        position_units=units,
        standard_lots=lots_from_units(units, STANDARD_LOT_UNITS),
        pips=pips,
        rr_targets=rr_values,
        warnings=warnings,
    )
