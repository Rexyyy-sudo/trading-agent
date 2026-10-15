#!/usr/bin/env python3
"""trading-agent CLI.

Examples:
    python -m src.main analyze XAUUSD M5
    python -m src.main analyze BTCUSDT --timeframes H1,M15,M5
    python -m src.main analyze XAUUSD M5 --json
    python -m src.main fetch XAUUSD -t M5 --provider yahoo
    python -m src.main backtest BTCUSDT -t M15
    python -m src.main paper status
    python -m src.main paper open XAUUSD LONG --entry 4337 --sl 4344 --risk-pct 1
    python -m src.main providers

This tool is educational ONLY: it analyzes data, it does not trade live.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent.orchestrator import Orchestrator  # noqa: E402
from src.agent.prompts import explain_report  # noqa: E402
from src.backtest.engine import run_backtest  # noqa: E402
from src.market.data_provider import build_provider, provider_names  # noqa: E402
from src.market.providers.csv_provider import save_series_csv  # noqa: E402
from src.market.symbols import resolve_symbol  # noqa: E402
from src.market.timeframes import normalize_timeframe, parse_timeframes  # noqa: E402
from src.paper.account import AccountStore  # noqa: E402
from src.paper.broker import PaperBroker  # noqa: E402
from src.paper.simulator import run_over_candles, summarize  # noqa: E402
from src.reporting.formatter import (  # noqa: E402
    format_analysis,
    format_backtest,
    format_news,
    format_paper_stats,
)
from src.utils.config import Settings, load_settings  # noqa: E402
from src.utils.errors import TradingAgentError  # noqa: E402
from src.utils.logging import setup_logging  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trading-agent",
        description=(
            "Modular market-analysis agent (analysis, scoring, risk, paper trading). "
            "Educational use only - no live execution."
        ),
    )
    parser.add_argument("--config", help="path to settings.yaml", default=None)
    parser.add_argument("--quiet", action="store_true", help="only show warnings/errors")
    parser.add_argument("--debug", action="store_true", help="show tracebacks on errors")
    sub = parser.add_subparsers(dest="command")

    analyze = sub.add_parser("analyze", help="full multi-timeframe analysis")
    analyze.add_argument("symbol")
    analyze.add_argument("timeframe", nargs="?", default=None, help="entry timeframe, e.g. M5")
    analyze.add_argument("-T", "--timeframes", default=None, help="comma list, e.g. H1,M15,M5")
    analyze.add_argument("-p", "--provider", default="auto")
    analyze.add_argument("--limit", type=int, default=None)
    analyze.add_argument("--json", action="store_true", help="machine-readable output")
    analyze.add_argument("--explain", action="store_true", help="append deterministic explanation")

    price = sub.add_parser("price", help="latest price and provenance")
    price.add_argument("symbol")
    price.add_argument("-p", "--provider", default="auto")

    fetch = sub.add_parser("fetch", help="download candles to data/raw as CSV")
    fetch.add_argument("symbol")
    fetch.add_argument("-t", "--timeframe", default=None)
    fetch.add_argument("-T", "--timeframes", default=None)
    fetch.add_argument("-p", "--provider", default="auto")
    fetch.add_argument("--limit", type=int, default=1000)
    fetch.add_argument("--out-dir", default=None)

    news = sub.add_parser("news", help="macro/news risk report")
    news.add_argument("symbol")
    news.add_argument("--hours", type=int, default=None, help="lookahead hours override")

    sub.add_parser("providers", help="show provider availability")

    paper = sub.add_parser("paper", help="paper trading (simulation only)")
    paper_sub = paper.add_subparsers(dest="paper_command", required=True)
    paper_sub.add_parser("status", help="account status and statistics")
    paper_sub.add_parser("history", help="closed trade history")
    reset = paper_sub.add_parser("reset", help="reset the virtual account")
    reset.add_argument("--balance", type=float, default=None)

    open_parser = paper_sub.add_parser("open", help="open a simulated position")
    open_parser.add_argument("symbol")
    open_parser.add_argument("side", choices=["LONG", "SHORT", "long", "short"])
    open_parser.add_argument("--entry", type=float, required=True)
    open_parser.add_argument("--sl", type=float, default=None)
    open_parser.add_argument("--tp", type=float, default=None)
    open_parser.add_argument("--size", type=float, default=None)
    open_parser.add_argument("--risk-pct", type=float, default=None)
    open_parser.add_argument("--timeframe", default="")
    open_parser.add_argument("--note", default="")

    close_parser = paper_sub.add_parser("close", help="close a simulated position")
    close_parser.add_argument("position_id")
    close_parser.add_argument("--price", type=float, default=None)

    simulate = paper_sub.add_parser("simulate", help="replay candles against open positions")
    simulate.add_argument("symbol")
    simulate.add_argument("-t", "--timeframe", default=None)
    simulate.add_argument("-p", "--provider", default="auto")
    simulate.add_argument("--limit", type=int, default=500)

    backtest = sub.add_parser("backtest", help="walk-forward rule-based backtest")
    backtest.add_argument("symbol")
    backtest.add_argument("-t", "--timeframe", default=None)
    backtest.add_argument("-p", "--provider", default="auto")
    backtest.add_argument("--limit", type=int, default=1500, help="candles to fetch")
    backtest.add_argument("--bars", type=int, default=800, help="max bars to replay")
    backtest.add_argument("--json", action="store_true")

    return parser


def _paper_broker(settings: Settings) -> PaperBroker:
    store = AccountStore(
        settings.resolve_path(settings.paper.storage_path),
        starting_balance=settings.paper.starting_balance,
    )
    return PaperBroker(store)


def cmd_analyze(args, settings: Settings) -> int:
    orchestrator = Orchestrator(settings, provider_name=args.provider)
    report = orchestrator.analyze(
        args.symbol, timeframe=args.timeframe, timeframes=args.timeframes, limit=args.limit
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print(format_analysis(report))
        if args.explain:
            print()
            print(explain_report(report))
    return 0


def cmd_price(args, settings: Settings) -> int:
    orchestrator = Orchestrator(settings, provider_name=args.provider)
    price, note, provider = orchestrator.latest_price(args.symbol)
    print(f"{args.symbol}: {price} (provider: {provider}; {note})")
    return 0


def cmd_fetch(args, settings: Settings) -> int:
    info = resolve_symbol(args.symbol)
    if args.timeframes:
        timeframes = parse_timeframes(args.timeframes)
    elif args.timeframe:
        timeframes = [normalize_timeframe(args.timeframe)]
    else:
        timeframes = [normalize_timeframe(settings.symbols.default_timeframes[-1])]
    out_dir = (
        Path(args.out_dir) if args.out_dir else settings.resolve_path(settings.providers.csv_dir)
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    orchestrator = Orchestrator(settings, provider_name=args.provider)
    failures = 0
    for timeframe in timeframes:
        try:
            bundle = orchestrator.fetch(info, [timeframe], args.limit)
            series = bundle.series[timeframe]
        except TradingAgentError as exc:
            print(f"{info.symbol} {timeframe}: FAILED - {exc}", file=sys.stderr)
            failures += 1
            continue
        path = out_dir / f"{info.symbol}_{timeframe}.csv"
        save_series_csv(series, path)
        print(
            f"{info.symbol} {timeframe}: saved {len(series)} candles to {path} "
            f"(provider: {bundle.provider})"
        )
    return 1 if failures == len(timeframes) else 0


def cmd_news(args, settings: Settings) -> int:
    info = resolve_symbol(args.symbol)
    if args.hours:
        settings.news.lookahead_hours = int(args.hours)
    orchestrator = Orchestrator(settings)
    report = orchestrator.news_provider.get_report(info)
    print(format_news(report, info.symbol))
    return 0


def cmd_providers(args, settings: Settings) -> int:
    print("Provider availability:")
    for name in provider_names():
        provider = build_provider(name, settings)
        availability = provider.availability()
        status = "available" if availability.available else "unavailable"
        print(f"  {name:14s} {status:12s} {availability.reason}")
    return 0


def cmd_paper(args, settings: Settings) -> int:
    broker = _paper_broker(settings)

    if args.paper_command == "status":
        prices: dict[str, float] = {}
        orchestrator = Orchestrator(settings)
        for position in broker.state.open_positions:
            try:
                price, _, _ = orchestrator.latest_price(position.symbol)
                prices[position.symbol] = price
            except TradingAgentError:
                pass
        print(format_paper_stats(broker.stats(prices)))
        if broker.state.open_positions:
            print("Open positions:")
            for position in broker.state.open_positions:
                current = prices.get(position.symbol)
                unrealized = (
                    position.unrealized_pnl(current) if current is not None else 0.0
                )
                print(
                    f"  {position.id} {position.side:5s} {position.symbol} "
                    f"size {position.size:g} entry {position.entry_price:g} "
                    f"SL {position.stop_loss} TP {position.take_profit} "
                    f"unrealized {unrealized:+.2f}"
                )
        else:
            print("No open positions.")
        return 0

    if args.paper_command == "history":
        trades = broker.state.trades
        if not trades:
            print("No closed trades yet.")
            return 0
        for trade in trades:
            print(
                f"{trade.id} {trade.side:5s} {trade.symbol} entry "
                f"{trade.entry_price:g} exit {trade.exit_price} "
                f"({trade.close_reason}) pnl {trade.pnl:+.2f}"
            )
        return 0

    if args.paper_command == "reset":
        state = broker.reset(args.balance)
        print(f"Paper account reset. Balance: {state.balance:,.2f}")
        return 0

    if args.paper_command == "open":
        side = args.side.upper()
        entry = args.entry
        size = args.size
        if size is None:
            if args.sl is None:
                print(
                    "error: provide --size or --sl (for automatic risk-based sizing)",
                    file=sys.stderr,
                )
                return 1
            risk_pct = (
                args.risk_pct
                if args.risk_pct is not None
                else settings.risk.default_risk_pct
            )
            risk_cash = broker.state.balance * risk_pct / 100.0
            distance = abs(entry - args.sl)
            if distance <= 0:
                print("error: entry and stop must differ", file=sys.stderr)
                return 1
            size = risk_cash / distance
            print(
                f"Auto-sized: risk {risk_pct:.2f}% = {risk_cash:,.2f} / "
                f"distance {distance:g} -> size {size:,.4f}"
            )
        position = broker.open_position(
            symbol=args.symbol.upper(),
            side=side,
            size=size,
            entry_price=entry,
            stop_loss=args.sl,
            take_profit=args.tp,
            timeframe=args.timeframe,
            note=args.note,
        )
        print(f"Opened paper position {position.id}: {side} {position.symbol}")
        print("Remember: simulated only; no live order was placed.")
        return 0

    if args.paper_command == "close":
        position = None
        for candidate in broker.state.open_positions:
            if candidate.id == args.position_id:
                position = candidate
                break
        if position is None:
            print(f"error: no open position with id {args.position_id!r}", file=sys.stderr)
            return 1
        price = args.price
        if price is None:
            orchestrator = Orchestrator(settings)
            price, note, _ = orchestrator.latest_price(position.symbol)
            print(f"Using latest price {price} ({note})")
        closed = broker.close_position(position.id, price, reason="MANUAL")
        print(f"Closed {closed.id} at {closed.exit_price}: P/L {closed.pnl:+.2f}")
        return 0

    if args.paper_command == "simulate":
        broker = _paper_broker(settings)
        open_symbols = {position.symbol for position in broker.state.open_positions}
        symbols = open_symbols or {args.symbol.upper()}
        orchestrator = Orchestrator(settings, provider_name=args.provider)
        timeframe = (
            normalize_timeframe(args.timeframe)
            if args.timeframe
            else normalize_timeframe(settings.symbols.default_timeframes[-1])
        )
        total_events = 0
        for symbol in sorted(symbols):
            info = resolve_symbol(symbol)
            try:
                bundle = orchestrator.fetch(info, [timeframe], args.limit)
            except TradingAgentError as exc:
                print(f"{symbol}: skipped - {exc}", file=sys.stderr)
                continue
            report = run_over_candles(broker, symbol, bundle.series[timeframe])
            print(f"{symbol}: {summarize(report)}")
            total_events += len(report.closed_events)
        if not total_events and not broker.state.open_positions:
            print("No open positions to simulate.")
        return 0

    return 1


def cmd_backtest(args, settings: Settings) -> int:
    info = resolve_symbol(args.symbol)
    timeframe = (
        normalize_timeframe(args.timeframe)
        if args.timeframe
        else normalize_timeframe(settings.symbols.default_timeframes[-1])
    )
    orchestrator = Orchestrator(settings, provider_name=args.provider)
    bundle = orchestrator.fetch(info, [timeframe], args.limit)
    series = bundle.series[timeframe]
    result = run_backtest(
        series, settings, provider_name=bundle.provider, max_bars=args.bars
    )
    if args.json:
        print(json.dumps(result.as_dict(), indent=2, default=str))
    else:
        print(format_backtest(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    try:
        settings = load_settings(args.config)
    except TradingAgentError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 1
    setup_logging(settings.app.log_level, quiet=args.quiet)

    handlers = {
        "analyze": cmd_analyze,
        "price": cmd_price,
        "fetch": cmd_fetch,
        "news": cmd_news,
        "providers": cmd_providers,
        "paper": cmd_paper,
        "backtest": cmd_backtest,
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    try:
        return handler(args, settings)
    except TradingAgentError as exc:
        print(f"error: {exc}", file=sys.stderr)
        if args.debug:
            raise
        return 1
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
