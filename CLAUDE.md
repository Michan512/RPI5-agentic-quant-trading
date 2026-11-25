# Agentic Quant Trading System

The source of truth is `Pi 5 LLM Trading System — Proposal.pdf`. The current task and its step list are in `claude_code_prompt.md`.

## Current stage

Stage E, research side complete (Steps 1–7 done, 2026-11-25). Still to do in Stage E: the live side on the Pi (engine, risk layer, broker, ledger, watchdog), which `claude_code_prompt.md` puts out of scope for now.

## Layout

```
research/        # PC only: never holds broker keys
  data/          # fetcher (yfinance), loader (holdout lock), splits.py, checks, qlib_export; raw CSVs in data/raw/ (gitignored)
  engine/        # settings.py (fees, slippage), backtest.py, metrics.py, lookahead.py
  strategies/    # one file per strategy; BENCHMARKS in __init__.py; xgb_candidate.py (Stage D candidate)
  trials/        # trials.jsonl (trial log), benchmarks.md, model_registry.py (versioned models)
  gates/         # promotion checks (empty); the ONLY code allowed to load holdout data
  run_benchmarks.py, run_xgb_candidate.py
live/            # Raspberry Pi only: never runs LLMs (only broker/alpaca_client.py so far, not yet reworked)
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
python -m unittest discover -s tests -t .
```

## Rules

- Paper trading only. Never call a live-trading endpoint.
- Never read, print, log or commit `.env` or any API key.
- Don't delete files; move retired code to `legacy/` with a one-line note in `legacy/README.md`.
- Ask before adding a dependency, restructuring folders, or changing a risk limit (`shared/limits.py`) or engine setting (`research/engine/settings.py`).
- Strategy = `shared.strategy.Strategy`: a PriceView cut at the close of T → target weights (long-only, sum ≤ 1, max 0.25 per stock, broad ETFs up to 1.0). Fills at the next open, costs always applied.
- Never edit `research/data/splits.py` dates to fit a result. Only `research/gates/` may pass `include_holdout=True`.
- Every candidate evaluation goes in the trial log (`research.trials.log.log_trial`); benchmarks don't.
- New model versions are candidates only; `load_approved()` requires a manual `approve()`.
- Every result must carry the survivorship-bias note (`shared.universe.SURVIVORSHIP_NOTE`).
- Stop after each step and wait for the user's go-ahead.

## Research environment

Qlib 0.9.7 runs in WSL2 Ubuntu 24.04: venv `~/qlib-check/.venv`, source `~/qlib-check/src`. Running `qrun` needs `MLFLOW_ALLOW_FILE_STORE=true`. The project's own engine is pure pandas (so the same strategy code runs on the Pi); `research/data/qlib_export.py` feeds Qlib the same non-holdout data.

## Open items

- Assumptions for the owner to confirm: costs of 1 bp fee + 5 bp slippage per side; broad ETFs exempt from the 25% per-stock cap.
- `requirements.txt` is out of date (lists torch, missing xgboost).
- `live/broker/alpaca_client.py` still imports the old root `config.py`; it gets reworked with the live side.
- Trial #1 (xgb_candidate, 2026-11-25): beats SPY but not an equal-weight hold of the same 19 stocks (research 26.0% vs 24.8%, validation 20.1% vs 21.3%; lower Sharpe; ~2,700% turnover/yr, ~3.2%/yr cost drag). Its edge over SPY is the hindsight universe, not skill. Consider adding equal-weight-universe as a benchmark (needs owner OK).
- Trend benchmark flips 100% between SPY and SHY, which will clash with the proposal's 30%-per-rebalance turnover cap in the live risk layer.
