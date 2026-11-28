# Tech stack and design notes

A plain-English guide to how this project is built and why. It's written so you can explain any part of it in an interview.

---

## The project in 30 seconds

A research platform for systematic trading strategies, built so that **AI can help with the research but never makes trading decisions**.

- A **PC** runs the research: it downloads prices, tests strategies on history, and records every attempt.
- A **Raspberry Pi 5** will run only the strategies that pass fixed checks, as plain code, through a paper-trading (fake money) broker account.
- The work is staged: **E** (textbook strategies), then **D** (my own research with AI coding help), then **B** (an autonomous AI research agent). Each stage is useful even if the next one never beats it.

Status: Stage E's research side is complete. The live (Pi) side is built and tested on a laptop against a simulated broker. Next it gets deployed to the Pi with paper-trading keys.

---

## Architecture

```
            PC (research)                               Raspberry Pi 5 (live, later)
  ┌──────────────────────────────────┐            ┌──────────────────────────────┐
  │ yfinance → data checks → loader  │            │ daily engine (after US close)│
  │   (holdout locked)               │  approved  │ risk layer: limits, hard stop│
  │ strategies → backtest engine     │ ─────────▶ │ Alpaca paper broker          │
  │ trial log, versioned models      │  strategy  │ SQLite ledger                │
  │ NO broker keys                   │    code    │ NO LLMs                      │
  └──────────────────────────────────┘            └──────────────────────────────┘
                 shared/: one strategy interface + universe + limits, used by both
```

**Why split across two machines?**
- **No broker keys on the PC.** Nothing on the research side (including AI tools) can ever touch money.
- **No AI on the Pi.** Trading decisions come only from tested, deterministic code.
- **The same strategy code runs on both.** What was tested is exactly what trades.

---

## The stack

| Tool | What it does here | Why this choice | Alternative considered |
|---|---|---|---|
| **Python 3.13** | Everything | The standard for quant research; same language on the PC and the Pi | — |
| **pandas / numpy** | Price tables, indicators, backtest maths | Fast, familiar, runs on a Raspberry Pi | Polars (faster, but less common) |
| **yfinance** | Free daily prices (Yahoo Finance), split- and dividend-adjusted | Free, with 20 years of history | Paid feeds (Polygon, Norgate) that include delisted stocks |
| **Own backtest engine** (`research/engine/`) | Replays history: signal at the close, fill at the next open, fees and slippage on every trade, cash only | Small and fully understood. It **must run on the Pi** so live trading matches the backtest | Qlib, Backtrader, vectorbt |
| **Qlib** (Microsoft), in **WSL2** | Installed and verified. An export feeds it the same data | Useful for exploring factors, and for Stage B (RD-Agent builds on it) | Can't run on the Pi, so it isn't the core engine |
| **RD-Agent** (Microsoft) | Checked, not installed (`research/RD_AGENT_CHECK.md`) | Automated factor and model research on Qlib | Its quant scenarios target China's CSI 300; US data isn't documented, and it mines factors across hundreds of stocks. Our evidence favours simple ETF rules, so a custom loop on our own engine and gates fits better |
| **XGBoost** | The machine-learning model in the Stage D candidate | Strong on tabular data, quick on a laptop CPU | Neural nets (overkill for ~80k rows) |
| **unittest** | 132 automated tests: look-ahead, holdout lock, engine, limits, registry | Built into Python, so no extra dependency | pytest |
| **git** | Version control. The trial log records the code version of every test | Reproducibility | — |
| **uv** | Fast Python environment manager (for the Qlib install) | Isolated, reproducible environments | conda, pip + venv |
| **Alpaca (alpaca-py)** *(next)* | Paper-trading broker API | Free paper accounts, no commission, fractional shares | Interactive Brokers |
| **SQLite** *(next)* | Ledger of orders, fills and positions on the Pi | A single file, no server, reliable | Postgres (too heavy for a Pi) |
| **Raspberry Pi 5 (8 GB)** *(next)* | The always-on live machine | Cheap, low power, physically separate from the research PC | Cloud VM |

**Hardware note:** all of Stage E runs on an ordinary laptop (i7, 16 GB). The heaviest job, a walk-forward XGBoost backtest, takes 46 seconds. A GPU would only matter for running local LLMs or deep-learning models in Stage B.

---

## Engineering decisions worth talking about

**1. Look-ahead bias is blocked three ways.**
- **By design:** strategies never see the full dataset. They get a `PriceView` that physically cuts off at today's close.
- **By test:** for every strategy, the test scrambles all prices after date T and checks that the weights for T don't change.
- **The test is itself tested:** a deliberately cheating strategy is included to prove the test catches it.
- **By code scan (gate 1):** planted cheaters exposed a blind spot. A strategy holding its *own copy* of the data ignores the scrambled panel, and it passed 10 of 11 gate checks with 91% a year of fake returns; only the turnover cap stopped it. Gate 1 now also scans the strategy's code and rejects any other route to data (file reads, network, globals or class attributes holding data, PriceView's private fields). A static scan can be evaded, so Stage B's sandbox stays the real fix.

**2. A locked holdout period.** The last ~3 years (2024 onwards) are a final exam.
- The data loader refuses to return those rows unless the code calling it lives in `research/gates/` (the future promotion checks).
- A test scans the codebase to make sure nothing reads the raw files directly.
- This is enforced in code, not just written in a document.

**3. Realistic execution.**
- Signals use the close of day T and fill at the **next day's open**. You can't trade at a price you've only just seen.
- Every trade pays 1 bp in fees plus 5 bp in slippage.
- Long-only, no leverage, at most 25% in any single stock.

**4. A data bug fixed: re-adjusted prices.**
- **The problem:** adjusted prices rewrite the *whole* past every time a stock pays a dividend or splits. The old code appended new bars to old ones, which quietly mixed two adjustment bases.
- **The fix:** each update re-downloads a short overlap. If it no longer matches what's stored, the whole history for that stock is downloaded again.

**5. A label bug fixed: the old model predicted something untradable.**
- **The old target:** "today's close vs yesterday's close". That includes the overnight gap, which happens before you can buy at the open.
- **The new target:** "will this stock beat the median stock over the next 5 days, measured from the next open?" It's tradable, and it doesn't reward simply betting that the market goes up.

**6. Every experiment is counted (the overfitting defence).**
- Try enough strategy variants and one will look great by luck. Every candidate test is appended to `trials.jsonl`: the idea, code version, settings and results.
- The total count will feed a penalty in the promotion gate (a deflated Sharpe ratio).
- Benchmarks aren't counted as trials.

**7. Models are versioned, never overwritten.**
- **The old system:** it retrained every week and silently replaced the live model.
- **Now:** each training run saves a new version marked "candidate". Loading a model for trading requires a manual `approve()`, and the file's hash is checked when it's loaded.

**8. Performance fixed by measuring first.**
- **The problem:** the XGBoost backtest took more than 10 minutes.
- **The diagnosis:** `cProfile` showed 95% of the time was one pandas reshape (`DataFrame.stack`) called at every weekly signal.
- **The fix:** replaced it with a numpy reshape, verified the output is **identical** to the old one, then re-ran the tests.
- **The result:** about 100× faster for that step; the full run takes 46 seconds.

**9. A live engine that's safe to rerun (`live/`).**
- **Duplicate runs:** every order gets a deterministic ID (`date-strategy-ticker-side`), and the plan is saved to SQLite *before* anything is sent.
- **Crash recovery:** after a crash or a broker timeout, a rerun asks the broker which IDs it already has and sends only the missing ones.
- **The proposal's failure cases are all automated tests:** broker timeout, duplicate run, missing data, crash mid-order, and invalid strategy output. Each ends in "no trade" or "the correct trade".
- **Risk layer outside the strategies:** a turnover cap (30% per rebalance), a 3% daily-loss halt, a 15% drawdown pause, a hard stop that sells everything and disables trading, and a kill switch.
- **Parity check:** replaying 2021 through the live engine and a simulated broker gives the same target weights and rebalance days as the backtest, with equity within 0.6% for every benchmark.
- **A real example of the risk layer:** in that replay, momentum fell 17.6% from its peak in March 2021, and the risk layer would have paused it.
- **A homemade NYSE calendar** (holiday rules plus Easter for Good Friday) that matches all 4,529 real trading days from 2006 to 2023, with no extra dependency.

**10. Deployment and operations (`deploy/`).**
- **Scheduling:** systemd timers run in New York time (`Mon..Fri 16:45 America/New_York`), so US daylight-saving changes need no attention. The engine also refuses to send orders if it starts while the market is open, for example a catch-up run after a power cut.
- **One-way updates:** the Pi pulls `live-v*` git tags with a read-only deploy key, tests each new version in a separate copy, and switches only if every test passes.
- **Watchdog off the Pi:** each run pings healthchecks.io. If the pings stop, the alert comes from outside the Pi, so a dead Pi can't stay silent.
- **Daily reconciliation:** fills are pulled from the broker and stored, and positions rebuilt from the ledger are compared with the broker's every day. A six-month replay stays matched every day.
- **Alerts:** Telegram messages for anything unusual, plus a weekly report. If an alert fails to send, it's logged and never stops a trading run.

**11. Promotion gate 1 (`research/gates/`): the final exam.**
- **The only code that may open the holdout.** Each exact strategy version (a hash of its code and settings) gets **one attempt**, and every attempt is logged, so you can't keep tweaking until it passes.
- **Eleven fixed checks:**
  - beats buy-and-hold and the 5% bank rate after costs
  - stock pickers must also beat equal-weight of the same stocks
  - deflated Sharpe ratio ≥ 95%
  - look-ahead test, plus a code scan for any data access outside the PriceView
  - no ticker names in the code
  - turnover ≤ 300%/yr
  - drawdown no deeper than buy-and-hold's
  - no single stock above 30%
  - still wins with doubled costs and with shifted start dates
- **Deflated Sharpe ratio, in one sentence:** if you try 100 ideas, the best will look good by luck. The DSR asks how likely it is that this strategy beats the *luckiest of N worthless strategies*, allowing for fat tails. More trials means a higher bar. It's written with only Python's standard library.
- **Tested on synthetic markets,** so the real holdout stays sealed until a genuine candidate exists.
- **Planted bad strategies are rejected for the right reason** (the Stage D exit checkpoint): two future-peekers fail the look-ahead and code-scan checks, and a rule picked as the best of 200 calendar tries fails on the holdout and on deflated Sharpe.

**12. Gate 3, the paper period, and shadow books.**
- One Alpaca paper account trades the main strategy. Every benchmark and candidate also runs daily on the Pi as a **shadow book**: its target weights are computed from the same data and recorded, but never traded. A failing shadow can't affect trading, and shadows keep recording even when trading is paused, so their record has no gaps.
- **Gate 3** replays each recorded book with the research engine (same next-open fills and costs) and checks four things. Do the recorded weights match what the code gives today (≥99% of rebalance days)? Is the forward return within 2 points of a fresh backtest? Does it beat SPY and 5%/yr? Is the record 6 months long (3 for a replacement)? A mismatch means a bug or bad data, not bad luck.
- **Go-live safety (`live/golive.py`):** a newly live strategy trades at half size for 4 weeks, and scales up only if every fill reconciled. For 3 months, a daily check compares the account with its paper record on settled days. A gap over 3 points switches back to the previous strategy automatically, or pauses trading if it's the first. A stress run found that counting every day caused false alarms (the 30% turnover cap phases trades in on purpose), so only days without fills count. Honest gaps then stayed under 0.75% even in the March 2020 crash.
- **It found a bug before it was even deployed.** The live feed had US holidays as empty rows, which silently sent the low-volatility rules to cash. The backtest data was clean, so only a live-vs-backtest comparison could see it.

**13. Stage B: an LLM agent as the quant researcher (`research/agent/`).**
- **The LLM writes the rules; it never places trades.** Its strategies go through the same trial log and gates as mine, then months of paper trading, before the Pi runs them as plain code.
- **Loop borrowed from Microsoft's RD-Agent:** hypothesis -> code -> backtest -> feedback -> knowledge. The agent reads every past trial's hypothesis, results and *lesson*, so it doesn't repeat ideas.
- **Defence in depth against a clever or compromised agent:**
  - A static allowlist: only pandas, numpy and the strategy interface; no files, network, reflection or monkeypatching.
  - A locked Docker sandbox: no network, read-only, no keys, resource caps. Tests attack it from inside to prove each wall.
  - A holdout it never sees.
  - Gate 1 run once per exact code version.
  - Reviewer models from *other* providers that never see the author's pitch, checked every round with planted bad strategies.
  - Hard dollar caps per session and per month.
- **The loop closes without a human, but never without evidence:** a strategy that passes gates 1 and 2 paper-trades on the Pi; when its paper record passes gate 3, the Pi promotes it itself at half size, with automatic rollback if live results drift. A rolled-back strategy can't be re-promoted (a bug the tests caught). Promotion waits for a checkpoint drill: planted bad strategies must be stopped by every layer for 3 rounds in a row.
- **Why custom instead of RD-Agent itself:** RD-Agent mines factors across hundreds of Chinese stocks and judges with its own backtest. This project needs rules over 37 ETFs and stocks, judged by a fixed engine the agent can't touch.

---

## Results, and what they taught

Annual return after costs. Research = 2007–2019, validation = 2020–2023. The holdout hasn't been touched.

| Strategy | Research | Validation | Worst drop (research) |
|---|---:|---:|---:|
| Buy-and-hold SPY | 8.7% | 12.1% | −55% |
| Equal-weight, all 19 stocks | 21.7% | 21.3% | −45% |
| Momentum (12-month winners) | 25.2% | 32.3% | −50% |
| Trend (SPY above its 200-day average, else bonds) | 8.8% | 6.2% | **−22%** |
| Low volatility | 8.2% | 13.1% | −39% |
| **XGBoost candidate (trial #1)** | 26.0%\* | 20.1% | −29% |

\*Measured from 2010, when the first walk-forward model exists. Over that same window, equal-weight made 24.8%.

**The key lesson: survivorship bias.**
- The 19 stocks are today's giants, chosen in 2026. Simply owning all of them beats SPY by 9–13 points a year. That's hindsight, not skill.
- So the honest yardstick for stock picking is **equal-weight of the same stocks**, not SPY.
- Against that yardstick, the XGBoost model shows **no edge**: +1.2 points in research, −1.2 in validation, with lower risk-adjusted returns. It also trades the whole portfolio almost every week, which costs about 3% a year.
- Momentum beats equal-weight on paper, but it concentrates in the biggest winners from a hindsight-picked list, so it's the result most inflated by the bias.

**ETF round 1 (published rules on bias-free ETFs):** Faber's asset-class trend, Antonacci's dual momentum, sector momentum and a combination of the three. They cut the worst fall from −55% (SPY) to −14% to −23%, but none beat a plain 60/40 portfolio on returns in both periods, so none earned a holdout attempt. The decision rule was written down *before* the results, and the rules weren't re-tuned afterwards.

**ETF round 2 (10 trials in total):** inverse-volatility weighting, trend-filtered 60/40, volatility-managed SPY (Moreira & Muir), sector momentum with a holding buffer, and low-volatility sectors. Volatility-managed SPY and low-vol sectors beat 60/40 in both periods with lower drawdowns than SPY, but neither beat SPY itself in validation (about 8.8% vs 12.1%). The lesson: lowering risk is easy; beating the index after costs is not. The buffer cut sector momentum's turnover in research but not in validation (328%/yr).

**The system worked as intended.** It turned an impressive-looking model into an honest "no edge", before any money was involved.

---

## Known limitations

- **Survivorship-biased universe:** free data has no delisted companies. A point-in-time universe would need a paid source.
- **yfinance is unofficial:** it can rate-limit or change format without warning. The live side needs a sturdier feed (for example Alpaca's market data).
- **Cost model is simple:** fixed basis points. No market-impact model, and no AUD/USD conversion costs.
- **The live side has only run against a simulated broker.** Real Alpaca paper keys, scheduling, the watchdog and alerts come with the Pi.

---

## Likely interview questions

**How do you prevent look-ahead bias?**
Strategies only get a data view that ends at today's close. On top of that, an automated test changes all future prices and checks that today's decision doesn't move, and it's proven to catch a cheating strategy. Planting cheaters also showed the test's limit: a strategy with its own copy of the data slips past it, so the gate also scans the code for any data access outside the view.

**Why not judge the model by accuracy?**
Accuracy doesn't pay. A model can be 55% accurate and still lose money after costs, or after trading at the open. Everything here is judged by returns after costs, against benchmarks.

**How do you avoid overfitting?**
- A locked holdout period that's enforced in code.
- Every trial is counted.
- Hyperparameters are fixed in advance, with no early stopping on the evaluation data.
- Models retrain walk-forward, using only past data.
- Later: a deflated Sharpe ratio in the promotion gate, plus a forward paper-trading period.

**Why build your own backtester instead of using a library?**
The exact same strategy code has to run on a Raspberry Pi in live trading. A small engine I fully understand guarantees that. Qlib is still installed for research exploration.

**What was the hardest bug?**
There were two quiet ones:
- The label included the untradable overnight gap.
- Incremental downloads mixed price-adjustment bases.

Neither crashes anything; both just make results wrong.

**What would you do differently, or next?**
- Get point-in-time universe data, so results stop being inflated.
- Build the Pi side with failure tests: broker timeout, duplicate run, crash mid-order.
- Only then move on to AI-assisted research.

**Why is AI kept away from trading decisions?**
An LLM can hallucinate or be prompted into doing something odd. Here, AI writes and tests strategy code on a machine with no broker access. Only code that passes fixed gates ever trades, and it runs as plain code under hard risk limits.

---

## Roadmap

1. **Stage E, live side:** the code is done (engine, risk layer, SQLite ledger, broker adapter). The deploy kit is also done: timers, alerts, watchdog, reconciliation and the update channel. Still to do: follow `deploy/README.md` on the Pi, then 4 weeks of unattended paper trading.
2. **Stage D:** promotion gate 1 is built; next comes my own research with AI coding help, judged by that gate. A mistakes log (`research/MISTAKES.md`) is kept as the future reviewer-agent checklist.
3. **Stage B:** an autonomous research agent, with independent reviewer agents and the same fixed gates.
