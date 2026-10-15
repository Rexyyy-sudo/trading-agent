"""Decision engine tests."""

from __future__ import annotations

from src.analysis.multi_timeframe import MTFResult, TFAssessment
from src.analysis.types import Direction, MomentumState, VolatilityClass
from src.analysis.volatility import VolatilityResult
from src.news.news_provider import NewsReport
from src.signal.decision import LONG, NO_TRADE, SHORT, WAIT, decide
from src.signal.scorer import ScoreResult
from src.utils.config import DecisionConfig


def _mtf(alignment="ALIGNED_BULLISH", bullish=3, bearish=0, multiplier=1.15):
    assessments = [
        TFAssessment(
            "H1", "htf",
            Direction.BULLISH if alignment == "ALIGNED_BULLISH" else Direction.BEARISH,
            Direction.BULLISH if alignment == "ALIGNED_BULLISH" else Direction.BEARISH,
            MomentumState.BULLISH if alignment == "ALIGNED_BULLISH" else MomentumState.BEARISH,
        ),
        TFAssessment(
            "M5", "ltf",
            Direction.BULLISH if alignment == "ALIGNED_BULLISH" else Direction.BEARISH,
            Direction.BULLISH if alignment == "ALIGNED_BULLISH" else Direction.BEARISH,
            MomentumState.BULLISH if alignment == "ALIGNED_BULLISH" else MomentumState.BEARISH,
        ),
    ]
    return MTFResult(
        alignment=alignment,
        bullish_count=bullish,
        bearish_count=bearish,
        required=2,
        htf_bias=Direction.BULLISH,
        multiplier=multiplier,
        assessments=assessments,
    )


def _score(bias=Direction.BULLISH, score=75.0):
    signed = score if bias is Direction.BULLISH else -score
    return ScoreResult(
        signed_score=signed,
        score=score,
        label="STRONG",
        bias=bias,
        confidence=0.8,
    )


def _normal_vol():
    return VolatilityResult(classification=VolatilityClass.NORMAL, atr=1.0)


def _news(level="LOW"):
    return NewsReport(risk_level=level, source="test", reason="test")


def test_strong_bullish_gives_long():
    result = decide(
        _score(), _mtf(), _normal_vol(), _news(), True, [], DecisionConfig()
    )
    assert result.signal == LONG
    assert result.bias is Direction.BULLISH


def test_strong_bearish_gives_short():
    result = decide(
        _score(Direction.BEARISH, 80),
        _mtf("ALIGNED_BEARISH", 0, 3),
        _normal_vol(),
        _news(),
        True,
        [],
        DecisionConfig(),
    )
    assert result.signal == SHORT


def test_weak_score_gives_wait():
    result = decide(
        _score(Direction.BULLISH, 30), _mtf(), _normal_vol(), _news(), True, [], DecisionConfig()
    )
    assert result.signal == WAIT
    assert result.blocked_by == "score"


def test_conflicting_timeframes_gives_wait():
    mtf = _mtf("CONFLICT", 1, 2, 0.55)
    result = decide(
        _score(), mtf, _normal_vol(), _news(), True, [], DecisionConfig()
    )
    assert result.signal == WAIT
    assert result.blocked_by == "mtf"


def test_insufficient_data_gives_no_trade():
    result = decide(
        _score(), _mtf(), _normal_vol(), _news(), False, ["no candles"], DecisionConfig()
    )
    assert result.signal == NO_TRADE
    assert result.blocked_by == "data"


def test_extreme_news_gives_no_trade():
    result = decide(
        _score(), _mtf(), _normal_vol(), _news("EXTREME"), True, [], DecisionConfig()
    )
    assert result.signal == NO_TRADE
    assert result.blocked_by == "news"


def test_high_news_allows_but_warns():
    result = decide(
        _score(), _mtf(), _normal_vol(), _news("HIGH"), True, [], DecisionConfig()
    )
    assert result.signal == LONG
    assert any("macro" in reason for reason in result.reasons)


def test_extreme_volatility_gives_wait():
    volatility = VolatilityResult(classification=VolatilityClass.EXTREME, atr=5.0)
    result = decide(
        _score(), _mtf(), volatility, _news(), True, [], DecisionConfig()
    )
    assert result.signal == WAIT
    assert result.blocked_by == "volatility"


def test_neutral_bias_gives_wait():
    score = ScoreResult(
        signed_score=5, score=5, label="WEAK", bias=Direction.NEUTRAL, confidence=0.3
    )
    result = decide(score, _mtf(), _normal_vol(), _news(), True, [], DecisionConfig())
    assert result.signal == WAIT
