# trading-agent

A modular, educational market-analysis framework. It turns raw OHLCV candles
into a structured, explainable view of the market:

```
market data -> validation -> structure / trend / S-R / liquidity / momentum /
volatility / volume -> multi-timeframe context -> news risk -> weighted score
-> LONG / SHORT / WAIT / NO TRADE -> entry scenario -> risk estimate
-> paper trading (simulation) -> walk-forward backtest
```

**This project never trades live and never fabricates data.** It is a study
tool: every output is a *scenario* with confirmation and invalidation, is
deterministic, and carries explicit warnings instead of promises. Nothing in
this repository is financial advice.

## Features

- Provider chain with fallbacks: CSV (offline), Binance, Yahoo, Twelve Data,
  Alpha Vantage, plus a `null` provider that yields an honest NO TRADE.
- Analysis: trend (EMA), market structure (swings, HH/HL/LH/LL, BOS, CHoCH),
  support/resistance zones, liquidity pools and sweeps, momentum (RSI, MACD,
  displacement), volatility (ATR vs its own baseline), volume.
- Multi-timeframe alignment (HTF/MTF/LTF) with conflict detection.
- Transparent weighted scoring (signed -100..100) with confidence values.
- Decision engine with explicit gates (data, news, volatility, bias, score,
  timeframe conflict, LTF confirmation).
- Entry scenario builder: pullback-retest and breakout-retest models with
  entry zone, structure/ATR stop, and R-multiple targets.
- Risk/position sizing with R:R per target and warnings.
- Paper trading with JSON persistence (simulation only).
- Walk-forward backtester with honest, listed limitations.
- CLI + JSON output + OpenCode agent/commands/tools integration.

## Requirements

- Python 3.11+
- No API keys required for the offline CSV workflow, Binance or Yahoo.

## Installation

```bash
git clone <this repo> trading-agent
cd trading-agent
python -m venv .venv
.venv/bin/pip install -e ".[dev]" -r requirements.txt
```

Optional: copy `.env.example` to `.env` and add API keys (all optional):

| Variable | Provider | Notes |
| --- | --- | --- |
| `TWELVE_DATA_API_KEY` | twelvedata | broad FX/metals/crypto coverage |
| `ALPHA_VANTAGE_API_KEY` | alphavantage | FX/crypto/equities, rate-limited |
| `FINNHUB_API_KEY` | news | macro calendar risk (paid plans for calendar) |
| `MARKET_DATA_API_KEY` | generic | fallback for providers taking a single token |

`config/settings.yaml` holds every tunable (scoring weights, decision
thresholds, risk defaults, provider priority, news window). Defaults live in
`src/utils/config.py`; the file is validated on load and unknown values are
rejected with clear errors.

## Quick start (offline, no keys)

```bash
# 1. Create SYNTHETIC demo candles (clearly not real market data)
.venv/bin/python scripts/make_synthetic_csv.py --symbol XAUUSD --bars 400

# 2. Analyse them with the CSV provider
.venv/bin/python -m src.main analyze XAUUSD M5 --provider csv --explain

# 3. Machine-readable output
.venv/bin/python -m src.main analyze XAUUSD M5 --provider csv --json
```

Real data (network required):

```bash
.venv/bin/python -m src.main providers                       # availability
.venv/bin/python -m src.main fetch BTCUSDT -t M5 -p binance  # save to data/raw
.venv/bin/python -m src.main fetch XAUUSD -t H1 -p yahoo     # GC=F futures proxy, labelled
.venv/bin/python -m src.main analyze BTCUSDT M5 -p binance
```

## CLI reference

```
trading-agent analyze SYMBOL [TIMEFRAME] [-T H1,M15,M5] [-p PROVIDER] [--limit N] [--json] [--explain]
trading-agent price SYMBOL [-p PROVIDER]
trading-agent fetch SYMBOL [-t TF | -T LIST] [-p PROVIDER] [--limit N] [--out-dir DIR]
trading-agent news SYMBOL [--hours N]
trading-agent providers
trading-agent paper {status,history,reset,open,close,simulate} ...
trading-agent backtest SYMBOL [-t TF] [-p PROVIDER] [--limit N] [--bars N] [--json]
```

Global flags: `--config PATH`, `--quiet`, `--debug`.

When no timeframe is given, the framework derives a set from the entry
timeframe (e.g. `M5 -> H1, M15, M5`) and labels roles HTF/MTF/LTF.

## How the analysis works

1. **Validation** - candles are checked (ordering, duplicates, OHLC sanity);
   too few bars (< `analysis.min_bars`, default 120) mean INSUFFICIENT DATA.
2. **Per-timeframe analysis** - structure first (swings, BOS/CHoCH),
   then trend, S/R zones, liquidity, momentum, volatility, volume.
3. **Multi-timeframe** - HTF/MTF/LTF alignment with a multiplier
   (aligned 1.15, mixed 0.85, conflicting 0.55, unknown 0.80).
4. **News risk** - LOW/MEDIUM/HIGH/EXTREME/UNKNOWN (UNKNOWN when no source
   is configured; that is reported, not guessed).
5. **Score** - weighted components (defaults: structure 30%, liquidity 20%,
   momentum 15%, trend 15%, S/R 10%, volatility 5%, volume 5%), signed by
   direction, confidence-weighted, insufficient components excluded and
   reported. Labels: WEAK < 40 <= MIXED < 60 <= MODERATE < 75 <= STRONG <
   90 <= VERY STRONG.
6. **Decision gates** (in order): sufficient data -> EXTREME news NO TRADE ->
   EXTREME volatility WAIT -> neutral bias WAIT -> score below threshold
   (default 65) WAIT -> timeframe conflict WAIT -> fewer than 2 aligned
   timeframes WAIT -> LTF confirmation WAIT -> LONG/SHORT.
7. **Entry scenario** - PULLBACK_RETEST when price is near the relevant S/R
   level, else BREAKOUT_RETEST; stop from structure (+0.5 ATR buffer) or ATR;
   targets at R multiples (1R/2R/3R) with R:R reported per target.
8. **Risk estimate** - position sizing from balance, risk %, entry and stop,
   with warnings (risk cap exceeded, weak R:R, wrong-side targets ignored).

## Paper trading (simulation only)

```bash
.venv/bin/python -m src.main paper status
.venv/bin/python -m src.main paper open XAUUSD LONG --entry 2350 --sl 2340 --risk-pct 1
.venv/bin/python -m src.main paper simulate XAUUSD -p csv --limit 400
.venv/bin/python -m src.main paper history
.venv/bin/python -m src.main paper reset --balance 10000
```

The account persists in `data/paper/account.json`. When stop and target are
both inside one candle, the stop is assumed to fill first (conservative).
No spread, slippage, commission or swap modelling exists - results are
optimistic by construction and must not be read as expected performance.

## Backtesting

```bash
.venv/bin/python -m src.main backtest BTCUSDT -t M15 -p binance --limit 1500 --bars 800
```

Walk-forward: each bar is evaluated with only past data, the decision engine
is reused, and entry orders fill only if price trades into the entry zone
within 10 bars. Limitations are printed with every run (no spread/slippage,
SL-first assumption, single-timeframe, news filter disabled). Historical
results are NOT evidence of future performance.

## OpenCode integration

This repo ships an OpenCode agent, slash commands and tools:

- Agent: `.opencode/agent/trading-analyst.md` (restricted bash; hard rules
  against inventing data or promising outcomes).
- Commands: `/analyze`, `/backtest`, `/paper`, `/news`, `/status`.
- Tools: `technical_analysis`, `market_data`, `risk_calculator`,
  `paper_trade`, `news` (all call the local CLI and return its exact output).
- Project config: `opencode.json` (permissions + AGENTS.md instructions).

OpenCode loads project config once at startup: **restart OpenCode after
changing any `.opencode/` file or `opencode.json`.**

## Testing and lint

```bash
.venv/bin/pytest                # offline test suite (no network calls)
.venv/bin/ruff check src tests
.venv/bin/python -m compileall -q src tests
```

Tests use deterministic synthetic fixtures from `tests/conftest.py` and the
CSV provider with `tmp_path`; they never hit the network. Synthetic data is
test/demo-only and clearly labelled in the code and script output.

## Project layout

```
config/settings.yaml      all tunables
data/                     raw CSVs, paper account, news cache (gitignored)
scripts/make_synthetic_csv.py  demo-only synthetic candles
src/
  agent/                  orchestrator, schemas, prompts
  analysis/               indicators + analyzers + types
  backtest/               walk-forward engine
  market/                 symbols, timeframes, candles, providers/
  news/                   news/macro risk providers
  paper/                  account store, broker, simulator
  reporting/              terminal formatters
  risk/                   position sizing, risk calculator
  signal/                 scorer, decision gates, entry model
  utils/                  config, errors, logging, validation
  main.py                 CLI
tests/                    pytest suite
.opencode/                OpenCode agent, commands, tools
```

## Limitations and safety

- Heuristics, not truth: every analyzer states its limitations and carries a
  confidence value. No indicator set can predict the future.
- Providers can be unavailable, stale or rate-limited; missing data yields an
  explicit INSUFFICIENT/PARTIAL status or NO TRADE. Nothing is interpolated
  or invented.
- Yahoo gold/silver data is served via futures proxies (GC=F, SI=F) and is
  labelled as such in provider notes - it is not spot.
- Paper trading and backtesting ignore spread, slippage, commissions, swap,
  funding and liquidity constraints.
- There is no live-trading code path by design. Do not add one.

Educational analysis only - not financial advice. No outcome is guaranteed;
every setup is a scenario with confirmation and invalidation.
