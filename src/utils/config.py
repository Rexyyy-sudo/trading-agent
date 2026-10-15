"""Typed configuration loading.

Configuration precedence:
    1. built-in DEFAULTS (this file)
    2. YAML file (config/settings.yaml by default, deep-merged)
    3. environment variables for secrets only (never analysis values)

Secrets are read lazily via os.environ and are NEVER written to config.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.utils.errors import ConfigError

DEFAULTS: dict[str, Any] = {
    "app": {"log_level": "INFO", "data_dir": "data"},
    "providers": {
        "priority": ["twelvedata", "binance", "yahoo", "csv"],
        "csv_dir": "data/raw",
        "request_timeout": 15,
        "default_limit": 500,
    },
    "symbols": {
        "default_timeframes": ["H1", "M15", "M5"],
        "auto_multi_timeframe": True,
        "timeframe_roles": {"H1": "htf", "M15": "mtf", "M5": "ltf"},
    },
    "analysis": {
        "min_bars": 120,
        "swing_lookback": 3,
        "ema_fast": 20,
        "ema_slow": 50,
        "ema_trend": 200,
        "rsi_period": 14,
        "atr_period": 14,
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "bollinger_period": 20,
        "bollinger_std": 2.0,
        "sr_cluster_tolerance_atr": 0.6,
        "sr_max_zones_per_side": 4,
        "equal_level_tolerance_atr": 0.2,
        "liquidity_lookback_swings": 12,
        "volatility_lookback": 200,
        "volatility_low_ratio": 0.75,
        "volatility_high_ratio": 1.3,
        "volatility_extreme_ratio": 1.8,
    },
    "scoring": {
        "weights": {
            "structure": 0.30,
            "liquidity": 0.20,
            "momentum": 0.15,
            "trend": 0.15,
            "support_resistance": 0.10,
            "volatility": 0.05,
            "volume": 0.05,
        },
        "label_thresholds": [40, 60, 75, 90],
    },
    "decision": {
        "long_threshold": 65,
        "short_threshold": 65,
        "min_timeframe_alignment": 2,
        "ltf_confirmation_required": True,
        "news_extreme": "NO TRADE",
        "news_high": "WAIT",
        "volatility_extreme": "WAIT",
    },
    "risk": {
        "default_balance": 10000.0,
        "default_risk_pct": 1.0,
        "max_risk_pct": 2.0,
        "sl_method": "structure",
        "atr_sl_multiplier": 1.5,
        "structure_buffer_atr": 0.5,
        "rr_targets": [1.0, 2.0, 3.0],
        "warn_rr_below": 1.5,
    },
    "paper": {
        "starting_balance": 10000.0,
        "storage_path": "data/paper/account.json",
    },
    "news": {
        "provider": "none",
        "local_calendar": "data/news/calendar.json",
        "lookahead_hours": 24,
        "window_hours": 2,
        "extreme_keywords": [
            "fomc", "federal funds rate", "interest rate decision", "rate decision",
            "nonfarm payroll", "nfp", "cpi", "consumer price index", "powell",
        ],
        "high_keywords": [
            "ppi", "producer price index", "gdp", "pce", "retail sales",
            "unemployment rate", "ecb", "boe", "boj", "fed", "central bank",
            "inflation", "jobless claims",
        ],
    },
}

SCORE_COMPONENTS = (
    "structure",
    "liquidity",
    "momentum",
    "trend",
    "support_resistance",
    "volatility",
    "volume",
)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, dict):
        raise ConfigError(f"config section '{key}' must be a mapping")
    return value


@dataclass
class AppConfig:
    log_level: str = "INFO"
    data_dir: str = "data"


@dataclass
class ProvidersConfig:
    priority: list[str] = field(default_factory=lambda: ["twelvedata", "binance", "yahoo", "csv"])
    csv_dir: str = "data/raw"
    request_timeout: int = 15
    default_limit: int = 500


@dataclass
class SymbolsConfig:
    default_timeframes: list[str] = field(default_factory=lambda: ["H1", "M15", "M5"])
    auto_multi_timeframe: bool = True
    timeframe_roles: dict[str, str] = field(
        default_factory=lambda: {"H1": "htf", "M15": "mtf", "M5": "ltf"}
    )


@dataclass
class AnalysisConfig:
    min_bars: int = 120
    swing_lookback: int = 3
    ema_fast: int = 20
    ema_slow: int = 50
    ema_trend: int = 200
    rsi_period: int = 14
    atr_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bollinger_period: int = 20
    bollinger_std: float = 2.0
    sr_cluster_tolerance_atr: float = 0.6
    sr_max_zones_per_side: int = 4
    equal_level_tolerance_atr: float = 0.2
    liquidity_lookback_swings: int = 12
    volatility_lookback: int = 200
    volatility_low_ratio: float = 0.75
    volatility_high_ratio: float = 1.3
    volatility_extreme_ratio: float = 1.8


@dataclass
class ScoringConfig:
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "structure": 0.30,
            "liquidity": 0.20,
            "momentum": 0.15,
            "trend": 0.15,
            "support_resistance": 0.10,
            "volatility": 0.05,
            "volume": 0.05,
        }
    )
    label_thresholds: list[int] = field(default_factory=lambda: [40, 60, 75, 90])


@dataclass
class DecisionConfig:
    long_threshold: float = 65
    short_threshold: float = 65
    min_timeframe_alignment: int = 2
    ltf_confirmation_required: bool = True
    news_extreme: str = "NO TRADE"
    news_high: str = "WAIT"
    volatility_extreme: str = "WAIT"


@dataclass
class RiskConfig:
    default_balance: float = 10000.0
    default_risk_pct: float = 1.0
    max_risk_pct: float = 2.0
    sl_method: str = "structure"
    atr_sl_multiplier: float = 1.5
    structure_buffer_atr: float = 0.5
    rr_targets: list[float] = field(default_factory=lambda: [1.0, 2.0, 3.0])
    warn_rr_below: float = 1.5


@dataclass
class PaperConfig:
    starting_balance: float = 10000.0
    storage_path: str = "data/paper/account.json"


@dataclass
class NewsConfig:
    provider: str = "none"
    local_calendar: str = "data/news/calendar.json"
    lookahead_hours: int = 24
    window_hours: int = 2
    extreme_keywords: list[str] = field(default_factory=list)
    high_keywords: list[str] = field(default_factory=list)


@dataclass
class Settings:
    app: AppConfig
    providers: ProvidersConfig
    symbols: SymbolsConfig
    analysis: AnalysisConfig
    scoring: ScoringConfig
    decision: DecisionConfig
    risk: RiskConfig
    paper: PaperConfig
    news: NewsConfig
    root: Path
    config_path: Path | None = None

    def resolve_path(self, value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else (self.root / path)


def find_config_file(explicit: str | Path | None = None) -> Path | None:
    if explicit:
        candidate = Path(explicit)
        if not candidate.is_file():
            raise ConfigError(f"config file not found: {candidate}")
        return candidate
    env_path = os.environ.get("TRADING_AGENT_CONFIG")
    candidates = []
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend([Path("config/settings.yaml"), Path("settings.yaml")])
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _validate(raw: dict[str, Any]) -> None:
    scoring = _section(raw, "scoring")
    weights = scoring.get("weights", {})
    if not isinstance(weights, dict) or not weights:
        raise ConfigError("scoring.weights must be a non-empty mapping")
    unknown = set(weights) - set(SCORE_COMPONENTS)
    if unknown:
        raise ConfigError(f"unknown scoring weight keys: {sorted(unknown)}")
    for key, value in weights.items():
        try:
            if float(value) < 0:
                raise ConfigError(f"scoring weight '{key}' must be >= 0")
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"scoring weight '{key}' must be numeric") from exc
    thresholds = scoring.get("label_thresholds", [])
    if not isinstance(thresholds, list) or len(thresholds) != 4:
        raise ConfigError("scoring.label_thresholds must contain exactly 4 values")
    if any(a >= b for a, b in zip(thresholds, thresholds[1:], strict=False)):
        raise ConfigError("scoring.label_thresholds must be strictly ascending")
    decision = _section(raw, "decision")
    for key in ("news_extreme", "news_high", "volatility_extreme"):
        value = decision.get(key)
        if value not in ("WAIT", "NO_TRADE", "NO TRADE"):
            raise ConfigError(f"decision.{key} must be WAIT or NO TRADE")
        decision[key] = "NO TRADE" if value == "NO_TRADE" else value
    risk = _section(raw, "risk")
    method = risk.get("sl_method", "structure")
    if method not in ("structure", "atr"):
        raise ConfigError("risk.sl_method must be 'structure' or 'atr'")
    max_risk = float(risk.get("max_risk_pct", 2.0))
    if not 0 < max_risk <= 100:
        raise ConfigError("risk.max_risk_pct must be within (0, 100]")
    news = _section(raw, "news")
    if news.get("provider") not in ("none", "local", "finnhub"):
        raise ConfigError("news.provider must be none, local or finnhub")
    analysis = _section(raw, "analysis")
    if int(analysis.get("min_bars", 120)) < 30:
        raise ConfigError("analysis.min_bars must be >= 30")


def load_settings(
    config_path: str | Path | None = None, root: str | Path | None = None
) -> Settings:
    """Load settings from YAML deep-merged over built-in defaults."""
    path = find_config_file(config_path)
    raw: dict[str, Any] = {}
    if path is not None:
        try:
            loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            raise ConfigError(f"cannot parse {path}: {exc}") from exc
        if loaded is None:
            loaded = {}
        if not isinstance(loaded, dict):
            raise ConfigError(f"top level of {path} must be a mapping")
        raw = loaded
    merged = _deep_merge(DEFAULTS, raw)
    _validate(merged)

    if root is not None:
        base = Path(root).resolve()
    elif path is not None:
        base = path.resolve().parent.parent if path.resolve().parent.name == "config" else path.resolve().parent
    else:
        base = Path.cwd()

    app = AppConfig(**_section(merged, "app"))
    providers = ProvidersConfig(**_section(merged, "providers"))
    symbols = SymbolsConfig(**_section(merged, "symbols"))
    analysis = AnalysisConfig(**_section(merged, "analysis"))
    scoring = ScoringConfig(**_section(merged, "scoring"))
    decision = DecisionConfig(**_section(merged, "decision"))
    risk = RiskConfig(**_section(merged, "risk"))
    paper = PaperConfig(**_section(merged, "paper"))
    news = NewsConfig(**_section(merged, "news"))
    return Settings(
        app=app,
        providers=providers,
        symbols=symbols,
        analysis=analysis,
        scoring=scoring,
        decision=decision,
        risk=risk,
        paper=paper,
        news=news,
        root=base,
        config_path=path,
    )


def env_secret(*names: str) -> str | None:
    """Return the first non-empty environment variable among names."""
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return None
