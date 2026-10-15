"""Structured output schemas for analysis reports.

Every report is JSON-serialisable via `to_dict()` so CLI tools, tests
and the OpenCode tool layer can consume the same structure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.analysis.liquidity import LiquidityResult
from src.analysis.momentum import MomentumResult
from src.analysis.multi_timeframe import MTFResult
from src.analysis.structure import StructureResult
from src.analysis.support_resistance import SRResult
from src.analysis.trend import TrendResult
from src.analysis.volatility import VolatilityResult
from src.analysis.volume import VolumeResult
from src.news.news_provider import NewsReport
from src.risk.calculator import RiskResult
from src.signal.decision import DecisionResult
from src.signal.entry_model import EntryPlan
from src.signal.scorer import ScoreResult

SUFFICIENT = "SUFFICIENT"
PARTIAL = "PARTIAL"
INSUFFICIENT = "INSUFFICIENT"


@dataclass
class AnalysisReport:
    symbol: str
    asset_class: str
    timeframe: str
    timeframes: list[str]
    data_status: str
    data_reasons: list[str]
    data_warnings: list[str]
    provider: str
    provider_notes: list[str]
    candle_count: int
    price: float | None
    price_note: str
    last_candle_time: str | None
    trend: TrendResult | None
    structure: StructureResult | None
    sr: SRResult | None
    liquidity: LiquidityResult | None
    momentum: MomentumResult | None
    volatility: VolatilityResult | None
    volume: VolumeResult | None
    mtf: MTFResult | None
    news: NewsReport
    score: ScoreResult | None
    decision: DecisionResult
    entry: EntryPlan | None
    risk: RiskResult | None
    warnings: list[str] = field(default_factory=list)
    generated_at: str = ""
    config_path: str | None = None

    @property
    def has_signal(self) -> bool:
        return self.decision.is_tradeable

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "asset_class": self.asset_class,
            "timeframe": self.timeframe,
            "timeframes": self.timeframes,
            "data_status": self.data_status,
            "data_reasons": self.data_reasons,
            "data_warnings": self.data_warnings,
            "provider": self.provider,
            "provider_notes": self.provider_notes,
            "candle_count": self.candle_count,
            "price": self.price,
            "price_note": self.price_note,
            "last_candle_time": self.last_candle_time,
            "trend": self.trend.as_dict() if self.trend else None,
            "structure": self.structure.as_dict() if self.structure else None,
            "support_resistance": self.sr.as_dict() if self.sr else None,
            "liquidity": self.liquidity.as_dict() if self.liquidity else None,
            "momentum": self.momentum.as_dict() if self.momentum else None,
            "volatility": self.volatility.as_dict() if self.volatility else None,
            "volume": self.volume.as_dict() if self.volume else None,
            "multi_timeframe": self.mtf.as_dict() if self.mtf else None,
            "news": self.news.as_dict(),
            "score": self.score.as_dict() if self.score else None,
            "decision": self.decision.as_dict(),
            "entry": self.entry.as_dict() if self.entry else None,
            "risk": self.risk.as_dict() if self.risk else None,
            "warnings": self.warnings,
            "generated_at": self.generated_at,
            "config_path": self.config_path,
            "disclaimer": (
                "Educational analysis only. Not financial advice. "
                "No outcome is guaranteed. Verify all levels before acting."
            ),
        }
