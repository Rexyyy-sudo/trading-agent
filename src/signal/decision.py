"""Deterministic decision engine.

States:
    LONG       - bullish evidence strong AND confirmations pass
    SHORT      - bearish evidence strong AND confirmations pass
    WAIT       - evidence conflicts, is weak, or conditions are risky
    NO TRADE   - data insufficient or extreme macro risk

The exact gates are configurable in config/settings.yaml (decision:).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.analysis.multi_timeframe import MTFResult
from src.analysis.types import Direction, VolatilityClass
from src.analysis.volatility import VolatilityResult
from src.news.news_provider import EXTREME, HIGH, NewsReport
from src.signal.scorer import ScoreResult
from src.utils.config import DecisionConfig

LONG = "LONG"
SHORT = "SHORT"
WAIT = "WAIT"
NO_TRADE = "NO TRADE"


@dataclass
class DecisionResult:
    signal: str
    bias: Direction
    reasons: list[str] = field(default_factory=list)
    blocked_by: str | None = None

    @property
    def is_tradeable(self) -> bool:
        return self.signal in (LONG, SHORT)

    def as_dict(self) -> dict:
        return {
            "signal": self.signal,
            "bias": self.bias.value,
            "reasons": self.reasons,
            "blocked_by": self.blocked_by,
        }


def decide(
    score: ScoreResult,
    mtf: MTFResult,
    volatility: VolatilityResult,
    news: NewsReport,
    data_ok: bool,
    missing: list[str],
    config: DecisionConfig,
) -> DecisionResult:
    reasons: list[str] = []
    bias = score.bias

    if not data_ok:
        detail = "; ".join(missing[:3]) if missing else "no usable market data"
        return DecisionResult(
            signal=NO_TRADE,
            bias=bias,
            reasons=[f"INSUFFICIENT DATA - {detail}"],
            blocked_by="data",
        )

    # --- macro risk gates -------------------------------------------------
    if news.risk_level == EXTREME:
        return DecisionResult(
            signal=config.news_extreme,
            bias=bias,
            reasons=[
                "extreme macro-event risk in the near future",
                f"news source: {news.source} ({news.reason})",
            ],
            blocked_by="news",
        )
    if news.risk_level == HIGH:
        reasons.append(
            f"high-impact macro event nearby (news source: {news.source})"
        )

    # --- volatility gate --------------------------------------------------
    if volatility.classification is VolatilityClass.EXTREME:
        return DecisionResult(
            signal=config.volatility_extreme,
            bias=bias,
            reasons=reasons
            + [
                "volatility is EXTREME - entries are unreliable",
                "wait for volatility to normalise before re-evaluating",
            ],
            blocked_by="volatility",
        )

    # --- insufficient score ----------------------------------------------
    if bias is Direction.NEUTRAL:
        reasons.append(
            f"bias is unclear (score {score.score:.0f}, label {score.label})"
        )
        return DecisionResult(
            signal=WAIT, bias=bias, reasons=reasons, blocked_by="bias"
        )

    # --- confirmation gates ----------------------------------------------
    threshold = (
        config.long_threshold if bias is Direction.BULLISH else config.short_threshold
    )
    required = mtf.required
    aligned = mtf.aligned_with(bias)
    mtf_known = mtf.alignment != "INSUFFICIENT_DATA"

    if score.score < threshold:
        reasons.append(
            f"score {score.score:.0f} is below the {threshold:.0f} threshold for "
            f"{'longs' if bias is Direction.BULLISH else 'shorts'}"
        )
        return DecisionResult(
            signal=WAIT, bias=bias, reasons=reasons, blocked_by="score"
        )

    if mtf_known and mtf.conflict:
        reasons.append("timeframes conflict with the higher-timeframe bias")
        return DecisionResult(
            signal=WAIT, bias=bias, reasons=reasons, blocked_by="mtf"
        )

    if mtf_known and aligned < required:
        reasons.append(
            f"only {aligned} of {required} required timeframes align with the bias"
        )
        return DecisionResult(
            signal=WAIT, bias=bias, reasons=reasons, blocked_by="mtf"
        )

    if (
        config.ltf_confirmation_required
        and mtf_known
        and not mtf.ltf_confirms(bias)
    ):
        reasons.append("entry timeframe has not confirmed the bias yet")
        return DecisionResult(
            signal=WAIT, bias=bias, reasons=reasons, blocked_by="confirmation"
        )

    if not mtf_known:
        reasons.append("multi-timeframe alignment unavailable - single timeframe view")

    reasons.append(
        f"{bias.value.lower()} evidence at score {score.score:.0f} ({score.label}) "
        f"with confirmations passing"
    )
    if news.risk_level == HIGH:
        reasons.append("reduce size or wait for the macro event to pass")
    return DecisionResult(
        signal=LONG if bias is Direction.BULLISH else SHORT,
        bias=bias,
        reasons=reasons,
    )
