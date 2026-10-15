"""Multi-timeframe analysis.

Combines per-timeframe trend/structure/momentum into an alignment view.
The framework NEVER forces a trade when timeframes disagree.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.analysis.types import Direction, MomentumState
from src.utils.config import DecisionConfig
from src.utils.validation import clamp

ALIGNED_BULLISH = "ALIGNED_BULLISH"
ALIGNED_BEARISH = "ALIGNED_BEARISH"
MIXED = "MIXED"
CONFLICT = "CONFLICT"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

_VOTE_THRESHOLD = 0.25


@dataclass
class TFAssessment:
    timeframe: str
    role: str  # htf | mtf | ltf
    trend: Direction = Direction.INSUFFICIENT_DATA
    structure: Direction = Direction.INSUFFICIENT_DATA
    momentum: MomentumState = MomentumState.INSUFFICIENT_DATA
    confidence: float = 0.5

    @property
    def direction_score(self) -> float:
        """Signed agreement score in -1..1 for this timeframe."""
        components: list[tuple[float, int]] = []
        if self.trend is not Direction.INSUFFICIENT_DATA:
            components.append((0.40, self.trend.sign))
        if self.structure is not Direction.INSUFFICIENT_DATA:
            components.append((0.35, self.structure.sign))
        if self.momentum is not MomentumState.INSUFFICIENT_DATA:
            components.append(
                (
                    0.25,
                    1
                    if self.momentum is MomentumState.BULLISH
                    else -1
                    if self.momentum is MomentumState.BEARISH
                    else 0,
                )
            )
        if not components:
            return 0.0
        total_weight = sum(weight for weight, _ in components)
        return sum(weight * sign for weight, sign in components) / total_weight

    def as_dict(self) -> dict:
        return {
            "timeframe": self.timeframe,
            "role": self.role,
            "trend": self.trend.value,
            "structure": self.structure.value,
            "momentum": self.momentum.value,
            "direction_score": round(self.direction_score, 3),
        }


@dataclass
class MTFResult:
    alignment: str = INSUFFICIENT_DATA
    bullish_count: int = 0
    bearish_count: int = 0
    required: int = 2
    htf_bias: Direction | None = None
    multiplier: float = 0.8
    assessments: list[TFAssessment] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def conflict(self) -> bool:
        return self.alignment == CONFLICT

    def ltf_assessment(self) -> TFAssessment | None:
        for assessment in reversed(self.assessments):
            if assessment.role == "ltf":
                return assessment
        return self.assessments[-1] if self.assessments else None

    def ltf_confirms(self, bias: Direction) -> bool:
        assessment = self.ltf_assessment()
        if assessment is None:
            return False
        score = assessment.direction_score
        if bias is Direction.BULLISH:
            return score >= _VOTE_THRESHOLD
        if bias is Direction.BEARISH:
            return score <= -_VOTE_THRESHOLD
        return False

    def aligned_with(self, bias: Direction) -> int:
        return self.bullish_count if bias is Direction.BULLISH else self.bearish_count

    def as_dict(self) -> dict:
        return {
            "alignment": self.alignment,
            "bullish_count": self.bullish_count,
            "bearish_count": self.bearish_count,
            "required": self.required,
            "htf_bias": self.htf_bias.value if self.htf_bias else None,
            "multiplier": round(self.multiplier, 3),
            "assessments": [item.as_dict() for item in self.assessments],
            "notes": self.notes,
        }


def analyze_multi_timeframe(
    assessments: list[TFAssessment], config: DecisionConfig
) -> MTFResult:
    result = MTFResult(required=config.min_timeframe_alignment, assessments=assessments)
    usable = [
        assessment
        for assessment in assessments
        if assessment.trend is not Direction.INSUFFICIENT_DATA
        or assessment.structure is not Direction.INSUFFICIENT_DATA
        or assessment.momentum is not MomentumState.INSUFFICIENT_DATA
    ]
    if not usable:
        result.notes.append("no timeframe had sufficient data for alignment analysis")
        return result

    scores = {assessment.timeframe: assessment.direction_score for assessment in assessments}
    result.bullish_count = sum(1 for score in scores.values() if score >= _VOTE_THRESHOLD)
    result.bearish_count = sum(1 for score in scores.values() if score <= -_VOTE_THRESHOLD)

    htf = next(
        (assessment for assessment in assessments if assessment.role == "htf"),
        assessments[0],
    )
    htf_score = htf.direction_score
    result.htf_bias = Direction.from_score(htf_score)

    required = min(config.min_timeframe_alignment, len(usable))
    bullish = result.bullish_count
    bearish = result.bearish_count

    if bullish >= required and htf_score >= 0:
        result.alignment = ALIGNED_BULLISH
        result.multiplier = 1.15 if bearish == 0 else 1.0
    elif bearish >= required and htf_score <= 0:
        result.alignment = ALIGNED_BEARISH
        result.multiplier = 1.15 if bullish == 0 else 1.0
    elif (bullish >= required and htf_score < 0) or (bearish >= required and htf_score > 0):
        result.alignment = CONFLICT
        result.multiplier = 0.55
        result.notes.append(
            "lower timeframes disagree with the higher-timeframe bias - do not force a trade"
        )
    else:
        result.alignment = MIXED
        result.multiplier = 0.8

    if len(usable) < len(assessments):
        missing = [item.timeframe for item in assessments if item not in usable]
        result.notes.append(f"timeframes without usable data: {', '.join(missing)}")
    if result.alignment in (ALIGNED_BULLISH, ALIGNED_BEARISH):
        result.multiplier = clamp(result.multiplier, 0.0, 1.15)
        result.notes.append(
            f"{max(bullish, bearish)} of {len(usable)} timeframes align "
            f"({result.alignment.lower().replace('aligned_', '')})"
        )
    return result
