"""Entry model.

Produces an ENTRY ZONE (never a single fabricated price), a stop loss
derived from structure or ATR, and R-multiple targets that can be
aligned with real opposing levels.

Confirmation is always required: the plan states exactly what needs to
happen before risking money, and what invalidates the scenario.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.analysis.structure import StructureResult
from src.analysis.support_resistance import SRResult
from src.utils.config import RiskConfig

LONG = "LONG"
SHORT = "SHORT"

PULLBACK_RETEST = "PULLBACK_RETEST"
BREAKOUT_RETEST = "BREAKOUT_RETEST"
STRUCTURE_RETEST = "STRUCTURE_RETEST"


@dataclass
class EntryPlan:
    side: str
    model: str
    entry_lower: float
    entry_upper: float
    entry_mid: float
    stop_loss: float
    targets: list[float] = field(default_factory=list)
    rr_values: list[float] = field(default_factory=list)
    confirmation: str = ""
    invalidation: str = ""
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "side": self.side,
            "model": self.model,
            "entry_zone": [round(self.entry_lower, 6), round(self.entry_upper, 6)],
            "entry_mid": round(self.entry_mid, 6),
            "stop_loss": round(self.stop_loss, 6),
            "targets": [round(value, 6) for value in self.targets],
            "risk_reward": [round(value, 2) for value in self.rr_values],
            "confirmation": self.confirmation,
            "invalidation": self.invalidation,
            "notes": self.notes,
        }


def _targets_with_structure(
    direction: int,
    entry_mid: float,
    risk_distance: float,
    rr_targets: list[float],
    opposing: tuple[float, float] | None,
) -> tuple[list[float], list[str]]:
    notes: list[str] = []
    targets = [
        entry_mid + direction * rr * risk_distance for rr in sorted(rr_targets)
    ]
    if opposing is None:
        return targets, notes
    lower, upper = opposing
    center = (lower + upper) / 2
    distance_ahead = direction * (center - entry_mid)
    if 0.8 * risk_distance <= distance_ahead <= 3.0 * risk_distance:
        adjusted = [center]
        for target in targets:
            if direction * (target - center) > 0 and len(adjusted) < len(targets):
                adjusted.append(target)
        targets = adjusted
        notes.append(
            "TP1 aligned to an opposing level/zone ahead of the entry"
        )
    return targets, notes


def build_entry_plan(
    side: str,
    frame: pd.DataFrame,
    structure: StructureResult,
    sr: SRResult,
    atr_value: float | None,
    config: RiskConfig,
) -> EntryPlan | None:
    """Build a scenario entry plan, or None when no honest plan exists."""
    if frame.empty:
        return None
    price = float(frame["close"].iloc[-1])
    if not atr_value or atr_value <= 0:
        return None
    notes: list[str] = []
    direction = 1 if side == LONG else -1

    swing_low = structure.last_swing_low
    swing_high = structure.last_swing_high
    support = sr.nearest_support
    resistance = sr.nearest_resistance

    anchor: float | None = None
    if side == LONG:
        if support is not None and 0 < price - support.upper <= 2.5 * atr_value:
            model = PULLBACK_RETEST
            lower, upper = support.upper - 0.15 * atr_value, support.upper + 0.25 * atr_value
            anchor = min(support.lower, swing_low if swing_low else support.lower)
            confirmation = (
                "wait for a bullish rejection or a close back above the zone "
                "before entering"
            )
        elif structure.bos == "BULLISH" and swing_high:
            model = BREAKOUT_RETEST
            lower, upper = swing_high - 0.15 * atr_value, swing_high + 0.25 * atr_value
            anchor = swing_high
            confirmation = (
                "wait for a candle close above the zone, then enter on the retest; "
                "do not chase"
            )
        elif swing_low:
            model = STRUCTURE_RETEST
            lower, upper = swing_low - 0.05 * atr_value, swing_low + 0.3 * atr_value
            anchor = swing_low
            confirmation = (
                "wait for a bullish reaction at the zone (rejection wick or "
                "engulfing close)"
            )
        else:
            return None
        stop = min(lower, anchor) - config.structure_buffer_atr * atr_value
        opposing_pair = (
            (resistance.lower, resistance.upper) if resistance is not None else None
        )
    else:
        if resistance is not None and 0 < resistance.lower - price <= 2.5 * atr_value:
            model = PULLBACK_RETEST
            lower, upper = resistance.lower - 0.25 * atr_value, resistance.lower + 0.15 * atr_value
            anchor = max(resistance.upper, swing_high if swing_high else resistance.upper)
            confirmation = (
                "wait for a bearish rejection or a close back below the zone "
                "before entering"
            )
        elif structure.bos == "BEARISH" and swing_low:
            model = BREAKOUT_RETEST
            lower, upper = swing_low - 0.25 * atr_value, swing_low + 0.15 * atr_value
            anchor = swing_low
            confirmation = (
                "wait for a candle close below the zone, then enter on the retest; "
                "do not chase"
            )
        elif swing_high:
            model = STRUCTURE_RETEST
            lower, upper = swing_high - 0.3 * atr_value, swing_high + 0.05 * atr_value
            anchor = swing_high
            confirmation = (
                "wait for a bearish reaction at the zone (rejection wick or "
                "engulfing close)"
            )
        else:
            return None
        stop = max(upper, anchor) + config.structure_buffer_atr * atr_value
        opposing_pair = (
            (support.lower, support.upper) if support is not None else None
        )

    if config.sl_method == "atr":
        entry_mid = (lower + upper) / 2
        stop = entry_mid - direction * config.atr_sl_multiplier * atr_value
        notes.append("ATR-based stop loss (configured)")

    entry_mid = (lower + upper) / 2
    risk_distance = direction * (entry_mid - stop)
    if risk_distance <= 0:
        return None

    targets, target_notes = _targets_with_structure(
        direction, entry_mid, risk_distance, config.rr_targets, opposing_pair
    )
    notes.extend(target_notes)
    rr_values = [abs(target - entry_mid) / risk_distance for target in targets]

    invalidation = (
        f"a candle close {'below' if side == LONG else 'above'} {stop:.5f} "
        f"invalidates this scenario; "
        + (
            "a bearish break of structure also invalidates it"
            if side == LONG
            else "a bullish break of structure also invalidates it"
        )
    )
    notes.append("entry zone is a scenario - confirmation at the zone is required")

    return EntryPlan(
        side=side,
        model=model,
        entry_lower=lower,
        entry_upper=upper,
        entry_mid=entry_mid,
        stop_loss=stop,
        targets=targets,
        rr_values=rr_values,
        confirmation=confirmation,
        invalidation=invalidation,
        notes=notes,
    )
