"""Market structure analysis.

Detects swing points, HH/HL/LH/LL sequences, Break of Structure (BOS)
and Change of Character (CHoCH).

This is a transparent heuristic, not a perfect representation of how
every trader labels structure. Results carry a confidence value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from src.analysis.types import Direction
from src.utils.config import AnalysisConfig
from src.utils.validation import clamp

HIGH = "HIGH"
LOW = "LOW"


@dataclass(frozen=True)
class SwingPoint:
    index: int
    time: datetime | None
    price: float
    kind: str  # HIGH | LOW


@dataclass
class StructureResult:
    trend: Direction
    label: str
    bos: str  # BULLISH | BEARISH | NONE
    choch: str  # BULLISH | BEARISH | NONE
    last_swing_high: float | None
    last_swing_low: float | None
    swings: list[SwingPoint] = field(default_factory=list)
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)

    def as_dict(self, include_swings: bool = False) -> dict:
        payload = {
            "trend": self.trend.value,
            "label": self.label,
            "bos": self.bos,
            "choch": self.choch,
            "last_swing_high": self.last_swing_high,
            "last_swing_low": self.last_swing_low,
            "confidence": round(self.confidence, 3),
            "notes": self.notes,
        }
        if include_swings:
            payload["swings"] = [
                {"index": s.index, "price": s.price, "kind": s.kind} for s in self.swings
            ]
        return payload


def find_swings(frame: pd.DataFrame, lookback: int = 3) -> list[SwingPoint]:
    """Fractal swing points: local extremum over +/- lookback bars."""
    if lookback < 1:
        raise ValueError("lookback must be >= 1")
    if len(frame) < lookback * 2 + 1:
        return []
    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    times = [ts.to_pydatetime() for ts in frame.index]
    swings: list[SwingPoint] = []
    for i in range(lookback, len(frame) - lookback):
        left_high = highs[i - lookback : i]
        right_high = highs[i + 1 : i + lookback + 1]
        if highs[i] > left_high.max() and highs[i] >= right_high.max():
            swings.append(SwingPoint(i, times[i], float(highs[i]), HIGH))
        left_low = lows[i - lookback : i]
        right_low = lows[i + 1 : i + lookback + 1]
        if lows[i] < left_low.min() and lows[i] <= right_low.min():
            swings.append(SwingPoint(i, times[i], float(lows[i]), LOW))
    swings.sort(key=lambda s: s.index)
    return swings


def simplify_swings(swings: list[SwingPoint]) -> list[SwingPoint]:
    """Alternate HIGH/LOW, keeping the most extreme consecutive same-kind swing."""
    simplified: list[SwingPoint] = []
    for swing in swings:
        if simplified and simplified[-1].kind == swing.kind:
            previous = simplified[-1]
            if swing.kind == HIGH and swing.price >= previous.price:
                simplified[-1] = swing
            elif swing.kind == LOW and swing.price <= previous.price:
                simplified[-1] = swing
        else:
            simplified.append(swing)
    return simplified


def _transition_labels(swings: list[SwingPoint]) -> list[tuple[int, str, str]]:
    """Return (index, kind, label) transitions: HH/HL/LH/LL."""
    labels: list[tuple[int, str, str]] = []
    for kind in (HIGH, LOW):
        points = [s for s in swings if s.kind == kind]
        for previous, current in zip(points, points[1:], strict=False):
            if kind == HIGH:
                label = "HH" if current.price > previous.price else "LH"
            else:
                label = "HL" if current.price > previous.price else "LL"
            labels.append((current.index, kind, label))
    labels.sort(key=lambda item: item[0])
    return labels


def _detect_breaks(
    frame: pd.DataFrame, swings: list[SwingPoint], lookback: int
) -> list[tuple[int, str, str]]:
    """Walk-forward BOS/CHoCH detection.

    A level is armed when a swing is *confirmed* (lookback bars later) and
    consumed once price closes beyond it. Breaking in the direction of the
    previous break is a BOS; breaking against it is a CHoCH.
    """
    closes = frame["close"].to_numpy(dtype=float)
    highs = [s for s in swings if s.kind == HIGH]
    lows = [s for s in swings if s.kind == LOW]
    high_cursor = 0
    low_cursor = 0
    pending_high: SwingPoint | None = None
    pending_low: SwingPoint | None = None
    events: list[tuple[int, str, str]] = []
    current_direction: str | None = None

    for i in range(len(frame)):
        while high_cursor < len(highs) and highs[high_cursor].index + lookback <= i:
            pending_high = highs[high_cursor]
            high_cursor += 1
        while low_cursor < len(lows) and lows[low_cursor].index + lookback <= i:
            pending_low = lows[low_cursor]
            low_cursor += 1
        close = closes[i]
        if pending_high is not None and close > pending_high.price:
            event = "CHoCH" if current_direction == "BEARISH" else "BOS"
            events.append((i, "BULLISH", event))
            current_direction = "BULLISH"
            pending_high = None
        elif pending_low is not None and close < pending_low.price:
            event = "CHoCH" if current_direction == "BULLISH" else "BOS"
            events.append((i, "BEARISH", event))
            current_direction = "BEARISH"
            pending_low = None
    return events


def analyze_structure(frame: pd.DataFrame, config: AnalysisConfig) -> StructureResult:
    lookback = config.swing_lookback
    if len(frame) < lookback * 4 + 2:
        return StructureResult(
            trend=Direction.INSUFFICIENT_DATA,
            label="INSUFFICIENT_DATA",
            bos="NONE",
            choch="NONE",
            last_swing_high=None,
            last_swing_low=None,
            notes=[f"need >= {lookback * 4 + 2} candles for structure detection"],
        )

    raw_swings = find_swings(frame, lookback)
    swings = simplify_swings(raw_swings)
    highs = [s for s in swings if s.kind == HIGH]
    lows = [s for s in swings if s.kind == LOW]
    if len(highs) < 2 or len(lows) < 2:
        return StructureResult(
            trend=Direction.INSUFFICIENT_DATA,
            label="INSUFFICIENT_DATA",
            bos="NONE",
            choch="NONE",
            last_swing_high=highs[-1].price if highs else None,
            last_swing_low=lows[-1].price if lows else None,
            swings=swings,
            notes=["not enough swing points to classify structure"],
        )

    labels = _transition_labels(swings)
    latest_high_label = next(
        (label for _, kind, label in reversed(labels) if kind == HIGH), None
    )
    latest_low_label = next(
        (label for _, kind, label in reversed(labels) if kind == LOW), None
    )

    notes: list[str] = []
    if latest_high_label == "HH" and latest_low_label == "HL":
        trend = Direction.BULLISH
        label = "HIGHER_HIGH_HIGHER_LOW"
    elif latest_high_label == "LH" and latest_low_label == "LL":
        trend = Direction.BEARISH
        label = "LOWER_HIGH_LOWER_LOW"
    else:
        trend = Direction.RANGING
        label = "MIXED"
        notes.append(
            f"mixed swing sequence (last high: {latest_high_label}, "
            f"last low: {latest_low_label})"
        )

    events = _detect_breaks(frame, swings, lookback)
    bos = "NONE"
    choch = "NONE"
    last_event_direction = None
    for _, direction, event_type in reversed(events):
        if event_type == "CHoCH" and choch == "NONE":
            choch = direction
            last_event_direction = direction
        elif event_type == "BOS" and bos == "NONE":
            bos = direction
            if last_event_direction is None:
                last_event_direction = direction
        if bos != "NONE" and choch != "NONE":
            break

    if last_event_direction == "BULLISH" and trend != Direction.BEARISH:
        trend = Direction.BULLISH
        notes.append("recent bullish break of structure")
    elif last_event_direction == "BEARISH" and trend != Direction.BULLISH:
        trend = Direction.BEARISH
        notes.append("recent bearish break of structure")

    confidence = 0.5
    if label != "MIXED":
        confidence += 0.15
    if last_event_direction is not None:
        confidence += 0.15
        if (last_event_direction == "BULLISH" and trend == Direction.BULLISH) or (
            last_event_direction == "BEARISH" and trend == Direction.BEARISH
        ):
            confidence += 0.1
    if trend == Direction.RANGING:
        confidence -= 0.15
    confidence = clamp(confidence, 0.1, 0.92)

    return StructureResult(
        trend=trend,
        label=label,
        bos=bos,
        choch=choch,
        last_swing_high=highs[-1].price,
        last_swing_low=lows[-1].price,
        swings=swings,
        confidence=round(confidence, 3),
        notes=notes,
    )
