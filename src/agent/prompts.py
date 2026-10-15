"""Prompt templates and deterministic explanations.

The deterministic engine needs no LLM. These prompts exist so an LLM
(e.g. the OpenCode trading-analyst agent) can EXPLAIN structured results
without inventing data.
"""

from __future__ import annotations

from src.agent.schemas import AnalysisReport

SYSTEM_PROMPT = """You are a market-analysis assistant for an educational trading tool.

Absolute rules:
1. NEVER guarantee profit, wins or accuracy. No "guaranteed", "100%", "sure".
2. NEVER invent prices, indicators, news, events or data. Use ONLY the data
   in this report. If something is missing, say it is missing.
3. If data status is INSUFFICIENT, the answer is "NO TRADE - INSUFFICIENT DATA".
4. Present setups as scenarios with confirmation and invalidation conditions.
5. Instrument analysis is technical/educational, not financial advice.
6. Respect uncertainty: use "potential", "scenario", "bias", "confirmation
   required", "invalidation", "insufficient data".
7. Multi-timeframe conflicts mean WAIT - never force a trade.
"""


def build_analysis_prompt(report: AnalysisReport) -> str:
    """Prompt asking an LLM to explain an existing structured report."""
    import json

    payload = json.dumps(report.to_dict(), indent=2, default=str)
    return (
        f"{SYSTEM_PROMPT}\n"
        "Explain the following structured analysis in concise, trader-friendly "
        "language. Do not add data that is not in the report. Finish with the "
        "final status and the invalidation condition.\n\n"
        f"STRUCTURED REPORT:\n{payload}\n"
    )


def explain_report(report: AnalysisReport) -> str:
    """Deterministic, data-only explanation (no LLM required)."""
    lines: list[str] = []
    decision = report.decision
    lines.append(
        f"{report.symbol} {report.timeframe}: data status {report.data_status}, "
        f"provider {report.provider}."
    )
    if report.score is not None:
        lines.append(
            f"Technical bias is {report.score.bias.value} with score "
            f"{report.score.score:.0f}/100 ({report.score.label}); confidence "
            f"estimate {report.score.confidence * 100:.0f}%."
        )
    lines.append(f"Decision engine returned: {decision.signal}.")
    for reason in decision.reasons:
        lines.append(f"- {reason}")
    if report.entry is not None:
        entry = report.entry
        lines.append(
            f"Scenario ({entry.model}): entry zone "
            f"{entry.entry_lower:.5f} - {entry.entry_upper:.5f}, stop "
            f"{entry.stop_loss:.5f}."
        )
        lines.append(f"Confirmation: {entry.confirmation}")
        lines.append(f"Invalidation: {entry.invalidation}")
    if report.news.known:
        lines.append(f"News risk: {report.news.risk_level} ({report.news.reason}).")
    else:
        lines.append("News risk: UNKNOWN - live news data is not available.")
    if report.warnings:
        lines.append("Warnings:")
        lines.extend(f"- {warning}" for warning in report.warnings)
    lines.append(
        "Educational analysis only - not financial advice. "
        "This is a scenario, not a prediction."
    )
    return "\n".join(lines)
