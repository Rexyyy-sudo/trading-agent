"""POTENTIAL liquidity analysis.

IMPORTANT: broker orders and stop-loss clusters are NOT observable from
OHLCV data. Everything here is a *potential* liquidity area inferred
from swing levels, equal highs/lows and wick sweeps.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.analysis.structure import SwingPoint
from src.analysis.types import Direction
from src.utils.config import AnalysisConfig

BUYSIDE = "BUYSIDE"
SELLSIDE = "SELLSIDE"


@dataclass
class LiquidityPool:
    side: str  # BUYSIDE (above price) | SELLSIDE (below price)
    lower: float
    upper: float
    label: str  # EQUAL_HIGHS | EQUAL_LOWS | RECENT_SWING_HIGH | RECENT_SWING_LOW
    touches: int
    formed_index: int
    is_swept: bool = False

    @property
    def level(self) -> float:
        return (self.lower + self.upper) / 2

    def as_dict(self) -> dict:
        return {
            "side": self.side,
            "label": self.label,
            "lower": round(self.lower, 6),
            "upper": round(self.upper, 6),
            "touches": self.touches,
            "is_swept": self.is_swept,
            "potential": True,
        }


@dataclass
class LiquidityResult:
    pools: list[LiquidityPool] = field(default_factory=list)
    last_sweep: Direction | None = None
    last_sweep_index: int | None = None
    nearest_buyside: LiquidityPool | None = None
    nearest_sellside: LiquidityPool | None = None
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "pools": [pool.as_dict() for pool in self.pools],
            "last_sweep": self.last_sweep.value if self.last_sweep else None,
            "nearest_buyside": (
                self.nearest_buyside.as_dict() if self.nearest_buyside else None
            ),
            "nearest_sellside": (
                self.nearest_sellside.as_dict() if self.nearest_sellside else None
            ),
            "notes": self.notes,
        }


def _cluster_equal(points: list[SwingPoint], tolerance: float) -> list[list[SwingPoint]]:
    if not points:
        return []
    ordered = sorted(points, key=lambda point: point.price)
    clusters: list[list[SwingPoint]] = [[ordered[0]]]
    for point in ordered[1:]:
        if abs(point.price - clusters[-1][-1].price) <= tolerance:
            clusters[-1].append(point)
        else:
            clusters.append([point])
    return clusters


def _find_sweeps(
    frame: pd.DataFrame, pools: list[LiquidityPool], lookback: int
) -> None:
    """Mark pools that were wicked through and closed back inside."""
    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    closes = frame["close"].to_numpy(dtype=float)
    start = max(0, len(frame) - lookback)
    for pool in pools:
        for i in range(start, len(frame)):
            if i <= pool.formed_index:
                continue
            if pool.side == BUYSIDE:
                if highs[i] > pool.upper and closes[i] < pool.upper:
                    pool.is_swept = True
                    break
            else:
                if lows[i] < pool.lower and closes[i] > pool.lower:
                    pool.is_swept = True
                    break


def analyze_liquidity(
    frame: pd.DataFrame,
    swings: list[SwingPoint],
    atr_value: float | None,
    config: AnalysisConfig,
) -> LiquidityResult:
    result = LiquidityResult()
    if frame.empty or not swings:
        result.notes.append("insufficient swing data for liquidity analysis")
        return result
    price = float(frame["close"].iloc[-1])
    if not atr_value or atr_value <= 0:
        atr_value = price * 0.002
        result.notes.append("ATR unavailable - using 0.2% of price as tolerance")
    tolerance = atr_value * config.equal_level_tolerance_atr

    highs = [swing for swing in swings if swing.kind == "HIGH"]
    lows = [swing for swing in swings if swing.kind == "LOW"]
    pools: list[LiquidityPool] = []

    for cluster in _cluster_equal(highs, tolerance):
        prices = [point.price for point in cluster]
        last_index = max(point.index for point in cluster)
        if len(cluster) >= 2:
            pools.append(
                LiquidityPool(
                    side=BUYSIDE,
                    lower=min(prices),
                    upper=max(prices),
                    label="EQUAL_HIGHS",
                    touches=len(cluster),
                    formed_index=last_index,
                )
            )

    for cluster in _cluster_equal(lows, tolerance):
        prices = [point.price for point in cluster]
        last_index = max(point.index for point in cluster)
        if len(cluster) >= 2:
            pools.append(
                LiquidityPool(
                    side=SELLSIDE,
                    lower=min(prices),
                    upper=max(prices),
                    label="EQUAL_LOWS",
                    touches=len(cluster),
                    formed_index=last_index,
                )
            )

    recent_count = max(1, config.liquidity_lookback_swings // 4)
    for swing in highs[-recent_count:]:
        if not any(
            pool.side == BUYSIDE and pool.lower <= swing.price <= pool.upper for pool in pools
        ):
            pools.append(
                LiquidityPool(
                    side=BUYSIDE,
                    lower=swing.price,
                    upper=swing.price,
                    label="RECENT_SWING_HIGH",
                    touches=1,
                    formed_index=swing.index,
                )
            )
    for swing in lows[-recent_count:]:
        if not any(
            pool.side == SELLSIDE and pool.lower <= swing.price <= pool.upper for pool in pools
        ):
            pools.append(
                LiquidityPool(
                    side=SELLSIDE,
                    lower=swing.price,
                    upper=swing.price,
                    label="RECENT_SWING_LOW",
                    touches=1,
                    formed_index=swing.index,
                )
            )

    _find_sweeps(frame, pools, lookback=min(len(frame), 60))

    swept = [pool for pool in pools if pool.is_swept]
    if swept:
        latest = max(swept, key=lambda pool: pool.formed_index)
        result.last_sweep = (
            Direction.BEARISH if latest.side == BUYSIDE else Direction.BULLISH
        )
        result.last_sweep_index = latest.formed_index
        direction = "sell-side" if latest.side == SELLSIDE else "buy-side"
        result.notes.append(
            f"potential {direction} liquidity sweep detected around "
            f"{latest.level:.5f} (wick through, close back inside)"
        )

    buyside = [pool for pool in pools if pool.side == BUYSIDE and pool.upper > price]
    sellside = [pool for pool in pools if pool.side == SELLSIDE and pool.lower < price]
    if buyside:
        result.nearest_buyside = min(buyside, key=lambda pool: pool.upper)
    if sellside:
        result.nearest_sellside = max(sellside, key=lambda pool: pool.lower)

    pools.sort(key=lambda pool: (pool.side, pool.formed_index), reverse=True)
    result.pools = pools[:12]
    result.notes.append("liquidity levels are POTENTIAL areas inferred from price action")
    return result
