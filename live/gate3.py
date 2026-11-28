"""
Promotion gate 3: the paper period (proposal, "Gate 3 paper period").

For one strategy (a shadow book or the traded one), using what the Pi recorded:
  1. target match     recorded weights == weights the strategy code gives today for
                      the same days (catches bugs, data revisions, live/backtest drift)
  2. return gap       forward return from the recorded weights vs a fresh backtest of
                      the same days, within MAX_CUMULATIVE_RETURN_GAP
  3. beats buy-and-hold over the same days, after costs (annualised)
  4. beats the bank rate
  5. beats the live strategy (only when replacing one)
  6. long enough      3 months for a first go-live, 6 weeks for a replacement

Verdict: "fail" if 1 or 2 fails (investigate: a bug or overfitting); otherwise
"not_yet" until the period is long enough; then "pass" only if 3-5 all pass.

Forward returns use the research engine (next-open fills, the same fees and
slippage), so a shadow book is judged exactly like a backtest, just on days that
were unknown when its weights were recorded.

Usage (from the repo root):
    python -m live.gate3 <strategy> [--replacing <live_strategy>] [--fake]
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

import pandas as pd

from live import config
from live import gate3_thresholds as T
from live.ledger.db import Ledger
from research.engine.backtest import run_backtest
from shared.strategy import PriceView, Strategy, is_rebalance_day, validate_weights


@dataclass
class Check:
    name: str
    passed: bool
    value: object = None
    threshold: object = None
    detail: str = ""


@dataclass
class Gate3Report:
    strategy: str
    verdict: str                          # pass | not_yet | fail
    start: str = ""
    end: str = ""
    months: float = 0.0
    checks: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


class RecordedBook(Strategy):
    """Replays recorded targets: on each rebalance day, the latest record on or before it."""

    def __init__(self, base_cls, records: dict[str, dict[str, float]]):
        self.name, self.rebalance = f"{base_cls.name}__forward", base_cls.rebalance
        self._days = pd.DatetimeIndex(pd.to_datetime(list(records)))
        self._weights = list(records.values())

    def target_weights(self, data: PriceView) -> pd.Series:
        i = self._days.searchsorted(data.asof, side="right") - 1
        return pd.Series(self._weights[i], dtype=float) if i >= 0 else pd.Series(dtype=float)


def _cum(equity: pd.Series) -> float:
    return float(equity.iloc[-1] / equity.iloc[0] - 1)


def evaluate(strategy: str, ledger: Ledger, panel: dict, registry: dict, *,
             replacing: str | None = None, end=None) -> Gate3Report:
    cls = registry[strategy]
    records = ledger.recorded_targets(strategy)
    if not records:
        return Gate3Report(strategy, "not_yet", checks=[Check("has_forward_record", False, 0, ">0 days")])
    idx = panel["close"].index
    start = pd.Timestamp(next(iter(records)))
    stop = pd.Timestamp(end) if end is not None else pd.Timestamp(list(records)[-1])
    window = idx[(idx >= start) & (idx <= stop)]
    if len(window) < 2:
        return Gate3Report(strategy, "not_yet", str(start.date()), str(stop.date()),
                           checks=[Check("has_forward_record", False, len(window), ">=2 trading days")])
    start, stop = window[0], window[-1]
    months = (stop - start).days / 30.44
    checks: list[Check] = []

    # 1. recorded weights vs fresh weights, on every rebalance day of the window
    rec_days = pd.DatetimeIndex(pd.to_datetime(list(records)))
    rec_w = list(records.values())
    days = [window[0]] + [d for d in window[:-1] if is_rebalance_day(idx, idx.get_loc(d), cls.rebalance)]
    mismatches = []
    for d in days:
        i = rec_days.searchsorted(d, side="right") - 1
        got = pd.Series(rec_w[i] if i >= 0 else {}, dtype=float)
        exp = validate_weights(cls().target_weights(PriceView(panel, d)))
        u = got.index.union(exp.index)
        if (got.reindex(u).fillna(0) - exp.reindex(u).fillna(0)).abs().max() > T.TARGET_MATCH_TOL:
            mismatches.append(str(d.date()))
    share = 1 - len(mismatches) / len(days)
    checks.append(Check("target_match", share >= T.MIN_TARGET_MATCH_SHARE, round(share, 4),
                        T.MIN_TARGET_MATCH_SHARE, ", ".join(mismatches[:10])))

    # 2. forward (recorded) vs predicted (fresh backtest), same days, same costs
    fwd = run_backtest(RecordedBook(cls, records), panel, start, stop)
    bt = run_backtest(cls(), panel, start, stop)
    gap = abs(_cum(fwd.equity) - _cum(bt.equity))
    checks.append(Check("return_gap_vs_backtest", gap <= T.MAX_CUMULATIVE_RETURN_GAP, round(gap, 4),
                        T.MAX_CUMULATIVE_RETURN_GAP,
                        f"forward {_cum(fwd.equity):+.2%} vs backtest {_cum(bt.equity):+.2%}"))

    # 3-5. performance over the same days
    cagr = fwd.metrics["cagr"]
    bh = run_backtest(registry[T.BENCHMARK](), panel, start, stop).metrics["cagr"]
    checks.append(Check("beats_buy_and_hold", cagr > bh, round(cagr, 4), round(bh, 4)))
    checks.append(Check("beats_bank_rate", cagr > T.BANK_RATE, round(cagr, 4), T.BANK_RATE))
    if replacing:
        live_records = ledger.recorded_targets(replacing)
        live_cagr = (run_backtest(RecordedBook(registry[replacing], live_records), panel, start, stop)
                     .metrics["cagr"] if live_records else float("nan"))
        checks.append(Check("beats_live_strategy", bool(cagr > live_cagr), round(cagr, 4), round(live_cagr, 4),
                            replacing))

    need = T.MIN_MONTHS_REPLACE if replacing else T.MIN_MONTHS_FIRST_GO_LIVE
    checks.append(Check("long_enough", months >= need, round(months, 1), need, "months of paper record"))

    by = {c.name: c for c in checks}
    if not (by["target_match"].passed and by["return_gap_vs_backtest"].passed):
        verdict = "fail"
    elif not by["long_enough"].passed:
        verdict = "not_yet"
    else:
        verdict = "pass" if all(c.passed for c in checks) else "fail"
    return Gate3Report(strategy, verdict, str(start.date()), str(stop.date()), round(months, 1), checks,
                       {"forward_cagr": cagr, "backtest_cagr": bt.metrics["cagr"], "buy_hold_cagr": bh,
                        "forward_max_drawdown": fwd.metrics["max_drawdown"]})


def format_report(r: Gate3Report) -> str:
    lines = [f"GATE 3: {r.strategy}  paper record {r.start} to {r.end} ({r.months} months)",
             f"VERDICT: {r.verdict.upper()}", ""]
    for c in r.checks:
        lines.append(f"  [{'pass' if c.passed else 'FAIL'}] {c.name}: {c.value} (limit {c.threshold})"
                     + (f"  {c.detail}" if c.detail else ""))
    return "\n".join(lines)


def main(argv=None) -> None:
    from live.engine.data import YFinanceProvider

    ap = argparse.ArgumentParser(description="Gate 3: judge a strategy's paper record")
    ap.add_argument("strategy")
    ap.add_argument("--replacing", help="the live strategy it would replace")
    ap.add_argument("--fake", action="store_true", help="use the laptop's simulated ledger")
    args = ap.parse_args(argv)
    ledger = Ledger(config.FAKE_LEDGER_PATH if args.fake else config.LEDGER_PATH)
    records = ledger.recorded_targets(args.strategy)
    if not records:
        print(f"no paper record for {args.strategy} yet")
        return
    panel = YFinanceProvider().panel(pd.Timestamp(list(records)[-1]))
    registry = config.shadow_registry()
    print(format_report(evaluate(args.strategy, ledger, panel, registry, replacing=args.replacing)))


if __name__ == "__main__":
    main()
