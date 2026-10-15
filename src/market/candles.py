"""Candle data model, validation and resampling.

Candles are stored as plain dataclasses; pandas is only used at the
analysis boundary. Validation NEVER silently repairs data: issues are
reported so the caller can decide (and so the framework can refuse to
analyze garbage).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from src.market.timeframes import normalize_timeframe, pandas_rule, timeframe_minutes
from src.utils.errors import ValidationError
from src.utils.logging import get_logger
from src.utils.validation import is_missing

logger = get_logger("candles")

OHLC_COLUMNS = ("open", "high", "low", "close")


@dataclass(frozen=True, slots=True)
class Candle:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None


def parse_timestamp(value: Any) -> datetime:
    """Parse datetime | ISO string | epoch seconds | epoch milliseconds (UTC)."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        if is_missing(value):
            raise ValidationError("timestamp is missing")
        seconds = float(value)
        if abs(seconds) > 1e11:  # milliseconds
            seconds /= 1000.0
        return datetime.fromtimestamp(seconds, tz=UTC)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValidationError("timestamp is empty")
        try:
            numeric = float(text)
        except ValueError:
            numeric = None
        if numeric is not None:
            return parse_timestamp(numeric)
        iso = text.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(iso)
        except ValueError as exc:
            raise ValidationError(f"cannot parse timestamp: {value!r}") from exc
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    raise ValidationError(f"cannot parse timestamp: {value!r}")


def _clean_volume(value: Any) -> float | None:
    if is_missing(value):
        return None
    return float(value)


@dataclass
class CandleSeries:
    """A validated-by-request list of candles for one symbol/timeframe."""

    symbol: str
    timeframe: str
    source: str
    candles: list[Candle] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.candles)

    def __bool__(self) -> bool:
        return bool(self.candles)

    @property
    def is_empty(self) -> bool:
        return not self.candles

    @property
    def start(self) -> datetime | None:
        return self.candles[0].time if self.candles else None

    @property
    def end(self) -> datetime | None:
        return self.candles[-1].time if self.candles else None

    def last_close(self) -> float | None:
        return self.candles[-1].close if self.candles else None

    @classmethod
    def from_rows(
        cls,
        symbol: str,
        timeframe: str,
        source: str,
        rows: Iterable[Mapping[str, Any] | Sequence[Any]],
        metadata: dict[str, Any] | None = None,
    ) -> CandleSeries:
        """Build from provider rows (mappings or 6-element sequences)."""
        parsed: list[Candle] = []
        for row in rows:
            if isinstance(row, Mapping):
                try:
                    time = parse_timestamp(row.get("time"))
                    open_ = float(row["open"])
                    high = float(row["high"])
                    low = float(row["low"])
                    close = float(row["close"])
                    volume = _clean_volume(row.get("volume"))
                except (KeyError, TypeError, ValueError, ValidationError) as exc:
                    raise ValidationError(f"malformed candle row: {row!r} ({exc})") from exc
            elif isinstance(row, Sequence) and len(row) >= 5:
                try:
                    time = parse_timestamp(row[0])
                    open_, high, low, close = (float(row[i]) for i in range(1, 5))
                    volume = _clean_volume(row[5]) if len(row) > 5 else None
                except (TypeError, ValueError, ValidationError) as exc:
                    raise ValidationError(f"malformed candle row: {row!r} ({exc})") from exc
            else:
                raise ValidationError(f"malformed candle row: {row!r}")
            parsed.append(Candle(time, open_, high, low, close, volume))
        return cls(
            symbol=symbol,
            timeframe=normalize_timeframe(timeframe),
            source=source,
            candles=parsed,
            metadata=dict(metadata or {}),
        )

    def _checks(self) -> list[tuple[str, str]]:
        issues: list[tuple[str, str]] = []
        if not self.candles:
            return [("fatal", "series is empty")]
        previous: datetime | None = None
        duplicates = 0
        for candle in self.candles:
            if previous is not None:
                if candle.time == previous:
                    duplicates += 1
                elif candle.time < previous:
                    issues.append(("fatal", "timestamps are not ascending"))
                    break
            previous = candle.time
        if duplicates:
            issues.append(("fatal", f"{duplicates} duplicate timestamp(s)"))
        bad_price = 0
        bad_shape = 0
        negative_volume = 0
        for candle in self.candles:
            values = (candle.open, candle.high, candle.low, candle.close)
            if any(is_missing(v) or not math.isfinite(v) for v in values):
                bad_price += 1
                continue
            if any(v <= 0 for v in values):
                bad_price += 1
                continue
            epsilon = max(1e-9, abs(candle.high) * 1e-9)
            if candle.high + epsilon < max(candle.open, candle.close) or candle.low - epsilon > min(
                candle.open, candle.close
            ):
                bad_shape += 1
            if candle.high < candle.low:
                bad_shape += 1
            if candle.volume is not None and candle.volume < 0:
                negative_volume += 1
        if bad_price:
            issues.append(("fatal", f"{bad_price} candle(s) with invalid price values"))
        if bad_shape:
            issues.append(("fatal", f"{bad_shape} candle(s) with inconsistent high/low"))
        if negative_volume:
            issues.append(("fatal", f"{negative_volume} candle(s) with negative volume"))

        expected = self._median_interval_seconds()
        if expected:
            gaps = 0
            previous_time = self.candles[0].time
            for candle in self.candles[1:]:
                delta = (candle.time - previous_time).total_seconds()
                if delta > expected * 3:
                    gaps += 1
                previous_time = candle.time
            if gaps:
                issues.append(("warning", f"{gaps} anomalous time gap(s) detected"))
            if self.metadata.get("live"):
                age = (datetime.now(UTC) - self.candles[-1].time).total_seconds()
                if age > expected * 20:
                    issues.append(
                        (
                            "warning",
                            f"data may be stale: last candle is {age / 60:.0f} min old",
                        )
                    )
        if all(candle.volume is None for candle in self.candles):
            issues.append(("warning", "volume data is unavailable for this source"))
        return issues

    def _median_interval_seconds(self) -> float | None:
        if len(self.candles) < 3:
            return None
        deltas = np.diff(np.array([c.time.timestamp() for c in self.candles], dtype=float))
        if deltas.size == 0:
            return None
        median = float(np.median(deltas))
        return median if median > 0 else None

    def validate(self) -> list[str]:
        """Return human-readable problems (fatal and warnings)."""
        return [f"[{severity}] {message}" for severity, message in self._checks()]

    def fatal_issues(self) -> list[str]:
        return [message for severity, message in self._checks() if severity == "fatal"]

    def warnings(self) -> list[str]:
        return [message for severity, message in self._checks() if severity == "warning"]

    def sanitize(self) -> tuple[CandleSeries, list[str]]:
        """Sort, drop duplicate timestamps and drop unusable rows.

        This is applied by providers so downstream analysis only ever
        sees clean, ascending data. Anything repaired is reported.
        """
        fixed: list[str] = []
        ordered = sorted(self.candles, key=lambda c: c.time)
        if ordered != self.candles:
            fixed.append("candles were not sorted; sorted ascending")
        deduped: list[Candle] = []
        duplicate_count = 0
        for candle in ordered:
            if deduped and deduped[-1].time == candle.time:
                duplicate_count += 1
                deduped[-1] = candle  # keep the most recent revision of the bar
            else:
                deduped.append(candle)
        if duplicate_count:
            fixed.append(f"removed {duplicate_count} duplicate candle(s)")
        usable: list[Candle] = []
        dropped = 0
        for candle in deduped:
            if any(is_missing(v) or not math.isfinite(v) for v in OHLC(candle)):
                dropped += 1
                continue
            usable.append(candle)
        if dropped:
            fixed.append(f"dropped {dropped} candle(s) with missing/non-finite prices")
        return (
            CandleSeries(
                symbol=self.symbol,
                timeframe=self.timeframe,
                source=self.source,
                candles=usable,
                metadata={**self.metadata, "sanitized": True},
            ),
            fixed,
        )

    def is_usable(self, min_bars: int) -> tuple[bool, list[str]]:
        """Whether the series can support analysis at all."""
        reasons: list[str] = []
        if not self.candles:
            reasons.append("no candles available")
        elif len(self.candles) < min_bars:
            reasons.append(
                f"only {len(self.candles)} candles available, {min_bars} required"
            )
        reasons.extend(self.fatal_issues())
        if self.candles and is_missing(self.candles[-1].close):
            reasons.append("last close price is missing")
        return (not reasons, reasons)

    def to_frame(self) -> pd.DataFrame:
        """DataFrame indexed by UTC time with open/high/low/close/volume."""
        columns = ["open", "high", "low", "close", "volume"]
        if not self.candles:
            frame = pd.DataFrame({key: [] for key in columns}, dtype=float)
            frame.index = pd.DatetimeIndex([], name="time")
            return frame
        index = pd.DatetimeIndex([candle.time for candle in self.candles], name="time")
        data = {
            "open": np.array([c.open for c in self.candles], dtype=float),
            "high": np.array([c.high for c in self.candles], dtype=float),
            "low": np.array([c.low for c in self.candles], dtype=float),
            "close": np.array([c.close for c in self.candles], dtype=float),
            "volume": np.array(
                [math.nan if c.volume is None else float(c.volume) for c in self.candles],
                dtype=float,
            ),
        }
        return pd.DataFrame(data, index=index)


def OHLC(candle: Candle) -> tuple[float, float, float, float]:
    return (candle.open, candle.high, candle.low, candle.close)


def slice_last(series: CandleSeries, count: int) -> CandleSeries:
    if count <= 0 or len(series) <= count:
        return series
    return CandleSeries(
        symbol=series.symbol,
        timeframe=series.timeframe,
        source=series.source,
        candles=series.candles[-count:],
        metadata=dict(series.metadata),
    )


def resample_series(series: CandleSeries, target_timeframe: str) -> CandleSeries:
    """Aggregate candles into a higher timeframe (never invents data).

    Resampling a higher timeframe down to a lower one is impossible and
    raises ValidationError.
    """
    target = normalize_timeframe(target_timeframe)
    base_minutes = timeframe_minutes(series.timeframe)
    target_minutes = timeframe_minutes(target)
    if target_minutes < base_minutes:
        raise ValidationError(
            f"cannot resample {series.timeframe} candles down to {target}"
        )
    if not series.candles:
        return CandleSeries(
            symbol=series.symbol,
            timeframe=target,
            source=f"{series.source}+resampled",
            candles=[],
            metadata={**series.metadata, "resampled_from": series.timeframe},
        )
    frame = series.to_frame()
    has_volume = bool(frame["volume"].notna().any())
    aggregation: dict[str, str] = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    if has_volume:
        aggregation["volume"] = "sum"
    resampled = frame.resample(pandas_rule(target)).agg(aggregation)
    resampled = resampled.dropna(subset=["open", "high", "low", "close"])
    candles: list[Candle] = []
    close_values = resampled["close"].to_numpy(dtype=float)
    open_values = resampled["open"].to_numpy(dtype=float)
    high_values = resampled["high"].to_numpy(dtype=float)
    low_values = resampled["low"].to_numpy(dtype=float)
    volume_values = (
        resampled["volume"].to_numpy(dtype=float) if has_volume else None
    )
    for position, timestamp in enumerate(resampled.index):
        volume = None
        if volume_values is not None and not math.isnan(volume_values[position]):
            volume = float(volume_values[position])
        candles.append(
            Candle(
                time=timestamp.to_pydatetime(),
                open=float(open_values[position]),
                high=float(high_values[position]),
                low=float(low_values[position]),
                close=float(close_values[position]),
                volume=volume,
            )
        )
    return CandleSeries(
        symbol=series.symbol,
        timeframe=target,
        source=f"{series.source}+resampled",
        candles=candles,
        metadata={**series.metadata, "resampled_from": series.timeframe},
    )
