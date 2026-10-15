"""Orchestrator: the end-to-end analysis pipeline.

    market data -> validation -> per-timeframe analysis -> MTF -> news
    -> scoring -> decision -> entry scenario -> risk -> report

Never fabricates data: any missing input produces an explicit
INSUFFICIENT/PARTIAL status instead of made-up values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.agent.schemas import (
    INSUFFICIENT,
    PARTIAL,
    SUFFICIENT,
    AnalysisReport,
)
from src.analysis.liquidity import analyze_liquidity
from src.analysis.momentum import analyze_momentum
from src.analysis.multi_timeframe import TFAssessment, analyze_multi_timeframe
from src.analysis.structure import analyze_structure
from src.analysis.support_resistance import analyze_sr
from src.analysis.trend import analyze_trend
from src.analysis.types import Direction
from src.analysis.volatility import analyze_volatility
from src.analysis.volume import analyze_volume
from src.market.candles import CandleSeries
from src.market.data_provider import build_provider_chain
from src.market.symbols import SymbolInfo, resolve_symbol
from src.market.timeframes import (
    assign_roles,
    auto_timeframe_set,
    parse_timeframes,
    timeframe_minutes,
)
from src.news.news_provider import NewsProvider, NewsReport, build_news_provider
from src.risk.calculator import RiskInput, calculate_risk
from src.signal.decision import NO_TRADE, decide
from src.signal.entry_model import build_entry_plan
from src.signal.scorer import score_setup
from src.utils.config import Settings
from src.utils.errors import DataUnavailableError
from src.utils.logging import get_logger

logger = get_logger("orchestrator")


@dataclass
class FetchBundle:
    provider: str
    series: dict[str, CandleSeries] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class Orchestrator:
    def __init__(
        self,
        settings: Settings,
        news_provider: NewsProvider | None = None,
        provider_name: str = "auto",
    ) -> None:
        self.settings = settings
        self.provider_name = provider_name
        self.news_provider = news_provider or build_news_provider(settings)

    # ------------------------------------------------------------------
    def resolve_timeframes(
        self, timeframe: str | None = None, timeframes: str | list[str] | None = None
    ) -> list[str]:
        if timeframes:
            resolved = parse_timeframes(timeframes)
        elif timeframe:
            if self.settings.symbols.auto_multi_timeframe:
                resolved = auto_timeframe_set(timeframe)
            else:
                resolved = parse_timeframes([timeframe])
        else:
            resolved = parse_timeframes(self.settings.symbols.default_timeframes)
        return sorted(resolved, key=timeframe_minutes, reverse=True)

    # ------------------------------------------------------------------
    def fetch(self, info: SymbolInfo, timeframes: list[str], limit: int) -> FetchBundle:
        chain = build_provider_chain(self.settings, info, self.provider_name)
        entry_tf = timeframes[-1]
        errors: list[str] = []
        for provider in chain:
            try:
                entry_series = provider.get_ohlcv(info, entry_tf, limit)
            except DataUnavailableError as exc:
                errors.append(f"{provider.name}: {exc}")
                continue
            usable, reasons = entry_series.is_usable(self.settings.analysis.min_bars)
            if not usable:
                errors.append(f"{provider.name}: " + "; ".join(reasons))
                continue

            bundle = FetchBundle(provider=provider.name)
            bundle.series[entry_tf] = entry_series
            bundle.notes.extend(entry_series.metadata.get("provider_notes", []))
            for tf in timeframes[:-1]:
                try:
                    bundle.series[tf] = provider.get_ohlcv(info, tf, limit)
                    bundle.notes.extend(
                        bundle.series[tf].metadata.get("provider_notes", [])
                    )
                except DataUnavailableError as exc:
                    bundle.missing.append(tf)
                    bundle.notes.append(f"{tf} unavailable from {provider.name}: {exc}")
            bundle.errors = errors
            return bundle
        raise DataUnavailableError(
            "no provider could supply usable data: " + " | ".join(errors[-4:] or ["none tried"])
        )

    # ------------------------------------------------------------------
    def analyze(
        self,
        symbol: str,
        timeframe: str | None = None,
        timeframes: str | list[str] | None = None,
        limit: int | None = None,
        news_now: datetime | None = None,
    ) -> AnalysisReport:
        generated_at = datetime.now(UTC).isoformat()
        info = resolve_symbol(symbol)
        resolved_tfs = self.resolve_timeframes(timeframe, timeframes)
        limit = int(limit or self.settings.providers.default_limit)
        entry_tf = resolved_tfs[-1]

        try:
            bundle = self.fetch(info, resolved_tfs, limit)
        except DataUnavailableError as exc:
            return self._empty_report(info, resolved_tfs, generated_at, str(exc))

        entry = bundle.series[entry_tf]
        roles = assign_roles(resolved_tfs)
        frame = entry.to_frame()
        cfg = self.settings.analysis

        trend = analyze_trend(frame, cfg)
        structure = analyze_structure(frame, cfg)
        volatility = analyze_volatility(frame, cfg)
        momentum = analyze_momentum(frame, cfg)
        volume = analyze_volume(frame)
        sr = analyze_sr(frame, structure.swings, volatility.atr, cfg)
        liquidity = analyze_liquidity(frame, structure.swings, volatility.atr, cfg)

        assessments: list[TFAssessment] = []
        for tf in resolved_tfs:
            series = bundle.series.get(tf)
            if series is None:
                continue
            tf_frame = series.to_frame()
            tf_trend = analyze_trend(tf_frame, cfg)
            tf_structure = analyze_structure(tf_frame, cfg)
            tf_momentum = analyze_momentum(tf_frame, cfg)
            assessments.append(
                TFAssessment(
                    timeframe=tf,
                    role=roles.get(tf, "mtf"),
                    trend=tf_trend.state,
                    structure=tf_structure.trend,
                    momentum=tf_momentum.state,
                    confidence=tf_trend.confidence,
                )
            )
        mtf = analyze_multi_timeframe(assessments, self.settings.decision)

        news = self.news_provider.get_report(info, now=news_now)

        score = score_setup(
            trend,
            structure,
            momentum,
            liquidity,
            sr,
            volatility,
            volume,
            mtf,
            self.settings.scoring,
        )

        decision = decide(
            score,
            mtf,
            volatility,
            news,
            data_ok=True,
            missing=bundle.missing,
            config=self.settings.decision,
        )

        plan = None
        risk = None
        if score.bias is not Direction.NEUTRAL:
            plan = build_entry_plan(
                "LONG" if score.bias is Direction.BULLISH else "SHORT",
                frame,
                structure,
                sr,
                volatility.atr,
                self.settings.risk,
            )
        if plan is not None:
            risk = calculate_risk(
                RiskInput(
                    balance=self.settings.risk.default_balance,
                    risk_pct=self.settings.risk.default_risk_pct,
                    entry=plan.entry_mid,
                    stop=plan.stop_loss,
                    targets=list(plan.targets),
                ),
                max_risk_pct=self.settings.risk.max_risk_pct,
                warn_rr_below=self.settings.risk.warn_rr_below,
                pip_size=info.pip_size,
            )

        warnings: list[str] = []
        warnings.extend(entry.warnings())
        warnings.extend(bundle.notes)
        if volatility.warning:
            warnings.append("VOLATILITY WARNING: " + "; ".join(volatility.notes))
        if not news.known:
            warnings.append(
                "news risk is UNKNOWN - no live news source configured "
                f"({news.reason})"
            )
        if bundle.missing:
            warnings.append(
                "multi-timeframe context incomplete: missing " + ", ".join(bundle.missing)
            )
        if bundle.errors:
            warnings.append(
                "provider fallback notes: " + " | ".join(bundle.errors[-2:])
            )
        if plan is not None and plan.rr_values and plan.rr_values[0] < self.settings.risk.warn_rr_below:
            warnings.append(
                f"TP1 R:R is {plan.rr_values[0]:.2f} - consider a better price before acting"
            )

        data_status = PARTIAL if bundle.missing else SUFFICIENT
        price = entry.last_close()
        price_note = f"{bundle.provider} {entry_tf} close"
        if entry.end is not None:
            price_note += f" ({entry.end.isoformat()})"

        return AnalysisReport(
            symbol=info.symbol,
            asset_class=info.asset_class,
            timeframe=entry_tf,
            timeframes=resolved_tfs,
            data_status=data_status,
            data_reasons=[],
            data_warnings=entry.warnings(),
            provider=bundle.provider,
            provider_notes=bundle.notes,
            candle_count=len(entry),
            price=price,
            price_note=price_note,
            last_candle_time=entry.end.isoformat() if entry.end else None,
            trend=trend,
            structure=structure,
            sr=sr,
            liquidity=liquidity,
            momentum=momentum,
            volatility=volatility,
            volume=volume,
            mtf=mtf,
            news=news,
            score=score,
            decision=decision,
            entry=plan,
            risk=risk,
            warnings=warnings,
            generated_at=generated_at,
            config_path=str(self.settings.config_path) if self.settings.config_path else None,
        )

    # ------------------------------------------------------------------
    def latest_price(self, symbol: str) -> tuple[float, str, str]:
        """Return (price, provenance, provider) using the provider chain."""
        info = resolve_symbol(symbol)
        chain = build_provider_chain(self.settings, info, self.provider_name)
        errors: list[str] = []
        for provider in chain:
            try:
                price, note = provider.get_latest_price_detail(info)
                return price, note, provider.name
            except DataUnavailableError as exc:
                errors.append(f"{provider.name}: {exc}")
        raise DataUnavailableError(
            "latest price unavailable: " + " | ".join(errors[-3:] or ["no providers"])
        )

    # ------------------------------------------------------------------
    def _empty_report(
        self,
        info: SymbolInfo,
        timeframes: list[str],
        generated_at: str,
        reason: str,
    ) -> AnalysisReport:
        entry_tf = timeframes[-1]
        return AnalysisReport(
            symbol=info.symbol,
            asset_class=info.asset_class,
            timeframe=entry_tf,
            timeframes=timeframes,
            data_status=INSUFFICIENT,
            data_reasons=[reason],
            data_warnings=[],
            provider="none",
            provider_notes=[],
            candle_count=0,
            price=None,
            price_note="unavailable",
            last_candle_time=None,
            trend=None,
            structure=None,
            sr=None,
            liquidity=None,
            momentum=None,
            volatility=None,
            volume=None,
            mtf=None,
            news=NewsReport(
                risk_level="UNKNOWN",
                source="none",
                reason="not queried - no market data",
            ),
            score=None,
            decision=_no_trade_decision(reason),
            entry=None,
            risk=None,
            warnings=["NO TRADE - INSUFFICIENT DATA"],
            generated_at=generated_at,
            config_path=str(self.settings.config_path) if self.settings.config_path else None,
        )


def _no_trade_decision(reason: str):
    from src.signal.decision import DecisionResult

    return DecisionResult(
        signal=NO_TRADE,
        bias=Direction.NEUTRAL,
        reasons=[f"INSUFFICIENT DATA - {reason}"],
        blocked_by="data",
    )
