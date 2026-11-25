"""
Data quality checks: missing days, splits, dividends, stale prices, bad bars.

Runs on the visible data only (research + validation); holdout rows are never
loaded here.

Usage (from the repo root):
    python -m research.data.checks
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from research.data.loader import RAW_DIR, load_panel
from research.data.splits import LAST_VISIBLE_DATE
from shared.universe import ALL_SYMBOLS, REFERENCE, SURVIVORSHIP_NOTE

JUMP = 0.25            # flag close-to-close moves larger than 25%
STALE_RUN = 3          # flag runs of >= 3 identical closes


def _actions(symbol: str) -> pd.DataFrame:
    p = RAW_DIR / "actions" / f"{symbol}.csv"
    if not p.exists():
        return pd.DataFrame(columns=["Dividends", "Stock Splits"])
    a = pd.read_csv(p, index_col=0, parse_dates=True)
    return a[a.index <= LAST_VISIBLE_DATE]


def _longest_run(s: pd.Series) -> tuple[int, pd.Timestamp | None]:
    s = s.dropna()
    if s.empty:
        return 0, None
    same = s.eq(s.shift())
    groups = (~same).cumsum()
    runs = same.groupby(groups).sum() + 1
    g = runs.idxmax()
    return int(runs.max()), s.index[groups == g][0]


def check_symbol(sym: str, panel: dict[str, pd.DataFrame]) -> dict:
    o, h, l, c, v = (panel[f][sym] for f in ("open", "high", "low", "close", "volume"))
    first, last = c.first_valid_index(), c.last_valid_index()
    active = c.loc[first:last]
    ret = c.pct_change(fill_method=None)
    actions = _actions(sym)
    splits = actions[actions.get("Stock Splits", 0) > 0] if len(actions) else actions
    divs = actions[actions.get("Dividends", 0) > 0] if len(actions) else actions

    jumps = ret[ret.abs() > JUMP]
    # A jump on a split date means the adjustment is missing.
    split_jumps = [d for d in jumps.index if d in set(splits.index)]
    bad_bars = int(((h < l) | (c > h * 1.0001) | (c < l * 0.9999) | (o > h * 1.0001) | (o < l * 0.9999)).sum())
    run, run_start = _longest_run(c)
    is_ref = sym in REFERENCE

    return {
        "symbol": sym,
        "first": first.date() if first is not None else None,
        "last": last.date() if last is not None else None,
        "missing_days": int(active.isna().sum()),
        "nonpositive": int((active <= 0).sum()),
        "bad_bars": bad_bars,
        "zero_volume": 0 if is_ref else int((v.loc[first:last] == 0).sum()),
        "longest_flat_run": run,
        "flat_run_start": run_start.date() if run_start is not None and run >= STALE_RUN else None,
        "jumps_gt_25pct": len(jumps),
        "jump_dates": ", ".join(str(d.date()) for d in jumps.index[:5]),
        "splits": len(splits),
        "unadjusted_split_jumps": len(split_jumps),
        "dividends": len(divs),
    }


def run_checks() -> pd.DataFrame:
    panel = load_panel(ALL_SYMBOLS)
    return pd.DataFrame([check_symbol(s, panel) for s in ALL_SYMBOLS]).set_index("symbol")


def problems(report: pd.DataFrame) -> list[str]:
    out = []
    for sym, r in report.iterrows():
        if r.missing_days:
            out.append(f"{sym}: {r.missing_days} missing trading days inside its history")
        if r.nonpositive or r.bad_bars:
            out.append(f"{sym}: {r.nonpositive} non-positive prices, {r.bad_bars} bars with high/low inconsistencies")
        if r.unadjusted_split_jumps:
            out.append(f"{sym}: {r.unadjusted_split_jumps} price jumps on split dates (adjustment missing)")
        if r.longest_flat_run >= STALE_RUN:
            out.append(f"{sym}: close unchanged for {r.longest_flat_run} days from {r.flat_run_start} (stale?)")
        if r.zero_volume:
            out.append(f"{sym}: {r.zero_volume} zero-volume days")
    return out


if __name__ == "__main__":
    pd.set_option("display.width", 200)
    rep = run_checks()
    print(rep.drop(columns=["jump_dates"]).to_string())
    print("\nLarge moves (>25%):")
    for sym, r in rep[rep.jumps_gt_25pct > 0].iterrows():
        print(f"  {sym}: {r.jump_dates}")
    print("\nProblems:")
    for p in problems(rep) or ["none"]:
        print("  -", p)
    print("\n" + SURVIVORSHIP_NOTE)
