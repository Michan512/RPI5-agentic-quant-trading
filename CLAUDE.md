# Agentic Quant Trading System

The source of truth is `Pi 5 LLM Trading System — Proposal.pdf`. The current task and its step list are in `claude_code_prompt.md`.

## Current stage

Stage E: research side complete (Steps 1–7). Live side built and tested offline on the laptop with a fake broker, plus the Pi deploy kit in `deploy/` (2026-11-26): reconcile, Telegram alerts, healthchecks.io heartbeat, weekly report, systemd timers, a one-way update via `live-v*` tags. Still needs the Pi itself: follow `deploy/README.md`, then 4 weeks of unattended paper trading.

Stage D started (2026-11-26): promotion gate 1 is built (`research/gates/`) and tested on synthetic data only. **The real holdout has not been opened yet**, and no strategy has taken gate 1. Mistakes log: `research/MISTAKES.md`.

ETF round 1 (2026-11-26): universe extended with 9 asset-class + 9 sector ETFs (sector ETFs capped at 25%); a 60/40 benchmark added; trials 2–5 (asset trend, dual momentum, sector momentum, combo) logged. **None met the pre-set rule** (beat 60/40 and 5%/yr with a fall no deeper than SPY's, in both periods). They cut worst falls a lot (−14% to −23% vs SPY's −55%) but earned less than 60/40. Report: `research/trials/etf_round1.md`. Don't tune these rules to pass; that's overfitting. Total trials: 5.

## Layout

```
research/        # PC only: never holds broker keys
  data/          # fetcher (yfinance), loader (holdout lock), splits.py, checks, qlib_export; raw CSVs in data/raw/ (gitignored)
  engine/        # settings.py (fees, slippage), backtest.py, metrics.py, lookahead.py
  strategies/    # one file per strategy; BENCHMARKS in __init__.py; xgb_candidate.py (Stage D candidate)
  trials/        # trials.jsonl (trial log), benchmarks.md, model_registry.py (versioned models)
  gates/         # gate1.py (fixed checks; the ONLY code allowed to load holdout data), thresholds.py (owner-set), dsr.py (deflated Sharpe); gate_log.jsonl records every attempt
  run_benchmarks.py, run_xgb_candidate.py
live/            # Raspberry Pi only: never runs LLMs
  engine/        # daily.py (the daily run), calendar.py (NYSE days), data.py (providers + freshness check)
  risk/          # limits.py (turnover cap, loss halts, hard stop), layer.py (guards + order planning)
  broker/        # base.py (interface), fake.py (simulator), alpaca_adapter.py (paper only, Pi only)
  ledger/        # db.py: SQLite runs/targets/orders/equity/cash_flows/events
  approved.json  # approved strategies + allocations; kill.py = manual controls; state/ (gitignored)
  reconcile.py, notify.py, report.py, check_broker.py   # ledger-vs-broker, alerts+heartbeat, weekly report, Pi connection test
deploy/          # Pi checklist (README.md), requirements-pi.txt, install_pi.sh, update_pi.sh, systemd/ timers
shared/          # strategy.py (interface, PriceView, validate_weights), universe.py, limits.py
legacy/          # retired XGBoost day-trader (see legacy/README.md)
tests/           # unittest (pytest isn't installed)
```

## Commands (run from the repo root, Windows Python 3.13)

```
python -m research.data.fetcher          # update prices (incremental; re-downloads a symbol if its adjustment changed)
python -m research.data.checks           # data quality report (visible data only)
python -m research.run_benchmarks        # Step 6 report -> research/trials/benchmarks.md
python -m research.run_xgb_candidate     # Step 7: evaluate, append a trial, save a candidate model version
python -m research.run_etf_round1        # ETF round 1: T1–T4 vs SPY and 60/40, logs trials (skips duplicates)
python -m research.gates.gate1 <name>    # explains; add --confirm to spend that version's ONE holdout attempt (ask the owner first)
python -m live.engine.daily --broker fake --dry-run   # laptop: plan today's orders, change nothing
python -m live.engine.daily --broker fake             # laptop: simulated account in live/state/
python -m live.kill [--clear|--resume|--status] [--fake]
python -m live.report --fake                          # weekly report from the simulated account
python -m unittest discover -s tests -t .
```

## Rules

- Paper trading only. Never call a live-trading endpoint.
- Never read, print, log or commit `.env` or any API key.
- Don't delete files; move retired code to `legacy/` with a one-line note in `legacy/README.md`.
- Ask before adding a dependency, restructuring folders, or changing a risk limit (`shared/limits.py`) or engine setting (`research/engine/settings.py`).
- Strategy = `shared.strategy.Strategy`: a PriceView cut at the close of T → target weights (long-only, sum ≤ 1, max 0.25 per stock, broad ETFs up to 1.0). Fills at the next open, costs always applied.
- Never edit `research/data/splits.py` dates to fit a result. Only `research/gates/` may pass `include_holdout=True`.
- Never run gate 1 with --confirm unless the owner asks: each strategy version gets one holdout attempt.
- Every candidate evaluation goes in the trial log (`research.trials.log.log_trial`); benchmarks don't.
- New model versions are candidates only; `load_approved()` requires a manual `approve()`.
- Every result must carry the survivorship-bias note (`shared.universe.SURVIVORSHIP_NOTE`).
- Stop after each step and wait for the user's go-ahead.

## Research environment

Qlib 0.9.7 runs in WSL2 Ubuntu 24.04: venv `~/qlib-check/.venv`, source `~/qlib-check/src`. Running `qrun` needs `MLFLOW_ALLOW_FILE_STORE=true`. The project's own engine is pure pandas (so the same strategy code runs on the Pi); `research/data/qlib_export.py` feeds Qlib the same non-holdout data.

## Open items

- `requirements.txt` is out of date (lists torch, missing xgboost).
- Confirmed by the owner (2026-11-26): drawdown pause at 15%; the 30% turnover cap has no cash exemption, so investing from all cash takes 2 days and trend's 100% switches take about 4.
- Never use real broker keys on the laptop (owner decision): the fake broker only, with Alpaca tested on the Pi.
- Trial #1 (xgb_candidate, 2026-11-25): beats SPY but not an equal-weight hold of the same 19 stocks (research 26.0% vs 24.8%, validation 20.1% vs 21.3%; lower Sharpe; ~2,700% turnover/yr, ~3.2%/yr cost drag). Its edge over SPY is the hindsight universe, not skill. Consider adding equal-weight-universe as a benchmark (needs owner OK).
- Trend benchmark flips 100% between SPY and SHY, which will clash with the proposal's 30%-per-rebalance turnover cap in the live risk layer.
