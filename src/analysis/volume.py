"""Volume analysis (only when real volume data exists).

FX/metals feeds frequently carry no volume. In that case the module
returns INSUFFICIENT_DATA and the scoring engine excludes the component
instead of inventing values.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.analysis.indicators import last_value, slope, sma
from src.analysis.types import VolumeState

_VOLUME_WINDOW = 20


@dataclass
class VolumeResult:
    state: VolumeState
    direction_sign: int = 0  # +1 bullish, -1 bearish, 0 neutral
    relative_volume: float | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "state": self.state.value,
            "relative_volume": (
                round(self.relative_volume, 2)
                if self.relative_volume is not None
                else None
            ),
            "notes": self.notes,
        }


def analyze_volume(frame: pd.DataFrame, window: int = _VOLUME_WINDOW) -> VolumeResult:
    if frame.empty or "volume" not in frame.columns:
        return VolumeResult(
            state=VolumeState.INSUFFICIENT_DATA,
            notes=["no volume column in the data"],
        )
    volume = frame["volume"].dropna()
    if len(volume) < window + 2 or float(volume.tail(window).abs().sum()) == 0.0:
        return VolumeResult(
            state=VolumeState.INSUFFICIENT_DATA,
            notes=["volume data is missing or zero for this source"],
        )

    average = last_value(sma(volume, window))
    latest = last_value(volume)
    if average is None or latest is None or average <= 0:
        return VolumeResult(
            state=VolumeState.INSUFFICIENT_DATA,
            notes=["volume average unavailable"],
        )

    relative = latest / average
    notes: list[str] = []
    price_change = float(frame["close"].iloc[-1] - frame["close"].iloc[-5]) if len(frame) >= 5 else 0.0
    direction_sign = 0
    if relative >= 1.2:
        state = VolumeState.CONFIRMING
        direction_sign = 1 if price_change > 0 else -1 if price_change < 0 else 0
        notes.append(f"volume {relative:.1f}x the {window}-bar average confirms the move")
    elif relative <= 0.8:
        state = VolumeState.DIVERGENT
        direction_sign = 0
        notes.append(
            f"volume is only {relative:.1f}x average - the move lacks participation"
        )
    else:
        state = VolumeState.NEUTRAL
        notes.append("volume is in line with its recent average")

    volume_slope = slope(volume, min(10, len(volume) - 1))
    if volume_slope is not None and volume_slope > 0 and relative > 1.0:
        notes.append("volume is rising")

    return VolumeResult(
        state=state,
        direction_sign=direction_sign,
        relative_volume=relative,
        notes=notes,
    )
