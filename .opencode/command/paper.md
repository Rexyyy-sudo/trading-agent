---
description: Paper-trading status, history and candle simulation (no live trading)
agent: trading-analyst
---

Paper-trading request: $ARGUMENTS

Allowed actions (simulation only - no live orders exist in this project):
- status: call the `paper_trade` tool with action `status`.
- history: call the `paper_trade` tool with action `history`.
- simulate: call `paper_trade` action `simulate` for a symbol/timeframe.
- open / close: only if the user explicitly gave entry/SL/TP or a position
  id. Format them with the CLI:
  `.venv/bin/python -m src.main paper open <SYMBOL> <LONG|SHORT> --entry <P> --sl <P> --tp <P> --risk-pct 1`
  or `.venv/bin/python -m src.main paper close <POSITION_ID>`.

If the user seems to think this places real trades, correct them: it is a
virtual account stored in `data/paper/account.json`. Report the exact tool
output (balance, equity, trades, stats). Never claim future performance.
