---
description: Walk-forward backtest a symbol, e.g. /backtest BTCUSDT M15
agent: trading-analyst
---

Backtest: $ARGUMENTS

Steps:
1. Parse `$ARGUMENTS` as `<SYMBOL> [TIMEFRAME]`. Default timeframe is M5.
2. Call the `technical_analysis` tool only if context is needed; otherwise
   run the backtest directly:
   `.venv/bin/python -m src.main backtest <SYMBOL> -t <TIMEFRAME> --json`
   (add `--limit 1500 --bars 800` for deeper runs when asked).
3. If the fetch fails, call `market_data` action `providers` and report
   which sources are available; optionally fetch CSV data first.
4. Report: bars replayed/evaluated, signals, orders filled, trade
   statistics (win rate, profit factor, expectancy, drawdown), and the full
   limitations list from the output.
5. State clearly: "Historical results are not evidence of future
   performance." Never present backtest output as expected profit.
