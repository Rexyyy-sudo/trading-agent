---
description: Analyse a symbol with the trading-agent framework, e.g. /analyze XAUUSD M5
agent: trading-analyst
---

Analyse: $ARGUMENTS

Steps:
1. Parse `$ARGUMENTS` as `<SYMBOL> [TIMEFRAME]`. Default timeframe is M5.
2. Call the `technical_analysis` tool with the symbol and timeframe.
3. If data is INSUFFICIENT or PARTIAL, call `market_data` with action
   `providers`, then fetch what is available - never invent data.
4. Report: final status (LONG / SHORT / WAIT / NO TRADE), score and label,
   structure and multi-timeframe context, entry scenario (zone, stop,
   targets, R:R) if present, reasons, warnings and limitations.
5. Quote all numbers exactly as the tool returned them. End with:
   "Educational analysis only - not financial advice."
