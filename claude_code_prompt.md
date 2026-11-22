# Task: Start Stage E of the trading system, reusing the existing project

## Context

Read these two files in this folder before doing anything else:

1. `CLAUDE.md` — the existing XGBoost project (data fetcher, features, training, Alpaca skeleton).
2. The proposal document ("Agentic Quant Trading System — Proposal") — the target design.

The proposal is the source of truth. The existing project is raw material: reuse what fits, change what conflicts, and keep nothing just because it exists.

Key points from the proposal you must follow:

- Staged path: **E** (known published strategies) → **D** (human research with AI help) → **B** (autonomous research agent). We are starting **Stage E** only.
- Research runs on this PC; live trading runs on a Raspberry Pi 5. The PC never holds broker keys; the Pi never runs LLMs.
- Strategy = a function: given data up to today, return target weights. The same code runs in backtests and live.
- Long-only, cash account, max 25% per stock, trade at the next open after a signal, fees and slippage always applied.
- History is split into research / validation / locked holdout (most recent 2–3 years). Nothing reads holdout results except the promotion-check code.

## Hard rules

- Paper trading only. Never call a live-trading endpoint. Never place real orders.
- Never read, print, log or commit the contents of `.env` or any API key.
- Don't delete existing files. Move anything retired into `legacy/` with a one-line note on why.
- Ask before: adding a dependency, restructuring folders beyond what's described here, or changing any risk limit.
- Stop at the end of each step below, summarise what you did and what you found, and wait for my go-ahead.

## Step 1: Audit (no code changes)

Read every file in the existing project and report:

1. What each file does, and whether it's **reuse as-is**, **reuse with changes**, or **retire**, judged against the proposal.
2. Check these specific concerns and say whether each is real:
   - **Untradable target.** The label is today's close vs yesterday's close, but trades execute at today's open. Does the label include the overnight gap that can't be captured? What should the label be instead (for example next-day open-to-close, or a multi-day forward return from the next open)?
   - **Evaluation.** Is the model judged only by accuracy or log-loss rather than strategy returns after fees?
   - **Validation leakage.** Early stopping uses the validation set; is the reported validation score therefore optimistic?
   - **No holdout.** Is there any untouched test period?
   - **Ticker selection.** Were the 20 stocks picked with hindsight (survivorship bias)?
   - **Auto-retrain.** Does `retrain.py` overwrite the model with no versioning or check before use?
   - **Data source.** yfinance is unofficial; flag reliability risks for live use.
3. List anything else that conflicts with the proposal.

## Step 2: Verify the research platform

1. Detect the OS (native Linux, WSL2 or other) and report it.
2. Install Qlib per its official docs in an isolated environment (use `uv` if Qlib supports the needed Python version; otherwise say what it needs).
3. Confirm Qlib can load **US daily price data from a free source** and run its own example backtest. Report exactly what worked and what didn't.
4. Check RD-Agent's requirements (OS, Docker, model providers, US data support). Don't install it yet; just report.
5. If Qlib can't work with free US data, stop and propose an alternative backtesting library, with reasons.

## Step 3: Project structure

Propose, then (after my go-ahead) create:

```
research/        # PC only
  data/          # loaders, quality checks, split definitions
  engine/        # fixed backtest settings: fees, slippage, next-open execution, limits
  strategies/    # one file per strategy, standard interface
  trials/        # automatic trial log
  gates/         # promotion checks (empty for now)
live/            # Pi only
  engine/        # pulls approved strategies, computes weights, queues orders
  risk/          # risk layer and hard stop
  broker/        # Alpaca paper adapter (alpaca-py)
  ledger/        # SQLite
shared/          # strategy interface, universe, config both sides read
legacy/          # retired code from the old project
tests/
```

Map each existing file to its new home or to `legacy/`.

## Step 4: Data and splits

1. Reuse the existing fetcher's incremental download and de-duplication logic where it fits; adapt it to feed Qlib (or the chosen library).
2. Add data checks: missing days, splits, dividends, stale prices. Report survivorship-bias limits of the free source.
3. Define research / validation / holdout periods in one config file. Make holdout unreadable from strategy and research code (enforced, not just documented).

## Step 5: Fixed engine and strategy interface

1. One strategy interface in `shared/`: input = data up to date T; output = target weights (long-only, sum ≤ 1, max 0.25 each).
2. Fixed backtest settings in one config file: fees, slippage, signals at close and execution at next open, cash only.
3. A look-ahead test: altering prices after date T must not change the output for date T. Run it on every strategy.

## Step 6: Benchmark strategies

Implement and backtest on research + validation periods only:

1. Momentum: strongest stocks by 12-month return skipping the last month, rebalanced monthly.
2. Trend: index ETF while above its 200-day average, otherwise cash or a short-term bond ETF.
3. Low volatility: least volatile stocks, rebalanced monthly.
4. Buy-and-hold of one broad index ETF.

Report for each: annualised return after costs, max drawdown, turnover, and comparison with buy-and-hold.

## Step 7: The existing XGBoost model

Don't make it a benchmark. Convert it into a **Stage D candidate**:

1. Fix the label per your Step 1 finding.
2. Wrap it in the standard strategy interface (predicted probabilities → target weights).
3. Evaluate by strategy returns after costs, not accuracy.
4. Log it as the first entry in the trial log.
5. Replace auto-retrain-and-overwrite with versioned models; a new version is only a candidate, never used automatically.

## Out of scope for now

Live engine on the Pi, risk layer, watchdog, gates, agents, RD-Agent install. These come after Stage E's research side works.

## Start

Begin with Step 1 and stop after reporting.
