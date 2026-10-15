"""Timeframe vocabulary and helpers.

Canonical form: M1, M5, M15, M30, H1, H4, D1, W1.
"""

from __future__ import annotations

from src.utils.errors import ValidationError

TF_MINUTES: dict[str, int] = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
    "W1": 10080,
}

_ALIASES: dict[str, str] = {
    "1": "M1", "1M": "M1", "1MIN": "M1", "M1": "M1",
    "5": "M5", "5M": "M5", "5MIN": "M5", "M5": "M5",
    "15": "M15", "15M": "M15", "15MIN": "M15", "M15": "M15",
    "30": "M30", "30M": "M30", "30MIN": "M30", "M30": "M30",
    "60": "H1", "60M": "H1", "1H": "H1", "60MIN": "H1", "H1": "H1",
    "240": "H4", "240M": "H4", "4H": "H4", "H4": "H4",
    "1D": "D1", "D": "D1", "D1": "D1", "1DAY": "D1",
    "1W": "W1", "W": "W1", "W1": "W1", "1WEEK": "W1",
}

# Explicit higher/mid timeframe sets per entry timeframe.
AUTO_MTF_SETS: dict[str, tuple[str, str, str]] = {
    "M1": ("M15", "M5", "M1"),
    "M5": ("H1", "M15", "M5"),
    "M15": ("H4", "H1", "M15"),
    "M30": ("H4", "H1", "M30"),
    "H1": ("D1", "H4", "H1"),
    "H4": ("W1", "D1", "H4"),
}


def normalize_timeframe(value: str) -> str:
    """Return the canonical timeframe name or raise ValidationError."""
    if value is None:
        raise ValidationError("timeframe is required")
    token = str(value).strip().upper()
    if token in _ALIASES:
        return _ALIASES[token]
    raise ValidationError(
        f"unsupported timeframe {value!r}. Supported: {', '.join(TF_MINUTES)}"
    )


def timeframe_minutes(timeframe: str) -> int:
    return TF_MINUTES[normalize_timeframe(timeframe)]


def pandas_rule(timeframe: str) -> str:
    """Pandas resample rule for a canonical timeframe."""
    tf = normalize_timeframe(timeframe)
    if tf.startswith("M"):
        return f"{TF_MINUTES[tf]}min"
    if tf.startswith("H"):
        return f"{TF_MINUTES[tf] // 60}h"
    if tf == "D1":
        return "1D"
    return "1W"


def parse_timeframes(
    value: str | list[str] | None, default: list[str] | None = None
) -> list[str]:
    """Parse 'H1,M15,M5' or a list into canonical, de-duplicated order."""
    if value is None or value == "":
        source = list(default or [])
    elif isinstance(value, str):
        source = [part for part in value.replace(";", ",").split(",") if part.strip()]
    else:
        source = [str(part) for part in value if str(part).strip()]
    result: list[str] = []
    for item in source:
        tf = normalize_timeframe(item)
        if tf not in result:
            result.append(tf)
    if not result:
        raise ValidationError("at least one timeframe is required")
    return result


def auto_timeframe_set(entry_timeframe: str) -> list[str]:
    """Higher/mid/entry timeframe trio for a given entry timeframe."""
    tf = normalize_timeframe(entry_timeframe)
    if tf in AUTO_MTF_SETS:
        return list(AUTO_MTF_SETS[tf])
    minutes = TF_MINUTES[tf]
    known = sorted(TF_MINUTES.items(), key=lambda kv: kv[1])
    htf = _nearest_known(minutes * 12, known, prefer_larger=True)
    mtf = _nearest_known(minutes * 3, known, prefer_larger=False)
    trio = [htf, mtf, tf]
    seen: list[str] = []
    for item in trio:
        if item not in seen:
            seen.append(item)
    return seen


def _nearest_known(
    minutes: int, known: list[tuple[str, int]], prefer_larger: bool
) -> str:
    best: tuple[float, tuple[str, int]] | None = None
    for item in known:
        diff = abs(item[1] - minutes)
        key = (diff, -item[1] if prefer_larger else item[1])
        if best is None or key < best[0]:
            best = (key, item)
    assert best is not None
    return best[1][0]


def assign_roles(timeframes: list[str]) -> dict[str, str]:
    """Assign htf/mtf/ltf roles: first is highest, last is entry."""
    roles: dict[str, str] = {}
    for index, tf in enumerate(timeframes):
        if len(timeframes) == 1:
            roles[tf] = "ltf"
        elif index == 0:
            roles[tf] = "htf"
        elif index == len(timeframes) - 1:
            roles[tf] = "ltf"
        else:
            roles[tf] = "mtf"
    return roles
