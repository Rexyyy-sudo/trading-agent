"""Human-readable output formatting (terminal-friendly boxes/tables)."""

from __future__ import annotations

import unicodedata

from src.agent.schemas import AnalysisReport
from src.backtest.engine import BacktestResult
from src.news.news_provider import NewsReport
from src.paper.broker import PaperStats

SIGNAL_ICONS = {
    "LONG": "\U0001f7e2",
    "SHORT": "\U0001f534",
    "WAIT": "\U0001f7e1",
    "NO TRADE": "\u26aa",
}

BOX_WIDTH = 42


def display_width(text: str) -> int:
    width = 0
    for char in text:
        if unicodedata.east_asian_width(char) in ("W", "F"):
            width += 2
        else:
            width += 1
    return width


def pad(text: str, width: int) -> str:
    padding = max(0, width - display_width(text))
    return text + " " * padding


def fmt_price(value: float | None) -> str:
    if value is None:
        return "n/a"
    if abs(value) >= 100:
        return f"{value:,.2f}"
    if abs(value) >= 1:
        return f"{value:.5f}"
    return f"{value:.6f}"


def _line(text: str, width: int = BOX_WIDTH) -> str:
    return "\u2551" + pad(" " + text, width) + "\u2551"


def _divider(width: int = BOX_WIDTH, char: str = "\u2500") -> str:
    return "\u2560" + char * width + "\u2563"


def _top(width: int = BOX_WIDTH) -> str:
    return "\u2554" + "\u2550" * width + "\u2557"


def _bottom(width: int = BOX_WIDTH) -> str:
    return "\u255a" + "\u2550" * width + "\u255d"


def _title(text: str, width: int = BOX_WIDTH) -> str:
    padding = max(0, width - display_width(text))
    left = padding // 2
    right = padding - left
    return "\u2551" + " " * left + text + " " * right + "\u2551"


def _liquidity_line(report: AnalysisReport) -> str:
    if report.liquidity is None:
        return "n/a"
    if report.liquidity.last_sweep is not None:
        return f"POTENTIAL {report.liquidity.last_sweep.value.lower()} sweep"
    if report.liquidity.nearest_buyside and report.liquidity.nearest_sellside:
        return "POTENTIAL both sides mapped"
    if report.liquidity.nearest_buyside:
        return "POTENTIAL buy-side above"
    if report.liquidity.nearest_sellside:
        return "POTENTIAL sell-side below"
    return "none detected"


def format_analysis(report: AnalysisReport) -> str:
    lines: list[str] = []
    title = f"{report.symbol} {report.timeframe} ANALYSIS"
    rows: list[str | None] = []

    signal = report.decision.signal
    icon = SIGNAL_ICONS.get(signal, "")
    bias = report.decision.bias.value
    rows.append(f"Bias        : {bias}")
    rows.append(f"Signal      : {icon} {signal}")
    if report.score is not None:
        rows.append(f"Score       : {report.score.score:.0f}/100 ({report.score.label})")
        rows.append(f"Confidence  : {report.score.confidence * 100:.0f}%")
    else:
        rows.append("Score       : n/a")
        rows.append("Confidence  : n/a")

    if report.entry is not None:
        plan = report.entry
        rows.append(None)
        rows.append(
            f"Entry zone  : {fmt_price(plan.entry_lower)} - {fmt_price(plan.entry_upper)}"
        )
        rows.append(f"Stop loss   : {fmt_price(plan.stop_loss)}")
        targets = plan.targets
        if targets:
            tp_text = " / ".join(fmt_price(value) for value in targets[:3])
            rows.append(f"Targets     : {tp_text}")
        if plan.rr_values:
            rr_text = " / ".join(f"{value:.2f}R" for value in plan.rr_values[:3])
            rows.append(f"R:R         : {rr_text}")
        rows.append(f"Entry model : {plan.model}")
    else:
        rows.append(None)
        rows.append("Entry zone  : n/a (no scenario)")

    rows.append(None)
    rows.append(
        f"Structure   : {report.structure.trend.value if report.structure else 'n/a'}"
        f"{' (BOS ' + report.structure.bos + ')' if report.structure and report.structure.bos != 'NONE' else ''}"
    )
    rows.append(f"Liquidity   : {_liquidity_line(report)}")
    rows.append(f"Momentum    : {report.momentum.state.value if report.momentum else 'n/a'}")
    rows.append(
        f"Volatility  : {report.volatility.classification.value if report.volatility else 'n/a'}"
    )
    rows.append(f"News risk   : {report.news.risk_level}")
    if report.mtf is not None:
        rows.append(f"Timeframes  : {report.mtf.alignment.lower()}")

    content_widths = [
        display_width(" " + row) for row in rows if row is not None
    ] + [display_width(title)]
    width = max(BOX_WIDTH, *content_widths)

    lines.append(_top(width))
    lines.append(_title(title, width) if display_width(title) < width else _line(title, width))
    lines.append(_divider(width))
    for row in rows:
        if row is None:
            lines.append(_divider(width))
        else:
            lines.append(_line(row, width))
    lines.append(_bottom(width))
    lines.append(f"FINAL STATUS: {signal}")

    if report.data_status != "SUFFICIENT":
        lines.append(f"DATA STATUS : {report.data_status}")
        for reason in report.data_reasons:
            lines.append(f"  - {reason}")

    if report.entry is not None:
        lines.append("")
        lines.append("Scenario")
        lines.append(f"  Confirmation : {report.entry.confirmation}")
        lines.append(f"  Invalidation : {report.entry.invalidation}")
        for note in report.entry.notes:
            lines.append(f"  Note         : {note}")

    lines.append("")
    lines.append("Reasoning")
    for reason in report.decision.reasons:
        lines.append(f"  - {reason}")

    if report.risk is not None:
        risk = report.risk
        lines.append("")
        lines.append("Risk estimate (educational)")
        lines.append(
            f"  Balance {risk.balance:.2f} | risk {risk.risk_pct:.2f}% "
            f"= {risk.risk_amount:.2f} | stop distance {risk.stop_distance:.5f} "
            f"({risk.stop_pct:.2f}%)"
        )
        lines.append(
            f"  Position estimate: {risk.position_units:,.4f} units "
            f"(~{risk.standard_lots:,.4f} standard lots)"
            + (f" | {risk.pips:,.1f} pips" if risk.pips is not None else "")
        )
        for warning in risk.warnings:
            lines.append(f"  Warning: {warning}")
        lines.append("  Estimates only - verify contract specs with your broker.")

    if report.warnings:
        lines.append("")
        lines.append("Warnings")
        for warning in report.warnings:
            lines.append(f"  - {warning}")

    lines.append("")
    lines.append(
        "Educational analysis only - not financial advice. No outcome is"
    )
    lines.append(
        "guaranteed; this is a scenario with confirmation and invalidation."
    )
    return "\n".join(lines)


def format_news(report: NewsReport, symbol: str) -> str:
    lines = [f"News / macro risk for {symbol}: {report.risk_level} (source: {report.source})"]
    lines.append(f"  {report.reason}")
    if report.events:
        lines.append("  Upcoming/relevant events:")
        for event in report.events:
            lines.append(
                f"    {event.time.isoformat()} {event.currency} "
                f"[{event.importance}] {event.title}"
            )
    else:
        lines.append("  No events in the configured window.")
    if not report.known:
        lines.append("  NOTE: status is UNKNOWN - no events are shown because no")
        lines.append("  live news source is configured or reachable.")
    return "\n".join(lines)


def format_paper_stats(stats: PaperStats, title: str = "Paper trading performance") -> str:
    lines = [title]
    lines.append(
        f"  balance {stats.balance:,.2f} | equity {stats.equity:,.2f} | "
        f"open positions {stats.open_positions}"
    )
    lines.append(
        f"  trades {stats.total_trades} | wins {stats.wins} | losses {stats.losses} | "
        f"win rate {stats.win_rate * 100:.1f}%"
    )
    profit_factor = f"{stats.profit_factor:.2f}" if stats.profit_factor is not None else "n/a"
    lines.append(
        f"  gross profit {stats.gross_profit:,.2f} | gross loss {stats.gross_loss:,.2f} | "
        f"profit factor {profit_factor}"
    )
    lines.append(
        f"  expectancy {stats.expectancy:,.2f} | total P/L {stats.total_pnl:,.2f} "
        f"({stats.return_pct:+.2f}%)"
    )
    lines.append(
        f"  max drawdown {stats.max_drawdown:,.2f} "
        f"({stats.max_drawdown_pct:.2f}%) | best {stats.best_trade:,.2f} | "
        f"worst {stats.worst_trade:,.2f}"
    )
    return "\n".join(lines)


def format_backtest(result: BacktestResult, max_trades: int = 10) -> str:
    lines = [
        f"Backtest {result.symbol} {result.timeframe} ({result.provider})",
        f"  bars replayed {result.bars} | evaluated {result.evaluated_bars} | "
        f"signals {result.signals_generated} | orders filled {result.orders_filled}",
    ]
    lines.append(format_paper_stats(result.stats, title="  Statistics"))
    if result.trades:
        lines.append("  Recent trades:")
        for trade in result.trades[-max_trades:]:
            lines.append(
                f"    {trade.side:5s} entry {trade.entry_price:.5f} -> "
                f"exit {trade.exit_price if trade.exit_price is not None else float('nan'):.5f} "
                f"({trade.reason}) pnl {trade.pnl:+.2f}"
            )
    for note in result.notes:
        lines.append(f"  Note: {note}")
    lines.append("  Limitations:")
    for limitation in result.limitations:
        lines.append(f"    - {limitation}")
    lines.append("  Historical results are NOT evidence of future performance.")
    return "\n".join(lines)
