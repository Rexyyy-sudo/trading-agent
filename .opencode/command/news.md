---
description: Macro/news risk report for a symbol, e.g. /news XAUUSD
agent: trading-analyst
---

News risk for: $ARGUMENTS

1. Parse `$ARGUMENTS` as `<SYMBOL> [HOURS]` (hours is an optional lookahead
   override).
2. Call the `news` tool with the symbol and optional hours.
3. Report the risk level (LOW/MEDIUM/HIGH/EXTREME/UNKNOWN), the reason, and
   any listed events. If the level is UNKNOWN, explain that no live news
   source is configured (see .env.example) - do not speculate about news.
4. Remind: extreme news risk makes the framework output NO TRADE.
