---
description: Show provider availability, paper account status and recent news risk
agent: trading-analyst
---

Project status check.

1. Call `market_data` with action `providers` and report which data sources
   are available/unavailable (and why keys are missing, if any).
2. Call `paper_trade` with action `status` and report the virtual account
   (balance, equity, open positions, statistics).
3. If a symbol is provided ($ARGUMENTS), call `news` for it and report the
   risk level (UNKNOWN is a valid answer - explain why).
4. Keep it short; quote exact numbers from tool output.
