"""Generic validation helpers used across the framework."""

from __future__ import annotations

import math
from typing import Any

from src.utils.errors import ValidationError


def is_missing(value: Any) -> bool:
    """True for None, NaN, infinities or pandas NA-like values."""
    if value is None:
        return True
    try:
        f = float(value)
    except (TypeError, ValueError):
        return True
    return math.isnan(f) or math.isinf(f)


def require(condition: bool, message: str) -> None:
    """Raise ValidationError unless condition is truthy."""
    if not condition:
        raise ValidationError(message)


def ensure_positive(value: Any, name: str = "value") -> float:
    """Coerce to float and require strictly positive."""
    if is_missing(value):
        raise ValidationError(f"{name} is required and must be a number")
    f = float(value)
    if f <= 0:
        raise ValidationError(f"{name} must be > 0 (got {f})")
    return f


def ensure_non_negative(value: Any, name: str = "value") -> float:
    if is_missing(value):
        raise ValidationError(f"{name} is required and must be a number")
    f = float(value)
    if f < 0:
        raise ValidationError(f"{name} must be >= 0 (got {f})")
    return f


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def safe_float(value: Any, default: float | None = None) -> float | None:
    """Best-effort float conversion; returns default when missing."""
    if is_missing(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clean_symbol_text(raw: str) -> str:
    """Normalise free-form symbol input: uppercase, strip separators."""
    if raw is None:
        raise ValidationError("symbol is required")
    cleaned = str(raw).strip().upper()
    if not cleaned:
        raise ValidationError("symbol is required")
    if ":" in cleaned:  # e.g. "BINANCE:BTCUSDT" or "OANDA:XAUUSD"
        cleaned = cleaned.split(":", 1)[1]
    for sep in (" ", "/", "\\", "-", "_", ".", "=", "?"):
        cleaned = cleaned.replace(sep, "")
    if not cleaned or not cleaned.isalnum():
        raise ValidationError(f"invalid symbol: {raw!r}")
    if len(cleaned) < 3 or len(cleaned) > 20:
        raise ValidationError(f"invalid symbol length: {raw!r}")
    return cleaned
