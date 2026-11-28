# Progress log

**Read this first at the start of every session**, then `CLAUDE.md` (rules and commands). At the end of every session, update "Where we are" and "Next step" and add a dated entry to the history. Newest entries first.

Source of truth: `Pi 5 LLM Trading System — Proposal.pdf`.

## Core goal (from the proposal)

- Net return **above 5%/yr after all costs AND above buy-and-hold of an index ETF**.
- Hard limit: total loss never exceeds **$5,000** of deposited money.
- LLMs write and test strategy code; they **never** make a trade decision. The Pi runs approved code inside a fixed risk layer.
- Biggest risk is overfitting, so: a locked holdout, every trial counted, deflated Sharpe, then a 6-month paper period before the first go-live.
- Stages: **E** (published benchmarks, platform, paper trading on the Pi) → **D** (own research + gate 1) → **B** (autonomous agent). If nothing beats buy-and-hold out-of-sample after D, decide whether B is worth its cost before building it.

## Where we are (2026-11-26)

| Stage | Exit checkpoint | Status |
|---|---|---|
| E | 4 weeks of unattended paper trading on the Pi; ledger = broker; Pi weights = backtest weights | Code and deploy kit done; gate 3, shadow books, half-size start and rollback built. **Waiting for the Pi** (owner is travelling). Forward-test clock not started. |
| D | ≥10 logged trials + gate 1 rejects a planted peeker and a planted overfit | **Met.** 10 trials logged; the planted strategies are rejected for the right reasons. |
| B | Planted bad strategies rejected by reviewer agents over 3 rounds | **Built, not run against real models yet** (needs keys). The loop, sandbox, gates 1-2 and pipeline are tested with scripted models and real Docker runs. |

- **Holdout (2024 onwards) is still sealed.** No strategy has taken gate 1. `--confirm` only when the owner asks.
- Round 2 (trials 6–10): **vol_target_15** and **sector_low_vol** met the pre-set round rule (beat 60/40 and 5%, worst fall ≤ SPY's, turnover ≤300%, in both periods). **But neither beat SPY in validation** (8.8% and 8.7% vs 12.1%), and gate 1 requires beating buy-and-hold on the holdout.
- No strategy so far beats buy-and-hold SPY in both periods.

## Next step

**Owner decisions, 2026-11-28:**
1. Build stage B fully. The owner's view: LLM agents are the quants. They research, write code, backtest and trade actively, including deciding when to sell even if the base case is buy-and-hold.
2. Use a custom loop that borrows RD-Agent's design.
3. "Do what's most beneficial" (I skipped the RD-Agent trial run, since it needs keys and spend).

Kept from the proposal: the LLM writes and improves the trading *rules*, and the Pi executes them. No live LLM trade calls; that protects the $5k limit. Frequency is limited only by owner-set limits (gate 1 turnover <=300%/yr, 30%/rebalance on the Pi).

**To do, in order:**
1. **Owner:** `pip install anthropic` on the research machine and set `ANTHROPIC_API_KEY` (and a monthly cap at the provider). For gate 2, set up keys for 2 other providers and put their real model names and prices in `research/agent/config.py` (the current entries are unverified examples).
2. First real session, small: `python -m research.agent.session --ideas 3 --budget-usd 2 --no-submit`. Read the report in `research/agent/state/sessions/`, then raise the limits.
3. ~~Pi-side automatic promotion~~ **done** (`live/promotion.py`). ~~Drill~~ **done** (`research/agent/drill.py`). ~~Scheduler~~ **done** (`deploy/windows/schedule_research.ps1`, owner runs it). Next: the stage B checkpoint needs 3 clean drill rounds, which needs the 2 reviewer providers' keys.
4. When back with the Pi: `deploy/README.md`, 4 weeks unattended. Shadow books start recording on the first run.
5. Small: `requirements.txt` refresh (add `anthropic` for the research machine; drop torch); trend's 100% flips vs the 30% cap.

Still owner-only: live broker cash account + W-8BEN; tax agent; Telegram bot + healthchecks.io.

## History

### 2026-11-28 (session 3, cont.): the loop closes
- **Automatic promotion on the Pi** (`live/promotion.py`): weekly, after a completed run, every strategy that passed gates 1+2 (agent registry + `live/eligible.json`) and has a shadow record is judged by gate 3. The best pass becomes a ledger overlay `{strategy, live_since, previous}`, so `golive.py` gives it half size and the drift rollback. Benchmarks are never promoted. A new `approved.json` release wins. `live.kill --clear-promotion` undoes it. Paper account only; real money stays manual.
- **Bug caught by the tests:** after a drift rollback, the same weekly check re-promoted the strategy the same day, undoing the rollback. Now a rolled-back strategy is never auto-promoted again (a new version must earn its own record).
- **Stage B checkpoint drill** (`research/agent/drill.py`): 5 planted strategies through static checks, sandbox, screen, gate 1 (synthetic market) and every reviewer. 3 clean counting rounds in a row are needed; until then gate-1 passes wait in `research/agent/state/pending.jsonl`.
- **First real drill round** (no reviewers yet, so it doesn't count): all 5 plants were stopped, but `memorised_dates` (hard-coded crash years) got past the static checks, sandbox and screen, and only gate 1 caught it. Fixed: the static checks now reject year comparisons and date literals (MISTAKES #18).
- **Scheduler:** `deploy/windows/schedule_research.ps1` registers drill + session + pending queue, monthly or quarterly (owner runs it). Sessions now send an alert at the end.
- 132 tests pass. Not committed.

### 2026-11-28 (session 3, cont.): stage B built
- **Research agent** (`research/agent/`), borrowing RD-Agent's hypothesis -> experiment -> feedback -> knowledge loop:
  - Each idea is proposed (hypothesis + code), statically checked, run in the sandbox (look-ahead test + backtests), screened, given a written lesson, logged as a trial, and submitted if it passes.
  - Repairs of broken code (up to 2) aren't trials.
  - Hard USD caps per session ($5 default) and per month ($30), plus time and idea caps.
- **Sandbox:** Docker in WSL with no network, a read-only filesystem, no capabilities, a non-root user, 2 GB / 2 CPU / 128 processes and a timeout. The code mount holds only the code it needs (no keys, gate log or raw data). Research jobs see no holdout. Tests prove the walls from inside: network, writes, secrets, holdout and runaway code are all blocked; gate 1 mode is tested on synthetic data.
- **Static allowlist** (`checks.py`): only pandas/numpy/math/shared imports; no files, reflection, printing, monkeypatching, ticker strings or import-time code. Promoted code later runs on the Pi next to the broker keys, so this matters.
- **Gate 2** (`reviewers.py`): reviewers from other providers see comment-stripped code and numbers, never the hypothesis. Any reject blocks, and unclear answers count as rejects. 3 planted bad strategies every round; a fooled reviewer pauses promotions and alerts. Rubber-stamp detection.
- **Pipeline:** gate 1 runs in the sandbox on the holdout snapshot, once per exact source, logged to the gate log. Then gate 2. A pass goes to `research/strategies/agent/` + `live/shadow.json` (gate 3 paper period) + an alert. The agent never sees any of it.
- Trial log: `hypothesis` + `lesson` fields; trials 1-10 backfilled in `research/trials/annotations.json`.
- Not done: no real model run (the `anthropic` package install was refused without the owner's OK; no keys); Pi-side automatic promotion.
- 119 tests pass. Not committed.


### 2026-11-27 (session 3, cont.)
- **RD-Agent check** (report only, nothing installed): `research/RD_AGENT_CHECK.md`. It runs on Linux/WSL2, Python 3.10–3.11 (our Qlib venv is 3.12), Docker for most scenarios (Docker 29.3 is already in WSL), and LiteLLM with chat + an embedding model. US data isn't documented: the templates hard-code China CSI 300. Its factor mining also needs a wide stock universe we don't have. Recommendation: a custom stage B loop on our own engine and gates.

### 2026-11-27 (session 3, cont.)
- **Go-live mechanics built** (`live/golive.py`, wired into `live/engine/daily.py`). An approved entry with `live_since` trades at half size for 4 weeks, then full size only if no `reconcile_mismatch` / `order_failed` events. For 3 months after go-live, account vs paper is checked on settled days; a gap over 3 points rolls back to `previous` (a critical alert), or pauses trading if there's no previous one. Owner choices: 3 points, 3 months, pause when there's no fallback. New limits in `live/risk/limits.py`.
- Two of my bugs caught on the way (MISTAKES #16–17): the scale-up never traded (fixed: re-plan when sizing changes), and turnover-cap phase-in gave false drift (fixed: settled days only; honest worst gap 0.74% in 2020).
- `deploy/README.md` explains `live_since` / `previous`. 94 tests pass. Not committed.

### 2026-11-26 (session 3, cont.)
- Q: "Can anything be done with only the laptop?" Yes. Only the 4-week Pi run and real Alpaca keys need the Pi; the 4080 PC only matters for local LLMs or deep models.
- **Gate 3 built** (owner choices): shadow books (`live/shadow.json`, ledger table `shadow_targets`, recorded daily even when trading is stopped, never traded). Judge in `live/gate3.py`, thresholds in `live/gate3_thresholds.py`. Tests in `tests/test_gate3.py`.
- **Live data bug found and fixed:** the Yahoo feed had Memorial Day and Labor Day 2026 as all-empty rows, which sent the low-vol rules to cash live. `live/engine/data.py` `drop_non_trading_rows`. MISTAKES #15.
- On 2026-11-25: SPY is below its 200-day average (716.70 vs 730.77), so trend is in short bonds. That's real, not a bug.
- 85 tests pass. Not committed.

### 2026-11-26 (session 3)
- Re-read the proposal and listed the stage checkpoints (above).
- **Planted strategies** (`tests/planted.py`, `tests/planted_overfit.py`): a peeker using PriceView's private fields, a peeker with its own data copy, and the best-of-200 calendar rule. **Found a gate hole:** the look-ahead test can't see a strategy with its own data copy. It passed 10 of 11 checks with 91%/yr of fake returns; only the turnover cap stopped it. Owner approved the fix: **gate check `data_only_via_priceview`** (`research/gates/data_access.py`, a static scan). All three plants are now rejected for the named reason. MISTAKES #13–14.
- **ETF round 2** (`research/run_etf_round2.py` → `research/trials/etf_round2.md`): trials 6–10 are inverse-vol, trend-filtered 60/40, vol-target SPY, sector momentum with a buffer, and sector low-vol. Two qualified on the round rule; neither beat SPY in validation.
- 75 tests pass. Not committed (the owner commits).

### 2026-11-26 (session 2)
- Pi deploy kit in `deploy/`. Gate 1 built with owner-set thresholds. ETF round 1 (trials 2–5): none beat 60/40 in both periods; the rules mainly cut drawdowns. Universe now has 37 tradables.

### 2026-11-24 / 25 (session 1)
- Stage E Steps 1–7: data, splits with a holdout lock, engine, strategy interface, benchmarks, trial log. Trial 1 (XGBoost) only matched an equal-weight hold of its 19 stocks. Live side built offline with a fake broker.
