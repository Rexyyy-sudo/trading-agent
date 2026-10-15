"""Generate SYNTHETIC OHLCV CSV files for offline demos and tests.

The data produced by this script is SIMULATED - it is NOT real market
data and must never be used for real trading decisions. It exists so
the pipeline can be exercised without internet access or API keys.

Example:
    python scripts/make_synthetic_csv.py --symbol XAUUSD --timeframes H1,M15,M5 --bars 400
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.market.candles import Candle, CandleSeries  # noqa: E402
from src.market.providers.csv_provider import save_series_csv  # noqa: E402
from src.market.timeframes import normalize_timeframe, timeframe_minutes  # noqa: E402

START_PRICE = {"XAUUSD": 2350.0, "EURUSD": 1.0850, "USDJPY": 155.0, "BTCUSDT": 65000.0}


def synthetic_closes(symbol: str, bars: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    price = START_PRICE.get(symbol, 100.0)
    scale = price * 0.001
    closes: list[float] = []
    drift = 0.0
    for index in range(bars):
        if index % 40 == 0:
            drift = rng.uniform(-1.0, 1.0) * scale * 0.1
        wave = math.sin(index / 17.0) * scale * 0.6
        noise = rng.gauss(0.0, scale * 0.45)
        price = max(price + drift + wave * 0.15 + noise, scale)
        closes.append(round(price, 5))
    return closes


def build_series(symbol: str, timeframe: str, bars: int, seed: int) -> CandleSeries:
    closes = synthetic_closes(symbol, bars, seed)
    spacing = timeframe_minutes(normalize_timeframe(timeframe))
    start = datetime(2026, 1, 1, tzinfo=UTC)
    rng = random.Random(seed + 1)
    candles: list[Candle] = []
    for index, close in enumerate(closes):
        open_ = closes[index - 1] if index else close
        wick = abs(rng.gauss(0.0, 0.35)) * abs(close - open_ + 1e-9)
        high = max(open_, close) + wick
        low = min(open_, close) - wick
        volume = float(rng.randint(500, 5000))
        candles.append(
            Candle(
                time=start + timedelta(minutes=spacing * index),
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=volume,
            )
        )
    return CandleSeries(symbol=symbol, timeframe=timeframe, source="synthetic:demo", candles=candles)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate SYNTHETIC CSV candles (demo only).")
    parser.add_argument("--symbol", default="XAUUSD")
    parser.add_argument("--timeframes", default="H1,M15,M5")
    parser.add_argument("--bars", type=int, default=400)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out-dir", default=str(PROJECT_ROOT / "data" / "raw"))
    args = parser.parse_args()

    symbol = args.symbol.upper()
    out_dir = Path(args.out_dir)
    for offset, timeframe in enumerate(args.timeframes.split(",")):
        tf = normalize_timeframe(timeframe.strip())
        series = build_series(symbol, tf, args.bars, args.seed + offset)
        path = save_series_csv(series, out_dir / f"{symbol}_{tf}.csv")
        print(f"wrote {path} ({len(series)} bars)")
    print("WARNING: these CSVs are SYNTHETIC demo data - not real market data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
