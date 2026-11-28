"""
What the research agent knows (RD-Agent's "knowledge base", kept simple).

  system_brief()   stable: goal, rules, interface, universe, worked examples, mistakes
                   checklist. Cached by the model API, since it rarely changes.
  research_state() changes every idea: benchmark numbers and every past trial with its
                   hypothesis, results and lesson (from the trial log).

Never included: holdout data, gate 1 reports, the gate log, promotion outcomes
(proposal: the agent can never "see holdout results").
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from research.data.loader import data_version, load_panel
from research.data.splits import PERIODS
from research.engine import settings as S
from research.gates import thresholds as T
from research.trials.log import read_trials
from shared.limits import MAX_WEIGHT_STOCK
from shared.universe import ETF_ROLES, SECTOR_ETFS, STOCKS, SURVIVORSHIP_NOTE

STATE_DIR = Path(__file__).resolve().parent / "state"
REPO = Path(__file__).resolve().parents[2]
BENCH_NAMES = ("buy_hold_index", "sixty_forty", "equal_weight_universe", "trend_sma200", "momentum_12_1",
               "low_vol_252")


def benchmarks() -> dict:
    """Research/validation metrics of the benchmarks (trusted code, run on the host). Cached per data version."""
    cache = STATE_DIR / "benchmarks.json"
    ver = data_version()
    if cache.exists():
        c = json.loads(cache.read_text())
        if c.get("data_version") == ver:
            return c["bench"]
    from research.engine.backtest import run_backtest
    from research.strategies import BENCHMARKS

    panel = load_panel()
    bench = {p: {n: run_backtest(BENCHMARKS[n](), panel, s, e).metrics for n in BENCH_NAMES}
             for p, (s, e) in PERIODS.items()}
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"data_version": ver, "bench": bench}, default=float))
    return bench


def _example(module_name: str) -> str:
    import importlib

    return inspect.getsource(importlib.import_module(module_name))


def _mistakes_checklist() -> str:
    rows = []
    for line in (REPO / "research" / "MISTAKES.md").read_text(encoding="utf-8").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0].isdigit():
            rows.append(f"- {cells[3]}")
    return "\n".join(rows)


def system_brief() -> str:
    (rs, re_), (vs, ve) = PERIODS["research"], PERIODS["validation"]
    roles = "\n".join(f"  etf({r!r}) -> {t}" for r, t in ETF_ROLES.items())
    return f"""You are the quant researcher of a small, long-only US trading system. You research and write
trading strategies as Python code. You never place trades: code that passes fixed checks, independent
reviewers and months of paper trading is run by a separate machine inside a fixed risk layer.

GOAL
Find a rule that, after all costs, beats buy-and-hold of the broad US index ETF AND earns more than 5% a year,
with a worst fall no deeper than buy-and-hold's. Simple, robust, economically motivated rules beat clever
curve-fits. Every backtest you run is counted, and the more you try, the higher the statistical bar for the
final test (deflated Sharpe ratio), so propose ideas you actually believe in, not small parameter tweaks.

DATA YOU SEE
Daily prices (open/high/low/close/volume, split- and dividend-adjusted) from 2006.
Research period {rs.date()} to {re_.date()}, validation period {vs.date()} to {ve.date()}.
A later holdout period exists; you never see it. Results on it decide promotion.
Caveat: {SURVIVORSHIP_NOTE}

FIXED RULES (enforced by the engine and checks; you can't change them)
- Long only. Weights per ticker, each >= 0, summing to <= 1 (the rest is cash at 0%).
- Single stocks and sector ETFs: at most {MAX_WEIGHT_STOCK:.0%} each. Broad asset-class ETFs: up to 100%.
- Signal at the close of day T, fills at the next open. Costs on every trade: {S.FEE_BPS} bp fee +
  {S.SLIPPAGE_BPS} bp slippage per side.
- Rebalance frequency is one of "daily", "weekly", "monthly", "once"; between rebalances holdings drift.
- Turnover above {T.MAX_TURNOVER_ONE_WAY_PER_YEAR:.0%} a year (one-way) is rejected. Live, at most 30% of the portfolio can change per day,
  so a full switch takes about 4 days: whipsaw rules suffer.
- Rules over the universe only: never write a ticker as a string. Use the names below.

THE UNIVERSE (from shared.universe)
STOCKS = {list(STOCKS)}
SECTOR_ETFS = {list(SECTOR_ETFS)}
Broad ETFs by role:
{roles}
Helpers: etf(role) -> ticker; etfs(role1, role2, ...) -> list of tickers.

CODE CONTRACT
One Python module with exactly one class that subclasses shared.strategy.Strategy:
    name = "snake_case_name"      (unique, 3-41 chars)
    rebalance = "monthly"         (or "weekly", "daily", "once" = buy at the start and hold)
    def params(self) -> dict      (optional: settings to record)
    def target_weights(self, data) -> pd.Series   (index = tickers, values = weights; empty = all cash)
`data` is a PriceView cut at today's close: data.close, data.open (DataFrames: dates x tickers),
data.field("high"/"low"/"volume"), data.dates, data.asof (today), data.symbols().
Missing prices are NaN (e.g. before a listing): handle them.
Allowed imports only: pandas, numpy, math, statistics, typing, dataclasses, __future__,
shared.strategy (Strategy, PriceView), shared.universe (STOCKS, SECTOR_ETFS, etf, etfs).
Not allowed: files, network, os/sys, print, getattr/eval/exec, dunder or private attributes, assigning
attributes on anything but self, code running at import time, ticker strings. Instances may be created
fresh at any time, so keep no state between calls that changes the answer; recompute from `data`.
The answer for day T must depend only on data up to T (a look-ahead test scrambles future prices).

WORKED EXAMPLES (existing strategies)
```python
{_example("research.strategies.trend")}
```
```python
{_example("research.strategies.vol_target")}
```

REVIEWERS WILL CHECK (mistakes made before in this project)
{_mistakes_checklist()}

HOW TO ANSWER
Reply in exactly this format, nothing else:
<hypothesis>Why this should work: the economic reason or behavioural effect, and what result would prove it
wrong. 2-5 sentences.</hypothesis>
<code>
```python
...the complete module...
```
</code>"""


def _fmt(m: dict) -> str:
    return (f"CAGR {m['cagr']:+.1%}, worst fall {m['max_drawdown']:.1%}, Sharpe {m['sharpe_rf0']:.2f}, "
            f"turnover {m['turnover_one_way_per_year']:.0%}/yr")


def research_state(max_trials: int = 60) -> str:
    bench = benchmarks()
    lines = ["BENCHMARKS (same costs and fills)"]
    for n in BENCH_NAMES:
        lines.append(f"- {n}: research {_fmt(bench['research'][n])}; validation {_fmt(bench['validation'][n])}")
    trials = read_trials()
    lines += ["", f"ALL PAST TRIALS ({len(trials)} so far; every one counts against the final test)"]
    for t in trials[-max_trials:]:
        r = t.get("results", {})
        res = "; ".join(f"{p} {_fmt(r[p])}" for p in PERIODS if p in r)
        lines.append(f"#{t['trial_id']} {t['strategy']} ({t.get('author', 'human')}): {res}")
        if t.get("hypothesis") or t.get("idea"):
            lines.append(f"   hypothesis: {t.get('hypothesis') or t.get('idea')}")
        if t.get("lesson"):
            lines.append(f"   lesson: {t['lesson']}")
    return "\n".join(lines)
