"""
Promotion gate 1: fixed checks. The ONLY code allowed to read the holdout.

A strategy passes only if every check passes (proposal, "Gate 1 checks"):
  1. rules only        no tradable ticker names written in the strategy's code
  2. look-ahead        prices only via the PriceView (static scan: no files, globals, private
                       fields), and changing future prices doesn't change today's weights
  3. beats buy-and-hold on the holdout, after costs
  4. beats the bank rate (5%/yr)
  5. stock pickers also beat equal-weight of all universe stocks
  6. deflated Sharpe   significant after the penalty for every trial so far
  7. turnover          within limit
  8. drawdown          no deeper than buy-and-hold's
  9. concentration     no single stock above the drift limit
 10. robustness        still beats buy-and-hold with doubled costs and shifted starts

Each strategy version (hash of its source code + settings) gets ONE attempt.
Every attempt, pass or fail, is appended to research/gates/gate_log.jsonl.

Usage (from the repo root):
    python -m research.gates.gate1 <strategy_name>             # explains, does nothing
    python -m research.gates.gate1 <strategy_name> --confirm   # spends the one attempt
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from research.data import splits
from research.data.loader import load_panel
from research.engine.backtest import run_backtest
from research.engine.lookahead import check_no_lookahead
from research.gates.data_access import data_access_violations
from research.gates import thresholds as T
from research.gates.dsr import deflated_sharpe
from research.strategies.buy_hold import BuyHold
from research.strategies.equal_weight import EqualWeight
from research.trials.log import read_trials
from shared.universe import STOCKS, SURVIVORSHIP_NOTE, TRADABLE

GATE_LOG = Path(__file__).resolve().parent / "gate_log.jsonl"
LOOKAHEAD_DATES = ("2012-06-29", "2016-03-31", "2021-09-30")


class AlreadyAttempted(RuntimeError):
    pass


@dataclass
class Check:
    name: str
    passed: bool
    value: object = None
    threshold: object = None
    detail: str = ""


@dataclass
class GateReport:
    strategy: str
    version: str
    passed: bool
    checks: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    window: tuple = ()


# ---------------------------------------------------------------------------
def strategy_version(strategy_cls) -> str:
    src = inspect.getsource(inspect.getmodule(strategy_cls))
    params = json.dumps(strategy_cls().params(), sort_keys=True, default=str)
    return hashlib.sha256((src + params).encode()).hexdigest()[:16]


def ticker_literals(strategy_cls) -> list[str]:
    """Tradable tickers written as string literals in the strategy's module."""
    src = inspect.getsource(inspect.getmodule(strategy_cls))
    found = set(re.findall(r"""["']([A-Z]{1,5})["']""", src))
    return sorted(found & set(TRADABLE))


def previous_attempts(version: str, log: Path = GATE_LOG) -> list[dict]:
    if not log.exists():
        return []
    rows = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    return [r for r in rows if r["version"] == version]


def _trial_sharpes_daily() -> list[float]:
    out = []
    for t in read_trials():
        for period in ("research", "validation"):
            s = t.get("results", {}).get(period, {}).get("sharpe_rf0")
            if s is not None and not math.isnan(s):
                out.append(s / math.sqrt(252))
    return out


def _cagr(start, end, panel, strategy, mult=1.0) -> tuple[float, object]:
    r = run_backtest(strategy, panel, start, end, cost_multiplier=mult)
    return r.metrics["cagr"], r


# ---------------------------------------------------------------------------
def run_gate1(strategy_cls, *, panel=None, holdout_start=None, end=None,
              lookahead_dates=LOOKAHEAD_DATES, n_trials=None, trial_sharpes=None,
              log: Path | None = GATE_LOG) -> GateReport:
    version = strategy_version(strategy_cls)
    name = strategy_cls.name
    if log is not None and T.ONE_ATTEMPT_PER_VERSION and previous_attempts(version, log):
        raise AlreadyAttempted(f"{name} version {version} already took gate 1; change the strategy "
                               f"(a new version, logged as a new trial) to try again")

    if panel is None:
        panel = load_panel(include_holdout=True)      # allowed: this module is research.gates.*
    hs = pd.Timestamp(holdout_start or splits.HOLDOUT_START)
    idx = panel["close"].index
    end = pd.Timestamp(end) if end is not None else idx[-1]
    window = idx[(idx >= hs) & (idx <= end)]
    checks: list[Check] = []

    # 1. rules only
    lit = ticker_literals(strategy_cls)
    checks.append(Check("rules_only_no_ticker_names", not lit, lit, "none",
                        "strategies must be rules over the universe, never named tickers"))

    # 2. look-ahead: prices only via the PriceView (static), and scrambled future = same output
    access = data_access_violations(strategy_cls)
    checks.append(Check("data_only_via_priceview", not access, len(access), 0, "; ".join(access)[:500]))
    fails = check_no_lookahead(strategy_cls, panel, [d for d in lookahead_dates if pd.Timestamp(d) < hs])
    checks.append(Check("look_ahead_test", not fails, len(fails), 0, "; ".join(fails)[:500]))

    # 3-5. holdout returns vs benchmarks and bank rate
    cagr, res = _cagr(hs, end, panel, strategy_cls())
    bh_cagr, bh = _cagr(hs, end, panel, BuyHold())
    m = res.metrics
    checks.append(Check("beats_buy_and_hold", cagr > bh_cagr, round(cagr, 4), round(bh_cagr, 4)))
    checks.append(Check("beats_bank_rate", cagr > T.BANK_RATE, round(cagr, 4), T.BANK_RATE))
    stock_cols = [c for c in res.weights.columns if c in STOCKS]
    picks_stocks = bool(stock_cols) and bool((res.weights[stock_cols] > 0).any().any())
    if T.STOCK_PICKERS_BEAT_EQUAL_WEIGHT and picks_stocks and name != EqualWeight.name:
        ew_cagr, _ = _cagr(hs, end, panel, EqualWeight())
        checks.append(Check("stock_picker_beats_equal_weight", cagr > ew_cagr, round(cagr, 4), round(ew_cagr, 4)))

    # 6. deflated Sharpe
    trials = n_trials if n_trials is not None else max(len(read_trials()), 1)
    sharpes = trial_sharpes if trial_sharpes is not None else _trial_sharpes_daily()
    d = deflated_sharpe(res.equity.pct_change().dropna(), trials, sharpes)
    checks.append(Check("deflated_sharpe", d["dsr"] >= T.MIN_DEFLATED_SHARPE, round(d["dsr"], 4),
                        T.MIN_DEFLATED_SHARPE,
                        f"Sharpe {d['sharpe_annual']:.2f}/yr vs luck benchmark "
                        f"{d['luck_benchmark_sharpe_annual']:.2f}/yr after {trials} trial(s)"))

    # 7-9. risk limits
    to = m["turnover_one_way_per_year"]
    checks.append(Check("turnover", to <= T.MAX_TURNOVER_ONE_WAY_PER_YEAR, round(to, 3),
                        T.MAX_TURNOVER_ONE_WAY_PER_YEAR))
    dd, bh_dd = m["max_drawdown"], bh.metrics["max_drawdown"]
    checks.append(Check("max_drawdown_vs_buy_hold", dd >= bh_dd - T.MAX_DRAWDOWN_VS_BUY_HOLD,
                        round(dd, 4), round(bh_dd, 4)))
    max_w = float(res.weights[stock_cols].max().max()) if stock_cols else 0.0
    checks.append(Check("concentration", max_w <= T.MAX_SINGLE_STOCK_WEIGHT_AFTER_DRIFT, round(max_w, 4),
                        T.MAX_SINGLE_STOCK_WEIGHT_AFTER_DRIFT))

    # 10. robustness
    c2, _ = _cagr(hs, end, panel, strategy_cls(), T.COST_MULTIPLIER_STRESS)
    b2, _ = _cagr(hs, end, panel, BuyHold(), T.COST_MULTIPLIER_STRESS)
    checks.append(Check("robust_doubled_costs", c2 > b2, round(c2, 4), round(b2, 4)))
    shifted = {}
    for k in T.START_SHIFTS_TRADING_DAYS:
        if k < len(window) - 63:
            s = window[k]
            sc, _ = _cagr(s, end, panel, strategy_cls())
            sb, _ = _cagr(s, end, panel, BuyHold())
            shifted[str(s.date())] = (round(sc, 4), round(sb, 4))
    ok = bool(shifted) and all(a > b for a, b in shifted.values())
    checks.append(Check("robust_shifted_start", ok, shifted, "beats buy-and-hold from every start"))

    report = GateReport(
        strategy=name, version=version, passed=all(c.passed for c in checks), checks=checks,
        metrics={**m, "buy_hold_cagr": bh_cagr, "deflated_sharpe": d, "caveat": SURVIVORSHIP_NOTE},
        window=(str(window[0].date()), str(window[-1].date())),
    )
    if log is not None:
        with log.open("a") as f:
            f.write(json.dumps({"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                **asdict(report)}, default=str) + "\n")
    return report


def format_report(r: GateReport) -> str:
    lines = [f"GATE 1: {r.strategy} (version {r.version})  holdout {r.window[0]} to {r.window[1]}",
             f"RESULT: {'PASS' if r.passed else 'FAIL'}", ""]
    for c in r.checks:
        lines.append(f"  [{'pass' if c.passed else 'FAIL'}] {c.name}: {c.value} (limit/benchmark: {c.threshold})"
                     + (f"  {c.detail}" if c.detail else ""))
    lines += ["", f"Caveat: {SURVIVORSHIP_NOTE}"]
    return "\n".join(lines)


def candidates() -> dict:
    from research.strategies import BENCHMARKS, ETF_ROUND1
    from research.strategies.xgb_candidate import XGBCandidate

    return {**BENCHMARKS, **ETF_ROUND1, XGBCandidate.name: XGBCandidate}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Promotion gate 1 (uses the locked holdout)")
    ap.add_argument("strategy", choices=sorted(candidates()))
    ap.add_argument("--confirm", action="store_true", help="really run it (spends this version's one attempt)")
    a = ap.parse_args(argv)
    cls = candidates()[a.strategy]
    v = strategy_version(cls)
    if previous_attempts(v):
        raise SystemExit(f"{a.strategy} version {v} has already taken gate 1 (one attempt per version).")
    if not a.confirm:
        print(f"{a.strategy} version {v} has not taken gate 1. Running it opens the locked holdout "
              f"({splits.HOLDOUT_START.date()} onwards) for this version, once. Add --confirm to proceed.")
        return
    print(format_report(run_gate1(cls)))


if __name__ == "__main__":
    main()
