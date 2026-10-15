"""Rule-based walk-forward backtester.

What it does
    Replays the SAME analysis -> score -> decision -> entry-plan pipeline
    bar by bar using only information available at each bar close, then
    fills pending entry orders when price trades into the entry zone.

Honest limitations (always reported in the result)
    - No spread, slippage, commissions, swaps or margin modelling.
    - If one candle touches both stop and target, the STOP is assumed
      first (worst case).
    - Analysis is single-timeframe unless the caller resamples first;
      the news filter is disabled (status UNKNOWN) during replay.
    - The entry timeframe's own data quality limits everything.

This is a sanity-check tool, NOT evidence of future performance.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pandas as pd

from src.analysis.liquidity import analyze_liquidity
from src.analysis.momentum import analyze_momentum
from src.analysis.multi_timeframe import TFAssessment, analyze_multi_timeframe
from src.analysis.structure import analyze_structure
from src.analysis.support_resistance import analyze_sr
from src.analysis.trend import analyze_trend
from src.analysis.types import Direction, VolatilityClass
from src.analysis.volatility import analyze_volatility
from src.analysis.volume import analyze_volume
from src.market.candles import CandleSeries
from src.news.news_provider import NewsReport
from src.paper.account import AccountStore
from src.paper.broker import PaperBroker, PaperStats, compute_stats
from src.signal.decision import decide
from src.signal.entry_model import build_entry_plan
from src.signal.scorer import score_setup
from src.utils.config import Settings
from src.utils.errors import InsufficientDataError
from src.utils.logging import get_logger

logger = get_logger("backtest")

PENDING_EXPIRY_BARS = 10
DEFAULT_MAX_BARS = 800


@dataclass
class BacktestTrade:
    side: str
    entry_time: str | None
    exit_time: str | None
    entry_price: float
    exit_price: float | None
    stop_loss: float | None
    take_profit: float | None
    size: float
    pnl: float
    reason: str | None

    def as_dict(self) -> dict:
        return {
            "side": self.side,
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "entry_price": round(self.entry_price, 6),
            "exit_price": round(self.exit_price, 6) if self.exit_price else None,
            "stop_loss": round(self.stop_loss, 6) if self.stop_loss else None,
            "take_profit": round(self.take_profit, 6) if self.take_profit else None,
            "size": round(self.size, 4),
            "pnl": round(self.pnl, 2),
            "reason": self.reason,
        }


@dataclass
class BacktestResult:
    symbol: str
    timeframe: str
    provider: str
    bars: int
    evaluated_bars: int
    signals_generated: int
    orders_filled: int
    stats: PaperStats
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "provider": self.provider,
            "bars": self.bars,
            "evaluated_bars": self.evaluated_bars,
            "signals_generated": self.signals_generated,
            "orders_filled": self.orders_filled,
            "stats": self.stats.as_dict(),
            "trades": [trade.as_dict() for trade in self.trades],
            "equity_curve": [round(value, 2) for value in self.equity_curve[-200:]],
            "limitations": self.limitations,
            "notes": self.notes,
        }


def _evaluate_window(frame: pd.DataFrame, settings: Settings, timeframe: str):
    trend = analyze_trend(frame, settings.analysis)
    structure = analyze_structure(frame, settings.analysis)
    momentum = analyze_momentum(frame, settings.analysis)
    volatility = analyze_volatility(frame, settings.analysis)
    volume = analyze_volume(frame)
    sr = analyze_sr(frame, structure.swings, volatility.atr, settings.analysis)
    liquidity = analyze_liquidity(
        frame, structure.swings, volatility.atr, settings.analysis
    )
    assessment = TFAssessment(
        timeframe=timeframe,
        role="ltf",
        trend=trend.state,
        structure=structure.trend,
        momentum=momentum.state,
    )
    mtf = analyze_multi_timeframe([assessment], settings.decision)
    score = score_setup(
        trend, structure, momentum, liquidity, sr, volatility, volume, mtf,
        settings.scoring,
    )
    return structure, sr, volatility, score, mtf


def run_backtest(
    series: CandleSeries,
    settings: Settings,
    provider_name: str = "unknown",
    max_bars: int = DEFAULT_MAX_BARS,
) -> BacktestResult:
    frame = series.to_frame()
    warmup = max(
        settings.analysis.min_bars,
        settings.analysis.macd_slow + settings.analysis.macd_signal + 10,
        settings.analysis.ema_slow + 10,
    )
    if len(frame) < warmup + 30:
        raise InsufficientDataError(
            f"backtest needs at least {warmup + 30} candles, got {len(frame)}"
        )
    truncated = False
    if len(frame) > max_bars + warmup:
        frame = frame.tail(max_bars + warmup)
        truncated = True
    notes: list[str] = []
    if truncated:
        notes.append(
            f"only the most recent {max_bars + warmup} candles were replayed "
            "(increase --bars to extend)"
        )

    store = AccountStore(None, starting_balance=settings.paper.starting_balance)
    broker = PaperBroker(store, persist=False)

    closes = frame["close"].to_numpy(dtype=float)
    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    times = [ts.to_pydatetime() for ts in frame.index]

    pending: dict | None = None
    signals = 0
    fills = 0
    equity_curve: list[float] = []
    spuriously_insufficient = 0

    for i in range(warmup, len(frame)):
        candle_time = times[i]
        close = float(closes[i])

        # 1) existing positions may hit SL/TP on this candle
        candle = series.candles[-len(frame) + i]
        broker.process_candle(series.symbol, candle)

        # 2) pending entry order may fill on this candle
        if pending is not None:
            if i > pending["expires_at"]:
                pending = None
                notes.append(f"pending order either expired or cancelled near bar {i}")
            else:
                if pending["side"] == "LONG":
                    if lows[i] <= pending["entry_price"] <= highs[i]:
                        broker.open_position(
                            symbol=series.symbol,
                            side="LONG",
                            size=pending["size"],
                            entry_price=pending["entry_price"],
                            stop_loss=pending["stop_loss"],
                            take_profit=pending["take_profit"],
                            timeframe=series.timeframe,
                            note="backtest",
                            opened_at=candle_time.isoformat(),
                        )
                        fills += 1
                        pending = None
                else:
                    if lows[i] <= pending["entry_price"] <= highs[i]:
                        broker.open_position(
                            symbol=series.symbol,
                            side="SHORT",
                            size=pending["size"],
                            entry_price=pending["entry_price"],
                            stop_loss=pending["stop_loss"],
                            take_profit=pending["take_profit"],
                            timeframe=series.timeframe,
                            note="backtest",
                            opened_at=candle_time.isoformat(),
                        )
                        fills += 1
                        pending = None

        # 3) evaluate a new signal when flat
        if pending is None and not broker.state.open_positions:
            window = frame.iloc[: i + 1]
            try:
                structure, sr, volatility, score, mtf = _evaluate_window(
                    window, settings, series.timeframe
                )
            except (ValueError, ZeroDivisionError):
                spuriously_insufficient += 1
                window = None
            if window is not None and volatility.classification is not VolatilityClass.INSUFFICIENT_DATA:
                news = NewsReport(risk_level="UNKNOWN", source="none", reason="disabled during backtest")
                decision = decide(
                    score, mtf, volatility, news,
                    data_ok=True, missing=[], config=settings.decision,
                )
                if decision.is_tradeable and score.bias is not Direction.NEUTRAL:
                    signals += 1
                    plan = build_entry_plan(
                        "LONG" if score.bias is Direction.BULLISH else "SHORT",
                        window,
                        structure,
                        sr,
                        volatility.atr,
                        settings.risk,
                    )
                    if plan is not None and plan.rr_values and plan.rr_values[0] > 0:
                        risk_distance = abs(plan.entry_mid - plan.stop_loss)
                        risk_cash = broker.state.balance * (
                            settings.risk.default_risk_pct / 100.0
                        )
                        size = risk_cash / risk_distance if risk_distance > 0 else 0.0
                        if size > 0:
                            pending = {
                                "side": plan.side,
                                "entry_price": plan.entry_mid,
                                "stop_loss": plan.stop_loss,
                                "take_profit": plan.targets[0] if plan.targets else None,
                                "size": size,
                                "expires_at": i + PENDING_EXPIRY_BARS,
                            }

        # 4) mark-to-market equity after this bar
        equity_curve.append(broker.state.equity({series.symbol: close}))

    # close anything still open at the last close
    last_close = float(closes[-1])
    for position in list(broker.state.open_positions):
        broker.close_position(position.id, last_close, reason="BACKTEST_END")
    if equity_curve:
        equity_curve.append(broker.state.balance)

    stats = compute_stats(broker.state)
    trades = [
        BacktestTrade(
            side=trade.side,
            entry_time=trade.opened_at,
            exit_time=trade.exit_at,
            entry_price=trade.entry_price,
            exit_price=trade.exit_price,
            stop_loss=trade.stop_loss,
            take_profit=trade.take_profit,
            size=trade.size,
            pnl=float(trade.pnl or 0.0),
            reason=trade.close_reason,
        )
        for trade in broker.state.trades
    ]

    limitations = [
        "no spread, slippage, commission or swap modelling",
        "stop assumed to fill before target when both touch the same candle",
        "single-timeframe analysis; news filter disabled during replay",
        "entries fill only when price trades into the entry zone within 10 bars",
        "historical results are not evidence of future performance",
    ]
    if spuriously_insufficient:
        notes.append(f"{spuriously_insufficient} bar(s) skipped due to calculation issues")
    if not trades:
        notes.append("no trades were taken - thresholds may be too strict for this sample")

    return BacktestResult(
        symbol=series.symbol,
        timeframe=series.timeframe,
        provider=provider_name,
        bars=len(frame),
        evaluated_bars=max(0, len(frame) - warmup),
        signals_generated=signals,
        orders_filled=fills,
        stats=stats,
        trades=trades,
        equity_curve=equity_curve,
        limitations=limitations,
        notes=notes,
    )
