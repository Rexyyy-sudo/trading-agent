"""News / macro-risk abstraction.

The framework NEVER invents upcoming events. When no news source is
configured or reachable the status is UNKNOWN and clearly reported.

Providers:
    none     - always UNKNOWN
    local    - reads a JSON calendar maintained by the user
    finnhub  - optional API (requires FINNHUB_API_KEY)
"""

from __future__ import annotations

import abc
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests

from src.market.symbols import SymbolInfo
from src.utils.config import NewsConfig, Settings, env_secret
from src.utils.errors import DataUnavailableError
from src.utils.logging import get_logger

logger = get_logger("news")

LOW = "LOW"
MEDIUM = "MEDIUM"
HIGH = "HIGH"
EXTREME = "EXTREME"
UNKNOWN = "UNKNOWN"

_LEVEL_ORDER = {LOW: 0, MEDIUM: 1, HIGH: 2, EXTREME: 3}
_IMPACT_MAP = {"low": LOW, "medium": MEDIUM, "high": HIGH, "3": HIGH, "2": MEDIUM, "1": LOW}


@dataclass(frozen=True)
class NewsEvent:
    time: datetime
    currency: str
    title: str
    importance: str
    source: str

    def as_dict(self) -> dict:
        return {
            "time": self.time.isoformat(),
            "currency": self.currency,
            "title": self.title,
            "importance": self.importance,
            "source": self.source,
        }


@dataclass
class NewsReport:
    risk_level: str = UNKNOWN
    events: list[NewsEvent] = field(default_factory=list)
    source: str = "none"
    reason: str = "no news provider configured"
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def known(self) -> bool:
        return self.risk_level != UNKNOWN

    def as_dict(self) -> dict:
        return {
            "risk_level": self.risk_level,
            "source": self.source,
            "reason": self.reason,
            "events": [event.as_dict() for event in self.events],
        }


def relevant_currencies(info: SymbolInfo) -> set[str]:
    """Currencies whose events are material for this instrument."""
    currencies: set[str] = set()
    if info.asset_class in ("forex", "metal"):
        if info.base in {"XAU", "XAG", "XPT", "XPD"}:
            currencies.add("USD")
        if info.quote:
            currencies.add(info.quote)
        if info.base and len(info.base) == 3:
            currencies.add(info.base)
    elif info.asset_class == "crypto":
        quote = info.quote if info.quote in {"USD", "USDT", "USDC"} else "USD"
        currencies.add("USD")
        if quote != "USD":
            currencies.add(quote)
    else:
        currencies.add("USD")
    return currencies


def classify_importance(title: str, config: NewsConfig) -> str:
    lowered = title.lower()
    for keyword in config.extreme_keywords:
        if keyword.lower() in lowered:
            return EXTREME
    for keyword in config.high_keywords:
        if keyword.lower() in lowered:
            return HIGH
    return MEDIUM


def build_report(
    events: list[NewsEvent],
    info: SymbolInfo,
    config: NewsConfig,
    source: str,
    now: datetime | None = None,
) -> NewsReport:
    now = now or datetime.now(UTC)
    currencies = relevant_currencies(info)
    window_start = now - timedelta(hours=config.window_hours)
    window_end = now + timedelta(hours=config.lookahead_hours)

    relevant = [
        event
        for event in events
        if event.currency.upper() in currencies and window_start <= event.time <= window_end
    ]
    relevant.sort(key=lambda event: event.time)

    if not relevant:
        return NewsReport(
            risk_level=LOW,
            events=[],
            source=source,
            reason=(
                f"no relevant events for {', '.join(sorted(currencies))} "
                f"in the next {config.lookahead_hours}h"
            ),
            generated_at=now,
        )

    level = LOW
    for event in relevant:
        hours_away = (event.time - now).total_seconds() / 3600.0
        importance = _LEVEL_ORDER.get(event.importance, 0)
        if event.importance == EXTREME and hours_away <= 6:
            importance = _LEVEL_ORDER[EXTREME]
        elif event.importance == HIGH and hours_away <= 12:
            importance = max(importance, _LEVEL_ORDER[HIGH])
        level = max(level, importance)

    level_name = [name for name, order in _LEVEL_ORDER.items() if order == level][0]
    imminent = [
        event
        for event in relevant
        if abs((event.time - now).total_seconds()) <= config.window_hours * 3600
    ]
    reason = f"{len(relevant)} relevant event(s) within window"
    if imminent:
        reason += f" - {len(imminent)} within +/-{config.window_hours}h"

    return NewsReport(
        risk_level=level_name,
        events=relevant[:10],
        source=source,
        reason=reason,
        generated_at=now,
    )


class NewsProvider(abc.ABC):
    name: str = "base"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.config = settings.news
        self.timeout = int(settings.providers.request_timeout)

    @abc.abstractmethod
    def get_events(self) -> list[NewsEvent]:
        """Return raw events (may be empty). Raises DataUnavailableError."""

    def get_report(self, info: SymbolInfo, now: datetime | None = None) -> NewsReport:
        try:
            events = self.get_events()
        except DataUnavailableError as exc:
            return NewsReport(
                risk_level=UNKNOWN,
                source=self.name,
                reason=f"news source unavailable: {exc}",
            )
        return build_report(events, info, self.config, self.name, now=now)


class NullNewsProvider(NewsProvider):
    name = "none"

    def get_events(self) -> list[NewsEvent]:
        raise DataUnavailableError("no news provider configured")


class LocalCalendarProvider(NewsProvider):
    """Reads data/news/calendar.json (user-maintained).

    Format: a JSON list (or {"events": [...]}) of objects:
        {"time": "2026-10-15T12:30:00Z", "currency": "USD",
         "title": "US CPI", "importance": "HIGH"}
    """

    name = "local"

    def path(self) -> Path:
        return self.settings.resolve_path(self.config.local_calendar)

    def get_events(self) -> list[NewsEvent]:
        path = self.path()
        if not path.is_file():
            raise DataUnavailableError(
                f"calendar file not found: {path} (create it or use another provider)"
            )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DataUnavailableError(f"cannot read calendar {path}: {exc}") from exc
        if isinstance(payload, dict):
            payload = payload.get("events", [])
        if not isinstance(payload, list):
            raise DataUnavailableError(f"calendar {path} must contain a list of events")

        events: list[NewsEvent] = []
        for item in payload:
            if not isinstance(item, dict) or "time" not in item:
                continue
            try:
                raw_time = str(item["time"]).replace("Z", "+00:00")
                event_time = datetime.fromisoformat(raw_time)
                if event_time.tzinfo is None:
                    event_time = event_time.replace(tzinfo=UTC)
            except ValueError:
                logger.warning("skipping calendar entry with bad time: %s", item)
                continue
            title = str(item.get("title") or item.get("event") or "unknown event")
            importance = str(item.get("importance", "")).upper()
            if importance not in _LEVEL_ORDER:
                importance = classify_importance(title, self.config)
            events.append(
                NewsEvent(
                    time=event_time,
                    currency=str(item.get("currency", "")).upper(),
                    title=title,
                    importance=importance,
                    source=self.name,
                )
            )
        return events


class FinnhubProvider(NewsProvider):
    name = "finnhub"
    base_url = "https://finnhub.io/api/v1/calendar/economic"

    _COUNTRY_TO_CURRENCY = {
        "US": "USD", "EU": "EUR", "DE": "EUR", "FR": "EUR", "IT": "EUR", "ES": "EUR",
        "GB": "GBP", "JP": "JPY", "AU": "AUD", "CA": "CAD", "CH": "CHF", "NZ": "NZD",
        "CN": "CNY", "TR": "TRY", "SE": "SEK", "NO": "NOK",
    }

    def api_key(self) -> str | None:
        return env_secret("FINNHUB_API_KEY", "NEWS_API_KEY")

    def get_events(self) -> list[NewsEvent]:
        key = self.api_key()
        if not key:
            raise DataUnavailableError(
                "FINNHUB_API_KEY is not set (see .env.example)"
            )
        now = datetime.now(UTC)
        params = {
            "from": now.date().isoformat(),
            "to": (now + timedelta(hours=self.config.lookahead_hours)).date().isoformat(),
            "token": key,
        }
        try:
            response = requests.get(self.base_url, params=params, timeout=self.timeout)
        except requests.RequestException as exc:
            raise DataUnavailableError(f"finnhub request failed: {exc}") from exc
        if response.status_code == 403:
            raise DataUnavailableError(
                "finnhub economic calendar requires a paid plan (HTTP 403)"
            )
        if response.status_code != 200:
            raise DataUnavailableError(f"finnhub HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise DataUnavailableError("finnhub returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise DataUnavailableError("finnhub returned an unexpected payload")

        events: list[NewsEvent] = []
        for item in payload.get("economicCalendar", []) or []:
            if not isinstance(item, dict):
                continue
            raw_time = item.get("time")
            if not raw_time:
                continue
            try:
                event_time = datetime.fromisoformat(
                    str(raw_time).replace("Z", "+00:00")
                )
                if event_time.tzinfo is None:
                    event_time = event_time.replace(tzinfo=UTC)
            except ValueError:
                continue
            country = str(item.get("country", "")).upper()
            currency = self._COUNTRY_TO_CURRENCY.get(country, country)
            title = str(item.get("event", "unknown event"))
            impact = _IMPACT_MAP.get(str(item.get("impact", "")).lower())
            importance = impact or classify_importance(title, self.config)
            events.append(
                NewsEvent(
                    time=event_time,
                    currency=currency,
                    title=title,
                    importance=importance,
                    source=self.name,
                )
            )
        return events


def build_news_provider(settings: Settings) -> NewsProvider:
    provider = settings.news.provider
    if provider == "local":
        return LocalCalendarProvider(settings)
    if provider == "finnhub":
        return FinnhubProvider(settings)
    return NullNewsProvider(settings)
