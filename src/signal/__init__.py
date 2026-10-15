"""Signal subpackage: scoring, decisions and entry models."""

from src.signal.decision import LONG, NO_TRADE, SHORT, WAIT, DecisionResult, decide
from src.signal.entry_model import EntryPlan, build_entry_plan
from src.signal.scorer import ScoreComponent, ScoreResult, label_for, score_setup

__all__ = [
    "LONG",
    "NO_TRADE",
    "SHORT",
    "WAIT",
    "DecisionResult",
    "EntryPlan",
    "ScoreComponent",
    "ScoreResult",
    "build_entry_plan",
    "decide",
    "label_for",
    "score_setup",
]
