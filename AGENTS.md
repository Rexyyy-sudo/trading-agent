# AGENTS.md - working notes for coding agents in this repository

## What this project is

`trading-agent` is a modular, educational market-analysis framework:
market data -> validation -> structure/trend/S-R/liquidity/momentum/
volatility/volume -> multi-timeframe context -> news risk -> scoring ->
LONG/SHORT/WAIT/NO TRADE decision -> entry scenario -> risk estimate ->
paper trading -> backtest. It never trades live and never fabricates data.

## Hard rules (do not violate)

- **Never fabricate market data.** Missing data must produce an explicit
  INSUFFICIENT/PARTIAL status or "NO TRADE - INSUFFICIENT DATA". Synthetic
  data is allowed **only** in `tests/` and `scripts/make_synthetic_csv.py`
  and must be clearly labelled as synthetic.
- **Never promise profit or predict outcomes.** Outputs are scenarios with
  confirmation/invalidation, plus disclaimers.
- **No live trading, ever.** `src/paper/` is a simulation; do not add broker
  execution. No secrets in code; API keys come from environment variables.
- Keep financial math deterministic and documented; heuristics carry
  confidence values and limitations, never false precision.

## Environment

- Python 3.11+ (dev machine uses `.venv` with Python 3.14).
- Install: `python -m venv .venv && .venv/bin/pip install -e ".[dev]" -r requirements.txt`
- Run everything through the venv: `.venv/bin/python -m src.main ...`

## Commands

- Tests: `.venv/bin/pytest` (config in `pyproject.toml`, pythonpath `.`)
- Lint: `.venv/bin/ruff check src tests`
- Byte-compile: `.venv/bin/python -m compileall -q src tests`
- CLI: `.venv/bin/python -m src.main --help`
- Offline demo data: `.venv/bin/python scripts/make_synthetic_csv.py`

## Layout

- `src/market/` - symbols, timeframes, candles, providers (csv/binance/
  yahoo/twelvedata/alphavantage/null), provider chain with fallbacks.
- `src/analysis/` - indicators + analyzers (pure pandas/numpy). Types and
  enums live in `src/analysis/types.py`.
- `src/news/` - news/macro risk providers (`none` yields UNKNOWN).
- `src/signal/` - scorer, decision gates, entry model (scenario builder).
- `src/risk/` - position sizing and risk calculator.
- `src/paper/` - account store, broker, candle simulator (simulation only).
- `src/backtest/` - walk-forward engine with explicit limitations.
- `src/agent/` - schemas, prompts, orchestrator pipeline.
- `src/reporting/` - terminal formatters (box output, stats tables).
- `src/utils/` - config loading/validation, errors, logging, validation.
- `config/settings.yaml` - all tunables; `src/utils/config.py` holds
  DEFAULTS and validation. Keep them in sync when adding keys.
- `tests/` - pytest suite; `tests/conftest.py` has synthetic builders.
- `.opencode/` - OpenCode agent, commands, tools; `opencode.json` wires
  permissions. Tool files import `tool` from `@opencode-ai/plugin` and share
  helpers from `.opencode/lib/cli.ts`.

## Conventions

- Study a neighbouring module before writing new ones; match docstring and
  dataclass style (results expose `as_dict()`).
- New pipelines must remain deterministic (`DEFAULT_*` constants, no random).
- Tests are offline: use the CSV provider and `tmp_path`; never call the
  network in tests.
- After changes always run pytest + ruff and fix failures before finishing.
- When adding config keys: update `DEFAULTS` **and** `config/settings.yaml`,
  plus any validation/`Settings` dataclass.
