"""Local CSV provider (fully offline).

Expected file: <csv_dir>/<SYMBOL>_<TIMEFRAME>.csv
Header (case-insensitive): time,open,high,low,close[,volume]
`time` accepts ISO strings or epoch seconds/milliseconds.

No file -> no data. The provider never fabricates rows.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.market.candles import CandleSeries
from src.market.data_provider import Availability, MarketDataProvider
from src.market.symbols import SymbolInfo
from src.market.timeframes import normalize_timeframe, timeframe_minutes
from src.utils.errors import ProviderError
from src.utils.logging import get_logger

logger = get_logger("provider.csv")

_TIME_COLUMNS = ("time", "datetime", "date", "timestamp", "open_time")
_REQUIRED = ("open", "high", "low", "close")


def save_series_csv(series: CandleSeries, path: Path) -> Path:
    """Persist a candle series as CSV (used by `fetch` and tests)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "time": candle.time.isoformat(),
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": "" if candle.volume is None else candle.volume,
        }
        for candle in series.candles
    ]
    pd.DataFrame(rows).to_csv(path, index=False)
    return path


class CSVProvider(MarketDataProvider):
    name = "csv"
    display_name = "Local CSV files"

    def csv_dir(self) -> Path:
        return self.settings.resolve_path(self.settings.providers.csv_dir)

    def availability(self) -> Availability:
        directory = self.csv_dir()
        if not directory.is_dir():
            return Availability(False, f"directory not found: {directory}")
        if not any(directory.glob("*.csv")):
            return Availability(False, f"no CSV files in {directory}")
        return Availability(True, f"reading CSV files from {directory}")

    def supports_symbol(self, info: SymbolInfo) -> bool:
        return True

    def _candidate_paths(self, info: SymbolInfo, timeframe: str) -> list[Path]:
        directory = self.csv_dir()
        symbol = info.symbol
        tf = normalize_timeframe(timeframe)
        names = [
            f"{symbol}_{tf}.csv",
            f"{symbol.lower()}_{tf.lower()}.csv",
            f"{symbol}_{tf.lower()}.csv",
            f"{symbol.lower()}_{tf}.csv",
        ]
        return [directory / name for name in names]

    def file_for(self, info: SymbolInfo, timeframe: str) -> Path:
        for candidate in self._candidate_paths(info, timeframe):
            if candidate.is_file():
                return candidate
        expected = self._candidate_paths(info, timeframe)[0]
        raise ProviderError(
            f"CSV data for {info.symbol} {timeframe} not found. "
            f"Expected a file like {expected.name} inside {self.csv_dir()}. "
            "Tip: fetch data first, e.g. "
            f"`python -m src.main fetch {info.symbol} --timeframe {timeframe} --provider yahoo`."
        )

    def fetch_ohlcv(self, info: SymbolInfo, timeframe: str, limit: int) -> CandleSeries:
        path = self.file_for(info, timeframe)
        try:
            frame = pd.read_csv(path)
        except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            raise ProviderError(f"cannot read CSV {path.name}: {exc}") from exc
        if frame.empty:
            raise ProviderError(f"CSV {path.name} is empty")

        frame.columns = [str(column).strip().lower().replace(" ", "_") for column in frame.columns]
        time_column = next((c for c in _TIME_COLUMNS if c in frame.columns), None)
        if time_column is None:
            raise ProviderError(
                f"malformed CSV {path.name}: no time column found "
                f"(expected one of {', '.join(_TIME_COLUMNS)})"
            )
        missing = [column for column in _REQUIRED if column not in frame.columns]
        if missing:
            raise ProviderError(
                f"malformed CSV {path.name}: missing column(s) {', '.join(missing)}"
            )

        frame = frame.rename(columns={time_column: "time"})
        if "volume" in frame.columns:
            frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
        for column in _REQUIRED:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        frame = frame.dropna(subset=["time", "open", "high", "low", "close"])
        if frame.empty:
            raise ProviderError(f"malformed CSV {path.name}: no usable rows after parsing")
        if limit and limit > 0:
            frame = frame.tail(int(limit))

        rows = frame.to_dict("records")
        try:
            series = CandleSeries.from_rows(
                symbol=info.symbol,
                timeframe=timeframe,
                source=f"csv:{path.name}",
                rows=rows,
                metadata={"live": False, "file": str(path)},
            )
        except Exception as exc:  # noqa: BLE001 - converted to provider error
            raise ProviderError(f"malformed CSV {path.name}: {exc}") from exc

        note = self._interval_note(series, normalize_timeframe(timeframe))
        if note:
            series.metadata.setdefault("provider_notes", []).append(note)
        return series

    @staticmethod
    def _interval_note(series: CandleSeries, declared: str) -> str | None:
        if len(series) < 5:
            return None
        median = series._median_interval_seconds()
        if median is None:
            return None
        expected = timeframe_minutes(declared) * 60
        if abs(median - expected) > expected * 0.5:
            detected_minutes = median / 60
            return (
                f"file '{series.source}' declared as {declared} but the median bar "
                f"spacing is {detected_minutes:.1f} minutes"
            )
        return None

    def get_latest_price_detail(self, info: SymbolInfo) -> tuple[float, str]:
        """Latest close from the newest CSV available for this symbol."""
        candidates: list[tuple[float, Path, str]] = []
        directory = self.csv_dir()
        if directory.is_dir():
            for path in directory.glob("*.csv"):
                stem = path.stem
                parts = stem.upper().split("_")
                if len(parts) >= 2 and parts[0] == info.symbol:
                    tf = parts[-1]
                    try:
                        normalize_timeframe(tf)
                    except Exception:  # noqa: BLE001
                        continue
                    candidates.append((path.stat().st_mtime, path, tf))
        if not candidates:
            raise ProviderError(
                f"no CSV files found for {info.symbol} in {directory}"
            )
        candidates.sort(reverse=True)
        _, path, tf = candidates[0]
        series = self.fetch_ohlcv(info, tf, 5)
        price = series.last_close()
        if price is None:
            raise ProviderError(f"latest CSV {path.name} has no close price")
        return price, f"csv {path.name} last close"
